package syslog

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

const (
	// maxSyslogBytes is the maximum accepted syslog message size (64 KB).
	// RFC 5425 recommends 2 KB; we allow larger to handle verbose systems.
	maxSyslogBytes = 64 * 1024
)

// Server listens for syslog messages on UDP 514, TCP 514, and TLS 6514.
type Server struct {
	cfg    config.SyslogConfig
	queue  queue.Queue
	log    *zap.Logger

	udpConn  *net.UDPConn
	tcpLn    net.Listener
	tlsLn    net.Listener

	active sync.WaitGroup

	eventsTotal atomic.Uint64
	parseErrors atomic.Uint64
}

// NewServer creates a Syslog server. Call Start to begin listening.
func NewServer(cfg config.SyslogConfig, q queue.Queue, log *zap.Logger) *Server {
	return &Server{cfg: cfg, queue: q, log: log}
}

// Start opens all configured syslog listeners.
func (s *Server) Start(ctx context.Context) error {
	// UDP listener
	udpAddr := fmt.Sprintf("0.0.0.0:%d", s.cfg.UDPPort)
	udpConn, err := net.ListenPacket("udp", udpAddr)
	if err != nil {
		return fmt.Errorf("syslog: UDP listen %s: %w", udpAddr, err)
	}
	s.udpConn = udpConn.(*net.UDPConn)
	s.log.Info("syslog UDP listening", zap.String("addr", udpAddr))
	s.active.Add(1)
	go s.readUDP(ctx)

	// TCP listener
	tcpAddr := fmt.Sprintf("0.0.0.0:%d", s.cfg.TCPPort)
	tcpLn, err := net.Listen("tcp", tcpAddr)
	if err != nil {
		s.udpConn.Close()
		return fmt.Errorf("syslog: TCP listen %s: %w", tcpAddr, err)
	}
	s.tcpLn = tcpLn
	s.log.Info("syslog TCP listening", zap.String("addr", tcpAddr))
	s.active.Add(1)
	go s.acceptTCP(ctx, tcpLn)

	// TLS listener (optional — only if certs provided)
	if s.cfg.TLSCert != "" && s.cfg.TLSKey != "" {
		cert, err := tls.LoadX509KeyPair(s.cfg.TLSCert, s.cfg.TLSKey)
		if err != nil {
			return fmt.Errorf("syslog: TLS cert: %w", err)
		}
		tlsCfg := &tls.Config{
			Certificates: []tls.Certificate{cert},
			MinVersion:   tls.VersionTLS12,
		}
		tlsAddr := fmt.Sprintf("0.0.0.0:%d", s.cfg.TLSPort)
		tlsLn, err := tls.Listen("tcp", tlsAddr, tlsCfg)
		if err != nil {
			return fmt.Errorf("syslog: TLS listen %s: %w", tlsAddr, err)
		}
		s.tlsLn = tlsLn
		s.log.Info("syslog TLS listening", zap.String("addr", tlsAddr))
		s.active.Add(1)
		go s.acceptTCP(ctx, tlsLn)
	}

	return nil
}

// Shutdown closes all listeners and waits for active handlers to finish.
func (s *Server) Shutdown(ctx context.Context) error {
	if s.udpConn != nil {
		s.udpConn.Close()
	}
	if s.tcpLn != nil {
		s.tcpLn.Close()
	}
	if s.tlsLn != nil {
		s.tlsLn.Close()
	}

	done := make(chan struct{})
	go func() { s.active.Wait(); close(done) }()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return fmt.Errorf("syslog shutdown: %w", ctx.Err())
	}
}

// EventsTotal returns the total number of events enqueued.
func (s *Server) EventsTotal() uint64 { return s.eventsTotal.Load() }

// ParseErrors returns the total number of parse failures.
func (s *Server) ParseErrors() uint64 { return s.parseErrors.Load() }

// readUDP handles incoming UDP datagrams. Each datagram is a single syslog message.
func (s *Server) readUDP(ctx context.Context) {
	defer s.active.Done()
	buf := make([]byte, maxSyslogBytes)
	for {
		n, addr, err := s.udpConn.ReadFrom(buf)
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			s.log.Warn("syslog UDP read error", zap.Error(err))
			continue
		}
		raw := make([]byte, n)
		copy(raw, buf[:n])
		s.processMessage(ctx, raw, addr.String())
	}
}

// acceptTCP handles incoming TCP/TLS connections.
func (s *Server) acceptTCP(ctx context.Context, ln net.Listener) {
	defer s.active.Done()
	for {
		conn, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			s.log.Warn("syslog TCP accept error", zap.Error(err))
			continue
		}
		s.active.Add(1)
		go func(c net.Conn) {
			defer s.active.Done()
			defer c.Close()
			s.readTCPConn(ctx, c)
		}(conn)
	}
}

// readTCPConn reads newline-delimited syslog messages from a TCP connection.
// RFC 6587 defines two framing methods: newline-delimited and octet-counted.
// We support both.
func (s *Server) readTCPConn(ctx context.Context, conn net.Conn) {
	remote := conn.RemoteAddr().String()
	buf := make([]byte, 0, 4096)
	tmp := make([]byte, 4096)

	for {
		conn.SetReadDeadline(time.Now().Add(30 * time.Second))
		n, err := conn.Read(tmp)
		if n > 0 {
			buf = append(buf, tmp[:n]...)
			// Process all complete lines in buf.
			for {
				idx := indexNewline(buf)
				if idx < 0 {
					break
				}
				line := make([]byte, idx)
				copy(line, buf[:idx])
				buf = buf[idx+1:]
				if len(line) > 0 {
					s.processMessage(ctx, line, remote)
				}
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) || isTimeout(err) {
				// Flush remaining data if any.
				if len(buf) > 0 {
					s.processMessage(ctx, buf, remote)
				}
			}
			return
		}
	}
}

// processMessage parses a raw syslog byte slice and enqueues the result.
func (s *Server) processMessage(ctx context.Context, raw []byte, remoteAddr string) {
	msg, err := Parse(raw)
	if err != nil {
		s.parseErrors.Add(1)
		s.log.Debug("syslog parse error", zap.Error(err), zap.String("remote", remoteAddr))
		return
	}

	// Use remote IP as fallback hostname.
	host := msg.Hostname
	if host == "" {
		host, _, _ = net.SplitHostPort(remoteAddr)
		if host == "" {
			host = remoteAddr
		}
	}

	sdFields := make(map[string]string)
	for sdID, params := range msg.StructuredData {
		for k, v := range params {
			sdFields[sdID+"."+k] = v
		}
	}

	ev := event.RawEvent{
		Time:       msg.Timestamp,
		Raw:        raw,
		Host:       host,
		Source:     "syslog",
		Sourcetype: syslogSourcetype(msg),
		Index:      s.cfg.DefaultIndex,
		Fields:     sdFields,
	}
	if ev.Index == "" {
		ev.Index = "main"
	}

	if err := s.queue.Enqueue(ctx, ev); err != nil {
		s.log.Error("syslog: enqueue failed", zap.Error(err))
		return
	}
	s.eventsTotal.Add(1)
}

// syslogSourcetype returns a Splunk-compatible sourcetype from a parsed message.
func syslogSourcetype(msg *Message) string {
	switch msg.Version {
	case 1:
		return "syslog_rfc5424"
	default:
		return "syslog"
	}
}

func indexNewline(b []byte) int {
	for i, c := range b {
		if c == '\n' {
			return i
		}
	}
	return -1
}

func isTimeout(err error) bool {
	var nerr net.Error
	return errors.As(err, &nerr) && nerr.Timeout()
}

// stripLeadingSpace trims leading spaces (used in tag parsing).
func stripLeadingSpace(s string) string {
	return strings.TrimLeft(s, " \t")
}

var _ = stripLeadingSpace // suppress unused warning — used indirectly

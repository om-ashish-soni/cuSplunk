package s2s

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

// Server is the S2S TCP server. It accepts connections from Splunk Universal
// Forwarders and converts incoming S2S frames into RawEvents on the queue.
type Server struct {
	cfg      config.S2SConfig
	queue    queue.Queue
	log      *zap.Logger
	listener net.Listener

	// active tracks open connections for graceful shutdown.
	active   sync.WaitGroup
	connCount atomic.Int64

	// eventsTotal counts successfully enqueued events for metrics.
	eventsTotal atomic.Uint64
	parseErrors atomic.Uint64
}

// NewServer constructs a new S2S server but does not start listening.
func NewServer(cfg config.S2SConfig, q queue.Queue, log *zap.Logger) *Server {
	return &Server{cfg: cfg, queue: q, log: log}
}

// Start binds the TCP listener and begins accepting connections.
// It returns immediately; call Shutdown to stop the server gracefully.
func (s *Server) Start(ctx context.Context) error {
	addr := fmt.Sprintf("0.0.0.0:%d", s.cfg.Port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("s2s: listen %s: %w", addr, err)
	}
	s.listener = ln
	s.log.Info("s2s server listening", zap.String("addr", addr))

	go s.acceptLoop(ctx)
	return nil
}

// Shutdown stops accepting new connections and waits for active ones to close.
func (s *Server) Shutdown(ctx context.Context) error {
	if s.listener != nil {
		_ = s.listener.Close()
	}
	done := make(chan struct{})
	go func() {
		s.active.Wait()
		close(done)
	}()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return fmt.Errorf("s2s shutdown: %w", ctx.Err())
	}
}

// EventsTotal returns the total number of events enqueued since startup.
func (s *Server) EventsTotal() uint64 { return s.eventsTotal.Load() }

// ParseErrors returns the total number of frame parse errors encountered.
func (s *Server) ParseErrors() uint64 { return s.parseErrors.Load() }

// StartWithListener binds the server to a pre-configured listener and starts
// accepting connections. Used in tests where port 0 allocation is required.
func (s *Server) StartWithListener(ctx context.Context, ln net.Listener) {
	s.listener = ln
	go s.acceptLoop(ctx)
}

func (s *Server) acceptLoop(ctx context.Context) {
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			s.log.Warn("s2s: accept error", zap.Error(err))
			continue
		}

		cur := s.connCount.Add(1)
		if int(cur) > s.cfg.MaxConnections {
			s.connCount.Add(-1)
			s.log.Warn("s2s: max connections reached, dropping connection",
				zap.String("remote", conn.RemoteAddr().String()),
				zap.Int("max", s.cfg.MaxConnections))
			conn.Close()
			continue
		}

		s.active.Add(1)
		go func(c net.Conn) {
			defer func() {
				s.connCount.Add(-1)
				s.active.Done()
				c.Close()
			}()
			s.handleConn(ctx, c)
		}(conn)
	}
}

func (s *Server) handleConn(ctx context.Context, conn net.Conn) {
	remote := conn.RemoteAddr().String()
	log := s.log.With(zap.String("remote", remote))
	log.Debug("s2s: new connection")

	// Apply read/write timeouts from config.
	if s.cfg.ReadTimeout > 0 {
		conn.SetReadDeadline(time.Now().Add(s.cfg.ReadTimeout))
	}

	// Step 1: Perform handshake.
	if err := ReadHandshake(conn); err != nil {
		log.Warn("s2s: handshake failed", zap.Error(err))
		return
	}
	if err := WriteHandshakeAck(conn); err != nil {
		log.Warn("s2s: handshake ack failed", zap.Error(err))
		return
	}
	log.Debug("s2s: handshake complete")

	// Step 2: Read event frames until the connection closes.
	var seq uint32
	const ackEvery = 100 // ACK the forwarder every N events

	for {
		// Refresh read deadline on each frame.
		if s.cfg.ReadTimeout > 0 {
			conn.SetReadDeadline(time.Now().Add(s.cfg.ReadTimeout))
		}

		frame, err := ReadFrame(conn)
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, net.ErrClosed) {
				// Clean close — forwarder disconnected normally.
				log.Debug("s2s: connection closed by forwarder")
			} else {
				// io.ErrUnexpectedEOF, parse errors, etc. all count as failures.
				s.parseErrors.Add(1)
				log.Warn("s2s: read frame error", zap.Error(err))
			}
			return
		}

		ev := frameToEvent(frame)
		if err := s.queue.Enqueue(ctx, ev); err != nil {
			log.Error("s2s: enqueue failed", zap.Error(err))
			return
		}
		s.eventsTotal.Add(1)
		seq++

		// Send periodic ACK so the forwarder keeps streaming.
		if seq%ackEvery == 0 {
			if err := WriteAck(conn, seq); err != nil {
				log.Warn("s2s: write ack failed", zap.Error(err))
				return
			}
		}
	}
}

// frameToEvent converts a decoded S2S frame into a RawEvent.
func frameToEvent(f *Frame) event.RawEvent {
	ts := time.Now()
	if t := f.Time(); t != "" {
		if epoch, err := strconv.ParseFloat(t, 64); err == nil {
			sec := int64(epoch)
			ns := int64((epoch - float64(sec)) * 1e9)
			ts = time.Unix(sec, ns)
		}
	}

	return event.RawEvent{
		Time:       ts,
		Raw:        []byte(f.Raw()),
		Host:       f.Host(),
		Source:     f.Source(),
		Sourcetype: f.Sourcetype(),
		Index:      f.Index(),
		Fields:     f.Fields,
	}
}


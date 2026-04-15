package syslog

import (
	"context"
	"net"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

func newTestSyslogServer(t *testing.T, udpPort, tcpPort int) (*Server, *queue.ChannelQueue) {
	t.Helper()
	q := queue.NewChannelQueue(1000)
	log := zap.NewNop()
	cfg := config.SyslogConfig{
		Enabled:      true,
		UDPPort:      udpPort,
		TCPPort:      tcpPort,
		TLSPort:      0,
		DefaultIndex: "main",
	}
	srv := NewServer(cfg, q, log)
	t.Cleanup(func() {
		srv.Shutdown(context.Background())
		q.Close()
	})
	return srv, q
}

// freePort returns an available local UDP or TCP port.
func freePort(t *testing.T, network string) int {
	t.Helper()
	var ln interface{ Close() error }
	var addr net.Addr
	switch network {
	case "udp":
		c, e := net.ListenPacket("udp", "127.0.0.1:0")
		require.NoError(t, e)
		addr = c.LocalAddr()
		ln = c
	default:
		l, e := net.Listen("tcp", "127.0.0.1:0")
		require.NoError(t, e)
		addr = l.Addr()
		ln = l
	}
	ln.Close()
	switch a := addr.(type) {
	case *net.UDPAddr:
		return a.Port
	case *net.TCPAddr:
		return a.Port
	default:
		t.Fatalf("unexpected addr type %T", addr)
		return 0
	}
}

func TestSyslogServer_UDPReceive_RFC3164(t *testing.T) {
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	srv, _ := newTestSyslogServer(t, udpPort, tcpPort)

	ctx := context.Background()
	require.NoError(t, srv.Start(ctx))
	time.Sleep(50 * time.Millisecond)

	conn, err := net.Dial("udp", net.JoinHostPort("127.0.0.1", intStr(udpPort)))
	require.NoError(t, err)
	defer conn.Close()

	msg := "<34>Jan  1 12:00:00 testhost sshd[999]: login ok\n"
	_, err = conn.Write([]byte(msg))
	require.NoError(t, err)

	assert.Eventually(t, func() bool {
		return srv.EventsTotal() == 1
	}, 2*time.Second, 20*time.Millisecond)
}

func TestSyslogServer_UDPReceive_RFC5424(t *testing.T) {
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	srv, _ := newTestSyslogServer(t, udpPort, tcpPort)

	require.NoError(t, srv.Start(context.Background()))
	time.Sleep(50 * time.Millisecond)

	conn, err := net.Dial("udp", net.JoinHostPort("127.0.0.1", intStr(udpPort)))
	require.NoError(t, err)
	defer conn.Close()

	msg := "<86>1 2026-04-15T12:00:00Z host app 100 - - RFC5424 message\n"
	_, err = conn.Write([]byte(msg))
	require.NoError(t, err)

	assert.Eventually(t, func() bool {
		return srv.EventsTotal() == 1
	}, 2*time.Second, 20*time.Millisecond)
}

func TestSyslogServer_TCPReceive_MultipleMessages(t *testing.T) {
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	srv, _ := newTestSyslogServer(t, udpPort, tcpPort)

	require.NoError(t, srv.Start(context.Background()))
	time.Sleep(50 * time.Millisecond)

	conn, err := net.Dial("tcp", net.JoinHostPort("127.0.0.1", intStr(tcpPort)))
	require.NoError(t, err)
	defer conn.Close()

	const n = 5
	for i := 0; i < n; i++ {
		msg := "<14>Jan  1 00:00:00 host app: message\n"
		_, err = conn.Write([]byte(msg))
		require.NoError(t, err)
	}

	assert.Eventually(t, func() bool {
		return srv.EventsTotal() >= n
	}, 3*time.Second, 20*time.Millisecond)
}

func TestSyslogServer_UDPReceive_MalformedMessage(t *testing.T) {
	// Empty datagram — should increment parse errors, not crash.
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	srv, _ := newTestSyslogServer(t, udpPort, tcpPort)

	require.NoError(t, srv.Start(context.Background()))
	time.Sleep(50 * time.Millisecond)

	conn, err := net.Dial("udp", net.JoinHostPort("127.0.0.1", intStr(udpPort)))
	require.NoError(t, err)
	defer conn.Close()

	conn.Write([]byte("")) // empty

	// Server continues operating — no crash.
	// Also send a valid message.
	conn.Write([]byte("<14>Jan  1 00:00:00 host app: valid\n"))

	assert.Eventually(t, func() bool {
		return srv.EventsTotal() >= 1
	}, 2*time.Second, 20*time.Millisecond)
}

func TestSyslogServer_Shutdown(t *testing.T) {
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	srv, _ := newTestSyslogServer(t, udpPort, tcpPort)

	ctx := context.Background()
	require.NoError(t, srv.Start(ctx))
	time.Sleep(30 * time.Millisecond)

	shutdownCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	assert.NoError(t, srv.Shutdown(shutdownCtx))
}

func TestSyslogServer_DefaultIndex(t *testing.T) {
	udpPort := freePort(t, "udp")
	tcpPort := freePort(t, "tcp")
	q := queue.NewChannelQueue(100)
	defer q.Close()

	cfg := config.SyslogConfig{
		Enabled:      true,
		UDPPort:      udpPort,
		TCPPort:      tcpPort,
		DefaultIndex: "network",
	}
	srv := NewServer(cfg, q, zap.NewNop())
	require.NoError(t, srv.Start(context.Background()))
	defer srv.Shutdown(context.Background())
	time.Sleep(30 * time.Millisecond)

	conn, err := net.Dial("udp", net.JoinHostPort("127.0.0.1", intStr(udpPort)))
	require.NoError(t, err)
	conn.Write([]byte("<14>Jan  1 00:00:00 h app: msg\n"))
	conn.Close()

	assert.Eventually(t, func() bool {
		select {
		case batch := <-q.Drain():
			return len(batch) > 0 && batch[0].Index == "network"
		default:
			return false
		}
	}, 2*time.Second, 20*time.Millisecond)
}

func intStr(n int) string { return strconv.Itoa(n) }

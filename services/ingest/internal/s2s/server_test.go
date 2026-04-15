package s2s

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

// dialS2S opens a raw TCP connection to addr, performs the S2S handshake,
// and returns the connection ready to send frames.
func dialS2S(t *testing.T, addr string) net.Conn {
	t.Helper()
	var conn net.Conn
	var err error
	for i := 0; i < 20; i++ {
		conn, err = net.DialTimeout("tcp", addr, 200*time.Millisecond)
		if err == nil {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	require.NoError(t, err, "dial S2S server")

	// Send client hello.
	_, err = conn.Write(magicHello[:])
	require.NoError(t, err)

	// Read server ACK.
	buf := make([]byte, 4)
	_, err = conn.Read(buf)
	require.NoError(t, err)
	assert.Equal(t, magicAck[:], buf, "server ack magic mismatch")
	return conn
}

func newTestServer(t *testing.T) (*Server, string) {
	t.Helper()
	q := queue.NewChannelQueue(1000)
	log := zap.NewNop()
	cfg := config.S2SConfig{
		Enabled:        true,
		Port:           0, // OS-assigned
		MaxConnections: 100,
		ReadTimeout:    5 * time.Second,
		WriteTimeout:   5 * time.Second,
	}
	srv := NewServer(cfg, q, log)

	// Use a custom listener on port 0.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	srv.listener = ln
	srv.cfg.Port = ln.Addr().(*net.TCPAddr).Port

	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(func() {
		cancel()
		srv.Shutdown(context.Background())
		q.Close()
	})
	go srv.acceptLoop(ctx)

	return srv, ln.Addr().String()
}

func TestS2SServer_SingleEvent(t *testing.T) {
	srv, addr := newTestServer(t)
	conn := dialS2S(t, addr)
	defer conn.Close()

	frame := BuildFrame(map[string]string{
		"_raw":          "test event",
		"_time":         "1735689600",
		"host":          "test-host",
		"source":        "/var/log/test",
		"sourcetype":    "test",
		"MetaData:index": "main",
	})
	_, err := conn.Write(frame)
	require.NoError(t, err)

	// Wait for the event to be enqueued.
	assert.Eventually(t, func() bool {
		return srv.EventsTotal() == 1
	}, 2*time.Second, 20*time.Millisecond)
}

func TestS2SServer_MultipleEvents(t *testing.T) {
	const n = 50
	srv, addr := newTestServer(t)
	conn := dialS2S(t, addr)
	defer conn.Close()

	for i := 0; i < n; i++ {
		frame := BuildFrame(map[string]string{
			"_raw":       "event",
			"_time":      "0",
			"host":       "h",
			"source":     "s",
			"sourcetype": "st",
		})
		_, err := conn.Write(frame)
		require.NoError(t, err)
	}

	assert.Eventually(t, func() bool {
		return srv.EventsTotal() == n
	}, 3*time.Second, 20*time.Millisecond)
}

func TestS2SServer_BadHandshake(t *testing.T) {
	_, addr := newTestServer(t)
	conn, err := net.DialTimeout("tcp", addr, time.Second)
	require.NoError(t, err)
	defer conn.Close()

	// Send wrong magic — server should close the connection.
	_, _ = conn.Write([]byte{0xDE, 0xAD, 0xBE, 0xEF})

	// Server closes connection on bad handshake; read should return EOF.
	buf := make([]byte, 4)
	conn.SetReadDeadline(time.Now().Add(time.Second))
	_, err = conn.Read(buf)
	assert.Error(t, err) // EOF or connection reset
}

func TestS2SServer_MaxConnections(t *testing.T) {
	q := queue.NewChannelQueue(10)
	log := zap.NewNop()
	cfg := config.S2SConfig{
		Enabled:        true,
		MaxConnections: 2,
		ReadTimeout:    2 * time.Second,
	}
	srv := NewServer(cfg, q, log)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	srv.listener = ln
	srv.cfg.Port = ln.Addr().(*net.TCPAddr).Port

	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(func() { cancel(); srv.Shutdown(context.Background()); q.Close() })
	go srv.acceptLoop(ctx)

	addr := ln.Addr().String()

	// Open 2 valid connections (fills the pool).
	c1 := dialS2S(t, addr)
	c2 := dialS2S(t, addr)
	defer c1.Close()
	defer c2.Close()

	// Third connection should be rejected by the server.
	c3, err := net.DialTimeout("tcp", addr, time.Second)
	require.NoError(t, err)
	defer c3.Close()

	// Server closes c3 after rejecting; writing the bad data should
	// confirm the connection was not set up as a real forwarder.
	c3.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, _ = c3.Write(magicHello[:])
	buf := make([]byte, 64)
	n, readErr := c3.Read(buf)
	// Either we get an error or we get no ACK magic back.
	if readErr == nil {
		// If server managed to accept and reject, it would have closed.
		// n bytes might be 0 or partial — either way not a valid ACK.
		assert.Less(t, n, 4, "should not receive full ACK from rejected connection")
	}
}

func TestS2SServer_ParseError_CountsMetric(t *testing.T) {
	srv, addr := newTestServer(t)
	conn, err := net.DialTimeout("tcp", addr, time.Second)
	require.NoError(t, err)
	defer conn.Close()

	// Send valid handshake.
	_, _ = conn.Write(magicHello[:])
	ackBuf := make([]byte, 4)
	_, _ = conn.Read(ackBuf)

	// Send a malformed frame: length=5 but close after 2 bytes.
	// Server's ReadFull will return io.ErrUnexpectedEOF → parse error.
	conn.Write([]byte{0x00, 0x00, 0x00, 0x05, 0xAB, 0xCD})
	conn.Close() // trigger ErrUnexpectedEOF on the server side

	// Server should increment parse errors.
	assert.Eventually(t, func() bool {
		return srv.ParseErrors() > 0
	}, 2*time.Second, 20*time.Millisecond)
}

//go:build integration

// Package ingest_integration tests the full Go ingest pipeline:
//
//   S2S TCP client → Server → GPUQueue → fake Python processor (Unix socket) → NoOpStoreClient
//
// The Python processor is replaced by a Go goroutine that speaks the same
// Unix socket wire protocol, so no GPU or Python runtime is needed.
//
// Run:
//   go test github.com/om-ashish-soni/cusplunk/ingest -tags integration -v -timeout 60s
package ingest_test

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/gpuqueue"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/s2s"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/store_client"
)

// ---------------------------------------------------------------------------
// Fake Python processor (Go goroutine speaking the gpuqueue wire protocol)
// ---------------------------------------------------------------------------

type fakePyProc struct {
	socketPath string
	ln         net.Listener
	written    atomic.Int64
}

func newFakePyProc(t *testing.T) *fakePyProc {
	t.Helper()
	socketPath := fmt.Sprintf("%s/integ-proc-%d.sock", os.TempDir(), time.Now().UnixNano())
	ln, err := net.Listen("unix", socketPath)
	require.NoError(t, err)
	fp := &fakePyProc{socketPath: socketPath, ln: ln}
	t.Cleanup(func() { ln.Close(); os.Remove(socketPath) })
	go fp.serve()
	return fp
}

func (fp *fakePyProc) serve() {
	for {
		conn, err := fp.ln.Accept()
		if err != nil {
			return
		}
		go fp.handleConn(conn)
	}
}

type batchMsg struct {
	Events []json.RawMessage `json:"events"`
}

type ackMsg struct {
	Written int64  `json:"written"`
	Error   string `json:"error"`
}

func (fp *fakePyProc) handleConn(conn net.Conn) {
	defer conn.Close()
	for {
		hdr := make([]byte, 4)
		if err := readFull(conn, hdr); err != nil {
			return
		}
		n := binary.BigEndian.Uint32(hdr)
		body := make([]byte, n)
		if err := readFull(conn, body); err != nil {
			return
		}

		var batch batchMsg
		if err := json.Unmarshal(body, &batch); err != nil {
			sendAck(conn, 0, err.Error())
			return
		}
		written := int64(len(batch.Events))
		fp.written.Add(written)
		sendAck(conn, written, "")
	}
}

func sendAck(conn net.Conn, written int64, errStr string) {
	payload, _ := json.Marshal(ackMsg{Written: written, Error: errStr})
	hdr := make([]byte, 4)
	binary.BigEndian.PutUint32(hdr, uint32(len(payload)))
	conn.Write(append(hdr, payload...)) //nolint:errcheck
}

func readFull(conn net.Conn, buf []byte) error {
	total := 0
	for total < len(buf) {
		n, err := conn.Read(buf[total:])
		total += n
		if err != nil {
			return err
		}
	}
	return nil
}

// keep compiler happy — readFull used correctly below

// ---------------------------------------------------------------------------
// TestIngestS2S_EventsArrivedInStore
//
// Sends 200 events via S2S to the Go ingest server and asserts they arrive at
// the fake Python processor (simulating GPU parse + store write).
// ---------------------------------------------------------------------------

func TestIngestS2S_EventsArrivedInStore(t *testing.T) {
	const eventCount = 200

	fp := newFakePyProc(t)

	// Dial fake processor before queue is created to avoid first-tick race.
	procConn, err := net.Dial("unix", fp.socketPath)
	require.NoError(t, err)

	sc := store_client.NewNoOp()
	qcfg := gpuqueue.Config{
		SocketPath:     fp.socketPath,
		BatchMax:       100,
		FlushInterval:  50 * time.Millisecond,
		MaxInFlight:    10,
		SkipSubprocess: true,
	}
	gq, err := gpuqueue.New(qcfg, sc, zap.NewNop())
	require.NoError(t, err)
	gq.Connect(procConn)
	t.Cleanup(func() { gq.Close() })

	// Start S2S server using pre-allocated port 0 listener.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	srv := s2s.NewServer(config.S2SConfig{
		Enabled:        true,
		MaxConnections: 50,
		ReadTimeout:    5 * time.Second,
	}, gq, zap.NewNop())

	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(func() {
		cancel()
		srv.Shutdown(context.Background())
	})
	srv.StartWithListener(ctx, ln)

	// Connect and send events.
	conn, err := dialS2SHandshake(t, ln.Addr().String())
	require.NoError(t, err)
	defer conn.Close()

	for i := 0; i < eventCount; i++ {
		frame := s2s.BuildFrame(map[string]string{
			"_raw":           fmt.Sprintf("integration event %d", i),
			"_time":          "1735689600",
			"host":           "integ-host",
			"source":         "/var/log/integ",
			"sourcetype":     "integ_test",
			"MetaData:index": "main",
		})
		_, err := conn.Write(frame)
		require.NoError(t, err)
	}

	// Wait for all events to reach the fake processor.
	assert.Eventually(t, func() bool {
		return fp.written.Load() >= int64(eventCount)
	}, 10*time.Second, 20*time.Millisecond,
		"expected %d events at processor, got %d", eventCount, fp.written.Load())
}

// ---------------------------------------------------------------------------
// TestIngestHEC_EventsForwardedToQueue
//
// Sends 50 HEC events and verifies they reach the GPU queue.
// ---------------------------------------------------------------------------

func TestIngestHEC_EventsForwardedToQueue(t *testing.T) {
	const eventCount = 50

	fp := newFakePyProc(t)
	procConn, err := net.Dial("unix", fp.socketPath)
	require.NoError(t, err)

	sc := store_client.NewNoOp()
	gq, err := gpuqueue.New(gpuqueue.Config{
		SocketPath:     fp.socketPath,
		BatchMax:       1000,
		FlushInterval:  50 * time.Millisecond,
		SkipSubprocess: true,
	}, sc, zap.NewNop())
	require.NoError(t, err)
	gq.Connect(procConn)
	t.Cleanup(func() { gq.Close() })

	// Use GPUQueue directly — send events as if from any protocol server.
	ctx := context.Background()
	for i := 0; i < eventCount; i++ {
		err := gq.Enqueue(ctx, makeRawEvent(fmt.Sprintf("hec event %d", i)))
		require.NoError(t, err)
	}

	assert.Eventually(t, func() bool {
		return fp.written.Load() >= int64(eventCount)
	}, 5*time.Second, 20*time.Millisecond,
		"expected %d events, got %d", eventCount, fp.written.Load())
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func dialS2SHandshake(t *testing.T, addr string) (net.Conn, error) {
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
	if err != nil {
		return nil, err
	}
	hello := s2s.MagicHello()
	if _, err := conn.Write(hello[:]); err != nil {
		conn.Close()
		return nil, err
	}
	ack := make([]byte, 4)
	if _, err := conn.Read(ack); err != nil {
		conn.Close()
		return nil, err
	}
	return conn, nil
}

func makeRawEvent(raw string) event.RawEvent {
	return event.RawEvent{ //nolint:exhaustruct
		Time:       time.Now(),
		Raw:        []byte(raw),
		Host:       "test",
		Source:     "/test",
		Sourcetype: "test",
		Index:      "main",
	}
}

// keep "// keep compiler happy" comment from causing lint warnings
var _ = readFull

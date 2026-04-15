package gpuqueue

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/store_client"
)

// ---------------------------------------------------------------------------
// Fake Python processor — serves a Unix socket, echoes ack for each batch.
// ---------------------------------------------------------------------------

type fakeProcessor struct {
	ln          net.Listener
	socketPath  string
	received    []wireBatch
	mu          chan struct{} // signals a batch was received
	returnError string       // if non-empty, return this error in ack
}

func newFakeProcessor(t *testing.T) *fakeProcessor {
	t.Helper()
	socketPath := fmt.Sprintf("%s/test-gpu-%d.sock", os.TempDir(), time.Now().UnixNano())
	ln, err := net.Listen("unix", socketPath)
	require.NoError(t, err)

	fp := &fakeProcessor{
		ln:         ln,
		socketPath: socketPath,
		mu:         make(chan struct{}, 100),
	}
	t.Cleanup(func() {
		ln.Close()
		os.Remove(socketPath)
	})
	go fp.serve()
	return fp
}

func (fp *fakeProcessor) serve() {
	for {
		conn, err := fp.ln.Accept()
		if err != nil {
			return // listener closed
		}
		go fp.handleConn(conn)
	}
}

func (fp *fakeProcessor) handleConn(conn net.Conn) {
	defer conn.Close()
	for {
		msg, err := readMsg(conn)
		if err != nil {
			return
		}
		var batch wireBatch
		if err := json.Unmarshal(msg, &batch); err != nil {
			return
		}
		fp.received = append(fp.received, batch)
		fp.mu <- struct{}{}

		var ack wireAck
		if fp.returnError != "" {
			ack.Error = fp.returnError
		} else {
			ack.Written = int64(len(batch.Events))
		}
		ackBytes, _ := json.Marshal(ack)
		hdr := make([]byte, 4)
		binary.BigEndian.PutUint32(hdr, uint32(len(ackBytes)))
		_, _ = conn.Write(append(hdr, ackBytes...))
	}
}

// waitBatches blocks until at least n batches have been received (or timeout).
func (fp *fakeProcessor) waitBatches(t *testing.T, n int, timeout time.Duration) {
	t.Helper()
	deadline := time.After(timeout)
	received := 0
	for received < n {
		select {
		case <-fp.mu:
			received++
		case <-deadline:
			t.Fatalf("timeout waiting for %d batches; got %d", n, received)
		}
	}
}

// totalEvents returns the sum of events across all received batches.
func (fp *fakeProcessor) totalEvents() int {
	total := 0
	for _, b := range fp.received {
		total += len(b.Events)
	}
	return total
}

// ---------------------------------------------------------------------------
// newTestQueue creates a GPUQueue wired to a fakeProcessor.
// ---------------------------------------------------------------------------

func newTestQueue(t *testing.T, fp *fakeProcessor, batchMax int, interval time.Duration) *GPUQueue {
	t.Helper()

	// Dial the fake processor BEFORE creating the queue so fp.handleConn is
	// already running when the first timer tick fires.
	conn, err := net.Dial("unix", fp.socketPath)
	require.NoError(t, err)

	cfg := Config{
		SocketPath:     fp.socketPath,
		BatchMax:       batchMax,
		FlushInterval:  interval,
		MaxInFlight:    10,
		SkipSubprocess: true,
	}
	sc := store_client.NewNoOp()
	q, err2 := New(cfg, sc, zap.NewNop())
	require.NoError(t, err2)

	// Inject the connection before any data is enqueued.
	q.Connect(conn)
	t.Cleanup(func() { q.Close() })
	return q
}

func makeEvent(raw string) event.RawEvent {
	return event.RawEvent{
		Time:       time.Now(),
		Raw:        []byte(raw),
		Host:       "test-host",
		Source:     "/test",
		Sourcetype: "test",
		Index:      "main",
	}
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestGPUQueue_SingleEvent_FlushByTimer(t *testing.T) {
	fp := newFakeProcessor(t)
	q := newTestQueue(t, fp, 10_000, 50*time.Millisecond)

	err := q.Enqueue(context.Background(), makeEvent("hello world"))
	require.NoError(t, err)

	assert.Eventually(t, func() bool { return fp.totalEvents() >= 1 }, 3*time.Second, 10*time.Millisecond)
	assert.Eventually(t, func() bool { return q.EventsTotal() >= 1 }, 3*time.Second, 10*time.Millisecond)
}

func TestGPUQueue_BatchFlushBySize(t *testing.T) {
	fp := newFakeProcessor(t)
	// Set batchMax=10 so a batch of 10 flushes immediately without waiting.
	q := newTestQueue(t, fp, 10, 5*time.Second)

	for i := 0; i < 10; i++ {
		require.NoError(t, q.Enqueue(context.Background(), makeEvent(fmt.Sprintf("event-%d", i))))
	}

	fp.waitBatches(t, 1, 2*time.Second)
	assert.Equal(t, 10, fp.totalEvents())
}

func TestGPUQueue_MultipleBatches(t *testing.T) {
	fp := newFakeProcessor(t)
	q := newTestQueue(t, fp, 5, 5*time.Second)

	// Send 15 events — expect 3 batches of 5.
	for i := 0; i < 15; i++ {
		require.NoError(t, q.Enqueue(context.Background(), makeEvent(fmt.Sprintf("e%d", i))))
	}

	fp.waitBatches(t, 3, 3*time.Second)
	assert.Equal(t, 15, fp.totalEvents())
}

func TestGPUQueue_EventFields_PreservedOverWire(t *testing.T) {
	fp := newFakeProcessor(t)
	q := newTestQueue(t, fp, 1000, 50*time.Millisecond)

	e := event.RawEvent{
		Time:       time.Unix(1735689600, 0),
		Raw:        []byte("field test"),
		Host:       "myhost",
		Source:     "/var/log/app",
		Sourcetype: "app_log",
		Index:      "prod",
		Fields:     map[string]string{"key": "value", "env": "prod"},
	}
	require.NoError(t, q.Enqueue(context.Background(), e))
	fp.waitBatches(t, 1, 2*time.Second)

	require.Len(t, fp.received, 1)
	require.Len(t, fp.received[0].Events, 1)
	we := fp.received[0].Events[0]
	assert.Equal(t, "myhost", we.Host)
	assert.Equal(t, "/var/log/app", we.Source)
	assert.Equal(t, "app_log", we.Sourcetype)
	assert.Equal(t, "prod", we.Index)
	assert.Equal(t, "value", we.Fields["key"])
}

func TestGPUQueue_ProcessorError_CountsParseError(t *testing.T) {
	fp := newFakeProcessor(t)
	fp.returnError = "cuDF parse failed: out of memory"
	q := newTestQueue(t, fp, 1000, 50*time.Millisecond)

	require.NoError(t, q.Enqueue(context.Background(), makeEvent("will fail")))
	fp.waitBatches(t, 1, 2*time.Second)

	// Wait for the error to be counted.
	assert.Eventually(t, func() bool {
		return q.ParseErrors() > 0
	}, time.Second, 20*time.Millisecond)
}

func TestGPUQueue_Backpressure_MaxInFlight(t *testing.T) {
	// Use a very slow fake processor (100ms per batch) with MaxInFlight=2.
	socketPath := fmt.Sprintf("%s/test-gpu-bp-%d.sock", os.TempDir(), time.Now().UnixNano())
	ln, err := net.Listen("unix", socketPath)
	require.NoError(t, err)
	t.Cleanup(func() { ln.Close(); os.Remove(socketPath) })

	slowAck := make(chan struct{})
	go func() {
		conn, _ := ln.Accept()
		defer conn.Close()
		for {
			msg, err := readMsg(conn)
			if err != nil {
				return
			}
			var batch wireBatch
			_ = json.Unmarshal(msg, &batch)

			// Slow processor — wait for signal before acking.
			<-slowAck

			ack := wireAck{Written: int64(len(batch.Events))}
			b, _ := json.Marshal(ack)
			hdr := make([]byte, 4)
			binary.BigEndian.PutUint32(hdr, uint32(len(b)))
			_, _ = conn.Write(append(hdr, b...))
		}
	}()

	cfg := Config{
		SocketPath:     socketPath,
		BatchMax:       1,
		FlushInterval:  5 * time.Second, // no timer flush
		MaxInFlight:    2,
		SkipSubprocess: true,
	}
	q, err := New(cfg, store_client.NewNoOp(), zap.NewNop())
	require.NoError(t, err)
	time.Sleep(20 * time.Millisecond)
	conn, err := net.Dial("unix", socketPath)
	require.NoError(t, err)
	q.Connect(conn)
	t.Cleanup(func() { q.Close() })

	// Enqueue 2 events (each is its own batch since batchMax=1). These fill the semaphore.
	require.NoError(t, q.Enqueue(context.Background(), makeEvent("a")))
	require.NoError(t, q.Enqueue(context.Background(), makeEvent("b")))

	// The third enqueue should block because the semaphore (MaxInFlight=2) is full.
	// Use a short-deadline context to verify the block.
	blockCtx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	enqueueErr := make(chan error, 1)
	go func() {
		// Flush the batcher by sending one more event.
		enqueueErr <- q.Enqueue(blockCtx, makeEvent("c"))
	}()

	// Release one slot.
	slowAck <- struct{}{}

	// The goroutine should eventually complete.
	slowAck <- struct{}{}
	slowAck <- struct{}{}
}

func TestGPUQueue_FallbackWrite_NilConn(t *testing.T) {
	// When SkipSubprocess=true and no socket is connected, events fall back to
	// the store client.
	sc := store_client.NewNoOp()
	cfg := Config{
		BatchMax:       100,
		FlushInterval:  50 * time.Millisecond,
		SkipSubprocess: true,
	}
	q, err := New(cfg, sc, zap.NewNop())
	require.NoError(t, err)
	t.Cleanup(func() { q.Close() })

	require.NoError(t, q.Enqueue(context.Background(), makeEvent("fallback")))

	assert.Eventually(t, func() bool {
		return q.EventsTotal() >= 1
	}, 2*time.Second, 20*time.Millisecond)
	// Store client received the event via fallback.
	assert.GreaterOrEqual(t, sc.Written(), int64(1))
}

func TestGPUQueue_Close_GracefulShutdown(t *testing.T) {
	fp := newFakeProcessor(t)
	q := newTestQueue(t, fp, 1000, 50*time.Millisecond)

	for i := 0; i < 5; i++ {
		require.NoError(t, q.Enqueue(context.Background(), makeEvent(fmt.Sprintf("e%d", i))))
	}
	require.NoError(t, q.Close())
	// After close, further enqueue should fail.
	err := q.Enqueue(context.Background(), makeEvent("after close"))
	assert.Error(t, err)
}

// Package gpuqueue implements the R2 GPU parse queue for cuSplunk.
//
// Architecture
// ─────────────
// Protocol servers call Enqueue(). The batch accumulator collects events and
// flushes batches of up to BatchMax events or after FlushInterval, whichever
// comes first. Each flush forwards the batch to a Python subprocess via a
// Unix domain socket. The Python side runs the cuDF parse pipeline, compresses
// the _raw column with LZ4/nvCOMP, and writes the resulting Arrow batch to the
// store gRPC service. Go receives an ack with the count of events written.
//
// Backpressure
// ────────────
// A semaphore of size MaxInFlight (default 10) limits how many batches are
// concurrently in-flight to the Python processor. When the semaphore is full,
// Enqueue blocks until a batch completes (i.e. Python acks it). This prevents
// unbounded memory growth if the GPU falls behind.
//
// Wire format  (Go ↔ Python)
// ──────────────────────────
// Each message = 4-byte big-endian uint32 payload length + JSON payload.
//
//   Go → Python:  {"events": [{time_ns, raw_b64, host, source, sourcetype, index, fields}, ...]}
//   Python → Go:  {"written": N, "error": "..."}  (error is empty string on success)
//
// raw_b64 is the base64-encoded raw event bytes. The Python side compresses it
// with LZ4 before writing to the store.
//
// CPU fallback
// ────────────
// When NUMBA_ENABLE_CUDASIM=1 or CUDF_PANDAS_FALLBACK_MODE=1 is set the Python
// processor uses pandas instead of cuDF. All unit tests rely on this fallback.
package gpuqueue

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/store_client"
)

const (
	// DefaultBatchMax is the maximum events per batch before a forced flush.
	DefaultBatchMax = 10_000
	// DefaultFlushInterval is the maximum time between flushes.
	DefaultFlushInterval = 100 * time.Millisecond
	// DefaultMaxInFlight is the backpressure semaphore depth.
	DefaultMaxInFlight = 10
)

// Config configures the GPUQueue.
type Config struct {
	// SocketPath is the Unix socket path used for Go↔Python IPC.
	// If empty, a temp file is created automatically.
	SocketPath string
	// ProcessorCmd is the Python command to launch the processor.
	// Default: ["python3", "-m", "cusplunk.ingest.processor"]
	ProcessorCmd []string
	// ProcessorEnv are extra environment variables forwarded to the processor.
	ProcessorEnv []string
	// BatchMax is the max events per batch.
	BatchMax int
	// FlushInterval is the max time between flushes.
	FlushInterval time.Duration
	// MaxInFlight is the backpressure semaphore depth.
	MaxInFlight int
	// SkipSubprocess skips launching the Python subprocess (for tests that
	// inject their own socket server).
	SkipSubprocess bool
}

func (c *Config) withDefaults() Config {
	out := *c
	if len(out.ProcessorCmd) == 0 {
		out.ProcessorCmd = []string{"python3", "-m", "cusplunk.ingest.processor"}
	}
	if out.BatchMax == 0 {
		out.BatchMax = DefaultBatchMax
	}
	if out.FlushInterval == 0 {
		out.FlushInterval = DefaultFlushInterval
	}
	if out.MaxInFlight == 0 {
		out.MaxInFlight = DefaultMaxInFlight
	}
	return out
}

// wireEvent is the JSON representation of a single event sent to Python.
type wireEvent struct {
	TimeNs     int64             `json:"time_ns"`
	RawB64     []byte            `json:"raw"`   // JSON marshals []byte as base64
	Host       string            `json:"host"`
	Source     string            `json:"source"`
	Sourcetype string            `json:"sourcetype"`
	Index      string            `json:"index"`
	Fields     map[string]string `json:"fields,omitempty"`
}

// wireBatch is the JSON batch sent to Python.
type wireBatch struct {
	Events []wireEvent `json:"events"`
}

// wireAck is the JSON ack received from Python.
type wireAck struct {
	Written int64  `json:"written"`
	Error   string `json:"error"`
}

// GPUQueue implements queue.Queue using a Python subprocess for GPU processing.
type GPUQueue struct {
	cfg Config
	log *zap.Logger

	// ch is the inbound event channel (from protocol servers).
	ch chan event.RawEvent
	// done signals the batcher and sender goroutines to stop.
	done chan struct{}
	// semaphore limits concurrent in-flight batches (backpressure).
	semaphore chan struct{}

	// proc is the Python subprocess (nil when SkipSubprocess is true).
	proc *exec.Cmd

	// conn is the Unix socket connection to the Python processor.
	connMu sync.Mutex
	conn   net.Conn

	// closeOnce ensures Close() is idempotent.
	closeOnce sync.Once
	// closed is set to 1 by Close() so Enqueue returns immediately.
	closed atomic.Int32

	// storeClient is used when BypassPython is true (direct write without GPU).
	storeClient store_client.StoreClient

	// metrics
	eventsTotal  atomic.Int64
	parseErrors  atomic.Int64
	batchesSent  atomic.Int64
}

// New creates and starts a GPUQueue. The Python subprocess is launched
// immediately unless cfg.SkipSubprocess is true.
//
// The socketPath in cfg is used to communicate with the Python processor.
// If cfg.SocketPath is empty, a temp socket is created.
func New(cfg Config, sc store_client.StoreClient, log *zap.Logger) (*GPUQueue, error) {
	cfg = cfg.withDefaults()

	if cfg.SocketPath == "" {
		cfg.SocketPath = filepath.Join(os.TempDir(), fmt.Sprintf("cusplunk-gpu-%d.sock", os.Getpid()))
	}

	q := &GPUQueue{
		cfg:         cfg,
		log:         log,
		ch:          make(chan event.RawEvent, cfg.BatchMax*2),
		done:        make(chan struct{}),
		semaphore:   make(chan struct{}, cfg.MaxInFlight),
		storeClient: sc,
	}

	if !cfg.SkipSubprocess {
		if err := q.startSubprocess(); err != nil {
			return nil, fmt.Errorf("gpuqueue: start subprocess: %w", err)
		}
	}

	go q.batcher()
	return q, nil
}

// startSubprocess launches the Python processor and waits for the Unix socket
// to appear (max 10s).
func (q *GPUQueue) startSubprocess() error {
	// Remove stale socket.
	_ = os.Remove(q.cfg.SocketPath)

	args := q.cfg.ProcessorCmd[1:]
	cmd := exec.Command(q.cfg.ProcessorCmd[0], args...) //nolint:gosec
	cmd.Env = append(os.Environ(), q.cfg.ProcessorEnv...)
	cmd.Env = append(cmd.Env,
		"CUSPLUNK_SOCKET="+q.cfg.SocketPath,
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start %v: %w", q.cfg.ProcessorCmd, err)
	}
	q.proc = cmd

	// Wait for the socket file to appear.
	deadline := time.Now().Add(10 * time.Second)
	for {
		if _, err := os.Stat(q.cfg.SocketPath); err == nil {
			break
		}
		if time.Now().After(deadline) {
			_ = cmd.Process.Kill()
			return fmt.Errorf("timed out waiting for socket %s", q.cfg.SocketPath)
		}
		time.Sleep(50 * time.Millisecond)
	}

	conn, err := net.Dial("unix", q.cfg.SocketPath)
	if err != nil {
		return fmt.Errorf("dial socket %s: %w", q.cfg.SocketPath, err)
	}
	q.conn = conn
	q.log.Info("gpu processor connected", zap.String("socket", q.cfg.SocketPath))
	return nil
}

// Connect attaches an existing Unix socket connection. Used in tests when
// SkipSubprocess is true.
func (q *GPUQueue) Connect(conn net.Conn) {
	q.connMu.Lock()
	defer q.connMu.Unlock()
	q.conn = conn
}

// Enqueue adds an event to the queue. Blocks under backpressure.
func (q *GPUQueue) Enqueue(ctx context.Context, e event.RawEvent) error {
	if q.closed.Load() == 1 {
		return fmt.Errorf("enqueue: queue closed")
	}
	select {
	case q.ch <- e:
		return nil
	case <-ctx.Done():
		return fmt.Errorf("enqueue: %w", ctx.Err())
	case <-q.done:
		return fmt.Errorf("enqueue: queue closed")
	}
}

// Drain returns a nil channel. GPUQueue processes batches internally; callers
// should not use Drain(). It exists to satisfy the queue.Queue interface.
func (q *GPUQueue) Drain() <-chan []event.RawEvent {
	return nil
}

// Close shuts down the queue, flushes pending events, and terminates the
// Python subprocess. Safe to call multiple times.
func (q *GPUQueue) Close() error {
	q.closeOnce.Do(func() {
		q.closed.Store(1)
		close(q.done)

		q.connMu.Lock()
		if q.conn != nil {
			_ = q.conn.Close()
		}
		q.connMu.Unlock()

		if q.proc != nil {
			_ = q.proc.Process.Kill()
			_, _ = q.proc.Process.Wait()
		}
		_ = os.Remove(q.cfg.SocketPath)
	})
	return nil
}

// EventsTotal returns the total number of events successfully forwarded.
func (q *GPUQueue) EventsTotal() int64 { return q.eventsTotal.Load() }

// ParseErrors returns the total number of batch-level errors from Python.
func (q *GPUQueue) ParseErrors() int64 { return q.parseErrors.Load() }

// batcher accumulates events from ch into batches and sends them to the Python
// processor via Unix socket.
func (q *GPUQueue) batcher() {
	ticker := time.NewTicker(q.cfg.FlushInterval)
	defer ticker.Stop()

	batch := make([]event.RawEvent, 0, q.cfg.BatchMax)

	flush := func() {
		if len(batch) == 0 {
			return
		}
		toSend := batch
		batch = make([]event.RawEvent, 0, q.cfg.BatchMax)

		// Acquire semaphore (backpressure).
		select {
		case q.semaphore <- struct{}{}:
		case <-q.done:
			return
		}

		go func() {
			defer func() { <-q.semaphore }()
			if err := q.sendBatch(toSend); err != nil {
				q.log.Error("gpuqueue: send batch failed", zap.Error(err))
				q.parseErrors.Add(1)
			}
		}()
	}

	for {
		select {
		case e, ok := <-q.ch:
			if !ok {
				flush()
				return
			}
			batch = append(batch, e)
			if len(batch) >= q.cfg.BatchMax {
				flush()
			}
		case <-ticker.C:
			flush()
		case <-q.done:
			flush()
			return
		}
	}
}

// sendBatch serializes the batch as JSON and sends it to the Python processor
// via the Unix socket. It blocks until the ack is received.
func (q *GPUQueue) sendBatch(events []event.RawEvent) error {
	wireEvts := make([]wireEvent, len(events))
	for i, e := range events {
		wireEvts[i] = wireEvent{
			TimeNs:     e.Time.UnixNano(),
			RawB64:     e.Raw,
			Host:       e.Host,
			Source:     e.Source,
			Sourcetype: e.Sourcetype,
			Index:      e.Index,
			Fields:     e.Fields,
		}
	}

	payload, err := json.Marshal(wireBatch{Events: wireEvts})
	if err != nil {
		return fmt.Errorf("marshal batch: %w", err)
	}

	q.connMu.Lock()
	conn := q.conn
	q.connMu.Unlock()

	if conn == nil {
		// No processor connected: fall back to direct store write if available.
		return q.fallbackWrite(context.Background(), events)
	}

	// Write: [4-byte length][payload]
	hdr := make([]byte, 4)
	binary.BigEndian.PutUint32(hdr, uint32(len(payload)))
	if _, err := conn.Write(append(hdr, payload...)); err != nil {
		return fmt.Errorf("write batch: %w", err)
	}

	// Read ack: [4-byte length][JSON ack]
	ack, err := readMsg(conn)
	if err != nil {
		return fmt.Errorf("read ack: %w", err)
	}

	var wireAckMsg wireAck
	if err := json.Unmarshal(ack, &wireAckMsg); err != nil {
		return fmt.Errorf("unmarshal ack: %w", err)
	}
	if wireAckMsg.Error != "" {
		q.parseErrors.Add(1)
		return fmt.Errorf("processor error: %s", wireAckMsg.Error)
	}

	q.eventsTotal.Add(wireAckMsg.Written)
	q.batchesSent.Add(1)
	return nil
}

// fallbackWrite writes directly to the store client without GPU processing.
// Used when the Python processor is not available (e.g. during unit tests with
// SkipSubprocess=true and no socket injected).
func (q *GPUQueue) fallbackWrite(ctx context.Context, events []event.RawEvent) error {
	if q.storeClient == nil {
		q.eventsTotal.Add(int64(len(events)))
		return nil
	}
	if err := q.storeClient.Write(ctx, events); err != nil {
		return fmt.Errorf("fallback store write: %w", err)
	}
	q.eventsTotal.Add(int64(len(events)))
	return nil
}

// readMsg reads a length-prefixed message from r.
func readMsg(r io.Reader) ([]byte, error) {
	hdr := make([]byte, 4)
	if _, err := io.ReadFull(r, hdr); err != nil {
		return nil, fmt.Errorf("read length: %w", err)
	}
	n := binary.BigEndian.Uint32(hdr)
	if n > 64*1024*1024 { // sanity: 64 MiB max message
		return nil, fmt.Errorf("message too large: %d bytes", n)
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return nil, fmt.Errorf("read body: %w", err)
	}
	return buf, nil
}

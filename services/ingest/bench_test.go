// Ingest pipeline benchmarks.
//
// Run (CPU mode, no GPU required):
//
//	go test github.com/om-ashish-soni/cusplunk/ingest \
//	    -bench=. -benchtime=10s -timeout 120s
//
// Throughput targets on A10G GPU:
//   BenchmarkIngest_GPUQueue              >1M enqueue/sec
//   BenchmarkIngest_GPUQueue_WithSocket   >500K events/sec (IPC roundtrip)
//   BenchmarkIngest_S2S                   >500K events/sec
package ingest_test

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"testing"
	"time"

	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/event"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/gpuqueue"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/s2s"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/store_client"
)

// ---------------------------------------------------------------------------
// BenchmarkIngest_GPUQueue — raw enqueue rate (no socket, fallback write)
// ---------------------------------------------------------------------------

func BenchmarkIngest_GPUQueue(b *testing.B) {
	sc := store_client.NewNoOp()
	q, err := gpuqueue.New(gpuqueue.Config{
		BatchMax:       10_000,
		FlushInterval:  100 * time.Millisecond,
		SkipSubprocess: true,
	}, sc, zap.NewNop())
	if err != nil {
		b.Fatal(err)
	}
	defer q.Close()

	ctx := context.Background()
	e := event.RawEvent{
		Time:       time.Now(),
		Raw:        []byte("benchmark event payload of typical length for syslog messages"),
		Host:       "bench-host",
		Source:     "/var/log/bench",
		Sourcetype: "bench",
		Index:      "main",
	}

	b.ResetTimer()
	b.ReportAllocs()
	b.SetBytes(int64(len(e.Raw)))

	for i := 0; i < b.N; i++ {
		if err := q.Enqueue(ctx, e); err != nil {
			b.Fatal(err)
		}
	}
	b.StopTimer()
	time.Sleep(50 * time.Millisecond) // let pending batches drain
}

// ---------------------------------------------------------------------------
// BenchmarkIngest_GPUQueue_WithSocket — full IPC roundtrip throughput
// ---------------------------------------------------------------------------

// BenchmarkIngest_GPUQueue_WithSocket measures the Go→Unix socket→ack
// roundtrip throughput using a no-op processor goroutine. This is the
// theoretical ceiling for the full pipeline without GPU processing overhead.
func BenchmarkIngest_GPUQueue_WithSocket(b *testing.B) {
	socketPath := fmt.Sprintf("%s/cusplunk-bench-%d.sock", os.TempDir(), time.Now().UnixNano())
	fp := startBenchProcessor(b, socketPath)
	defer fp.ln.Close()
	defer os.Remove(socketPath)

	procConn, err := net.Dial("unix", socketPath)
	if err != nil {
		b.Fatal(err)
	}

	sc := store_client.NewNoOp()
	q, err := gpuqueue.New(gpuqueue.Config{
		SocketPath:     socketPath,
		BatchMax:       10_000,
		FlushInterval:  100 * time.Millisecond,
		MaxInFlight:    10,
		SkipSubprocess: true,
	}, sc, zap.NewNop())
	if err != nil {
		b.Fatal(err)
	}
	q.Connect(procConn)
	defer q.Close()

	ctx := context.Background()
	e := event.RawEvent{
		Time:       time.Now(),
		Raw:        []byte("benchmark event payload for IPC throughput measurement"),
		Host:       "bench-host",
		Source:     "/var/log/bench",
		Sourcetype: "bench",
		Index:      "main",
	}

	b.ResetTimer()
	b.ReportAllocs()
	b.SetBytes(int64(len(e.Raw)))

	for i := 0; i < b.N; i++ {
		if err := q.Enqueue(ctx, e); err != nil {
			b.Fatal(err)
		}
	}
	b.StopTimer()
	time.Sleep(300 * time.Millisecond) // drain
	b.ReportMetric(float64(q.EventsTotal()), "events_total")
}

// ---------------------------------------------------------------------------
// BenchmarkIngest_S2S — S2S TCP end-to-end frame throughput
// ---------------------------------------------------------------------------

func BenchmarkIngest_S2S(b *testing.B) {
	sc := store_client.NewNoOp()
	q, err := gpuqueue.New(gpuqueue.Config{
		BatchMax:       10_000,
		FlushInterval:  100 * time.Millisecond,
		SkipSubprocess: true,
	}, sc, zap.NewNop())
	if err != nil {
		b.Fatal(err)
	}
	defer q.Close()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		b.Fatal(err)
	}
	srv := s2s.NewServer(config.S2SConfig{
		Enabled:        true,
		MaxConnections: 100,
		ReadTimeout:    30 * time.Second,
	}, q, zap.NewNop())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	srv.StartWithListener(ctx, ln)

	conn, err := net.DialTimeout("tcp", ln.Addr().String(), time.Second)
	if err != nil {
		b.Fatal(err)
	}
	hello := s2s.MagicHello()
	conn.Write(hello[:])
	ack := make([]byte, 4)
	conn.Read(ack)
	defer conn.Close()

	frame := s2s.BuildFrame(map[string]string{
		"_raw":           "benchmark s2s event payload typical syslog line for performance measurement",
		"_time":          "1735689600",
		"host":           "bench-host",
		"source":         "/var/log/bench",
		"sourcetype":     "bench",
		"MetaData:index": "main",
	})

	b.ResetTimer()
	b.ReportAllocs()
	b.SetBytes(int64(len(frame)))

	for i := 0; i < b.N; i++ {
		if _, err := conn.Write(frame); err != nil {
			b.Fatal(err)
		}
	}
	b.StopTimer()
	time.Sleep(200 * time.Millisecond)
	b.ReportMetric(float64(srv.EventsTotal()), "events_total")
}

// ---------------------------------------------------------------------------
// benchProcessor — no-op Unix socket server for IPC benchmarks
// ---------------------------------------------------------------------------

type benchProc struct {
	ln net.Listener
}

func startBenchProcessor(b *testing.B, socketPath string) *benchProc {
	b.Helper()
	ln, err := net.Listen("unix", socketPath)
	if err != nil {
		b.Fatal(err)
	}
	bp := &benchProc{ln: ln}
	go bp.serve()
	return bp
}

func (bp *benchProc) serve() {
	for {
		conn, err := bp.ln.Accept()
		if err != nil {
			return
		}
		go bp.handleConn(conn)
	}
}

func (bp *benchProc) handleConn(conn net.Conn) {
	defer conn.Close()
	hdr := make([]byte, 4)
	for {
		if err := benchReadFull(conn, hdr); err != nil {
			return
		}
		n := binary.BigEndian.Uint32(hdr)
		body := make([]byte, n)
		if err := benchReadFull(conn, body); err != nil {
			return
		}
		var batch struct {
			Events []json.RawMessage `json:"events"`
		}
		json.Unmarshal(body, &batch) //nolint:errcheck

		ack, _ := json.Marshal(map[string]interface{}{
			"written": len(batch.Events),
			"error":   "",
		})
		ackHdr := make([]byte, 4)
		binary.BigEndian.PutUint32(ackHdr, uint32(len(ack)))
		conn.Write(append(ackHdr, ack...)) //nolint:errcheck
	}
}

func benchReadFull(conn net.Conn, buf []byte) error {
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

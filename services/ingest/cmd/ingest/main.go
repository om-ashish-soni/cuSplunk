// Command ingest is the cuSplunk ingest service entry point.
//
// R1 wired: S2S, HEC, Syslog protocol servers → ChannelQueue → drain stub.
// R2 wired: S2S, HEC, Syslog protocol servers → GPUQueue → Python cuDF processor
//           → store gRPC service.
//
// GPU queue is enabled when CUSPLUNK_GPU_QUEUE=1 (default in docker-compose.gpu.yml).
// Processor socket path is CUSPLUNK_SOCKET (default: /tmp/cusplunk-gpu.sock).
// Store gRPC address is CUSPLUNK_STORE_ADDR (default: localhost:50051).
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/gpuqueue"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/hec"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/metrics"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/s2s"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/store_client"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/syslog"
)

func main() {
	cfgPath := flag.String("config", "", "Path to config YAML file (optional; built-in defaults apply)")
	flag.Parse()

	cfg, err := config.Load(*cfgPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ingest: failed to load config: %v\n", err)
		os.Exit(1)
	}

	log, err := buildLogger(cfg.Log.Level)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ingest: failed to build logger: %v\n", err)
		os.Exit(1)
	}
	defer log.Sync()

	log.Info("cuSplunk ingest service starting")

	// Metrics server (Prometheus).
	metrics.StartHTTP(cfg.Metrics.Port, log)

	// ---------------------------------------------------------------------------
	// Queue selection: GPUQueue (R2) or ChannelQueue (R1 fallback)
	// ---------------------------------------------------------------------------

	useGPUQueue := os.Getenv("CUSPLUNK_GPU_QUEUE") == "1"
	var q queue.Queue
	var sc store_client.StoreClient

	if useGPUQueue {
		socketPath := os.Getenv("CUSPLUNK_SOCKET")
		if socketPath == "" {
			socketPath = "/tmp/cusplunk-gpu.sock"
		}
		storeAddr := os.Getenv("CUSPLUNK_STORE_ADDR")
		if storeAddr == "" {
			storeAddr = "localhost:50051"
		}

		// Create gRPC store client for direct writes (bypass GPU path).
		sc, err = store_client.New(store_client.Config{
			Address: storeAddr,
		}, log)
		if err != nil {
			log.Warn("store gRPC client unavailable, using no-op",
				zap.Error(err), zap.String("addr", storeAddr))
			sc = store_client.NewNoOp()
		} else {
			defer sc.Close()
		}

		gq, err := gpuqueue.New(gpuqueue.Config{
			SocketPath: socketPath,
			ProcessorCmd: []string{
				"python3", "-m", "cusplunk.ingest.processor",
			},
			ProcessorEnv: []string{
				"CUSPLUNK_STORE_ADDR=" + storeAddr,
			},
			BatchMax:      cfg.GPUQueue.BatchSize,
			FlushInterval: time.Duration(cfg.GPUQueue.FlushIntervalMs) * time.Millisecond,
			MaxInFlight:   10,
		}, sc, log)
		if err != nil {
			log.Fatal("failed to start GPU queue", zap.Error(err))
		}
		defer gq.Close()
		q = gq
		log.Info("GPU queue started",
			zap.String("socket", socketPath),
			zap.String("store", storeAddr))
	} else {
		// R1/CI fallback: plain channel queue, drain to void.
		cq := queue.NewChannelQueue(cfg.GPUQueue.ChannelCapacity)
		defer cq.Close()
		go drainQueue(cq, log)
		q = cq
		log.Info("channel queue started (CPU mode, no GPU processing)")
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// --- S2S server (Splunk Universal Forwarder protocol) ---
	if cfg.S2S.Enabled {
		s2sSrv := s2s.NewServer(cfg.S2S, q, log)
		if err := s2sSrv.Start(ctx); err != nil {
			log.Fatal("s2s server failed to start", zap.Error(err))
		}
		log.Info("s2s server started", zap.Int("port", cfg.S2S.Port))
		defer func() {
			shutCtx, c := context.WithTimeout(context.Background(), 10*time.Second)
			defer c()
			if err := s2sSrv.Shutdown(shutCtx); err != nil {
				log.Warn("s2s shutdown error", zap.Error(err))
			}
		}()
	}

	// --- HEC server (HTTP Event Collector) ---
	if cfg.HEC.Enabled {
		hecSrv := hec.NewServer(cfg.HEC, q, log)
		if err := hecSrv.Start(ctx); err != nil {
			log.Fatal("hec server failed to start", zap.Error(err))
		}
		log.Info("hec server started", zap.Int("port", cfg.HEC.Port))
		defer func() {
			shutCtx, c := context.WithTimeout(context.Background(), 10*time.Second)
			defer c()
			if err := hecSrv.Shutdown(shutCtx); err != nil {
				log.Warn("hec shutdown error", zap.Error(err))
			}
		}()
	}

	// --- Syslog server (UDP 514, TCP 514, TLS 6514) ---
	if cfg.Syslog.Enabled {
		syslogSrv := syslog.NewServer(cfg.Syslog, q, log)
		if err := syslogSrv.Start(ctx); err != nil {
			log.Fatal("syslog server failed to start", zap.Error(err))
		}
		log.Info("syslog servers started",
			zap.Int("udp", cfg.Syslog.UDPPort),
			zap.Int("tcp", cfg.Syslog.TCPPort))
		defer func() {
			shutCtx, c := context.WithTimeout(context.Background(), 10*time.Second)
			defer c()
			if err := syslogSrv.Shutdown(shutCtx); err != nil {
				log.Warn("syslog shutdown error", zap.Error(err))
			}
		}()
	}

	log.Info("all servers started — waiting for signals")

	// Block until SIGINT or SIGTERM.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigCh
	log.Info("received signal, shutting down", zap.String("signal", sig.String()))
}

// drainQueue discards events (used in CPU/CI mode where no GPU pipeline is wired).
func drainQueue(q *queue.ChannelQueue, log *zap.Logger) {
	var total uint64
	for batch := range q.Drain() {
		total += uint64(len(batch))
		if total%100_000 == 0 {
			log.Info("ingest queue: events processed (channel drain)",
				zap.Uint64("total", total))
		}
	}
}

// buildLogger constructs a production zap logger at the given level.
func buildLogger(level string) (*zap.Logger, error) {
	lvl := zap.InfoLevel
	if err := lvl.UnmarshalText([]byte(level)); err != nil {
		return nil, fmt.Errorf("invalid log level %q: %w", level, err)
	}
	encCfg := zap.NewProductionEncoderConfig()
	encCfg.TimeKey = "ts"
	encCfg.EncodeTime = zapcore.ISO8601TimeEncoder

	zapCfg := zap.Config{
		Level:            zap.NewAtomicLevelAt(lvl),
		Development:      false,
		Encoding:         "json",
		EncoderConfig:    encCfg,
		OutputPaths:      []string{"stdout"},
		ErrorOutputPaths: []string{"stderr"},
	}
	return zapCfg.Build()
}

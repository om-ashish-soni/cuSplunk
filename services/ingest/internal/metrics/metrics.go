// Package metrics registers and exposes Prometheus metrics for the ingest service.
package metrics

import (
	"fmt"
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.uber.org/zap"
)

// Metrics holds all Prometheus counters and gauges for the ingest service.
type Metrics struct {
	// EventsTotal counts the number of raw events accepted by each protocol.
	EventsTotal *prometheus.CounterVec

	// BytesTotal counts the number of raw bytes ingested by each protocol.
	BytesTotal *prometheus.CounterVec

	// ParseErrors counts the number of parse failures by protocol.
	ParseErrors *prometheus.CounterVec

	// GPUQueueDepth is the current number of events waiting in the GPU parse queue.
	GPUQueueDepth prometheus.Gauge

	// ActiveConnections tracks the number of live S2S connections.
	ActiveConnections prometheus.Gauge
}

// New registers all metrics in reg and returns a Metrics instance.
func New(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		EventsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "cusplunk_ingest_events_total",
			Help: "Total number of events accepted by the ingest service.",
		}, []string{"protocol"}),

		BytesTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "cusplunk_ingest_bytes_total",
			Help: "Total bytes ingested by protocol.",
		}, []string{"protocol"}),

		ParseErrors: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "cusplunk_ingest_parse_errors_total",
			Help: "Total parse errors by protocol.",
		}, []string{"protocol"}),

		GPUQueueDepth: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "cusplunk_gpu_queue_depth",
			Help: "Current depth of the GPU parse queue.",
		}),

		ActiveConnections: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "cusplunk_s2s_active_connections",
			Help: "Number of active S2S forwarder connections.",
		}),
	}

	reg.MustRegister(
		m.EventsTotal,
		m.BytesTotal,
		m.ParseErrors,
		m.GPUQueueDepth,
		m.ActiveConnections,
	)
	return m
}

// StartHTTP starts the Prometheus HTTP metrics server on the given port.
func StartHTTP(port int, log *zap.Logger) {
	addr := fmt.Sprintf("0.0.0.0:%d", port)
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "ok")
	})
	log.Info("metrics server listening", zap.String("addr", addr))
	go func() {
		if err := http.ListenAndServe(addr, mux); err != nil && err != http.ErrServerClosed {
			log.Error("metrics server error", zap.Error(err))
		}
	}()
}

package hec

import (
	"context"
	"crypto/tls"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"

	"github.com/om-ashish-soni/cusplunk/ingest/internal/config"
	"github.com/om-ashish-soni/cusplunk/ingest/internal/queue"
)

// Server is the HEC HTTP server. It exposes the Splunk-compatible HEC API
// on port 8088 so any existing HEC client can POST events without changes.
type Server struct {
	cfg    config.HECConfig
	queue  queue.Queue
	log    *zap.Logger
	tokens *tokenStore
	srv    *http.Server
}

// NewServer constructs a new HEC server. Call Start to begin serving.
func NewServer(cfg config.HECConfig, q queue.Queue, log *zap.Logger) *Server {
	ts := newTokenStore()
	for _, t := range cfg.Tokens {
		ts.add(t.Token, t.DefaultIndex, t.DefaultHost)
	}
	return &Server{cfg: cfg, queue: q, log: log, tokens: ts}
}

// Start configures and starts the HTTP (or HTTPS) server in a goroutine.
func (s *Server) Start(_ context.Context) error {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	h := &handler{q: s.queue, tokens: s.tokens}

	// Splunk-compatible routes.
	r.POST("/services/collector/event", h.handleEvent)
	r.POST("/services/collector/raw", h.handleRaw)
	r.POST("/services/collector/ack", h.handleAck)
	r.GET("/services/collector/health", h.handleHealth)
	// Splunk also accepts the shorter path.
	r.POST("/services/collector", h.handleEvent)

	addr := fmt.Sprintf("0.0.0.0:%d", s.cfg.Port)
	s.srv = &http.Server{
		Addr:         addr,
		Handler:      r,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	if s.cfg.TLSCert != "" && s.cfg.TLSKey != "" {
		cert, err := tls.LoadX509KeyPair(s.cfg.TLSCert, s.cfg.TLSKey)
		if err != nil {
			return fmt.Errorf("hec: load TLS cert: %w", err)
		}
		s.srv.TLSConfig = &tls.Config{
			Certificates: []tls.Certificate{cert},
			MinVersion:   tls.VersionTLS12,
		}
		s.log.Info("hec server listening (TLS)", zap.String("addr", addr))
		go func() {
			if err := s.srv.ListenAndServeTLS("", ""); err != nil && err != http.ErrServerClosed {
				s.log.Error("hec TLS server error", zap.Error(err))
			}
		}()
	} else {
		s.log.Info("hec server listening", zap.String("addr", addr))
		go func() {
			if err := s.srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				s.log.Error("hec server error", zap.Error(err))
			}
		}()
	}
	return nil
}

// Shutdown gracefully stops the HEC server.
func (s *Server) Shutdown(ctx context.Context) error {
	if s.srv != nil {
		return s.srv.Shutdown(ctx)
	}
	return nil
}

// AddToken registers an additional valid HEC token at runtime.
func (s *Server) AddToken(token, defaultIndex, defaultHost string) {
	s.tokens.add(token, defaultIndex, defaultHost)
}

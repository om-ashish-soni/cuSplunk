// Package config loads and validates the ingest service configuration.
package config

import (
	"fmt"
	"time"

	"github.com/spf13/viper"
)

// Config is the top-level configuration for the ingest service.
type Config struct {
	S2S      S2SConfig      `mapstructure:"s2s"`
	HEC      HECConfig      `mapstructure:"hec"`
	Syslog   SyslogConfig   `mapstructure:"syslog"`
	GPUQueue GPUQueueConfig `mapstructure:"gpu_queue"`
	Store    StoreConfig    `mapstructure:"store_grpc"`
	Metrics  MetricsConfig  `mapstructure:"metrics"`
	Log      LogConfig      `mapstructure:"log"`
}

// S2SConfig configures the Splunk-to-Splunk protocol listener (port 9997).
type S2SConfig struct {
	Enabled        bool          `mapstructure:"enabled"`
	Port           int           `mapstructure:"port"`
	MaxConnections int           `mapstructure:"max_connections"`
	ReadTimeout    time.Duration `mapstructure:"read_timeout"`
	WriteTimeout   time.Duration `mapstructure:"write_timeout"`
}

// HECConfig configures the HTTP Event Collector listener (port 8088).
type HECConfig struct {
	Enabled      bool        `mapstructure:"enabled"`
	Port         int         `mapstructure:"port"`
	TLSCert      string      `mapstructure:"tls_cert"`
	TLSKey       string      `mapstructure:"tls_key"`
	Tokens       []HECToken  `mapstructure:"tokens"`
	MaxBodyBytes int64       `mapstructure:"max_body_bytes"`
}

// HECToken is a valid HEC authentication token with its associated defaults.
type HECToken struct {
	Token        string `mapstructure:"token"`
	DefaultIndex string `mapstructure:"default_index"`
	DefaultHost  string `mapstructure:"default_host"`
}

// SyslogConfig configures syslog listeners (UDP 514, TCP 514, TLS 6514).
type SyslogConfig struct {
	Enabled     bool   `mapstructure:"enabled"`
	UDPPort     int    `mapstructure:"udp_port"`
	TCPPort     int    `mapstructure:"tcp_port"`
	TLSPort     int    `mapstructure:"tls_port"`
	TLSCert     string `mapstructure:"tls_cert"`
	TLSKey      string `mapstructure:"tls_key"`
	DefaultIndex string `mapstructure:"default_index"`
}

// GPUQueueConfig controls the GPU parse queue (R1: channel stub; R2: CUDA ring buffer).
type GPUQueueConfig struct {
	BatchSize       int           `mapstructure:"batch_size"`
	FlushIntervalMs time.Duration `mapstructure:"flush_interval_ms"`
	ChannelCapacity int           `mapstructure:"channel_capacity"`
}

// StoreConfig is the address of the store service gRPC endpoint.
type StoreConfig struct {
	Address string `mapstructure:"address"`
}

// MetricsConfig configures the Prometheus metrics HTTP endpoint.
type MetricsConfig struct {
	Port int `mapstructure:"port"`
}

// LogConfig controls structured logging.
type LogConfig struct {
	Level string `mapstructure:"level"` // debug | info | warn | error
}

// Load reads configuration from the file at path, falling back to defaults.
func Load(path string) (*Config, error) {
	v := viper.New()

	// Defaults
	v.SetDefault("s2s.enabled", true)
	v.SetDefault("s2s.port", 9997)
	v.SetDefault("s2s.max_connections", 10000)
	v.SetDefault("s2s.read_timeout", "30s")
	v.SetDefault("s2s.write_timeout", "10s")

	v.SetDefault("hec.enabled", true)
	v.SetDefault("hec.port", 8088)
	v.SetDefault("hec.max_body_bytes", 1<<20) // 1 MB

	v.SetDefault("syslog.enabled", true)
	v.SetDefault("syslog.udp_port", 514)
	v.SetDefault("syslog.tcp_port", 514)
	v.SetDefault("syslog.tls_port", 6514)
	v.SetDefault("syslog.default_index", "main")

	v.SetDefault("gpu_queue.batch_size", 10000)
	v.SetDefault("gpu_queue.flush_interval_ms", 100)
	v.SetDefault("gpu_queue.channel_capacity", 100000)

	v.SetDefault("store_grpc.address", "store-service:50051")
	v.SetDefault("metrics.port", 9090)
	v.SetDefault("log.level", "info")

	if path != "" {
		v.SetConfigFile(path)
		if err := v.ReadInConfig(); err != nil {
			return nil, fmt.Errorf("config: read %q: %w", path, err)
		}
	}

	v.AutomaticEnv()

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("config: unmarshal: %w", err)
	}
	return &cfg, nil
}

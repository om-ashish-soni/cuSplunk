# cuSplunk Ingest Service

**Language:** Go  
**Epic:** [E1 — INGEST](../../docs/epics/e1-ingest.md)  
**Owner:** P1

## Protocols

| Protocol | Port | Status |
|---|---|---|
| Splunk S2S (Universal Forwarder) | 9997 TCP | TODO |
| HTTP Event Collector (HEC) | 8088 HTTPS | TODO |
| Syslog UDP | 514 UDP | TODO |
| Syslog TCP | 514 TCP | TODO |
| Syslog TLS | 6514 TLS | TODO |
| Kafka Consumer | configurable | TODO |

## Quick Start

```bash
go run ./cmd/ingest --config config.yaml
```

## Config

```yaml
s2s:
  port: 9997
  max_connections: 10000

hec:
  port: 8088
  tokens:
    - token: "your-hec-token"
      default_index: "main"

syslog:
  udp_port: 514
  tcp_port: 514
  tls_port: 6514
  tls_cert: /etc/cusplunk/tls/cert.pem
  tls_key: /etc/cusplunk/tls/key.pem

gpu_queue:
  batch_size: 10000
  flush_interval_ms: 100

store_grpc:
  address: "store-service:50051"
```

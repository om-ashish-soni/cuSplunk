# cuSplunk Bridge Service

**Language:** Go  
**Epic:** [E4 — BRIDGE](../../docs/epics/e4-bridge.md)  
**Owner:** P1

Transparent 90-day federation layer between existing Splunk and cuSplunk GPU store.
Auto-expires at day 90. Customers never need to manually migrate data.

## Quick Start

```bash
go run ./cmd/bridge --config config.yaml
```

## Config

```yaml
splunk:
  url: https://your-splunk-host:8089
  token: ${SPLUNK_TOKEN}
  timeout: 300s
  verify_tls: true

cutover_date: "2025-06-01T00:00:00Z"
auto_sunset_days: 90

grpc:
  port: 50052
```

## How It Works

```
Query time_range=[T-120d, now], cutover=T-60d

  T-120d ──────── T-60d ──────────────── now
  [  Splunk  ]    [     GPU Store      ]
       │                   │
       └─────────┬─────────┘
              merge + dedup
```

After day 90: all queries route to GPU store. Bridge logs shutdown and disables itself.

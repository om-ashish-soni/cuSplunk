# ADR-004: Go for Ingest and API Services

**Status:** Accepted  
**Date:** 2026-04-15

## Context

The ingest service handles: Splunk S2S protocol, HEC, Syslog, Kafka. It needs:
1. High concurrency (10,000+ simultaneous forwarder connections)
2. Low latency protocol parsing
3. Easy gRPC client to storage service
4. Small binary, easy to deploy

## Decision

Use **Go** for `services/ingest/` and `services/api/` and `services/bridge/`.

## Consequences

**Good:**
- Goroutines handle 10,000 concurrent TCP connections trivially
- `encoding/binary` for S2S protocol parsing
- `google.golang.org/grpc` — first-class gRPC support
- Single binary deployment, small Docker image (~15 MB)
- Team has Go experience

**Bad:**
- Not ideal for GPU code (but ingest doesn't touch GPU directly — it enqueues to Python GPU service)
- CGo required if we ever need C library bindings

## Alternatives Considered

| Language | Rejected reason |
|---|---|
| Rust | Correct choice for storage (we use it there), but Go is faster to iterate for protocol servers |
| Python | Too slow for 10K concurrent connections at protocol parsing layer |
| Java | Heavy runtime, slow startup, over-engineered for this use case |

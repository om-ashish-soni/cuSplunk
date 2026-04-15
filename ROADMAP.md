# cuSplunk — Roadmap

## Vision

Ship a GPU-native, SPL-compatible SIEM that makes enterprise security teams 10–100× faster — without changing a single forwarder config or rewriting a single saved search.

## Milestones

```
M1: Proof of Concept (E1+E2+E3 MVP)
    Target: ingest via HEC, store on GPU, run basic SPL, benchmark vs Splunk
    
M2: Drop-in Replacement (E1+E2+E3+E4 complete)
    Target: Universal Forwarder compatibility, 90-day bridge working,
            enterprise can run cuSplunk alongside Splunk

M3: Detection-Ready (M2 + E5)
    Target: Sigma rules on GPU, ML inference, alerting working
    
M4: Full Platform (M3 + E6)
    Target: UI live, Splunk-familiar UX, first external beta customers
    
M5: Enterprise-Ready (M4 + E7)
    Target: SSO, multi-tenancy, compliance reports, K8s operator
    
M6: Scale Proven (M5 + E8)
    Target: Published benchmarks, 10-node cluster tested,
            acquisition conversations start
```

## Epic Status

| Epic | Milestone | Owner | Status |
|---|---|---|---|
| [E1 INGEST](docs/epics/e1-ingest.md) | M1 | P1 | Planning |
| [E2 STORE](docs/epics/e2-store.md) | M1 | P2 | Planning |
| [E3 QUERY](docs/epics/e3-query.md) | M1 | P3 | Planning |
| [E4 BRIDGE](docs/epics/e4-bridge.md) | M2 | P1 | Planning |
| [E5 DETECT](docs/epics/e5-detect.md) | M3 | P4 | Planning |
| [E6 PLATFORM](docs/epics/e6-platform.md) | M4 | P4 | Planning |
| [E7 ENTERPRISE](docs/epics/e7-enterprise.md) | M5 | All | Planning |
| [E8 SCALE](docs/epics/e8-scale.md) | M6 | P2 | Planning |

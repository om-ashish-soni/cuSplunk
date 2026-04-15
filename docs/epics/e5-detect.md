# E5 — DETECT: GPU-Powered Detection Engine

**Owner:** P4  
**Service:** `services/detect/` (Python + NVIDIA Morpheus)  
**Milestone:** M3  
**Status:** R2 ✅ S5.1 (Sigma engine) + S5.5 (cyBERT normalize) — pipeline skeleton — uncommitted to branch

## Goal

Run 10,000 detection rules simultaneously on GPU against live log streams. Alert latency target: **<100ms from event ingestion to alert fired.**

## Stories

### S5.1 — Sigma Rule Engine
- Parse Sigma YAML rules (all condition types: keywords, field matches, aggregations)
- Transpile Sigma → GPU multi-pattern regex pipeline
- HybridSA-inspired bit-parallel matching on GPU
- Bulk load: 10,000 rules loaded at startup, hot-reload on change
- Per-rule match counter, false positive rate tracking

### S5.2 — YARA Rule Engine
- YARA rule ingestion via REST API
- GPU-parallel string/pattern matching on raw log bytes
- libyara for rule compilation, CUDA for parallel evaluation
- Useful for: malware hash matching, known bad strings in logs

### S5.3 — Streaming Detection Pipeline
- NVIDIA Morpheus pipeline: ingest stream → GPU detection → alert output
- RAPIDS cuStreamz for streaming DataFrame processing
- Batch size: 1,000 events per GPU evaluation pass
- Latency budget: <50ms parse → <30ms detection → <20ms alert emit = <100ms total

### S5.4 — ML Model Inference (Triton)
Pre-trained models served via NVIDIA Triton Inference Server:

| Model | Input | Output | Use case |
|---|---|---|---|
| DGA Detector | DNS query strings | prob(malicious) | C2 detection |
| Phishing Detector | Email headers + URLs | prob(phishing) | Email security |
| UEBA | User action sequences | anomaly_score | Insider threat |
| cyBERT | Raw log strings | structured fields | Log normalization |
| Port Scan Detector | NetFlow events | prob(scan) | Recon detection |

- Triton gRPC client in Python
- Model versioning: A/B deploy new models without downtime
- Inference latency target: <10ms per batch (1,000 events)

### S5.5 — cyBERT Normalization
- Fork of RAPIDS CLX cyBERT, productionized
- Supported log types: Windows Event Logs, Syslog, CEF, LEEF, JSON, DNS, Web proxy
- Output: normalized ECS-compatible field set
- Runs at ingest time (not query time) — fields stored in `extracted/` columns
- F1 target: >0.995 on Windows Event Log field extraction

### S5.6 — MITRE ATT&CK Enrichment
- Every Sigma rule tagged with MITRE technique(s)
- Alert output includes: `mitre.tactic`, `mitre.technique`, `mitre.technique_id`, `mitre.url`
- MITRE ATT&CK matrix view in UI: heatmap of detections by technique
- ATT&CK Navigator export (JSON)

### S5.7 — Threat Intelligence Feed Ingestion
- STIX 2.1 / TAXII 2.1 feed ingestion
- Supported IOC types: IPv4, IPv6, domain, URL, file hash, email
- GPU join: event IPs/domains vs threat intel table at query time (not pre-processing)
- Feed refresh: configurable (default 1 hour)
- Free feeds: AlienVault OTX, Abuse.ch, CISA KEV

### S5.8 — Alert Management
- Alert dedup: same rule + same entity within 5 min = one alert
- Alert grouping: cluster related alerts into incidents
- Severity scoring: `critical / high / medium / low / info`
- Suppression windows: silence rule X for Y minutes
- Alert lifecycle: `new → assigned → investigating → resolved / false_positive`

### S5.9 — Alert Output Integrations
- PagerDuty (Events API v2)
- Slack (webhook)
- JIRA (create issue)
- Email (SMTP)
- Webhook (generic POST)
- cuSplunk Case (native case management in E6)

### S5.10 — Detection Rule API
```
GET    /api/v1/rules              # list all rules
POST   /api/v1/rules              # create rule (Sigma YAML)
GET    /api/v1/rules/{id}         # get rule
PUT    /api/v1/rules/{id}         # update rule
DELETE /api/v1/rules/{id}         # delete rule
POST   /api/v1/rules/{id}/test    # test rule against sample events
GET    /api/v1/rules/{id}/stats   # match count, false positive rate
```

## Detection Benchmark Target

| Metric | Target |
|---|---|
| Rules evaluated simultaneously | 10,000 |
| Ingest rate with detection active | 1M events/sec (no degradation) |
| Alert latency (p99) | <100ms |
| Sigma rule compatibility | >95% of SigmaHQ rules |
| ML inference latency (p99) | <10ms per 1,000 events |

## Dependencies

- NVIDIA Morpheus (open-source, GPU AI framework)
- RAPIDS cuStreamz
- NVIDIA Triton Inference Server
- libyara
- CUDA C++ (HybridSA regex kernels)
- STIX2 Python library
- PyYAML (Sigma parsing)

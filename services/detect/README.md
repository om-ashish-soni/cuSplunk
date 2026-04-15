# cuSplunk Detection Service

**Language:** Python + NVIDIA Morpheus  
**Epic:** [E5 — DETECT](../../docs/epics/e5-detect.md)  
**Owner:** P4

## Detection Engines

| Engine | Rules | Latency Target |
|---|---|---|
| Sigma (GPU regex) | 10,000+ rules | <30ms/batch |
| YARA | Unlimited | <50ms/batch |
| ML Models (Triton) | DGA, Phishing, UEBA, cyBERT | <10ms/batch |
| Threat Intel Join | IP/domain/hash IOCs | <5ms/batch |

## Quick Start

```bash
pip install -r requirements.txt
python -m cusplunk.detect --config config.yaml
```

## Config

```yaml
sigma:
  rules_path: /etc/cusplunk/sigma/
  reload_interval_seconds: 60

triton:
  url: localhost:8001
  models:
    - name: dga_detector
      version: 1
    - name: cybert
      version: 2

threat_intel:
  feeds:
    - name: alientvault_otx
      url: ${OTX_FEED_URL}
      refresh_hours: 1
    - name: abuse_ch
      url: https://feodotracker.abuse.ch/downloads/ipblocklist.json
      refresh_hours: 6

alerts:
  dedup_window_minutes: 5
  outputs:
    - type: webhook
      url: ${ALERT_WEBHOOK_URL}
```

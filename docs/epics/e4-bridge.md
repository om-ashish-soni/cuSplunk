# E4 — BRIDGE: 90-Day Splunk Federation Layer

**Owner:** P1  
**Service:** `services/bridge/` (Go)  
**Milestone:** M2  
**Status:** Planning

## Goal

Zero-downtime cutover from Splunk to cuSplunk. Enterprise runs both for up to 90 days. Queries transparently fan out to both. Bridge auto-expires. **Customers say "we forgot we were running both."**

## Stories

### S4.1 — Splunk REST Client
- Authenticated HTTP client to existing Splunk instance
- Submit SPL via `POST /services/search/jobs`
- Poll for completion: `GET /services/search/jobs/{sid}`
- Fetch results: `GET /services/search/jobs/{sid}/results`
- Support Splunk token auth + username/password
- Retry with exponential backoff on 429/503

### S4.2 — Time-Range Query Router
```
Parse time range from every incoming SPL query
    │
    ├─ Entirely after cutover_date → GPU store only
    ├─ Entirely before cutover_date → Splunk only
    └─ Spanning cutover_date → fan out to both
```
- `cutover_date` from bridge config
- Handles `earliest`, `latest`, relative times (`-7d@d`, `now`)
- All routing decisions logged for debugging

### S4.3 — Result Merger
When query spans both backends:
- Execute both in parallel (goroutines)
- Stream results from each backend as they arrive
- Merge by `_time` ascending (merge sort)
- Dedup: drop events where `hash(_time + _raw)` already seen
- Preserve all Splunk fields (`_indextime`, `_serial`, etc.)

### S4.4 — Bridge Configuration
`bridge/config.yaml`:
```yaml
splunk:
  url: https://splunk-host:8089
  token: ${SPLUNK_TOKEN}
  timeout: 300s
  verify_tls: true

cutover_date: "2025-06-01T00:00:00Z"
auto_sunset_days: 90

routing:
  force_gpu_after: ""       # override: always use GPU after this date
  force_splunk_before: ""   # override: always use Splunk before this date
```

### S4.5 — Migration Progress Dashboard
Admin page: `/admin/bridge`
- Days since cutover
- % of 90-day retention window now in GPU store
- Per-index migration status
- Query split ratio (GPU vs Splunk) over time (chart)
- Estimated Splunk shutdown date

### S4.6 — Auto-Sunset
- Day 90+: bridge disabled automatically
- All queries route to GPU store only
- Admin alert: "Splunk bridge decommissioned. Safe to shut down Splunk."
- `cusplunk_bridge_active` metric drops to 0
- Config flag to extend: `auto_sunset_override: true`

### S4.7 — Splunk rawdata Bulk Export (Optional Accelerator)
For enterprises that want to decommission Splunk before 90 days:
- Script: `scripts/splunk-export.sh`
- Uses `splunk export search` to dump index to JSON
- Streams into cuSplunk HEC endpoint
- Progress tracking: events exported, GB transferred, ETA
- Acceptance criteria: 1 TB export completes without data loss

## Bridge Metrics

| Metric | Description |
|---|---|
| `cusplunk_bridge_active` | 1 = active, 0 = sunset |
| `cusplunk_bridge_splunk_queries_total` | Queries routed to Splunk |
| `cusplunk_bridge_gpu_queries_total` | Queries routed to GPU |
| `cusplunk_bridge_fanout_queries_total` | Queries fanned to both |
| `cusplunk_bridge_splunk_latency_ms` | Splunk query latency histogram |
| `cusplunk_bridge_days_until_sunset` | Countdown gauge |

## Acceptance Criteria

- [ ] A query spanning cutover date returns correct merged results
- [ ] Results from GPU store and Splunk are deduped correctly
- [ ] Auto-sunset fires at exactly day 90 (configurable)
- [ ] Migration dashboard shows accurate progress
- [ ] Bulk export script handles 1 TB without errors

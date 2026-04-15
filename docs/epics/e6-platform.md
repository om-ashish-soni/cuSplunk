# E6 — PLATFORM: Splunk-Familiar UI + API

**Owner:** P4  
**Service:** `ui/` (React + Next.js), `services/api/` (Go)  
**Milestone:** M4  
**Status:** Planning

## Goal

A SOC analyst sits down, sees Splunk. Searches faster. Learns nothing new. Splunk-compatible REST API means existing automation scripts work without changes.

## Stories

### S6.1 — SPL Search Bar
- Monaco Editor with SPL syntax highlighting
- Real-time autocomplete: field names, commands, macros, index names
- Time range picker: relative (last 15m, 1h, 24h, 7d, 30d, 90d) + absolute
- Search history (last 50 searches per user)
- Save search button

### S6.2 — Results Table
- Paginated event viewer (virtual scroll, 10,000 rows without lag)
- Field extraction sidebar: click field name → auto-filter
- Click any value → `field="value"` appended to SPL
- JSON expand/collapse for structured fields
- Download results: CSV, JSON, XML (Splunk-compatible)
- Column picker: show/hide fields

### S6.3 — Dashboard Builder
- Drag-and-drop panel layout
- Panel types: timechart, bar, pie, single value, table, geo map, heatmap
- Each panel = saved SPL + visualization config
- Auto-refresh: 30s, 1m, 5m, off
- Dashboard sharing: URL-based, embed iframe
- Export to PDF

### S6.4 — Saved Searches + Scheduled Alerts
- Save any SPL as named search
- Schedule: cron expression or relative (every 5m, every 1h)
- Alert conditions: `results > 0`, `count > threshold`, `field comparison`
- Throttle: max 1 alert per N minutes per entity
- Alert actions: see E5 integrations

### S6.5 — Case Management
- Alert → Create Case (one click)
- Case fields: title, severity, assignee, status, MITRE technique, affected assets
- Case timeline: ordered events, comments, status changes
- Evidence: attach SPL searches, screenshots, file uploads
- Case export: PDF report

### S6.6 — User Management + RBAC
Roles:
| Role | Can do |
|---|---|
| Admin | Everything + user management + config |
| Power User | Search all indexes, create dashboards, manage saved searches |
| User | Search assigned indexes, view dashboards |
| Read Only | View dashboards only, no search |

- Local user accounts (bcrypt passwords)
- LDAP/AD integration (basic, full in E7)
- API tokens per user (for automation)

### S6.7 — REST API (Splunk-Compatible)
All Splunk SDK clients work unchanged:

```
POST   /services/search/jobs                     # create search job
GET    /services/search/jobs/{sid}               # job status
GET    /services/search/jobs/{sid}/results       # fetch results
DELETE /services/search/jobs/{sid}               # cancel job
GET    /services/data/indexes                    # list indexes
POST   /services/data/indexes                    # create index
GET    /services/saved/searches                  # list saved searches
POST   /services/saved/searches                  # create saved search
GET    /services/search/timeparser               # parse time string
```

Response format: identical to Splunk 9.x JSON responses.

### S6.8 — Index Management UI
- List all indexes with: event count, size, last event time, retention policy
- Create/delete indexes
- Set retention per index
- Per-index search restriction (for multi-team environments)

### S6.9 — System Health Dashboard
- Ingest rate (events/sec, GB/hr) — live chart
- GPU utilization across nodes
- Storage usage: hot / warm / cold breakdown per index
- Active searches count
- Detection engine: rules loaded, alerts/hr
- Bridge status + migration progress (while active)

## UI Tech Stack

- React 18 + Next.js 14 (App Router)
- TypeScript
- Monaco Editor (SPL syntax highlighting)
- ECharts (visualization)
- TailwindCSS (styling — Splunk color palette)
- SWR (data fetching + cache)
- Zustand (state management)

## API Tech Stack

- Go (Gin HTTP framework)
- gRPC clients to internal services
- JWT authentication
- OpenAPI 3.0 spec (auto-generated)
- Rate limiting: 100 req/min per user

## Acceptance Criteria

- [ ] Splunk Python SDK `client.jobs.create()` works against cuSplunk API
- [ ] Existing Splunk dashboard JSON can be imported
- [ ] SPL autocomplete covers all standard commands
- [ ] 100 concurrent dashboard users with <500ms load time

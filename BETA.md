# cuSplunk — Beta Testing Strategy

## Beta Philosophy

We are replacing Splunk in enterprise SOC environments. The bar is:
1. **Zero data loss** — ever
2. **SPL compatibility** — existing searches just work
3. **Faster than Splunk** — provably, on their own data
4. **Boring reliable** — nobody wants exciting infrastructure

Beta is not a soft launch. It is a controlled technical validation with real enterprise data and real SOC workflows.

---

## Beta Phases

```
Alpha (internal)      Private Beta          Public Beta           GA
M1 → M3               M3 → M5               M5 → M6               M6+
Team only             5-10 companies        50-100 companies      Open
                      NDA + contract        Waitlist              Paid
                      Free                  Free or pilot pricing  Full pricing
```

---

## Phase 0: Alpha (Internal) — M1 to M3

**Who:** Team of 4 only  
**Goal:** Validate core assumptions before touching customer data

### Alpha Checklist
- [ ] 1M events/sec ingest sustained for 1 hour
- [ ] 10 SPL queries from golden corpus return correct results
- [ ] S2S protocol accepts real Universal Forwarder (test with Splunk lab)
- [ ] Bridge correctly merges results from Splunk + GPU store
- [ ] Zero data loss after simulated node failure
- [ ] GPU memory stable (no OOM) after 24h continuous ingest
- [ ] Docker Compose setup works fresh on team member's machine in <30 min

**Duration:** Until M3 complete (detection engine working)  
**Exit criteria:** All alpha checklist items green, no P0 bugs open

---

## Phase 1: Private Beta — M3 to M5

**Target:** 5–10 enterprise SOC teams  
**Duration:** 90 days (exactly one retention cycle — deliberate)  
**Agreement:** NDA + beta agreement, data stays on their infra, we get telemetry

### Beta Customer Profile

Ideal beta customer:
- SOC team of 5-50 analysts
- Currently running Splunk Enterprise (not Splunk Cloud — need indexer access)
- Pain: Splunk cost or search performance
- Technical: has a DevOps/Platform engineer who can deploy Docker/K8s
- Willing to run cuSplunk alongside Splunk for 90 days
- Willing to give weekly feedback (30 min call)

**Disqualified:** Splunk Cloud customers (no access to indexers), teams without GPU hardware access, highly regulated environments (wait for E7 compliance features)

### Beta Customer Recruitment

| Channel | Action |
|---|---|
| LinkedIn | Post benchmarks ("we're 45× faster than Splunk, DM for beta access") |
| Twitter/X | Tweet benchmark results, link to repo |
| Hacker News | "Show HN: cuSplunk — GPU-native Splunk replacement" when M1 ships |
| DEF CON / Black Hat | Demo at booth or talk (if accepted) |
| Splunk Community | Post benchmarks in community forum |
| Direct outreach | Find Splunk admins complaining about cost on Reddit/HN/Twitter |
| ClickBench listing | Submit results → traffic from DB engineers |

**Target:** 20 applications → 5-10 selected (quality over quantity for private beta)

### Beta Onboarding (Per Customer)

**Week 1:**
- Deploy call (2 hours): install cuSplunk alongside their Splunk, configure bridge
- Verify: Universal Forwarders routing to cuSplunk, bridge working, first queries run

**Week 2-12:**
- Run alongside Splunk (dual-write, bridge active)
- Customer uses cuSplunk for new searches, validates results match Splunk
- Weekly 30-min check-in call

**Week 13 (Day 90):**
- Bridge auto-sunsets
- Customer officially on cuSplunk only
- Decision point: continue (pay) or roll back to Splunk

### Beta Success Metrics (per customer)

| Metric | Target |
|---|---|
| Onboarding time (deploy to first search) | <4 hours |
| SPL compatibility rate | >99% of their saved searches work |
| Query latency improvement vs Splunk | >10× on p50 |
| Ingest reliability | >99.99% events received |
| Zero data loss events | 0 |
| Alert latency (sigma rules) | <100ms |
| NPS at 90-day mark | >50 |
| Customer willing to pay | Primary success signal |

### Beta Infrastructure (We Provide)

- Dedicated Slack channel per customer (#beta-[company])
- GitHub Issues label for beta bugs: `beta-feedback`
- Weekly beta digest email (what we fixed, what's coming)
- On-call response: P0 bugs (data loss, ingest down) → 2-hour response SLA
- Rollback playbook: documented, tested, <30 min to full Splunk restore

### Beta Telemetry (Opt-in, Anonymized)

With customer consent, collect:
```json
{
  "ingest_events_per_day": 450000000,
  "query_count_per_day": 2847,
  "query_latency_p50_ms": 340,
  "query_latency_p95_ms": 2100,
  "gpu_utilization_avg_pct": 67,
  "spl_parse_error_count": 3,
  "sigma_alerts_per_day": 142,
  "storage_compression_ratio": 7.2,
  "cusplunk_version": "0.3.1"
}
```

No event data, no log content, no customer-identifiable fields.

---

## Phase 2: Public Beta — M5 to M6

**Target:** 50–100 companies  
**Access:** Waitlist, approved in batches of 20  
**Pricing:** Free for beta period, or pilot pricing ($X/GB/month, 50% off GA)

### Expanded Target Profiles
- Splunk Cloud customers (deploy cuSplunk for new data only, bridge via Splunk REST)
- MSSPs (Managed Security Service Providers) — high-volume, cost-sensitive
- Mid-market companies (50-500 employees, price-sensitive)
- Open-source enthusiasts (deploy on-prem, GPU cloud)

### Public Beta Requirements (vs Private Beta)
- [ ] Kubernetes operator working (self-serve deploy)
- [ ] Documentation site live (docs.cusplunk.io)
- [ ] Status page (status.cusplunk.io)
- [ ] Support portal (GitHub Discussions + paid tier email)
- [ ] Pricing calculator on website
- [ ] SOC2 Type II audit started

---

## Phase 3: GA Readiness Checklist

Before General Availability:

### Technical
- [ ] All 8 epics complete
- [ ] Zero P0 bugs from public beta
- [ ] Load test: 1,000 concurrent users sustained
- [ ] Chaos tests: all 7 scenarios pass gracefully
- [ ] SPL corpus: 100% parse rate, 100% golden match
- [ ] Benchmarks published and independently verified

### Business
- [ ] 3+ paying customers from private beta
- [ ] SOC2 Type II report in-hand (or in-progress)
- [ ] Pricing model finalized (GB/day ingested model, like Splunk)
- [ ] Support SLA documented (P0: 2hr, P1: 8hr, P2: 48hr)
- [ ] Splunk migration guide published

### Acquisition Readiness
- [ ] Clean IP: all NVIDIA tools used via open-source licenses (Apache 2.0 / BSD)
- [ ] No GPL dependencies in core services
- [ ] Customer list includes recognizable enterprise names
- [ ] Benchmark published on ClickBench — visible to DB engineering community
- [ ] GitHub stars > 2,000 (signals community traction)
- [ ] Blog post read by Cisco/Splunk engineers (target: HN front page)

---

## Beta Bug Triage

| Severity | Definition | Response SLA | Example |
|---|---|---|---|
| P0 | Data loss, ingest completely down | 2 hours | Events dropped, GPU crash |
| P1 | Core feature broken, no workaround | 8 hours | SPL query returns wrong results |
| P2 | Feature broken, workaround exists | 48 hours | Dashboard render error |
| P3 | Minor UX issue | Next sprint | Button alignment, typo |

**P0 protocol:** Page all 4 team members simultaneously, real-time incident channel, post-mortem within 48 hours.

---

## Beta Feedback Loops

**Weekly:** 30-min customer call → action items in GitHub Issues  
**Monthly:** Written survey (5 questions, NPS) → summarized in team retro  
**Ad-hoc:** Slack DM for urgent issues → triaged to P0-P3 within 4 hours  
**On close:** Exit interview (60 min) for any beta customer who churns  

Track in a simple spreadsheet:
- Customer, week #, NPS, top complaint, top praise, open P0/P1 count

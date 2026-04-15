# E7 — ENTERPRISE: Acquisition-Ready Features

**Owner:** All (P1–P4 contribute to their layer)  
**Milestone:** M5  
**Status:** Planning

## Goal

Pass enterprise security reviews. Get on Cisco's acquisition radar. Every feature in this epic is a line item on enterprise procurement checklists.

## Stories

### S7.1 — SSO: SAML 2.0 + OIDC
- SAML 2.0 SP implementation (Okta, Azure AD, Ping Identity, ADFS)
- OIDC client (Google Workspace, Azure AD, Auth0)
- JIT provisioning: auto-create user on first SSO login
- Group-to-role mapping: AD group → cuSplunk role
- Session timeout: configurable (default 8h)

### S7.2 — Multi-Tenancy
- Isolated index namespaces per tenant (data plane separation)
- Tenant-scoped API tokens
- Per-tenant resource quotas: max ingest GB/day, max search concurrency
- Billing metering per tenant
- Tenant admin role: manage users within tenant only

### S7.3 — Compliance Report Packs
Pre-built report packages:
- **PCI-DSS**: access to cardholder data, failed logins, privileged account usage
- **HIPAA**: PHI access logs, audit trail, unauthorized access attempts
- **SOC2 Type II**: system availability, change management, logical access
- **GDPR**: data access by EU subjects, deletion audit, consent logs
- **NIST CSF**: detection/response metrics mapped to CSF functions

Reports: scheduled PDF export, email delivery, retention in evidence store.

### S7.4 — Immutable Audit Log
- Every user action logged: searches run, dashboards viewed, config changes, logins
- Write-once storage: audit log entries cannot be deleted or modified
- Signed with HMAC chain (tamper evidence)
- Searchable via SPL: `index=_audit`
- Retention: configurable, default 365 days (separate from data retention)

### S7.5 — Data Masking + PII Redaction
- Rule-based field masking at ingest: `SSN`, `credit_card`, `email`, custom regex
- Masking happens before storage — original never written
- Role-based unmask: Admin can see original via privileged search
- GDPR right-to-erasure: targeted deletion of events containing specific PII values

### S7.6 — Kubernetes Operator
- Custom Resource: `CuSplunkCluster`
- `kubectl apply -f cusplunk-cluster.yaml` deploys full production cluster
- Handles: GPU node affinity, NVMe PVC provisioning, TLS cert rotation, rolling upgrades
- Helm chart for simple deployments
- Operator on OperatorHub

### S7.7 — Splunk API Compatibility Mode
Full drop-in for Splunk Python/Java/JS SDK:
- All Splunk 9.x API endpoints implemented
- Same JSON response schemas
- Same error codes
- Splunk `outputs.conf` forwarder config syntax parsed by bridge
- Test suite: run Splunk SDK test suite against cuSplunk, target 100% pass

### S7.8 — License + Usage Metering
- Track: GB ingested per day, per index, per tenant
- Usage dashboard: 30-day trend, projected month-end
- Overage alerts: email at 80% and 100% of licensed volume
- License enforcement: graceful throttle at limit (not hard stop)
- API: `GET /api/v1/license/usage`

### S7.9 — Encryption
- TLS 1.3 everywhere (ingest, API, internal gRPC)
- Data at rest: AES-256 for warm/cold tier
- Key management: HashiCorp Vault integration, AWS KMS, GCP KMS
- FIPS 140-2 compliant crypto mode (for US government)

### S7.10 — Network Security
- IP allowlist for API and ingest endpoints
- mTLS for internal service communication
- Network policy templates for Kubernetes
- Ingress rate limiting per source IP

## Enterprise Procurement Checklist

| Requirement | Status |
|---|---|
| SSO (SAML + OIDC) | S7.1 |
| MFA enforcement | Via SSO provider |
| RBAC | E6 + S7.2 |
| Audit logging | S7.4 |
| Data encryption at rest + in transit | S7.9 |
| PII masking | S7.5 |
| Compliance reports | S7.3 |
| Multi-tenancy | S7.2 |
| SLA: 99.9% uptime | E8 + S7.6 |
| Kubernetes native | S7.6 |
| Splunk migration path | E4 |
| Pen test report | External (post-M5) |

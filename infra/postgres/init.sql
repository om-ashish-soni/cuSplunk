-- cuSplunk metadata database schema
-- Applied automatically by PostgreSQL on first container start.

-- ── Users + auth ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT        NOT NULL UNIQUE,
    email       TEXT        NOT NULL UNIQUE,
    password_hash TEXT      NOT NULL,
    role        TEXT        NOT NULL DEFAULT 'user',  -- admin | power | user | readonly
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    last_used   TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes (Splunk equivalent) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS indexes (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,
    retention_days  INT         NOT NULL DEFAULT 90,
    max_size_gb     INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO indexes (name, retention_days) VALUES
    ('main',     90),
    ('_internal', 30),
    ('_audit',   365)
ON CONFLICT (name) DO NOTHING;

-- ── Saved searches ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS saved_searches (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        BIGINT      NOT NULL REFERENCES users(id),
    name            TEXT        NOT NULL,
    spl             TEXT        NOT NULL,
    cron_schedule   TEXT,
    alert_condition TEXT,
    alert_throttle_seconds INT  DEFAULT 300,
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, name)
);

-- ── Alerts ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    rule_id         TEXT        NOT NULL,
    rule_name       TEXT        NOT NULL,
    severity        TEXT        NOT NULL DEFAULT 'medium',  -- critical|high|medium|low|info
    status          TEXT        NOT NULL DEFAULT 'new',     -- new|assigned|investigating|resolved|false_positive
    assignee_id     BIGINT      REFERENCES users(id),
    mitre_tactic    TEXT,
    mitre_technique TEXT,
    mitre_technique_id TEXT,
    event_count     INT         NOT NULL DEFAULT 1,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_last_seen ON alerts(last_seen DESC);

-- ── Cases ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cases (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    description     TEXT,
    severity        TEXT        NOT NULL DEFAULT 'medium',
    status          TEXT        NOT NULL DEFAULT 'new',
    assignee_id     BIGINT      REFERENCES users(id),
    created_by      BIGINT      NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS case_comments (
    id          BIGSERIAL PRIMARY KEY,
    case_id     BIGINT      NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    author_id   BIGINT      NOT NULL REFERENCES users(id),
    body        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS case_evidence (
    id          BIGSERIAL PRIMARY KEY,
    case_id     BIGINT      NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    filename    TEXT        NOT NULL,
    mime_type   TEXT        NOT NULL,
    size_bytes  BIGINT      NOT NULL,
    storage_key TEXT        NOT NULL,
    uploaded_by BIGINT      NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Audit log (append-only, tamper-evident HMAC chain) ────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    BIGINT      REFERENCES users(id),
    actor_name  TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    resource    TEXT,
    detail      JSONB,
    ip_address  INET,
    prev_hash   TEXT,        -- SHA-256 of previous row
    row_hash    TEXT,        -- SHA-256(id || actor || action || prev_hash)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Revoke DELETE on audit_log so no row can be removed
REVOKE DELETE ON audit_log FROM PUBLIC;

-- ── Detection rules ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS detection_rules (
    id          BIGSERIAL PRIMARY KEY,
    rule_id     TEXT        NOT NULL UNIQUE,  -- Sigma rule id field
    name        TEXT        NOT NULL,
    type        TEXT        NOT NULL DEFAULT 'sigma',  -- sigma|yara|custom
    content     TEXT        NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
    hit_count   BIGINT      NOT NULL DEFAULT 0,
    fp_count    BIGINT      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Dashboards ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dashboards (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    BIGINT      NOT NULL REFERENCES users(id),
    name        TEXT        NOT NULL,
    definition  JSONB       NOT NULL DEFAULT '{}',
    is_shared   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, name)
);

-- ── Tenants (multi-tenancy, R5) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id              BIGSERIAL PRIMARY KEY,
    slug            TEXT        NOT NULL UNIQUE,
    display_name    TEXT        NOT NULL,
    quota_ingest_gb_day INT,
    quota_storage_gb    INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Default seed data for local dev
INSERT INTO users (username, email, password_hash, role)
VALUES ('admin', 'admin@cusplunk.local',
        -- bcrypt of "cusplunk_dev" — NOT for production
        '$2a$12$placeholder_bcrypt_hash_for_dev_only_replace_me_xxxx',
        'admin')
ON CONFLICT (username) DO NOTHING;

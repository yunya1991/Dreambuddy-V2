-- 001_init.sql — 45-评测系统 初始迁移（P0-2）
-- =============================================
-- 依据：SPEC v1.0 §12 数据模型（PostgreSQL）
-- 建表顺序遵循外键依赖：父表在前，子表在后
--   eval_requests → eval_runs → evidence / eval_items → eval_reports
--   eval_requests → callbacks；thresholds / registry_items 独立
-- 幂等：全部 CREATE TABLE/INDEX IF NOT EXISTS，可重复执行

-- 1) 受理与幂等（SPEC §12）
CREATE TABLE IF NOT EXISTS eval_requests (
    eval_id          TEXT PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    category         TEXT NOT NULL CHECK (category IN ('finance', 'ai', 'engineering')),
    object_type      TEXT NOT NULL CHECK (object_type IN ('strategy', 'model', 'service', 'code_artifact', 'dataset', 'knowledge')),
    purpose          TEXT NOT NULL CHECK (purpose IN ('l0_settle', 'deploy')),
    priority         TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high')),
    object_ref       TEXT NOT NULL,
    submitter        TEXT NOT NULL,
    env_manifest     JSONB NOT NULL,
    spec_id          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2) 不可变执行记录（SPEC §3.2 / §12）
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id            TEXT PRIMARY KEY,
    eval_id           TEXT NOT NULL REFERENCES eval_requests (eval_id) ON DELETE CASCADE,
    evaluator_id      TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    scorer_versions   JSONB,
    attempt           INTEGER NOT NULL DEFAULT 1,
    spec_hash         TEXT NOT NULL,
    code_commit       TEXT,
    env_snapshot      JSONB,
    budget_ms         INTEGER,
    degraded          BOOLEAN NOT NULL DEFAULT FALSE,
    started_at        TIMESTAMPTZ,
    ended_at          TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled', 'timeout'))
);

-- 3) 证据链（哈希链 prev_hash/hash，SPEC §2.1 / §12）
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES eval_runs (run_id) ON DELETE CASCADE,
    sha256       TEXT NOT NULL,
    uri          TEXT NOT NULL,
    prev_hash    TEXT,
    hash         TEXT NOT NULL UNIQUE,
    signed_by    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4) 评测项级结果（hard/weighted，SPEC §4 / §12）
CREATE TABLE IF NOT EXISTS eval_items (
    item_id     TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES eval_runs (run_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('hard', 'weighted')),
    score       DOUBLE PRECISION,
    n           INTEGER,
    ci_lower    DOUBLE PRECISION,
    ci_upper    DOUBLE PRECISION,
    weight      DOUBLE PRECISION,
    status      TEXT NOT NULL CHECK (status IN ('PASS', 'BLOCK', 'INCONCLUSIVE', 'SKIPPED')),
    evidence_id TEXT REFERENCES evidence (evidence_id),
    detail      JSONB
);

-- 5) 判定与报告（SPEC §4 / §12）
CREATE TABLE IF NOT EXISTS eval_reports (
    eval_id            TEXT PRIMARY KEY REFERENCES eval_requests (eval_id) ON DELETE CASCADE,
    run_id             TEXT NOT NULL REFERENCES eval_runs (run_id),
    verdict            TEXT NOT NULL CHECK (verdict IN ('PASS', 'BLOCK', 'INCONCLUSIVE')),
    score              DOUBLE PRECISION,
    n                  INTEGER,
    ci_lower           DOUBLE PRECISION,
    ci_upper           DOUBLE PRECISION,
    thresholds_version TEXT NOT NULL,
    baseline_run_id    TEXT,
    block_reasons      JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_uri         TEXT,
    report_sha256      TEXT,
    decided_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6) 阈值版本（SPEC §3.3 Threshold Registry / §12）
CREATE TABLE IF NOT EXISTS thresholds (
    version        TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('finance', 'ai', 'engineering')),
    item           TEXT NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    metric         TEXT NOT NULL,
    min_n          INTEGER NOT NULL DEFAULT 0,
    kind           TEXT NOT NULL DEFAULT 'weighted' CHECK (kind IN ('hard', 'weighted')),
    effective_from TIMESTAMPTZ NOT NULL,
    approved_by    TEXT NOT NULL,
    reason         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (version, category, item)
);

-- 7) 回调重试（SPEC §13.3 / §12）
CREATE TABLE IF NOT EXISTS callbacks (
    callback_id  TEXT PRIMARY KEY,
    eval_id      TEXT NOT NULL REFERENCES eval_requests (eval_id) ON DELETE CASCADE,
    target       TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'delivered', 'failed')),
    last_error   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8) Dataset/Evaluator/Scorer 注册（SPEC §3.3 / §12）
CREATE TABLE IF NOT EXISTS registry_items (
    reg_type     TEXT NOT NULL CHECK (reg_type IN ('dataset', 'evaluator', 'scorer', 'threshold')),
    item_id      TEXT NOT NULL,
    version      TEXT NOT NULL,
    manifest     JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (reg_type, item_id, version)
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_eval_requests_status ON eval_requests (status);
CREATE INDEX IF NOT EXISTS idx_eval_requests_submitter ON eval_requests (submitter);
CREATE INDEX IF NOT EXISTS idx_eval_requests_created_at ON eval_requests (created_at);
CREATE INDEX IF NOT EXISTS idx_eval_runs_eval_id ON eval_runs (eval_id);
CREATE INDEX IF NOT EXISTS idx_eval_items_run_id ON eval_items (run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_run_id ON evidence (run_id);
CREATE INDEX IF NOT EXISTS idx_callbacks_eval_id ON callbacks (eval_id);
CREATE INDEX IF NOT EXISTS idx_callbacks_status ON callbacks (status);

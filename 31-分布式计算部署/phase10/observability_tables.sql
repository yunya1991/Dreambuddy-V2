-- ============================================================
-- Dreambuddy V2 — observability 三表（幂等）
-- 来源: 7-产物中台 prisma migration 20260928234204_add_observability_tables
-- 用途: etl-worker 将 events/{system}/*.jsonl 物化到 PostgreSQL
--       (dreamos_sessions / dreamos_spans / dsh_subagent_calls)
-- 说明: 不使用 prisma migrate —— 产物中台 PG 由 dream-universal-gateway 管理，
--       执行 migrate/db push 会触发 drift 冲突，故以裸 SQL 幂等建表。
-- 执行: docker exec -i dreambuddy-pg psql -U dreambuddy -d dreambuddy
-- ============================================================

CREATE TABLE IF NOT EXISTS public.dreamos_sessions (
    id bigserial NOT NULL,
    trace_id text NOT NULL,
    session_id text NOT NULL,
    graph_name text NOT NULL,
    status text NOT NULL,
    start_ts timestamp(3) without time zone NOT NULL,
    end_ts timestamp(3) without time zone,
    duration_ms integer,
    total_nodes integer,
    executed_nodes integer,
    budget_tokens integer,
    used_tokens integer,
    termination_reason text,
    extra jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    CONSTRAINT dreamos_sessions_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.dreamos_spans (
    id bigserial NOT NULL,
    trace_id text NOT NULL,
    span_id text NOT NULL,
    parent_span_id text,
    node_id text NOT NULL,
    node_type text NOT NULL,
    status text NOT NULL,
    start_ts timestamp(3) without time zone NOT NULL,
    end_ts timestamp(3) without time zone,
    duration_ms integer,
    allocated_tokens integer,
    used_tokens integer,
    confidence numeric(5,4),
    error_message text,
    meta jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT dreamos_spans_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.dsh_subagent_calls (
    id bigserial NOT NULL,
    trace_id text NOT NULL,
    subagent_type text NOT NULL,
    request_payload jsonb,
    response_payload jsonb,
    status text NOT NULL,
    duration_ms integer,
    error_message text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT dsh_subagent_calls_pkey PRIMARY KEY (id)
);

-- 索引（etl-worker ON CONFLICT 依赖唯一索引）
CREATE INDEX IF NOT EXISTS dreamos_sessions_trace_id_idx ON public.dreamos_sessions USING btree (trace_id);
CREATE INDEX IF NOT EXISTS dreamos_sessions_status_start_ts_idx ON public.dreamos_sessions USING btree (status, start_ts);
CREATE UNIQUE INDEX IF NOT EXISTS dreamos_sessions_trace_id_key ON public.dreamos_sessions USING btree (trace_id);
CREATE INDEX IF NOT EXISTS dreamos_spans_trace_id_idx ON public.dreamos_spans USING btree (trace_id);
CREATE INDEX IF NOT EXISTS dreamos_spans_node_id_status_idx ON public.dreamos_spans USING btree (node_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS dreamos_spans_trace_id_span_id_key ON public.dreamos_spans USING btree (trace_id, span_id);
CREATE INDEX IF NOT EXISTS dsh_subagent_calls_trace_id_idx ON public.dsh_subagent_calls USING btree (trace_id);
CREATE INDEX IF NOT EXISTS dsh_subagent_calls_subagent_type_status_idx ON public.dsh_subagent_calls USING btree (subagent_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS dsh_subagent_calls_trace_id_subagent_type_key ON public.dsh_subagent_calls USING btree (trace_id, subagent_type);

-- 外键: dreamos_spans.trace_id -> dreamos_sessions.trace_id（幂等）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dreamos_spans_trace_id_fkey') THEN
        ALTER TABLE ONLY public.dreamos_spans
            ADD CONSTRAINT dreamos_spans_trace_id_fkey
            FOREIGN KEY (trace_id) REFERENCES public.dreamos_sessions(trace_id)
            ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;

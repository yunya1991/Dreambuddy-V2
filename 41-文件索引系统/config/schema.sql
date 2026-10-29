-- schema.sql — 41-文件索引系统 PostgreSQL 索引库初始化脚本
-- 依据: SPEC-41-文件索引系统 v0.6 §4.1（存储层 PostgreSQL 迁移）
-- 用法: psql -U dreambuddy -d fis -f schema.sql
-- 说明: 全部 DDL 在单事务内执行，失败自动回滚（对齐 v0.6 事务化重建策略）

BEGIN;

-- meta 表：schema 版本与运行元信息（v0.4 闭环 C2）
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- files 表：L1 元数据索引（Evidence-First 来源证据）
CREATE TABLE IF NOT EXISTS files (
    id          BIGSERIAL PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,          -- 相对根目录路径（正斜杠分隔）
    type        TEXT NOT NULL,                 -- doc/report/strategy/memory/case/code
    mtime       DOUBLE PRECISION NOT NULL,     -- epoch 秒
    size        BIGINT NOT NULL,
    hash        TEXT,                          -- 内容哈希（对账用）
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_type ON files(type);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);

-- chunks 表：L2 语义分块（v0.5 闭环 A2，boundary_kind 字段）
CREATE TABLE IF NOT EXISTS chunks (
    id            BIGSERIAL PRIMARY KEY,
    file_id       BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    heading       TEXT,                        -- 所属标题（可空）
    position      INTEGER NOT NULL,            -- 块序号
    boundary_kind TEXT NOT NULL CHECK (boundary_kind IN ('heading','paragraph','window','code')),
    content       TEXT NOT NULL                -- 块原文（snippet 生成）
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);

-- tokens 表：倒排索引（token -> chunk）
CREATE TABLE IF NOT EXISTS tokens (
    token     TEXT NOT NULL,
    chunk_id  BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    positions INTEGER[] NOT NULL DEFAULT '{}', -- 命中位置（行号/字符偏移）
    tf        INTEGER NOT NULL DEFAULT 1       -- 词频
);
CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token);
CREATE INDEX IF NOT EXISTS idx_tokens_chunk ON tokens(chunk_id);

-- documents 表：文档级摘要信息
CREATE TABLE IF NOT EXISTS documents (
    file_id  BIGINT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    title    TEXT,
    summary  TEXT,
    lang     TEXT
);

-- 初始化 schema 版本（v0.6 起 PostgreSQL 存储）
INSERT INTO meta(key, value) VALUES ('schema_version', '0.6')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

COMMIT;

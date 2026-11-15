-- ============================================================================
-- 管理台写操作日志表 DDL（SPEC-7 §7）
-- 执行方：云端 DBA（唯一生产写入口），本地禁止执行
-- 硬约束：禁止 prisma migrate / db push（库存在 drift，见 VM-1791896024014）
-- 执行方式：
--   ssh 云端 → sudo -u luke psql -d <业务库> -f 20261115_admin_operation_logs.sql
-- 幂等：全部 IF NOT EXISTS，可重复执行
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS admin_operation_logs (
  id                TEXT PRIMARY KEY,
  "requestId"       TEXT NOT NULL,
  "idempotencyKey"  TEXT,
  nonce             TEXT,
  "actorUid"        TEXT NOT NULL,
  "actorRole"       TEXT NOT NULL,
  level             TEXT NOT NULL,
  action            TEXT NOT NULL,
  "targetType"      TEXT NOT NULL,
  "targetId"        TEXT NOT NULL,
  reason            TEXT,
  "beforeData"      JSONB,
  "afterData"       JSONB,
  diff              JSONB,
  status            TEXT NOT NULL DEFAULT 'PENDING_AUDIT',
  warnings          JSONB,
  "errorCode"       TEXT,
  "errorMessage"    TEXT,
  "approvalId"      TEXT,
  "auditHash"       TEXT,
  "snapshotPath"    TEXT,
  ip                TEXT,
  "userAgent"       TEXT,
  "createdAt"       TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "appliedAt"       TIMESTAMP(3),
  "rolledBackAt"    TIMESTAMP(3),
  "auditFlushedAt"  TIMESTAMP(3)
);

-- 唯一约束：requestId 全链路追踪；idempotencyKey 幂等回放；nonce 确认令牌一次性
CREATE UNIQUE INDEX IF NOT EXISTS admin_operation_logs_requestid_key
  ON admin_operation_logs ("requestId");
CREATE UNIQUE INDEX IF NOT EXISTS admin_operation_logs_idempotencykey_key
  ON admin_operation_logs ("idempotencyKey");
CREATE UNIQUE INDEX IF NOT EXISTS admin_operation_logs_nonce_key
  ON admin_operation_logs (nonce);

-- 查询索引：补偿扫描 / 对象追溯 / 操作者追溯
CREATE INDEX IF NOT EXISTS admin_operation_logs_status_createdat_idx
  ON admin_operation_logs (status, "createdAt");
CREATE INDEX IF NOT EXISTS admin_operation_logs_targettype_targetid_idx
  ON admin_operation_logs ("targetType", "targetId");
CREATE INDEX IF NOT EXISTS admin_operation_logs_actoruid_createdat_idx
  ON admin_operation_logs ("actorUid", "createdAt");

COMMENT ON TABLE admin_operation_logs IS '管理台写操作日志（SPEC-7），180 天后归档';

COMMIT;

-- 回滚（仅在确认无数据依赖时执行）：
-- DROP TABLE IF EXISTS admin_operation_logs;

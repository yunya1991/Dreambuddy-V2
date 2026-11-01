-- 002_eval_items_kind_status.sql — eval_items 契约对齐（P0-5）
-- ==============================================================
-- 背景：报告契约 eval_report.v1.json 允许 kind=reference、status=TIMEOUT，
-- 001_init.sql 的 CHECK 仅含 hard/weighted 与 PASS/BLOCK/INCONCLUSIVE/SKIPPED，
-- 评测器落地（P2）插入 reference/TIMEOUT 项会被拒 —— 契约漂移修复。
-- 幂等：DROP CONSTRAINT IF EXISTS + 重建，可重复执行。

ALTER TABLE eval_items DROP CONSTRAINT IF EXISTS eval_items_kind_check;
ALTER TABLE eval_items ADD CONSTRAINT eval_items_kind_check
    CHECK (kind IN ('hard', 'weighted', 'reference'));

ALTER TABLE eval_items DROP CONSTRAINT IF EXISTS eval_items_status_check;
ALTER TABLE eval_items ADD CONSTRAINT eval_items_status_check
    CHECK (status IN ('PASS', 'BLOCK', 'INCONCLUSIVE', 'TIMEOUT', 'SKIPPED'));

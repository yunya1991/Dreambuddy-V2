# Evolution P0 Acceptance Checklist

## DoD Checklist

- [ ] candidate ingest 可入队并生成 Candidate 契约实例
- [ ] audit gate 可阻断字段/来源/证据链不合格候选
- [ ] sandbox gate 可阻断回归候选
- [ ] decision gate 仅全绿候选可批准
- [ ] promotion 前生成 rollback pointer
- [ ] 每个阶段输出结构化 ValidationReport
- [ ] artifacts 路径可追溯且与候选 ID 对齐

## Acceptance Procedure

1. 使用至少 1 条正样本候选跑通 `C0 -> C7`
2. 使用至少 1 条反样本候选触发 `C_FAIL`
3. 校验两条样本均存在完整 `evidence_refs`
4. 记录验收报告与结论（Go/No-Go）

## Latest Run

- `2026-05-11`：已完成 Day1 手工验收，报告见 `constraints/workflows-spec/evolution-p0-acceptance-report-2026-05-11.md`。
- `2026-05-12`：已完成 Day2 自动化验收，报告见 `constraints/workflows-spec/evolution-p0-acceptance-report-2026-05-12.md`。
- `2026-05-12`：已完成 P1 多门禁聚合验收，报告见 `constraints/workflows-spec/evolution-p1-acceptance-report-2026-05-12.md`。

# 待终审：R8 终审权归云端（SPEC v2.1）

> 状态：`pending`（等待云端终审）
> 依据：[SPEC-dual-end-collab-governance.md](../docs/tech/SPEC-dual-end-collab-governance.md) §3.3 R8 / §5.1 / §5.2 / §八.7
> 起草端：local · 起草日期：2026-10-30

## 待终审内容

1. `review/approved/` 仅允许 `end=cloud` 的 `review` 租约；本地申请或把文档推进到 `approved/` 一律 `exit 2`。
2. 两条文档同步路径的终审都发生在云端（本地只出 `review/feedback/` 意见）。
3. 落地证据：`lease.py` R8 判定 + `test_lease.py` 17 项单测通过；`lease-guard.yml` PR 门禁。

## 云端终审清单

- [ ] D1 代码一致性：云端 HEAD == origin/main
- [ ] D4 数据链路：文档结论与实际链路字段契约一致
- [ ] D5 模型质量：涉及模型结论有当次 D5 报告支撑
- [ ] D6 风控行为：涉及风控结论与实际日志一致
- [ ] 终审结论写入 `review/feedback/YYYY-MM-DD-<slug>-review.md`，通过后由云端移入 `review/approved/`

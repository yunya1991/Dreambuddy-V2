# CHANGELOG — 52-LobeHub 协议集成

> **版本**: v1.0.0（对应 52 模块 v0.11.0） | **更新日期**: 2026-11-11
> 格式：按版本倒序；日期为本地决策/落地日期。
> 版本以 `SPEC.md` 头部版本号为准；本文件只记录**已落地**的变更。

---

## v0.11.0 — 2026-11-11（ADR-001 实盘出关 + 蒸馏桥常态运转 + T1 跨侧 + 本地守护）

### 新增（ADR-001 脑暴出关）

- `orchestrator/live_policy.py`：三道门（策略 / 角色 / 自然周预算）+ append-only 账本；
  策略缺失或损坏一律返回「关闭」，绝不隐式开启实盘。
- `orchestrator/live_policy.json`：灰度策略 `enabled=true / allowed_roles=[auditor] /
  allowed_routes=[workers,debate] / max_per_week=1`。
- `brainstorm_orchestrator.py`：`shadow=False` 走实盘分支——先过三道门（未过 `PermissionError`，
  CLI exit 2），仅对 `decision.kind=dispatch` 的胜方卡调用 `executor(card)`；执行异常降级为
  `execution.error` 不中断；成功与失败都记账（失败也占预算）。
- `decisions/ADR-001-脑暴出关.md`：方案对比、PoE 自评 0.79、灰度阶梯 S1-S3、回滚方式。
- CLI 新增 `--role / --executor-module / --live-policy / --live-ledger`。

### 新增（桥与调度）

- `bridge/distill_bridge.py`：内容指纹去重（`.seen`，sha1；归一化抹去 `plancard=\S+` 与
  `score=[\d.]+`），跨批次不重复蒸馏同一意图；新增 CLI `--seen`、`--no-dedupe`。
- `orchestrator/scoring.py`：T1 改为**跨侧最佳分差**判定（`basis=cross_side`），单侧退回 Top2
  （`basis=top2`）；避免同侧 variant 恒触发导致永不分派。
- `orchestrator/ops/supervisor.py`：每日守护（默认 22:30，pidfile，SIGTERM 优雅退出），
  作为 launchd 被 macOS TCC 拦截时的本地替代。
- `orchestrator/ops/daily_pipeline.sh`：shadow → bridge 串联，双 rc 记账到 `logs/pipeline.log`。
- `bridge/ops/com.dreambuddy.bridge.plist`、`orchestrator/ops/com.dreambuddy.shadow.plist`：
  launchd 模板（本机不可用，仅备用）。
- `docs/` 五文档标准补齐：`ENGINEERING_INDEX.md`、`TECHNICAL_DESIGN.md`、`API_SPEC.md`、
  `CHANGELOG.md`，根目录 `README.md`。

### 变更

- `orchestrator/tests/test_brainstorm.py`：新增 T1 跨侧三例
  （`test_t1_uses_cross_side_gap_not_global_top2` / `test_t1_fires_on_close_cross_side_scores` /
  `test_t1_falls_back_to_top2_on_single_side`）。
- `bridge/test_distill_bridge.py`：新增跨批次去重用例（3 条含 1 重复 → `written=2, skipped=1`；
  游标回退重跑 → `written=0, skipped=3`）。
- `.gitignore`：orchestrator 忽略 `traces/ logs/ .supervisor.pid`；bridge 忽略
  `outbox.jsonl .cursor .seen logs/`。

### 验证

- 积压 88 条：`written=52 / skipped=36 / errors=0`，`.cursor=89`。
- 复跑 shadow：`T1 gap=0.155/0.182 → dispatch`，outbox 新增 6 条被桥全部消费。
- 回归：orchestrator 84 passed、bridge 20 passed、debate 壳 22 passed；ruff/black 通过。
- 认知回流：`recall` 命中 `source=protocol-bridge`。

---

## v0.10.0 — 2026-11-11（side-B 同量级结构扣分）

- `orchestrator/domain_eval.py`：`_evidence_raw()` 排除 `dreamos.*` 自证引用，仅外部取证计分。
- `orchestrator/proposers.py`：`_enrich_side_b_card()` 注入 3 条可证伪的规划器局限
  （`deterministic_planner_no_independent_evidence` / `registry_mapping_unvalidated` /
  `single_intent_call_no_variant_diversity`），已有人工 risk 不覆盖。
- 效果：side-B 由恒 `1.0` 降至约 `0.736`，与 side-A 可比；Top2 回归同侧 A vs A（gap 0.027）。

---

## v0.9.0 — 2026-11-11（Phase 5：45 域评测器适配层）

- 新增 `orchestrator/domain_eval.py`：`discover()` 隔离导入 45 评测 registry（fail-open），
  `DOMAIN_MAP` 三域映射，`evaluate_plan()` 四类 `INCONCLUSIVE` 原因，缺产物绝不编造分数。
- 新增 `structural_score()`：六维确定性结构分（权重和 1.10，归一化防饱和），替代退化常数。
- `scoring.score()`：结构分叠加 45 verdict（BLOCK→0 / PASS→+0.05 / INCONCLUSIVE→仅 base），
  新增 `evaluator_provenance`。
- 候选池新增同侧结构指纹去重（`dedupe_pool`），跨侧不合并。

---

## v0.6.1 — 2026-11-11（"唯一前端"澄清）

- 明确删除第二 UI（`src/app/agent/page.tsx`），保留协议层能力件
  `src/lib/agent/{providers,mcp-client,distill-outbox,plancard}.ts` 与 `api/agent/{chat,plan}`。
- 远端 `360e1f78dd` 误回退 SPEC（删脑暴章节）作废，以本地为准。

---

## v0.5.0 — 2026-11-11（内置协议层定案）

- 弃用 LobeHub desktop/server/docker 等独立应用形态；52 定位改为 3.1 前端内置协议层。
- 决策：不 fork、不 vendor 上游源码（其包均 `private: true`），只做协议语义对齐。
- Phase 0 PoC：三模型（kimi / sonnet / opus）经同一 stdio 链路调通 `recall`；写门禁正确拒绝。

---

## v0.3.1 — 2026-11-11（成熟实践对标）

- 新增铁律⑤（多样性契约化，fail-closed）、⑥（任务类型分流）、⑦（结构化产物交接）。
- 依据：Anthropic Building Effective Agents、arXiv《More Debate, Same Evidence》。

---

## v0.3.0 — 2026-11-11（双链协作定案）

- 用户确认 D5：统一入口 → 双链意图规划 → Debate → 评估器裁决 → 分工 → L0 沉淀 → 涌现回流。
- 新增四条修正铁律①-④（评估器裁决 / 竞争限规划层 / 门禁监督 / live 永禁）。
- 新增评审决议 R1-R9 与 `schemas/plancard.schema.json`。

---

## v0.2.0 — 2026-11-11（SPEC 初稿 + 架构评审）

- 形成 Phase 0-5 路线、集成契约、数据边界、风险对策、验收标准 A1-A6。
- 完成 GitHub 调研与代码架构评审：`REVIEW-20261111-LobeHub代码架构调研与SPEC评审.md`。

---

## v0.1.0 — 2026-11-11（立项）

- 新建 `52-lobehub协议集成`，明确其为叠加层而非主骨架，唯一接口 = MCP。

---

## 未发布 / 待落地

| 项 | 状态 | 说明 |
|---|---|---|
| Phase 2 云端部署 | 未开工 | l0_gateway SSE/HTTP 封装；44-三端协作登记 52 拓扑 |
| 45 真实产物评测 | 待接入 | 需 `artifacts/inputs/{run_id}.json` 领域对象映射 |
| 定时跨重启 | 受限 | macOS TCC 拦截 launchd/crontab；现用 `ops/supervisor.py` |
| T2-T4 真实触发样本 | 待积累 | 现有 trace 以 T1 跨侧判定为主 |

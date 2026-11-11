# ENGINEERING INDEX — 52-LobeHub 协议集成

> **版本**: v1.1.0（对应 52 模块 v0.12.0） | **更新日期**: 2026-11-11
> 状态：协议层 / 蒸馏桥 / 脑暴编排器已落地；Phase 2 云端部署待开工

---

## 1. 模块定位

| 项 | 内容 |
|---|---|
| 模块编号 | 52 |
| 模块名 | LobeHub 协议集成（Agent 前台与模型路由叠加层） |
| 层级 | 叠加层（非主骨架） |
| 唯一职责 | 以 MCP 唯一接口，把任意 LLM 的规划/脑暴能力接到既有 L0 能力面 |
| 不是 | 主骨架 / 能力实现层 / 认知记忆库 / 交易系统 / 第二套前端 |
| 上游 | 47-MCP 管理系统（L0 能力面唯一事实源）、46-DSH 架构 |
| 下游 | DreamOS/SACG 编排（唯一执行体）、33-REA / 48-涌现（反思回流） |
| 外部依赖 | `lobehub/lobehub`（仅协议对齐，不 fork、不 vendor、不部署） |
| 运行时依赖 | Python 3.10+ 标准库；`yaml` 可选（缺失走正则解析 registry） |

---

## 2. 文件地图

| 路径 | 职责 | 状态 |
|---|---|---|
| `SPEC.md` | 协议层 SSoT：定位/决策/阶段/契约/风险/验收 | 已建（v0.12.0） |
| `README.md` | 使用说明、目录、环境变量、已知限制 | 已建 |
| `REVIEW-20261111-...md` | GitHub 调研 + SPEC 评审 R1-R9 | 已建 |
| `decisions/ADR-001-脑暴出关.md` | shadow → 限量实盘（live）出关决策 | 已采纳（灰度） |
| `schemas/plancard.schema.json` | PlanCard JSON Schema（R8） | 已建 |
| `docs/ENGINEERING_INDEX.md` | 本文件 | 已建 |
| `docs/TECHNICAL_DESIGN.md` | 进程模型、门禁评分、幂等、治理 | 已建 |
| `docs/API_SPEC.md` | CLI / PlanCard / outbox / HTTP / MCP 契约 | 已建 |
| `docs/CHANGELOG.md` | 版本变更 | 已建 |
| `orchestrator/brainstorm_orchestrator.py` | 主流程 `run()`、trace/outbox、live 执行、CLI（1024 行） | 已落地 |
| `orchestrator/proposers.py` | side-A（3.1 `/plan`）/ side-B（DreamOS intent）双链提案，N-per-side | 已落地 |
| `orchestrator/plancard.py` | PlanCard 校验、`from_dreamos_intent`、variant 链构造 | 已落地 |
| `orchestrator/registry_tools.py` | 47 `mcp_capabilities.yaml` 只读加载（yaml 优先，正则兜底） | 已落地 |
| `orchestrator/scoring.py` | 铁律⑤多样性校验、G1-G4 门禁、结构分、T1-T4 | 已落地 |
| `orchestrator/domain_eval.py` | 45 评测器发现与适配、`structural_score`、side-B 扣分 | 已落地 |
| `orchestrator/adjudicator.py` | grounded semantics 裁决器（shadow 并行 A/B，214 行） | 已落地 |
| `orchestrator/debate_client.py` | `agent.debate.mcp` stdio JSON-RPC 客户端 | 已落地 |
| `orchestrator/router.py` | 意图路由 `r9-v1`（五分流，纯确定性） | 已落地 |
| `orchestrator/live_policy.py` | 三道门 + 周预算账本（append-only JSONL） | 已落地 |
| `orchestrator/live_policy.json` | 默认策略：auditor / workers+debate / 每周 1 次 | 已落地 |
| `orchestrator/shadow_batch.py` | 批量 shadow 入口（服务未就绪静默跳过） | 已落地 |
| `orchestrator/ops/supervisor.py` | 每日守护（pidfile，默认 22:30） | 已落地 |
| `orchestrator/ops/daily_pipeline.sh` | shadow → bridge 串联，双 rc 记账 | 已落地 |
| `orchestrator/ops/com.dreambuddy.shadow.plist` | launchd 模板（本机 EIO，仅备用） | 模板 |
| `bridge/distill_bridge.py` | outbox → cognition record（R6 映射/游标/去重，383 行） | 已落地 |
| `bridge/test_distill_bridge.py` | 桥测试 20 例 | 已落地 |
| `bridge/ops/com.dreambuddy.bridge.plist` | launchd 模板（同上，仅备用） | 模板 |
| `orchestrator/tests/test_brainstorm.py` | 主流程 / 门禁 / T1 / live 用例 | 已落地 |
| `orchestrator/tests/test_router.py` | 五分流与优先序 | 已落地 |
| `orchestrator/tests/test_domain_eval.py` | 45 适配与结构分 | 已落地 |
| `orchestrator/tests/test_adjudicator.py` | grounded semantics 求解 | 已落地 |

3.1 前端侧（不属本目录，但为 52 的落点）：

| 路径 | 职责 |
|---|---|
| `3.1-FRONTEND/src/lib/agent/providers.ts` | Vercel AI SDK 模型工厂（任意 provider） |
| `3.1-FRONTEND/src/lib/agent/mcp-client.ts` | stdio MCP 客户端（l0_gateway） |
| `3.1-FRONTEND/src/lib/agent/plancard.ts` / `plan-variant.ts` | PlanCard 契约与变体提示 |
| `3.1-FRONTEND/src/lib/agent/distill-outbox.ts` | outbox 写入器 |
| `3.1-FRONTEND/src/app/api/agent/{chat,plan,brainstorm}/route.ts` | 聊天 / 规划 / 脑暴入口 |

---

## 3. 依赖图

```text
brainstorm_orchestrator.py
  ├─ router.py            （意图分流，先于候选池生成）
  ├─ proposers.py         （side-A HTTP / side-B HTTP）
  ├─ plancard.py ── schemas/plancard.schema.json
  ├─ registry_tools.py ── 47-MCP管理系统/registry/mcp_capabilities.yaml
  ├─ scoring.py ── domain_eval.py ── 45-评测系统/evaluators/registry
  ├─ adjudicator.py       （shadow 并行裁决）
  ├─ debate_client.py ── mcp_shells/debate_adversarial/server.py
  └─ live_policy.py ── live_policy.json + live_ledger.jsonl

shadow_batch.py ── subprocess ── brainstorm_orchestrator.py
ops/supervisor.py ── subprocess ── ops/daily_pipeline.sh
                                   ├─ shadow_batch.py
                                   └─ bridge/distill_bridge.py
                                          └─ 4-MEMORY/9-工具与接口/cognitive_mcp_server.py（stdio）
```

无反向依赖：52 不被任何交易热路径引用。

---

## 4. 测试矩阵

| 套件 | 用例数 | 覆盖点 |
|---|---|---|
| `orchestrator/tests/test_brainstorm.py` | 60 | 双链收集、去重、门禁（G4 三档含误伤回归）、评分、T1-T4、outbox、live 出关六例 |
| `orchestrator/tests/test_router.py` | 16 | `trade_deny / high_risk_human / debate / direct_answer / workers` 与优先序 |
| `orchestrator/tests/test_domain_eval.py` | 15 | 45 发现/映射/fail-open、结构分权重、side-B 扣分 |
| `orchestrator/tests/test_adjudicator.py` | 4 | grounded semantics 最小不动点、agree 记录 |
| 小计 | **95 passed** | `python3 -m pytest orchestrator/tests -q` |
| `bridge/test_distill_bridge.py` | **20 passed** | R6 映射、校验 fail-closed、游标续跑、内容指纹去重 |
| `mcp_shells/debate_adversarial` | **22 passed** | model 多样性拒绝、plancards 契约（跨模块回归） |

---

## 5. 数据流与产物

| 产物 | 位置 | 可提交 | 说明 |
|---|---|---|---|
| 脑暴 trace | `orchestrator/traces/brainstorm.jsonl` | 否（gitignore） | 每轮 route/gate/score/decision/adjudication |
| 蒸馏 outbox | `bridge/outbox.jsonl` | 否（gitignore） | 编排器写、桥消费（append-only） |
| 桥游标 | `bridge/.cursor` | 否 | 已消费行号 |
| 桥去重指纹 | `bridge/.seen` | 否 | 内容指纹（sha1） |
| 实盘预算账本 | `orchestrator/live_ledger.jsonl` | 否 | 成功与失败都占预算 |
| shadow 批次日志 | `orchestrator/logs/shadow_batch.log` | 否 | 每意图一行 JSON |
| 守护日志 | `orchestrator/logs/supervisor.log` | 否 | 启动/触发/退出 |

认知写入唯一出口：`bridge → cognition MCP 壳 record`（`source=protocol-bridge`）。

---

## 6. 运行入口速查

| 场景 | 命令 |
|---|---|
| 单次脑暴（shadow） | `python3 orchestrator/brainstorm_orchestrator.py --intent "..." --json-out` |
| 批量 shadow | `python3 orchestrator/shadow_batch.py --max 2 --n-per-side 2` |
| 桥消费一批 | `python3 bridge/distill_bridge.py --once` |
| 每日守护 | `nohup python3 orchestrator/ops/supervisor.py >> orchestrator/logs/supervisor.log 2>&1 &` |
| 3.1 入口 | `POST /api/agent/brainstorm`（ChatPanel「择优脑暴」开关） |
| 实盘（受控） | `--no-shadow --role auditor --executor-module ...`（ADR-001 三道门） |

---

## 7. 已知差距

| # | 差距 | 阻塞原因 | 后续入口 |
|---|---|---|---|
| 1 | Phase 2 云端部署未开工 | l0_gateway 需 SSE/HTTP 封装；44 未登记 52 拓扑 | 按 SPEC Phase 2 清单推进 |
| 2 | 45 真实评测未执行 | 规划期无 `artifacts/inputs/{run_id}.json` | 产物落盘格式冻结后替换 `artifact_not_evaluated` 分支 |
| 3 | 定时不跨重启 | macOS TCC 拦截 launchd/crontab | 有权限环境装 `ops/*.plist`，或每次登录重拉守护 |
| 4 | shadow 样本不足 | 需 2-4 周 trace 积累 | 用 `supervisor.py` 常态跑批 |
| 5 | T2-T4 真实触发样本少 | 现有 trace 以 T1 跨侧判定为主 | 增加 BLOCK 卡/证据冲突/用户显式辩论样本 |

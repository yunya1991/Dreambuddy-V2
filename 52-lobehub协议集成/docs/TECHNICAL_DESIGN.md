# TECHNICAL DESIGN — 52-LobeHub 协议集成

> **版本**: v1.1.0（对应 52 模块 v0.12.0） | **更新日期**: 2026-11-11
> 适用代码：`orchestrator/`、`bridge/`、`orchestrator/ops/`

---

## 1. 设计目标与约束

| 目标 | 落地方式 |
|---|---|
| 零侵入主骨架 | 编排器/桥全部放 52 目录，不改 DreamOS、DSH、L0 源码 |
| 协议唯一 | 与既有架构只通过 MCP 交互；无 DB 直连、无 Python 模块反向引用 |
| 确定性可审计 | 门禁、评分、路由、裁决全部确定性；LLM 只产生候选方案 |
| 认知写入可治理 | 只有蒸馏桥写认知库，且只经 L0 cognition 壳的 record |
| 失败不阻塞 | 提案/评测/召回任一环节失败均降级，不抛穿主流程 |

四条修正铁律（SPEC §7.2）在代码层的硬落点：

| 铁律 | 代码位置 | 表现形式 |
|---|---|---|
| ① 裁判是评估器 | `scoring.py::score`、`domain_eval.py` | 评分只读结构分与 45 verdict，不调 LLM |
| ② 竞争限定在规划层 | `brainstorm_orchestrator.py::run` | 只比较 PlanCard，不比较执行结果 |
| ③ 监督交确定性门禁 | `scoring.py::gate` | G1-G4 纯规则，败方只进 outbox 作负样本 |
| ④ live 交易永禁 | `gate` G3/G4、`router.py` | trade-exec 域工具与实盘 risk 直接 BLOCK；交易意图 `trade_deny` |
| ⑤ 多样性 fail-closed | `scoring.py::validate_diversity` | model 空/占位、跨侧同 model、同 evidence_path 一律拒绝开题 |

---

## 2. 进程与组件模型

```text
┌────────────────────────── 3.1-FRONTEND（唯一前端）──────────────────────────┐
│ ChatPanel「择优脑暴」 → POST /api/agent/brainstorm                          │
│ POST /api/agent/plan（side-A 规划，Vercel AI SDK + MCP）                    │
│ POST /api/agent/chat（普通对话，MCP 消费）                                   │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ HTTP
┌───────────────▼───────────────┐        ┌──────────────────────────────┐
│ orchestrator/（Python 进程）   │◀──────▶│ DreamOS POST /api/v1/intent  │
│  router → proposers → gate    │        │ （side-B 确定性意图引擎）     │
│  → score → triggers → trace   │        └──────────────────────────────┘
│  → outbox / debate / live     │
└───────┬───────────────┬───────┘
        │               │ stdio JSON-RPC
        │               ▼
        │      mcp_shells/debate_adversarial（Debate 壳）
        ▼
┌───────────────────────────────┐
│ bridge/distill_bridge.py      │  outbox.jsonl → cognition record
│ （独立进程，可 cron/守护触发）  │  只经 4-MEMORY/9-工具与接口/cognitive_mcp_server.py
└───────────────────────────────┘
```

- 编排器是**短时进程**：一次 `--intent` 跑完即退，不常驻（便于定时与超时控制）。
- 桥是**短时进程**：`--once` 处理一批即退，游标保证续跑。
- 调度由 `ops/supervisor.py`（常驻）或外部调度器提供，二者都不进入编排器主流程。

---

## 3. 主流程时序

```text
run(intent, n_per_side, shadow, force, ...)
 1. route(intent, risk_flags, intent_type)        # r9-v1 五分流
    ├─ trade_deny / high_risk_human → 仅写 trace，直接返回 skipped
    ├─ direct_answer              → 同上（省 token）
    ├─ workers                    → 单边（n_per_side 强制 1），T1-T4 只记录
    └─ debate                     → 继续；--force 可跳过路由
 2. collect_proposals(n_per_side)                 # 双链并行/顺序取卡
    ├─ side-A: N 次 POST /api/agent/plan（variant: focus/seed 轮转）
    └─ side-B: 1 次 POST /api/v1/intent，本地派生 N 个 variant
 3. dedupe_pool(cards)                            # card_id + 同侧结构指纹去重
 4. validate_diversity(proposals)                 # 铁律⑤，违规即终止开题
 5. gate(card, registry_view) × N                 # G1-G4
 6. score(card) × N                               # 结构分 + 45 域结果
 7. recall_via_mcp(intent)                        # T3 证据
 8. triggers(cards, gates, recall_hits, ...)      # T1-T4
 9. decision = escalate_debate | dispatch
    ├─ escalate_debate → debate_client.start_debate(...)（写败方/胜方证据）
    └─ dispatch        → shadow: executed=false，仅记意图
                          live : 过 live_policy 三道门后执行胜方卡
10. trace jsonl + outbox.jsonl（winner=B / loser=D）
11. （异步）bridge --once 消费 outbox → cognition record
```

一次 `run` 的稳定摘要字段见 `docs/API_SPEC.md` §3。

---

## 4. 门禁算法（G1-G4）

| 门禁 | 判据 | 结果 |
|---|---|---|
| G1 | PlanCard schema 校验（必填、类型、`id` 前缀 `pc-`、`intent ≤500`、`plan_steps ≥1`） | 任一不合规 → BLOCK |
| G2 | `plan_steps[].tool` 必须在 47 registry 的允许集内 | 未注册 → BLOCK |
| G3 | 工具所属壳 `domain == trade-exec` | 命中 → BLOCK（铁律④） |
| G4 | `risk_flags` 的实盘意图：执行动作 / 裸声明 / 无否定前缀的英文标识符 → BLOCK；风险描述或否定语境 → `notes` 放行（v0.12.0 起，真实护栏是 G3 + ADR-001） | 见右 |

BLOCK 卡不进入候选池排名（`score` 返回 0.0），但仍写 trace 供分析；T2 用其分数检测
"高分被拦"的治理冲突。

---

## 5. 评分算法

### 5.1 结构分（确定性，`domain_eval.structural_score`）

| 维度 | 权重 | 归一化口径 |
|---|---|---|
| tool 合法率 | 0.25 | 合法工具步数 / 总步数 |
| 步骤数 | 0.15 | `min(1, steps/6)` 阶梯 |
| validation | 0.20 | 有 `evaluator_refs` 或 `acceptance_checks` 计 1 |
| evidence_refs | 0.20 | **排除 `dreamos.*` 自证**，有效独立取证 ≥2 计满 |
| risk_flags | 0.20 | `max(0.4, 1-0.15n)`：有风险标注优于无标注 |
| cost_estimate | 0.10 | 显式 tokens/tool_calls 计 1 |

权重和 1.10，按总权重归一化，避免满分饱和；明细 `{name, raw, weight, contribution}` 全量入 trace。

### 5.2 域评测叠加（`scoring.score`）

```text
final = base                                   # INCONCLUSIVE
final = min(1, base + 0.05)                    # PASS
final = 0.0                                    # BLOCK
```

45 不可用（导入失败/未注册/缺 artifacts/产物未映射）→ `INCONCLUSIVE`，**绝不编造分数**；
`evaluator_provenance.source` 区分 `structural` 与 `45`。

### 5.3 side-B 同量级扣分

side-B 是确定性意图引擎，天然无独立取证。为使其与 side-A 可比：

- `_enrich_side_b_card()` 在 `risk_flags` 为空（或仅 `chain_unmapped`）时注入 3 条**可证伪的规划器局限**：
  `deterministic_planner_no_independent_evidence` / `registry_mapping_unvalidated` /
  `single_intent_call_no_variant_diversity`；已有人工 risk 时不覆盖。
- `_evidence_raw()` 不把 `dreamos.*` 自证计入独立取证。

效果：B 侧由 `1.0` 降至约 `0.736`；未来 B 侧接入独立取证后分数自动回升，无需改代码。

---

## 6. 争议触发器 T1-T4

| 触发器 | 判据 | 语义 |
|---|---|---|
| T1 | **跨侧最佳分差** `< 0.1`（两侧都有卡时）；单侧退回全局 Top1-Top2 | 方案难分优劣 → 升级 Debate |
| T2 | 存在 BLOCK 卡且其分数 > 可行卡最高分 | 治理与效用的冲突 → 升级 |
| T3 | recall 命中 D 级记忆，且其词元与任一 plan 文本有交集 | 历史反例冲突 → 升级 |
| T4 | 用户显式要求辩论（`--user-requested-debate`） | 人工指定 → 升级 |

T1 为什么必须跨侧：`--n-per-side ≥2` 时全局 Top1/Top2 常是同侧变体（同一规划器、同一证据基础，
天然只差 0.02-0.03），会导致 T1 恒命中、永远 `escalate_debate`、outbox 永不增长。
跨侧比较后实测 `gap=0.155/0.182`，恢复正常 `dispatch`。

`workers` 模式下 T1-T4 只记录不升级（`escalate` 被忽略）。

---

## 7. 幂等与去重

| 层 | 机制 | 保证 |
|---|---|---|
| 候选池 | `card_id` 去重 + 同侧结构指纹去重（跨侧不合并） | 同一侧重复 variant 不占用 Top 位 |
| trace | append-only，每轮独立 `run_id` | 可回放、可审计 |
| outbox | append-only，`source_ref = run_id:card_id` | 可追溯来源 |
| 桥游标 `.cursor` | 记录最后消费行号 | 不重读，跨批续跑 |
| 桥指纹 `.seen` | `sha1(content)`，抹去 `plancard=\S+` 与 `score=[\d.]+` | 不重写，跨批去重 |
| cognition | `external_id = bridge:{source_ref}` | 壳层幂等，同键单条 |

游标与指纹是两层不同保证：游标防"重复读"，指纹防"重复写"。游标回退或重跑时，
指纹仍能拦住同一意图的重复蒸馏（实测 88 条 → `written=52 / skipped=36`）。

---

## 8. 认知写入治理（R3）

- 桥是唯一写入方；工具白名单在代码层断言：`ALLOWED_TOOLS = {"record","verify"}`。
- 子进程仅覆写三个 env：`COGNITIVE_MCP_MODE=ssh`、`COGNITIVE_MCP_WRITE_ENABLED=true`、
  `COGNITIVE_MCP_DEFAULT_PRINCIPAL=orchestrator`；其余继承宿主环境。
- 桥不直连 `cognitive_memory.db`；无 SQLite 句柄、无 ORM。
- R6 质量映射（fail-closed，未知类型拒写）：

| outbox.type | quality | 用途 |
|---|---|---|
| `expertise_canon` | B | 上游已固化条目 |
| `expertise_candidate` | C | 待验证假设 |
| `debate_winner` / `brainstorm_winner` | B | 胜方方案 |
| `debate_loser` / `brainstorm_loser` | D | 反模式负样本 |
| `session_summary` | C | 高价值会话摘要 |

---

## 9. fail-open / fail-closed 矩阵

| 环节 | 异常 | 策略 |
|---|---|---|
| 45 发现与评测 | 导入失败 / 未注册 / 缺 artifacts | fail-open → `INCONCLUSIVE`，流程继续 |
| registry 加载 | yaml 缺失 | 正则兜底解析；仍失败则 G2 全拒（等价 fail-closed） |
| 提案 HTTP | 超时 / 非 200 / 非法 JSON | 该侧记 error，不整体失败；无卡则返回 `diversity_violations` 或空池 |
| recall 取证 | 壳不可用 | `recall_hits=None` → T3 `skipped` |
| Debate 壳 | 传输错误 | 记 `debate.error`，不阻断 trace/outbox |
| 桥校验 | 条目不合规 | 跳过该行并推进游标（毒丸不阻塞队列） |
| 桥传输 | stdio 错误 | 中止本批，游标停在最后成功行，下次续传 |
| 桥去重 | 指纹命中 | 跳过写入、推进游标，计 `skipped` |
| live 执行 | 门禁未过 | `PermissionError` → CLI exit 2 |
| live 执行器 | 运行异常 | 记 `execution.error`，不中断主流程；失败仍占预算 |

---

## 10. 实盘出关（ADR-001）

```text
shadow=False
  → live_policy.check_live_allowed(role, route, policy, ledger)
      ├─ enabled == false            → 拒绝
      ├─ role ∉ allowed_roles        → 拒绝
      ├─ route ∉ allowed_routes      → 拒绝
      └─ 本自然周记录数 ≥ max_per_week → 拒绝
  → 仅对 decision.kind == "dispatch" 的胜方卡调用 executor(card)
  → record_execution(...)   # 成功/失败都 append
```

默认 `live_policy.json`：`enabled=true`、`allowed_roles=["auditor"]`、
`allowed_routes=["workers","debate"]`、`max_per_week=1`。提额必须改 ADR。
边界：live 只执行 dispatch 胜方，**不执行 debate 结论**；交易域仍被 G3/G4 与路由阻断。

---

## 11. 调度设计

launchd 在本机 `bootstrap/load` 恒返回 `Input/output error (5)`（`/tmp` 路径同样失败，
判定为进程无 launchd 注册权限，非路径 TCC 问题），crontab 与产品 Schedule 不可用。
替代方案：

```text
ops/supervisor.py（常驻）
  ├─ pidfile ops/.supervisor.pid，重复启动直接退出
  ├─ next_run(hour=22, minute=30) 计算下一次触发
  ├─ subprocess.run(["bash", "ops/daily_pipeline.sh"])
  └─ SIGTERM/SIGINT 退出；每次跑完 sleep 61s 再排期

ops/daily_pipeline.sh
  ├─ shadow_batch.py --max 5 --n-per-side 2 >> logs/shadow_batch.cron.log
  ├─ distill_bridge.py --once        >> bridge/logs/bridge.cron.log
  └─ logs/pipeline.log 记 "时间 shadow_rc=… bridge_rc=…"
```

局限：不跨重启；机器重启后需重新 `nohup` 拉起（或改用有权限环境的 launchd）。

---

## 12. 扩展点

| 扩展 | 位置 | 方式 |
|---|---|---|
| 新增提案方（第三链） | `proposers.py::build_proposers` | 实现 `Proposer.propose()` 返回卡列表 |
| 新增门禁 G5+ | `scoring.py::gate` | 追加规则并同步 SPEC 铁律 |
| 接入 45 真实产物 | `domain_eval.py::evaluate_plan` | 替换 `artifact_not_evaluated` 分支 |
| 调整路由规则 | `router.py` + `ROUTE_RULES_VERSION` | 版本号随 trace 落盘，变更需评审 |
| 新增蒸馏类型 | `bridge/distill_bridge.py::R6_QUALITY_MAP` | 同步 SPEC §7.4 与测试 |
| 云端部署 | 新 SSE/HTTP 适配 | 保持 MCP 语义，前端只改连接方式 |

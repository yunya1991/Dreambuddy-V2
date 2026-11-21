# 架构总装与调度能力评测报告 v0.1

> 日期：2026-11-18 ｜ 范围：DreamOS SACG 总装（L0/L1/L2 18 壳）+ 调度链（P1/P1b/P2/P3）
> 依据：[SPEC-56-架构总装与调度能力评测-v0.1.md](../SPEC-56-架构总装与调度能力评测-v0.1.md)
> 证据：`evals/out/evidence.jsonl`、`coverage_matrix.json`、`baseline_comparison.json`、`acceptance.json`
> 复跑：`python3 evals/run_all.py`

---

## 1. 结论摘要

| 结论 | 证据 |
|---|---|
| **总装完整**：18 壳全部映射到场景；16 个 active 壳 100% 可拉起，`tools/list` 与 registry 零漂移 | P2 sweep：16/16 available，`list_mismatch=[]` |
| **读能力无死角**：81 个 active 工具中 70 个被真实调用命中（86.4%），**全部 70 个只读工具 100% 触达** | `coverage_matrix.json` `tool_coverage_ratio=0.864` |
| **写能力按设计隔离**：未触达的 11 个工具 **全部是 write/requires_mandate**，非能力缺失 | `uncovered_tools` 11 项均为 write |
| **调度链四入口均有实证**：产品链答题 7/7、bridge 8 场景、MCP stdio 16 壳、SACG in-process S→A→C→G 齐全 | `evidence.jsonl` |
| **编排相对单模型有结构性增益，但事实正确性不占优**：D1/D3/D4 系统 2.25/3.25/4.38 vs 基线 0/0/0；D2 系统 2.29 vs 基线 3.75 | `baseline_comparison.md` |
| **产品链存在意图级断路**：S2/S3/S7 返回 `S2_ANALYSIS 分析中` 占位模板，未调用已可用的 L0 工具 | 第 6 节 |
| **13 项机器验收：AC1/1b/2/4/5/5b/6/7 全过，AC3 为设计性 partial** | `acceptance.json` |

> 一句话：**“零件齐全、可被调度”，但“产品链的路由把部分意图接到了占位分支”**——这是当前最大的调度风险，而非能力缺失。

---

## 2. 方法与口径

| 入口 | 方式 | 证明什么 | 结果 |
|---|---|---|---|
| **P1 产品链** | `POST /api/task/stream`（3001） | 用户真实入口可答题 | 7/7 有返回；时延 p50 6.1s |
| **P1b bridge** | `dsh_frontend_bridge.call_tool` | 与产品同一 handler 链可调 | 8 场景，expected_tools 命中率 100% |
| **P2 MCP stdio** | 逐壳 `initialize → tools/list → tools/call` | 壳可用、工具契约一致 | 16/16 壳；70 只读工具实测 |
| **P3 SACG** | `SACGOrchestrator.handle`（in-process） | S→A→C→G 决策与门控 | 全阶段齐全，**未接入产品链** |

**排除规则**：mock/注入结果标 `simulated:true`（G 层认知分流注入 fake）；写链路使用 `DREAMBUDDY_COGNITIVE_DB=<tmp>` 隔离根；任何 stub 不计入真实触达。

---

## 3. 总装覆盖（静态 × 证据）

```
壳: 18（active 16 / deprecated 2 / 豁免 2）
工具: active 81，实测命中 70 → 86.4%（目标 70%）
场景: 18（抽样 10 / DeepSeek 基线 8）
```

- **壳级**：18/18 出现在覆盖映射；16 个 active 壳每个 ≥1 场景（AC1 PASS）。
- **工具级**：每个 active 壳 ≥1 工具被证据命中；整体 86.4%（AC1b PASS）。
- **未触达 11 个**（全部 write）：`cognition:record/verify`、`semantic:distill_aliases/training_feed`、`data:data_store_write`、`trade-exec:place_order/cancel_order/ingest_signal`、`trading:forward_signal`、`dreamos:submit_run`、`train:trigger_training`。
  - 其中 `cognition:record` 已在 S16 走通“有 Mandate → 落盘”完整写链路（AC5b PASS）。
- **注册缺口**：`mcp_shells/l1_stats/server.py` 已实现 4 工具但未注册（`l1.stats.mcp` 不在 registry）；已在 S15 标注为 `expected_unregistered`，P2 可直测。
- **唯一豁免**：`l0.rea-client.mcp`（deprecated、`shell_path` 为空、无实现）；`agent.debate.mcp`（deprecated，与 `l2.debate.mcp` 共用 server）。

---

## 4. 调度实证

### 4.1 产品链（P1）

7 个安全分析题全部有返回，trace_id 贯穿。典型：

- S1「BTC 现价」→ 真实行情（`$63,897.7`，链路 `market_query`），D2=5。
- S5「BTC 本周结构」→ 1082 字结构化回答，D2=5。
- S4「宏观与资金面是否矛盾」→ 给出“宏观偏鹰 vs 技术面超卖”主矛盾，但行情表为 `N/A`。

### 4.2 Bridge（P1b）

8 场景全部达到 `expected_tools` 命中率 100%，且每个场景至少 1 个非 health/stats 业务工具（AC2 PASS）。

### 4.3 MCP stdio（P2）

16 壳全部拉起、`tools/list` 与 registry 完全一致（无漂移）。**唯一异常**：`l0.cognition.health` 调用 12s 超时（1/70）。

### 4.4 SACG（P3）

- S4：`route=L2_HANDOFF`，`stages=[S,A,C,G]`，3 节点执行，G 层产出 case 沉淀。
- S11/S12：S 层充分性短路正确（`NEED_CLARIFY` / `EARLY_TERMINATE`），无下游节点。
- S15：G 四分流 `case / skill / doc / cognitive` 均可触发（AC4 PASS）。
- **重要边界**：SACG 目前**只被测试与 bench 引用，未接入 `/api/task/stream`**（D-2）。因此以上是“编排器可用”证据，不是“产品链在跑 SACG”证据。

---

## 5. 故障与门控

| 场景 | 注入 | 结果 |
|---|---|---|
| S13 超时 | 不可达 OKX base + 50ms 超时 | `degraded=true`，`data=null`，**不编造数值**（AC5） |
| S13b 鉴权 | `docs.search` 缺参降级代理 | `degraded=true`；未直连外部 Tavily |
| S14 并发 | 5 并发 `get_ticket_status` | 5/5 完成、无丢单；**但无并发上限配置**（发现 D-10） |
| S16 审批 | 无/有 Mandate | 无 → `forbidden` 且无落盘；有 → `memory_id` 落盘（AC5b） |
| C 层 REDO | 节点返回 `REDO` | 验收 `degraded` → doc 沉淀（AC5） |

---

## 6. 与 DeepSeek 单模型对比（8 题 × 六维，分列）

> 口径：D2 = `must_have_facts[].match` 关键词命中率 × 5（非 LLM 评审）；时延 n=1（非推断统计）；系统 token 用量产品链未暴露，记 `null`；DeepSeek 调用 8/40。

| 题 | D1 能力覆盖 sys/base | D2 正确性 sys/base | D3 调度 sys/base | D4 证据 sys/base | D5 时延分 sys/base | D6 token sys/base |
|---|---|---|---|---|---|---|
| S1 BTC 现价 | 2/0 | **5/2.5** | 3/0 | 5/0 | 5/5 | n/a/5 |
| S2 茅台财务 | 2/0 | 1.67/**5** | 3/0 | 5/0 | 4/5 | n/a/5 |
| S3 实体别名 | 2/0 | 0/**5** | 3/0 | 5/0 | 5/5 | n/a/5 |
| S4 矛盾识别 | 2/0 | 5/5 | **5**/0 | 5/0 | 4/5 | n/a/5 |
| S5 技术复盘 | 3/0 | **5**/2.5 | 3/0 | 5/0 | 3/5 | n/a/5 |
| S7 交易计划 | 2/0 | 1.67/**5** | 3/0 | 5/0 | 4/5 | n/a/5 |
| S10 案例入库 | 2/0 | 0/2.5 | 3/0 | 0/0 | n/a/5 | n/a/5 |
| S13 降级行情 | 3/0 | 0/2.5 | 3/0 | 5/0 | 5/5 | n/a/5 |
| **均值** | **2.25/0** | **2.29/3.75** | **3.25/0** | **4.38/0** | **4.14/5** | — |

**怎么读这张表**：

1. **D1/D3/D4 是结构性碾压**：单模型没有任何工具、路由与证据链，这不是模型能力问题，是架构有无问题。
2. **D2 系统落后，原因不是“模型笨”**：S2/S3/S7 的产品链回答是 `### S2_ANALYSIS 分析中...` 占位模板（详见 6.1），而 P1b 已证明 `semantic_lookup`、`data_store_read` 等工具**本身可调**。即：**能力在，路由没接上**。
3. **D5 时延**：系统 p50 6.1s vs 基线 2.0s；S5 达 23.3s。代价主要在多壳冷启动与串行取证，属可优化项。
4. **D6**：系统 token 成本无法从产品链观测（D-6），基线约 94–586 tokens/题。

### 6.1 关键发现：意图级断路

| 意图 | 产品链行为 | 应有行为 |
|---|---|---|
| 行情（S1） | ✅ `market_query` 真实行情 | — |
| 深度分析（S4/S5） | ✅ 生成分析（但 S4 行情表 `N/A`） | 数据应回填 |
| 财务/估值（S2） | ❌ 返回 `S2_ANALYSIS 分析中` 模板 | 调 `l0.data` + `l1.strategy` |
| 实体解析（S3） | ❌ 返回同类模板 | 调 `l0.semantic-39` |
| 交易计划（S7） | ❌ 返回同类模板 | 调 `l1.trading` + `l0.trade-exec` |

> 这是本次评测最重要的结论：**问题不在“有没有能力”，而在“意图到能力的路由表有空洞”**。

---

## 7. 同类项目逆向对照

| 机制 | 我们 | Dify | LangGraph | OpenAI Agents SDK |
|---|---|---|---|---|
| 工具/壳注册单一事实源 | ✅ 47 registry SSoT | ⚠️ 插件分散 | ❌ 代码即图 | ⚠️ 代码注册 |
| 工具级契约校验 | ✅ `tools/list` 强制派生 | ⚠️ | ❌ | ⚠️ |
| 逐节点重试/超时 | ⚠️ 壳层有，编排层无 | ✅ | ✅ | ⚠️ |
| 超步级 checkpoint | ❌ | ⚠️ | ✅ | ❌ |
| 审批票据（Mandate） | ✅ `mandate_gate` + H7 纵深 | ⚠️ 人工节点 | ⚠️ interrupt | ✅ approvals |
| 并发限流 | ❌（D-10） | ✅ | ⚠️ | ⚠️ |
| 运行时可观测（per-tool） | ⚠️ 壳层有，产品链无 | ✅ | ✅ | ✅ |

**结论**：我们的**注册与门禁**强于四个参照；**编排层弹性（重试/checkpoint/限流）**弱于 LangGraph/Dify。这与 SPEC §10 的预期一致，属下一步增强方向而非当前缺陷。

---

## 8. 能力死角清单（含豁免与理由）

| ID | 死角 | 严重度 | 证据 | 处置 |
|---|---|---|---|---|
| D-1 | 产品链只走 in-process handler，MCP 壳零触达 | 高 | P1 无法观测工具调用；P2 只能另测 | 需在 Node/DSH 侧加 per-tool 计数 |
| D-2 | SACG 未接入 `/api/task/stream` | 高 | 仅 tests/bench 引用 | 单独立项接入 |
| D-3 | Ticket 四模块默认全关 | 中 | `ticket_store.py` 默认 False | 评测时显式开启 |
| D-4 | `l1.stats.mcp` 已实现未注册；`l0.rea-client.mcp` 死壳 | 中 | registry 无 `l1.stats` | 补注册 / 删死壳 |
| D-5 | 240 条意图场景无断言 | 中 | 仅复用输入语料 | 补断言 |
| D-6 | 全仓无 per-tool 调用统计 | 高 | AC3 partial 直接后果 | 加探针/埋点 |
| **D-7** | **`l0.data` 壳委托空门面：`dreambuddy_l0.facade` 从未 `register_scope`，全部 scope 返回 `unknown_scope`** | **高** | `bogus.scope` 与 `market.ticker` 同为 `unknown_scope` | 二选一：壳改走 34 `L0Foundation`，或注册 fetcher |
| **D-8** | **产品链意图断路：S2/S3/S7 落占位模板** | **高** | 第 6.1 节 | 修 intent→handler 路由表 |
| **D-9** | **A 股别名缺失**：`entity_aliases.json` 仅 20 个加密/美股标的 | 中 | S3 口径修正说明 | 扩别名表 |
| **D-10** | **DSH 无并发上限**：5 并发全放行 | 中 | S14 `cap_enforced=false` | 加信号量 |
| **D-11** | `l0.cognition.health` 12s 超时 | 低 | P2 sweep 1/70 | 排查 DB 锁 |
| D-12 | 分析回答行情表 `N/A`（S4） | 中 | 第 6.1 节 | 分析 handler 数据回填 |

**豁免（不计死角）**：`l0.rea-client.mcp`、`agent.debate.mcp`（deprecated）。

---

## 9. 建议（按投入产出排序）

1. **修 D-8 意图路由（最高优先）**：让 `fundamental_valuation / semantic / trade_plan` 三类意图真正调用 L0/L1 工具，而非返回占位模板。预期 D2 从 2.29 提升至 ≥3.5。
2. **修 D-7 数据壳双路径**：MCP `l0.data` 与产品链 `market_query` 目前是两套数据实现；统一到一个 `L0Foundation`，避免“壳可调但无数据”。
3. **补 D-6 可观测**：在 DSH 执行器加 per-tool 计数（shell_id/tool/ok/latency），让 AC3 从 partial 转 pass。
4. **接 D-2 SACG**：按 SPEC v1.2 将 `SACGOrchestrator.handle` 接到产品链，替换直连 handler。
5. **补 D-4 注册**：`l1.stats.mcp` 入册；删除 `l0.rea-client.mcp`。
6. **加 D-10 限流**：在 `ShellHandleManager` 或 DSH 路由层加并发信号量。
7. **扩 D-9 别名表**：补 A 股核心标的，支撑 S2/S3 类问题。

---

## 10. 复跑与产物

```bash
cd 56-L2架构能力聚合层
python3 evals/run_all.py            # 静态 → 抽样 → 带证据静态 → DeepSeek 基线 → 验收
python3 evals/run_static_audit.py   # 仅静态矩阵
python3 evals/run_smoke.py --phase sweep,p1,p1b,p3,faults
python3 evals/run_baseline.py --max-calls 40
```

| 产物 | 说明 |
|---|---|
| `evals/scenarios.yaml` | 18 场景 + 期望工具 + 事实清单（含来源/签核） |
| `evals/probes.py` | 工具调用探针 + MCP stdio 客户端 |
| `evals/run_static_audit.py` | 壳级/工具级覆盖矩阵 |
| `evals/run_smoke.py` | 四入口实跑 + 故障注入 |
| `evals/run_baseline.py` | DeepSeek 8 题 × 六维 |
| `evals/run_all.py` | 一键复跑 + AC1-AC7 自验收 |
| `evals/out/*` | evidence / coverage / baseline / acceptance |

**验收结果**：AC1 ✅、AC1b ✅、AC2 ✅、AC3 ⚠️ partial（产品链 per-tool 不可观测）、AC4 ✅、AC5 ✅、AC5b ✅、AC6 ✅、AC7 ✅。

---

## 11. 局限与诚实声明

1. **D2/D5 非统计推断**：时延 n=1，正确性为关键词命中，不是人工/AI 评审。
2. **P1 工具链不可见**：产品链工具调用发生在 Node/DSH 进程，Python 探针无法跨进程观测（D-1），故 AC3 只能 partial。
3. **S3 口径修正**：SPEC 原示例「宁王/茅台/大饼」不在别名表，已改为表内实体并单列 D-9，未粉饰。
4. **S2 事实清单待签核**：财务表契约未纳入本仓，`signed_off=false`，需独立评审者抽查。
5. **G 层认知分流为注入双打**：`record_fn/verify_fn` 为 fake，标记 `simulated:true`，只证明路由逻辑，不证明真实认知写库。

---

## 12. 修复记录（v0.1 → v0.2，2026-11-18）

针对第 6 节「意图级断路」与第 9 节缺陷清单，已完成一轮「旧链清理 + 能力接齐」。以下均为实测证据。

### 12.1 指针错误（D-11，新增）

- 前端 14 处硬编码 `/home/luke/...` 全部清除，统一由 `3.1-FRONTEND/src/lib/runtime-paths.ts` 解析仓库根、Python 解释器与 34 系统目录。
- 运行时日志原证：`[ComplexIntentLibrary] L2 库查询失败: spawn /home/luke/venv-trading/bin/python ENOENT`。
- **桥接层第二个指针缺陷**：`34-前端应用训练系统/core/dsh_frontend_bridge.py:call_handler` 只读信封 `data` 字段，而真实结果在 `output`，导致所有 SubAgent 调用被丢成 `null`。修复后 `dsh_adapter.py technical` 返回真实 `summary/signals/confidence`。

### 12.2 旧链清理（D-8 关闭）

| 旧实现 | 处理 |
|---|---|
| `getChainByThinkingDepth()` 忽略意图，quick 恒为 `S2_ANALYSIS + S5_EXECUTE` | 改为意图感知；分析类意图不再路由到 S5；simple_qa 前置到 S0 |
| `generateNonDZEStepContent()` 输出「多维度分析与评估中...」占位模板 | 改为真实 DSH 调用（S1 macro+flow / S2 technical+sentiment+valuation / S3 synthesizer / S4 risk / S5 c_drive）；取不到即明示降级，禁止编造 |
| simple_qa 落入 S 链 2ms 空转 | 新增 `executeSimpleQaInline()` 走真实 LLM |
| `detectFinanceRelevance()` 误杀中文金融词 | 补充资金费率/爆仓/多空/基本面/A股/板块等关键词 |

### 12.3 能力接齐（D-9/D-10/D-7）

- **A 系列 26 个技能**：`skills-registry-init.ts` 不再使用 `Math.random()`，统一走 `3.1-FRONTEND/src/lib/trading-capability.ts` 四级适配：6-TRADING 脚本 → `deepseek_analyst.py`（a1/a2/a3/gate_c/process_d）→ DSH 8 SubAgent → 明确失败。
  - 依据：`6-TRADING/bridge/api/skill_router_api.py:SKILL_MAP` 与 `6-TRADING/scripts/*.py` 实际 argparse 契约。
  - 注意：`/api/skill/execute` 仍是排队占位（`note: will be handled by WorkBuddy`），**不可作为数据源**，已绕开。
- **D-7 `l0.data` 空门面**：壳改走 `34-前端应用训练系统/core/l0_foundation.L0Foundation`。实测 `data_collect_once` 返回 14 个 scope；`bogus.scope` → `unknown_scope`；`market.ticker` 已进入真实 fetcher（沙箱内 SSL 受限，非路由缺陷）。
- **D-10 并发上限**：`dsh-execution-engine.ts` 新增信号量，`DSH_MAX_CONCURRENCY` 默认 4。
- **D-9 A 股别名**：`entity_aliases.json` 新增茅台/宁德/比亚迪/平安/招行/工行/上证/沪深300/创业板/恒指/腾讯/阿里/美团共 13 组。

### 12.4 复验证据

| 场景 | 修复前 | 修复后实测 |
|---|---|---|
| simple_qa「什么是资金费率」 | 0-1ms 返回范围外/占位 | 1990ms 真实 LLM 回答，`chain=S0_DIRECT_ANSWER` |
| deep_analysis「BTC 多空矛盾/资金面/风险」 | `S2_ANALYSIS 分析中...` | 174s 完整报告，引用真实价格 63,720 / 持仓量 42.79B / 爆仓 86.5M；无占位；缺失维度显式说明 |
| `l0.data` scope | 全量 `unknown_scope` | 14 scope 可用，未知 scope 正确降级 |
| 前端类型检查 | — | `npx tsc --noEmit` 通过（0 error） |

### 12.5 未完成 / 后续

1. `skills-registry-init.ts` 中 26 段旧 `execute` 实现已不可达但仍留在文件内，建议下一轮删除（行为已无影响）。
2. `6-TRADING/bridge/api/skill_router_api.py` 的 `/execute` 仍是排队桩，建议改为真实调用 `SKILL_MAP` 对应实现，或从前端文档中移除该入口。
3. `market.ticker` 在沙箱内因 SSL 出口受限失败，需在允许出网的运行环境复测。

### 12.6 分析问法被行情卡截胡（D-12）

症状：开启 AI Agent 后，「分析比特币未来几天价格走势」仍返回行情卡 + 通用追问，与「查询比特币价格」完全一致。

根因两处：
1. `scripts/l1_route_signal.py`：`price_query` 属 `DETERMINISTIC_INTENTS`，只要命中价格正则就直接 `L1_DIRECT` 返回行情卡，分析类问法从不进入 L2。
2. `/api/agent/chat`：L1 直答在 `agent_enabled` 判断之前执行，AI Agent 开关形同失效。
3. `task-manager.ts`：意图识别回退到 `market_query` 时命中行情快路径，直接返回价格卡。

修复：
- L1 新增 `is_analysis_query()` 闸门（分析/预测/走势/研判/复盘/建议/未来/概率…），命中即 `L2_HANDOFF`，reason=`analysis_requires_l2`。
- `task-manager` 在入口把「market_query + 分析问法」纠正为 `deep_analysis`。
- 实测：`查询比特币价格` → `L1_DIRECT price_query`；`分析比特币未来几天价格走势` → `L2_HANDOFF`，`/api/agent/chat` 实际进入 LLM+tool 循环，`/api/task/stream` 输出 77s 深度报告（含真实价格/资金费率/情景推演），无行情卡、无占位。

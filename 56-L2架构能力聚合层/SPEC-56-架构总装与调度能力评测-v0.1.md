# SPEC-56-架构总装与调度能力评测 v0.2

> 阶段：开工SKILL 阶段 3（SPEC 形成）→ 已按 [评审报告](./SPEC评审报告-架构总装与调度能力评测-v0.1.md) P0/P1 修订
> 输入：[evals/inventory.md](./evals/inventory.md)、[evals/external-orchestration-bench.md](./evals/external-orchestration-bench.md)
> 目标目录：`56-L2架构能力聚合层/evals/`

## 1. 目标与非目标

### 1.1 目标
用可复现场景证明三件事，并给出机器可判定的证据：

1. **总装完整**：18 个注册壳（active 16）都有场景触达，覆盖矩阵无空列；
2. **调度有效**：L1→L2 交接、S 充分性状态机、A OKR 验收、C 五步反思门、G 四分流、DSH Ticket/Worker 的调度决策与消息流可观测；
3. **编排有增益**：同等问题上，SACG 全链相对 DeepSeek 单模型在“结论正确性 / 证据可追溯 / 能力覆盖”上不劣，且给出时延与 token 代价。

### 1.2 非目标
- 不改业务语义、不改注册表配额、不新增生产依赖；
- 不评测模型能力本身（不训练、不调参）；
- 不替代 45-评测系统 的常规回归，只做“架构总装与调度”专项。

## 2. 已确认口径
| 项 | 取值 |
|---|---|
| 执行深度 | 静态全量 + 抽样实跑（8 个场景） |
| 单模型基线 | DeepSeek（`dreamos/.env` 已有 Key），Trae 不参与 API 对比 |
| 外部调研 | Dify / LangGraph / OpenAI Agents SDK（已完成） |
| 产物 | 总报告 + 可复跑场景包 |

## 3. 调研结论驱动的设计约束
| 结论 | 约束 |
|---|---|
| D-1：产品链只调 in-process handler，MCP 壳零触达 | 取证必须分 P1/P2 两个入口，不能用 P2 结果冒充产品链 |
| D-2：SACG 未接入 `/api/task/stream` | SACG 场景走 P3（in-process）单独取证，并单列“未接入”结论 |
| D-3：Ticket 四模块默认关 | 并发/调度场景需显式开启开关，记录开关状态作为证据 |
| D-4：`l0.rea-client` 无实现、`l1.stats` 未注册 | 前者豁免；后者以 P2 stdio 直测并计入“注册缺口” |
| D-5：现有 240 条意图场景无断言 | 不复用其判定，仅复用输入语句 |
| D-6：无 per-tool 调用统计 | 新增探针（§5），否则覆盖不可证 |

## 4. 场景矩阵（9 类 / 18 条）

每条场景字段：`id / 类别 / 输入 / 期望调度路径 / 期望能力（shell.tool，即 expected_tools） / 必须凭证 / 断言 / 成本`

| ID | 类别 | 输入（示例） | 期望路径 | 期望能力 | 断言要点 |
|---|---|---|---|---|---|
| S1 | 简单直答 | “BTC 现价多少” | L1_DIRECT | `l0.data.data_fetch`、`l1.intent` | 不进入 L2；带数据源字段 |
| S2 | 数据取证 | “茅台近 4 季营收与毛利率” | L2_HANDOFF / light | `l0.data`、`l0.store-admin` | 返回 4 期且数值非 0.000 |
| S3 | 语义解析 | “宁王、茅台、大饼分别指谁” | L1_DIRECT 或 light | `l0.semantic-39.semantic_lookup` | 三实体全命中 |
| S4 | 矛盾识别 | “同一标的宏观与资金面是否矛盾” | L2_HANDOFF / standard | `l0.rea`、`l0.cognition.recall` | 产出矛盾维度与主矛盾 |
| S5 | 技术复盘 | “BTC 本周结构是否转弱” | L2_HANDOFF / deep | `l1.strategy`、`l0.rea.submit_rea_trace` | REA 四项状态齐全 |
| S6 | 估值 | “当前估值分位是否极端” | L2_HANDOFF / standard | `l1.strategy`、`l0.data` | 给出分位与样本区间 |
| S7 | 交易计划 | “给我 BTC 交易计划与仓位” | L2_HANDOFF | `l1.trading`、`l0.trade-exec`（只读） | 有止损/仓位/失效条件 |
| S8 | 风控 | “持仓回撤 12%，怎么处置” | L2_HANDOFF | `l1.trading`、`l0.cognition.verify` | 处置动作分级 |
| S9 | 回测验证 | “验证最近 20 笔信号质量” | L2_HANDOFF | `l0.eval`、`l2.train` | 产出样本数与胜率口径 |
| S10 | 进化沉淀 | “把这次失败案例入库” | L2_HANDOFF / write | `l2.emergence`、`l2.train`、`l0.semantic-39.training_feed` | 无 Mandate → 拒绝；有 → 入队 |
| S11 | 澄清 | “帮我看看这个” | NEED_CLARIFY | `l1.intent` | 返回结构化选项，不瞎猜 |
| S12 | 早停 | “今天天气如何” | EARLY_TERMINATE | `l1.intent` | 不触发下游 LLM |
| S13 | 故障降级 | 数据源超时/Tavily 401 | 任一 | `l0.data`、`l1.ops`、`l0.store-admin` | 信封 degraded、不编造数值 |
| S14 | 并发调度 | 同标的 5 并发请求 | L2_HANDOFF ×5 | `l2.dsh`、`l1.ops`、`l0.gateway` | 不超并发上限、Ticket 可查、无丢单 |
| S15 | 审计回放 | 任意 S4 回放 | — | `l2.dsh`、`l2.dreamos` | trace_id 贯穿；G 四类沉淀可查 |
| S16 | 审批门 | 写工具无/有 Mandate | — | `l0.cognition.record`、`l0.trade-exec` | 无 Mandate 拒绝；有则执行 |
| S17 | 事件驱动 | “非农超预期，对风险资产如何传导” | L2_HANDOFF / deep | `l0.data`、`l0.cognition.recall`、`l1.strategy` | 事件-资产-时滞三段齐全 |
| S18 | 跨资产轮动 | “股债商汇现在该往哪边偏” | L2_HANDOFF / deep | `l1.strategy`、`l0.data`、`l0.rea` | 给出轮动方向与依据 |

### 4.1 壳 → 场景覆盖映射（无死角判定依据）
> 映射只是“期望”；是否真实命中由探针证据判定（AC1/AC2）。工具级覆盖另见 AC1b。
| 壳 | 场景 | 说明 |
|---|---|---|
| `l0.cognition.mcp` | S4 / S8 / S15 / S16 / S17 | recall / verify / record |
| `l0.semantic-39.mcp` | S3 / S10 | lookup / training_feed |
| `l0.rea.mcp` | S4 / S5 / S18 | analyze / trace |
| `l0.rea-client.mcp` | — | **豁免**：deprecated 且无实现（D-4） |
| `l0.data.mcp` | S1 / S2 / S6 / S13 / S17 / S18 | fetch / store_read |
| `l0.eval.mcp` | S9 / S15 | eval_analyze |
| `l0.store-admin.mcp` | S2 / S13 / S14 | status / query |
| `l0.trade-exec.mcp` | S7 / S16 | 只读快照 + 写审批 |
| `l1.intent.mcp` | S1 / S11 / S12 | 路由与澄清 |
| `l1.ops.mcp` | S13 / S14 | 运维观测 |
| `l1.stats.mcp` | S14 / S15 | **注册缺口**：P2 直测 |
| `l1.strategy.mcp` | S5 / S6 / S17 / S18 | 策略/估值/轮动 |
| `l1.trading.mcp` | S7 / S8 | 交易/风控 |
| `l2.debate.mcp` | S5 | 多空辩论 |
| `l2.dreamos.mcp` | S15 | submit/poll 回放 |
| `l2.dsh.mcp` | S14 / S15 | Router/Ticket/Worker |
| `l2.emergence.mcp` | S10 | 案例入库 |
| `l2.train.mcp` | S9 / S10 | 训练/实验 |

## 5. 三维取证协议

| 入口 | 方式 | 用途 | 限制 |
|---|---|---|---|
| P1 产品链 | `POST http://localhost:3001/api/task/stream` | 证明产品入口可调度 | 前端不可用时降级为 **P1b** |
| P1b bridge | 直接 `dsh_frontend_bridge.call_tool` | 证明产品同一 handler 可用 | 证据标 `degraded_entry`，与 P1 分列统计 |
| P2 MCP stdio | 逐壳拉起 `mcp_shells/*/server.py`，`initialize → tools/list → tools/call` | 证明壳可用、工具契约一致 | 只读探针，不写生产数据 |
| P3 SACG | 直接调用 `core.sacg_orchestrator`（in-process） | 证明 S/A/C/G 决策与门控 | 结果标注“未接入产品链” |

### 5.3 模拟结果排除（P0-2）
以下结果**不计入真实触达**，证据必须标 `simulated: true`，并在报告中单列：
- `l2.dreamos` 的 mock 引擎（未设 `DREAMOS_API_BASE` 时的 `_advance_job_state`）
- SACG 中任何 stub/占位决策（未产生真实工具调用）
- 直接伪造的 fixture 外壳输出

### 5.4 故障注入（P1-1）
| 场景 | 注入点 | 断言 |
|---|---|---|
| S13-超时 | monkeypatch `l0.data.data_fetch` 抛 `TimeoutError` | 返回 `degraded=true` 且无数值编造 |
| S13-鉴权 | 设 `TAVILY_API_KEY=invalid` 或注入 401 | 降级到 DAL/本地源，证据含降级原因 |
| S14-并发 | 并发 5 次调用 + 并发上限设 2 | 无丢单：提交数 = 完成数 + 明确失败数 |
| S16-越权 | 不带 Mandate 调用写工具 | 拒绝码 `mandate_required`，无落盘 |

### 5.1 探针（解决 D-6）
`evals/probes.py`：会话内 monkeypatch `dsh_frontend_bridge.call_tool` 与 `shell_handles` 入口，记录每次工具调用的 `{ts, shell_id, tool, entry, trace_id, ok, latency_ms}` 到 JSONL；进程退出即还原，不写入生产代码。

### 5.2 证据 JSONL schema
```json
{
  "scenario_id": "S4",
  "entry": "P1|P2|P3",
  "trace_id": "hex16",
  "started_at": "ISO8601",
  "latency_ms": 1234,
  "tokens": {"prompt": 0, "completion": 0},
  "route": {"decision": "L2_HANDOFF", "confidence": 0.72},
  "stages": ["S", "A", "C", "G"],
  "tool_calls": [{"shell_id": "l0.rea.mcp", "tool": "submit_rea_analyze", "ok": true}],
  "verdicts": [{"node_id": "K1", "verdict": "pass"}],
  "sediments": [{"kind": "case|cognition|process|doc", "status": "written|async_stub"}],
  "assertions": [{"name": "has_trace_id", "pass": true}],
  "degraded": false,
  "raw_ref": "out/raw/S4-P3-<ts>.json"
}
```

## 6. DeepSeek 单模型基线

- 同 8 个抽样场景 × 同一份数据 fixture；单轮 prompt，不给工具；
- 六维（0–5，**分列，禁止合成总分**）：`capability_coverage / correctness / scheduling / evidence / latency / token_cost`；
  - 系统侧 D1/D3/D4 由探针与证据自动算；D2 用 `must_have_facts` 命中率折算（分母=事实条数）；
  - 基线侧 D1=0、D3=0、D4=0（结构性缺失，仅作事实呈现）；D2 用同一 checklist；D5/D6 实测；
- 时延：系统侧 n=3 取中位数；基线侧 n=1 仅作描述，报告注明“非推断统计”；
- 调用上限：≤ 40 次 DeepSeek（系统 8×3 + 基线 8×1 + 重试余量 8）。

## 7. 产物布局
```
56-L2架构能力聚合层/
├─ SPEC-56-架构总装与调度能力评测-v0.2.md        # 本文件
├─ SPEC评审报告-架构总装与调度能力评测-v0.1.md   # 阶段4
├─ evals/
│  ├─ inventory.md / external-orchestration-bench.md   # 阶段2 产物
│  ├─ scenarios.yaml            # 18 场景 + expected_tools + must_have_facts(含来源/签核字段)
│  ├─ probes.py                 # per-tool 调用探针
│  ├─ run_static_audit.py       # 静态覆盖矩阵（registry × scenarios，壳级+工具级）
│  ├─ run_smoke.py              # P1/P1b/P2/P3 抽样实跑 + DeepSeek 基线
│  ├─ run_all.py                # 一条命令跑全量（静态→抽样→报告骨架）
│  └─ out/                      # evidence.jsonl / raw/ / coverage_matrix.json
└─ docs/
   └─ ASSESSMENT-20261118-架构总装与调度能力评测-v0.1.md   # 最终报告
```

## 8. 验收标准（机器可判定）
| # | 标准 | 判定方式 |
|---|---|---|
| AC1 | 18 壳全部出现在覆盖映射；16 个 active 壳每个 ≥1 场景 | `run_static_audit.py` 退出码 0 |
| AC1b | **工具级**：每 active 壳 ≥1 个工具被证据命中；整体工具触达 ≥70%（未触达需列清单+理由） | coverage_matrix.json `tools_hit` |
| AC2 | 抽样实跑 ≥8 条；每条有 trace_id；`expected_tools` 命中率 ≥80%，且至少 1 个非 health/stats 业务工具 | evidence.jsonl 校验 |
| AC3 | **双列口径**：P1 真实触达壳 ≥6；P2 可用壳 16/16；`P1b` 与 `simulated` 单列，不计入 P1 | coverage_matrix.json 分列 |
| AC4 | G 四分流每类 ≥1 实例（含 `async_stub` 显式标注） | sediments 聚合 |
| AC5 | 至少各 1 例：C 层 REDO/中止、Mandate 拒绝、degraded 不编造 | 断言命中 |
| AC5b | 写链路证明：S10/S16 用 `DREAMBUDDY_L0_ROOT=<tmp>` + mock Mandate 走**完整写入**后断言落盘，再清理临时根；不得只测拒绝路径 | 临时根快照比对 |
| AC6 | 对比报告含 8 题 × 6 维（分列、无总分）+ 原始输出存档 + 时延样本量说明 | 报告自检 |
| AC7 | `python3 evals/run_all.py` 可复跑，静态 <60s | 实测 |

## 9. 风险与边界
| 风险 | 处置 |
|---|---|
| 前端 3001 未启动 | 降级 `P1b`，与 P1 分列统计并在报告注明 |
| L2 API 冷启动约 2 分钟 | 抽样前预检 `/api/v1/health`，超时 180s |
| 写工具污染生产数据 | S10/S16 用 `DREAMBUDDY_L0_ROOT=<tmp>` 隔离根，走完整写入后断言并清理 |
| 自证偏误 | `must_have_facts` 必须从既有契约（56/contracts、34/tests fixtures）或 30 系统固定输入派生，禁止凭印象编写；留 30% 场景由独立评审者抽查事实清单 |
| mock 刷绿 | `l2.dreamos` mock 引擎与任何 stub 结果标 `simulated:true`，不计入真实触达 |
| DeepSeek 计费 | 硬上限 40 次，超限即停并记录 |
| SACG 未接入产品链（D-2） | 作为结论输出，不在本 SPEC 内修复 |

## 10. 与外部项目的对应
| 我们缺的机制 | 外部参照 | 本 SPEC 中的落点 |
|---|---|---|
| 超步级 checkpoint | LangGraph | S15 审计回放（只观测，不实现） |
| 节点 Retry/Timeout | LangGraph / Dify | S13 降级场景 |
| 审批票据 | OpenAI Agents SDK | S16 Mandate 拒绝路径 |
| 能力发布面 | — | P2 + `l2.dsh.mcp` 已具备 |

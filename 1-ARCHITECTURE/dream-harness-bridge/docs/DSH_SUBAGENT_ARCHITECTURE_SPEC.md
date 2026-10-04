# DSH Subagent 架构 Spec — DreamOS 编排 + DSH 驱动

> **版本**: v0.2（含行业调研优化）
> **状态**: 📋 调研+行业对标完成，待批准实施
> **日期**: 2026-09-24
> **前置文档**:
> - [CHAIN_INTEGRATION_SPEC.md](./CHAIN_INTEGRATION_SPEC.md)（端口统一方案 A 已实施）
> - [TECHNICAL_DESIGN.md](../../dreamos/docs/TECHNICAL_DESIGN.md)（SACG 四层架构）
> **定位**: DSH Subagent 架构设计方案 + 调研结论 + 行业对标 + 实施路径
> **调研方法**: recall 认知记忆 + Explore agent 代码审计 + WebSearch 行业对标（Anthropic/TradingAgents/Bloomberg/FactSet）
> **v0.2 变更**:
> - 新增 §1.4 Orchestrator+隔离 subagent 模式（行业共识）
> - 新增 §1.5 Bull/Bear 辩论机制（TradingAgents 启发）
> - 新增 §3.6 Subagent 实现形态选择
> - 新增 §八 行业对标调研结论
> - 七·待调研项全部勾销

---

## 一、核心设计原则

### 1.1 职责分层

| 层 | 职责 | 类比 |
|----|------|------|
| **DreamOS SACG** | 编排规划——"做什么" | OS 内核调度器 |
| **DSH Subagent** | 驱动力——"怎么做" | OS 驱动程序 |

### 1.2 数据驱动避幻觉（硬约束）

- Subagent 的**输入数据**必须来自 DreamOS 编排节点（基本面 F1-F5 + 技术分析 C1-C3）的已验证输出
- LLM **只做提炼和图表生成**，不生成原始数据
- 节点能力经过回测验证和实盘检验，有效避免大模型幻觉问题

### 1.3 C 层驱动闭环（核心创新）

SACG 的 C 层（Compute 执行层）本身需要 DSH subagent 驱动，承载四步循环：

```
C-Drive-Agent 四步循环
  1. 调用认知系统查询经验（recall 历史相似场景）
  2. 反思推理（扩展 Reflector，基于历史经验 + Bull/Bear 辩论决策）
  3. 调用 jeval 判断（noul/score 质量评估）
  4. 置信度不足 → 路由到金融 subagent 补充资料
```

### 1.4 Orchestrator + 隔离 Subagent 模式（行业共识，硬约束）

2025-2026 行业已收敛到 "Orchestrator + 隔离 subagent" 模式，peer collaboration（GroupChat）衰落。依据：
- Anthropic research multi-agent + Claude Code Task tool + OpenAI agents-as-tools + Cognition Managed Devins 均用此模式
- peer 协作 O(n²) 通信爆炸，每次唤醒重读全部 transcript，成本 ~15x token
- 隔离 subagent 只返回压缩摘要，主 agent 持有完整上下文

**本项目应用**：

| 角色 | 定位 | 上下文 |
|------|------|--------|
| **DreamOS SACG** | Orchestrator（规划者） | 持完整上下文：意图+执行图+所有节点结果 |
| **DSH Subagent** | 隔离执行者 | 独立上下文：接收任务描述 → 执行 → 返回 SubagentOutput 摘要 |

- Subagent 之间**不通信**，只与 C-Drive-Agent 交互
- Subagent 返回的 SubagentOutput 是压缩摘要，不携带完整执行过程
- C-Drive-Agent 持有所有 subagent 返回的摘要，做聚合决策

### 1.5 Bull/Bear 辩论机制（TradingAgents 启发）

TradingAgents（82K stars，Tauric Research）最成功的设计是 Bull/Bear Researcher 显式辩论——不是简单聚合，而是多空对抗。我们的 A0 矛盾论节点部分覆盖但不够显式。

**本项目应用**：在 C-Drive-Agent 第 2 步"反思推理"中，当置信度 < 0.65 时触发 Bull/Bear 对抗辩论：

```
Bull/Bear 辩论流程（置信度 < 0.65 时触发）
  1. Bull agent：从 subagent 输出中提取利好信号，生成多头论据
  2. Bear agent：从 subagent 输出中提取利空信号，生成空头论据
  3. 辩论结果：bull_confidence vs bear_confidence + 关键论据列表
  4. 注入 Aggregator：辩论结果作为 A0 矛盾论的输入
```

- Bull/Bear 不是独立 subagent，而是 C-Drive-Agent 内部的两个 LLM 角色
- 辩论结果（多空论据+置信度）比简单 recall 历史经验更有效
- 避免单一视角偏见，确保 balanced analysis

---

## 二、调研结论

### 2.1 C 层现状审计

| C 层组件 | 现状 | 目标 | 差距 |
|---------|------|------|------|
| `GraphExecutor.execute()` | 内部调度 C1→C2→C3，返回 ExecutionReport | DSH subagent 驱动执行 | ❌ 无 DSH 接入 |
| `Reflector.decide()` | 低置信度返回 REDO（重做当前节点） | 1.调认知 2.反思 3.jeval 4.补资料 | ❌ 只有 REDO |
| `Aggregator.aggregate()` | 按节点结果算方向/置信度 | 聚合 subagent 输出+图表配置 | ❌ 无图表 |
| 认知系统 | `cognitive_loop_adapter.py` L62-85 已封装 recall/record/verify | C 层直接调用 | ⚠️ 适配器存在但未接入 C 层 |
| jev-judge | 通过 Python IPC 接入 harness（3个 Harness 事件） | C 层 Aggregator 聚合后调用 | ⚠️ 在 harness 层未进 C 层 |

**关键证据**：
- `graph_executor.py` L100-106：execute() 签名无认知/jeval/subagent 接口
- `reflector.py` L127-140：当前只有 REDO 逻辑，无认知查询
- `cognitive_loop_adapter.py` L62-85：recall 封装已存在，MCP 不可用时返回 []（FAIL-OPEN）
- recall 记忆 VM-1786324739691：Reflector REDO 机制已验证运行（95次/日，max_retries=2）

### 2.2 DSH Subagent 现状

- DSH 当前**没有 subagent 概念**，是"Cordis 插件 + 节点链路"架构
- `cordis-plugin-fundamental` 把新闻/资金流/宏观/链上全混在一个 tool 里返回
- **图表能力完全缺失**：所有插件输出都是 JSON 文本或文本卡片
- 前端 `src/app/fundamental/` 下有 12 个基本面页面，但 DSH 无对应 subagent 输出结构化数据

### 2.3 金融模块缺失清单

| 传统金融模块 | DreamOS 节点 | DSH 插件 | 前端页面 | 缺失 |
|-------------|-------------|---------|---------|------|
| 宏观经济 | F5 | fundamental 混合 | ✅ | 独立 subagent + 图表 |
| 资金流向 | F2 | fundamental 混合 | ✅ | 独立 subagent + 图表 |
| 链上指标 | F4 | fundamental 混合 | ✅ | 独立 subagent + 图表 |
| 市场情绪 | F1 | fundamental 混合 | ✅ | 独立 subagent + 图表 |
| 估值分析 | F3 | fundamental 混合 | ✅ | 独立 subagent + 图表 |
| 技术面 | C1-C3 | c-chain + indicators | ✅ | 独立 subagent + 图表 |
| 风险管理 | 无 | 无 | ✅ | 全缺 |
| 组合管理 | 无 | 无 | ✅ | 全缺 |

---

## 三、架构设计

### 3.1 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  DreamOS SACG (Orchestrator - 编排层, 持完整上下文)          │
│  S: IntentEngine 识别意图                                    │
│  A: GraphPlanner 编排执行图（选A/C/F链）                      │
│  C: GraphExecutor 执行 ← C-Drive-Agent 驱动                 │
│  G: GraphStore 存储检查点                                    │
└────────────────────┬───────────────────────────────────────┘
                     │ IPC (NDJSON)
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  DSH Subagent 架构 (隔离执行 - 驱动力层, 独立上下文)         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  C-Drive-Agent (C层驱动, Orchestrator 的执行代理)    │    │
│  │  Step 1: recall 认知查询                             │    │
│  │  Step 2: 反思推理 + Bull/Bear 辩论 (置信度<0.65时)  │    │
│  │  Step 3: jeval 判断 (noul/score)                    │    │
│  │  Step 4: 置信度不足 → 路由到金融 subagent 补充      │    │
│  └──────────────┬──────────────────────────────────────┘    │
│                 │ 路由 (subagent 间不通信, HC-7)             │
│     ┌───────────┼───────────┐                                │
│     ▼           ▼           ▼                                │
│  macro-agent  flow-agent  onchain-agent  ...  (隔离执行)     │
│  每个: 节点输出 → LLM提炼 → SubagentOutput 摘要 (返回 C层)  │
│                                                              │
│  实现形态: Cordis 插件 + Python server IPC (§3.6 决策)       │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Subagent 清单

| Subagent | 对应节点 | 数据源 | 图表类型 | 优先级 |
|----------|---------|--------|---------|--------|
| `C-Drive-Agent` | C 层本身 | 认知库 + jeval | — | P0 |
| `technical-agent` | C1+C2+C3 | OKX K线 | K线+指标叠加 | P0 |
| `sentiment-agent` | F1 | 贪婪恐惧/期权PCR | 仪表盘+折线 | P0 |
| `macro-agent` | F5 | GDP/CPI/利率/流动性 | 柱状+趋势线 | P1 |
| `flow-agent` | F2 | ETF/杠杆/稳定币 | Sankey+柱状 | P1 |
| `onchain-agent` | F4 | 活跃地址/算力/MVRV | 折线+热力图 | P1 |
| `valuation-agent` | F3 | NVT/StockFlow | 散点+回归线 | P1 |
| `risk-agent` | 无 | 需新建 VaR/相关性/压力 | 热力图+矩阵 | P2 |
| `portfolio-agent` | 无 | 需新建 仓位/再平衡 | 饼图+柱状 | P2 |
| `synthesizer-agent` | Aggregator 输出 | LLM 综合重写为 insight/recommendation 卡片 | InsightCard+RecommendationCard | P1 |

> **synthesizer-agent** 是第 9 个 subagent，定位为"聚合层 LLM 综合器"：将 `aggregator.py` 聚合结果经 LLM 综合重写为 insight/recommendation 卡片，供前端 `InsightCard.tsx` + `RecommendationCard.tsx` 渲染。FAIL-OPEN：无 `llm_fn` 时降级为 `_rule_based_synthesis` 规则综合。认知闭环：`recall()` 检索历史综合经验 → `record()` 记录新结果。与 aggregator 解耦：`synthesize(aggregated_dict) → List[SynthesizedCard]`。

### 3.3 Subagent 输出契约

```typescript
interface SubagentOutput {
  module: string;           // "macro" | "flow" | "onchain" | ...
  summary: string;          // LLM 提炼的 1-2 句人读结论
  signals: Signal[];        // 标准化信号 [{name, value, direction, confidence}]
  charts: ChartSpec[];      // 图表配置 [{type, title, data, config}]  // ECharts option
  raw_data?: any;           // 原始数据（可选，供下钻）
}

interface Signal {
  name: string;             // "MACD死叉" | "ETF流入" | ...
  value: number | string;   // 数值或描述
  direction: "long" | "short" | "neutral";
  confidence: number;       // 0.0-1.0
}

interface ChartSpec {
  type: "candlestick" | "line" | "bar" | "sankey" | "gauge" | "scatter" | "heatmap" | "pie";
  title: string;
  data: any;                // ECharts data 格式
  config?: any;             // ECharts option 补充配置
}
```

### 3.4 C-Drive-Agent 四步循环详设

```
C 层每个节点执行后：
  Step 1: recall(context="当前节点+意图+市场状态", top_k=5, min_quality="C")
    → 返回历史相似场景经验

  Step 2: Reflector 扩展（含 Bull/Bear 辩论）
    → 基于 recall 结果 + 当前节点结果，决策：
      - CONTINUE: 置信度足够，继续下一步
      - REDO: 重做当前节点（recall 提示参数调整）
      - JUMP: 跳转到指定节点（recall 提示更优路径）
      - SUPPLEMENT: 置信度不足，触发 subagent 补充
      - DEBATE: 置信度 < 0.65 时，触发 Bull/Bear 辩论子流程
          Bull: 从已有信号提取利好 → 多头论据 + bull_confidence
          Bear: 从已有信号提取利空 → 空头论据 + bear_confidence
          辩论结果注入 Aggregator 作为 A0 矛盾论输入
          辩论后重新评估置信度，回到决策分支

  Step 3: jeval 判断（仅 Step 2 返回 CONTINUE 时）
    → 调用 jev_judge(state, questions)
    → noul >= 0.85: 放行，进入下一节点
    → noul < 0.50: 阻止，回到 Step 2 重新反思
    → 0.50-0.85: 记录但放行

  Step 4: subagent 补充（仅 Step 2 返回 SUPPLEMENT 时）
    → 基于 intent_type + 不足维度 路由：
      - DEEP_ANALYSIS 缺基本面 → macro/flow/valuation agent
      - 缺技术面 → technical agent
      - 缺情绪面 → sentiment agent
    → subagent 返回 SubagentOutput
    → 注入到 market_data，重新执行当前节点
```

### 3.5 分级触发机制（避免延迟累积）

| 置信度 | 触发动作 | 预估延迟 |
|--------|---------|---------|
| > 0.75 | 跳过四步循环，直接下一节点 | 0ms |
| 0.65-0.75 | 只 Step 1 recall + Step 2 反思 | ~50ms |
| 0.50-0.65 | recall + 反思 + Bull/Bear 辩论 | ~200-300ms |
| < 0.50 | 全链路四步循环（含辩论 + subagent 补充） | ~500ms-1s |

### 3.6 Subagent 实现形态选择

三种主流方案对比：

| 方案 | 代表 | 优势 | 劣势 |
|------|------|------|------|
| Cordis 插件 + Python server IPC | 我们当前架构 | 与 DSH 深度集成，FAIL-OPEN 成熟 | 需手写 IPC 协议 |
| Claude Managed Agent | Anthropic 金融模板 | 企业级，有审计日志 | 依赖外部平台，不可控 |
| LangGraph 节点 | TradingAgents | 开源，状态管理强，checkpoint | 引入新框架，增加复杂度 |

**决策：采用 Cordis 插件 + Python server IPC 模式**（与现有架构一致，不引入新框架）

每个 subagent 的实现结构：

```
cordis-plugin-<module>-agent/        # Cordis 插件入口
  package.json                        # 插件元数据
  lib/index.js                        # 注册 tool + agent/* 事件 hook

python-server/modules/<module>_agent.py  # Python 实现
  class <Module>Agent:
    def execute(self, node_output: dict) -> SubagentOutput:
        # 1. 接收 DreamOS 节点输出（已验证数据）
        # 2. LLM 提炼（DeepSeek API）
        # 3. 生成 signals + charts
        # 4. 返回 SubagentOutput
```

- 不引入 LangGraph（避免增加框架复杂度，与 HC-1a 一致）
- 每个 subagent 是一个独立 Python 类 + 一个 Cordis 插件入口
- 通过 Python server IPC 统一调度，C 层通过 IPC 调用
- LLM 调用走 DeepSeek（已配置），FAIL-OPEN 超时降级

---

## 四、风险评估

| 风险 | 严重度 | 缓解方案 |
|------|--------|---------|
| C 层每步反思都调认知+jeval，延迟累积 | 高 | 分级触发：>0.75 跳过；0.65-0.75 只 recall；0.50-0.65 加辩论；<0.50 全链路 |
| Bull/Bear 辩论增加 LLM 调用次数 | 中 | 仅置信度 <0.65 时触发；辩论用 deepseek-flash（快速低成本）；两个角色可并行调用 |
| 9 个 subagent 工作量大 | 中 | 分批：P0 先做 C-Drive + technical + sentiment（3个），P1 做 4个+synthesizer，P2 做 2个 |
| jeval 当前在 harness 层不在 C 层 | 中 | 在 Python server 暴露 `jev_judge` IPC method，C 层通过 IPC 调用 |
| subagent 路由逻辑复杂 | 中 | 基于 intent_type + 不足维度 路由表 |
| "Laya 备用"方案未调研 | 低 | 先用 jeval（TYPESAFE_API_KEY 已配置），Laya 作为后续备选 |
| subagent 之间产生通信需求 | 低 | HC-7 硬约束禁止 subagent 间通信，只与 C-Drive-Agent 交互 |

---

## 五、实施路径

| 阶段 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| **P0** | 1. C 层 Reflector 扩展 recall 调用<br>2. 新建 C-Drive-Agent 框架（含 Bull/Bear 辩论）<br>3. 新建 technical-agent + sentiment-agent 试点 | C 层具备认知查询 + 辩论 + 2 个 subagent 验证 | cognitive_loop_adapter |
| **P1** | 4. Python server 暴露 jev_judge IPC<br>5. Aggregator 聚合后调 jeval<br>6. 新建 macro/flow/onchain/valuation 4 个 subagent | C 层完整四步循环 + 6 个金融 subagent | P0 完成 |
| **P2** | 7. 置信度不足时路由逻辑<br>8. 新建 risk/portfolio subagent<br>9. 图表配置标准化 + 前端渲染 | 9 个 subagent 全覆盖 + 图表输出 | P1 完成 |

---

## 六、硬约束

- HC-1: Subagent 输入数据必须来自 DreamOS 节点已验证输出，LLM 不生成原始数据
- HC-2: C 层四步循环必须分级触发，置信度 >0.75 时跳过避免延迟
- HC-3: 认知系统调用必须 FAIL-OPEN（MCP 不可用时返回 []，不阻塞执行）
- HC-4: jeval 调用必须 FAIL-OPEN（超时或异常时降级为纯规则判断）
- HC-5: Subagent 输出必须符合 SubagentOutput 契约（module/summary/signals/charts）
- HC-6: 图表配置必须符合 ECharts option 格式，前端做 schema 校验后渲染
- HC-7: Subagent 之间禁止直接通信，只与 C-Drive-Agent 交互（Orchestrator+隔离模式）
- HC-8: Bull/Bear 辩论仅置信度 <0.65 时触发，用 deepseek-flash 并行调用控制延迟

---

## 七、行业对标调研结论

### 7.1 传统金融终端

| 对标 | 架构特点 | 我们的对应 |
|------|---------|-----------|
| Bloomberg Terminal | 垂直一体化：私有数据网络→集中标准化→统一客户端；模块按资产类别划分（Equity/Fixed Income/Commodity） | 我们的奖章架构（Bronze/Silver/Gold）与 Bloomberg"集中标准化"一致；模块按分析维度而非资产类别 |
| Bloomberg ASKB (2026.2) | 125K beta 用户，使用 Anthropic 模型，CTO 称"新终端" | 我们的 DreamOS + DSH 是自建版，不依赖外部终端 |
| FactSet Workstation | 800+ 数据源统一接入，FactSet Intelligence AI 自动化，"数据层不变+AI 编排层在上" | 我们的 SACG+DSH 分层与 FactSet"数据层+AI 编排层"一致 |

### 7.2 AI 大模型公司

| 对标 | 实践 | 我们的对应 |
|------|------|-----------|
| Anthropic 10 个金融 agent 模板 | github.com/anthropics/financial-services；agent = skills + connectors + subagents；Valuation Reviewer 对标我们的 valuation-agent | 我们 9 个 subagent 覆盖加密场景（Anthropic 偏股票投行） |
| Anthropic Orchestrator 模式 | 主 agent 持完整上下文 + subagent 隔离执行返回摘要 | HC-7 直接采用此模式 |
| DeepSeek 扩招方向 | 9月扩招 150 名工程师，核心是 Agent 弹性计算研发（非 AI 研究） | 模型已成熟，重点转向"如何让 Agent 稳定高效运行"——我们 DSH subagent 要解决的问题 |
| Mint-Agent (arxiv 2608.16386) | 金融原生 agent 基础模型；Evidence Ledger + Working Memory + 推理/执行双专家 | 我们的认知库 + GraphStore 部分对应 |

### 7.3 GitHub 开源金融框架

| 对标 | 架构 | 我们的对应与差异 |
|------|------|-----------------|
| TradingAgents (82K stars, Tauric Research) | Analyst Team→Research Team(Bull/Bear 辩论)→Trader→Risk Mgmt→Portfolio Manager；基于 LangGraph | HC-8 Bull/Bear 辩论直接借鉴；我们用 Cordis+IPC 不用 LangGraph；我们做加密不做股票 |
| CrewAI (49.2K stars) | 角色驱动 multi-agent；Crews(自治) + Flows(事件驱动) | 不采用——peer 协作 O(n²) 通信不符合 HC-7 |
| Microsoft Agent Framework | AutoGen+Semantic Kernel 合并 1.0 GA；graph-based workflow | 不采用——与 DSH Cordis 架构不一致 |
| LangGraph (LangChain 生态) | 状态管理+checkpoint；TradingAgents 基础 | 不采用——§3.6 决策 Cordis+IPC |

### 7.4 行业共识总结

1. **Orchestrator + 隔离 subagent 模式胜出**：Anthropic/Cognition/OpenAI 2025-2026 全部收敛到此模式，peer collaboration 衰落
2. **Bull/Bear 辩论是金融场景最佳实践**：TradingAgents 82K stars 验证，比简单聚合更有效
3. **数据驱动避幻觉是行业共识**：FactSet "trusted data + governed AI"、Anthropic "agents don't make recommendations, stage for human sign-off"、TradingAgents "grounded decisions"
4. **不引入新框架**：Cordis+IPC 与现有架构一致，LangGraph/CrewAI 增加复杂度无收益

---

## 八、待澄清项

- [x] ~~传统金融公司模块划分参考~~ → §7.1 已完成
- [x] ~~AI 大模型公司金融 agent 实践~~ → §7.2 已完成
- [x] ~~GitHub 开源金融框架 subagent 模式~~ → §7.3 已完成
- [x] ~~Subagent 具体实现形态~~ → §3.6 已决策 Cordis+IPC
- [ ] "备用 Laya"方案的具体含义（用户待澄清）

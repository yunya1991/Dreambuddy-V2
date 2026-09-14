# PROP-20260829-B · P1 最小对话环验证报告

- **日期**: 2026-08-29
- **状态**: ✅ 核心假设已验证（P1a：Hermes → DreamOS 只读编排全链路）
- **验证方式**: 零新代码——全部使用 DreamOS 现有接口（`apps/api_server.py`）

---

## 一、验证目标

核心公理（用户定调）：**大模型只决定「做什么」，「怎么做」由 DreamOS 物理管道 + 模块化能力确定性完成，LLM 漂移被隔离在执行层之外。**

最小验证环：用户对话 → 意图识别 → DreamOS 物理编排 → 结构化结果回流。

## 二、验证环境

| 项 | 值 |
|---|---|
| 入口 | `python -m dreamos.apps.api_server --port 8000`（加载 ab-trading config/.env） |
| 实时行情 | Hyperliquid mid: BTC = 77,859.5（验证时刻） |
| 意图识别器 | rule_based + llm_based（双识别器融合） |
| 预算守卫 | standard 模式（6000/cycle），运行中 ✓ |

## 三、验证结果

### P1-1 只读意图识别（`POST /api/v1/intent`）✅

- 请求：`{"user_input": "BTC 现在能做多吗？"}`
- 返回：`intent_type=UNCERTAIN`，`confidence=0.7`，`base_chain=[A1,A2,A3,A4,A5,A9]`（决策类物理链）
- 识别器：`rule_based + llm_based`，590 tokens
- 结论：**S 层对外部自然语言输入可用，返回结构化意图 + 物理链推荐。**

### P1-2 完整编排（`POST /api/v1/run`）✅

- 请求：`{"user_input": "BTC 现在能做多吗？", "market_data": {"symbol": "BTC", "price": 77859.5}}`
- 返回（关键字段）：

```
cycle_id   : trade_20260828175603_e9266b
intent     : TREND_FOLLOWING (conf 0.315)
capability : trading（精确匹配, score 1.00, 意图→交易能力域）
execution  : nodes_planned=9, nodes_executed=9, success=9, skipped=0  ← 物理图全绿
action     : SHORT, confidence=0.701
latency    : 57.7s（Qwen 节点内调用）
budget     : healthy，无降级
outputs    : A2 三维评分（fundamental 等）结构化回流
```

- 结论：**外部单次触发 → 能力路由 → 9 节点物理图确定性执行 → 结构化决策回流。全链路导通，0 跳过 0 失败。**

## 四、结论与边界

### 已验证（P1a）
1. DreamOS 物理编排可被外部（Hermes）单轮调用驱动，无需 crontab。
2. 意图 → 能力域路由是确定性匹配（score 1.00 exact），不是 LLM 自由发挥。
3. 执行层 9/9 节点确定性完成——「怎么做」由物理管道保证，符合公理。
4. 结果结构化（action/confidence/rationale/trace），可被前端直接渲染。

### 未验证（需 P1b，涉及新代码）
1. **前端对话桥**：gateway(:3000) → Hermes → DreamOS 的 UI 链路（当前前端零引用 DreamOS API）。
2. Hermes 意图前置覆盖：本轮 DreamOS 内部 IntentEngine 自行识别；目标架构是 Hermes 识别后下达结构化编排指令（intent 透传/覆盖），需 P0 意图正典对齐后实现。
3. 决策质量不在 P1 范围（仅传 price 一个字段，SHORT 结论仅证明管道导通，非交易建议）。

### 观察项
- `/api/v1/run` 无 market_data 时意图降为 UNCERTAIN（conf 0.7）——对话驱动场景必须注入行情快照，B1 桥设计需内置数据装配。
- 单轮 57.7s 延迟：Qwen 节点内调用主导；前端桥需异步/流式响应设计。

## 五、下一步（P1b 候选桥接方案，均需新代码 + 审批）

| 方案 | 形态 | 工作量 | 特点 |
|---|---|---|---|
| B1 | gateway 新增 `/api/dreamos-bridge` 路由 → Hermes webhook(:8644) → api_server | 中 | 前端无感，链路最长 |
| B2 | Hermes MCP 适配器注册 DreamOS API 为工具 | 小 | Hermes 原生，前端仍走 gateway 对话 |
| B3 | 前端直连 api_server + Hermes 仅做意图前置 | 大改前端 | 最短链路但绕过 Hermes 编排权 |

推荐：**B2**（Hermes 原生工具化，符合「Hermes 决定做什么」的公理，改动最小）。

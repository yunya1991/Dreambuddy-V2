# PROP-20260829-B v2 — Hermes 意图识别 + DreamOS 物理编排（对话驱动方案）

> **状态**: 📋 方案重梳完成，待用户决策
> **范围纠正（用户 2026-08-29）**: 本方案**只覆盖前端对话驱动链路**。cron/:30 自动交易循环是独立泳道，其风险与治理不混入本方案。
> **上一版问题**: v1 把自动循环的双脑冲突风险混入对话方案，已按用户纠正重梳。

---

## 一、核心架构：三层分工，漂移物理隔离

```
用户对话（前端 UI / 飞书 / 微信）
    ↓ 自然语言
前端网关（薄转发层，逐步废弃现有 4 套 TS 意图实现）
    ↓
【Hermes = 意图识别层】
    tool calling = 意图（已验证架构，无独立分类器）
    持久记忆 / 技能库 / clarify 反问 / FC 参数修复级联
    ↓ 编排指令：调哪些能力、走哪条管道（结构化，非自由文本）
【DreamOS = 物理管道编排层】
    SACG：IntentEngine 对接 → arrange 图规划 → GraphEngine 确定性调度
    ↓
【模块化能力 = 执行层】
    节点（a/c/f/g 系列）全部代码实现、确定性执行
    ↓
结果逐层回流 → 对话回复
```

**设计公理（用户定调）**：大模型只决定「做什么」（意图 + 编排选择），「怎么做」完全由 DreamOS 物理管道 + 模块化能力确定性完成。LLM 漂移被隔离在执行层之外——这是相对「裸大模型直接生成执行逻辑」的本质优势。

## 二、泳道划分（风险不混谈）

| 泳道 | 驱动方 | 本方案 |
|------|--------|--------|
| **交互对话道** | 用户触发 → Hermes 意图 → DreamOS 编排 → 模块化能力 | ✅ 本方案范围 |
| 定时自动道 | cron → F层调度器 → 四闭环 | ❌ 不动、不讨论其风险 |

## 三、现状事实（D1 实测，对话道相关）

1. 前端网关有 **4 套互不兼容的意图实现**（2026-08-28 实测）：chat 内联 9 意图 / fallback-engine 15 / llm-planner 5(FC) / clarification-engine；JSON 正则解析脆弱，qwen3 思考链曾致 15s 超时 P0。
2. 前端编排**闭环在 TS 侧，零调用 DreamOS**（grep 实测）——「模块化能力」完全没被前端用上，这是当前最大浪费。
3. DreamOS 具备完整承接面：`core/sense/intent_engine.py`（规则+LLM+动态识别）、`core/arrange/`（图规划/节点选择）、Flask `api_server.py`（/api/v1/intent|run|analyze|chat，当前未启动，可复活）。
4. Hermes 集成面就绪：gateway webhook **:8644 运行中**（审批 webhook 已生产验证）；API Server 适配器（Open WebUI 接入模式）；`hermes -z` one-shot；MCP 客户端（认知系统接入先例）。
5. 🔴 `coin_selector._select_via_hermes()` 是 TODO 桩（实际 mock）——DreamOS 主动调 Hermes 的方向目前无生产实现，需在本方案中一并定标准。

## 四、桥接面设计（前端 ↔ Hermes ↔ DreamOS）

### 前端 → Hermes（三选一，Z1 定案）
| 桥接 | 机制 | 特点 |
|------|------|------|
| **B1（推荐）** | Hermes API Server 适配器（OpenAI 兼容，Open WebUI 同款） | 前端把「LLM 端点」换成 Hermes 即完成替换；对话式同步体验最好 |
| B2 | Webhook :8644（审批同款） | 生产已验证；异步，需补回调/轮询取结果 |
| B3 | 桥进程调 `hermes -z` one-shot | 最简单但无会话连续性 |

### Hermes → DreamOS（编排调用面）
| 桥接 | 机制 | 特点 |
|------|------|------|
| **D1（推荐起步）** | 复活 Flask api_server（/api/v1/run\|analyze\|intent）+ Hermes 工具包装 | 代码已存在，启动即用 |
| D2 | DreamOS MCP server | 架构最正（认知系统先例），Hermes 原生 tool；工作量+1 |
| D3 | CLI 命令组包装 | 最快出活，适合 Phase 1 |

## 五、实施阶段（每段可独立验收）

| 阶段 | 内容 | 验收 |
|------|------|------|
| **P0 意图对齐** | 定正典意图集（以前端 15 意图为基础，保留 smart-router 环归属字段：执行/情报/治理/通用 → 映射 SACG）；角色门禁（FREE/付费）转策略表 | 意图映射表评审通过 |
| **P1 最小对话环** | 前端 1 条对话 → B1/B2 → Hermes 识别 → D1/D3 → DreamOS 只读编排（状态/分析）→ 回流 | 「分析下 BTC 当前管道状态」端到端返回结构化结果 |
| **P2 能力调用面扩展** | 白名单写操作 + 审批挂接 + clarify 歧义反问 + 高危意图确定性确认门禁 | 写操作 100% 过门禁；误识别可被 clarify 拦截 |
| **P3 前端收敛** | 废弃 4 套 TS 意图实现，前端降级为薄转发+展示；feature flag 灰度切换 | 旧实现下线，单一意图链路 |

## 六、风险（仅对话道）

| 风险 | 缓解 | 事实锚点 |
|------|------|---------|
| 意图误识别触发错误能力 | Hermes clarify 结构化反问（现成机制）+ 高危意图确定性确认（`coerce_plaintext` 先例） | Hermes 架构实测 2026-08-28 |
| 对话时延/超时 | 秒级时延对话场景可接受；保留 `enable_thinking:false` + 超时预算教训 | 前端 qwen3 思考链 15s P0 前科 |
| 过渡期新旧双实现 | chat route 已有 `intentMethod` 开关，扩展为 feature flag 灰度 | FC 地图实测 |
| DreamOS→Hermes 反向调用无标准 | 以 `hermes -z` one-shot 为临时标准，P2 定稿 | coin_selector TODO 桩实测 |

## 七、不做范围
不动四闭环自动循环与 A系列 cron；Hermes 永不直接下单（执行类意图必须经 DreamOS 能力层 + 门禁）；本提案不含代码实施。

## 八、可验证假设
P1 最小对话环走通一条端到端（前端问 → Hermes 识别 → DreamOS 只读编排 → 结构化回答），即证明「Hermes 意图 + DreamOS 物理编排 + 模块化能力」架构可行。

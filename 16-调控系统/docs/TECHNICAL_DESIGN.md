# 统一持仓离场评估系统 技术设计文档 v1.0

> **文档状态**: 设计阶段 (Design Phase)
> **创建日期**: 2026-07-12
> **版本**: v1.0
> **更新日期**: 2026-07-12
> **作者**: Dream-MultiSkill System
> **阶段**: Phase 2 — SKILL 引擎集成完成

---

## 1. 项目背景与目标

### 1.1 背景

现有实验系统包含 6 个独立交易系统（Agent A、Agent B、Agent C、三屏趋势、易经推理、V15 马丁），各自独立产生交易信号并执行下单。各系统的离场逻辑分散且自成体系，缺少一个**跨系统的、基于宏观战略判断的统一离场评估视角**。

现有离场体系的盲区：

| 离场系统 | 技术分析 | 风险事件 | 宏观基本面 | 战略趋势 | 跨系统视角 |
|---|:---:|:---:|:---:|:---:|:---:|
| ClassicExitSystem | ✅ 强 | ✅ 有 | ❌ 无 | ❌ 无 | ❌ 无 |
| exit_module.py (L1-L3) | ✅ 强 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 |
| C5 离场节点 | ✅ 中 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 |
| A9 (dream-exit-skill-v2) | ✅ 有 | ✅ 有 | ⚠️ 弱 | ❌ 无 | ❌ 无 |
| A6 (情报监控) | ✅ 有 | ✅ 有 | ✅ 有 | ⚠️ 部分 | ❌ 无 |

**核心问题**：所有离场系统都缺一个"周线/日线级别的深度战略判断"——即当前大趋势到底处于什么阶段、宏观基本面是否支持趋势延续、持仓方向与主要矛盾是否一致。

### 1.2 设计目标

| 目标 | 描述 |
|---|---|
| **统一视角** | 建立跨所有交易系统的持仓全局视图 |
| **宏观赋能** | 将 A1/A2/A3 的深度战略分析注入离场决策 |
| **四态输出** | 统一输出 平仓 / 减仓 / HOLD / 提高止盈 四种行为建议 |
| **建议制** | 阶段 0-2 只输出建议，不自动执行，避免与各系统自主离场冲突 |
| **可追溯** | 每次评估有完整的分析过程和结论记录 |
| **可演进** | 从简化版逐步升级到完整 A1/A2/A3/A9 SKILL 调用 |

### 1.3 定位边界

**本系统做什么**：
- 聚合所有交易系统的持仓数据
- 执行宏观战略分析（A1/A2/A3）
- 输出离场评估建议（四态）
- 以报告形式投递到产物通道

**本系统不做什么**：
- 不直接执行交易操作（阶段 3 后考虑）
- 不替代各系统自身的技术离场逻辑
- 不做高频实时监控（小时级以下）
- 不管理开仓决策

---

## 2. 整体架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TRAE Work 自动化任务调度层                              │
│  触发频率: 每天 2 次（08:00 / 20:00）                                     │
│  职责: 定时触发、执行历史、产物管理                                        │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         宏观分析层 (A1/A2/A3)                              │
│  输入: 全市场数据 + 历史记忆 + 做梦产物                                    │
│  输出: market_strategic_assessment.json                                   │
│         （战略方向 / 信号强度 / 主要矛盾 / 情景推演 / 建议）                │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      离场决策层 (A9 + ClassicExitSystem)                   │
│  输入: 持仓数据 + 技术指标 + 战略评估                                      │
│  输出: exit_recommendations.json                                          │
│         （平仓 / 减仓 / HOLD / 提高止盈 + 理由）                           │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          产物投递层 (AAM)                                  │
│  双通道: 秘书邮箱 + 前端产物中心                                           │
│  格式: JSON + Markdown                                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
各交易系统持仓  ──┐
                  ├─→  统一持仓查询  ──→  持仓全景图
市场行情数据    ──┘
                          │
                          ▼
              A1 深度调研（信号充分性 + 矛盾发现）
                          │
                          ▼
              A2 第一性原理（阻力最小方向 + 趋势阶段）
                          │
                          ▼
              A3 战略合成（战略方向 + 应急预案）
                          │
                          ▼
              A9 离场评估（逐持仓四态建议）
                          │
                          ▼
              产物投递（JSON + Markdown）
```

### 2.3 与现有系统的关系

| 现有系统 | 关系 | 集成方式 |
|---|---|---|
| Agent A/B/C | 持仓数据源 | Hyperliquid API + 本地 memory.json |
| V15 马丁 | 持仓数据源 | OKX API + 本地 state.json |
| 易经推理 | 持仓数据源 | OKX 模拟盘 + 本地 open_positions |
| 三屏趋势 | 持仓数据源 | 通过 Agent B 持仓间接体现 |
| ClassicExitSystem | 技术离场参考 | 后续阶段集成技术指标 |
| A6 (情报监控) | 同级互补 | A6 做小时级监控，本系统做天级战略评估 |
| A9 (离场技能) | 决策层核心 | 逐步替换简化版逻辑 |
| AAM (产物管理) | 输出通道 | 复用双通道投递规范 |

---

## 3. 统一持仓查询层设计

### 3.1 数据源矩阵

| 系统 | 交易所 | 数据来源 | 查询方式 | 状态 | 备注 |
|---|---|---|---|---|---|
| Agent A | Hyperliquid | 链上实时持仓 | REST API | ✅ Phase 1 完成 |  |
| Agent B | Hyperliquid | 链上实时持仓 | REST API | ✅ Phase 1 完成 |  |
| Agent C | Hyperliquid | 共用 B 账户 + memory.json | 文件读取 | ✅ Phase 1 完成 | 内存持仓，共用 B 的交易所账户 |
| 三屏趋势 | Hyperliquid / Aster | ml_trade_service 的 `three_screen_open_positions` | HTTP API | ⚠️ 过渡期 | 三屏是**独立策略系统**，当前委托经典系统管理持仓，未来将完全独立 |
| 易经推理 | OKX 模拟盘 | `.workbuddy/memory_l4/open_positions/*.json` | 文件读取 | ✅ Phase 1 完成 | 6 个持仓，卦象+置信度元数据完整 |
| V15 马丁 | OKX (模拟/实盘) | `v15_state.json` + OKX API | 文件读取 + API | ✅ Phase 1 完成 | 当前 0 持仓，state 文件可正常读取 |

**三屏趋势系统架构说明**：

```
当前（过渡期）                           未来（完全独立）
┌──────────────────────┐              ┌──────────────────────┐
│ 12-三屏趋势系统        │              │ 12-三屏趋势系统        │
│ （纯信号计算 = 大脑）   │              │ （信号 + 执行 + 持仓） │
└──────────┬───────────┘              └──────────┬───────────┘
           │ 信号                                    │
           ▼                                        ▼
┌──────────────────────┐              ┌──────────────────────┐
│ 10-经典指标系统        │              │ 三屏自有的执行器        │
│ ml_trade_service     │              │ 三屏自有的持仓管理      │
│ three_screen_open_   │              │ （state.json）        │
│   positions          │              └──────────────────────┘
└──────────────────────┘
```

- **当前**：三屏趋势系统是独立的策略系统（有自己的代码库、算法、文档），但执行和持仓委托给经典系统
- **未来**：三屏系统自建持仓管理和执行器，查询来源将切换为三屏自己的 state
- **统一查询层对外接口不变**：无论底层来源如何变化，`fetch_three_screen_positions()` 的输出格式保持一致

### 3.2 统一数据模型

```python
# 单个持仓
Position = {
    "system": str,           # 所属系统: agent_a / agent_b / agent_c / v15_martin / yijing_bcrm / screen_trend
    "symbol": str,           # 币种符号: BTC / ETH / ...
    "inst_id": str,          # 合约ID: BTC-USDT-SWAP (可选)
    "exchange": str,         # 交易所: hyperliquid / okx / okx_simulated
    "direction": str,        # 方向: LONG / SHORT
    "size": float,           # 持仓数量
    "entry_price": float,    # 入场均价
    "current_price": float,  # 当前价格 (可选)
    "unrealized_pnl": float, # 未实现盈亏 (USDT)
    "upl_ratio": float,      # 盈亏比例 (可选)
    "leverage": float,       # 杠杆倍数 (可选)
    "open_time": str,        # 开仓时间 ISO (可选)
    "stop_loss": float,      # 止损价 (可选)
    "take_profit": float,    # 止盈价 (可选)
    "meta": dict,            # 各系统自定义元数据
}

# 持仓全景图
UnifiedPositions = {
    "timestamp": str,              # 查询时间 ISO
    "total_systems": int,          # 系统总数
    "total_positions": int,        # 持仓总数
    "total_unrealized_pnl": float, # 总未实现盈亏
    "system_status": dict,         # 各系统查询状态 {system: ok/error}
    "systems": dict,               # 各系统详情 {system: SystemData}
    "all_positions": list[Position], # 所有持仓的扁平列表
}
```

### 3.3 查询接口设计

```python
# 统一查询入口
def fetch_all_positions() -> UnifiedPositions: ...

# 单系统查询
def fetch_agent_a_positions() -> SystemData: ...
def fetch_agent_b_positions() -> SystemData: ...
def fetch_agent_c_positions() -> SystemData: ...
def fetch_v15ct_positions() -> SystemData: ...
def fetch_yijing_positions() -> SystemData: ...
def fetch_screen_trend_positions() -> SystemData: ...

# 汇总统计
def get_position_summary() -> PositionSummary: ...
```

### 3.4 缓存与频率

| 指标 | 建议值 | 说明 |
|---|---|---|
| 查询频率 | 每次评估执行一次 | 与评估周期一致（天级） |
| 缓存策略 | 单次执行内缓存 | 同一次评估中多个模块共享同一份持仓数据 |
| 超时时间 | 单数据源 5s | 总查询不超过 30s |
| 容错模式 | 部分失败降级 | 单个系统查询失败不影响整体，标记 error 状态 |

---

## 4. 宏观分析层设计

### 4.1 三阶段分析流水线

```
A1: 深度调研
  ├── 市场状态采集（价格/趋势/波动/资金费率）
  ├── 三角准则验证（记忆/历史/当下）
  ├── 矛盾发现（≥2个矛盾对）
  └── 信号充分性评估（HIGH/MODERATE/LOW）
          ↓
A2: 第一性原理
  ├── 基本面分析（资金流/情绪/地缘/政策）
  ├── 技术面分析（趋势/动量/支撑阻力）
  ├── 宏观资产共振（黄金/原油/铜/TSLA/COIN）
  ├── 矛盾抓住（4维评分法识别主要矛盾）
  └── 阻力最小方向（UP/DOWN/NEUTRAL + 置信度）
          ↓
A3: 战略合成
  ├── 特征蒸馏
  ├── 历史模式匹配
  ├── 战略方向判断（BULLISH/BEARISH/NEUTRAL）
  ├── 应急预案（黑天鹅/极端情景）
  └── 整体立场（RAISE_TP/HOLD/REDUCE/CLOSE）
```

### 4.2 阶段演进路径

| 阶段 | A1 实现 | A2 实现 | A3 实现 |
|---|---|---|---|
| Phase 0 | 简化版（价格涨跌幅 + 信号充分性） | 简化版（阻力方向 + 趋势阶段） | 简化版（战略方向 + 整体立场） |
| Phase 1 | 接入 dream-strategy-research SKILL | 接入 dream-first-principles SKILL | 接入 dream-strategy-designer SKILL |
| Phase 2 | + 记忆系统集成 + 做梦产物 | + 宏观资产池 + 左右脑辩证 | + 历史模式 + 大师辩论 |

### 4.3 输出数据模型

```python
StrategicAssessment = {
    "timestamp": str,
    "a1_research": {
        "signal_sufficiency": str,      # HIGH / MODERATE / LOW
        "market_regime": str,           # TREND_UP / TREND_DOWN / RANGE
        "action_pressure": str,         # LOW / MEDIUM / HIGH
        "contradiction_list": list,     # 矛盾列表
        "summary": str,
    },
    "a2_first_principles": {
        "least_resistance_path": str,   # UP / DOWN / NEUTRAL
        "trend_phase": str,             # ACCELERATING / CONSOLIDATING / RANGING / REVERSING
        "confidence": str,              # HIGH / MEDIUM / LOW
        "resistance_score": float,
        "summary": str,
    },
    "a3_strategy": {
        "strategy_direction": str,      # BULLISH / BEARISH / NEUTRAL
        "overall_stance": str,          # RAISE_TP / HOLD / REDUCE / CLOSE
        "risk_level": str,              # LOW / MEDIUM / HIGH / CRITICAL
        "rationale": str,
        "summary": str,
    },
}
```

---

## 5. 离场决策层设计

### 5.1 决策框架

```
输入:
  ├── 单持仓数据（方向/入场价/盈亏/杠杆...）
  ├── 战略评估（A1/A2/A3 输出）
  └── 技术指标（后续阶段补充：RSI/ATR/MA...）

决策逻辑:
  ├── Step 1: 方向一致性检查
  │     持仓方向 vs 战略方向 → 一致 / 矛盾 / 中性
  │
  ├── Step 2: 置信度加权
  │     战略评估置信度 HIGH/MEDIUM/LOW → 影响建议强度
  │
  ├── Step 3: 四态输出
  │     CLOSE   → 方向严重矛盾 + 高置信度
  │     REDUCE  → 方向矛盾 + 中置信度
  │     HOLD    → 方向中性 / 低置信度
  │     RAISE_TP → 方向一致 + 趋势延续
  │
  └── Step 4: 理由生成
        基于上述步骤，生成可解释的决策理由
```

### 5.2 四态行为定义

| 行为 | 含义 | 触发条件（简化版） |
|---|---|---|
| **CLOSE (平仓)** | 建议全部平仓离场 | 持仓方向与战略方向相反 + 战略置信度 HIGH |
| **REDUCE (减仓)** | 建议部分减仓 | 持仓方向与战略方向相反 + 战略置信度 MEDIUM |
| **HOLD (持有)** | 维持现状不变 | 战略方向中性 / 置信度 LOW / 方向一致但无趋势加速 |
| **RAISE_TP (提高止盈)** | 建议上调止盈价位 | 持仓方向与战略方向一致 + 趋势明确 |

### 5.3 输出数据模型

```python
ExitEvaluation = {
    "version": str,
    "timestamp": str,
    "status": str,                    # completed / partial_failed / failed
    "positions_overview": {
        "total_systems": int,
        "total_positions": int,
        "system_status": dict,
    },
    "market_snapshot": dict,          # 市场数据快照
    "macro_analysis": StrategicAssessment,  # A1/A2/A3 输出
    "exit_evaluations": [
        {
            "position": Position,     # 持仓详情
            "recommended_action": str, # CLOSE / REDUCE / HOLD / RAISE_TP
            "reason": str,            # 决策理由
            "urgency": str,           # LOW / MEDIUM / HIGH / CRITICAL
            "confidence": str,        # 决策置信度
        }
    ],
    "overall_summary": {
        "total_evaluated": int,
        "close_count": int,
        "reduce_count": int,
        "hold_count": int,
        "raise_tp_count": int,
        "overall_stance": str,
        "rationale": str,
    },
    "disclaimer": str,
}
```

### 5.4 与各系统自主离场的关系

**原则：建议制，不替代**

```
各系统自主离场（技术面） ──→  执行层（直接下单）
                              ↑
                              │ 参考（可选）
                              │
统一离场评估（宏观面） ────────┘
```

- 各系统的技术离场逻辑**保持独立**，继续正常工作
- 统一离场评估输出**建议报告**，不直接触发交易
- 各系统可以选择是否采纳统一评估的建议
- 阶段 3 后考虑建立建议采纳的反馈闭环

---

## 6. TRAE Work 自动化任务接入方案

### 6.1 为什么用 TRAE Work 自动化

| 维度 | master_daemon | TRAE Work 自动化 |
|---|---|---|
| 可靠性 | ⭐⭐⭐⭐⭐ 系统级守护 | ⭐⭐⭐ 依赖 Work 运行时 |
| 执行可追溯性 | ⭐⭐ 只有日志 | ⭐⭐⭐⭐⭐ 完整对话流记录 |
| AI 分析能力 | ⭐⭐ 只能跑脚本 | ⭐⭐⭐⭐⭐ 原生 AI 代理执行 |
| 产物管理 | ⭐⭐ 需自己实现 | ⭐⭐⭐⭐ 内置产物存储 |
| 创建/修改成本 | ⭐⭐⭐ 改代码 + 重启服务 | ⭐⭐⭐⭐⭐ 对话中直接改 |
| 适合任务类型 | 高频、必须执行的交易任务 | 低频、分析型、实验性任务 |

**定位**：TRAE Work 自动化 = "带 AI 大脑的定时任务 + 完整对话流审计 + 低门槛迭代"。

### 6.2 自动化任务配置

| 配置项 | 建议值 | 说明 |
|---|---|---|
| 任务名称 | 持仓战略评估 & 离场建议 | 明确任务性质 |
| 触发方式 | 每天 2 次：08:00 和 20:00 | 覆盖亚盘和欧美盘开盘前 |
| 运行模式 | Code 模式 | 需要执行 Python 脚本和访问代码库 |
| 运行环境 | 本地 | 需要访问本地交易系统和数据 |
| 输出存储 | 6-TRADING/artifacts/exit-evaluations/ | 统一产物目录 |

### 6.3 任务执行流程

```
TRAE Work 定时触发
    │
    ▼
1. 执行 Python 脚本（phase0_exit_evaluator.py）
    │   ├── 查询统一持仓
    │   ├── 获取市场数据
    │   ├── 简化 A1/A2/A3 分析
    │   ├── 逐持仓离场评估
    │   └── 输出 JSON + Markdown
    │
    ▼
2. AI 代理补充分析（可选，阶段 1 后启用）
    │   ├── 加载 dream-strategy-research SKILL
    │   ├── 执行深度调研
    │   └── 补充报告内容
    │
    ▼
3. 产物投递
    │   ├── 写入 artifacts/exit-evaluations/
    │   ├── （可选）推送至秘书邮箱
    │   └── （可选）更新前端产物中心
    │
    ▼
完成，执行历史可查
```

### 6.4 手动触发方式

除了定时触发，也支持手动触发：
- 在 TRAE Work 自动化面板中点击"立即运行"
- 或在对话中直接要求执行一次评估

---

## 7. 产物规范

### 7.1 存储位置

```
6-TRADING/artifacts/exit-evaluations/
├── exit_evaluation_YYYYMMDD_HHMMSS.json
├── exit_evaluation_YYYYMMDD_HHMMSS.md
└── ...
```

### 7.2 文件格式

**JSON 格式**：完整的结构化数据，供程序消费
**Markdown 格式**：人类可读报告，含 frontmatter，供 AAM 投递

### 7.3 Markdown 报告结构

```yaml
---
title: "离场评估报告 - YYYY-MM-DD"
department: trading
chain_phase: A9
date: "YYYY-MM-DDTHH:MM:SS"
type: exit_evaluation
status: completed
tags: "exit-evaluation a1-a2-a3 a9"
by_a_phase: A1+A2+A3+A9
---
```

报告章节：
1. 概览（整体立场 + 理由）
2. 持仓概览（系统状态 + 持仓统计）
3. 宏观分析（A1 + A2 + A3）
4. 逐持仓评估（表格 + 详情）
5. 评估统计
6. 免责声明

### 7.4 投递通道

| 阶段 | 秘书邮箱 | 前端产物中心 |
|---|:---:|:---:|
| Phase 0 | ❌ 本地 artifacts 即可 | ❌ 本地 artifacts 即可 |
| Phase 1 | ✅ 接入 | ✅ 接入 |
| Phase 2 | ✅ 正式投递 | ✅ 正式投递 |

---

## 8. 阶段规划

### Phase 0：可行性验证 ✅ 已完成

**目标**：验证技术通路，确认端到端流程可行

**交付物**：
- ✅ 统一持仓查询模块（简化版，5 个系统）
- ✅ 阶段 0 主验证脚本（简化 A1/A2/A3 + A9）
- ✅ 产物输出（JSON + Markdown）
- ✅ 本地运行验证通过

**验证点**：
- ✅ 脚本可以独立运行
- ✅ 持仓数据可以聚合（3/5 系统成功）
- ✅ 市场数据可以获取
- ✅ 简化分析逻辑可以执行
- ✅ 产物可以输出

### Phase 1：查询层建设 ✅ 已完成

**目标**：完善统一持仓查询，覆盖所有 6 个系统，产品化

**交付物**：
- ✅ 覆盖 6 个系统的统一持仓查询模块 v1.0
- ✅ Agent A / Agent B / Agent C：Hyperliquid API + 本地 memory
- ✅ V15 马丁：state.json + OKX API（可配置密钥）
- ✅ 易经推理：`.workbuddy/memory_l4/open_positions/*.json`（6 个持仓）
- ✅ 三屏趋势：ml_trade_service HTTP API（过渡期架构，未来独立）
- ✅ 60 秒结果缓存机制
- ✅ 单系统失败降级容错（不影响整体）
- ✅ 超时控制（单源 8s，总 30s 内）
- ✅ 统一数据模型（13 个标准字段 + meta 扩展）
- ✅ `--summary` 快速摘要模式

**验收结果**：
- ✅ 6 个系统全部接入（5 个 ok + 1 个 unavailable 降级）
- ✅ 总持仓数：14 个（agent_a 2 + agent_b 6 + yijing 6）
- ✅ 查询总耗时 < 5s
- ✅ 单个系统失败不影响整体
- ✅ 三屏趋势系统定位澄清：独立策略系统，过渡期委托经典系统管理持仓

### Phase 2：分析层升级

**目标**：接入真实 A1/A2/A3 SKILL，替换简化版逻辑

**交付物**：
- 接入 dream-strategy-research (A1) SKILL
- 接入 dream-first-principles (A2) SKILL
- 接入 dream-strategy-designer (A3) SKILL
- 记忆系统集成
- 做梦产物集成
- 矛盾论 (A0) 深度集成
- 产物接入 AAM 双通道投递

**验收标准**：
- A1/A2/A3 完整 SKILL 流程可以执行
- 输出质量达到三屏系统 Screen 1/2 的分析深度
- 产物可在前端产物中心查看

### Phase 3：决策层 + 执行层（可选）

**目标**：接入 A9 完整能力，考虑与各系统执行层对接

**交付物**：
- 接入 dream-exit-skill-v2 (A9) 四层决策链
- 接入 ClassicExitSystem 技术分析
- 建立建议 → 各系统的反馈机制
- 风险控制：建议采纳权限管理
- 回测验证：宏观赋能 vs 纯技术离场的对比

**验收标准**：
- 离场决策融合宏观 + 技术双维度
- 回测表现优于纯技术离场（或至少不劣于）
- 有明确的风险控制和回退机制

---

## 9. 风险与缓解

### 9.1 技术风险

| 风险 | 严重程度 | 缓解措施 |
|---|---|---|
| TRAE Work 不运行导致任务漏执行 | ⚠️ 中 | 设置执行失败告警；master_daemon 保留技术离场兜底 |
| A1/A2/A3 分析结论不稳定 | ⚠️ 中 | 结构化验证；连续两次不一致标记"分歧"，不触发强建议 |
| 与各系统离场逻辑冲突 | 🔴 高 | 建议制，不自动执行；各系统自行决定是否采纳 |
| 多系统持仓聚合困难 | ⚠️ 中 | 分阶段建设，先易后难；降级容错 |
| 市场数据源不稳定 | ⚠️ 低 | 多源 fallback（Hyperliquid → CoinGecko → Binance → OKX） |

### 9.2 决策风险

| 风险 | 严重程度 | 缓解措施 |
|---|---|---|
| 宏观判断错误导致过早离场 | 🔴 高 | 建议制，不直接执行；技术离场仍为第一道防线 |
| 宏观判断错误导致扛单 | 🔴 高 | 硬止损由各系统技术离场保障，宏观评估只影响止盈和减仓建议 |
| 多系统持仓重复统计 | ⚠️ 中 | 建立去重规则（如 Agent C 共用 B 账户则标记归属） |

### 9.3 运维风险

| 风险 | 严重程度 | 缓解措施 |
|---|---|---|
| SKILL 调用链路复杂，排障困难 | ⚠️ 中 | TRAE Work 自动化天然有对话流记录，可追溯 |
| 评估频率过高导致 token 成本高 | ⚠️ 低 | 每天 2 次足够；完整 SKILL 调用成本较高，不宜高频 |
| 产物堆积 | ⚠️ 低 | 定期归档，保留最近 30 天 |

---

## 10. 附录

### 10.1 相关文件

| 文件 | 位置 | 说明 |
|---|---|---|
| 统一持仓查询模块 | `6-TRADING/scripts/unified_position_query.py` | Phase 0 实现 |
| 阶段 0 验证脚本 | `6-TRADING/scripts/phase0_exit_evaluator.py` | Phase 0 实现 |
| 产物目录 | `6-TRADING/artifacts/exit-evaluations/` | JSON + Markdown |
| A1 SKILL | `6-TRADING/skills/dream-strategy-research/SKILL.md` | 深度调研 |
| A2 SKILL | `6-TRADING/skills/dream-first-principles/SKILL.md` | 第一性原理 |
| A3 SKILL | `6-TRADING/skills/dream-strategy-designer/SKILL.md` | 战略合成 |
| A9 SKILL | `6-TRADING/skills/dream-exit-skill-v2/SKILL.md` | 离场决策 |
| A6 SKILL | `6-TRADING/skills/dream-intelligence-monitor/SKILL.md` | 情报监控 |
| ClassicExitSystem | `10-经典指标系统/classic_exit_system.py` | 技术离场 SSOT |
| data_server.py | `experiments/ab-trading/data_server.py` | 现有持仓查询参考 |

### 10.2 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-07-12 | 初始版本，Phase 0 完成后撰写 |

### 10.3 术语表

| 术语 | 含义 |
|---|---|
| A1 | 深度调研阶段（dream-strategy-research） |
| A2 | 第一性原理分析阶段（dream-first-principles） |
| A3 | 战略合成阶段（dream-strategy-designer） |
| A6 | 情报监控（dream-intelligence-monitor） |
| A9 | 离场决策（dream-exit-skill-v2） |
| AAM | 产物对齐管理器（artifact-alignment-manager） |
| 四态 | CLOSE / REDUCE / HOLD / RAISE_TP 四种离场行为 |
| 建议制 | 只输出建议，不自动执行的模式 |

---

## 11. Phase 2 — SKILL 引擎集成架构

### 11.1 设计理念

**代码适配层模式（code_adapter）**：将每个 SKILL 的核心逻辑封装为 Python 适配层，对外输出严格遵循 SKILL.md 规范定义的输出契约。

| 维度 | 说明 |
|---|---|
| **架构模式** | Adapter 模式，每个 SKILL 对应一个 adapter 文件 |
| **输出契约** | 与 SKILL.md 定义的输出字段完全一致 |
| **执行方式** | 本地 Python 代码直接执行，无需 LLM 调用 |
| **未来演进** | 可无缝切换为 LLM bridge 模式（调用真实 SKILL 引擎），调用方无需修改 |

**核心优势**：
- Phase 2 阶段用代码实现确定性逻辑，保证稳定性和可测试性
- 输出格式与 SKILL 规范对齐，未来切换到 LLM 驱动时零成本迁移
- 每个 adapter 独立演进，互不影响

### 11.2 核心组件

#### SkillEngine 执行引擎

SKILL 调用的统一入口，负责：
- 注册和管理所有可用的 SKILL adapter
- 统一的输入/输出格式校验
- 执行链路追踪和日志记录
- 错误处理和降级机制

```python
class SkillEngine:
    def register_skill(self, name: str, skill_fn: callable) -> None: ...
    def execute(self, skill_name: str, context: dict) -> SkillResult: ...
    def list_skills(self) -> list[str]: ...
```

#### register_skill 装饰器

用于声明式注册 SKILL adapter，简化适配器编写：

```python
@register_skill("a1_research", version="v1.7.0")
def a1_research_adapter(context: dict) -> SkillResult:
    # 执行深度调研逻辑
    return SkillResult(data=..., status="success")
```

#### SkillResult 数据结构

所有 SKILL 统一的返回结构：

```python
SkillResult = {
    "skill_name": str,
    "version": str,
    "status": str,           # success / partial_failed / failed
    "timestamp": str,
    "data": dict,            # 具体 SKILL 的输出数据
    "error": str | None,
    "duration_ms": int,
}
```

### 11.3 四层决策链详细说明

Phase 2 的离场决策采用四层递进式决策链，由 A9 离场决策模块（v2.2.0）实现：

#### Layer 1: 战略方向一致性检查

**输入**：A3 directive_bias（战略方向） vs 持仓方向

| 持仓方向 | A3 战略方向 | 一致性判定 | 基准得分 |
|---|---|---|---|
| LONG | BULLISH | ✅ 一致 | +1.0 |
| LONG | BEARISH | ❌ 矛盾 | -1.0 |
| LONG | NEUTRAL | ⚪ 中性 | 0.0 |
| SHORT | BEARISH | ✅ 一致 | +1.0 |
| SHORT | BULLISH | ❌ 矛盾 | -1.0 |
| SHORT | NEUTRAL | ⚪ 中性 | 0.0 |

**作用**：决定建议的基本方向（平仓/减仓 vs 持有/提止盈）。

#### Layer 2: 置信度加权

**输入**：A2 path_confidence（阻力最小路径置信度）

| 置信度等级 | 权重系数 | 效果 |
|---|---|---|
| HIGH | 1.5 | 放大 Layer 1 的方向信号 |
| MEDIUM | 1.0 | 标准强度 |
| LOW | 0.5 | 削弱方向信号，倾向于 HOLD |

**作用**：根据 A2 分析的置信度调整决策强度，置信度越低越保守。

#### Layer 3: 市场状态修正

**输入**：A1 market_regime（市场状态）

| 市场状态 | 调整因子 | 说明 |
|---|---|---|
| TREND_UP | +0.3 | 趋势明确，顺势持仓可更激进 |
| TREND_DOWN | +0.3 | 趋势明确，顺势持仓可更激进 |
| RANGE | -0.5 | 震荡行情，降低操作强度，倾向 HOLD |
| VOLATILE | -0.3 | 高波动，降低置信度，谨慎操作 |

**作用**：根据当前市场所处的状态（趋势/震荡/高波动）对决策进行修正。

#### Layer 4: 最终合成 + 紧急度评级

将前三层结果合成为最终建议，并给出紧急度评级：

```
final_score = (layer1_base * layer2_weight) + layer3_adjustment
```

| final_score 区间 | 建议动作 | 紧急度 |
|---|---|---|
| ≤ -1.2 | CLOSE（平仓） | CRITICAL |
| -1.2 ~ -0.5 | REDUCE（减仓） | HIGH |
| -0.5 ~ +0.3 | HOLD（持有） | LOW |
| +0.3 ~ +1.0 | HOLD + 观察趋势延续 | MEDIUM |
| ≥ +1.0 | RAISE_TP（提高止盈） | MEDIUM |

**紧急度评级**：
- `CRITICAL`：建议立即处理（如方向严重矛盾 + 高置信度 + 趋势确认）
- `HIGH`：建议尽快处理（24 小时内）
- `MEDIUM`：可以按计划处理
- `LOW`：保持关注即可

### 11.4 模块清单

Phase 2 共包含 7 个核心文件：

| 文件名 | 版本 | 说明 |
|---|---|---|
| `skill_engine.py` | — | SKILL 执行引擎框架，提供注册、执行、校验能力 |
| `a1_research_adapter.py` | v1.7.0 | A1 深度调研适配，输出信号充分性、市场状态、矛盾列表 |
| `a2_first_principles_adapter.py` | v2.6.1 | A2 第一性原理适配，输出阻力最小方向、趋势阶段、置信度 |
| `a3_strategy_adapter.py` | v2.7.0 | A3 战略合成适配，输出战略方向、整体立场、风险等级 |
| `a9_exit_decision.py` | v2.2.0 | A9 离场决策，实现四层决策链，逐持仓给出四态建议 |
| `phase2_exit_evaluator.py` | — | Phase 2 主脚本，串联完整流程，输出 JSON + Markdown 产物 |

**依赖关系**：

```
phase2_exit_evaluator.py（主入口）
    ├── skill_engine.py（引擎框架）
    ├── a1_research_adapter.py → A1 输出
    ├── a2_first_principles_adapter.py → A2 输出
    ├── a3_strategy_adapter.py → A3 输出
    └── a9_exit_decision.py → 最终离场建议
            └── 依赖 A1/A2/A3 的输出作为输入
```

### 11.5 输出格式规范

每个 SKILL adapter 的核心输出字段与 SKILL.md 规范保持一致：

#### A1 深度调研输出（a1_research）

| 字段 | 类型 | 说明 |
|---|---|---|
| `signal_sufficiency` | str | 信号充分性：HIGH / MODERATE / LOW |
| `market_regime` | str | 市场状态：TREND_UP / TREND_DOWN / RANGE / VOLATILE |
| `action_pressure` | str | 行动压力：LOW / MEDIUM / HIGH |
| `contradiction_list` | list | 矛盾列表，每项包含矛盾描述和强度 |
| `summary` | str | 调研结论摘要 |

#### A2 第一性原理输出（a2_first_principles）

| 字段 | 类型 | 说明 |
|---|---|---|
| `least_resistance_path` | str | 阻力最小方向：UP / DOWN / NEUTRAL |
| `trend_phase` | str | 趋势阶段：ACCELERATING / CONSOLIDATING / RANGING / REVERSING |
| `confidence` | str | 路径置信度：HIGH / MEDIUM / LOW |
| `resistance_score` | float | 阻力评分，数值越小阻力越小 |
| `summary` | str | 分析结论摘要 |

#### A3 战略合成输出（a3_strategy）

| 字段 | 类型 | 说明 |
|---|---|---|
| `strategy_direction` | str | 战略方向：BULLISH / BEARISH / NEUTRAL |
| `directive_bias` | str | 指令倾向：LONG_BIAS / SHORT_BIAS / NEUTRAL |
| `overall_stance` | str | 整体立场：RAISE_TP / HOLD / REDUCE / CLOSE |
| `risk_level` | str | 风险等级：LOW / MEDIUM / HIGH / CRITICAL |
| `rationale` | str | 战略判断核心理由 |
| `summary` | str | 战略结论摘要 |

#### A9 离场决策输出（a9_exit_decision）

| 字段 | 类型 | 说明 |
|---|---|---|
| `recommended_action` | str | 建议动作：CLOSE / REDUCE / HOLD / RAISE_TP |
| `urgency` | str | 紧急度：LOW / MEDIUM / HIGH / CRITICAL |
| `confidence` | str | 决策置信度：HIGH / MEDIUM / LOW |
| `reason` | str | 决策理由，包含四层决策链的关键依据 |
| `layer_scores` | dict | 四层决策链各层得分明细 |

---

## 12. 版本演进路线图

| 阶段 | 状态 | 核心目标 | 关键交付物 |
|---|---|---|---|
| **Phase 0** | ✅ 已完成 | 可行性验证 | 统一持仓查询（简化版）、简化 A1/A2/A3 + A9、产物输出验证 |
| **Phase 1** | ✅ 已完成 | 查询层建设 | 6 个系统全覆盖的统一持仓查询 v1.0、缓存与容错机制、统一数据模型 |
| **Phase 2** | 🔄 当前 | SKILL 引擎集成 | SkillEngine 框架、A1/A2/A3 code_adapter、A9 四层决策链、Phase 2 主脚本 |
| **Phase 3** | 📋 规划中 | 决策执行层 | 自动执行、AAM 投递、定时调度、建议反馈闭环、风险控制权限管理 |

### 各阶段详细说明

**Phase 0: 可行性验证**（已完成）
- 验证端到端技术通路
- 简化版分析逻辑跑通
- 产物输出格式确认

**Phase 1: 查询层建设**（已完成）
- 覆盖所有 6 个交易系统的持仓查询
- 统一数据模型和接口规范
- 容错、缓存、超时等生产级能力

**Phase 2: SKILL 引擎集成**（当前）
- 建立 SKILL 执行引擎框架
- A1/A2/A3 以 code_adapter 模式接入
- A9 四层决策链落地
- 输出质量达到 SKILL 规范标准

**Phase 3: 决策执行层**（规划中）
- 接入 TRAE Work 自动化定时调度
- 产物通过 AAM 双通道正式投递
- 探索建议 → 各系统的反馈机制
- 风险控制：建议采纳权限管理
- 回测验证：宏观赋能 vs 纯技术离场对比

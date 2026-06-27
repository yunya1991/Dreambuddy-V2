---
name: dreambuddy-os
description: |
  Dreambuddy V2 AI 驱动操作系统 — 系统级 SKILL 内核

  定位： Dreambuddy OS 的核心调度层，通过调用已有 SKILL 和 API 实现完整协作，
  本身是纯编排层，不重复建设任何能力。

  核心能力：
  1. 意图识别 — 零 Token 本地计算，6 种意图类型
  2. 架构规划（BAC 三层）— 基于 A1 Feed + 知识库 + 记忆构建蓝图/执行图/时间线
  3. 动态执行 — 三大思维链主链 + 节点动态组合 + 反思决策
  4. 自我进化 — A7/A8 实践论 + gap_score 路由 + 做梦部
  5. D-Z-E 开发链 — 自进化引擎驱动，向外学习创建新能力
  6. 预算管理 — Token 三档 + 仓位风控 + 成本核算

  验证实验： Agent B（系统架构验证组）通过执行本 SKILL 来验证整个系统设计的可行性。

  调用原则：
  - 调用的不重复建设
  - 能力清单在总架构中已存在
  - 架构检查模块可定期验证执行效果

version: 1.0.0
created: 2026-06-27
updated: 2026-06-27
license: Internal
---

# Dreambuddy OS — AI 驱动操作系统内核 SKILL (v1.0)

> 本 SKILL 是 Dreambuddy V2 的系统级调度核心，通过调用已有能力实现完整协作，不重复建设。

---

## 一、系统全景

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Dreambuddy OS 核心调度层                              │
│                                                                         │
│  意图识别 ──→ 架构规划（BAC） ──→ 动态执行 ──→ 自我进化 ──→ D-Z-E │
│       │               │                │              │            │
│       ▼               ▼                ▼              ▼            ▼    │
│   IntentGateway   ChainPlanner     ChainRouter     A7/A8       chain_  │
│                   + BAC三层         +反思决策      gap_score    guard  │
│                                    +动态链                        │
│                                                                         │
│                          ↕ 调用（纯编排，不重复建设）                    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  29个 SKILL + 970+ API端点 + 经典指标系统 + 基本面分析系统        │   │
│  │  A0-A9 · 治理系 · 情报系 · 策略系 · 风控系 · 支撑系              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、调用能力清单

### 2.1 核心能力（已验证可用）

| 能力域 | 调用路径 | 用途 |
|--------|---------|------|
| **意图识别** | `experiments/ab-trading/core/intent_gateway.py` | 6 种意图分类，零 Token |
| **BAC 图规划** | `experiments/ab-trading/core/chain_planner.py` | 四维规划，B/A/C 三层构建 |
| **动态执行** | `experiments/ab-trading/core/chain_router.py` | 节点执行 + 反思决策 + 动态链 |
| **Hyperliquid 执行** | `experiments/ab-trading/execution/aster_spot.py` | 交易下单 + 账户查询 |
| **自我进化** | `experiments/ab-trading/core/evolution_engine.py` | gap_score + A7/A8 + 做梦部 |
| **D-Z-E 开发链** | `3-CHAIN-DEVELOPMENT/scripts/chain_guard.py` | 状态管理 + 接力协议 |

### 2.2 SKILL 调用矩阵

| 系统阶段 | SKILL / 能力 | 调用方式 | 状态 |
|---------|-------------|---------|------|
| **A0 矛盾识别** | `dream-contradiction-theory` | 读取 `6-TRADING/skills/dream-contradiction-theory/SKILL.md` | ✅ |
| **A1 深度调研** | `dream-strategy-research` | 读 A1 Feed：`http://49.233.123.96:3456/feed` | ✅ |
| **A2 第一性原理** | `dream-first-principles` | 读取 `6-TRADING/skills/dream-first-principles/SKILL.md` | ✅ |
| **A3 沙盘推演** | `master-seminar` | 读取 `6-TRADING/skills/master-seminar/SKILL.md` | ✅ |
| **A4 战术验证** | `dream-tactical-validator` | 读取 `6-TRADING/skills/dream-tactical-validator/SKILL.md` | ✅ |
| **A5 决策执行** | `dream-tactical-executor` | 调用 `HyperliquidClient` | ✅ |
| **A6 情报监控** | `dream-intelligence-monitor` | 读取 `6-TRADING/skills/dream-intelligence-monitor/SKILL.md` | ✅ |
| **A7 实践论门禁** | `A7-practice-theory` | 读取 `6-TRADING/skills/A7-practice-theory/SKILL.md` | ✅ |
| **A8 知行合一** | `A8-theory-practice-verification` | 读取 `6-TRADING/skills/A8-theory-practice-verification/SKILL.md` | ✅ |
| **A9 离场决策** | `dream-exit-skill-v2` | 读取 `6-TRADING/skills/dream-exit-skill-v2/SKILL.md` | ✅ |
| **三屏交易** | `dream-screen1/2/3` | 读取 `6-TRADING/skills/dream-screen{1,2,3}-{first,second,third}/SKILL.md` | ✅ |
| **BAC 图压缩** | `graph-compressor` | 读取 `6-图结构上下文压缩/skills/graph-compressor/SKILL.md` | ✅ |
| **治理闭环** | `dream-constitution` 等 | 读取 `6-TRADING/skills/dream-constitution/SKILL.md` 等 | ✅ |
| **D-Z-E 开发链** | `chain_guard.py` | subprocess 调用 `python3 chain_guard.py <cmd>` | ✅ |

### 2.3 API 端点（按域调用）

| 域 | 基础路径 | 主要端点 |
|---|---------|---------|
| **经典指标系统** | `http://127.0.0.1:8092` | 14 指标 + 7 策略 + 回测 + 评估 |
| **基本面分析** | `http://49.233.123.96:3456` | 情绪/信号/资金流/新闻/宏观 |
| **A1 产物中心** | `http://49.233.123.96:3456/feed` | 调研报告输入 |

---

## 三、工作流程

### 第一步：意图识别（零 Token）

**输入**：市场数据 + 记忆 + 知识库

**处理**：
```python
from core.intent_gateway import detect_intent, IntentResult

intent: IntentResult = detect_intent(mkt, memory)
# intent.intent_type: TREND_FOLLOWING / MEAN_REVERSION / FUNDAMENTAL_PLAY / BREAKOUT / KNOWLEDGE_MATCH / UNCERTAIN
# intent.confidence: 0.0-1.0
# intent.base_chain: 推荐主链节点序列
# intent.extend_nodes: 扩展节点池
```

**输出**：IntentResult（意图类型 + 置信度 + 主链 + 扩展池）

**调用文件**：`experiments/ab-trading/core/intent_gateway.py`

---

### 第二步：架构规划 — BAC 三层构建

**输入**：IntentResult + A1 Feed + 知识库 + 记忆

#### B 层：Blueprint（蓝图）

**处理**：读 A1 Feed 作为核心输入
```python
import requests

feed = requests.get("http://49.233.123.96:3456/feed", timeout=10).json()
# 解析 feed 中的 A1 调研报告内容 → B 层市场判断 + 策略方向
```

**结合**：
- 知识库检索：`chain_planner.py` → `_check_knowledge_base()`
- 记忆库：`agent_b_memory.json`
- regime 模式：`regime_patterns/`

**B 层输出**：
```python
blueprint = {
    "id": "bp_{timestamp}",
    "name": "交易决策蓝图",
    "objective": "赚更多的钱",
    "market_judgment": "...",   # 基于 A1 Feed 的市场判断
    "strategy_direction": "...", # 策略方向
    "confidence": 0.xx,
    "regime": "TREND_UP / TREND_DOWN / RANGE"
}
```

#### A 层：Architecture（执行图）

**处理**：ChainPlanner 四维规划
```python
from core.chain_planner import ChainPlanner

planner = ChainPlanner(token_budget=6000)
plan = planner.plan(intent, mkt, memory)
# plan.planned_chain   : 最优节点序列
# plan.pruned_nodes    : 剪枝记录 + 原因
# plan.added_nodes     : 主动追加节点
# plan.budget_mode     : full / standard / lean
# plan.estimated_tokens: 预估消耗
# plan.plan_rationale  : 规划理由
```

**四维过滤**：
1. Token 预算 → 决定模式（full/standard/lean）
2. 知识库命中 → 高分策略走快捷路径
3. 历史表现 → 当前 Regime 下节点命中率
4. 标的覆盖 → 小币/冷门标的节点处理

**A 层输出**：
```python
architecture = {
    "id": "arch_{timestamp}",
    "blueprint_id": blueprint["id"],
    "planned_chain": ["C1_技术扫描", "F2_资金流", "A2_分析(含A0)", "A4_门禁"],
    "node_trace": [...],  # 每节点元信息
    "budget_mode": "standard",
    "estimated_tokens": 4800
}
```

#### C 层：Chronicle（时间线预留）

每步执行后写入执行记录（见第三步）。

---

### 第三步：动态执行（ChainRouter）

**输入**：A 层planned_chain + 市场数据 + 记忆

**处理**：逐节点执行 + 反思决策
```python
from core.chain_router import ChainRouter

router = ChainRouter(client, mkt, memory, intent, BUDGET_USDC)
chain_result = router.execute()
# chain_result.final_action    : LONG / SHORT / HOLD
# chain_result.final_confidence: 0.0-1.0
# chain_result.gate_passed      : True / False
# chain_result.gate_reason      : 门禁理由
# chain_result.position_size_usdt: 仓位大小
# chain_result.stop_loss        : 止损价
# chain_result.take_profit      : 止盈价
# chain_result.node_trace       : 每步执行记录（C层）
```

**反思决策类型**：

| 决策 | 条件 | 动作 |
|------|------|------|
| `CONTINUE` | 正常推进 | 执行下一步 |
| `REDO` | confidence < 0.55 或 risk > 0.7 或 issues >= 2 | 重做当前步 |
| `INSERT_BEFORE` | 缺少必要信息（无止损/止盈） | 插入补充节点 |
| `JUMP_TO` | 高置信度(≥0.78) + 无 issues | 跳过后续验证 |
| `EARLY_TERMINATE` | 基本完成 + avg_conf ≥ 0.65 | 提前终止 |

**C 层写入**：
```python
# 每步执行后自动写入 graph_compressor
c_node = {
    "id": f"c_{node_id}_{timestamp}",
    "architecture_node_id": node_id,
    "execution_id": cycle_id,
    "start_time": start_ms,
    "end_time": end_ms,
    "inputs": {...},
    "outputs": {...},
    "confidence": 0.xx,
    "decision": "CONTINUE / REDO / ...",
    "logs": [...]
}
```

---

### 第四步：自我进化（盈亏驱动）

#### 4.1 A7 实践论门禁

```python
# 读取 A7-practice-theory SKILL
with open("6-TRADING/skills/A7-practice-theory/SKILL.md") as f:
    a7_content = f.read()
# 应用 A7 门禁逻辑：
# - 置信度 < 门槛 → HOLD
# - 连败 >= 3 → 强制观望
# - 最大回撤 >= 15% → 暂停交易
```

#### 4.2 A8 知行合一验证

```python
# 读取 A8-theory-practice-verification SKILL
with open("6-TRADING/skills/A8-theory-practice-verification/SKILL.md") as f:
    a8_content = f.read()
# gap_score 计算：
# gap = abs(理论置信度 - 实际执行置信度)
# gap >= 0.5 → A1 重启调研（严重背离）
# gap 0.3-0.5 → A2 更新分析（中度背离）
# gap < 0.3 → A3 策略优化（轻微背离）
```

#### 4.3 做梦部（Oneirology）

```python
# 读取 dream-oneirology SKILL
with open("6-TRADING/skills/dream-oneirology/SKILL.md") as f:
    oneirology_content = f.read()
# 触发条件：
# - 连续 SKIP >= 3 次
# - 置信度 55-64% 反复被拦
# - gap_score < 0.3
# 五大机制：强迫性重复 / 反事实推演 / 凝缩检测 / 移置检测 / 投射还原
```

#### 4.4 Episode → Lesson

```python
# learning-episode-writer：每笔（含 HOLD）记录
# learning-lesson-distiller：提炼教训，入库（上限 20 条）
# 评分 = 普适性(1-5) × 重要性(1-5)，<10 分淘汰
```

---

### 第五步：D-Z-E 开发链（向外学习）

**触发条件**：
- 做梦部发现新能力需求
- gap_score ≥ 0.5（严重背离）
- Lesson 提炼出系统性改进

**调用方式**：
```python
import subprocess
import os

CHAIN_DEV_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-CHAIN-DEVELOPMENT/scripts"
STATE_FILE = os.path.expanduser("~/.workbuddy/memory/chain_state.json")

# 初始化新任务
result = subprocess.run(
    ["python3", "chain_guard.py", "init", "新能力开发任务描述"],
    cwd=CHAIN_DEV_PATH,
    capture_output=True, text=True
)

# 阶段跳转（需遵守接力协议）
# D1 → D2 → D3 → D4 → Z1 → Z2 → Z3 → Z4 → E1 → E2 → E3
result = subprocess.run(
    ["python3", "chain_guard.py", "transition", "d1", "d2"],
    cwd=CHAIN_DEV_PATH
)
```

**D-Z-E 各阶段职责**：

| 阶段 | 职责 | 产出 |
|------|------|------|
| D1 深度调研 | 代码现状/依赖/历史/外部方案 | 现状调查报告 |
| D2 分析诊断 | 根因链/矛盾识别/方案矩阵 | 根因分析与方案矩阵 |
| D3 推演验证 | 方案A/B/C三景推演/风险评估 | 多方案推演报告 |
| D4 Spec合成 | 方案论证/Spec编写/验收标准 | 完整Spec文档 |
| Z1-Z4 | 架构/边界/路径/验收 | 实施计划 |
| E1-E3 | 执行/测试/部署 | 交付产物 |

---

### 第六步：预算管理

#### Token 三档

| 档位 | 上限 | 适用场景 |
|------|------|---------|
| `lean` | 3,000 t | 信号弱/震荡/高 HOLD 率 |
| `standard` | 6,000 t | 正常交易决策（默认） |
| `full` | 10,000 t | 强信号/UNCERTAIN 意图 |

#### 仓位风控

```python
equity = client.get_account()["equity"]

# 单笔仓位
position_size = max(equity * 0.05, 5)  # 5% 或最小 $5

# 杠杆
leverage = min(5, max(1, int(final_confidence * 5)))

# 止损止盈
stop_loss = entry_price * (1 - 0.04)    # 4% 止损
take_profit = entry_price * (1 + 0.08) # 8% 止盈

# 最大持仓
max_position = equity * 0.20  # 不超过账户 20%
```

---

## 四、执行输出格式

### 4.1 决策日志（DecisionLog）

```python
log = {
    "cycle_id": "20260627_143000",
    "agent": "Agent B",
    "timestamp": "2026-06-27T14:30:00Z",
    "source": "dreambuddy-os v1.0",

    "intent": {
        "type": "TREND_FOLLOWING",
        "confidence": 0.72
    },

    "bac": {
        "blueprint_id": "bp_20260627_143000",
        "architecture_id": "arch_20260627_143000",
        "planned_chain": ["C1", "F2", "A2(含A0)", "A4"],
        "budget_mode": "standard",
        "estimated_tokens": 4800
    },

    "execution": {
        "action": "LONG",
        "coin": "BTC",
        "leverage": 3,
        "entry_price": 65000.0,
        "position_size_usdt": 6.0,
        "stop_loss": 62400.0,
        "take_profit": 70200.0,
        "confidence": 0.74,
        "gate_passed": True,
        "gate_reason": "A7门禁通过"
    },

    "market_snapshot": {
        "coin": "BTC",
        "price": 65000.0,
        "change_24h": 3.2,
        "rsi_14": 62.5,
        "funding_rate": 0.00012
    },

    "self_evolution": {
        "win_streaks": 2,
        "loss_streaks": 0,
        "gap_score": 0.15,
        "lessons_count": 8,
        "dream_triggered": False
    },

    "node_trace": [
        {"node_id": "C1", "confidence": 0.70, "direction": "LONG"},
        {"node_id": "F2", "confidence": 0.68, "direction": "LONG"},
        {"node_id": "A2(含A0)", "confidence": 0.72, "direction": "LONG"},
        {"node_id": "A4_门禁", "confidence": 0.74, "direction": "LONG", "gate": "PASS"}
    ]
}
```

### 4.2 PR 评论格式

```
🤖 **Agent B 交易报告** | 2026-06-27 14:30 (CST)

**系统**：Dreambuddy OS v1.0
**意图**：{意图类型} | **置信度**：{xx}%
**决策**：{LONG / SHORT / HOLD}
**大师风格**：系统架构验证（无大师切换）

{if 开仓：
**标的**：{BTC/ETH}
**方向**：{多/空}
**杠杆**：{x}x
**仓位**：${金额}
**止损**：{价格} ({pct}%)
**止盈**：{价格} ({pct}%)
}

**市场快照**：
1. {币1} — 24H {±x.x%}，RSI {xx}
2. {币2} — 24H {±x.x%}，RSI {xx}
3. {币3} — 24H {±x.x%}，RSI {xx}

**BAC 执行链路**：{节点序列}
**Token 消耗**：~{xxxx}t（{budget_mode}模式）

**连胜/连败**：{连胜N场 / 连败N场}
**gap_score**：{0.xx}
**Lessons**：{N条}
```

---

## 五、环境与依赖

### 5.1 环境变量

| 变量 | 用途 | 必需 |
|------|------|------|
| `HYPERLIQUID_API_KEY` | Hyperliquid 签名 | ✅ |
| `HYPERLIQUID_API_SECRET` | Hyperliquid 签名私钥 | ✅ |
| `AGENT_B_ASTER_USER` | Agent B 钱包地址 | ✅ |
| `AGENT_B_ASTER_SIGNER` | 签名地址 | ✅ |
| `AGENT_B_ASTER_SIGNER_PRIVATE_KEY` | 签名私钥 | ✅ |
| `TAVILY_API_KEY` | 消息面检索 | ✅ |
| `AUTO_EXECUTE` | 是否实盘执行（true/false） | ✅ |
| `TOKEN_BUDGET` | Token 预算（默认 6000） | 否 |
| `PER_TRADE_PCT` | 单笔仓位比例（默认 0.05） | 否 |

### 5.2 目录依赖

| 路径 | 用途 |
|------|------|
| `experiments/ab-trading/core/` | 核心引擎 |
| `experiments/ab-trading/execution/` | 交易执行 |
| `experiments/ab-trading/data/` | 记忆/图数据 |
| `6-TRADING/skills/` | A 系列 SKILL |
| `6-图结构上下文压缩/` | BAC 图架构 |
| `3-CHAIN-DEVELOPMENT/scripts/` | D-Z-E 开发链 |
| `10-经典指标系统/` | 经典指标 API |
| `9-基本面分析/` | 基本面分析 API |

### 5.3 外部接口

| 接口 | 用途 | 密钥 |
|------|------|------|
| `http://49.233.123.96:3456/feed` | A1 产物中心 | 无 |
| `http://127.0.0.1:8092` | 经典指标系统 | 无 |

---

## 六、Agent B vs Agent A

| 维度 | Agent A | Agent B |
|------|---------|---------|
| **定位** | LLM 驱动实战交易 | Dreambuddy OS 系统架构验证 |
| **决策模式** | LLM 主 + 规则兜底 | **完整 Dreambuddy OS 工作流** |
| **SKILL 体系** | 独立 `agent-a-trading` SKILL | **调用系统级 `dreambuddy-os` SKILL** |
| **工作流** | 六步 + LLM | **BAC + 动态链 + 自进化 + D-Z-E** |
| **目的** | 实盘赚钱 | 验证系统设计可行性 |
| **对比实验** | 对照组 | 实验组 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-06-27 | 初始版本，Dreambuddy OS 内核 SKILL |

---
name: dream-tactical-executor
description: |
  ⚡ 战术执行 — **综合判断决策执行**
  
  **【v3.5定位】**
  
  A5 = 根据A4验证报告 + A6情报，综合判断并执行
  
  **【v3.5核心链路】**
  
  A4验证报告 → A6情报 → 综合判断 → 决策执行 → 仓位同步
  
  **【自动化闭环】**
  
  - A4确定性高 (SI≥±30+Edge同向≥20) → 内置A5自动执行
  - A4确定性不高 → 等待A5综合判断（A4+A6）
  
  **【约束条件】**
  
  - 完整链路: A1→A2→A3→A4 必须就位
  - A7实践论门禁检查
  - RM顾问评审否决权
  
  触发词：战术执行、生成信号、执行信号、入场点位、止损止盈、大仓入场、下单前检查、交易检查、执行前请顾问确认、A5自主执行、实践论、实践指导、真理标准、实践验证、A4联动、确定性联动、A4触发A5
license: Internal
version: 3.8.0
created: 2026-04-20
updated: 2026-04-29
---

# ⚡ Dream-Tactical-Executor: 战术执行部 (v3.8)

## 【合规要求】⭐ v3.8 新增

### §合规 问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §合规 常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规 违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

## ⚡ A7 强制调度门禁 (P0 Fix v2.6 → v3.6 独立验证)

> **⚠️ 强制执行**: 本SKILL必须在执行下单前首先调用A7实践论
> 
> **⚠️ v3.6 升级 (2026-04-28 A8修复)**:
> A7门禁从"自我评分"升级为**INDEPENDENT_AUTO独立自动验证**。
> A8验证(EP68)确认`verification_type: "INDEPENDENT_AUTO"`已存在，
> 现在正式文档化并强化为**强制标准流程**。

### Phase 0: A7实践论强制调用 (v3.6 INDEPENDENT_AUTO)

**必须首先执行以下操作（不可跳过）：**

```python
# ═════════ Step 0.0: 调用A7实践论SKILL（必须首先执行！）═════════
use_skill("A7-practice-theory")

# ═════════ Step 0.1: 独立自动验证 (INDEPENDENT_AUTO) ═════════
# ⚠️ v3.6: 不再是A5自我评分，而是基于客观数据的独立验证

a7_gate = {
    "verification_type": "INDEPENDENT_AUTO",     # ← 强制: 非SELF_SCORE
    "timestamp": "ISO8601",
    "episode_count_4h": <count_recent_episodes>, # ← 最近4h内episode数量
    "checks": {
        # C1: 认识来源充分性 — 基于episode数据自动判定
        "verification_sufficiency": "PASS|FAIL",
        "_rule": "最近4h episode≥2个 → PASS, <2个 → FAIL",
        
        # C2: 认识正确性 — 基于A4侦察报告交叉验证
        "knowledge_correctness": "PASS|FAIL",
        "_rule": "A4结论与当前行情偏差<5% → PASS, ≥10% → FAIL",
        
        # C3: 执行纪律 — 基于历史episode执行率
        "execution_discipline": "PASS|FAIL",
        "_rule": "最近3次episode中执行纪律违规=0 → PASS",
        
        # C4: 风险可控 — 基于账户状态客观检查
        "risk_controllable": "PASS|FAIL",
        "_rule": "杠杆≤MAX且浮亏<5% → PASS, 杠杆>MAX或浮亏≥5% → FAIL",
        
        # C5: 反馈机制 — 基于episodes目录写入频率
        "feedback_mechanism": "PASS|FAIL",
        "_rule": "最近24h有新episode写入 → PASS"
    },
    "overall": "PASS|FAIL",  # 全部5项PASS → 总体PASS
    "fail_reason": "<string if any check FAILED>"  # 失败原因(仅FAIL时)
}
```

**⚠️ INDEPENDENT_AUTO vs SELF_SCORE 对比：**

| 维度 | SELF_SCORE(旧) | INDEPENDENT_AUTO(新·v3.6) |
|:---|:---|:---|
| **验证者** | A5自己打分 | 基于episode/行情/账户**客观数据** |
| **episode_count_4h** | 无 | ✅ 必填，统计最近4h episode数 |
| **C1判定规则** | 主观判断 | episode数量阈值自动判定 |
| **C4风险检查** | 无 | 杠杆+浮亏客观阈值 |
| **可审计性** | 低(依赖A5自觉) | **高**(数据可追溯) |
| **A8可信度** | ❌ 自我评分无效 | ✅ 独立验证有效 |

**门禁检查清单（必须逐项确认）：**
- [ ] `use_skill("A7-practice-theory")` 已执行
- [ ] `verification_type = "INDEPENDENT_AUTO"` (非SELF_SCORE)
- [ ] `episode_count_4h` 已填写实际数值
- [ ] 5项checks均有`_rule`字段说明判定依据
- [ ] A7实践论门禁 overall = **PASS**
- [ ] 报告中的a7_gate包含完整JSON(非简写形式)
- [ ] 铁律检查遵循A7的实践论指导

**违规处理**: 
- 若跳过Phase 0 → `a7_integration=FAILED`, A8 P0告警
- 若使用SELF_SCORE → `a7_verification_type=INVALID`, A8 P1告警
- 若任何check为FAIL但overall=PASS → `a7_check_inconsistency`, A8 P1告警

---

## 核心职能

> "侦察成功则大举入场，侦察失败则按兵不动"

## ⚠️ 铁律：完整链路前置检查（不可绕过）

> **战术执行绝不是盲目的。任何下单前，必须确认A1→A2→A3→A4的完整决策链路已经就位。**

### 铁律一：战略复盘预演（A1→A2→A3 必须齐全）

| 环节 | 对应SKILL | 产出物 | 缺失处理 |
|:---|:---|:---|:---|
| **A1 深度调研** | `dream-strategy-research` | 调研报告（含做梦产物交叉验证） | 创建临时任务驱动A1执行 |
| **A2 第一性原理** | `dream-first-principles` | 阻力/趋势分析报告 | 创建临时任务驱动A2执行 |
| **A3 战略制定** | `dream-strategy-designer` | 战略指令（strategy_directive） | 创建临时任务驱动A3执行 |
| **A4 战术验证** | `dream-tactical-validator` | 侦察报告（scout_report） | 创建临时任务驱动A4执行 |

### 铁律二：侦察实践（A4 火力侦探必须有）

- A4的侦察是小仓试探市场脾气，验证A3战略方向是否正确
- **没有A4侦察报告 = 不能大仓入场**，最多只能执行侦察仓（10-15%）
- 如果A4侦察数据过时（>4小时），必须重新驱动A4执行

### 铁律三：重要事件驱动战略更新

当出现以下情况时，**必须先创建临时任务驱动A1-A3重新评估**，不能沿用旧战略：

| 重要事件类型 | 示例 | 必须动作 |
|:---|:---|:---|
| 🚨 地缘突发事件 | 停火破裂/军事冲突升级 | 驱动A1调研+A2分析+A3更新战略 |
| 📊 宏观数据发布 | FOMC/CPI/NFP等重大数据 | 驱动A1调研+A2分析 |
| 📈 Regime转换 | TREND→RANGE / RANGE→BREAKOUT | 驱动A3重新评估战略 |
| 💰 资金费率异变 | 从正转负/负转正/绝对值>0.05% | 驱动A2分析 |
| 🌊 极端行情 | 1H涨跌>5% / 闪崩/插针 | 驱动A1+A2+A3全链路 |
| 🔄 做梦部重大洞察 | 噩梦场景+矛盾图谱触发 | 驱动A1交叉验证+A2分析 |

### 铁律四：顾问评审最终确认 (v2.6 更新)

> **A5执行前必须确认顾问评审已通过**
>
> **⚠️ v2.6 架构变更**: 顾问评审统一使用 `advisor_direct_call` 模块内联调用。

**调用方式**:
```python
import sys
sys.path.insert(0, str(Path.home() / ".workbuddy" / "advisor-team" / "shared"))
from advisor_direct_call import advisors_review

# A5 执行前 RM 最终风险确认
result = advisors_review(
    consultation_id=f"A5-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    scene="RISK_REVIEW",
    required_advisors=["advisor-rm"],
    context={
        "a3_strategy": { "direction": "...", "instrument": "..." },
        "a4_scout_report": { "conclusion": "SUCCESS/PENDING/FAILED" },
        "current_price": 85000,
        "position_size": 100,
        "account_status": { ... },
    },
    source="dream-tactical-executor"
)

verdict = result["summary"]["final_verdict"]
# DISAGREE → SKIP，禁止执行
# AGREE/PARTIAL → 继续执行
```

**检查流程**:
```
A5执行前扫描交易邮箱 (reports/trading/):
1. 检查A1-A3报告末尾的顾问评审章节
2. 验证评审时效: 评审时间戳 < 4h
3. 验证评审结论: verdict != DISAGREE
```

**评审来源**:
- A1: Phase 5顾问评审 (QT+RM)
- A2: Phase 8顾问评审 (MR+TR)
- A3: Phase 8顾问评审 (SC+QT)

**无评审处理**:
- 如果交易邮箱中A1-A3报告无顾问评审 → 召唤 ADVISOR-RM 执行最终风险确认
- RM确认 verdict=DISAGREE → SKIP，禁止执行
- RM确认 verdict=AGREE/PARTIAL → 继续执行

**RM最终确认输入**:
```
执行摘要:
- A3战略指令: [方向/币种/工具]
- A4侦察结论: [成功/待定/失败]
- 当前市场: [价格/波动率]
- 账户状态: [余额/持仓/PnL]

请输出:
- verdict: AGREE/DISAGREE/PARTIAL
- confidence: 0-100
- final_position_cap: "X%"
- circuit_breakers: [熔断条件]
```

> **⚠️ 原则: RM拥有一票否决权，任何时刻verdict=DISAGREE都必须SKIP**

### 铁律五：A7实践论门禁检查 (v2.5 新增)

> **A5执行前必须通过A7实践论门禁检查**

**检查项**:
```
1. 验证充分性: A4验证是否充分? (样本≥3-5次)
2. 认识正确性: A4反馈是否修正了认识? 
3. 执行纪律: 是否有明确的执行纪律和止损?
4. 风险可控: 实践风险是否在可接受范围?
5. 反馈机制: 是否有实时反馈机制?
```

**门禁结果**:
- PASS → 继续执行A5
- FAIL → 返回A4重新验证 或 重新A1-A3

**调用方法**:
```
在A5执行流程第一步，调用 use_skill a7-practice-theory
读取 A7-practice-theory/workflows/practice_execute.md
执行 A7门禁检查
```

## ⚡ A5自主执行权限说明 (v2.4 新增)

> **用户授权**: A5有自主决策权可直接落地执行，无需每次人工确认

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    A5 自主执行权限说明                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  【自主执行条件】                                                        │
│  ├── 1. A1-A3链路完整（报告新鲜度<4h）                                  │
│  ├── 2. A4侦察报告存在（验证方向正确性）                                │
│  ├── 3. 顾问评审 verdict != DISAGREE                                    │
│  └── 4. 门禁检查全部通过 (dream-pretrade-gatekeeper)                   │
│                          ↓                                              │
│  【满足条件】→ 自主执行大仓 (30-40%)                                    │
│  【不满足】→ 创建临时任务补齐，等待链路完整                             │
│  【否决】→ verdict=DISAGREE → SKIP，禁止执行                            │
│                          ↓                                              │
│  【约束红线】(违反立即停止)                                              │
│  ├── ❌ 链路不完整时执行大仓                                            │
│  ├── ❌ verdict=DISAGREE时执行                                          │
│  ├── ❌ 门禁检查失败时执行                                              │
│  └── ❌ 无止损设置直接开仓                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 交易邮箱（决策链路产出物专用）

> A1-A5的决策链路产出物统一存放在交易邮箱，A5执行前先检查此目录。

| 项目 | 值 |
|:---|:---|
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **所属** | 秘书邮箱子目录 |
| **用途** | 存放A1-A5完整决策链路报告 |

#### 文件命名规范

| 环节 | 文件名格式 | 示例 |
|:---|:---|:---|
| A1 调研 | `a1_research_{YYYYMMDD}_{HHMM}.md` | `a1_research_20260422_1600.md` |
| A2 第一性原理 | `a2_first_principles_{YYYYMMDD}_{HHMM}.md` | `a2_first_principles_20260422_1620.md` |
| A3 战略指令 | `a3_strategy_{YYYYMMDD}_{HHMM}.md` | `a3_strategy_20260422_1640.md` |
| A4 战术侦察 | `a4_scout_{YYYYMMDD}_{HHMM}.md` | `a4_scout_20260422_1700.md` |
| A5 执行报告 | `a5_execution_{YYYYMMDD}_{HHMM}.md` | `a5_execution_20260422_1710.md` |
| 链路摘要 | `chain_summary_{YYYYMMDD}_{EPN}.md` | `chain_summary_20260422_EP49.md` |

#### A5检查逻辑

```
A5执行前，扫描 trading/ 目录：
1. search_file("a1_research_*.md") → 检查最新A1报告
2. search_file("a2_first_principles_*.md") → 检查最新A2报告
3. search_file("a3_strategy_*.md") → 检查最新A3报告
4. search_file("a4_scout_*.md") → 检查最新A4报告
5. 检查报告时间戳是否<4h（数据新鲜度）
```

### 执行前检查流程

```
A5收到执行指令
    ↓
检查交易邮箱 reports/trading/ 中A1-A4链路完整性
    ├── 全部齐全 + 数据新鲜(<4h) → 继续执行流程
    ├── 缺少A1 → 创建临时任务 16:00 "A5-EP{N}-A1-Research" → SKIP等待
    ├── 缺A2 → 创建临时任务 16:20 "A5-EP{N}-A2-Analysis" → SKIP等待
    ├── 缺A3 → 创建临时任务 16:40 "A5-EP{N}-A3-Strategy" → SKIP等待
    ├── 缺A4 → 创建临时任务 17:00 "A5-EP{N}-A4-Scout" → SKIP等待
    ├── 全部缺失 → 按时间串行创建 A1→A2→A3→A4 四个临时任务
    ├── 数据过时(>4h) → 创建临时任务刷新 → SKIP等待
    └── 有重要事件未评估 → 创建临时任务驱动A1-A3 → SKIP等待
    ↓
⭐ 新增: 检查A1-A3报告中的顾问评审章节
    ├── 有顾问评审 + verdict!=DISAGREE → 使用评审结论继续
    └── 无评审或verdict=DISAGREE → 召唤 ADVISOR-RM 最终确认 → SKIP等待
    ↓
门禁检查（7项）
    ↓
执行下单
    ↓
生成 chain_summary_*.md 链路摘要
```

### 临时任务驱动缺失环节

当A1-A4链路有缺失时，A5必须按以下优先级和时间线创建临时任务补齐：

```
全部缺失时（标准时间线）:
  16:00 A1调研 → 16:20 A2原理 → 16:40 A3战略 → 17:00 A4侦察 → 17:10 A5执行

部分缺失时（只补缺失环节）:
缺失A1 → 创建 "A5-EP{N}-A1-Research" 一次性任务（T+0）
缺失A2 → 创建 "A5-EP{N}-A2-Analysis" 一次性任务（T+20min）
缺失A3 → 创建 "A5-EP{N}-A3-Strategy" 一次性任务（T+40min）
缺失A4 → 创建 "A5-EP{N}-A4-Scout" 一次性任务（T+60min）
重要事件 → 创建 "A5-EP{N}-A1A2A3-Recalibrate" 一次性任务
```

> **原则：宁可多等10分钟补齐链路，不可盲目下单。**

## 战略 vs 战术 vs 执行 分工

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    三层决策架构                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  📊 战略层 (A3)                                                        │
│  └── 问题: "往哪走？" → LONG / SHORT / WAIT                          │
│                          ↓                                              │
│  🔬 战术层 (A4)                                                        │
│  └── 问题: "能用吗？" → 侦察成功 / 待定 / 失败                        │
│                          ↓                                              │
│  ⚡ 执行层 (A5) ← 当前                                                 │
│  └── 问题: "下多少？" → 侦察仓 / 大仓 / 不下                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 输入（必须字段）

| 字段 | 类型 | 来源 | 说明 |
|:---|:---|:---|:---|
| `strategy_directive` | object | A3 | 战略指令 |
| `scout_report` | object | A4 | 侦察报告 |
| `phase7_contingency` | object | Phase7 | 应急预案 |
| `market_state` | object | 实时 | 当前市场状态 |
| `current_price` | number | OKX | 当前价格 |
| `current_atr` | number | 计算 | 当前ATR值 |

---

## 输出（必须结构化）

```json
{
  "execution_signal": {
    "signal_id": "EXEC_20260421_001",
    "signal_type": "SCOUT_ENTRY|LARGE_ENTRY|SKIP",
    "wave_position": "1浪|2浪|3浪",
    "signal_confidence": 0.0-1.0,
    "generation_time": "ISO时间戳",
    "valid_until": "ISO时间戳",
    "reason_codes": ["SCOUT_SUCCESS", "TREND_CONFIRMED"]
  },
  
  "execution_size": {
    "size_type": "SCOUT|LARGE",
    "size_pct": 0.10,
    "direction": "LONG|SHORT",
    "contracts": 1,
    "leverage": 2,
    "notional_usdt": 150,
    "rationale": "侦察成功，执行大仓"
  },
  
  "entry_plan": {
    "trigger_type": "MARKET|LIMIT|STOP",
    "trigger_conditions": ["价格回踩至73500"],
    "entry_price": 73500,
    "limit_offset": -0.002
  },
  
  "risk_management": {
    "stop_loss": {
      "type": "触发价",
      "trigger_price": 72090,
      "max_loss_usdt": 70,
      "max_loss_pct": 0.01
    },
    "take_profit": [
      {"level": 1, "trigger_price": 75000, "close_pct": 30},
      {"level": 2, "trigger_price": 76000, "close_pct": 40},
      {"level": 3, "trigger_price": 77000, "close_pct": 30}
    ],
    "trailing_stop": {
      "enabled": true,
      "activation": "level_2_reached",
      "distance": 0.02
    }
  },
  
  "wave_tracking": {
    "current_wave": "3浪",
    "wave_target": "3浪目标: 77000-78000",
    "next_wave": "4浪回踩",
    "wave_stop_loss": 75500
  },
  
  "contingency_check": {
    "black_swan_alert": false,
    "deviation_score": 0.2,
    "contingency_plan": null
  },
  
  "monitoring_plan": {
    "checkpoints": [
      {"time": "T+15min", "check": "是否按预期运行"},
      {"time": "T+1h", "check": "1浪是否完成"},
      {"time": "T+4h", "check": "是否进入2浪回踩"}
    ],
    "adjustment_rules": [
      "若1h内上涨>2%，考虑提前启动追踪止损",
      "若回踩破2浪支撑，立即止损"
    ],
    "exit_conditions": [
      "触及止损",
      "触及止盈",
      "黑天鹅触发应急预案"
    ]
  }
}
```

---

## 执行决策矩阵

### 基于侦察报告的执行决策

| 侦察结果 | 侦察仓位 | 大仓仓位 | 执行动作 |
|:---|:---:|:---:|:---|
| **侦察成功 (1浪+2浪验证)** | 已完成 | 30-40% | 执行大仓 |
| **侦察成功 (仅1浪)** | 已完成 | 15-20% | 执行中仓，等待2浪 |
| **侦察待定** | 未开始 | - | 执行侦察仓 |
| **侦察失败** | - | 0% | 不入场，观望 |

### 执行信号类型

| 信号类型 | 说明 | 触发条件 |
|:---|:---|:---|
| `SCOUT_ENTRY` | 侦察仓入场 | 侦察待定 + 符合侦察时机 |
| `LARGE_ENTRY` | 大仓入场 | 侦察成功 (1浪+2浪) |
| `MID_ENTRY` | 中仓入场 | 侦察成功 (仅1浪) |
| `SKIP` | 不入场 | 侦察失败 / 战略WAIT |

---

## 波浪式执行流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    波浪式执行流程 (v2.0)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  读取侦察报告                                                          │
│  ├── 侦察状态: 成功 / 待定 / 失败                                      │
│  └── 当前波浪位置                                                      │
│                          ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  状态1: 侦察待定 → 执行侦察仓 (10-15%)                         │   │
│  │  ├── 入场: 等待回踩确认                                         │   │
│  │  ├── 止损: ±2%                                                 │   │
│  │  ├── 目标: 验证方向                                             │   │
│  │  └── 下一动作: 等1浪结果                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                          ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  状态2: 1浪验证成功 → 执行中仓 (15-20%)                       │   │
│  │  ├── 入场: 回踩确认后                                           │   │
│  │  ├── 止损: 2浪低点下方                                         │   │
│  │  ├── 目标: 验证2浪支撑                                          │   │
│  │  └── 下一动作: 等2浪回踩结果                                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                          ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  状态3: 2浪验证成功 → 执行大仓 (30-40%)                       │   │
│  │  ├── 入场: 突破确认后                                           │   │
│  │  ├── 止损: 2浪低点                                             │   │
│  │  ├── 目标: 3浪主升                                              │   │
│  │  └── 风控: 移动止损，跟踪利润                                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                          ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  状态4: 侦察失败 → SKIP，不入场                                │   │
│  │  ├── 可能原因: 方向错误 / 支撑破位 / 市场脾气不符              │   │
│  │  └── 下一动作: 重新评估战略或换策略                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase7应急预案集成 (v3.2 新增读取逻辑)

### 7.1 应急预案读取流程

**Step 1: 读取A3应急预案**
```bash
# 方法1: 从A3报告读取Phase7章节
search_file("reports/trading/a3_strategy_*.md")
# 提取最新A3报告中的 "Phase 7: 战略沙盘推演" 章节

# 方法2: 使用应急预案加载器
python3 ~/.workbuddy/strategy-library/phase7_contingency_loader.py load --latest
```

**Step 2: 加载应急预案库**
```bash
# 读取完整应急预案库
read_file("~/.workbuddy/strategy-library/strategy_contingency_library.yaml")
```

**Step 3: 匹配触发条件**
```yaml
应急预案触发检测:
├── 黑天鹅警报:
│   ├── 检测: deviation_score > 0.7
│   ├── 预案: BS_FLASH_CRASH | BS_WAR | BS_HACK
│   └── 动作: 立即执行对应预案
│
├── 极端情景:
│   ├── 检测: 1H涨跌 > 10%
│   ├── 预案: EXT_LIQUIDATION | EXT_PUMP
│   └── 动作: 暂停正常执行，执行极端预案
│
├── 假突破警报:
│   ├── 检测: 突破关键位后收回
│   ├── 预案: PLAN_B | PREPARE_PLAN_C
│   └── 动作: 平仓止损，准备反向
│
└── 预案优先级:
    ├── 黑天鹅应急预案 (最高优先级)
    ├── 极端情景预案
    └── 概率情景预案 (PLAN_A/B/C)
```

### 7.2 应急预案结构

```yaml
# 应急预案模板
contingency_plan:
  plan_id: BS_xxx | EXT_xxx | PLAN_A/B/C
  trigger_condition: 触发条件描述
  trigger_indicators:
    - 指标1: 阈值
    - 指标2: 阈值
  actions:
    - 动作1: 具体操作
    - 动作2: 具体操作
  exit_conditions:
    - 退出条件1
    - 退出条件2
  rollback_plan_id: 回滚预案ID
  evidence_refs:
    - A3报告引用
    - 历史案例引用
```

### 7.3 执行预案时的A5动作

```python
# 伪代码: 应急预案执行逻辑
def execute_contingency_plan(plan_id, context):
    plan = load_plan(plan_id)  # 从应急预案库加载
    
    # 检查触发条件
    if not check_trigger(plan.trigger_indicators):
        return None  # 未触发，不执行
    
    # 生成执行指令
    if plan_id.startswith("BS_"):  # 黑天鹅预案
        return {
            "action": "EMERGENCY_CLOSE_ALL",
            "reason": f"黑天鹅预案触发: {plan_id}",
            "rollback": plan.rollback_plan_id
        }
    elif plan_id.startswith("EXT_"):  # 极端行情预案
        return {
            "action": "REDUCE_POSITION",
            "factor": 0.5,  # 降仓50%
            "reason": f"极端行情预案触发: {plan_id}",
            "rollback": plan.rollback_plan_id
        }
    elif plan_id.startswith("PLAN_"):  # 概率情景预案
        return {
            "action": "ADJUST_STOP_LOSS",
            "new_sl": calculate_new_sl(),
            "reason": f"情景预案触发: {plan_id}",
            "rollback": plan.rollback_plan_id
        }
```

### 7.4 触发条件速查表

| 触发指标 | 阈值 | 预案 | A5动作 |
|:---|:---:|:---|:---|
| deviation_score | >0.7 | BS_FLASH_CRASH | 全平+禁止开仓 |
| deviation_score | >0.8 | BS_WAR | 全平+禁止开仓 |
| 1H涨跌 | >10% | EXT_PUMP/EXT_LIQUIDATION | 降仓50% |
| deviation_score | >0.5 | 极端情景 | 降仓50% |
| 突破失败 | 2次 | PLAN_B | 止损+观望 |
| 突破失败 | 3次 | PREPARE_PLAN_C | 反向试探 |

---

## 仓位计算规则

```
仓位 = f(侦察结果, 战略仓位上限, 波浪位置)

侦察成功(1浪+2浪):
  执行仓位 = min(战略仓位上限 × 0.8, 40%)

侦察成功(仅1浪):
  执行仓位 = min(战略仓位上限 × 0.4, 20%)

侦察待定:
  执行仓位 = 10-15% (侦察仓)

侦察失败:
  执行仓位 = 0% (不下单)
```

---

## 止损止盈规则

### 止损规则

| 波浪位置 | 止损类型 | 距离 |
|:---|:---|:---|
| 侦察仓 (1浪) | 固定 | ±2% |
| 中仓 (2浪) | 2浪低点下方 | 2-3% |
| 大仓 (3浪) | 移动止损 | 追踪利润的50% |

### 止盈规则

| 波浪位置 | 止盈方式 | 说明 |
|:---|:---|:---|
| 侦察仓 | 目标±3% | 验证方向为目的 |
| 中仓 | 分批止盈 | 30%+30%+40% |
| 大仓 | 移动止损 + 分批止盈 | 让利润奔跑 |

---

## 执行前门禁检查 ⭐ (整合 dream-pretrade-gatekeeper)

> **重要**: 在生成下单指令前，必须执行完整的交易前门禁检查。任何一项检查失败都将导致 `SKIP` 或强制降级。

### 门禁检查流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    执行前门禁检查流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 1: 数据完整性检查                                                │
│  └── 核心数据缺失? → SKIP (HARD_FAIL_MISSING_CORE_DATA)               │
│                          ↓                                              │
│  Step 2: 战略方向匹配检查 ⭐ P0                                         │
│  ├── 战略排除条件命中? → SKIP (HARD_FAIL_STRATEGY_EXCLUDED)          │
│  ├── 方向冲突? → SKIP (HARD_FAIL_STRATEGY_DIRECTION_MISMATCH)       │
│  └── 战略REDUCE? → 强制降级                                            │
│                          ↓                                              │
│  Step 3: 评分门禁检查                                                  │
│  ├── 维度分 < 3? → SKIP (HARD_FAIL_LOW_DIM_SCORE)                    │
│  └── 总分 < 12? → SKIP (HARD_FAIL_LOW_TOTAL_SCORE)                   │
│                          ↓                                              │
│  Step 4: 执行成本检查                                                  │
│  ├── 滑点 > 60bps? → SKIP (HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH)       │
│  └── 负Edge? → SKIP (HARD_FAIL_NEGATIVE_EDGE)                        │
│                          ↓                                              │
│  Step 5: 账户风险检查                                                  │
│  ├── 当日回撤熔断? → SKIP                                             │
│  └── Dream Mode? → 强制降级 (DEGRADE_DREAM_MODE)                      │
│                          ↓                                              │
│  Step 6: 黑窗期检查                                                    │
│  └── 宏观数据发布/交易所维护窗口? → SKIP                              │
│                          ↓                                              │
│  Step 7: 应急预案检查 (Phase7)                                         │
│  ├── 黑天鹅警报 (deviation > 0.7)? → 执行应急预案                     │
│  └── 极端情景触发? → 执行EXT_xxx                                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 门禁检查详细规则

#### 1️⃣ 数据完整性检查 (Fail-Closed)

| 检查项 | 要求 | 失败动作 |
|:---|:---|:---|
| K线数据 | candles_ok = true | SKIP |
| 资金费率 | funding_ok = true | SKIP |
| 持仓量 | oi_ok = true | SKIP |
| 宏观数据 | macro_ok = true | SKIP |

**失败理由码**: `HARD_FAIL_MISSING_CORE_DATA`

#### 2️⃣ 战略方向匹配检查 ⭐ P0 最高优先级

| 战略指令 | 检查项 | 失败动作 |
|:---|:---|:---|
| `exclusion_conditions` 非空 | 排除条件命中 | SKIP |
| LONG | 尝试做空 | SKIP |
| SHORT | 尝试做多 | SKIP |
| REDUCE | 任意信号 | 强制降级 (仓位×0.5, 杠杆×0.5) |
| WAIT | 任意信号 | 软警告，可覆盖但需记录理由 |

**失败理由码**: 
- `HARD_FAIL_STRATEGY_EXCLUDED`
- `HARD_FAIL_STRATEGY_DIRECTION_MISMATCH`
- `DEGRADE_STRATEGY_REDUCED_RISK`
- `SOFT_WARN_STRATEGY_DIRECTS_WAIT`

#### 3️⃣ 评分门禁检查

| 检查项 | 阈值 | 失败动作 |
|:---|:---|:---|
| 任一维度分 | < 3 | SKIP |
| 总分 | < 12 | SKIP |
| strategy_match | < 3 且无战略 | SKIP (极端行情) |

**失败理由码**:
- `HARD_FAIL_LOW_DIM_SCORE`
- `HARD_FAIL_LOW_TOTAL_SCORE`
- `HARD_FAIL_NO_STRATEGY_EXTREME_REGIME`

#### 4️⃣ 执行成本检查

| 检查项 | 阈值 | 失败动作 |
|:---|:---|:---|
| 最坏滑点 | > 60 bps | SKIP |
| Edge | <= 0 bps | SKIP |

**Edge 计算**: `Edge_bps = E[R]_bps - Costs_bps - λ × Risk_bps`

**失败理由码**:
- `HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH`
- `HARD_FAIL_NEGATIVE_EDGE`

#### 5️⃣ 账户风险检查

| 检查项 | 状态 | 动作 |
|:---|:---|:---|
| 当日回撤 | > 熔断阈值 | SKIP |
| Dream Mode | active = true | 强制降级 (杠杆-50%) |

**失败理由码**:
- `HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER`
- `DEGRADE_DREAM_MODE_RISK_REDUCTION`

#### 6️⃣ 黑窗期检查

| 检查项 | 示例 | 失败动作 |
|:---|:---|:---|
| 宏观数据发布窗口 | CPI/FOMC发布前15min | SKIP |
| 交易所维护窗口 | 交易所公告的维护时段 | SKIP |

**失败理由码**: `HARD_FAIL_EXECUTION_BLACKOUT_WINDOW`

#### 7️⃣ 应急预案检查 (Phase7)

| 触发条件 | 动作 | 优先级 |
|:---|:---|:---:|
| deviation_score > 0.7 | 执行 BS_xxx 应急预案 | 最高 |
| 价格异动 > 10%/h | 执行 EXT_xxx 应急预案 | 次高 |
| deviation_score 0.5-0.7 | 降级执行50%仓位 | 中 |
| deviation_score 0.3-0.5 | 观察，不改变仓位 | 低 |

### 门禁输出格式

```json
{
  "gate_check": {
    "overall_decision": "PASS|DEGRADE|SKIP",
    "check_results": {
      "data_integrity": {
        "pass": true,
        "checks": {"candles": true, "funding": true, "oi": true, "macro": true}
      },
      "strategy_match": {
        "pass": true,
        "directive": "LONG",
        "checks": {"direction_match": true, "exclusion": false}
      },
      "score_gates": {
        "pass": true,
        "total_score": 45,
        "min_dim_score": 5
      },
      "execution_cost": {
        "pass": true,
        "worst_slippage_bps": 15,
        "edge_bps": 28.5
      },
      "account_risk": {
        "pass": true,
        "drawdown_pct": 0.5,
        "dream_mode": false
      },
      "blackout_window": {
        "pass": true,
        "active_window": null
      },
      "contingency": {
        "active": false,
        "deviation_score": 0.2,
        "plan_id": null
      }
    },
    "reason_codes": [],
    "degradations": [],
    "position_override": null
  }
}
```

### 降级规则汇总

| 降级类型 | 触发条件 | 降级动作 |
|:---|:---|:---|
| 战略REDUCE | directive = REDUCE | 仓位×0.5, 杠杆×0.5 |
| Dream Mode | dream_mode = true | 仓位×0.5, 杠杆×0.5 |
| 极端情景 | deviation 0.5-0.7 | 仓位×0.5 |
| 弱验证 | stability = unstable | 仓位×0.7, 杠杆×0.8 |
| 高波动 | vol = high + 滑点压力高 | 优先降级杠杆 |

---

## 完整执行流程 (v3.2)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    A5 战术执行完整流程 (v3.2)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  输入                                                                │
│  ├── 侦察报告 (A4): reports/trading/a4_scout_*.md                     │
│  ├── 战略指令 (A3): reports/trading/a3_strategy_*.md                 │
│  ├── 应急预案 (Phase7): a3 Phase7章节 / phase7_contingency_loader    │
│  └── 实时市场数据                                                     │
│                          ↓                                              │
│  Phase 0: A7实践论门禁检查 ⚠️ (必须首先执行)                           │
│  └── use_skill("A7-practice-theory") → 通过才继续                    │
│                          ↓                                              │
│  Step 1: 读取前置报告                                                  │
│  ├── search_file("reports/trading/a4_scout_*.md")                    │
│  ├── search_file("reports/trading/a3_strategy_*.md")                 │
│  └── python3 phase7_contingency_loader.py load --latest               │
│                          ↓                                              │
│  Step 2: 仓位决策                                                     │
│  ├── 侦察成功(1+2浪) → LARGE 30-40%                                  │
│  ├── 侦察成功(仅1浪) → MEDIUM 15-20%                                  │
│  ├── 侦察待定 → SCOUT 10-15%                                          │
│  └── 侦察失败 → SKIP                                                  │
│                          ↓                                              │
│  Step 3: 应急预案检查 (Phase7) ⭐ 新增                                 │
│  ├── deviation_score > 0.7 → BS_xxx黑天鹅预案                        │
│  ├── 1H涨跌 > 10% → EXT_xxx极端行情预案                              │
│  ├── 突破失败2次 → PLAN_B                                             │
│  └── 触发预案 → 执行预案动作                                           │
│                          ↓                                              │
│  Step 4: 执行前门禁检查 ⭐                                             │
│  ├── 数据完整性 → 缺失则SKIP                                          │
│  ├── 战略匹配 → 冲突则SKIP/降级                                       │
│  ├── 评分门禁 → 不达标则SKIP                                          │
│  ├── 执行成本 → 负Edge则SKIP                                          │
│  ├── 账户风险 → 熔断则SKIP                                            │
│  └── 黑窗期 → 窗口期则SKIP                                            │
│                          ↓                                              │
│  Step 5: 生成下单指令                                                  │
│  ├── 入场参数 (价格/类型)                                              │
│  ├── 仓位参数 (数量/杠杆)                                              │
│  ├── 风控参数 (止损/止盈)                                              │
│  └── 跟踪计划 (波浪位置/检查点)                                        │
│                          ↓                                              │
│  输出                                                                │
│  └── execution_order → OKX 交易执行                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---|:---|:---|
| **输入←** | ← | `dream-tactical-validator` | 侦察报告 |
| **输入←** | ← | `dream-strategy-designer` | A3战略指令 |
| **输入←** | ← | Phase7沙盘推演 | 应急预案 |
| **门禁集成** | 内置 | `dream-pretrade-gatekeeper` | 执行前7项检查 ⭐ |
| **输出→** | → | `dream-multiSkill` | 交易执行 |
| **数据源←** | ← | `dream-risk-position-sizing` | 仓位建议 |
| **数据源←** | ← | `dream-execution-cost-model` | 执行成本 |
| **数据源←** | ← | `dream-signal-scoring-spec` | 评分结果 |

---

## OKX CLI 正确使用方法 (v2.5 新增)

> **⚠️ 宪法§11 FAQ自愈**: 遇到OKX问题必须先查FAQ (`/.workbuddy/faq/OKX_FAQ.md`)，找到匹配项直接用已有方案。

### 命令行工具选择

| 工具 | 用途 | 优先级 |
|:---|:---|:---|
| **OKX CLI** (`okx` 命令) | 交易/账户查询/算法订单 | ⭐ 优先 |
| **OKX Python SDK** (`scripts/okx_cli.py`) | 需要签名的API调用 | 次选 |
| **直接 requests/urllib** | 公开市场数据 | 备选 |

⚠️ **禁止**: 不要用 `okx-trade` 命令（不存在，正确是 `okx`）

---

### 下单命令正确格式

#### 市价单（立即成交）

```bash
# ✅ LONG 方向（买入开多）
okx swap place --instId BTC-USDT-SWAP --side buy --ordType market --sz 0.01 --posSide long --tdMode cross --profile dreamdemo

# ✅ SHORT 方向（卖出开空）
okx swap place --instId BTC-USDT-SWAP --side sell --ordType market --sz 0.01 --posSide short --tdMode cross --profile dreamdemo
```

**关键参数**:
- `--instId`: 合约ID（必须，格式：`BTC-USDT-SWAP`）
- `--side`: `buy`（买入）或 `sell`（卖出）
- `--ordType`: `market`（市价）或 `limit`（限价）
- `--sz`: 数量（张数，必须是整张）
- `--posSide`: `long`（多头）或 `short`（空头）
- `--tdMode`: `cross`（全仓）或 `isolated`（逐仓）
- `--px`: 限价单价格（仅限价单需要）

---

#### 限价单（指定价格）

```bash
# ✅ LONG 限价单
okx swap place --instId BTC-USDT-SWAP --side buy --ordType limit --px 75000 --sz 0.01 --posSide long --tdMode cross --profile dreamdemo
```

---

### 止盈（TP）/ 止损（SL）设置方法

> **⚠️ 关键发现（2026-04-26 真实测试验证）**:
> 1. TP 和 SL 需要 **分别创建两个独立算法订单**
> 2. 一个算法订单只能设置一个触发价（要么 TP，要么 SL）
> 3. 参数格式必须是 `--tpOrdPx=-1`（用 `=` 连接，避免 `-1` 被解析为选项）

---

#### 为 LONG 持仓设置 TP/SL

```bash
# ✅ 设置止损（SL）算法订单 - LONG 持仓
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.01 --posSide long --tdMode cross --slTriggerPx 76000 --slOrdPx=-1 --profile dreamdemo

# ✅ 设置止盈（TP）算法订单 - LONG 持仓
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.01 --posSide long --tdMode cross --tpTriggerPx 78500 --tpOrdPx=-1 --profile dreamdemo
```

**说明**:
- LONG 持仓的平仓方向是 `sell`
- `--slTriggerPx`: 止损触发价（当价格 **跌破** 此价时触发）
- `--tpTriggerPx`: 止盈触发价（当价格 **涨破** 此价时触发）
- `--slOrdPx=-1`: 止损委托价 = -1（市价单）
- `--tpOrdPx=-1`: 止盈委托价 = -1（市价单）

---

#### 为 SHORT 持仓设置 TP/SL

```bash
# ✅ 设置止损（SL）算法订单 - SHORT 持仓
okx swap algo place --instId BTC-USDT-SWAP --side buy --sz 0.01 --posSide short --tdMode cross --slTriggerPx 79000 --slOrdPx=-1 --profile dreamdemo

# ✅ 设置止盈（TP）算法订单 - SHORT 持仓
okx swap algo place --instId BTC-USDT-SWAP --side buy --sz 0.01 --posSide short --tdMode cross --tpTriggerPx 76000 --tpOrdPx=-1 --profile dreamdemo
```

**说明**:
- SHORT 持仓的平仓方向是 `buy`
- `--slTriggerPx`: 止损触发价（当价格 **涨破** 此价时触发）
- `--tpTriggerPx`: 止盈触发价（当价格 **跌破** 此价时触发）

---

### 平仓命令正确格式

```bash
# ✅ 平仓 LONG 持仓
okx swap close --instId BTC-USDT-SWAP --mgnMode cross --posSide long --profile dreamdemo

# ✅ 平仓 SHORT 持仓
okx swap close --instId BTC-USDT-SWAP --mgnMode cross --posSide short --profile dreamdemo

# ✅ 平仓（逐仓模式）
okx swap close --instId BTC-USDT-SWAP --mgnMode isolated --posSide long --profile dreamdemo
```

⚠️ **重要**: 平仓后，绑定的 TP/SL 算法订单会 **自动取消**，不需要手动取消。

---

### 杠杆设置

```bash
# ✅ 设置全仓杠杆
okx swap leverage --instId BTC-USDT-SWAP --lever 2 --mgnMode cross --posSide long --profile dreamdemo

# ✅ 设置逐仓杠杆
okx swap leverage --instId BTC-USDT-SWAP --lever 2 --mgnMode isolated --posSide short --profile dreamdemo
```

---

### 查询命令

```bash
# ✅ 查询持仓
okx swap positions BTC-USDT-SWAP --profile dreamdemo

# ✅ 查询算法订单（TP/SL）
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# ✅ 查询账户余额
okx account balance --profile dreamdemo

# ✅ 查询当前价格
okx market ticker BTC-USDT-SWAP --profile dreamdemo
```

---

### 常见错误与解决方案

| 错误 | 原因 | 解决方案 |
|:---|:---|:---|
| `okx-trade: command not found` | 命令名错误 | 使用 `okx` 而非 `okx-trade` |
| `Option '--tpOrdPx' argument is ambiguous` | `-1` 被解析为另一个选项 | 使用 `--tpOrdPx=-1`（用 `=` 连接） |
| `Error: unknown option '--ordType conditional'` | `okx swap algo place` 默认就是 `conditional` | 删除 `--ordType conditional` 参数 |
| `HTTP 403: signature verification failed` | 直接用 Python requests 调用 API 签名错误 | 改用 `okx` CLI 而非 Python requests |
| `No algo orders` | 算法订单不存在或已取消 | 检查是否成功创建算法订单 |
| `sCode 51000: Parameter posSide error` | 双向持仓模式未指定 `posSide` | 必须显式指定 `--posSide long/short` |

---

### 完整执行流程示例（LONG 方向）

```bash
# 1. 设置杠杆
okx swap leverage --instId BTC-USDT-SWAP --lever 2 --mgnMode cross --posSide long --profile dreamdemo

# 2. 下单（市价单）
okx swap place --instId BTC-USDT-SWAP --side buy --ordType market --sz 0.01 --posSide long --tdMode cross --profile dreamdemo

# 3. 设置止损（SL）
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.01 --posSide long --tdMode cross --slTriggerPx 76000 --slOrdPx=-1 --profile dreamdemo

# 4. 设置止盈（TP）
okx swap algo place --instId BTC-USDT-SWAP --side sell --sz 0.01 --posSide long --tdMode cross --tpTriggerPx 78500 --tpOrdPx=-1 --profile dreamdemo

# 5. 验证算法订单
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# 6. 平仓（会自动取消 TP/SL 算法订单）
okx swap close --instId BTC-USDT-SWAP --mgnMode cross --posSide long --profile dreamdemo

# 7. 验证算法订单已自动取消
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo
# 预期输出: No algo orders
```

---

### 真实测试验证（2026-04-26）

| 测试场景 | 结果 | 说明 |
|:---|:---:|:---|
| **LONG 下单（全仓）** | ✅ 通过 | 市价单，0.01 张 |
| **SHORT 下单（逐仓）** | ✅ 通过 | 市价单，0.01 张 |
| **设置 SL 算法订单** | ✅ 通过 | 需独立创建 |
| **设置 TP 算法订单** | ✅ 通过 | 需独立创建 |
| **验证算法订单状态** | ✅ 通过 | 两个订单都 `live` |
| **平仓（LONG）** | ✅ 通过 | 成功平仓 |
| **平仓（SHORT）** | ✅ 通过 | 成功平仓 |
| **算法订单自动取消** | ✅ 通过 | 平仓后自动取消 |

**测试环境**: dreamdemo 模拟盘（`--profile dreamdemo`）

---

## 约束

1. **铁律-完整链路**: A1→A2→A3→A4缺一不可，缺失则创建临时任务补齐，不可盲目下单
2. **铁律-重要事件**: 重要事件(地缘/宏观/Regime转换/费率异变)必须先驱动A1-A3重新评估
3. **铁律-侦察优先**: 没有A4侦察报告 = 最多侦察仓(10-15%)，不允许大仓
4. **侦察成功才大仓**: 未经验证不得执行大仓
5. **仓位严格分级**: 侦察仓 ≤ 15%, 中仓 ≤ 20%, 大仓 ≤ 40%
6. **止损必须设**: 不允许无止损信号
7. **应急预案优先**: 黑天鹅警报时执行预案，不执行常规信号
8. **波浪跟踪**: 大仓入场后必须跟踪波浪位置
9. **信号有时效**: 标注 valid_until，超时重新评估
10. **门禁一票否决**: 任何一项门禁检查失败 → SKIP (除非显式降级)
11. **门禁优先级**: 战略匹配 > 评分门禁 > 执行成本 > 账户风险
12. **不投递秘书邮箱**: A5是交易执行系统，报告直接写reports/，不走信息流

---

## 临时任务调度（定时入场）

> A5属于交易执行系统，不需要投递秘书邮箱。需要定时执行时，直接创建一次性自动化任务。

### 适用场景
- 等待资金费率结算后入场（如16:00结算→16:30执行）
- 等待关键K线收盘确认后入场
- 分批建仓的时间间隔入场
- 任何需要"等N分钟后执行"的场景

### 创建规则（⚠️ 硬性约束）
1. **只创建一次**: 调用`automation_update`创建一次性任务，不管输出是否截断，**不再重复创建**
2. **创建后验证**: 用`list_dir`检查`~/.workbuddy/automations/`目录确认任务存在
3. **不成功就放弃**: 如果验证发现任务不存在，**不再重试**，直接手动执行或告知用户
4. **命名规范**: `A5-EP{N}-{HHMM}-{Action}`，例如`A5-EP48-1630-Entry`

### 任务模板

**入场执行模板**:
```
automation_update:
  mode: "suggested create"
  name: "A5-EP{N}-{HHMM}-{Action}"
  scheduleType: "once"
  scheduledAt: "YYYY-MM-DDTHH:MM:00"
  status: "ACTIVE"
  cwds: ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]
  prompt: |
    你是A5战术执行部，执行EP{N}的{HHMM}入场任务。
    ## 铁律检查（最高优先级）
    1. 检查A1-A4链路完整性（最新报告是否<4h）
    2. 检查是否有重要事件未评估（地缘/宏观/Regime转换）
    3. 如有缺失，创建临时任务驱动对应环节，SKIP等待
    ## 执行步骤
    4. 数据采集（okx CLI）
    5. 入场条件验证
    6. 门禁检查（7项）
    7. 条件满足则执行，不满足则SKIP
    8. 写报告到reports/目录
```

**链路补齐模板**（当A1-A4有缺失时）:
```
automation_update:
  mode: "suggested create"
  name: "A5-EP{N}-{Missing}-{Purpose}"
  scheduleType: "once"
  scheduledAt: "YYYY-MM-DDTHH:MM:00"
  status: "ACTIVE"
  cwds: ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]
  prompt: |
    你是A5战术执行部，发现EP{N}缺少{Missing}环节，需要补齐后才能执行下单。
    执行{Missing}的分析任务，产出物写入reports/目录。
    完成后，如果时间允许，直接执行后续链路。
```

**重要事件重评估模板**:
```
automation_update:
  mode: "suggested create"
  name: "A5-EP{N}-A1A2A3-Recalibrate"
  scheduleType: "once"
  scheduledAt: "YYYY-MM-DDTHH:MM:00"
  status: "ACTIVE"
  cwds: ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]
  prompt: |
    你是A5战术执行部，检测到重要事件需要重新评估战略方向。
    事件: {Event Description}
    依次执行A1(调研)→A2(第一性原理)→A3(战略更新)，产出物写入reports/。
    战略更新完成后评估是否需要修改执行计划。
```

### 验证流程
```
创建任务 → list_dir验证 → 存在则完成 / 不存在则放弃（不重试）
```


---

## 调度

- **自动化**: `dream-tactical-executor` (周二 14:00 + 实时触发)
- **前置依赖**:
  - `dream-tactical-validator` (周二 09:00) → 侦察报告
  - `dream-war-game-simulator` (周一 11:30) → 应急预案
- **触发词**: "战术执行"、"大仓入场"、"生成信号"、"波浪跟踪"、"下单前检查"、"交易检查"
- **实时触发**: 侦察成功信号 → 立即执行大仓

---

## 投递规范

> ⚠️ **A5是交易执行系统，不投递秘书邮箱。**
> - A1-A4决策链路报告 → 写入交易邮箱 `~/.workbuddy/skills/boss-secretary/reports/trading/`
> - A5执行报告 → 也写入交易邮箱 `reports/trading/a5_execution_*.md`
> - 定时入场任务通过一次性自动化任务调度，不走信息流
> - 每次执行完成后生成 `chain_summary_{日期}_EP{N}.md` 链路摘要

---


> **前端产物中心文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "A5执行报告 YYYYMMDD"
> department: trading
> chain_phase: A5
> date: "YYYY-MM-DDTHH:MM:SS"
> type: execution_report
> status: completed
> tags: "a5 execution 执行"
> by_a_phase: A5
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三


### 投递后验证（强制调用AD SKILL）

完成秘书邮箱投递后，必须调用 `artifact-alignment-manager` SKILL 执行双通道验证：

1. **调用方式**: 触发词「产物投递验证」或加载 `artifact-alignment-manager` SKILL
2. **验证内容**:
   - ✅ 秘书邮箱文件存在 + frontmatter完整（含 tags, by_a_phase）
   - ✅ 前端产物中心文件存在（`~/.workbuddy/artifacts/trading/`）
   - ✅ `index.json` 已更新（含 `chain_phase` + `tags`）
   - ✅ 前端详情页返回 200
3. **不通过**: 按 AD SKILL 第四章步骤修复，重新验证
4. **通过**: 投递完成

> ⚠️ 没有 AD SKILL 验证通过 = 投递未完成

## 执行报告生成 (v2.3 新增)

> **⚠️ 铁律五: 执行=下单+报告，无报告=未执行**

### 报告必须包含

| 字段 | 说明 |
|:-----|:-----|
| 执行时间戳 | ISO格式 (YYYY-MM-DDTHH:MM:SS) |
| EP编号 | 执行计划的编号 |
| 下单详情 | 币种/方向/数量/价格 |
| 顾问评审引用 | A1-A3评审章节的verdict |
| 实际vs计划偏差 | 入场价差/仓位差/执行时间差 |

### 报告模板

```markdown
# A5 执行报告

**EP编号**: EP{N}
**执行时间**: {ISO时间戳}
**执行结果**: SUCCESS / PARTIAL / SKIP

## 下单详情

| 字段 | 值 |
|:-----|:---|
| 币种 | {COIN} |
| 方向 | {LONG/SHORT} |
| 数量 | {AMOUNT} |
| 入场价 | {PRICE} |
| 计划入场价 | {PLANNED_PRICE} |
| 偏差 | {DEVIATION}% |

## 顾问评审引用

### A1 调研评审 (QT+RM)
- verdict: {AGREE/PARTIAL/DISAGREE}
- confidence: {N}
- 时间: {TIMESTAMP}

### A2 第一性原理评审 (MR+TR)
- verdict: {AGREE/PARTIAL/DISAGREE}
- confidence: {N}
- 时间: {TIMESTAMP}

### A3 战略评审 (SC+QT)
- verdict: {AGREE/PARTIAL/DISAGREE}
- confidence: {N}
- 时间: {TIMESTAMP}

## 执行偏差分析

| 项目 | 计划 | 实际 | 偏差 |
|:-----|:-----|:-----|:-----|
| 入场价 | {计划价} | {实际价} | {偏差%} |
| 仓位 | {计划仓位} | {实际仓位} | {偏差%} |
| 执行时间 | {计划时间} | {实际时间} | {偏差min} |

## 门禁检查

- 数据完整性: ✅/❌
- 战略方向匹配: ✅/❌
- 评分门禁: ✅/❌
- 执行成本: ✅/❌
- 账户风险: ✅/❌
- 黑窗期: ✅/❌
- 应急预案: ✅/❌

---

*A5执行报告由dream-tactical-executor自动生成 | {TIMESTAMP}*
```

### 投递规则

1. **生成时机**: 下单执行完成后立即生成
2. **投递位置**: `~/.workbuddy/skills/boss-secretary/reports/trading/a5_execution_{YYYYMMDD}_{HHMM}.md`
3. **失败处理**: 
   - 报告生成失败 → SKIP，禁止Episode固化
   - 必须重试直到报告生成成功
4. **文件名格式**: `a5_execution_{日期}_{时间}.md`

### 报告生成失败处理

```
下单执行
    ↓
报告生成
    ├── 成功 → 写入交易邮箱 → 流程完成
    └── 失败 → SKIP → 重试(最多3次) → 仍失败则告警
              ↓
        触发告警: 通知ADVISOR-RM
        禁止Episode固化，直到报告生成
```

> **⚠️ 原则: 没有执行报告=没有完成执行，Episode不能固化，交易闭环未闭合**

---

## A5 仓位分级权限架构 (v3.1 新增)

> **EP57觉醒 → v3.1优化**: 按仓位比例划分权限，更直观、更易执行。

### 仓位分级标准

| 级别 | 仓位范围 | 权限类型 | 决策方式 | 执行方式 |
|:---:|:---:|:---|:---|:---|
| **P1** | ≤10% | 自主执行 | 自动评估 | 立即执行，无需确认 |
| **P2** | 10%-20% | 预授权 | 自动评估 | 执行后通知用户 |
| **P3** | 20%-30% | 人工授权 | 风险评估 | 执行前通知用户，用户确认 |
| **P4** | >30% | **禁止** | - | 触发A6审查，特殊审批 |

### P1 自主执行（≤10%）

**权限范围**：
- 止损触发 → 立即平仓（任何仓位）
- 杠杆调整 → 立即执行
- 追踪止损触发 → 立即移动
- 侦察仓（≤10%）→ 立即执行
- 实时行情急剧反转 → 自主SKIP

**自主SKIP触发条件**：
- A3=LONG 但价格跌破关键支撑（破位>2%）→ 自主SKIP
- A3=SHORT 但价格突破关键阻力（突破>2%）→ 自主SKIP
- 资金费率急剧反转（30分钟内从-0.05% → +0.05%）→ 自主SKIP
- 1h涨跌>3% → 自主SKIP

### P2 预授权执行（10%-20%）

**权限范围**：
- 中仓入场（10%-20%）
- 减仓至10%-20%
- 调整止盈点

**执行流程**：
```
风险评估 → 生成操作计划 → 执行（自动） → 通知用户
```

### P3 人工授权（20%-30%）

**权限范围**：
- 大仓入场（20%-30%）
- 全仓平仓
- 反向开仓

**执行流程**：
```
风险评估 → 生成操作建议 → 通知用户 → 等待确认 → 执行
```

### P4 禁止执行（>30%）

**触发条件**：
- 任何单次操作超过30%
- 反向开仓超过10%

**处理流程**：
```
检测到P4操作 → 上报A6审查 → 等待A6批复 → 执行或拒绝
```

### 权限检查流程

```
A5执行前
    ↓
检查仓位比例
    ↓
P1 (≤10%) → 直接执行 → 记录
P2 (10%-20%) → 执行 → 通知用户
P3 (20%-30%) → 通知用户 → 等待确认 → 执行
P4 (>30%) → 上报A6 → 等待批复
```

### 仓位比例速查表

| 场景 | 仓位 | 级别 | 权限 |
|:---|:---:|:---:|:---|
| 侦察仓 | 5%-10% | P1 | 自主执行 |
| 验证仓 | 10%-15% | P2 | 预授权 |
| 确认仓 | 15%-20% | P2 | 预授权 |
| 趋势仓 | 20%-30% | P3 | 人工授权 |
| 追仓/重仓 | >30% | P4 | 禁止 |

### SI_Index仓位映射（v3.1）

| SI_Index | 分级 | 仓位系数 | 建议仓位 | 级别 |
|:---:|:---|:---:|:---:|:---:|
| ≥+30 | STRONG_BULL | 0.8-1.0x | 0.5-0.8张 | P2-P3 |
| +15~+29 | MODERATE_BULL | 0.5-0.7x | 0.3-0.5张 | P2 |
| 0~+14 | NEUTRAL | 0.2-0.4x | 0.1-0.3张 | P1 |
| -15~0 | MODERATE_BEAR | 0.1-0.2x | 0.05-0.1张 | P1 |
| <-15 | STRONG_BEAR | 0x | 0张 | 禁止 |

### PTSD仓位降级（v3.1）

| PTSD触发条件 | 降级系数 | 示例(SI建议0.5张) |
|:---|:---:|:---|
| 30天内有创伤日 | 0.5x | 0.5→0.25张(P2→P1) |
| 30天内连续2次止损 | 0.3x | 0.5→0.15张(P2→P1) |
| 30天内追涨被套 | 禁止追高 | N/A |

---

## Episode Writer 集成 (v2.5 新增)

> **联动触发**: A5检测到T1-T5条件时，主动上报A6，由A6查记忆账本后决定链路深度。

### T1-T5 触发条件（A5检测）

| T编号 | A5检测条件 | 上报A6后的链路 |
|:---|:---|:---|
| **T1: 战略指令矛盾** | A5执行时，战略指令与实时行情矛盾（A3=LONG但价格破位>2%） | A1→A2→A3→A4→A5 |
| **T2: Regime偏差持续** | 连续3次A5执行后都止损（Regime判断错误） | A3→A4→A5 |
| **T3: 极端事件** | 1h涨跌>5% / 闪崩/插针 | A1→A2→A3→A4→A5 |
| **T4: 多次实践失败≥2** | A5连续2次执行失败（止损/回撤>2%） | A4→A5 |
| **T5: 战略假设证伪** | A5战略假设证伪（例如LONG策略连续3次止损） | A1→A2→A3→A4→A5 |

### A5→A6 上报格式

```json
{
  "report_type": "A5_TO_A6",
  "trigger": "T1/T2/T3/T4/T5",
  "timestamp": "ISO8601",
  "a5_status": {
    "position": "LONG/SHORT",
    "pnl_pct": -2.5,
    "consecutive_losses": 3,
    "current_regime": "TREND_STRONG"
  },
  "trigger_reason": "连续3次止损，战略假设证伪",
  "suggested_chain": "A1→A2→A3→A4→A5"
}
```

**上报文件**: `~/.workbuddy/skills/boss-secretary/reports/trading/a5_to_a6_{YYYYMMDD}_{HHMM}.json`（注：原路径 advisor/ 已废弃，改投 trading/ 邮箱）

### A6 反馈处理

```
A5检测到T1-T5
    ↓
生成上报文件 (a5_to_a6_*.json)
    ↓
调用 use_skill "dream-intelligence-monitor" (A6)
    ↓
A6查记忆账本
    ↓
A6决定链路深度
    ↓
A6执行对应链路 (A1→A2→A3→A4→A5 或 A3→A4→A5 或 A4→A5)
    ↓
A6生成新战略指令 → 写入交易邮箱
    ↓
A5读取新战略指令 → 调整执行计划
```

---

## A5 自主出场逻辑 (v2.5 新增)

> **出场与入场同等重要**: A5不仅要决定何时入场，还要决定何时出场。

### 出场信号类型

| 出场类型 | 触发条件 | 执行动作 |
|:---|:---|:---|
| **止损出场** | 价格触及止损价 | 立即平仓 |
| **追踪止损出场** | 价格回撤>追踪距离 | 立即平仓 |
| **目标止盈出场** | 价格触及止盈目标 | 分批平仓 |
| **技术反转出场** | 关键指标反转（MACD死叉/RSI超买） | 立即平仓或部分平仓 |
| **时间止损出场** | 持仓>24h 但未达目标 | 评估后出场 |

### 出场执行流程

```
持仓中 (LONG / SHORT)
    ↓
实时监控 (每次K线收盘)
    ↓
检查出场信号
    ├── 止损触发 → L1自主执行，立即平仓
    ├── 追踪止损触发 → L1自主执行，移动止损或平仓
    ├── 目标止盈触发 → L2自主决策，分批平仓
    ├── 技术反转触发 → L2自主决策，评估后出场
    └── 无出场信号 → 继续持仓，更新追踪止损
```

### 波浪式出场（与入场对应）

| 波浪位置 | 出场策略 |
|:---|:---|
| **1浪入场** | 目标: 2浪低点；止损: 入场价-2% |
| **2浪回踩** | 目标: 3浪高点；止损: 2浪低点-1% |
| **3浪主升** | 目标: 分批止盈；止损: 移动止损（追踪利润的50%） |
| **4浪回调** | 目标: 5浪高点；止损: 3浪低点 |
| **5浪末端** | 目标: 全部止盈；止损: 移动止损 |

---

## A5 熔断机制 (v2.5 新增)

> **A5作为执行层，必须具备自主熔断能力，防止继续亏损。**

### 熔断触发条件（4项，任一触发即熔断）

| 熔断条件 | 阈值 | 动作 |
|:---|:---|:---|
| **单次亏损** | 单笔亏损 > 10% | 熔断，暂停交易 |
| **当日账户回撤** | 当日回撤 > 20% | 熔断，暂停交易 |
| **连续止损** | 连续3次止损 | 熔断，暂停交易 |
| **极端行情** | 1h涨跌 > 5% | 熔断，观望 |

### 熔断执行流程

```
A5执行中
    ↓
实时计算 (每次K线收盘)
    ↓
检测熔断条件
    ├── 触发 → 熔断，立即平仓
    └── 未触发 → 继续执行
    ↓
熔断后动作
    ├── 写入熔断日志 `~/.a5/circuit_breaker/{timestamp}.json`
    ├── 通知A6 (上报熔断原因)
    ├── 暂停交易 (直到A6反馈或人工干预)
    └── 生成熔断报告 `reports/trading/a5_circuit_breaker_{YYYYMMDD}_{HHMM}.md`
```

### 熔断恢复条件

| 恢复条件 | 说明 |
|:---|:---|
| **A6反馈新战略** | A6生成新战略指令，A5读取后恢复执行 |
| **人工干预** | 用户手动恢复交易 |
| **熔断>24h** | 自动恢复，但仓位限制在10%以内 |

---

## Episode Writer 集成 (v2.5 新增)

> **⚠️ 铁律六: 执行=下单+报告+Episode固化，三者缺一不可**

### Episode 固化触发时机

| 触发时机 | 说明 |
|:---|:---|
| **下单执行完成** | 无论成功/失败，都必须固化Episode |
| **出场执行完成** | 平仓后必须固化Episode |
| **熔断触发** | 熔断后必须固化Episode（记录熔断原因） |

### Episode 数据结构

```json
{
  "episode_id": "EP{N}",
  "timestamp": "ISO8601",
  "decision": {
    "signal": "LARGE_ENTRY|SCOUT_ENTRY|SKIP",
    "direction": "LONG|SHORT",
    "size_pct": 30.0,
    "leverage": 2
  },
  "gate_check": {
    "overall_decision": "PASS|DEGRADE|SKIP",
    "reason_codes": ["..."]
  },
  "execution": {
    "entry_price": 75000.0,
    "exit_price": 77000.0,
    "pnl_usdt": 50.0,
    "pnl_pct": 2.5
  },
  "result": "WIN|LOSS|SKIP",
  "evidence_refs": [
    "reports/trading/a3_strategy_20260426_1430.md",
    "reports/trading/a4_scout_20260426_1500.md"
  ]
}
```

### 调用 Episode Writer 流程

```
A5执行完成 (入场或出场)
    ↓
调用 use_skill "learning-episode-writer"
    ↓
传入 Episode 数据
    ↓
Episode Writer 固化 Episode
    ↓
写入 episodes/ 目录
    ↓
A5继续执行或等待
```

⚠️ **强制规则**: Episode未固化 = 执行未闭环，禁止继续下单。

---

## 门禁检查调用逻辑 (v2.5 更新)

> **明确调用指令**: A5执行前必须调用 `dream-pretrade-gatekeeper` skill，不能只有描述。

### 调用流程

```
A5执行前
    ↓
调用 use_skill "dream-pretrade-gatekeeper"
    ↓
传入参数:
  - strategy_directive (A3战略指令)
  - scout_report (A4侦察报告)
  - market_state (当前市场状态)
  - account_state (账户状态)
    ↓
Gatekeeper 返回:
  {
    "gate_check": {
      "overall_decision": "PASS|DEGRADE|SKIP",
      "reason_codes": [...],
      "degradations": [...]
    }
  }
    ↓
解析 Gatekeeper 结果
    ├── PASS → 继续执行
    ├── DEGRADE → 降级执行 (仓位×0.5, 杠杆×0.5)
    └── SKIP → 停止执行，生成SKIP报告
```

### 门禁检查与三层权限的关系

| 门禁结果 | L1操作 | L2操作 | L3操作 |
|:---|:---|:---|:---|
| **PASS** | 正常执行 | 正常执行 | 正常执行（cap at 50%） |
| **DEGRADE** | 降级执行 | 降级执行 | 降级执行（cap at 30%） |
| **SKIP** | 停止执行 | 停止执行 | 停止执行 |

⚠️ **门禁优先级高于三层权限**: 门禁SKIP → 无论L1/L2/L3都停止执行。

---

## 完整执行流程图 (v2.5 更新)

```
A5收到执行指令
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 0: 实时行情检查 (新增)                                  │
│  ├── 行情与战略矛盾? → 自主SKIP (L1权限)                   │
│  └── 不矛盾 → 继续                                          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 0.5: A0矛盾回流检查 (v3.3 新增 PROP_A8_001) ⚖️        │
│  ├── 调用A0矛盾论，对比A2矛盾图谱与当前市场状态            │
│  ├── 矛盾状态未变化 → 继续                                  │
│  ├── 矛盾主导方变化(bear→bull / bull→bear) → 触发A2增量更新 │
│  │   ├── 写入矛盾回流报告到交易邮箱:                        │
│  │   │   reports/trading/a2_contradiction_update_*.md        │
│  │   ├── 回流内容: 新主要矛盾+方向+转化条件+证据            │
│  │   └── 标记: a2_contradiction_drift=DETECTED              │
│  └── 新矛盾出现(C8宏观等) → 触发A2增量更新                  │
│      └── 标记: a2_new_contradiction=DETECTED                │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: A1→A2→A3→A4 链路完整性检查                        │
│  ├── 齐全 + 新鲜(<4h) → 继续                              │
│  └── 缺失 → 创建临时任务补齐，SKIP等待                       │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 顾问评审检查                                        │
│  ├── verdict!=DISAGREE → 继续                               │
│  └── verdict=DISAGREE → SKIP，禁止执行                      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 门禁检查 (调用 dream-pretrade-gatekeeper)             │
│  ├── PASS → 继续执行                                        │
│  ├── DEGRADE → 降级执行                                    │
│  └── SKIP → 停止执行                                       │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 执行下单 (L1/L2/L3权限)                             │
│  ├── 侦察仓 (10-15%) → L1执行                              │
│  ├── 中仓 (15-20%) → L2执行                                │
│  └── 大仓 (30-40%) → L2执行                                │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 实时监控 + 出场管理                                 │
│  ├── 止损触发 → L1执行                                      │
│  ├── 追踪止损触发 → L1执行                                  │
│  ├── 目标止盈触发 → L2执行                                  │
│  └── 技术反转触发 → L2执行                                  │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: 熔断检测 (实时)                                      │
│  ├── 触发 → 熔断，上报A6                                    │
│  └── 未触发 → 继续                                          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: Episode固化 (调用 learning-episode-writer)             │
│  └── 写入episodes/目录                                      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 8: A5→A6 联动检测 (T1-T5)                              │
│  ├── 触发 → 上报A6                                          │
│  └── 未触发 → 完成                                          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 9: monitoring审计日志写入 (v3.2 新增 → v3.7 强制执行)
│
│ ⚠️ v3.7 修正 (2026-04-28 A8修复):
│ A8核查(EP68/69/70)发现A5调用了A0/A7但monitoring/未写入。
│ **根因**: Step 9指令不够明确，缺少可执行代码模板。
│ 现升级为"强制执行+可执行代码+失败处理"。
│
│ 【强制执行 — 不可跳过!】
│
│ Step 9a: A0调用记录写入
│   - 路径: monitoring/a0/{YYYYMMDD_HHMM}.json
│   - 内容来源: Step 0.5的A0矛盾回流检查结果(a0_contradiction对象)
│   - 若Step 0.5未执行 -> 必须先执行A0矛盾论再写!(禁止空文件)
│
│ Step 9b: A7门禁记录写入
│   - 路径: monitoring/a7/{YYYYMMDD_HHMM}.json
│   - 内容来源: Phase 0的INDEPENDENT_AUTO验证结果(a7_gate完整JSON)
│   - 禁止写入SELF_SCORE或简写版!
│
│ Step 9c: 写入失败处理
│   - mkdir -p monitoring/a0/ monitoring/a7/
│   - 失败 -> 记录到episode warnings字段，不阻止固化但必须标记
│
│ 【可执行代码模板】(Python伪代码):
│ import json, os, datetime
│ now = datetime.datetime.now().strftime("%Y%m%d_%H%M")
│ # 9a: A0记录 (从Step 0.5取a0_contradiction)
│ a0_data = episode.get("a0_contradiction") or run_a0_check()
│ with open(f"monitoring/a0/{now}.json","w") as f:
│     json.dump({"timestamp":datetime.datetime.now().isoformat(),
│                 "source":"A5_Step9_v3.7", **a0_data}, f, indent=2)
│ # 9b: A7记录 (从Phase 0取a7_gate, 必须INDEPENDENT_AUTO)
│ a7_data = episode.get("a7_gate") or run_a7_verification()
│ assert a7_data["verification_type"]=="INDEPENDENT_AUTO"
│ with open(f"monitoring/a7/{now}.json","w") as f:
│     json.dump({"timestamp":datetime.datetime.now().isoformat(),
│                 "source":"A5_Step9_v3.7", **a7_data}, f, indent=2)
└─────────────────────────────────────────────────────────────────┘
    ↓
完成
```

---

## 17. SI_Index 仓位-信号映射 (v3.0新增)

### 17.1 仓位决策矩阵

| SI_Index | 分级 | 仓位系数 | 最大仓位 | 适用场景 |
|:---:|:---|:---:|:---:|:---|
| ≥+30 | **STRONG_BULL** | 0.8-1.0x | 0.8张 | 大仓入场，确认趋势 |
| +15~+29 | MODERATE_BULL | 0.5-0.7x | 0.5张 | 中仓试探 |
| 0~+14 | NEUTRAL | 0.2-0.4x | 0.3张 | 小仓验证 |
| -15~0 | MODERATE_BEAR | 0.1-0.2x | 0.1张 | 极小仓/观望 |
| <-15 | **STRONG_BEAR** | 0x | 0张 | 禁止做多 |

### 17.2 A4→A5仓位同步接收

A5必须能接收并处理A4的仓位同步请求：

```
【A5接收A4请求】
a4_sync_request:
  si_index: "+55"
  si_grade: "STRONG_BULL"
  position_coefficient: "0.8x"
  existing_position: "0.05张"
  target_position: "0.8张"
  adjustment: "+0.75张"

a5_response_protocol:
  1. 验证A4请求有效性
  2. 检查A5执行条件（pretrade_gate + risk_limits）
  3. 若通过 → 执行补仓
  4. 若拒绝 → 输出拒绝理由
```

### 17.3 PTSD仓位降级规则

| PTSD触发条件 | 仓位降级系数 | 示例(SI建议0.8张) |
|:---|:---:|:---|
| 30天内有创伤日 | 0.5x | 0.8→0.4张 |
| 30天内连续2次止损 | 0.3x | 0.8→0.25张 |
| 30天内追涨被套 | 禁止追高 | N/A |

**PTSD日期列表：**
- 04-23：强熊信号日，负向信号3个，仓位应降级

### 17.4 最终仓位计算公式

```
Final_Position = Base_Position × SI_Coefficient × PTSD_Adjustment × Risk_Adjustment

其中：
- Base_Position = A4建议仓位（如0.8张）
- SI_Coefficient = SI_Index对应系数（如0.8x）
- PTSD_Adjustment = PTSD检测结果（如0.5x或有创伤）
- Risk_Adjustment = A5风险评估（如0.9x）
```

**04-26案例重演：**

| 维度 | 旧系统 | 新系统 |
|:---|:---|:---|
| SI_Index | 未计算 | +55 |
| SI分级 | 未识别 | STRONG_BULL |
| PTSD检测 | 缺失 | 04-23创伤，降级0.5x |
| Base_Position | 0.1张固定 | A4建议0.8张 |
| 最终仓位 | 0.1张 | **0.32张** (+220%) |

---

## 18. A4→A5 仓位同步执行流程 (v3.0新增)

### 18.1 完整同步流程

```
1. A4侦察验证
   ↓
2. A4计算SI_Index
   ↓
3. A4发出仓位同步请求
   ↓
4. A5接收并验证请求
   ↓
5. A5检查PTSD历史
   ↓
6. A5计算Final_Position
   ↓
7. A5执行pretrade_gate
   ↓
8. A5执行下单
   ↓
9. A5输出执行报告
   ↓
10. A5→A6同步记录
```

### 18.2 同步失败处理

| 失败原因 | A5动作 |
|:---|:---|
| A4请求超时(>1h) | 使用默认仓位(0.2x) |
| pretrade_gate失败 | 输出拒绝理由，等待修复 |
| 账户余额不足 | 计算最大可执行仓位 |
| PTSD检测阳性 | 强制降仓并记录 |

---

## 19. SI_Index 自动化执行 (v3.0新增)

### 19.1 自动化引擎集成

A5可以使用自动化脚本接收A4的仓位同步请求并自动执行：

```bash
# 运行完整自动化（含执行）
python3 scripts/si_index_automation.py --mode automation --symbol BTC-USDT-SWAP --live

# 仅获取决策建议
python3 scripts/si_index_automation.py --mode automation --symbol BTC-USDT-SWAP --dry-run
```

### 19.2 自动化执行流程

```
A4触发 → SI_Index计算 → PTSD检测 → 仓位决策 → A5执行 → 执行报告 → A6记录
```

### 19.3 OKX下单关键参数

```bash
# 必须包含 --posSide 参数（即使是逐仓也要指定）
okx swap place \
  --instId BTC-USDT-SWAP \
  --side buy \
  --ordType market \
  --sz 0.27 \
  --tdMode isolated \
  --posSide long \
  --profile dreamdemo
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|:---|:---|:---|
| **v3.2** | 2026-04-27 | **Phase7应急预案读取逻辑**：添加真实读取A3报告/phase7_contingency_loader.py的步骤，包含触发条件速查表和执行动作 |
| **v3.1** | 2026-04-26 | 权限层级简化：P1/P2/P3/P4按仓位10%/20%/30%划分，SI_Index映射表更新 |
| v3.0 | 2026-04-26 | SI_Index信号强度映射 · A4↔A5仓位同步 · PTSD仓位降级规则 |
| v2.5 | 2026-04-26 | 三层权限架构、A5→A6联动、自主出场逻辑、熔断机制 |
| v2.4 | 2026-04-24 | A5自主执行权限说明 |
| v2.3 | 2026-04-22 | 执行报告生成 + 顾问评审检查 |
| v2.2 | 2026-04-20 | 初始版本 |


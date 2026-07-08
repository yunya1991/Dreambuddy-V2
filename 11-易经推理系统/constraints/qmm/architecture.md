# QMM 记忆量化模型 — 总架构设计

**日期**: 2026-05-13
**类型**: 系统架构升级方案
**状态**: 修正版（v2）
**版本**: architecture-v2

---

## 零、约束与原则（必须遵守）

本方案用于升级 L4 的量化能力，但必须遵守底层约束：优先可回测、可验证、可降级；宁可拒绝也不默默出错；线上只消费通过门禁的产物。

### 0.1 Contracts First（输出契约优先）

QMM/L4 量化层对外只输出固定数学结论集，不接管 L1-L4 主链路，不生成长文本/复盘/蒸馏（解释与抽象继续由 L2/L3 完成）：

- `trend_state` — 趋势状态 (UP / DOWN / FLAT / TRANSITIONING)
- `trend_change_point` — 趋势变化点 (ACCELERATING / DECELERATING / REVERSING / STABLE)
- `mrd_vector` — 阻力最小方向向量 {direction, resistance_up, resistance_down, confidence}
- `uncertainty` — 不确定性量化 (0-1)
- `reason_codes` — 原因代码（英文大写枚举，如 `BULLISH_ALIGNMENT`, `HIGH_UNCERTAINTY`）
- `evidence_refs` — 证据引用（指向 TradeCase/Distill ID）

### 0.2 Fail-Closed（失败语义）

- 关键输入缺失、schema 漂移、时间对齐失败 → 直接 fail-closed 或显式降级；必须输出可追溯的 `reason_codes` 与 `evidence_refs`。
- 未通过门禁的输出 → 线上（A 系列调用）不得消费；离线允许继续分析，但不得写入主链产物。

### 0.3 先确定性基线，再谈训练

- Phase 1 以确定性/统计基线为主：三屏一致性 + 变化速度 + 变化点检测 + MRD（可回测、可解释）。
- 所有权重默认等权 (1/N)，任何非等权必须通过回测门禁（0.4）证明增量收益。
- 只有当基线在多个 `regime` 上稳定胜过简单策略，才引入学习型权重/表征学习；否则视为用复杂性掩盖不确定性。
- **Phase 1 零外部依赖**：仅使用 `math` / `statistics` / `json` / `dataclasses`，与现有 L4 系统依赖一致。

### 0.4 回测门禁（Stop 条件）

如果不能用离线回测证明以下任意一条，则不应扩大范围：

- 相比事件驱动 baseline，黑天鹅下误判率下降
- 趋势翻转识别更早且更稳
- 跨市场/跨周期泛化更好
- 漂移出现时能自动降级/回滚

### 0.5 可回放/可复现（Reproducibility by Design）

- 事件为事实源：episode/TradeCase 等不可变事实源；索引/统计/图谱/候选均为可再生成物化产物。
- 回放基准集：固定一组黄金样本（多 `regime` 与黑天鹅段）作为回归门禁输入，任何验收/回测必须可重放。
- 所有计算纯确定性，无随机种子依赖（Phase 1/2）。

### 0.6 版本三元组（Data/Feature/QMM Versioning）

- `data_version`：事实事件流切片/快照版本
- `feature_def_version`：特征口径与派生规则版本
- `qmm_version`：QMM 规则/参数版本

每次产物可追溯到完整版本链。详见 `version-triple-spec.md`。

### 0.7 模块化不等于 SKILL 拆分

- 允许内部工程模块拆分与演进，但初期只暴露一个稳定入口与输出契约（见 0.1）。
- 单入口：`run_qmm(cases, distills, config) -> QMMOutput`
- 不以"新建多个 SKILL"作为交付标准，避免入口膨胀、依赖膨胀、发布膨胀。

### 0.8 VectorSpace 风险与定位（离线研究/召回辅助）

- MVP 主路径：以确定性/统计基线为主（0.3），优先可回测与可解释。
- 离线价值：VectorSpace 可用于样本聚类、相似情景召回、特征探索与标注辅助。
- 如需线上引入：必须纳入回测门禁与漂移监控，并支持 fail-closed/显式降级输出。
- Phase 1 的相似性召回复用现有 `query_similar.py`（纯 math 余弦+Jaccard），不引入新向量基础设施。

---

## 一、背景与目标

### 1.1 QMM 与 L4 的定位区分

```
┌──────────────────────────────────────────────────────────┐
│              L4 认知层（已有，保持不变）                     │
│                                                          │
│  L1 事件索引 ── L2 复盘 ── L3 蒸馏 ── L4 统计              │
│  做什么：记录、分析、抽象、归纳                              │
│  产出物：TradeCase / ReviewRecord / DistillRecord / Stats  │
│  性质：具象化、语义化、可解释                               │
└──────────────────────────────────────────────────────────┘
                          │ 只读产出物
                          ▼
┌──────────────────────────────────────────────────────────┐
│              QMM 量化内核（可插拔，独立模块）                 │
│                                                          │
│  做什么：从 L4 产出物中提取数学信号                          │
│  产出物：trend_state / mrd_vector / uncertainty / ...     │
│  性质：数值化、可回测、可验证、固定契约                       │
│                                                          │
│  核心算法：三屏对齐 + MRD + 趋势速度 + 变化点检测             │
│           + 回测门禁 + 过拟合检测 + 漂移监控                  │
└──────────────────────────────────────────────────────────┘
                          │ 输出固定契约
                          ▼
┌──────────────────────────────────────────────────────────┐
│              消费层（A 系列 + 外部系统）                      │
│                                                          │
│  A2 第一性原理 ← 可接入 MRD 替代现有简单评分                 │
│  A3 模拟 ← 可接入趋势信号增强策略选择                         │
│  A4 验证 ← 可接入不确定性作为风险门禁                        │
│  A5 执行 ← 可接入阻力信号调整仓位                            │
│  A9 离场 ← 可接入趋势变化点判断                              │
└──────────────────────────────────────────────────────────┘
```

**QMM 不是 L4 的替代，而是 L4 的"数学内核"**。L4 产出认知产物，QMM 从这些产物中提炼数学信号。

### 1.2 现有 L4 数学能力清单（不复造轮子）

| 能力 | 位置 | 公式/逻辑 |
|------|------|-----------|
| 象限 x/y 计算 | `quadrant_migrator.py` | x=clamp(pnl/scale,-1,1), y=0.4*y_perf+0.4*y_consistency+0.2*y_human |
| 相似性检索 | `query_similar.py` | 0.4*struct + 0.4*num + 0.2*strategy，Jaccard+cosine+Euclidean |
| 模式成熟度 | `stats_engine.py` | 0.35*y + 0.25*log_case + 0.25*tightness + 0.15*x_clarity |
| 演化指标 | `stats_engine.py` | y_growth_rate (环比增长), pattern_stability (1-CV) |
| PnL 统计 | `stats_engine.py` | mean, median, win_rate |
| 最大回撤 | `stats_engine.py` | peak-to-trough |
| 盈亏比 | `stats_engine.py` | gross_win / gross_loss |
| 密度聚类 | `stats_engine.py` | 贪心 radius-based 聚类 |
| 一致性评分 | `quadrant_migrator.py` | 步函数：0→0, 1→0.2, 2→0.35, ... 22+→1.0 |

**QMM 新增能力**（不重复上述）：
- 趋势速度与加速度（时间序列微分）
- 三屏时间窗口对齐
- 阻力最小方向 (MRD) 计算
- 趋势变化点检测
- 不确定性量化
- 回测门禁 + 过拟合检测 + 漂移监控

### 1.3 升级目标

| 层级 | 目标 | 关键词 |
|:---|:---|:---|
| L4.1 | 记忆量化 | 事件→特征→信号 |
| L4.2 | 趋势融合 | 三屏+记忆+阻力最小 |
| L4.3 | 训练闭环 | 回测+过拟合+防漂移 |

---

## 二、理论基础

### 2.1 数学作为最终归宿

**核心理念**：从简单（0和1）到复杂（抽象思维），再回归简单（数学模型）

```
记忆事件 (文本/结构化数据)
    ↓
特征提取 (从 TradeCase 提取数值特征)
    ↓
量化信号 (趋势/阻力/不确定性)
    ↓
趋势预测 (数学模型: 速度/加速度/变化点)
    ↓
交易决策 (阻力最小方向)
```

**与现有系统的衔接**：
- TradeCase 已经包含数值特征：quadrant(x,y), pnl_pct, drawdown, stage_coverage 等
- QMM 不引入新的 embedding/向量基础设施，直接利用现有数值特征做时间序列分析
- 相似性检索复用 `query_similar.py`（已有 cosine+Jaccard）

### 2.2 趋势不会轻易改变

**三屏交易原理在 QMM 中的映射**：

QMM 的"三屏"不是真实 K 线时间框架，而是**时间窗口抽象**：

| 屏幕 | L4 映射 | 含义 |
|------|---------|------|
| 长期（类比周线） | 最近 N 天的所有 case | 宏观趋势方向 |
| 中期（类比日线） | 最近 M 天的 case | 中期趋势确认 |
| 短期（类比1h） | 最近 K 个 case | 短期交易信号 |

N/M/K 可配置，不依赖真实 K 线数据。核心思想：
- 三屏同向 → 强信号（趋势确认）
- 两屏同向 → 标准信号
- 一屏同向 → 背离预警

**记忆与趋势的融合**：
```
记忆象限时间序列 (x_mean, y_mean over time)
    ↓
计算速度 (dx/dt, dy/dt) + 加速度 (d²x/dt², d²y/dt²)
    ↓
三屏窗口对齐度检测
    ↓
趋势方向 + 变化方向 + 强度输出
```

### 2.3 确定性基线方法论

Phase 1/2 不引入 ML 训练，采用以下确定性方法：

| ML 概念 | 确定性替代 | 实现方式 |
|---------|-----------|----------|
| 数据清洗 | 异常值检测 + 缺失值处理 | IQR 方法 + 中位数填充 |
| 记忆标注 | 规则分类 | 基于 quadrant + regime 的规则引擎 |
| 模型训练 | 历史胜率查表 | 从 L4 case registry 按 regime 聚合 |
| 回测验证 | walk-forward 验证 | 时间序列分割 + 方向预测准确率 |
| 过拟合检测 | train/test gap | 确定性方法，无随机性 |
| 漂移检测 | PSI + 性能漂移 | 分布差异 + rolling win_rate 对比 |

---

## 三、系统架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    QMM 记忆量化模型 架构                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  输入层 (只读 L4 产出物)                                             │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐          │
│  │ cases/    │ │ distills/ │ │ stats/    │ │ index/    │          │
│  │ *.json    │ │ *.json    │ │ *.json    │ │ latest    │          │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘          │
│        └──────────────┴──────────────┴──────────────┘               │
│                                ↓                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              单入口: run_qmm()                                │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                                                             │   │
│  │  Phase 1 (确定性基线)                                        │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │   │
│  │  │ 数据准备     │→ │ 三屏对齐     │→ │ 阻力方向     │      │   │
│  │  │ DataPrep    │  │ TripleScreen │  │ MRD          │      │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │   │
│  │  │ 趋势速度     │→ │ 变化点检测   │→ │ 不确定性     │      │   │
│  │  │ TrendVel    │  │ ChangePoint  │  │ Uncertainty  │      │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │   │
│  │                                                             │   │
│  │  Phase 2 (在线门禁)                                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │   │
│  │  │ 回测验证     │  │ 过拟合检测   │  │ 漂移监控     │      │   │
│  │  │ Backtest    │  │ Overfit      │  │ Drift        │      │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                ↓                                    │
│  输出层 (固定契约，写入独立目录)                                      │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │  .workbuddy/memory_l4/qmm/                                │     │
│  │  ├── qmm_snapshot_{ts}.json   ← 完整量化快照               │     │
│  │  └── signals_index.json       ← 最新信号索引               │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 单入口定义

```python
def run_qmm(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> QMMOutput:
    """QMM 唯一入口。

    执行流程:
    1. 数据准备 (DataPrep)
    2. 三屏对齐 (TripleScreen)
    3. 阻力方向 (MRD)
    4. 趋势速度 + 变化点 + 不确定性
    5. (Phase 2) 回测门禁
    6. 输出固定契约
    """
```

所有子模块为私有实现，不对外暴露。

### 3.3 输出契约详解

```python
@dataclass
class QMMOutput:
    version: str = "qmm-v1.0"
    snapshot_ts: str = ""

    # 版本三元组
    data_version: str = ""
    feature_def_version: str = ""
    qmm_version: str = "qmm-v1.0"

    # 核心信号
    trend_state: str = "UNKNOWN"         # UP / DOWN / FLAT / TRANSITIONING
    trend_change_point: str = "UNKNOWN"  # ACCELERATING / DECELERATING / REVERSING / STABLE
    mrd_vector: Dict = field(default_factory=dict)
    #   {direction: "UP"/"DOWN"/"NEUTRAL",
    #    resistance_up: float, resistance_down: float,
    #    confidence: float}
    uncertainty: float = 1.0             # 0=确定, 1=完全不确定

    # 三屏详情
    triple_screen: Dict = field(default_factory=dict)
    #   {weekly: {direction, confidence, x_mean, y_mean},
    #    daily:  {...},
    #    short:  {...},
    #    alignment: float}  # -1~1, 完全对齐=1

    # 趋势速度 (三维)
    velocity: Dict = field(default_factory=dict)
    #   {price: float, confidence: float, resistance: float}
    acceleration: Dict = field(default_factory=dict)
    #   {price: float, confidence: float}

    # 元信息
    reason_codes: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    gate_status: str = "OFFLINE"         # OFFLINE / PASSED / FAILED
    gate_results: Dict = field(default_factory=dict)
```

---

## 四、核心算法

### 4.1 数据准备 (DataPrep)

从 L4 产出物提取时间序列特征：

```
输入: cases (按 ts_start 排序)
输出: CleanedEvent 列表

每个 CleanedEvent 包含:
- event_id: case_id
- ts: ts_start
- regime: environment_snapshot.regime
- quadrant_x: quadrant.x
- quadrant_y: quadrant.y
- pnl_pct: decision_outcome.pnl_pct
- is_profit: decision_outcome.pnl_pct > 0
- stages_present: thinking_chain 中 A0-A9 覆盖
- severity: 从 pnl 计算的影响程度
```

**异常值处理**（IQR 方法）：
- pnl_pct 超出 `[Q1 - 1.5*IQR, Q3 + 1.5*IQR]` 的标记为 outlier，不剔除但标记 `clean_flags: ["OUTLIER_PNL"]`

**质量评分**：
- `completeness = 非空字段数 / 总字段数`
- `recency = exp(-days_since_event / 90)`（与 L4 现有 90 天半衰期一致）
- `quality = 0.4 * completeness + 0.3 * 1.0 + 0.3 * recency`

### 4.2 三屏对齐 (TripleScreen)

**窗口划分**（可配置，默认值）：

| 窗口 | 范围 | 用途 |
|------|------|------|
| long (类比周线) | 最近 N=20 个 case | 长期趋势 |
| mid (类比日线) | 最近 M=10 个 case | 中期确认 |
| short (类比1h) | 最近 K=5 个 case | 短期信号 |

**单屏趋势计算**：

```python
def compute_screen(cases_window):
    x_mean = mean(c.quadrant_x for c in cases_window)
    y_mean = mean(c.quadrant_y for c in cases_window)
    profit_rate = sum(1 for c in cases_window if c.is_profit) / len(cases_window)

    # 方向判断
    if x_mean > 0.1:
        direction = "UP"
    elif x_mean < -0.1:
        direction = "DOWN"
    else:
        direction = "FLAT"

    # 置信度 = y_mean * 覆盖率 * 盈利方向一致性
    profit_alignment = 1.0 if (x_mean > 0 and profit_rate > 0.5) or \
                             (x_mean < 0 and profit_rate < 0.5) else 0.5
    confidence = y_mean * min(1.0, len(cases_window) / target_window) * profit_alignment

    return {direction, confidence, x_mean, y_mean, profit_rate}
```

**对齐度计算**：

```python
dirs = [screen.direction for screen in [long, mid, short]]
if len(set(dirs)) == 1 and dirs[0] != "FLAT":
    alignment = 1.0           # 三屏完全同向
elif dirs.count(dirs[0]) >= 2:
    alignment = 0.3           # 两屏同向
else:
    alignment = -0.3          # 全部背离

# 最终趋势状态
if alignment > 0.5:
    trend_state = long.direction    # 以长期为准
elif alignment > 0:
    trend_state = mid.direction     # 以中期为准
else:
    trend_state = "TRANSITIONING"   # 背离期
```

### 4.3 阻力最小方向 (MRD)

**核心思想**：趋势方向由多维阻力的最小范数方向决定。

**复用现有**：`skills/2-INTELLIGENCE/dream-data-analysis/analyzer.py` 的 `ResistanceAnalyzer`（4 摩擦分量：cost, liquidity, crowding, vol）

**计算步骤**：

```python
def compute_mrd(cases, resistance_scores):
    # Step 1: 从象限密度计算方向阻力
    benefit_density = count(x > 0.3 and y > 0.5) / N   # 有利方向密度
    harm_density = count(x < -0.3 and y > 0.5) / N     # 有害方向密度

    # Step 2: 各方向阻力
    # UP 方向的阻力 = 有害密度 * 100（ opposing force ）
    r_up = harm_density * 100
    # DOWN 方向的阻力 = 有利密度 * 100
    r_down = benefit_density * 100

    # Step 3: 净阻力（正数表示 UP 更容易）
    net = r_down - r_up

    # Step 4: 方向判断
    threshold = 20  # 可配置
    if net > threshold:
        direction = "UP"
    elif net < -threshold:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    # Step 5: 置信度
    total = r_up + r_down
    confidence = abs(net) / max(total, 1) if total > 0 else 0

    return {direction, r_up, r_down, net, confidence}
```

**与 A2 的关系**：
- A2 `_least_resistance_path(rsi, funding_rate, fgi)` 基于 3 个即时指标
- QMM MRD 基于 L4 历史记忆数据
- **两者共存**：A2 保持为独立降级路径，QMM MRD 作为增强信号供 A2 参考
- 如果 QMM 未通过门禁，A2 继续使用原有逻辑

### 4.4 趋势速度 + 变化点检测

**三维速度**（从 quadrant 时间序列计算）：

```python
def compute_velocity(events):
    # 按时间排序
    events.sort(key=lambda e: e.ts)

    # 速度 = d(x_mean)/dt
    velocities = []
    for i in range(1, len(events)):
        dt = days_between(events[i].ts, events[i-1].ts)
        if dt > 0:
            velocities.append((events[i].quadrant_x - events[i-1].quadrant_x) / dt)

    # 加速度 = d(velocity)/dt
    accelerations = []
    for i in range(1, len(velocities)):
        accelerations.append(velocities[i] - velocities[i-1])

    return {
        price: velocities[-1] if velocities else 0,
        confidence: mean(abs(v) for v in velocities[-3:]) if len(velocities) >= 3 else 0,
    }
```

**变化点检测**：

```python
def detect_change_point(velocities, accelerations):
    if not velocities or not accelerations:
        return "STABLE"

    v = velocities[-1]
    a = accelerations[-1]
    eps = 0.001  # 阈值

    if abs(v) < eps and abs(a) < eps:
        return "STABLE"
    elif v * a > 0 and abs(a) > eps:
        return "ACCELERATING"    # 速度和加速度同号
    elif v * a < 0 and abs(a) > eps:
        return "DECELERATING"    # 速度和加速度异号
    elif len(velocities) >= 3 and sign(velocities[-1]) != sign(velocities[-3]):
        return "REVERSING"       # 速度方向翻转
    else:
        return "STABLE"
```

### 4.5 不确定性量化

```python
def compute_uncertainty(triple_screen, mrd, velocity):
    factors = []

    # 因子 1: 三屏对齐度
    alignment = triple_screen.get("alignment", 0)
    factors.append(1.0 - abs(alignment))  # 对齐度越低，不确定性越高

    # 因子 2: MRD 置信度
    mrd_conf = mrd.get("confidence", 0)
    factors.append(1.0 - mrd_conf)

    # 因子 3: 数据量
    n = triple_screen.get("total_cases", 0)
    data_factor = max(0, 1.0 - n / 20)   # < 20 个 case 时不确定性高
    factors.append(data_factor)

    # 因子 4: 速度稳定性
    vel_conf = velocity.get("confidence", 0)
    factors.append(1.0 - vel_conf)

    # 综合不确定性（等权平均）
    uncertainty = sum(factors) / len(factors)
    return round(max(0.0, min(1.0, uncertainty)), 4)
```

---

## 五、回测门禁（Phase 2）

### 5.1 Walk-Forward 验证

```
事件序列: [e1, e2, e3, ..., eN]  (按时间排序)

Fold 1: train=[e1..ek], test=[ek+1..e2k]
Fold 2: train=[e1..e2k], test=[e2k+1..e3k]
...
Fold M: train=[e1..e(M-1)k], test=[e(M-1)k+1..eN]

对每个 fold:
  1. 从 train 数据计算特征统计（regime 分布、象限中心等）
  2. 对 test 中每个事件，用 QMM 预测方向
  3. 与实际 pnl 方向对比，计算准确率

聚合所有 fold 的准确率作为门禁指标
```

### 5.2 门禁通过条件

| 指标 | 阈值 | 说明 |
|------|------|------|
| 方向预测准确率 | > 55% | 优于随机猜测 (50%) |
| 高置信度子集准确率 | > 65% | uncertainty < 0.3 的子集 |
| 跨 regime 准确率 | > 50% 每个 regime | 不在单一 regime 上过拟合 |
| train/test gap | < 10% | 无显著过拟合 |

### 5.3 降级策略

- 未通过门禁 → `gate_status = "FAILED"`，A 系列不得消费
- 部分通过 → `gate_status = "PASSED"` 但 `reason_codes` 标注限制条件
- 漂移检测触发 → `gate_status = "FAILED"`，冻结输出

---

## 六、与现有系统的集成

### 6.1 数据依赖（只读）

```
QMM 读取:
  - .workbuddy/memory_l4/cases/*.json      (TradeCase)
  - .workbuddy/memory_l4/distills/*.json   (DistillRecord)
  - .workbuddy/memory_l4/stats/*.json      (StatsSnapshot)
  - .workbuddy/memory_l4/index/latest.json (search index)

QMM 不修改以上任何文件。
```

### 6.2 输出路径（独立）

```
QMM 写入:
  - .workbuddy/memory_l4/qmm/qmm_snapshot_{ts}.json
  - .workbuddy/memory_l4/qmm/signals_index.json

与 L4 现有目录完全隔离。
```

### 6.3 A 系列消费模式

```python
# A 系列 stage entrypoint 中的可选消费模式
def _load_qmm_signals(regime: str) -> Optional[Dict]:
    """加载 QMM 信号（可选，不阻塞）。"""
    try:
        signals_path = workbuddy_dir() / "memory_l4" / "qmm" / "signals_index.json"
        if not signals_path.exists():
            return None
        data = json.loads(signals_path.read_text())
        if data.get("gate_status") != "PASSED":
            return None  # 未通过门禁，不消费
        return data
    except Exception:
        return None  # fail-closed
```

- **不改变 A 系列现有逻辑**
- QMM 信号作为额外参考信号，不替换现有决策
- A2 可参考 MRD 方向但不依赖
- A3 可参考趋势状态但不依赖

---

## 七、阶段路线图（双轨战略）

### Phase A（并行验证期）

| 轨道 | 任务 | 目标 | 依赖 |
|------|------|------|------|
| 保守线 (V2 基线) | 实现 phase-1 最小集 | 零依赖确定性基线，输出固定契约 JSON | math/statistics |
| 激进线 (V5 原型) | 快速端到端链路验证 | walk-forward 回测，验证 ML 胜率 >55% | numpy/sklearn |

### Phase B（收敛判断）

Phase A 完成后，按 `execution-plan.md` 的收敛标准决定方向：

| V5 原型结果 | 后续方向 |
|-------------|----------|
| 胜率 >55% 且稳定 | 放弃 V3→V4，直接在 V2 引入 V5 核心 ML 组件 |
| 胜率 ≤55% 或过拟合 | 走 V2→V3→V4 保守路线 |

> 详细收敛判断标准见 `execution-plan.md` 第五节。

---

## 八、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 数据量不足 | 信号不稳定 | 最小 case 数门槛 (N<5 时 output uncertainty=1.0) |
| 数据质量差 | 信号失真 | IQR 异常值检测 + quality score 过滤 |
| 冷启动 | 新市场无参考 | 规则兜底：三屏全空 → trend_state=UNKNOWN, uncertainty=1.0 |
| 与 A2 冲突 | 两套阻力计算 | A2 保持独立降级路径，QMM 仅作增强参考 |
| 概念漂移 | 模型失效 | 漂移监控 + 自动降级 |

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 (PR #48) | 2026-05-13 | 初始草案，含约束与矛盾实现 |
| v2 (PR #50) | 2026-05-13 | 修正所有矛盾：去掉 numpy/sklearn、定义单入口、统一英文 reason_codes、明确 L4/QMM 定位、修正硬编码权重为等权基线 |
| v3 (本文) | 2026-05-13 | 双轨战略：Phase A 并行验证（V2 基线 + V5 原型），Phase B 按回测收敛选择方向 |

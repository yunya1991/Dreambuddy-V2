# 易经推理系统 技术设计文档

> **版本**: v3.0 | **日期**: 2026-08-01
> **定位**: 易经推理系统的技术架构、设计原则、核心算法与系统边界
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md)（工程索引）

---

## 0. 文档说明

### 0.1 文档范围

本文档是易经推理系统（I Ching Reasoning System）的技术设计总览，涵盖：

- 系统级架构范式（约束层驱动 + 记忆底座 + 并联工作流）
- 三大核心引擎（BCRM 1.0 / BCRM 2.0 / QMM）
- L4 记忆体系与自进化闭环
- A0-A9 决策链编排
- CI/CD 与治理架构
- 关键算法与数据流

### 0.2 SSoT 层级

| 层级 | 文档 | 冲突时优先级 |
|------|------|-------------|
| L0 | `constraints/system-index/engineering-architecture.md` | 约束层面最高 |
| L0 | 本文件（TECHNICAL_DESIGN.md） | 架构层面最高 |
| L0 | [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 工程索引层面 |
| L1 | BCRM 2.0 技术细节（本文第4章） | 该子模块内最高 |
| L2 | 各模块内联注释 / docstring | 代码级 |

---

## 1. 系统概述

### 1.1 设计哲学

> "易有太极，是生两仪，两仪生四象，四象生八卦。" — 《周易·系辞上》

将易经的辩证思维（阴阳、八卦、六十四卦、量变/质变、物极必反）与现代量化交易的特征工程、机器学习、进化计算深度融合，构建一个既有理论根基又有实战能力的智能交易系统。

### 1.2 核心目标

| 目标 | 说明 | 当前状态 |
|------|------|----------|
| **可解释性AI** | 将ML输出映射为易经卦象，提供"象数理"完整解释链 | ✅ BCRM 2.0已实现 |
| **动态适应性** | 根据市场状态自动调整策略参数和置信度阈值 | ✅ 8种市态切换 |
| **多币种组合** | 支持多币种资金分配和风险分散 | ✅ 27币种（BTC/ETH/SOL/BNB/XRP等） |
| **增量学习** | 实盘数据自动反馈模型迭代 | ✅ IncrementalLearner |
| **自进化闭环** | 经验→知识→约束→验证→升级的完整闭环 | ⚠️ 部分实现 |
| **L4四级记忆** | 实时→短期→长期→归档的记忆生命周期 | ✅ pipeline全链路 |
| **五角校验** | BCRM2×力学×A0×Ising×TDA 五源交叉验证 | ✅ 五源齐全 |

### 1.3 核心指标（BCRM 2.0基线）

| 指标 | 目标 | Phase 0 基线 | 五角校验+贝叶斯优化后 |
|------|------|----------|----------|
| 综合夏普 | >5.0 | **7.45** | **8.20** |
| 组合胜率 | >60% | **70.2%** | — |
| 组合盈亏比 | >1.5 | **2.61** | — |
| 组合最大回撤 | <20% | **12.75%** | **11.8%** |
| 单币种夏普 | >1.0 | 全部通过 | 全部通过 |

> 注：7.45 为 Phase 0 基线回测综合夏普；8.20 为接入五角校验+Optuna贝叶斯优化后的回测综合夏普（详见 §4.1.1c 与 §8.1）。

---

## 2. 系统架构

### 2.1 顶层架构范式

**约束层驱动 + 记忆底座服务 + 并联工作流协同 + 统一产物出口**

```
┌──────────────────────────────────────────────────────────────┐
│  约束层 (constraints/)                                       │  ← 唯一规则源（SSOT）
│  ┌────────────┬──────────────┬──────────────┬─────────────┐  │
│  │constitution │ system-index │workflows-spec│  qmm/faq/   │  │
│  └────────────┴──────────────┴──────────────┴─────────────┘  │
└──────────────────────────────┬───────────────────────────────┘
                               ↓ 约束
┌──────────────────────────────▼───────────────────────────────┐
│  记忆底座 (L1-L4 Memory)                                     │
│  实时 → 短期 → 长期 → 归档 + review + distill + index       │
└──────────────────────────────┬───────────────────────────────┘
                               ↓ 服务
┌──────────────────────────────▼───────────────────────────────┐
│  并联工作流 (Four Lines)                                     │
│  ┌──────────┬──────────┬────────────┬──────────────────┐    │
│  │Governance│ Trading  │ Knowledge  │    Evolution     │    │
│  │  治理线  │  交易线  │  知识线    │    进化线        │    │
│  └──────────┴──────────┴────────────┴──────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**核心原则：**
- 约束层是唯一规则源（SSOT）
- 记忆工作流是共享底座，不直接改写约束层
- 并联工作流按职责分工协作，统一输出到 `artifacts/`
- 经验升格为制度必须经过 `evolution/` 通道

### 2.2 四层功能架构

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层 (User Interface)                 │
│  飞书机器人 / CLI / 前端 / API / GitHub Actions             │
└───────────────────────────┬─────────────────────────────────┘
                            │ 任务队列 / 事件触发
┌───────────────────────────▼─────────────────────────────────┐
│                    编排层 (Orchestration)                     │
│  A0-A9 决策链 / 状态机 / 执行循环 / L4记忆管道               │
└───────────────────────────┬─────────────────────────────────┘
                            │ 意图/策略/信号
┌───────────────────────────▼─────────────────────────────────┐
│                    决策层 (Decision Engine)                   │
│  BCRM 1.0 (矛盾力学) / BCRM 2.0 (辩证ML) / QMM (量化记忆)   │
│  八卦力学引擎 / 市态切换 / 组合策略 / 离场决策                │
└───────────────────────────┬─────────────────────────────────┘
                            │ 特征/数据/记忆
┌───────────────────────────▼─────────────────────────────────┐
│                    支撑层 (Infrastructure)                    │
│  特征工程 / 数据服务 / 回测引擎 / 增量学习 / 共享内存总线     │
│  进程守护 / 访问控制 / CI/CD / 约束层                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 通信与调用结构（强制遵守）

```
constraints → memory / trading / governance / knowledge / evolution
memory → trading-decision（服务调用）
trading-decision → memory（回写 episode/case）
memory → evolution（提交约束候选）
evolution → constraints（唯一允许的约束升级通道）
```

**禁止项：**
- ❌ memory 直接修改 constraints
- ❌ trading-decision 绕过约束校验直接执行关键动作
- ❌ 无 trace_id 和无证据引用的产物进入主链

---

## 3. 核心引擎架构

### 3.1 三引擎协同架构

易经推理系统采用"三引擎协同"的决策架构：

```
                    ┌──────────────────┐
                    │   PollingTrader  │
                    │   轮询交易器      │
                    └────────┬─────────┘
                             │
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
┌──────────────────┐ ┌──────────────┐ ┌───────────────┐
│   BCRM 1.0       │ │  BCRM 2.0    │ │    QMM        │
│  矛盾力学引擎     │ │  辩证ML引擎   │ │  量化记忆模型  │
│  (易经推理)       │ │  (主力引擎)   │ │  (历史对照)   │
└────────┬─────────┘ └──────┬───────┘ └───────┬───────┘
         │                  │                 │
         └──────────────────┼─────────────────┘
                            ▼
                    ┌──────────────────┐
                    │  Market Regime   │
                    │  市态切换引擎     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Risk Manager    │
                    │  风控 + 离场      │
                    └──────────────────┘
```

### 3.2 BCRM 1.0 — 矛盾力学推理引擎

#### 3.2.1 核心理论

**第一性原理**：市场沿阻力最小方向运动 = 力的合成

**三层架构：**
- **数据层**：供需/技术/资金/情绪 四维评分
- **哲学层**：唯物辩证法三规律 + 矛盾论 + 黑格尔正反合
- **算法层**：易经六十四卦推理算法

#### 3.2.2 七步推理循环

```
Step 1: 矛盾识别（矛盾论）
    ↓ 识别主要矛盾与次要矛盾
Step 2: 张力量化（对立统一规律）
    ↓ 量化矛盾双方力量对比
Step 3: 质变判定（量变质变规律）
    ↓ 判断是否达到质变阈值
Step 4: 正反合裁决（黑格尔 + 易经）
    ↓ 力学引擎决定方向强度 + 易经引擎翻译卦象
Step 5: 螺旋定位（否定之否定规律）
    ↓ 判断处于螺旋上升/下降/盘整的哪个阶段
Step 6: 策略分支生成
    ↓ 基于卦象和市态生成具体策略
Step 7: 实践指令（知行合一）
    ↓ 输出可执行交易指令
```

#### 3.2.3 四维评分体系

| 维度 | 权重 | 核心指标 | 说明 |
|------|------|----------|------|
| 供需 (supply_demand) | 0.30 | 价格与量能关系、支撑阻力 | 市场供需平衡状态 |
| 技术 (technical) | 0.25 | MA/MACD/RSI/布林带等 | 技术指标形态 |
| 资金 (capital_flow) | 0.25 | 大单动向、资金流向 | 主力资金意图 |
| 情绪 (market_sentiment) | 0.20 | RSI极值、成交量突变 | 市场情绪温度 |

#### 3.2.4 双引擎结构

```
┌────────────────────────────────────────────────┐
│                  BCRMEngine                     │
│  ┌──────────────────────┐  ┌────────────────┐  │
│  │    ForceEngine       │  │  YijingEngine  │  │
│  │   力学引擎（核心）    │  │  易经引擎      │  │
│  │   - 力的合成计算      │  │  - 卦象翻译    │  │
│  │   - 方向与强度        │  │  - 六爻解释    │  │
│  │   - 矛盾张力计算      │  │  - 互卦/变卦   │  │
│  └──────────┬───────────┘  └───────┬────────┘  │
│             │                      │           │
│             └──────────┬───────────┘           │
│                        ▼                       │
│              Step4 正反合裁决                  │
└────────────────────────────────────────────────┘
```

**设计原则**：
- 力学引擎决定方向和强度（物理计算）
- 易经引擎负责把物理结果翻译成卦象符号（解释层）
- 两仪引擎 → 四象 → 八卦 → 六十四卦 的层级映射

---

### 3.3 BCRM 2.0 — 辩证ML量化引擎 ★当前主力

> 详细内容见第4章「BCRM 2.0 技术深度」

#### 3.3.1 核心思想

辩证法「正题-反题-合题」与机器学习深度融合：

- **L1 主方向模型（正题）**：LightGBM多分类，预测UP/DOWN/FLAT
- **L2 Meta-Labeling（反题）**：对L1信号做"是否盈利"二次判断
- **L3 辩证裁决（合题）**：L1置信度 × L2盈利概率 = 最终置信度

#### 3.3.2 与BCRM 1.0的关系

| 维度 | BCRM 1.0 | BCRM 2.0 |
|------|----------|----------|
| 核心范式 | 力学推理 + 易经哲学 | 辩证ML + 卦象映射 |
| 特征体系 | 四维评分（供需/技术/资金/情绪） | 11个特征模块（八卦+经典+WDH+...） |
| 决策方式 | 规则 + 力的合成 | ML概率 + 阈值裁决 |
| 可解释性 | 卦象直接解释 | ML输出→卦象映射解释 |
| 适用场景 | 哲理推演、案例分析 | 实盘交易、回测验证 |
| 状态 | Fallback备用引擎 | ★当前实盘主力引擎 |
| 实盘集成 | 通过 `PollingTrader` 直接调用 | 通过 `BCRM2Adapter` 适配层调用 |

#### 3.3.3 BCRM2Adapter 适配层

BCRM 2.0 通过 `BCRM2Adapter`（`bcrm2_adapter.py`）实现与实盘交易系统的平滑对接：

- **训练/推理/缓存一体化**：首次调用自动训练模型并缓存，后续直接加载
- **接口兼容**：输出格式与 BCRM 1.0 兼容，`PollingTrader` 可无缝切换
- **自动重训**：每 24 小时检查并重训模型
- **Fallback机制**：币种数据不足时自动回退到 BCRM 1.0
- **数据自动补充**：小币种K线数据不足时自动获取更多数据（max_bars=2000）

---

### 3.4 QMM — 量化记忆模型

#### 3.4.1 核心定位

**Quantitative Memory Model** — 从历史交易案例中提取量化规律，为决策提供历史对照。

#### 3.4.2 三屏趋势体系

```
┌─────────────────────────────────────────────────┐
│  Long-term Screen (长期趋势)                     │
│  - 主要趋势方向判定                              │
│  - 大级别支撑阻力                                │
└──────────────────┬──────────────────────────────┘
                   ↓ 确认
┌──────────────────▼──────────────────────────────┐
│  Mid-term Screen (中期结构)                      │
│  - 趋势阶段定位（启动/加速/衰竭/反转）            │
│  - 趋势速度与加速度                              │
└──────────────────┬──────────────────────────────┘
                   ↓ 入场时机
┌──────────────────▼──────────────────────────────┐
│  Short-term Screen (短期动量)                    │
│  - 入场信号触发                                  │
│  - 精确入场点位                                  │
└─────────────────────────────────────────────────┘
```

#### 3.4.3 核心输出

```python
QMMOutput(
    trend_state="UP/DOWN/FLAT/UNKNOWN",      # 趋势状态
    trend_change_point="STABLE/BREAKOUT/REVERSAL",  # 变化点
    mrd_vector={                                # 最小阻力方向
        "direction": "BULLISH/BEARISH/NEUTRAL",
        "resistance_up": 0-100,    # 上行阻力
        "resistance_down": 0-100,  # 下行阻力
        "confidence": 0-1,
    },
    uncertainty=0-1,                           # 不确定性
    reason_codes=[...],                        # 原因编码
    evidence_refs=[...],                       # 证据引用
    version_triple=(data_version, feature_def_version, qmm_version),
)
```

#### 3.4.4 质量门禁（Gate）

QMM 输出经过 Gate 验证后才可用于决策：
- 数据充足性检查（最少案例数）
- 一致性检查（三屏结论是否冲突）
- 不确定性阈值检查
- 过拟合风险评估
- 漂移检测（概念漂移/数据漂移）

---

## 4. BCRM 2.0 技术深度

### 4.1 决策层核心组件

#### 4.1.1 八卦力学引擎 (Bagua Mechanics Engine)

**设计哲学**: 将易经八卦映射为8个市场特征维度，每个卦象对应一组技术指标，实现"以卦观市"。

**特征映射**:

| 卦象 | 名称 | 特征维度 | 核心指标 | 特征数 |
|------|------|----------|----------|--------|
| 乾 ☰ | 天 | 趋势强度 | MA/EMA/MACD/ADX/均线排列 | ~18 |
| 坤 ☷ | 地 | 支撑阻力 | 布林带/近期高低点/Keltner/VWAP | ~15 |
| 震 ☳ | 雷 | 动量突破 | RSI/Stochastic/CCI/ROC/MFI/突破标记 | ~20 |
| 巽 ☴ | 风 | 波动率 | 历史波动率/ATR/波动率锥/BB压缩 | ~12 |
| 坎 ☵ | 水 | 成交量 | 量价比/量价背离/OBV/放量缩量 | ~10 |
| 离 ☲ | 火 | 蜡烛形态 | 阴阳线/十字星/锤子/吞没/跳空 | ~12 |
| 艮 ☶ | 山 | 市场结构 | 趋势vs震荡/Hurst指数/自相关/局部极值 | ~14 |
| 兑 ☱ | 泽 | 多周期共振 | 多周期动量一致性/均线排列/RSI共振 | ~10 |

**卦象强度计算**:
- 六爻计算: 上下卦各三爻，基于技术状态确定阴阳
- 互卦: 矛盾内部深层结构（2-3-4爻+3-4-5爻）
- 变卦: 物极必反提示（关键指标反转时触发）
- 卦象强度: 矛盾激化程度（0-1之间）

#### 4.1.1b 物理推理引擎 (Force Engine) — 五象力场趋势推理

**设计哲学**: 基于牛顿力学 F=ma 的市场趋势推理，将市场力量分解为五象力场，通过Verlet辛积分和Langevin随机项计算加速度和速度，判定趋势方向和强度。

**五象力场**:

| 力场 | 符号 | 物理意义 | 数据来源 | 权重 |
|------|------|----------|----------|------|
| 时（周期力） | F_time | 周期性力量（周/日/时三屏共振） | WDH时间维度 | 0.20 |
| 空（空间力） | F_space | 支撑阻力位置力 | 斐波那契+枢纽点 | 0.20 |
| 表（技术力） | F_technical | 技术指标合力 | 八卦特征 | 0.25 |
| 里（内驱力） | F_intrinsic | 资金流向与供需 | 经典经验特征 | 0.20 |
| 流（流动性力） | F_liquidity | 流动性维度 | 量价+波动率 | 0.15 |

**核心算法**:
- **Verlet辛积分器**: 二阶精度积分，时间反演对称，能量长期守恒（替代欧拉法）
- **Langevin随机项**: 引入市场热噪声，γ=-ln(decay)/dt（阻尼系数），T=0.5×volatility²（市场温度）
- **卡尔曼滤波（可选）**: 速度-加速度贝叶斯状态估计，自适应噪声（Q∝波动率，R∝买卖价差）
- **转折预警归一化**: reversal_strength = |a|/|v|（减速占速度比例），与Kalman路径decay_ratio统一量纲

**转折预警三层阶梯**:

| 层级 | 预警源 | 物理原理 | 提前量 |
|------|--------|----------|--------|
| 1（最早） | TDA拓扑突变 | Takens延迟嵌入+持久同调，拓扑结构变化先于动力学 | ~4 bars |
| 2（中期） | Ising相变 | 统计力学磁化强度下降=共识减弱=趋势衰竭 | ~2 bars |
| 3（确认） | 力学引擎减速 | 加速度与速度反向=合力衰减 | 0 bars |

#### 4.1.1c 五角校验架构 (Pentagon Verification)

**设计哲学**: 多源交叉验证，通过五源独立校验降低单点失误风险。

**五源校验体系**:

| 校验源 | 域 | 方法 | 输出 |
|--------|-----|------|------|
| BCRM2 | ML | LightGBM L1/L2/L3辩证ML | 方向+置信度 |
| 力学引擎 | 物理 | F=ma五象力场Verlet积分 | 方向+速度+加速度 |
| A0矛盾 | 逻辑 | 七维矛盾分析（纯代码） | 方向偏置+张力 |
| Ising相变 | 统计力学 | 二维Ising模型Onsager解 | 相态（ORDERED/CRITICAL/DISORDERED） |
| TDA拓扑 | 代数拓扑 | Vietoris-Rips复形持久同调 | Betti曲线+瓶颈距离 |

**校验输出**:
- `verdict`: STRONG_AGREE / MAJORITY_AGREE / DIVERGENT / CONFLICT / INSUFFICIENT_SOURCES
- `confidence_adjustment`: 基于一致性评分的置信度调整
- `should_fail_closed`: 严重分歧时强制熔断
- `position_factor`: P3联动降仓系数（0.5-1.0）
- `sl_tighten_factor`: P3联动止损收紧系数（0.6-1.0）
- `early_exit_signal`: TDA+Ising双重预警提前退出

**P3预警联动策略**:
- TDA+Ising同时触发 → position_factor=0.5, sl_tighten=0.6, early_exit=True
- 单一预警触发 → position_factor=0.8, sl_tighten=0.9

**贝叶斯优化参数（v1基线）**:

| 参数 | 值 | 说明 |
|------|-----|------|
| ISING_TEMP_SCALE | 401.4 | 温度映射 T=scale×volatility |
| ISING_ORDERED_RATIO | 0.857 | 有序相温度比上限 |
| ISING_DISORDERED_RATIO | 1.132 | 无序相温度比下限 |
| ISING_MAGNETIZATION_THRESHOLD | 0.192 | 磁化强度阈值 |
| ISING_ENERGY_SPIKE_FACTOR | 1.79 | 能量突变因子 |
| TDA_BETTI_SPIKE_FACTOR | 3.28 | Betti曲线突增因子 |
| TDA_BOTTLENECK_DISTANCE_THRESHOLD | 0.64 | 瓶颈距离阈值 |
| REVERSAL_WARNING_THRESHOLD | 0.14 | 减速预警阈值 |

#### 4.1.2 辩证ML引擎 (Dialectical ML Engine)

**三层架构**:

```
L1 主方向模型 (正题)
├── 输入: 八卦特征 + 经典经验 + 斐波那契 + 枢纽点 + WDH + 库存周期 + 跨资产
├── 模型: LightGBM多分类 (UP/DOWN/FLAT)
├── 输出: 方向预测 + 置信度
└── 验证: Walk-Forward 5折交叉验证

L2 Meta-Labeling (反题)
├── 输入: L1信号 + 时间维度 + 宏观环境 + 信号稀有度 + 市场结构 + 跨资产验证
├── 模型: LightGBM二分类 (盈利/亏损)
├── 输出: 盈利概率
└── 作用: 判断"这个时机好不好"

L3 辩证裁决 (合题)
├── 输入: L1置信度 × L2盈利概率
├── 输出: 最终置信度
└── 阈值: 0.60 (实盘优化, 代码默认0.55), 动态调整 by 市态
```

**卦象映射器**:
- 将L3最终置信度映射为易经64卦
- 提供六爻/互卦/变卦解释
- 保留"象数理"完整解释链

#### 4.1.3 市态切换引擎 (Market Regime Switching)

**8种市场状态**:

| 市态 | 分类依据 | 方向过滤 | 置信度调整 | TP/SL | 持仓周期 | 仓位因子 |
|------|----------|----------|------------|-------|----------|----------|
| TREND_UP_STRONG | ADX>30, 价格>EMA200, RSI>60 | 仅多 | -0.08 | 4x/1.5x | 80 | 1.2 |
| TREND_UP_MILD | ADX 20-30, 价格>EMA100 | 仅多 | -0.04 | 3x/1.8x | 70 | 1.0 |
| RANGE_BOUND | ADX<20, 波动率中等 | 多空 | +0.05 | 2x/2x | 30 | 0.8 |
| CONSOLIDATION | ADX<15, 波动率低 | 多空 | +0.10 | 2x/2x | 25 | 0.5 |
| BREAKOUT | 突破近期高低点 | 多空 | -0.05 | 3.5x/2.5x | 50 | 1.0 |
| FOMO_RALLY | RSI>80, 成交量激增 | 仅多 | -0.20 | 5x/1.2x | 40 | 1.5 |
| VOLATILE_DROP | RSI<20, 成交量激增 | 仅空 | -0.05 | 2.5x/3x | 40 | 0.8 |
| REVERSAL | 背离信号 | 多空 | +0.05 | 2.5x/2.5x | 35 | 1.0 |

**仓位管理实现**:
- `position_factor` 由市态决定
- 调整公式: `effective_conf_thresh = base_thresh + 0.20 * (1 - position_factor)`
- FOMO时: position_factor=1.5 → 阈值降低 → 更容易开仓
- 盘整时: position_factor=0.5 → 阈值提高 → 更难开仓

#### 4.1.4 组合策略引擎 (Portfolio Strategy)

**资金分配**:

| 市值等级 | 币种 | 权重 | 说明 |
|----------|------|------|------|
| 大市值 | BTC, ETH | 40% (各20%) | 稳健基座 |
| 中市值 | SOL | 35% | 增长引擎 |
| 小市值 | UNI | 25% | 高收益弹性 |

**组合层指标**:
- 组合日收益率: 各币种日收益按权重加权
- 组合夏普: 基于组合日收益率计算
- 综合夏普: 加权平均各币种夏普
- 最大回撤: 组合资金曲线的最大回撤

### 4.2 特征工程

#### 4.2.1 特征模块总览

| 模块 | 特征数 | 适用市值 | 核心思想 |
|------|--------|----------|----------|
| 八卦特征 | ~111 | 全部 | 易经八卦映射8维度 |
| 经典经验 | ~30 | 全部 | 传统技术分析 |
| 斐波那契 | ~10 | 全部 | 黄金比例回撤/扩展 |
| 枢纽点 | ~10 | 全部 | 支撑阻力计算 |
| WDH时间维度 | ~45 | 全部 | 量变→质变（周/日/时三屏） |
| 库存周期 | ~55 | 大/中 | 基钦周期四阶段 |
| 市值等级 | ~10 | 全部 | 市值分层与特征配置 |
| 跨资产 | ~33 | 全部 | BTC→altcoin传导 |
| 美林时钟 | ~55 | 全部 | 宏观周期映射 |
| Meta-Labeling V2 | ~25 | 全部 | L2时机判断（与L1互补） |
| RSI情绪 | ~8 | 全部 | RSI情绪指标 |

#### 4.2.2 关键特征模块详解

**WDH时间维度特征（量变→质变）**:

- **第一屏（周线）**: 量变积累层
  - 累计收益率/RSI持续性/成交量累积/EMA趋势
- **第二屏（日线）**: 质变确认层
  - 日线与周线共振/背离检测
- **第三屏（小时线）**: 入场时机层
  - 突破日高日低/短期动量/RSI(6)

质变触发信号:
- 顶部质变: 周线RSI连续超买 + RSI回落 + 小时线跌破日低
- 底部质变: 周线RSI连续超卖 + RSI回升 + 小时线突破日高
- 三级共振评分: 周线方向×0.5 + 日线方向×0.3 + 小时线方向×0.2

**美林时钟周期特征**:

将传统美林时钟映射到加密市场:

| 维度 | 代理指标 |
|------|----------|
| 通胀代理 | BTC.Dominance |
| 增长代理 | 库存周期四阶段 |
| 宏观-技术共振 | 周期方向 × 技术信号方向 |
| 跨资产动量 | BTC vs 目标资产相对强弱 |
| 流动性与信用 | 成交量百分位/量价背离 |

四阶段分类: 复苏/过热/滞胀/衰退 + one-hot编码

**Meta-Labeling V2**:

设计哲学: L1说"方向是对的"，L2说"这个时机好不好"

| 特征类别 | 特征数 | 作用 |
|----------|--------|------|
| 时间维度 | 5 | 交易时段/周一效应/月内相位 |
| 宏观环境 | 5 | BTC.D趋势/风险偏好/资金流向 |
| 信号稀有度 | 5 | 近期信号频率/间隔/密度 |
| 市场结构 | 5 | 趋势成熟度/反转概率/波动率结构 |
| 跨资产验证 | 5 | Beta/相关性/动量差/波动率比 |

与L1严格互补: 避免特征重叠导致过拟合

### 4.3 回测引擎

#### 4.3.1 Walk-Forward验证

**设计原理**: 模拟真实交易场景，避免未来信息泄露

```
数据序列: |---Fold 1---|---Fold 2---|---Fold 3---|---Fold 4---|---Fold 5---|
           [训练][验证] [训练][验证] [训练][验证] [训练][验证] [训练][验证]
           80%   20%    80%   20%    80%   20%    80%   20%    80%   20%
```

**参数**:
- 折数: 5
- 训练/验证比例: 80%/20%
- 特征选择: 每折独立

#### 4.3.2 组合回测

**流程**:
1. 各币种独立运行Walk-Forward回测
2. 按市值等级分配资金权重
3. 组合日收益率 = Σ(币种日收益率 × 权重)
4. 计算组合层指标(夏普/回撤/胜率等)

**风险控制**:
- 最大并发持仓: 4
- 组合最大回撤: 20%

#### 4.3.3 回测参数

| 参数 | 值 | 说明 |
|------|-----|------|
| K线周期 | 1H | 1小时 |
| 数据量 | 6000根 | 约8个月 |
| 手续费 | 0.05% | OKX实际费率 |
| 滑点 | 0.1% | 模拟实际交易 |
| 止盈 | 3.0x ATR | 动态 |
| 止损 | 2.0x ATR | 动态 |
| 最大持仓 | 60根K线 | 约2.5天 |

### 4.4 增量学习

#### 4.4.1 架构

```
实盘交易
    ↓
TradeDatabase (SQLite)
    ├── trades表: 交易记录
    ├── versions表: 模型版本
    └── performance表: 性能指标
    ↓
ModelVersionManager
    ├── 版本管理 (软链接)
    └── 清理策略 (保留最近10个)
    ↓
IncrementalLearner
    ├── 再训练触发条件
    │   ├── 累计交易数 >= 100
    │   ├── 胜率 < 50%
    │   └── 手动触发
    └── 数据窗口: 最近8个月
```

#### 4.4.2 再训练触发

| 条件 | 阈值 | 说明 |
|------|------|------|
| 累计交易数 | >= 100 | 数据量足够 |
| 胜率 | < 50% | 模型退化 |
| 手动触发 | - | 人工干预 |

---

## 5. L4 记忆体系

### 5.1 四级记忆架构

```
L1 实时记忆 (Real-time)
├── 即时行情、当前持仓、未决订单
└── 生命周期: 实时更新

L2 短期记忆 (Short-term)
├── 当日交易记录、近期案例
└── 生命周期: 1-7天

L3 长期记忆 (Long-term)
├── 历史案例库、蒸馏知识、统计指标
└── 生命周期: 长期保存

L4 归档记忆 (Archived)
├── 历史版本快照、约束升级记录
└── 生命周期: 永久归档
```

### 5.2 L4 记忆全链路（M0→M5）

```
M0_CASE_REGISTERED          Case注册
       ↓  (case_registry.py)
M1_REVIEW_COMPLETED        复盘完成
       ↓  (review_engine.py)
M2_DISTILLED                经验蒸馏
       ↓  (distill_engine.py)
M3_STATS_UPDATED           统计更新
       ↓  (stats_engine.py)
M4_INDEXED                  索引构建
       ↓  (index_builder.py)
M5_CANDIDATE_READY          候选就绪
       ↓  (进化评估)
  升级为约束? → evolution/ → constraints/
```

### 5.2.1 TradingAgents Review Agent 集成

L4 Review Engine 已集成 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 的两阶段复盘机制，增强复盘深度与多维度分析能力。

**集成组件：**

| 组件 | 文件 | 功能 |
|------|------|------|
| `L4MemoryLog` | `tradingagents_reflector.py` | TradingMemoryLog 的 L4 适配版，追加式决策日志 |
| `MultiDimensionalAnalyzer` | `tradingagents_reflector.py` | 多维度分析师（基本面/技术面/情绪面/风控面） |
| `Reflector` | `tradingagents_reflector.py` | 两阶段反思引擎（Phase A 记录决策 → Phase B 延迟反思） |
| `run_review()` | `review_engine.py` | 批量复盘入口，默认 `enable_tradingagents=True` |

**ReviewRecord 扩展字段：**

```json
{
  "tradingagents_reflection": {
    "reflection_text": "The long call on BTC was correct, delivering +2.50%...",
    "direction_correct": true,
    "confirmed_theories_count": 3,
    "contradicted_theories_count": 1,
    "lessons": [...],
    "past_context": "..."
  },
  "multi_dimensional_analysis": {
    "fundamentals_report": {"entry_price": ..., "leverage": ...},
    "technical_report": {"regime": ..., "volatility": ...},
    "sentiment_report": {"confidence": ..., "overall_bullish": ...},
    "risk_report": {"drawdown": ..., "stop_loss_triggered": ...},
    "summary": "..."
  }
}
```

**调用链：** `pipeline.py` M1 阶段 → `step_review()` → `review_engine.build_review_record()` → 自动调用 `Reflector.reflect()` → 生成 `tradingagents_reflection` + `multi_dimensional_analysis`。

### 5.2.2 evidence_chain 增强（TradingAgents 投研证据链结构）

`evidence_chain` 已从 5 维基础结构扩展为 6 维 TradingAgents 增强版，新增 `analyst_refs` 分析师维度证据。

**完整结构：**

```json
{
  "evidence_chain": {
    "market_data_refs": [{"type": "symbol", "ref": "BTC"}, ...],
    "signal_refs": [{"type": "hexagram", "ref": "水山蹇"}, ...],
    "strategy_refs": [{"type": "system_source", "ref": "yijing_inference"}, ...],
    "historical_refs": [{"type": "pnl", "ref": "0.025"}, ...],
    "constraint_refs": [{"type": "quadrant_x", "ref": "1.0"}, ...],
    "analyst_refs": [
      {"type": "yijing_analyst", "ref": "hexagram=水山蹇, confidence=0.91"},
      {"type": "technical_analyst", "ref": "regime=recovery|sprout, volatility=0.15"},
      {"type": "sentiment_analyst", "ref": "confidence=0.91, direction=long"},
      {"type": "risk_analyst", "ref": "leverage=3x"}
    ]
  }
}
```

**按系统来源的分析师映射：**

| 系统来源 | 专属 analyst | 通用分析师 |
|----------|-------------|-----------|
| `yijing_inference` | `yijing_analyst` (卦象+置信度+两仪) | technical + sentiment + risk |
| `martin_v15` | `martin_analyst` (加仓层级+配置) | technical + sentiment + risk |
| `three_screen` | `three_screen_analyst` (三屏信号) | technical + sentiment + risk |
| `agent_a` / `agent_b` | `{system}_analyst` (置信度+策略) | technical + sentiment + risk |
| `dream_os` | `dreamos_analyst` (融合模式+策略ID) | technical + sentiment + risk |

**构建入口：** `optimize_l4.py` → `_build_evidence_chain()` → 按 `system_source` 分派构建逻辑。`schema_validator.py` 已验证 `analyst_refs` 为可选字段（向后兼容）。

### 5.3 记忆沉淀闭环

```
实盘交易 → TradeCase → 复盘 → 蒸馏 → 统计 → 索引
                                       ↓
                         进化引擎评估候选质量
                                       ↓
                    通过 → 写入 constraints/ 新版本
                    失败 → 驳回并记录原因
                                       ↓
                           rollback 持续监控
```

**闭环规则：**
- 经验升格为制度必须经过 `evolution/` 通道
- 每条约束变更都要绑定来源证据：`episode_id/case_id/distill_id`
- 所有约束发布必须可回放、可审计、可回滚

### 5.4 共享内存总线

**Shared Memory Bus** — 跨Agent事件通信机制：

- 基于 JSONL 文件的事件流
- ACL 访问控制（agent_acl.py）
- 支持发布/订阅模式
- 事件统一格式: `{version, timestamp, agent_id, event_type, payload, trace_id}`

---

## 6. 自进化体系

### 6.1 三层反思闭环

当系统自身进化很难完成提升时（停滞检测）触发三层反思：

```
Layer 1: A8 理论与实践验证
    └── 内部批评自循环，检验理论与实践背离
    └── 6-TRADING/skills/A8-theory-practice-verification/
              ↓ 不够
Layer 2: 做梦部（dream-oneirology）
    └── 弗洛伊德潜意识视角，发现被压制的判断
    └── 6-TRADING/skills/dream-oneirology/
              ↓ 仍不够
Layer 3: 联网反思（Tavily + GitHub 成熟经验）
    └── 外部视角，搜索成熟量化策略，验证后引入
    └── scripts/memory_l4/tavily_macro.py
```

### 6.2 停滞检测触发条件

满足任一即触发自进化：
- 最近 N 轮胜率 < 45%（停滞）
- 连续 hold >= 10 轮（系统保守过度）
- 方向准确率连续下降 3 期
- 手动触发

### 6.3 约束升级通道

```
memory 经验沉淀
    ↓
形成 constraint_candidate
    ↓
evolution/feedback 接收
    ↓
evolution/audit 评估
    ↓
evolution/sandbox 回放与压测
    ↓
(通过) 写入 constraints 新版本
(失败) 驳回并记录原因
    ↓
evolution/rollback 持续监控与回滚
```

---

## 7. A0-A9 决策链

### 7.1 决策链概览

| 阶段 | 卦象 | 名称 | 职责 |
|------|------|------|------|
| A0 | 坤卦 | 矛盾分析 | 识别主要矛盾，定义问题边界 |
| A1 | 坎卦 | 深度调研 | 收集数据，调研背景，了解现状 |
| A2 | 艮卦 | 第一性原理 | 回归本质，拆解核心要素 |
| A3 | 巽卦 | 沙盘推演 | 多方案模拟，风险评估 |
| A4 | 震卦 | 战术验证 | 小范围验证，快速迭代 |
| A5 | 离卦 | 决策执行 | 正式执行，全力推进 |
| A6 | 兑卦 | 情报监控 | 实时监控，情报收集 |
| A7 | 乾卦 | 审计门禁 | 合规检查，质量门禁 |
| A8 | 复/渐卦 | 理论实践验证 | 理论与实践对照，深度反思 |
| A9 | 恒/归妹卦 | 离场决策 | 止盈止损，退出时机 |

### 7.2 与易经卦象的对应

每个阶段对应一个易经卦象，提供决策哲学指导：
- A0 坤卦：厚德载物 — 全面收集，不遗漏
- A1 坎卦：水善利万物而不争 — 深入调研，了解全貌
- A2 艮卦：高山仰止 — 回归本质，抓住核心
- A3 巽卦：随风潜入夜 — 灵活推演，多方案并行
- A4 震卦：春雷乍动 — 果断验证，快速行动
- A5 离卦：日月丽天 — 明确执行，光明正大
- A6 兑卦：泽被万物 — 广泛收集，全面监控
- A7 乾卦：天行健 — 严格标准，质量第一
- A8 复/渐卦：反复其道 / 循序渐进 — 螺旋上升
- A9 恒/归妹卦：恒久 / 归宿 — 知止不殆

---

## 8. CI/CD 与治理架构

### 8.1 CI/CD 体系

**16个CI脚本 + 6个GitHub Actions工作流**

| 类别 | 脚本数 | 核心功能 |
|------|--------|----------|
| 架构守护 | 2 | architecture_sync_guard, remote_repo_guard |
| 分支管理 | 2 | branch_lifecycle_bot, safe_main_merge_gate |
| 进化管理 | 5 | decision_gate, governance_report, candidate_priority, policy_regression, version_compare |
| 约束管理 | 3 | release_snapshot, constraint_rollback, review_policy_guard |
| 审计追溯 | 3 | post_merge_audit, trading_traceability_guard, quick_merge |

**GitHub Actions工作流：**

| Workflow | 触发 | 职责 |
|----------|------|------|
| safe-main-merge-gate.yml | PR合入前 | 代码质量与安全检查 |
| trading-ladder-a1-a3.yml | 推送 | 交易阶梯A1-A3阶段 |
| trading-a4-validation.yml | 推送 | A4战术验证 |
| trading-a5-execution.yml | 推送 | A5决策执行 |
| trading-a6-intelligence.yml | 定时 | A6情报监控 |
| trading-a8-governance.yml | 定时 | A8治理审计 |

### 8.2 治理架构

**Fail-closed 原则**：约束校验失败时默认中止关键执行。

**治理体系：**
- 审计优先：所有主链动作必须可生成审计产物
- 小步发布：约束升级先沙箱，后主链
- 回滚可用：每个约束版本都要有回滚目标

---

## 9. 数据流

### 9.1 实盘交易数据流

```
OKX API (K线)
    ↓
data_fetcher.py / okx_simulated.py
    ↓
特征工程 (bcrm2/*_features.py)
    ├── 八卦特征
    ├── 经典经验
    ├── WDH时间维度
    └── ...
    ↓
BCRM2Adapter (bcrm2_adapter.py)
    ├── 模型缓存检查 → 命中则直接推理
    └── 未命中 → DialecticalMLEngine 训练 (L1→L2→L3)
    ↓
DialecticalMLEngine (L1→L2→L3) → 置信度 + 方向
    ↓
KG知识图谱校准 → 历史胜率校准确信度
    ↓
A0矛盾分析 → 方向一致性校准 + 创伤信号检测
    ↓
五角校验 (TriangleVerifier)
    ├── BCRM2(ML) × 力学引擎(物理) × A0(矛盾)
    ├── Ising相变检测 → ORDERED/CRITICAL/DISORDERED
    ├── TDA拓扑突变 → Betti曲线+瓶颈距离
    ├── 一致性评分 → confidence_adjustment
    ├── 严重分歧 → fail_closed
    └── P3预警联动 → position_factor + sl_tighten + early_exit
    ↓
MarketRegimeClassifier (8种市态) → 仓位因子
    ↓
震荡市增强层 (RangingMarketEnhancer) ← 后置增强（见 §9.4）
    ├── 5态自适应（TREND_UP/DOWN, RANGING_UP/DOWN, SIDEWAYS）
    ├── BTC MA200 方向性偏向
    ├── 布林带双信号确认
    ├── 止损宽度动态化（震荡2.5-3×ATR / 趋势1.5×ATR / 过渡2.0×ATR）
    └── 置信度校准（分市态/卦象/方向）
    ↓
信号生成 (置信度阈值 0.60) + 仓位计算（含P3调整）
    ↓
CBR 案例检索增强 (CBRSignalEnhancer) ← 见 §9.5
    ├── 检索 L4 历史相似案例
    └── 融合策略：cbr_override / cbr_blend / bcrm_only
    ↓
RiskManager (日亏损/连续亏损熔断)
    ↓
OKX下单执行
    ↓
持仓跟踪 → YijingExitSystem 主离场决策 (见 §9.6)
    ├── 主路径: FORCE_CLOSE / RAISE_TP / HOLD（卦象驱动）
    ├── 降级路径: NO_INTERVENE 且风险偏高 → 调用 ClassicExitSystem
    ├── 备用路径: 无卦象 → 直接调用 ClassicExitSystem (P0→P1→P2→P3)
    └── 五角校验 early_exit_signal → 提前平仓
    ↓
交易记录 → PerformanceTracker
    ↓
Case生成 → save_case_to_l4()
    ↓
L4记忆管道 (pipeline.py)
    ↓
IncrementalLearner 检查触发再训练?
    ↓
(数据不足时) Fallback → BCRM 1.0 矛盾力学引擎
```

### 9.2 记忆沉淀数据流

```
TradeCase (M0)
    ↓
A0-A9阶段数据收集 (a0a9_bridge.py)
    ↓
复盘引擎 (review_engine.py) → M1_REVIEW_COMPLETED
    ↓
蒸馏引擎 (distill_engine.py) → M2_DISTILLED
    ↓
统计引擎 (stats_engine.py) → M3_STATS_UPDATED
    ↓
索引构建器 (index_builder.py) → M4_INDEXED
    ↓
候选就绪 → M5_CANDIDATE_READY
    ↓
进化引擎评估 → 升级为约束?
```

### 9.3 统一数据契约（v1）

所有关键产物统一包含：
- `trace_id`：一次完整决策链唯一 ID
- `stage_id`：A0-A9 或 memory 子阶段标识
- `constraint_version`：执行时使用的约束版本
- `memory_refs[]`：引用的记忆实体 ID
- `evidence_refs[]`：证据文件路径或证据 ID
- `timestamp`：UTC 时间戳
- `decision_summary`：阶段结论摘要

### 9.4 震荡市增强层（RangingMarketEnhancer）

**文件**: `scripts/memory_l4/ranging_market_enhancer.py`

**定位**: BCRM 2.0 信号生成后的后置增强层，与 BCRM/易经引擎解耦，纯函数式计算无状态。

**5 种市场状态自适应**:

| 状态 | 含义 | 参数偏向 |
|------|------|----------|
| `TREND_UP` | 趋势上涨 | 快速止损 1.5×ATR |
| `TREND_DOWN` | 趋势下跌 | 快速止损 1.5×ATR |
| `RANGING_UP` | 震荡偏多 | 偏多多头，空头需更高置信度 |
| `RANGING_DOWN` | 震荡偏空 | 偏好空头，多头需更高置信度 |
| `SIDEWAYS` | 横盘震荡 | 止损放宽 2.5-3×ATR |

**四大增强能力**:

1. **BTC MA200 方向性偏向**: BTC 在 MA200 上方 → 偏多多头；下方 → 偏好空头（需更高置信度 + 阻力/支撑确认）
2. **布林带双信号确认**: 易经信号 + 布林带信号（下轨支撑/上轨压力/中轨突破）同时满足才入场
3. **止损宽度动态化**: 震荡市 2.5-3×ATR（减少被洗盘）/ 趋势市 1.5×ATR（快速止损）/ 过渡市 2.0×ATR
4. **置信度校准机制**: 预测置信度 → 实际胜率校准表，分市态/分卦象/分方向校准；500+样本后启用 Platt 缩放，之前用简单分桶平均

**集成点**: `polling_trader.py` 通过 `self.ranging_enhancer` 调用，在 BCRM 信号生成后增强。

### 9.5 CBR 案例检索增强（CBRSignalEnhancer）

**文件**: `scripts/memory_l4/cbr_engine.py` / `cbr_similarity.py` / `cbr_sharded_retriever.py` / `cbr_adapter.py`

**定位**: 基于 Case-Based Reasoning 的相似案例检索与策略适配层，作为 BCRM 2.0 的辅助决策层。

> **环境要求**: Python 3.9+（原实现使用 PEP 695 类型别名和 dataclass slots，已向下兼容至 3.9）

**4R 循环**（参考 cbrkit, ICCBR 2024 Best Student Paper）:

| 阶段 | 说明 | 输出 |
|------|------|------|
| Retrieve | 从 L4 历史案例库检索相似市态案例 | Top-K 相似案例 + 相似度 |
| Reuse | 复用成功案例策略参数，规避失败案例陷阱 | 历史胜率 + 平均 PnL + 风险提示 |
| Revise | 根据当前市态和风险预算修正策略 | 修正参数 + 修正说明 |
| Retain | 新交易完成后自动保留到案例库 | 案例库增量更新 |

**相似度计算**: 特征距离 + 卦象匹配 + 市态对齐；支持分片检索（`cbr_sharded_retriever.py`）提升大规模案例库检索效率。

**三种融合策略**（`CBRSignalEnhancer.enhance()`）:

| 策略 | 触发条件 | 行为 |
|------|----------|------|
| `cbr_override` | CBR 历史胜率 > 60% 且 Top-1 相似度 > 0.5 | 信任 CBR，完全覆盖 BCRM 参数 |
| `cbr_blend` | CBR 历史胜率 40-60% | 混合 BCRM 和 CBR 参数 |
| `bcrm_only` | CBR 历史胜率 < 40% 或无相似案例 | 降级为 BCRM 原始信号 |

**集成点**: `polling_trader.py` 通过 `self.cbr_bridge.cbr` 调用，输出 `EnhancedSignal`（含 `cbr_similarity_top1`、`cbr_historical_win_rate`、`cbr_avg_pnl`、`fusion_method` 等元数据）。

### 9.6 易经离场系统（YijingExitSystem）— 主离场模块

**文件**: `scripts/memory_l4/yijing_exit_system.py`

**架构反转（v2）**: `YijingExitSystem` 作为主离场模块，`ClassicExitSystem` 降为备用。

**三条决策路径**:

| 路径 | 触发条件 | 动作 |
|------|----------|------|
| 主路径 | 卦象风险评估 + 价值评估 + 方向一致性 | `FORCE_CLOSE` / `RAISE_TP` / `HOLD` / `LOWER_SL` / `LOWER_TP` |
| 降级路径 | `NO_INTERVENE` 且风险偏高/价值偏低 | 调用 `ClassicExitSystem` 评估 |
| 备用路径 | `yijing_hexagram is None`（无卦象） | 直接调用 `ClassicExitSystem`（fail-open） |

**主路径决策规则**:

1. 卦象 `risk_level=高` + 方向冲突 + 风险分≥0.80 → `FORCE_CLOSE`
2. 卦象价值分>0.70 + 成长期/成熟期 + 飞龙在天/或跃在渊 + 已盈利 → `RAISE_TP`（TP 上浮 30%）
3. 卦象风险分<0.35 + 价值分>0.60 + 方向一致 + 亏损未破-3% + 未超 48h → `HOLD`
4. 其他 → `NO_INTERVENE`，降级调用 classic

**六爻阶段风险/价值映射**:

| 阶段 | 卦辞 | 风险分 | 价值分 |
|------|------|--------|--------|
| 初九 | 潜龙勿用 | 0.65 | 0.35 |
| 九二 | 见龙在田 | 0.40 | 0.65 |
| 九三 | 终日乾乾 | 0.55 | 0.55 |
| 九四 | 或跃在渊 | 0.45 | 0.70 |
| 九五 | 飞龙在天 | 0.25 | 0.90 |
| 上九 | 亢龙有悔 | 0.85 | 0.20 |

**集成点**:
1. **独立链路（polling_trader）**: `polling_trader.py` 通过 `self.yijing_exit_system.evaluate()` 调用，含 `set_log_callback()` 日志钩子；veto 机制支持 `VETO_CLOSE` / `VETO_REDUCE` 否决 classic 决策。
2. **DreamOS 链路（auto_trader）**: 通过 `YijingExitAdapter` 适配器封装为统一接口，经 `ExitModuleSelector` 按场景回测表现择优调用（详见 §9.8）。

### 9.7 经典离场系统（ClassicExitSystem）— 备用离场模块

**文件**: `scripts/memory_l4/classic_exit_system.py`

**角色**: 作为 `YijingExitSystem` 的降级/备用路径，也可独立运行。实现四大优先级离场架构。

**四大优先级（由高到低）**:

| 优先级 | 模块 | 触发条件 | 动作 |
|--------|------|----------|------|
| P0 | L0 硬退出 | 最大持仓时间 / 最大未实现亏损 / 强平缓冲 / 周线反转 / 风险闸门 | CLOSE / REDUCE |
| P2 | Triple Barrier | ATR 止损/止盈/时间屏障 | CLOSE / REDUCE |
| P3 | 跟踪止损 + 移动止盈 + TSTP | Trailing Stop / Trailing TP / 时间衰减止盈 | CLOSE / REDUCE / RAISE_TP |
| P1 | L1/L2 价值-风险评估 | hold_risk / hold_value 阈值 | CLOSE / REDUCE / RAISE_TP / HOLD |

**v2.6 重大修复（8 项缺陷）**:

#### P0 致命缺陷修复

1. **dd 计算重写**（`_compute_features`）:
   - 修复前：用 K 线窗口 peak/trough 代替持仓回撤，且 mfe 启用门槛导致亏损单 dd=0
   - 修复后：基于 `entry_price` 和 `current_price` 计算真实持仓回撤，优先使用 `pos.max_dd_pct`
   - 影响：`hold_risk` 核心输入 `dd_risk`（权重 0.42）不再失真

2. **hold_value 独立计算**（新增 `_calc_hold_value`）:
   - 修复前：`hold_value = 1 - hold_risk`，等价反推导致亏损单价值虚高，误触发 RAISE_TP
   - 修复后：独立评估，基于趋势一致性(0.30) + 动量延续(0.20) + 量价配合(0.15) + ADX强趋势(0.15) + 盈利加成(0.20) - 震荡市惩罚
   - 影响：RAISE_TP 仅在真正趋势+盈利+动量一致时触发

3. **Choppiness Index 实现**（新增 `_calc_chop`）:
   - 修复前：`feats.chop` 永远为默认值 50.0，`_calc_hold_risk` 中 `chop_risk` 为死代码
   - 修复后：实现标准 CI 公式 `100 * log10(sum(ATR) / (HH-LL)) / log10(n)`，>61.8 为震荡市
   - 影响：震荡市识别恢复，hold_risk 和 hold_value 均接入 chop 因子

#### P1 参数调优（经贝叶斯寻优最终定参）

4. **L0 `max_loss_pct` -0.05 → -0.15 → -0.1915（贝叶斯寻优）**:
   - 修复前：3x 杠杆下价格跌 1.67% 即触发强平，加密日内波动频繁扫损
   - 修复后：-0.15（3x 杠杆下价格跌 5% 才触发）
   - 寻优后：-0.1915（3x 杠杆下价格跌 ~6.4% 触发），进一步减少假突破扫损

5. **L2 `close_threshold` 0.75 → 0.65 → 0.6721（贝叶斯寻优）**:
   - 修复前：阈值过高，配合 dd 计算缺陷 hold_risk 难以达到，等到触发时已大亏
   - 修复后：0.65，与 `risk_gate_long_thr=0.50` 形成更合理阶梯
   - 寻优后：0.6721，在 0.65 基础上微调，`reduce_threshold` 同步至 0.5599

6. **风险闸门 `cooldown` 30min → 10min → 11.11min（贝叶斯寻优）**:
   - 修复前：armed 后等 30 分钟才减仓，加密行情 30 分钟可让 -2% 扩大到 -10%
   - 修复后：10 分钟响应
   - 寻优后：11.11 分钟，在噪声过滤与响应速度间取得最优平衡

7. **TSTP 亏损超时释放死仓**:
   - 修复前：盈利 < 成本缓冲时直接 HOLD，长时间无盈利持仓占用仓位
   - 修复后：持仓达最大阶段且仍无盈利 → `CLOSE_NO_PROFIT`（价值低）或 `REDUCE_NO_PROFIT`（价值尚可）

#### 9.7.1 离场系统对比实验与回退决策

**实验脚本**: `scripts/memory_l4/exit_comparison.py`

**回测条件**: 4 币种（BTC/ETH/SOL/UNI）× 252 笔交易 × 3x 杠杆 × 0.1%/边手续费

**四组离场策略对比**:

| 指标 | 原始BCRM | ClassicExit修复版 | ATR自适应 | 贝叶斯寻优 |
|------|:---:|:---:|:---:|:---:|
| 总收益率%(加总) | **+334.73** | +6.16 | +5.67 | +2.61 |
| 总收益率%(账户) | **+16.74** | +0.31 | +0.28 | +0.13 |
| 胜率% | 70.2 | **80.2** | 61.5 | 57.9 |
| 夏普比率 | **33.15** | 33.03 | 28.39 | 17.47 |
| 最大回撤%(账户) | 2.46 | 0.03 | **0.02** | 0.02 |
| 盈亏比 | 2.61 | **3.48** | 2.29 | 2.03 |
| 平均持仓h | **29.0** | 7.5 | 10.4 | 4.3 |
| 综合评分 | **36.38** | 33.09 | 28.45 | 17.50 |

> **结论**: 原始 BCRM 离场（tp/sl/time）全面碾压所有复杂离场系统。ComplexExitSystem 和 ATR 自适应离场的根本问题是**过早平仓**（平均持仓 4-10h vs 原始 29h），导致利润无法充分奔跑。虽然复杂系统在回撤控制上略优（0.02% vs 2.46%），但收益牺牲超过 98%，得不偿失。

**回退决策**: ClassicExitSystem 参数全部回退到保守值，L0_RISK_GATE 默认关闭，仅保留 L0 硬止损作为安全网。原始 BCRM 的 tp/sl/time 离场作为主离场策略。

**回退后 ExitConfig 默认值**:

| 参数 | 贝叶斯寻优值 | 回退值 | 说明 |
|------|-------------|--------|------|
| `l0_risk_gate_enabled` | True | **False** | 风险闸门默认关闭（收益杀手） |
| `l0_max_loss_pct` | -0.1915 | **-0.20** | L0 硬止损放宽到极端亏损 |
| `l0_risk_gate_long_thr` | 0.50 | **0.75** | 阈值提高（仅启用时生效） |
| `l0_risk_gate_confirm_n` | 2 | **4** | 确认次数提高 |
| `l2_close_threshold` | 0.6721 | **0.80** | L2 平仓阈值提高 |
| `tb_sl_atr_mult` | 1.0261 | **1.5** | 三重屏障止损恢复原始值 |
| `tb_tp_atr_mult` | 2.0298 | **3.0** | 三重屏障止盈恢复原始值 |
| `trailing_arm_profit_pct` | 0.0991 | **0.06** | 跟踪止损恢复原始值 |
| `trailing_retrace_pct` | 0.0500 | **0.03** | 跟踪止损恢复原始值 |
| `l2_raise_tp_value_thr` | 0.7874 | **0.65** | RAISE_TP 恢复原始值 |
| `l2_raise_tp_risk_thr` | 0.3623 | **0.30** | RAISE_TP 恢复原始值 |

**新增盈利旁路机制**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `l0_risk_gate_profit_bypass_enabled` | True | 盈利旁路开关 |
| `l0_risk_gate_profit_bypass_pct` | 0.03 | pnl_eff > 3% 时跳过 risk_gate |

**ATR/市态/币种分组对比（原始BCRM vs ATR自适应）**:

| 维度 | BCRM收益% | ATR收益% | 差异% |
|------|----------|---------|-------|
| uptrend | +52.34 | +1.08 | -51.26 |
| downtrend | +128.30 | +2.48 | -125.81 |
| trend | +38.31 | +0.39 | -37.91 |
| chop | +115.79 | +1.71 | -114.08 |
| low_atr | +81.35 | +1.07 | -80.28 |
| mid_atr | +103.64 | +1.87 | -101.77 |
| high_atr | +149.74 | +2.72 | -147.01 |
| BTC | +68.52 | +0.87 | -67.65 |
| ETH | +53.80 | +0.30 | -53.50 |
| SOL | +92.93 | +2.13 | -90.80 |
| UNI | +119.49 | +2.36 | -117.12 |

> ATR 自适应离场在所有市态、所有波动率分组、所有币种上均远逊于原始 BCRM。

**杠杆口径统一**: 所有止盈/止损/时间止盈/移动止盈的触发判断统一使用 `pnl_eff`（含杠杆收益率）。

### 9.8 DreamOS 离场模块集成（YijingExitAdapter + ExitModuleSelector）

**文件**:
- `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_adapter.py` — YijingExitAdapter
- `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_selector.py` — ExitModuleSelector
- `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_backtester.py` — ExitModuleBacktester
- `1-ARCHITECTURE/dreamos/core/memory/exit_performance_memory.json` — 性能记忆表

**架构定位**: 将 YijingExitSystem 封装为 DreamOS 统一离场接口（`UnifiedExitDecision`），通过 `ExitModuleSelector` 按场景回测表现与 classic / simple 模块公平竞争择优。

#### 9.8.1 YijingExitAdapter 实现

**卦象数据来源（三级降级，零回归保障）**:

| 级别 | 来源 | 说明 |
|------|------|------|
| L1 | `market_data['hexagram_result']` | 未来 A_YJ_INFER 节点注入 |
| L2 | `market_data['yijing_hexagram']` | A2 综合感知节点注入 |
| L3 | `_synthesize_hexagram()` | 基于 scenario_id + change_24h + rsi14 + atr_pct 合成（回测/冷启动自动启用） |

**决策映射（9→4）**:

| YijingExitAction | UnifiedExitDecision | 说明 |
|-----------------|---------------------|------|
| `FORCE_CLOSE` | `CLOSE` + exit_price | 方向冲突+高风险 |
| `LOWER_TP` | `CLOSE` + exit_price | 风险升高提前锁定利润 |
| `RAISE_TP` | `RAISE_TP` + new_tp_price | 价值高+成长期/成熟期 |
| `LOWER_SL` / `TIGHTEN_SL` / `ADJUST_SL_TP` | `HOLD` + 动态 SL/TP 调整 | 按 adjust_pct 重算基准 ATR SL/TP |
| `VETO_CLOSE` / `VETO_REDUCE` / `NO_INTERVENE` | `HOLD` | 不干预 |

**SL/TP 动态调整**: 基准 `SL=1.5×ATR, TP=3.0×ATR`（RR=2），叠加 `sl_adjust_pct`（正数放宽/负数收紧）和 `tp_adjust_pct`（正数提高/负数降低）。

**懒加载路径**: 优先 `$DREAMBUDDY_ROOT/11-易经推理系统/scripts/memory_l4/yijing_exit_system.py`，向上递归查找 `11-易经推理系统` 目录。

#### 9.8.2 回测结果（3 场景 × 592 交易）

**回测条件**: BTC/ETH/SOL × 2161 根 1h K线 × 窗口 48 × 步长 8 × 持仓 20 根

| 场景 | yijing score | classic score | simple score | 最优 |
|------|:-----------:|:------------:|:-----------:|:----:|
| NEUTRAL_NORMAL_ACCELERATING | 3.187 (sharpe 6.76, ret 88.42%) | 3.187 (相同) | 2.410 | classic/yijing 并列 |
| NEUTRAL_HIGH_ACCELERATING | 2.406 | 2.406 | **3.727** | simple |
| NEUTRAL_LOW_ACCELERATING | −1.023 | −1.028 | −1.336 | 所有模块负分 → auto_trader 回退内置逻辑 |

**记忆表**: `exit_performance_memory.json` 已写入 3 场景 × 3 模块（classic/simple/yijing）完整指标。

**Selector 验证**: 当 yijing score 最高时，`ExitModuleSelector.select()` 返回 `module_name=yijing, fallback_level=0`（L0 精确匹配）；所有模块 score<0 时返回 `fallback_level=3`，auto_trader 回退内置 ATR 逻辑（零回归保护）。

#### 9.8.3 易经与经典离场评估重叠分析

**输入信号层**: 完全不同，零重叠。
- 经典: 技术指标量化（RSI/ADX/EMA/MACD/资金流 → hold_risk / hold_value）
- 易经: 卦象 7 维加权（risk_level×0.40 + phase×0.18 + stage×0.18 + direction×0.24）

**决策动作层**: 3 项重叠（CLOSE / RAISE_TP / TIGHTEN_SL），但触发条件和计算机制完全不同，为互补关系而非冗余。

**经典独有**: L0 硬退出（超时/亏损/强平/周线反转/风险闸门）、P2 Triple Barrier、P3 Trailing Stop / TSTP、L2 REDUCE 分批减仓。

**易经独有**: 1h 节奏门禁、LOWER_SL（放宽止损）、LOWER_TP（降低止盈）、VETO_CLOSE/REDUCE（否决机制）、方向冲突检测、冷静期保护。

**结论**: 两个模块在信号层和独有能力层有清晰边界，重叠仅存在于动作空间交集且触发条件各异，不需要修改评估逻辑。当 `ExitModuleSelector` 选中 yijing 时，经典 L0 安全硬退出会被跳过，通过 auto_trader 内置 check_exit P1（时间衰减+ATR止损）作为兜底补偿。

#### 9.8.4 实盘启用

当前默认零回归安全模式（`DREAMOS_EXIT_SELECTOR_ENABLED=0`），auto_trader check_exit 走内置 ATR 逻辑。启用易经离场择优：

```bash
export DREAMOS_EXIT_SELECTOR_ENABLED=1
```

未来 A_YJ_INFER 节点接入后，将真实卦象写入 `market_data['hexagram_result']`，L3 合成 fallback 自动升级为 L1 真实卦象。

---

## 10. 配置管理

### 10.1 配置层级

| 层级 | 位置 | 说明 |
|------|------|------|
| L1 | 代码默认值 | 最低优先级，保底配置 |
| L2 | configs/*.json | 系统级配置，如baseline_config.json |
| L3 | 环境变量 | 部署级配置，覆盖文件配置 |
| L4 | 命令行参数 | 最高优先级，单次运行覆盖 |

### 10.2 BCRM 2.0 基线配置

**文件**: `configs/baseline_config.json`

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 币种 | BTC, ETH, SOL, UNI | 4个币种 |
| K线周期 | 1H | 1小时K线 |
| 数据量 | 6000根 | 约8个月 |
| Walk-Forward折数 | 5 | 80%训练/20%验证 |
| 置信度阈值 | 0.60 | 实盘优化值（回测最优）；代码默认 0.55，实盘通过配置覆写 |
| 止盈 | 3.0x ATR | 动态止盈 |
| 止损 | 2.0x ATR | 动态止损 |
| 最大持仓 | 60根K线 | 约2.5天 |
| 市态切换 | ✅ 启用 | 8种市态自适应 |
| 仓位管理 | ✅ 启用 | position_factor调整阈值 |
| auto_mcap | ✅ 启用 | 按市值等级配置特征 |
| 特征选择 | ✅ 启用 | LightGBM重要性+相关性去冗余 |
| 组合回测 | ✅ 启用 | 大40%/中35%/小25% |
| 美林时钟 | ❌ 禁用 | 实验中 |
| Meta-Labeling | ❌ 禁用 | 调试中 |

---

## 11. 逐仓风控模式

### 11.1 设计原则

**核心原则**: 风险隔离，单个币种亏损不蔓延至其他持仓。

| 模式 | 特点 | 风险 | 适用场景 |
|------|------|------|----------|
| **逐仓 (isolated)** | 每个合约独立保证金账户 | 单币种最多损失该笔保证金 | 多币种策略，风险隔离优先 |
| 全仓 (cross) | 所有持仓共享账户权益 | 一个币种爆仓影响全部 | 单币种或高胜率策略 |

易经推理系统默认采用 **逐仓模式**。

### 11.2 技术实现

**配置项**: `td_mode = "isolated"`（可通过环境变量 `OKX_TD_MODE` 覆盖）

**代码位置**: [okx_simulated.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/okx_simulated.py)

- `DEFAULT_CONFIG["td_mode"]` = `"isolated"`
- `_load_config()` 支持从 `data/okx_sim/config.json` 和环境变量读取
- `place_order()` 从配置读取，不再硬编码 `td_mode`
- `place_stop_loss_take_profit()` 止盈止损单同步使用配置的 td_mode

**保证金检查**: [polling_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py)

| 模式 | 检查逻辑 |
|------|----------|
| 逐仓 | `USDT可用余额 ≥ 开仓所需保证金` |
| 全仓 | `总权益 - 已用保证金(IMR) ≥ 开仓所需保证金` |

**仓位计算逻辑**（v2.3 修正）：

`_open_position()` 在计算仓位大小时，先查询账户实际可用余额，再传递给 `calc_position_size()`：

```python
# 获取实际可用资金（而非总权益）
if td_mode == "isolated":
    available_equity = avail_usdt  # 逐仓：USDT可用余额
else:
    available_equity = total_eq - total_imr  # 全仓：总权益 - 已用保证金

# 用可用余额计算仓位（而非总权益）
pos_size_info = self.risk_manager.calc_position_size(
    confidence=confidence,
    volatility=volatility,
    current_equity=available_equity,  # ← 关键修正
)
```

**修正原因**：当多个交易系统共用同一账户时（如 V15 马丁 + 三屏趋势 + 易经推理），总权益包含其他系统占用的保证金，直接使用总权益计算会导致仓位过大、开仓失败。

### 11.3 资金分配

- 默认杠杆: 3x
- 单仓位资金比例: 10%（position_pct）
- 最大持仓数: 10 个币种
- 单币种保证金 = `仓位价值 / 杠杆`，独立占用

### 11.4 切换方式

```bash
# 切换为全仓模式（不推荐，仅作回测对比）
export OKX_TD_MODE=cross

# 恢复逐仓模式（默认）
export OKX_TD_MODE=isolated
```

---

## 11.5 监控告警集成

易经推理系统已接入 [15-监控告警系统](../../15-监控告警系统/)，实现统一监控和异常告警。

### 监控适配器

**文件**: [15-监控告警系统/adapters/yijing_adapter.py](../../15-监控告警系统/adapters/yijing_adapter.py)

| 监控项 | 检查逻辑 | 告警级别 |
|--------|----------|----------|
| 进程心跳 | 检查 `data/polling_trader/` 下最新日志时间戳 | CRITICAL（>3小时无日志） |
| 交易活跃度 | 检查当日交易笔数是否为0 | WARNING（连续6小时无交易） |
| 持仓健康 | 检查持仓浮动盈亏是否超过日亏损限额 | ERROR |
| 模型状态 | 检查 BCRM 2.0 模型是否正常加载 | ERROR |
| 余额充足性 | 检查可用 USDT 是否低于最低开仓要求 | WARNING |

### 飞书告警

**文件**: [scripts/memory_l4/yijing_feishu_alert.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/yijing_feishu_alert.py)

- 告警类型：heartbeat / trading / model / position / system / performance
- 告警级别：critical / error / warning / info
- 推送目标：飞书管理后台群组
- 配置方式：环境变量 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`

### 调度配置

| 任务 | 频率 | 入口 |
|------|------|------|
| 健康检查 | 每小时 | `yijing_monitor.py` → `YijingAdapter.check_health()` |
| 完整监控 | 每3小时 | `yijing_monitor.py` → 全量检查 + 飞书推送 |
| 自进化触发 | 每4小时或10笔新交易 | `self_evolution_engine.py` |

---

## 12. 性能基准

### 12.1 BCRM 2.0 基线回测（6000根1H K线）

**配置**: 市态切换 + auto_mcap + 特征选择 + 组合回测

#### 单币种表现（Phase 0 基线）

| 币种 | 市值 | 特征数 | 交易数 | 胜率 | 总收益 | 最大回撤 | 盈亏比 | 夏普 |
|------|------|--------|--------|------|--------|----------|--------|------|
| BTC | 大 | 429 | 43 | 81.4% | 68.52% | 4.58% | 5.14 | 10.67 |
| ETH | 大 | 463 | 52 | 71.2% | 53.79% | 14.30% | 2.37 | 5.77 |
| SOL | 中 | 463 | 65 | 75.4% | 92.92% | 11.20% | 3.02 | 7.88 |
| UNI | 小 | 402 | 92 | 60.9% | 119.48% | 33.45% | 2.12 | 5.62 |

#### 组合层指标

| 指标 | Phase 0 基线 | 五角校验+贝叶斯优化后 |
|------|----------|----------|
| 组合总收益 | 86.85% | — |
| 组合胜率 | 70.2% | — |
| 组合盈亏比 | 2.61 | — |
| 组合夏普 | 6.61 | — |
| 组合最大回撤 | 12.75% | **11.8%** |
| **综合夏普(加权)** | **7.45** | **8.20** |

> 注：8.20 为接入五角校验（§4.1.1c）+ Optuna TPE 贝叶斯优化 8 参数后（§4.1.1c 末尾参数表）的回测综合夏普；回撤由 12.75% 改善至 11.8%。详见 `bayesian_optimize.py` 与 `pentagon_backtest.py`。

---

## 13. 技术栈

| 组件 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 编程语言 | Python | 3.9+ | 核心引擎与交易 |
| ML框架 | LightGBM / XGBoost | latest | 辩证ML、Meta-Labeling |
| 数据处理 | Pandas / NumPy | latest | 特征工程、回测 |
| 特征工程 | scikit-learn | latest | 特征选择、标准化 |
| 数据存储 | SQLite | built-in | 交易记录、版本管理 |
| 行情接口 | OKX API | v5 | 实盘行情与交易 |
| 回测引擎 | 自研 | v2.0 | Walk-Forward + 组合回测 |
| CI/CD | GitHub Actions | - | 架构门禁、进化门禁 |
| 进程管理 | launchd (macOS) | - | 定时任务调度 |
| 技能体系 | Skills (5大类) | - | 模块化能力封装 |

---

## 14. 系统边界

### 14.1 负责范围

✅ **本系统负责：**
- 易经哲学框架下的交易决策推理
- BCRM 1.0/2.0 双引擎的开发与维护
- QMM量化记忆模型的开发与维护
- L4级记忆体系（案例、复盘、蒸馏、索引）
- A0-A9决策链编排
- 自进化闭环（经验→约束升级）
- CI/CD与治理架构
- 与OKX的交易接口

### 14.2 不负责范围

❌ **本系统不负责：**
- 整体DreamOS的系统级调度（由master_daemon负责）
- 通用风控引擎（由13-通用风控模块负责）
- V15马丁策略、经典指标系统等其他策略系统
- 前端界面开发
- 资金账户管理
- 多系统组合配置（由全局配置系统负责）

---

## 15. 未来优化方向

### 15.1 Phase 0 ✅ 已完成
- [x] BCRM 2.0基础框架
- [x] 八卦特征引擎
- [x] 辩证ML三层架构
- [x] Walk-Forward回测
- [x] 组合回测
- [x] 市态切换（8种市态）

### 15.2 Phase 1 ✅ 已完成
- [x] 增量学习闭环
- [x] PollingTrader集成（实盘）
- [x] WDH时间维度特征
- [x] auto_mcap市值等级配置
- [x] 特征选择模块
- [x] **BCRM 2.0实盘切换**（BCRM2Adapter + 置信度优化0.60）
- [x] **ClassicExitSystem离场系统集成**（四优先级 CLOSE/REDUCE/RAISE_TP/HOLD）
- [x] **逐仓风控模式**（td_mode=isolated，风险隔离）

### 15.3 Phase 2 ⚠️ 进行中
- [ ] 美林时钟特征优化
- [ ] Meta-Labeling V2调试（L2训练失败问题待排查）
- [ ] 跨资产特征深化
- [ ] 市场模式聚类
- [ ] 异常检测（混合架构）
- [ ] 小币种数据不足Fallback策略优化

### 15.4 Phase 3 📋 规划中
- [x] **YijingExitAdapter DreamOS 集成** ✅ 已实现 — 卦象三级降级注入 + 9→4 决策映射 + ATR 基准 SL/TP 动态调整（详见 §9.8）
- [x] **ExitModuleBacktester yijing 回测** ✅ 已实现 — 3 场景 × 592 交易全量回测，性能数据写入 exit_performance_memory.json
- [x] **ExitModuleSelector 择优验证** ✅ 已实现 — L0 精确匹配选中 yijing，fallback_level=3 零回归保护
- [ ] BCRM 1.0与2.0深度融合
- [ ] QMM与BCRM的深度集成
- [ ] 多时间框架融合
- [ ] 强化学习优化
- [ ] 情绪分析集成
- [ ] 链上数据接入
- [ ] 统一API网关
- [ ] 配置中心化

### 15.5 Phase 4 🧠 认知增强
- [x] **CBR 案例检索引擎** ✅ 已实现 — 基于 Case-Based Reasoning 的相似案例检索与策略适配
  - 已实现：4R 循环（Retrieve → Reuse → Revise → Retain），参考 cbrkit（ICCBR 2024 Best Student Paper）
  - 已实现：案例相似度计算（特征距离 + 卦象匹配 + 市态对齐）、分片检索（`cbr_sharded_retriever.py`）
  - 已实现：三种融合策略 `cbr_override` / `cbr_blend` / `bcrm_only`（见 §9.5）
  - 已集成：`polling_trader.py` 通过 `CBRSignalEnhancer` 调用，输出 `EnhancedSignal`
- [ ] LLM 驱动的案例摘要生成（长案例压缩为决策要点）
- [ ] 跨币种案例迁移学习（BTC 成功案例适配到 ETH/SOL）

---

## 16. 变更日志

| 日期 | 版本 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 2026-08-01 | v3.0 | **DreamOS 离场模块集成**：①新增 §9.8 DreamOS 离场模块集成章节（YijingExitAdapter + ExitModuleSelector + ExitModuleBacktester）；②YijingExitAdapter 从占位符升级为完整实现（懒加载+三级卦象降级+9→4决策映射+ATR基准SL/TP动态调整）；③ExitModuleBacktester 补充 change_24h/rsi14 动态注入，支持 yijing 卦象合成 fallback；④3场景×592交易全量回测，性能数据写入 exit_performance_memory.json；⑤ExitModuleSelector L0 精确匹配验证通过（yijing score最高时选中 yijing）；⑥§9.6 集成点补充 DreamOS 链路描述；⑦§15.4 Phase 3 标记 3 项已完成；版本号 v2.9→v3.0 | DreamBuddy v2 |
| 2026-07-25 | v2.9 | **P1修复与系统增强**：①修复 `inspect.py` 模型路径错误（从 `.workbuddy/memory_l4/bcrm2/` 修正为 `scripts/data/bcrm2_models/`，新增目录扫描统计 L1/L2 模型数、币种数、周期数）；②安装 ripser + persim 依赖，TDA 拓扑检测第五源恢复可用（五角校验五源齐全）；③新增多场景验证脚本（25个用例覆盖推理/离场/风控/反馈/异常五场景，全部通过）；④币种规模从 4 扩展至 27（含 BTC/ETH/SOL/BNB/XRP/SEI/TIA/IMX 等，小市值<5亿剔除）；⑤技术栈补充 ripser/persim/Optuna；版本号 v2.8→v2.9 | DreamBuddy v2 |
| 2026-07-24 | v2.8 | **A8 SKILL 系统自评估与多场景验证**：新增A8纯理性内部批判自循环评估框架；生成系统现状评估报告（胜率13.3%、卦象分布偏斜、7条反馈链路断裂等问题识别）；多场景验证框架设计；版本号 v2.7→v2.8 | DreamBuddy v2 |
| 2026-07-24 | v2.7 | **ClassicExitSystem 离场参数优化与 ATR 自适应离场系统**：Optuna 贝叶斯优化后夏普提升、回撤降低；新增 ATR 波动率分组自适应离场（低/中/高三档 + 8市态 + 币种适配）；新增离场系统对比回测框架；版本号 v2.6→v2.7 | DreamBuddy v2 |
| 2026-07-24 | v2.6 | **ClassicExitSystem 重大修复（8 项缺陷）**：①dd 计算重写，基于 entry_price 而非 K 线窗口 peak/trough，移除 mfe 启用门槛（修复亏损单 dd=0 导致 hold_risk 失真）；②hold_value 独立计算，新增 `_calc_hold_value` 方法（修复 `1-risk` 等价反推导致 RAISE_TP 误触发）；③实现 Choppiness Index（修复 chop 永远=50 死代码）；④L0 max_loss_pct -0.05→-0.15（避免 3x 杠杆下 1.67% 波动扫损）；⑤L2 close_threshold 0.75→0.65；⑥风险闸门 cooldown 30min→10min；⑦TSTP 亏损超时改为 REDUCE/CLOSE 释放死仓；⑧新增 §9.7 经典离场系统章节；版本号 v2.5→v2.6 | DreamBuddy v2 |
| 2026-07-24 | v2.5 | **文档与代码同步更新**：①§9.1 数据流反映离场架构反转（`YijingExitSystem` 为主离场，`ClassicExitSystem` 降为备用）；②新增 §9.4 震荡市增强层（`RangingMarketEnhancer`，5 态自适应+布林双信号+动态止损+置信度校准）；③新增 §9.5 CBR 案例检索增强（4R 循环+三种融合策略 `cbr_override`/`cbr_blend`/`bcrm_only`）；④新增 §9.6 易经离场系统（三条决策路径+六爻阶段风险/价值映射）；⑤§15.5 Phase 4 CBR 状态从"📋 规划中"改为"✅ 已实现"；⑥§1.3 与 §12 性能基准统一标注 Phase 0 基线（7.45）与五角校验+贝叶斯优化后（8.20）两套数值，消除自相矛盾；版本号 v2.4→v2.5 | DreamBuddy v2 |
| 2026-07-21 | v2.4 | **新增§5.2.1 TradingAgents Review Agent 集成**：L4 Review Engine 集成 TradingAgents 两阶段复盘机制（L4MemoryLog + MultiDimensionalAnalyzer + Reflector）；**新增§5.2.2 evidence_chain 增强**：从 5 维扩展为 6 维（新增 `analyst_refs`），支持按系统来源分派分析师维度；**新增§15.5 Phase 4 认知增强**：CBR 案例检索引擎、LLM 案例摘要、跨币种迁移学习；版本号 v2.3→v2.4 | DreamBuddy v2 |
| 2026-07-15 | v2.3 | **保证金计算逻辑修正**：`_open_position()` 使用可用余额（而非总权益）计算仓位，解决多系统共用账户时仓位过大的问题；新增§11.5监控告警集成（15-监控告警系统适配器 + 飞书告警）；BCRM 2.0实盘验证通过（BTC/ETH开仓成功） | DreamBuddy v2 |
| 2026-07-15 | v2.2 | 仓位模式从全仓(cross)切换为逐仓(isolated)；新增第11章逐仓风控模式；okx_simulated.py默认td_mode=isolated；polling_trader.py支持逐仓/全仓保证金检查；Phase 1增加逐仓风控模式标记 | DreamBuddy v2 |
| 2026-07-14 | v2.1 | BCRM 2.0实盘切换：新增§3.3.3 BCRM2Adapter适配层；更新数据流（含Fallback机制）；置信度阈值0.60；Phase 1标记BCRM 2.0实盘+离场集成完成；Phase 2增加L2修复和小币种Fallback优化 | DreamBuddy v2 |
| 2026-07-13 | v2.0 | 扩展为完整系统级技术设计，增加顶层架构、BCRM 1.0、QMM、L4记忆、自进化、A0-A9、CI/CD治理等章节 | DreamBuddy v2 |
| （历史） | v1.0 | 初始版本，仅覆盖BCRM 2.0量化引擎 | BCRM 2.0团队 |

---

_维护原则：本文件是易经推理系统的技术设计基线，任何架构级变更必须同步更新本文件。_

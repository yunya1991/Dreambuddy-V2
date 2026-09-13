# SPEC: 自进化交易系统 → 交易AGI升级蓝图

> **状态：** Spec（待评审·v2·哲学修订）
> **创建：** 2026-09-10
> **目标：** 以"万物皆数·最小阻力路径"为核心哲学，将当前系统升级为**深度学习驱动**的交易AGI——统计学→抽象模型→多路径计算→最优路径→最小阻力
> **硬约束：** FAIL-OPEN 铁律不可破坏；不破坏现有四层闭环/认知记忆/BCRM2.0/BDSM/战略层接入；新能力以模块化开关接入，默认关闭，验证后渐进开启
> **架构原则：** 自进化系统是AGI核心，消费战略层/BCRM2.0/BDSM作为感知输入；**精细管理而非辩论**；**深度学习而非大语言模型**；**数据驱动·万物皆数**

***

## 零 · 现状基线（纠正前置误判）

### 0.1 三系统接入关系（代码验证）

经代码考古确认，自进化系统与三个外部子系统的接入关系是 **"自进化系统消费三系统作为输入"**，不是"战略层调控自进化系统"：

| 接入方向 | 接入点 | 代码位置 | 数据流 |
| :--- | :--- | :--- | :--- |
| 战略层 → 自进化 | `SubSystemBridge.get_war_state()` | [subsystem_bridge.py:L45-66](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/subsystem_bridge.py) | war_state → Feynman温度T → ESS评分调制 |
| 战略层 → 自进化 | `get_ess_temperature()` | [subsystem_bridge.py:L64-66](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/subsystem_bridge.py) | ALLOW=1.0/COOLDOWN=0.5/RESTRICT=0.2/FREEZE=0.1 |
| BCRM2.0 → 自进化(开仓) | `compute_bcrm_entry_weight_factor()` | [entry_signal_governor.py:L84-133](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/entry_signal_governor.py) | 反向信号分层：≥0.95硬否决/0.85-0.95×0.5/0.80-0.85×0.7 |
| BCRM2.0 → 自进化(离场) | `_decide_impl()` 规则2b | [exit_engine.py:L374-423](file:///Users/zhangjiangtao/WorkBuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/exit_engine/exit_engine.py) | 反向信号分层减仓：30%/50%/70%(BDSM共振) |
| BDSM → 自进化(开仓) | `_apply_bdsm_direction_constraint` | polling_trader.py | direction_constraint: LONG_ONLY/SHORT_ONLY/NEUTRAL |
| BDSM → 自进化(离场) | exit_action/trend_stop | exit_engine.py | bds_score/bds_score<-0.3→SHORT_ONLY |

**结论：** 三系统接入架构是健全的，AGI升级不是"补接入"，而是在已有接入基础上补"认知深度"和"自主进化"。

### 0.2 真实差距清单（经代码验证）

以下差距经代码验证为真实存在，非误判：

| 差距项 | 验证依据 | 性质 |
| :--- | :--- | :--- |
| Shadow RL 是 stub | [shadow_rl.py:L59-64](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/shadow_rl.py) `activate_phase3()` 未实现 | 学习闭环空壳 |
| 基因库静态 | [strategy_gene.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/strategy_gene.py) 手动JSON定义 | 无自主策略发现 |
| 头肩顶未接实盘 | 仅在 [shadow_backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/scripts/shadow_backtest.py) | 市场理解缺口 |
| BTC-美股相关性regime | 代码全局搜索无实现 | 市场理解缺口 |
| ETF流出权重仅5% | 战略层权重配置 | 信号权重偏低 |
| 无因果推理 | 全局搜索无 do-calculus/DML | 认知深度缺口 |
| 无反事实推理 | 无 what-if/synthetic-control | 认知深度缺口 |
| 无元认知 | confidence是规则计算非认知性 | 认知深度缺口 |
| RAG只检索不合成 | 热路径只注入context | 知识利用缺口 |

***

## 一 · 核心哲学：万物皆数 · 最小阻力路径

### 1.1 哲学基石

| 哲学命题 | 数学表达 | 物理类比 |
| :--- | :--- | :--- |
| **万物皆数** | 市场状态=高维张量，价格路径=签名(Signature) | 毕达哥拉斯：数是万物的本原 |
| **最小阻力路径** | 路径积分 $\int D[q]\exp(iS[q]/\hbar)$，最小作用量 $S[q]$ 对应最优交易路径 | 市场=引力场，价格=粒子，沿最小能量势垒运动 |
| **最优路径=阻力最小** | 变分法 $\delta S=0$，Hamilton-Jacobi方程 | 光线沿最短光程传播（费马原理） |
| **多路径计算** | 蒙特卡洛路径采样 + 签名特征提取 | 费曼路径积分：所有可能路径的加权和 |

### 1.2 方法论五步法

```
统计学 → 抽象模型 → 多路径计算 → 最优路径 → 最小阻力
   ↓         ↓          ↓          ↓          ↓
数据清洗  签名/Neural   蒙特卡洛   变分法/    最小作用量
特征工程  ODE抽象       路径采样   最优控制   路径落地
```

1. **统计学**：Bronze→Silver→Gold数据清洗，统计特征（均值/方差/偏度/峰度/Hurst指数）
2. **抽象模型**：用**签名方法(Signature)** 将价格路径抽象为张量代数坐标；用**Neural ODE/SDE**建模连续时间动态
3. **多路径计算**：蒙特卡洛采样大量可能路径，计算每条路径的"阻力"（成本+风险+不确定性）
4. **最优路径**：变分法/Hamilton-Jacobi-Bellman方程求解最小阻力路径
5. **最小阻力**：选择作用量最小的路径作为交易决策

### 1.3 三个范式跃迁

| 范式 | 当前 | AGI目标 | 跃迁核心 |
| :--- | :--- | :--- | :--- |
| **学习范式** | 参数微调（ESS±0.02/笔） | 深度学习策略表示+签名路径特征 | 激活RL训练 + Decision Transformer + 签名方法 |
| **认知范式** | 相关性匹配（CBR/RAG） | 因果推断+路径积分+深度学习时序建模 | 因果模型(causalml) + 签名方法 + TimesFM/Neural ODE |
| **进化范式** | 手动定义基因库 | 自主策略合成+结构变异 | 进化算法 + 深度学习策略生成器（非LLM） |

**关键区别：** 不用大语言模型做推理，用**深度学习（Transformer/SDE/World Model）**做数据驱动的模式发现；不用多Agent辩论，用**精细分层管理**（宏观→约束→信号→形态→后置→策略）。

***

## 二 · 目标架构：自进化系统作为AGI核心

### 2.1 核心哲学与数学基础

**万物皆数**：市场的一切（价格、成交量、订单流、情绪、基本面）都映射为数值张量。
**最小阻力路径**：交易决策等价于在高维市场流形上寻找作用量最小的路径——这是费曼路径积分在金融领域的应用。

**数学工具链：**
- **签名方法 (Signature)**：路径的通用坐标，将任意价格路径映射为截断张量代数中的向量。签名是路径无关的、可微的、信息完备的抽象表示。
- **路径积分 (Path Integral)**：$K(q',t';q,t)=\int D[q]\exp(iS[q]/\hbar)$，计算所有可能路径的加权和，最小作用量路径即最优交易路径。
- **Neural ODE/SDE**：用神经网络参数化市场的连续时间动态，$dS_t=f_\theta(S_t,t)dt+g_\phi(S_t,t)dW_t$。
- **变分法/最优控制**：Hamilton-Jacobi-Bellman方程求解最优控制策略。

### 2.2 精细分层管理架构（非辩论）

```
                    ┌──────────────────────────────────────────┐
                    │        自进化系统（AGI Core）              │
                    │                                          │
                    │  ┌────────────────────────────────────┐  │
                    │  │ L1 感知层（消费三系统+市场数据）    │  │
                    │  │  宏观层：战略层→war_state→趋势方向   │  │
   战略层 ────────→│  │  约束层：BDSM→direction_constraint  │  │
   BCRM2.0 ───────→│  │  信号层：BCRM2.0→反向信号分层        │  │
   BDSM ──────────→│  │  形态层：价格形态(头肩顶等)          │  │
                    │  │  数据层：K线/订单流/链上/宏观        │  │
                    │  ├────────────────────────────────────┤  │
                    │  │ L2 抽象层（新增·数学抽象）          │  │
                    │  │  签名引擎：路径→Signature张量       │  │
                    │  │  Neural SDE：连续时间动态建模        │  │
                    │  │  因果引擎：causalml因果归因          │  │
                    │  ├────────────────────────────────────┤  │
                    │  │ L3 路径计算层（新增·多路径+最优）   │  │
                    │  │  多路径蒙特卡洛采样                 │  │
                    │  │  路径阻力计算（成本+风险+不确定）   │  │
                    │  │  最优路径求解（HJB/变分法）         │  │
                    │  ├────────────────────────────────────┤  │
                    │  │ L4 决策层（已有·增强）              │  │
                    │  │  Entry/Exit Engine                  │  │
                    │  │  +元认知Uncertainty Gate            │  │
                    │  ├────────────────────────────────────┤  │
                    │  │ L5 进化层（激活·自主发现）          │  │
                    │  │  Shadow RL Phase3 + DT              │  │
                    │  │  深度学习策略生成器（非LLM）         │  │
                    │  │  跨资产迁移学习                     │  │
                    │  └────────────────────────────────────┘  │
                    └──────────────────────────────────────────┘
```

### 2.3 各层精细分工

| 层级 | 名称 | 职责 | 输入 | 输出 |
| :--- | :--- | :--- | :--- | :--- |
| L1 | **感知层** | 多源数据采集与三系统信号消费 | 战略层/BCRM2.0/BDSM/K线/订单流 | war_state/反向信号/约束/形态特征 |
| L2 | **抽象层** | 数学抽象：签名+Neural SDE+因果 | 感知层原始数据 | Signature张量/SDE参数/因果效应 |
| L3 | **路径计算层** | 多路径蒙特卡洛+最优路径求解 | 抽象层特征 | 最优路径+阻力估计 |
| L4 | **决策层** | 开仓/离场/仓位决策 | 最优路径 | 交易指令 |
| L5 | **进化层** | 策略发现+参数自适应 | 交易结果 | 新策略基因+参数更新 |

### 2.4 核心设计原则

1. **自进化系统是AGI核心，三系统是传感器**：战略层(宏观方向)/BDSM(基本面约束)/BCRM2.0(信号)提供感知，自进化系统做抽象、计算、决策、进化
2. **精细管理而非辩论**：各层有明确职责和数据流向，不需要多Agent对抗辩论，通过数学优化做决策
3. **深度学习而非大语言模型**：用Transformer/Neural SDE/World Model/Decision Transformer做数据驱动学习，不用LLM做推理
4. **万物皆数**：一切市场状态映射为数值张量，用签名方法做路径抽象
5. **最小阻力路径**：交易决策=在市场流形上求最小作用量路径
6. **FAIL-OPEN不可破坏**：所有新模块异常→中性兜底+日志
7. **模块化开关**：每个新能力独立开关，默认关闭

***

## 三 · 技术选型矩阵（传统金融 × AI技术）

基于2024-2026年学术研究和GitHub开源项目调研，选定以下技术组合：

### 3.1 核心技术选型

| AGI模块 | 传统金融理论 | AI/数学技术 | 组合价值 | 参考来源 |
| :--- | :--- | :--- | :--- | :--- |
| **路径抽象** | 价格路径理论 | **签名方法(Signature)** | 路径→张量坐标，信息完备可微 | [signatory](https://github.com/patrick-kidger/signatory) / [Path Portfolio Opt arXiv 2608.02355](https://arxiv.org/html/2608.02355v1) |
| **最优路径** | 变分法/最优控制 | **路径积分(Path Integral)** | 最小作用量=最小阻力路径 | [Quantum Leap MDPI 2024](https://www.mdpi.com/2227-7390/12/2/315) |
| **市场动态建模** | 随机微分方程 | **Neural SDE** | 连续时间动态+不确定性 | [Stable-Neural-SDEs ICLR 2024](https://github.com/yongkyung-oh/Stable-Neural-SDEs) |
| **时序预测** | 时间序列分析 | **TimesFM/TimeGPT** | 预训练深度学习时序模型 | [TimesFM 32k★](https://github.com/google-research/timesfm) |
| **序列决策** | 强化学习 | **Decision Transformer** | RL as Sequence Modeling | [decision-transformer 2.8k★](https://github.com/kzl/decision-transformer) |
| **仓位sizing** | 分数Kelly+波动率目标 | Conformal Prediction | 形式化覆盖保证下的最优下注 | [TECP arXiv 2509.00461](https://arxiv.org/html/2509.00461v2) |
| **执行算法** | Almgren-Chriss+VWAP | **Sig-REINFORCE** | 签名方法最优执行 | [Signature Optimal Execution arXiv 2606.31387](https://arxiv.org/html/2606.31387v2) |
| **组合构建** | HRP去噪变体 | 因果DAG+causalml | 超越相关的因果抗崩盘配置 | [HRP Variants UCEMA 2026](https://ucema.edu.ar/sites/default/files/2026-06/dt928.pdf) / [causalml 6k★](https://github.com/uber/causalml) |
| **自进化** | 行为金融反身性 | **进化算法+深度学习策略生成** | 自我评估+策略自动发现（非LLM） | [Meta-RL-Crypto arXiv 2509.09751](https://arxiv.org/html/2509.09751v2) |
| **不确定性** | VaR/ES/CVaR | Deep Ensembles+BNN | 双重校准的尾部风险对冲 | [FinRL-DeepSeek CVaR-PPO](https://arxiv.org/pdf/2502.07393v1) |
| **因果归因** | 反事实施工 | causalml(DML/Causal Forest) | 因果归因替代相关归因 | [causalml 6k★](https://github.com/uber/causalml) |
| **市场环境建模** | 市场微观结构 | **World Model(Dreamer V3)** | 无风险想象训练+样本高效 | [Dreamer V3 Nature 2025](https://blog.csdn.net/Discover304/article/details/163618063) |

### 3.2 参考蓝本（GitHub开源项目·2026-09-10 实测数据）

| 蓝本角色 | 项目 | ★Stars | 最后更新 | 借鉴点 |
| :--- | :--- | :--- | :--- | :--- |
| **签名计算库** | [signatory](https://github.com/patrick-kidger/signatory) | 311 | 2026-09-10 | PyTorch可微分签名计算（ICLR 2021），路径抽象核心 |
| **时间序列基础模型** | [TimesFM](https://github.com/google-research/timesfm) | **32.2k** | 2026-09-10 | Google预训练时序模型，深度学习预测（非LLM） |
| **时序生成模型** | [TimeGPT](https://github.com/Nixtla/nixtla) | 4.0k | 2026-09-10 | 100B数据点预训练Transformer时序模型 |
| **时序MoE** | [Time-MoE](https://github.com/Time-MoE/Time-MoE) | 999 | 2026-09-10 | ICLR 2025，百亿参数时序MoE |
| **Neural SDE** | [Stable-Neural-SDEs](https://github.com/yongkyung-oh/Stable-Neural-SDEs) | 79 | 2026-09-03 | ICLR 2024，稳定神经SDE |
| **Decision Transformer** | [decision-transformer](https://github.com/kzl/decision-transformer) | 2.8k | 2026-09-09 | RL as Sequence Modeling官方实现 |
| **因果推断库** | [causalml](https://github.com/uber/causalml) | 6.0k | 2026-09-10 | Uber出品，DML/Causal Forest直接复用 |
| **执行引擎** | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 28.7k | 2026-09-10 | Rust核心+Python API，回测实盘统一 |
| **AI量化平台** | [qlib](https://github.com/microsoft/qlib) | 48.5k | 2026-09-10 | 数据→模型→回测→实盘工作流 |
| **加密实盘框架** | [freqtrade](https://github.com/freqtrade/freqtrade) | 54.2k | 2026-09-10 | FreqAI自适应ML+分档止损+追踪止损 |
| **RL训练底座** | [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16.3k | 2026-09-10 | 数据→环境→Agent三层解耦 |
| **并行RL训练** | [ElegantRL](https://github.com/AI4Finance-Foundation/ElegantRL) | 4.4k | 2026-09-06 | 云原生轻量高效 |
| **遗传策略进化** | [finclaw](https://github.com/NeuZhou/finclaw) | 29 | 2026-09-04 | GA进化策略+前向验证+蒙特卡洛 |
| **签名方法ML** | [the-signature-method-in-ML](https://github.com/kormilitzin/the-signature-method-in-machine-learning) | 105 | 2026-08-12 | 签名方法ML基础与应用 |
| **随机投资组合签名** | [Sig-SPT](https://github.com/janka-moeller/Sig-SPT) | 11 | 2026-08-09 | 随机投资组合理论中的签名方法 |

***

## 四 · 分阶段升级计划

### Phase 1：激活学习闭环（P0·最高优先）

**目标：** 让Shadow RL真正"学习"，不再只记录样本

#### 4.1.1 激活 Shadow RL Phase 3

**蓝本：** [FinRL (16.3k★)](https://github.com/AI4Finance-Foundation/FinRL) 三层解耦 + [ElegantRL (4.4k★)](https://github.com/AI4Finance-Foundation/ElegantRL) 并行训练

**现状：** [shadow_rl.py:L62-64](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/shadow_rl.py) `activate_phase3()` 是空方法

**升级：**
1. 样本≥2000时自动激活（自动检测，非PR评审）
2. 引入FinRL标准MDP环境封装（State/Action/Reward/Transition）
3. 实现gmax变异：策略基因权重±0.01~0.05随机扰动
4. 实现Thompson sampling：基于Beta(α,β)分布采样策略选择
5. Bellman V(s)回流：L4的V值影响L1状态空间权重
6. 可选：ElegantRL云原生并行训练（样本量足够后启用）

**新增模块：** `dreambuddy_evolution/core/shadow_rl_trainer.py`

```python
from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv

class ShadowRLTrainer:
    """Shadow RL Phase3 训练器（基于FinRL环境封装）
    - 样本≥2000自动激活
    - FinRL标准MDP环境 + gmax变异 + Thompson sampling
    - V(s)回流L1状态空间
    - 可选ElegantRL并行训练
    """
    MIN_SAMPLES = 2000
    GMAX_MUTATION_RANGE = (0.01, 0.05)
    
    def maybe_activate(self, sample_count: int) -> bool:
        if sample_count >= self.MIN_SAMPLES:
            self._activated = True
            return True
        return False
    
    def thompson_sample(self, gene_id: str) -> float:
        # Beta(α=成功+1, β=失败+1) 采样
        ...
    
    def mutate_gmax(self, current_gmax: float) -> float:
        # ±0.01~0.05 随机扰动
        ...
    
    def train_policy(self, samples: list) -> dict:
        # 基于FinRL环境训练策略（PPO/SAC）
        # 蓝本：FinRL agents/
        ...
```

**依赖：** `pip install finrl`（可选elegantrl并行），FAIL-OPEN：导入失败→降级为当前record-only

**验收：** 样本≥2000自动激活；gmax变异后回测Sharpe提升≥0.1；Thompson采样收敛

#### 4.1.2 ESS适应加速

**现状：** 成功+0.02/失败-0.05，需≥20样本冷启动

**升级：**
1. 冷启动阈值降至10样本
2. 适应步长动态化：高CS(≥0.9)时+0.05，低CS时+0.02
3. 引入EMA衰减：近期样本权重更高

### Phase 2：因果认知层（P1·核心认知跃迁）

**目标：** 从相关性匹配跃迁到因果推断+反事实推理

#### 4.2.1 因果推断引擎

**蓝本：** [causalml (6.0k★·Uber)](https://github.com/uber/causalml) — 直接复用DML/Causal Forest，不从零实现do-calculus

**新增模块：** `dreambuddy_evolution/core/causal_engine.py`

```python
from causalml.inference.meta import LRSRegressor, BaseTRegressor

class CausalInferenceEngine:
    """因果推断引擎（基于causalml构建）
    - NOTEARS算法学习因果DAG（结构学习）
    - DML/Causal Forest做异质性处理效应估计
    - do-calculus做干预推断
    - 识别虚假关联（spurious correlation）
    """
    def learn_dag(self, market_data: dict) -> nx.DiGraph:
        # NOTEARS连续优化学习DAG
        # 蓝本：causalml + 自实现NOTEARS
        ...
    
    def estimate_heterogeneous_effect(self, treatment, outcome, covariates) -> dict:
        # DML双机器学习估计异质性效应
        # 蓝本：causalml.inference.meta.LRSRegressor
        ...
    
    def detect_spurious(self, signal_a, signal_b) -> float:
        # 检测A-B是否为虚假关联（条件独立性检验）
        ...
```

**接入点：** 信号评估阶段，在ESS评分前过滤虚假关联信号
**依赖：** `pip install causalml`（FAIL-OPEN：导入失败→降级为相关性匹配）

#### 4.2.2 反事实评估器

**新增模块：** `dreambuddy_evolution/core/counterfactual_evaluator.py`

```python
class CounterfactualEvaluator:
    """反事实推理评估器
    - 合成控制法构建反事实基准
    - 回答"如果不开仓会怎样"
    - 识别spurious alpha
    """
    def synthetic_control(self, treated: dict, controls: list) -> dict:
        # 合成控制法
        ...
    
    def what_if_no_trade(self, actual_pnl: float, position: dict) -> float:
        # 反事实P&L估计
        ...
```

**接入点：** ReflectionEngine.apply_reward后，补充因果归因

#### 4.2.3 深度学习推理引擎（非LLM）

**蓝本：** [signatory (签名计算)](https://github.com/patrick-kidger/signatory) + [TimesFM (32.2k★)](https://github.com/google-research/timesfm) + [Stable-Neural-SDEs (ICLR 2024)](https://github.com/yongkyung-oh/Stable-Neural-SDEs)

**核心思想：** 不用大语言模型做推理，用**深度学习**做数据驱动的模式发现。市场路径→签名抽象→Neural SDE动态建模→TimesFM预测→最优路径求解。

**新增模块：** `dreambuddy_evolution/engines/deep_reasoning_engine.py`

```python
import signatory
import torch
from timesfm import TimesFm

class DeepReasoningEngine:
    """深度学习推理引擎（万物皆数·最小阻力路径）
    
    推理流程（无LLM·纯数据驱动）：
    1. 路径抽象：价格路径 → Signature张量（签名方法）
    2. 动态建模：Neural SDE学习市场连续时间动态
    3. 时序预测：TimesFM预训练模型预测价格分布
    4. 多路径采样：蒙特卡洛生成N条可能路径
    5. 最优路径：计算每条路径阻力→选最小阻力路径
    """
    
    def path_to_signature(self, price_path: torch.Tensor, depth: int = 5) -> torch.Tensor:
        # 签名方法：路径→截断张量代数坐标
        # 蓝本：signatory.signature()
        return signatory.signature(price_path.unsqueeze(0), depth)
    
    def neural_sde_forecast(self, state: torch.Tensor, horizon: int) -> torch.Tensor:
        # Neural SDE：dS = fθ(S,t)dt + gφ(S,t)dW
        # 蓝本：Stable-Neural-SDEs
        ...
    
    def timesfm_predict(self, history: torch.Tensor, horizon: int) -> torch.Tensor:
        # TimesFM预训练模型预测
        # 蓝本：google-research/timesfm
        ...
    
    def monte_carlo_paths(self, n_paths: int = 1000) -> torch.Tensor:
        # 多路径蒙特卡洛采样
        ...
    
    def compute_path_resistance(self, path: torch.Tensor) -> float:
        # 路径阻力 = 交易成本 + 风险 + 不确定性
        ...
    
    def find_min_resistance_path(self, paths: torch.Tensor) -> dict:
        # 最小阻力路径 = 作用量最小的路径
        # 数学：变分法 δS=0
        ...
```

**技术参考：**
- 签名方法：[signatory](https://github.com/patrick-kidger/signatory) + [Path Portfolio Optimization arXiv 2608.02355](https://arxiv.org/html/2608.02355v1)
- 路径积分：[Quantum Leap MDPI 2024](https://www.mdpi.com/2227-7390/12/2/315) — 市场=引力场，价格=粒子，最小能量势垒
- Neural SDE：[Stable-Neural-SDEs ICLR 2024](https://github.com/yongkyung-oh/Stable-Neural-SDEs)
- 时序预测：[TimesFM](https://github.com/google-research/timesfm) + [TimeGPT](https://github.com/Nixtla/nixtla)

**接入点：** L2抽象层→L3路径计算层，FAIL-OPEN：任一模块异常→降级为当前规则决策

### Phase 2.5：签名方法+路径积分（核心数学基建·P1）

**目标：** 实现"万物皆数·最小阻力路径"的数学基建——签名抽象+路径积分

**新增模块：** `dreambuddy_evolution/core/signature_engine.py` + `dreambuddy_evolution/core/path_integral.py`

```python
class SignatureEngine:
    """签名引擎：路径的通用坐标
    - 将任意价格路径映射为截断张量代数向量
    - 签名是路径无关的、可微的、信息完备的
    """
    def compute_signature(self, path: torch.Tensor, depth: int) -> torch.Tensor:
        # 蓝本：signatory.signature
        ...
    
    def log_signature(self, path: torch.Tensor, depth: int) -> torch.Tensor:
        # 蓝本：signatory.logsignature
        ...

class PathIntegralEngine:
    """路径积分引擎：最小阻力路径
    - K(q',t';q,t) = ∫D[q]exp(iS[q]/ħ)
    - 所有可能路径的加权和
    - 最小作用量路径 = 最优交易路径
    """
    def compute_path_integral(self, start_state, end_state, n_paths) -> dict:
        # 路径积分计算
        ...
    
    def min_action_path(self, paths: list) -> dict:
        # 最小作用量路径（变分法 δS=0）
        ...
```

### Phase 3：自主策略进化（P2·进化范式跃迁）

**目标：** 系统自动发现新策略，不再依赖手动基因库

#### 4.3.1 深度学习策略生成器（非LLM）

**蓝本：** [decision-transformer (2.8k★)](https://github.com/kzl/decision-transformer) + [finclaw](https://github.com/NeuZhou/finclaw) GA进化 + [Meta-RL-Crypto](https://arxiv.org/html/2509.09751v2)

**核心思想：** 不用LLM生成策略，用**深度学习+进化算法**做数据驱动的策略发现。Decision Transformer学习历史最优轨迹，遗传编程做策略结构变异，回测验证后接入基因库。

**新增模块：** `dreambuddy_evolution/core/strategy_synthesizer.py`

```python
class StrategySynthesizer:
    """深度学习策略生成器（非LLM·数据驱动）
    
    进化闭环：
    1. 轨迹学习：Decision Transformer学习历史最优交易轨迹
    2. 策略变异：遗传编程(GP)对策略基因做结构变异
    3. 回测验证：ESS评估新基因的Sharpe/最大回撤
    4. 优胜劣汰：优质基因接入基因库，劣质淘汰
    5. 参数自适应：Meta-RL三环自改进（Actor/Judge/Meta-Judge）
    """
    def dt_learn_trajectories(self, historical_trades: list) -> dict:
        # Decision Transformer学习历史最优轨迹
        # 蓝本：decision-transformer
        ...
    
    def genetic_programming(self, target_metric: str) -> list:
        # GP生成可解释策略公式（白盒alpha）
        # 蓝本：finclaw GA + gplearn
        ...
    
    def validate_and_integrate(self, new_gene: dict) -> bool:
        # 回测ESS验证→接入基因库
        # 硬约束HC-AGI-04：必须经回测验证
        ...
    
    def meta_rl_self_improve(self, gene_id: str, outcome: dict) -> dict:
        # Meta-RL三环自改进
        # 蓝本：Meta-RL-Crypto (Actor/Judge/Meta-Judge)
        ...
```

**技术参考：** [decision-transformer](https://github.com/kzl/decision-transformer) RL as Sequence Modeling + [finclaw (29★)](https://github.com/NeuZhou/finclaw) GA进化+前向验证+蒙特卡洛 + [Meta-RL-Crypto arXiv 2509.09751](https://arxiv.org/html/2509.09751v2)

#### 4.3.2 跨资产迁移学习

**新增模块：** `dreambuddy_evolution/core/transfer_learner.py`

```python
class TransferLearner:
    """跨资产迁移学习
    - BTC学到的pattern迁移到SOL/ETH
    - Prototypical Network相似度匹配
    - MAML元学习快速适应
    """
    def extract_pattern(self, source_symbol: str) -> dict:
        # 提取可迁移pattern
        ...
    
    def transfer_to(self, pattern: dict, target_symbol: str) -> float:
        # 迁移+适应度评估
        ...
```

### Phase 4：市场理解补齐（P1·补齐感知缺口）

#### 4.4.1 头肩顶检测接入实盘

**现状：** 仅在 [shadow_backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/scripts/shadow_backtest.py)

**升级：** 提取为独立模块，接入BCRM2.0技术评估

```python
# dreambuddy_evolution/engines/pattern_detector.py
class PatternDetector:
    """价格形态检测器
    - 头肩顶/底
    - 双顶/双底
    - 三角形/旗形
    """
    def detect_head_shoulders(self, klines: list) -> dict:
        ...
```

**接入点：** BCRM2.0技术评估调用，作为反向信号因子

#### 4.4.2 BTC-美股相关性regime

**新增模块：** `dreambuddy_evolution/core/regime_classifier.py`

```python
class RegimeClassifier:
    """BTC-美股相关性regime分类器
    - 强BTC：与美股脱钩（独立行情）
    - 弱BTC：与美股高相关（风险资产联动）
    - 基于滚动相关系数+波动率分类
    """
    def classify(self, btc_returns: list, spy_returns: list) -> str:
        # "strong" / "weak" / "neutral"
        ...
```

**接入点：** 战略层"天"维度因子 + BCRM2.0方向约束

#### 4.4.3 ETF流出信号权重提升

**现状：** 战略层权重5%

**升级：** 
1. 权重提升至15%（ stagnation后ETF流出=强信号）
2. 接入BDSM作为exit_action触发条件
3. 与头肩顶+BTC regime三因子共振时允许BTC/ETH做空

### Phase 5：不确定性量化与元认知（P2·认知安全）

#### 4.5.1 Conformal Prediction置信区间

**新增模块：** `dreambuddy_evolution/core/uncertainty_quantifier.py`

```python
class UncertaintyQuantifier:
    """不确定性量化器
    - Conformal Prediction形式化覆盖保证
    - Deep Ensemble集成不确定性
    - BNN贝叶斯神经网络
    """
    def conformal_interval(self, prediction: float, confidence: float) -> tuple:
        # (lower, upper) 带覆盖保证的区间
        ...
```

#### 4.5.2 元认知门禁

**新增模块：** `dreambuddy_evolution/engines/meta_cognition_gate.py`

```python
class MetaCognitionGate:
    """元认知门禁
    - 评估confidence的可靠性
    - 低可靠时降仓位或拒开仓
    - 知道自己"不知道什么"
    """
    def evaluate(self, confidence: float, context: dict) -> dict:
        # 返回 {adjusted_confidence, uncertainty, action}
        ...
```

***

## 五 · 硬约束清单（新增）

以下为本次SPEC新增硬约束，需写入认知记忆库：

| ID | 硬约束 | 域 |
| :--- | :--- | :--- |
| HC-AGI-01 | Shadow RL Phase3 激活阈值：样本≥2000自动激活，非PR评审 | 学习闭环域 |
| HC-AGI-02 | 因果推断引擎异常→中性兜底+日志，不阻塞交易热路径 | FAIL-OPEN域 |
| HC-AGI-03 | 深度学习推理引擎(签名/SDE/TimesFM)异常→中性兜底+6层堆栈日志，5分钟≥3次触发Lark告警 | FAIL-OPEN域 |
| HC-AGI-04 | 策略基因自动生成器产出必须经回测ESS验证才能接入基因库 | 自进化域 |
| HC-AGI-05 | 跨资产迁移学习pattern必须通过反事实评估才能落地 | 自进化域 |
| HC-AGI-06 | 元认知门禁低可靠时（uncertainty>0.4）强制降仓位至0.5×原值 | 认知安全域 |
| HC-AGI-07 | 所有新认知模块默认关闭，Shadow模式验证≥7天+Sharpe正向才能小流量 | 模块化开关域 |
| HC-AGI-08 | 因果DAG学习需≥500样本，低于阈值降级为相关性匹配 | 因果推理域 |
| HC-AGI-09 | 反事实评估器异常→actual_pnl兜底，不阻塞ReflectionEngine | FAIL-OPEN域 |
| HC-AGI-10 | 策略合成器新基因冷启动期（前20笔）仓位强制≤0.05地板 | 自进化域 |
| HC-AGI-11 | 签名方法深度depth≤5，避免张量维度爆炸 | 数学基建域 |
| HC-AGI-12 | 路径积分蒙特卡洛采样数≥1000，保证路径覆盖 | 数学基建域 |
| HC-AGI-13 | Neural SDE训练需≥1000条路径样本，低于阈值降级为GARCH | 数学基建域 |
| HC-AGI-14 | 最小阻力路径求解必须同时满足：成本<阈值 AND 风险<阈值 AND 不确定性<阈值 | 决策域 |

***

## 六 · 开关架构

```python
# dreambuddy_evolution/agi_config.py
AGI_SWITCHES = {
    "enable_agi_core": False,  # AGI总开关（默认关）
    "enable_shadow_rl_phase3": False,  # Shadow RL训练（默认关）
    "enable_signature_engine": False,  # 签名方法引擎（默认关）
    "enable_path_integral": False,  # 路径积分最小阻力路径（默认关）
    "enable_neural_sde": False,  # Neural SDE动态建模（默认关）
    "enable_timesfm_forecast": False,  # TimesFM时序预测（默认关）
    "enable_deep_reasoning": False,  # 深度学习推理引擎（默认关）
    "enable_causal_engine": False,  # 因果推断引擎（默认关）
    "enable_counterfactual": False,  # 反事实评估器（默认关）
    "enable_strategy_synthesizer": False,  # 深度学习策略生成器（默认关）
    "enable_transfer_learning": False,  # 跨资产迁移（默认关）
    "enable_meta_cognition": False,  # 元认知门禁（默认关）
    "enable_conformal_prediction": False,  # 不确定性量化（默认关）
    "enable_pattern_detector_live": False,  # 头肩顶接入实盘（默认关）
    "enable_btc_regime_classifier": False,  # BTC-美股regime（默认关）
}
```

**开关关断时等价性：** 所有开关关闭时，系统行为与当前完全等价，不影响现有四层闭环+三系统接入。

***

## 七 · 验收标准

| 阶段 | 验收指标 | 门槛 |
| :--- | :--- | :--- |
| Phase 1 | Shadow RL激活后回测Sharpe | ≥当前基线+0.1 |
| Phase 1 | ESS适应收敛速度 | <10样本启动 |
| Phase 2 | 因果DAG识别虚假关联 | ≥3个已知虚假关联 |
| Phase 2 | 签名方法路径重建误差 | ≤5%（截断depth=5） |
| Phase 2 | Neural SDE预测MAE | ≤当前GARCH基线 |
| Phase 2 | TimesFM预测准确率 | ≥60%方向正确 |
| Phase 2.5 | 最小阻力路径回测Sharpe | ≥当前规则基线+0.15 |
| Phase 3 | 策略合成器产出可用基因 | ≥1个/月 |
| Phase 3 | 新基因回测Sharpe | ≥现有top基因×0.8 |
| Phase 4 | 头肩顶检测准确率 | ≥60% |
| Phase 4 | BTC regime分类准确率 | ≥65% |
| Phase 5 | 元认知门禁触发后亏损率 | 低于无门禁×0.7 |
| 全局 | 所有开关关闭时字节等价 | 100%等价 |

***

## 八 · 实施优先级

```
P0（立即启动）:
  ├─ Phase 1: 激活Shadow RL Phase3 + ESS加速
  └─ Phase 4.1: 头肩顶接入实盘

P1（Phase1完成后）:
  ├─ Phase 2.5: 签名方法+路径积分（核心数学基建）
  ├─ Phase 2.3: 深度学习推理引擎（签名+Neural SDE+TimesFM）
  └─ Phase 4.2: BTC-美股regime

P2（Phase2完成后）:
  ├─ Phase 2.1: 因果推断引擎(causalml)
  ├─ Phase 3.1: 深度学习策略生成器(DT+GA)
  └─ Phase 4.3: ETF流出权重提升

P3（Phase3完成后）:
  ├─ Phase 2.2: 反事实评估器
  ├─ Phase 3.2: 跨资产迁移学习
  ├─ Phase 5.1: Conformal Prediction
  └─ Phase 5.2: 元认知门禁
```

***

## 九 · 参考来源汇总

### 传统金融理论
- [Explainable Patterns in Cryptocurrency Microstructure (arXiv 2026)](https://arxiv.org/html/2602.00776v1/)
- [HRP Variants for Cryptocurrency Portfolios (UCEMA 2026)](https://ucema.edu.ar/sites/default/files/2026-06/dt928.pdf)
- [Kelly Criterion Position Sizing in Crypto (2024)](https://www.hyper-quant.tech/research/kelly-criterion-position-sizing)
- [RL for Optimal Execution when Liquidity is Time-Varying (arXiv 2024)](https://arxiv.org/html/2402.12049)

### AI AGI技术（深度学习驱动·非LLM）
- [Decision Transformer for Trading (arXiv 2411.17900)](https://arxiv.org/html/2411.17900)
- [Dreamer V3 Nature 2025](https://blog.csdn.net/Discover304/article/details/163618063)
- [CausalStock NeurIPS 2024](https://blog.csdn.net/b3n4m5q6w7/article/details/154519672)
- [TECP: Conformal Prediction](https://arxiv.org/html/2509.00461v2)
- [Meta-RL-Crypto](https://arxiv.org/html/2509.09751v2)

### 签名方法+路径积分（核心数学基建）
- [Quantum Leap: Price Leap Mechanism (MDPI 2024)](https://www.mdpi.com/2227-7390/12/2/315) — 路径积分+最小能量势垒
- [Path Integral for Time-Dependent Hamiltonians (arXiv 2408.02064)](https://ar5iv.labs.arxiv.org/html/2408.02064)
- [Signature Methods for Optimal Market Making (arXiv 2606.19772)](https://arxiv.org/html/2606.19772v1) — Sig-REINFORCE
- [Signature-Based Optimal Execution (arXiv 2606.31387)](https://arxiv.org/html/2606.31387v2) — 签名最优执行
- [Path Portfolio Optimization (arXiv 2608.02355)](https://arxiv.org/html/2608.02355v1) — 签名路径组合优化
- [Stable Neural SDEs (ICLR 2024)](https://github.com/yongkyung-oh/Stable-Neural-SDEs)

### GitHub开源项目（★数为2026-09-10实测·深度学习为主）
- [TimesFM (32.2k★)](https://github.com/google-research/timesfm) — Google时间序列基础模型
- [freqtrade (54.2k★)](https://github.com/freqtrade/freqtrade) — 加密实盘+FreqAI自适应ML
- [qlib (48.5k★)](https://github.com/microsoft/qlib) — AI量化平台
- [NautilusTrader (28.7k★)](https://github.com/nautechsystems/nautilus_trader) — Rust核心执行引擎
- [Lean (21.6k★)](https://github.com/QuantConnect/Lean) — 多资产量化引擎
- [FinRL (16.3k★)](https://github.com/AI4Finance-Foundation/FinRL) — RL训练pipeline
- [causalml (6.0k★)](https://github.com/uber/causalml) — Uber因果推断ML
- [ElegantRL (4.4k★)](https://github.com/AI4Finance-Foundation/ElegantRL) — 并行RL
- [decision-transformer (2.8k★)](https://github.com/kzl/decision-transformer) — DT官方实现
- [signatory (311★)](https://github.com/patrick-kidger/signatory) — PyTorch可微分签名计算
- [TimeGPT (4.0k★)](https://github.com/Nixtla/nixtla) — 时序生成模型
- [Time-MoE (999★)](https://github.com/Time-MoE/Time-MoE) — 时序MoE
- [Stable-Neural-SDEs (79★)](https://github.com/yongkyung-oh/Stable-Neural-SDEs) — ICLR 2024神经SDE
- [finclaw (29★)](https://github.com/NeuZhou/finclaw) — GA策略进化
- [the-signature-method-in-ML (105★)](https://github.com/kormilitzin/the-signature-method-in-machine-learning) — 签名方法ML

***

## 附录A · 核心技术深度调研（2026-09-10实测）

### A.1 签名方法（Signature Methods）— 万物皆数的数学实现

**核心思想：** 签名是路径的通用坐标。任意价格路径（无论长度、采样频率）都可以映射为截断张量代数中的一个向量，且这个向量是路径无关的、可微的、信息完备的。这正是"万物皆数"的数学实现。

**数学定义：** 对于路径 $X:[0,T]\to\mathbb{R}^d$，其截断签名为：
$$S_N(X) = \left(1, \int dX_{t_1}, \int\int dX_{t_1}dX_{t_2}, \ldots, \int\ldots\int dX_{t_1}\ldots dX_{t_N}\right)$$

**GitHub工具库：**
- [signatory (311★)](https://github.com/patrick-kidger/signatory) — PyTorch可微分签名计算（ICLR 2021），支持signature/logsignature/在线签名
- [iisignature](https://github.com/iisignature/iisignature) — Python签名计算，CPU版本
- [the-signature-method-in-ML (105★)](https://github.com/kormilitzin/the-signature-method-in-machine-learning) — 签名方法ML基础

**学术应用（2026年最新）：**
- [Signature Methods for Optimal Market Making (arXiv 2606.19772)](https://arxiv.org/html/2606.19772v1) — UC Berkeley，用签名方法做最优做市，Sig-REINFORCE算法
- [Signature-Based Optimal Execution (arXiv 2606.31387)](https://arxiv.org/html/2606.31387v2) — Deep Blue Capital，信号生成和执行放在同一签名基上
- [Path Portfolio Optimization (arXiv 2608.02355)](https://arxiv.org/html/2608.02355v1) — AI Finance Institute，签名路径组合优化，确定性等价提升11-60倍

**对本系统映射：** 签名引擎作为L2抽象层核心，将所有市场路径（价格、成交量、订单流）统一映射为签名张量，作为后续深度学习模型的输入特征。

### A.2 路径积分（Path Integral）— 最小阻力路径的物理基础

**核心思想：** 把市场比作引力场，价格比作粒子。价格运动遵循最小作用量原理——沿能量势垒最低的路径运动。费曼路径积分计算所有可能路径的加权和，最小作用量路径即最优交易路径。

**数学表达：** $K(q',t';q,t)=\int D[q]\exp(iS[q]/\hbar)$，其中 $S[q]=\int L(q,\dot{q},t)dt$ 是作用量。

**学术基础：**
- [Quantum Leap: Price Leap Mechanism (MDPI 2024)](https://www.mdpi.com/2227-7390/12/2/315) — 上海大学，市场=引力场，价格=粒子，哈密顿量+薛定谔方程+路径积分计算最小能量势垒
- [Path Integral for Time-Dependent Hamiltonians (arXiv 2408.02064)](https://ar5iv.labs.arxiv.org/html/2408.02064) — 时变哈密顿量的路径积分方法

**路径阻力定义：** $R[\text{path}] = \alpha\cdot\text{交易成本} + \beta\cdot\text{风险(VaR)} + \gamma\cdot\text{不确定性}$，最小阻力路径 = $\arg\min R[\text{path}]$

**对本系统映射：** 路径积分引擎作为L3路径计算层核心，蒙特卡洛采样N条可能路径，计算每条路径的阻力，选择最小阻力路径作为交易决策。

### A.3 Neural SDE — 连续时间动态建模

**核心思想：** 用神经网络参数化市场的随机微分方程 $dS_t=f_\theta(S_t,t)dt+g_\phi(S_t,t)dW_t$，其中 $f_\theta$ 是漂移项，$g_\phi$ 是扩散项。这比离散时间模型更贴合市场连续运行的本质。

**GitHub实现：**
- [Stable-Neural-SDEs (79★·ICLR 2024)](https://github.com/yongkyung-oh/Stable-Neural-SDEs) — 稳定神经SDE，处理不规则时间序列
- [Calibration-of-Neural-SDEs](https://github.com/evaflonner/Calibration-of-Neural-SDEs-using-Bayesian-Methods) — 贝叶斯方法校准金融神经SDE

**对本系统映射：** Neural SDE作为L2抽象层的动态建模组件，学习市场连续时间动态，为路径积分提供漂移和扩散参数。

### A.4 时间序列基础模型 — 深度学习预测（非LLM）

**核心思想：** 用预训练的深度学习时序模型做价格预测，不用大语言模型。这些模型在大规模时间序列数据上预训练，能捕捉复杂的时序依赖。

**GitHub项目：**
- [TimesFM (32.2k★·Google)](https://github.com/google-research/timesfm) — Google Research时间序列基础模型，纯Transformer架构
- [TimeGPT (4.0k★·Nixtla)](https://github.com/Nixtla/nixtla) — 100B数据点预训练，支持金融预测
- [Time-MoE (999★·ICLR 2025)](https://github.com/Time-MoE/Time-MoE) — 百亿参数时序MoE
- [MOMENT (837★·ICML 2024)](https://github.com/moment-timeseries-foundation-model/moment) — 开放时序基础模型

**对本系统映射：** TimesFM作为L3路径计算层的预测组件，预测未来价格分布，为蒙特卡洛路径采样提供条件分布。

### A.5 Decision Transformer — 序列决策

**核心思想：** 把强化学习重新表述为序列建模问题。给定历史最优轨迹的(状态,动作,回报)序列，用Transformer学习条件分布，直接生成最优动作。不需要传统RL的Q值函数。

**GitHub实现：** [decision-transformer (2.8k★)](https://github.com/kzl/decision-transformer) — RL via Sequence Modeling官方实现

**对本系统映射：** Decision Transformer作为L5进化层的策略学习组件，学习历史最优交易轨迹，生成新的策略基因。

### A.6 RL训练底座：FinRL（16.3k★）+ ElegantRL（4.4k★）

**FinRL核心架构：**
```
finrl/
├── agents/        # DRL算法（PPO/SAC/DDPG/TD3/A2C）
├── meta/          # 环境配置
└── applications/  # 应用场景
```

**三层解耦标准：** 数据层→环境层（Gym接口）→Agent层

**ElegantRL增强：**
- 云原生并行训练（解决金融RL需百万episode的算力瓶颈）
- 轻量高效，适合本地+云混合部署

**可借鉴点：**
- MDP环境标准化封装（State/Action/Reward/Transition）
- 数据-环境-Agent解耦，便于替换算法
- 并行训练加速样本收集

**对本系统映射：** Shadow RL Phase3激活时，可复用FinRL的环境封装+ElegantRL的并行训练，替换当前的stub record-only实现。

### A.7 因果推断工具链：causalml（6.0k★·Uber）

**核心能力：**
- Uplift modeling（增益模型）
- 因果推断ML算法（DML/Causal Forest等）
- 异质性处理效应估计
- 政策评估

**可借鉴点：**
- 直接复用其DML/Causal Forest实现因果归因
- Uplift modeling可用于"什么信号在什么条件下有效"的异质性分析
- 成熟的因果效应估计API，降低实现门槛

**对本系统映射：** 因果推断引擎（Phase 2.1）可基于causalml构建，不必从零实现do-calculus。

### A.8 遗传策略进化：finclaw（29★）

**核心：** 遗传算法(GA)进化策略+前向验证+蒙特卡洛，策略YAML-DSL变异+帕累托前沿

**可借鉴点：**
- 策略基因表示协议（QEP），可扩展为JSON基因
- 分布式进化网络
- 防过拟合三件套：前向验证+蒙特卡洛+帕累托前沿

**对本系统映射：** 深度学习策略生成器（Phase 3.1）的遗传编程组件可参考finclaw的GA变异机制。

### A.9 生产级执行引擎：NautilusTrader（28.7k★）

**核心特性：**
- Rust核心 + Python策略API，纳秒级事件驱动
- **回测↔实盘统一架构**（同一套策略代码，切换环境即可）
- 确定性事件回放，保证回测可复现

**可借鉴点：**
- 回测实盘统一架构是生产级系统的核心标志
- 事件驱动+确定性回放解决"回测过拟合实盘失效"问题

**对本系统映射：** 当前执行层可参考NautilusTrader的事件驱动架构，实现回测↔实盘统一。

### A.10 技术选型决策矩阵

| 本系统模块 | 首选蓝本 | 次选蓝本 | 选型理由 |
| :--- | :--- | :--- | :--- |
| 路径抽象 | signatory | iisignature | PyTorch可微签名，ICLR 2021 |
| 最优路径 | 路径积分(Quantum Leap) | 变分法/HJB | 最小作用量=最小阻力 |
| 市场动态 | Stable-Neural-SDEs | — | ICLR 2024连续时间建模 |
| 时序预测 | TimesFM | TimeGPT | 32k★Google预训练 |
| 序列决策 | decision-transformer | — | RL as Sequence Modeling |
| RL训练 | FinRL + ElegantRL | — | 三层解耦+并行 |
| 因果归因 | causalml | — | Uber DML/Causal Forest |
| 策略进化 | finclaw GA | Meta-RL-Crypto | 遗传变异+自改进 |
| 执行引擎 | NautilusTrader | freqtrade | 回测实盘统一 |

***

## 十 · 待决事项

1. **签名深度depth选择**：depth=4还是5？depth=5时签名维度约为 $d^5$（d=输入维度），需平衡信息完整性与计算量
2. **路径积分采样数**：蒙特卡洛1000条路径是否足够？需回测验证路径收敛性
3. **Neural SDE训练数据量**：当前历史数据是否足够训练Neural SDE？低于1000条路径时降级为GARCH
4. **TimesFM微调策略**：是直接用预训练TimesFM，还是用加密货币数据微调？
5. **元认知uncertainty阈值**：0.4是否合理？需回测校准
6. **路径阻力权重**：$\alpha$(成本):$\beta$(风险):$\gamma$(不确定性) 的比例如何确定？

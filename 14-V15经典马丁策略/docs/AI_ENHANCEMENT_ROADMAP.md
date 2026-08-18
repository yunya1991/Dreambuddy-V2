# 大模型增强路线图 — V15 经典马丁策略

> **定位：** 模块级 AI 增强技术设计文档，描述大模型/机器学习接入 V15 马丁的三阶段方案 + 四条不可违背的决策铁律
> **版本：** v1.0 | **更新：** 2026-08-10
> **系统：** V15 经典马丁策略 AI 增强体系（Phase D：BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测 → Phase E：PPO-LSTM 强化学习加仓决策 + 确定性风控盾 → Phase F：FLAG-Trader LLM 策略网络 + SFT→PPO 两阶段训练）
> **前置基线（Baseline）：** v15-final 即 TECHNICAL_DESIGN.md v6.0 最终形态 = Phase B+（Phase A+ 基线 + SubMorph 子形态微调），Phase C（易经）默认关闭。**任何 AI 模型输出在实盘生效前必须严格通过 §3 四大铁律门禁，且任何时刻可一键回退到此基线。**

---

## 目录

- [1. 文档目的与演进链](#1-文档目的与演进链)
  - [1.1 与 TECHNICAL_DESIGN v6.0 的相位对应关系](#11-与-technical_design-v60-的相位对应关系)
  - [1.2 调研依据](#12-调研依据)
- [2. 模型族谱与 V15 适配场景](#2-模型族谱与-v15-适配场景)
  - [2.1 金融领域大模型（LLM for Finance）](#21-金融领域大模型llm-for-finance)
  - [2.2 时间序列大模型（价格/波动/胜率直接预测）](#22-时间序列大模型价格波动胜率直接预测)
  - [2.3 深度强化学习（直接学习开仓/加仓/平仓决策）](#23-深度强化学习直接学习开仓加仓平仓决策)
  - [2.4 GitHub 可参考马丁 + AI 项目](#24-github-可参考马丁--ai-项目)
- [3. AI 决策四大铁律（不可违背的门禁原则）](#3-ai-决策四大铁律不可违背的门禁原则)
  - [3.1 铁律 1：基线可随时回退（一键 OFF 开关 + 状态快照）](#31-铁律-1基线可随时回退一键-off-开关--状态快照)
  - [3.2 铁律 2：不超基线不启用（Walk-Forward + 全量双验证）](#32-铁律-2不超基线不启用walk-forward--全量双验证)
  - [3.3 铁律 3：最大最小调节边界（防止 AI 放飞自我）](#33-铁律-3最大最小调节边界防止-ai-放飞自我)
  - [3.4 铁律 4：边界随回测+实盘表现缩放（不是一成不变的硬编码）](#34-铁律-4边界随回测实盘表现缩放不是一成不变的硬编码)
- [4. Phase D（1-2 周）：BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测](#4-phase-d1-2-周bilstm-attention-爆仓预警--patchtst-回撤预测)
  - [4.1 模型选型与数据集构造](#41-模型选型与数据集构造)
  - [4.2 Phase D 输出空间与四大铁律边界](#42-phase-d-输出空间与四大铁律边界)
  - [4.3 Phase D 代码接入点映射（精确到模块与函数）](#43-phase-d-代码接入点映射精确到模块与函数)
  - [4.4 Phase D 启用门禁流程（§3 铁律 2 的可执行化）](#44-phase-d-启用门禁流程3-铁律-2-的可执行化)
- [5. Phase E（3-6 周）：PPO-LSTM 强化学习接管加仓金字塔 + 确定性风控盾](#5-phase-e3-6-周ppo-lstm-强化学习接管加仓金字塔--确定性风控盾)
  - [5.1 状态空间 / 动作空间 / 奖励函数设计](#51-状态空间--动作空间--奖励函数设计)
  - [5.2 确定性风控盾（Deterministic Shield）设计](#52-确定性风控盾deterministic-shield设计)
  - [5.3 Phase E 输出边界与边界缩放](#53-phase-e-输出边界与边界缩放)
  - [5.4 Phase E 代码接入点映射（精确到模块与函数）](#54-phase-e-代码接入点映射精确到模块与函数)
  - [5.5 Phase E 训练框架与离线评估方案](#55-phase-e-训练框架与离线评估方案)
- [6. Phase F（长期架构）：FLAG-Trader 式 LLM 策略网络 + SFT→PPO 两阶段训练](#6-phase-f长期架构flag-trader-式-llm-策略网络--sftppo-两阶段训练)
  - [6.1 SFT 暖启动阶段：模仿 V15 基线成功轨迹](#61-sft-暖启动阶段模仿-v15-基线成功轨迹)
  - [6.2 PPO 策略梯度阶段：按真实交易收益继续调参](#62-ppo-策略梯度阶段按真实交易收益继续调参)
  - [6.3 易经桥接与 LLM 的融合方案](#63-易经桥接与-llm-的融合方案)
  - [6.4 Phase F 输出边界与可回退策略](#64-phase-f-输出边界与可回退策略)
- [7. 配置规范（环境变量 + config 位）](#7-配置规范环境变量--config-位)
- [8. 三阶段启用总门禁（Phase D → E → F 的升级判定流程）](#8-三阶段启用总门禁phase-d--e--f-的升级判定流程)
- [9. 风险与失效模式清单](#9-风险与失效模式清单)

---

## 1. 文档目的与演进链

### 1.1 与 TECHNICAL_DESIGN v6.0 的相位对应关系

V15 马丁策略的演进遵循「基线稳定在前、智能增强在后；每步双验证、不达标必回退」的节奏：

| Phase | 对应文档 | 启用状态 | 核心说明 |
|---|---|---|---|
| Phase A+ | TECHNICAL_DESIGN.md v6.0 §18.1 | ✅ 启用（基线组成部分） | 智能参数基线：ATR 动态止盈 + 移动止盈 + ELDER-RAY 资金调度 + BTC 风向标智能模式 |
| Phase B+ | TECHNICAL_DESIGN.md v6.0 §18.2 | ✅ 启用（v15-final 最终形态） | BULL/BEAR × Elder-ray 6 类 SubMorph 子形态微调 |
| Phase C  | TECHNICAL_DESIGN.md v6.0 §18.3 | ❌ 默认关闭（模块化保留） | 易经推理桥接 + risk/value 插值；Walk-Forward 全段退化未达 <5% 通过线 |
| **Phase D** | **本文件 §4** | ⏳ 待开发（MVP） | **BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测 → 作为 TimingGate/DirectionGate 的加分闸** |
| **Phase E** | **本文件 §5** | ⏳ 待开发（核心） | **PPO-LSTM 深度强化学习 + 确定性风控盾 → 接管加仓金字塔决策** |
| **Phase F** | **本文件 §6** | ⏳ 待开发（长期架构） | **FLAG-Trader 式 LLM 策略网络 + 易经 Prompt + SFT→PPO 两阶段训练** |

> **相位升级铁律：** 前一 Phase 通过 §3 铁律 2 的双验证（Walk-Forward 5 段全过 + 全量回测）之前，**禁止** 开发/启用后一 Phase。即 Phase D 没通过，Phase E/F 永远不进实盘。

### 1.2 调研依据

本路线图基于以下公开资料与 GitHub 调研结果（2025-08 ~ 2026-08）综合得出：

1. **FinGPT 开源金融大模型族**：GitHub AI4Finance-Foundation/FinGPT（21k+ star）；LoRA 微调 Llama-2-7B 成本 ~$300/次；FinGPT-Forecaster 端到端预测管线；FinRL-X 深度强化学习交易框架。
2. **时间序列 SOTA 架构**：PatchTST（A Time Series is Worth 64 Words, ICLR 2023）、iTransformer（Inverted Transformer, ICLR 2024 Spotlight）、TimesNet（ICLR 2023 Oral）、VAIOM 2026（ICLR 匿名）。
3. **强化学习马丁/交易前沿**：CVaR-PPO + LLM 风险信号（FinRL-DeepSeek 2025）、Dynamic Multi-Pair PPO + Deterministic Shield（arXiv 2606.04574，2026）、FLAG-Trader（LLM as Policy + Policy Gradient RL，12 作者联合 2025）。
4. **马丁 + AI GitHub 参考项目**：houzhaohan《BiLSTM-Attention 模型分析马丁策略爆仓风险》论文代码、studerus/martingalebot R 包（DEoptim 全局优化）、studerus/ai-trading-bot（Alpaca LLM 马丁助手）、chl-5g/QuantLLM（Qwen2.5-14B QLoRA + LangGraph 多 Agent 交易架构）。

---

## 2. 模型族谱与 V15 适配场景

### 2.1 金融领域大模型（LLM for Finance）

| 模型 | 开源 | 底座 | 核心能力 | 训练成本 | V15 适配场景 |
|---|---|---|---|---|---|
| **FinGPT** | ✅ 21k star | Llama-2-7B/13B、ChatGLM2、Qwen、MPT、Falcon | 金融情感 F1=87.62%、新闻分类 95.5%、股票预测 45–53%、Forecaster 端到端 | LoRA 微调 $300/次（RTX3090 可跑） | 推特/OKX 新闻情感 → 叠加 TimingGate 评分 |
| **BloombergGPT** | ❌ 闭源 | Bloom 50B | 金融 NLP SOTA | $300 万训练 | 不可得，忽略 |
| **QuantLLM (chl-5g)** | ✅ 2026.5 | Qwen2.5-14B QLoRA | A股/期货/ETF/可转债 + **LangGraph 多 Agent** | 单卡 24G 可微调 | 多 Agent 架构映射 V15 多模块 |
| **FLAG-Trader 2025** | ✅ 顶会开源 | 任意 LLM | **LLM 本身 = RL 策略网络**，PEFT 学领域 → PPO 收益梯度调参，双向增强 | 需 2×24G 以上 | Phase F 核心范式 |
| **FinRL-DeepSeek 2025** | ✅ 代码开源 | DeepSeek V3 / Llama 3.3 / Qwen-2.5 | LLM 风险评分 → CVaR-PPO 风险敏感 RL | 单卡可跑 | kelly_optimizer 接 CPPO 替代固定胜率 |

> ⚠️ **LLM 价格预测 = 硬币翻面警示：** FinGPT 官方公布 price prediction 仅 45–53%。**禁止** 任何 Phase 直接把 LLM 输出作为开仓方向信号。LLM 只用于：情感、风险评估、策略推理、与 RL/CPPO 结合的风险信号。

### 2.2 时间序列大模型（价格/波动/胜率直接预测）

| 模型 | 金融实测表现 | 参数量级 | 马丁策略价值 |
|---|---|---|---|
| **PatchTST** ⭐️ | 击败 DLinear，16/24 benchmark SOTA，**保留局部价格动力学 + 通道独立防噪声过拟合** | 1–3M | 预测未来 8–16 根 K 线**回撤深度** → 决定 addon 间距 & 下档是否挂 |
| **iTransformer** | 多变量跨资产关联 SOTA | 中 | BTC 风向标多变量建模 → 预测「目标币种是否跟 BTC 跌到补仓线」 |
| **TimesNet** | 周期/非周期同时捕捉 | 中 | **自动识别 swing 周期长度** 回传给 TimingGate，替代 swing_window 固定 2/3 |
| **VAIOM 2026** | 1H 外汇 next return 建模，连续向量 + ordinal 离散 bucket | 0.9M | 下一根收益 bucket → 映射成 TimingGate 软阈值 |
| **BiLSTM-Attention** | 论文专门研究马丁爆仓预警 | 极轻 | 输出「当前继续加仓风险」→ 闸门截断 addon4 等深档 |

### 2.3 深度强化学习（直接学习开仓/加仓/平仓决策）

| 算法/框架 | 回测成绩 | V15 接入点 |
|---|---|---|
| **PPO + LSTM + Deterministic Shield** ⭐️(2606.04574) | 加密货币动态配对 OOS 优于启发式 10% 统计显著；**确定性风控盾是显著夏普提升的根源** | 直接输出 加仓间距/加仓金额倍率/最大加仓档/TP 伸缩；见 §5.2 风控盾设计 |
| **CVaR-PPO (CPPO) + LLM 风险评分** | 熊市（2021后大跌）夏普显著高于纯 PPO；纯 PPO + LLM 反而伤性能，必须加风险框架 | `kelly_optimizer.py` 替代固定胜率 |
| **TD3 + FinGPT 情绪** (Wo Long 2025) | 44 S&P OOS 夏普 > 1.5 | TimingGate 4 维度权重（structure/retrace/extension/sentiment）动态学 |
| **LSTM + PPO 2 阶段** (MDPI Electronics 2026) | BTC 平均利润率 32%、夏普 1.34 | `v15_signal.py` 超前方向预测 → DirectionGate 闸门增强 |
| **FLAG-Trader 范式** (2025 顶会) | 纯 LLM + 纯 RL 双向增强 | Phase F 核心：SFT 模仿 V15 成功轨迹 → PPO 按收益梯度 |

**训练框架选型：**
- **FinRL / FinRL-X** ⭐️：AI4Finance 官方出品，**Gym 风格环境 + PPO/A2C/DDPG/SAC/TD3 全预实现 + CCXT/OKX 数据对接**，天然兼容 `okx_client.py`
- **Stable-Baselines3 + Gymnasium**：最小改动，把 `v15_backtest.py` 包装成 env.step
- **RLlib**：分布式大算力场景

### 2.4 GitHub 可参考马丁 + AI 项目

| 项目 (owner/repo) | 语言 | 核心 | V15 可借鉴点 |
|---|---|---|---|
| houzhaohan BiLSTM-Attention-Martingale | Python | 马丁爆仓预警模型 | 输入 = 价格 + 马丁档位历史；输出 = 爆仓风险 → 接 `_place_addon_grid_orders` 闸门 |
| studenterus/martingalebot (R) | R | DEoptim 差分进化全局搜索马丁参数 | 贝叶斯 BO 之外的另一种参数调优对比基线 |
| studenterus/ai-trading-bot | Python | Alpaca API 马丁 + LLM Assistant | `auto_monitor.py` 异常警报 + LLM 生成处置建议 |
| chl-5g/QuantLLM | Python | Qwen2.5-14B QLoRA + LangGraph 多 Agent 4 市场 | **多 Agent 架构直接映射：TimingGate Agent / DirectionGate Agent / 风控 Agent / 易经 Agent** |
| alimogh/Passivbot | Python | 多交易所马丁网格机器人多年实盘 | OKX/Binance 接口一致性设计参考 |

---

## 3. AI 决策四大铁律（不可违背的门禁原则）

> 本节是本文档的灵魂与最高优先级约束。**任何 AI 模型输出，若与本节任一铁律冲突，一律作废（直接 fallback 到 v15-final 基线输出）。**

### 3.1 铁律 1：基线可随时回退（一键 OFF 开关 + 状态快照）

**定义：** 任何 AI 增强模块（Phase D/E/F）必须满足：
1. 单一环境变量即可一键关闭（见 §7 配置规范 `V15_AI_ENABLED=false`、各 Phase 独立开关、模块独立开关共 3 级）。
2. 关闭后系统行为与 `TECHNICAL_DESIGN.md v6.0 v15-final (Phase B+)` **字节级等价**（除新增的日志字段外，不允许任何逻辑差异）。
3. 每一 Phase 启用前必须对当时实盘状态（`data/v15_state.json` + `data/bayesian_opt/` + 持仓）做版本化快照：`data/ai_snapshots/phase_{D,E,F}_before_{YYYYMMDD}.tar.gz`，快照哈希存到 `docs/CHANGELOG.md`，确保回退有锚点。
4. 已挂的 OCO/加仓网格订单：回退瞬间，如果 AI 已修改过这些订单（例如 Phase D 建议取消 addon4），回退必须**恢复**到基线本该挂的订单集合（由 `_place_addon_grid_orders` 基线版本重新计算并自动 cancel+re-place，不允许留下 AI 污染的挂单）。
5. 进程级守护：`run.py trader` 启动时读取 `V15_AI_ENABLED`，若为 false 则 `import lib/ai_*` 分支一律跳过，**不在内存加载 AI 模型**（防止模型错误或内存膨胀影响基线）。

### 3.2 铁律 2：不超基线不启用（Walk-Forward + 全量双验证）

**定义：** 某 Phase（或任何子模型）从「开发完成」进入「实盘启用」前必须：

| 验证项 | 方法 | 通过阈值 | 不通过处理 |
|---|---|---|---|
| **① 全量历史回测相对增益** | 对 Phase4 小币种池 5 个币种全量跑，对比 v15-final 基线 | **总收益 基线 + ≥5%** 且 **卡尔马比率 ≥ 基线 × 1.05** | 不达标模型作废，不得实盘 |
| **② Walk-Forward 5 段稳定性** | 复用 `walk_forward_validator.py` 框架；5 段等长切分；每段只用段前训练；段内不可调参 | **5/5 段退化率 < 10%**（任意段相对基线下跌不超过 10%）且 **≥ 3 段正向增益** | 退化率超标 → 模型作废；正向段数不足 → 降低模型复杂度或降低动作空间维度 |
| **③ 回撤控制不劣化** | 最大回撤 MDD、最大连续亏损笔数 | MDD ≤ 基线 × 1.10；最大连续亏损笔数 ≤ 基线 + 2 | MDD 或连亏超标 → 加强 §3.3 边界下限、或加强风控盾 |
| **④ 小样本 out-of-distribution 鲁棒** | 对 2024-11、2025-05 两段极端行情（大跌/横盘）单独跑 | 必须 ≥ 基线 × 0.90（AI 在极端行情不得恶化超 10%） | 不达标 → 加强边缘样本增强或缩小动作空间 |

**验证执行方式：** 生成 JSON 报告（路径 `data/ai_benchmarks/phase_{D,E,F}_{commit_sha}_wf_report.json`），报告含 ①②③④ 所有数值，自动写入 `docs/CHANGELOG.md`，人工二次确认后方可在配置中把对应 Phase 的 `*_ENABLED` 置为 true。

### 3.3 铁律 3：最大最小调节边界（防止 AI 放飞自我）

**核心思想：** 马丁策略最致命的失效模式 = 「AI 学到了越亏越补、无限制加仓」。因此 **所有 AI 输出值必须先 clamp 到「基线相对边界」内，才允许影响实际决策**。边界本身可缩放（见 §3.4），但缩放的范围也有外层铁壳（缩放因子本身 ∈ [0.50, 1.50]）。

**通用 clamp 公式：** 设 `X_base` 为基线（v15-final）的原始决策值，`X_ai` 为 AI 模型输出建议值，最终生效值：

```
X_clamped = clamp( X_ai ,  X_base × LOWER(·) ,  X_base × UPPER(·)  )
```

下表列出各关键决策变量的 **初始默认边界**（Phase 初启用时的值），后续按 §3.4 可逐步放大或收紧：

| 决策变量 | 基线出处 (X_base) | LOWER 默认 | UPPER 默认 | 外层铁壳（任何情况不得越界） | 适用 Phase |
|---|---|---|---|---|---|
| **TimingGate 总分阈值 timing_threshold** | `timing_gate.py __init__` default 0.42 | 0.70×（放宽，AI 不得把门禁设得比基线更松超过 30%） | 1.20×（收紧） | [0.30, 0.80] 绝对阈值 | D |
| **TimingGate soft size_power** | `v15_backtest.py` default 2.49 | 0.60×（弱化低分惩罚） | 1.40×（强化低分惩罚） | [1.00, 4.00] 绝对区间 | D, E |
| **加仓间距 addon_pct 倍率** | `strategy_params.py get_vol_adjusted_params` 返回 addon_pct | 0.80×（更密） | 1.30×（更疏） | 绝对间距 ∈ [3%, 25%] | E |
| **单档加仓金额倍率 addon_size_mult** | `capital_manager.py` ADDON1~4_PCT 金字塔 | 0.60×（降加仓额度） | 1.50×（升加仓额度） | 各档总和 ≤ 原预算总和 × 1.10 | E, F |
| **最大加仓档 max_addons** | `capital_manager.py` MAX_ADDONS_PER_POSITION=4 | -1 档（允许缩成 3 档） | +0 档（**禁止 AI 扩大到 5 档**，马丁最多 5 单基线已定） | [1, 4] 整数 | D, E, F |
| **TP 比例 tp_pct 倍率** | `strategy_params.py` BASE_TP_PCT + vol 调整 | 0.80×（更快止盈） | 1.30×（更宽止盈） | 绝对 TP ∈ [1.5%, 12%] | E, F |
| **底仓比例 base_position_pct 倍率** | `.env.common` BASE_POSITION_PCT=0.22 | 0.70×（减底仓） | 1.20×（加底仓） | 绝对 pct ∈ [5%, 40%] | E, F |
| **DirectionGate 闸门严格度** | `direction_gate.py` strict 参数 & BTC 风向标 3 日确认 | 放宽最多 1 日（2 日确认） | 收紧最多 2 日（5 日确认） | 严格度整数 ∈ [2, 5] 日 | D |
| **易经插值 net_value 的 clamp 范围** | `yijing_param_interpolator.py _NEUTRAL_THRESHOLD=0.12` & clamp[0.75,1.25] | 只允许收紧：下界 ≥ 0.80，上界 ≤ 1.20 | —— | Phase C 本身没启用，叠加 AI 更保守 | F（C 未启用则禁止） |
| **Skip 首单（不开仓）闸门** | `v15_trader.py execute_open_position` 是否 return | AI 可以建议「Skip 本次」，**AI 不得强制「必开」**（开不开最终必须基线信号也同意） | —— | —— | D, E, F |

> **最高优先级规则（上表最后一行特别强调）：** AI 只能「否决」或「微调」开仓；**AI 永远无权在基线信号判定 WAIT 时强制开仓**。开仓的最终「是否开」决定权 100% 保留在 v15-final 基线的 16 层入场决策 + DirectionGate。AI 只能：(a) 如果基线同意开，则调仓位；(b) 如果基线同意开，AI 可以说「这次别开」；(c) 如果基线不同意开，AI 啥也不能做。

### 3.4 铁律 4：边界随回测+实盘表现缩放（不是一成不变的硬编码）

§3.3 的 LOWER/UPPER 默认边界不是硬编码，而是**随模型表现**动态缩放。缩放用两个独立指标：**回测稳健度得分 S_bt**（开发期）和 **实盘跟踪得分 S_live**（实盘启用后）。

#### 3.4.1 回测稳健度得分 S_bt（§3.2 双验证通过时计算）

```
S_bt = (gross_return_ratio × 0.40)           # 总收益 / 基线总收益
     + (calmar_ratio_ratio × 0.30)           # 卡尔马 / 基线卡尔马
     + (wf_positive_segments / 5 × 0.20)     # Walk-Forward 正向段数占比
     + max(0, 1 - abs(mdd_ratio - 1)) × 0.10 # 回撤接近基线给分，偏离扣分
```

- **S_bt ≥ 1.20**：模型优秀 → 边界**放大**，缩放因子 `K_bound = 1.20`
- **1.05 ≤ S_bt < 1.20**：模型合格 → 边界保持默认，`K_bound = 1.00`
- **1.00 ≤ S_bt < 1.05**：模型刚好达标 → 边界**收紧**，`K_bound = 0.80`
- **S_bt < 1.00**：模型不合格 → **禁止启用**（触发铁律 2）

**实际 LOWER/UPPER 随 K_bound 调整：**
```
LOWER_eff = 1 - (1 - LOWER_default) / K_bound    # K_bound > 1 时，LOWER_eff 更靠近 1.0（更宽松的下边界）
UPPER_eff = 1 + (UPPER_default - 1) × K_bound    # K_bound > 1 时，UPPER_eff 进一步放大
最后外层铁壳必须再 clamp 一次，防止 K_bound 缩放后越界。
```

#### 3.4.2 实盘跟踪得分 S_live（启用后每 7 天重算一次）

实盘启用后，用「AI 开启的实盘表现」对比「同期模拟盘基线表现」（模拟盘基线需同步并行跑，写入 `data/ai_benchmarks/live_baseline_sims.csv`）：

```
S_live = (live_pnl_ai / live_pnl_baseline_sim × 0.50)
       + (live_win_rate_ai - live_win_rate_baseline_sim + 1) × 0.25
       + max(0, 1 - abs(live_mdd_ai / live_mdd_baseline_sim - 1)) × 0.25
```

每 7 天滚动窗口重算，并触发边界调整：

| S_live 区间 | 动作 |
|---|---|
| **≥ 1.20（连续 2 窗口）** | K_bound 上调一档：0.80 → 1.00 → 1.20 → **1.35 封顶**（外层铁壳，防止过拟合历史后无限放大） |
| **(1.05, 1.20)** | K_bound 不变 |
| **[0.95, 1.05]** | K_bound 不变（中性区，不调） |
| **(0.85, 0.95)（连续 2 窗口）** | K_bound 下调一档：1.35 → 1.20 → 1.00 → 0.80 → **0.50 保底** |
| **< 0.85（单窗口触发）** | **立即触发回退**（执行 §3.1 铁律 1 的一键 OFF，关闭本 Phase 所有 AI 输出，切换为纯基线，并生成回退告警） |

> **缩放铁壳：** K_bound ∈ [0.50, 1.35]，任何情况不能超出。S_live 重算 & K_bound 调整脚本 = `core/ai_boundary_scaler.py`（待实现，Phase D 同时交付）。

---

## 4. Phase D（1-2 周）：BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测

### 4.1 模型选型与数据集构造

| 模型 | 职责 | 输入 | 输出 |
|---|---|---|---|
| **BiLSTM-Attention（马丁爆仓预警器）** ⭐️ | 对「当前持仓位置」的爆仓概率打分 | 最近 60 根 4H OHLCV（5×60=300 维）+ 当前 position_level (0~4) + 未实现盈亏比 + ATR z-score + TimingGate 三维评分（共 307 维） | `P_bust` ∈ [0, 1]，即「当前持仓补满所有允许的加仓后仍不能 TP 的概率」 |
| **PatchTST（回撤深度预测器）** ⭐️ | 预测未来 24 根 1H K 线的最大回撤比例 | 最近 120 根 1H OHLCV（5×120=600 维，通道独立按 PatchTST 切 patch_len=12 stride=6） | `predicted_max_drawdown_24h` ∈ [-1, 0]（负值，百分比，如 -0.18 = 未来 24h 最大回撤 18%） |

**数据集构造（离线批处理）：**
1. 用 `v15_backtest.py` 的参数随机化版跑 1000 次以上合成回测（币种池 5 币 × 参数扰动 × 起止时间随机偏移），覆盖首单、加 1 档、加 2 档、加 3 档、加 4 档所有 level。
2. 每次回测的「每个 step」打标签：
   - BiLSTM：最终 TP 平仓 = 0（安全）；达到 max_addons 且后续 N 根没 TP 而触发强制离场 = 1（爆仓）
   - PatchTST：以 step 为起点，未来 24 根实际最大回撤 = 回归标签
3. Walk-Forward 切分：严格复用 `walk_forward_validator.py split_walk_forward()` 分段，训练只允许段前数据，禁止段后泄漏。
4. 数据集落地：`data/ai_datasets/phase_d_bilstm.{train|wf1..wf5|test}.npz` 与 `phase_d_patchtst.*.npz`。

### 4.2 Phase D 输出空间与四大铁律边界

Phase D 两个模型的输出**不能直接改任何数值参数**，只能在三个离散闸门点上提供「否决建议 + 微调建议」，且严格遵守 §3.3 边界：

| 闸门点 | 触发条件（模型输出 + 基线结合） | 生效动作（在基线基础上叠加） | 边界依据 |
|---|---|---|---|
| **G-D1：Skip 首单** | 基线判定「可开仓」，但满足任一：(a) PatchTST `predicted_max_drawdown_24h < -32%`（马丁 5 单总跨度默认 4×8%=32%）；或 (b) 首单 level 时 BiLSTM `P_bust > 0.60` | 本次不开仓，日志打 `G-D1 SKIP`，state 不写入任何持仓 | §3.3 最后一行：AI 只能否决，不可强开 |
| **G-D2：缩加仓档数** | 已经开仓或即将加仓；BiLSTM `P_bust > 0.55`（当前 level 继续往下补 → 爆仓风险高） | `max_addons_eff = max(1, MAX_ADDONS - 1)`，丢弃最深档 addon；如果是 level 0 开仓阶段 → `addon_budgets` 去除末尾一档 | §3.3 max_addons 的 LOWER=-1 档；不允许缩到 0 |
| **G-D3：Timing 硬门禁降低 strictness** | TimingGate 判定 `UNCLEAR` 但 patchtst_drawdown > -10%（没那么深回撤）且 BiLSTM `P_bust < 0.30`（爆仓风险低） | timing_score × 1.05 放宽（进入 §3.3 timing_threshold LOWER=0.70× 范围内）；soft_mode 下 size_power × 0.9 微放宽松 | §3.3 timing_threshold LOWER 0.70× & size_power LOWER 0.60× |

### 4.3 Phase D 代码接入点映射（精确到模块与函数）

| V15 现有文件 | 接入函数/位置 | 注入 AI 逻辑 | 新文件/新类 |
|---|---|---|---|
| [core/v15_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_trader.py) | `execute_open_position()` 函数开头，在检查 `_get_direction_ctx()` 之后、实际开仓之前 | 调用 `PhaseDGateway.should_skip_open(coin, ctx)` → 返回 true 则 `return None` 不开仓并打 `G-D1 SKIP` 日志 | 新增 `lib/phase_d_gateway.py` 类 `PhaseDGateway`（封装两个模型推理 + 闸门逻辑） |
| [core/v15_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_trader.py) | `_place_addon_grid_orders()` 中构造 `addon_budgets` 之后、实际挂单之前 | 调用 `PhaseDGateway.compute_effective_max_addons(coin, pos, addon_budgets)` → 返回 `(effective_max_addons, trimmed_addon_budgets)`；若缩档则 log `G-D2 TRIM addon4` | 同上 |
| [lib/timing_gate.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/lib/timing_gate.py) | `TimingGate.evaluate()` 末尾，计算完 `timing_score` 与 `hard_pass`/`unclear` 之后、返回之前 | 调用 `PhaseDGateway.apply_timing_relaxation(symbol, timing_score, size_power, regime)` → 返回调整后的 `(timing_score, size_power)`；**strict=true 不可被 AI 改成 false（§3.3 外层铁壳），只能改数值** | 同上 |
| [core/v15_backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_backtest.py) | `run_backtest()` 中对应 3 个位置对称注入（实盘与回测必须一致，否则§3.2 无意义） | 同实盘三处逻辑；回测模型可用「历史 oracle 值」与「真实推理值」双模式，oracle 模式当模型理论上界 | 复用 `PhaseDGateway`，加 `mode="infer"` / `"oracle"` 切换 |
| `14-V15经典马丁策略/`（根） | 新增训练脚本（不在实盘 import 路径里） | `phase_d_train_bilstm.py` 和 `phase_d_train_patchtst.py`：读取 `data/ai_datasets/` → 训练 → 保存权重到 `data/ai_models/phase_d_bilstm_vX.pt`、`phase_d_patchtst_vX.pt`；版本号 X 升 + 记录到 CHANGELOG | 新增 `ai_trainers/` 子目录（含 trainer、plot、eval） |
| [lib/bayesian_optimizer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/lib/bayesian_optimizer.py) | 贝叶斯优化流程末尾（参数评估后） | 增加钩子：评估结果自动写入 `data/ai_benchmarks/baseline_refs.csv`，作为 §3.2 双验证的基线引用 | 无新文件，加 1 个写 CSV 函数 |
| `core/` | 新增 `ai_boundary_scaler.py`（§3.4 共用） | 计算 S_bt / S_live → 读/写 K_bound → 每次 PhaseDGateway 加载时注入生效的边界 | 新增 `core/ai_boundary_scaler.py` |

### 4.4 Phase D 启用门禁流程（§3 铁律 2 的可执行化）

```
开发完成 phase_d_gateway.py + 两模型权重 v1
    │
    ├─ step 1: 跑 §3.2 ①全量回测（5 币种）
    │           失败 → 回到调参/调模型，不进下一步
    │           成功 → 写入报告 JSON
    │
    ├─ step 2: 跑 §3.2 ② Walk-Forward 5 段（复用 walk_forward_validator）
    │           5 段任一段退化率 ≥ 10% → 作废
    │           正向段 < 3 → 作废
    │           通过 → 写 wf_report.json
    │
    ├─ step 3: ③ 回撤 & ④ OOD 极端行情检查
    │           不通过 → 加强边界收紧或减动作
    │           通过 → 所有 JSON 归档 data/ai_benchmarks/
    │
    ├─ step 4: 生成 §3.1 (3) 状态快照 & CHANGELOG.md 记录
    │
    └─ step 5: 手动（PR 审批后）在 config/.env.v15 把
               V15_AI_ENABLED=true
               V15_AI_PHASE_D_ENABLED=true
               合并入 main，随下次 poll_once 生效
```

---

## 5. Phase E（3-6 周）：PPO-LSTM 强化学习接管加仓金字塔 + 确定性风控盾

### 5.1 状态空间 / 动作空间 / 奖励函数设计

**5.1.1 状态空间 S（从 V15 现有模块直接取，保证与实盘一致）**

```
s = [
  # --- TimingGate 状态 (4 维) ---
  timing_score, structure_match_score, retrace_quality_score, extension_chase_score,

  # --- DirectionGate 状态 (4 维 one-hot + 1 维强度) ---
  regime(ACCUM/UP/DOWN 3 hot) + short_enabled(bool) + long_enabled(bool) + btc_windvane_strength,

  # --- RegimeManager 状态 (5 维) ---
  regime_zone(0~4 one-hot), days_in_current_zone,

  # --- 持仓状态 (9 维) ---
  position_level ∈ [0,1,2,3,4]  (one-hot 5 维),
  avg_entry_price_pct_diff,     # (当前价 - 均价) / 均价
  unrealized_pnl_ratio,         # 浮亏浮盈 / 预算
  distance_to_liq_ratio,        # 距强平线 / 价格

  # --- 波动 & 周期 (8 维) ---
  atr_14 / price, atr_14_zscore_30,
  realized_vol_30d, vol_zscore_60,
  btc_corr_30d, btc_rsi_14 / 100,
  swing_window_daily, swing_window_4h,

  # --- 历史表现 (3 维) ---
  recent_10_trades_win_rate,    # 最近 10 笔 TP/爆仓 的胜率
  recent_10_trades_avg_pnl_ratio,
  max_drawdown_30d,
]
# 总维度 ≈ 4 + 5 + 5 + 9 + 8 + 3 = 34 维（小维度，防止 RL 过拟合）
```

**5.1.2 动作空间 A（4 连续 + 1 离散 clipped，严格 §3.3 边界）**

```
a = [
  addon_pct_mult,      # 连续 ∈ [LOWER=0.80, UPPER=1.30] × 基线
  addon_size_mult,     # 连续 ∈ [0.60, 1.50]；§3.3 铁壳：各档总和 ≤ 原预算 × 1.10
  tp_pct_mult,         # 连续 ∈ [0.80, 1.30]
  base_position_mult,  # 连续 ∈ [0.70, 1.20]
  max_addons_delta,    # 离散 ∈ {-1, 0}（只能减档，AI 无权开第 5 档）
]
```

> **重要：** 动作空间的每个维度在 env.step 返回前，先经 §3.3 LOWER/UPPER + §3.4 K_bound 双层 clamp，RL 探索过程中永远不会产生越界动作。

**5.1.3 奖励函数 R（马丁灵魂 = TP 重置奖励 + 深档惩罚 + 风控盾硬罚）**

```
r_step = 0 （每根 K 线中间步无奖励，避免稠密噪声）

r_event = {
  +5.0    if 仓位以 TP 成功平仓（完全或部分 TP 且仓位清零 = 马丁完整重置）
  +1.0 × ratio   部分止盈且仓位未清零，ratio = 已落袋 PnL / 预算
  -1.0 × (total_deployed / initial_budget)   step 结束时资金占用率惩罚（鼓励快 TP）
  -3.0 × addon_level                          加档越深惩罚越大（level 4 罚最狠）
  -20.0   触发 max_addons 且未 TP（最坏情况，强制离场或超时）
  -3.0    触发 Deterministic Shield 越界告警（见 §5.2）
}

R_final = Σ r_event + γ=0.995 折扣
```

### 5.2 确定性风控盾（Deterministic Shield）设计

参考 2026 Dynamic Multi-Pair 论文，**RL 动作 a 在 env.step 执行前先过风控盾**，盾不通过 → 直接用基线动作 a_base 替代并返回 `-3.0` 盾告警奖励。这是 Phase E 防止 AI 放飞自我的核心硬防线（§3.3 的可执行化）：

| 盾检查项 | 越界判定 | 越界处理 |
|---|---|---|
| **DS1 总保证金率安全** | `account_margin_ratio < (IMR + 2%) × 1.50` （距维持保证金不足 1.5 倍缓冲） | 拒绝任何 `addon_size_mult > 1.0` 的动作；若已在缓冲区内则 `max_addons_delta = -1`（撤最深档） |
| **DS2 单币种投入上限** | `coin_total_deployed > per_coin_budget × 1.10`（超预算 10%，§3.3 铁壳） | 拒绝任何 `addon_size_mult > 1.0` 和 `base_position_mult > 1.0` |
| **DS3 TP 过低 / 过高绝对值** | 应用 `tp_pct_mult` 后实际 TP < 1.5% 或 > 12%（§3.3 绝对区间） | tp_pct_mult clamp 到区间边界 |
| **DS4 加仓间距绝对值** | 应用 `addon_pct_mult` 后实际 addon_pct < 3% 或 > 25%（§3.3 绝对区间） | addon_pct_mult clamp 到边界 |
| **DS5 极端行情下禁用 AI 放大** | `realized_vol_zscore_60 > 2.5`（当前波动 > 历史 99 分位） | 禁止所有 `*_mult > 1.0`（只能收紧、不能放大） |
| **DS6 连亏熔断** | `recent_10_trades_win_rate < 0.20` 且 `recent_10_count ≥ 10` | 直接拒绝所有 `max_addons_delta != -1`（只能缩档不能扩） |

### 5.3 Phase E 输出边界与边界缩放

Phase E 的 5 维动作均落入 §3.3 的对应条目，且直接使用 §3.4 的 `K_bound` 动态缩放。**特殊规定：**
- K_bound 初始值永远从 0.80 起（Phase E 上线先用收紧边界跑，连续 2 周 S_live > 1.2 才能放到 1.00）
- 即使 K_bound=1.35，`max_addons_delta` 永远不允许为 +1（基线 4 档加仓 = 5 单，不可突破）

### 5.4 Phase E 代码接入点映射（精确到模块与函数）

| V15 现有文件 | 接入函数/位置 | 注入 AI 逻辑 | 新文件/新类 |
|---|---|---|---|
| [lib/capital_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/lib/capital_manager.py) | `calculate_per_coin_allocation()` 返回结果之后、被 trader 调用前 | 取返回的 `base_usd / addon1~4_usd` 作为基线，调用 `PhaseEGateway.apply_size_multipliers(allocation, s_state)` → 返回最终预算，总和自动 clamp ≤ 原 ×1.10 | 新增 `lib/phase_e_gateway.py` 类 `PhaseEGateway`（封装 PPO policy 推理 + Deterministic Shield + 边界 clamp） |
| [lib/strategy_params.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/lib/strategy_params.py) | `get_vol_adjusted_params()` 返回结果（addon_pct / tp_pct）之后 | 调用 `PhaseEGateway.apply_param_multipliers(coin, base_params, s_state)` → 返回 `(eff_addon_pct, eff_tp_pct)` 再经 DS3/DS4 clamp | 同上 |
| [core/v15_backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_backtest.py) | `run_backtest()` 包装成 Gym 风格环境 | `env = V15MartingaleGymEnv(backtest_runner, use_shield=True)`；`env.step(a)` 内部执行基线逻辑 + 叠加动作 + 应用盾 + 返回 r(s,a) + s_next | 新增 `ai_trainers/v15_gym_env.py`（Stable-Baselines3 兼容） |
| `ai_trainers/` | 训练脚本 | `phase_e_train_ppo.py`：FinRL-X 或 SB3 PPO + LSTM policy；默认 `n_steps=2048, batch_size=64, gamma=0.995, ent_coef=0.01`；每训完 10 更新评估一次 walk-forward | 新增 `phase_e_train_ppo.py` + `phase_e_eval_wf.py` |
| [core/v15_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/v15_trader.py) | `run_poll_cycle()` 每轮循环构建 `s_state`（34 维状态）→ 传给 PhaseEGateway → 生效动作 | 每轮 1 次推理，避免高频调用；推理结果先持久化到 `data/ai_logs/phase_e_decisions.jsonl`，再应用（可复现 & 事后回溯） | 复用 `PhaseEGateway` |
| [core/auto_monitor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/core/auto_monitor.py) | 每轮轮询结尾 | 读取 phase_e_decisions.jsonl + 盾告警次数，若 24h 内 DS 告警 ≥ 5 次 → 邮件/IM 告警 + 自动触发 S_live 重算 | 在现有告警框架中新增检查项 |

### 5.5 Phase E 训练框架与离线评估方案

1. **训练数据来源：** 先纯历史回测（离线训练 20M step）→ 再用回测最佳 checkpoint 做 self-play（同一段历史，RL 动作产生新的 state 分布，迭代 3 轮）。
2. **离线评估 = §3.2 双验证**：PPO checkpoint 必须通过 Phase E 专属的回测 + 5 段 Walk-Forward。
3. **模型版本：** checkpoint 以 `phase_e_ppo_lstm_v{X}_{commit_sha}_{wf_pass_date}.zip` 命名；通过验证的版本才被 `PhaseEGateway` 加载（未通过的权重路径在 config 中直接被 reject）。

---

## 6. Phase F（长期架构）：FLAG-Trader 式 LLM 策略网络 + SFT→PPO 两阶段训练

### 6.1 SFT 暖启动阶段：模仿 V15 基线成功轨迹

**底座模型：** Qwen2.5-14B（或同尺寸开源中语金融模型），QLoRA 4-bit 量化（单卡 24G 可训练）。

**示教数据构造：** 从 V15 历史成功轨迹（最终 TP 平仓且 PnL > 0 的完整仓位周期）中抽取 step，转成 Prompt → JSON 动作的 SFT 对：

```
<SYS>你是加密货币马丁策略交易员。根据卦象、市场状态、当前仓位，给出下一动作。
【易经卦象（可选，V15_YIJING_ENABLED=false 时写"未启用"）】: {gua_text}
【TimingGate评分】: structure={s:.2f}, retrace={r:.2f}, extension={e:.2f}, score_total={t:.2f}
【DirectionGate闸门】: regime={dg_regime}, long={dg_long}, short={dg_short}, btc_windvane={dg_btc:.1f}
【当前持仓】: level={level}/4, avg_price={avg:.2f}, pnl_pct={pnl:.2f}%, dist_to_liq={liq:.1f}%
【波动环境】: atr_z={atr_z:.2f}, vol_z={vol_z:.2f}, btc_corr={corr:.2f}
【最近10笔】: win_rate={wr:.0%}, avg_pnl={pnl10:.2f}%, mdd_30d={mdd:.2f}%
【基线建议动作（参考）】: {baseline_action_json}
</SYS>
请输出下一动作的严格 JSON（无额外文本）：
```

Label = 当时真实发生且最终 TP 成功的动作（由历史回测填充）。SFT 训练 2 epoch，loss 收敛到 < 0.5 即通过暖启动。

### 6.2 PPO 策略梯度阶段：按真实交易收益继续调参

**范式 = FLAG-Trader 核心思想：LLM 本身做 RL 策略网络。**
- 用 §5.1.3 的同一奖励函数
- SFT 后的 LLM policy 继续 PPO 训练（LoRA 权重上回传梯度）
- 每 1000 step 做一次 walk-forward 早停，防止 PPO 过拟合把 SFT 学到的「合理交易风格」搞坏
- 最终 checkpoint = SFT 初始化 + PPO 收益梯度后的 LoRA 权重组合

### 6.3 易经桥接与 LLM 的融合方案

Phase F 的 Prompt 里**显式**留出易经卦象槽位（Phase C 模块化保留桥接）：
- `V15_YIJING_ENABLED=false` 时槽位写「未启用」，LLM 忽略；
- 若未来 Phase C 独立通过 §3.2 双验证重新启用，槽位填充 `yijing_bridge.py` 的 risk/value/net_value 文本 + 卦象解释文；
- 即便启用，§3.3 易经插值的 clamp 边界仍然**收紧于基线的 [0.75, 1.25] → LLM 版本下界≥0.80，上界≤1.20**（叠加 AI 反而更保守，符合铁律 3 精神）。

### 6.4 Phase F 输出边界与可回退策略

1. **LLM 输出 = §5.1.2 Phase E 相同的 5 维动作空间**（严格同一格式，便于回退对比）；
2. LLM JSON 解析失败 / 字段缺失 → 立即 fall back 到 Phase E 的 PPO checkpoint（若 Phase E 也关，则回到 v15-final 纯基线），并记 1 次解析告警，24h 内 ≥ 3 次解析告警 → 自动关 Phase F 回退到 Phase E；
3. LLM 输出动作仍然**必须经过 §3.3 边界 clamp + §5.2 确定性风控盾**两层过滤（不因为是 LLM 就有特权）；
4. S_live < 0.90 单窗口即触发 Phase F → Phase E 回退；<0.85 触发 Phase F → 纯基线回退。

---

## 7. 配置规范（环境变量 + config 位）

新增配置统一写入 `config/.env.v15`（V15 专属配置文件，不改 `.env.common` 影响其他模块）：

```ini
# =========================================================================
# V15 大模型增强总开关（§3.1 铁律 1：一键 OFF）
#   - false 时，所有 ai_* 模块代码不在内存加载
#   - true 时，才根据子开关决定各 Phase
# =========================================================================
V15_AI_ENABLED=false

# -------------------------------------------------------------------------
# Phase D：BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测
# -------------------------------------------------------------------------
V15_AI_PHASE_D_ENABLED=false
V15_AI_PHASE_D_BILSTM_MODEL_PATH=data/ai_models/phase_d_bilstm_v1.pt
V15_AI_PHASE_D_PATCHTST_MODEL_PATH=data/ai_models/phase_d_patchtst_v1.pt
V15_AI_PHASE_D_GD1_DRAWDOWN_THRESHOLD=-0.32   # PatchTST 预测回撤 -32% 触发 G-D1
V15_AI_PHASE_D_GD1_BUST_THRESHOLD=0.60        # BiLSTM 爆仓概率 60% 触发 G-D1
V15_AI_PHASE_D_GD2_BUST_THRESHOLD=0.55        # 触发 G-D2 缩档
V15_AI_PHASE_D_GD3_MAX_RELAX=1.05             # Timing 放宽最多 1.05×

# -------------------------------------------------------------------------
# Phase E：PPO-LSTM 强化学习加仓金字塔
# -------------------------------------------------------------------------
V15_AI_PHASE_E_ENABLED=false
V15_AI_PHASE_E_PPO_MODEL_PATH=data/ai_models/phase_e_ppo_lstm_v1.zip
V15_AI_PHASE_E_DETERMINISTIC_SHIELD=true      # §5.2 永远默认 true，生产不可关
V15_AI_PHASE_E_INITIAL_K_BOUND=0.80           # §3.4 起始边界缩放（Phase E 从收紧起）

# -------------------------------------------------------------------------
# Phase F：FLAG-Trader LLM 策略网络
# -------------------------------------------------------------------------
V15_AI_PHASE_F_ENABLED=false
V15_AI_PHASE_F_MODEL_PATH=data/ai_models/phase_f_qwen2_5_14b_qlora_v1/
V15_AI_PHASE_F_USE_YIJING_IN_PROMPT=false     # 易经槽位填充开关（C 没启用时必须 false）
V15_AI_PHASE_F_SFT_TEMPERATURE=0.0            # 实盘推理 temperature=0，禁用采样
V15_AI_PHASE_F_MAX_RETRIES_BEFORE_ROLLBACK=3  # 24h 内解析告警次数，超了自动回退 Phase E

# -------------------------------------------------------------------------
# 全局边界缩放状态（由 ai_boundary_scaler.py 读写，人工不手改）
# -------------------------------------------------------------------------
# 以下配置由脚本维护，可作为回退锚点；人工修改需 PR 审批
# V15_AI_K_BOUND_PHASE_D=1.00
# V15_AI_K_BOUND_PHASE_E=0.80
# V15_AI_K_BOUND_PHASE_F=0.80
```

配置加载复用现有 `lib/config_loader.py get_config_bool/get_config_float`，无需新框架。

---

## 8. 三阶段启用总门禁（Phase D → E → F 的升级判定流程）

升级前置条件（缺一不可）：

```
升级到 Phase D 实盘：
  ✅ §3.2 ①②③④ 全通过
  ✅ 状态快照 + CHANGELOG 记录
  ✅ PR 审批通过
  ✅ 其他 Phase（E/F）均 false

升级到 Phase E 实盘：
  ✅ Phase D 已实盘连续运行 ≥ 28 天
  ✅ Phase D S_live 28 天 ≥ 1.05
  ✅ Phase E 自身 §3.2 ①②③④ 全通过
  ✅ 新增快照 + CHANGELOG

升级到 Phase F 实盘：
  ✅ Phase E 已实盘连续运行 ≥ 56 天
  ✅ Phase E S_live 56 天 ≥ 1.10
  ✅ Phase F 自身 §3.2 ①②③④ 全通过
  ✅ 新增快照 + CHANGELOG
```

任意 Phase 在实盘出现以下任一情况 → **降级回退自动触发**：
- S_live < 0.85 单窗口
- 24h 内 Deterministic Shield 告警 ≥ 10 次
- MDD 连续 3 天 > 基线 MDD × 1.20

---

## 9. 风险与失效模式清单

| 失效模式 | 触发原因 | 防护措施（来自本文档哪一节） |
|---|---|---|
| AI 学到越亏越补 | RL 奖励稀疏 + 稠密深档未惩罚 | §5.1.3 奖励 `-1.0 × 资金占用率` `-3.0 × addon_level`；§5.2 DS6 连亏熔断；§3.3 max_addons 只可缩档 |
| 金融 LLM 幻觉导致错误动作 | 纯 LLM 价格预测只有 50% | §2.1 警示 + §3.3 最高优先级规则：AI 不可强制开仓，只能否决/微调 |
| 过拟合历史训练集 | Walk-Forward 不严谨 + checkpoint 选得太贪 | §3.2 ② Walk-Forward 5/5 <10% 退化硬门槛 |
| 实盘/回测分布差异导致 AI 劣化 | 模型在极端行情下行为发散 | §3.2 ④ OOD 单独门槛；§3.4 S_live <0.85 立即回退；§5.2 DS5 高波动禁放大 |
| 模型推理延迟/崩溃影响实盘轮询 | 大模型推理耗时 > poll_once 预算 | §3.1 (5) 进程级守护，可完全不加载 AI；Phase D/E 推理 <50ms（轻模型），Phase F 离线批量推理缓存 |
| 配置误操作打开 AI，导致污染 | 手滑改了 env | §7 V15_AI_ENABLED 总闸 + 各 Phase 子闸；启动时 log 明确打印 "AI 模型未加载" 或 "Phase X loaded, model=path" |
| 易经桥接 + LLM 双迷信 | 叠加后过度收紧/放宽参数 | §6.3 LLM 版本易经插值 clamp ≥[0.80, 1.20]；Phase C 本身未通过双验证时 LLM Prompt 槽位写「未启用」 |
| 升级太快，前后 Phase 叠加复杂度飙升 | 人类心智负载过大 | §8 硬性天数门槛 + S_live 门槛；前 Phase 稳定 ≥ 28/56 天才能升级 |
| 无法解释某笔订单为何这样开 | AI 动作黑盒、事后无法追溯 | §5.4 所有推理决策先写 `data/ai_logs/phase_*_decisions.jsonl`（含 state 哈希、动作、盾检查、边界 clamp 前后值），可审计可回放 |

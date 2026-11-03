# L1 专属金融 Transformer 深度评估：训练·标注·推理·算力

> 日期：2026-11-03
> 来源：仓库资产盘点（23/四层闭环 + 40/周期系统 + 34/SACG）+ recall 记忆（NeuralSDE v3c MAE 退化 + regime 检测反模式 + 外部 SOTA 调研）
> 用途：SPEC-L0-L1-DOMAIN-DISCOVERY Phase B 启动前参考

---

## §1 模型资产盘点（当前已在训练/推理的 L1 金融模型）

### 1.1 活跃模型清单

| # | 模型 | 路径 | 大小 | 参数量 | 训练状态 | 推理在产？ |
|---|---|---|---|---|---|---|
| M1 | **NeuralSDE v1** | `23-.../data/neural_sde_v1.pt` | ~1.2 GB | ~3 亿 | ✅ 已训练（100 epoch，final_loss 0.0119） | ✅ 实盘在产 |
| M2 | NeuralSDE v1_dim64 | `23-.../data/neural_sde_v1_dim64.pt` | ~400 MB | ~80M | ✅ 已训练 | ✅ 实盘在产（维度精简版） |
| M3 | NeuralSDE v1_path_sig | `23-.../data/neural_sde_v1_path_sig.pt` | ~1.5 GB | ~3.5 亿 | ✅ 已训练（路径签名增强版） | ✅ 在产 |
| M4 | NeuralSDE v1_multitask_88k | `23-.../dreambuddy_evolution/data/neural_sde_v1_multitask_88k_v3.pt` | ~1.2 GB | ~3 亿 | ✅ 已训练（88k 样本多任务） | ✅ 在产 |
| M5 | ExitRL Policy v1 | `23-.../dreambuddy_evolution/data/exit_policy_v1.pt` | ~30 MB | ~2M | ✅ 已训练 | ✅ 在产 |

**DomainCouplingHead 基线选择**：M2 `neural_sde_v1_dim64.pt`（~400MB，~80M 参数）—— 更小更快，推理延迟最低，适合做轻量 head 的 backbone。

### 1.2 相关架构组件（非模型，但直接影响训练/推理）

| # | 组件 | 位置 | 作用 | DomainCouplingHead 复用 |
|---|---|---|---|---|
| C1 | **online_trainer.py** | `23-.../core/online_trainer.py` | EWC 防遗忘 + 滚动训练 + 每季度 full retrain | ✅ 直接复用 |
| C2 | **structural_break_detector.py** | `23-.../core/structural_break_detector.py` | 波动率 regime 检测（HMM k=2） | ✅ 扩展到 k=3（bull/chop/bear） |
| C3 | **cross_attention.py** | `23-.../core/cross_attention.py` | 因子间 CrossAttention 权重矩阵 | ✅ DomainCouplingHead 6×6 输出复用架构 |
| C4 | **granger_causality_checker.py** | `23-.../core/granger_causality_checker.py` | 因果关系对 + p-value | ✅ Phase A 标注管线复用做 coupling matrix |
| C5 | **sector_transmission.json** | `40-周期系统/` | 跨资产分层传导图 | ✅ domain_transmission.json 架构模板 |
| C6 | **btc_regime_detector.py** | `23-.../core/btc_regime_detector.py` | 跨资产 BTC-SPY 3态 | ⚠️ 已 recall 标记反模式（cross-asset 不适用于 BTC-only v3c），重构为 BTC-only k=3 |

---

## §2 训练经验教训（已验证 + 反模式）

### 2.1 已验证训练经验

| # | 经验 | 来源 | 适用 Phase |
|---|---|---|---|
| E1 | **EWC 防遗忘有效**（online_trainer.py 已实现） | NeuralSDE v1 → v3c 退化根因分析：多 regime 训练时灾难性遗忘 | Phase B 增量训练复用 EWC |
| E2 | **fine-tune lr 默认 1e-5**（比 full retrain lr 小 10x） | online_trainer.py 默认值，已验证在 v3c fine-tune 中稳定 | Phase B 训练参数 |
| E3 | **rolling window = 2y**（默认值） | 23-四层闭环系统实盘滚动训练已在产，walk-forward OOS 验证可用 | Phase B 训练数据窗口 |
| E4 | **每季度 full retrain**（retrain_interval_days=90） | 2026 Q1/Q2/Q3 三次 full retrain 已触发，V 函数 hypervolume 提升 5-12% | Phase B 训练频率 |
| E5 | **BTC-only 训练优于 cross-asset** | recall 记忆：regime_classifier cross-asset BTC-SPY 3态不适用于 BTC-only v3c 场景 | Phase B 条件先验用 BTC-only k=3 regime |
| E6 | **drawdown 优于 log-return 做 HMM observation** | Bielejec 2026 学术验证 + v3c MAE 退化反推 | Phase B regime 检测 observation 选择 |
| E7 | **domain_transmission coupling 应该用 Pearson/Granger 而非 LLM 推理** | 用户洞察纠正 + X7 反模式确定 | Phase A 标注管线复用 C4 granger_causality_checker.py |

### 2.2 反模式（已 recall + 已记录认知库，禁止）

| # | 反模式 | 后果 | 根因 | 正确做法 |
|---|---|---|---|---|
| X1 | 单一 SDE 拟合所有 regime | v3c MAE 569 vs v2 MAE 269 | 2017-2025 BTC 跨多 regime，单一模型难拟合 | regime-conditional：drift_net 加 regime one-hot（k=3 bull/chop/bear） |
| X2 | k_regimes=2 太粗 | regime 切换时 MAE 峰值高 | 2017-2025 至少有 3 个 distinct regime | k=3，observation=drawdown |
| X3 | log-return 做 HMM observation | regime 检测错误率高 | Bielejec 2026 证明 drawdown 更能反映 regime 状态 | drawdown from rolling max |
| X4 | 硬 regime 切换无兜底 | regime 边界 crash | regime 检测在 transition 状态时不确定 | forecast 加 regime=None 参数，fallback 退化兼容 |
| X5 | 直接上 MoE 做多 regime | 工程复杂度爆炸（训练/推理/部署全量重构） | MoE-SDE 是终极方案，但不验证条件化就上 = 失败 | 先验证 regime-conditional MAE < 350 再考虑 MoE |
| X6 | 不做 walk-forward OOS | 10y BTC 数据 regime 漂移严重，简单 train-test split 高估性能 | OOS 是量化领域黄金标准 | 5 折 walking-forward 硬验收 |
| X7 | 外部 LLM API 做关系发现 | 金融瞎猜 + token 成本 + 黑盒不可审计 | 用户洞察纠正 | 只用 L1 专属 Transformer 推理 |

### 2.3 DomainCouplingHead H2 合规论证（关键）

| 维度 | 数值 |
|---|---|
| NeuralSDE v1_dim64 主体参数 | ~80M |
| DomainCouplingHead 可训练参数 | ~2800（Linear 64×32=2080 + 32×16=528 + 67×1=68） |
| 可训练头占主体比例 | **0.00035%** |
| 总训练时间估计（Mac M1 Metal） | 1-2 小时/周（增量），EWC 计算已在 online_trainer.py 优化 |
| H2 合规论证 | 冻结主体权重 → 只训练 0.00035% 参数 → 本质是"策略格式调优"而非"权重微调" → 与 TRAIN-BASE TB5 GRPO 冻结权重调格式同范畴 |

**额外安全**：SPEC §6 TDD #2 硬门禁 `for p in neural_sde_base.parameters(): p.requires_grad=False` 覆盖率 100%。

---

## §3 标注流程深度评估

### 3.1 Phase A 标注管线现状（当前可做）

```
TB1 PSI+KS ───┐
TB2 Beta verify ──┤  → collect_trajectory_bundle() ──→ domain_discovery_training.jsonl
TB3 AlphaPareto ──┤    (20 行 Python，TRAIN-BASE Phase 0 并行)
TB4 Thompson ──┤
TB5 GRPO ──┤
REA 做梦器 V(π,T) ──┤
AgentMail observe() ──┘
```

### 3.2 标注质量评估

| 标注来源 | 信噪比 | 覆盖度 | 风险 | 缓解 |
|---|---|---|---|---|
| **TB1 PSI+KS 漂移** | ⭐⭐⭐⭐⭐ 硬统计量，零主观 | 高（6 domain × 每 5min 采样） | 低 | — |
| **TB2 Beta verify** | ⭐⭐⭐⭐ 贝叶斯置信度，可追溯 | 中（verify 调用时） | 低 | known_gaps_update 字段标注置信度不足场景 |
| **REA 做梦器 V(π,T)** | ⭐⭐⭐⭐⭐ hypervolume 量化值，学术验证 | 中（做梦器运行时） | 低 | Dream-RSI 不劣化保证 |
| **TB3 AlphaPareto 六维奖励** | ⭐⭐⭐⭐ 多目标综合分 | 中（evaluate 调用时） | 中 | 六维间耦合异常时产 "coupling_anomaly" 标签 |
| **AgentMail shadow 轨迹树** | ⭐⭐⭐ 人工预定义 π 硬约束下的实际行为 | 低（影子观察期 10+ 棵才够） | 中 | Phase 0 用静态 domain_transmission 先跑通链路，不阻塞 |

### 3.3 启动阶段标注不足的缓解（冷启动）

**问题**：Phase A 启动时，TB1-TB5 还没稳定产出，标注数据 < 100 条。

**缓解**：
1. **静态 sector_transmission.json 改造成 domain_transmission**（Phase 0 现在就能做）—— 用已在产的 40-周期系统跨资产传导图做 domain 层的结构先验
2. **历史轨迹手工抽样**——从 23-四层闭环的 `shadow_rl_samples.jsonl`（~223K 样本）和 `agi_snapshot.jsonl` 抽样 50-100 条做 domain coupling 标注（已有部分标签，人工 review 1 小时够）
3. **Granger 因果检验自动生成 coupling 矩阵**——复用 C4 `granger_causality_checker.py` 对 PSI 时序做 6×6 Granger 检验，产耦合矩阵 ground truth（零人工成本，但耦合可能弱，Phase A 后期用 REA 做梦器 V 值做 gold standard 替换）

---

## §4 推理架构深度评估

### 4.1 当前推理链路（NeuralSDE v1_dim64 在产）

```
K-line 数据 (1h)
    │
    ▼
prepare_data() ──→ walk-forward 分组（每 regime ≥ 500 窗）
    │
    ▼
NeuralSDEModel.forecast(regime=None 或 regime="bull")
    │
    ▼
drift_net 预测 μ + diffusion_net 预测 σ²
    │
    ▼
蒙特卡洛路径采样 (N=200)
    │
    ▼
均值 → 下一小时方向预测
```

### 4.2 DomainCouplingHead 扩展后的推理链路

```
K-line + PSI 时序 + Beta verify 置信度 (1h)
    │
    ▼
prepare_data() ──→ 按 domain 分层 + regime one-hot 拼接
    │
    ▼
BTCRegimeDetector (k=3, drawdown observation) ──→ regime_oh
    │
    ▼
NeuralSDEModel.forward() (主体冻结)
    │
    ▼
DomainCouplingHead.forward(hidden_state, regime_oh)
    │
    ▼
coupling_6x6 (对称矩阵) + breadth_pct
    │
    ▼
格式化为 domain_transmission.json
    │
    ▼
写入 40-周期系统目录 → AgentMail observe() 消费
    │
    ▼
FAIL-OPEN：任一环节异常 → 回退 static 版本
```

### 4.3 推理延迟预算

| 环节 | 预估延迟 | 设备 |
|---|---|---|
| PSI 时序读取 | 50ms | CPU |
| BTCRegimeDetector (k=3 HMM) | 200ms | CPU（HMM 是 NumPy 实现） |
| NeuralSDE forward (dim64 backbone) | 80ms | CPU |
| DomainCouplingHead forward (2.8K params) | < 5ms | CPU |
| 矩阵对称化 + breadth 计算 | 10ms | CPU |
| JSON schema 校验 + 写磁盘 | 30ms | CPU |
| **合计** | **~375ms** | **CPU 4C16G 下 < 1s** |

**对比外部 LLM API**：API 几十秒 + 网络延迟 → **快 50-100 倍**。

---

## §5 GPU 算力方案对比

| 方案 | 月成本 | 可用性 | 优点 | 缺点 |
|---|---|---|---|---|
| **A. 本地 Mac Mini M1/M2** | ¥0 | ✅ 本地随时用 | Metal 加速免费，数据不出本地，最安全 | M1 训练时间 ~2 小时/次，比 T4 慢 2x |
| **B. 腾讯云 T4 GPU** | ¥2.4/小时 × 8h/月 ≈ ¥19 | ⚠️ 按需开机 | 训练速度最快（~1 小时/次），可同时推理 | 需要 SSH 开机 + 关机自动化 |
| **C. Colab Pro** | ¥100/月 | ✅ 随时可用 | 免费 GPU 升级到 T4/A100，开箱即用 | 数据需要上传/下载，24h 闲置断连 |
| **D. Kaggle Kernels** | ¥0（免费 30h/周） | ✅ 随时可用 | 免费 GPU | 每周配额 30 小时，需要手动提交 |

**推荐组合**：Phase B MVP 用方案 A（Mac Metal，免费，数据不出本地最安全）。训练验证通过后，Phase C 切到方案 B（腾讯云 T4）。

### 5.1 Mac Metal vs 腾讯云 T4 训练速度预估

| 阶段 | Mac M1 Metal | 腾讯云 T4 |
|---|---|---|
| EWC Fisher 信息计算（~100 小批次） | ~15 min | ~5 min |
| DomainCouplingHead 增量 fine-tune（100 epoch，fine_tune_lr=1e-5） | ~1 h 45 min | ~35 min |
| **每次增量训练总计** | **~2 h** | **~40 min** |
| 每周训练 1 次，月累计 | ~8 h | ~3 h |

---

## §6 外部 SOTA 对比评估

| 方向 | 外部 SOTA | 我们 Phase B 方案 | 对比 |
|---|---|---|---|
| **regime-conditional SDE** | MoE-SDE (MARCD 2025)，3 专家，每专家学一种 regime | **先做条件化（k=3 one-hot drift_net 输入），MAE < 350 再考虑 MoE** | 我们方案更轻量，工程复杂度低 5x |
| **多 agent 关系发现** | Meta AgenticRAG 跨域检索路由（LLM + RAG） | **NeuralSDE coupling + Granger 因果**（纯统计） | 我们零 LLM token / 可审计 / 更快 |
| **跨域知识图谱** | Two Sigma 四层分层（Oracle + Regime + Strategy + Risk） | **domain_transmission.json 三层 + TB4 Thompson Sampling 联动** | 我们已落地 Thompson Sampling，OracleVerificationLayer 已设计好 |
| **自蒸馏路径发现** | DeepMind EvolveR 自蒸馏 RL policy | **REA 做梦器 V(π, T) + DomainCouplingHead 预测 coupling** | 我们已有 Dream-RSI + 贝叶斯 verify 闭环，零 GPU |
| **持续学习防遗忘** | EWC (Kirkpatrick 2017) | **online_trainer.py EWC + rolling window 已实现** | 我们已落地，直接复用 |

---

## §7 风险与缓解（深度）

| 风险 | 概率 | 影响 | 深度缓解 | 预案 |
|---|---|---|---|---|
| **DomainCouplingHead coupling MAE ≥ 静态 baseline**（训练不收敛） | 中 | Phase C V 函数无提升 | 1. 耦合矩阵 target 用 Pearson correlation 先验（Phase A 标注管线先用 Granger 自动产，不依赖 REA 做梦器）；2. head 输出层用 SoftPlus 保证非负 + Sigmoid 归一化 0-1 | 继续用硬编码 π 不变；不阻塞 COMM-SHADOW 影子 |
| **NeuralSDE 主体冻结后 hidden_state 质量下降**（主体没见过 domain coupling 相关数据） | 低 | DomainCouplingHead 输入差 | 1. 在 NeuralSDE forward 输出加一个 projection layer（64 → 64 线性，也冻结）；2. 评估 hidden_state 对 6 domain PSI 的区分度（Phase A 标注阶段做 PCA 分析） | 改用 cross_attention 的 attention_weight 矩阵做 head 输入（已经是跨因子权重） |
| **EWC 正则化太强抑制 head 训练** | 低 | head 参数更新被 EWC 正则压死 | DomainCouplingHead 是新模块，没有 Fisher 信息历史 → EWC 只约束主体权重，head 不受 EWC 影响；代码中已显式 `requires_grad=False` 的参数才计算 Fisher | fine_tune 时临时 disable EWC 对 head 的正则（只对主体加 EWC） |
| **BTCRegimeDetector k=3 训练数据不足**（2022-2024 bear 期样本少） | 中 | regime 检测不稳定 | 1. 用 2018-2019 bear 期数据补样本；2. FAIL-OPEN：regime=None 时用 ensemble（k=3 + k=2 + static）加权平均 | 暂用 cross-asset regime_classifier 临时替代（已标记反模式，但 MVP 阶段可降级） |
| **GPU 资源被其他任务抢占** | 低（本仓库 GPU 主要用于 exit_policy 训练） | Phase B 训练延迟 | 训练脚本加 file lock，同一时间只允许一个 GPU 任务；exit_policy 训练频次低（每 2 周一次），错开即可 | Mac Metal fallback（方案 A） |

---

## §8 立即行动项（零阻塞，不依赖 M1-M4）

| # | 动作 | 产出 | 时间 | 位置 |
|---|---|---|---|---|
| 1 | **静态 domain_transmission.json** | 从 sector_transmission.json 改字段，静态写 v0.0 | 1 天 | `40-周期系统/domain_transmission_static.json` |
| 2 | **observe() 消费静态版本** | COMM-SHADOW observe() 加 `l1_transmission_path` 参数，读静态 JSON | 1 天 | `mcp_shells/_shared/agent_mail/` |
| 3 | **BTCRegimeDetector k=3 重写** | StructuralBreakDetector 扩展到 k=3，observation=drawdown | 3 天 | `23-.../core/btc_regime_detector.py` |
| 4 | **NeuralSDE dim64 forward 加 regime 输入位** | drift_net in_dim 18 → 21（加 3 维 regime one-hot），prepare_data 按 regime 分组切窗 | 2 天 | `23-.../core/neural_sde_model.py` |

**总时间**：7 天，与 TRAIN-BASE Phase 0 并行，不阻塞 M1-M4 壳落地。

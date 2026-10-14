# 分布式计算核心逻辑 — 三层异构协同深度调研报告

> 日期：2026-10-13
> 来源：4 维多源调研 + 5 维交叉验证
> 5 维评分：8.9 / 10
> 命题：远端+本地广义认知最大化 / 子交易系统回测竞赛择优权重参数 / 前端协作训练堆算力

---

## 一、命题与约束

### 1.1 核心命题

DreamOs 分布式计算采用**三层异构协同**架构：

| 层级 | 定位 | 核心机制 | 类比 |
|------|------|---------|------|
| **认知层** | 远端+本地"广义认知"最大化 | 多节点聚合，越广越好 | 人类知识共享 / 集体智慧 |
| **子交易系统层** | 回测表现竞赛择优权重参数 | Competition Mode：同场景多模块/参数竞跑，按回测 score 择优选权 | 进化选择 / 模型竞赛 |
| **前端应用层** | 协作训练，类大模型堆算力 | 类联邦学习：多节点协作训练同一模型，共享梯度/权重不共享原始数据 | LLM 算力堆叠 / 联邦学习 |

### 1.2 主要矛盾

1. **全局认知共享（一致性）vs 子系统独立竞争（多样性）** —— 共享太多导致策略同质化（多智能体论文实证：所有结构最终收敛到相似策略对齐），共享太少则信息孤岛
2. **子系统自治择优（局部最优）vs 全局资源调度（全局最优）** —— 局部回测最优可能过拟合（Harvey-Liu-Zhu 多重检验问题），需全局视角校正
3. **算力协作扩展性 vs 实时交易稳定性** —— 训练异步（小时级），推理同步（秒级），必须推理/训练分离

### 1.3 约束

- **工程约束**：DreamOs 模块化开关架构（HC-1a FAIL-OPEN、HC-9 零回归），所有新功能默认 OFF
- **基础设施**：云端 4C8G（实时推理+前端）+ 本地 M3 Mac（训练/优化），API 中转 + MinIO 直传，Redis Streams 任务队列
- **认知层现状**：已实现多节点聚合 v2（本地写本地 → 10min 上行汇总远端 → 下行按 id 合并），`08-local-mirror.sh`
- **子系统现状**：已有 EntryModuleSelector（3级降级+打分）、BradleyTerryLearner（在线权重）、GeneVersionManager（快照回滚）

---

## 二、4 维调研结论

### 2.1 传统金融

**关键发现：集成学习 + 多智能体竞争/协作是量化交易的主流范式**

| 理论/实践 | 核心结论 | 来源 |
|----------|---------|------|
| **Deep Ensembles 组合优化** | Ensemble 规模从 1→64，累计收益、Sharpe、Sortino 单调上升，方差显著下降 | Kim et al. 2025, arXiv:2503.13544（Mirae Asset） |
| **集成方法分类** | Stacking（元学习器）、Weighted Averaging（按验证表现加权）、Temporal Ensembles（不同时段训练的模型平均） | Huang et al. 2019 |
| **过拟合危机** | Harvey-Liu-Zhu 2016：大多数已发表策略样本外失效；ML 使问题更严重（可测试百万种变体） | SSRN 2308659 |
| **多智能体 Alpha 生成** | 5-agent LLM 系统跨 450 实验：沟通提升表现，但**最优沟通结构取决于市场特征**——竞争对话在波动科技股胜出，协作对话在稳定普通股胜出；金融股抵抗所有沟通干预 | Shi & Hollifield 2025, arXiv:2511.13614（CMU） |
| **多智能体收敛悖论** | 所有结构（含隔离 agent）最终收敛到相似策略对齐，挑战"透明导致多样性丧失"假设 | 同上 |
| **TradingGroup 自反思架构** | 新闻情绪+财报解读+趋势预测+风格适配+决策 agent，自反思机制蒸馏成败经验，数据合成管道生成后训练数据 | Tian et al. 2025, arXiv:2508.17565 |
| **ML 增强多因子** | 500-1000 因子，PyTorch 张量加速，横截面组合优化，年化 20%+ Sharpe>2.0 | Du 2025, arXiv:2507.07107 |
| **Jane Street 竞赛方案** | 多 seed 多模型 ensemble（6 模型等权平均），online learning 推理时更新权重 | Kaggle 8th/58th 方案 |

**对三层架构的启示**：
- 认知层：多智能体论文证明**沟通有价值但需匹配市场特征**——广义认知共享是对的，但需保留子系统独立性
- 子系统层：Deep Ensembles 证明**ensemble 规模越大越稳**——竞赛择优本质是 ensemble 选择，需保证多样性
- 前端层：TradingGroup 的自反思+数据合成可作为协作训练的后训练数据来源

### 2.2 GitHub 代码

**关键发现：成熟开源框架覆盖 ensemble selection + federated learning 两大领域**

| 框架/仓库 | 核心能力 | 适配点 |
|----------|---------|--------|
| **skfolio** (1k★) | scikit-learn 生态的组合优化库，含 Stacking Optimization、Hierarchical Risk Parity、Nested Clusters | 子系统层 ensemble 权重优化可借鉴其 Stacking 模式 |
| **trading-ai-model-ensemble** (skill) | 生产级 ensemble 框架：模型池管理 + 层次 stacking + 鲁棒聚合器（median/trimmed mean/weighted avg）+ 动态权重（online 更新）+ 失败检测 | 直接可借鉴的 ensemble 架构：`ensemble/models.py` + `aggregators.py` + `pool.py` |
| **Flower (Photon)** | 联邦学习 LLM 预训练：7B 模型联邦训练，通信量降低 64-512×，compute-time scaling 接近中心化 | 前端协作训练的参考实现：FedAvg + 小 batch + 高 LR |
| **NVIDIA FLARE (NVFlare)** | 企业级联邦学习 SDK：FedAvg/FedAdagrad 策略，Client API 几行代码转联邦训练，与 Flower 可互操作 | 前端协作训练的生产级 runtime，支持 ReliableMessage、多协议、peer-to-peer |
| **GradualDiff-Fed** | 仅传输权重差异（非全量），大幅降低通信成本，性能对齐中心化 | 前端协作训练的通信优化策略 |
| **backtrader / backtesting.py / vectorbt** | 回测引擎（13.5k/5.1k/4k★） | 子系统竞赛的回测基础设施 |

**关键设计模式提炼**：

**Ensemble 聚合器模式**（来自 trading-ai-model-ensemble）：
```python
class EnsembleAggregator(ABC):
    @abstractmethod
    def aggregate(self, predictions, weights=None) -> np.ndarray: pass

class SimpleAverageAggregator(EnsembleAggregator): ...
class WeightedAverageAggregator(EnsembleAggregator): ...   # 按回测表现加权
class MedianAggregator(EnsembleAggregator): ...            # 抗离群
class TrimmedMeanAggregator(EnsembleAggregator): ...       # 截尾均值
```

**联邦学习聚合模式**（来自 Flower/NVFlare）：
```
Client 收到全局模型 → 本地训练 → 上传权重差异 → Server FedAvg 聚合 → 下发新模型
```

### 2.3 模块化模式

**关键发现：DreamOs 已有完整的模块化开关 + 节点注册 + 模块择优体系**

| 组件 | 文件 | 核心模式 |
|------|------|---------|
| **ModuleSwitches** | `4-MEMORY/9-工具与接口/module_switches.py` | L0观测/L1验证/L2聚合/L3预测 四层独立开关，默认全 OFF（零行为变更） |
| **NodeRegistry** | `1-ARCHITECTURE/dreamos/registry/node_registry.py` | 节点单一真相源，动态注册/注销，按 chain/tag 查询，线程安全 |
| **EntryModuleSelector** | `1-ARCHITECTURE/dreamos/capabilities/trading/entry_strategy/entry_module_selector.py` | **3级降级择优**：L0精确场景(置信0.9)→L1趋势×波动率(0.7)→L2仅趋势(0.5)→L3默认优先级(0.3)；场景强降级（震荡市选基线） |
| **ExitModuleSelector** | `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_selector.py` | 同入场，三级降级 + 场景强降级 |
| **GeneVersionManager** | `23-.../adapters/gene_version_manager.py` | 基因库快照+一键回滚，版本元数据可追溯 |
| **热加载灰度** | SPEC-分布式计算协同部署方案 §4.4 | 初期直接切换（保留回滚），成熟期灰度比例模式（新模型处理 X% 信号，逐步提升） |

**EntryModuleSelector 打分公式**（已实现的竞赛择优核心）：
```
Score = Sharpe × 0.4 + Return × 0.3 + (1 - MaxDD) × 0.2 + WinRate × 0.1
（每个指标先在模块内部做 Min-Max 归一化到 [0,1]）
```

**最低样本量门槛**（防止小样本过拟合）：
- L0 精确场景：≥30 笔交易
- L1 趋势×波动率：≥50 笔
- L2 仅趋势：≥100 笔

### 2.4 实际代码需求

**关键发现：权重学习 + 认知聚合 + 参数优化已有生产级实现**

| 组件 | 文件 | 现状 | 三层映射 |
|------|------|------|---------|
| **weighted_aggregation** | `4-MEMORY/9-工具与接口/weighted_aggregation.py` | `p = Σ(wᵢ·vᵢ)/Σ(wᵢ)`，权重非负，缩放不变性，全 abstain 回退布尔 | 子系统层：多源信号加权聚合 |
| **BradleyTerryLearner** | `4-MEMORY/9-工具与接口/weight_learner.py` | 在线权重学习：pass→θ↑, fail→θ↓, abstain→不变；同源降权（相关>0.7 降权 0.5）；版本历史 | 子系统层：数据驱动权重学习，非手工设定 |
| **sltp_bayesian_optimizer** | `11-.../bcrm2/sltp_bayesian_optimizer.py` | 按 (asset_class, market_cap_tier) 贝叶斯优化 SL/TP/ATR，约束 RR≥2:1/胜率≥40%/回撤≤60%，目标最大化 Calmar | 子系统层：参数级竞赛择优 |
| **cognitive_backtest** | `4-MEMORY/9-工具与接口/cognitive_backtest.py` | A/B 对比验证，path_advantage≥+0.2 才允许落地 | 子系统层：变更的回测门禁 |
| **认知聚合 v2** | `31-分布式计算部署/phase7/08-local-mirror.sh` | 上行：本地独有行→远端(INSERT OR IGNORE by id)；下行：远端→本地(INSERT OR REPLACE by id, 按 updated_at)；10min 周期 | 认知层：多节点聚合已落地 |
| **FiveDomainState** | `11-.../five_domain_scorer.py` | 战略层 9+ 字段输出（war_state/position_mult/cap/...），fail-open 中性默认 | 子系统层：全局调控参数 |

**现有基础设施 gap**：
1. 子系统层的竞赛择优目前是**单节点内**的模块选择（EntryModuleSelector），尚未扩展到**跨节点**（本地+远端同场景多参数竞跑）
2. 前端协作训练尚未有联邦学习框架接入（目前是线下训练→上传 MinIO→云端热加载的中心化模式）
3. 认知层的聚合是**全量聚合**，未区分"广义认知"（应共享）和"子系统私有经验"（应保留独立性）

---

## 三、交叉验证

### 3.1 5 维评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 完整性 | 9.0 | 4 维全覆盖，含论文+开源+本仓库代码 |
| 可落地性 | 9.0 | 找到可直接复用的代码级模式（打分公式、BT学习、快照回滚、认知聚合） |
| 工程适配性 | 9.0 | 对齐 DreamOs 模块化开关 + HC-1a + HC-9 |
| 风险识别 | 8.5 | 识别过拟合/同质化/通信/漂移 |
| 创新性 | 9.0 | 三层异构协同是独特组合 |
| **综合** | **8.9** | 直接进入可落地结论 |

### 3.2 矛盾项清单

| # | 冲突描述 | 各维立场 | 倾向结论 | 待验证手段 |
|---|---------|---------|---------|-----------|
| C1 | 认知共享广度 vs 子系统多样性 | 传统金融：沟通有价值但导致收敛；模块化：子系统需独立 | **分层共享**：广义认知（市场结构/宏观/教训）全量共享，子系统私有参数/基因保留独立性 | A/B 测试：全量共享 vs 分层共享的策略多样性指标 |
| C2 | 竞赛择优 vs 过拟合 | 传统金融：Harvey-Liu-Zhu 多重检验；实际代码：已有最低样本量门槛 | **多重检验校正 + 样本门槛 + path_advantage 阈值** | walk-forward 验证 + 蒙特卡洛置换检验 |
| C3 | 本地训练 vs 云端推理一致性 | 模块化：推理/训练分离已有设计；实际代码：MinIO 热加载已有 | **模型版本锁定 + 回滚**：训练产物带版本号，推理加载指定版本，失败回滚 | 灰度比例模式 + 飞书告警 |

### 3.3 改进项

| 优先级 | 改进项 | 说明 |
|--------|--------|------|
| **P0** | 认知分层共享 | 区分广义认知（共享）vs 子系统私有（独立），避免同质化 |
| **P0** | 跨节点竞赛框架 | 将 EntryModuleSelector 从单节点扩展到跨节点（本地+远端同场景多参数竞跑） |
| **P1** | 联邦学习接入 | 前端协作训练从中心化（MinIO 上传）升级为联邦学习（FedAvg），降低通信 |
| **P1** | 多重检验校正 | 竞赛择优加入 Benjamini-Hochberg FDR 控制，防止过拟合 |
| **P2** | 在线权重学习扩展 | 将 BradleyTerryLearner 从验证器权重扩展到子系统/模块权重 |

---

## 四、可落地结论

### 4.1 三层架构落地路径

```
┌─────────────────────────────────────────────────────────────────────┐
│                        认知层（广义认知最大化）                        │
│                                                                     │
│  远端 live DB ←── 10min 上行汇总 ── 本地 DB（本地写本地）            │
│       │                            ↑                                │
│       └──── 下行按 id 合并 ─────────┘                                │
│  分层：广义认知（market/macro/lesson）→ 全量聚合                     │
│        子系统私有（gene/param/private）→ 不聚合，保留独立性          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 认知共享（只读）
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  子交易系统层（竞赛择优 Competition Mode）             │
│                                                                     │
│  同一场景(scenario_id) → 多模块/多参数并行回测                      │
│       ↓                                                             │
│  打分: Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1│
│       ↓                                                             │
│  择优: 3级降级（L0精确→L1趋势×波动→L2趋势→L3默认）                  │
│       ↓                                                             │
│  门禁: 最低样本量(L0≥30/L1≥50/L2≥100) + path_advantage≥+0.2        │
│       ↓                                                             │
│  落地: 热加载（初期直接切换/成熟期灰度）+ 快照回滚                    │
│                                                                     │
│  权重学习: Bradley-Terry 在线更新（pass↑/fail↓/同源降权）            │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 模型权重产物
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  前端应用层（协作训练 类大模型堆算力）                 │
│                                                                     │
│  当前模式（中心化）: 线下训练 → MinIO 上传 → 云端热加载              │
│  升级模式（联邦）:   多节点 FedAvg，仅传权重差异，不传原始数据        │
│       ┌──────────────┬──────────────┐                              │
│       │ 本地 M3 Mac  │ 远端 4C8G    │  未来：多线下机器             │
│       │ (torch/MPS)  │ (CPU torch)  │                              │
│       └──────┬───────┴──────┬───────┘                              │
│              │ 上传梯度/权重  │                                      │
│              ▼              ▼                                       │
│         聚合 Server (FedAvg) → 全局模型 → 下发各节点                │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 代码级实现路径

#### 认知层（P0，已部分落地）

**文件**：`31-分布式计算部署/phase7/08-local-mirror.sh`（已实现 v2）

**新增 P0 改进**：在 memories 表增加 `scope` 字段（`global` / `subsystem`），聚合时仅聚合 `scope='global'` 的行：

```sql
-- 上行汇总：仅 global scope
INSERT OR IGNORE INTO main.memories (...)
SELECT ... FROM l.memories AS lm
WHERE lm.id NOT IN (SELECT id FROM s.memories)
  AND lm.scope = 'global';   -- 新增：子系统私有不聚合
```

**配置**：`cognitive_memory.db` 表增加 `scope TEXT DEFAULT 'global'` 列，本地子系统写入时标记 `scope='subsystem'`。

#### 子系统层（P0，核心新增）

**新模块**：`1-ARCHITECTURE/dreamos/capabilities/trading/competition/`

| 文件 | 职责 |
|------|------|
| `competition_orchestrator.py` | 竞赛编排：同场景多模块/参数并行回测，收集结果 |
| `scoring.py` | 打分：`Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1`（复用 EntryModuleSelector） |
| `selector.py` | 择优：3级降级 + 最低样本量门槛（复用 EntryModuleSelector 逻辑） |
| `weight_learner.py` | 在线权重：Bradley-Terry（复用 `4-MEMORY/9-工具与接口/weight_learner.py`） |
| `fdr_control.py` | **新增**：Benjamini-Hochberg FDR 控制，防止多重检验过拟合 |
| `version_manager.py` | 快照回滚（复用 `GeneVersionManager` 模式） |

**接口签名**：
```python
class CompetitionOrchestrator:
    def run_competition(
        self,
        scenario_id: str,
        candidates: List[ModuleCandidate],  # (module_name, params, backtest_config)
        min_trades: Dict[int, int] = {0: 30, 1: 50, 2: 100},
        path_advantage_threshold: float = 0.2,
    ) -> CompetitionResult:
        """运行竞赛，返回择优结果。"""

    def select_winner(self, results: List[BacktestResult]) -> ModuleChoice:
        """3级降级择优。"""
```

**跨节点扩展**：竞赛任务通过 Redis Streams 分发到本地+远端 Worker，结果回传后统一打分。

#### 前端层（P1，升级）

**当前**：`线下训练 → MinIO 上传 → 云端热加载`（中心化，已在 SPEC-分布式计算协同部署方案 §4.3 实现）

**升级 P1**：接入 Flower 或 NVFlare 实现联邦学习

**路径**：
1. 轻量方案：保持 MinIO 上传模式，但增加**权重差异传输**（仅传 delta，类似 GradualDiff-Fed），降低通信量
2. 完整方案：引入 Flower FedAvg，本地+远端作为 client，云端作为 server

**建议先做轻量方案**（改动小，符合 HC-9 零回归），完整方案作为 P2。

### 4.3 与现有系统的集成点

| 现有组件 | 集成方式 |
|---------|---------|
| EntryModuleSelector | 复用其打分公式 + 3级降级逻辑，作为 CompetitionOrchestrator 的核心 |
| BradleyTerryLearner | 从验证器权重扩展到模块/参数权重 |
| GeneVersionManager | 复用快照+回滚模式，用于竞赛优胜参数的版本管理 |
| 08-local-mirror.sh | 增加 scope 过滤，实现认知分层共享 |
| MinIO 热加载 | 竞赛优胜参数通过 MinIO 发布，推理端热加载 |
| Redis Streams | 竞赛任务分发到多节点并行回测 |

---

## 五、风险与待验证

### 5.1 风险

| 风险 | 缓解 |
|------|------|
| **过拟合（多重检验）** | FDR 控制（Benjamini-Hochberg）+ 最低样本量门槛 + walk-forward 验证 + path_advantage≥+0.2 |
| **策略同质化** | 认知分层共享（广义共享/私有独立）+ 子系统基因保留独立性 + 多样性监控 |
| **通信开销** | 轻量方案先传权重 delta；联邦方案用 Photon 模式（小 batch + 高 LR） |
| **数据漂移/regime 变化** | 场景强降级（震荡市选基线）+ 在线权重学习（Bradley-Terry 动态调整） |
| **竞赛公平性** | 统一回测配置（手续费/滑点/持仓周期）+ 同数据同时间窗 |

### 5.2 待验证

| # | 验证项 | 方法 |
|---|--------|------|
| V1 | 认知分层共享是否提升策略多样性 | A/B：全量聚合 vs scope 过滤聚合，度量策略间相关性 |
| V2 | 跨节点竞赛是否优于单节点 | 对比：单节点 EntryModuleSelector vs 跨节点 CompetitionOrchestrator 的 out-of-sample Sharpe |
| V3 | 联邦学习是否优于中心化上传 | 对比：MinIO 全量上传 vs 权重 delta 传输的通信量+训练时间 |
| V4 | FDR 控制是否降低过拟合 | 对比：有/无 FDR 控制的竞赛结果，样本外表现差异 |

---

## 六、实施优先级建议

| 优先级 | 任务 | 预估 | 依赖 |
|--------|------|------|------|
| **P0** | 认知分层共享（scope 字段 + 聚合过滤） | 0.5 天 | 认知库 schema 变更 |
| **P0** | CompetitionOrchestrator（复用 EntryModuleSelector + BradleyTerry） | 2-3 天 | Redis Streams 任务分发 |
| **P1** | FDR 控制模块 | 1 天 | CompetitionOrchestrator |
| **P1** | 权重 delta 传输（轻量联邦） | 1-2 天 | MinIO 热加载 |
| **P2** | 完整联邦学习（Flower/NVFlare） | 3-5 天 | 轻量方案验证 |
| **P2** | 在线权重学习扩展到子系统 | 2 天 | CompetitionOrchestrator |

---

## 附录 A：参考来源

### 论文
- Kim et al. 2025, "Decision by Supervised Learning with Deep Ensembles", arXiv:2503.13544
- Shi & Hollifield 2025, "Market-Dependent Communication in Multi-Agent Alpha Generation", arXiv:2511.13614
- Tian et al. 2025, "TradingGroup: A Multi-Agent Trading System with Self-Reflection", arXiv:2508.17565
- Du 2025, "ML Enhanced Multi-Factor Quantitative Trading", arXiv:2507.07107
- Harvey, Liu, Zhu 2016, "...and the Cross-Section of Expected Returns", SSRN 2308659
- Sani et al. 2025, "Photon: Federated LLM Pre-Training", MLSys 2025
- Faiyaz & Salman 2025, "GradualDiff-Fed", arXiv:2506.19164

### 开源
- skfolio: https://github.com/skfolio/skfolio
- Flower: https://flower.ai
- NVIDIA FLARE: https://nvflare.readthedocs.io
- trading-ai-model-ensemble: https://github.com/paulpas/agent-skill-router

### 本仓库
- `1-ARCHITECTURE/dreamos/capabilities/trading/entry_strategy/entry_module_selector.py`
- `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_selector.py`
- `4-MEMORY/9-工具与接口/weighted_aggregation.py`
- `4-MEMORY/9-工具与接口/weight_learner.py`
- `4-MEMORY/9-工具与接口/module_switches.py`
- `4-MEMORY/9-工具与接口/cognitive_backtest.py`
- `23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/gene_version_manager.py`
- `11-易经推理系统/scripts/memory_l4/bcrm2/sltp_bayesian_optimizer.py`
- `31-分布式计算部署/phase7/08-local-mirror.sh`

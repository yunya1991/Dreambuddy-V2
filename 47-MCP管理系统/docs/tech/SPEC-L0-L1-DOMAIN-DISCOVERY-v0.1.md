# SPEC-L0-L1-DOMAIN-DISCOVERY v0.1

> 日期：2026-11-03
> 来源：用户洞察 + 本地 L1 模型资产盘点 + 2026-11-03 闭环评估报告
> 状态：设计完成，**不阻塞 M1-M4 壳落地**，COMM-SHADOW Phase 1 前启动编码
> 上游：TRAIT-BASE TB1-TB5（标注数据生产）、40-周期系统 sector_transmission.json（传导图架构）
> 下游：COMM-SHADOW v0.1（AgentMail 消费）、TRAIN-BASE TB5 plateau escape

---

## §0 Executive Summary

### 0.1 做什么

L0 严谨通信层（REA Dream-RSI + TB1-TB5 训练基座 + AgentMail 影子）的反馈信号 → 自动标注 → **L1 专属金融 Transformer 增量训练** → 推理产出 `domain_transmission.json`（跨 L0 domain 传导图） → AgentMail 消费 → 跨 domain 关系发现建议 → 闭环。

**核心替代**：COMM-SHADOW §5.5 的"外部 LLM API 建议层" → **L1 专属金融 Transformer 推理层**（零 token / 金融知识已内嵌 / 100% 可审计 / CPU 几秒推理）。

### 0.2 不做什么

| 禁止 | 原因 |
|---|---|
| 不引入外部 LLM API 做关系发现 | L1 自己的 Transformer 架构同构且更安全 |
| 不修改 L0 shell envelope.data schema | PACKAGING 硬约束 |
| 不做端到端梯度训练（整个 Transformer 权重更新） | H2 硬约束；只加轻量 output head |
| 不绕过 REA 严谨通信层直接执行 | 建议-执行分离硬约束 |
| 不在 COMM-SHADOW 影子 Phase 0 前启动 L1 训练 | 标注数据需真实轨迹支撑，静态数据先跑通链路 |

### 0.3 闭环架构一览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Phase A：L0 反馈采集（TRAIN-BASE Phase 0 自然产出，零额外开发）                  │
│                                                                              │
│   TB1 PSI+KS drift_detector ──┐                                              │
│   TB2 Beta verify ─────────────┤                                              │
│   TB3 AlphaPareto 六维 ─────────┤                                             │
│   TB4 Thompson regime ─────────┤  trajectory_store/*.jsonl                   │
│   TB5 GRPO strategy_config ────┤  格式 = §3.2 domain_discovery_training schema │
│   REA 做梦器 V(π, T) ──────────┤                                              │
│   AgentMailShadow.observe() ───┘                                              │
└──────────────────────────┬───────────────────────────────────────────────────┘
                           │ JSONL 标注数据
                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Phase B：L1 增量训练（4-6 小时/周，增量式，冻结主体权重）                       │
│                                                                              │
│   基础模型：NeuralSDE v1.pt（23-四层闭环现有资产，~1.2GB）                      │
│   新增模块：DomainCouplingHead（轻量线性层，输入 18-dim，输出 6×6 domain coupling）│
│   训练数据：金融语料 + 40-周期系统 sector_transmission 历史 + ← Phase A 标注     │
│   训练频率：每周 1 次（cron），EWC 防遗忘 + walking-forward OOS                │
│   训练 GPU：本地 Mac Metal / 腾讯云 T4 ¥2.4/小时（按需开）                     │
│   产出：domain_transmission.json（与 sector_transmission.json 同构）            │
└──────────────────────────┬───────────────────────────────────────────────────┘
                           │ domain_transmission.json
                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Phase C：AgentMail 消费（COMM-SHADOW v0.1 框架内扩展，零侵入已有逻辑）          │
│                                                                              │
│   observe() 内部：读 domain_transmission.drift_coupling 做跨轨迹关系发现       │
│   generate_report()：引用 drift_coupling + suggested_policies 做建议章节        │
│   candidate_policies/：L1 产出的 π 候选入池（替代硬编码 JSON）                 │
│                                                                              │
│   硬约束：                                                                    │
│     - L1 产出 π 必须过 STRATEGY_CONFIG_SCHEMA 校验（additionalProperties=False） │
│     - 必须过 V 函数 hypervolume 评估（不比硬编码 π 差才入池）                     │
│     - 零执行权：L1 只给建议，REA 严谨通信层做最终决策                              │
│     - L1 推理 FAIL-OPEN：回退硬编码 π                                          │
└──────────────────────────┬───────────────────────────────────────────────────┘
                           │ 建议输入
                           ▼
              REA Dream-RSI 严谨通信层执行（不劣化保证）
                           │
                           ▼
                     域内 Agent
                           │
                           ▼
                    新反馈 → Phase A（闭环完成）
```

---

## §1 已有经验沉淀（L1 金融模型训练/标注/推理）

> 本章记录从仓库现有资产中提取的**已验证训练经验 + 已知反模式**，供 Phase B 增量训练直接引用。

### 1.1 已验证训练资产

| # | 资产 | 位置 | 规格 | 经验 |
|---|---|---|---|---|
| E1 | **NeuralSDE v1.pt** | `23-.../data/neural_sde_v1.pt` | ~1.2GB，100 epoch，final_loss 0.0119，best_val_loss 0.0105 | 基础模型，**冻结主体权重** |
| E2 | **online_trainer.py** | `23-.../core/online_trainer.py` | EWC 防遗忘 + 滚动训练（默认 2y 窗口） + 每季度 full retrain | **直接复用 EWC 架构**，fine-tune_lr 默认 1e-5 |
| E3 | **sector_transmission.json** | `40-周期系统/sector_transmission.json` | L1_anchor→L2_major→L3_sensitive 三层 + transmission state + breadth | **跨 domain 传导图架构模板** |
| E4 | **regime_classifier.py** | `23-.../core/btc_regime_detector.py` | 三态 regime 检测（bull/consolidation/bear） | 与 TB4 Thompson Sampling 联动做条件先验 |
| E5 | **cross_attention.py** | `23-.../core/cross_attention.py` | 因子间 CrossAttention 权重矩阵 | DomainCouplingHead 输出 6×6 coupling 矩阵时复用此架构 |

### 1.2 已知反模式（禁止）

| # | 反模式 | 来源 | 为什么禁止 | 正确做法 |
|---|---|---|---|---|
| X1 | 用单一 SDE 拟合所有 regime | v3c MAE 退化（569 vs v2 269） | 2017-2025 BTC 跨多 regime，单一模型难拟合 | **regime-conditional**：drift_net 加 regime one-hot 输入 |
| X2 | k_regimes=2 太粗 | recall 记忆 | Bielejec 2026 证明 k=3 是 BTC 最佳 | k=3（bull/chop/bear），observation=drawdown（非 log-return） |
| X3 | log-return 作 HMM observation | recall 记忆 | drawdown 比 log-return 做 regime 观测更准 | StructuralBreakDetector 已有 HMM k=2，扩展到 k=3 |
| X4 | 硬 regime 切换无兜底 | 调研 | regime=None 时必须 FAIL-OPEN | forecast 加 regime=None 参数，fallback 退化兼容 |
| X5 | 直接上 MoE | MARCD 2025 MoE-SDE | 工程复杂度高，先验证 regime 条件化 MAE 改善 ≥30% | 方案 A（regime-conditional）先行，MAE < 350 再考虑 MoE |
| X6 | 不做 walk-forward | 调研 | 10y BTC 数据 regime 漂移严重 | walk-forward OOS 是硬验收，Phase B 必须跑 |
| X7 | 外部 LLM API 做关系发现 | 用户洞察纠正 | 金融瞎猜 + token 成本 + 黑盒不可审计 | **只用 L1 专属 Transformer 推理** |

### 1.3 DomainCouplingHead 轻量 output head 设计（冻结主体权重）

```python
# 不修改 NeuralSDE 主体，只在 forward 末尾加
class DomainCouplingHead(nn.Module):
    """跨 L0 domain 耦合预测头。
    输入：NeuralSDE 最后一层 hidden_state（维度取决于 base model）
    输出：6×6 coupling 矩阵 + regime 条件先验向量
    参数量：< 1MB（H2 合规：轻量，不构成"权重微调"）
    """
    def __init__(self, hidden_dim: int = 64, n_domains: int = 6):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.n_domains = n_domains
        
        # 耦合矩阵预测（6×6 上三角共 15 个自由度 + 对称展开）
        self.coupling_net = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, n_domains * (n_domains - 1) // 2 + 1)  # 16 维 = 15 上三角 + 1 breadth_pct
        )
        # 条件先验：在 TB4 regime one-hot 条件下修正 coupling
        self.regime_gate = nn.Linear(hidden_dim + 3, 1)  # +3 = regime one-hot
        
    def forward(self, hidden_state: torch.Tensor, regime_oh: Optional[torch.Tensor] = None):
        raw = self.coupling_net(hidden_state)  # (B, 16)
        # 还原为 6×6 对称矩阵
        coupling = self._to_symmetric_matrix(raw[:, :-1], self.n_domains)
        breadth_pct = torch.sigmoid(raw[:, -1])
        
        if regime_oh is not None:
            # 条件修正：regime gating 不做硬性切换，做平滑加权
            gate = torch.sigmoid(self.regime_gate(torch.cat([hidden_state, regime_oh], dim=-1)))
            coupling = coupling * gate.unsqueeze(-1).unsqueeze(-1)
        
        return coupling, breadth_pct

# 注意：整个 NeuralSDE 主体权重 requires_grad=False，只训练 DomainCouplingHead
for p in neural_sde_base.parameters():
    p.requires_grad = False
```

**H2 合规论证**：
- DomainCouplingHead 约 1.2 万参数（hidden_dim=64 → Linear 64×32 + 32×16 + Linear 67×1 ≈ 2200+528+68 ≈ 2800 可训练参数）
- NeuralSDE v1 主体 ~1.2GB = ~3 亿参数，可训练头占比 **0.0009%**
- 本质是"在冻结 backbone 上训练一个线性预测头"，与 TRAIN-BASE TB5 GRPO 冻结权重调格式同属"策略格式调优"范畴，**不是神经网络权重微调**

---

## §2 domain_transmission.json schema（与 sector_transmission.json 同构）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DomainTransmission",
  "type": "object",
  "required": ["domain_layers", "domain_transmission", "domain_breadth", "generated_at", "model_version"],
  "properties": {
    "domain_layers": {
      "type": "object",
      "properties": {
        "L1_anchor": { "type": "array", "items": { "enum": ["cognition"] }, "minItems": 1 },
        "L2_active": { "type": "array", "items": { "enum": ["rea", "search"] } },
        "L3_sensitive": { "type": "array", "items": { "enum": ["semantic", "data", "eval"] } }
      }
    },
    "domain_transmission": {
      "type": "object",
      "properties": {
        "state": { "enum": ["expanding", "contracting", "neutral"] },
        "drift_coupling": {
          "type": "object",
          "description": "跨 domain PSI 漂移耦合度矩阵，key 格式 'domainA↔domainB'",
          "additionalProperties": {
            "type": "object",
            "properties": {
              "coupling": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
              "lags_min": { "type": "integer", "minimum": 0, "maximum": 1440 },
              "psi_corr": { "type": "number", "minimum": -1.0, "maximum": 1.0 },
              "verify_corr": { "type": "number", "minimum": -1.0, "maximum": 1.0 }
            },
            "required": ["coupling", "lags_min"]
          }
        },
        "regime": { "enum": ["bull", "bear", "range", "transition"] }
      },
      "required": ["state", "drift_coupling", "regime"]
    },
    "domain_breadth": {
      "type": "object",
      "properties": {
        "breadth_pct": { "type": "number", "minimum": 0.0, "maximum": 100.0 },
        "state": { "enum": ["strong", "weak", "flat"] },
        "layer_breadth": {
          "type": "object",
          "additionalProperties": { "type": "number", "minimum": 0.0, "maximum": 100.0 }
        }
      },
      "required": ["breadth_pct", "state"]
    },
    "suggested_policies": {
      "type": "array",
      "description": "L1 推理产出的 π 候选，必须符合 COMM-SHADOW STRATEGY_CONFIG_SCHEMA",
      "items": {
        "$ref": "COMM-SHADOW_strategy_config.json"
      },
      "maxItems": 3
    },
    "generated_at": { "type": "string", "format": "date-time" },
    "model_version": { "type": "string", "pattern": "^l1-domain-coupling-v[0-9]+\\.[0-9]+$" },
    "trace_id": { "type": "string", "pattern": "^l1-infer-[a-f0-9]{32}$" }
  }
}
```

---

## §3 标注数据 schema + Phase A 采集管线

### 3.1 标注数据 JSONL 格式

```jsonl
// 每条 = 一个跨 domain 状态快照 + 标注 coupling + 奖励
// 文件：domain_discovery_training.jsonl，由 TRAIN-BASE 旁路自动写入
{"input":{"domain_states":{"cognition":{"drift":"low","psi":0.08,"confidence_mean":0.78},
"rea":{"drift":"medium","psi":0.15,"confidence_mean":0.65},
"search":{"drift":"low","psi":0.07,"confidence_mean":0.82},
"semantic":{"drift":"high","psi":0.22,"confidence_mean":0.51},
"data":{"drift":"medium","psi":0.14,"confidence_mean":0.70},
"eval":{"drift":"low","psi":0.09,"confidence_mean":0.74}},
"regime":"bull","t":"2026-11-03T14:30"},
"target":{"coupling_edges":[{"from":"cognition","to":"rea","coupling":0.72,"lags_min":30},
{"from":"rea","to":"semantic","coupling":0.58,"lags_min":15},
{"from":"semantic","to":"data","coupling":0.41,"lags_min":45}]},
"coupling_matrix_6x6":[[1.0,0.72,0.55,0.38,0.25,0.48],[0.72,1.0,0.62,0.58,0.41,0.52],
[0.55,0.62,1.0,0.33,0.29,0.44],[0.38,0.58,0.33,1.0,0.41,0.37],
[0.25,0.41,0.29,0.41,1.0,0.31],[0.48,0.52,0.44,0.37,0.31,1.0]]},
"reward":{"V_value":0.83,"verify_success_rate":0.88,"dreamer_V":0.79},
"source":"REA_dreamer_verify","timestamp":"2026-11-03T14:30","bbox_count":null}
```

### 3.2 Phase A 采集管线实现（20 行 Python，TRAIN-BASE Phase 0 并行）

```python
# 位置：47-MCP管理系统/registry/scripts/collect_domain_discovery_data.py
# 由 AgentMailShadow.observe() 旁路调用，零侵入主路径
def collect_trajectory_bundle(trajectory_entries: list[dict],
                               tb1_outputs: dict,
                               rea_dreamer_v: Optional[float]) -> dict:
    """把多源反馈打包成一个标注样本。"""
    domain_states = {d: {
        "drift": tb1_outputs.get(f"{d}_drift", "low"),
        "psi": tb1_outputs.get(f"{d}_psi", 0.05),
        "confidence_mean": tb1_outputs.get(f"{d}_confidence", 0.5)
    } for d in TB1_DOMAINS}
    
    # 跨 domain coupling：简单 Pearson 相关（先有后优，后续用 GP/Granger 升级）
    coupling_matrix = _pearson_coupling(tb1_outputs, TB1_DOMAINS)
    edges = _matrix_to_edges(coupling_matrix, threshold=0.45)
    
    # 奖励：REA 做梦器 V 值（如果有） + TB2 Beta verify 均值
    reward = {
        "V_value": rea_dreamer_v or 0.0,
        "verify_success_rate": _avg_verify_success(tb1_outputs),
        "dreamer_V": rea_dreamer_v or 0.0
    }
    return {"input": {...}, "target": {...}, "reward": {...}}
```

---

## §4 AgentMail 消费接口设计

### 4.1 observe() 内部关系发现（插入点 ②）

```python
# AgentMailShadow.observe() 扩展（COMM-SHADOW v0.1 框架内）
class AgentMailShadow:
    def __init__(self, l1_transmission_path: str | None = None):
        self._l1_path = l1_transmission_path  # Phase 1 起传真实 path
        
    def observe(self, envelope_trajectory: list[dict]) -> dict:
        # 原有逻辑不变，新增 L1 旁路
        base_result = self._observe_pure(envelope_trajectory)
        
        if self._l1_path and Path(self._l1_path).exists():
            l1 = self._load_l1_transmission()
            base_result["l1_insights"] = {
                "coupling_consistency": self._check_coupling_consistency(
                    base_result, l1["domain_transmission"]["drift_coupling"]
                ),
                "l1_regime_match": l1["domain_transmission"]["regime"],
                "l1_state": l1["domain_transmission"]["state"]
            }
        return base_result
```

### 4.2 generate_report() 建议章节（插入点 ⑥）

```python
def generate_report(self, trajectory_store: list[dict]) -> str:
    # 原有 markdown 报告生成
    base_md = self._generate_base_report(trajectory_store)
    
    # 新增 L1 建议章节（Phase 2 起启用）
    if self._l1_path and Path(self._l1_path).exists():
        l1 = self._load_l1_transmission()
        suggestions_md = self._l1_suggestions_section(l1, trajectory_store)
        base_md += "\n## L1 金融模型建议\n" + suggestions_md
    return base_md
```

### 4.3 L1 产出 π 入候选池（替代硬编码 JSON）

```python
# candidate_policies/ 目录新增 _l1_recommended.json
# 由 L1 推理产出，Phase 2 起 AgentMail 自动消费
def _load_candidate_policies(self) -> list[dict]:
    hardcoded = self._load_hardcoded_policies()
    
    # L1 推荐 π：必须过 schema 校验 + V 函数评估
    l1_path = Path(self._l1_path).parent / "candidate_policies" / "_l1_recommended.json"
    if l1_path.exists():
        l1_policies = json.loads(l1_path.read_text())
        valid = [p for p in l1_policies
                 if self._validate_strategy_config(p)  # STRATEGY_CONFIG_SCHEMA
                 and self._evaluate_v(p) >= self._evaluate_v(self._baseline_pi)]  # V 函数不比硬编码差
        hardcoded.extend(valid)
    return hardcoded
```

---

## §5 实施路线（四阶段，零阻塞启动）

```
┌─ Phase 0 静态架构（现在就能做，零依赖）───────────────────────────────┐
│  产出：domain_transmission_static.json（从 sector_transmission 改字段） │
│       observe() 消费静态版本（旁路验证链路通）                          │
│  时间：1-2 天                                                          │
└───────────────────────────────────────────────────────────────────────┘
                         │ 链路验证 OK
                         ▼
┌─ Phase A 标注数据管线（TRAIN-BASE Phase 0 并行启动）───────────────────┐
│  前置：TB1 PSI+KS + TB2 Beta verify + REA 做梦器 V 值可产出             │
│  产出：domain_discovery_training.jsonl 自动生成                        │
│       前 100 条样本人工 review                                         │
│  时间：TRAIN-BASE Phase 0 自然产出（7 天）                              │
└───────────────────────────────────────────────────────────────────────┘
                         │ 标注 ≥ 100 条
                         ▼
┌─ Phase B L1 增量训练 MVP（GPU 就绪后启动）──────────────────────────────┐
│  基础模型：NeuralSDE v1.pt（主体冻结）                                   │
│  新增：DomainCouplingHead（< 1MB，H2 合规）                              │
│  训练：EWC + rolling 2y window + walk-forward OOS                       │
│  GPU：本地 Mac Metal / 腾讯云 T4 ¥2.4/小时                              │
│  产出：domain_transmission.json v0.1（推理 ≥ 90% 覆盖率）               │
│  验收：regime-conditional coupling 比静态 coupling MAE 改善 ≥ 20%        │
│  时间：GPU 就绪后 3 天                                                  │
└───────────────────────────────────────────────────────────────────────┘
                         │ 训练通过
                         ▼
┌─ Phase C AgentMail 消费 + 闭环验证（COMM-SHADOW Phase 1 观察期）───────┐
│  observe()：读真实 domain_transmission.drift_coupling                  │
│  generate_report()：加 L1 建议章节                                      │
│  candidate_policies/：消费 L1 推荐 π 候选                                │
│  验证：COMM-SHADOW V 函数 hypervolume 提升 ≥ 10% + coupling 稳定性 ≥ 85% │
│  时间：影子观察期 2 周 + 验证 1 周                                      │
└───────────────────────────────────────────────────────────────────────┘
```

### §4.5 跨域组合验证沙箱（2026-11-03 三问评估补，闭环验证层）

> 来源：三问评估 "通信层要做沙箱，把叠加印证假设跑回测验证真实增量"
> 位置：`23-四层闭环自进化交易架构/dreambuddy_evolution/core/domain_hypothesis_sandbox.py`
> 特性：零 GPU，离线，不接实盘，单假设回测 ~2-5 分钟（CPU 4C16G）

#### 4.5.1 已有资产复用

| # | 组件 | 位置 | 复用点 |
|---|---|---|---|
| S1 | **CounterfactualEvaluator** | `23-.../core/counterfactual_evaluator.py` | 合成控制法 + alpha/beta 归因 |
| S2 | **ShadowRLTracker + shadow_rl_samples.db** | `23-.../core/shadow_rl.py` | ~29 万影子样本库做历史基线 |
| S3 | **ftc_backtest.py + reverse_backtest.py** | `23-.../adapters/ftc_backtest.py` | 正向/逆向回测 |
| S4 | **NeuralSDE v1_path_sig** | `23-.../data/neural_sde_v1_path_sig.pt` | 路径置信度交叉验证 |
| S5 | **sector_transmission.json** | `40-周期系统/` | regime context 验证 |
| S6 | **SPEC-Shadow验证自动放量门禁** | `23-.../PLAN-Shadow验证自动放量门禁.md` | 自动接受/拒绝/部分接受门禁 |

#### 4.5.2 沙箱执行流程

```
P3 叠加印证假设
     │
     ├─→ S1 CounterfactualEvaluator (合成控制法)
     │     treatment = hypothesis.prediction.signal_combination
     │     control_group = hypothesis.validation_plan.control_group
     │     min_trades ≥ 50（统计显著性硬门禁）
     │     输出：CounterfactualResult {treatment_alpha, control_alpha_mean, pnl_delta, sharpe_delta, n_trades, ci95}
     │
     ├─→ S4 NeuralSDE v1_path_sig (路径置信度交叉验证)
     │     hypothesis.prediction.time_horizon_min 对应 NeuralSDE forecast step
     │     输出：PathConfidenceDiff {combo_confidence, single_mean, direction_match}
     │
     ├─→ S5 sector_transmission.json (regime context 验证)
     │     hypothesis.trigger.regime_context 匹配当前 regime？
     │     历史回测里该 regime 下 alpha_delta > 其他 regime？
     │     输出：RegimeConsistency {context_match, historical_alpha_in_regime, historical_delta_outside}
     │
     └─→ S6 Shadow 放量门禁（自动接受/拒绝/部分接受）
           ✅ treatment_alpha > control_alpha_mean × 1.1
           ✅ ci95.low > 0（统计显著）
           ✅ PathConfidenceDiff.direction_match = true
           ✅ min_trades ≥ 50
           ✅ RegimeConsistency.context_match = true
           → 输出 P4 验证回执 {result, counterfactual_result, path_confidence, regime_consistency, trace_id}
```

#### 4.5.3 TDD 验收（见 §6 验收项 11-17）

#### 4.5.4 P4 回执消费闭环

P4 验证回执被以下四个模块同步消费：
1. **TRAIN-BASE TB3**：`compute_reward(counterfactual_result=...)` → pnl_delta_score 第七维
2. **TRAIN-BASE TB5 GRPO**：`evolve_step(p4_receipts=...)` → v_adjusted（alpha 加权）
3. **DOMAIN-AGENTS Phase B Dream-RSI**：`V_new(π, T) = V(π, T) + α × mean(validated_hypotheses.pnl_delta_pct)`
4. **COMM-SHADOW observe()**：L1 DomainCouplingHead 推理结果经沙箱验证后回写标注数据

---

## §6 TDD 验收标准（Phase B 硬门禁）

| # | 验收项 | 标准 | 硬约束验证 |
|---|---|---|---|
| 1 | **DomainCouplingHead 参数量级** | 可训练参数 < 5MB（实际 ~0.003MB） | **H2 合规**：冻结主体权重声明 |
| 2 | **主体权重冻结验证** | `for p in neural_sde_base.parameters(): p.requires_grad=False` 覆盖率 100% | H2 |
| 3 | **训练 loss 收敛** | 100 epoch 后 final_loss < 0.02（与 v1 基础持平） | X1 反模式修复：regime-conditional |
| 4 | **walk-forward OOS** | 5 折 walking-forward，每折 coupling MAE < 静态 baseline × 0.8 | X6 反模式：必须做 |
| 5 | **推理 FAIL-OPEN** | L1 推理抛出任何异常 → AgentMail 回退硬编码 π（零 crash） | H4 |
| 6 | **推理延迟** | CPU 单次推理 < 5 秒（6 domain × 6 coupling 矩阵） | — |
| 7 | **domain_transmission.json schema 校验** | Phase C 启动后每日跑 JSON schema 校验，0 fail | H3 可审计 |
| 8 | **V 函数 hypervolume 提升** | Phase C 结束后，AgentMail 消费 L1 coupling 的 hypervolume ≥ 硬编码 baseline × 1.1 | Dream-RSI 不劣化保证 |
| 9 | **L1 推理 trace_id** | 每条 domain_transmission.json 带 `trace_id: "l1-infer-<sha256>"`，可回溯 | H3 |
| 10 | **L1 训练版本登记** | model_version 格式 `l1-domain-coupling-vX.Y`，与 COMM-SHADOW config_version 对账 | TRAIN-BASE §0.5.5 竞态修复 |
| 11 | **Counterfactual alpha/beta 归因正确** | 合成控制法 treatment_alpha = 真实 PnL - 合成反事实，误差 < 0.05 | H2 合规：统计方法不训练 |
| 12 | **影子验证不泄漏实盘** | 历史窗口严格 ≤ 假设生成时间点 `t_start ≤ t_generation`，无未来函数 | 量化黄金标准 |
| 13 | **min_trades ≥ 50** | 任何假设 < 50 笔回测自动降级 `partially_valid` | 统计显著性硬约束 |
| 14 | **沙箱 FAIL-OPEN** | 沙箱任何异常（CounterfactualEvaluator 抛错 / K-line 数据缺失）→ hypothesis.status 保持 `pending_validation`，**不阻塞主流程** | H4 |
| 15 | **P4 回执 trace_id 可追溯** | 每条 P4 验证回执带 `trace_id: "sandbox-<sha256>"`，关联完整 CounterfactualResult JSON 落盘 | H3 |
| 16 | **regime context 对齐** | `hypothesis.trigger.regime_context` 必须能在 `sector_transmission.json` 历史中找到匹配时段 | Shadow 放量门禁 |
| 17 | **沙箱零 GPU** | CPU 4C16G 单假设回测 ≤ 5 分钟 | — |

---

## §7 算力预算

| 阶段 | 算力类型 | 时长/周期 | 成本 |
|---|---|---|---|
| Phase A 标注采集 | CPU 4C16G（云端） | 旁路写入，零额外开销 | ¥0 |
| Phase B 增量训练 | GPU（T4/M1 Metal） | 每次 1-2 小时，每周 1 次 | 腾讯云 T4 ¥2.4/小时 × 8h/月 ≈ ¥19；Mac Metal ¥0 |
| Phase C 推理消费 | CPU 4C16G（云端） | 每次 < 5 秒，每小时 1 次 | ¥0 |
| **总计** | | | **¥19/月（云端方案）或 ¥0（本地方案）** |

**对比外部 LLM API 方案**：按 COMM-SHADOW §5.5 估算月成本 ¥10-100，节省 50-100%。

---

## §8 不突破硬约束声明

| 硬约束 | 如何保证 | 验证方法 |
|---|---|---|
| **H1** 壳零感知 | 所有 L1 产出通过 domain_transmission.json 旁路消费，不修改 envelope.data schema | 代码 diff 静态检查 |
| **H2** 无权重微调 | 主体权重冻结，DomainCouplingHead 可训练参数 < 0.001MB | 训练前 `requires_grad` 覆盖率扫描 |
| **H3** 可审计 | trace_id 前缀 `l1-infer-`，domain_transmission.json 落盘 + JSONL 标注数据完整保留 | 每日审计脚本 |
| **H4** FAIL-OPEN | L1 推理失败 → AgentMail 回退硬编码 π；训练失败 → 用上一版 model.pt | Phase C 集成测试 |
| **H8** PSI 阈值硬编码 | L1 只读 TB1 PSI 值，不修改 `PSI_STABLE=0.1` 等常量 | 代码 grep 静态检查 |
| **H9** 影子三条 | observe() 内部读 domain_transmission.json 是旁路，零触发 agent | COMM-SHADOW 影子测试 |
| **PACKAGING Mandate** | L1 训练/推理代码不进 shell 目录，shell 不 import L1 | 目录结构检查 |

---

## §9 与其他 SPEC 的交叉引用

| 本文节 | 引用 SPEC | 交叉点 |
|---|---|---|
| §0.3 闭环架构 | TRAIN-BASE TB1-TB5 | TB1 PSI+KS / TB2 Beta verify / TB5 GRPO 输出 → 标注数据 |
| §1.3 DomainCouplingHead | TRAIN-BASE H2 | H2 合规：冻结主体权重，只训练轻量 head |
| §2 domain_transmission.json | 40-周期系统 sector_transmission.json | 同构设计，L1_anchor→L2_major→L3_sensitive 分层结构 |
| §4 AgentMail 消费 | COMM-SHADOW v0.1 | observe() / generate_report() / candidate_policies/ 三处扩展点 |
| §4.3 V 函数评估 | COMM-SHADOW §4 + TRAIN-BASE TB3 AlphaPareto | L1 产出 π 必须过 hypervolume 评估 |
| §5 Phase C | COMM-SHADOW §6 升级判据 V-S1~V-S6 | Phase C 结束后触发升级判据评估 |
| §6 TDD | TRAIN-BASE §6.1 | 训练基座 Phase 0 启动后协同跑 TDD |
| §6 #10 version 对账 | TRAIN-BASE §0.5.5 | config_version 冻结→对账链 |

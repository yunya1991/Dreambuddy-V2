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

### 4.6 时序特征提取层（Phase B 前置，路径签名基线）

> **来源**：用户洞察（"L0 通信层必须考虑不同 agent 的时序特征，趋势延续性是 40 周期系统核心假设，不用 GPT 式、用 BERT 类"）+ 三维评估（本地代码 × 传统金融 × AI 工程）
> **调研报告**：[2026-11-03-L0通信层时序特征建模调研](../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-03-L0通信层时序特征建模调研.md)
> **认知**：VM-1793700900477-589cad59（禁自回归）/ VM-1793702513243-ef7a2ea3（选型决策），B 级

#### 4.6.1 问题定位（为什么现有架构丢掉了时序）

| 缺口 | 现状 | 后果 |
|---|---|---|
| **观测层** | `_to_entry()` 每条轨迹是单点快照（`poe_score / cross_domain_refs / latency_ms / messages_sent`），无窗口序列 | 时序流退化为点集 |
| **编码层** | DomainCouplingHead 输入是 backbone hidden 的 mean-pool 单点 | 时序维度被压平，趋势/动量信息归零 |
| **决策层** | `drift_coupling.lags_min` 是**人工先验**（`domain_transmission_static.json`） | 滞后关系未经实测，P3 触发条件（coupling≥0.55）不看时序形态 |

**结论**：时序性不是"加个模型"，而是补齐这三层的观测-编码-决策链路。

#### 4.6.2 选型决策（路径签名深度 3，非 Transformer）

| 维度 | 证据 | 结论 |
|---|---|---|
| 本地代码 | `23-.../core/signature_engine.py` 已具备：`depth=3` 默认、`MAX_DEPTH=5`、**signatory → esig → numpy 三级 FAIL-OPEN**、显式时间增广路径 `(t, X_t)` 以捕获 lead-lag | 零改造即可用于 1D 信号流 |
| 传统金融 | lead-lag 传导的数学本质 = 路径签名二级反对称项（signed area），美股网络研究已验证（arXiv:2201.08283）；Granger/VAR 需 ≥50–100 观测且滞后阶敏感 | 签名比 Granger 更适合**短窗小样本** |
| AI 工程 | 低维短序列（4 通道 × ≤128 步）Transformer 严重过参数化（FaCTR 2025 / Frontiers 2023：1D ResNet/TCN 全面优于 Transformer）；签名 CPU <1ms、零训练 | 签名是**零成本强基线 + 永久降级兜底** |

**硬性排除**：GPT 式自回归（误差累积+暴露偏差，TimeDART arXiv:2410.05711）；PatchTST 冷启动（标注 <1k 时 masked 预训练不稳）。

**升级路径（仅在同时满足以下三条时评估）**：
1. 签名基线 coupling 预测 MAE 连续 3 个 walk-forward 折 > 静态 baseline × 0.8（即不达标）
2. 标注样本 > 5,000
3. 无标签窗口 > 250,000（Mantis/CauKer 给出的预训练:标注 ≥ 50:1 下限）
→ 此时再评估 1D ResNet/TCN，预训练目标**必须用金融 MAP（移动平均预测）**（arXiv:2506.16746），禁用标准值重建。

#### 4.6.3 接口设计（TemporalSignatureExtractor，≤ 200 行）

```python
class TemporalSignatureExtractor:
    """L0 跨域信号流的时序特征提取器（路径签名基线）。

    复用 23-.../core/signature_engine.py（depth=3，三级 FAIL-OPEN）。
    硬约束：
      - T1 零训练（无预训练、无梯度）
      - T2 只读窗口内数据归一化，禁止全局/未来统计量（无 look-ahead）
      - T3 任何异常 → 返回零向量 + degraded=True（FAIL-OPEN，不阻断 Head）
    """

    def __init__(self, depth: int = 3, window_minutes: int = 60,
                 step_minutes: int = 10, max_steps: int = 128):
        self._engine = SignatureEngine(depth=depth)

    def extract(self, entries: list[dict]) -> dict:
        """输入 AgentMailShadow 轨迹条目，输出时序特征。

        输出：
          per_domain_sig: dict[domain, np.ndarray(14,)]   # 6 域 × 14 维
          pair_signed_area: dict["A↔B", float]            # 15 对 lead-lag 强度
          lag_estimate_min: dict["A↔B", int]              # 15 对滞后估计
          feature_vector: np.ndarray(99,)                  # 84 + 15，供 Head
          degraded: bool
        """
```

**特征组成（99 维）**：

| 组 | 维度 | 计算 | 语义 |
|---|---|---|---|
| 每域主通道签名 | 6 × 14 = 84 | `SignatureEngine.signature(zscore(poe_score 窗口))`（时间增广 2 通道，depth 3 → 2+4+8=14） | 本域信号路径形状（趋势/波动/反转形态） |
| 跨域 signed area | 15 | 2D 路径 `(zscore_A, zscore_B)` depth 2 的反对称项 | **lead-lag 方向与强度**（谁领先谁） |
| 滞后估计 | 15 | 窗口内互相关峰值位置的 argmax（粗粒度，10min 分辨率） | 替换 `lags_min` 人工先验 |

**接入 Head**：`Linear(99 → 64)` 投影层（约 6.4k 参数），输出与 backbone hidden 拼接后喂 DomainCouplingHead。新增可训练参数总计 ~9.2k（Head 2.8k + 投影 6.4k），仍远低于 §6 验收项 1 的 5MB 上限。

**输入来源（S0 已就绪）**：`extract()` 消费 `AgentMailShadow.get_domain_window(domain)` 返回的时序步列表（每步 = 同批聚合的 `{ts, poe_score, cross_domain_refs, messages_sent, latency_ms, n}`）。S0 已完成去重与滑窗，S1 不再需要重复实现。

#### 4.6.4 窗口规格（数据驱动，先量化再定档）

| 参数 | 初始值 | 依据 | 校准方式 |
|---|---|---|---|
| `window_minutes` | 60 | 传统金融：日内信息扩散 15–60min（Whaley 股票领先期权） | Phase 0 统计 `trajectories.jsonl` 每域每小时条数 |
| `step_minutes` | 10 | 与影子观察粒度对齐 | 同上 |
| `max_steps` | 128 | 签名深度 3 对 2 通道 → 14 维恒定，与步数无关；但 numpy 降级实现 O(n²) | 实测 CPU 耗时 |
| `depth` | 3 | depth 4 在多通道下维度指数爆炸（2+4+8+16=30/通道） | 固定 |

**前置量化任务（Phase 0 硬前置）**：统计每域每小时产出条数 `λ_d`。若 `λ_d × 60 < 3`（窗口内不足 3 点无法成签名），则该域降级为"不参与时序特征"，仅保留原 mean-pool 通路并标记 `insufficient_steps`。

#### 4.6.5 反模式（禁止）

| # | 禁止 | 理由 |
|---|---|---|
| Z1 | GPT 式自回归生成做时序编码 | 用户明确排除 + TimeDART 误差累积证据 |
| Z2 | 微调 NeuralSDE 主体以接收时序输入 | H2 硬约束；时序特征必须走**外置零训练编码器** |
| Z3 | 冷启动期直接上 PatchTST / Transformer | 标注 <1k 不稳；低维短序列 Transformer 过参数化 |
| Z4 | 用全局统计量做签名前归一化 | look-ahead bias，违反量化黄金标准 |
| Z5 | 用签名特征替换 mean-pool 通路 | 必须**并行拼接**，签名失效时回退原通路（T3） |
| Z6 | 把 `l1_case_store.jsonl` 的 `source_counts` 当时序信号 | 实测 7,977/7,983 次不变（常量快照），方差≈0 → 签名会学出"伪趋势"。禁止作为域信号流；仅可作调度频率单变量 |
| Z7 | 用"行数多"代替"信号有方差"作为数据门禁 | 密度高 ≠ 信息量大；入模前必须先做方差/单调性检验 |

#### 4.6.6 合理性证伪条件（不达标就撤销时序层）

时序层不是默认正确。必须通过以下消融，否则**回退到纯 mean-pool + 人工先验**：

| # | 证伪实验 | 撤销条件 |
|---|---|---|
| F1 | **消融对比**：Head 输入 `[hidden]` vs `[hidden ‖ sig_99]`，同数据同折数 | coupling MAE 改善 < 10% → 撤销 |
| F2 | **随机签名对照**：把 `sig_99` 替换为同分布随机向量重训 Head | 性能与真签名无显著差异（p>0.05）→ 说明是参数增量而非时序信息起作用，撤销 |
| F3 | **lag 预测有效性**：签名派生的 `lag_estimate_min` vs 人工先验，在 walk-forward 上的预测误差 | MAE 不比人工先验低 → 保留人工先验，撤销 lag 分支 |
| F4 | **端到端增益**：P4 沙箱 `pnl_delta` 在含时序特征 vs 不含，min_trades ≥ 50 | `treatment_alpha` 无提升 → 只保留作为诊断信号，不接 Head |
| F5 | **数据充分性**：窗口内点数中位数 | 中位数 < 3 → 时序层不启用（§4.6.4 降级） |

#### 4.6.7 实测数据体检（本地 + 云端 43.160.201.117）

**本地（`.workbuddy/agent_mail/trajectories.jsonl`）**

| 指标 | 实测值 | 门禁 | 判定 |
|---|---|---|---|
| 总条目 | 33 | — | — |
| 时间跨度 | 1,562 秒（≈26 分钟） | 需 ≥ 数周连续积累 | ❌ 严重不足 |
| 唯一时间戳 | 25（33 条中 8 条为同批多条目） | 需按唯一时间戳去重成路径步 | ✅ S0 已解决（`batch_id` 去重） |
| 域分布 | data 11 / eval 9 / cognition 5 / search 5 / rea 2 / semantic 1 | 每域窗口内 ≥3 点 | ❌ rea、semantic 不达标 |
| `poe_score == 0` 占比 | 9.1% | — | ✅ 信号非全零 |
| 有效信号变化度 | 33 条中 23 种 (poe, refs) 组合 | — | ✅ 有一定区分度 |

**云端（2026-11-03 实测，`/home/luke/dreambuddy`）**

| 数据源 | 行数 | 时间跨度 | 密度（活跃小时中位） | 判定 |
|---|---|---|---|---|
| `39-金融语义蒸馏系统/semantic_events.jsonl` | 9,756 | 9.9 天 | 31 条/小时；6 个 term 各 5–13 条/小时；79.9% 数值可解析 | ✅ **真时序流**（域维度=交易决策口径，非 L0 6 域） |
| `39-金融语义蒸馏系统/atomic_events.jsonl` | 3,929 | **33.7 天** | 5 条/小时；19 category × 56 metric | ✅ **真时序流**（市场侧信号，跨度最长） |
| `39-金融语义蒸馏系统/contradiction_events.jsonl` | 1,376 | — | 用 `window_start/window_end` 而非单点 ts | ⚠️ 需窗口重采样 |
| `34-前端应用训练系统/l1_case_store.jsonl` | 7,985 | 4.8 天 | 53 条/小时 | ❌ **伪信号陷阱**：`source_counts` 31 键中 7,977/7,983 次完全不变（Skill=30/Doc=30 恒定），是**静态配置快照**，非时序信号 |
| `23-.../gene_data/shadow_rl_samples.jsonl` | 418,578 | 无 ts | state/action/reward/next_state | ⚠️ RL 样本池，**非时序流**（可作 F1 消融训练量） |
| `40-周期神经网络系统/execution_trades.jsonl` | 32 | 3.0 天 | `pnl` 多为 null | ❌ F4 的 pnl ground truth 不足 |
| `.workbuddy/agent_mail/trajectories.jsonl` | **18（α 首跑 2 轮）** | 2 轮 × 9 调用 | 10 分钟/轮（systemd timer） | ✅ **α 已接线（2026-11-03）**，见 §4.6.10；接入前该文件不存在 |

**结论（修正版）**：

1. **数据量已不是瓶颈**：云端有 33.7 天 / 3,929 条 + 9.9 天 / 9,756 条连续流，远超本地 33 条。
2. **但数据域维度错配**：可用时序流（`semantic_events`/`atomic_events`）的"域维度"是**交易决策口径/市场指标**，而 L0 需要 6 个 agent 域。α 接线后云端已有 4 个真实壳域（data/eval/store-admin/rea）的轨迹，但**只有 4 个壳存在**（cognition/search/semantic 壳尚未实现），6 域覆盖仍不完整（见 §4.6.10）。
3. **密度最高的源是陷阱**：`l1_case_store` 53 条/小时看似完美，但信号方差≈0（常量快照），签名会学出"伪趋势"。已列反模式 Z6。

**分阶段执行（修正）**：

| 阶段 | 动作 | 启动条件（数据门禁） |
|---|---|---|
| **S0（✅ 已落地 2026-11-03）** | 观测层改造：`observe()` 同批去重（`batch_id` → 每域 1 步）+ 每域滑窗（`window_minutes=60` / `max_steps=128`，纯内存）+ `get_domain_window()` / `get_window_summary()` 查询接口；`trajectories.jsonl` 持续积累 | 已完成（`mcp_shells` 53 项测试全通过） |
| **S0.5（✅ 已执行 2026-11-03）** | 选源：<br>**α ✅** 云端接线 AgentMailShadow（壳调用链挂 `observe()`），积累真实域轨迹（结果见 §4.6.10）；<br>**β ✅** 先用 `semantic_events`+`atomic_events` 做方法原型验证（结果 F1/F2 未通过，见 §4.6.9） | α 已上线 timer；β 已出结论 |
| **S1** | 实现 `TemporalSignatureExtractor` + 单测（验收 18/19/20/23） | ⛔ **暂缓**（β 未通过 F1/F2，见 §4.6.9）；重启条件：≥10 条连续流 + ≥6 个月 + 日级 horizon |
| **S2** | 跑 F1/F2 消融（验收 21）+ F3 lag 对比（验收 22） | ⛔ 暂缓（同上；β 已用真实流预演过一次，结果见 §4.6.9） |
| **S3** | 时序特征接入 DomainCouplingHead | ⛔ 暂缓（F1 未达标，按撤销条件不得接入） |
| **撤销** | 回退 pure mean-pool + 人工先验 | 任一 F 项不达标 |

#### 4.6.8 外部调研证据索引（正文规格的支撑材料）

> 本表是 §4.6.2 选型与 §4.6.6 证伪条件的**证据索引**；完整调研过程见[调研报告](../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-03-L0通信层时序特征建模调研.md)。两者冲突时**以本节及 §4.6.2 为准**。

**时序架构（外部证据，非本项目选型）**

| 架构 | 年份/出处 | 关键结论 | 对本项目的意义 |
|---|---|---|---|
| PatchTST | ICLR 2023, arXiv:2211.14730 | patch + channel-independence + masked 自监督；监督版 MSE 降 21.0%；自监督预训练+微调优于全监督；含 freeze/linear-probe 实验 | 未来升级候选（非默认） |
| SimMTM | NeurIPS 2023, arXiv:2302.00861 | 10% 数据微调 MSE 0.591 vs 对比学习 TF-C 降 26.0% | 小样本可行性证据 |
| 金融 MAP 预训练 | 2025, arXiv:2506.16746 | 股价序列直接 masked 值预测不适合，改用**移动平均预测**作代理任务 | §4.6.2 升级路径的预训练目标 |
| DLinear | AAAI 2023, arXiv:2205.13504 | 单层线性在 9 个数据集击败当时全部 Transformer | 反对"必须上 Transformer" |
| TimesNet | ICLR 2023, arXiv:2210.02186 | FFT 多周期 → 2D 折叠；参数/FLOPs 显著大于 PatchTST | 仅作对照 |
| iTransformer | ICLR 2024, arXiv:2310.06625 | 对变量（非时间点）做 attention；无原生 masked 预训练 | 6 域多变量场景备选 |
| TimeDART | arXiv:2410.05711 | 自回归"易过拟合时序噪声与异常，加剧误差累积" | **Z1 禁自回归的直接依据** |

**传统金融范式（lead-lag / 传导建模）**

| 方法 | 适用与局限 | 对本项目的意义 |
|---|---|---|
| Granger 因果 / VAR | 对滞后期高度敏感、两两分析、高维 O(N²·lags)；跨域 6 变量尚可 | 可作 lag 估计的对照基线（非首选） |
| VECM / 协整（Johansen） | 小样本功效低，需 ≥50–100 观测；结构性断点易误判 | 数据量达标后再评估 |
| 转移熵 TE（Schreiber） | 非线性的信息流向；样本饥渴、联合状态空间随历史指数膨胀 | 不适用本项目数据量 |
| DCC-GARCH（Engle 2002） | 动态条件相关、波动联动 | 无（本项目是事件流非价格流） |
| Heston lead-lag | 行业/截面动量领先-滞后 | 支撑"滞后窗口 1 日–数周"的经验区间 |
| 路径签名 signed area | 二级反对称项直接度量 lead-lag（arXiv:2201.08283 美股验证） | **§4.6.3 跨域 15 对特征的数学依据** |

**经验性滞后窗口（§4.6.4 的取值依据）**

| 场景 | 经验滞后 | 出处 |
|---|---|---|
| 股票领先期权（日内） | 15–20 分钟 | Whaley |
| 股指期货领先现货 | 1–5 分钟 | CSI300 研究 |
| 大盘领先小盘 | 1 日 | "Leads, Lags, and Trading in Global Markets" |
| ETF 资金流领先板块动量见顶 | 4–8 周 | Pomegra |
| 行业动量形成期 | t-12 至 t-2 月（剔除最近 1 月） | Heston-Rouwenhorst |
| 跨资产动量 lookback | 1 / 21 / 252 日 | EFMA 2021 |

**小样本与验证硬标准（§4.6.6 / §4.6.7 的门禁依据）**

| 标准 | 数值 | 出处 |
|---|---|---|
| 可信交易样本量 | ≥200 笔（理想 500+）；<100 笔 Sharpe 置信区间过宽 | Keel |
| walk-forward OOS/IS Sharpe | 应在 70–90%；>90% 警惕 lookahead | 行业通行 |
| 预训练 : 标注 样本比 | ≥50:1（CauKer 2025，100K 合成数据接近 1.89M 真实数据效果） | arXiv:2508.02879 / Mantis arXiv:2502.15637 |
| 冻结 vs 全量微调差距 | linear probing 约低 5–7 个点 | Mantis ICLR 2026 |
| 多重检验校正 | Deflated Sharpe Ratio | Bailey & López de Prado 2012 |

#### 4.6.9 β 原型验证结果（2026-11-03，F1/F2/F3 预演）

> 完整报告：[prototype/temporal_signature_beta/report.md](../../prototype/temporal_signature_beta/report.md) ｜ 代码 `proto_beta.py` ｜ 原始结果 `beta_result.json`
> 数据：云端 `semantic_events.jsonl`（4 条达标流 / 3 对 / 平均 104 窗）+ `atomic_events.jsonl`（2 条达标流 / 1 对 / 588 窗）

| 门槛 | 阈值 | 实测 | 结论 |
|---|---|---|---|
| **F1 消融** | 中位 MAE 改善 ≥10% | semantic **-0.68%**；atomic **-0.42%** | ❌ **未通过** |
| **F2 随机对照** | ≥1/3 对 p<0.05 且方向为正 | semantic 0/3；atomic p=0.005 但**方向为负**（真签名劣于置换） | ❌ **未通过** |
| **F3 lead-lag** | 一致率 ≥80% | semantic 66.7%；atomic 100%（单对且 lag 触边界，不可采信） | ⚠️ 方向存在，样本不足 |
| 敏感性 | window 4/8/12 × coverage 0.4/0.5 | 中位改善始终在 ±1% 内 | 排除配置因素 |
| 同流对照 | A 预测自身 | 仅 `反向信号软权重` +23.7%，其余持平/变差 | 窄正向线索 |

**判定**：按 §4.6.6 预设撤销条件，**F1 未达标 → 时序层不接入 DomainCouplingHead，S1/S2/S3 暂缓**。

**解读**：
1. 低维事件流上，五维统计特征已吃掉可解释信息；签名 15 维主要增加方差。
2. 随机对照多数对不劣于真签名 → 增量更像"自由度噪声"而非"时序结构"。
3. 时序有用性取决于**信号是否连续可测**：稀疏事件触发流上窗口路径本身不可信。这直接印证 §4.6.7 的"数据源错配"判断。
4. 因此前置条件从"实现编码器"改为"**先确保每域有连续高频信号**"（即 S0.5 选项 α）。

**保留项**：`反向信号软权重` 同流 +23.7% 与 `BDSM→反向` lag=6 → 仅作为窄场景候选，不构成通用结论。

**重新评估的触发条件**（三条同时满足才重启 S1）：≥10 条连续流、覆盖 ≥6 个月、且目标 horizon 改为日级（降低噪声）。

#### 4.6.10 α 云端接线结果（2026-11-03）

**接线方式（不是进程内直调，而是经过壳边界）**

| 层 | 改动 | 说明 |
|---|---|---|
| 壳内计时 | 4 个壳 `tools/call` 分支实测 handler 耗时 | `observe_envelope(text, latency_ms=..., action=工具名)` |
| 旁路开关 | `shadow_hook.enabled()`：显式 env > `.workbuddy/agent_mail/ENABLED` flag > 默认关 | 云端无需改 env 即可启停；`AGENT_MAIL_SHADOW=0` 可临时否决 |
| meta 补齐 | 信封 meta 缺失时补 `latency_ms` / `event_type` / `poe_score`(成功 1.0、降级 0.0) / `messages_sent` | 以实测值为准，信封自带值零覆盖（Z7：连续信号交给真实 latency） |
| 流量驱动 | `mcp_shells/_shared/shadow_driver.py` 按 MCP stdio JSON-RPC 拉起壳进程执行只读工具面 | 云端无 MCP host 常驻，必须由驱动产生真实壳调用 |
| 调度 | `31-分布式计算部署/phase13/dreambuddy-shadow-driver.{service,timer}`，10 分钟一轮 | `User=luke`，`TimeoutStartSec=300` |

**首跑实测（`sudo -u luke -H` 读取 `/home/luke/dreambuddy/.workbuddy/agent_mail/trajectories.jsonl`）**

| 指标 | 实测 | 判定 |
|---|---|---|
| 条目 | 18（2 轮 × 9 调用；`systemctl start` 首跑 + timer 首触发） | ✅ 落盘生效 |
| 域覆盖 | data 8 / store-admin 4 / rea 4 / eval 2 | ⚠️ 仅 4 域（云端只有 4 个壳） |
| 动作 | data_fetch 4、data_collect_once 2、data_store_read 2、eval_report 2、store_admin_status/query 各 2、submit/poll_rea_trace 各 2 | ✅ 工具面真实 |
| latency_ms | 0.021~46.1（eval 46ms、store_admin 29ms、data <3ms） | ✅ 连续真实信号 |
| poe_score | 1.0 ×16 / 0.0 ×2 | ✅ 有方差（非全常量） |
| trace_id | 100% `shadow-` 前缀 | ✅ S2 合规 |
| 降级 | `data_store_read` 2 次 `unavailable`（云端 DAL container 无 `query_repo`） | ⚠️ 真实缺口，待 DAL 只读仓配置 |

**与 S1 的关系**：α 只解决"有没有真实轨迹"，不解决"是否该上时序"——F1/F2 仍未通过（§4.6.9）。按 §4.6.6 撤销条件，S1/S2/S3 继续暂缓；α 的价值是让重启条件（≥10 条连续流、≥6 个月）**开始真实累积**而非靠合成样本。

**已知缺口**：
1. 6 域只覆盖 4 域（cognition/search/semantic 壳未实现）。
2. 10 分钟 9 调用 ≈ 每域 6 步/小时，S0 去重后仍满足窗口 ≥3 步，但跨度需累积数周才可信。
3. `cross_domain_refs` 壳侧无法感知，保持缺省 0；跨域共现只能由 S0 窗口层事后推导。

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
| 18 | **时序特征零训练** | `TemporalSignatureExtractor` 无 `requires_grad`、无 `.fit()`、无预训练权重文件 | §4.6 T1；H2 |
| 19 | **时序无 look-ahead** | 签名前归一化只用窗口内统计量；单测：注入未来点 → 特征值不变 | §4.6 T2；量化黄金标准 |
| 20 | **时序 FAIL-OPEN** | 空窗口 / 单点 / 异常输入 → 返回零向量 + `degraded=True`，Head 原通路不受影响 | §4.6 T3；H4 |
| 21 | **时序特征消融达标** | F1 coupling MAE 改善 ≥ 10% 且 F2 随机对照显著（p<0.05） | §4.6.6 F1/F2 |
| 22 | **lag 估计优于人工先验** | F3 walk-forward lag MAE < 静态 `lags_min` 先验 MAE | §4.6.6 F3 |
| 23 | **时序层推理开销** | 6 域 × 60min 窗口单次 `extract()` < 20ms（CPU） | §4.6.4 实测 |
| 24 | **数据充分性门禁** | 每域窗口内点数中位数 ≥ 3，否则该域降级 `insufficient_steps` | §4.6.6 F5 |

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

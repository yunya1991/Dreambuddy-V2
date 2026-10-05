# 集成方案：外生力量 + 质变检测 接入 NeuralSDE 训练

> **状态：** 方案设计（待评审）
> **创建：** 2026-10-05
> **目标：** 将外生力量度量（9 维）接入 drift_net 输入，质变检测作为 regime 辅助信号，弥补 NeuralSDE"无外生信息"的核心短板

## 一 · 背景与动机

### 1.1 问题
NeuralSDE 当前 drift_net 输入 = `[y, log_sig, regime, transition]`，全部来自**价格序列本身**（内生信息）。认知记忆 VM-1791185382877 已记录根因：

> "NeuralSDE 当前架构本质是马尔可夫 SDE（只依赖当前状态），无法捕获趋势/动量等历史依赖模式。要超越 GARCH，需升级为路径依赖 SDE 或引入外生信息。"

当前 OOS MAE=901.98, ratio=0.9630（击败 GARCH 3.7%），但瓶颈在于**信息来源单一**。

### 1.2 机会
项目已有 5 个反身性监测模块，其中：
- **外生力量度量**（`exogenous_strength_evaluator.py`）：输出 9 个 [0,1] 标准化力量值，维度匹配、信息增益最大
- **质变检测**（`structural_break_detector.py`）：仅需 closes 即可运行，可辅助 regime 切换

### 1.3 集成价值预期
- 外生力量 9 维 → drift_net 输入扩展，引入 ETF 流向/funding/CPI/NVT 等跨市场信号
- 质变检测 → regime 边界更精准，减少 regime 误判导致的 expert 路由错误
- **预期收益**：ratio 0.9630 → <0.93（外生信息是趋势预测的关键缺失信号）

## 二 · 现状分析

### 2.1 NeuralSDE drift_net 输入接口
```python
# _PathSignatureDriftNet.forward / _MoEDriftNet.forward
def forward(self, t, y, log_sig=None, regime=None, transition=None):
    # 当前拼接: [y(1) + log_sig(sig_dim) + regime(n_regimes) + transition(n_transition)]
    # MoE router 输入: [regime + transition]
```

### 2.2 prepare_data 窗口结构
```python
# 返回: list[(input_window(seq_len,), target_window(horizon,), log_sig(sig_dim,), regime_label(int))]
# 窗口切分: 按 seq_len+horizon 滑动
# regime 附加: per_window_regime = regime_labels[start + seq_len - 1]
```

### 2.3 外生力量评估器接口
```python
# ExogenousStrengthEvaluator.evaluate(data: dict) -> dict[str, dict[str, float]]
#   输出: {technical/fundamental/macro: {short/medium/long: float[0,1]}}
#   9 个 [0,1] 标量
# 依赖: etf_net_flow, funding_rate, cpi_actual, rate_hike_prob, nvt_ratio, active_addresses, dxy, ma_200, close...
```

### 2.4 数据桥梁（已存在）
`exogenous_data_bridge.py` → `ExogenousDataBridge.fetch()`：
- 从 19-DAL `MarketMacroRepository.mm_metrics` 读取真实数据
- **关键约束**：`fetch()` 只返回**最新快照**（标量），非时序对齐
- 宏观数据（CPI/FOMC）是月度/事件级，技术面（ma_200/funding）可逐 bar 算

### 2.5 质变检测器接口
```python
# StructuralBreakDetector.detect_all(price, returns=None, benchmark=None) -> dict
#   输出: {volatility_regime_shift: {...}, correlation_break: {...}, market_form_shift: {...}, any_structural_break: bool}
#   仅需 closes 即可运行 ✅
#   输出频率: 逐序列（给一段 price 返回一个断裂判断）
```

## 三 · P1 外生力量接入 drift_net

### 3.1 核心挑战：时序对齐
- `ExogenousDataBridge.fetch()` 返回最新快照，但训练需要逐窗口对齐的 9 维向量
- 宏观数据低频（月度），需前向填充到小时级
- 技术面指标（ma_200, monthly_trend_slope）可从 closes 直接计算

### 3.2 设计决策：解耦的时序注入

**不让 NeuralSDE 直接依赖 DAL**，而是接收预构建的外生时序数组：

```python
# NeuralSDETrainer.prepare_data 新增参数
def prepare_data(
    self, closes, max_windows=3000,
    regime_labels=None, regime_balance="balanced",
    exogenous_series: Optional[np.ndarray] = None,  # NEW: shape=(len(closes), 9)
) -> list[tuple]:
    ...
    # 每个窗口取末尾点的 exogenous 向量（对齐 regime 取法）
    if exogenous_series is not None:
        win_exo = exogenous_series[start + seq_len - 1]  # (9,)
    else:
        win_exo = np.zeros(9)  # FAIL-OPEN: 无外生数据用零向量
    # 窗口元组扩展: (input_window, target_window, log_sig, regime_label, win_exo)
```

### 3.3 drift_net 输入扩展

```python
# _PathSignatureDriftNet.forward 新增 exogenous 参数
def forward(self, t, y, log_sig=None, regime=None, transition=None, exogenous=None):
    pieces = [y]
    if log_sig is not None: pieces.append(log_sig)
    if regime is not None: pieces.append(regime)
    if transition is not None: pieces.append(transition)
    if exogenous is not None: pieces.append(exogenous)  # NEW: +9 维
    x = torch.cat(pieces, dim=-1)
    ...
```

### 3.4 辅助函数：构建外生时序

新增 `build_exogenous_series(closes, bridge=None) -> np.ndarray`：
- 若 bridge 可用：逐点调用 `bridge.fetch()` + 前向填充（低频宏观用最近值）
- 若 bridge 不可用：从 closes 计算技术面子集（ma_200, trend_slope），其余用 0.5 中性值
- 返回 shape=(len(closes), 9) 的 [0,1] 标准化数组

### 3.5 训练流程改动

```python
# train() 新增 exogenous_series 透传
def train(self, closes, epochs=200, regime_labels=None, ...,
          exogenous_series: Optional[np.ndarray] = None):
    windows = self.prepare_data(closes, ..., exogenous_series=exogenous_series)
    # 训练循环中 drift_net 调用增加 exogenous 参数
```

### 3.6 FAIL-OPEN 铁律
- `exogenous_series=None` → 零向量，drift_net 维度不变（行为等价于当前）
- `exogenous_series` 长度不足 → 截断/补零
- DAL 不可用 → `build_exogenous_series` 回退到 closes 衍生技术面
- 新参数全部默认 None/False，不破坏现有调用方

### 3.7 forecast 推理兼容
```python
# NeuralSDEModel.forecast() 新增 exogenous_snapshot 参数
def forecast(self, history, horizon, n_paths, regime=None, exogenous_snapshot=None):
    # exogenous_snapshot: (9,) 最新外生向量，None → 零向量
```

## 四 · P2 质变检测辅助 regime

### 4.1 可行性
- `StructuralBreakDetector.detect_all(price)` 仅需 closes，无外部依赖
- 可在 prepare_data 窗口级运行

### 4.2 设计：regime 边界增强

**方案 A（推荐）：断裂点作为 regime 切换信号**

```python
# BTCRegimeDetector.detect(closes) 新增 structural_break_labels 参数
def detect(self, closes, structural_break_points: Optional[np.ndarray] = None):
    # 原有 drawdown-based regime
    raw_regimes = self._drawdown_regime(closes)
    # 若提供断裂点，在断裂处强制切分（覆盖 drawdown 判断）
    if structural_break_points is not None:
        for bp in structural_break_points:
            # 断裂点处启动新 regime 段
            raw_regimes = self._override_at_break(raw_regimes, bp)
    return raw_regimes
```

**方案 B（备选）：断裂标志作为 drift_net 1 维特征**

每个窗口附加 `any_structural_break` 布尔 → 转为 0/1 标量拼到 drift_net 输入。

**推荐方案 A**：因为 regime 切换是 MoE router 的路由依据，断裂点直接增强路由质量，比作为 1 维特征信息密度更高。

### 4.3 断裂点提取
```python
# 新增辅助函数
def extract_break_points(closes, detector: StructuralBreakDetector) -> np.ndarray:
    """滑动窗口检测，返回发生 any_structural_break=True 的时间点索引。"""
    # 用 seq_len 窗口滑动，每窗调用 detect_all
    # 收集 any_structural_break=True 的窗口末尾索引
```

### 4.4 验证需求（用户标注"需进一步验证"）
- ablation: regime(纯 drawdown) vs regime(drawdown + structural_break)
- 评估指标：regime 切换点数量、OOS MAE 对比
- 风险：断裂点过多导致 regime 碎片化（需设置最小段长度）

## 五 · 任务分解

| ID | 任务 | 优先级 | 依赖 |
|----|------|--------|------|
| E1 | `build_exogenous_series()` 辅助函数 | 高 | — |
| E2 | `prepare_data` 新增 `exogenous_series` 参数 | 高 | E1 |
| E3 | drift_net forward 新增 `exogenous` 输入 | 高 | E2 |
| E4 | `train()` 透传 exogenous_series | 高 | E2,E3 |
| E5 | `forecast()` 新增 exogenous_snapshot | 高 | E3 |
| E6 | TDD: test_exogenous_integration.py | 高 | E1-E5 |
| E7 | PoC: walk-forward 2024 对比（有/无外生） | 高 | E6 |
| B1 | `extract_break_points()` 辅助函数 | 中 | — |
| B2 | `BTCRegimeDetector` 接收断裂点 | 中 | B1 |
| B3 | ablation: regime(+break) vs regime(纯) | 中 | B2 |

## 六 · 验证方案

### 6.1 单元测试（E6）
- test_prepare_data_exogenous：exogenous_series 正确附加到窗口
- test_drift_net_exogenous：drift_net 输入维度 +9
- test_fail_open：exogenous_series=None 行为等价当前
- test_forecast_exogenous：推理时 exogenous_snapshot 透传

### 6.2 OOS PoC（E7）
- 配置 A：当前最佳（MoE hard + return_mse + dropout0.05）— baseline
- 配置 B：配置 A + exogenous_series（9 维）
- 对比：2024 OOS MAE, ratio
- 闸门：配置 B ratio < 配置 A ratio（否则回退）

### 6.3 质变检测 ablation（B3）
- 配置 C：配置 A + structural_break regime
- 对比：regime 切换点数量、OOS MAE
- 闸门：不恶化（MAE 不超过配置 A +1%）

## 七 · 风险与回退

| 风险 | 缓解 |
|------|------|
| 外生数据 DAL 不可用 | build_exogenous_series 回退到 closes 衍生技术面 |
| 外生数据维度爆炸 | 仅 9 维，已标准化 [0,1]，无爆炸风险 |
| 断裂点碎片化 regime | 设置最小段长度（如 48h） |
| OOS 恶化 | FAIL-OPEN：exogenous_series=None 回退到当前最佳 |
| 训练耗时增加 | 9 维输入增量小，预计 <10% 耗时增加 |

## 八 · 修改文件清单

| 文件 | 改动 |
|------|------|
| `core/neural_sde_model.py` | prepare_data + drift_net + train + forecast 新增 exogenous |
| `core/btc_regime_detector.py` | detect() 接收 structural_break_points（P2） |
| `core/exogenous_data_bridge.py` | 新增 build_exogenous_series 辅助函数 |
| `tests/test_exogenous_integration.py` | TDD 测试 |
| `tests/walk_forward_2024_oos.py` | PoC 对比实验配置 |

## 九 · 科研调研验证（2026-10-05）

### 9.1 P1 外生力量接入 drift — 文献强支持 ✅

| 文献 | 关键发现 | 对方案的验证 |
|------|----------|-------------|
| Longitudinal Flow Matching (arXiv 2510.03569, 2025) | 联合优化 drift + diffusion，支持 subject-specific conditioning | 验证"外生信息作为 conditioning 注入 drift"是标准方法 |
| Score-Based + Neural ODE (arXiv 2511.03862, 2025) | Langevin drift = score function + non-autonomous exogenous forcing | 直接支持"drift 包含外生 forcing"的架构 |
| Neural Brownian Motion (arXiv 2507.14499, 2025) | BSDE driver 参数化为神经网络，drift 由 learned measure 决定 | 验证 drift 可由 learned 参数（含外生）驱动 |
| FinWorld (arXiv 2508.02292, KDD 2026) | 明确定义 exogenous covariate series z ∈ R^(T×C) | 外生特征接入是金融预测标准做法 |
| ConvTimeXer (Entropy 2026) | endogenous + exogenous 动态解耦 + cross-attention | 简单拼接是合理 baseline，cross-attention 是进阶 |

**结论**：方案"drift_net 输入拼接 exogenous 9 维"与最新文献一致。简单拼接作为 baseline 先行，后续可升级为 cross-attention（ConvTimeXer 方向）。

### 9.2 P2 质变检测辅助 regime — 文献支持 ✅

| 文献 | 关键发现 | 对方案的验证 |
|------|----------|-------------|
| Kramers-Moyal + 断裂点 (arXiv 2507.01989, 2025) | rolling-window 估计 drift/diffusion + 断裂点检测，断裂点与重大事件对齐 | 直接验证"断裂点 = regime 切换" |
| Param-CPD (arXiv 2510.17933, 2025) | 在 parameter space 检测 changepoint，F1 优于 observation space | 优化方向：未来可检测 drift 参数断裂（不只价格断裂） |
| ETH RiskLab (2026) | Kalman Filter + PELT 检测 structural breaks，multivariate 恢复 common breakpoints | 验证断裂检测的多维度方法 |
| RegimeChange (2026) | Type I/II error 权衡是核心 | 提醒：需设最小段长度防碎片化 |

**结论**：质变检测辅助 regime 有理论基础。方案 A（断裂点作为 regime 切分）与 Kramers-Moyal 文献一致。优化方向：参考 Param-CPD，未来可升级为 drift 参数空间断裂检测。

### 9.3 Granger 因果作为筛选器 — 最新文献验证 ✅

| 文献 | 关键发现 | 对方案的验证 |
|------|----------|-------------|
| GS-Fuse (arXiv 2605.28520, 2026) | Granger-supervised gated fusion — 只在事件提供增量预测价值时打开 gate | 验证"Granger 因果决定哪些特征接入"的方向 |
| GraphTM (arXiv 2607.06719, 2026) | 外生宏观变量通过 message passing 更新节点特征，预测 FX regime | 验证"外生宏观变量辅助 regime 识别" |

**结论**：评估中"Granger 因果作为离线特征筛选器"的方向与 GS-Fuse 的 Granger-supervised gating 一致。可作为 P1 的后续优化（给 exogenous 9 维加 gate）。

### 9.4 方案优化建议（基于调研）

1. **P1 baseline 先行**：简单拼接 exogenous 9 维到 drift_net 输入 — 文献充分支持，无需过度设计
2. **后续优化 A**：参考 GS-Fuse，给 exogenous 加 learned gate（学习何时打开），避免外生数据噪声时段干扰
3. **后续优化 B**：参考 ConvTimeXer，用 cross-attention 替代简单拼接，实现 endogenous-exogenous 动态解耦
4. **P2 先做价格断裂**：与 Kramers-Moyal 文献一致，先用价格断裂点辅助 regime
5. **P2 后续优化**：参考 Param-CPD，升级为 drift 参数空间断裂检测（更准但更复杂）

### 9.5 调研结论

**方案整体合理**：P1 和 P2 的设计方向均有最新文献支持，简单拼接/价格断裂作为 baseline 是合理的第一步，cross-attention/parameter-space 检测可作为后续优化方向。无需调整核心方案，可按原计划实施。

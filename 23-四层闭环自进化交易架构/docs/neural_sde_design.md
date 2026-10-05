# NeuralSDE 路径依赖 SDE 设计文档

> **版本**: v1.0 | **创建日期**: 2026-10-05 | **最后更新**: 2026-10-05
> **定位**: NeuralSDE 子系统技术设计, 对齐 SPEC-AGI升级蓝图.md §4.2.3 / HC-AGI-13
> **关联**: [CHANGELOG.md](./CHANGELOG.md) v1.9 | [neural_sde_model.py](../dreambuddy_evolution/core/neural_sde_model.py) | [signature_engine.py](../dreambuddy_evolution/core/signature_engine.py) | [garch_fallback.py](../dreambuddy_evolution/core/garch_fallback.py)
> **硬约束**: 4 级 FAIL-OPEN 铁律 + MIN_SAMPLES_FOR_ACTIVATION=1000 样本阈值 + CS 维度 8 硬约束不可增

---

## 1. 概述

### 1.1 系统定位

NeuralSDE 是 23-四层闭环自进化交易架构 L2 级子系统, 提供连续时间动态建模能力. 核心思想: dS = fθ(S_t, t, log_sig(history))dt + gφ(S_t, t)dW, 其中 drift 网络输入路径签名 (Lyons 粗路径理论), 实现**路径依赖 SDE** (非马尔可夫).

### 1.2 设计目标

- **超越 GARCH**: 路径依赖 SDE 在价格预测 MAE 上优于 GARCH(1,1) baseline
- **FAIL-OPEN 4 级降级**: torchsde → 手写 Euler-Maruyama → GARCH → GBM
- **认知闭环接入**: 训练→PoC→record→verify 全流程
- **生产激活门控**: 样本数 ≥ 1000 才自动激活 (HC-AGI-13)

### 1.3 蓝本

- Stable-Neural-SDEs (ICLR 2024)
- Lyons 1998 粗路径理论 + Hambly-Lyons 2010 唯一性
- Gatheral 2018 "Volatility is rough" (粗波动率证据)
- 参考 CQLTrainer 模式 (延迟导入 / _available 标志 / save-load)

---

## 2. 架构设计

### 2.1 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│  NeuralSDEModel                                             │
│                                                              │
│  ┌────────────────────┐    ┌────────────────────┐            │
│  │ _PathSignatureDriftNet │  │ _DiffusionNet     │            │
│  │ fθ(S_t, t, log_sig)  │    │ gφ(S_t, t) → σ>0  │            │
│  │ 输入: 3+sig_dim 维  │    │ 输入: 3 维         │            │
│  │ 输出: 标量 drift    │    │ 输出: 标量波动率   │            │
│  └────────────────────┘    └────────────────────┘            │
│           │                          │                       │
│           └─────────┬────────────────┘                       │
│                     ▼                                        │
│         ┌──────────────────────┐                             │
│         │ SignatureEngine      │ (三级降级)                  │
│         │ signatory → esig → numpy │                          │
│         │ depth=3, 返回 6/15 维 │                             │
│         └──────────────────────┘                             │
│                     │                                        │
│                     ▼                                        │
│         ┌──────────────────────┐                             │
│         │ forecast(history, h, n_paths) │                    │
│         │ 路径依赖: log_sig(history) │                       │
│         └──────────────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 FAIL-OPEN 4 级降级链

| 级别 | 触发条件 | 实现 |
|------|----------|------|
| Level 1 | torchsde 可用 | `torchsde.sdeint()` + path-signature drift |
| Level 2 | torchsde 不可用 | 手写 Euler-Maruyama + path-signature drift |
| Level 2.5 | signature 计算失败 | log_sig pad zeros (退化马尔可夫), 仍走 EM |
| Level 2.7 | history < N_step | log_sig pad zeros, 退化马尔可夫 |
| Level 3 | 样本 < 1000 | GARCH(1,1) (HC-AGI-13) |
| Level 4 | GARCH 失败 | GBM (deep_reasoning_engine 兜底) |

### 2.3 关键参数 (DEFAULT_*)

| 参数 | 值 | 说明 |
|------|----|------|
| `DEFAULT_SIG_DIM` | 15 | log-signature 维度 (esig depth=3 输出 15, numpy 6 维 pad zeros) |
| `DEFAULT_N_STEP` | 32 | 最近窗口长度 |
| `DEFAULT_SIG_DEPTH` | 3 | 签名深度 (HC-AGI-11 ≤5) |
| `DEFAULT_DRIFT_CLIP` | 2.0 | drift tanh 裁剪防爆炸 |
| `DEFAULT_DIFFUSION_FLOOR` | 0.001 | diffusion 正值下限 |
| `MIN_SAMPLES_FOR_ACTIVATION` | 1000 | HC-AGI-13 激活阈值 |

---

## 3. 训练流程

### 3.1 NeuralSDETrainer

[neural_sde_model.py#L746-L838](../dreambuddy_evolution/core/neural_sde_model.py#L746) `NeuralSDETrainer`

**prepare_data 两阶段** (TDD-010 z-score 归一化):
1. 第一阶段: 用 `_compute_log_sig_raw` 累积所有窗口的 raw log_sig
2. `_fit_log_sig_normalization` 拟合 z-score 归一化参数 (mean/std)
3. 第二阶段: 用 `_normalize_log_sig` 生成归一化 windows

**loss_type 三选项** (TDD-012 + TDD-013):
- `"mse"` (默认, 向后兼容): 价格路径 MSE
- `"qlike"`: 波动率 QLIKE quasi-likelihood
- `"multitask"` (TDD-013): 0.7*MSE + 0.3*QLIKE ⚠️ **反模式, 见 §5**

### 3.2 训练脚本

[scripts/train_neural_sde.py](../dreambuddy_evolution/scripts/train_neural_sde.py) 训练 + `select_best_version()` 自动选最优版本复制为 `neural_sde_v1.pt`

---

## 4. PoC 实验矩阵 (TDD-007~013)

### 4.1 完整对照表

| 实验 | Loss | 数据 | final_loss | NeuralSDE MAE | GARCH MAE | ratio | 闸门 |
|------|------|------|------------|---------------|-----------|-------|------|
| v1 (马尔可夫) | MSE | 17k (1h) | 1.214 | 1331.64 | 840.82 | 1.59 | ❌ FAIL |
| v1 (路径依赖) | MSE | 17k (1h) | 0.0069 | 1173 | 840 | 1.40 | ❌ FAIL |
| **v2 (生产最优)** | **MSE** | **17k (1h, 2y)** | **0.0073** | **269.51** | **881.14** | **0.31** | **✅ PASS** |
| v3 | multitask | 88k (30m, 5y) | 72.677 | 244676 | 324 | 753.87 | ❌ FAIL |
| v3b | MSE | 88k (30m, 5y) | 0.00219 | 512 | 332 | 1.54 | ❌ FAIL |
| v3c | MSE | 80k (1h, 10y) | 0.00246 | 569.76 | 844.85 | 0.67 | ✅ PASS |

### 4.2 突破性改善路径

- v1 → v2: MAE 1331 → 269 (5x 改善) — 关键修复: z-score 归一化 (TDD-010) + sig_dim=15 不截断 (TDD-011)
- v2 → v3: MAE 269 → 244676 (灾难性回归) — 反模式: multitask QLIKE 分量主导
- v2 → v3c: MAE 269 → 569 (退化) — 数据扩充引入 regime 切换噪声

---

## 5. 反模式记录 (认知库 VM-1791189381322, A 级)

### 5.1 multitask loss 权重失衡

**症状**: 0.7*MSE + 0.3*QLIKE 训练后 MAE=244676 (753x 差于 GARCH), 价格路径发散.

**根因**: QLIKE 分量数值 (~72) 远大于 MSE 分量 (~0.002), 0.3*QLIKE 主导优化, 模型主要最小化 QLIKE (波动率), 忽视 MSE (价格路径).

**解决**: 放弃 0.7/0.3 固定权重. 未来方向:
- A. 自适应权重 (基于 loss 分量运行均值动态调整)
- B. loss 分量 z-score 归一化后加权
- C. 纯 MSE (已验证 v2/v3c 都 PASS)

### 5.2 数据频率改变导致 horizon 时长不可比

**症状**: v3b (30m + MSE) MAE=512 仍 FAIL, 比 v2 (1h + MSE) MAE=269 差.

**根因**: 30m K 线 horizon=20 步 = 10h 预测窗口 vs 1h K 线 horizon=20 步 = 20h, 窗口时长不同导致 GARCH baseline MAE 也变 (881→332), 直接 MAE 不可比. 30m 噪声/信号比更高.

**解决**: 保持预测窗口时长一致 (同频率同 horizon, 或调整 horizon 使时长等价). 数据扩充用 1h 长时段 (10y → 80k 点) 而非改频率.

---

## 6. 生产部署

### 6.1 当前生产模型

- **权重**: [neural_sde_v1.pt](../dreambuddy_evolution/data/neural_sde_v1.pt) (= v2, MAE=269.51, ratio=0.31)
- **加载点**: [deep_reasoning_engine.py#L81](../dreambuddy_evolution/engines/deep_reasoning_engine.py#L81) `Path(...) / "data" / "neural_sde_v1.pt"`
- **开关**: [agi_config.py](../dreambuddy_evolution/agi_config.py) `enable_neural_sde=True` (2026-09-11 用户决策全部开启)

### 6.2 切换生产模型流程

```bash
# 1. 训练新版本 (生成 neural_sde_v1_<tag>.pt + .training_report.json)
python dreambuddy_evolution/scripts/train_neural_sde.py

# 2. select_best_version 自动比对 MAE, 将最优复制为 neural_sde_v1.pt
# (在 train_neural_sde.py 末尾自动调用, 也可手动调用)
```

`select_best_version` 通过 `training_report.json` 中 `mae_comparison.neural_sde_mae` 字段判断最优.

### 6.3 验证生产权重

```python
from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel
model = NeuralSDEModel(device="cpu")
model.load("dreambuddy_evolution/data/neural_sde_v1.pt")
# 验证: sig_dim=15, loss_type=mse, MAE=269.51
```

---

## 7. 未来优化方向

| 优先级 | 方向 | 预期 |
|--------|------|------|
| P0 | regime detection + 分 regime 训练 | 解决 v3c MAE 退化 (569 → <269) |
| P1 | 自适应 multitask 权重 (loss 分量归一化后加权) | 同时优化价格+波动率, 可能 < 269 |
| P2 | Transformer/RNN-based SDE (序列编码器替代标量状态) | 学术证据弱-中, 工程复杂度 8/10 |
| P3 | walk-forward 验证 NeuralSDE (现仅 PoC 单点) | 提升统计严谨性 |

---

## 8. 关联文件

| 类型 | 路径 |
|------|------|
| 模型实现 | [core/neural_sde_model.py](../dreambuddy_evolution/core/neural_sde_model.py) (~970 行) |
| 签名引擎 | [core/signature_engine.py](../dreambuddy_evolution/core/signature_engine.py) (三级降级) |
| GARCH baseline | [core/garch_fallback.py](../dreambuddy_evolution/core/garch_fallback.py) |
| 训练脚本 | [scripts/train_neural_sde.py](../dreambuddy_evolution/scripts/train_neural_sde.py) |
| 数据下载 | [scripts/download_binance_klines.py](../dreambuddy_evolution/scripts/download_binance_klines.py) |
| 集成点 | [engines/deep_reasoning_engine.py](../dreambuddy_evolution/engines/deep_reasoning_engine.py) L81 |
| 开关配置 | [agi_config.py](../dreambuddy_evolution/agi_config.py) `enable_neural_sde` |
| TDD 测试 | [tests/test_neural_sde_optimization.py](../dreambuddy_evolution/tests/test_neural_sde_optimization.py) (TDD-010~013, 16 测试) |
| PoC 脚本 | [tests/poc_tdd007_v2_mae_garch_band.py](../dreambuddy_evolution/tests/poc_tdd007_v2_mae_garch_band.py) (v2 PASS) |
| PoC 脚本 | [tests/poc_v3c_mse_1h_10y.py](../dreambuddy_evolution/tests/poc_v3c_mse_1h_10y.py) (v3c PASS) |
| 生产权重 | [data/neural_sde_v1.pt](../dreambuddy_evolution/data/neural_sde_v1.pt) (= v2) |
| 训练报告 | [data/neural_sde_v1.training_report.json](../dreambuddy_evolution/data/neural_sde_v1.training_report.json) |

---

**文档版本**: v1.0 | **最后更新**: 2026-10-05 | **维护者**: NeuralSDE TDD 团队

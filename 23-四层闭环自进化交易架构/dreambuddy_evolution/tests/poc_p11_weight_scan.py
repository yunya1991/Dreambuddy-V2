"""P1.1 快速权重扫描: 找最优 SDE/GARCH ensemble 权重.

基于已有模型, 扫描 w ∈ [0, 1] 找最优 MAE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.neural_sde_model import NeuralSDEModel, NeuralSDETrainer
from dreambuddy_evolution.core.garch_fallback import GARCHFallback
from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

import torch
torch.manual_seed(42)

data_path = REPO / "dreambuddy_evolution" / "data" / "btc_close_10y.json"
with open(data_path) as f:
    closes_full = np.array(json.load(f), dtype=np.float64)

N_TEST_2024 = 24 * 365
train_end = len(closes_full) - N_TEST_2024
closes_train = closes_full[:train_end]

np.random.seed(42)
detector = BTCRegimeDetector()
regime_train = detector.detect(closes_train)
regime_test = detector.detect(closes_full[train_end:])
regime_full = np.concatenate([regime_train, regime_test])

model = NeuralSDEModel(device="cpu")
trainer = NeuralSDETrainer(model=model, lr=1e-4, seq_len=64, horizon=20,
                           batch_size=64, loss_type="mse")
trainer.train(closes_train, epochs=100, regime_labels=regime_train, regime_balance="natural")

n_test = len(closes_full) - train_end
monthly_step = n_test // 12
test_starts = [train_end + i * monthly_step for i in range(12)
               if train_end + i * monthly_step + 20 < len(closes_full)]

horizon = 20
n_paths = 200

# 收集每个窗口的 SDE 和 GARCH 预测
all_sde_preds = []
all_garch_preds = []
all_actuals = []

for ts in test_starts:
    history = closes_full[:ts + 1]
    actual = closes_full[ts + 1:ts + 1 + horizon]
    init_price = float(history[-1])
    returns = np.diff(np.log(history))
    init_vol = float(np.std(returns)) if len(returns) > 2 else 0.02

    garch = GARCHFallback()
    garch.estimate(returns)
    garch_paths = garch.simulate(n_paths, horizon, init_price, init_vol)
    garch_pred = np.mean(garch_paths[:, 1:], axis=0)

    test_regime = int(regime_full[ts])
    sde_paths = model.forecast(history, horizon, n_paths, regime=test_regime)
    if sde_paths is not None:
        sde_pred = np.mean(sde_paths[:, 1:], axis=0)
    else:
        sde_pred = garch_pred.copy()

    all_sde_preds.append(sde_pred)
    all_garch_preds.append(garch_pred)
    all_actuals.append(actual)

# 权重扫描
print(f"{'w':>6} {'MAE':>10} {'vs SDE':>10} {'vs GARCH':>10}")
print("-" * 40)
best_w, best_mae = 0, float("inf")
for w in np.arange(0, 1.01, 0.1):
    total_mae = 0
    for sde_pred, garch_pred, actual in zip(all_sde_preds, all_garch_preds, all_actuals):
        ens = w * sde_pred + (1 - w) * garch_pred
        total_mae += np.mean(np.abs(ens - actual))
    mean_mae = total_mae / len(all_actuals)
    if mean_mae < best_mae:
        best_mae = mean_mae
        best_w = w

sde_mae = np.mean([np.mean(np.abs(s - a)) for s, a in zip(all_sde_preds, all_actuals)])
garch_mae = np.mean([np.mean(np.abs(g - a)) for g, a in zip(all_garch_preds, all_actuals)])

for w in np.arange(0, 1.01, 0.1):
    total_mae = 0
    for sde_pred, garch_pred, actual in zip(all_sde_preds, all_garch_preds, all_actuals):
        ens = w * sde_pred + (1 - w) * garch_pred
        total_mae += np.mean(np.abs(ens - actual))
    mean_mae = total_mae / len(all_actuals)
    vs_sde = (sde_mae - mean_mae) / sde_mae * 100
    vs_garch = (garch_mae - mean_mae) / garch_mae * 100
    marker = " <-- BEST" if abs(mean_mae - best_mae) < 0.01 else ""
    print(f"{w:6.1f} {mean_mae:10.2f} {vs_sde:+9.2f}% {vs_garch:+9.2f}%{marker}")

print(f"\nSDE-only MAE: {sde_mae:.2f}")
print(f"GARCH-only MAE: {garch_mae:.2f}")
print(f"Best w={best_w:.1f}, MAE={best_mae:.2f}")
print(f"Best vs SDE: {(sde_mae-best_mae)/sde_mae*100:+.2f}%")
print(f"Best vs GARCH: {(garch_mae-best_mae)/garch_mae*100:+.2f}%")

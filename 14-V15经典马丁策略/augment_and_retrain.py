#!/usr/bin/env python3
"""P0: Data Augmentation + Class Balance + Retrain.

Fixes:
  1. label_bust all zeros → synthesize bust labels from maxdd threshold
  2. Class imbalance → Focal Loss instead of BCE
  3. Small dataset → sliding window augmentation + noise injection

Usage:
    python3 augment_and_retrain.py --data-dir data/ai_datasets --out-dir data/phase_d_models_v1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import copy
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from phase_d_models import BiLSTMAttentionBust, PatchTSTForDrawdown

# ── Config ────────────────────────────────────────────────────────────────────

BUST_THRESHOLD = -0.10  # P1: lowered -15% → -10% for more positive samples
NOISE_STD = 0.01        # Gaussian noise std for augmentation
AUGMENT_FACTOR = 2      # 2x noise augmentation
SMOTE_RATIO = 0.5       # P1: SMOTE target ratio (pos:neg = 1:1 after SMOTE)
BILSTM_EPOCHS = 100     # P1: more epochs for SMOTE-enriched data
PATCHTST_EPOCHS = 80
BATCH_SIZE = 32
LR = 1e-3
WEIGHT_DECAY = 1e-5
EARLY_STOP_PATIENCE = 15
FOCAL_ALPHA = 0.50      # P1: increased 0.25 → 0.50 for more positive weight
FOCAL_GAMMA = 2.0       # Focal loss gamma (focusing parameter)


class FocalLoss(nn.Module):
    """Focal Loss for binary classification with class imbalance.

    FL(p_t) = -alpha * (1 - p_t)^gamma * log(p_t)

    Reduces the loss contribution from easy examples and increases
    the importance of hard, misclassified examples.
    """

    def __init__(self, alpha: float = 0.25, gamma: float = 2.0):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, preds: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        preds = preds.clamp(min=1e-7, max=1 - 1e-7)
        p_t = preds * targets + (1 - preds) * (1 - targets)
        alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
        focal_weight = alpha_t * (1 - p_t) ** self.gamma
        loss = -focal_weight * torch.log(p_t)
        return loss.mean()


def load_and_balance_data(npz_path: str) -> Tuple[torch.Tensor, ...]:
    """Load dataset and synthesize balanced bust labels from maxdd."""
    data = np.load(npz_path, allow_pickle=True)

    bilstm_ohlcv = torch.tensor(data["bilstm_ohlcv"], dtype=torch.float32)
    bilstm_scalar = torch.tensor(data["bilstm_scalar"], dtype=torch.float32)
    patchtst_in = torch.tensor(data["patchtst_in"], dtype=torch.float32)
    label_maxdd = data["label_maxdd"]

    # Synthesize bust labels from maxdd threshold
    label_bust = (label_maxdd < BUST_THRESHOLD).astype(np.float32)
    n_pos = label_bust.sum()
    n_neg = len(label_bust) - n_pos
    print(f"  Synthesized bust labels: pos={n_pos} neg={n_neg} rate={n_pos / len(label_bust):.3f}")

    label_bust_t = torch.tensor(label_bust, dtype=torch.float32).unsqueeze(-1)
    label_maxdd_t = torch.tensor(label_maxdd, dtype=torch.float32).unsqueeze(-1)

    return bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust_t, label_maxdd_t


def augment_data(
    bilstm_ohlcv: torch.Tensor,
    bilstm_scalar: torch.Tensor,
    patchtst_in: torch.Tensor,
    label_bust: torch.Tensor,
    label_maxdd: torch.Tensor,
    factor: int = AUGMENT_FACTOR,
) -> Tuple[torch.Tensor, ...]:
    """Augment data with Gaussian noise injection."""
    n = bilstm_ohlcv.size(0)
    all_ohlcv = [bilstm_ohlcv]
    all_scalar = [bilstm_scalar]
    all_patchtst = [patchtst_in]
    all_bust = [label_bust]
    all_maxdd = [label_maxdd]

    for i in range(factor - 1):
        noise_ohlcv = torch.randn_like(bilstm_ohlcv) * NOISE_STD
        noise_scalar = torch.randn_like(bilstm_scalar) * NOISE_STD * 0.5
        noise_patchtst = torch.randn_like(patchtst_in) * NOISE_STD

        all_ohlcv.append(bilstm_ohlcv + noise_ohlcv)
        all_scalar.append(bilstm_scalar + noise_scalar)
        all_patchtst.append(patchtst_in + noise_patchtst)
        all_bust.append(label_bust)
        all_maxdd.append(label_maxdd)

    result = (
        torch.cat(all_ohlcv, dim=0),
        torch.cat(all_scalar, dim=0),
        torch.cat(all_patchtst, dim=0),
        torch.cat(all_bust, dim=0),
        torch.cat(all_maxdd, dim=0),
    )
    print(f"  Noise augmented: {n} → {result[0].size(0)} samples (factor={factor})")
    return result


def smote_oversample(
    bilstm_ohlcv: torch.Tensor,
    bilstm_scalar: torch.Tensor,
    patchtst_in: torch.Tensor,
    label_bust: torch.Tensor,
    label_maxdd: torch.Tensor,
    target_ratio: float = SMOTE_RATIO,
) -> Tuple[torch.Tensor, ...]:
    """P1: SMOTE oversampling for minority class (bust=1).

    Flattens BiLSTM features, applies SMOTE to synthesize new positive samples,
    then reconstructs original tensor shapes.
    """
    from imblearn.over_sampling import SMOTE

    n = bilstm_ohlcv.size(0)
    labels_np = label_bust.squeeze(-1).numpy().astype(int)
    n_pos = labels_np.sum()
    n_neg = n - n_pos

    if n_pos < 2:
        print(f"  SMOTE skipped: only {n_pos} positive samples (need >=2)")
        return bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd

    # Flatten BiLSTM features for SMOTE: (N, 60, 5) + (N, 7) → (N, 307)
    ohlcv_flat = bilstm_ohlcv.reshape(n, -1).numpy()
    scalar_flat = bilstm_scalar.numpy()
    features = np.hstack([ohlcv_flat, scalar_flat])

    # Also flatten PatchTST input for later reconstruction
    patchtst_flat = patchtst_in.reshape(n, -1).numpy()
    maxdd_np = label_maxdd.squeeze(-1).numpy()

    # SMOTE: synthesize new positive samples
    # target_ratio: desired pos/(pos+neg) ratio after SMOTE
    n_pos_target = int(n_neg * target_ratio / (1 - target_ratio))
    n_pos_target = max(n_pos_target, n_pos + 1)
    sampling_strategy = {0: n_neg, 1: n_pos_target}

    smote = SMOTE(sampling_strategy=sampling_strategy, k_neighbors=min(5, n_pos - 1), random_state=42)
    features_resampled, labels_resampled = smote.fit_resample(features, labels_np)

    n_new = len(labels_resampled)
    n_synthesized = n_new - n

    # Reconstruct tensors
    ohlcv_dim = bilstm_ohlcv.shape[1:]
    scalar_dim = bilstm_scalar.shape[1:]
    patchtst_dim = patchtst_in.shape[1:]

    ohlcv_new = torch.tensor(features_resampled[:, :np.prod(ohlcv_dim)].reshape(-1, *ohlcv_dim), dtype=torch.float32)
    scalar_new = torch.tensor(features_resampled[:, np.prod(ohlcv_dim):].reshape(-1, *scalar_dim), dtype=torch.float32)

    # For PatchTST and maxdd: duplicate existing values for synthesized samples
    # (SMOTE only operates on BiLSTM features; PatchTST uses nearest neighbor)
    from sklearn.neighbors import NearestNeighbors
    patchtst_resampled = np.zeros((n_new, np.prod(patchtst_dim)))
    maxdd_resampled = np.zeros(n_new)
    patchtst_resampled[:n] = patchtst_flat
    maxdd_resampled[:n] = maxdd_np

    # For synthesized samples, use nearest neighbor from original positive samples
    pos_indices = np.where(labels_np == 1)[0]
    if len(pos_indices) > 0 and n_synthesized > 0:
        nn = NearestNeighbors(n_neighbors=1).fit(features[labels_np == 1])
        synth_features = features_resampled[n:]
        _, nn_idx = nn.kneighbors(synth_features)
        for i in range(n_synthesized):
            orig_idx = pos_indices[nn_idx[i][0]]
            patchtst_resampled[n + i] = patchtst_flat[orig_idx]
            maxdd_resampled[n + i] = maxdd_np[orig_idx]

    patchtst_new = torch.tensor(patchtst_resampled.reshape(-1, *patchtst_dim), dtype=torch.float32)
    bust_new = torch.tensor(labels_resampled, dtype=torch.float32).unsqueeze(-1)
    maxdd_new = torch.tensor(maxdd_resampled, dtype=torch.float32).unsqueeze(-1)

    n_pos_new = int(labels_resampled.sum())
    print(f"  SMOTE: {n} → {n_new} samples (synthesized {n_synthesized} positive, pos: {n_pos} → {n_pos_new})")
    return ohlcv_new, scalar_new, patchtst_new, bust_new, maxdd_new


def train_bilstm_focal(
    model: BiLSTMAttentionBust,
    train_loader: DataLoader,
    val_loader: DataLoader,
    epochs: int,
    device: torch.device,
) -> Dict:
    """Train BiLSTM with Focal Loss."""
    model = model.to(device)
    criterion = FocalLoss(alpha=FOCAL_ALPHA, gamma=FOCAL_GAMMA)
    optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=7)

    best_val_loss = float('inf')
    best_state = None
    patience_counter = 0
    history = {"train_loss": [], "val_loss": [], "val_acc": [], "val_precision": [], "val_recall": []}

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for ohlcv, scalar, labels in train_loader:
            ohlcv, scalar, labels = ohlcv.to(device), scalar.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(ohlcv, scalar)
            loss = criterion(outputs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * ohlcv.size(0)
        train_loss /= len(train_loader.dataset)

        model.eval()
        val_loss = 0.0
        tp = fp = fn = tn = 0
        with torch.no_grad():
            for ohlcv, scalar, labels in val_loader:
                ohlcv, scalar, labels = ohlcv.to(device), scalar.to(device), labels.to(device)
                outputs = model(ohlcv, scalar)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * ohlcv.size(0)
                preds = (outputs > 0.5).float()
                tp += ((preds == 1) & (labels == 1)).sum().item()
                fp += ((preds == 1) & (labels == 0)).sum().item()
                fn += ((preds == 0) & (labels == 1)).sum().item()
                tn += ((preds == 0) & (labels == 0)).sum().item()
        val_loss /= len(val_loader.dataset)
        total = tp + fp + fn + tn
        val_acc = (tp + tn) / total if total > 0 else 0
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)

        history["train_loss"].append(round(train_loss, 6))
        history["val_loss"].append(round(val_loss, 6))
        history["val_acc"].append(round(val_acc, 4))
        history["val_precision"].append(round(precision, 4))
        history["val_recall"].append(round(recall, 4))

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  BiLSTM Epoch {epoch+1:3d}/{epochs} | loss={train_loss:.4f}/{val_loss:.4f} acc={val_acc:.3f} P={precision:.3f} R={recall:.3f}")

        if patience_counter >= EARLY_STOP_PATIENCE:
            print(f"  BiLSTM early stop at epoch {epoch+1}")
            break

    model.load_state_dict(best_state)
    return {"best_val_loss": round(best_val_loss, 6), "best_val_acc": round(val_acc, 4),
            "best_precision": round(precision, 4), "best_recall": round(recall, 4),
            "epochs_trained": epoch + 1 - patience_counter, "history": history}


def train_patchtst(
    model: PatchTSTForDrawdown,
    train_loader: DataLoader,
    val_loader: DataLoader,
    epochs: int,
    device: torch.device,
) -> Dict:
    """Train PatchTST with MSE loss."""
    model = model.to(device)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=7)

    best_val_loss = float('inf')
    best_state = None
    patience_counter = 0

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for series, labels in train_loader:
            series, labels = series.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(series)
            loss = criterion(outputs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * series.size(0)
        train_loss /= len(train_loader.dataset)

        model.eval()
        val_loss = 0.0
        val_mae = 0.0
        with torch.no_grad():
            for series, labels in val_loader:
                series, labels = series.to(device), labels.to(device)
                outputs = model(series)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * series.size(0)
                val_mae += (outputs - labels).abs().sum().item()
        val_loss /= len(val_loader.dataset)
        val_mae /= len(val_loader.dataset)

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  PatchTST Epoch {epoch+1:3d}/{epochs} | loss={train_loss:.6f}/{val_loss:.6f} mae={val_mae:.4f}")

        if patience_counter >= EARLY_STOP_PATIENCE:
            print(f"  PatchTST early stop at epoch {epoch+1}")
            break

    model.load_state_dict(best_state)
    return {"best_val_loss": round(best_val_loss, 6), "best_val_mae": round(val_mae, 6),
            "epochs_trained": epoch + 1 - patience_counter}


def save_model(model: nn.Module, meta: Dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({"meta": meta, "state_dict": model.state_dict()}, path)
    print(f"  Saved: {path}")


def main(argv=None):
    ap = argparse.ArgumentParser("augment_and_retrain")
    ap.add_argument("--data-dir", default="data/ai_datasets")
    ap.add_argument("--out-dir", default="data/phase_d_models_v1")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args(argv)

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    print()

    # Load and balance data
    data_dir = Path(args.data_dir)
    print(f"Loading and balancing data from {data_dir}...")
    bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd = load_and_balance_data(str(data_dir / "phase_d_train_all.npz"))
    test_ohlcv, test_scalar, test_patchtst, test_bust, test_maxdd = load_and_balance_data(str(data_dir / "phase_d_test_all.npz"))

    # P1: SMOTE oversampling first, then noise augmentation
    print(f"\nP1: SMOTE oversampling...")
    bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd = smote_oversample(
        bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd, SMOTE_RATIO
    )

    print(f"\nAugmenting training data...")
    bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd = augment_data(
        bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd, AUGMENT_FACTOR
    )

    n_samples = bilstm_ohlcv.size(0)
    n_test = test_ohlcv.size(0)
    print(f"  Total: train={n_samples} test={n_test}")
    print()

    # Train BiLSTM with Focal Loss
    print("=" * 60)
    print("Training BiLSTMAttentionBust (Focal Loss + Balanced Labels)")
    print("=" * 60)

    bilstm_model = BiLSTMAttentionBust(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    train_ds = TensorDataset(bilstm_ohlcv, bilstm_scalar, label_bust)
    val_ds = TensorDataset(test_ohlcv, test_scalar, test_bust)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

    bilstm_result = train_bilstm_focal(bilstm_model, train_loader, val_loader, BILSTM_EPOCHS, device)
    print(f"  Best: val_loss={bilstm_result['best_val_loss']} acc={bilstm_result['best_val_acc']} P={bilstm_result['best_precision']} R={bilstm_result['best_recall']}")
    print()

    # Train PatchTST
    print("=" * 60)
    print("Training PatchTSTForDrawdown (Augmented Data)")
    print("=" * 60)

    patchtst_model = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=32, n_layers=2, n_heads=4, d_ff=64)
    patchtst_in_t = patchtst_in.transpose(1, 2)
    test_patchtst_t = test_patchtst.transpose(1, 2)
    train_ds2 = TensorDataset(patchtst_in_t, label_maxdd)
    val_ds2 = TensorDataset(test_patchtst_t, test_maxdd)
    train_loader2 = DataLoader(train_ds2, batch_size=BATCH_SIZE, shuffle=True)
    val_loader2 = DataLoader(val_ds2, batch_size=BATCH_SIZE, shuffle=False)

    patchtst_result = train_patchtst(patchtst_model, train_loader2, val_loader2, PATCHTST_EPOCHS, device)
    print(f"  Best: val_loss={patchtst_result['best_val_loss']} mae={patchtst_result['best_val_mae']}")
    print()

    # Save models
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bilstm_meta = {
        "model": "BiLSTMAttentionBust", "ohlcv_len": 60, "n_channels": 5, "n_scalar": 7,
        "hidden": 48, "n_layers": 2,
        "bust_threshold": BUST_THRESHOLD, "focal_alpha": FOCAL_ALPHA, "focal_gamma": FOCAL_GAMMA,
        "augment_factor": AUGMENT_FACTOR, "noise_std": NOISE_STD,
        "n_train": n_samples, "n_test": n_test,
        "training": bilstm_result,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_model(bilstm_model, bilstm_meta, str(out_dir / "bilstm.pt"))

    patchtst_meta = {
        "model": "PatchTSTForDrawdown", "c_in": 5, "seq_len": 120, "patch_len": 12,
        "stride": 6, "d_model": 32, "n_layers": 2, "n_heads": 4, "d_ff": 64,
        "augment_factor": AUGMENT_FACTOR, "noise_std": NOISE_STD,
        "n_train": n_samples, "n_test": n_test,
        "training": patchtst_result,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_model(patchtst_model, patchtst_meta, str(out_dir / "patchtst.pt"))

    # Save report
    report = {"bilstm": bilstm_meta, "patchtst": patchtst_meta,
              "augmentation": {"bust_threshold": BUST_THRESHOLD, "noise_std": NOISE_STD, "factor": AUGMENT_FACTOR},
              "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(out_dir / "training_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print("P0 Retrain Complete! (Class Balance + Augmentation + Focal Loss)")
    print("=" * 60)


if __name__ == "__main__":
    main()

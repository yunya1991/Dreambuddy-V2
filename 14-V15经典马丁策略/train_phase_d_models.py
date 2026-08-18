#!/usr/bin/env python3
"""Phase D Model Training Script — BiLSTM-Attention + PatchTST.

Trains both Phase D models on the generated dataset and saves .pt weights.

Usage:
    python3 train_phase_d_models.py --data-dir data/ai_datasets --out-dir data/phase_d_models_v1

Author: Dreambuddy-V2 DreamOS
Version: 1.0.0
Date: 2026-08-18
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

# Path setup
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from phase_d_models import BiLSTMAttentionBust, PatchTSTForDrawdown


# ── Training hyperparameters ──────────────────────────────────────────────────

BILSTM_EPOCHS = 50
BILSTM_BATCH_SIZE = 32
BILSTM_LR = 1e-3
BILSTM_WEIGHT_DECAY = 1e-5

PATCHTST_EPOCHS = 50
PATCHTST_BATCH_SIZE = 32
PATCHTST_LR = 1e-3
PATCHTST_WEIGHT_DECAY = 1e-5

EARLY_STOP_PATIENCE = 10


def load_dataset(npz_path: str) -> Tuple[torch.Tensor, ...]:
    """Load dataset from .npz file.

    Returns:
        bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd
    """
    data = np.load(npz_path, allow_pickle=True)
    
    bilstm_ohlcv = torch.tensor(data["bilstm_ohlcv"], dtype=torch.float32)
    bilstm_scalar = torch.tensor(data["bilstm_scalar"], dtype=torch.float32)
    patchtst_in = torch.tensor(data["patchtst_in"], dtype=torch.float32)
    label_bust = torch.tensor(data["label_bust"], dtype=torch.float32).unsqueeze(-1)
    label_maxdd = torch.tensor(data["label_maxdd"], dtype=torch.float32).unsqueeze(-1)
    
    return bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd


def train_bilstm(
    model: BiLSTMAttentionBust,
    train_loader: DataLoader,
    val_loader: DataLoader,
    epochs: int,
    lr: float,
    weight_decay: float,
    device: torch.device,
) -> Dict:
    """Train BiLSTMAttentionBust model."""
    model = model.to(device)
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
    
    best_val_loss = float('inf')
    best_state = None
    patience_counter = 0
    history = {"train_loss": [], "val_loss": [], "val_acc": []}
    
    for epoch in range(epochs):
        # Training
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
        
        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for ohlcv, scalar, labels in val_loader:
                ohlcv, scalar, labels = ohlcv.to(device), scalar.to(device), labels.to(device)
                outputs = model(ohlcv, scalar)
                loss = criterion(outputs, labels)
                val_loss += loss.item() * ohlcv.size(0)
                preds = (outputs > 0.5).float()
                correct += (preds == labels).sum().item()
                total += labels.size(0)
        val_loss /= len(val_loader.dataset)
        val_acc = correct / total if total > 0 else 0.0
        
        history["train_loss"].append(round(train_loss, 6))
        history["val_loss"].append(round(val_loss, 6))
        history["val_acc"].append(round(val_acc, 4))
        
        scheduler.step(val_loss)
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
        
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  BiLSTM Epoch {epoch+1:3d}/{epochs} | train_loss={train_loss:.4f} val_loss={val_loss:.4f} val_acc={val_acc:.3f}")
        
        if patience_counter >= EARLY_STOP_PATIENCE:
            print(f"  BiLSTM early stop at epoch {epoch+1}")
            break
    
    model.load_state_dict(best_state)
    return {"best_val_loss": round(best_val_loss, 6), "best_val_acc": round(val_acc, 4), "epochs_trained": epoch + 1 - patience_counter, "history": history}


def train_patchtst(
    model: PatchTSTForDrawdown,
    train_loader: DataLoader,
    val_loader: DataLoader,
    epochs: int,
    lr: float,
    weight_decay: float,
    device: torch.device,
) -> Dict:
    """Train PatchTSTForDrawdown model."""
    model = model.to(device)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
    
    best_val_loss = float('inf')
    best_state = None
    patience_counter = 0
    history = {"train_loss": [], "val_loss": [], "val_mae": []}
    
    for epoch in range(epochs):
        # Training
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
        
        # Validation
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
        
        history["train_loss"].append(round(train_loss, 6))
        history["val_loss"].append(round(val_loss, 6))
        history["val_mae"].append(round(val_mae, 6))
        
        scheduler.step(val_loss)
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
        
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  PatchTST Epoch {epoch+1:3d}/{epochs} | train_loss={train_loss:.6f} val_loss={val_loss:.6f} val_mae={val_mae:.4f}")
        
        if patience_counter >= EARLY_STOP_PATIENCE:
            print(f"  PatchTST early stop at epoch {epoch+1}")
            break
    
    model.load_state_dict(best_state)
    return {"best_val_loss": round(best_val_loss, 6), "best_val_mae": round(val_mae, 6), "epochs_trained": epoch + 1 - patience_counter, "history": history}


def save_model(model: nn.Module, meta: Dict, path: str) -> None:
    """Save model weights with metadata."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "meta": meta,
        "state_dict": model.state_dict(),
    }
    torch.save(payload, path)
    print(f"  Saved: {path}")


def main(argv=None):
    ap = argparse.ArgumentParser("train_phase_d_models")
    ap.add_argument("--data-dir", default="data/ai_datasets", help="训练数据目录")
    ap.add_argument("--out-dir", default="data/phase_d_models_v1", help="模型输出目录")
    ap.add_argument("--device", default="cpu", help="训练设备 (cpu/cuda)")
    ap.add_argument("--bilstm-epochs", type=int, default=BILSTM_EPOCHS)
    ap.add_argument("--patchtst-epochs", type=int, default=PATCHTST_EPOCHS)
    args = ap.parse_args(argv)
    
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    print()
    
    # Load dataset
    data_dir = Path(args.data_dir)
    train_path = data_dir / "phase_d_train_all.npz"
    test_path = data_dir / "phase_d_test_all.npz"
    
    if not train_path.exists():
        print(f"ERROR: Training data not found: {train_path}")
        sys.exit(1)
    
    print(f"Loading training data from {train_path}...")
    bilstm_ohlcv, bilstm_scalar, patchtst_in, label_bust, label_maxdd = load_dataset(str(train_path))
    n_samples = bilstm_ohlcv.size(0)
    print(f"  Samples: {n_samples}")
    print(f"  BiLSTM OHLCV: {bilstm_ohlcv.shape}")
    print(f"  BiLSTM Scalar: {bilstm_scalar.shape}")
    print(f"  PatchTST Input: {patchtst_in.shape}")
    print(f"  Label Bust: {label_bust.shape} (pos={label_bust.sum().item():.0f})")
    print(f"  Label MaxDD: {label_maxdd.shape} (mean={label_maxdd.mean().item():.4f})")
    print()
    
    # Train/val split (80/20)
    n_train = int(n_samples * 0.8)
    indices = torch.randperm(n_samples)
    train_idx = indices[:n_train]
    val_idx = indices[n_train:]
    
    # ── Train BiLSTMAttentionBust ──────────────────────────────────────────
    print("=" * 60)
    print("Training BiLSTMAttentionBust (Bust Prediction)")
    print("=" * 60)
    
    bilstm_model = BiLSTMAttentionBust(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    
    train_ds = TensorDataset(bilstm_ohlcv[train_idx], bilstm_scalar[train_idx], label_bust[train_idx])
    val_ds = TensorDataset(bilstm_ohlcv[val_idx], bilstm_scalar[val_idx], label_bust[val_idx])
    train_loader = DataLoader(train_ds, batch_size=BILSTM_BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BILSTM_BATCH_SIZE, shuffle=False)
    
    bilstm_result = train_bilstm(bilstm_model, train_loader, val_loader, args.bilstm_epochs, BILSTM_LR, BILSTM_WEIGHT_DECAY, device)
    print(f"  Best val_loss: {bilstm_result['best_val_loss']}, val_acc: {bilstm_result['best_val_acc']}")
    print()
    
    # ── Train PatchTSTForDrawdown ──────────────────────────────────────────
    print("=" * 60)
    print("Training PatchTSTForDrawdown (Drawdown Prediction)")
    print("=" * 60)
    
    patchtst_model = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6, d_model=32, n_layers=2, n_heads=4, d_ff=64)
    
    # PatchTST expects (batch, c_in, seq_len); dataset has (batch, seq_len, c_in)
    patchtst_in_t = patchtst_in.transpose(1, 2)  # (N, c_in, seq_len)
    train_ds2 = TensorDataset(patchtst_in_t[train_idx], label_maxdd[train_idx])
    val_ds2 = TensorDataset(patchtst_in_t[val_idx], label_maxdd[val_idx])
    train_loader2 = DataLoader(train_ds2, batch_size=PATCHTST_BATCH_SIZE, shuffle=True)
    val_loader2 = DataLoader(val_ds2, batch_size=PATCHTST_BATCH_SIZE, shuffle=False)
    
    patchtst_result = train_patchtst(patchtst_model, train_loader2, val_loader2, args.patchtst_epochs, PATCHTST_LR, PATCHTST_WEIGHT_DECAY, device)
    print(f"  Best val_loss: {patchtst_result['best_val_loss']}, val_mae: {patchtst_result['best_val_mae']}")
    print()
    
    # ── Save models ────────────────────────────────────────────────────────
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    bilstm_meta = {
        "model": "BiLSTMAttentionBust",
        "ohlcv_len": 60,
        "n_channels": 5,
        "n_scalar": 7,
        "hidden": 48,
        "n_layers": 2,
        "n_samples": n_samples,
        "n_train": n_train,
        "n_val": n_samples - n_train,
        "training": bilstm_result,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_model(bilstm_model, bilstm_meta, str(out_dir / "bilstm.pt"))
    
    patchtst_meta = {
        "model": "PatchTSTForDrawdown",
        "c_in": 5,
        "seq_len": 120,
        "patch_len": 12,
        "stride": 6,
        "d_model": 32,
        "n_layers": 2,
        "n_heads": 4,
        "d_ff": 64,
        "n_samples": n_samples,
        "n_train": n_train,
        "n_val": n_samples - n_train,
        "training": patchtst_result,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_model(patchtst_model, patchtst_meta, str(out_dir / "patchtst.pt"))
    
    # ── Save training report ───────────────────────────────────────────────
    report = {
        "bilstm": bilstm_meta,
        "patchtst": patchtst_meta,
        "dataset": {
            "source": str(train_path),
            "n_samples": n_samples,
            "n_train": n_train,
            "n_val": n_samples - n_train,
        },
        "device": str(device),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    report_path = out_dir / "training_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  Report: {report_path}")
    
    print()
    print("=" * 60)
    print("Training complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

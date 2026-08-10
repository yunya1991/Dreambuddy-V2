#!/usr/bin/env python3
"""
Phase D · BiLSTM-Attention 爆仓预测训练脚本

使用：
    # 从 phase_d_dataset_generator 产生的 NPZ 直接训
    python3 phase_d_train_bilstm.py \
        --data data/ai_datasets/phase_d_train_all.npz \
        --val  data/ai_datasets/phase_d_test_all.npz \
        --epochs 20 --batch 64 --lr 1e-3 \
        --out data/ai_models/phase_d_bilstm_v1.pt

    # 冒烟快速跑（不读 NPZ，用内置随机假数据跑 1 epoch 并保存权重）
    python3 phase_d_train_bilstm.py --quick-smoke --epochs 1 \
        --out /tmp/bilstm_smoke.pt

输出：
    *.pt 权重文件（torch.save state_dict）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "ai_trainers"))

from phase_d_models import BiLSTMAttentionBust  # noqa: E402


def _load_npz_split(npz_path: Path):
    data = np.load(npz_path)
    ohlcv = torch.from_numpy(data["bilstm_ohlcv"]).float()
    scalar = torch.from_numpy(data["bilstm_scalar"]).float()
    y = torch.from_numpy(data["label_bust"]).float().unsqueeze(-1)
    return TensorDataset(ohlcv, scalar, y)


def _make_smoke_dataset(n=128, seed=1):
    rng = torch.Generator().manual_seed(seed)
    ohlcv = torch.randn(n, 60, 5, generator=rng)
    scalar = torch.randn(n, 7, generator=rng)
    y = torch.rand(n, 1, generator=rng)  # 标签 [0,1]
    return TensorDataset(ohlcv, scalar, y), TensorDataset(ohlcv[-32:], scalar[-32:], y[-32:])


def compute_balanced_bce(pred: Tensor, y: Tensor) -> Tensor:
    """F.binary_cross_entropy 本身不支持 pos_weight 关键字；手动给正样本加权。"""
    pos_mask = (y > 0.5).float()
    neg_mask = 1.0 - pos_mask
    pos_w = (neg_mask.sum() / max(1, pos_mask.sum())).clamp(min=0.2, max=5.0)
    weight = pos_mask * pos_w + neg_mask * 1.0
    pointwise = F.binary_cross_entropy(pred, y, reduction="none")
    return (pointwise * weight).mean()


def train_one_epoch(model, loader, opt, device):
    model.train()
    tot, loss_sum, correct, total = 0, 0.0, 0, 0
    for ohlcv, s, y in loader:
        ohlcv, s, y = ohlcv.to(device), s.to(device), y.to(device)
        opt.zero_grad()
        p = model(ohlcv, s)
        loss = compute_balanced_bce(p, y)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        bs = y.shape[0]
        tot += bs
        loss_sum += float(loss.item()) * bs
        correct += int(((p > 0.5).long() == y.long()).sum().item())
        total += bs
    return loss_sum / max(1, tot), correct / max(1, total)


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    preds, ys = [], []
    for ohlcv, s, y in loader:
        ohlcv, s = ohlcv.to(device), s.to(device)
        p = model(ohlcv, s)
        preds.append(p.cpu())
        ys.append(y)
    p = torch.cat(preds, dim=0).squeeze(-1)
    y = torch.cat(ys, dim=0).squeeze(-1)
    bce = F.binary_cross_entropy(p, y)
    acc = float(((p > 0.5).long() == y.long()).float().mean().item())
    # 简单 AUC 近似（按 label 分位数排序一致率）
    try:
        from sklearn.metrics import roc_auc_score  # type: ignore

        auc = float(roc_auc_score(y.numpy(), p.numpy()))
    except Exception:
        auc = float("nan")
    return {"bce": float(bce.item()), "acc": acc, "auc": auc}


def main(argv=None):
    ap = argparse.ArgumentParser("phase_d_train_bilstm")
    ap.add_argument("--data", type=str, default="data/ai_datasets/phase_d_train_all.npz")
    ap.add_argument("--val", type=str, default="data/ai_datasets/phase_d_test_all.npz")
    ap.add_argument("--out", type=str, default="data/ai_models/phase_d_bilstm_v1.pt")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--hidden", type=int, default=48)
    ap.add_argument("--n-layers", type=int, default=2)
    ap.add_argument("--quick-smoke", action="store_true",
                    help="跳过读NPZ，使用内置假数据，用于CLI冒烟测试")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    device = torch.device("cpu")  # MVP：CPU 即可，小模型 <2M 参数量
    # quick-smoke 优先级最高，跳过 NPZ 读取（避免传入无效文件）
    if args.quick_smoke:
        tr_ds, va_ds = _make_smoke_dataset(128, args.seed)
    else:
        tr_ds = _load_npz_split(Path(args.data))
        va_ds = _load_npz_split(Path(args.val))
    tr_ld = DataLoader(tr_ds, batch_size=args.batch, shuffle=True, drop_last=False)
    va_ld = DataLoader(va_ds, batch_size=args.batch * 2, shuffle=False)

    model = BiLSTMAttentionBust(hidden=args.hidden, n_layers=args.n_layers).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[BiLSTM] params={n_params:,}  device={device}  train_samples={len(tr_ds)}  val_samples={len(va_ds)}")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.epochs))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    best_auc = -1.0
    best_state = None
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        tr_loss, tr_acc = train_one_epoch(model, tr_ld, opt, device)
        metrics = evaluate(model, va_ld, device)
        sched.step()
        dt = time.time() - t0
        print(
            f"[BiLSTM] epoch={epoch:02d}/{args.epochs}  loss={tr_loss:.4f}  tr_acc={tr_acc:.2%}  "
            f"val_bce={metrics['bce']:.4f}  val_acc={metrics['acc']:.2%}  val_auc={metrics['auc']:.3f}  dt={dt:.1f}s"
        )
        if (not np.isnan(metrics["auc"])) and metrics["auc"] > best_auc:
            best_auc = metrics["auc"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    # 保存权重 + 元信息
    payload = {
        "state_dict": best_state,
        "meta": {
            "ohlcv_len": 60, "n_channels": 5, "n_scalar": 7,
            "hidden": args.hidden, "n_layers": args.n_layers,
            "best_val_auc": best_auc, "epochs": args.epochs, "seed": args.seed,
            "quick_smoke": bool(args.quick_smoke),
            "train_date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }
    torch.save(payload, args.out)
    print(f"[BiLSTM] 权重已保存: {args.out}  (best_auc={best_auc:.3f})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Phase D · PatchTST 回撤深度预测训练脚本

使用：
    python3 phase_d_train_patchtst.py \
        --data data/ai_datasets/phase_d_train_all.npz \
        --val  data/ai_datasets/phase_d_test_all.npz \
        --epochs 20 --batch 64 --lr 1e-3 \
        --out data/ai_models/phase_d_patchtst_v1.pt

    # CLI 冒烟
    python3 phase_d_train_patchtst.py --quick-smoke --epochs 1 --out /tmp/patch_smoke.pt
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "ai_trainers"))

from phase_d_models import PatchTSTForDrawdown  # noqa: E402


def _load_npz_split(npz_path: Path):
    data = np.load(npz_path)
    x = torch.from_numpy(data["patchtst_in"]).float()
    y = torch.from_numpy(data["label_maxdd"]).float().unsqueeze(-1)
    return TensorDataset(x, y)


def _make_smoke_dataset(n=128, seed=1):
    rng = torch.Generator().manual_seed(seed)
    x = torch.randn(n, 120, 5, generator=rng)
    # 标签生成：取窗口最小值占比近似
    mins = x[:, -24:, 2].min(dim=1).values  # 未来 24 low (本窗口中最后24)
    lasts = x[:, -24:-23, 3].squeeze(1)      # 起点收盘价
    y = (mins - lasts) / lasts.clamp_min(1e-6)
    y = y.unsqueeze(-1).float().clamp_min(-1.0).clamp_max(0.0)
    return TensorDataset(x, y), TensorDataset(x[-32:], y[-32:])


def huber_loss(pred: torch.Tensor, target: torch.Tensor, delta=0.03) -> torch.Tensor:
    """回撤是小量级（%级），Huber 稳于纯 MSE"""
    return F.huber_loss(pred, target, delta=delta)


def train_one_epoch(model, loader, opt, device):
    model.train()
    tot, loss_sum = 0, 0.0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        opt.zero_grad()
        p = model(x)
        loss = huber_loss(p, y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        bs = y.shape[0]
        tot += bs
        loss_sum += float(loss.item()) * bs
    return loss_sum / max(1, tot)


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    preds, ys = [], []
    for x, y in loader:
        x = x.to(device)
        p = model(x)
        preds.append(p.cpu())
        ys.append(y)
    p = torch.cat(preds, dim=0).squeeze(-1)
    y = torch.cat(ys, dim=0).squeeze(-1)
    mse = float(F.mse_loss(p, y).item())
    mae = float(F.l1_loss(p, y).item())
    # 方向准确率：预测是否 ≤-0.08 （触及首档加仓线）和真实同号
    pred_dir = (p <= -0.08).long()
    true_dir = (y <= -0.08).long()
    acc8 = float((pred_dir == true_dir).float().mean().item())
    return {"mse": mse, "mae": mae, "hit8pct_acc": acc8}


def main(argv=None):
    ap = argparse.ArgumentParser("phase_d_train_patchtst")
    ap.add_argument("--data", type=str, default="data/ai_datasets/phase_d_train_all.npz")
    ap.add_argument("--val", type=str, default="data/ai_datasets/phase_d_test_all.npz")
    ap.add_argument("--out", type=str, default="data/ai_models/phase_d_patchtst_v1.pt")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patch-len", type=int, default=12)
    ap.add_argument("--stride", type=int, default=6)
    ap.add_argument("--d-model", type=int, default=32)
    ap.add_argument("--n-layers", type=int, default=2)
    ap.add_argument("--n-heads", type=int, default=4)
    ap.add_argument("--quick-smoke", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cpu")

    # quick-smoke 优先级最高，不读 NPZ（防止调用方传无效路径 bytes dummy 等）
    if args.quick_smoke:
        tr_ds, va_ds = _make_smoke_dataset(128, args.seed)
    else:
        tr_ds = _load_npz_split(Path(args.data))
        va_ds = _load_npz_split(Path(args.val))
    tr_ld = DataLoader(tr_ds, batch_size=args.batch, shuffle=True)
    va_ld = DataLoader(va_ds, batch_size=args.batch * 2, shuffle=False)

    model = PatchTSTForDrawdown(
        c_in=5, seq_len=120, patch_len=args.patch_len, stride=args.stride,
        d_model=args.d_model, n_layers=args.n_layers, n_heads=args.n_heads,
    ).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[PatchTST] params={n_params:,}  num_patches={model.num_patches}  device={device}  "
          f"train_samples={len(tr_ds)}  val_samples={len(va_ds)}")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.epochs))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    best_mse = float("inf")
    best_state = None
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        loss = train_one_epoch(model, tr_ld, opt, device)
        m = evaluate(model, va_ld, device)
        sched.step()
        dt = time.time() - t0
        print(
            f"[PatchTST] epoch={epoch:02d}/{args.epochs}  huber={loss:.5f}  "
            f"val_mse={m['mse']:.5f}  val_mae={m['mae']:.4f}  hit8pct_acc={m['hit8pct_acc']:.2%}  dt={dt:.1f}s"
        )
        if m["mse"] < best_mse:
            best_mse = m["mse"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    payload = {
        "state_dict": best_state,
        "meta": {
            "c_in": 5, "seq_len": 120, "patch_len": args.patch_len, "stride": args.stride,
            "d_model": args.d_model, "n_layers": args.n_layers, "n_heads": args.n_heads,
            "best_val_mse": best_mse, "epochs": args.epochs, "seed": args.seed,
            "quick_smoke": bool(args.quick_smoke),
            "train_date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }
    torch.save(payload, args.out)
    print(f"[PatchTST] 权重已保存: {args.out}  (best_mse={best_mse:.5f})")


if __name__ == "__main__":
    main()

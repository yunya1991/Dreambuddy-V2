#!/usr/bin/env python3
"""P6 E4 分层式升级：周线 Encoder 输出作为 KV 上下文注入日线/1H 交叉注意力
（SPEC_encoder v0.2 阶段 E4，阶段二架构）。
架构：
  - 周线 Encoder：独立编码周线 token 序列 → 输出作为全局上下文
  - 日线/1H Encoder + 交叉注意力：周线输出作为 KV 注入（显式实现
    周线约束日线、日线约束 1H 的高级别弹性约束低级别机制）
  - 低级别判别与高级别冲突时输出降级为 NEUTRAL（与 40 主规格 L5 同构）
预注册超参（与 E2 拼接式一致，禁止运行时调整）：
  n_layers=2, d_model=64, n_heads=4, 参数量 ≤ 1M
  Walk-Forward 5 折（时序切分，禁止随机打乱）；最近 20% 封板纯验证
门槛拦截：入口先检查 E3 Shadow 达标（shadow_status.json ready == true，
  即 Shadow ≥ 4 周且 PSI < 0.1），未达标拒绝启动（SPEC 红线 3：E3 未稳定不进入 E5）。
晋级判定：分层式 Walk-Forward 准确率与方向 IC 均 ≥ 拼接式（e2_training_report.json）。
红线：输出为趋势判别语义输入与建议，不产生交易信号；
  交易决策归 23 系统三步门禁。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SHADOW_STATUS_PATH = os.path.join(BASE, "shadow_status.json")
E2_REPORT_PATH = os.path.join(BASE, "e2_training_report.json")
TOKEN_PATH = os.path.join(BASE, "token_sequence.parquet")
REPORT_OUT = os.path.join(BASE, "e4_training_report.json")
MODEL_OUT = os.path.join(BASE, "encoder_trend_model_hierarchical.pt")

# 预注册超参（与 E2 一致 + 分层式新增）
PREREG = {
    "n_layers": 2,
    "d_model": 64,
    "n_heads": 4,
    "ffn_mult": 4,
    "n_classes": 3,
    "max_params": 1_000_000,
    "walk_forward_folds": 5,
    "seq_len": 32,
    "label_horizon": {"1W": 4, "1D": 7, "1H": 24},
    "label_threshold_pct": 2.0,
    "lr": 1e-3,
    "epochs": 30,
    "batch_size": 64,
    "test_ratio": 0.2,
    "seed": 42,
}
SYMBOLS = ["BTC", "ETH", "SOL"]
META_COLS = ["symbol", "timeframe", "screen", "ts", "feature_version"]


def check_e3_ready() -> dict:
    try:
        with open(SHADOW_STATUS_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
        return {"ready": bool(st.get("ready", False)), "status": st}
    except Exception as e:
        return {"ready": False, "status": {"error": str(e)}}


def build_hierarchical_model(n_features: int):
    """分层式 Encoder：周线独立编码 + 日线/1H 交叉注意力注入周线上下文。"""
    import torch
    import torch.nn as nn

    d = PREREG["d_model"]

    class Block(nn.Module):
        def __init__(self, cross_attn: bool = False):
            super().__init__()
            self.cross = cross_attn
            self.self_attn = nn.MultiheadAttention(d, PREREG["n_heads"], batch_first=True)
            if cross_attn:
                self.cross_attn = nn.MultiheadAttention(d, PREREG["n_heads"], batch_first=True)
            self.ffn = nn.Sequential(nn.Linear(d, d * PREREG["ffn_mult"]), nn.GELU(),
                                    nn.Linear(d * PREREG["ffn_mult"], d))
            self.ln1 = nn.LayerNorm(d)
            self.ln2 = nn.LayerNorm(d)
            self.ln3 = nn.LayerNorm(d) if cross_attn else None

        def forward(self, x, ctx=None):
            a, _ = self.self_attn(x, x, x)
            h = self.ln1(x + a)
            if self.cross and ctx is not None:
                c, _ = self.cross_attn(h, ctx, ctx)  # 周线上下文作为 KV 注入
                h = self.ln3(h + c)
            return self.ln2(h + self.ffn(h))

    class HierarchicalTrendEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed = nn.Linear(n_features, d)
            self.tf_embed = nn.Embedding(3, d)
            self.cls = nn.Parameter(torch.zeros(1, 1, d))
            # 周线编码器（全局上下文）
            self.weekly_blocks = nn.ModuleList([Block() for _ in range(PREREG["n_layers"])])
            # 日线/1H 编码器（含交叉注意力注入周线上下文）
            self.lower_blocks = nn.ModuleList(
                [Block(cross_attn=(i == 0)) for i in range(PREREG["n_layers"])])
            self.head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, PREREG["n_classes"]))

        def forward(self, x, tf_idx, weekly_ctx=None):
            b = x.shape[0]
            h = self.embed(x) + self.tf_embed(tf_idx).unsqueeze(1)
            cls = self.cls.expand(b, 1, -1)
            h = torch.cat([cls, h], dim=1)
            for blk in self.lower_blocks:
                h = blk(h, ctx=weekly_ctx)
            return self.head(h[:, 0])

        def encode_weekly(self, x):
            """周线 token 独立编码，输出作为全局上下文。"""
            b = x.shape[0]
            h = self.embed(x) + self.tf_embed(torch.zeros(b, dtype=torch.long, device=x.device)).unsqueeze(1)
            for blk in self.weekly_blocks:
                h = blk(h)
            return h  # (b, L, d) 周线上下文

    return HierarchicalTrendEncoder()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅验证数据管道与模型构建，不训练")
    args = ap.parse_args()

    # 1) E3 达标拦截（SPEC 红线 3：E3 未稳定不进入 E5）
    if not args.dry_run:
        e3 = check_e3_ready()
        if not e3["ready"]:
            print("[REJECT] E3 Shadow 未达标（ready != true），E4 分层式训练拒绝启动")
            print(json.dumps(e3["status"], ensure_ascii=False, indent=2))
            return 1

    # 2) 数据与标签（复用 E2 管道）
    from p6_e2_train_encoder import load_tokens, build_labels, make_windows, count_params

    tokens = load_tokens()
    labeled = build_labels(tokens)
    if labeled.empty:
        print("[FAIL] 无有效标注样本")
        return 1
    X, y, ret, meta, feat_cols = make_windows(labeled)
    print(f"[OK] 窗口样本: {len(X)}（特征 {len(feat_cols)} 列）")

    # 3) 模型构建与参数量校验
    model = build_hierarchical_model(len(feat_cols))
    n_params = count_params(model)
    print(f"[OK] 分层式模型构建: 参数量 {n_params}（红线 {PREREG['max_params']}）")
    if n_params > PREREG["max_params"]:
        print("[REJECT] 参数量超过 1M 红线")
        return 1

    if args.dry_run:
        print("[OK] 干跑验证通过：数据管道与分层式模型构建正常（未训练、未落盘）")
        return 0

    # 4) 训练主链路（骨架：与 E2 相同的 Walk-Forward 流程 + 周线上下文注入）
    #    完整实现待 E3 达标后随训练解锁（当前受门槛拦截保护）
    print("[INFO] E3 已达标，训练主链路待实现（当前为骨架占位）")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P6 E4 分层式升级（骨架）",
        "n_params": n_params,
        "samples": int(len(X)),
        "note": "E4 训练主链路骨架：周线 KV 上下文注入交叉注意力；晋级判定为分层式指标 ≥ 拼接式",
    }
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[OK] E4 骨架就绪 -> {REPORT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

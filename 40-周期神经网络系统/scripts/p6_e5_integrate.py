#!/usr/bin/env python3
"""P6 E5 接入主链路：trend_classification 输出作为 40 系统 L2 周期判定的
语义输入（SPEC_encoder v0.2 阶段 E5）。
定位声明（v0.2）：本输出是 L2 周期判定模块的语义输入之一，
  不替代、不绕过周期判定状态机（真实周期/理论周期仍归 40 主链路 L2）。
产出：trend_classification.json
  {direction, confidence, calibrated_prob, feature_version, model_version,
   per_symbol_timeframe: {...}, disclaimer, research_only}
门槛拦截：入口先检查 E4 晋级判定（e4_training_report.json 的
  hierarchical_passed == true，即分层式 ≥ 拼接式），未通过拒绝启动
  （SPEC 红线 3：E3 未稳定不进入 E5；E4 未超拼接式不进入 E5）。
红线：输出为周期判定的语义输入与建议，不产生交易信号；
  交易决策归 23 系统三步门禁；与 40 L2 周期判定信号冲突时
  以 40 L2 为高级别约束（高级别弹性约束低级别）。
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

E4_REPORT_PATH = os.path.join(BASE, "e4_training_report.json")
MODEL_PATH = os.path.join(BASE, "encoder_trend_model_hierarchical.pt")
TOKEN_PATH = os.path.join(BASE, "token_sequence.parquet")
OUT_PATH = os.path.join(BASE, "trend_classification.json")

SYMBOLS = ["BTC", "ETH", "SOL"]
SCREENS = ["1W", "1D", "1H"]


def check_e4_passed() -> dict:
    try:
        with open(E4_REPORT_PATH, "r", encoding="utf-8") as f:
            r = json.load(f)
        return {"passed": bool(r.get("hierarchical_passed", False)), "report": r}
    except Exception as e:
        return {"passed": False, "report": {"error": str(e)}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅验证数据与模型加载，不落盘")
    args = ap.parse_args()

    # 1) E4 晋级判定拦截（SPEC 红线 3）
    if not args.dry_run:
        e4 = check_e4_passed()
        if not e4["passed"]:
            print("[REJECT] E4 晋级判定未通过（hierarchical_passed != true），E5 接入拒绝启动")
            return 1

    # 2) 加载分层式模型与最新 token 窗口
    import torch
    from p6_e4_hierarchical_train import build_hierarchical_model
    from p6_e2_train_encoder import PREREG as E2_PREREG

    if not os.path.exists(MODEL_PATH):
        print(f"[FAIL] 分层式模型不存在: {MODEL_PATH}")
        return 1

    ckpt = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
    feat_cols = ckpt["feature_cols"]
    model = build_hierarchical_model(len(feat_cols))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    tokens = pd.read_parquet(TOKEN_PATH).sort_values(["symbol", "timeframe", "ts"]).reset_index(drop=True)
    L = E2_PREREG["seq_len"]
    tf_map = {"1W": 0, "1D": 1, "1H": 2}

    feat_vals = tokens[feat_cols].to_numpy(dtype=np.float32)
    mu = np.nanmean(feat_vals, axis=0)
    sd = np.nanstd(feat_vals, axis=0) + 1e-8

    now_iso = datetime.now(timezone.utc).isoformat()
    per_st = {}
    for sym in SYMBOLS:
        for bar in SCREENS:
            sub = tokens[(tokens["symbol"] == sym) & (tokens["timeframe"] == bar)].sort_values("ts")
            if len(sub) < L:
                continue
            win = sub[feat_cols].iloc[-L:].to_numpy(dtype=np.float32)
            win = np.nan_to_num((win - mu) / sd, nan=0.0)
            x = torch.from_numpy(win).unsqueeze(0)
            tf = torch.tensor([tf_map[bar]])
            with torch.no_grad():
                # 周线上下文：同资产周线窗口独立编码
                wsub = tokens[(tokens["symbol"] == sym) & (tokens["timeframe"] == "1W")].sort_values("ts")
                wwin = wsub[feat_cols].iloc[-L:].to_numpy(dtype=np.float32)
                wwin = np.nan_to_num((wwin - mu) / sd, nan=0.0)
                wctx = model.encode_weekly(torch.from_numpy(wwin).unsqueeze(0))
                logits = model(x, tf, weekly_ctx=wctx)
                prob = torch.softmax(logits, dim=1)[0].numpy()
            cls = int(np.argmax(prob))
            direction = {0: "NEUTRAL", 1: "UP", 2: "DOWN"}[cls]
            per_st[f"{sym}_{bar}"] = {
                "direction": direction,
                "confidence": float(prob[cls]),
                "calibrated_prob": {"UP": float(prob[1]), "NEUTRAL": float(prob[0]), "DOWN": float(prob[2])},
            }

    if args.dry_run:
        print(f"[OK] 干跑验证通过：模型加载与推理正常（{len(per_st)} 条判别，未落盘）")
        return 0

    # 3) 落盘 trend_classification.json（L2 周期判定的语义输入）
    out = {
        "generated_at": now_iso,
        "module": "P6 E5 trend_classification（40 L2 周期判定语义输入）",
        "model_version": "encoder_hierarchical_v1",
        "feature_version": str(tokens["feature_version"].iloc[-1]),
        "per_symbol_timeframe": per_st,
        "disclaimer": "研究建议，非交易信号；本输出为周期判定的语义输入，不替代周期判定状态机",
        "research_only": True,
        "boundary": "与 40 L2 周期判定信号冲突时以 40 L2 为高级别约束；交易决策归 23 系统三步门禁",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] E5 trend_classification -> {OUT_PATH}")
    for k, v in per_st.items():
        print(f"     {k}: {v['direction']} (conf {v['confidence']:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

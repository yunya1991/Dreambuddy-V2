#!/usr/bin/env python3
"""P6 E3 Shadow 运行：实盘旁路并行推理，不产生交易影响（SPEC_encoder v0.2 阶段 E3）。
机制：
  - 每日旁路推理：加载 encoder_trend_model.pt，对三资产最新 token 窗口预测，
    落盘 shadow_predictions.jsonl（追加式，含时间戳/方向/置信度/校准概率）
  - PSI 分布稳定性监测：滚动窗口对比预测概率分布（UP 概率十分位），
    PSI < 0.1 达标（预注册，禁止调整）
  - Shadow 达标判定：运行 ≥ 4 周（预测流时间跨度）且 PSI 达标
  - 门槛拦截：入口先检查 E2 晋级判定（e2_training_report.json 的
    baseline_comparison.e2_passed == true），未通过拒绝启动（SPEC 红线 3：
    E2 未超基线不进入 E3）
  - --dry-run 模式仅验证数据与模型加载，不落盘预测，不受门槛拦截
红线：Shadow 输出为旁路观测，不产生交易信号，不影响任何交易链路；
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

MODEL_PATH = os.path.join(BASE, "encoder_trend_model.pt")
E2_REPORT_PATH = os.path.join(BASE, "e2_training_report.json")
TOKEN_PATH = os.path.join(BASE, "token_sequence.parquet")
PRED_OUT = os.path.join(BASE, "shadow_predictions.jsonl")
SHADOW_STATUS_OUT = os.path.join(BASE, "shadow_status.json")

# 预注册参数（禁止运行时调整）
PREREG = {
    "min_weeks": 4,        # Shadow 运行 ≥ 4 周
    "psi_threshold": 0.1,  # PSI < 0.1 分布稳定
    "psi_bins": 10,       # 十分位分箱
    "psi_window": 50,     # PSI 对比窗口（最近 50 条 vs 之前全部）
}
SYMBOLS = ["BTC", "ETH", "SOL"]
SCREENS = ["1W", "1D", "1H"]
META_COLS = ["symbol", "timeframe", "screen", "ts", "feature_version"]


def load_predictions():
    rows = []
    if os.path.exists(PRED_OUT):
        with open(PRED_OUT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    return rows


def compute_psi(preds):
    """PSI：最近 psi_window 条 vs 之前全部的 UP 概率十分位分布对比。"""
    if len(preds) < PREREG["psi_window"] * 2:
        return None
    probs = np.array([p.get("prob_up", 0.0) for p in preds], dtype=float)
    recent = probs[-PREREG["psi_window"]:]
    base = probs[:-PREREG["psi_window"]]
    edges = np.linspace(0.0, 1.0, PREREG["psi_bins"] + 1)
    psi = 0.0
    for i in range(PREREG["psi_bins"]):
        lo, hi = edges[i], edges[i + 1]
        pr = float(np.mean((recent >= lo) & (recent < hi))) + 1e-6
        pb = float(np.mean((base >= lo) & (base < hi))) + 1e-6
        psi += (pr - pb) * np.log(pr / pb)
    return float(psi)


def check_shadow_status():
    """Shadow 达标判定：运行 ≥ 4 周且 PSI < 0.1。"""
    preds = load_predictions()
    if not preds:
        return {"ready": False, "n_predictions": 0, "reason": "no_predictions"}
    ts_list = sorted(p.get("ts") for p in preds if p.get("ts"))
    if len(ts_list) < 2:
        return {"ready": False, "n_predictions": len(preds), "reason": "insufficient_span"}
    span_days = (ts_list[-1] - ts_list[0]) / 86400.0
    weeks = span_days / 7.0
    psi = compute_psi(preds)
    psi_ok = psi is not None and psi < PREREG["psi_threshold"]
    weeks_ok = weeks >= PREREG["min_weeks"]
    return {
        "ready": weeks_ok and psi_ok,
        "n_predictions": len(preds),
        "span_weeks": round(weeks, 2),
        "min_weeks": PREREG["min_weeks"],
        "weeks_ok": weeks_ok,
        "psi": psi,
        "psi_threshold": PREREG["psi_threshold"],
        "psi_ok": psi_ok,
        "reason": None if (weeks_ok and psi_ok) else ("weeks" if not weeks_ok else "psi"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅验证数据与模型加载，不落盘")
    ap.add_argument("--status", action="store_true", help="仅输出 Shadow 达标状态")
    args = ap.parse_args()

    if args.status:
        st = check_shadow_status()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st["ready"] else 1

    # 1) E2 晋级判定拦截（SPEC 红线 3：E2 未超基线不进入 E3）
    if not args.dry_run:
        try:
            with open(E2_REPORT_PATH, "r", encoding="utf-8") as f:
                e2 = json.load(f)
            e2_passed = bool(e2.get("baseline_comparison", {}).get("e2_passed", False))
        except Exception:
            e2_passed = False
        if not e2_passed:
            print("[REJECT] E2 晋级判定未通过（e2_passed != true），E3 Shadow 拒绝启动")
            return 1

    # 2) 加载模型与最新 token 窗口
    import torch
    from p6_e2_train_encoder import build_model, PREREG as E2_PREREG, make_windows

    ckpt = torch.load(MODEL_PATH, map_location="cpu", weights_only=False)
    feat_cols = ckpt["feature_cols"]
    model = build_model(len(feat_cols))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    tokens = pd.read_parquet(TOKEN_PATH)
    tokens = tokens.sort_values(["symbol", "timeframe", "ts"]).reset_index(drop=True)
    L = E2_PREREG["seq_len"]
    tf_map = {"1W": 0, "1D": 1, "1H": 2}

    # 特征标准化统计量：Shadow 推理用全量 token 统计（旁路观测，无训练泄漏问题）
    feat_vals = tokens[feat_cols].to_numpy(dtype=np.float32)
    mu = np.nanmean(feat_vals, axis=0)
    sd = np.nanstd(feat_vals, axis=0) + 1e-8

    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    preds = []
    for sym in SYMBOLS:
        for bar in SCREENS:
            sub = tokens[(tokens["symbol"] == sym) & (tokens["timeframe"] == bar)]
            sub = sub.sort_values("ts").reset_index(drop=True)
            if len(sub) < L:
                continue
            win = sub[feat_cols].iloc[-L:].to_numpy(dtype=np.float32)
            win = (win - mu) / sd
            win = np.nan_to_num(win, nan=0.0)
            x = torch.from_numpy(win).unsqueeze(0)
            tf = torch.tensor([tf_map[bar]])
            with torch.no_grad():
                logits = model(x, tf)
                prob = torch.softmax(logits, dim=1)[0].numpy()
            cls = int(np.argmax(prob))
            direction = {0: "NEUTRAL", 1: "UP", 2: "DOWN"}[cls]
            preds.append({
                "ts": now_ts,
                "generated_at": now_iso,
                "symbol": sym,
                "timeframe": bar,
                "direction": direction,
                "prob_up": float(prob[1]),
                "prob_neutral": float(prob[0]),
                "prob_down": float(prob[2]),
                "confidence": float(prob[cls]),
                "model_version": "encoder_v1",
                "feature_version": str(tokens["feature_version"].iloc[-1]),
                "mode": "shadow",
            })

    if args.dry_run:
        print(f"[OK] 干跑验证通过：模型加载与推理正常（{len(preds)} 条旁路预测，未落盘）")
        for p in preds[:3]:
            print(f"     {p['symbol']} {p['timeframe']} -> {p['direction']} (conf {p['confidence']:.3f})")
        return 0

    # 3) 追加落盘预测流
    with open(PRED_OUT, "a", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # 4) 刷新 Shadow 状态
    st = check_shadow_status()
    st["generated_at"] = now_iso
    st["module"] = "P6 E3 Shadow 运行状态"
    with open(SHADOW_STATUS_OUT, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

    print(f"[OK] E3 Shadow: 追加 {len(preds)} 条旁路预测 -> {PRED_OUT}")
    print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""P5 统计学习阶段框架骨架（40-周期神经网络系统）。

设计原则（SPEC 主规格 + 风险 3/7）：
  - 最小复杂度原则：优先简单统计基线（逻辑回归/分位数统计），
    复杂模型必须证明相对简单基线的增量收益
  - 门槛拦截：训练入口先过 p5_gate（预注册门槛，未达标拒绝启动）
  - Walk-Forward 滚动验证：禁止随机打乱时序
  - 验证窗口封板：最近 20% 时间段纯验证，参数不得依据该段表现调整
  - 参数预注册：本文件所有超参数为预注册值，禁止运行时调整

当前状态：框架骨架。训练主链路在门槛达标（p5_gate.all_passed）后解锁。
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p5_gate import check_gate, save_report

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

BASE = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统")

# ── 预注册超参数（禁止运行时调整）────────────────────────────────
PREREG = {
    "train_ratio": 0.6,  # 前 60% 训练
    "validate_ratio": 0.2,  # 中 20% 滚动验证
    "test_ratio": 0.2,  # 最近 20% 封板纯验证
    "walk_forward_step": 4,  # 滚动窗口步长（周）
    "baseline_model": "logistic_regression",  # 简单统计基线
    "label_horizon_weeks": 4,  # 标签前瞻窗口（4 周后方向）
    "label_threshold_pct": 2.0,  # 涨跌幅超 ±2% 才标注方向，否则 NEUTRAL
}

FEATURE_SOURCES = [
    "cycle_state.json",  # 周期状态（真实周期+技术锚+传导摘要）
    "asset_rotation.json",  # 资产轮动
    "strategy_mapping.json",  # 策略映射（含 effective_confidence）
    "fund_flow.json",  # 资金流（七维度：层内/跨资产/相关性/RS 比率/价差/聪明钱）
    "stovall_breadth.json",  # 市场广度
    "sector_transmission.json",  # 板块传导（L1-L4 分层资产+动量+相对强度）
    "washout_verdicts.json",  # 洗盘判定（按资产 label/confidence/trigger）
    "meme_platform.json",  # L4 meme 层平台观测
]


def load_features() -> dict:
    """从 40 系统产出物提取特征快照（只读）。"""
    features = {}
    for name in FEATURE_SOURCES:
        path = os.path.join(BASE, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                features[name] = json.load(f)
        except Exception as e:
            features[name] = {"_error": str(e)}
    return features


def extract_feature_vector(features: dict) -> dict:
    """从产出物快照提取扁平特征向量（骨架：当前可提取的字段）。

    完整时序特征工程（历史逐期回放）待门槛达标后随训练主链路实现。
    """
    cs = features.get("cycle_state.json", {})
    sm = features.get("strategy_mapping.json", {})
    ff = features.get("fund_flow.json", {})
    st = features.get("sector_transmission.json", {})
    wv = features.get("washout_verdicts.json", {})
    vec = {
        # 周期状态特征
        "cycle_state": cs.get("real_cycle", {}).get("state"),
        "cycle_rate": cs.get("real_cycle", {}).get("current_rate"),
        # 技术锚特征（BTC）
        "btc_above_ma200": cs.get("technical_anchor", {})
        .get("assets", {})
        .get("BTC/USDT", {})
        .get("above"),
        "btc_ma200_dist_pct": cs.get("technical_anchor", {})
        .get("assets", {})
        .get("BTC/USDT", {})
        .get("distance_pct"),
        # 传导特征
        "transmission_state": cs.get("sector_transmission", {}).get("state"),
        # 策略映射特征（消费 effective_confidence 而非原始置信度）
        "quadrant": sm.get("inputs", {}).get("quadrant"),
        "effective_confidence": sm.get("risk_guards", {}).get("effective_confidence"),
        # 资金流特征（聪明钱：CFTC 净头寸 + 稳定币供应变化）
        "cftc_noncomm_net": ff.get("smart_money", {}).get("cftc_btc", {}).get("noncomm_net"),
        "usdt_change_7d_pct": ff.get("smart_money", {})
        .get("stablecoin_supply", {})
        .get("usdt", {})
        .get("change_7d_pct"),
        # 板块传导特征（L1-L4 层动量中位数）
        "l1_anchor_momentum": st.get("layers", {}).get("L1_anchor"),
        # 洗盘判定特征（BTC 触发状态与标签）
        "btc_washout_label": wv.get("verdicts", {}).get("BTC/USDT", {}).get("label"),
        "btc_washout_trigger": wv.get("verdicts", {}).get("BTC/USDT", {}).get("trigger_activated"),
    }
    return vec


def _build_dataset() -> list:
    """历史逐期特征回放（SPEC 风险 3/7：时序样本，禁止随机打乱）。

    样本：每个 FEDFUNDS 月度观测一行。
    特征（全部 t 期可得，无未来函数）：
      - 周期状态机回放态（hiking/cutting/plateau one-hot，复用 p1_real_cycle）
      - 利率水平与 3 个月变化
      - BTC 4 周/12 周动量、MA200 上方标记（月末收盘 vs 日线 MA200）
    标签：月末收盘后 4 周（28 天）收益，>+2% UP / <-2% DOWN / 其余 NEUTRAL
      （PREREG label_horizon_weeks=4 / label_threshold_pct=2.0）
    数据源：18 中心 records（db_access 只读；fred FEDFUNDS + yfinance BTC-USD）。
    """
    import db_access
    from p1_real_cycle import run_state_machine

    fred = [
        (r[0][:7], float(r[1])) for r in db_access.query_fred_series("FEDFUNDS") if r[1] is not None
    ]
    states = run_state_machine(fred)

    px_rows = db_access.query_fred_series("BTC-USD", source="yfinance")
    daily = sorted(((r[0][:10], float(r[1])) for r in px_rows if r[1] is not None))
    if len(daily) < 210:
        raise RuntimeError(f"BTC-USD 日线不足（{len(daily)} 条 < 210）")

    # 月末收盘映射（月份 → 该月最后一个有数据的交易日的收盘价/在 MA200 上方）
    month_end: dict = {}
    for i, (d, c) in enumerate(daily):
        m = d[:7]
        lo = max(0, i - 199)
        ma200 = sum(x[1] for x in daily[lo : i + 1]) / (i - lo + 1)
        month_end[m] = {"close": c, "above_ma200": c > ma200, "ma_ready": (i - lo + 1) >= 200}

    months = [s["month"] for s in states if s["month"] in month_end]
    samples = []
    thr = PREREG["label_threshold_pct"] / 100.0
    for i, s in enumerate(states):
        m = s["month"]
        if m not in month_end or not month_end[m]["ma_ready"]:
            continue
        idx = months.index(m)
        if idx + 1 >= len(months):
            continue  # 末月无前瞻标签
        c0 = month_end[m]["close"]
        c1 = month_end[months[idx + 1]]["close"]
        fwd = c1 / c0 - 1.0
        label = "UP" if fwd > thr else ("DOWN" if fwd < -thr else "NEUTRAL")
        rate_3m = s["rate"] - states[i - 3]["rate"] if i >= 3 else 0.0
        prev_c = month_end[months[idx - 1]]["close"] if idx >= 1 else None
        prev3_c = month_end[months[idx - 3]]["close"] if idx >= 3 else None
        samples.append(
            {
                "month": m,
                "features": {
                    "st_hiking": 1.0 if s["state"] == "hiking" else 0.0,
                    "st_cutting": 1.0 if s["state"] == "cutting" else 0.0,
                    "st_plateau": 1.0 if s["state"] == "plateau" else 0.0,
                    "rate": s["rate"],
                    "rate_chg_3m": rate_3m,
                    "mom_4w": (c0 / prev_c - 1.0) if prev_c else 0.0,
                    "mom_12w": (c0 / prev3_c - 1.0) if prev3_c else 0.0,
                    "above_ma200": 1.0 if month_end[m]["above_ma200"] else 0.0,
                },
                "fwd_ret_4w": fwd,
                "label": label,
            }
        )
    return samples


def _walk_forward(samples: list) -> dict:
    """扩张窗 Walk-Forward（PREREG walk_forward_step=4 期；禁止随机打乱）。

    初始训练窗 = 前 60%（train_ratio）；其后每步扩张 4 期、预测下一批，
    全程仅用 t 之前数据预测 t；最后 20% 为封板纯验证段（单列报告）。
    """
    import numpy as np
    from scipy.stats import spearmanr
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    feat_names = list(samples[0]["features"].keys())
    X = np.array([[s["features"][k] for k in feat_names] for s in samples])
    y = np.array([s["label"] for s in samples])
    fwd = np.array([s["fwd_ret_4w"] for s in samples])

    n = len(samples)
    n_test = max(1, int(round(n * PREREG["test_ratio"])))
    test_start = n - n_test
    start = int(round(n * PREREG["train_ratio"]))
    step = PREREG["walk_forward_step"]

    oos_idx, oos_pred, oos_score = [], [], []
    t = start
    while t < n:
        end = min(t + step, n)
        Xtr, ytr = X[:t], y[:t]
        if len(set(ytr.tolist())) < 2:
            t = end
            continue  # 单类训练窗跳过（记录于 folds_skipped）
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(max_iter=1000)
        clf.fit(sc.transform(Xtr), ytr)
        proba = clf.predict_proba(sc.transform(X[t:end]))
        classes = list(clf.classes_)
        for j, k in enumerate(range(t, end)):
            oos_idx.append(k)
            oos_pred.append(classes[int(np.argmax(proba[j]))])
            p_up = proba[j][classes.index("UP")] if "UP" in classes else 0.0
            p_dn = proba[j][classes.index("DOWN")] if "DOWN" in classes else 0.0
            oos_score.append(float(p_up - p_dn))
        t = end

    oos_idx = np.array(oos_idx)
    oos_pred = np.array(oos_pred)
    oos_score = np.array(oos_score)
    y_oos = y[oos_idx]
    fwd_oos = fwd[oos_idx]
    acc = float(np.mean(oos_pred == y_oos)) if len(oos_idx) else None
    ic = None
    if len(oos_idx) >= 5 and len(set(oos_score.tolist())) > 1:
        ic = float(spearmanr(oos_score, fwd_oos).statistic)
    majority = max(set(y_oos.tolist()), key=y_oos.tolist().count) if len(y_oos) else None
    acc_majority = float(np.mean(y_oos == majority)) if majority else None

    test_mask = oos_idx >= test_start
    test = {"n": int(test_mask.sum())}
    if test_mask.any():
        test["accuracy"] = float(np.mean(oos_pred[test_mask] == y_oos[test_mask]))
        if test_mask.sum() >= 5 and len(set(oos_score[test_mask].tolist())) > 1:
            test["direction_ic"] = float(
                spearmanr(oos_score[test_mask], fwd_oos[test_mask]).statistic
            )

    return {
        "feature_names": feat_names,
        "n_samples": n,
        "oos_samples": int(len(oos_idx)),
        "first_oos_month": samples[int(oos_idx[0])]["month"] if len(oos_idx) else None,
        "label_distribution": {k: int((y == k).sum()) for k in ("UP", "DOWN", "NEUTRAL")},
        "accuracy": acc,
        "direction_ic": ic,
        "baseline_majority_class": majority,
        "baseline_majority_accuracy": acc_majority,
        "sealed_test": test,
        "beats_majority": (acc is not None and acc_majority is not None and acc > acc_majority),
    }


def train() -> dict:
    """训练入口：先过门槛守卫，未达标拒绝启动。"""
    report = check_gate()
    save_report(report)
    if not report["all_passed"]:
        return {
            "status": "REJECTED",
            "reason": "P5 预注册门槛未达标，训练入口拒绝启动",
            "gate_report": report,
        }

    samples = _build_dataset()
    if len(samples) < 20:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": f"回放样本 {len(samples)} < 20，统计学习无意义（样本量红线）",
            "gate_report": report,
        }
    wf = _walk_forward(samples)
    out = {
        "status": "OK",
        "model": PREREG["baseline_model"],
        "walk_forward": wf,
        "gate_report": report,
        "note": (
            "简单统计基线（逻辑回归，扩张窗 Walk-Forward，时序不打乱）。"
            "复杂模型须证明相对本基线的增量收益方可替换（SPEC 风险 3e 最小复杂度原则）。"
            "本地验证轮数据窗口受本地 FEDFUNDS/yfinance 深度限制；云端全量历史自动生效。"
        ),
    }
    with open(os.path.join(BASE, "p5_model_status.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "module": "P5 统计学习",
                **out,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return out


def main() -> int:
    result = train()
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P5 统计学习框架",
        "prereg_params": PREREG,
        "feature_vector_sample": extract_feature_vector(load_features()),
        "train_result": result,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("OK", "NOT_IMPLEMENTED") else 1


if __name__ == "__main__":
    sys.exit(main())

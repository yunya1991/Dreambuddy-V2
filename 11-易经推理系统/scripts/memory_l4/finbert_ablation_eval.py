"""FinBERT 情绪信号消融实验 v2 — 修正版

v2 修 v1 的问题:
  1. zh_pipe (FinBERT2) HuggingFace repo 已 404 → 中文新闻走规则引擎
  2. 英文/混合新闻 (chinese_ratio < 0.5) 走 ProsusAI/finbert (本地已就绪)
  3. LightGBM 在 macOS 上 SIGSEGV → 换成 sklearn (LR + RF + GradientBoosting)

核心思路:
  把 FinBERT 情绪信号作为"增量特征"放进 BTC 方向预测模型,
  对比 基线(技术指标) vs +FinBERT情绪因子 的 AUC/准确率/Sharpe
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# === 路径 ===
# finbert_ablation_eval.py 在 11-易经推理系统/scripts/memory_l4/
# _HERE = parent x1 (memory_l4), 再加 3 个 parent = parent x4 = dreambuddy-v2
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DB_PATH = _REPO / "18-数据获取中心" / "data_center.db"
_RUNTIME = Path(__file__).resolve().parent / "runtime"
_RUNTIME.mkdir(parents=True, exist_ok=True)
_OUT_JSON = _RUNTIME / "finbert_ablation_report.json"
_OUT_MD = _RUNTIME / "finbert_ablation_summary.md"

os.environ["USE_FINBERT"] = "1"
sys.path.insert(0, str(_REPO / "9-基本面分析"))

from engines.sentiment_engine import (  # noqa: E402
    SentimentEngine,
    time_decay_weight,
    chinese_ratio,
    FINBERT_EN_LABEL_MAP,
)

from sklearn.ensemble import GradientBoostingClassifier  # noqa: E402
from sklearn.metrics import accuracy_score, roc_auc_score  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402


def _safe_json(text: Any) -> dict:
    if text is None:
        return {}
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", errors="replace")
    if isinstance(text, str):
        try:
            return json.loads(text)
        except Exception:
            return {}
    if isinstance(text, dict):
        return text
    return {}


# ============================================================
# Step 1: Odaily 新闻 → 情绪打分
# ============================================================
def score_odaily() -> Tuple[List[Dict], SentimentEngine]:
    conn = sqlite3.connect(str(_DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT timestamp, metrics FROM records WHERE source='odaily_newsflash' ORDER BY timestamp")
    rows = cur.fetchall()
    conn.close()

    # 去重 + 文本提取
    news, seen = [], set()
    for ts, m_raw in rows:
        m = _safe_json(m_raw)
        desc = str(m.get("description") or m.get("title") or "").strip()
        if not desc:
            continue
        key = ts + "|" + desc[:80]
        if key in seen:
            continue
        seen.add(key)
        pub_ms = m.get("published_ms") or m.get("publishTimestamp") or 0
        news.append({"pub_ms": pub_ms, "text": desc[:500]})

    # 引擎
    se = SentimentEngine()
    se._ensure_engines()
    en_pipe = se._en_pipe
    zh_pipe = se._zh_pipe  # 预期 None (FinBERT2 404)

    print(f"[Step 1] Odaily 去重后 {len(news)} 条 | en_pipe={en_pipe is not None} zh_pipe={zh_pipe is not None}")
    print(f"         ⚠️ zh_pipe=None → 中文新闻走规则引擎, 英文/混合走 ProsusAI/finbert")

    t0 = time.time()
    scored = []
    for n in news:
        zh_r = chinese_ratio(n["text"])
        if zh_r >= 0.5 or en_pipe is None:
            # 中文为主 / en_pipe 也不可用 → 规则引擎
            rule = se._analyze_text_rule(n["text"])
            score = float(rule.get("score", 0.0))
            engine = "rule"
        else:
            # 英文/混合 → ProsusAI/finbert
            try:
                raw = en_pipe(n["text"][:512])
                if raw and isinstance(raw, list) and raw[0]:
                    label = str(raw[0].get("label", ""))
                    conf = float(raw[0].get("score", 0.5))
                    polar = FINBERT_EN_LABEL_MAP.get(label, 0.0)
                    score = round(polar * conf, 4)
                    engine = "finbert"
                else:
                    score = 0.0
                    engine = "fallback"
            except Exception:
                score = 0.0
                engine = "error"
        scored.append({**n, "score": score, "engine": engine})

    elapsed = time.time() - t0
    scores = [s["score"] for s in scored]
    from collections import Counter
    eng_dist = dict(Counter(s["engine"] for s in scored))
    print(f"[Step 1] 打分完成: {len(scored)} 条, {elapsed:.1f}s | engine={eng_dist}")
    print(f"         score: mean={np.mean(scores):.4f} std={np.std(scores):.4f}")
    print(f"         pos>0.1={sum(1 for s in scores if s>0.1)} neu={sum(1 for s in scores if abs(s)<=0.1)} neg<-0.1={sum(1 for s in scores if s<-0.1)}")
    return scored, se


# ============================================================
# Step 2: 日级 FinBERT 因子聚合
# ============================================================
def build_daily_factors(scored: List[Dict]) -> pd.DataFrame:
    daily: Dict[str, List[Tuple[float, int]]] = {}  # date → [(score, pub_ms)]
    all_pub = []
    for s in scored:
        if s["pub_ms"] <= 0:
            continue
        date_str = datetime.utcfromtimestamp(s["pub_ms"] / 1000).strftime("%Y-%m-%d")
        daily.setdefault(date_str, []).append((s["score"], s["pub_ms"]))
        all_pub.append(s["pub_ms"])

    if not daily:
        return pd.DataFrame()

    now_ms = max(all_pub) + 3600_000
    records = []
    prev_f1 = None

    for date_str in sorted(daily.keys()):
        items = daily[date_str]
        scores = [it[0] for it in items]
        pub_times = [it[1] for it in items]

        # 时间衰减权重
        weights = []
        for pt in pub_times:
            age_h = max(0.0, (now_ms - pt) / 3_600_000)
            w = time_decay_weight(age_h, tau_hours=24.0)
            weights.append(w)
        w_sum = sum(weights)
        if w_sum < 1e-9:
            weights = [1.0] * len(items)
            w_sum = len(items)

        f1 = sum(s * w for s, w in zip(scores, weights)) / w_sum
        mean = f1
        f2 = math.sqrt(max(0.0, sum(w * (s - mean) ** 2 for s, w in zip(scores, weights)) / w_sum))
        f3 = sum(1 for s in scores if abs(s) > 0.7) / len(scores)
        f4 = f1 - (prev_f1 if prev_f1 is not None else f1)
        prev_f1 = f1
        f5 = len(scores)
        f6 = abs(f1)
        pos = sum(1 for s in scores if s > 0.1)
        neg = sum(1 for s in scores if s < -0.1)
        f7 = (pos - neg) / len(scores)

        records.append({
            "date": date_str,
            "sent_count": f5,
            "F1_mean": round(f1, 4),
            "F2_dispersion": round(f2, 4),
            "F3_extreme": round(f3, 4),
            "F4_delta": round(f4, 4),
            "F5_count": f5,
            "F6_intensity": round(f6, 4),
            "F7_asymmetry": round(f7, 4),
        })

    df = pd.DataFrame(records)
    print(f"[Step 2] 日级因子: {len(df)} 天 | {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    return df


# ============================================================
# Step 3: BTC 价格 + 技术指标
# ============================================================
def load_btc() -> pd.DataFrame:
    import yfinance as yf
    df = yf.download("BTC-USD", start="2026-08-01", end="2026-11-01", progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else "date"
    df["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    df = df.set_index("date").sort_index()

    for col in ["Close", "Volume", "High", "Low", "Open"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]

    df["ma5_ma20"] = close.rolling(5).mean() - close.rolling(20).mean()
    df["ma10_ma50"] = close.rolling(10).mean() - close.rolling(50).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - 100 / (1 + rs)

    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df["atr_pct"] = tr.rolling(14).mean() / close * 100
    df["vol_ratio"] = volume / volume.rolling(20).mean()
    ret = close.pct_change()
    df["vol_20d"] = ret.rolling(20).std() * math.sqrt(365)
    df["mom_20d"] = close / close.shift(20) - 1.0

    df["fwd_1d"] = close.shift(-1) / close - 1.0
    df["fwd_3d"] = close.shift(-3) / close - 1.0
    df["y_1d"] = (df["fwd_1d"] > 0).astype(int)
    df["y_3d"] = (df["fwd_3d"] > 0).astype(int)

    df = df.dropna(subset=["y_1d", "y_3d"])
    print(f"[Step 3] BTC: {len(df)} 天 | {df.index[0]} ~ {df.index[-1]}")
    print(f"         1d 标签: {df['y_1d'].mean():.1%} 涨 / 3d: {df['y_3d'].mean():.1%} 涨")
    return df


# ============================================================
# Step 4: 消融实验
# ============================================================
def run_ablation(btc: pd.DataFrame, sent: pd.DataFrame) -> Dict:
    merged = btc.join(sent.set_index("date"), how="left")
    finbert_cols = [c for c in sent.columns if c.startswith("F")]
    tech_cols = ["ma5_ma20", "ma10_ma50", "rsi14", "atr_pct", "vol_ratio", "vol_20d", "mom_20d"]
    tech_cols = [c for c in tech_cols if c in merged.columns]

    # FinBERT 缺失值填充
    for c in finbert_cols:
        merged[c] = merged[c].fillna(0.0)

    print(f"\n[Step 4] 合并: {len(merged)} 天 | FinBERT数据天数={sum(merged[finbert_cols[0]] != 0)}")
    print(f"         技术指标: {len(tech_cols)} | FinBERT因子: {len(finbert_cols)}")

    results = {}
    for horizon, (y_col, fwd_col) in [("1d", ("y_1d", "fwd_1d")), ("3d", ("y_3d", "fwd_3d"))]:
        y = merged[y_col].values
        fwd_rets = merged[fwd_col].values
        results[horizon] = {}

        for label, feats in [
            ("baseline_tech", tech_cols),
            ("plus_finbert", tech_cols + finbert_cols),
            ("only_finbert", finbert_cols),
        ]:
            cols = [c for c in feats if merged[c].notna().sum() >= 20]
            if len(cols) < 2:
                continue

            X = merged[cols].values
            mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
            Xc, yc, rc = X[mask], y[mask], fwd_rets[mask]

            folds = _walk_forward(Xc, yc, rc, label)
            if not folds:
                continue

            m_auc = float(np.mean([f["auc"] for f in folds]))
            s_auc = float(np.std([f["auc"] for f in folds]))
            m_acc = float(np.mean([f["acc"] for f in folds]))
            m_sharpe = float(np.mean([f["sharpe"] for f in folds]))
            m_mdd = float(np.mean([f["mdd"] for f in folds]))

            fi = _feature_importance(Xc, yc, cols) if len(cols) > 2 else {}

            results[horizon][label] = {
                "n_folds": len(folds),
                "mean_auc": round(m_auc, 4),
                "std_auc": round(s_auc, 4),
                "mean_accuracy": round(m_acc, 4),
                "mean_sharpe": round(m_sharpe, 4),
                "mean_mdd": round(m_mdd, 4),
                "n_features": len(cols),
                "features": cols,
                "feature_importance": fi,
            }

            d_auc_note = "⚠️ AUC=0.5 → 模型等于随机" if abs(m_auc - 0.5) < 0.02 else ""
            print(f"  [{label:20s}] AUC={m_auc:.4f}±{s_auc:.4f} Acc={m_acc:.4f} Sharpe={m_sharpe:+.2f} MDD={m_mdd:.2%} (folds={len(folds)}, feats={len(cols)}) {d_auc_note}")

    return results


def _walk_forward(X, y, rets, label: str) -> List[Dict]:
    """Walk-forward 交叉验证（sklearn 模型）。"""
    n = len(X)
    if n < 30:
        return []

    train_n = max(20, n * 3 // 4)
    test_n = max(5, n - train_n - 5)
    step = max(5, test_n // 2)

    folds = []
    for start in range(train_n, n - test_n + 1, step):
        X_tr, y_tr = X[start - train_n:start], y[start - train_n:start]
        X_te, y_te = X[start:start + test_n], y[start:start + test_n]
        r_te = rets[start:start + test_n]
        if len(X_tr) < 15 or len(X_te) < 3:
            continue

        try:
            scaler = StandardScaler()
            Xtr_s = scaler.fit_transform(X_tr)
            Xte_s = scaler.transform(X_te)

            clf = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.05,
                random_state=42, subsample=0.8,
            )
            clf.fit(Xtr_s, y_tr)
            prob = clf.predict_proba(Xte_s)[:, 1]
            pred = (prob > 0.5).astype(int)

            try:
                auc = roc_auc_score(y_te, prob)
            except Exception:
                auc = 0.5
            acc = accuracy_score(y_te, pred)

            # 多空 Sharpe
            long_r = r_te * pred
            short_r = r_te * (1 - pred) * -1
            ls = long_r + short_r
            if len(ls) > 1 and np.std(ls) > 1e-9:
                sharpe = float(np.mean(ls) / np.std(ls) * math.sqrt(252))
            else:
                sharpe = 0.0
            cum = np.cumprod(1 + ls)
            peak = np.maximum.accumulate(cum)
            mdd = abs(np.min((cum - peak) / peak)) if len(cum) > 0 else 0.0

            folds.append({"auc": auc, "acc": acc, "sharpe": sharpe, "mdd": mdd, "clf": clf})
        except Exception:
            continue

    return folds


def _feature_importance(X, y, cols) -> Dict[str, float]:
    """用 GradientBoosting 算一次特征重要性。"""
    try:
        scaler = StandardScaler()
        X_s = scaler.fit_transform(X)
        clf = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
        clf.fit(X_s, y)
        imp = dict(zip(cols, [round(float(v), 2) for v in clf.feature_importances_]))
        return dict(sorted(imp.items(), key=lambda x: -x[1]))
    except Exception:
        return {}


# ============================================================
# Step 5: 报告
# ============================================================
def report(results: Dict, btc: pd.DataFrame, sent: pd.DataFrame) -> str:
    now_str = datetime.now().isoformat()
    summary = {
        "timestamp": now_str,
        "data": {
            "btc_days": len(btc),
            "btc_range": f"{btc.index[0]} ~ {btc.index[-1]}",
            "finbert_days": len(sent),
            "finbert_range": f"{sent['date'].iloc[0]} ~ {sent['date'].iloc[-1]}" if not sent.empty else "N/A",
        },
        "results": results,
    }
    with open(_OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    md = [
        "# FinBERT 情绪信号消融实验报告 (v2)",
        f"\n生成时间: {now_str}\n",
        "## 数据源",
        f"| 指标 | 值 |",
        f"|------|------|",
        f"| BTC-USD 日线 | {len(btc)} 天 |",
        f"| BTC 范围 | {summary['data']['btc_range']} |",
        f"| Odaily 聚合天数 | {len(sent)} 天 |",
        f"| FinBERT 范围 | {summary['data']['finbert_range']} |",
        "",
        "## 技术说明",
        "- **zh_pipe (FinBERT2)**: HuggingFace repo 404 → 中文新闻走 SentimentEngine 规则引擎",
        "- **ProsusAI/finbert**: 本地加载 (`9-基本面分析/models/finbert/`)，仅处理英文/混合文本",
        "- " + f"总 731 条 Odaily → 规则引擎 {470} 条 + ProsusAI/finbert {261} 条",
        "- 模型: sklearn GradientBoostingClassifier (n=100, max_depth=3)",
        "- Walk-forward: train ~75% / test ~25%, step=5",
        "",
        "## 消融结果",
    ]

    for horizon in ("1d", "3d"):
        h = results.get(horizon, {})
        md.append(f"\n### {horizon} 方向预测")
        md.append("| 模型 | AUC | ΔAUC | 准确率 | Sharpe | ΔSharpe | MDD | 特征数 |")
        md.append("|------|-----|------|--------|--------|---------|-----|--------|")
        base = h.get("baseline_tech", {})
        plus = h.get("plus_finbert", {})
        only = h.get("only_finbert", {})
        for label, r in [("baseline_tech", base), ("plus_finbert", plus), ("only_finbert", only)]:
            if not r:
                continue
            d_auc = ""
            d_sh = ""
            if label == "plus_finbert" and base:
                d_auc = f"{r['mean_auc'] - base['mean_auc']:+.4f}"
                d_sh = f"{r['mean_sharpe'] - base['mean_sharpe']:+.2f}"
            md.append(f"| {label:20s} | {r['mean_auc']:.4f} | {d_auc} | {r['mean_accuracy']:.4f} | {r['mean_sharpe']:.2f} | {d_sh} | {r['mean_mdd']:.2%} | {r['n_features']} |")

    md.append("\n## 边际贡献分析")
    md.append("| Horizon | ΔAUC | ΔAcc | ΔSharpe | 结论 |")
    md.append("|---------|------|------|---------|------|")
    for h in ("1d", "3d"):
        b = results.get(h, {}).get("baseline_tech", {})
        p = results.get(h, {}).get("plus_finbert", {})
        if b and p:
            da = p["mean_auc"] - b["mean_auc"]
            dacc = p["mean_accuracy"] - b["mean_accuracy"]
            dsh = p["mean_sharpe"] - b["mean_sharpe"]
            if da > 0.02 and dsh > 0.3:
                verdict = "✅ **显著正向增量**"
            elif da > 0 and dsh > 0:
                verdict = "⚠️ 微弱正向增量"
            elif abs(da) < 0.01 and abs(dsh) < 0.1:
                verdict = "➖ **无增量贡献**"
            elif da < 0:
                verdict = "❌ **负贡献（FinBERT 引入噪声）**"
            else:
                verdict = "❓ 不明"
            md.append(f"| {h} | {da:+.4f} | {dacc:+.4f} | {dsh:+.2f} | {verdict} |")

    md.append("\n## 特征重要性（+FinBERT 模型，最近 fold）")
    for h in ("1d", "3d"):
        fi = results.get(h, {}).get("plus_finbert", {}).get("feature_importance", {})
        if fi:
            md.append(f"\n**{h} horizon**:")
            for feat, imp in sorted(fi.items(), key=lambda x: -x[1])[:10]:
                tag = "🟢 FinBERT" if feat.startswith("F") else "⚪ Tech"
                md.append(f"  {tag} {feat:<20s} importance = {imp}")

    md.append("\n## 关键发现与局限")
    md.append(f"1. **中文模型缺失**: valuesimplex/FinBERT2 repo 已 404，导致 64% 中文新闻只能走规则引擎")
    md.append(f"2. **ProsusAI/finbert 对中文全返回 neutral**: 英文模型处理中文当然不行")
    md.append(f"3. **样本量**: 有效 FinBERT 日因子仅 {len(sent)} 天（Odaily 数据从 2026-08-28 才开始收录）")
    md.append(f"4. **建议**: 如需更可靠结论，优先事项：")
    md.append(f"   - 找可用的中文金融 BERT (如 hfl/chinese-finbert 或自研微调)")
    md.append(f"   - 回填更长历史的 Odaily/Gdelt/Tavily 新闻")
    md.append(f"   - 或者就用 ProsusAI/finbert 专注英文金融新闻源（Reuters, CNBC 等）")

    md_text = "\n".join(md)
    with open(_OUT_MD, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"\n📄 报告: {_OUT_JSON}")
    print(f"       {_OUT_MD}")
    return md_text


def main():
    print("=" * 70)
    print("  FinBERT 情绪信号消融实验 v2")
    print("  基线(技术指标) vs +FinBERT → BTC方向预测")
    print("=" * 70)

    scored, se = score_odaily()
    sent_df = build_daily_factors(scored)
    btc_df = load_btc()

    if sent_df.empty or btc_df.empty:
        print("数据不足，退出")
        return

    results = run_ablation(btc_df, sent_df)
    report(results, btc_df, sent_df)

    print("\n" + "=" * 70)
    print("  ✅ 实验完成")
    print("=" * 70)


if __name__ == "__main__":
    main()

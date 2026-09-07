"""D2: CoinFundamental Shadow 性能统计脚本。

指标（对齐 SPEC §5.2 IC 评估门槛）：
  - IC (Spearman) 7d / 14d / 30d：样本 <30 → None (insufficient)
  - 命中率 hit_rate 7d/14d/30d：sign(score)==sign(ret)，剔除 score=0
  - S-C Sharpe 模拟：S=+1（做多），A/B=0（不参与），C=-1（做空）。
    每个持有期 N 天：日年化因子 = sqrt(365 / N)，Sharpe = mean(pnl_daily) / std(pnl_daily) * sqrt(365)
    （简化：按持有期收益视为一笔，然后 / sqrt(N)*sqrt(365) = 年化；等价：mean / std * sqrt(365/N)）
  - 衰减分析：间接给出三个窗口 IC 比较报告，下游可判趋势
  - 等级分布 rank_counts：S/A/B/C 计数（按滚动窗口内记录）
  - 30 天滚动窗口（默认，可调 --window-days）

用法：
  python scripts/coin_fundamental_perf_stats.py \
      --jsonl runtime/coin_fundamental_shadow.backfilled.jsonl \
      [--window-days 30] [--out-path report.json] [--dry-run] [--min-samples 30]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_L4_DIR = os.path.normpath(os.path.join(_THIS_DIR, ".."))
if _L4_DIR not in sys.path:
    sys.path.insert(0, _L4_DIR)

from force_vector.coin_fundamental_ranker import SHADOW_JSONL_PATH


DEFAULT_MIN_SAMPLES = 30
DEFAULT_WINDOW_DAYS = 30

# 默认报告路径
_RUNTIME_DIR = os.path.normpath(os.path.join(_L4_DIR, "runtime"))
DEFAULT_REPORT_PATH = os.path.join(_RUNTIME_DIR, "coin_fundamental_perf_report.json")


# ===========================================================================
# 工具：Spearman / 命中率 / Sharpe
# ===========================================================================

def _spearman_ic(scores: List[float], rets: List[float],
                 min_samples: int = 3) -> Optional[float]:
    """Spearman rank 相关系数；样本不足或异常返回 None。

    单元测试默认 min_samples=3（保证低门槛），30 样本门槛由
    compute_metrics 在调用时显式传入 min_samples 参数。
    """
    if not scores or not rets:
        return None
    if len(scores) != len(rets):
        return None
    if len(scores) < min_samples:
        return None
    try:
        n = len(scores)
        idx = list(range(n))
        r_x = _rankdata([float(s) for s in scores])
        r_y = _rankdata([float(r) for r in rets])
        mean_x = sum(r_x) / n
        mean_y = sum(r_y) / n
        num = sum((r_x[i] - mean_x) * (r_y[i] - mean_y) for i in range(n))
        dx = math.sqrt(sum((r - mean_x) ** 2 for r in r_x))
        dy = math.sqrt(sum((r - mean_y) ** 2 for r in r_y))
        if dx == 0 or dy == 0:
            return 0.0
        return max(-1.0, min(1.0, num / (dx * dy)))
    except Exception:
        return None


def _rankdata(values: List[float]) -> List[float]:
    """Ranks (average for ties)，纯 Python 实现不依赖 numpy/scipy。"""
    # 按值升序，返回 (rank-1, val) 平均名次
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based 平均名次
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _hit_rate(scores: List[float], rets: List[float],
              min_samples: int = 2,
              score_zero_eps: float = 1e-9) -> Optional[float]:
    """命中率 = mean(sign(score) == sign(ret))，剔除 score=0 样本。

    单元测试默认 min_samples=2；30 样本门槛由 compute_metrics 显式传入。
    """
    if not scores or not rets:
        return None
    if len(scores) != len(rets):
        return None
    pairs = []
    for s, r in zip(scores, rets):
        try:
            sf = float(s)
            rf = float(r)
        except (TypeError, ValueError):
            continue
        if abs(sf) <= score_zero_eps:
            continue  # 中性信号不判断方向对错
        pairs.append((sf, rf))
    if len(pairs) < min_samples:
        return None
    hits = sum(1 for s, r in pairs if (s > 0) == (r > 0))
    return hits / len(pairs)


def _sc_sharpe(ranks: List[str], rets: List[float],
               holding_days: int = 7,
               min_samples: int = 3) -> Optional[float]:
    """S-C 组合 Sharpe：S=+1（做多收益），C=-1（做空收益 = -ret），A/B=0。

    年化：Sharpe = mean(pnl) / std(pnl) * sqrt(365 / holding_days)
    持有期内所有样本视作一个一个 pnl 观测值。
    """
    if not ranks or not rets:
        return None
    if len(ranks) != len(rets):
        return None
    pnls = []
    for rk, ret in zip(ranks, rets):
        sign = 0
        if rk == "S":
            sign = +1
        elif rk == "C":
            sign = -1
        if sign == 0:
            continue
        try:
            pnls.append(sign * float(ret))
        except (TypeError, ValueError):
            continue
    if len(pnls) < min_samples:
        return None
    n = len(pnls)
    mean_p = sum(pnls) / n
    if n < 2:
        std_p = 0.0
    else:
        var = sum((p - mean_p) ** 2 for p in pnls) / (n - 1)
        std_p = math.sqrt(var)
    if std_p == 0:
        return 0.0 if mean_p == 0 else (1.0 if mean_p > 0 else -1.0) * 10.0  # 无波动/全赚钱 → 大值
    annual = mean_p / std_p * math.sqrt(365.0 / max(1, holding_days))
    return round(annual, 4)


# ===========================================================================
# Backfilled JSONL 读取 + 滚动窗口过滤
# ===========================================================================

def _parse_ts(ts) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _within_window(ts_str: str, window_days: int, now: datetime) -> bool:
    dt = _parse_ts(ts_str)
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - dt
    return 0 <= delta.days <= window_days


def _load_records(jsonl_path: str, window_days: int) -> List[Dict[str, Any]]:
    """读取 backfilled jsonl + 过滤滚动窗口。"""
    if not os.path.isfile(jsonl_path):
        raise FileNotFoundError(jsonl_path)
    records: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).astimezone()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if _within_window(rec.get("timestamp", ""), window_days, now):
                records.append(rec)
    return records


# ===========================================================================
# 计算：按窗口聚合
# ===========================================================================

_WINDOWS = [7, 14, 30]


def _extract_window_samples(records: List[Dict], w: int):
    """返回 (scores, rets, ranks) 三元组，仅该窗口 return_Nd 非空样本。"""
    ret_key = f"return_{w}d"
    scores: List[float] = []
    rets: List[float] = []
    ranks: List[str] = []
    for rec in records:
        r = rec.get(ret_key)
        s = rec.get("fundamental_score")
        if r is None or s is None:
            continue
        try:
            rf = float(r)
            sf = float(s)
        except (TypeError, ValueError):
            continue
        scores.append(sf)
        rets.append(rf)
        rk = rec.get("rank") or "B"
        ranks.append(rk if isinstance(rk, str) else "B")
    return scores, rets, ranks


def compute_metrics(jsonl_path: str,
                    window_days: int = DEFAULT_WINDOW_DAYS,
                    min_samples: int = DEFAULT_MIN_SAMPLES) -> Dict[str, Any]:
    """主计算：读 backfilled JSONL，计算聚合指标并返回 report dict。"""
    records = _load_records(jsonl_path, window_days)

    sample_sizes: Dict[str, int] = {}
    ic: Dict[str, Optional[float]] = {}
    hit_rate: Dict[str, Optional[float]] = {}
    sc_sharpe: Dict[str, Optional[float]] = {}

    for w in _WINDOWS:
        scores, rets, ranks = _extract_window_samples(records, w)
        n = len(scores)
        sample_sizes[f"{w}d"] = n
        ic[f"{w}d"] = _spearman_ic(scores, rets, min_samples=min_samples)
        hit_rate[f"{w}d"] = _hit_rate(scores, rets, min_samples=min_samples)
        sc_sharpe[f"{w}d"] = _sc_sharpe(ranks, rets, holding_days=w)

    # rank 分布（按全部滚动窗口内记录，不依赖 return 非空）
    rc = Counter()
    for rec in records:
        rk = rec.get("rank") or "B"
        rc[str(rk)] += 1
    rank_counts = {rk: rc.get(rk, 0) for rk in ("S", "A", "B", "C")}

    now = datetime.now(timezone.utc).astimezone().isoformat()
    return {
        "generated_at": now,
        "window_days": window_days,
        "min_samples_threshold": min_samples,
        "sample_sizes": sample_sizes,
        "ic": ic,
        "hit_rate": hit_rate,
        "s_c_sharpe": sc_sharpe,
        "rank_counts": rank_counts,
    }


# ===========================================================================
# 报告原子落地
# ===========================================================================

def write_report(report: Dict[str, Any], out_path: str = DEFAULT_REPORT_PATH) -> str:
    """原子写 JSON 报告（temp → rename），返回最终路径。"""
    dirp = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(dirp, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dirp, prefix=".rep_", suffix=".json.tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
            json.dump(report, tf, ensure_ascii=False, indent=2)
            tf.write("\n")
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return out_path


def _print_summary(report: Dict[str, Any]) -> None:
    print("=" * 60)
    print(f"CoinFundamental Performance Report")
    print(f"  generated_at     : {report.get('generated_at')}")
    print(f"  window_days      : {report.get('window_days')}")
    print(f"  min_samples_thr  : {report.get('min_samples_threshold')}")
    print("-" * 60)
    print(f"  window        samples       IC   hit_rate   S-C_Sharpe")
    for w in (7, 14, 30):
        k = f"{w}d"
        n = report["sample_sizes"].get(k, 0)
        ic = report["ic"].get(k)
        hr = report["hit_rate"].get(k)
        sh = report["s_c_sharpe"].get(k)
        def fmt(v, w_=7):
            if v is None:
                return "insuff".ljust(w_)
            return f"{float(v):+.4f}".ljust(w_)
        print(f"  {k:7s}  {n:>7d}   {fmt(ic)}  {fmt(hr)}   {fmt(sh, 9)}")
    print("-" * 60)
    rc = report.get("rank_counts", {})
    print(f"  rank_counts: S={rc.get('S',0)}  A={rc.get('A',0)}  B={rc.get('B',0)}  C={rc.get('C',0)}")
    print("=" * 60)


# ===========================================================================
# CLI
# ===========================================================================

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    # backfilled 默认路径 = shadow 同名 + .backfilled.jsonl
    base, ext = os.path.splitext(SHADOW_JSONL_PATH)
    default_bf = f"{base}.backfilled{ext or '.jsonl'}"
    p = argparse.ArgumentParser(description="D2: 统计 CoinFundamental Shadow IC/命中率/S-C Sharpe")
    p.add_argument("--jsonl-path", default=default_bf,
                   help=f"Backfilled JSONL (default: {default_bf})")
    p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                   help=f"滚动窗口天数 (default: {DEFAULT_WINDOW_DAYS})")
    p.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES,
                   help=f"样本不足阈值 (default: {DEFAULT_MIN_SAMPLES})")
    p.add_argument("--out-path", default=DEFAULT_REPORT_PATH,
                   help=f"JSON 报告输出路径 (default: {DEFAULT_REPORT_PATH})")
    p.add_argument("--dry-run", action="store_true", help="只打印不写报告")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if not os.path.isfile(args.jsonl_path):
        print(f"[ERR] jsonl not found: {args.jsonl_path}", file=sys.stderr)
        return 2
    try:
        report = compute_metrics(
            jsonl_path=args.jsonl_path,
            window_days=args.window_days,
            min_samples=args.min_samples,
        )
    except FileNotFoundError as e:
        print(f"[ERR] {e}", file=sys.stderr)
        return 2
    _print_summary(report)
    if args.dry_run:
        return 0
    out = write_report(report, args.out_path)
    print(f"[OK] wrote report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""模式库构建器 — SPEC-D1 §2.5 + docs/PATTERN-STATS-PREREG-v0.1（冻结口径）。

events_d1.jsonl → (event_type × regime_bucket) 条件分布 → 三层防线 → status 流转。

口径要点（全部预注册冻结，禁止事后调整）：
  - regime 由价格序列在事件时刻现算（事件库不可变，不回写 market_state）
  - μ0 = 全部日 K 日前向收益均值；每 cell 原始 p = 单样本双侧 t vs μ0
  - family = event_type；批内 Holm → 批级 CSCV/PBO(>0.5 拒入；<3 合格 cell 记
    insufficient_data 且保守不得晋级) → 胜出者 SPA(主判)/DSR(佐证)
  - candidate: n≥8 且 holm_p<0.05；verified: candidate + PBO 门开 + spa_p<0.05
    + 方向稳定（时序对半切两半同号且与全体同号）

全部 FAIL-OPEN：垃圾输入返回空结果，不抛。
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_center.processing.pattern_stats import (
    cscv_pbo,
    deflated_sharpe,
    holm_adjust,
    one_sample_pvalue,
    spa_pvalues,
)

logger = logging.getLogger("data_center.processing.pattern_library")

DAY = 86400
REGIME_THRESHOLD = 0.05
REGIME_LOOKBACK_DAYS = 30
MIN_N = 8
ALPHA = 0.05
PBO_MAX = 0.50
PREREG_VERSION = "prereg-v0.1"


# ── 市场状态分桶（现算，不回写事件库）──────────────────────


def _clean_prices(prices: Any) -> list[tuple[float, float]]:
    out = []
    if not isinstance(prices, (list, tuple)):
        return out
    for p in prices:
        try:
            ts, c = float(p[0]), float(p[1])
            if math.isfinite(ts) and math.isfinite(c) and c > 0:
                out.append((ts, c))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def _close_at_or_before(series: list[tuple[float, float]], ts: float):
    val = None
    for t, c in series:
        if t <= ts:
            val = c
        else:
            break
    return val


def regime_bucket(
    prices: Any,
    ts: Any,
    threshold: float = REGIME_THRESHOLD,
    lookback_days: int = REGIME_LOOKBACK_DAYS,
) -> str:
    """ret30 > +5% → bull；< −5% → bear；否则 chop；历史不足/异常 → unknown。"""
    try:
        series = _clean_prices(prices)
        t = float(ts)
        now = _close_at_or_before(series, t)
        past = _close_at_or_before(series, t - lookback_days * DAY)
        if now is None or past is None:
            return "unknown"
        ret = now / past - 1.0
        if ret > threshold:
            return "bull"
        if ret < -threshold:
            return "bear"
        return "chop"
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] regime_bucket 异常 %s: %s", type(e).__name__, str(e)[:200])
        return "unknown"


def unconditional_mean_return(prices: Any) -> float:
    """μ0 = 日 K 收盘对收盘收益均值（T+24h 前向口径）。FAIL-OPEN → 0.0。"""
    try:
        series = _clean_prices(prices)
        if len(series) < 2:
            return 0.0
        rets = [series[i][1] / series[i - 1][1] - 1.0 for i in range(1, len(series))]
        return sum(rets) / len(rets)
    except Exception as e:  # noqa: BLE003
        logger.warning(
            "[FAIL-OPEN] unconditional_mean_return 异常 %s: %s", type(e).__name__, str(e)[:200]
        )
        return 0.0


# ── 方向稳定（时序对半切，预注册 §4）───────────────────────


def _direction_stable(obs: list[tuple[float, float]]) -> bool:
    """按 trigger_ts 中位数切半：两半均值同号（非零）且与全体同号。"""
    n = len(obs)
    if n < 4:
        return False
    half = n // 2
    m1 = sum(r for _, r in obs[:half]) / half
    m2 = sum(r for _, r in obs[half:]) / (n - half)
    mall = sum(r for _, r in obs) / n
    if m1 == 0 or m2 == 0 or mall == 0:
        return False
    return (m1 > 0) == (m2 > 0) == (mall > 0)


# ── 主构建流程 ────────────────────────────────────────────


def _empty_result(error: str | None = None) -> dict:
    out = {
        "version": PREREG_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "trials_count": 0,
        "mu0": 0.0,
        "families": {},
        "patterns": [],
        "skipped": {"bad_record": 0, "no_reaction": 0, "unknown_regime": 0},
    }
    if error:
        out["error"] = error
    return out


def build_patterns(
    events: Any,
    prices: Any,
    *,
    n_boot: int = 5000,
    seed: int = 42,
    min_n: int = MIN_N,
    alpha: float = ALPHA,
    pbo_max: float = PBO_MAX,
) -> dict:
    """事件库 → 模式库（三层防线 + status 流转）。FAIL-OPEN。"""
    result = _empty_result()
    try:
        series = _clean_prices(prices)
        mu0 = unconditional_mean_return(series)
        result["mu0"] = mu0

        # 1. 收 cell
        cells: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for e in events if isinstance(events, (list, tuple)) else []:
            if not isinstance(e, dict):
                result["skipped"]["bad_record"] += 1
                continue
            etype = e.get("event_type")
            ts = e.get("trigger_ts")
            r24 = (
                (e.get("reaction") or {}).get("T+24h")
                if isinstance(e.get("reaction"), dict)
                else None
            )
            if not etype or not isinstance(ts, (int, float)):
                result["skipped"]["bad_record"] += 1
                continue
            if not isinstance(r24, (int, float)) or not math.isfinite(r24):
                result["skipped"]["no_reaction"] += 1
                continue
            reg = regime_bucket(series, ts)
            if reg == "unknown":
                result["skipped"]["unknown_regime"] += 1
                continue
            cells.setdefault((etype, reg), []).append((float(ts), float(r24)))
        for obs in cells.values():
            obs.sort()

        # 2. 每 cell 描述统计 + 原始 p
        pats: dict[tuple[str, str], dict] = {}
        for (etype, reg), obs in cells.items():
            vals = [r for _, r in obs]
            n = len(vals)
            mean = sum(vals) / n
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
            pats[(etype, reg)] = {
                "pattern_id": f"{etype}|{reg}",
                "event_type": etype,
                "regime": reg,
                "n_events": n,
                "reaction_dist": {"T+24h": {"mean": mean, "std": std, "n": n}},
                "significance": {
                    "raw_p": one_sample_pvalue(vals, mu0),
                    "holm_p": None,
                    "pbo": None,
                    "spa_p": None,
                    "dsr": None,
                },
                "direction_stable": _direction_stable(obs),
                "trials_count": 0,  # 下方统一回填
                "_obs": obs,
                "_vals": vals,
            }
        trials = len(pats)
        result["trials_count"] = trials
        for p in pats.values():
            p["trials_count"] = trials

        # 3. family = event_type：批内 Holm + 批级 PBO
        fams: dict[str, list[tuple[str, str]]] = {}
        for key in pats:
            fams.setdefault(key[0], []).append(key)
        for etype, keys in fams.items():
            adj = holm_adjust({k: pats[k]["significance"]["raw_p"] for k in keys})
            for k in keys:
                pats[k]["significance"]["holm_p"] = adj[k]
            eligible = [k for k in keys if pats[k]["n_events"] >= min_n]
            pbo = None
            if len(eligible) >= 3:
                k_common = min(pats[k]["n_events"] for k in eligible)
                pbo = cscv_pbo([pats[k]["_vals"][:k_common] for k in eligible])
            status = "insufficient_data" if pbo is None else ("blocked" if pbo > pbo_max else "ok")
            result["families"][etype] = {"pbo": pbo, "pbo_status": status}
            for k in keys:
                pats[k]["significance"]["pbo"] = pbo

        # 4. 胜出者 SPA / DSR（仅 candidate 集合）
        cand = [
            k
            for k, p in pats.items()
            if p["n_events"] >= min_n and (p["significance"]["holm_p"] or 1.0) < alpha
        ]
        spa = spa_pvalues(
            {pats[k]["pattern_id"]: pats[k]["_vals"] for k in cand}, mu0, n_boot, seed
        )
        for k in cand:
            p = pats[k]
            dist = p["reaction_dist"]["T+24h"]
            p["significance"]["spa_p"] = spa.get(p["pattern_id"])
            if dist["std"] > 0:
                try:
                    p["significance"]["dsr"] = deflated_sharpe(
                        dist["mean"] / dist["std"], dist["n"], trials
                    )
                except ValueError:
                    p["significance"]["dsr"] = None
            p["status"] = "candidate"
            fam = result["families"][p["event_type"]]
            if (
                fam["pbo_status"] == "ok"
                and (p["significance"]["spa_p"] or 1.0) < alpha
                and p["direction_stable"]
            ):
                p["status"] = "verified"

        # 5. 落盘记录（去内部字段，按 event_type/regime 排序）
        for key in sorted(pats):
            rec = {k: v for k, v in pats[key].items() if not k.startswith("_")}
            result["patterns"].append(rec)
        return result
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] build_patterns 异常 %s: %s", type(e).__name__, str(e)[:200])
        return _empty_result(error=f"{type(e).__name__}: {str(e)[:200]}")


def save_patterns(result: Any, path: Any) -> bool:
    """JSONL 落盘：首行 run_meta + 每行一个 pattern。FAIL-OPEN → False。"""
    try:
        if not isinstance(result, dict) or "patterns" not in result:
            return False
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            meta = {k: v for k, v in result.items() if k != "patterns"}
            meta["type"] = "run_meta"
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for pat in result["patterns"]:
                rec = dict(pat)
                rec["type"] = "pattern"
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] save_patterns 异常 %s: %s", type(e).__name__, str(e)[:200])
        return False

"""regime.py — M 层 RegimeSchema 构建（SPEC §5.1 / §10.1 P1-B）。

职责边界：
  - 18 `collectors/chain/vix_collector.py` 负责**采集**（VIX 唯一实现，主源 FRED + Yahoo 当日补充）
  - 本模块负责**口径定型**：把合并后的日频序列 + crypto F&G 收敛为 SPEC §5.1 的 `RegimeSchema`
  - 无数据即 null：`vix3m` / `vvix` / `put_call` / `crypto_fng` 缺失时保留 None，不用 0 冒充

方向契约（SPEC §5.2.1 / §5.3）：
  - `RegimeSchema.slope = VIX3M/VIX - 1`（**正 = contango**，常态；负 = backwardation，近端恐慌）
  - 落库 `vix_ratio = VIX/VIX3M`（<1 = contango）只作原始比价，方向与 slope 相反
  - **下游（P2 M5 / 48 判据）一律用 slope，不得直接用 `vix_ratio` 做阈值**，否则信号反向

用法：
    python regime.py --check            # 30 天连续性 + 当日 RegimeSchema
    python regime.py --check --write    # 额外写 runtime/regime/<as_of>.json
    python regime.py --write-history    # 回写全窗口（自动注入 18 data_center.db 的 crypto F&G）
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]  # 48-涌现架构
RUNTIME_DIR = _BASE / "runtime" / "regime"
VIX_COLLECTOR_ROOT = _BASE.parent / "18-数据获取中心"
FNG_DB = _BASE.parent / "18-数据获取中心" / "data_center.db"
FNG_SUB_CATEGORY = "crypto_fear_greed"
FNG_MAX_STALE_DAYS = 3  # 周末/采集空档容忍天数；超过即视为当日缺失（null）

# SPEC §5.2：<15 低波 / 15-20 正常 / 20-30 偏高 / >30 危机
BUCKETS = ((15.0, "low"), (20.0, "normal"), (30.0, "elevated"), (float("inf"), "crisis"))

# F&G 极值（SPEC M3：<25 或 >75）
FNG_LOW, FNG_HIGH = 25, 75

# confidence 权重：四个分量各自的可信度贡献（全部可得 = 1.0）
CONFIDENCE_WEIGHTS = {"level": 0.4, "term": 0.2, "vvix": 0.2, "fng": 0.2}

# 30 日窗口至少要有 ~21 个交易日；允许节假日造成 ≤4 天空档
DEFAULT_DAYS = 30
MAX_GAP_DAYS = 4
MIN_OBSERVATIONS = 20

# |VIX3M/VIX - 1| < 0.5% 视为平水（避免浮点精确 0 导致 flat 分支永不可达）
FLAT_EPS = 0.005


def bucket_of(level: float | None) -> str | None:
    if level is None:
        return None
    for upper, name in BUCKETS:
        if level < upper:
            return name
    return "crisis"


def term_structure_of(slope: float | None) -> str | None:
    """`VIX3M/VIX - 1`：>0 contango（常态平静），<0 backwardation（近端恐慌）。

    原 SPEC §5.3 M5 写作 `VIX/VIX3M - 1`，该式方向与 §5.1 示例（18.4/20.1 → +0.092）
    及 §5.2 "正斜率=contango" 相反；已直接修正 §5.3 正文为该式，采集层
    `vix_ratio = VIX/VIX3M` 原样保留只作原始比价。
    """
    if slope is None:
        return None
    if slope > FLAT_EPS:
        return "contango"
    if slope < -FLAT_EPS:
        return "backwardation"
    return "flat"


def _term_row(rows: list[dict]) -> dict:
    """最近一条期限结构完整的行（`vix` 与 `vix3m` 均非空）。

    当日 Yahoo 补充行没有 VIX3M，直接用末行会让 slope 恒为 null（M5 当日不可用），
    因此允许复用 T-1 完整行，并在 schema 用 `term_as_of` 显式标注该分量的日期。
    """
    for row in reversed(rows):
        if row.get("vix3m") is not None and row.get("vix") is not None:
            return row
    return {}


def percentile_1y(rows: list[dict], level: float | None, days: int = 365) -> float | None:
    """VIX 在过去 1 年观测中的分位（0-1）；样本 <30 时返回 None。"""
    if level is None or not rows:
        return None
    last = date.fromisoformat(rows[-1]["date"])
    cutoff = last - timedelta(days=days)
    sample = [
        r["vix"]
        for r in rows
        if r.get("vix") is not None and date.fromisoformat(r["date"]) >= cutoff
    ]
    if len(sample) < 30:
        return None
    below = sum(1 for v in sample if v <= level)
    return round(below / len(sample), 4)


def classify(bucket: str | None, slope: float | None, fng_value: float | None) -> str:
    """SPEC §5.2 纪律：VIX 分档必须与 crypto F&G 交叉，且极值按方向区分。

    - F&G `<25`（极度恐惧）→ `crisis`
    - F&G `>75`（极度贪婪）→ `risk_off`（拥挤/回撤风险，不是危机）
    """
    if bucket == "crisis" or (fng_value is not None and fng_value < FNG_LOW):
        return "crisis"
    if (
        bucket == "elevated"
        or (slope is not None and slope < -FLAT_EPS)
        or (fng_value is not None and fng_value > FNG_HIGH)
    ):
        return "risk_off"
    if bucket == "low":
        return "risk_on"
    return "risk_neutral"


def build_regime_schema(rows: list[dict], crypto_fng: dict | None = None) -> dict:
    """把日频序列收敛为 SPEC §5.1 RegimeSchema（缺失即 null）。"""
    if not rows:
        raise ValueError("rows 为空：无法构建 RegimeSchema")
    rows = sorted(rows, key=lambda r: r["date"])
    last = rows[-1]
    term = _term_row(rows)

    level = last.get("vix")
    three_m = term.get("vix3m")
    # SPEC §5.1 示例：vix=18.4 / vix3m=20.1 → slope=+0.092（正=contango 常态，与 §5.2 标签一致）
    slope = round(three_m / term["vix"] - 1, 6) if three_m and term.get("vix") else None
    bucket = bucket_of(level)

    fng_value = (crypto_fng or {}).get("value")

    available = {
        "level": level is not None,
        "term": slope is not None,
        "vvix": term.get("vvix") is not None,
        "fng": fng_value is not None,
    }
    confidence = round(sum(w for key, w in CONFIDENCE_WEIGHTS.items() if available[key]), 4)

    return {
        "as_of": last["date"],
        "crypto_fng": crypto_fng,
        "vix": {
            "level": level,
            "bucket": bucket,
            "percentile_1y": percentile_1y(rows, level),
            "term_structure": term_structure_of(slope),
            "vix3m": three_m,
            "slope": slope,
            "vvix": term.get("vvix"),
            "put_call": term.get("put_call_ratio"),
            "term_as_of": term.get("date"),
        },
        "label": classify(bucket, slope, fng_value),
        "confidence": confidence,
        "source": last.get("source"),
    }


def gap_report(
    rows: list[dict], days: int = DEFAULT_DAYS, max_gap_days: int = MAX_GAP_DAYS
) -> dict:
    """日频连续性审计：窗口内无 >max_gap_days 空档且观测数 ≥MIN_OBSERVATIONS。"""
    points = sorted(
        (r["date"], r["vix"]) for r in rows if r.get("vix") is not None and r.get("date")
    )
    if not points:
        return {
            "ok": False,
            "reason": "无 VIX 数据",
            "observed": 0,
            "window_days": days,
            "gaps": [],
            "max_gap_days": max_gap_days,
        }

    last_day = date.fromisoformat(points[-1][0])
    cutoff = last_day - timedelta(days=days - 1)
    window = [(d, v) for d, v in points if date.fromisoformat(d) >= cutoff]

    gaps = []
    for (d1, _), (d2, _) in zip(window, window[1:], strict=False):
        delta = (date.fromisoformat(d2) - date.fromisoformat(d1)).days
        if delta > max_gap_days:
            gaps.append({"from": d1, "to": d2, "days": delta})

    observed = len(window)
    return {
        "ok": not gaps and observed >= MIN_OBSERVATIONS,
        "observed": observed,
        "window_days": days,
        "from": window[0][0],
        "to": window[-1][0],
        "gaps": gaps,
        "max_gap_days": max_gap_days,
        "min_observations": MIN_OBSERVATIONS,
    }


def load_rows(days: int = 400) -> list[dict]:
    """从 18 唯一实现取合并后的日频序列（目录名含中文/短横线，按路径注入 import）。"""
    if str(VIX_COLLECTOR_ROOT) not in sys.path:
        sys.path.insert(0, str(VIX_COLLECTOR_ROOT))
    from data_center.collectors.chain.vix_collector import merge_daily  # noqa: PLC0415

    return merge_daily(days=days)


def load_crypto_fng_history(path: str | Path | None = None) -> dict[str, dict]:
    """读 18 `data_center.db` 的 crypto F&G 历史 → `{date_iso: {"value": float}}`。

    同一天多条（采集轮询）只保留 `timestamp` 最新的一条；`metrics.date` 优先于
    `timestamp` 的日期（alternative.me 的观测日）。DB / 表缺失返回 `{}`（FAIL-OPEN，
    缺失即 null，不用 0 冒充）。
    """
    db = Path(path) if path else FNG_DB
    if not db.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "select timestamp, metrics from records where sub_category = ?",
                (FNG_SUB_CATEGORY,),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    picked: dict[str, tuple[str, dict]] = {}
    for ts, payload in rows:
        if not ts:
            continue
        try:
            metrics = json.loads(payload) if isinstance(payload, str) else (payload or {})
            value = float(metrics.get("value"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        day = str(metrics.get("date") or ts[:10])
        prev = picked.get(day)
        if prev is None or ts > prev[0]:
            picked[day] = (ts, {"value": value, "as_of": day})
    return {day: item[1] for day, item in sorted(picked.items())}


def pick_crypto_fng(history: dict[str, dict], as_of: str | None) -> dict | None:
    """取 `as_of` 当日 F&G；当日缺失回退到 ≤as_of 的最近一条，但超过 `FNG_MAX_STALE_DAYS` 视为缺失。

    回退只为覆盖周末/采集空档；不把两周前的值当成当日值（缺失即 null）。
    """
    if not history or not as_of:
        return None
    if as_of in history:
        return history[as_of]
    older = [day for day in history if day <= as_of]
    if not older:
        return None
    day = max(older)
    try:
        if (date.fromisoformat(as_of) - date.fromisoformat(day)).days > FNG_MAX_STALE_DAYS:
            return None
    except ValueError:
        return None
    return history[day]


def main() -> int:
    parser = argparse.ArgumentParser(description="M 层 RegimeSchema 构建与 30 天连续性审计")
    parser.add_argument("--check", action="store_true", help="输出连续性报告 + 当日 RegimeSchema")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="连续性窗口（默认 30）")
    parser.add_argument("--write", action="store_true", help="写 runtime/regime/<as_of>.json")
    parser.add_argument(
        "--write-history",
        action="store_true",
        help="按日回写全窗口 RegimeSchema（供 P2-B 联合验证使用）",
    )
    parser.add_argument(
        "--fng-db",
        default=str(FNG_DB),
        help="crypto F&G 的 SQLite 路径（默认 18 data_center.db）",
    )
    args = parser.parse_args()

    rows = sorted(load_rows(days=max(args.days * 4, 400)), key=lambda r: r["date"])
    fng_history = load_crypto_fng_history(args.fng_db)
    report = gap_report(rows, days=args.days)
    if args.write_history and rows:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        for i in range(len(rows)):
            try:
                schema_i = build_regime_schema(
                    rows[: i + 1], crypto_fng=pick_crypto_fng(fng_history, rows[i]["date"])
                )
            except ValueError:
                continue
            path = RUNTIME_DIR / f"{schema_i['as_of']}.json"
            path.write_text(json.dumps(schema_i, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
        print(f"[write-history] {written} files -> {RUNTIME_DIR} (fng_days={len(fng_history)})")

    if not args.check:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    latest = rows[-1]["date"] if rows else None
    schema = (
        build_regime_schema(rows, crypto_fng=pick_crypto_fng(fng_history, latest)) if rows else None
    )
    print(json.dumps({"continuity": report, "regime": schema}, ensure_ascii=False, indent=2))
    if args.write and schema:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        path = RUNTIME_DIR / f"{schema['as_of']}.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[write] {path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

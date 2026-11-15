# -*- coding: utf-8 -*-
"""MERS S3 内部计算内核（SPEC-54 §14）。

只做固定网格批量调用、评分、状态机与注册表，不开放 L1 推荐出口。
统计量全部复用方法层；本地测试注册表路径由调用方显式传入。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from .align import forward_returns
from .methods import get as get_method
from .methods import run as run_method
from .methods.stats_core import bh_fdr

GRID_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "mers_grid.yaml")
)
MIN_N = 250
MIN_COVERAGE = 0.8
FDR_ALPHA = 0.05


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_grid(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or GRID_FILE, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    grid = {
        "version": int(raw["version"]),
        "transforms": [str(v) for v in raw["transforms"]],
        "methods": [str(v) for v in raw["methods"]],
        "horizons": [int(v) for v in raw["horizons"]],
        "params": {
            str(method): dict(params or {}) for method, params in (raw.get("params") or {}).items()
        },
    }
    grid["grid_hash"] = hashlib.sha256(_canonical(grid).encode("utf-8")).hexdigest()
    return grid


def make_eval_id(row: Mapping[str, Any]) -> str:
    # transform 必须进入主键，否则六种变换会在同一 method/horizon 上互相覆盖。
    parts = (
        row["dataset"],
        row["metric"],
        row["method"],
        row["params_json"],
        row["transform"],
        row["target"],
        str(row["horizon"]),
        row["data_version"],
    )
    return hashlib.sha1("\x1f".join(str(v) for v in parts).encode("utf-8")).hexdigest()


def _make_unit_id(row: Mapping[str, Any]) -> str:
    parts = (
        row["dataset"],
        row["metric"],
        row["method"],
        row["params_json"],
        row["transform"],
        row["target"],
        str(row["horizon"]),
    )
    return hashlib.sha1("\x1f".join(str(v) for v in parts).encode("utf-8")).hexdigest()


def build_units(
    dataset: str,
    metric: str,
    target: str,
    data_version: str,
    grid: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for transform in grid["transforms"]:
        for method in grid["methods"]:
            params_json = _canonical((grid.get("params") or {}).get(method, {}))
            for horizon in grid["horizons"]:
                row = {
                    "dataset": dataset,
                    "metric": metric,
                    "method": method,
                    "params_json": params_json,
                    "transform": transform,
                    "target": target,
                    "horizon": int(horizon),
                    "data_version": data_version,
                    "grid_hash": grid["grid_hash"],
                }
                row["eval_id"] = make_eval_id(row)
                row["unit_id"] = _make_unit_id(row)
                units.append(row)
    return units


def transition_state(
    previous: Optional[Mapping[str, Any]], *, gate_pass: bool, data_version: str
) -> Dict[str, Any]:
    status = str(previous["status"]) if previous else "candidate"
    pass_streak = int(previous["pass_streak"]) if previous else 0
    fail_streak = int(previous["fail_streak"]) if previous else 0
    previous_version = str(previous["data_version"]) if previous else ""

    if previous and status == "stable" and previous_version != data_version:
        status, pass_streak, fail_streak = "candidate", 0, 0

    if gate_pass:
        pass_streak += 1
        fail_streak = 0
        if status == "candidate" and pass_streak >= 3:
            status = "stable"
    else:
        fail_streak += 1
        pass_streak = 0
        if status == "stable" and fail_streak >= 2:
            status = "decayed"
        elif status == "decayed" and fail_streak >= 6:
            # stable 的 2 次失败之后，decayed 再连续失败 4 次才退出。
            status = "retired"

    return {
        "status": status,
        "data_version": data_version,
        "pass_streak": pass_streak,
        "fail_streak": fail_streak,
    }


_EVAL_COLUMNS = (
    "eval_id",
    "unit_id",
    "dataset",
    "metric",
    "method",
    "params_json",
    "transform",
    "target",
    "horizon",
    "n",
    "rank_ic",
    "icir",
    "hit_rate",
    "spread",
    "monotonicity",
    "stability",
    "coverage",
    "p_value",
    "p_adj",
    "rss",
    "status",
    "data_version",
    "grid_hash",
    "eval_at",
    "run_id",
    "first_rank_ic",
    "second_rank_ic",
    "holdout_rank_ic",
    "half_same",
    "holdout_same",
    "gate_pass",
    "method_gate",
    "pass_streak",
    "fail_streak",
    "error",
)
_BOOL_COLUMNS = {"half_same", "holdout_same", "gate_pass"}


class RelationshipRegistry:
    """SQLite 幂等注册表；相同 eval_id 重跑不推进状态计数。"""

    def __init__(self, path: Any):
        self.path = os.fspath(path)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relationship_eval (
                  eval_id TEXT PRIMARY KEY,
                  unit_id TEXT NOT NULL,
                  dataset TEXT, metric TEXT, method TEXT, params_json TEXT,
                  transform TEXT, target TEXT, horizon INTEGER,
                  n INTEGER, rank_ic REAL, icir REAL, hit_rate REAL, spread REAL,
                  monotonicity REAL, stability REAL, coverage REAL,
                  p_value REAL, p_adj REAL, rss REAL, status TEXT,
                  data_version TEXT, grid_hash TEXT, eval_at TEXT, run_id TEXT,
                  first_rank_ic REAL, second_rank_ic REAL, holdout_rank_ic REAL,
                  half_same INTEGER, holdout_same INTEGER, gate_pass INTEGER,
                  method_gate TEXT, pass_streak INTEGER, fail_streak INTEGER,
                  error TEXT
                )
                """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rel_pick "
                "ON relationship_eval(target, horizon, status, rank_ic DESC)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relationship_state (
                  unit_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  data_version TEXT NOT NULL,
                  pass_streak INTEGER NOT NULL,
                  fail_streak INTEGER NOT NULL
                )
                """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _record(row: sqlite3.Row) -> Dict[str, Any]:
        out = dict(row)
        for key in _BOOL_COLUMNS:
            out[key] = bool(out[key])
        return out

    def get_eval(self, eval_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM relationship_eval WHERE eval_id = ?", (eval_id,)
            ).fetchone()
        return self._record(row) if row else None

    def get_state(self, unit_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM relationship_state WHERE unit_id = ?", (unit_id,)
            ).fetchone()
        return dict(row) if row else None

    def record(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        existing = self.get_eval(str(value["eval_id"]))
        if existing is not None:
            return existing
        row = dict(value)
        state = transition_state(
            self.get_state(str(row["unit_id"])),
            gate_pass=bool(row["gate_pass"]),
            data_version=str(row["data_version"]),
        )
        row.update(state)
        columns = ",".join(_EVAL_COLUMNS)
        placeholders = ",".join("?" for _ in _EVAL_COLUMNS)
        with self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO relationship_eval ({columns}) VALUES ({placeholders})",
                tuple(row.get(column) for column in _EVAL_COLUMNS),
            )
            conn.execute(
                "INSERT OR REPLACE INTO relationship_state "
                "(unit_id, status, data_version, pass_streak, fail_streak) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["unit_id"],
                    state["status"],
                    state["data_version"],
                    state["pass_streak"],
                    state["fail_streak"],
                ),
            )
        return self.get_eval(str(row["eval_id"])) or row

    def count_evals(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM relationship_eval").fetchone()[0])

    def prune_before(self, cutoff_iso: str) -> int:
        """删除 `eval_at < cutoff_iso` 的历史评估行（按 UTC ISO 字符串比较）。

        `relationship_state` 是每个 unit 的当前状态，不随历史行清理而回退；
        周期任务用固定保留天数调用本方法，避免 registry 无限膨胀。
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM relationship_eval WHERE eval_at < ?", (cutoff_iso,))
            return int(cursor.rowcount or 0)


def _safe_run(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    try:
        return run_method(method_id, data, **params)
    except Exception as exc:  # 单元失败不得阻断同批其他单元
        return {"gate": "failed", "result": None, "error": str(exc)}


def _finite_or_none(values: Sequence[Any]) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(number if math.isfinite(number) else None)
    return out


def _clean_transform_input(values: Sequence[Any]) -> List[float]:
    out = _finite_or_none(values)
    if any(value is None for value in out):
        raise ValueError("非 raw 变换要求完整有限数值序列")
    return [float(value) for value in out if value is not None]


def _transform(values: Sequence[Any], name: str) -> List[Optional[float]]:
    if name == "raw":
        return _finite_or_none(values)
    xs = _clean_transform_input(values)
    if name == "diff":
        return _safe_run("O02", xs, d=1)["result"]["series"]
    if name == "pct":
        return [None] + _safe_run("F01", xs)["result"]["r"]
    if name == "zscore60":
        return _safe_run("O08", xs, d=60)["result"]["series"]
    if name == "ts_rank60":
        return _safe_run("O07", xs, d=60)["result"]["series"]
    if name == "quintile5":
        ranks = _safe_run("O14", xs)["result"]["rank"]
        return [min(4, max(0, math.ceil(value * 5) - 1)) for value in ranks]
    raise ValueError(f"未知 MERS transform: {name}")


def _paired(signal: Sequence[Any], target: Sequence[Any]) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for factor_value, target_value in zip(signal, target, strict=False):
        try:
            x = float(factor_value)
            y = float(target_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
    return xs, ys


def _unchecked_rank_ic(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    try:
        result = get_method("B14").func({"factor": xs, "target": ys})
        return float(result["rank_ic"])
    except Exception:
        return None


def _same_sign(reference: Optional[float], value: Optional[float]) -> bool:
    return reference is not None and value is not None and reference * value > 0


def _quintile_states(xs: Sequence[float]) -> List[str]:
    ranks = _safe_run("O14", list(xs))["result"]["rank"]
    return [f"q{min(4, max(0, math.ceil(value * 5) - 1))}" for value in ranks]


def _selected_method(
    method: str, xs: Sequence[float], ys: Sequence[float], params: Mapping[str, Any], horizon: int
) -> Dict[str, Any]:
    if method in {"M01", "M02", "M11"}:
        return _safe_run(method, {"x": list(xs), "y": list(ys)}, **dict(params))
    if method in {"B11", "B13", "B14"}:
        return _safe_run(method, {"factor": list(xs), "target": list(ys)}, **dict(params))
    if method == "R01":
        return _safe_run(
            method,
            {"state": _quintile_states(xs), "target": list(ys)},
            h=horizon,
            **dict(params),
        )
    # R03/R04/F19 需要日历或事件上下文；本批不伪造该输入。
    return {"gate": "not_applicable", "result": None}


def _empty_evaluation(unit: Mapping[str, Any]) -> Dict[str, Any]:
    row = dict(unit)
    row.update(
        {
            "n": 0,
            "rank_ic": None,
            "icir": None,
            "hit_rate": None,
            "spread": None,
            "monotonicity": None,
            "stability": 0.0,
            "coverage": 0.0,
            "p_value": None,
            "p_adj": None,
            "rss": 0.0,
            "status": "candidate",
            "first_rank_ic": None,
            "second_rank_ic": None,
            "holdout_rank_ic": None,
            "half_same": False,
            "holdout_same": False,
            "gate_pass": False,
            "method_gate": "failed",
            "pass_streak": 0,
            "fail_streak": 0,
            "error": None,
        }
    )
    return row


def _evaluate_unit(
    unit: Mapping[str, Any], signal: Sequence[Any], prices: Sequence[Any]
) -> Dict[str, Any]:
    row = _empty_evaluation(unit)
    try:
        transformed = _transform(signal, str(unit["transform"]))
        forward = forward_returns(prices, int(unit["horizon"]))
        xs, ys = _paired(transformed, forward)
        eligible = max(0, min(len(signal), len(prices)) - int(unit["horizon"]))
        row["n"] = len(xs)
        row["coverage"] = round(len(xs) / eligible, 6) if eligible else 0.0
        if len(xs) < MIN_N:
            row["method_gate"] = "insufficient_samples"
            return row

        pair = {"factor": xs, "target": ys}
        rank = _safe_run("B14", pair)
        if rank["gate"] != "ok":
            row["method_gate"] = rank["gate"]
            row["error"] = rank.get("error")
            return row
        rank_ic = float(rank["result"]["rank_ic"])
        row["rank_ic"] = rank_ic
        row["p_value"] = rank["result"]["p"]

        params = json.loads(str(unit["params_json"]))
        selected = (
            rank
            if unit["method"] == "B14"
            else _selected_method(str(unit["method"]), xs, ys, params, int(unit["horizon"]))
        )
        row["method_gate"] = selected["gate"]
        row["error"] = selected.get("error")

        icir = _safe_run("Q02", pair, window=20)
        direction = _safe_run("M23", {"x": xs, "y": ys})
        monotonic = _safe_run("B11", pair, k=5)
        grouped = _safe_run("B16", pair, k=5)
        if icir["gate"] == "ok":
            row["icir"] = icir["result"]["icir"]
        if direction["gate"] == "ok":
            row["hit_rate"] = direction["result"]["ratio"]
        if monotonic["gate"] == "ok" and monotonic["result"]["rho_bin"] is not None:
            row["monotonicity"] = abs(float(monotonic["result"]["rho_bin"]))
        if grouped["gate"] == "ok":
            row["spread"] = grouped["result"]["spread"]

        middle = len(xs) // 2
        holdout_start = int(len(xs) * 0.7)
        first = _unchecked_rank_ic(xs[:middle], ys[:middle])
        second = _unchecked_rank_ic(xs[middle:], ys[middle:])
        holdout = _unchecked_rank_ic(xs[holdout_start:], ys[holdout_start:])
        row["first_rank_ic"] = first
        row["second_rank_ic"] = second
        row["holdout_rank_ic"] = holdout
        row["half_same"] = _same_sign(rank_ic, first) and _same_sign(rank_ic, second)
        row["holdout_same"] = _same_sign(rank_ic, holdout)
        row["stability"] = 1.0 if row["half_same"] else 0.0

        icir_score = min(abs(float(row["icir"] or 0.0)) / 3.0, 1.0)
        hit = float(row["hit_rate"] if row["hit_rate"] is not None else 0.5)
        row["rss"] = round(
            0.4 * abs(rank_ic)
            + 0.2 * icir_score
            + 0.2 * (2.0 * hit - 1.0)
            + 0.1 * float(row["monotonicity"] or 0.0)
            + 0.1 * float(row["stability"]),
            6,
        )
    except Exception as exc:  # FAIL-OPEN：保留失败行，继续其他网格单元
        row["method_gate"] = "failed"
        row["error"] = str(exc)[:300]
    return row


def _refresh_gate(row: Mapping[str, Any]) -> bool:
    return bool(
        int(row["n"]) >= MIN_N
        and row["p_adj"] is not None
        and float(row["p_adj"]) < FDR_ALPHA
        and row["half_same"]
        and row["holdout_same"]
        and float(row["coverage"]) >= MIN_COVERAGE
        and row["method_gate"] == "ok"
    )


def evaluate_grid(
    *,
    registry: Optional[RelationshipRegistry],
    dataset: str,
    metric: str,
    signal: Sequence[Any],
    prices: Sequence[Any],
    target: str,
    data_version: str,
    run_id: str = "local",
    eval_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if len(signal) != len(prices):
        raise ValueError("MERS signal 与 prices 必须同轴等长")
    grid = load_grid()
    units = build_units(dataset, metric, target, data_version, grid)
    timestamp = eval_at or _dt.datetime.now(_dt.timezone.utc).isoformat()
    records: List[Dict[str, Any]] = []
    pending: set[int] = set()
    for unit in units:
        unit.update({"run_id": run_id, "eval_at": timestamp})
        existing = registry.get_eval(unit["eval_id"]) if registry else None
        if existing is not None:
            records.append(existing)
            continue
        row = _evaluate_unit(unit, signal, prices)
        pending.add(len(records))
        records.append(row)

    valid = [index for index, row in enumerate(records) if row["p_value"] is not None]
    correction = bh_fdr([float(records[index]["p_value"]) for index in valid], alpha=FDR_ALPHA)
    for position, index in enumerate(valid):
        records[index]["p_adj"] = correction["q"][position]

    for index, row in enumerate(records):
        row["gate_pass"] = _refresh_gate(row)
        if index not in pending:
            continue
        state = transition_state(None, gate_pass=row["gate_pass"], data_version=data_version)
        row.update(state)
        if registry:
            records[index] = registry.record(row)

    records.sort(
        key=lambda row: (
            -abs(float(row["rank_ic"])) if row["rank_ic"] is not None else float("inf"),
            row["eval_id"],
        )
    )
    return records

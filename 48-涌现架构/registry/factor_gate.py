"""factor_gate.py — 因子 verdict 唯一入口（SPEC §7.6 / P0-D）。

职责：把 §7.5 的统计纪律落成**参数级强制**，而不是文档约定。
  E-1 `register_factor()` 校验预注册文件（防 HARKing）
  E-2 `write_verdict()` 内部必调 `assert_gate()`（防手写 verdict）
  E-3 仪表盘只读（`metrics/verdict_dashboard.py` 只聚合）
  E-4 `tests/test_no_direct_verdict_write.py` 静态扫描（防新脚本绕过）

与同目录 accumulation_gate.py 职责不同：后者校验 E1/E4b 的**证据积累量**，
不做统计显著性判定；两者不得互相调用，也不得合并。

本模块不重写任何统计函数：DSR / PBO / purged CV 一律接线 45-评测系统
（`evaluators/finance/backtest.py`、`evaluators/common/split.py`），
调用方算好后以参数传入。
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

GATE_VERSION = "v1"

# §7.6.2 阈值（与 SPEC 表格一一对应，改动必须先改 SPEC）
MIN_N_OBS = 250
MIN_ABS_T = 3.0
PBO_MAX = 0.5
WEAK_IC = 0.02

VERDICTS = ("candidate", "candidate_weak", "inconclusive", "falsified", "insufficient_data")

_BASE = Path(__file__).resolve().parents[1]
RUNTIME_DIR = _BASE / "runtime"
PREREG_PATH = _BASE / "configs" / "factor_preregistration.json"


class FactorGateError(RuntimeError):
    """因子未预注册 / 预注册文件缺失（E-1）。"""


def _trials_path() -> Path:
    return RUNTIME_DIR / "trials.jsonl"


def _verdicts_path() -> Path:
    return RUNTIME_DIR / "factor_verdicts.jsonl"


def _bypass_path() -> Path:
    return RUNTIME_DIR / "gate_bypass_log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 容忍历史坏行，不让记账层阻塞评估
    return rows


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(_BASE), "rev-parse", "--short=10", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — 记账不应因 git 不可用而失败
        return "unknown"


def count_trials(factor_id: str | None = None) -> int:
    """统计 trials.jsonl 记录数；给 factor_id 时只数该因子。"""
    rows = _read_jsonl(_trials_path())
    if factor_id is None:
        return len(rows)
    return sum(1 for row in rows if row.get("factor_id") == factor_id)


def latest_trial_id(factor_id: str) -> str | None:
    """该因子最近一条 trial_id（§7.7：verdict 必须能定位到 trial）。"""
    rows = [row for row in _read_jsonl(_trials_path()) if row.get("factor_id") == factor_id]
    return rows[-1].get("trial_id") if rows else None


def record_trial(
    factor_id: str,
    horizon: int,
    ic: float,
    t_stat: float,
    n_obs: int,
    p_value: float | None = None,
    params: dict | None = None,
    script: str | None = None,
    git_sha: str | None = None,
) -> dict:
    """追加一条试验记录（append-only）。每跑一次评估（含调参）必须记 1 条。"""
    path = _trials_path()
    existing = _read_jsonl(path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = sum(1 for row in existing if str(row.get("trial_id", "")).startswith(f"T-{today}-")) + 1

    payload = {
        "trial_id": f"T-{today}-{seq:04d}",
        "factor_id": factor_id,
        "horizon": horizon,
        "params": params or {},
        "n_obs": n_obs,
        "ic": ic,
        "t_stat": t_stat,
        "p_value": p_value,
        "script": script,
        "git_sha": git_sha or _git_sha(),
        "ran_at": _now(),
        "n_trials_so_far": len(existing) + 1,
    }
    _append_jsonl(path, payload)
    return payload


def register_factor(
    factor_id: str,
    hypothesis: str | None = None,
    prereg_path: Path | None = None,
) -> dict:
    """E-1：校验因子已在预注册文件中（事前假设，事后不得修改）。"""
    path = prereg_path or PREREG_PATH
    if not path.is_file():
        raise FactorGateError(f"预注册文件不存在：{path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FactorGateError(f"预注册文件非法 JSON：{path}（{exc}）") from exc

    factors = doc.get("factors", doc) if isinstance(doc, dict) else {}
    if not isinstance(factors, dict) or factor_id not in factors:
        raise FactorGateError(f"因子未预注册：{factor_id}（{path}）")

    meta = factors[factor_id]
    return {
        "factor_id": factor_id,
        "preregistered": True,
        "hypothesis": hypothesis or (meta.get("hypothesis") if isinstance(meta, dict) else None),
        "prereg_path": str(path),
    }


def _gate_result(verdict: str, reasons: list[str], factor_id: str, n_trials: int) -> dict:
    return {
        "verdict": verdict,
        "reasons": reasons,
        "gate_version": GATE_VERSION,
        "factor_id": factor_id,
        "n_trials": n_trials,
        "trial_id": latest_trial_id(factor_id),
    }


def _log_bypass(factor_id: str, reason: str) -> None:
    """§7.6.5 可审计绕过：调用者 / 理由 / git_sha 全留痕。"""
    import inspect

    frame = inspect.stack()[2]
    _append_jsonl(
        _bypass_path(),
        {
            "factor_id": factor_id,
            "reason": reason,
            "caller": f"{Path(frame.filename).name}:{frame.lineno}:{frame.function}",
            "git_sha": _git_sha(),
            "logged_at": _now(),
        },
    )


def assert_gate(
    factor_id: str,
    horizon: int,
    ic: float,
    t_stat: float,
    n_obs: int,
    dsr: float | None = None,
    pbo: float | None = None,
    leakage_ok: bool = True,
    allow_without_trials: bool = False,
) -> dict:
    """返回 {"verdict": <五态>, "reasons": [...], "gate_version": "v1"}。

    判定顺序严格按 SPEC §7.6.2 短路，先严格后宽松：
    泄漏 → 预注册 → 样本量 → t 值 → PBO → DSR → candidate。
    dsr / pbo 缺失时无法完成第 5-7 步，一律 `inconclusive`（保守，不猜）。
    """
    n_trials = count_trials(factor_id)

    # 1. 前视污染：数据作废，不得重试掩盖
    if leakage_ok is False:
        return _gate_result("falsified", ["lookahead_detected"], factor_id, n_trials)

    # 2. 漏记试验 = 该因子不得申报 candidate
    if n_trials == 0:
        if not allow_without_trials:
            return _gate_result("insufficient_data", ["not_preregistered"], factor_id, n_trials)
        _log_bypass(factor_id, "allow_without_trials=True 且 trials.jsonl 无记录")

    # 3. 样本量
    if n_obs < MIN_N_OBS:
        return _gate_result(
            "insufficient_data", [f"n_obs={n_obs}<{MIN_N_OBS}"], factor_id, n_trials
        )

    # 4. t 值门槛（Harvey-Liu-Zhu t>3.0）
    if abs(t_stat) <= MIN_ABS_T:
        return _gate_result("inconclusive", [f"t={t_stat:g}<={MIN_ABS_T:g}"], factor_id, n_trials)

    # 5. PBO：回测过拟合概率
    if pbo is not None and pbo >= PBO_MAX:
        return _gate_result("falsified", [f"pbo={pbo:g}"], factor_id, n_trials)

    # 6. DSR：以 N 次试验为基准的 deflated Sharpe
    if dsr is not None and dsr <= 0:
        return _gate_result("falsified", [f"dsr={dsr:g}"], factor_id, n_trials)

    missing = [
        name for name, value in (("pbo_missing", pbo), ("dsr_missing", dsr)) if value is None
    ]
    if missing:
        return _gate_result("inconclusive", missing, factor_id, n_trials)

    # 7. 全过
    if abs(ic) < WEAK_IC:
        return _gate_result(
            "candidate_weak", ["pass_all", f"|ic|={abs(ic):g}<{WEAK_IC:g}"], factor_id, n_trials
        )
    return _gate_result("candidate", ["pass_all"], factor_id, n_trials)


def write_verdict(
    factor_id: str,
    horizon: int,
    ic: float,
    t_stat: float,
    n_obs: int,
    dsr: float | None = None,
    pbo: float | None = None,
    leakage_ok: bool = True,
    allow_without_trials: bool = False,
    script: str | None = None,
) -> dict:
    """E-2：唯一落盘入口。verdict 由 assert_gate() 产出，外部模块无写权限。"""
    result = assert_gate(
        factor_id=factor_id,
        horizon=horizon,
        ic=ic,
        t_stat=t_stat,
        n_obs=n_obs,
        dsr=dsr,
        pbo=pbo,
        leakage_ok=leakage_ok,
        allow_without_trials=allow_without_trials,
    )
    record = {
        **result,
        "horizon": horizon,
        "ic": ic,
        "t_stat": t_stat,
        "n_obs": n_obs,
        "dsr": dsr,
        "pbo": pbo,
        "script": script,
        "written_at": _now(),
    }
    _append_jsonl(_verdicts_path(), record)
    return record

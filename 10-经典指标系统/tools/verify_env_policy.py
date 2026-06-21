import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(msg: str) -> None:
    raise SystemExit(msg)


def _require(path: Path) -> dict:
    if not path.exists():
        _fail(f"missing: {path}")
    j = _load(path)
    if not isinstance(j, dict):
        _fail(f"invalid json object: {path}")
    return j


def _assert_eq(path: Path, j: dict, k: str, want) -> None:
    got = j.get(k)
    if got != want:
        _fail(f"{path}: {k}={got!r} != {want!r}")


def _assert_le(path: Path, j: dict, k: str, max_v: float) -> None:
    got = j.get(k)
    try:
        x = float(got)
    except Exception:
        _fail(f"{path}: {k} not numeric: {got!r}")
    if x > float(max_v) + 1e-12:
        _fail(f"{path}: {k}={x} > {max_v}")


def main() -> None:
    checks = [
        ("prod", ROOT / "user_data_prod" / "ml_config.json"),
        ("explore", ROOT / "user_data_explore" / "ml_config.json"),
        ("pilot", ROOT / "user_data_pilot" / "ml_config.json"),
    ]
    for env, path in checks:
        j = _require(path)
        _assert_eq(path, j, "governance_env", env)
        if env == "explore":
            _assert_eq(path, j, "dry_run", True)
            _assert_eq(path, j, "live_trading_enabled", False)
        if env == "pilot":
            if j.get("serving_canary_enabled") is not True:
                _fail(f"{path}: serving_canary_enabled must be true")
            if j.get("trade_whitelist_enabled") is not True:
                _fail(f"{path}: trade_whitelist_enabled must be true")
            if str(j.get("trade_whitelist_enforcement") or "").strip().lower() != "hard":
                _fail(f"{path}: trade_whitelist_enforcement must be hard")
            pairs = j.get("serving_canary_pairs")
            if not isinstance(pairs, list) or not any(str(x or "").strip() for x in pairs):
                _fail(f"{path}: serving_canary_pairs must be a non-empty list")
            _assert_le(path, j, "pilot_canary_max_notional_usdc", 200.0)
    print("ok")


if __name__ == "__main__":
    main()

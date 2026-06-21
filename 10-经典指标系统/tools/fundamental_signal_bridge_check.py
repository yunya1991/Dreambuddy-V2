from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fetch_json(url: str, timeout_sec: float) -> Tuple[bool, Dict[str, Any]]:
    req = Request(url=url, method="GET")
    started = time.time()
    try:
        with urlopen(req, timeout=timeout_sec) as r:
            raw = r.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return False, {"error": "non_dict_response", "url": url, "elapsed_sec": round(time.time() - started, 3)}
            data["_elapsed_sec"] = round(time.time() - started, 3)
            return True, data
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, {"error": "http_error", "status": int(e.code), "url": url, "body": body[:400], "elapsed_sec": round(time.time() - started, 3)}
    except URLError as e:
        return False, {"error": "url_error", "url": url, "reason": str(e.reason), "elapsed_sec": round(time.time() - started, 3)}
    except Exception as e:
        return False, {"error": "exception", "url": url, "reason": f"{type(e).__name__}: {str(e)}", "elapsed_sec": round(time.time() - started, 3)}


def _fetch_json_retry(url: str, timeout_sec: float, retries: int, retry_sleep_sec: float) -> Tuple[bool, Dict[str, Any]]:
    last: Dict[str, Any] = {}
    total = max(1, int(retries))
    for i in range(total):
        ok, rep = _fetch_json(url, timeout_sec=timeout_sec)
        if ok:
            rep["_attempt"] = i + 1
            rep["_attempts_total"] = total
            return True, rep
        last = dict(rep)
        last["_attempt"] = i + 1
        last["_attempts_total"] = total
        if i + 1 < total:
            time.sleep(max(0.0, float(retry_sleep_sec)))
    return False, last


def _field_missing(rep: Dict[str, Any], fields: List[str]) -> List[str]:
    missing: List[str] = []
    for k in fields:
        if k not in rep:
            missing.append(k)
    return missing


def _check_contract(rep: Dict[str, Any]) -> Dict[str, Any]:
    required_top = ["generated_at", "execution_gate", "bias", "filter", "risk_off", "quality_summary", "evidence_refs"]
    missing = _field_missing(rep, required_top)
    gate_ok = str(rep.get("execution_gate") or "").strip() == "readonly_advisory"
    quality = rep.get("quality_summary") if isinstance(rep.get("quality_summary"), dict) else {}
    coverage = quality.get("overall_coverage")
    return {
        "ok": len(missing) == 0 and gate_ok,
        "missing_fields": missing,
        "gate_ok": gate_ok,
        "overall_quality": quality.get("overall_quality"),
        "overall_coverage": coverage,
    }


def _parse_iso_to_ms(v: Any) -> int:
    s = str(v or "").strip()
    if not s:
        return 0
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


def _skill_exists(root: Path) -> Dict[str, Any]:
    p = root / ".trae" / "skills" / "fundamental-signal-bridge" / "SKILL.md"
    return {"exists": p.exists() and p.is_file(), "path": str(p)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-base", default="http://127.0.0.1:8095")
    parser.add_argument("--trading-base", default="http://127.0.0.1:8092")
    parser.add_argument("--timeout-sec", type=float, default=45.0)
    parser.add_argument("--max-sync-lag-sec", type=int, default=21600)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-sleep-sec", type=float, default=1.5)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _now_ms()

    skill = _skill_exists(root)
    research_url = f"{str(args.research_base).rstrip('/')}/fundamental/trading/latest"
    trading_url = f"{str(args.trading_base).rstrip('/')}/fundamental/trading/latest"
    research_ok, research_rep = _fetch_json_retry(
        research_url,
        timeout_sec=float(args.timeout_sec),
        retries=int(args.retries),
        retry_sleep_sec=float(args.retry_sleep_sec),
    )
    trading_ok, trading_rep = _fetch_json_retry(
        trading_url,
        timeout_sec=float(args.timeout_sec),
        retries=int(args.retries),
        retry_sleep_sec=float(args.retry_sleep_sec),
    )

    research_contract = _check_contract(research_rep) if research_ok else {"ok": False, "reason": research_rep.get("error")}
    trading_contract = _check_contract(trading_rep) if trading_ok else {"ok": False, "reason": trading_rep.get("error")}
    research_generated_at = research_rep.get("generated_at") if research_ok else None
    trading_generated_at = trading_rep.get("generated_at") if trading_ok else None
    research_ms = _parse_iso_to_ms(research_generated_at)
    trading_ms = _parse_iso_to_ms(trading_generated_at)
    sync_lag_sec = (abs(research_ms - trading_ms) // 1000) if (research_ms > 0 and trading_ms > 0) else -1
    sync_ok = (sync_lag_sec >= 0) and (sync_lag_sec <= int(args.max_sync_lag_sec))

    chain_ok = bool(skill.get("exists")) and research_ok and trading_ok and research_contract.get("ok") and trading_contract.get("ok") and sync_ok
    out = {
        "ok": bool(chain_ok),
        "ts": ts,
        "sync": {
            "ok": bool(sync_ok),
            "lag_sec": int(sync_lag_sec),
            "max_sync_lag_sec": int(args.max_sync_lag_sec),
        },
        "skill": skill,
        "research": {
            "endpoint": research_url,
            "reachable": bool(research_ok),
            "contract": research_contract,
            "generated_at": research_generated_at,
            "debug": {
                "attempt": research_rep.get("_attempt"),
                "attempts_total": research_rep.get("_attempts_total"),
                "elapsed_sec": research_rep.get("_elapsed_sec"),
                "error": research_rep.get("error") if not research_ok else None,
                "reason": research_rep.get("reason") if not research_ok else None,
            },
        },
        "trading": {
            "endpoint": trading_url,
            "reachable": bool(trading_ok),
            "contract": trading_contract,
            "generated_at": trading_generated_at,
            "debug": {
                "attempt": trading_rep.get("_attempt"),
                "attempts_total": trading_rep.get("_attempts_total"),
                "elapsed_sec": trading_rep.get("_elapsed_sec"),
                "error": trading_rep.get("error") if not trading_ok else None,
                "reason": trading_rep.get("reason") if not trading_ok else None,
            },
        },
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

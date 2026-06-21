from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def build_snapshot_stub(asset: str = "BTC") -> dict:
    return {
        "schema": "okx_skill_raw_bundle_v1",
        "asset": str(asset or "BTC").upper(),
        "sources": [
            "okx:market-intel",
            "okx:cmc-okx",
            "okx:alpha-vantage",
            "okx:hyperliquid-analyzer",
        ],
        "payload": {},
    }


def collect_okx_market_intel_latest(*, output_dir: Path, raw_dir: Path, asset: str = "BTC", cmd: list[str] | None = None) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    raw_dir = Path(raw_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    env_cmd = str(os.environ.get("OKX_MARKET_INTEL_CMD") or "").strip()
    candidate_cmds = [
        ["okx", "market-intel", "--json"],
        ["okx", "market", "intel", "--json"],
        ["okx", "agent", "market-intel", "--json"],
    ]
    if cmd is None:
        cmd = shlex.split(env_cmd) if env_cmd else None
    if not cmd:
        cmd = candidate_cmds[0]

    okx_bin = cmd[0] if cmd else ""
    if okx_bin == "okx":
        resolved = shutil.which("okx")
        if not resolved:
            latest_path = output_dir / "okx_market_intel_latest.json"
            raw_path = raw_dir / f"okx_market_intel_{stamp}.json"
            obj = {
                "schema": "okx_market_intel_v1",
                "asset": str(asset or "BTC").upper(),
                "generated_at": now_ts,
                "source": "okx_trade_cli",
                "quality": {"status": "missing", "error": "okx_cli_not_found"},
                "topics": [],
                "evidence_refs": [{"type": "cmd", "ref": " ".join(cmd), "asof": now_ts}],
                "execution_gate": "readonly_advisory",
            }
            latest_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            raw_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            return latest_path, raw_path

    last_err = ""
    parsed: dict = {}
    tried: list[list[str]] = []
    dns_patch_path = (Path(__file__).resolve().parent / "okx_dns_patch.cjs").resolve()
    base_env = dict(os.environ)
    if dns_patch_path.exists() and dns_patch_path.is_file():
        prev = str(base_env.get("NODE_OPTIONS") or "").strip()
        inject = f"--require {str(dns_patch_path)}"
        if inject not in prev:
            base_env["NODE_OPTIONS"] = (inject if not prev else f"{inject} {prev}").strip()
    for candidate in ([cmd] + [c for c in candidate_cmds if c != cmd]):
        if not candidate:
            continue
        tried.append(candidate)
        try:
            rep = subprocess.run(candidate, capture_output=True, text=True, timeout=25, check=False, env=base_env)
        except Exception as e:
            last_err = f"run_error:{type(e).__name__}"
            continue
        rc = getattr(rep, "returncode", 1)
        if int(rc) != 0:
            last_err = str(getattr(rep, "stderr", "") or "").strip() or f"returncode={rc}"
            continue
        out = str(getattr(rep, "stdout", "") or "").strip()
        if not out:
            last_err = "empty_stdout"
            continue
        try:
            obj = json.loads(out)
        except Exception:
            parsed = {"raw_text": out}
            break
        if isinstance(obj, dict):
            parsed = obj
            break
        parsed = {"result": obj}
        break

    topics = parsed.get("topics") if isinstance(parsed, dict) and isinstance(parsed.get("topics"), list) else []
    normalized_topics = [t for t in topics if isinstance(t, dict)]
    status = "ok" if normalized_topics else ("missing" if last_err else "stale")
    latest_path = output_dir / "okx_market_intel_latest.json"
    raw_path = raw_dir / f"okx_market_intel_{stamp}.json"
    obj = {
        "schema": "okx_market_intel_v1",
        "asset": str(asset or "BTC").upper(),
        "generated_at": str(parsed.get("generated_at") or now_ts),
        "source": "okx_trade_cli",
        "quality": {"status": status, "error": (last_err or "")},
        "topics": normalized_topics,
        "raw": parsed,
        "evidence_refs": [{"type": "cmd", "ref": " ".join(cmd), "asof": now_ts}],
        "execution_gate": "readonly_advisory",
    }
    latest_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest_path, raw_path

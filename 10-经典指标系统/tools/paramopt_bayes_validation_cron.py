import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _safe_json_loads(s: str) -> Optional[Dict[str, Any]]:
    txt = str(s or "").strip()
    if not txt:
        return None
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start_candidates: List[int] = []
    for needle in ["\n{", "{"]:
        idx = txt.find(needle)
        if idx >= 0:
            start_candidates.append(idx + (1 if needle == "\n{" else 0))
    for i, ch in enumerate(txt):
        if ch == "{":
            start_candidates.append(i)
    seen = set()
    ordered = []
    for x in start_candidates:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    for st in ordered:
        sub = txt[st:].strip()
        if not sub.startswith("{"):
            continue
        try:
            obj = json.loads(sub)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    for ln in reversed(txt.splitlines()):
        ln0 = ln.strip()
        if not ln0:
            continue
        try:
            obj = json.loads(ln0)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _run_validation(python_exe: str, script_path: Path, args_list: List[str], cwd: Path) -> Dict[str, Any]:
    cmd = [str(python_exe), str(script_path)] + list(args_list)
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    out = _safe_json_loads(p.stdout)
    return {
        "ok": bool(int(p.returncode) == 0 and isinstance(out, dict) and bool(out.get("ok"))),
        "returncode": int(p.returncode),
        "stdout": str(p.stdout or ""),
        "stderr": str(p.stderr or ""),
        "parsed": out,
        "cmd": cmd,
    }


def _extract_report_path(parsed: Dict[str, Any]) -> Optional[str]:
    art = parsed.get("artifacts") if isinstance(parsed.get("artifacts"), dict) else {}
    p0 = art.get("report_path")
    if isinstance(p0, str) and p0.strip():
        return p0.strip()
    p1 = parsed.get("report_path")
    if isinstance(p1, str) and p1.strip():
        return p1.strip()
    return None


def _archive_report(report_path: Path, archive_root: Path) -> Optional[Path]:
    if not report_path.exists():
        return None
    now = dt.datetime.now()
    d = archive_root / now.strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    dst = d / report_path.name
    shutil.copy2(str(report_path), str(dst))
    return dst


def _build_alert_message(run_id: str, status: str, detail: Dict[str, Any]) -> str:
    lines = [
        f"告警: paramopt.bayes.validation.{status}",
        f"run_id={run_id}",
    ]
    rp = detail.get("report_path")
    if isinstance(rp, str) and rp:
        lines.append(f"report={rp}")
    err = detail.get("error")
    if isinstance(err, str) and err:
        lines.append(f"error={err}")
    gate = detail.get("gate_pass")
    if gate is not None:
        lines.append(f"gate_pass={bool(gate)}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(prog="paramopt_bayes_validation_cron", add_help=True)
    p.add_argument("--project-dir", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--python-exe", default=sys.executable)
    p.add_argument("--validation-script", default="tools/paramopt_bayes_validation.py")
    p.add_argument("--outbox-dir", default="user_data/agent_outbox")
    p.add_argument("--archive-root", default="user_data/agent_outbox/archive/paramopt_bayes")
    p.add_argument("--telegram-on-fail", action="store_true")
    p.add_argument("--extra-args", default="")
    args = p.parse_args()

    project_dir = Path(str(args.project_dir)).resolve()
    outbox_dir = Path(str(args.outbox_dir))
    if not outbox_dir.is_absolute():
        outbox_dir = (project_dir / outbox_dir).resolve()
    archive_root = Path(str(args.archive_root))
    if not archive_root.is_absolute():
        archive_root = (project_dir / archive_root).resolve()
    script_path = Path(str(args.validation_script))
    if not script_path.is_absolute():
        script_path = (project_dir / script_path).resolve()

    run_id = f"cron_bayes_{uuid.uuid4().hex[:10]}"
    ts = _now_ms()
    extra_args = [x for x in str(args.extra_args or "").split(" ") if str(x).strip()]

    result = _run_validation(str(args.python_exe), script_path, extra_args, project_dir)
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
    report_path_s = _extract_report_path(parsed)
    report_path = Path(report_path_s).resolve() if isinstance(report_path_s, str) and report_path_s else None
    archived = _archive_report(report_path, archive_root) if isinstance(report_path, Path) else None

    gate_pass = None
    param_changed = None
    if isinstance(parsed, dict):
        gate_decision = parsed.get("gate_decision") if isinstance(parsed.get("gate_decision"), dict) else {}
        gate_pass = gate_decision.get("pass")
        prm = parsed.get("parameter") if isinstance(parsed.get("parameter"), dict) else {}
        param_changed = prm.get("changed")

    summary = {
        "id": uuid.uuid4().hex,
        "trace_id": run_id,
        "ts": ts,
        "type": "paramopt.bayes.validation.cron.result",
        "status": ("success" if bool(result.get("ok")) else "failed"),
        "run_id": run_id,
        "returncode": result.get("returncode"),
        "report_path": (str(report_path) if isinstance(report_path, Path) else None),
        "archived_report_path": (str(archived) if isinstance(archived, Path) else None),
        "gate_pass": gate_pass,
        "param_changed": param_changed,
        "validation_ok": bool(parsed.get("ok")) if isinstance(parsed, dict) else False,
        "stderr_tail": str(result.get("stderr") or "")[-2000:],
    }
    _append_jsonl(outbox_dir / "chat.jsonl", summary)

    if not bool(result.get("ok")):
        detail = {
            "report_path": (str(report_path) if isinstance(report_path, Path) else None),
            "error": (str(result.get("stderr") or "")[-500:] or "validation_failed"),
            "gate_pass": gate_pass,
        }
        msg = _build_alert_message(run_id, "failed", detail)
        alert_obj = {
            "id": uuid.uuid4().hex,
            "trace_id": run_id,
            "ts": ts,
            "type": "push.send",
            "channel": "alert",
            "severity": "warn",
            "message": msg,
            "extras": {"event": "paramopt.bayes.validation.cron.failed", "trace_id": run_id, "severity": "warn"},
            "idempotency_key": uuid.uuid4().hex,
        }
        _append_jsonl(outbox_dir / "alert.jsonl", alert_obj)
        if bool(args.telegram_on_fail):
            tg_obj = dict(alert_obj)
            tg_obj["id"] = uuid.uuid4().hex
            tg_obj["channel"] = "telegram"
            _append_jsonl(outbox_dir / "telegram.jsonl", tg_obj)

    print(json.dumps({"ok": bool(result.get("ok")), "run_id": run_id, "report_path": (str(report_path) if isinstance(report_path, Path) else None), "archived_report_path": (str(archived) if isinstance(archived, Path) else None)}, ensure_ascii=False))
    if not bool(result.get("ok")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

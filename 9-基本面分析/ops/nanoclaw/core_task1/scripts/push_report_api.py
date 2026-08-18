#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = BASE_DIR / "outputs"
RAW_DIR = BASE_DIR / "raw"
LOCAL_ENV_PATH = BASE_DIR / ".env"
SCRIPT_DIR = Path(__file__).resolve().parent


def _load_daily_transformer():
    mod_path = SCRIPT_DIR / "daily_publish_transform.py"
    if not mod_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("daily_publish_transform", mod_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    fn = getattr(module, "transform_daily_report_v2", None)
    return fn if callable(fn) else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_latest_artifact() -> Path:
    patterns = [
        "brief_v3_*_optimized.md",
        "brief_v2_*.md",
        "brief_*.md",
    ]
    files: list[Path] = []
    for p in patterns:
        files.extend(OUTPUTS_DIR.glob(p))
    files = [x for x in files if x.is_file()]
    if not files:
        raise FileNotFoundError(f"no briefing markdown found in {OUTPUTS_DIR}")
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0]


def _build_summary(content: str, limit: int = 220) -> str:
    rows = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("```"):
            continue
        if "|" in s and s.count("|") >= 2:
            continue
        rows.append(s)
    merged = " ".join(rows)
    merged = re.sub(r"\s+", " ", merged).strip()
    if not merged:
        merged = "市场新闻简报自动推送"
    return merged[:limit]


def _clean_line(s: str) -> str:
    x = re.sub(r"\s+", " ", str(s or "")).strip()
    x = x.replace("•", "-").replace("：", ":")
    return x


def _strip_non_public_noise(content: str) -> str:
    out: list[str] = []
    in_code = False
    for raw in str(content or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s:
            out.append("")
            continue
        low = s.lower()
        if "trace_id" in low or "debug" in low:
            continue
        if "/users/" in low or "\\users\\" in low:
            continue
        if "localhost" in low or "127.0.0.1" in low:
            continue
        if s.startswith("{") and s.endswith("}"):
            continue
        out.append(s)
    text = "\n".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _parse_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "正文"
    sections[current] = []
    for raw in str(content or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        s = line.strip()
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", s)
        if m:
            current = m.group(1).strip() or "正文"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _pick_section(parsed: dict[str, str], keywords: list[str]) -> str:
    for k, v in parsed.items():
        kk = k.lower()
        if any(x.lower() in kk for x in keywords):
            if v.strip():
                return v.strip()
    return ""


def _to_bullets(text: str, max_items: int = 6) -> list[str]:
    chunks: list[str] = []
    for raw in re.split(r"[\n；;。]", str(text or "")):
        s = _clean_line(raw)
        if not s:
            continue
        if s.startswith("-"):
            s = s[1:].strip()
        if len(s) < 4:
            continue
        chunks.append(s)
    out: list[str] = []
    seen: set[str] = set()
    for x in chunks:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        if len(out) >= max_items:
            break
    return out


def _traditional_public_transform(raw_content: str, title: str, trace_id: str) -> tuple[str, str, str, dict]:
    cleaned = _strip_non_public_noise(raw_content)
    parsed = _parse_sections(cleaned)

    sec_exec = _pick_section(parsed, ["执行摘要", "摘要", "结论", "summary", "executive"])
    sec_market = _pick_section(parsed, ["市场", "宏观", "行情", "新闻", "事件", "market"])
    sec_signal = _pick_section(parsed, ["信号", "因子", "资金流", "情绪", "narrative", "flow"])
    sec_risk = _pick_section(parsed, ["风险", "失效", "注意", "risk"])
    sec_watch = _pick_section(parsed, ["观察", "清单", "watchlist", "候选", "建议"])

    if not sec_exec:
        sec_exec = cleaned[:1200]
    if not sec_market:
        sec_market = cleaned[:1400]
    if not sec_signal:
        sec_signal = cleaned[:1400]
    if not sec_risk:
        sec_risk = "短期波动与流动性变化可能放大价格偏离，需结合仓位与风险预算动态调整。"
    if not sec_watch:
        sec_watch = cleaned[:800]

    exec_bullets = _to_bullets(sec_exec, max_items=4)
    market_bullets = _to_bullets(sec_market, max_items=5)
    signal_bullets = _to_bullets(sec_signal, max_items=5)
    risk_bullets = _to_bullets(sec_risk, max_items=4)
    watch_bullets = _to_bullets(sec_watch, max_items=5)

    if not exec_bullets:
        exec_bullets = [_build_summary(cleaned, limit=180)]
    if not market_bullets:
        market_bullets = ["市场处于事件驱动阶段，需重点跟踪消息面与流动性变化。"]
    if not signal_bullets:
        signal_bullets = ["当前信号以结构性分化为主，建议结合因子一致性判断机会质量。"]
    if not risk_bullets:
        risk_bullets = ["若成交深度下降或风险事件升级，需下调风险暴露。"]
    if not watch_bullets:
        watch_bullets = ["建议跟踪高关注度与高流动性标的的持续性。"]

    public_title = f"{title}｜对外发布版"
    public_summary = _build_summary("\n".join(exec_bullets), limit=220)
    published_at = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    content = "\n".join(
        [
            f"# {public_title}",
            "",
            f"> 发布时间: {published_at}",
            f"> 跟踪编号: {trace_id}",
            "",
            "## 一、执行摘要",
            *[f"- {x}" for x in exec_bullets],
            "",
            "## 二、市场背景与驱动",
            *[f"- {x}" for x in market_bullets],
            "",
            "## 三、关键信号与证据",
            *[f"- {x}" for x in signal_bullets],
            "",
            "## 四、情景与风险提示",
            *[f"- {x}" for x in risk_bullets],
            "",
            "## 五、观察清单（非投资建议）",
            *[f"- {x}" for x in watch_bullets],
            "",
            "## 六、合规声明",
            "- 本内容仅用于市场信息交流，不构成任何投资建议或收益承诺。",
            "- 市场有风险，决策需结合自身风险承受能力与独立判断。",
            "",
        ]
    ).strip() + "\n"
    meta = {
        "transform_profile": "traditional_sellside_v1",
        "source_chars": len(raw_content or ""),
        "public_chars": len(content),
        "sections_used": {
            "exec": bool(sec_exec),
            "market": bool(sec_market),
            "signal": bool(sec_signal),
            "risk": bool(sec_risk),
            "watch": bool(sec_watch),
        },
    }
    return public_title, public_summary, content, meta


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")



def _load_local_env(path: Path) -> None:
    if not path.exists() or (not path.is_file()):
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        k = key.strip()
        if not k:
            continue
        v = val.strip()
        if len(v) >= 2 and ((v[0] == "'" and v[-1] == "'") or (v[0] == '"' and v[-1] == '"')):
            v = v[1:-1]
        if os.environ.get(k) is None:
            os.environ[k] = v


def _request_with_retry(method: str, url: str, headers: dict, payload: dict, timeout_sec: int, max_retries: int) -> tuple[dict, int, int]:
    retry_wait = [10, 30, 90]
    attempts = 0
    last_error = ""
    while attempts < max(1, max_retries):
        attempts += 1
        try:
            resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=float(timeout_sec))
            status = int(resp.status_code)
            body = resp.json() if resp.text else {}
            if status == 401:
                raise RuntimeError("401 unauthorized")
            if status >= 500:
                raise RuntimeError(f"{status} server_error")
            return body if isinstance(body, dict) else {}, status, attempts
        except Exception as exc:
            last_error = str(exc)
            if "401" in last_error:
                raise
            if attempts >= max(1, max_retries):
                raise RuntimeError(last_error)
            time.sleep(retry_wait[min(attempts - 1, len(retry_wait) - 1)])
    raise RuntimeError(last_error or "request_failed")


def _check_api_reachable(api_base: str, timeout_sec: int) -> tuple[bool, int, str]:
    url = f"{api_base.rstrip('/')}/reports"
    try:
        resp = requests.get(url, params={"page": 1, "page_size": 1}, timeout=float(max(2, timeout_sec)))
        status = int(resp.status_code)
        if status >= 500:
            return False, status, "server_error"
        return True, status, ""
    except Exception as exc:
        return False, 0, str(exc)


def main() -> int:
    _load_local_env(LOCAL_ENV_PATH)
    parser = argparse.ArgumentParser(description="Push latest news briefing to production report API")
    parser.add_argument("--artifact", type=str, default="", help="markdown artifact path")
    default_mode = str(os.environ.get("REPORT_PUSH_MODE") or "prod").strip().lower() or "prod"
    default_api_base = os.environ.get("REPORT_API_BASE_PROD") or "http://8.209.238.108/api/v1"
    if default_mode == "test":
        default_api_base = os.environ.get("REPORT_API_BASE_TEST") or default_api_base
    parser.add_argument("--api-base", type=str, default=default_api_base)
    parser.add_argument("--api-key", type=str, default=os.environ.get("INTERNAL_API_KEY") or "")
    parser.add_argument("--state-file", type=str, default=(os.environ.get("REPORT_PUSH_STATE_FILE") or str(RAW_DIR / "report_push_state.json")))
    parser.add_argument("--receipt-file", type=str, default=(os.environ.get("REPORT_PUSH_RECEIPT_FILE") or str(RAW_DIR / "report_push_outbox.jsonl")))
    parser.add_argument("--trace-id", type=str, default="")
    parser.add_argument("--title", type=str, default="")
    parser.add_argument("--summary", type=str, default="")
    parser.add_argument("--related-coins", type=str, default="BTC,ETH")
    parser.add_argument(
        "--transform-profile",
        type=str,
        default=str(os.environ.get("REPORT_PUSH_TRANSFORM_PROFILE") or "daily_report_v2_tavily"),
    )
    parser.add_argument(
        "--disable-transform",
        action="store_true",
        help="push raw content directly without public transform",
    )
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--force-create", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.preflight:
        env_exists = LOCAL_ENV_PATH.exists() and LOCAL_ENV_PATH.is_file()
        api_key_present = bool(str(args.api_key or "").strip())
        api_ok, api_status, api_error = _check_api_reachable(args.api_base, args.timeout_sec)
        preflight = {
            "ok": bool(env_exists and api_key_present and api_ok),
            "env_file": str(LOCAL_ENV_PATH),
            "env_exists": bool(env_exists),
            "api_base": args.api_base,
            "api_reachable": bool(api_ok),
            "api_status": int(api_status),
            "api_error": api_error,
            "api_key_present": bool(api_key_present),
            "checked_at": _now_iso(),
        }
        print(json.dumps(preflight, ensure_ascii=False))
        return 0 if preflight["ok"] else 2

    if not args.api_key:
        raise RuntimeError("INTERNAL_API_KEY is required")

    artifact_path = Path(args.artifact).resolve() if args.artifact else _pick_latest_artifact().resolve()
    if not artifact_path.exists():
        raise FileNotFoundError(f"artifact not found: {artifact_path}")
    content = artifact_path.read_text(encoding="utf-8", errors="replace")
    now = datetime.now()
    trace_id = args.trace_id.strip() or f"news_digest_push_{now.strftime('%Y%m%d_%H%M%S')}"
    title = args.title.strip() or f"市场新闻简报 {now.strftime('%Y-%m-%d %H:%M')}"
    summary = args.summary.strip() or _build_summary(content)
    source_content = content
    transform_profile = str(args.transform_profile or "").strip() or "daily_report_v2_tavily"
    transform_meta: dict = {"transform_profile": "raw_passthrough", "source_chars": len(source_content), "public_chars": len(source_content)}
    public_artifact_path = artifact_path
    if not args.disable_transform:
        if transform_profile == "traditional_sellside_v1":
            pub_title, pub_summary, pub_content, tmeta = _traditional_public_transform(source_content, title, trace_id)
            title = pub_title
            summary = args.summary.strip() or pub_summary
            content = pub_content
            transform_meta = tmeta
            public_dir = RAW_DIR / "report_public"
            public_dir.mkdir(parents=True, exist_ok=True)
            public_artifact_path = public_dir / f"{artifact_path.stem}.public.md"
            public_artifact_path.write_text(content, encoding="utf-8")
        elif transform_profile == "daily_report_v2_tavily":
            transformer = _load_daily_transformer()
            if transformer is None:
                raise RuntimeError("daily_report_v2_tavily requires scripts/daily_publish_transform.py")
            transformed = transformer(
                raw_content=source_content,
                title=title,
                tavily_api_key=str(os.environ.get("TAVILY_API_KEY") or "").strip(),
            )
            pub_title = str(transformed.get("title") or title).strip() or title
            pub_summary = str(transformed.get("summary") or summary).strip() or summary
            pub_content = str(transformed.get("content") or source_content)
            tmeta = transformed.get("meta") if isinstance(transformed.get("meta"), dict) else {}
            title = pub_title
            summary = args.summary.strip() or pub_summary
            content = pub_content
            transform_meta = {
                "transform_profile": "daily_report_v2_tavily",
                **tmeta,
            }
            public_dir = RAW_DIR / "report_public"
            public_dir.mkdir(parents=True, exist_ok=True)
            public_artifact_path = public_dir / f"{artifact_path.stem}.public.md"
            public_artifact_path.write_text(content, encoding="utf-8")
        elif transform_profile == "daily_report_v3_llm":
            mod_path = SCRIPT_DIR / "daily_publish_transform.py"
            if not mod_path.exists():
                raise RuntimeError("daily_report_v3_llm requires scripts/daily_publish_transform.py")
            spec = importlib.util.spec_from_file_location("daily_publish_transform", mod_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("failed to load daily_publish_transform.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            fn = getattr(module, "transform_daily_report_v3", None)
            if not callable(fn):
                raise RuntimeError("daily_publish_transform.py missing transform_daily_report_v3")
            transformed = fn(
                raw_content=source_content,
                title=title,
                tavily_api_key=str(os.environ.get("TAVILY_API_KEY") or "").strip(),
            )
            pub_title = str(transformed.get("title") or title).strip() or title
            pub_summary = str(transformed.get("summary") or summary).strip() or summary
            pub_content = str(transformed.get("content") or source_content)
            tmeta = transformed.get("meta") if isinstance(transformed.get("meta"), dict) else {}
            title = pub_title
            summary = args.summary.strip() or pub_summary
            content = pub_content
            transform_meta = {
                "transform_profile": "daily_report_v3_llm",
                **tmeta,
            }
            public_dir = RAW_DIR / "report_public"
            public_dir.mkdir(parents=True, exist_ok=True)
            public_artifact_path = public_dir / f"{artifact_path.stem}.public.md"
            public_artifact_path.write_text(content, encoding="utf-8")
        else:
            raise RuntimeError(f"unsupported transform profile: {transform_profile}")
    related_coins = [x.strip().upper() for x in str(args.related_coins or "").split(",") if x.strip()]
    payload = {
        "title": title[:256],
        "summary": summary,
        "content": content,
        "related_coins": related_coins,
    }

    state_path = Path(args.state_file).resolve()
    receipt_path = Path(args.receipt_file).resolve()
    state = _load_state(state_path)
    report_id = state.get("report_id")
    method = "POST"
    endpoint = f"{args.api_base.rstrip('/')}/admin/reports"
    if report_id and (not args.force_create):
        method = "PUT"
        endpoint = f"{args.api_base.rstrip('/')}/admin/reports/{int(report_id)}"

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": args.api_key,
    }

    receipt = {
        "trace_id": trace_id,
        "artifact_path": str(artifact_path),
        "artifact_path_raw": str(artifact_path),
        "artifact_path_public": str(public_artifact_path),
        "push_mode": default_mode,
        "api_base": args.api_base,
        "transform_profile": transform_meta.get("transform_profile", transform_profile),
        "transform_meta": transform_meta,
        "method": method,
        "report_id": int(report_id) if report_id else 0,
        "http_status": 0,
        "attempts": 0,
        "pushed_at": _now_iso(),
        "ok": False,
    }

    qa_gate = str(transform_meta.get("qa_gate") or "").strip()
    qa_score = transform_meta.get("qa_score")
    qa_fail_reasons = transform_meta.get("qa_fail_reasons")
    if qa_gate:
        receipt["qa_gate"] = qa_gate
    if qa_score is not None:
        receipt["qa_score"] = qa_score
    if qa_fail_reasons is not None:
        receipt["qa_fail_reasons"] = qa_fail_reasons

    if args.dry_run:
        receipt["ok"] = True
        receipt["dry_run"] = True
        _append_jsonl(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False))
        return 0

    if qa_gate == "fail":
        receipt["ok"] = False
        receipt["dry_run"] = False
        receipt["error"] = "qa_gate=fail, refuse_to_push"
        _append_jsonl(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False))
        return 2

    body, http_status, attempts = _request_with_retry(
        method=method,
        url=endpoint,
        headers=headers,
        payload=payload,
        timeout_sec=max(2, int(args.timeout_sec)),
        max_retries=max(1, int(args.max_retries)),
    )
    code = int(body.get("code", -1)) if isinstance(body, dict) else -1
    if code != 0:
        raise RuntimeError(f"api_error: code={code}, body={body}")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    new_report_id = int(data.get("id") or report_id or 0)
    if new_report_id <= 0:
        raise RuntimeError(f"invalid_report_id: {data}")
    state.update(
        {
            "report_id": new_report_id,
            "last_trace_id": trace_id,
            "last_artifact_path_raw": str(artifact_path),
            "last_artifact_path_public": str(public_artifact_path),
            "last_pushed_at": _now_iso(),
            "api_base": args.api_base,
            "transform_profile": transform_meta.get("transform_profile", transform_profile),
        }
    )
    _save_state(state_path, state)
    receipt.update(
        {
            "ok": True,
            "report_id": new_report_id,
            "http_status": int(http_status),
            "attempts": int(attempts),
            "response_code": code,
            "pushed_at": _now_iso(),
        }
    )
    _append_jsonl(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

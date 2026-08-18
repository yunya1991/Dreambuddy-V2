import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse as urllib_parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clip_str(s: Any, max_len: int) -> str:
    try:
        s0 = "" if s is None else str(s)
    except Exception:
        s0 = ""
    s0 = s0.strip()
    if max_len <= 0:
        return ""
    if len(s0) <= max_len:
        return s0
    return s0[: max(0, max_len - 1)] + "…"


def _twitter_env_bearer_token() -> Optional[str]:
    try:
        v = str(os.environ.get("TWITTER_BEARER_TOKEN", "") or "").strip()
        if v:
            return v
    except Exception:
        pass
    try:
        v2 = str(os.environ.get("TWITTER_TOKEN", "") or "").strip()
        if v2:
            return v2
    except Exception:
        pass
    return None


def _twitter_env_oauth1_keys() -> Optional[Dict[str, str]]:
    ck = None
    cs = None
    at = None
    ats = None
    try:
        ck = str(os.environ.get("TWITTER_CONSUMER_KEY", "") or "").strip() or None
    except Exception:
        ck = None
    try:
        cs = str(os.environ.get("TWITTER_CONSUMER_SECRET", "") or "").strip() or None
    except Exception:
        cs = None
    try:
        at = str(os.environ.get("TWITTER_ACCESS_TOKEN", "") or "").strip() or None
    except Exception:
        at = None
    try:
        ats = str(os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "") or "").strip() or None
    except Exception:
        ats = None

    if not ck or not cs or not at or not ats:
        return None
    return {
        "consumer_key": ck,
        "consumer_secret": cs,
        "access_token": at,
        "access_token_secret": ats,
    }


def _oauth1_pct_encode(v: Any) -> str:
    try:
        s = "" if v is None else str(v)
    except Exception:
        s = ""
    return urllib_parse.quote(s, safe="~-._")


def _oauth1_signature_base(method: str, base_url: str, params: Dict[str, Any]) -> str:
    items = []
    for k, v in (params or {}).items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            for vv in v:
                items.append((_oauth1_pct_encode(k), _oauth1_pct_encode(vv)))
        else:
            items.append((_oauth1_pct_encode(k), _oauth1_pct_encode(v)))
    items.sort(key=lambda x: (x[0], x[1]))
    param_str = "&".join([f"{k}={v}" for k, v in items])
    return "&".join([
        _oauth1_pct_encode(str(method or "").upper()),
        _oauth1_pct_encode(str(base_url or "")),
        _oauth1_pct_encode(param_str),
    ])


def _oauth1_sign_hmac_sha1(base_str: str, consumer_secret: str, token_secret: str) -> str:
    key = f"{_oauth1_pct_encode(consumer_secret)}&{_oauth1_pct_encode(token_secret)}".encode("utf-8")
    msg = str(base_str or "").encode("utf-8")
    sig = hmac.new(key, msg, hashlib.sha1).digest()
    return base64.b64encode(sig).decode("utf-8")


def _oauth1_auth_header(params: Dict[str, Any]) -> str:
    keys = [
        "oauth_consumer_key",
        "oauth_body_hash",
        "oauth_nonce",
        "oauth_signature",
        "oauth_signature_method",
        "oauth_timestamp",
        "oauth_token",
        "oauth_version",
    ]
    parts = []
    for k in keys:
        if k not in params:
            continue
        parts.append(f"{_oauth1_pct_encode(k)}=\"{_oauth1_pct_encode(params.get(k))}\"")
    return "OAuth " + ", ".join(parts)


def _http_post(url: str, *, headers: Dict[str, str], body: bytes, timeout: float) -> Tuple[int, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            raw = resp.read()
        try:
            return code, json.loads(raw.decode("utf-8"))
        except Exception:
            return code, {"raw": raw.decode("utf-8", errors="ignore")[:2000]}
    except urllib.error.HTTPError as e:
        try:
            code = int(getattr(e, "code", 0) or 0)
        except Exception:
            code = 0
        raw = b""
        try:
            raw = e.read() or b""
        except Exception:
            raw = b""
        try:
            return code, json.loads(raw.decode("utf-8"))
        except Exception:
            return code, {"raw": raw.decode("utf-8", errors="ignore")[:2000]}
    except Exception as e:
        return 0, {"error": str(e)}


def _twitter_post_v2(text: str, bearer_token: str, *, timeout: float = 20.0) -> Tuple[bool, Dict[str, Any]]:
    txt = str(text or "").strip()
    if not txt:
        return False, {"error": "empty_text"}
    if len(txt) > 280:
        txt = _clip_str(txt, 280)
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    payload = {"text": txt}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    code, obj = _http_post("https://api.twitter.com/2/tweets", headers=headers, body=body, timeout=float(timeout))
    ok = 200 <= int(code) < 300
    out: Dict[str, Any] = {"status_code": int(code), "body": obj}
    if ok and isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, dict) and data.get("id") is not None:
            out["tweet_id"] = str(data.get("id"))
    if not ok and isinstance(obj, dict) and obj.get("error") is not None:
        out["error"] = obj.get("error")
    return bool(ok), out


def _twitter_post_v2_oauth1(text: str, oauth1: Dict[str, str], *, timeout: float = 20.0) -> Tuple[bool, Dict[str, Any]]:
    txt = str(text or "").strip()
    if not txt:
        return False, {"error": "empty_text"}
    if len(txt) > 280:
        txt = _clip_str(txt, 280)

    url = "https://api.twitter.com/2/tweets"
    payload = {"text": txt}
    nonce = hashlib.sha256(f"{time.time()}|{os.getpid()}".encode("utf-8")).hexdigest()[:32]
    ts = str(int(time.time()))
    oauth_params: Dict[str, Any] = {
        "oauth_consumer_key": oauth1.get("consumer_key"),
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_token": oauth1.get("access_token"),
        "oauth_version": "1.0",
    }

    body_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    body_hash = base64.b64encode(hashlib.sha1(body_str.encode("utf-8")).digest()).decode("utf-8")
    sign_params = dict(oauth_params)
    sign_params["oauth_body_hash"] = body_hash
    base_str = _oauth1_signature_base("POST", url, sign_params)
    sig = _oauth1_sign_hmac_sha1(base_str, oauth1.get("consumer_secret") or "", oauth1.get("access_token_secret") or "")
    oauth_params["oauth_signature"] = sig
    oauth_params["oauth_body_hash"] = body_hash

    headers = {
        "Authorization": _oauth1_auth_header(oauth_params),
        "Content-Type": "application/json",
    }
    code, obj = _http_post(url, headers=headers, body=body_str.encode("utf-8"), timeout=float(timeout))
    ok = 200 <= int(code) < 300
    out: Dict[str, Any] = {"status_code": int(code), "body": obj}
    if ok and isinstance(obj, dict):
        data = obj.get("data")
        if isinstance(data, dict) and data.get("id") is not None:
            out["tweet_id"] = str(data.get("id"))
    if not ok and isinstance(obj, dict) and obj.get("error") is not None:
        out["error"] = obj.get("error")
    return bool(ok), out


def _twitter_send_text(text: str, *, timeout: float = 20.0) -> Tuple[bool, Dict[str, Any]]:
    oauth1 = _twitter_env_oauth1_keys()
    if oauth1 is not None:
        return _twitter_post_v2_oauth1(text=text, oauth1=oauth1, timeout=float(timeout))
    bearer = _twitter_env_bearer_token()
    if bearer is not None:
        return _twitter_post_v2(text=text, bearer_token=bearer, timeout=float(timeout))
    return False, {"error": "missing_twitter_credentials"}


def _load_processed_ids(receipts_path: Path) -> Set[str]:
    done: Set[str] = set()
    if not receipts_path.exists():
        return done
    try:
        with open(receipts_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip("\n")
                if not s.strip():
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("channel") or "").strip().lower() != "twitter":
                    continue
                tid = obj.get("id")
                if tid is None:
                    continue
                done.add(str(tid))
    except Exception:
        return done
    return done


def _append_receipt(receipts_path: Path, receipt: Dict[str, Any]) -> None:
    try:
        with open(receipts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _iter_outbox_items(outbox_path: Path, *, tail_lines: int) -> Iterable[Dict[str, Any]]:
    if not outbox_path.exists():
        return []
    lines: List[str] = []
    try:
        with open(outbox_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    if tail_lines > 0 and len(lines) > tail_lines:
        lines = lines[-tail_lines:]
    out: List[Dict[str, Any]] = []
    for raw in lines:
        s = raw.strip("\n")
        if not s.strip():
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _default_outbox_dir() -> Path:
    p1 = Path(__file__).resolve().parent.parent / "user_data" / "agent_outbox"
    if p1.exists():
        return p1
    return Path.cwd() / "user_data" / "agent_outbox"


def _parse_dotenv_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    for raw in txt.splitlines():
        s = str(raw or "").strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if not k:
            continue
        v = v.strip()
        if (len(v) >= 2) and ((v[0] == v[-1]) and (v[0] in ("\"", "'"))):
            v = v[1:-1]
        out[k] = v
    return out


def _load_dotenv_optional(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {"ok": True, "loaded": False, "path": None, "count": 0}
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "loaded": False, "path": str(p), "error": "not_found", "count": 0}
    kv = _parse_dotenv_file(p)
    n = 0
    for k, v in kv.items():
        if k in os.environ:
            continue
        os.environ[k] = v
        n += 1
    return {"ok": True, "loaded": True, "path": str(p), "count": int(n)}


def _default_env_file() -> Optional[Path]:
    base = Path(__file__).resolve().parent.parent
    p2 = base / "user_data" / ".env"
    if p2.exists():
        return p2
    p1 = base / ".env"
    if p1.exists():
        return p1
    return None


def _auth_status() -> Dict[str, Any]:
    has_bearer = bool(_twitter_env_bearer_token())
    has_oauth1 = bool(_twitter_env_oauth1_keys())
    mode = "none"
    if has_bearer:
        mode = "bearer"
    elif has_oauth1:
        mode = "oauth1"
    missing: List[str] = []
    if not has_bearer:
        missing.extend(["TWITTER_BEARER_TOKEN", "TWITTER_TOKEN"])
    if not has_oauth1:
        missing.extend(["TWITTER_CONSUMER_KEY", "TWITTER_CONSUMER_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET"])
    return {"ok": True, "auth_mode": mode, "has_bearer": bool(has_bearer), "has_oauth1": bool(has_oauth1), "missing": missing}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outbox-dir", default=None)
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--print-auth", action="store_true")
    ap.add_argument("--only-id", default=None)
    ap.add_argument("--only-trace", default=None)
    ap.add_argument("--tail-lines", type=int, default=8000)
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--sleep-sec", type=float, default=1.0)
    ap.add_argument("--timeout-sec", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    env_file = None
    if args.env_file is not None and str(args.env_file).strip():
        env_file = Path(str(args.env_file)).expanduser()
    else:
        env_file = _default_env_file()
    _load_dotenv_optional(env_file)

    if bool(args.print_auth):
        sys.stdout.write(json.dumps(_auth_status(), ensure_ascii=False) + "\n")
        return 0

    outbox_dir = _default_outbox_dir() if not args.outbox_dir else Path(str(args.outbox_dir)).expanduser()
    outbox_path = outbox_dir / "twitter.jsonl"
    receipts_path = outbox_dir / "delivery_receipts.jsonl"

    only_id = str(args.only_id or "").strip() or None
    only_trace = str(args.only_trace or "").strip() or None

    tail_lines = int(args.tail_lines or 0)
    limit = max(0, int(args.limit or 0))
    sleep_sec = float(max(0.0, float(args.sleep_sec or 0.0)))
    timeout_sec = float(max(1.0, float(args.timeout_sec or 20.0)))

    processed = _load_processed_ids(receipts_path)
    items = _iter_outbox_items(outbox_path, tail_lines=tail_lines)
    sent = 0
    skipped = 0

    for env in items:
        if limit > 0 and sent >= limit:
            break
        if str(env.get("channel") or "").strip().lower() != "twitter":
            continue
        if str(env.get("type") or "").strip().lower() != "push.send":
            continue
        eid = str(env.get("id") or "").strip()
        if not eid:
            continue
        if only_id is not None and eid != only_id:
            continue
        if eid in processed:
            continue
        msg = str(env.get("message") or "").strip()
        if not msg:
            processed.add(eid)
            continue

        trace_id = str(env.get("trace_id") or eid).strip() or eid
        if only_trace is not None and trace_id != only_trace:
            continue
        idem = None
        try:
            idem = str(env.get("idempotency_key") or "").strip() or None
        except Exception:
            idem = None

        expired = False
        try:
            exp = env.get("expires_at")
            if exp is not None and int(exp) > 0 and int(_now_ms()) > int(exp):
                expired = True
        except Exception:
            expired = False
        if expired:
            receipt = {
                "id": eid,
                "trace_id": trace_id,
                "channel": "twitter",
                "ok": False,
                "attempt": 1,
                "provider_msg_id": None,
                "status_code": None,
                "error": "expired",
                "ts": int(_now_ms()),
                "idempotency_key": idem,
            }
            if not bool(args.dry_run):
                _append_receipt(receipts_path, receipt)
            processed.add(eid)
            skipped += 1
            continue

        if bool(args.dry_run):
            sys.stdout.write(json.dumps({"dry_run": True, "id": eid, "trace_id": trace_id, "len": len(msg)}, ensure_ascii=False) + "\n")
            sent += 1
            continue

        ok, result = _twitter_send_text(msg, timeout=float(timeout_sec))
        tweet_id = None
        try:
            tweet_id = str(result.get("tweet_id") or "").strip() or None
        except Exception:
            tweet_id = None
        try:
            status_code = (None if result.get("status_code") is None else int(result.get("status_code") or 0))
        except Exception:
            status_code = None
        err_obj = None
        if not ok:
            err_obj = result.get("error") if result.get("error") is not None else result.get("body")

        receipt = {
            "id": eid,
            "trace_id": trace_id,
            "channel": "twitter",
            "ok": bool(ok),
            "attempt": 1,
            "provider_msg_id": tweet_id,
            "status_code": status_code,
            "error": (None if ok else _clip_str(err_obj, 600)),
            "ts": int(_now_ms()),
            "idempotency_key": idem,
        }
        _append_receipt(receipts_path, receipt)
        processed.add(eid)
        sys.stdout.write(json.dumps({"ok": bool(ok), "id": eid, "trace_id": trace_id, "tweet_id": tweet_id, "status_code": status_code}, ensure_ascii=False) + "\n")
        sent += 1
        if sleep_sec > 0:
            time.sleep(float(sleep_sec))

    sys.stdout.write(json.dumps({"ok": True, "outbox": str(outbox_path), "receipts": str(receipts_path), "sent": int(sent), "skipped": int(skipped)}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

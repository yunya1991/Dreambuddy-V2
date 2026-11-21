"""隐私、凭据与提交门禁：redact、容器判定、grant 签发/校验。"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from adapters.base import GateDenied, date_key, target_fingerprint

GRANT_TTL_MS = 2 * 3600 * 1000
KEYCHAIN_PREFIX = "com.reservation-assist"

MIN_LOGIN_DAYS = 3
MIN_LOGIN_SAMPLES = 30
MIN_SUBMIT_DRILLS = 20

_ID_RE = re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_SECRET_RE = re.compile(
    r"(?i)\b(cookie|set-cookie|authorization|token|access_token|sessionid)\b(\s*[:=]\s*)(\S+)"
)
_ADDR_RE = re.compile(r"((?:住址|地址|address)\s*[:：=]\s*)([^\n,;，；]{2,})")

_SECRET_KEYS = {"cookie", "set-cookie", "authorization", "token", "access_token", "refresh_token"}
_ADDRESS_KEYS = {"address", "住址", "地址"}


def redact(text: str) -> str:
    """证件号、手机号、cookie/token、地址统一脱敏；可重复调用。"""
    if not text:
        return text
    out = _ID_RE.sub(lambda m: m.group(1)[:4] + "**********" + m.group(1)[-4:], text)
    out = _PHONE_RE.sub(lambda m: "{}****{}".format(m.group(1), m.group(3)), out)
    out = _SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", out)
    out = _ADDR_RE.sub(lambda m: m.group(1) + m.group(2)[:2] + "***", out)
    return out


def redact_obj(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SECRET_KEYS:
                output[key] = "[REDACTED]"
            elif lowered in _ADDRESS_KEYS and isinstance(item, str):
                output[key] = item[:2] + "***"
            else:
                output[key] = redact_obj(item)
        return output
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    return value


def is_container() -> bool:
    if os.environ.get("RA_CONTAINER") == "1":
        return True
    if Path("/.dockerenv").exists():
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    cgroup = Path("/proc/1/cgroup")
    if cgroup.is_file():
        try:
            content = cgroup.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return any(mark in content for mark in ("docker", "kubepods", "containerd"))
    return False


def env_allows_submit(env: dict | None = None) -> bool:
    return (env or os.environ).get("RA_ALLOW_SUBMIT", "1") != "0"


def secret_for(state_dir: str | Path) -> bytes:
    """本地 HMAC 密钥：优先环境变量，其次 0700 目录下的 0600 文件。"""
    env_secret = os.environ.get("RA_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    path = Path(state_dir) / "secret"
    if path.is_file():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    path.write_bytes(raw)
    path.chmod(0o600)
    return raw


def keychain_service(name: str) -> str:
    return "{}.{}".format(KEYCHAIN_PREFIX, name)


def load_cookie(name: str, timeout: float = 3.0) -> str:
    """从 Keychain 读取登录态 Cookie；失败返回空串，不降级明文。"""
    if not shutil.which("security"):
        return ""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_service(name), "-w"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def store_cookie(name: str, value: str) -> bool:
    """写入/更新 Keychain 条目；只返回是否成功，不回显内容。"""
    if not shutil.which("security") or not value:
        return False
    proc = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            keychain_service(name),
            "-a",
            name,
            "-w",
            value,
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def delete_cookie(name: str) -> bool:
    if not shutil.which("security"):
        return False
    proc = subprocess.run(
        ["security", "delete-generic-password", "-s", keychain_service(name)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def grant_hmac(
    grant_id: str, task_id: str, fingerprint: str, issued_at: int, expires_at: int, secret: bytes
) -> str:
    message = "|".join([grant_id, task_id, fingerprint, str(issued_at), str(expires_at)]).encode(
        "utf-8"
    )
    return hmac_lib.new(secret, message, hashlib.sha256).hexdigest()


def issue_grant(
    task_id: str,
    fingerprint: str,
    secret: bytes,
    now: int | None = None,
    ttl_ms: int = GRANT_TTL_MS,
) -> dict:
    if ttl_ms > GRANT_TTL_MS:
        raise ValueError("grant 有效期不得超过 2 小时")
    issued_at = int(now if now is not None else time.time() * 1000)
    expires_at = issued_at + ttl_ms
    grant_id = secrets.token_hex(8)
    return {
        "id": grant_id,
        "task_id": task_id,
        "fingerprint": fingerprint,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "hmac": grant_hmac(grant_id, task_id, fingerprint, issued_at, expires_at, secret),
    }


def verify_grant(row: dict | None, fingerprint: str, secret: bytes, now: int | None = None) -> dict:
    if not row:
        raise GateDenied("grant")
    now = int(now if now is not None else time.time() * 1000)
    if int(row["expires_at"]) < now or int(row["issued_at"]) > now + 60_000:
        raise GateDenied("grant")
    if row["fingerprint"] != fingerprint:
        raise GateDenied("grant")
    expected = grant_hmac(
        row["id"],
        row["task_id"],
        row["fingerprint"],
        int(row["issued_at"]),
        int(row["expires_at"]),
        secret,
    )
    if not hmac_lib.compare_digest(expected, row["hmac"]):
        raise GateDenied("grant")
    return row


def evaluate_submit(
    task: dict,
    adapter,
    store,
    secret: bytes,
    env: dict | None = None,
    now: int | None = None,
    fingerprint: str | None = None,
) -> dict:
    """提交前置条件全部满足才返回 grant；否则抛 GateDenied。"""
    if not env_allows_submit(env) or is_container():
        raise GateDenied("env")
    if not getattr(adapter, "SUBMIT_READY", False):
        raise GateDenied("adapter_not_ready")
    rule = task.get("rule") or {}
    if not int(task.get("submit_enabled") or 0):
        raise GateDenied("task_config")
    if int(task.get("max_orders") or 1) != 1:
        raise GateDenied("task_config")
    if rule.get("max_price") is None:
        raise GateDenied("task_config")
    if not rule.get("identity_selected"):
        raise GateDenied("task_config")
    fp = fingerprint or target_fingerprint(task, now)
    if store.has_terminal_submit(task["id"], fp):
        raise GateDenied("already_submitted")
    return verify_grant(store.get_grant(task["id"]), fp, secret, now)


def evaluate_readiness(adapter: str, login_samples: list[dict], drills: list[dict]) -> dict:
    """就绪实验判定：只读记录，不发网络请求，也不自动打开 SUBMIT_READY。"""
    days = sorted({date_key(item["at"]) for item in login_samples})
    failed = [item for item in drills if not item["ok"]]
    captcha_blocked = [
        item for item in drills if (item.get("detail") or {}).get("captcha") not in (None, "none")
    ]
    checks = [
        {
            "name": "login_days",
            "ok": len(days) >= MIN_LOGIN_DAYS,
            "detail": "{} 天（需 ≥{}）".format(len(days), MIN_LOGIN_DAYS),
        },
        {
            "name": "login_samples",
            "ok": len(login_samples) >= MIN_LOGIN_SAMPLES,
            "detail": "{} 次（需 ≥{}，约每 2h 一次）".format(len(login_samples), MIN_LOGIN_SAMPLES),
        },
        {
            "name": "submit_drills",
            "ok": len(drills) >= MIN_SUBMIT_DRILLS,
            "detail": "{} 次（需 ≥{}，不付款）".format(len(drills), MIN_SUBMIT_DRILLS),
        },
        {
            "name": "no_wrong_target_or_duplicate",
            "ok": not failed,
            "detail": "异常 {} 次（需 0）".format(len(failed)),
        },
        {
            "name": "no_unhandled_captcha",
            "ok": not captcha_blocked,
            "detail": "需人工验证 {} 次（需 0）".format(len(captcha_blocked)),
        },
    ]
    return {
        "adapter": adapter,
        "ready": all(item["ok"] for item in checks),
        "checks": checks,
        "login_days": days,
        "login_samples": len(login_samples),
        "submit_drills": len(drills),
    }

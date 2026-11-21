"""隐私与凭据：redact、容器判定、执行开关、网关 Token 管理。

约定：本文件不含平台名与绝对路径；状态目录由调用方传入。
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

_CN_ID_RE = re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)")
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
    out = _CN_ID_RE.sub(lambda m: m.group(1)[:4] + "**********" + m.group(1)[-4:], text)
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
    """容器/云主机判定；命中则执行层拒绝派发（对齐上游提交门禁）。"""
    if os.environ.get("MRA_CONTAINER") == "1":
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


def env_allows_execute(env: dict | None = None) -> bool:
    return (env or os.environ).get("MRA_ALLOW_EXECUTE", "1") != "0"


def token_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "gateway_token"


def load_token(state_dir: str | Path) -> str:
    """读取网关 Token；不存在则生成并落盘（0600）。"""
    path = token_path(state_dir)
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return rotate_token(state_dir)


def rotate_token(state_dir: str | Path) -> str:
    path = token_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(24)
    path.write_text(value, encoding="utf-8")
    try:
        path.chmod(0o600)
    except PermissionError:
        pass
    return value


def token_matches(expected: str, provided: str) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


def now_ms() -> int:
    return int(time.time() * 1000)

#!/usr/bin/env python3
"""云端通道治理（P5-1）：Partner 令牌管理与真实探活。

边界：
  - 只管 Partner 数据网关（https://www.neodrm.com/api/partner/v1）的令牌与连通性；
  - 不碰生产云 43.160.201.117，也不碰 DAL 写入口；
  - 令牌只写本地 600 文件，命令输出永不回显令牌。

用法:
    python3 tools/cloud_channel.py status [--json]
    python3 tools/cloud_channel.py token status [--json]
    python3 tools/cloud_channel.py token set --file <来源文件> [--out <目标>]
    python3 tools/cloud_channel.py probe [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

DEFAULT_BASE = "https://www.neodrm.com/api/partner/v1"
ENV_VAR = "DREAMBUDDY_PARTNER_ENV"
MIN_TOKEN_LEN = 8
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{8,}$")
PARTNER_KEYS = ("PARTNER_TOKEN", "PARTNER_TOKEN_FILE", "MDH_ENDPOINT")


def partner_env_path() -> Path:
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".local/share/dreambuddy/partner.env"


def environment() -> Dict[str, str]:
    """合并进程环境与 partner.env（env 优先），只返回 Partner 相关键。"""
    values: Dict[str, str] = {key: os.environ[key] for key in PARTNER_KEYS if os.environ.get(key)}
    path = partner_env_path()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in PARTNER_KEYS:
                values.setdefault(key, value.strip().strip("\"'"))
    return values


def token_status() -> Dict[str, Any]:
    values = environment()
    token = values.get("PARTNER_TOKEN", "").strip()
    token_file = values.get("PARTNER_TOKEN_FILE", "").strip()
    if not token and token_file:
        candidate = Path(os.path.expanduser(token_file))
        if candidate.is_file():
            token = candidate.read_text(encoding="utf-8").strip()
    path = partner_env_path()
    from_env = bool(os.environ.get("PARTNER_TOKEN"))
    return {
        "configured": bool(token),
        "source": "env" if from_env else ("file" if token else "none"),
        "env_file": str(path),
        "env_file_exists": path.is_file(),
        "base": values.get("MDH_ENDPOINT") or DEFAULT_BASE,
    }


def extract_token(text: str) -> str:
    """从 audit.env 片段或纯令牌文件中提取 PARTNER_TOKEN。"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in {"PARTNER_TOKEN", "MDH_TOKEN", "TOKEN"}:
            return value.strip().strip("\"'")
    raw = text.strip()
    for line in raw.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            return candidate.strip("\"'")
    return ""


def validate_token(token: str) -> str:
    if not TOKEN_RE.fullmatch(token or ""):
        raise ValueError("E_CLOUD_AUTH：令牌格式非法（至少 8 位，仅允许 A-Za-z0-9._~+/=-）")
    if len(token) < MIN_TOKEN_LEN:
        raise ValueError("E_CLOUD_AUTH：令牌长度不足 {}".format(MIN_TOKEN_LEN))
    return token


def write_token(token: str, out: Optional[Path] = None) -> Path:
    token = validate_token(token)
    path = out or partner_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PARTNER_TOKEN={}\n".format(token), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def _http_get(url: str, timeout: int) -> int:
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "dreambuddy-cloud-probe/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status)


def probe(
    base: Optional[str] = None,
    timeout: int = 8,
    http_get: Optional[Callable[[str, int], int]] = None,
) -> Dict[str, Any]:
    """分段探活：DNS → TCP/TLS → HTTP，返回可判定的 stage。"""
    url = (base or environment().get("MDH_ENDPOINT") or DEFAULT_BASE).rstrip("/")
    result: Dict[str, Any] = {
        "base": url,
        "ok": False,
        "stage": "",
        "http_status": None,
        "error": "",
    }
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        result.update(stage="dns", error="E_CLOUD_UNAVAILABLE：DNS 失败（{}）".format(exc))
        return result

    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                pass
    except ssl.SSLError as exc:
        result.update(stage="tls", error="E_CLOUD_UNAVAILABLE：TLS 失败（{}）".format(exc))
        return result
    except (OSError, socket.timeout) as exc:
        result.update(stage="tcp", error="E_CLOUD_UNAVAILABLE：TCP 失败（{}）".format(exc))
        return result

    getter = http_get or _http_get
    try:
        status = getter(url + "/", timeout)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        result.update(stage="http", error="E_CLOUD_UNAVAILABLE：HTTP 失败（{}）".format(exc))
        return result

    result["http_status"] = status
    if status >= 500:
        result.update(stage="http", error="E_CLOUD_UNAVAILABLE：网关 5xx（{}）".format(status))
        return result
    result.update(ok=True, stage="http")
    if status in (401, 403):
        result["auth_required"] = True
    return result


def status_report(do_probe: bool = True) -> Dict[str, Any]:
    status = token_status()
    report: Dict[str, Any] = {"token": status, "probe": None}
    if not status["configured"]:
        report["ok"] = False
        report["error"] = (
            "E_CLOUD_AUTH：未配置 PARTNER_TOKEN（写入 {}，或设置 PARTNER_TOKEN_FILE）".format(
                status["env_file"]
            )
        )
        return report
    report["probe"] = probe(status["base"]) if do_probe else None
    report["ok"] = bool(report["probe"] and report["probe"]["ok"])
    if not report["ok"] and report["probe"]:
        report["error"] = report["probe"]["error"]
    return report


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Partner 云端通道：令牌与探活")
    sub = parser.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status", help="令牌状态 + 真实探活")
    p_status.add_argument("--json", action="store_true")
    p_probe = sub.add_parser("probe", help="只做探活")
    p_probe.add_argument("--json", action="store_true")
    p_token = sub.add_parser("token", help="令牌管理")
    p_token.add_argument("action", choices=["status", "set"])
    p_token.add_argument("--file", type=Path, default=None)
    p_token.add_argument("--out", type=Path, default=None)
    p_token.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "token":
        if args.action == "status":
            payload = token_status()
        else:
            if not args.file or not args.file.is_file():
                print("E_INPUT：--file 指向的令牌来源文件不存在", file=sys.stderr)
                return 2
            try:
                token = validate_token(extract_token(args.file.read_text(encoding="utf-8")))
                path = write_token(token, args.out)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            payload = {"written": str(path), "configured": True, "mode": "600"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for key, value in payload.items():
                print("{}: {}".format(key, value))
        return 0
    if args.cmd == "probe":
        result = probe()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    report = status_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        token = report["token"]
        print("通道：Partner 数据网关")
        print("地址：{}".format(token["base"]))
        print(
            "令牌：{}（{}）".format(
                "已配置" if token["configured"] else "未配置", token["env_file"]
            )
        )
        if report.get("probe"):
            probe_info = report["probe"]
            print(
                "探活：{} · stage={} · http={}".format(
                    "OK" if probe_info["ok"] else "FAIL",
                    probe_info["stage"],
                    probe_info.get("http_status"),
                )
            )
        if report.get("error"):
            print(report["error"])
    if not report["ok"]:
        return 2 if not report["token"]["configured"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

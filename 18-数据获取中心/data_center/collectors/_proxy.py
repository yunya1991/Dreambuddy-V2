"""系统代理探测工具 — 供各 collector 复用。

读取 macOS 系统代理（scutil --proxy），返回代理 URL 或 None。
不修改全局环境变量，避免影响飞书/Hermes 等需要直连的调用。
"""
from __future__ import annotations

import os
import re
import subprocess


def system_proxy() -> str | None:
    """返回系统代理 URL（如 http://127.0.0.1:7890），无代理则返回 None。"""
    if os.name != "posix":
        return None
    try:
        out = subprocess.run(
            ["scutil", "--proxy"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return None
    for proto in ("HTTPS", "HTTP"):
        m_en = re.search(rf"{proto}Enable\s*:\s*(\d)", out)
        m_host = re.search(rf"{proto}Proxy\s*:\s*(\S+)", out)
        m_port = re.search(rf"{proto}Port\s*:\s*(\d+)", out)
        if m_en and m_en.group(1) == "1" and m_host and m_port:
            return f"http://{m_host.group(1)}:{m_port.group(1)}"
    return None


def requests_proxies() -> dict:
    """返回 requests 库可用的 proxies dict；无代理则返回空 dict。"""
    proxy = system_proxy()
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}

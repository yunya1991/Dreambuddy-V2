#!/usr/bin/env python3
"""云端通道（可选）：优先走自有网关，失败自动回退本地直连。

约定:
    GET {BASE}/run?skill=market-data-hub&cmd=<命令>&<原参数...>
    BASE 默认 https://www.neodrm.com/api/partner/v1，可用环境变量 MDH_ENDPOINT 覆盖。

超时策略:
    连接（含 TLS 握手）5s，响应 30s —— 该站 TLS 握手偶发抖动，握手与读取必须分开计时，
    否则慢数据集会被误判为网关不可用。

熔断:
    同进程连续 2 次失败后，本进程不再尝试云端。
"""

import http.client
import json
import os
import ssl
import urllib.parse

BASE = os.environ.get("MDH_ENDPOINT", "https://www.neodrm.com/api/partner/v1")
UA = {"User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)"}
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
BREAK_AFTER = 2

_fail = 0
_reason = ""


def route(arg):
    value = (arg or "auto").lower()
    if value not in ("auto", "cloud", "local"):
        raise ValueError("endpoint 取值 auto / cloud / local")
    return value


def available():
    return _fail < BREAK_AFTER


def reason():
    return _reason


def describe():
    if _reason == "no_token":
        return "未配置订阅令牌 PARTNER_TOKEN"
    return _reason or "unknown"


def token():
    """令牌只从环境读取，不随包分发。

    PARTNER_TOKEN     直接给出令牌
    PARTNER_TOKEN_FILE 指向保存令牌的文件路径
    """
    value = (os.environ.get("PARTNER_TOKEN") or "").strip()
    if value:
        return value
    path = (os.environ.get("PARTNER_TOKEN_FILE") or "").strip()
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def get(url, headers, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT):
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port or 443,
        timeout=connect_timeout,
        context=ssl.create_default_context(),
    )
    try:
        conn.connect()
        conn.sock.settimeout(read_timeout)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def call(cmd, params):
    global _fail, _reason
    if not available():
        return None
    tok = token()
    if not tok:
        _reason = "no_token"
        return None
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "", False)})
    url = "{}/run?skill=market-data-hub&cmd={}&{}".format(BASE, cmd, query)
    headers = dict(UA)
    headers["X-Partner-Token"] = tok
    try:
        status, body = get(url, headers)
        if status != 200:
            raise ValueError("http {}".format(status))
        data = json.loads(body.decode("utf-8", errors="replace"))
        if not isinstance(data, dict) or "rows" not in data:
            raise ValueError("bad payload")
        _fail = 0
        return data
    except Exception as exc:
        _fail += 1
        _reason = type(exc).__name__
        return None

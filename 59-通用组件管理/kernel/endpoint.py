#!/usr/bin/env python3
"""云端通道内核：auto / cloud / local 三通道、令牌读取与熔断。

构建期由 tools/sync_kernel.py 注入到组件 `scripts/_kernel/`，组件通过
`from _kernel import endpoint` 使用；源码树不直接 import kernel。

约定:
    GET {base}/run?skill=<skill>&cmd=<命令>&<原参数...>

超时策略:
    连接（含 TLS 握手）与响应分开计时：该站 TLS 握手偶发抖动，
    握手超时不该把慢数据集误判为网关不可用。

熔断:
    同进程连续 break_after 次失败后，本进程不再尝试云端。
"""

import http.client
import json
import os
import ssl
import urllib.parse

DEFAULT_BASE = "https://www.neodrm.com/api/partner/v1"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
BREAK_AFTER = 2


def http_get(url, headers, connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT):
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


class Endpoint:
    """一个组件的云端通道；熔断计数与失败原因由实例持有。"""

    def __init__(
        self,
        skill,
        env_var,
        user_agent,
        base=None,
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        break_after=BREAK_AFTER,
        require_rows=False,
    ):
        self.skill = skill
        self.env_var = env_var
        self.user_agent = user_agent
        self.base = base or os.environ.get(env_var, DEFAULT_BASE)
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.break_after = break_after
        self.require_rows = require_rows
        self._fail = 0
        self._reason = ""

    @staticmethod
    def route(arg):
        value = (arg or "auto").lower()
        if value not in ("auto", "cloud", "local"):
            raise ValueError("endpoint 取值 auto / cloud / local")
        return value

    def available(self):
        return self._fail < self.break_after

    def reason(self):
        return self._reason

    def describe(self):
        if self._reason == "no_token":
            return "未配置订阅令牌 PARTNER_TOKEN"
        return self._reason or "unknown"

    def token(self):
        """令牌只从环境读取，不随包分发。

        PARTNER_TOKEN      直接给出令牌
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

    def call(self, cmd, params):
        if not self.available():
            return None
        tok = self.token()
        if not tok:
            self._reason = "no_token"
            return None
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "", False)}
        )
        url = "{}/run?skill={}&cmd={}&{}".format(self.base, self.skill, cmd, query)
        headers = {"User-Agent": self.user_agent}
        headers["X-Partner-Token"] = tok
        try:
            status, body = http_get(url, headers, self.connect_timeout, self.read_timeout)
            if status != 200:
                raise ValueError("http {}".format(status))
            data = json.loads(body.decode("utf-8", errors="replace"))
            if not isinstance(data, dict):
                raise ValueError("bad payload")
            if self.require_rows and "rows" not in data:
                raise ValueError("bad payload")
            self._fail = 0
            return data
        except Exception as exc:
            self._fail += 1
            self._reason = type(exc).__name__
            return None

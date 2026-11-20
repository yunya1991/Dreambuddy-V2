#!/usr/bin/env python3
"""云端通道（event-context）：配置 _kernel.endpoint 并保持原调用面。

约定:
    GET {BASE}/run?skill=event-context&cmd=<命令>&<原参数...>
    BASE 默认 https://www.neodrm.com/api/partner/v1，可用环境变量 EC_ENDPOINT 覆盖。

共享逻辑在 kernel/endpoint.py，构建期注入为 scripts/_kernel/。
"""

from _kernel import endpoint, headers

SKILL = "event-context"
_ENDPOINT = endpoint.Endpoint(
    skill=SKILL,
    env_var="EC_ENDPOINT",
    user_agent=headers.user_agent(SKILL, "1.0"),
)

BASE = _ENDPOINT.base
UA = {"User-Agent": _ENDPOINT.user_agent}
CONNECT_TIMEOUT = _ENDPOINT.connect_timeout
READ_TIMEOUT = _ENDPOINT.read_timeout
BREAK_AFTER = _ENDPOINT.break_after

route = _ENDPOINT.route
available = _ENDPOINT.available
reason = _ENDPOINT.reason
describe = _ENDPOINT.describe
token = _ENDPOINT.token
get = endpoint.http_get


def call(cmd, params):
    return _ENDPOINT.call(cmd, params)

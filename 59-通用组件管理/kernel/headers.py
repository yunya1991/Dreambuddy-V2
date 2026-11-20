#!/usr/bin/env python3
"""声明式 UA、超时与重试退避。

构建期由 tools/sync_kernel.py 注入到组件 `scripts/_kernel/`。
"""

MAX_RETRIES = 2
BACKOFF = (0.8, 1.6)

TIMEOUT_CONNECT = 5.0
TIMEOUT_READ = 30.0
TIMEOUT_CALL = 60.0


def user_agent(skill, version="1.0"):
    return "{}/{} (research; contact: ops@neodrm.com)".format(skill, version)


def backoff(index):
    """第 index 次重试前的等待秒数；超出表长时沿用末项。"""
    if index < len(BACKOFF):
        return BACKOFF[index]
    return BACKOFF[-1]

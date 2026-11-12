"""tradefin 采集器共用的 HTTP 工具：UA 标识 + 全局限频 + 重试。

SPEC §3.2 合规红线：每个采集器必须有限频与 UA 标识。
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

# 官方源要求的可识别 UA（SEC 明确要求含联系方式）
USER_AGENT = "dreambuddy-research admin@dreambuddy.local"

DEFAULT_INTERVAL = 0.15  # 秒/请求：官方建议 ≥10 req/s 上限的一半
_last_call = 0.0


def _throttle(interval: float) -> None:
    global _last_call
    wait = interval - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def get_text(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 3,
    interval: float = DEFAULT_INTERVAL,
    headers: dict | None = None,
    params: dict | None = None,
) -> str:
    """GET 文本，失败重试；全部失败抛 RuntimeError（调用方 FAIL-OPEN 处理）。"""
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if headers:
        hdrs.update(headers)

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        _throttle(interval)
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # noqa: BLE001 — 网络异常一律重试
            last_err = e
            logger.debug("[tradefin] %s 第 %d 次失败：%s", url, attempt, e)
            time.sleep(min(2**attempt * 0.5, 5))
    raise RuntimeError(f"GET 失败（{retries} 次）：{url} — {last_err}")


def get_json(url: str, **kwargs) -> dict:
    import json

    return json.loads(get_text(url, **kwargs))

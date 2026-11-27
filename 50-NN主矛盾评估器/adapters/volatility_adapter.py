# 50 决策侧波动率取数适配器：OKX 公开 K 线（无凭据）→ ATR%。
#
# 只读公开接口，任何异常/超时一律 fail-open 返回 0.0，
# 由 core.volatility.resolve_sl_tp_pct 退回类别下限，绝不阻塞决策链。
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from core.volatility import ATR_PERIOD, wilder_atr_pct

_DEFAULT_BASE_URL = "https://www.okx.com"
_DEFAULT_BAR = "4H"  # 4H×14 ≈ 2.3 天样本，与「hours」持有周期的间距量级匹配
_DEFAULT_TIMEOUT = 5.0
_DEFAULT_LIMIT = 60


def _base_url() -> str:
    return os.environ.get("50_OKX_BASE_URL") or _DEFAULT_BASE_URL


def fetch_candles(
    inst_id: str,
    bar: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    timeout: float | None = None,
) -> list[dict[str, float]]:
    """拉取 OKX K 线并按时间正序（旧→新）返回 [{h,l,c}]；失败抛异常由调用方兜底。"""
    _bar = bar or os.environ.get("50_LIVE_ATR_BAR") or _DEFAULT_BAR
    _timeout = float(
        timeout
        if timeout is not None
        else os.environ.get("50_LIVE_ATR_TIMEOUT") or _DEFAULT_TIMEOUT
    )
    url = (
        f"{_base_url()}/api/v5/market/candles"
        f"?instId={urllib.parse.quote(str(inst_id))}&bar={_bar}&limit={int(limit)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "dreambuddy-50/1.0"})
    with urllib.request.urlopen(req, timeout=_timeout) as resp:  # noqa: S310 - 固定 https 公开行情
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    if str(data.get("code")) != "0":
        raise RuntimeError(f"okx candles code={data.get('code')} msg={data.get('msg')}")
    rows: list[dict[str, float]] = []
    for d in data.get("data") or []:
        rows.append({"h": float(d[2]), "l": float(d[3]), "c": float(d[4])})
    rows.reverse()  # OKX 倒序（最新在前）→ 旧→新
    return rows


def atr_pct_for(
    inst_id: str,
    bar: str | None = None,
    period: int = ATR_PERIOD,
    timeout: float | None = None,
) -> float:
    """标的 ATR%（百分比）；取数失败返回 0.0（fail-open）。"""
    try:
        return wilder_atr_pct(fetch_candles(inst_id, bar=bar, timeout=timeout), period=period)
    except Exception:  # noqa: BLE001 - 波动率只作间距依据，不得阻断决策
        return 0.0

"""23 动态币池：CoinScanner 扫描 + 已注册标的过滤 + FAIL-OPEN 兜底。

设计口径（2026-11-22）：
- 只允许已注册标的进池：以 22/config/live_symbols.json 为运行时事实源，
  并并入 23 独占的 BTC/ETH/SOL 锚点；未注册新币不进入交易池。
- 扫描只对在册标的拉 K 线（CoinScanner.scan(allow=...)），控制限频与耗时。
- 扫描失败 → 上一轮成功池 → 16 币基线，逐级 FAIL-OPEN。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("entry23.pool")

_REPO = Path(__file__).resolve().parents[3]
_LIVE_SYMBOLS_PATH = _REPO / "22-执行引擎中心" / "config" / "live_symbols.json"

# 与 run_evolution_snapshot.py 的 DEFAULT_SYMBOLS 保持一致（23 可探索基线）。
SNAPSHOT_ANCHORS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "HYPE",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "XAU",
    "XPT",
    "NG",
    "USO",
    "US500",
    "AMD",
    "NVDA",
)

# 23 独占、未登记在 22 live_symbols.json 的锚点。
EXCLUSIVE_ANCHORS: tuple[str, ...] = ("BTC", "ETH", "SOL")

_UNIVERSE_CACHE: dict[str, str] | None = None
_UNIVERSE_MTIME: float = -1.0


def _base_symbol(inst_id: str) -> str:
    return str(inst_id or "").upper().replace("-USDT-SWAP", "").split("-")[0]


def load_universe() -> dict[str, str]:
    """返回 {base_symbol: asset_class}；文件缺失/损坏返回空 dict。"""
    global _UNIVERSE_CACHE, _UNIVERSE_MTIME
    try:
        mtime = _LIVE_SYMBOLS_PATH.stat().st_mtime
    except OSError:
        return {}
    if _UNIVERSE_CACHE is not None and mtime == _UNIVERSE_MTIME:
        return _UNIVERSE_CACHE
    try:
        data = json.loads(_LIVE_SYMBOLS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[pool] 读取 live_symbols.json 失败: %s", exc)
        return {}
    symbols = data.get("symbols") if isinstance(data, dict) else {}
    universe: dict[str, str] = {}
    for _key, cfg in (symbols or {}).items():
        if not isinstance(cfg, dict):
            continue
        _sym = _base_symbol(cfg.get("inst_id") or _key)
        if _sym:
            universe[_sym] = str(cfg.get("asset_class") or "")
    for _sym in EXCLUSIVE_ANCHORS:
        universe.setdefault(_sym, "crypto")
    _UNIVERSE_CACHE = universe
    _UNIVERSE_MTIME = mtime
    return universe


class DynamicSymbolProvider:
    """每轮返回参与 23 开仓巡检的币种列表。"""

    def __init__(
        self,
        scanner: Any,
        scan_top: int = 8,
        max_pool: int = 11,
        universe_fn: Callable[[], dict[str, str]] = load_universe,
    ) -> None:
        self._scanner = scanner
        self._scan_top = max(1, int(scan_top))
        self._max_pool = max(1, int(max_pool))
        self._universe_fn = universe_fn
        self._last_good: list[str] = []
        self.last_source: str = "init"

    def _fallback(self, universe: dict[str, str]) -> list[str]:
        if self._last_good:
            self.last_source = "cache"
            return list(self._last_good)
        self.last_source = "fallback"
        return [s for s in SNAPSHOT_ANCHORS if not universe or s in universe]

    def get(self) -> list[str]:
        _t0 = time.time()
        universe = self._universe_fn() or {}
        if not universe:
            # 注册表不可用时不放开全市场扫描，直接走基线兜底（安全侧）。
            logger.warning("[pool] universe 为空，跳过扫描(FAIL-OPEN)")
            _picked = self._fallback(universe)
            _picked = _picked[: self._max_pool]
            logger.info(
                "[pool] source=%s count=%s elapsed_ms=%.0f symbols=%s",
                self.last_source,
                len(_picked),
                (time.time() - _t0) * 1000,
                ",".join(_picked),
            )
            return _picked
        try:
            rows = self._scanner.scan(
                top_n=self._scan_top,
                force=False,
                allow=set(universe) if universe else None,
            )
        except Exception as exc:  # noqa: BLE001 — 扫描失败不影响巡检
            logger.warning("[pool] 扫描异常(FAIL-OPEN): %s", exc)
            rows = []

        _picked: list[str] = []
        _seen: set[str] = set()
        for row in rows or []:
            _sym = _base_symbol((row or {}).get("symbol") or "")
            if not _sym or _sym in _seen:
                continue
            if universe and _sym not in universe:
                continue
            _seen.add(_sym)
            _picked.append(_sym)

        if not _picked:
            _picked = self._fallback(universe)
        else:
            self.last_source = "scan"
            self._last_good = list(_picked)

        _picked = _picked[: self._max_pool]
        logger.info(
            "[pool] source=%s count=%s elapsed_ms=%.0f symbols=%s",
            self.last_source,
            len(_picked),
            (time.time() - _t0) * 1000,
            ",".join(_picked),
        )
        return _picked

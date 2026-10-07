"""P0 T2: ParamRepository — 参数仓库查询 + 5min TTL 缓存 + FAIL-OPEN

职责：
  1. 包装 sl_tp_config.get_sltp_params() 的只读查询
  2. 5min TTL 本地缓存（避免高频查询参数中心）
  3. FAIL-OPEN：异常时返回 _DEFAULT_PARAMS（SL=4%, TP=12%）

接口契约（SPEC §3.1）：
  get(symbol, regime) -> SLTPParams

注意：
  _underlying_get_sltp_params 是 sl_tp_config.get_sltp_params 的薄包装，
  设计为模块级函数便于测试 patch（不直接 patch 第三方 sl_tp_config）。
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 路径设置：让 repository 能导入 memory_l4.bcrm2.sl_tp_config
# ============================================================================
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent                  # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent          # dreambuddy-v2
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
if str(_YIJING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YIJING_SCRIPTS))

from memory_l4.bcrm2.asset_classifier import classify_asset  # noqa: E402
from memory_l4.bcrm2.sl_tp_config import (  # noqa: E402
    SLTPParams,
    _DEFAULT_PARAMS,
    get_sltp_params as _sl_config_get,
)

# 默认 regime（未知时兜底）
_DEFAULT_REGIME = "chop"

# 默认缓存 TTL（5 分钟）
_DEFAULT_TTL = 300


# ============================================================================
# 模块级底层查询函数（便于测试 patch）
# ============================================================================
def _underlying_get_sltp_params(
    asset_class: str,
    market_cap_tier: str,
    market_regime: str,
) -> SLTPParams:
    """底层参数查询：直接调用 sl_tp_config.get_sltp_params。

    设计为模块级函数（非方法），便于测试时用 patch 监控调用计数。
    """
    return _sl_config_get(asset_class, market_cap_tier, market_regime)


# ============================================================================
# ParamRepository
# ============================================================================
class ParamRepository:
    """参数仓库：5min TTL 缓存 + FAIL-OPEN。

    缓存键：(symbol_upper, regime)，缓存值：(SLTPParams, timestamp)
    线程安全：当前为单线程轮询模型，dict 缓存足够；多线程场景可加 Lock。
    """

    def __init__(self, cache_ttl_seconds: int = _DEFAULT_TTL) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[Tuple[str, str], Tuple[SLTPParams, float]] = {}

    def get(
        self,
        symbol: str,
        market_regime: str = _DEFAULT_REGIME,
        use_cache: bool = True,
    ) -> SLTPParams:
        """查询 SL/TP 参数。

        Args:
            symbol: 交易对（如 "BTC", "PEPE"）
            market_regime: 市场形态（bull/chop/bear），未知按 chop 处理
            use_cache: 是否使用本地缓存（默认 True）

        Returns:
            SLTPParams

        FAIL-OPEN:
            - 未知 regime → 按 chop 处理
            - 底层异常 → 返回 _DEFAULT_PARAMS（SL=4%, TP=12%）
        """
        symbol_up = (symbol or "").upper().strip() or "BTC"
        regime = market_regime or _DEFAULT_REGIME
        cache_key = (symbol_up, regime)

        # 1. 缓存命中
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                params, ts = cached
                if (time.time() - ts) < self._cache_ttl:
                    return cached[0]

        # 2. 查询底层（带 FAIL-OPEN）
        try:
            asset_class, market_cap_tier = classify_asset(symbol_up)
            params = _underlying_get_sltp_params(
                asset_class, market_cap_tier, regime
            )
        except Exception as exc:
            logger.warning(
                "FAIL-OPEN: 参数查询异常 symbol=%s regime=%s err=%s, "
                "返回 _DEFAULT_PARAMS",
                symbol_up, regime, exc,
            )
            params = _DEFAULT_PARAMS

        # 3. 写入缓存
        self._cache[cache_key] = (params, time.time())
        return params

    def invalidate(self, symbol: str = None, regime: str = None) -> None:
        """主动失效缓存。

        Args:
            symbol: 指定币种失效；None 清空全部
            regime: 指定形态失效；None 清空该 symbol 所有形态
        """
        if symbol is None:
            self._cache.clear()
            return
        symbol_up = symbol.upper().strip()
        if regime is None:
            keys_to_remove = [k for k in self._cache if k[0] == symbol_up]
        else:
            keys_to_remove = [(symbol_up, regime)]
        for k in keys_to_remove:
            self._cache.pop(k, None)


# ============================================================================
# 模块级单例（子系统直接 import 使用）
# ============================================================================
_DEFAULT_REPO = ParamRepository(cache_ttl_seconds=_DEFAULT_TTL)


def get_repository() -> ParamRepository:
    """获取默认 ParamRepository 单例。"""
    return _DEFAULT_REPO

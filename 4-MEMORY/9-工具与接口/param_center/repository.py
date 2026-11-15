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
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 路径设置：让 repository 能导入 memory_l4.bcrm2.sl_tp_config
# ============================================================================
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent  # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent  # dreambuddy-v2
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
if str(_YIJING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YIJING_SCRIPTS))

from memory_l4.bcrm2.asset_classifier import classify_asset  # noqa: E402
from memory_l4.bcrm2.sl_tp_config import (  # noqa: E402
    _DEFAULT_PARAMS,
    SLTPParams,
)
from memory_l4.bcrm2.sl_tp_config import (  # noqa: E402
    get_sltp_params as _sl_config_get,
)

# 默认 regime（未知时兜底）
_DEFAULT_REGIME = "chop"

# 默认缓存 TTL（5 分钟）
_DEFAULT_TTL = 300

# 聚合缓存 TTL（2 小时 > scheduler 1 小时间隔，确保聚合参数不会在两次调度间过期）
_AGGREGATED_TTL = 7200

# 聚合缓存持久化文件（跨进程共享：runner 写入 → polling_trader 读取）
_AGGREGATED_CACHE_FILE = _THIS.parent / "data" / "aggregated_params.json"

# L2 审批覆盖文件（中台 /api/admin/system-config/apply 写入，SPEC-7 §6.4/§16-3）
_OVERRIDE_FILE = _PROJECT_ROOT / "16-调控系统" / "config" / "param_center_override.json"

# 硬下限（G3）：任何来源（静态表/聚合缓存/覆盖文件）都不得突破
_FLOOR_SL = 0.04
_FLOOR_TP = 0.12
_FLOOR_RR = 2.0
_FLOOR_ATR_MIN = 2.0
_FLOOR_ATR_MAX = 6.0


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
        # 聚合缓存：runner 写入的动态参数，优先级高于静态表
        # value: (SLTPParams, timestamp, confidence)
        self._aggregated_cache: Dict[Tuple[str, str], Tuple[SLTPParams, float, float]] = {}
        # 磁盘加载频率限制（避免每次 get 都读文件）
        self._last_disk_load: float = 0.0
        self._disk_load_interval: float = 60.0  # 最少 60 秒重新加载一次
        # 从磁盘加载聚合缓存（跨进程共享）
        self._load_aggregated_from_disk()
        # L2 审批覆盖文件（中台写入；无文件/异常时保持 None，不影响既有链路）
        self._override: Optional[Dict[str, object]] = None
        self._override_mtime: float = -1.0
        self._last_override_load: float = 0.0
        self._load_override_from_disk()

    def _load_aggregated_from_disk(self) -> None:
        """从 JSON 文件加载聚合缓存（跨进程共享）。"""
        self._last_disk_load = time.time()
        try:
            if not _AGGREGATED_CACHE_FILE.exists():
                return
            import json

            data = json.loads(_AGGREGATED_CACHE_FILE.read_text(encoding="utf-8"))
            now = time.time()
            loaded = 0
            for key_str, entry in data.items():
                # key_str 格式: "BTC|chop"
                parts = key_str.split("|", 1)
                if len(parts) != 2:
                    continue
                symbol_up, regime = parts[0], parts[1]
                params_dict = entry.get("params", {})
                ts = float(entry.get("ts", 0))
                conf = float(entry.get("conf", 0.0))
                # 跳过过期数据
                if (now - ts) > self._cache_ttl * 6:  # 持久化容忍 6 倍 TTL
                    continue
                params = SLTPParams(
                    sl_floor=float(params_dict.get("sl_floor", 0.04)),
                    tp_floor=float(params_dict.get("tp_floor", 0.12)),
                    rr_ratio_target=float(params_dict.get("rr_ratio_target", 2.4)),
                    atr_mult_range=tuple(params_dict.get("atr_mult_range", (3.5, 5.0))),
                )
                self._aggregated_cache[(symbol_up, regime)] = (params, ts, conf)
                loaded += 1
            if loaded:
                logger.info("ParamRepository: 从磁盘加载聚合缓存 %d 条", loaded)
        except Exception as exc:
            logger.warning("加载聚合缓存失败: %s", exc)

    def _save_aggregated_to_disk(self) -> None:
        """将聚合缓存持久化到 JSON 文件（供 polling_trader 进程读取）。"""
        try:
            import json

            data = {}
            for (symbol_up, regime), (params, ts, conf) in self._aggregated_cache.items():
                data[f"{symbol_up}|{regime}"] = {
                    "params": {
                        "sl_floor": params.sl_floor,
                        "tp_floor": params.tp_floor,
                        "rr_ratio_target": params.rr_ratio_target,
                        "atr_mult_range": list(params.atr_mult_range),
                    },
                    "ts": ts,
                    "conf": conf,
                }
            _AGGREGATED_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _AGGREGATED_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("保存聚合缓存失败: %s", exc)

    def _load_override_from_disk(self) -> None:
        """加载 L2 审批覆盖文件（SPEC-7 §16-3）。

        - 只记录文件里出现的键，未出现的维度沿用原有链路
        - 载入即按硬下限钳制：文件里即使写了更小的值也不会生效
        - FAIL-SAFE：缺失/损坏只忽略覆盖，不影响既有链路
        """
        self._last_override_load = time.time()
        try:
            if not _OVERRIDE_FILE.exists():
                self._override = None
                self._override_mtime = -1.0
                return
            mtime = _OVERRIDE_FILE.stat().st_mtime
            if self._override is not None and abs(mtime - self._override_mtime) < 1e-6:
                return
            import json

            data = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("override 顶层必须是对象")

            override: Dict[str, object] = {}
            if "sl_floor" in data:
                override["sl_floor"] = max(float(data["sl_floor"]), _FLOOR_SL)
            if "tp_floor" in data:
                override["tp_floor"] = max(float(data["tp_floor"]), _FLOOR_TP)
            if "rr_ratio_target" in data:
                override["rr_ratio_target"] = max(float(data["rr_ratio_target"]), _FLOOR_RR)
            atr = data.get("atr_mult_range")
            if isinstance(atr, (list, tuple)) and len(atr) == 2:
                low = min(max(float(atr[0]), _FLOOR_ATR_MIN), _FLOOR_ATR_MAX)
                high = min(max(float(atr[1]), _FLOOR_ATR_MIN), _FLOOR_ATR_MAX)
                if low > high:
                    low, high = high, low
                override["atr_mult_range"] = (low, high)

            self._override = override or None
            self._override_mtime = mtime
            if self._override:
                logger.info("ParamRepository: 已加载 param_center 覆盖 %s", self._override)
        except Exception as exc:
            logger.warning("加载 param_center 覆盖失败（忽略覆盖，保持既有链路）: %s", exc)
            self._override = None

    def _effective(self, params: SLTPParams) -> SLTPParams:
        """应用 L2 覆盖；无覆盖时原样返回，保持既有 FAIL-OPEN 语义。

        有覆盖时：各维度 max(基础值, 覆盖值, 硬下限)，ATR 取覆盖区间并钳制到 [2,6]，
        保证 SL≥4% / TP≥12% / RR≥2 / ATR∈[2,6]（G3）。
        """
        if (time.time() - self._last_override_load) > self._disk_load_interval:
            self._load_override_from_disk()
        override = self._override
        if not override:
            return params
        sl = max(params.sl_floor, float(override.get("sl_floor", 0.0)), _FLOOR_SL)
        tp = max(params.tp_floor, float(override.get("tp_floor", 0.0)), _FLOOR_TP)
        rr = max(
            params.rr_ratio_target,
            float(override.get("rr_ratio_target", 0.0)),
            _FLOOR_RR,
        )
        atr = override.get("atr_mult_range") or params.atr_mult_range
        low = min(max(float(atr[0]), _FLOOR_ATR_MIN), _FLOOR_ATR_MAX)
        high = min(max(float(atr[1]), _FLOOR_ATR_MIN), _FLOOR_ATR_MAX)
        if low > high:
            low, high = high, low
        return SLTPParams(
            sl_floor=sl,
            tp_floor=tp,
            rr_ratio_target=rr,
            atr_mult_range=(low, high),
        )

    def get(
        self,
        symbol: str,
        market_regime: str = _DEFAULT_REGIME,
        use_cache: bool = True,
    ) -> SLTPParams:
        """查询 SL/TP 参数（对外接口）：结果统一应用 L2 覆盖与硬下限。"""
        return self._effective(self._get_raw(symbol, market_regime, use_cache))

    def _get_raw(
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

        # 0. 聚合缓存优先（runner 写入的动态参数）
        # 聚合缓存 TTL 比静态缓存长（2 小时 > scheduler 1 小时间隔）
        if use_cache:
            agg = self._aggregated_cache.get(cache_key)
            if agg is not None:
                params, ts, _conf = agg
                if (time.time() - ts) < _AGGREGATED_TTL:
                    return params
            # 聚合缓存未命中或过期 → 从磁盘重新加载（scheduler 可能更新了）
            if (time.time() - self._last_disk_load) > self._disk_load_interval:
                self._load_aggregated_from_disk()
                agg = self._aggregated_cache.get(cache_key)
                if agg is not None:
                    params, ts, _conf = agg
                    if (time.time() - ts) < _AGGREGATED_TTL:
                        return params

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
            params = _underlying_get_sltp_params(asset_class, market_cap_tier, regime)
        except Exception as exc:
            logger.warning(
                "FAIL-OPEN: 参数查询异常 symbol=%s regime=%s err=%s, " "返回 _DEFAULT_PARAMS",
                symbol_up,
                regime,
                exc,
            )
            params = _DEFAULT_PARAMS

        # 3. 写入缓存
        self._cache[cache_key] = (params, time.time())
        return params

    def set_aggregated(
        self,
        symbol: str,
        regime: str,
        params: SLTPParams,
        confidence: float = 0.0,
    ) -> None:
        """写入聚合缓存（由 runner 调用）。

        聚合缓存优先级高于静态表缓存，TTL 相同。
        """
        symbol_up = (symbol or "").upper().strip() or "BTC"
        regime = regime or _DEFAULT_REGIME
        self._aggregated_cache[(symbol_up, regime)] = (params, time.time(), confidence)
        # 持久化到磁盘（供 polling_trader 进程读取）
        self._save_aggregated_to_disk()

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

"""
TrailingStopComponent 主组件
=============================

对外暴露的唯一入口：
- evaluate(systems=None) -> TrailingSnapshot
- get_snapshot() -> Optional[TrailingSnapshot]
- health_check() -> Dict

使用方式::

    from trailing_stop import TrailingStopComponent

    component = TrailingStopComponent()
    snapshot = component.evaluate()
    # snapshot.stats.armed_count / snapshot.by_state 查看详情
    for sk, r in snapshot.by_state.items():
        if r.action == TrailingAction.TRIGGER_CLOSE:
            # 执行平仓：r.system / r.coin / r.side

设计约束：
  * 数据输入：仅通过 unified_position_query.fetch_all_positions() 获取持仓
  * 算法：ATR 波动率自适应法（types.calc_atr_trailing_price）
      - 激活阈值：arm_threshold_pct 默认 0.20（含杠杆有效盈利 ≥ 20%）
      - 追踪距离：max(ATR(14) × 2.5, peak_price × 3%)
  * 持久化：artifacts/trailing-stop/state.json，启动时自动恢复
  * 5 分钟轮询：由 auto_exit_system.py 负责调用间隔，组件自身无定时器
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_TRAIL_DIR = Path(__file__).resolve().parent          # trailing_stop
_16_CORE_DIR = _TRAIL_DIR.parent                      # 16-调控系统/core
_PROJECT_DIR = _16_CORE_DIR.parents[1]                # dreambuddy-v2
_ARTIFACTS_DIR = _16_CORE_DIR.parent / "artifacts" / "trailing-stop"
_STATE_FILE = _ARTIFACTS_DIR / "state.json"

for _p in (_16_CORE_DIR,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from .types import (  # noqa: E402
    TrailingAction,
    TrailingResult,
    TrailingSnapshot,
    TrailingState,
    TrailingStats,
    TrailingStatus,
    calc_atr_trailing_price,
    calc_pnl_eff_pct,
    now_iso,
)

_DEFAULT_SYSTEMS: List[str] = [
    "v15_martin",
    "yijing_bcrm",
    "agent_a",
    "agent_b",
    "agent_c_memory",
    "three_screen",
]

_DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "enabled_systems": list(_DEFAULT_SYSTEMS),
    "cache_ttl_sec": 60,
    "persist_enabled": True,
    "persist_file": "artifacts/trailing-stop/state.json",
    # 算法参数
    "algorithm": {
        "arm_threshold_pct": 0.20,        # 激活阈值：有效盈利≥20%（含杠杆）
        "atr_period": 14,                 # ATR 周期
        "atr_multiplier": 2.5,            # ATR 倍数
        "min_trail_pct": 0.03,            # 最小追踪距离百分比 3%
        "atr_fallback_pct": 0.02,         # ATR 缺失时的回退波动率（2%）
    },
    # 触发保护：避免同一仓位在 N 秒内重复触发
    "trigger_cooldown_sec": 300,
    # 已触发后多少秒标记为 CLOSED（避免在状态文件里永远 TRIGGERED）
    "auto_close_after_sec": 1800,
}


class TrailingStopComponent:
    """ATR 波动率自适应移动止盈通用组件。"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        cache_ttl: Optional[int] = None,
    ):
        # 1) 配置路径
        if config_path is None:
            config_path = _16_CORE_DIR.parent / "config" / "trailing_stop.json"
        self._config_path: Path = Path(config_path)

        # 2) 加载配置
        self._config: Dict[str, Any] = self._load_config(self._config_path)

        # 3) 缓存 TTL
        if cache_ttl is not None:
            self._cache_ttl = int(cache_ttl)
        else:
            self._cache_ttl = int(self._config.get("cache_ttl_sec", 60))

        # 4) 持久化目录 & 文件
        self._persist_enabled = bool(self._config.get("persist_enabled", True))
        self._state_file: Path = self._resolve_state_file()
        _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

        # 5) 加载历史状态
        self._lock = threading.RLock()
        self._states: Dict[str, TrailingState] = self._load_states()

        # 6) 缓存
        self._last_snapshot: Optional[TrailingSnapshot] = None
        self._last_eval_ts: float = 0.0

    # ------------------------------------------------------------------
    # 初始化辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        cfg: Dict[str, Any] = json.loads(json.dumps(_DEFAULT_CONFIG))  # deep copy
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    for k, v in file_cfg.items():
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            new_dict = dict(cfg[k])
                            new_dict.update(v)
                            cfg[k] = new_dict
                        else:
                            cfg[k] = v
        except (OSError, json.JSONDecodeError):
            pass
        enabled_systems = cfg.get("enabled_systems") or []
        cfg["enabled_systems"] = [s for s in enabled_systems if s in _DEFAULT_SYSTEMS] or list(_DEFAULT_SYSTEMS)
        # algorithm 段合并兜底
        if "algorithm" not in cfg or not isinstance(cfg["algorithm"], dict):
            cfg["algorithm"] = dict(_DEFAULT_CONFIG["algorithm"])
        else:
            for ak, av in _DEFAULT_CONFIG["algorithm"].items():
                cfg["algorithm"].setdefault(ak, av)
        return cfg

    def _resolve_state_file(self) -> Path:
        pf = self._config.get("persist_file")
        if not pf:
            return _STATE_FILE
        p = Path(pf)
        if not p.is_absolute():
            p = _PROJECT_DIR / "16-调控系统" / p
        return p

    def _load_states(self) -> Dict[str, TrailingState]:
        if not self._persist_enabled:
            return {}
        try:
            if not self._state_file.exists():
                return {}
            with open(self._state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
            states: Dict[str, TrailingState] = {}
            for sk, d in raw.items():
                if not isinstance(d, dict):
                    continue
                try:
                    states[sk] = TrailingState.from_dict(d)
                except Exception:
                    continue
            return states
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_states(self) -> None:
        if not self._persist_enabled:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {sk: st.to_dict() for sk, st in self._states.items()}
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def evaluate(self, systems: Optional[List[str]] = None) -> TrailingSnapshot:
        """执行移动止盈评估。

        流程：
          1. 距离上次 evaluate < cache_ttl 秒，且 systems=None → 返回缓存。
          2. 调用 fetch_all_positions() 拉取全部持仓。
          3. 对每个持仓：
             - 计算当前价 & 有效收益率（含杠杆）
             - 若未激活且 ≥ arm_threshold → ARM 激活
             - 若已激活 → 更新 peak_price、计算 trailing_stop_price、检查触发
          4. 持久化状态到 state.json
          5. 聚合输出 TrailingSnapshot
        """
        with self._lock:
            now_ts = time.time()
            if (
                self._last_snapshot is not None
                and (now_ts - self._last_eval_ts) < self._cache_ttl
                and systems is None
            ):
                return self._last_snapshot

            snapshot = self._do_evaluate(systems=systems)
            self._last_snapshot = snapshot
            self._last_eval_ts = time.time()
            return snapshot

    def get_snapshot(self) -> Optional[TrailingSnapshot]:
        return self._last_snapshot

    def get_state(self, system: str, coin: str, side: str) -> Optional[TrailingState]:
        """查询某一持仓的追踪状态（持久化版）。"""
        sk = f"{system}:{coin}:{side.lower()}"
        with self._lock:
            return self._states.get(sk)

    def health_check(self) -> Dict[str, Any]:
        snap = self._last_snapshot
        evaluated = False
        if snap is None:
            try:
                snap = self.evaluate()
                evaluated = True
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"evaluate_failed: {exc}",
                    "config_path": str(self._config_path),
                    "state_file": str(self._state_file),
                }
        return {
            "ok": True,
            "evaluated": evaluated,
            "total_positions": snap.stats.total_positions,
            "armed_count": snap.stats.armed_count,
            "triggered_count": snap.stats.triggered_count,
            "triggered_total": snap.stats.triggered_total,
            "persist_enabled": self._persist_enabled,
            "state_file": str(self._state_file),
            "config_path": str(self._config_path),
            "cache_ttl_sec": self._cache_ttl,
        }

    # ------------------------------------------------------------------
    # 内部：evaluate 主逻辑
    # ------------------------------------------------------------------

    def _enabled_systems(self, override: Optional[Iterable[str]] = None) -> List[str]:
        if override is not None:
            return [s for s in override if s in _DEFAULT_SYSTEMS]
        return list(self._config.get("enabled_systems") or _DEFAULT_SYSTEMS)

    def _lazy_fetch_positions(self) -> Dict[str, Any]:
        try:
            from unified_position_query import fetch_all_positions
            result = fetch_all_positions()
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            return {"_fetch_error": str(exc)}

    @staticmethod
    def _direction_to_side(direction: Optional[str]) -> str:
        d = (direction or "").upper()
        if d in ("LONG", "BUY"):
            return "long"
        if d in ("SHORT", "SELL"):
            return "short"
        return "long"  # 兜底当做多

    @staticmethod
    def _estimate_current_price(
        entry_price: float,
        upl_ratio: float,
        leverage: float,
        side: str,
    ) -> float:
        """在缺少 current_price 时，通过 upl_ratio（无杠杆名义收益率估算）推导。"""
        if entry_price <= 0:
            return 0.0
        lev = leverage if leverage > 0 else 1.0
        # upl_ratio 通常 = unrealized_pnl / (entry_price * size) 即名义收益率
        # 为兼容含杠杆/无杠杆，直接用 upl_ratio 作为 raw pct
        raw_pct = upl_ratio
        if side == "long":
            return entry_price * (1.0 + raw_pct)
        return entry_price * (1.0 - raw_pct)

    @staticmethod
    def _extract_atr_pct(position: Dict[str, Any], fallback_pct: float) -> float:
        """从 position.meta 或 position 里提取 atr_pct，否则返回 fallback。"""
        try:
            meta = position.get("meta") or {}
            if isinstance(meta, dict):
                for k in ("atr_pct", "atrPercent", "atr_ratio"):
                    v = meta.get(k)
                    if isinstance(v, (int, float)) and v > 0:
                        return float(v)
            for k in ("atr_pct", "atr_ratio"):
                v = position.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v)
        except Exception:
            pass
        return fallback_pct

    def _do_evaluate(self, systems: Optional[List[str]] = None) -> TrailingSnapshot:
        target_systems = set(self._enabled_systems(systems))
        positions_result = self._lazy_fetch_positions()

        algo_cfg: Dict[str, Any] = self._config.get("algorithm", {})
        arm_threshold_pct = float(algo_cfg.get("arm_threshold_pct", 0.20))
        atr_period = int(algo_cfg.get("atr_period", 14))
        atr_multiplier = float(algo_cfg.get("atr_multiplier", 2.5))
        min_trail_pct = float(algo_cfg.get("min_trail_pct", 0.03))
        atr_fallback_pct = float(algo_cfg.get("atr_fallback_pct", 0.02))
        trigger_cooldown_sec = int(self._config.get("trigger_cooldown_sec", 300))
        auto_close_after_sec = int(self._config.get("auto_close_after_sec", 1800))

        results: Dict[str, TrailingResult] = {}
        seen_keys: set = set()

        # 遍历所有系统的 positions
        by_sys_raw: Dict[str, Any] = positions_result.get("by_system") or {}
        for system_name, sys_data in by_sys_raw.items():
            if system_name not in target_systems:
                continue
            positions = (sys_data.get("positions") if isinstance(sys_data, dict) else None) or []
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                coin = str(pos.get("symbol") or pos.get("coin") or "")
                if not coin:
                    continue
                side = self._direction_to_side(pos.get("direction"))
                sk = f"{system_name}:{coin}:{side}"
                seen_keys.add(sk)

                entry_price = float(pos.get("entry_price") or 0.0)
                size = float(pos.get("size") or 0.0)
                leverage = float(pos.get("leverage") or 1.0) or 1.0
                if entry_price <= 0 or size <= 0:
                    # 无有效持仓，跳过
                    continue

                upl_ratio = float(pos.get("upl_ratio") or 0.0)
                unrealized_pnl = float(pos.get("unrealized_pnl") or 0.0)

                # 当前价估算：优先用 position.meta.last_price / current_price
                meta = pos.get("meta") or {}
                current_price = 0.0
                for k in ("current_price", "last_price", "mark_price", "lastPx", "last"):
                    v = (meta if isinstance(meta, dict) else {}).get(k)
                    if isinstance(v, (int, float)) and v > 0:
                        current_price = float(v)
                        break
                if current_price <= 0:
                    v = pos.get("current_price")
                    if isinstance(v, (int, float)) and v > 0:
                        current_price = float(v)
                if current_price <= 0:
                    current_price = self._estimate_current_price(
                        entry_price, upl_ratio, leverage, side,
                    )
                if current_price <= 0:
                    continue

                is_long = side == "long"
                pnl_eff = calc_pnl_eff_pct(is_long, entry_price, current_price, leverage)

                # ATR 估值
                atr_pct = self._extract_atr_pct(pos, atr_fallback_pct)
                atr_value = entry_price * atr_pct
                # 对 ATR 进行动态修正（如果 current_price ≠ entry_price，则用 current_price 更合理）
                if current_price > 0:
                    atr_value = current_price * atr_pct

                # 取/建状态
                state = self._states.get(sk)
                just_armed = False
                if state is None or state.status == TrailingStatus.CLOSED:
                    state = TrailingState(
                        system=system_name,
                        coin=coin,
                        side=side,
                        status=TrailingStatus.IDLE,
                        entry_price=entry_price,
                        leverage=leverage,
                        position_size=size,
                        peak_price=current_price if is_long else current_price,
                        peak_ts=now_iso(),
                        atr_period=atr_period,
                        atr_multiplier=atr_multiplier,
                        min_trail_pct=min_trail_pct,
                        arm_threshold_pct=arm_threshold_pct,
                        current_atr=atr_value,
                        current_price=current_price,
                        created_ts=now_iso(),
                        updated_ts=now_iso(),
                    )
                    self._states[sk] = state

                # 同步基本属性（开仓价/杠杆/数量可能发生变化）
                state.entry_price = entry_price
                state.leverage = leverage
                state.position_size = size
                state.current_price = current_price
                state.current_atr = atr_value
                state.updated_ts = now_iso()

                # 处理已触发后冷却 / 自动关闭
                if state.status == TrailingStatus.TRIGGERED:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        trig_ts_iso = state.triggered_ts or ""
                        trig_dt = _dt.fromisoformat(trig_ts_iso.replace("Z", "+00:00")) if trig_ts_iso else None
                        now_dt = _dt.now(_tz.utc)
                        if trig_dt:
                            elapsed = (now_dt - trig_dt).total_seconds()
                            if elapsed >= auto_close_after_sec:
                                state.status = TrailingStatus.CLOSED
                    except Exception:
                        pass

                # 更新峰值价格（单边更新）
                if is_long:
                    if current_price > state.peak_price or state.peak_price <= 0:
                        state.peak_price = current_price
                        state.peak_ts = now_iso()
                else:
                    if (current_price < state.peak_price) or state.peak_price <= 0:
                        state.peak_price = current_price
                        state.peak_ts = now_iso()

                # 状态机：IDLE → 检查是否 ARMED
                action = TrailingAction.HOLD
                reason = ""
                trail_price = 0.0
                locked_profit_pct = 0.0

                if state.status == TrailingStatus.IDLE:
                    if pnl_eff >= arm_threshold_pct:
                        # 激活追踪
                        state.status = TrailingStatus.ARMED
                        state.armed_ts = now_iso()
                        state.arm_pnl_eff_pct = pnl_eff
                        trail_price = calc_atr_trailing_price(
                            is_long, state.peak_price, atr_value, atr_multiplier, min_trail_pct,
                        )
                        state.trailing_stop_price = trail_price
                        action = TrailingAction.ARM
                        reason = (
                            f"[ARM] 有效盈利 {pnl_eff:.2%} ≥ 激活阈值 {arm_threshold_pct:.2%}，"
                            f"追踪止损价={trail_price:.4f}"
                        )
                        just_armed = True
                    else:
                        reason = (
                            f"[IDLE] 有效盈利 {pnl_eff:.2%} < 激活阈值 {arm_threshold_pct:.2%}"
                        )

                # 状态机：ARMED → 更新追踪价 & 检查触发
                if state.status == TrailingStatus.ARMED and not just_armed:
                    trail_price = calc_atr_trailing_price(
                        is_long, state.peak_price, atr_value, atr_multiplier, min_trail_pct,
                    )
                    # 追踪止损价只向有利方向调整（做多时只上移，不下降）
                    if is_long:
                        if trail_price > state.trailing_stop_price or state.trailing_stop_price <= 0:
                            state.trailing_stop_price = trail_price
                    else:
                        if (trail_price < state.trailing_stop_price or state.trailing_stop_price <= 0) and trail_price > 0:
                            state.trailing_stop_price = trail_price
                    trail_price = state.trailing_stop_price

                    # 触发判断
                    triggered = False
                    trigger_reason = ""
                    if is_long:
                        if trail_price > 0 and current_price <= trail_price:
                            triggered = True
                            trigger_reason = "price_below_trail"
                    else:
                        if trail_price > 0 and current_price >= trail_price:
                            triggered = True
                            trigger_reason = "price_above_trail"

                    if triggered:
                        # 冷却保护（防止短时间重复触发，通常一次就够）
                        cooldown_ok = True
                        try:
                            from datetime import datetime as _dt, timezone as _tz
                            trig_ts_iso = state.triggered_ts or ""
                            if trig_ts_iso:
                                trig_dt = _dt.fromisoformat(trig_ts_iso.replace("Z", "+00:00"))
                                now_dt = _dt.now(_tz.utc)
                                if (now_dt - trig_dt).total_seconds() < trigger_cooldown_sec:
                                    cooldown_ok = False
                        except Exception:
                            pass

                        if cooldown_ok:
                            state.status = TrailingStatus.TRIGGERED
                            state.triggered_ts = now_iso()
                            state.triggered_price = current_price
                            state.trigger_reason = trigger_reason
                            # 相对开仓的有效盈利
                            locked_profit_pct = calc_pnl_eff_pct(
                                is_long, entry_price, current_price, leverage,
                            )
                            state.locked_profit_pct = locked_profit_pct
                            action = TrailingAction.TRIGGER_CLOSE
                            reason = (
                                f"[TRIGGER] {trigger_reason}：当前价 {current_price:.4f} "
                                f"({'<=' if is_long else '>='}) 追踪止损价 {trail_price:.4f}，"
                                f"锁定有效盈利 {locked_profit_pct:.2%}"
                            )
                        else:
                            action = TrailingAction.HOLD
                            reason = (
                                f"[COOLDOWN] 已触发保护期内（≤{trigger_cooldown_sec}s），暂不重复触发"
                            )
                    else:
                        # 距离触发还剩多少
                        if trail_price > 0 and state.peak_price > 0:
                            distance_pct = abs(current_price - trail_price) / state.peak_price
                        else:
                            distance_pct = 0.0
                        reason = (
                            f"[ARMED] 追踪价 {trail_price:.4f}，距触发 {distance_pct:.2%}，"
                            f"峰值 {state.peak_price:.4f}"
                        )

                # TRIGGERED/CLOSED 的结果信息
                if state.status == TrailingStatus.TRIGGERED and action == TrailingAction.HOLD:
                    locked_profit_pct = state.locked_profit_pct
                    trail_price = state.trailing_stop_price
                    reason = (
                        f"[TRIGGERED] 已于 {state.triggered_ts} 触发，"
                        f"触发价 {state.triggered_price:.4f}，锁定盈利 {state.locked_profit_pct:.2%}"
                    )
                if state.status == TrailingStatus.CLOSED:
                    locked_profit_pct = state.locked_profit_pct
                    trail_price = state.trailing_stop_price
                    reason = f"[CLOSED] 追踪已结束"

                # 距离（peak → trail 百分比）
                if state.peak_price > 0 and trail_price > 0:
                    trail_distance_pct = abs(state.peak_price - trail_price) / state.peak_price
                else:
                    trail_distance_pct = 0.0

                results[sk] = TrailingResult(
                    state_key=sk,
                    system=system_name,
                    coin=coin,
                    side=side,
                    action=action,
                    status=state.status,
                    current_pnl_eff_pct=pnl_eff,
                    peak_price=state.peak_price,
                    trailing_stop_price=trail_price,
                    current_atr=atr_value,
                    trail_distance_pct=trail_distance_pct,
                    locked_profit_pct=locked_profit_pct,
                    reason=reason,
                    details={
                        "arm_threshold_pct": arm_threshold_pct,
                        "atr_multiplier": atr_multiplier,
                        "min_trail_pct": min_trail_pct,
                        "is_long": is_long,
                        "size": size,
                    },
                )

        # 清理：state 中但本次不在 seen_keys 里的，如果是 IDLE 则可保留（防止重启丢失），
        # 如果是 ARMED/TRIGGERED 但当前已无该持仓 → 过 auto_close_after_sec 后标记 CLOSED
        for sk, state in list(self._states.items()):
            if sk in seen_keys:
                continue
            try:
                from datetime import datetime as _dt, timezone as _tz
                updated_iso = state.updated_ts or state.created_ts or ""
                if not updated_iso:
                    continue
                up_dt = _dt.fromisoformat(updated_iso.replace("Z", "+00:00"))
                now_dt = _dt.now(_tz.utc)
                elapsed = (now_dt - up_dt).total_seconds()
                if elapsed >= auto_close_after_sec:
                    state.status = TrailingStatus.CLOSED
                    state.updated_ts = now_iso()
            except Exception:
                continue

        # 写入状态文件
        self._save_states()

        # 统计
        stats = self._aggregate_stats(results)

        # 建议
        recs: Dict[str, str] = {}
        for sk, r in results.items():
            if r.action == TrailingAction.TRIGGER_CLOSE:
                recs[sk] = f"CLOSE:{r.coin}_{r.side} locked_profit={r.locked_profit_pct:.2%}"
            elif r.action == TrailingAction.ARM:
                recs[sk] = f"ARM:{r.coin}_{r.side} trail_stop={r.trailing_stop_price:.4f}"

        return TrailingSnapshot(
            timestamp=now_iso(),
            by_state=results,
            stats=stats,
            recommendations=recs,
            extra={
                "fetch_error": positions_result.get("_fetch_error", ""),
                "algorithm": "atr_adaptive",
                "algorithm_params": dict(algo_cfg),
            },
        )

    def _aggregate_stats(self, results: Dict[str, TrailingResult]) -> TrailingStats:
        total = len(results)
        idle = armed = triggered = closed = 0
        armed_pnl_list: List[float] = []
        locked_list: List[float] = []
        triggered_total = 0

        # 从持久化历史里统计 triggered_total
        for st in self._states.values():
            if st.status == TrailingStatus.TRIGGERED and st.triggered_ts:
                triggered_total += 1
            if st.status == TrailingStatus.CLOSED and st.triggered_ts:
                triggered_total += 1

        for r in results.values():
            s = r.status
            if s == TrailingStatus.IDLE:
                idle += 1
            elif s == TrailingStatus.ARMED:
                armed += 1
                armed_pnl_list.append(r.current_pnl_eff_pct)
            elif s == TrailingStatus.TRIGGERED:
                triggered += 1
                locked_list.append(r.locked_profit_pct)
            elif s == TrailingStatus.CLOSED:
                closed += 1

        avg_armed = sum(armed_pnl_list) / len(armed_pnl_list) if armed_pnl_list else 0.0
        avg_locked = sum(locked_list) / len(locked_list) if locked_list else 0.0

        # 把 states 中未出现在本次结果里的 ARMED 也计入 armed_total？保持统计保守，只看当前结果
        return TrailingStats(
            total_positions=total,
            idle_count=idle,
            armed_count=armed,
            triggered_count=triggered,
            closed_count=closed,
            triggered_total=triggered_total,
            avg_armed_pnl_pct=avg_armed,
            avg_locked_profit_pct=avg_locked,
        )


__all__ = ["TrailingStopComponent"]

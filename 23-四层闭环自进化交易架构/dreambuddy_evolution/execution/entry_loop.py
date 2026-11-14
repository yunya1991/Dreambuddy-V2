"""23 域开仓循环（M1-e：entry loop 下沉）。

职责边界：
- 23 负责：闸门编排（执行权/黑名单/耦合/熔断/去重/冷静期/方向状态/子池/集中度/
  probe 上限/禁空）、定容（base × FTC 轨道 × u_open × 分层倍数 × cap）、
  probe 交易所最小量地板、SL/TP 定价、产出 FinalDecisionSignal 并提交 22 网关；
- 11 负责：提供闸门判定/持仓快照/权益/轨道乘数/宏观约束/已用名义/交易所最小量
  等 callable（构造注入），以及成交后的持仓落账与影子审计回调；
- 本模块不 import 任何 11 模块，也不直接持有交易所客户端。

所有闸门 FAIL-OPEN：单闸异常只跳过该闸并按放行处理；顶层异常返回 failed。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

from .decision_signal import (
    EvolutionSignalDispatcher,
    build_entry_decision,
    compute_sl_tp_pct,
)

_DEFAULT_CONFIG: dict[str, Any] = {
    "budget_per_coin": 2000.0,
    "min_notional": 250.0,
    "min_notional_probe": 100.0,
    "max_notional": 2000.0,
    "leverage": 5,
    "subpool_max": 5,
    "probe_max": 2,
    "max_direction_ratio": 0.70,
    "direction_ratio_min_positions": 3,
    "probe_min_sz_buffer": 1.2,
    "sl_floor_pct": 0.04,
    "tp_floor_pct": 0.12,
}

_LONG_ALIASES = {"long", "buy", "up", "open_long"}
_SHORT_ONLY = "SHORT_ONLY"
_LONG_ONLY = "LONG_ONLY"
_FREEZE = "FREEZE"


def _env_on(name: str, default: str = "on") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "on", "yes")


class EvolutionEntryLoop:
    """23 域开仓闸门 + 定容 + 22 下单编排器。

    用法::

        loop = EvolutionEntryLoop(gateway=gateway, blacklist_fn=fn, ...)
        report = loop.run("BTC", "long", u_open=0.8, confidence=0.62, tier="standard")

    run 返回 dict：
      status: opened / blocked / failed
      gate:   被拦截的闸门名（blocked 时）
      reason: 归因说明
      notional_usdt: 最终名义仓位（通过定容后）
      result: 22 网关回执
    """

    def __init__(
        self,
        gateway: Any = None,
        dispatcher: Any = None,
        runtime_dir: str | Path | None = None,
        log_fn: Optional[Callable[[str, str], None]] = None,
        config: dict[str, Any] | None = None,
        # ── 闸门（构造注入，23 不 import 11） ──
        authority_fn: Optional[Callable[[str], bool]] = None,
        blacklist_fn: Optional[Callable[[str], Any]] = None,
        fuse_fn: Optional[Callable[[], Any]] = None,
        has_position_fn: Optional[Callable[[str], bool]] = None,
        cooldown_fn: Optional[Callable[[str, str], Any]] = None,
        direction_state_fn: Optional[Callable[[str, str], Any]] = None,
        subpool_fn: Optional[Callable[[], dict[str, Any]]] = None,
        short_ban_fn: Optional[Callable[[str, str], dict[str, Any]]] = None,
        # ── 定容输入 ──
        equity_fn: Optional[Callable[[], float]] = None,
        track_mult_fn: Optional[Callable[[dict[str, Any] | None], float]] = None,
        asset_class_fn: Optional[Callable[[str], str]] = None,
        macro_constraint_fn: Optional[Callable[[str], dict[str, Any]]] = None,
        used_notional_fn: Optional[Callable[[], dict[str, float]]] = None,
        min_sz_fn: Optional[Callable[[str], float]] = None,
        price_fn: Optional[Callable[[str], float]] = None,
        sltp_fn: Optional[Callable[..., Any]] = None,
        # ── 回调 ──
        on_shadow: Optional[Callable[[dict[str, Any]], None]] = None,
        on_opened: Optional[Callable[[dict[str, Any], dict[str, Any]], None]] = None,
        on_blocked: Optional[Callable[[dict[str, Any], str, str], None]] = None,
    ) -> None:
        self._gateway = gateway
        self._log_fn = log_fn or (lambda msg, level="INFO": None)

        self._dispatcher = dispatcher
        if self._dispatcher is None and gateway is not None:
            from .outbox import default_outbox

            self._dispatcher = EvolutionSignalDispatcher(
                gateway=gateway, runtime_dir=runtime_dir, outbox=default_outbox()
            )

        self._cfg = dict(_DEFAULT_CONFIG)
        if config:
            self._cfg.update(config)

        self.authority_fn = authority_fn
        self.blacklist_fn = blacklist_fn
        self.fuse_fn = fuse_fn
        self.has_position_fn = has_position_fn
        self.cooldown_fn = cooldown_fn
        self.direction_state_fn = direction_state_fn
        self.subpool_fn = subpool_fn
        self.short_ban_fn = short_ban_fn

        self.equity_fn = equity_fn
        self.track_mult_fn = track_mult_fn
        self.asset_class_fn = asset_class_fn
        self.macro_constraint_fn = macro_constraint_fn
        self.used_notional_fn = used_notional_fn
        self.min_sz_fn = min_sz_fn
        self.price_fn = price_fn
        self.sltp_fn = sltp_fn

        self.on_shadow = on_shadow
        self.on_opened = on_opened
        self.on_blocked = on_blocked

    # ── 基础设施 ──────────────────────────────────────────────────
    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            self._log_fn(msg, level)
        except Exception:  # noqa: BLE001
            pass

    def _call(self, fn, default, label: str, args: tuple = ()) -> Any:
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 — 单闸 FAIL-OPEN
            self._log(f"[P2-S4b] {label} 异常(FAIL-OPEN放行): {type(e).__name__}: {e}", "WARN")
            return default

    @staticmethod
    def _inst_id(symbol: str) -> str:
        _s = str(symbol or "").upper()
        return _s if _s.endswith("-USDT-SWAP") else f"{_s}-USDT-SWAP"

    @staticmethod
    def _coin(symbol: str) -> str:
        return str(symbol or "").upper().replace("-USDT-SWAP", "")

    @staticmethod
    def _direction(action: str) -> str:
        return "long" if str(action or "").strip().lower() in _LONG_ALIASES else "short"

    @staticmethod
    def _kline_last_price(kline: dict[str, Any] | None) -> float:
        """kline 可能是标量或 11 的收盘价列表，取最新一根。"""
        if not kline:
            return 0.0
        _close = kline.get("close")
        if isinstance(_close, (list, tuple)):
            _close = _close[-1] if _close else 0.0
        try:
            return float(_close or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _blocked(
        self, ctx: dict[str, Any], gate: str, reason: str, level: str = "WARN"
    ) -> dict[str, Any]:
        self._log(f"[P2-S4b] {ctx['symbol']} 开仓拦截 gate={gate} | {reason}", level)
        if self.on_blocked is not None:
            try:
                self.on_blocked(ctx, gate, reason)
            except Exception:  # noqa: BLE001
                pass
        return {
            "status": "blocked",
            "gate": gate,
            "reason": reason,
            "symbol": ctx["symbol"],
            "direction": ctx["direction"],
            "tier": ctx["tier"],
            "notional_usdt": 0.0,
        }

    # ── 主入口 ────────────────────────────────────────────────────
    def run(
        self,
        symbol: str,
        action: str,
        u_open: float = 1.0,
        d_star: str = "",
        confidence: float = 0.5,
        tier: str = "standard",
        source_tag: str | None = None,
        cbr_sim: float = 0.5,
        signal: dict[str, Any] | None = None,
        kline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "symbol": self._coin(symbol),
            "inst_id": self._inst_id(symbol),
            "direction": self._direction(action),
            "u_open": float(u_open or 0.0),
            "d_star": d_star,
            "confidence": float(confidence or 0.0),
            "tier": str(tier or "standard").lower(),
            "source_tag": str(source_tag or "evolution").strip().lower(),
            "cbr_sim": float(cbr_sim if cbr_sim is not None else 0.5),
            "signal": signal or {},
            "kline": kline or {},
        }
        _check = self._check_gates(ctx)
        if _check is not None:
            return _check

        try:
            _sized = self._size(ctx)
        except Exception as e:  # noqa: BLE001 — 定容异常不阻断主循环
            self._log(f"[P2-S4b] {ctx['symbol']} 定容异常(FAIL-OPEN): {e}", "WARN")
            return {"status": "failed", "reason": f"sizing_exception:{e}", **ctx}
        if _sized.get("status") == "blocked":
            return _sized
        ctx.update(_sized)

        return self._dispatch(ctx)

    # ── 闸门链 ────────────────────────────────────────────────────
    def _check_gates(self, ctx: dict[str, Any]) -> Optional[dict[str, Any]]:
        _sym = ctx["symbol"]
        _inst = ctx["inst_id"]
        _dir = ctx["direction"]
        _tag = ctx["source_tag"]
        _tier = ctx["tier"]

        # 0.0 执行权限闸门（影子模式拦截非白名单标签）
        _permit = self._call(self.authority_fn, True, "authority_fn", (_tag,))
        if not _permit:
            if self.on_shadow is not None:
                try:
                    self.on_shadow(ctx)
                except Exception:  # noqa: BLE001
                    pass
            return self._blocked(ctx, "execution_authority", f"tag={_tag} → 影子模式", "WARN")

        # 0.1 统一黑名单
        _bl = self._call(self.blacklist_fn, (False, ""), "blacklist_fn", (_sym,))
        if isinstance(_bl, tuple) and len(_bl) == 2:
            _bl_blocked, _bl_reason = bool(_bl[0]), str(_bl[1])
        else:
            _bl_blocked, _bl_reason = bool(_bl), ""
        if _bl_blocked:
            return self._blocked(ctx, "blacklist", _bl_reason or "dynamic_blacklist")

        # 0.5 u_open/cbr_sim 耦合拦截：强信号 + 弱历史相似度
        if ctx["u_open"] >= 1.0 and ctx["cbr_sim"] < 0.4:
            return self._blocked(
                ctx,
                "u_open_cbr_coupling",
                f"u_open={ctx['u_open']} cbr_sim={ctx['cbr_sim']} < 0.4",
            )

        # 1. 组合熔断
        _fuse = self._call(self.fuse_fn, None, "fuse_fn")
        if _fuse is not None and bool(getattr(_fuse, "block_new_open", False)):
            return self._blocked(ctx, "portfolio_fuse", str(_fuse))

        # 1.5 防重复建仓
        if self._call(self.has_position_fn, False, "has_position_fn", (_inst,)):
            return self._blocked(ctx, "duplicate_position", f"已有持仓 inst_id={_inst}", "DEBUG")

        # 1.6 冷静期
        _cd = self._call(self.cooldown_fn, (False, ""), "cooldown_fn", (_inst, _dir))
        if isinstance(_cd, tuple) and _cd[0]:
            return self._blocked(ctx, "cooldown", str(_cd[1] or "in_cooldown"), "INFO")

        # 1.7 方向状态（FREEZE / SHORT_ONLY / LONG_ONLY）
        _ds = self._call(self.direction_state_fn, "", "direction_state_fn", (_sym, _dir))
        _ds_blocked, _ds_reason = self._direction_state_blocked(_ds, _dir)
        if _ds_blocked:
            return self._blocked(ctx, "direction_state", _ds_reason)

        # 2. evolution 子池总上限
        _sub = self._call(self.subpool_fn, {}, "subpool_fn") or {}
        _count = int(_sub.get("count", 0) or 0)
        _sub_max = int(self._cfg["subpool_max"])
        if _count >= _sub_max:
            return self._blocked(
                ctx, "subpool_full", f"evolution 子池已满 {_count}/{_sub_max}", "DEBUG"
            )

        # 2b. 方向集中度（tier=trend 允许突破）
        _long = int(_sub.get("long", 0) or 0)
        _short = int(_sub.get("short", 0) or 0)
        _ratio_cap = float(self._cfg["max_direction_ratio"])
        _min_pos = int(self._cfg["direction_ratio_min_positions"])
        if _count >= _min_pos and _tier != "trend":
            _long_ratio = _long / max(_count, 1)
            _short_ratio = _short / max(_count, 1)
            if _dir == "long" and _long_ratio > _ratio_cap:
                return self._blocked(
                    ctx,
                    "direction_concentration",
                    f"多头占比 {_long_ratio*100:.0f}% > {_ratio_cap*100:.0f}% "
                    f"(long={_long}/{_count})",
                )
            if _dir == "short" and _short_ratio > _ratio_cap:
                return self._blocked(
                    ctx,
                    "direction_concentration",
                    f"空头占比 {_short_ratio*100:.0f}% > {_ratio_cap*100:.0f}% "
                    f"(short={_short}/{_count})",
                )

        # 2c. probe 独立上限
        if _tier == "probe":
            _probe_count = int(_sub.get("probe_count", 0) or 0)
            _probe_max = int(self._cfg["probe_max"])
            if _probe_count >= _probe_max:
                return self._blocked(
                    ctx,
                    "probe_full",
                    f"evolution 测试仓已满 {_probe_count}/{_probe_max}",
                    "INFO",
                )

        # 2d. 禁空铁律（分层豁免由注入函数返回 pos_mult/sl_mult）
        ctx["layered_pos_mult"] = 1.0
        ctx["layered_sl_mult"] = 1.0
        if _dir == "short":
            _sb = self._call(self.short_ban_fn, {}, "short_ban_fn", (_sym, _dir)) or {}
            if _sb.get("blocked"):
                return self._blocked(
                    ctx, "short_ban", str(_sb.get("reason") or "SHORT_ONLY_BLACKLIST")
                )
            ctx["layered_pos_mult"] = float(_sb.get("pos_mult", 1.0) or 1.0)
            ctx["layered_sl_mult"] = float(_sb.get("sl_mult", 1.0) or 1.0)
            if _sb.get("reason"):
                self._log(f"[P2-S4b] {_sym} SHORT_BAN 豁免 | {_sb.get('reason')}", "INFO")
        return None

    @staticmethod
    def _direction_state_blocked(_ds: Any, direction: str) -> tuple[bool, str]:
        if isinstance(_ds, tuple) and len(_ds) >= 2:
            return bool(_ds[0]), str(_ds[1])
        _state = str(_ds or "").upper()
        if _state == _FREEZE:
            return True, "direction_state=FREEZE 禁止开仓"
        if _state == _SHORT_ONLY and direction == "long":
            return True, "direction_state=SHORT_ONLY 禁止做多"
        if _state == _LONG_ONLY and direction == "short":
            return True, "direction_state=LONG_ONLY 禁止做空"
        return False, ""

    # ── 定容 ──────────────────────────────────────────────────────
    def _size(self, ctx: dict[str, Any]) -> dict[str, Any]:
        _sym = ctx["symbol"]
        _inst = ctx["inst_id"]
        _tier = ctx["tier"]
        _dir = ctx["direction"]
        _kline = ctx["kline"] or {}

        _equity = float(self._call(self.equity_fn, 100.0, "equity_fn") or 100.0)
        _leverage = int(self._cfg["leverage"])
        _notional_budget = _equity * _leverage
        _base_budget = min(_notional_budget, float(self._cfg["budget_per_coin"]))

        _track_mult = float(self._call(self.track_mult_fn, 1.0, "track_mult_fn", (_kline,)) or 0.0)
        if _track_mult <= 0:
            return self._blocked(
                ctx,
                "ftc_track_zero",
                f"FTC track={_kline.get('top_ftc_track', 'exploit')} 仓位为 0",
                "DEBUG",
            )

        _notional = _base_budget * _track_mult * float(ctx["u_open"])
        _notional *= float(ctx.get("layered_pos_mult", 1.0) or 1.0)

        _coin_cls = str(self._call(self.asset_class_fn, "crypto_usdt", "asset_class_fn", (_sym,)))
        _cap_mode = 1.0
        if _env_on("EVOLUTION_MACRO_CAP_MODE", "off"):
            _caps = (
                self._call(self.macro_constraint_fn, {}, "macro_constraint_fn", (_coin_cls,)) or {}
            ).get("aggregate_position_cap_pct", {}) or {}
            _cap_mode = float(_caps.get(_coin_cls, 1.0) or 1.0)
            if _cap_mode < 1.0:
                self._log(
                    f"[P2-S4b] {_sym} 战略层 cap_mode 压缩: cap={_cap_mode:.2f} "
                    f"(cls={_coin_cls}) → {_notional:.1f}U×{_cap_mode:.2f}",
                    "WARN",
                )
        _notional *= _cap_mode

        _max_notional = float(self._cfg["max_notional"])
        if _notional > _max_notional:
            self._log(
                f"[P2-S4b] {_sym} 仓位 {_notional:.1f}U > 最大 {_max_notional}U，钳位至上限",
                "DEBUG",
            )
            _notional = _max_notional

        _price = float((ctx.get("signal") or {}).get("px") or 0.0)
        if _price <= 0:
            _price = self._kline_last_price(_kline)
        if _price <= 0:
            _price = float(self._call(self.price_fn, 0.0, "price_fn", (_inst,)) or 0.0)
        _min_notional, _floor_src = self._resolve_min_notional(_tier, _inst, _price)

        _notional, _quota_attr, _blocked = self._apply_quota(
            ctx, _notional, _coin_cls, _equity, _leverage, _min_notional
        )
        if _blocked is not None:
            return _blocked

        if _notional < _min_notional:
            self._log(
                f"[P2-S4b][ATTR] {_sym} 仓位 {_notional:.1f}U < 最小 {_min_notional:.0f}U "
                f"(tier={_tier} mult={ctx['u_open']:.2f} floor={_floor_src})，跳过 | "
                f"signal_dir={_dir.upper()} mapped_side="
                f"{'buy' if _dir == 'long' else 'sell'} pos_side={_dir} "
                f"exec_path=23.entry_loop",
                "WARN",
            )
            return {
                "status": "blocked",
                "gate": "floor_rejected",
                "reason": f"notional={_notional:.1f}U < min={_min_notional:.0f}U",
                "symbol": _sym,
                "direction": _dir,
                "tier": _tier,
                "notional_usdt": _notional,
            }

        return {
            "status": "sized",
            "notional_usdt": _notional,
            "price": _price,
            "coin_cls": _coin_cls,
            "track_mult": _track_mult,
            "cap_mode": _cap_mode,
            "min_notional": _min_notional,
            "quota_attr": _quota_attr,
        }

    def _resolve_min_notional(self, tier: str, inst_id: str, price: float) -> tuple[float, str]:
        """probe 用交易所 minSz×px×1.2；standard/trend 守配置地板。"""
        if tier != "probe":
            return float(self._cfg["min_notional"]), "config"
        if _env_on("EVOLUTION_PROBE_MIN_SZ_FLOOR", "on"):
            _min_sz = float(self._call(self.min_sz_fn, 0.0, "min_sz_fn", (inst_id,)) or 0.0)
            if _min_sz > 0 and price > 0:
                _buffer = float(self._cfg["probe_min_sz_buffer"])
                return _min_sz * price * _buffer, f"exchange({_min_sz}x{price:.6g}x{_buffer})"
        return float(self._cfg["min_notional_probe"]), "probe_config"

    def _apply_quota(
        self,
        ctx: dict[str, Any],
        notional: float,
        coin_cls: str,
        equity: float,
        leverage: int,
        min_notional: float,
    ) -> tuple[float, str, Optional[dict[str, Any]]]:
        """40/43 弹性约束配额（FAIL-OPEN；缺约束时原样放行）。"""
        if not _env_on("EVOLUTION_QUOTA_GATE", "on"):
            return notional, "quota=NA", None
        _mc = self._call(self.macro_constraint_fn, {}, "macro_constraint_fn", (coin_cls,)) or {}
        if not _mc:
            return notional, "quota=NA", None

        from dreambuddy_evolution.adapters.asset_class_quota import (
            build_quota_plan,
            direction_policy,
            evaluate_entry,
        )

        _plan = build_quota_plan(
            total_equity=equity,
            leverage=leverage,
            band_upper_pct=_mc.get("band_upper_pct"),
            exposure_hint=_mc.get("exposure_hint"),
            allocation=_mc.get("allocation"),
            stale=bool(_mc.get("stale")),
        )
        _bias_row = (_mc.get("direction_bias") or {}).get(coin_cls) or {}
        _dp = direction_policy(ctx["direction"], _bias_row)
        notional = notional * float(_dp["multiplier"])
        if _dp["probe_only"] and ctx["tier"] != "probe":
            return (
                notional,
                "quota=NA",
                self._blocked(
                    ctx,
                    "direction_bias_probe_only",
                    f"direction_bias 中性，仅允许 probe，当前 tier={ctx['tier']}",
                ),
            )

        _used_by_cls = self._call(self.used_notional_fn, {}, "used_notional_fn") or {}
        _qv = evaluate_entry(
            asset_class=coin_cls,
            requested_notional=notional,
            used_notional_by_class=_used_by_cls,
            plan=_plan,
            min_notional=min_notional,
        )
        _q_attr = (
            f"quota={_qv.get('quota', 0):.0f}U used={_qv.get('used', 0):.0f}U "
            f"band={_mc.get('band_upper_pct')}% hint={_mc.get('exposure_hint')} "
            f"bias={_dp.get('reason')} stale={_mc.get('stale')} src={_mc.get('source')}"
        )
        if _qv["decision"] == "block_over_quota":
            self._log(
                f"[P2-S4b][CONSTRAINT] {ctx['symbol']} block_over_quota cls={coin_cls} "
                f"used={_qv['used']:.0f}U ≥ quota={_qv['quota']:.0f}U | {_q_attr}",
                "WARN",
            )
            return notional, _q_attr, self._blocked(ctx, "block_over_quota", _q_attr)
        if _qv["decision"] == "constraint_suppressed":
            return (
                notional,
                _q_attr,
                self._blocked(
                    ctx,
                    "constraint_suppressed",
                    f"remaining={_qv['remaining']:.1f}U < min_notional={min_notional:.0f}U",
                ),
            )
        if _qv["decision"] == "allow_clamped":
            self._log(
                f"[P2-S4b][CONSTRAINT] {ctx['symbol']} 配额钳位 {notional:.1f}U → "
                f"{_qv['allowed_notional']:.1f}U | {_q_attr}",
                "INFO",
            )
        return float(_qv["allowed_notional"]), _q_attr, None

    # ── SL/TP + 下单 ──────────────────────────────────────────────
    def _compute_sltp(self, ctx: dict[str, Any], price: float) -> tuple[float, float, float, float]:
        """返回 (sl_px, tp_px, sl_pct, tp_pct)。优先注入的 11 三维参数中心实现。"""
        _raw = self._call(
            self.sltp_fn,
            None,
            "sltp_fn",
            (
                ctx["tier"],
                ctx["direction"],
                price,
                ctx["source_tag"],
                ctx["kline"],
                ctx["symbol"],
            ),
        )
        if isinstance(_raw, (tuple, list)) and len(_raw) == 4:
            try:
                return (
                    float(_raw[0]),
                    float(_raw[1]),
                    float(_raw[2]),
                    float(_raw[3]),
                )
            except (TypeError, ValueError):
                pass

        _atr = float((ctx["kline"] or {}).get("atr_pct", 0.0) or 0.0)
        _sl_pct, _tp_pct = compute_sl_tp_pct(
            ctx["tier"], _atr, float(self._cfg["sl_floor_pct"]), float(self._cfg["tp_floor_pct"])
        )
        if price <= 0:
            return 0.0, 0.0, _sl_pct, _tp_pct
        if ctx["direction"] == "long":
            return price * (1 - _sl_pct), price * (1 + _tp_pct), _sl_pct, _tp_pct
        return price * (1 + _sl_pct), price * (1 - _tp_pct), _sl_pct, _tp_pct

    def _dispatch(self, ctx: dict[str, Any]) -> dict[str, Any]:
        _sym = ctx["symbol"]
        _inst = ctx["inst_id"]
        _dir = ctx["direction"]
        _notional = float(ctx["notional_usdt"])
        _price = float(ctx.get("price") or 0.0)

        _sl_px, _tp_px, _sl_pct, _tp_pct = self._compute_sltp(ctx, _price)
        ctx.update({"sl_px": _sl_px, "tp_px": _tp_px, "sl_pct": _sl_pct, "tp_pct": _tp_pct})

        self._log(
            f"[P2-S4b][ATTR] {_sym} signal_dir={_dir.upper()} "
            f"mapped_side={'buy' if _dir == 'long' else 'sell'} pos_side={_dir} "
            f"exec_path=23.entry_loop→22.gateway | notional={_notional:.1f}U "
            f"tier={ctx['tier']} conf={ctx['confidence']:.3f} d*={ctx['d_star']} "
            f"u_open={ctx['u_open']:.3f} track={ctx.get('track_mult', 1.0):.2f} "
            f"cap={ctx.get('cap_mode', 1.0):.2f} cls={ctx.get('coin_cls', 'NA')} "
            f"{ctx.get('quota_attr', 'quota=NA')} "
            f"decision_id={(ctx.get('signal') or {}).get('decision_id', '-')}",
            "INFO",
        )

        _decision = build_entry_decision(
            symbol=_inst,
            direction=_dir,
            confidence=ctx["confidence"],
            notional_usdt=_notional,
            tier=ctx["tier"],
            price=_price,
            sl_pct=_sl_pct,
            tp_pct=_tp_pct,
            reason=(
                f"evolution_auto_{_dir} conf={ctx['confidence']:.2f} "
                f"d*={ctx['d_star']} tier={ctx['tier']}"
            ),
            source_tag=ctx["source_tag"],
            strategy="evolution",
        )
        _decision["payload"]["coin"] = _sym
        _decision["payload"]["position_mult"] = ctx["u_open"]
        _decision["payload"]["sl_pct"] = _sl_pct
        _decision["payload"]["tp_pct"] = _tp_pct

        # 23 产出的 signal 元数据（decision_id/expires_at）若存在，保持 23 主链一致
        _incoming = ctx.get("signal") or {}
        if _incoming.get("decision_id"):
            _decision["payload"]["upstream_decision_id"] = _incoming["decision_id"]

        if self._dispatcher is None:
            self._log(f"[P2-S4b] {_sym} 无 22 网关，放弃下单", "WARN")
            return {
                "status": "failed",
                "reason": "no_gateway_injected",
                "symbol": _sym,
                "direction": _dir,
                "notional_usdt": _notional,
            }

        _res = self._dispatcher.dispatch(_decision)
        _out = {
            "status": "opened" if _res.get("executed") else "failed",
            "symbol": _sym,
            "direction": _dir,
            "tier": ctx["tier"],
            "notional_usdt": _notional,
            "decision_id": _res.get("decision_id") or _decision.get("decision_id"),
            "reason": _res.get("reason", ""),
            "reason_code": _res.get("reason_code", ""),
            "result": _res,
        }
        if not _res.get("executed"):
            self._log(
                f"[P2-S4b] {_sym} {_dir} 建仓失败: "
                f"{_res.get('reason') or _res.get('reason_code') or 'unknown'}",
                "WARN",
            )
            return _out

        if self.on_opened is not None:
            try:
                self.on_opened(ctx, _res)
            except Exception as e:  # noqa: BLE001 — 落账异常不影响已成交订单
                self._log(f"[P2-S4b] {_sym} on_opened 回调异常(FAIL-OPEN): {e}", "WARN")

        self._log(
            f"[P2-S4b] {_sym} {_dir} 建仓成功 | 仓位={_notional:.1f}U tier={ctx['tier']} "
            f"mult={ctx['u_open']:.2f} conf={ctx['confidence']:.2f} d*={ctx['d_star']} "
            f"decision_id={_out['decision_id']}",
            "INFO",
        )
        return _out

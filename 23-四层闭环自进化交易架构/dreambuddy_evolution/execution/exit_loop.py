"""23 域离场循环（M1-b：exit loop 下沉）。

职责边界：
- 23 负责：持仓巡检编排 → 上下文组装 → EvolutionExitEngine.decide → RL 覆盖 →
  经 22 TradeExecutionGateway 执行平仓/减仓；SL/TP 调整走注入的 okx_client；
- 11 只负责：提供持仓数据、补充 11 本地上下文（RAG/换仓/BCRM/BDSM）、
  平仓落账与反思回调（hooks）；
- 本模块不 import 任何 11 模块，也不直接持有交易所客户端（构造器注入）。

FAIL-OPEN：单仓异常只跳过该仓；顶层异常由调用方兜底。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .decision_signal import build_exit_decision

_HERE = Path(__file__).resolve().parents[2]
_DEFAULT_RL_MODEL = _HERE / "dreambuddy_evolution" / "data" / "exit_policy_v1.pt"
_DEFAULT_SHADOW_PATH = _HERE / "dreambuddy_evolution" / "gene_data" / "shadow_rl_samples.jsonl"

# 与 11 旧逻辑一致：exit_engine 统一处理的子池
EXIT_ENGINE_TAGS = {"evolution", "bcrm", "strategy", "event_arbitrage"}


def _env_on(name: str, default: str = "on") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "on", "yes")


def _to_epoch(value: Any) -> float:
    """entry_time（ISO 字符串 / epoch）→ 秒。无法解析返回 0。"""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        _ts = str(value)
        _ts = _ts.replace("Z", "+00:00") if _ts.endswith("Z") else _ts
        return datetime.fromisoformat(_ts).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


class EvolutionExitLoop:
    """23 域持仓离场巡检器。

    用法::

        loop = EvolutionExitLoop(gateway=gateway, okx_client=okx_client)
        report = loop.run(positions, enricher=fn, on_closed=fn, on_ghost=fn)

    positions 为 dict 列表，必需字段：
      inst_id / coin / pos_side / entry_price
    可选字段：current_price / position_usdt / position_qty / entry_time /
      source_tag / confidence / tier
    """

    def __init__(
        self,
        gateway: Any = None,
        okx_client: Any = None,
        dispatcher: Any = None,
        exit_engine: Any = None,
        ess_provider: Any = None,
        log_fn: Optional[Callable[[str, str], None]] = None,
        runtime_dir: str | Path | None = None,
        enable_rl: bool | None = None,
        enable_shadow_rl: bool | None = None,
        rl_model_path: str | Path | None = None,
        shadow_persist_path: str | Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._okx = okx_client
        self._log_fn = log_fn or (lambda msg, level="INFO": None)
        self._runtime_dir = Path(runtime_dir) if runtime_dir else None
        self._ess_provider = ess_provider

        self._dispatcher = dispatcher
        if self._dispatcher is None and gateway is not None:
            from .decision_signal import EvolutionSignalDispatcher
            from .outbox import default_outbox

            self._dispatcher = EvolutionSignalDispatcher(
                gateway=gateway, runtime_dir=runtime_dir, outbox=default_outbox()
            )

        self._engine = exit_engine
        self._rl_enabled = _env_on("EVOLUTION_EXIT_RL") if enable_rl is None else bool(enable_rl)
        self._shadow_enabled = (
            _env_on("EVOLUTION_EXIT_SHADOW_RL")
            if enable_shadow_rl is None
            else bool(enable_shadow_rl)
        )
        self._rl_model_path = Path(rl_model_path) if rl_model_path else _DEFAULT_RL_MODEL
        self._shadow_path = (
            Path(shadow_persist_path) if shadow_persist_path else _DEFAULT_SHADOW_PATH
        )
        self._policy = None
        self._policy_ready = False
        self._shadow_tracker = None
        self._reward_calc = None

    # ── 懒初始化 ──────────────────────────────────────────────────
    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            self._log_fn(msg, level)
        except Exception:  # noqa: BLE001
            pass

    def _get_engine(self):
        if self._engine is None:
            from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine

            self._engine = EvolutionExitEngine(
                okx_client=self._okx,
                ess_provider=self._ess_provider,
                ftc_bridge=None,
                shadow_rl_tracker=None,
                log_fn=self._log,
            )
        return self._engine

    def _get_policy(self):
        if self._policy_ready:
            return self._policy
        self._policy_ready = True
        if not self._rl_enabled:
            return None
        try:
            from dreambuddy_evolution.core.exit_rl_policy import CQLTrainer, ShieldedPolicy

            _cql = CQLTrainer(state_dim=8, n_actions=5, lr=1e-4, cql_alpha=0.1)
            if self._rl_model_path.exists():
                _cql.load(str(self._rl_model_path))
                self._log(f"[ExitLoop] ShieldedPolicy 加载 CQL 模型: {self._rl_model_path}", "INFO")
            else:
                self._log(
                    f"[ExitLoop] CQL 模型不存在，ShieldedPolicy FAIL-OPEN(规则兜底): {self._rl_model_path}",
                    "WARN",
                )
                _cql = None
            self._policy = ShieldedPolicy(
                cql_trainer=_cql,
                exit_engine=self._get_engine(),
                log_fn=self._log,
                min_confidence=0.3,
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"[ExitLoop] ShieldedPolicy 初始化异常(FAIL-OPEN): {e}", "WARN")
            self._policy = None
        return self._policy

    def _get_shadow_tracker(self):
        if self._shadow_tracker is not None or not self._shadow_enabled:
            return self._shadow_tracker
        try:
            from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker

            self._shadow_tracker = ShadowRLTracker(
                max_samples=10000, persist_path=self._shadow_path
            )
            self._shadow_tracker.load_from_disk()
            self._log(
                f"[ExitLoop] ShadowRLTracker 初始化 (loaded={self._shadow_tracker.sample_count()})",
                "INFO",
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"[ExitLoop] ShadowRLTracker 初始化异常(FAIL-OPEN): {e}", "WARN")
            self._shadow_tracker = None
        return self._shadow_tracker

    def _get_reward_calc(self):
        if self._reward_calc is None:
            try:
                from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator

                self._reward_calc = ExitRewardCalculator()
            except Exception as e:  # noqa: BLE001
                self._log(f"[ExitLoop] ExitRewardCalculator 初始化异常(FAIL-OPEN): {e}", "WARN")
        return self._reward_calc

    # ── 主循环 ────────────────────────────────────────────────────
    def run(
        self,
        positions: list[dict[str, Any]],
        enricher: Optional[
            Callable[[dict[str, Any], dict[str, Any]], Optional[dict[str, Any]]]
        ] = None,
        on_closed: Optional[
            Callable[[dict[str, Any], Any, dict[str, Any], dict[str, Any]], None]
        ] = None,
        on_ghost: Optional[Callable[[dict[str, Any], float], None]] = None,
        on_decision: Optional[Callable[[dict[str, Any], Any, dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        """巡检一批持仓并执行离场动作，返回汇总报告。"""
        report: dict[str, Any] = {
            "checked": 0,
            "hold": 0,
            "executed": [],
            "failed": [],
            "skipped": 0,
        }
        if not positions:
            return report

        _engine = self._get_engine()
        _policy = self._get_policy()
        _shadow = self._get_shadow_tracker()

        for pos in positions:
            try:
                _res = self._run_one(
                    pos, _engine, _policy, _shadow, enricher, on_closed, on_ghost, on_decision
                )
            except Exception as e:  # noqa: BLE001 — 单仓 FAIL-OPEN
                self._log(f"[ExitLoop] {pos.get('coin', '?')} 巡检异常(FAIL-OPEN): {e}", "WARN")
                _res = {"status": "failed", "reason": f"exception:{e}"}

            report["checked"] += 1
            _status = _res.get("status")
            if _status == "hold":
                report["hold"] += 1
            elif _status == "skipped":
                report["skipped"] += 1
            elif _status == "executed":
                report["executed"].append(_res)
            else:
                report["failed"].append(_res)

        return report

    def _run_one(self, pos, engine, policy, shadow, enricher, on_closed, on_ghost, on_decision):
        inst_id = str(pos.get("inst_id") or "")
        coin = str(pos.get("coin") or inst_id.split("-")[0]).upper()
        pos_side = str(pos.get("pos_side") or pos.get("direction") or "long").lower()
        entry_price = float(pos.get("entry_price") or 0.0)
        if not inst_id or entry_price <= 0:
            return {"status": "skipped", "reason": "invalid_position"}

        current_price = float(pos.get("current_price") or 0.0)
        position_usdt = float(pos.get("position_usdt") or 0.0)

        # OKX 持仓消失检测（幽灵仓）
        if current_price <= 0 or position_usdt <= 0:
            _gone = self._sync_from_exchange(pos, current_price, position_usdt)
            if _gone is not None:
                current_price, position_usdt = _gone
                if current_price <= 0:
                    if on_ghost is not None:
                        on_ghost(pos, entry_price)
                    return {"status": "skipped", "reason": "ghost_position"}
        if current_price <= 0:
            current_price = entry_price

        upl_ratio = (
            (current_price - entry_price) / entry_price
            if pos_side == "long"
            else (entry_price - current_price) / entry_price
        )
        upl = position_usdt * upl_ratio
        _entry_epoch = _to_epoch(pos.get("entry_time"))
        age_sec = max(0.0, time.time() - _entry_epoch) if _entry_epoch > 0 else 0.0

        ctx: dict[str, Any] = {
            "symbol": coin,
            "inst_id": inst_id,
            "pos_side": pos_side,
            "source_tag": str(pos.get("source_tag") or "").lower(),
            "entry_price": entry_price,
            "current_price": current_price,
            "position_usdt": position_usdt,
            "upl": upl,
            "upl_ratio": upl_ratio,
            "position_age_sec": age_sec,
            "confidence": float(pos.get("confidence") or 0.0),
            "tier": str(pos.get("tier") or "standard").lower(),
            "r_vector": {},
            "ess": 0.5,
            "ftc_track": "exploit",
            "regime": "",
            "atr_pct": 0.02,
            "current_sl_px": 0.0,
            "current_tp_px": 0.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": False,
            "stronger_signal_info": None,
            "bcrm_reverse_dir": "",
            "bcrm_reverse_conf": 0.0,
            "bcrm_reverse_ts": 0.0,
            "bdsm_direction_constraint": "",
            "rag_context": [],
        }

        if enricher is not None:
            _extra = enricher(pos, ctx)
            if _extra is None:
                return {"status": "skipped", "reason": "enricher_skip"}
            if isinstance(_extra, dict):
                ctx.update(_extra)

        decision = engine.decide(ctx)
        decision = self._apply_rl_override(decision, ctx, policy)
        self._log(
            f"[ExitLoop] {coin} decide: action={decision.action} reason={decision.reason} "
            f"conf={decision.confidence:.2f} upl={upl:.2f}({upl_ratio:.2%}) "
            f"age={int(age_sec / 60)}min",
            "INFO",
        )

        if on_decision is not None:
            try:
                on_decision(pos, decision, ctx)
            except Exception as e:  # noqa: BLE001
                self._log(f"[ExitLoop] {coin} on_decision 异常(FAIL-OPEN): {e}", "DEBUG")

        self._record_shadow(shadow, coin, ctx, decision, upl_ratio)

        if decision.action == "hold":
            return {"status": "hold", "action": "hold"}

        if decision.action == "force_close":
            return self._execute_close(pos, inst_id, coin, pos_side, 1.0, decision, ctx, on_closed)

        if decision.action == "partial_close":
            _pct = float((decision.params or {}).get("partial_pct", 0.5) or 0.5)
            _pct = max(0.1, min(0.9, _pct))
            return self._execute_close(pos, inst_id, coin, pos_side, _pct, decision, ctx, on_closed)

        if decision.action in ("adjust_sl_tp", "trailing"):
            return self._apply_sl_tp(pos, inst_id, coin, decision, ctx)

        return {"status": "skipped", "reason": f"unsupported_action:{decision.action}"}

    # ── 子步骤 ────────────────────────────────────────────────────
    def _sync_from_exchange(self, pos, current_price: float, position_usdt: float):
        """用 OKX 持仓补齐价格/名义；确认无仓返回 (0, 0) 表示幽灵仓。"""
        if self._okx is None:
            return None
        try:
            _q = self._okx.get_positions(pos.get("inst_id"))
            if not _q.get("ok"):
                return None
            _hits = [p for p in (_q.get("positions") or []) if float(p.get("pos", 0) or 0) > 0]
            if not _hits:
                if _q.get("query_failed"):
                    return None
                self._log(
                    f"[ExitLoop] {pos.get('coin')} OKX 无持仓但本地有记录，标记幽灵仓", "WARN"
                )
                return (0.0, 0.0)
            _p = _hits[0]
            _px = float(_p.get("mark_px") or _p.get("last_px") or current_price or 0)
            _qty = abs(float(_p.get("pos", 0) or 0))
            _usdt = position_usdt if position_usdt > 0 else _qty * _px
            return (max(current_price, _px), _usdt)
        except Exception as e:  # noqa: BLE001
            self._log(f"[ExitLoop] 持仓同步失败(FAIL-OPEN): {e}", "DEBUG")
            return None

    def _apply_rl_override(self, decision, ctx: dict[str, Any], policy):
        if policy is None:
            return decision
        try:
            import numpy as np

            _tier_idx = {"probe": 0, "standard": 1, "trend": 2}.get(ctx.get("tier", "standard"), 1)
            _state = np.array(
                [
                    ctx["upl_ratio"],
                    ctx["position_age_sec"] / 60.0,
                    ctx["atr_pct"],
                    float(ctx.get("rsi", 50.0) or 50.0),
                    float(ctx.get("ess", 0.5) or 0.5),
                    float(ctx.get("cs", 0.5) or 0.5),
                    float(ctx.get("vol_ratio", 1.0) or 1.0),
                    _tier_idx,
                ],
                dtype=np.float32,
            )
            _action, _params = policy.act_with_shield(_state, ctx)
            _conf = float(_params.get("confidence", 0.0) or 0.0)
            self._log(
                f"[ExitLoop] {ctx['symbol']} RL: action={_action} conf={_conf:.3f} "
                f"shielded={_params.get('shielded', False)}",
                "DEBUG",
            )
            if _conf <= 0.7 or _action == "hold" or _action == decision.action:
                return decision
            from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision

            return ExitDecision(
                action=_action,
                params={"rl_confidence": _conf, "q_values": _params.get("q_values", [])},
                reason=f"evolution_rl:override:{_action}",
                sl_px=decision.sl_px,
                tp_px=decision.tp_px,
                confidence=max(decision.confidence, _conf),
            )
        except Exception as e:  # noqa: BLE001 — RL 失败保留规则决策
            self._log(f"[ExitLoop] {ctx.get('symbol')} RL 推理异常(FAIL-OPEN): {e}", "WARN")
            return decision

    def _record_shadow(self, shadow, coin: str, ctx: dict[str, Any], decision, upl_ratio: float):
        if shadow is None:
            return
        try:
            if decision.action == "hold":
                _reward = 0.0
            else:
                _calc = self._get_reward_calc()
                _reward = upl_ratio * 5.0
                if _calc is not None:
                    try:
                        _r = _calc.calculate(
                            {
                                "cs": ctx.get("cs", 0.0),
                                "sl_in_range": True,
                                "pnl_pct": upl_ratio,
                                "tp_pct_target": ctx.get("tp_pct", 0.06),
                                "sl_pct_target": ctx.get("sl_pct", 0.03),
                            }
                        )
                        _reward = _r.get("R_total", _reward)
                    except Exception:  # noqa: BLE001
                        pass
            shadow.record(
                symbol=coin,
                state={
                    "upl_ratio": upl_ratio,
                    "position_age_min": ctx["position_age_sec"] / 60.0,
                    "atr_pct": ctx["atr_pct"],
                    "ess": ctx.get("ess", 0.5),
                    "tier": ctx.get("tier", "standard"),
                    "action": decision.action,
                },
                action=decision.action,
                reward=_reward,
                next_state=None,
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"[ExitLoop] {coin} ShadowRL 记录异常(FAIL-OPEN): {e}", "DEBUG")

    def _resolve_close_sz(self, pos, inst_id: str, pos_side: str, ratio: float) -> int:
        _full = 0
        if self._okx is not None:
            try:
                _q = self._okx.get_positions(inst_id)
                if _q.get("ok"):
                    for _p in _q.get("positions") or []:
                        if _p.get("pos_side") == pos_side and float(_p.get("pos", 0) or 0) > 0:
                            _full = int(float(_p.get("pos", 0)))
                            break
            except Exception as e:  # noqa: BLE001
                self._log(f"[ExitLoop] {inst_id} 查询持仓失败: {e}", "DEBUG")
        if _full <= 0:
            _full = int(float(pos.get("position_qty") or pos.get("sz") or 0))
        if _full <= 0:
            return 0
        if ratio >= 0.999:
            return _full
        return max(1, int(_full * max(0.01, min(ratio, 1.0))))

    def _execute_close(self, pos, inst_id, coin, pos_side, ratio, decision, ctx, on_closed):
        if self._dispatcher is None:
            return {"status": "failed", "reason": "no_gateway"}
        _sz = self._resolve_close_sz(pos, inst_id, pos_side, ratio)
        if _sz <= 0:
            self._log(f"[ExitLoop] {coin} 无法确定平仓数量，跳过", "WARN")
            return {"status": "failed", "reason": "size_unknown"}

        _sig = build_exit_decision(
            symbol=inst_id,
            direction=pos_side,
            sz=_sz,
            notional_usdt=float(ctx.get("position_usdt") or 0.0),
            reduce_ratio=ratio,
            reason=str(decision.reason or f"23 exit {inst_id}"),
        )
        _res = self._dispatcher.dispatch(_sig)
        if not _res.get("executed"):
            self._log(
                f"[ExitLoop] {coin} {_sig['action']} 失败: "
                f"{_res.get('reason')}({_res.get('reason_code')})",
                "WARN",
            )
            return {
                "status": "failed",
                "reason": _res.get("reason"),
                "reason_code": _res.get("reason_code"),
                "action": _sig["action"],
            }

        self._log(
            f"[ExitLoop] {coin} {_sig['action']} 成功 sz={_sz} decision_id={_sig['decision_id']}",
            "INFO",
        )
        if on_closed is not None:
            try:
                on_closed(pos, decision, _res, ctx)
            except Exception as e:  # noqa: BLE001
                self._log(f"[ExitLoop] {coin} on_closed 异常(FAIL-OPEN): {e}", "WARN")
        return {
            "status": "executed",
            "action": _sig["action"],
            "sz": _sz,
            "decision_id": _sig["decision_id"],
        }

    def _apply_sl_tp(self, pos, inst_id, coin, decision, ctx):
        if self._okx is None:
            return {"status": "failed", "reason": "no_okx_client"}
        _new_sl = float(decision.sl_px or 0.0) or float(ctx.get("current_sl_px") or 0.0)
        _new_tp = float(decision.tp_px or 0.0) or float(ctx.get("current_tp_px") or 0.0)
        if _new_sl <= 0 and _new_tp <= 0:
            return {"status": "skipped", "reason": "no_sl_tp"}
        try:
            if hasattr(self._okx, "cancel_algo_orders"):
                self._okx.cancel_algo_orders(inst_id=inst_id)
            if not hasattr(self._okx, "place_stop_loss_take_profit"):
                return {"status": "failed", "reason": "sltp_unsupported"}
            self._okx.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=str(ctx.get("pos_side") or "long"),
                stop_loss_px=_new_sl,
                take_profit_px=_new_tp,
                reason=decision.reason,
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"[ExitLoop] {coin} {decision.action} 失败: {e}", "WARN")
            return {"status": "failed", "reason": f"sltp_error:{e}", "action": decision.action}
        self._log(f"[ExitLoop] {coin} {decision.action} SL→{_new_sl:.4f} TP→{_new_tp:.4f}", "INFO")
        return {"status": "executed", "action": decision.action}

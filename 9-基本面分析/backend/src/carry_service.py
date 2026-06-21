import math
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request


def _now_ms_fallback() -> int:
    return int(time.time() * 1000)


def ensure_carry_worker_started(svc: Any) -> None:
    try:
        flag = bool(getattr(svc, "_CARRY_WORKER_STARTED", False))
    except Exception:
        flag = False
    enabled = os.environ.get("CARRY_WORKER_ENABLED", "1")
    try:
        enabled = str(enabled).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        enabled = True
    th = getattr(svc, "_CARRY_WORKER_THREAD", None)
    try:
        th_alive = bool(th is not None and hasattr(th, "is_alive") and th.is_alive())
    except Exception:
        th_alive = False
    if not (enabled and ((not flag) or (not th_alive))):
        return

    def _loop() -> None:
        while True:
            try:
                try:
                    now_ms = int(svc._now_ms())
                except Exception:
                    now_ms = int(_now_ms_fallback())
                need_tick = bool((svc.CONFIG or {}).get("carry_trade_enabled", False))
                if not need_tick:
                    try:
                        cp = (svc.TRACKER_STATE or {}).get("carry_positions")
                        if isinstance(cp, dict) and len(cp) > 0:
                            need_tick = True
                    except Exception:
                        need_tick = False
                if need_tick:
                    try:
                        with svc.app.app_context():
                            svc._carry_trade_tick_safe(now_ms=int(now_ms))
                    except Exception as e:
                        try:
                            svc.LOG.error("carry_worker_tick_error %s", str(e))
                        except Exception:
                            pass
            except Exception as e:
                try:
                    svc.LOG.error("carry_worker_error %s", str(e))
                except Exception:
                    pass

            try:
                per = int((svc.CONFIG or {}).get("carry_trade_tick_period_seconds", 3600) or 3600)
            except Exception:
                per = 3600
            per = max(3, min(21600, int(per)))
            time.sleep(float(per))

    try:
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        setattr(svc, "_CARRY_WORKER_STARTED", True)
        setattr(svc, "_CARRY_WORKER_THREAD", t)
    except Exception:
        return


def register_routes(app: Flask, svc: Any) -> None:
    try:
        if bool(getattr(svc, "_CARRY_ROUTES_REGISTERED", False)):
            return
    except Exception:
        pass

    def _carry_status_step_map(step: Optional[str]) -> Optional[str]:
        if step is None:
            return None
        s = str(step).strip().lower()
        if not s:
            return None
        if s in ("refresh", "universe", "funding", "idle", "paused", "error"):
            return s
        if "funding" in s:
            return "funding"
        if s.startswith("universe"):
            return "universe"
        if s.startswith("pool") or "refresh" in s:
            return "refresh"
        return s

    @app.route("/carry/status", methods=["GET"], endpoint="carry__status")
    def carry_status():
        now_ms = int(svc._now_ms())
        venue_eff = "hyperliquid"
        eff = svc._carry_cfg_effective(int(now_ms), venue=str(venue_eff))
        cfg_eff = (eff.get("cfg_effective") if isinstance(eff, dict) else None)
        cfg_eff = (cfg_eff if isinstance(cfg_eff, dict) else {})
        carry_mode = str(cfg_eff.get("carry_trade_mode", "perp") or "perp").strip().lower() or "perp"

        clk = svc._carry_funding_clock(int(now_ms), str(venue_eff))
        minutes_to_next = 0.0
        try:
            if int(clk.get("next_ts") or 0) > 0:
                minutes_to_next = (float(int(clk.get("next_ts") or 0) - int(now_ms))) / 60_000.0
        except Exception:
            minutes_to_next = 0.0

        pnl = svc._carry_pnl_breakdown(int(now_ms), venue=str(clk.get("venue") or venue_eff), cfg=dict(cfg_eff))
        try:
            svc._carry_funding_ledger_tick(int(now_ms), dict(clk), dict(pnl) if isinstance(pnl, dict) else {})
        except Exception:
            pass
        try:
            funding_income = svc._carry_funding_income_view(int(now_ms), dict(clk), dict(pnl) if isinstance(pnl, dict) else {})
        except Exception:
            funding_income = {"ok": False}
        eng = svc._carry_state_get()
        eng_view = {
            "tick_ts": (None if not isinstance(eng, dict) else eng.get("tick_ts")),
            "pool_ts": (None if not isinstance(eng, dict) else eng.get("pool_ts")),
            "pool_n": (None if not isinstance(eng, dict) else (len(eng.get("pool") or []) if isinstance(eng.get("pool"), list) else None)),
            "pool_refreshing": (None if not isinstance(eng, dict) else eng.get("pool_refreshing")),
            "pool_refreshing_ok": (None if not isinstance(eng, dict) else eng.get("pool_refreshing_ok")),
            "pool_last_error": (None if not isinstance(eng, dict) else eng.get("pool_last_error")),
            "positions_count": (None if not isinstance(eng, dict) else eng.get("positions_count")),
            "open_window": (None if not isinstance(eng, dict) else eng.get("open_window")),
        }

        carry_universe_view = None
        try:
            if str(venue_eff).strip().lower() in ("hyperliquid", "hl"):
                with svc.CARRY_UNIVERSE_LOCK:
                    coins0 = svc.CARRY_UNIVERSE_STATE.get("coins") if isinstance(svc.CARRY_UNIVERSE_STATE, dict) else None
                    n0 = int(len(coins0)) if isinstance(coins0, list) else 0
                    carry_universe_view = {
                        "ts": int(svc.CARRY_UNIVERSE_STATE.get("ts") or 0),
                        "venue": str(svc.CARRY_UNIVERSE_STATE.get("venue") or "hyperliquid"),
                        "n": int(n0),
                        "last_error": (
                            None
                            if svc.CARRY_UNIVERSE_STATE.get("last_error") is None
                            else dict(svc.CARRY_UNIVERSE_STATE.get("last_error"))
                            if isinstance(svc.CARRY_UNIVERSE_STATE.get("last_error"), dict)
                            else {"raw": svc.CARRY_UNIVERSE_STATE.get("last_error")}
                        ),
                    }
        except Exception:
            carry_universe_view = None

        include_positions_q = request.args.get("include_positions")
        include_positions = False
        if include_positions_q is not None:
            v = str(include_positions_q).strip().lower()
            include_positions = v in ("1", "true", "yes", "on")

        include_events_q = request.args.get("include_events")
        include_events = False
        if include_events_q is not None:
            v = str(include_events_q).strip().lower()
            include_events = v in ("1", "true", "yes", "on")

        positions_view = None
        if bool(include_positions):
            v = str(clk.get("venue") or venue_eff).strip().lower() or str(venue_eff)
            pos = svc._carry_positions_get()
            out: List[Dict[str, Any]] = []
            for pair, p in pos.items():
                if not isinstance(p, dict):
                    continue
                if str(p.get("venue") or "").strip().lower() != str(v):
                    continue
                out.append(
                    {
                        "pair": str(pair),
                        "coin": (None if p.get("coin") is None else str(p.get("coin"))),
                        "mode": (None if p.get("mode") is None else str(p.get("mode"))),
                        "status": (None if p.get("status") is None else str(p.get("status"))),
                        "hedge_stage": (None if p.get("hedge_stage") is None else str(p.get("hedge_stage"))),
                        "entry_ts": (None if p.get("entry_ts") is None else int(p.get("entry_ts") or 0)),
                        "target_funding_ts": (None if p.get("target_funding_ts") is None else int(p.get("target_funding_ts") or 0)),
                        "unhedge_ts": (None if p.get("unhedge_ts") is None else int(p.get("unhedge_ts") or 0)),
                        "unhedge_deadline_ts": (None if p.get("unhedge_deadline_ts") is None else int(p.get("unhedge_deadline_ts") or 0)),
                        "macro_dir": (None if p.get("macro_dir") is None else int(p.get("macro_dir") or 0)),
                        "reversal_dir": (None if p.get("reversal_dir") is None else int(p.get("reversal_dir") or 0)),
                        "best_timing_score": (None if p.get("best_timing_score") is None else float(p.get("best_timing_score") or 0.0)),
                        "unhedge_exit_score": (None if p.get("unhedge_exit_score") is None else float(p.get("unhedge_exit_score") or 0.0)),
                        "net_pnl_usdc_est": (None if p.get("net_pnl_usdc_est") is None else float(p.get("net_pnl_usdc_est") or 0.0)),
                        "last_unhedge": (
                            None
                            if p.get("last_unhedge") is None
                            else (dict(p.get("last_unhedge")) if isinstance(p.get("last_unhedge"), dict) else {"raw": p.get("last_unhedge")})
                        ),
                        "active_monitor": (
                            None
                            if p.get("active_monitor") is None
                            else (dict(p.get("active_monitor")) if isinstance(p.get("active_monitor"), dict) else {"raw": p.get("active_monitor")})
                        ),
                    }
                )
            positions_view = {"n": int(len(out)), "items": out}

        active_position = None
        try:
            v = str(clk.get("venue") or venue_eff).strip().lower() or str(venue_eff)
            pos = svc._carry_positions_get()
            for pair, p in pos.items():
                if not isinstance(p, dict):
                    continue
                if str(p.get("venue") or "").strip().lower() != str(v):
                    continue
                if str(p.get("status") or "").strip().lower() not in ("open", "opened", "paper_opened", "closing"):
                    continue
                active_position = {
                    "pair": str(pair),
                    "coin": (None if p.get("coin") is None else str(p.get("coin"))),
                    "mode": (None if p.get("mode") is None else str(p.get("mode"))),
                    "status": (None if p.get("status") is None else str(p.get("status"))),
                    "hedge_stage": (None if p.get("hedge_stage") is None else str(p.get("hedge_stage"))),
                    "entry_ts": (None if p.get("entry_ts") is None else int(p.get("entry_ts") or 0)),
                }
                break
        except Exception:
            active_position = None

        events_view = None
        if bool(include_events):
            try:
                evs = (eng.get("events") if isinstance(eng, dict) else None)
                if not isinstance(evs, list):
                    evs = []
                tail_n = 50
                try:
                    tail_n = int(request.args.get("events_n") or 50)
                except Exception:
                    tail_n = 50
                tail_n = max(1, min(200, int(tail_n)))
                events_view = {"n": int(min(len(evs), tail_n)), "items": list(evs)[-int(tail_n) :]}
            except Exception:
                events_view = {"n": 0, "items": []}

        payload: Dict[str, Any] = {
            "ok": True,
            "ts": int(now_ms),
            "venue": str(clk.get("venue") or venue_eff),
            "enabled": bool((eff.get("cfg_base") or {}).get("carry_trade_enabled", False)),
            "enabled_effective": bool(((eff.get("gate") or {}).get("enabled_effective")) if isinstance(eff, dict) else False),
            "live_enabled": (
                bool(svc._carry_live_trading_enabled())
                if hasattr(svc, "_carry_live_trading_enabled")
                else bool((eff.get("cfg_effective") or {}).get("carry_trade_live_enabled", False))
            ),
            "sandbox": bool((eff.get("cfg_effective") or {}).get("carry_trade_sandbox", True)),
            "execute_allowed": bool(svc._carry_execute_allowed(str(clk.get("venue") or venue_eff))),
            "execute_effective": bool(((eff.get("gate") or {}).get("enabled_effective")) if isinstance(eff, dict) else False)
            and (not bool((eff.get("cfg_effective") or {}).get("carry_trade_sandbox", True)))
            and bool(svc._carry_execute_allowed(str(clk.get("venue") or venue_eff))),
            "next_funding_ts": int(clk.get("next_ts") or 0),
            "minutes_to_funding": float(minutes_to_next),
            "window_state": svc._carry_window_state(float(clk.get("minutes_to") or 0.0)),
            "base_ts": int(clk.get("base_ts") or 0),
            "minutes_to_base": float(clk.get("minutes_to") or 0.0),
            "funding_pnl": (None if not isinstance(pnl, dict) or pnl.get("funding_pnl") is None else float(pnl.get("funding_pnl") or 0.0)),
            "price_move_pnl": (None if not isinstance(pnl, dict) or pnl.get("price_move_pnl") is None else float(pnl.get("price_move_pnl") or 0.0)),
            "costs": (None if not isinstance(pnl, dict) or pnl.get("costs") is None else float(pnl.get("costs") or 0.0)),
            "pnl": pnl,
            "funding_income": funding_income,
            "profile": str(eff.get("profile") or ""),
            "profiles": (eff.get("profiles") or {}),
            "regime": (eff.get("regime") or {}),
            "gate": (eff.get("gate") or {}),
            "cfg_base": (eff.get("cfg_base") or {}),
            "cfg_effective": (eff.get("cfg_effective") or {}),
            "status": {
                "step_raw": (None if not isinstance(eng, dict) else eng.get("step")),
                "step": _carry_status_step_map(
                    (
                        (None if not isinstance(eng, dict) else eng.get("step"))
                        or (
                            "paused"
                            if not bool(((eff.get("gate") or {}).get("enabled_effective")) if isinstance(eff, dict) else False)
                            else "idle"
                        )
                    )
                ),
                "step_ts": (None if not isinstance(eng, dict) else (eng.get("step_ts") or eng.get("tick_ts"))),
                "last_error": (None if not isinstance(eng, dict) else eng.get("last_error")),
            },
            "engine": eng_view,
            "carry_universe": carry_universe_view,
            "active_position": active_position,
        }
        if positions_view is not None:
            payload["positions"] = positions_view
        if events_view is not None:
            payload["events"] = events_view
        return jsonify(payload)

    @app.route("/carry/candidates", methods=["GET"], endpoint="carry__candidates")
    def carry_candidates():
        now_ms = int(svc._now_ms())
        try:
            n = int(request.args.get("n") or ((svc.CONFIG or {}).get("carry_trade_candidates_top_n") or 10))
        except Exception:
            n = int((svc.CONFIG or {}).get("carry_trade_candidates_top_n") or 10)
        n = max(1, min(200, int(n)))

        venue_eff = "hyperliquid"
        eff = svc._carry_cfg_effective(int(now_ms), venue=str(venue_eff))
        cfg_eff = (eff.get("cfg_effective") if isinstance(eff, dict) else None)
        cfg_eff = (cfg_eff if isinstance(cfg_eff, dict) else {})

        clk = svc._carry_funding_clock(int(now_ms), str(venue_eff))
        minutes_to_next = 0.0
        try:
            if int(clk.get("next_ts") or 0) > 0:
                minutes_to_next = (float(int(clk.get("next_ts") or 0) - int(now_ms))) / 60_000.0
        except Exception:
            minutes_to_next = 0.0

        ws = svc._carry_window_state(float(clk.get("minutes_to") or 0.0))
        if str(ws) == "WAIT":
            n = min(int(n), 8)

        refresh_q = request.args.get("refresh")
        refresh = False
        if refresh_q is not None:
            v = str(refresh_q).strip().lower()
            refresh = v in ("1", "true", "yes", "on")

        cache_info: Dict[str, Any] = {"ok": False}

        pool_state: Dict[str, Any] = {"ok": False}

        universe_state: Dict[str, Any] = {"ok": True, "n": 0, "ts": 0, "venue": str(venue_eff), "last_error": None}
        try:
            with svc.CARRY_UNIVERSE_LOCK:
                coins0 = svc.CARRY_UNIVERSE_STATE.get("coins") if isinstance(svc.CARRY_UNIVERSE_STATE, dict) else None
                n0 = int(len(coins0)) if isinstance(coins0, list) else 0
                universe_state = {
                    "ok": True,
                    "ts": int(svc.CARRY_UNIVERSE_STATE.get("ts") or 0),
                    "venue": str(svc.CARRY_UNIVERSE_STATE.get("venue") or str(venue_eff)),
                    "n": int(n0),
                    "last_error": (
                        None
                        if svc.CARRY_UNIVERSE_STATE.get("last_error") is None
                        else dict(svc.CARRY_UNIVERSE_STATE.get("last_error"))
                        if isinstance(svc.CARRY_UNIVERSE_STATE.get("last_error"), dict)
                        else {"raw": svc.CARRY_UNIVERSE_STATE.get("last_error")}
                    ),
                }
        except Exception as e:
            universe_state = {"ok": False, "error": str(e)}

        refresh_scheduled = False

        candidates: List[Dict[str, Any]] = []
        if venue_eff in ("hyperliquid", "hl"):
            try:
                cfg_eff = (eff.get("cfg_effective") if isinstance(eff, dict) else None)
                st = svc._carry_state_get()
                cached_pool = (st.get("pool") if isinstance(st, dict) else None)
                cached_venue = (st.get("venue") if isinstance(st, dict) else None)
                try:
                    cached_ts = int((st.get("pool_ts") if isinstance(st, dict) else 0) or 0)
                except Exception:
                    cached_ts = 0

                try:
                    if isinstance(st, dict) and bool(st.get("pool_refreshing", False)):
                        ts0 = int(st.get("pool_refreshing_ts") or 0)
                        max_ms = int((cfg_eff or {}).get("carry_trade_pool_refresh_max_ms", (svc.CONFIG or {}).get("carry_trade_pool_refresh_max_ms", 30000)) or 30000)
                        max_ms = max(1000, min(600000, int(max_ms)))
                        if ts0 > 0 and (int(now_ms) - int(ts0)) > int(max_ms):
                            st["pool_refreshing"] = False
                            st["pool_refreshing_done_ts"] = int(now_ms)
                            st["pool_refreshing_ok"] = False
                            st["pool_last_error"] = {"ts": int(now_ms), "error": "pool_refresh_timeout"}
                except Exception:
                    pass
                if isinstance(cached_pool, list) and str(cached_venue or "").strip().lower() == str(venue_eff) and cached_ts > 0:
                    candidates = list(cached_pool)[: int(n)]
                    try:
                        cache_info = {
                            "ok": True,
                            "venue": str(cached_venue),
                            "pool_ts": int(cached_ts),
                            "age_ms": int(now_ms) - int(cached_ts),
                            "pool_n": int(len(cached_pool)),
                        }
                    except Exception:
                        cache_info = {"ok": True}

                if isinstance(st, dict):
                    pool_state = {
                        "ok": True,
                        "venue": (None if st.get("venue") is None else str(st.get("venue"))),
                        "pool_ts": (None if st.get("pool_ts") is None else int(st.get("pool_ts") or 0)),
                        "pool_n": (len(st.get("pool") or []) if isinstance(st.get("pool"), list) else None),
                        "refreshing": bool(st.get("pool_refreshing", False)),
                        "refreshing_ts": (None if st.get("pool_refreshing_ts") is None else int(st.get("pool_refreshing_ts") or 0)),
                        "refreshing_done_ts": (None if st.get("pool_refreshing_done_ts") is None else int(st.get("pool_refreshing_done_ts") or 0)),
                        "refreshing_ok": (None if st.get("pool_refreshing_ok") is None else bool(st.get("pool_refreshing_ok"))),
                        "last_error": (None if st.get("pool_last_error") is None else (dict(st.get("pool_last_error")) if isinstance(st.get("pool_last_error"), dict) else {"raw": st.get("pool_last_error")})),
                    }

                cache_stale = False
                try:
                    cache_stale = bool(cache_info.get("ok")) and int(cache_info.get("age_ms") or 0) >= 20_000
                except Exception:
                    cache_stale = False

                if bool(refresh) or (not candidates) or bool(cache_stale):
                    if isinstance(st, dict) and (not bool(st.get("pool_refreshing", False))):
                        st["pool_refreshing"] = True
                        st["pool_refreshing_ts"] = int(now_ms)

                        def _bg_refresh_pool():
                            with svc.app.app_context():
                                ok = False
                                try:
                                    cfg0 = (cfg_eff if isinstance(cfg_eff, dict) else None)
                                    n_pool = 10
                                    try:
                                        n_pool = int((cfg0 or {}).get("carry_trade_candidates_top_n", (svc.CONFIG or {}).get("carry_trade_candidates_top_n", 10)) or 10)
                                    except Exception:
                                        n_pool = 10
                                    n_pool = max(int(n), max(1, min(200, int(n_pool))))
                                    pool2 = svc._carry_candidates_hl(int(svc._now_ms()), int(n_pool), cfg=(cfg0 if isinstance(cfg0, dict) else None))
                                    st2 = svc._carry_state_get()
                                    st2["pool"] = list(pool2) if isinstance(pool2, list) else []
                                    st2["pool_ts"] = int(svc._now_ms())
                                    st2["venue"] = str(venue_eff)
                                    last_err = None
                                    try:
                                        last_err = (svc.HL_META_ASSET_CTX_CACHE.get("last_error") if isinstance(getattr(svc, "HL_META_ASSET_CTX_CACHE", None), dict) else None)
                                    except Exception:
                                        last_err = None
                                    if ((not isinstance(pool2, list)) or (len(pool2) == 0)) and last_err is not None:
                                        st2["pool_last_error"] = (
                                            dict(last_err)
                                            if isinstance(last_err, dict)
                                            else {"ts": int(svc._now_ms()), "error": str(last_err)}
                                        )
                                    else:
                                        st2["pool_last_error"] = None
                                    ok = True
                                except Exception as e:
                                    ok = False
                                    try:
                                        st2 = svc._carry_state_get()
                                        st2["pool_last_error"] = {"ts": int(svc._now_ms()), "error": str(e)}
                                    except Exception:
                                        pass
                                try:
                                    st2 = svc._carry_state_get()
                                    st2["pool_refreshing"] = False
                                    st2["pool_refreshing_done_ts"] = int(svc._now_ms())
                                    st2["pool_refreshing_ok"] = bool(ok)
                                except Exception:
                                    pass

                        threading.Thread(target=_bg_refresh_pool, daemon=True).start()
                        refresh_scheduled = True

                if bool(refresh):
                    try:
                        if isinstance(pool_state, dict):
                            pool_state["refreshing"] = True
                            pool_state["refreshing_ts"] = int(now_ms)
                    except Exception:
                        pass
            except Exception:
                candidates = []

        gate = ({} if not isinstance(eff, dict) else (eff.get("gate") or {}))
        if isinstance(gate, dict) and (not bool(gate.get("enabled_effective", True))):
            for x in candidates:
                if isinstance(x, dict):
                    x["vetoed"] = True
                    if not x.get("veto_reason"):
                        x["veto_reason"] = "module_paused"

        for x in candidates:
            if not isinstance(x, dict):
                continue
            try:
                if str(x.get("carry_side") or "").strip().lower() == "long":
                    x["vetoed"] = True
                    if not x.get("veto_reason"):
                        x["veto_reason"] = "long_carry_not_supported"
            except Exception:
                continue

        try:
            corr_thr = float((eff.get("cfg_effective") or {}).get("carry_trade_corr_threshold", (svc.CONFIG or {}).get("carry_trade_corr_threshold", 0.80)) or 0.80)
        except Exception:
            corr_thr = 0.80
        corr_thr = float(svc._clip(float(corr_thr), 0.0, 1.0))
        corr_hit = False
        for x in candidates:
            try:
                if bool(x.get("vetoed")):
                    continue
                cm = x.get("corr_max_abs")
                if cm is not None and math.isfinite(float(cm)) and float(cm) >= float(corr_thr):
                    corr_hit = True
                    break
            except Exception:
                continue
        recommended_open_top_k = None
        try:
            base_k = int((eff.get("cfg_effective") or {}).get("carry_trade_open_top_k", (svc.CONFIG or {}).get("carry_trade_open_top_k", 1)) or 1)
            recommended_open_top_k = int(max(1, 1 if corr_hit else base_k))
        except Exception:
            recommended_open_top_k = None

        try:
            with svc.CARRY_UNIVERSE_LOCK:
                coins0 = svc.CARRY_UNIVERSE_STATE.get("coins") if isinstance(getattr(svc, "CARRY_UNIVERSE_STATE", None), dict) else None
                n0 = int(len(coins0)) if isinstance(coins0, list) else 0
                universe_state = {
                    "ok": True,
                    "ts": int(svc.CARRY_UNIVERSE_STATE.get("ts") or 0),
                    "venue": str(svc.CARRY_UNIVERSE_STATE.get("venue") or str(venue_eff)),
                    "n": int(n0),
                    "last_error": (
                        None
                        if svc.CARRY_UNIVERSE_STATE.get("last_error") is None
                        else dict(svc.CARRY_UNIVERSE_STATE.get("last_error"))
                        if isinstance(svc.CARRY_UNIVERSE_STATE.get("last_error"), dict)
                        else {"raw": svc.CARRY_UNIVERSE_STATE.get("last_error")}
                    ),
                }
        except Exception as e:
            universe_state = {"ok": False, "error": str(e)}

        return jsonify(
            {
                "ok": True,
                "ts": int(now_ms),
                "venue": str(clk.get("venue") or venue_eff),
                "n": int(n),
                "cache": cache_info,
                "pool": pool_state,
                "universe": universe_state,
                "refresh_scheduled": bool(refresh_scheduled),
                "next_funding_ts": int(clk.get("next_ts") or 0),
                "minutes_to_funding": float(minutes_to_next),
                "window_state": str(ws),
                "profile": (None if not isinstance(eff, dict) else str(eff.get("profile") or "")),
                "regime": ({} if not isinstance(eff, dict) else (eff.get("regime") or {})),
                "gate": gate,
                "cfg_effective": ({} if not isinstance(eff, dict) else (eff.get("cfg_effective") or {})),
                "recommended_open_top_k": recommended_open_top_k,
                "candidates": candidates,
            }
        )

    @app.route("/carry/acceptance", methods=["GET"], endpoint="carry__acceptance")
    def carry_acceptance():
        now_ms = int(svc._now_ms())
        req_venue = request.args.get("venue")
        if req_venue is not None:
            vv = str(req_venue or "").strip().lower()
            if vv not in ("", "hyperliquid", "hl"):
                return jsonify({"ok": False, "error": "venue_hl_only", "got": vv}), 400
        venue_eff = "hyperliquid"

        try:
            lb = int(request.args.get("lookback_days") or 90)
        except Exception:
            lb = 90
        lb = max(7, min(3650, int(lb)))

        eff = svc._carry_cfg_effective(int(now_ms), venue=str(venue_eff))
        cfg_eff = (eff.get("cfg_effective") if isinstance(eff, dict) else None)
        cfg_eff = (cfg_eff if isinstance(cfg_eff, dict) else {})
        out = svc._carry_acceptance_report(int(now_ms), venue=str(venue_eff), lookback_days=int(lb), cfg=dict(cfg_eff))
        return jsonify(out)

    @app.route("/carry/universe", methods=["GET"], endpoint="carry__universe")
    def carry_universe():
        now_ms = int(svc._now_ms())
        venue_eff = "hyperliquid"
        eff = svc._carry_cfg_effective(int(now_ms), venue=str(venue_eff))
        cfg_eff = (eff.get("cfg_effective") if isinstance(eff, dict) else None)
        cfg_eff = (cfg_eff if isinstance(cfg_eff, dict) else {})

        refresh_q = request.args.get("refresh")
        refresh = False
        if refresh_q is not None:
            v = str(refresh_q).strip().lower()
            refresh = v in ("1", "true", "yes", "on")

        refresh_out = None
        try:
            if bool(refresh):
                refresh_out = svc._carry_universe_refresh(int(now_ms), dict(cfg_eff), force=True)
        except Exception as e:
            refresh_out = {"ok": False, "error": str(e)}

        view: Dict[str, Any] = {"ok": True, "ts": int(now_ms), "venue": str(venue_eff)}
        try:
            with svc.CARRY_UNIVERSE_LOCK:
                coins0 = svc.CARRY_UNIVERSE_STATE.get("coins") if isinstance(svc.CARRY_UNIVERSE_STATE, dict) else None
                meta0 = svc.CARRY_UNIVERSE_STATE.get("metadata") if isinstance(svc.CARRY_UNIVERSE_STATE, dict) else None
                n0 = int(len(coins0)) if isinstance(coins0, list) else 0
                view["state"] = {
                    "ts": int(svc.CARRY_UNIVERSE_STATE.get("ts") or 0),
                    "venue": str(svc.CARRY_UNIVERSE_STATE.get("venue") or "hyperliquid"),
                    "n": int(n0),
                    "coins": (list(coins0) if isinstance(coins0, list) else []),
                    "metadata": (dict(meta0) if isinstance(meta0, dict) else {}),
                    "last_error": (
                        None
                        if svc.CARRY_UNIVERSE_STATE.get("last_error") is None
                        else dict(svc.CARRY_UNIVERSE_STATE.get("last_error"))
                        if isinstance(svc.CARRY_UNIVERSE_STATE.get("last_error"), dict)
                        else {"raw": svc.CARRY_UNIVERSE_STATE.get("last_error")}
                    ),
                }
        except Exception as e:
            view["state"] = {"ok": False, "error": str(e)}

        view["cfg_effective"] = {k: v for k, v in dict(cfg_eff).items() if str(k).startswith("carry_universe_")}
        if refresh_out is not None:
            view["refresh"] = refresh_out
        return jsonify(view)

    @app.route("/carry/config", methods=["POST"], endpoint="carry__config_set")
    def carry_config_set():
        if not svc._governance_write_auth_ok():
            return jsonify({"ok": False, "error": "config_forbidden"}), 403

        raw = request.get_json(force=True) or {}
        if not isinstance(raw, dict):
            return jsonify({"ok": False, "error": "bad_payload"}), 400

        data: Dict[str, Any] = {}
        for k, v in raw.items():
            kk = str(k or "").strip()
            if (not kk.startswith("carry_trade_")) and (not kk.startswith("carry_universe_")):
                continue
            if kk not in (svc.CONFIG or {}):
                continue
            if kk == "carry_trade_venue":
                vv = str(v or "").strip().lower()
                if vv not in ("", "hyperliquid", "hl"):
                    return jsonify({"ok": False, "error": "carry_trade_venue_hl_only", "got": vv}), 400
                data[kk] = "hyperliquid"
                continue
            data[kk] = v

        out, code = svc._config_set_impl(data, confirm_live=False)
        if int(code) != 200 or not isinstance(out, dict) or not bool(out.get("ok")):
            return jsonify(out), int(code)
        changed = {k: (svc.CONFIG or {}).get(k) for k in data.keys()}
        return (
            jsonify(
                {
                    "ok": True,
                    "changed": changed,
                    "config": {k: (svc.CONFIG or {}).get(k) for k in (svc.CONFIG or {}).keys() if str(k).startswith("carry_trade_") or str(k).startswith("carry_universe_")},
                }
            ),
            200,
        )

    @app.route("/carry/hyperliquid/sync_open", methods=["POST"], endpoint="carry__hyperliquid_sync_open")
    def carry_hyperliquid_sync_open():
        data = request.get_json(force=True) or {}
        if not isinstance(data, dict):
            return jsonify({"ok": False, "error": "bad_payload"}), 400

        def _final(resp: Dict[str, Any], http_status: int):
            try:
                svc._execute_idempotency_finalize(data, resp, int(http_status))
            except Exception:
                pass
            return jsonify(resp), int(http_status)

        idem = svc._execute_idempotency_precheck(data)
        if idem is not None:
            return idem

        guard = svc._check_execute_guard(data)
        if guard is not None:
            return guard

        coin = str(data.get("coin") or data.get("pair") or "BTC")
        coin = svc._hl_coin_from_pair(coin)

        execute = bool(data.get("execute", False))
        if bool(execute) and (not svc._governance_write_auth_ok()):
            return _final({"ok": False, "error": "config_forbidden"}, 403)

        try:
            notional_perp = float(
                data.get("perp_notional_usdc")
                if data.get("perp_notional_usdc") is not None
                else (data.get("notional_perp_usdc") if data.get("notional_perp_usdc") is not None else 100.0)
            )
        except Exception:
            notional_perp = 100.0
        try:
            notional_spot = float(
                data.get("spot_notional_usdc")
                if data.get("spot_notional_usdc") is not None
                else (data.get("notional_spot_usdc") if data.get("notional_spot_usdc") is not None else 100.0)
            )
        except Exception:
            notional_spot = 100.0
        if (not math.isfinite(float(notional_perp))) or float(notional_perp) <= 0.0:
            return _final({"ok": False, "error": "invalid_perp_notional"}, 400)
        if (not math.isfinite(float(notional_spot))) or float(notional_spot) <= 0.0:
            return _final({"ok": False, "error": "invalid_spot_notional"}, 400)

        try:
            leverage = int(data.get("leverage") if data.get("leverage") is not None else ((svc.CONFIG or {}).get("hl_default_leverage", 3) or 3))
        except Exception:
            leverage = 3
        leverage = max(1, min(100, int(leverage)))

        lev_out = None
        try:
            lev_out = svc.hyperliquid_set_leverage_internal(coin=str(coin), leverage=int(leverage), execute=bool(execute), strategy_id="CarryTrade", ab_owner="carry")
            lev_out, _ = svc._unpack_jsonify_resp(lev_out)
        except Exception:
            lev_out = None

        perp_resp, perp_code = {}, 200
        spot_resp, spot_code = {}, 200

        try:
            spot_resp, spot_code = svc._unpack_jsonify_resp(
                svc.hyperliquid_spot_market_open_internal(
                    coin=str(coin),
                    side="buy",
                    notional_usdc=float(notional_spot),
                    execute=bool(execute),
                    tag="carry_sync_open_spot",
                    strategy_id="CarryTrade",
                    ab_owner="carry",
                )
            )
        except Exception as e:
            spot_resp, spot_code = {"ok": False, "error": str(e)}, 500

        ok_spot = bool(isinstance(spot_resp, dict) and spot_resp.get("ok", True) and int(spot_code) < 400)
        if bool(ok_spot):
            pf = None
            try:
                od = spot_resp.get("order") if isinstance(spot_resp, dict) else None
                ex0 = (od.get("exec") if isinstance(od, dict) and isinstance(od.get("exec"), dict) else None)
                if isinstance(ex0, dict):
                    pf = ex0.get("preflight_error") if ex0.get("preflight_error") is not None else ex0.get("error")
            except Exception:
                pf = None
            if pf is not None:
                ok_spot = False
        rollback: Dict[str, Any] = {"ok": True, "did": False}
        if not bool(ok_spot):
            return _final(
                {
                    "ok": False,
                    "ts": int(svc._now_ms()),
                    "venue": "hyperliquid",
                    "execute": bool(execute),
                    "coin": str(coin),
                    "perp_notional_usdc": float(notional_perp),
                    "spot_notional_usdc": float(notional_spot),
                    "leverage": int(leverage),
                    "leverage_resp": lev_out,
                    "perp": {"http": int(perp_code), "resp": perp_resp},
                    "spot": {"http": int(spot_code), "resp": spot_resp},
                    "rollback": rollback,
                },
                502,
            )

        try:
            perp_resp, perp_code = svc._unpack_jsonify_resp(
                svc.hyperliquid_market_open_internal(
                    coin=str(coin),
                    side="sell",
                    notional_usdc=float(notional_perp),
                    execute=bool(execute),
                    tag="carry_sync_open_perp",
                    strategy_id="CarryTrade",
                    ab_owner="carry",
                )
            )
        except Exception as e:
            perp_resp, perp_code = {"ok": False, "error": str(e)}, 500

        ok_perp = bool(isinstance(perp_resp, dict) and perp_resp.get("ok", True) and int(perp_code) < 400)
        if bool(execute) and (not bool(ok_perp)):
            rollback = {"ok": False, "did": False, "skipped": True}
            qty = None
            try:
                od = spot_resp.get("order") if isinstance(spot_resp, dict) else None
                if isinstance(od, dict):
                    if od.get("executedQty") is not None:
                        qty = float(svc._to_float(od.get("executedQty"), 0.0))
                    if qty is None and (od.get("exec") is not None or od.get("sz") is not None):
                        ex0 = od.get("exec") if isinstance(od.get("exec"), dict) else od
                        if isinstance(ex0, dict) and ex0.get("sz") is not None:
                            qty = float(svc._to_float(ex0.get("sz"), 0.0))
            except Exception:
                qty = None
            if qty is not None and math.isfinite(float(qty)) and float(qty) > 0.0:
                try:
                    r, c = svc._unpack_jsonify_resp(
                        svc.hyperliquid_spot_market_close_internal(
                            coin=str(coin),
                            qty=float(qty),
                            execute=True,
                            tag="carry_sync_open_rollback_spot",
                            strategy_id="CarryTrade",
                            ab_owner="carry",
                        )
                    )
                    rollback = {"ok": bool(int(c) < 400), "did": True, "spot": {"http": int(c), "resp": r}}
                except Exception as e:
                    rollback = {"ok": False, "did": False, "error": str(e)}

        return _final(
            {
                "ok": bool(ok_perp and ok_spot),
                "ts": int(svc._now_ms()),
                "venue": "hyperliquid",
                "execute": bool(execute),
                "coin": str(coin),
                "perp_notional_usdc": float(notional_perp),
                "spot_notional_usdc": float(notional_spot),
                "leverage": int(leverage),
                "leverage_resp": lev_out,
                "perp": {"http": int(perp_code), "resp": perp_resp},
                "spot": {"http": int(spot_code), "resp": spot_resp},
                "rollback": rollback,
            },
            200 if bool(ok_perp and ok_spot) else 502,
        )

    @app.route("/funding/schedule", methods=["GET"], endpoint="carry__funding_schedule")
    def funding_schedule():
        now_ms = int(svc._now_ms())
        req_venue = request.args.get("venue")
        if req_venue is not None:
            vv = str(req_venue or "").strip().lower()
            if vv not in ("", "hyperliquid", "hl"):
                return jsonify({"ok": False, "error": "venue_hl_only", "got": vv}), 400
        venue = "hyperliquid"
        try:
            n = int(request.args.get("n") or 8)
        except Exception:
            n = 8
        n = max(1, min(48, int(n)))

        next_ts, period_ms = svc._carry_funding_schedule_hl(int(now_ms))
        sched = [int(next_ts) + int(i) * int(period_ms) for i in range(int(n))]
        return jsonify({"ok": True, "ts": int(now_ms), "venue": str(venue), "period_ms": int(period_ms), "schedule": sched})

    @app.route("/funding/rates", methods=["GET"], endpoint="carry__funding_rates")
    def funding_rates():
        now_ms = int(svc._now_ms())
        req_venue = request.args.get("venue")
        if req_venue is not None:
            vv = str(req_venue or "").strip().lower()
            if vv not in ("", "hyperliquid", "hl"):
                return jsonify({"ok": False, "error": "venue_hl_only", "got": vv}), 400
        venue = "hyperliquid"
        try:
            limit = int(request.args.get("limit") or 0)
        except Exception:
            limit = 0
        limit = max(0, min(500, int(limit)))

        key_mode = str(request.args.get("key") or "pair").strip().lower() or "pair"
        if key_mode not in ("pair", "coin"):
            key_mode = "pair"

        rates: Dict[str, Dict[str, Any]] = {}
        next_ts = 0
        minutes_to = 0.0
        coins_order: List[str] = []
        period_ms = 0

        try:
            next_ts, period_ms = svc._carry_funding_schedule_hl(int(now_ms))
        except Exception:
            next_ts, period_ms = 0, 0
        try:
            if int(next_ts) > 0:
                minutes_to = (float(int(next_ts) - int(now_ms))) / 60_000.0
        except Exception:
            minutes_to = 0.0

        ctxs = svc._hl_meta_and_asset_ctxs_cached(int(now_ms))
        items: List[Tuple[str, Dict[str, Any]]] = []
        for coin, ctx in (ctxs or {}).items():
            if not isinstance(ctx, dict):
                continue
            items.append((str(coin).upper(), ctx))
        items.sort(key=lambda x: abs(float(svc._to_float((x[1] or {}).get("funding"), 0.0))), reverse=True)
        if limit > 0:
            items = items[:limit]

        for coin, ctx in items:
            coins_order.append(str(coin).upper())
            try:
                fr = float(ctx.get("funding") or 0.0)
            except Exception:
                fr = 0.0
            mark_px = float(svc._to_float(ctx.get("markPx"), 0.0))
            oracle_px = float(svc._to_float(ctx.get("oraclePx"), 0.0))
            prem = float(svc._to_float(ctx.get("premium"), 0.0))
            basis_bps = 0.0
            if mark_px > 0.0 and oracle_px > 0.0:
                basis_bps = (mark_px / oracle_px - 1.0) * 10_000.0
            elif prem != 0.0:
                basis_bps = float(prem) * 10_000.0
            rates[coin] = {
                "funding_rate": float(fr),
                "funding_period_ms": (int(period_ms) if int(period_ms) > 0 else None),
                "funding_rate_1h": (
                    None
                    if int(period_ms) <= 0
                    else (float(fr) / (float(int(period_ms)) / 3_600_000.0))
                    if float(int(period_ms)) > 0.0
                    else None
                ),
                "funding_rate_apr": (
                    None
                    if int(period_ms) <= 0
                    else ((float(fr) / (float(int(period_ms)) / 3_600_000.0)) * 24.0 * 365.0)
                    if float(int(period_ms)) > 0.0
                    else None
                ),
                "next_funding_ts": int(next_ts) if int(next_ts) > 0 else None,
                "minutes_to_funding": float(minutes_to),
                "mark_price": (float(mark_px) if float(mark_px) > 0 else None),
                "index_price": (float(oracle_px) if float(oracle_px) > 0 else None),
                "basis_bps": float(basis_bps),
                "ts": int(now_ms),
            }

        rates_by_coin: Dict[str, Dict[str, Any]] = dict(rates)
        rates_by_pair: Dict[str, Dict[str, Any]] = {}
        for coin, it in list(rates_by_coin.items()):
            c = str(coin).upper()
            pair = c + "-PERP"
            item = dict(it) if isinstance(it, dict) else {"raw": it}
            if "coin" not in item:
                item["coin"] = c
            if "pair" not in item:
                item["pair"] = pair
            rates_by_pair[pair] = item

        rates_out = rates_by_pair if key_mode == "pair" else rates_by_coin

        try:
            arch_lim = int((svc.CONFIG or {}).get("funding_archive_limit", 200) or 200)
        except Exception:
            arch_lim = 200
        arch_lim = max(1, min(500, int(arch_lim)))
        if limit > 0:
            arch_lim = min(int(arch_lim), int(limit))
        arch_coins = list(coins_order) if coins_order else [str(x).upper() for x in list(rates_by_coin.keys())]
        arch_coins = arch_coins[: int(arch_lim)]
        arch_rates_by_pair: Dict[str, Dict[str, Any]] = {}
        for c in arch_coins:
            it = rates_by_coin.get(str(c).upper())
            if not isinstance(it, dict):
                continue
            pair = str(c).upper() + "-PERP"
            item = dict(it)
            item["coin"] = str(c).upper()
            item["pair"] = pair
            arch_rates_by_pair[pair] = item
        try:
            svc._archive_funding_rates_snapshot(
                {
                    "ts": int(now_ms),
                    "venue": str(venue),
                    "period_ms": (int(period_ms) if int(period_ms) > 0 else None),
                    "next_funding_ts": (int(next_ts) if int(next_ts) > 0 else None),
                    "minutes_to_funding": float(minutes_to),
                    "n": int(len(arch_rates_by_pair)),
                    "rates": arch_rates_by_pair,
                }
            )
        except Exception:
            pass

        payload: Dict[str, Any] = {
            "ok": True,
            "ts": int(now_ms),
            "venue": str(venue),
            "period_ms": (int(period_ms) if int(period_ms) > 0 else None),
            "next_funding_ts": (int(next_ts) if int(next_ts) > 0 else None),
            "minutes_to_funding": float(minutes_to),
            "key_mode": str(key_mode),
            "rates": rates_out,
        }
        if key_mode == "pair":
            payload["rates_by_coin"] = rates_by_coin
        else:
            payload["rates_by_pair"] = rates_by_pair
        return jsonify(payload)

    try:
        setattr(svc, "_CARRY_ROUTES_REGISTERED", True)
    except Exception:
        pass


def create_standalone_app() -> Flask:
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "ts": int(_now_ms_fallback())})

    return app

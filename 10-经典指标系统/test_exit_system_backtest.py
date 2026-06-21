import unittest

import ml_trade_service as svc


class TestExitSystemBacktest(unittest.TestCase):
    def setUp(self) -> None:
        svc.TRACKER_STATE["gate_history"] = []
        svc.TRACKER_STATE["open_positions"] = {}
        svc.TRACKER_STATE["carry_open_positions"] = {}
        svc.TRACKER_STATE["quant_open_positions"] = {}
        svc.TRACKER_STATE["three_screen_open_positions"] = {}
        svc.TRACKER_STATE["exit_snapshots"] = {}
        svc.TRACKER_STATE["exit_inflight"] = {}

        svc.CONFIG["exit_observe_enabled"] = False
        svc.CONFIG["exit_macro_flow_enabled"] = False
        svc.CONFIG["macro_gate_enabled"] = False

        svc.CONFIG["exit_shadow_mode"] = True
        svc.CONFIG["execution_venue"] = "hyperliquid"

        svc.CONFIG["exit_l0_max_hold_sec"] = 3600
        svc.CONFIG["exit_l0_max_unrealized_loss_pct"] = -0.05
        svc.CONFIG["exit_l0_weekly_reversal_enabled"] = False
        svc.CONFIG["exit_l0_weekly_reversal_stop_enabled"] = False

        svc.CONFIG["exit_risk_gate_enabled"] = True
        svc.CONFIG["exit_risk_gate_long_thr"] = 0.50
        svc.CONFIG["exit_risk_gate_short_thr"] = 0.40
        svc.CONFIG["exit_risk_gate_confirm_n"] = 1
        svc.CONFIG["exit_risk_gate_confirm_window_m"] = 0
        svc.CONFIG["exit_risk_gate_cooldown_min"] = 0
        svc.CONFIG["exit_risk_gate_reduce_frac"] = 0.40
        svc.CONFIG["exit_risk_gate_min_hold_sec"] = 0

        svc.CONFIG["exit_l1_enabled"] = True
        svc.CONFIG["exit_l1_mode"] = "heuristic"
        svc.CONFIG["exit_l1_hysteresis_n"] = 1
        svc.CONFIG["exit_l1_action_cooldown_sec"] = 0
        svc.CONFIG["exit_l1_close_cooldown_sec"] = 0
        svc.CONFIG["exit_l1_reduce_cooldown_sec"] = 0
        svc.CONFIG["exit_l1_hold_risk_close_threshold"] = 0.99
        svc.CONFIG["exit_l1_hold_risk_reduce_threshold"] = 0.99

        svc.CONFIG["exit_l2_take_profit_pct"] = 0.04
        svc.CONFIG["exit_l2_trailing_retrace_pct"] = 0.35
        svc.CONFIG["exit_l2_reduce_frac"] = 0.50

        self._orig_exit_gate_should_take = svc._exit_gate_should_take
        self._orig_exit_hold_risk_score = svc._exit_hold_risk_score
        self._orig_exit_build_position_snapshot = svc._exit_build_position_snapshot
        self._orig_hl_market_close = svc.hyperliquid_market_close_internal
        self._orig_aster_market_close = svc.aster_market_close_internal

        svc._exit_gate_should_take = lambda **kwargs: (1.0, True, "test")
        self._hold_risk = 0.05
        svc._exit_hold_risk_score = lambda **kwargs: float(self._hold_risk)
        svc._exit_build_position_snapshot = (
            lambda pair, pos, now_ms: dict((pos or {}).get("exit_snapshot") or {"dd": 0.0, "atr_pct": 0.01})
        )
        svc.hyperliquid_market_close_internal = lambda **kwargs: {}
        svc.aster_market_close_internal = lambda **kwargs: {}

    def tearDown(self) -> None:
        svc._exit_gate_should_take = self._orig_exit_gate_should_take
        svc._exit_hold_risk_score = self._orig_exit_hold_risk_score
        svc._exit_build_position_snapshot = self._orig_exit_build_position_snapshot
        svc.hyperliquid_market_close_internal = self._orig_hl_market_close
        svc.aster_market_close_internal = self._orig_aster_market_close

    def _run_tick(self, now_ms: int, pos: dict) -> dict:
        pair = str(pos.get("pair") or "BTC-PERP")
        svc.TRACKER_STATE["open_positions"] = {pair: dict(pos)}
        return svc._exit_pipeline_tick(now_ms=int(now_ms), execute=False)

    def _latest_reason(self) -> str:
        gh = svc.TRACKER_STATE.get("gate_history")
        if not isinstance(gh, list) or not gh:
            return ""
        last = gh[-1]
        if not isinstance(last, dict):
            return ""
        return str(last.get("reason") or "")

    def _latest_action(self) -> str:
        gh = svc.TRACKER_STATE.get("gate_history")
        if not isinstance(gh, list) or not gh:
            return ""
        last = gh[-1]
        if not isinstance(last, dict):
            return ""
        return str(last.get("action") or "")

    def test_l0_max_hold_close(self) -> None:
        now_ms = 1_700_000_000_000
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms - 3_601_000,
                "unrealized_pnl_pct": -0.01,
                "hl_unrealized_pnl_u": -1.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "close")
        self.assertEqual(self._latest_reason(), "exit_l0:l0_max_hold:close")

    def test_l0_stop_loss_close(self) -> None:
        now_ms = 1_700_000_000_000
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": -0.06,
                "hl_unrealized_pnl_u": -6.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "close")
        self.assertEqual(self._latest_reason(), "exit_l0:l0_stop_loss:close")

    def test_l0_risk_gate_reduce(self) -> None:
        now_ms = 1_700_000_000_000
        svc.CONFIG["exit_l0_max_unrealized_loss_pct"] = -0.20
        self._hold_risk = 0.95
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": -0.01,
                "hl_unrealized_pnl_u": -1.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.10, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "reduce")
        self.assertEqual(self._latest_reason(), "exit_l0:l0_risk_gate_reduce:reduce")

    def test_l1_take_profit_reduce(self) -> None:
        now_ms = 1_700_000_000_000
        svc.CONFIG["exit_risk_gate_enabled"] = False
        svc.CONFIG["exit_l0_max_unrealized_loss_pct"] = -0.20
        self._hold_risk = 0.05
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.05,
                "hl_unrealized_pnl_u": 5.0,
                "mfe_pnl_u": 6.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.10, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "reduce")
        self.assertEqual(self._latest_reason(), "exit_exit_feeder:l1_take_profit_reduce:reduce")

    def test_l1_trailing_close(self) -> None:
        now_ms = 1_700_000_000_000
        svc.CONFIG["exit_risk_gate_enabled"] = False
        svc.CONFIG["exit_l0_max_unrealized_loss_pct"] = -0.20
        self._hold_risk = 0.05
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.06,
                "hl_unrealized_pnl_u": 6.0,
                "mfe_pnl_u": 8.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.60, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "close")
        self.assertEqual(self._latest_reason(), "exit_exit_feeder:l1_trailing_close:close")

    def test_l1_hold_risk_close(self) -> None:
        now_ms = 1_700_000_000_000
        svc.CONFIG["exit_risk_gate_enabled"] = False
        svc.CONFIG["exit_l0_max_unrealized_loss_pct"] = -0.20
        svc.CONFIG["exit_l1_hold_risk_close_threshold"] = 0.10
        svc.CONFIG["exit_l1_hold_risk_close_enter_threshold"] = 0.10
        svc.CONFIG["exit_l1_hold_risk_close_deadband"] = 0.0
        svc.CONFIG["exit_l1_hold_risk_reduce_threshold"] = 0.0
        svc.CONFIG["exit_l1_hold_risk_reduce_enter_threshold"] = 0.0
        svc.CONFIG["exit_l1_hold_risk_reduce_deadband"] = 0.0
        svc.CONFIG["exit_l1_reduce_min_profit_pct"] = 0.05
        self._hold_risk = 0.95
        out = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "BTC-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "hl_szi": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.0,
                "hl_unrealized_pnl_u": 0.0,
                "mfe_pnl_u": 0.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(self._latest_action(), "close")
        self.assertEqual(self._latest_reason(), "exit_exit_feeder:l1_hold_risk_close:close")

    def test_exit_inflight_not_set_when_reduce_size_zero(self) -> None:
        now_ms = 1_700_000_000_000
        svc.TRACKER_STATE["exit_inflight"] = {}
        out = svc._exit_execute_action(
            pair="PENDLE-PERP",
            pos={
                "pair": "PENDLE-PERP",
                "side": "long",
                "exit_owner": "exit_feeder",
                "venue": "hyperliquid",
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.05,
                "hl_unrealized_pnl_u": 5.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
            dec={"action": "reduce", "reason": "exit_exit_feeder:l1_take_profit_reduce:reduce", "reduce_frac": 0.25},
            now_ms=int(now_ms),
            execute=True,
            owner="exit_feeder",
        )
        self.assertIsNone(out)

    def test_exit_pipeline_skips_quant_positions(self) -> None:
        now_ms = 1_700_000_000_000

        out1 = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "DOGE-PERP",
                "side": "long",
                "system_id": "quant",
                "strategy_id": "quant_any",
                "exit_owner": "exit_feeder",
                "venue": "aster",
                "notional_usdc": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.10,
                "aster_unrealized_pnl_u": 10.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out1.get("ok")))
        self.assertEqual(len(svc.TRACKER_STATE.get("gate_history") or []), 0)

        out2 = self._run_tick(
            now_ms=now_ms,
            pos={
                "pair": "DOGE-PERP",
                "side": "long",
                "strategy_id": "quant_any",
                "exit_owner": "exit_feeder",
                "venue": "aster",
                "notional_usdc": 100.0,
                "entry_ts": now_ms,
                "unrealized_pnl_pct": 0.10,
                "aster_unrealized_pnl_u": 10.0,
                "exit_snapshot_ts": now_ms,
                "exit_snapshot": {"dd": 0.0, "atr_pct": 0.01},
            },
        )
        self.assertTrue(bool(out2.get("ok")))
        self.assertEqual(len(svc.TRACKER_STATE.get("gate_history") or []), 0)


class TestQuantPairsBtcethPnlExit(unittest.TestCase):
    def setUp(self) -> None:
        svc.TRACKER_STATE["quant_open_positions"] = {}
        svc.TRACKER_STATE.pop(svc._quant_pairs_pnl_track_key("btceth"), None)

    def test_z_exit_blocked_before_min_hold_bars(self) -> None:
        params = {
            "exit_pnl_enabled": True,
            "pnl_min_hold_bars": 10,
            "pnl_min_on_z_exit_r": 0.0,
        }
        position = {
            "ok": True,
            "any": True,
            "pair_ok": True,
            "entry_ts": 123,
            "hold_bars": 1,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "eth": {"notional_usdc": 100.0},
            },
        }
        pnl = {
            "ok": True,
            "net_est_usdc": 2.0,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "eth": {"notional_usdc": 100.0},
            },
        }
        out = svc._quant_pairs_apply_pnl_exit(
            action="exit",
            reason="z_exit",
            params=params,
            position_pack=position,
            pnl_pack=pnl,
            zf=0.0,
            exit_z_eff=0.5,
            track_key=svc._quant_pairs_pnl_track_key("btceth"),
            now_ms=1_700_000_000_000,
        )
        self.assertEqual(str(out.get("action")), "hold")
        self.assertEqual(str(out.get("reason")), "z_exit_before_min_hold")

    def test_z_exit_blocked_when_pnl_below_min(self) -> None:
        params = {
            "exit_pnl_enabled": True,
            "pnl_min_hold_bars": 0,
            "pnl_min_on_z_exit_r": 0.01,
        }
        position = {
            "ok": True,
            "any": True,
            "pair_ok": True,
            "entry_ts": 123,
            "hold_bars": 10,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "eth": {"notional_usdc": 100.0},
            },
        }
        pnl = {
            "ok": True,
            "net_est_usdc": 0.0,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "eth": {"notional_usdc": 100.0},
            },
        }
        out = svc._quant_pairs_apply_pnl_exit(
            action="exit",
            reason="z_exit",
            params=params,
            position_pack=position,
            pnl_pack=pnl,
            zf=0.0,
            exit_z_eff=0.5,
            track_key=svc._quant_pairs_pnl_track_key("btceth"),
            now_ms=1_700_000_000_000,
        )
        self.assertEqual(str(out.get("action")), "hold")
        self.assertEqual(str(out.get("reason")), "z_exit_pnl_below_min")

    def test_btcalt_z_exit_blocked_before_min_hold_bars(self) -> None:
        params = {
            "exit_pnl_enabled": True,
            "pnl_min_hold_bars": 10,
            "pnl_min_on_z_exit_r": 0.0,
        }
        position = {
            "ok": True,
            "any": True,
            "pair_ok": True,
            "entry_ts": 123,
            "hold_bars": 1,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "alt": {"notional_usdc": 100.0},
            },
        }
        pnl = {
            "ok": True,
            "net_est_usdc": 2.0,
            "legs": {
                "btc": {"notional_usdc": 100.0},
                "alt": {"notional_usdc": 100.0},
            },
        }
        out = svc._quant_pairs_apply_pnl_exit(
            action="exit",
            reason="z_exit",
            params=params,
            position_pack=position,
            pnl_pack=pnl,
            zf=0.0,
            exit_z_eff=0.5,
            track_key=svc._quant_pairs_pnl_track_key("btcalt", alt="SOL"),
            now_ms=1_700_000_000_000,
        )
        self.assertEqual(str(out.get("action")), "hold")
        self.assertEqual(str(out.get("reason")), "z_exit_before_min_hold")

    def test_pairs_btcalt_close_retries_failed_leg(self) -> None:
        svc.TRACKER_STATE["quant_open_positions"] = {
            "BTC-PERP": {"pair": "BTC-PERP", "side": "short", "strategy_id": "quant_pairs_btcalt", "tag": "t|g", "pair_group": "g", "alt": "SOL", "base_sz": 1.0},
            "SOL-PERP": {"pair": "SOL-PERP", "side": "long", "strategy_id": "quant_pairs_btcalt", "tag": "t|g", "pair_group": "g", "alt": "SOL", "base_sz": 1.0},
        }
        svc.TRACKER_STATE["open_positions"] = {
            "BTC-PERP": {"pair": "BTC-PERP", "side": "short", "notional_usdc": 100.0},
            "SOL-PERP": {"pair": "SOL-PERP", "side": "long", "notional_usdc": 100.0},
        }

        calls = []
        per_coin = {"BTC": 0, "SOL": 0}
        orig_close_leg = svc._pairs_btceth_close_leg
        try:
            def _fake_close_leg(**kwargs):
                coin = str(kwargs.get("coin") or "").strip().upper()
                per_coin[coin] = int(per_coin.get(coin, 0)) + 1
                calls.append({"coin": coin, "tag": kwargs.get("tag")})
                if coin == "SOL" and per_coin[coin] == 1:
                    return ({"ok": False, "error": "temporary"}, None)
                if coin == "BTC":
                    svc.TRACKER_STATE["open_positions"].pop("BTC-PERP", None)
                    svc.TRACKER_STATE["quant_open_positions"].pop("BTC-PERP", None)
                if coin == "SOL":
                    svc.TRACKER_STATE["open_positions"].pop("SOL-PERP", None)
                    svc.TRACKER_STATE["quant_open_positions"].pop("SOL-PERP", None)
                return ({"ok": True, "order": {"status": "filled"}}, None)

            svc._pairs_btceth_close_leg = _fake_close_leg

            with svc.app.test_request_context(
                "/execution/pairs/btcalt/market_close",
                method="POST",
                json={"venue": "hyperliquid", "execute": False, "confirm_execute": True, "tag": "t", "alt": "SOL"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ):
                out = svc.execution_pairs_btcalt_market_close()
            resp = out[0] if isinstance(out, tuple) else out
            data = resp.get_json(silent=True)
            self.assertTrue(bool(data.get("ok")))
            self.assertEqual(int(per_coin.get("BTC")), 1)
            self.assertEqual(int(per_coin.get("SOL")), 2)
            self.assertTrue(isinstance(data.get("retry"), dict))
            self.assertTrue(isinstance((data.get("retry") or {}).get("alt"), dict))
        finally:
            svc._pairs_btceth_close_leg = orig_close_leg

    def test_pairs_btcalt_close_rolls_back_when_one_leg_still_open(self) -> None:
        now_ms = 1_700_000_000_000
        svc.CONFIG["execution_venue"] = "hyperliquid"
        svc.TRACKER_STATE["open_positions"] = {
            "BTC-PERP": {"pair": "BTC-PERP", "side": "short", "notional_usdc": 100.0, "entry_ts": now_ms},
            "SOL-PERP": {"pair": "SOL-PERP", "side": "long", "notional_usdc": 100.0, "entry_ts": now_ms},
        }
        svc.TRACKER_STATE["quant_open_positions"] = {
            "BTC-PERP": {"pair": "BTC-PERP", "side": "short", "strategy_id": "quant_pairs_btcalt", "tag": "t|g", "pair_group": "g", "alt": "SOL", "notional_usdc": 100.0, "base_sz": 1.0},
            "SOL-PERP": {"pair": "SOL-PERP", "side": "long", "strategy_id": "quant_pairs_btcalt", "tag": "t|g", "pair_group": "g", "alt": "SOL", "notional_usdc": 100.0, "base_sz": 1.0},
        }

        orig_close_leg = svc._pairs_btceth_close_leg
        orig_open_leg = svc._pairs_quant_open_leg
        orig_hl_sync = svc._hl_sync_record

        try:
            per_coin = {"BTC": 0, "SOL": 0}

            def _fake_close_leg(**kwargs):
                coin = str(kwargs.get("coin") or "").strip().upper()
                per_coin[coin] = int(per_coin.get(coin, 0)) + 1
                if coin == "SOL" and per_coin[coin] == 1:
                    return ({"ok": False, "error": "temporary"}, None)
                if coin == "BTC":
                    svc.TRACKER_STATE["open_positions"].pop("BTC-PERP", None)
                    svc.TRACKER_STATE["quant_open_positions"].pop("BTC-PERP", None)
                return ({"ok": True, "order": {"status": "filled"}}, None)

            def _fake_open_leg(**kwargs):
                coin = str(kwargs.get("coin") or "").strip().upper()
                side = str(kwargs.get("side") or "").strip().lower()
                notional = float(kwargs.get("notional_usdc") or 0.0)
                if coin == "BTC":
                    svc.TRACKER_STATE["open_positions"]["BTC-PERP"] = {"pair": "BTC-PERP", "side": side, "notional_usdc": float(notional)}
                    svc.TRACKER_STATE["quant_open_positions"]["BTC-PERP"] = {"pair": "BTC-PERP", "side": side, "strategy_id": "quant_pairs_btcalt", "tag": "t|g", "pair_group": "g", "alt": "SOL", "notional_usdc": float(notional)}
                return ({"ok": True, "order": {"status": "filled"}}, None)

            def _fake_hl_sync_record(**kwargs):
                return {"ok": True, "sync": "noop"}

            svc._pairs_btceth_close_leg = _fake_close_leg
            svc._pairs_quant_open_leg = _fake_open_leg
            svc._hl_sync_record = _fake_hl_sync_record

            with svc.app.test_request_context(
                "/execution/pairs/btcalt/market_close",
                method="POST",
                json={"venue": "hyperliquid", "execute": True, "confirm_execute": True, "tag": "t", "alt": "SOL", "close_verify_timeout_sec": 0.1, "close_verify_poll_sec": 0.05},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ):
                out = svc.execution_pairs_btcalt_market_close()
            resp = out[0] if isinstance(out, tuple) else out
            data = resp.get_json(silent=True)
            self.assertFalse(bool(data.get("ok")))
            self.assertTrue(isinstance(data.get("rollback"), dict))
            self.assertTrue(isinstance((data.get("rollback") or {}).get("btc"), dict))
            self.assertTrue(isinstance(data.get("quasi_atomic"), dict))
        finally:
            svc._pairs_btceth_close_leg = orig_close_leg
            svc._pairs_quant_open_leg = orig_open_leg
            svc._hl_sync_record = orig_hl_sync
        self.assertEqual(svc.TRACKER_STATE.get("exit_inflight"), {})

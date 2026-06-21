import time
import unittest

import ml_trade_service as svc


class TestPostCloseCooldown(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))

        try:
            svc.TRACKER_STATE.clear()
        except Exception:
            pass

        svc.CONFIG["coin_freeze_post_close_hours"] = 4
        svc.CONFIG["correlation_threshold"] = 0
        svc.CONFIG["max_open_trades"] = 999
        svc.CONFIG["execute_guard_enabled"] = False
        svc.CONFIG["trade_whitelist_enabled"] = False
        svc.CONFIG["macro_gate_enabled"] = False
        svc.TRACKER_STATE["post_close_cooldowns"] = {}
        svc.TRACKER_STATE["daily_pnl"] = {}
        svc.TRACKER_STATE["weekly_pnl"] = {}
        svc.TRACKER_STATE["order_ts"] = []
        svc.TRACKER_STATE["open_positions"] = {}
        svc.TRACKER_STATE["carry_open_positions"] = {}
        svc.TRACKER_STATE["quant_open_positions"] = {}
        svc.TRACKER_STATE["three_screen_open_positions"] = {}

    def tearDown(self) -> None:
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass

    def test_clear_marks_post_close_cooldown(self) -> None:
        svc.TRACKER_STATE["open_positions"]["ZRO-PERP"] = {"pair": "ZRO-PERP", "side": "long"}
        res = svc._tracker_clear_open_positions(raw_pair="ZRO-PERP", coin="ZRO")
        self.assertTrue(bool(res.get("ok")))
        self.assertGreaterEqual(int(res.get("cleared") or 0), 1)

        pcd = svc.TRACKER_STATE.get("post_close_cooldowns")
        self.assertIsInstance(pcd, dict)
        pcd_s = pcd.get("strategy")
        self.assertIsInstance(pcd_s, dict)
        self.assertIn("ZRO-PERP", pcd_s)
        self.assertIn("ZRO", pcd_s)

    def test_order_gate_blocks_reentry_after_clear(self) -> None:
        svc.TRACKER_STATE["open_positions"]["ZRO-PERP"] = {"pair": "ZRO-PERP", "side": "long"}
        svc._tracker_clear_open_positions(raw_pair="ZRO-PERP", coin="ZRO")

        now_ms = int(time.time() * 1000)
        out, code = svc._order_gate_open(
            pair="ZRO-PERP",
            side="short",
            now_ms=now_ms,
            meta={"reserve_gate": False},
        )
        self.assertEqual(int(code), 200)
        self.assertFalse(bool(out.get("ok")))
        self.assertEqual(str(out.get("reason")), "post_close_freeze")

    def test_order_gate_corr_bypass_uses_pair_group_when_tag_missing(self) -> None:
        now_ms = int(time.time() * 1000)
        svc.CONFIG["execution_venue"] = "aster"
        svc.CONFIG["correlation_threshold"] = 0.85
        svc.CONFIG["correlation_lookback_hours"] = 72

        orig_corr = svc._pair_corr_cached
        try:
            svc._pair_corr_cached = lambda *_args, **_kwargs: 0.99
            svc.TRACKER_STATE["quant_open_positions"]["ETH-PERP"] = {
                "pair": "ETH-PERP",
                "side": "long",
                "venue": "aster",
                "ab_owner": "quant",
                "pair_group": "pair_test_0",
                "tag": "",
                "strategy_id": "quant_pairs_btcalt",
            }

            out, code = svc._order_gate_open(
                pair="BTC-PERP",
                side="short",
                now_ms=now_ms,
                meta={
                    "system_id": "quant",
                    "ab_owner": "quant",
                    "strategy_id": "quant_pairs_btcalt",
                    "tag": "quant_pairs_btcalt|pair_test_0",
                    "reserve_gate": False,
                },
            )
            self.assertEqual(int(code), 200)
            self.assertTrue(bool(out.get("ok")), msg=str(out))
        finally:
            svc._pair_corr_cached = orig_corr

    def test_aster_sync_prune_marks_post_close_cooldown(self) -> None:
        svc.TRACKER_STATE["open_positions"]["ZRO-PERP"] = {
            "pair": "ZRO-PERP",
            "side": "long",
            "venue": "aster",
            "mode": "real",
            "simulated": False,
        }

        orig_fetch_positions = svc._aster_fetch_positions
        try:
            svc._aster_fetch_positions = lambda: ([], None)
            out = svc._aster_sync(update_orders=False)
            self.assertTrue(bool(out.get("ok")))
        finally:
            svc._aster_fetch_positions = orig_fetch_positions

        pcd = svc.TRACKER_STATE.get("post_close_cooldowns")
        self.assertIsInstance(pcd, dict)
        pcd_s = pcd.get("strategy")
        self.assertIsInstance(pcd_s, dict)
        self.assertIn("ZRO", pcd_s)
        self.assertIn("ZRO-PERP", pcd_s)

    def test_aster_sync_does_not_prune_simulated_positions(self) -> None:
        svc.TRACKER_STATE["open_positions"]["BTC-PERP"] = {
            "pair": "BTC-PERP",
            "side": "long",
            "venue": "aster",
            "mode": "dry-run",
            "simulated": True,
        }
        svc.TRACKER_STATE["quant_open_positions"]["ETH-PERP"] = {
            "pair": "ETH-PERP",
            "side": "short",
            "venue": "aster",
            "mode": "dry-run",
            "simulated": True,
        }

        orig_fetch_positions = svc._aster_fetch_positions
        try:
            svc._aster_fetch_positions = lambda: ([], None)
            out = svc._aster_sync(update_orders=False)
            self.assertTrue(bool(out.get("ok")))
        finally:
            svc._aster_fetch_positions = orig_fetch_positions

        self.assertIn("BTC-PERP", svc.TRACKER_STATE.get("open_positions") or {})
        self.assertIn("ETH-PERP", svc.TRACKER_STATE.get("quant_open_positions") or {})

    def test_open_positions_clear_endpoint_marks_post_close_cooldown(self) -> None:
        svc.TRACKER_STATE["open_positions"]["ZRO-PERP"] = {
            "pair": "ZRO-PERP",
            "side": "long",
            "venue": "aster",
            "mode": "real",
            "simulated": False,
        }

        client = svc.app.test_client()
        res = client.post(
            "/tracker/open_positions/clear",
            json={"pairs": ["ZRO-PERP"], "system_id": "strategy"},
        )
        self.assertEqual(int(res.status_code), 200)
        out = res.get_json() or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertGreaterEqual(int(out.get("n_removed") or 0), 1)

        pcd = svc.TRACKER_STATE.get("post_close_cooldowns")
        self.assertIsInstance(pcd, dict)
        pcd_s = pcd.get("strategy")
        self.assertIsInstance(pcd_s, dict)
        self.assertIn("ZRO", pcd_s)
        self.assertIn("ZRO-PERP", pcd_s)

    def test_open_positions_stats_counts_three_screen_bucket(self) -> None:
        svc.TRACKER_STATE["three_screen_open_positions"]["BTC-PERP"] = {
            "pair": "BTC-PERP",
            "side": "long",
            "strategy_id": "ThreeScreen",
            "group_id": "g1",
            "notional_usdc": 12.5,
        }
        svc.TRACKER_STATE["open_positions"]["ETH-PERP"] = {
            "pair": "ETH-PERP",
            "side": "short",
            "strategy_id": "Other",
            "group_id": "g1",
            "notional_usdc": 3.0,
        }

        s = svc._open_positions_stats(strategy_id="ThreeScreen")
        self.assertEqual(int(s.get("n") or 0), 1)
        self.assertAlmostEqual(float(s.get("notional_usdc") or 0.0), 12.5, places=8)

        g = svc._open_positions_stats(group_id="g1")
        self.assertEqual(int(g.get("n") or 0), 2)
        self.assertAlmostEqual(float(g.get("notional_usdc") or 0.0), 15.5, places=8)

    def test_tracker_risk_reset_clears_pair_coin_cooldowns(self) -> None:
        svc.TRACKER_STATE["cooldowns"] = {"BTC-PERP|long": 1700000000000}
        svc.TRACKER_STATE["coin_cooldowns"] = {"BTC|long": 1700000000000}
        svc.TRACKER_STATE["entry_pending_side"] = {"BTC-PERP": {"ts": 1700000000000, "side": "long"}}

        client = svc.app.test_client()
        res = client.post(
            "/tracker/risk/reset",
            json={
                "reset_subportfolio": False,
                "reset_pnl": False,
                "reset_cooldowns": True,
                "reset_gate_history": False,
            },
        )
        self.assertEqual(int(res.status_code), 200)
        out = res.get_json() or {}
        self.assertTrue(bool(out.get("ok")))

        self.assertEqual(svc.TRACKER_STATE.get("cooldowns") or {}, {})
        self.assertEqual(svc.TRACKER_STATE.get("coin_cooldowns") or {}, {})
        self.assertEqual(svc.TRACKER_STATE.get("entry_pending_side") or {}, {})

    def test_quant_pairs_btcalt_btc_leg_ignores_post_close_freeze(self) -> None:
        client = svc.app.test_client()

        orig_resolve_alt = svc._quant_pairs_btcalt_resolve_alt
        orig_latest_beta = svc._quant_pairs_btcalt_latest_beta
        orig_open_leg = svc._pairs_quant_open_leg
        orig_macro_veto = svc._quant_pairs_macro_trend_veto
        try:
            svc._quant_pairs_btcalt_resolve_alt = lambda *args, **kwargs: {
                "alt": "ZEC",
                "source": "test",
                "candidates": ["ZEC"],
                "snap": {"ok": True, "beta": 1.0, "btc_px": 30000.0},
            }
            svc._quant_pairs_btcalt_latest_beta = lambda *args, **kwargs: {"ok": True, "beta": 1.0, "btc_px": 30000.0}
            svc._quant_pairs_macro_trend_veto = lambda *args, **kwargs: {"ok": True, "blocked": False}

            calls = []

            def _open_leg_stub(*, coin: str, ignore_post_close_freeze: bool = False, **kwargs):
                calls.append({"coin": str(coin), "ignore_post_close_freeze": bool(ignore_post_close_freeze)})
                return {"ok": True, "order": {"size": 1.0}}, 200

            svc._pairs_quant_open_leg = _open_leg_stub

            res = client.post(
                "/execution/pairs/btcalt/market_open",
                json={
                    "alt": "ZEC",
                    "direction": "short_alt_long_btc",
                    "execute": False,
                    "notional_usdc": 100.0,
                },
            )
            self.assertEqual(int(res.status_code), 200)
            out = res.get_json() or {}
            self.assertTrue(bool(out.get("ok")))
            btc_calls = [c for c in calls if c.get("coin") == "BTC"]
            self.assertTrue(bool(btc_calls))
            self.assertTrue(all(bool(c.get("ignore_post_close_freeze")) for c in btc_calls))
        finally:
            svc._quant_pairs_btcalt_resolve_alt = orig_resolve_alt
            svc._quant_pairs_btcalt_latest_beta = orig_latest_beta
            svc._pairs_quant_open_leg = orig_open_leg
            svc._quant_pairs_macro_trend_veto = orig_macro_veto

    def test_btcalt_bc_opens_btc_after_alt_with_market_order(self) -> None:
        client = svc.app.test_client()

        orig_resolve_alt = svc._quant_pairs_btcalt_resolve_alt
        orig_latest_beta = svc._quant_pairs_btcalt_latest_beta
        orig_open_leg = svc._pairs_quant_open_leg
        orig_macro_veto = svc._quant_pairs_macro_trend_veto
        orig_order_gate_open = svc._order_gate_open
        orig_pool = svc._quant_pairs_btcalt_sub_pool_snapshot
        orig_pf = svc._aster_preflight_notional
        try:
            svc._quant_pairs_btcalt_resolve_alt = lambda *args, **kwargs: {
                "alt": "ZEC",
                "source": "test",
                "candidates": ["ZEC"],
                "snap": {"ok": True, "beta": 1.0, "btc_px": 30000.0},
            }
            svc._quant_pairs_btcalt_latest_beta = lambda *args, **kwargs: {"ok": True, "beta": 1.0, "btc_px": 30000.0}
            svc._quant_pairs_macro_trend_veto = lambda *args, **kwargs: {"ok": True, "blocked": False}
            svc._order_gate_open = lambda **_kw: ({"ok": True}, 200)
            svc._quant_pairs_btcalt_sub_pool_snapshot = lambda *args, **kwargs: {"cap_usdc": 10_000_000.0, "used_usdc": 0.0}
            svc._aster_preflight_notional = lambda *args, **kwargs: {"ok": True, "required_notional_usdc": float(args[1] if len(args) >= 2 else kwargs.get("notional_usdc") or 0.0)}

            calls = []

            def _open_leg_stub(*, coin: str, maker: bool = False, **kwargs):
                calls.append({"coin": str(coin), "maker": bool(maker)})
                return {"ok": True, "order": {"size": 1.0}}, 200

            svc._pairs_quant_open_leg = _open_leg_stub

            res = client.post(
                "/execution/pairs/btcalt/market_open",
                json={
                    "alt": "ZEC",
                    "direction": "short_alt_long_btc",
                    "execute": False,
                    "notional_usdc": 100.0,
                    "strategy_mode": "B",
                    "maker": True,
                },
            )
            self.assertEqual(int(res.status_code), 200)
            out = res.get_json() or {}
            self.assertTrue(bool(out.get("ok")))
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(str(calls[0].get("coin")), "ZEC")
            self.assertEqual(str(calls[1].get("coin")), "BTC")
            self.assertTrue(all(not bool(c.get("maker")) for c in calls[:2]))
        finally:
            svc._quant_pairs_btcalt_resolve_alt = orig_resolve_alt
            svc._quant_pairs_btcalt_latest_beta = orig_latest_beta
            svc._pairs_quant_open_leg = orig_open_leg
            svc._quant_pairs_macro_trend_veto = orig_macro_veto
            svc._order_gate_open = orig_order_gate_open
            svc._quant_pairs_btcalt_sub_pool_snapshot = orig_pool
            svc._aster_preflight_notional = orig_pf

    def test_btcalt_btc_leg_failure_keeps_alt_with_5m_grace(self) -> None:
        client = svc.app.test_client()

        orig_resolve_alt = svc._quant_pairs_btcalt_resolve_alt
        orig_latest_beta = svc._quant_pairs_btcalt_latest_beta
        orig_open_leg = svc._pairs_quant_open_leg
        orig_macro_veto = svc._quant_pairs_macro_trend_veto
        orig_order_gate_open = svc._order_gate_open
        orig_pool = svc._quant_pairs_btcalt_sub_pool_snapshot
        orig_pf = svc._aster_preflight_notional
        orig_close_leg = svc._pairs_btceth_close_leg
        try:
            svc._quant_pairs_btcalt_resolve_alt = lambda *args, **kwargs: {
                "alt": "ZEC",
                "source": "test",
                "candidates": ["ZEC"],
                "snap": {"ok": True, "beta": 1.0, "btc_px": 30000.0},
            }
            svc._quant_pairs_btcalt_latest_beta = lambda *args, **kwargs: {"ok": True, "beta": 1.0, "btc_px": 30000.0}
            svc._quant_pairs_macro_trend_veto = lambda *args, **kwargs: {"ok": True, "blocked": False}
            svc._order_gate_open = lambda **_kw: ({"ok": True}, 200)
            svc._quant_pairs_btcalt_sub_pool_snapshot = lambda *args, **kwargs: {"cap_usdc": 10_000_000.0, "used_usdc": 0.0}
            svc._aster_preflight_notional = lambda *args, **kwargs: {"ok": True, "required_notional_usdc": float(args[1] if len(args) >= 2 else kwargs.get("notional_usdc") or 0.0)}

            def _open_leg_stub(*, coin: str, **kwargs):
                if str(coin).strip().upper() == "BTC":
                    return {"ok": False, "error": "btc_fail"}, 502
                return {"ok": True, "order": {"size": 1.0}}, 200

            def _close_leg_forbidden(*args, **kwargs):
                raise AssertionError("rollback should not happen when one-leg grace is enabled")

            svc._pairs_quant_open_leg = _open_leg_stub
            svc._pairs_btceth_close_leg = _close_leg_forbidden

            res = client.post(
                "/execution/pairs/btcalt/market_open",
                json={
                    "alt": "ZEC",
                    "direction": "short_alt_long_btc",
                    "execute": False,
                    "notional_usdc": 100.0,
                    "strategy_mode": "B",
                },
            )
            self.assertEqual(int(res.status_code), 200)
            out = res.get_json() or {}
            self.assertTrue(bool(out.get("ok")))
            self.assertEqual(str(out.get("status")), "partial_open")
            self.assertEqual(str(out.get("error")), "btc_leg_failed")
            self.assertAlmostEqual(float(out.get("one_leg_grace_sec") or 0.0), 300.0, places=6)

            pending = svc.TRACKER_STATE.get("quant_auto_btcalts_pending_hedges") or {}
            self.assertIsInstance(pending, dict)
            self.assertTrue(any(str(k).startswith("quant_pairs_btcalt|") for k in pending.keys()))
        finally:
            svc._quant_pairs_btcalt_resolve_alt = orig_resolve_alt
            svc._quant_pairs_btcalt_latest_beta = orig_latest_beta
            svc._pairs_quant_open_leg = orig_open_leg
            svc._quant_pairs_macro_trend_veto = orig_macro_veto
            svc._order_gate_open = orig_order_gate_open
            svc._quant_pairs_btcalt_sub_pool_snapshot = orig_pool
            svc._aster_preflight_notional = orig_pf
            svc._pairs_btceth_close_leg = orig_close_leg

    def test_btcalts_one_leg_retry_is_2m_for_bc_default(self) -> None:
        orig_status = svc.quant_pairs_btcalt_status
        orig_open_leg = svc._pairs_quant_open_leg
        try:
            svc.CONFIG["quant_auto_mode"] = "paper"
            svc.CONFIG["quant_auto_enabled"] = True
            svc.CONFIG["quant_auto_btcalts_enabled"] = True
            svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
            svc.CONFIG["quant_auto_btcalts_one_leg_grace_sec"] = 300

            tag_pos = "quant_pairs_btcalt|pair_test"
            entry_ts = 1_700_000_000_000
            svc.TRACKER_STATE["quant_open_positions"]["ZEC-PERP"] = {
                "pair": "ZEC-PERP",
                "side": "long",
                "tag": tag_pos,
                "strategy_id": "quant_auto_btcalts",
                "system_id": "quant",
                "ab_owner": "quant",
                "notional_usdc": 100.0,
                "beta_abs": 1.0,
                "btc_hedge_frac": 0.75,
                "entry_ts": entry_ts,
                "pair_group": "pair_test",
            }

            now_box = {"now_ms": entry_ts}

            def _status_stub():
                alt = str(svc.request.args.get("alt") or "ZEC").strip().upper() or "ZEC"
                out = {
                    "ok": True,
                    "action": "hold",
                    "reason": None,
                    "position": {
                        "any": True,
                        "pair_ok": False,
                        "entry_ts": entry_ts,
                        "legs": {"alt": {"coin": alt}},
                    },
                }
                return svc.jsonify(out), 200

            calls = []

            def _open_leg_stub(*, coin: str, **kwargs):
                calls.append({"now_ms": int(now_box["now_ms"]), "coin": str(coin)})
                return {"ok": False, "error": "btc_fail"}, 502

            svc.quant_pairs_btcalt_status = _status_stub
            svc._pairs_quant_open_leg = _open_leg_stub
            now_box["now_ms"] = entry_ts + 10_000
            svc._quant_auto_btcalts_tick(now_ms=entry_ts + 10_000)
            now_box["now_ms"] = entry_ts + 70_000
            svc._quant_auto_btcalts_tick(now_ms=entry_ts + 70_000)
            now_box["now_ms"] = entry_ts + 130_000
            svc._quant_auto_btcalts_tick(now_ms=entry_ts + 130_000)

            btc_calls = [c for c in calls if str(c.get("coin")).strip().upper() == "BTC"]
            self.assertEqual(len(btc_calls), 2)
            self.assertEqual(int(btc_calls[0].get("now_ms")), int(entry_ts + 10_000))
            self.assertEqual(int(btc_calls[1].get("now_ms")), int(entry_ts + 130_000))
        finally:
            svc.quant_pairs_btcalt_status = orig_status
            svc._pairs_quant_open_leg = orig_open_leg

    def test_quant_pairs_btcalt_orders_recent_includes_quant_pairs(self) -> None:
        oid = "test_ord_quant_pairs_btcalt_1"
        ts = int(time.time() * 1000)
        existed = bool(oid in getattr(svc, "ORDERS", {}))
        prev = None
        try:
            if existed:
                prev = svc.ORDERS.get(oid)
            svc.ORDERS[oid] = {
                "id": oid,
                "ts": ts,
                "strategy_id": "quant_pairs_btcalt",
                "tag": "quant_pairs_btcalt|pair_test",
            }
            out = svc._quant_pairs_btcalt_orders_recent(limit=50)
            self.assertTrue(any(str(o.get("id")) == oid for o in (out or [])))
        finally:
            try:
                if existed:
                    svc.ORDERS[oid] = prev
                else:
                    svc.ORDERS.pop(oid, None)
            except Exception:
                pass

    def test_quant_pairs_btceth_btc_leg_ignores_post_close_freeze(self) -> None:
        client = svc.app.test_client()

        orig_latest_beta = svc._quant_pairs_btceth_latest_beta
        orig_open_leg = svc._pairs_quant_open_leg
        orig_macro_veto = svc._quant_pairs_macro_trend_veto
        try:
            svc._quant_pairs_btceth_latest_beta = lambda *args, **kwargs: {"ok": True, "beta": 1.0, "btc_px": 30000.0}
            svc._quant_pairs_macro_trend_veto = lambda *args, **kwargs: {"ok": True, "blocked": False}

            calls = []

            def _open_leg_stub(*, coin: str, ignore_post_close_freeze: bool = False, **kwargs):
                calls.append({"coin": str(coin), "ignore_post_close_freeze": bool(ignore_post_close_freeze)})
                return {"ok": True, "order": {"size": 1.0}}, 200

            svc._pairs_quant_open_leg = _open_leg_stub

            res = client.post(
                "/execution/pairs/btceth/market_open",
                json={
                    "direction": "long_btc_short_eth",
                    "execute": False,
                    "notional_usdc": 100.0,
                },
            )
            self.assertEqual(int(res.status_code), 200)
            out = res.get_json() or {}
            self.assertTrue(bool(out.get("ok")))
            btc_calls = [c for c in calls if c.get("coin") == "BTC"]
            self.assertTrue(bool(btc_calls))
            self.assertTrue(all(bool(c.get("ignore_post_close_freeze")) for c in btc_calls))
        finally:
            svc._quant_pairs_btceth_latest_beta = orig_latest_beta
            svc._pairs_quant_open_leg = orig_open_leg
            svc._quant_pairs_macro_trend_veto = orig_macro_veto

    def test_isolation_matrix_minimal_dryrun(self) -> None:
        client = svc.app.test_client()

        orig_orders = dict(getattr(svc, "ORDERS", {}))
        orig_open_positions = dict(svc.TRACKER_STATE.get("open_positions") or {})
        orig_carry_open_positions = dict(svc.TRACKER_STATE.get("carry_open_positions") or {})
        orig_quant_open_positions = dict(svc.TRACKER_STATE.get("quant_open_positions") or {})

        orig_aster_open = svc.aster_market_open_internal
        orig_hl_open = svc.hyperliquid_market_open_internal
        orig_latest_beta = svc._quant_pairs_btceth_latest_beta
        orig_open_leg = svc._pairs_quant_open_leg
        orig_macro_veto = svc._quant_pairs_macro_trend_veto
        orig_order_gate_open = svc._order_gate_open

        calls = {"aster": [], "hl": [], "leg": []}
        seq = {"i": 0}

        def _next_id(prefix: str) -> str:
            seq["i"] += 1
            return f"{prefix}_{seq['i']}"

        try:
            try:
                svc.ORDERS.clear()
            except Exception:
                pass
            svc.TRACKER_STATE["open_positions"] = {}
            svc.TRACKER_STATE["carry_open_positions"] = {}
            svc.TRACKER_STATE["quant_open_positions"] = {}
            svc.TRACKER_STATE["three_screen_open_positions"] = {}

            svc._order_gate_open = lambda **_kw: ({"ok": True}, 200)
            svc._quant_pairs_btceth_latest_beta = lambda *args, **kwargs: {"ok": True, "beta": 1.0, "btc_px": 30000.0}
            svc._quant_pairs_macro_trend_veto = lambda *args, **kwargs: {"ok": True, "blocked": False}

            def _stub_aster_market_open_internal(**kwargs):
                calls["aster"].append(dict(kwargs))
                coin = str(kwargs.get("coin") or "").upper().strip() or "BTC"
                pair = f"{coin}-PERP"
                ab_owner = str(kwargs.get("ab_owner") or "strategy").strip().lower() or "strategy"
                oid = _next_id("ord")
                order = {
                    "id": oid,
                    "ts": 1_700_000_000_000 + seq["i"],
                    "ingested_ms": 1_700_000_000_000 + seq["i"],
                    "action": "open",
                    "pair": pair,
                    "side": str(kwargs.get("side") or "long"),
                    "exchange": "aster",
                    "ab_owner": ab_owner,
                    "book_id": ab_owner,
                    "system_id": ("quant" if ab_owner == "quant" else ("carry" if ab_owner == "carry" else ("three_screen" if ab_owner == "three_screen" else "strategy"))),
                    "mode": "dry-run",
                    "simulated": True,
                    "tag": str(kwargs.get("tag") or ""),
                    "strategy_id": (None if kwargs.get("strategy_id") is None else str(kwargs.get("strategy_id"))),
                }
                svc.ORDERS[oid] = order
                if order["system_id"] == "quant":
                    svc.TRACKER_STATE["quant_open_positions"][pair] = dict(order)
                elif order["system_id"] == "carry":
                    svc.TRACKER_STATE["carry_open_positions"][pair] = dict(order)
                elif order["system_id"] == "three_screen":
                    svc.TRACKER_STATE["three_screen_open_positions"][pair] = dict(order)
                else:
                    svc.TRACKER_STATE["open_positions"][pair] = dict(order)
                return svc.jsonify({"ok": True, "order": order, "order_id": oid}), 200

            def _stub_hl_market_open_internal(**kwargs):
                calls["hl"].append(dict(kwargs))
                coin = str(kwargs.get("coin") or "").upper().strip() or "BTC"
                pair = f"{coin}-PERP"
                ab_owner = str(kwargs.get("ab_owner") or "carry").strip().lower() or "carry"
                oid = _next_id("ord")
                order = {
                    "id": oid,
                    "ts": 1_700_000_000_000 + seq["i"],
                    "ingested_ms": 1_700_000_000_000 + seq["i"],
                    "action": "open",
                    "pair": pair,
                    "side": str(kwargs.get("side") or "long"),
                    "exchange": "hyperliquid",
                    "ab_owner": ab_owner,
                    "book_id": ab_owner,
                    "system_id": ("quant" if ab_owner == "quant" else ("carry" if ab_owner == "carry" else ("three_screen" if ab_owner == "three_screen" else "strategy"))),
                    "mode": "dry-run",
                    "simulated": True,
                    "tag": str(kwargs.get("tag") or ""),
                    "strategy_id": (None if kwargs.get("strategy_id") is None else str(kwargs.get("strategy_id"))),
                }
                svc.ORDERS[oid] = order
                if order["system_id"] == "carry":
                    svc.TRACKER_STATE["carry_open_positions"][pair] = dict(order)
                elif order["system_id"] == "quant":
                    svc.TRACKER_STATE["quant_open_positions"][pair] = dict(order)
                elif order["system_id"] == "three_screen":
                    svc.TRACKER_STATE["three_screen_open_positions"][pair] = dict(order)
                else:
                    svc.TRACKER_STATE["open_positions"][pair] = dict(order)
                return svc.jsonify({"ok": True, "order": order, "order_id": oid}), 200

            def _stub_pairs_quant_open_leg(*, coin: str, **kwargs):
                calls["leg"].append({"coin": str(coin), **dict(kwargs)})
                coin_u = str(coin).upper().strip()
                pair = f"{coin_u}-PERP"
                oid = _next_id("ord")
                order = {
                    "id": oid,
                    "ts": 1_700_000_000_000 + seq["i"],
                    "ingested_ms": 1_700_000_000_000 + seq["i"],
                    "action": "open",
                    "pair": pair,
                    "side": "long",
                    "exchange": "aster",
                    "ab_owner": "quant",
                    "book_id": "quant",
                    "system_id": "quant",
                    "mode": "dry-run",
                    "simulated": True,
                    "tag": str(kwargs.get("tag") or ""),
                    "strategy_id": "quant_pairs_btceth",
                }
                svc.ORDERS[oid] = order
                svc.TRACKER_STATE["quant_open_positions"][pair] = dict(order)
                return {"ok": True, "order": order}, 200

            svc.aster_market_open_internal = _stub_aster_market_open_internal
            svc.hyperliquid_market_open_internal = _stub_hl_market_open_internal
            svc._pairs_quant_open_leg = _stub_pairs_quant_open_leg

            r1 = client.post("/webhook/freqtrade", json={
                "strategy": "Strategy005",
                "pair": "BTC-PERP",
                "type": "entry",
                "side": "long",
                "venue": "aster",
                "execute": False,
                "ignore_post_close_freeze": True,
                "ignore_cooldown": True,
                "skip_gate": True,
            })
            self.assertEqual(int(r1.status_code), 200)
            out1 = r1.get_json() or {}
            self.assertTrue(bool(out1.get("ok")))
            self.assertTrue(bool(calls["aster"]))
            self.assertTrue(all(bool(x.get("skip_gate")) for x in calls["aster"]))

            r2 = client.post("/webhook/freqtrade", json={
                "strategy": "carry_trade",
                "pair": "BTC-PERP",
                "type": "entry",
                "side": "short",
                "notional_usdc": 300,
                "execute": False,
                "ignore_post_close_freeze": True,
                "ignore_cooldown": True,
                "skip_gate": True,
            })
            self.assertEqual(int(r2.status_code), 200)
            out2 = r2.get_json() or {}
            self.assertTrue(bool(out2.get("ok")))
            self.assertTrue(bool(calls["hl"]))
            self.assertTrue(all(bool(x.get("ignore_post_close_freeze")) for x in calls["hl"]))
            self.assertTrue(all(bool(x.get("ignore_cooldown")) for x in calls["hl"]))
            self.assertTrue(all(bool(x.get("skip_gate")) for x in calls["hl"]))

            r3 = client.post("/execution/pairs/btceth/market_open", json={
                "direction": "long_btc_short_eth",
                "execute": False,
                "notional_usdc": 100.0,
            })
            self.assertEqual(int(r3.status_code), 200)
            out3 = r3.get_json() or {}
            self.assertTrue(bool(out3.get("ok")))
            self.assertGreaterEqual(len(calls["leg"]), 2)

            ops = svc.TRACKER_STATE.get("open_positions") or {}
            cps = svc.TRACKER_STATE.get("carry_open_positions") or {}
            qps = svc.TRACKER_STATE.get("quant_open_positions") or {}
            self.assertIn("BTC-PERP", ops)
            self.assertIn("BTC-PERP", cps)
            self.assertIn("BTC-PERP", qps)
            self.assertIn("ETH-PERP", qps)

            rs = client.get("/orders/recent", query_string={"limit": 50, "include_shadow": 1, "sort": "ingest", "ab_owner": "strategy"})
            self.assertEqual(int(rs.status_code), 200)
            xs = rs.get_json() or []
            self.assertTrue(any(isinstance(o, dict) and o.get("ab_owner") == "strategy" for o in xs))

            rc = client.get("/orders/recent", query_string={"limit": 50, "include_shadow": 1, "sort": "ingest", "ab_owner": "carry"})
            self.assertEqual(int(rc.status_code), 200)
            xc = rc.get_json() or []
            self.assertTrue(any(isinstance(o, dict) and o.get("ab_owner") == "carry" for o in xc))

            rq = client.get("/orders/recent", query_string={"limit": 50, "include_shadow": 1, "sort": "ingest", "ab_owner": "quant"})
            self.assertEqual(int(rq.status_code), 200)
            xq = rq.get_json() or []
            self.assertTrue(any(isinstance(o, dict) and o.get("ab_owner") == "quant" for o in xq))
        finally:
            try:
                svc.ORDERS.clear()
                svc.ORDERS.update(orig_orders)
            except Exception:
                pass
            svc.TRACKER_STATE["open_positions"] = orig_open_positions
            svc.TRACKER_STATE["carry_open_positions"] = orig_carry_open_positions
            svc.TRACKER_STATE["quant_open_positions"] = orig_quant_open_positions

            svc.aster_market_open_internal = orig_aster_open
            svc.hyperliquid_market_open_internal = orig_hl_open
            svc._quant_pairs_btceth_latest_beta = orig_latest_beta
            svc._pairs_quant_open_leg = orig_open_leg
            svc._quant_pairs_macro_trend_veto = orig_macro_veto
            svc._order_gate_open = orig_order_gate_open

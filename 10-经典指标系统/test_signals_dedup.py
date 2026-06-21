import threading
import time
import unittest


import ml_trade_service as svc


class TestSignalsDedup(unittest.TestCase):
    def setUp(self) -> None:
        svc.CONFIG["dry_run"] = True
        svc.CONFIG["live_trading_enabled"] = False
        svc.CONFIG["strategy_tier_trading_enabled"] = True
        svc.CONFIG["strategy_tier_default"] = "C"
        svc.CONFIG["signals_dedup_ttl_sec"] = 3600
        svc.CONFIG["signals_v1_confirm_enabled"] = False
        svc.CONFIG["signals_v1_confirm_n"] = 2
        svc.CONFIG["signals_v1_confirm_m"] = 3
        with svc.SIGNAL_DEDUP_LOCK:
            svc.SIGNAL_DEDUP.clear()
            svc.SIGNAL_DEDUP_V1_BASE.clear()
        svc.SIGNAL_CONFIRM_V1.clear()
        svc.EVENTS.clear()
        svc.ORDERS.clear()

    def test_v1_base_upgrade_trigger_reuses_event_id(self) -> None:
        old = svc._decision_entry_impl

        def _stub_decision(dreq):
            return {"ok": True, "stub": True}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="hyperliquid",
                pair="BTC/USDC",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=True,
                strategy_id="Strategy005",
                strategy_version="1.0.0",
                group_id="test",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )

            r1 = svc._emit_signal_v1(dict(payload), False, {"source": "unit"})
            r2 = svc._emit_signal_v1(dict(payload), True, {"source": "unit"})

            self.assertTrue(r1.get("ok"))
            self.assertTrue(r2.get("ok"))
            self.assertEqual(r1.get("id"), r2.get("id"))
            self.assertEqual(r1.get("event_id"), r1.get("id"))
            self.assertEqual(r1.get("trace_id"), r1.get("id"))
            self.assertEqual(r2.get("event_id"), r2.get("id"))
            self.assertEqual(r2.get("trace_id"), r2.get("id"))
            self.assertTrue(r2.get("auto_decision"))
            self.assertEqual(r2.get("decision_code"), 200)
        finally:
            svc._decision_entry_impl = old

    def test_concurrent_trigger_and_nontrigger_share_one_event(self) -> None:
        old = svc._decision_entry_impl

        def _stub_decision(dreq):
            return {"ok": True, "stub": True}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="hyperliquid",
                pair="BTC/USDC",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=True,
                strategy_id="Strategy005",
                strategy_version="1.0.0",
                group_id="test",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )

            results = []

            def worker(trig: bool) -> None:
                results.append(svc._emit_signal_v1(dict(payload), trig, {"source": "unit"}))

            threads = [threading.Thread(target=worker, args=(False,)), threading.Thread(target=worker, args=(True,))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            ids = [r.get("id") for r in results if isinstance(r, dict) and r.get("id")]
            self.assertEqual(len(set(ids)), 1)
        finally:
            svc._decision_entry_impl = old

    def test_selfcheck_smoke_forces_dry_run_temporarily(self) -> None:
        old = svc._decision_entry_impl

        def _stub_decision(_dreq):
            return {"ok": True, "decision": "observe", "mode": "dry-run"}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            svc.CONFIG["dry_run"] = False
            res = svc._selfcheck_smoke(int(time.time() * 1000), cleanup=True)
            self.assertTrue(bool(res.get("ok")))
            self.assertTrue(bool(res.get("forced_dry_run")))
            self.assertFalse(bool(svc.CONFIG.get("dry_run", True)))
        finally:
            svc._decision_entry_impl = old

    def test_signals_v1_triggers_decision_when_bar_closed(self) -> None:
        old = svc._decision_entry_impl
        called = {"n": 0}

        def _stub_decision(_dreq):
            called["n"] += 1
            return {"ok": True, "decision": "observe"}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="freqtrade",
                pair="BTC/USDC",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=True,
                strategy_id="Strategy005",
                strategy_version="1.0.0",
                group_id="test",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )
            client = svc.app.test_client()
            r = client.post("/signals/v1", json={"signal": payload, "trigger_decision": True})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(bool(data.get("ok")))
            self.assertEqual(data.get("event_id"), data.get("id"))
            self.assertEqual(data.get("trace_id"), data.get("id"))
            self.assertTrue(bool(data.get("trigger_decision")))
            self.assertTrue(bool(data.get("auto_decision")))
            self.assertEqual(int(data.get("decision_code") or 0), 200)
            self.assertEqual(called["n"], 1)
        finally:
            svc._decision_entry_impl = old

    def test_signals_v1_forces_observe_when_bar_not_closed(self) -> None:
        old = svc._decision_entry_impl
        called = {"n": 0}

        def _stub_decision(_dreq):
            called["n"] += 1
            return {"ok": True, "decision": "observe"}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="freqtrade",
                pair="BTC/USDC",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=False,
                strategy_id="Strategy005",
                strategy_version="1.0.0",
                group_id="test",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )
            client = svc.app.test_client()
            r = client.post("/signals/v1", json={"signal": payload, "trigger_decision": True})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(bool(data.get("ok")))
            self.assertFalse(bool(data.get("trigger_decision")))
            self.assertEqual(str(data.get("action") or ""), "observe")
            self.assertEqual(called["n"], 0)
        finally:
            svc._decision_entry_impl = old

    def test_http_v1_bar_closed_false_blocks_decision(self) -> None:
        old = svc._decision_entry_impl

        def _stub_decision(dreq):
            return {"ok": True, "stub": True}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            client = svc.app.test_client()
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="freqtrade",
                pair="BTC/USDT:USDT",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=False,
                strategy_id="ManualSmoke",
                strategy_version="0.0.1",
                group_id="manual",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )
            r = client.post("/signals/v1", json={"signal": payload, "trigger_decision": True})
            self.assertEqual(r.status_code, 200)
            d = r.get_json()
            self.assertTrue(d.get("ok"))
            self.assertFalse(d.get("trigger_decision"))
            self.assertEqual(d.get("action"), "observe")
            self.assertFalse(bool(d.get("auto_decision")))
        finally:
            svc._decision_entry_impl = old

    def test_http_v1_dedup_and_upgrade(self) -> None:
        old = svc._decision_entry_impl

        def _stub_decision(dreq):
            return {"ok": True, "stub": True}, 200

        svc._decision_entry_impl = _stub_decision
        try:
            client = svc.app.test_client()
            bar_open_ms = int(time.time() // 3600 * 3600 * 1000)
            payload = svc._build_signal_schema_v1(
                venue="freqtrade",
                pair="BTC/USDT:USDT",
                side="long",
                action="open",
                timeframe="1h",
                bar_open_ms=bar_open_ms,
                bar_close_ms=bar_open_ms + 3600 * 1000,
                bar_closed=True,
                strategy_id="ManualSmoke",
                strategy_version="0.0.1",
                group_id="manual",
                feature_set_id="",
                tag="unit",
                confidence=0.5,
                features={},
            )

            r1 = client.post("/signals/v1", json={"signal": payload, "trigger_decision": True}).get_json()
            r2 = client.post("/signals/v1", json={"signal": payload, "trigger_decision": True}).get_json()
            self.assertTrue(r1.get("ok"))
            self.assertTrue(r2.get("ok"))
            self.assertEqual(r1.get("id"), r2.get("id"))

            payload2 = dict(payload)
            payload2["tag"] = "upgrade"
            r3 = client.post("/signals/v1", json={"signal": payload2, "trigger_decision": False}).get_json()
            r4 = client.post("/signals/v1", json={"signal": payload2, "trigger_decision": True}).get_json()
            self.assertTrue(r3.get("ok"))
            self.assertTrue(r4.get("ok"))
            self.assertEqual(r3.get("id"), r4.get("id"))
            self.assertTrue(r4.get("auto_decision"))
            self.assertEqual(r4.get("decision_code"), 200)
        finally:
            svc._decision_entry_impl = old

    def test_strategy_tier_c_forces_shadow_and_dry_run(self) -> None:
        old_score = svc._score
        old_calibrate = svc._calibrate
        old_get_entry = svc._strategy_registry_get_entry
        old_live_allowed = svc._strategy_live_trading_allowed
        old_archive_event = svc._archive_event
        old_archive_order = svc._archive_order
        try:
            svc.CONFIG["dry_run"] = False
            svc.CONFIG["live_trading_enabled"] = True
            svc.CONFIG["strategy_live_trading_enabled"] = True
            svc.CONFIG["serving_shadow_mode"] = False
            svc.CONFIG["serving_canary_enabled"] = False
            svc.CONFIG["strategy_tier_trading_enabled"] = True
            svc.CONFIG["strategy_tier_default"] = "C"

            svc._score = lambda _features, _side=None: 1.0
            svc._calibrate = lambda _p, _features=None, _regime=None: 1.0
            svc._strategy_registry_get_entry = lambda _sid, _scope: {}
            svc._strategy_live_trading_allowed = lambda *_args, **_kwargs: True
            svc._archive_event = lambda *_args, **_kwargs: None
            svc._archive_order = lambda *_args, **_kwargs: None

            ts0 = int(time.time() * 1000)
            svc.EVENTS["evt_tier_c"] = {
                "id": "evt_tier_c",
                "event_id": "evt_tier_c",
                "pair": "BTC-PERP",
                "side": "long",
                "tag": "unit",
                "features": {"close": 40000},
                "strategy_features": {"close": 40000},
                "market_features": {},
                "ts": ts0,
                "ingested_ms": ts0,
                "bar_closed": True,
                "action": "open",
                "strategy_id": "Strategy005",
                "strategy_version": "1.0.0",
                "group_id": "test",
                "feature_set_id": "",
                "source": "unit",
            }

            out, code = svc._decision_entry_impl({
                "event_id": "evt_tier_c",
                "pair": "BTC-PERP",
                "side": "long",
                "tag": "unit",
                "features": {"close": 40000},
                "threshold": 0.5,
                "size": 10,
                "ts": ts0,
            })
            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("decision"), "observe")
            self.assertEqual(out.get("reason"), "tier_shadow")
            self.assertEqual(out.get("tier"), "C")
            self.assertTrue(bool(out.get("order_id")))

            oid = str(out.get("order_id"))
            od = svc.ORDERS.get(oid) or {}
            self.assertEqual(od.get("entry_type"), "shadow")
            self.assertEqual(od.get("mode"), "dry-run")
            self.assertEqual(od.get("tier"), "C")
        finally:
            svc._score = old_score
            svc._calibrate = old_calibrate
            svc._strategy_registry_get_entry = old_get_entry
            svc._strategy_live_trading_allowed = old_live_allowed
            svc._archive_event = old_archive_event
            svc._archive_order = old_archive_order

    def test_strategy_tier_b_forces_canary_pair_whitelist(self) -> None:
        old_score = svc._score
        old_calibrate = svc._calibrate
        old_get_entry = svc._strategy_registry_get_entry
        old_live_allowed = svc._strategy_live_trading_allowed
        old_archive_event = svc._archive_event
        old_archive_order = svc._archive_order
        try:
            svc.CONFIG["dry_run"] = False
            svc.CONFIG["live_trading_enabled"] = True
            svc.CONFIG["strategy_live_trading_enabled"] = True
            svc.CONFIG["serving_canary_enabled"] = False
            svc.CONFIG["serving_canary_pairs"] = ["BTC"]
            svc.CONFIG["strategy_tier_trading_enabled"] = True
            svc.CONFIG["strategy_tier_default"] = "B"

            svc._score = lambda _features, _side=None: 1.0
            svc._calibrate = lambda _p, _features=None, _regime=None: 1.0
            svc._strategy_registry_get_entry = lambda _sid, _scope: {}
            svc._strategy_live_trading_allowed = lambda *_args, **_kwargs: True
            svc._archive_event = lambda *_args, **_kwargs: None
            svc._archive_order = lambda *_args, **_kwargs: None

            ts0 = int(time.time() * 1000)
            svc.EVENTS["evt_tier_b"] = {
                "id": "evt_tier_b",
                "event_id": "evt_tier_b",
                "pair": "ETH-PERP",
                "side": "long",
                "tag": "unit",
                "features": {"close": 2000},
                "strategy_features": {"close": 2000},
                "market_features": {},
                "ts": ts0,
                "ingested_ms": ts0,
                "bar_closed": True,
                "action": "open",
                "strategy_id": "Strategy005",
                "strategy_version": "1.0.0",
                "group_id": "test",
                "feature_set_id": "",
                "source": "unit",
            }

            out, code = svc._decision_entry_impl({
                "event_id": "evt_tier_b",
                "pair": "ETH-PERP",
                "side": "long",
                "tag": "unit",
                "features": {"close": 2000},
                "threshold": 0.5,
                "size": 10,
                "ts": ts0,
            })

            self.assertEqual(code, 200)
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("decision"), "hold")
            self.assertEqual(out.get("reason"), "canary_pair_not_whitelisted")
            self.assertEqual(out.get("tier"), "B")
        finally:
            svc._score = old_score
            svc._calibrate = old_calibrate
            svc._strategy_registry_get_entry = old_get_entry
            svc._strategy_live_trading_allowed = old_live_allowed
            svc._archive_event = old_archive_event
            svc._archive_order = old_archive_order


class TestSignalIngestSyntheticEventFields(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_config = dict(svc.CONFIG)
        try:
            svc.EVENTS.clear()
        except Exception:
            pass

    def tearDown(self) -> None:
        try:
            svc.CONFIG.clear()
            svc.CONFIG.update(self._orig_config)
        except Exception:
            pass
        try:
            svc.EVENTS.clear()
        except Exception:
            pass

    def test_ensure_trace_event_sets_book_id_from_ab_owner(self) -> None:
        svc.CONFIG["three_screen_phase"] = 1
        svc.CONFIG["three_screen_phase0_force_ab_owner_strategy"] = True
        order = {
            "id": "o1",
            "event_id": "e1",
            "pair": "BTC-PERP",
            "side": "long",
            "action": "open",
            "tag": "unit",
            "mode": "real",
            "ab_owner": "quant",
            "system_id": "quant",
        }
        svc._ensure_trace_event_for_order("sig_unit_1", order=order, strategy_id="quant_pairs_btcalt")
        evt = svc.EVENTS.get("sig_unit_1") if isinstance(getattr(svc, "EVENTS", None), dict) else None
        self.assertTrue(isinstance(evt, dict))
        self.assertEqual(str(evt.get("ab_owner")), "quant")
        self.assertEqual(str(evt.get("system_id")), "quant")
        self.assertEqual(str(evt.get("book_id")), "quant")

    def test_ensure_trace_event_three_screen_phase0_uses_strategy_book(self) -> None:
        svc.CONFIG["three_screen_phase"] = 0
        svc.CONFIG["three_screen_phase0_force_ab_owner_strategy"] = True
        order = {
            "id": "o2",
            "event_id": "e2",
            "pair": "BTC-PERP",
            "side": "long",
            "action": "open",
            "tag": "ThreeScreen",
            "mode": "real",
            "ab_owner": "three_screen",
            "system_id": "three_screen",
        }
        svc._ensure_trace_event_for_order("sig_unit_2", order=order, strategy_id="ThreeScreen")
        evt = svc.EVENTS.get("sig_unit_2") if isinstance(getattr(svc, "EVENTS", None), dict) else None
        self.assertTrue(isinstance(evt, dict))
        self.assertEqual(str(evt.get("ab_owner")), "strategy")
        self.assertEqual(str(evt.get("system_id")), "strategy")
        self.assertEqual(str(evt.get("book_id")), "strategy")


if __name__ == "__main__":
    unittest.main()

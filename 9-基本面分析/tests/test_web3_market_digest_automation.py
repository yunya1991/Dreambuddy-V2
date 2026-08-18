import json
import unittest
import os
import pytest


if str(os.getenv("RUN_SLOW_TESTS", "0")).strip() != "1":
    pytestmark = pytest.mark.skip(reason="set RUN_SLOW_TESTS=1 to run slow digest automation tests")
else:
    pytestmark = pytest.mark.slow


class TestWeb3MarketDigestAutomation(unittest.TestCase):
    def test_web3_market_digest_run_builds_thread_and_enqueues(self) -> None:
        import ml_trade_service as svc

        orig_rank = getattr(svc, "_skill_binance_web3_crypto_market_rank", None)
        orig_token = getattr(svc, "_skill_binance_web3_query_token_info", None)
        orig_addr = getattr(svc, "_skill_binance_web3_query_address_info", None)
        orig_llm = getattr(svc, "_agent_llm_chat", None)
        orig_outbox = getattr(svc, "_agent_outbox_append_jsonl", None)
        orig_enqueue = getattr(svc, "_twitter_thread_publish_request_enqueue", None)
        orig_rl = getattr(svc, "_twitter_rate_limit_reasons", None)

        def _rank_stub(inp):
            return {
                "ok": True,
                "ranks": {
                    "trending": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa"}],
                    "top_search": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa"}],
                    "smart_money_inflow": [{"tokenName": "BBB/USDT", "ca": "0xbbb"}],
                    "top_traders_pnl": [{"address": "0x222", "addressLabel": "top_trader_1", "realizedPnl": 123.0}],
                },
                "priority": ["smart_money_inflow", "trending"],
            }

        def _token_stub(inp):
            ca = str((inp or {}).get("contractAddress") or "").strip().lower()
            if ca == "0xbbb":
                sym = "BBB"
                liq = 35_000_000
                vol = 12_000_000
                chg = 2.5
            else:
                sym = str((inp or {}).get("keyword") or "AAA").strip().upper() or "AAA"
                liq = 30_000_000
                vol = 10_000_000
                chg = 5.0
                ca = "0xaaa"
            return {
                "ok": True,
                "found": True,
                "token": {"symbol": sym, "chainId": "56", "contractAddress": ca},
                "market": {"liquidity": liq, "volume24h": vol, "percentChange24h": chg, "holders": 12345},
            }

        def _addr_stub(inp):
            return {
                "ok": True,
                "summary": {"address": (inp or {}).get("address"), "chainId": (inp or {}).get("chainId")},
                "positions": [{"contractAddress": "0xaaa", "valueUsd_est": 1000.0, "remainQty": 1.0}],
            }

        def _llm_stub(*, provider, model, messages, timeout_sec=30, **kwargs):
            _ = (provider, model, messages, timeout_sec, kwargs)
            content = json.dumps(
                {
                    "confidence": 0.9,
                    "regime": "flow_driven",
                    "summary": "Flows converging with attention on AAA/BBB.",
                    "watchlist": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa", "reason": "overlap", "risk": "volatility", "invalidations": ["liquidity drops"]}],
                    "risk_alerts": ["Thin liquidity risk for small caps."],
                    "actions": ["Monitor overlap tokens with sufficient liquidity."],
                    "tweets": ["t1", "t2", "t3", "t4"],
                }
            )
            return {"ok": True, "data": {"message": {"content": content}}}

        enqueued = {}

        def _enqueue_stub(*, trace_id, tweets, idempotency_key, ttl_sec, refs, intent_level):
            enqueued["trace_id"] = trace_id
            enqueued["tweets"] = list(tweets)
            enqueued["idempotency_key"] = idempotency_key
            enqueued["ttl_sec"] = ttl_sec
            enqueued["refs"] = dict(refs or {})
            enqueued["intent_level"] = intent_level
            return {"id": "evt1", "event": {"type": "twitter.thread.publish.request"}, "ts": 1}

        def _outbox_stub(*args, **kwargs):
            _ = (args, kwargs)
            return None

        try:
            svc._skill_binance_web3_crypto_market_rank = _rank_stub
            svc._skill_binance_web3_query_token_info = _token_stub
            svc._skill_binance_web3_query_address_info = _addr_stub
            svc._agent_llm_chat = _llm_stub
            svc._agent_outbox_append_jsonl = _outbox_stub
            svc._twitter_thread_publish_request_enqueue = _enqueue_stub
            svc._twitter_rate_limit_reasons = lambda: []

            svc.AUTOMATION["enable_web3_market_digest"] = True
            svc.AUTOMATION["web3_market_digest_period_sec"] = 300
            svc.AUTOMATION["web3_market_digest_chain_id"] = "56"
            svc.AUTOMATION["web3_market_digest_rank_limit"] = 10
            svc.AUTOMATION["web3_market_digest_candidates_max"] = 20
            svc.AUTOMATION["web3_market_digest_min_overlap_sources"] = 1
            svc.AUTOMATION["web3_market_digest_liquidity_floor_usd"] = 1_000_000
            svc.AUTOMATION["web3_market_digest_volume24h_floor_usd"] = 1_000_000
            svc.AUTOMATION["web3_market_digest_watch_addresses"] = [{"tag": "whale1", "address": "0x111", "chainId": "56"}]
            svc.AUTOMATION["web3_market_digest_llm_enabled"] = True
            svc.AUTOMATION["web3_market_digest_confidence_threshold"] = 0.6
            svc.AUTOMATION["web3_market_digest_thread_ttl_sec"] = 1800

            svc.CONFIG["agent_push"] = {"twitter_enabled": True, "twitter_llm_provider": "ollama", "twitter_llm_model": "unit"}

            rep = svc._automation_web3_market_digest_run(1_700_000_000_000, force=True, trigger_event="unit_test", source="unit_test")
            self.assertTrue(bool(rep.get("ok")))
            d = rep.get("digest") if isinstance(rep.get("digest"), dict) else {}
            self.assertEqual(str(d.get("kind") or ""), "web3.market_digest")
            self.assertTrue(isinstance(d.get("tweets"), list))
            dv1 = d.get("digest_v1") if isinstance(d.get("digest_v1"), dict) else {}
            self.assertEqual(str(dv1.get("schema") or ""), "web3_market_digest_v1")
            self.assertTrue(isinstance((dv1.get("thread") if isinstance(dv1.get("thread"), dict) else {}).get("tweets"), list))
            factors = d.get("factors") if isinstance(d.get("factors"), dict) else {}
            cmr = factors.get("crypto_market_rank") if isinstance(factors.get("crypto_market_rank"), dict) else {}
            self.assertTrue(isinstance(cmr.get("attention_factors"), dict))
            self.assertTrue(isinstance(cmr.get("flow_factors"), dict))
            self.assertTrue(isinstance(cmr.get("top_trader_factors"), dict))
            qti = factors.get("query_token_info") if isinstance(factors.get("query_token_info"), dict) else {}
            toks = qti.get("tokens") if isinstance(qti.get("tokens"), list) else []
            self.assertTrue(len(toks) >= 1)
            self.assertTrue(isinstance((toks[0] if toks else {}).get("metadata"), dict))
            self.assertTrue(isinstance((toks[0] if toks else {}).get("market"), dict))
            wa = d.get("watch_addresses") if isinstance(d.get("watch_addresses"), list) else []
            self.assertTrue(any(isinstance(x, dict) and str(x.get("address") or "").lower() == "0x222" for x in wa))
            self.assertTrue(len(enqueued.get("tweets") or []) >= 3)
            self.assertEqual(str(enqueued.get("intent_level") or ""), "L2")
        finally:
            if orig_rank is not None:
                svc._skill_binance_web3_crypto_market_rank = orig_rank
            if orig_token is not None:
                svc._skill_binance_web3_query_token_info = orig_token
            if orig_addr is not None:
                svc._skill_binance_web3_query_address_info = orig_addr
            if orig_llm is not None:
                svc._agent_llm_chat = orig_llm
            if orig_outbox is not None:
                svc._agent_outbox_append_jsonl = orig_outbox
            if orig_enqueue is not None:
                svc._twitter_thread_publish_request_enqueue = orig_enqueue
            if orig_rl is not None:
                svc._twitter_rate_limit_reasons = orig_rl

    def test_auto_trade_decisions_emit_calibrated_scoring_and_score_outbox(self) -> None:
        import ml_trade_service as svc

        orig_recent = getattr(svc, "_web3_market_digest_recent_digests_from_outbox", None)
        orig_outbox = getattr(svc, "_agent_outbox_append_jsonl", None)
        captured = []

        def _recent_stub(*, now_ms, lookback_sec):
            _ = (now_ms, lookback_sec)
            h1 = {
                "ts": 1_700_000_000_000,
                "regime_guess": "flow_driven",
                "digest_v1": {
                    "snapshot": {"regime": "flow_driven"},
                    "rankings": {"smart_money_inflow": [{"tokenName": "AAA/USDT"}], "trending": [{"symbol": "AAA"}], "top_search": [{"symbol": "AAA"}]},
                    "candidates": {"C2": [{"symbol": "AAA", "contractAddress": "0xaaa", "chainId": "56"}]},
                    "token_info": [{"symbol": "AAA", "contractAddress": "0xaaa", "liquidity_usd": 30_000_000, "volume24h_usd": 10_000_000}],
                    "constraints": {"min_liquidity_usd": 20_000_000, "min_volume24h_usd": 5_000_000},
                    "address_insights": [],
                },
            }
            h2 = {
                "ts": 1_700_000_000_000 + 2_000_000,
                "regime_guess": "flow_driven",
                "digest_v1": {
                    "snapshot": {"regime": "flow_driven"},
                    "rankings": {"smart_money_inflow": [{"tokenName": "AAA/USDT"}], "trending": [{"symbol": "AAA"}], "top_search": [{"symbol": "AAA"}]},
                    "candidates": {"C2": [{"symbol": "AAA", "contractAddress": "0xaaa", "chainId": "56"}]},
                    "token_info": [{"symbol": "AAA", "contractAddress": "0xaaa", "liquidity_usd": 31_000_000, "volume24h_usd": 10_500_000}],
                    "constraints": {"min_liquidity_usd": 20_000_000, "min_volume24h_usd": 5_000_000},
                    "address_insights": [],
                },
            }
            return [h2, h1]

        def _outbox_stub(name, payload):
            captured.append((name, payload))
            return None

        try:
            svc._web3_market_digest_recent_digests_from_outbox = _recent_stub
            svc._agent_outbox_append_jsonl = _outbox_stub
            digest = {
                "ts": 1_700_000_000_000 + 4_000_000,
                "regime_guess": "flow_driven",
                "digest_v1": {
                    "snapshot": {"regime": "flow_driven"},
                    "thread": {"tweets": ["a", "b"]},
                    "constraints": {"min_liquidity_usd": 20_000_000, "min_volume24h_usd": 5_000_000, "max_slippage_bps": 300, "max_position_pct": 0.05},
                    "rankings": {"smart_money_inflow": [{"tokenName": "AAA/USDT"}], "trending": [{"symbol": "AAA"}], "top_search": [{"symbol": "AAA"}]},
                    "candidates": {"C2": [{"symbol": "AAA", "contractAddress": "0xaaa", "chainId": "56", "reason": "overlap", "risk": "", "invalidations": ["liq_drop"]}]},
                    "token_info": [{"symbol": "AAA", "contractAddress": "0xaaa", "liquidity_usd": 32_000_000, "volume24h_usd": 11_000_000}],
                    "address_insights": [],
                },
            }
            n = svc._auto_trade_emit_decisions_from_digest(trace_id="t1", ts_ms=1_700_000_000_000 + 4_000_000, chain_id="56", digest=digest)
            self.assertGreaterEqual(int(n), 1)
            decision_rows = [p for (nm, p) in captured if str(nm) == svc._auto_trade_decision_outbox_name()]
            score_rows = [p for (nm, p) in captured if str(nm) == "trade_decision_scores.jsonl"]
            self.assertGreaterEqual(len(decision_rows), 1)
            self.assertGreaterEqual(len(score_rows), 1)
            sc = (decision_rows[0] if isinstance(decision_rows[0], dict) else {}).get("scoring") if decision_rows else {}
            self.assertTrue(isinstance(sc, dict))
            self.assertTrue("calibrated_prob" in sc)
            ci = sc.get("confidence_interval") if isinstance(sc, dict) else {}
            self.assertTrue(isinstance(ci, dict))
            self.assertTrue("low" in ci and "high" in ci)
        finally:
            if orig_recent is not None:
                svc._web3_market_digest_recent_digests_from_outbox = orig_recent
            if orig_outbox is not None:
                svc._agent_outbox_append_jsonl = orig_outbox

    def test_web3_market_digest_keeps_top10_watch_addresses_and_tweet_displays_top3(self) -> None:
        import ml_trade_service as svc

        orig_rank = getattr(svc, "_skill_binance_web3_crypto_market_rank", None)
        orig_token = getattr(svc, "_skill_binance_web3_query_token_info", None)
        orig_addr = getattr(svc, "_skill_binance_web3_query_address_info", None)
        orig_llm = getattr(svc, "_agent_llm_chat", None)
        orig_outbox = getattr(svc, "_agent_outbox_append_jsonl", None)
        orig_enqueue = getattr(svc, "_twitter_thread_publish_request_enqueue", None)
        orig_rl = getattr(svc, "_twitter_rate_limit_reasons", None)

        def _rank_stub(inp):
            _ = inp
            traders = []
            for i in range(12):
                traders.append({
                    "address": f"0x{i:040x}",
                    "addressLabel": f"trader_{i+1}",
                    "realizedPnl": 1000 + i,
                    "winRate": 0.6,
                })
            return {
                "ok": True,
                "ranks": {
                    "trending": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa"}],
                    "top_search": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa"}],
                    "smart_money_inflow": [{"tokenName": "AAA/USDT", "ca": "0xaaa"}],
                    "top_traders_pnl": traders,
                },
                "priority": ["smart_money_inflow", "trending"],
            }

        def _token_stub(inp):
            _ = inp
            return {
                "ok": True,
                "found": True,
                "token": {"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa"},
                "market": {"liquidity": 30_000_000, "volume24h": 10_000_000, "percentChange24h": 2.5, "holders": 10000},
            }

        def _addr_stub(inp):
            addr = str((inp or {}).get("address") or "").strip().lower()
            k = int(addr[-1], 16) if addr else 0
            return {
                "ok": True,
                "summary": {"address": (inp or {}).get("address"), "chainId": (inp or {}).get("chainId")},
                "positions": [
                    {"contractAddress": "0xaaa", "valueUsd_est": 30000 - 1000 * k, "remainQty": 1.0},
                    {"contractAddress": "0xbbb", "valueUsd_est": 20000 - 500 * k, "remainQty": 1.0},
                    {"contractAddress": "0xccc", "valueUsd_est": 10000 - 300 * k, "remainQty": 1.0},
                ],
            }

        def _llm_stub(*, provider, model, messages, timeout_sec=30, **kwargs):
            _ = (provider, model, messages, timeout_sec, kwargs)
            content = json.dumps(
                {
                    "confidence": 0.9,
                    "regime": "flow_driven",
                    "summary": "ok",
                    "watchlist": [{"symbol": "AAA", "chainId": "56", "contractAddress": "0xaaa", "reason": "overlap", "risk": "", "invalidations": ["liq_drop"]}],
                    "risk_alerts": [],
                    "actions": [],
                    "tweets": ["t1", "t2", "t3", "t4"],
                }
            )
            return {"ok": True, "data": {"message": {"content": content}}}

        captured = []

        def _outbox_stub(name, payload):
            captured.append((name, payload))
            return None

        try:
            svc._skill_binance_web3_crypto_market_rank = _rank_stub
            svc._skill_binance_web3_query_token_info = _token_stub
            svc._skill_binance_web3_query_address_info = _addr_stub
            svc._agent_llm_chat = _llm_stub
            svc._agent_outbox_append_jsonl = _outbox_stub
            svc._twitter_thread_publish_request_enqueue = lambda **kwargs: {"id": "evt1", "event": {"type": "twitter.thread.publish.request"}, "ts": 1}
            svc._twitter_rate_limit_reasons = lambda: []
            svc.AUTOMATION["enable_web3_market_digest"] = True
            svc.AUTOMATION["web3_market_digest_chain_id"] = "56"
            svc.AUTOMATION["web3_market_digest_rank_limit"] = 12
            svc.AUTOMATION["web3_market_digest_top_trader_watch_n"] = 10
            svc.AUTOMATION["web3_market_digest_top_trader_display_n"] = 3
            svc.AUTOMATION["web3_market_digest_liquidity_floor_usd"] = 1_000_000
            svc.AUTOMATION["web3_market_digest_volume24h_floor_usd"] = 1_000_000
            svc.AUTOMATION["web3_market_digest_watch_addresses"] = []
            svc.AUTOMATION["web3_market_digest_llm_enabled"] = True
            svc.CONFIG["agent_push"] = {"twitter_enabled": True, "twitter_llm_provider": "ollama", "twitter_llm_model": "unit"}
            rep = svc._automation_web3_market_digest_run(1_700_100_000_000, force=True, trigger_event="unit_test_top10", source="unit_test")
            self.assertTrue(bool(rep.get("ok")))
            d = rep.get("digest") if isinstance(rep.get("digest"), dict) else {}
            wa = d.get("watch_addresses") if isinstance(d.get("watch_addresses"), list) else []
            top_traders = [x for x in wa if isinstance(x, dict) and str(x.get("source") or "") == "top_traders_pnl"]
            self.assertGreaterEqual(len(top_traders), 10)
            tws = d.get("tweets") if isinstance(d.get("tweets"), list) else []
            tw5 = ""
            for t in tws:
                if isinstance(t, str) and "Tweet 5/6" in t:
                    tw5 = t
                    break
            self.assertIn("Watch addresses: ", tw5)
            self.assertIn("holdings top3", tw5)
        finally:
            if orig_rank is not None:
                svc._skill_binance_web3_crypto_market_rank = orig_rank
            if orig_token is not None:
                svc._skill_binance_web3_query_token_info = orig_token
            if orig_addr is not None:
                svc._skill_binance_web3_query_address_info = orig_addr
            if orig_llm is not None:
                svc._agent_llm_chat = orig_llm
            if orig_outbox is not None:
                svc._agent_outbox_append_jsonl = orig_outbox
            if orig_enqueue is not None:
                svc._twitter_thread_publish_request_enqueue = orig_enqueue
            if orig_rl is not None:
                svc._twitter_rate_limit_reasons = orig_rl

    def test_recommend_buy_signal_executes_and_precheck_blocks_untradeable(self) -> None:
        import ml_trade_service as svc

        orig_outbox = getattr(svc, "_agent_outbox_append_jsonl", None)
        orig_trade = getattr(svc, "_skill_binance_spot_trade", None)
        orig_audit = getattr(svc, "_skill_binance_web3_query_token_audit", None)
        orig_tradeable = getattr(svc, "_skill_binance_web3_token_tradeable_check", None)
        orig_cfg = getattr(svc, "_agent_skill_binance_spot_cfg", None)
        orig_key = getattr(svc, "_binance_spot_skill_api_key", None)
        orig_sec = getattr(svc, "_binance_spot_skill_secret", None)
        captured = []
        bak_auto = dict(svc.AUTOMATION)
        bak_state = dict(svc.TRACKER_STATE.get("auto_trade") if isinstance(svc.TRACKER_STATE.get("auto_trade"), dict) else {})

        def _outbox_stub(name, payload):
            captured.append((str(name), dict(payload or {})))
            return None

        def _trade_stub(inp):
            _ = inp
            return {"ok": True, "result": {"orderId": "123", "executedQty": "10", "price": "1.0"}}

        def _audit_stub(inp):
            ca = str((inp or {}).get("contractAddress") or "").strip().lower()
            if ca == "0xbbb":
                return {"ok": True, "supported": True, "hasResult": True, "riskLevel": 5}
            return {"ok": True, "supported": True, "hasResult": True, "riskLevel": 1}

        def _tradeable_stub(inp):
            ca = str((inp or {}).get("contractAddress") or "").strip().lower()
            if ca == "0xbbb":
                return {"ok": True, "block": True}
            return {"ok": True, "block": False}

        try:
            svc._agent_outbox_append_jsonl = _outbox_stub
            svc._skill_binance_spot_trade = _trade_stub
            svc._skill_binance_web3_query_token_audit = _audit_stub
            svc._skill_binance_web3_token_tradeable_check = _tradeable_stub
            svc._agent_skill_binance_spot_cfg = lambda: {"enabled": True}
            svc._binance_spot_skill_api_key = lambda: "k"
            svc._binance_spot_skill_secret = lambda: "s"
            svc.AUTOMATION["auto_trade_enabled"] = True
            svc.AUTOMATION["auto_trade_mode"] = "auto"
            svc.AUTOMATION["auto_trade_env"] = "prod"
            svc.AUTOMATION["auto_trade_require_isolation"] = False
            svc.AUTOMATION["auto_trade_binance_spot_open_in_prod"] = True
            svc.AUTOMATION["auto_trade_binance_spot_enforce_min_prob"] = False
            svc.AUTOMATION["auto_trade_binance_spot_max_orders_per_run"] = 5
            svc.TRACKER_STATE["auto_trade"] = {}

            rows = [
                {
                    "decision_id": "d1",
                    "candidate": {"symbol": "AAA", "contractAddress": "0xaaa"},
                    "scoring": {"recommend_buy": True, "calibrated_prob": 0.61, "thresholds": {"prob_min_buy": 0.60}},
                },
                {
                    "decision_id": "d2",
                    "candidate": {"symbol": "BBB", "contractAddress": "0xbbb"},
                    "scoring": {"recommend_buy": True, "calibrated_prob": 0.80, "thresholds": {"prob_min_buy": 0.60}},
                },
            ]
            rep = svc._auto_trade_execute_binance_spot_from_decisions(trace_id="t_exec", ts_ms=1_700_000_000_000, chain_id="56", rows=rows)
            self.assertTrue(bool(rep.get("ok")))
            self.assertEqual(int(rep.get("attempted") or 0), 1)
            self.assertEqual(int(rep.get("executed") or 0), 1)
            prechecks = [p for (n, p) in captured if n == "trade_prechecks.jsonl"]
            intents = [p for (n, p) in captured if n == "orders.jsonl" and str(p.get("type") or "") == "order.intent"]
            receipts = [p for (n, p) in captured if n == "orders.jsonl" and str(p.get("type") or "") == "order.receipt"]
            self.assertGreaterEqual(len(prechecks), 2)
            self.assertEqual(len(intents), 1)
            self.assertGreaterEqual(len(receipts), 1)
            self.assertTrue(any(str((p.get("gate") if isinstance(p.get("gate"), dict) else {}).get("reason") or "") == "tradeable_block" for p in prechecks))
            self.assertTrue(any(str(r.get("status") or "") == "blocked" for r in (rep.get("receipts") if isinstance(rep.get("receipts"), list) else [])))
        finally:
            svc.AUTOMATION.clear()
            svc.AUTOMATION.update(bak_auto)
            svc.TRACKER_STATE["auto_trade"] = bak_state
            if orig_outbox is not None:
                svc._agent_outbox_append_jsonl = orig_outbox
            if orig_trade is not None:
                svc._skill_binance_spot_trade = orig_trade
            if orig_audit is not None:
                svc._skill_binance_web3_query_token_audit = orig_audit
            if orig_tradeable is not None:
                svc._skill_binance_web3_token_tradeable_check = orig_tradeable
            if orig_cfg is not None:
                svc._agent_skill_binance_spot_cfg = orig_cfg
            if orig_key is not None:
                svc._binance_spot_skill_api_key = orig_key
            if orig_sec is not None:
                svc._binance_spot_skill_secret = orig_sec

    def test_live_toggle_requires_password(self) -> None:
        import ml_trade_service as svc
        import os

        orig_gov = getattr(svc, "_governance_write_auth_ok", None)
        orig_is_local = getattr(svc, "_is_local_request", None)
        orig_approval = getattr(svc, "_governance_require_approval_or_error", None)
        orig_rb = getattr(svc, "_rollback_snapshot_append", None)
        orig_save = getattr(svc, "_save_config", None)
        bak_auto = dict(svc.AUTOMATION)

        try:
            svc._governance_write_auth_ok = lambda: True
            svc._is_local_request = lambda: True
            svc._governance_require_approval_or_error = lambda data, trace_id, action: (True, "appr1", {}, 200)
            svc._rollback_snapshot_append = lambda **kwargs: {"id": "rb1"}
            svc._save_config = lambda: None
            svc.AUTOMATION["auto_trade_enabled"] = False
            svc.AUTOMATION["auto_trade_enable_password_required"] = True

            os.environ["AUTO_TRADE_ENABLE_PASSWORD"] = "pw1"
            os.environ["CONFIG_TOKEN"] = "ct1"

            c = svc.app.test_client()
            r1 = c.post("/automation/config", json={"trace_id": "t1", "confirm_live": True, "auto_trade_enabled": True})
            self.assertEqual(int(r1.status_code), 400)
            r2 = c.post("/automation/config", json={"trace_id": "t2", "confirm_live": True, "auto_trade_enabled": True, "auto_trade_enable_password": "bad"})
            self.assertEqual(int(r2.status_code), 400)
            r3 = c.post("/automation/config", json={"trace_id": "t3", "confirm_live": True, "auto_trade_enabled": True, "auto_trade_enable_password": "pw1"})
            self.assertEqual(int(r3.status_code), 200)
        finally:
            svc.AUTOMATION.clear()
            svc.AUTOMATION.update(bak_auto)
            try:
                os.environ.pop("AUTO_TRADE_ENABLE_PASSWORD", None)
                os.environ.pop("CONFIG_TOKEN", None)
            except Exception:
                pass
            if orig_gov is not None:
                svc._governance_write_auth_ok = orig_gov
            if orig_is_local is not None:
                svc._is_local_request = orig_is_local
            if orig_approval is not None:
                svc._governance_require_approval_or_error = orig_approval
            if orig_rb is not None:
                svc._rollback_snapshot_append = orig_rb
            if orig_save is not None:
                svc._save_config = orig_save


if __name__ == "__main__":
    unittest.main()

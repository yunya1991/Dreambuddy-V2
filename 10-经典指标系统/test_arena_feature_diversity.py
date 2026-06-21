import unittest

import os
import json
import math
import tempfile


import ml_trade_service as svc


class TestArenaEntryGate(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_elastic_state = dict(getattr(svc, "ELASTIC_STATE", {}))

        svc.CONFIG.update({
            "arena_entry_min_votes": 3,
            "arena_entry_min_weight_sum": 0.55,
            "arena_entry_weight_sum_floor_votes": 2,
            "arena_entry_vote_eligible_only": True,
            "arena_capital_floor_u": 0.0,
            "elastic_gating_enabled": False,
            "elastic_vote_rule": "auto",
        })
        try:
            svc.ELASTIC_STATE.clear()
            svc.ELASTIC_STATE.update({"by_group": {}})
        except Exception:
            pass

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.ELASTIC_STATE.clear()
            svc.ELASTIC_STATE.update(self._orig_elastic_state)
        except Exception:
            pass

    def test_no_models_considered_returns_not_ok(self):
        arena_evt = {"models": {"A": "not_a_dict"}}
        out = svc._arena_entry_gate(arena_evt)
        self.assertFalse(bool(out.get("ok")))
        self.assertFalse(bool(out.get("pass")))
        self.assertEqual(out.get("reason"), "no_models_considered")

    def test_eligible_only_falls_back_to_non_eligible(self):
        arena_evt = {
            "models": {
                "A": {"eligible": False, "capital_u": 100.0, "take": True, "weight": 0.3},
                "B": {"eligible": False, "capital_u": 100.0, "take": True, "weight": 0.3},
            }
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("pass")))
        self.assertEqual(int(out.get("n_models_considered") or 0), 2)

    def test_vote_rule_switches_to_2of5_for_tier_1(self):
        svc.CONFIG["elastic_gating_enabled"] = True

        arena_evt = {
            "elastic": {"tier": 1},
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.1},
                "B": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.1},
            },
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("vote_rule"), "2of5")
        self.assertTrue(bool(out.get("pass_votes")))

    def test_vote_rule_allows_1of5_only_for_explore(self):
        svc.CONFIG["elastic_gating_enabled"] = True

        arena_evt = {
            "elastic": {"tier": 0},
            "explore": True,
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.1},
            },
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("vote_rule"), "1of5")
        self.assertTrue(bool(out.get("pass_votes")))

    def test_vote_rule_switches_to_2of5_for_tier_2(self):
        svc.CONFIG["elastic_gating_enabled"] = True

        arena_evt = {
            "elastic": {"tier": 2},
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.1},
                "B": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.1},
            },
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("vote_rule"), "2of5")
        self.assertTrue(bool(out.get("pass_votes")))

    def test_weight_sum_path_can_pass_with_single_model(self):
        arena_evt = {
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.60},
            }
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("pass")))
        self.assertTrue(bool(out.get("pass_weight")))

    def test_threshold_override_uses_pc_field(self):
        arena_evt = {
            "threshold": 0.70,
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "pc": 0.71, "take": False, "weight": 0.1},
                "B": {"eligible": True, "capital_u": 100.0, "pc": 0.75, "take": False, "weight": 0.1},
            },
        }
        out = svc._arena_entry_gate(arena_evt)
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("pass")))


class TestArenaEffectiveFeatureKeys(unittest.TestCase):
    def setUp(self):
        self._orig_models = dict(svc.MODELS)
        self._orig_cache = dict(getattr(svc, "_ARENA_FEATURE_KEYS_CACHE", {}))
        self._orig_arena_model_family = svc._arena_model_family
        self._orig_eval_feature_keys = svc._eval_feature_keys
        self._orig_artifact_meta_for_name = svc._artifact_meta_for_name
        self._orig_resolve_feature_set_id_for_meta = svc._resolve_feature_set_id_for_meta
        self._orig_arena_find_model_key = svc._arena_find_model_key
        self._orig_arena_find_model_key_for_feature_set = svc._arena_find_model_key_for_feature_set

        svc.MODELS.clear()
        svc._ARENA_FEATURE_KEYS_CACHE.clear()

        svc._arena_model_family = lambda _name: "fam"
        svc._resolve_feature_set_id_for_meta = lambda feature_set_id, _meta: feature_set_id
        svc._artifact_meta_for_name = lambda _name: {"feature_keys": []}
        svc._arena_find_model_key_for_feature_set = lambda _tokens, _fsid: None

    def tearDown(self):
        svc.MODELS.clear()
        svc.MODELS.update(self._orig_models)
        svc._ARENA_FEATURE_KEYS_CACHE.clear()
        svc._ARENA_FEATURE_KEYS_CACHE.update(self._orig_cache)
        svc._arena_model_family = self._orig_arena_model_family
        svc._eval_feature_keys = self._orig_eval_feature_keys
        svc._artifact_meta_for_name = self._orig_artifact_meta_for_name
        svc._resolve_feature_set_id_for_meta = self._orig_resolve_feature_set_id_for_meta
        svc._arena_find_model_key = self._orig_arena_find_model_key
        svc._arena_find_model_key_for_feature_set = self._orig_arena_find_model_key_for_feature_set

    def test_effective_feature_keys_filters_by_preferred_keys(self):
        svc.MODELS["modelA"] = {"keys": ["a", "c"]}
        svc._eval_feature_keys = lambda _fam, _fsid: ["a", "b"]

        keys1 = svc._arena_effective_feature_keys("modelA", "fs1")
        self.assertEqual(keys1, ["a"])

        keys1.append("x")
        keys2 = svc._arena_effective_feature_keys("modelA", "fs1")
        self.assertEqual(keys2, ["a"])

    def test_effective_feature_keys_alias_resolves_model_key(self):
        svc.MODELS["nn_model"] = {"keys": ["k1", "k2"]}
        svc._arena_find_model_key_for_feature_set = lambda _cands, _fsid: "nn_model"
        svc._artifact_meta_for_name = lambda _name: {"feature_keys": ["k1", "k2", "k3"]}
        svc._eval_feature_keys = lambda _fam, _fsid: ["k1", "k3"]

        keys = svc._arena_effective_feature_keys("__nn__", "fsx")
        self.assertEqual(keys, ["k1"])


class TestAlignFeaturesAlias(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        svc.CONFIG["feature_set_keys"] = dict(svc.CONFIG.get("feature_set_keys") or {})
        svc.CONFIG["feature_set_keys"]["trend_4h_mtf_v1"] = [
            "rsi_d",
            "macd_d",
            "macdsignal_d",
            "atr_h",
            "ema_short_dist",
            "ema_long_dist",
            "donchian_upper_dist",
            "donchian_lower_dist",
            "donchian_mid_dist",
            "volume_ratio",
            "bb_width_ratio",
            "willr_d",
            "weekly_state",
            "btc_weekly_short_ok",
            "returns",
            "return_1",
        ]

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)

    def test_alias_fill_from_trend_fields(self):
        raw = {
            "rsi": 57.0,
            "macd": 0.12,
            "macdsignal": 0.09,
            "atr": 123.0,
            "ema_short_dist_pct": 0.01,
            "ema_long_dist_pct": -0.02,
            "donchian_upper_dist_pct": 0.03,
            "donchian_lower_dist_pct": -0.02,
            "volume": 200.0,
            "volume_mean": 100.0,
            "volatility": 0.22,
            "fastk": 80.0,
            "ema_1d_trend_up_1": 1.0,
        }
        out = svc._align_features("trend_4h_mtf_v1", raw)
        self.assertAlmostEqual(float(out.get("rsi_d")), 57.0, places=7)
        self.assertAlmostEqual(float(out.get("macd_d")), 0.12, places=7)
        self.assertAlmostEqual(float(out.get("macdsignal_d")), 0.09, places=7)
        self.assertAlmostEqual(float(out.get("atr_h")), 123.0, places=7)
        self.assertAlmostEqual(float(out.get("ema_short_dist")), 0.01, places=7)
        self.assertAlmostEqual(float(out.get("ema_long_dist")), -0.02, places=7)
        self.assertAlmostEqual(float(out.get("donchian_upper_dist")), 0.03, places=7)
        self.assertAlmostEqual(float(out.get("donchian_lower_dist")), -0.02, places=7)
        self.assertAlmostEqual(float(out.get("donchian_mid_dist")), 0.005, places=7)
        self.assertAlmostEqual(float(out.get("volume_ratio")), 2.0, places=7)
        self.assertAlmostEqual(float(out.get("bb_width_ratio")), 0.22, places=7)
        self.assertAlmostEqual(float(out.get("willr_d")), -20.0, places=7)
        self.assertAlmostEqual(float(out.get("weekly_state")), 1.0, places=7)
        self.assertAlmostEqual(float(out.get("btc_weekly_short_ok")), 0.0, places=7)


class TestArenaFeatureJaccard(unittest.TestCase):
    def setUp(self):
        self._orig = svc._arena_effective_feature_keys

    def tearDown(self):
        svc._arena_effective_feature_keys = self._orig

    def test_jaccard_basic(self):
        svc._arena_effective_feature_keys = lambda mid, _fsid: {
            "a": ["x", "y", "z"],
            "b": ["y", "z", "w"],
        }.get(str(mid), [])
        j = svc._arena_feature_jaccard("a", "b", "fs")
        self.assertAlmostEqual(j, 0.5, places=7)

    def test_jaccard_empty_returns_zero(self):
        svc._arena_effective_feature_keys = lambda _mid, _fsid: []
        j = svc._arena_feature_jaccard("a", "b", "fs")
        self.assertEqual(j, 0.0)


class TestArenaDiversityAntiCorrelationBonus(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_arena_state = dict(svc.ARENA_STATE)
        self._orig_corr_from_hist = svc._arena_corr_from_hist
        self._orig_feature_jaccard = svc._arena_feature_jaccard

        svc.ARENA_STATE.clear()
        svc.ARENA_STATE.update({"inited": True, "models": {}, "history": []})

        svc.CONFIG.update({
            "arena_select_method": "weight",
            "arena_use_capital_in_selection": False,
            "arena_capital_floor_u": 0.0,
            "arena_diversity_enabled": True,
            "arena_diversity_use_recent_count": False,
            "arena_diversity_recent_k": 0,
            "arena_diversity_lambda": 0.0,
            "arena_diversity_use_feature": False,
            "arena_diversity_feature_lambda": 0.0,
            "arena_diversity_use_corr": True,
            "arena_diversity_corr_metric": "edge",
            "arena_diversity_corr_window": 200,
            "arena_diversity_corr_min_overlap": 2,
            "arena_diversity_corr_start": 0.7,
            "arena_diversity_corr_use_abs": False,
            "arena_diversity_corr_lambda": 0.0,
            "arena_diversity_corr_anti_start": 0.2,
            "arena_diversity_corr_anti_lambda": 3.0,
            "arena_diversity_corr_anti_cap": 2.0,
            "arena_diversity_ref": "recent_top",
        })

        svc._arena_feature_jaccard = lambda *_args, **_kwargs: 0.0

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        svc.ARENA_STATE.clear()
        svc.ARENA_STATE.update(self._orig_arena_state)
        svc._arena_corr_from_hist = self._orig_corr_from_hist
        svc._arena_feature_jaccard = self._orig_feature_jaccard

    def test_anti_correlation_bonus_can_change_choice(self):
        svc.ARENA_STATE["history"] = [{"chosen": "A"}]

        def _stub_corr(hist, a, b, metric, window, min_overlap):
            if str(a) == "B" and str(b) == "A":
                return -0.9, 50
            return 0.0, 50

        svc._arena_corr_from_hist = _stub_corr

        arena_evt = {
            "feature_set_id": "fs",
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 1.0},
                "B": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 0.6},
            },
        }
        chosen, explore = svc._arena_choose_executor(arena_evt)
        self.assertEqual(chosen, "B")
        self.assertFalse(explore)
        div = svc.ARENA_STATE.get("diversity") or {}
        self.assertIn("corr_anti", div)


class TestQuantAutoBtcaltsTick(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig_universe_state = dict(getattr(svc, "UNIVERSE_STATE", {}))
        self._orig_status = svc.quant_pairs_btcalt_status
        self._orig_open = svc.execution_pairs_btcalt_market_open
        self._orig_close = svc.execution_pairs_btcalt_market_close
        self._orig_universe = svc._universe_btc_alt_candidates
        self._orig_build_universe = svc._build_universe_pipeline
        self._orig_macro_dir = svc._macro_btc_dir_snapshot
        self._orig_macro_shape = svc._entry_macro_btceth_shape_at

        svc.CONFIG.update({
            "quant_auto_enabled": True,
            "quant_auto_btcalts_enabled": True,
            "quant_auto_mode": "paper",
            "quant_auto_btcalts_max_open_pairs": 1,
            "quant_auto_btcalts_scan_n": 10,
            "quant_auto_btcalts_selector_topk": 3,
            "quant_auto_btcalts_cooldown_bars": 3,
            "quant_auto_btcalts_btc_hedge_frac": "",
            "quant_pairs_btcalt_notional_usdc": 123.0,
        })

        try:
            svc.TRACKER_STATE.clear()
        except Exception:
            pass
        svc.TRACKER_STATE.update({
            "quant_open_positions": {},
            "quant_auto_btcalts_cooldown": {},
        })

        try:
            svc.UNIVERSE_STATE.clear()
        except Exception:
            pass
        try:
            svc.UNIVERSE_STATE.update({"metadata": {"candidates": []}})
        except Exception:
            pass

        svc._build_universe_pipeline = lambda *_args, **_kwargs: None

        svc._macro_btc_dir_snapshot = lambda **_kw: {"ok": True, "dir": 0}
        svc._entry_macro_btceth_shape_at = lambda *_a, **_kw: {"ok": True, "valid": True, "shape": "neutral"}

        self._calls = {"open": [], "close": [], "status": []}

        def _stub_open():
            payload = svc.request.get_json(force=True) or {}
            self._calls["open"].append(payload)
            alt = str(payload.get("alt") or "").upper().strip()
            tag = str(payload.get("tag") or "quant_auto_btcalts")
            sid = str(payload.get("strategy_id") or "quant_auto_btcalts")
            op = svc.TRACKER_STATE.get("quant_open_positions")
            if not isinstance(op, dict):
                op = {}
                svc.TRACKER_STATE["quant_open_positions"] = op
            op["BTC-PERP"] = {"side": "long", "notional_usdc": 100.0, "strategy_id": sid, "tag": tag}
            if alt:
                op[f"{alt}-PERP"] = {"side": "short", "notional_usdc": 100.0, "strategy_id": sid, "tag": tag}
            return svc.jsonify({"ok": True, "payload": payload})

        def _stub_close():
            payload = svc.request.get_json(force=True) or {}
            self._calls["close"].append(payload)
            alt = str(payload.get("alt") or "").upper().strip()
            op = svc.TRACKER_STATE.get("quant_open_positions")
            if isinstance(op, dict):
                op.pop("BTC-PERP", None)
                if alt:
                    op.pop(f"{alt}-PERP", None)
            return svc.jsonify({"ok": True, "payload": payload})

        svc.execution_pairs_btcalt_market_open = _stub_open
        svc.execution_pairs_btcalt_market_close = _stub_close

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass
        try:
            svc.UNIVERSE_STATE.clear()
            svc.UNIVERSE_STATE.update(self._orig_universe_state)
        except Exception:
            pass
        svc.quant_pairs_btcalt_status = self._orig_status
        svc.execution_pairs_btcalt_market_open = self._orig_open
        svc.execution_pairs_btcalt_market_close = self._orig_close
        svc._universe_btc_alt_candidates = self._orig_universe
        svc._build_universe_pipeline = self._orig_build_universe
        svc._macro_btc_dir_snapshot = self._orig_macro_dir
        svc._entry_macro_btceth_shape_at = self._orig_macro_shape

    def test_open_ignores_other_quant_positions_when_btcalts_capacity_allows(self):
        svc.TRACKER_STATE["quant_open_positions"].update({
            "SOL-PERP": {"side": "long", "notional_usdc": 50.0, "strategy_id": "other", "tag": "other"},
        })

        svc._universe_btc_alt_candidates = lambda: ["ETH", "XRP"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            score = 1.0 if alt == "ETH" else 2.0
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": score},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": score}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(out.get("decision", {}).get("alt"), "XRP")
        self.assertEqual(len(self._calls["open"]), 1)
        self.assertEqual(str(self._calls["open"][0].get("alt") or "").upper().strip(), "XRP")

    def test_exit_sets_cooldown_after_successful_close(self):
        svc.TRACKER_STATE["quant_open_positions"].update({
            "BTC-PERP": {"side": "short", "notional_usdc": 100.0, "strategy_id": "quant_auto_btcalts", "tag": "quant_auto_btcalts|g"},
            "ETH-PERP": {"side": "long", "notional_usdc": 100.0, "strategy_id": "quant_auto_btcalts", "tag": "quant_auto_btcalts|g"},
        })

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({"ok": True, "alt": alt, "action": "exit", "latest": {"z": 0.0}})

        svc.quant_pairs_btcalt_status = _stub_status

        now_ms = 1700000000000
        out = svc._quant_auto_btcalts_tick(now_ms=now_ms)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "exit")
        self.assertEqual(len(self._calls["close"]), 1)
        cd = svc.TRACKER_STATE.get("quant_auto_btcalts_cooldown") or {}
        self.assertTrue(int(cd.get("ETH") or 0) > int(now_ms))

    def test_cooldown_skips_candidate(self):
        svc._universe_btc_alt_candidates = lambda: ["ETH", "XRP"]
        svc.TRACKER_STATE["quant_auto_btcalts_cooldown"]["ETH"] = 1700000000000 + 3600_000

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            score = 10.0 if alt == "ETH" else 1.0
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": score},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": score}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(out.get("decision", {}).get("alt"), "XRP")
        self.assertEqual(len(self._calls["open"]), 1)
        self.assertEqual(str(self._calls["open"][0].get("alt") or "").upper().strip(), "XRP")

    def test_selector_topk_prefers_higher_corr_within_topk(self):
        svc._universe_btc_alt_candidates = lambda: ["A", "B", "C"]
        svc.CONFIG["quant_auto_btcalts_selector_topk"] = 3

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            z_map = {"A": 3.0, "B": 2.0, "C": 1.0}
            corr_map = {"A": 0.2, "B": 0.9, "C": 0.1}
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": z_map.get(alt, 0.0), "corr": corr_map.get(alt, 0.0)},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": z_map.get(alt, 0.0)}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(out.get("decision", {}).get("alt"), "B")
        self.assertEqual(len(self._calls["open"]), 1)
        self.assertEqual(str(self._calls["open"][0].get("alt") or "").upper().strip(), "B")

    def test_selector_topk_excludes_high_corr_outside_topk(self):
        svc._universe_btc_alt_candidates = lambda: ["A", "B", "C", "D"]
        svc.CONFIG["quant_auto_btcalts_selector_topk"] = 3

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            z_map = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0}
            corr_map = {"A": 0.1, "B": 0.2, "C": 0.5, "D": 0.99}
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": z_map.get(alt, 0.0), "corr": corr_map.get(alt, 0.0)},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": z_map.get(alt, 0.0)}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(out.get("decision", {}).get("alt"), "C")
        self.assertEqual(len(self._calls["open"]), 1)
        self.assertEqual(str(self._calls["open"][0].get("alt") or "").upper().strip(), "C")

    def test_btc_leg_busy_blocks_open(self):
        svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
        svc.TRACKER_STATE["quant_open_positions"].update({
            "BTC-PERP": {"side": "long", "notional_usdc": 50.0, "strategy_id": "other", "tag": "other"},
        })
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": 10.0}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("blocked"), "btc_leg_busy")
        self.assertEqual(len(self._calls["open"]), 0)

    def test_b_neutral_gate_uses_neutral_net_hedge_frac(self):
        svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
        svc._macro_btc_dir_snapshot = lambda **_kw: {"ok": True, "dir": 0}
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": 10.0}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(len(self._calls["open"]), 1)
        hf = float(self._calls["open"][0].get("btc_hedge_frac"))
        self.assertAlmostEqual(hf, 0.9, places=6)

    def test_b_aligned_gate_uses_aligned_net_hedge_frac(self):
        svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
        svc._macro_btc_dir_snapshot = lambda **_kw: {"ok": True, "dir_h": 1, "dir_short": 1}
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": 10.0}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "open")
        self.assertEqual(len(self._calls["open"]), 1)
        hf = float(self._calls["open"][0].get("btc_hedge_frac"))
        self.assertAlmostEqual(hf, 0.6, places=6)

    def test_b_strong_trend_filters_inverse_direction_before_budget_and_rank(self):
        svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
        svc.CONFIG["quant_auto_btcalts_macro_strong_chg_strength_min"] = 0.01
        svc._macro_btc_dir_snapshot = lambda **_kw: {"ok": True, "dir_h": 1, "dir_short": 1, "chg_strength": 1.0}
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "short_alt_long_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "trend"}},
                "rs": {"latest": {"rs_score": -10.0}},
                "trade_mode": "trend",
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision", {}).get("action"), "hold")
        self.assertEqual(len(self._calls["open"]), 0)

    def test_b_conflict_gate_can_block_open(self):
        svc.CONFIG["quant_auto_btcalts_strategy_mode"] = "B"
        svc.CONFIG["quant_auto_btcalts_macro_conflict_block_open"] = True
        svc._macro_btc_dir_snapshot = lambda **_kw: {"ok": True, "dir_h": 1, "dir_short": -1}
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": 10.0}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("blocked"), "macro_conflict")
        self.assertEqual(len(self._calls["open"]), 0)

    def test_dangling_btc_leg_blocks_open(self):
        svc.TRACKER_STATE["quant_open_positions"].update({
            "BTC-PERP": {"side": "short", "notional_usdc": 100.0, "strategy_id": "quant_auto_btcalts", "tag": "quant_auto_btcalts|g"},
        })
        svc._universe_btc_alt_candidates = lambda: ["ETH"]

        def _stub_status():
            alt = str(svc.request.args.get("alt") or "").upper().strip()
            self._calls["status"].append(alt)
            return svc.jsonify({
                "ok": True,
                "alt": alt,
                "action": "long_alt_short_btc",
                "latest": {"z": 10.0},
                "regime": {"latest": {"regime": "range"}},
                "rs": {"latest": {"rs_score": 10.0}},
            })

        svc.quant_pairs_btcalt_status = _stub_status

        out = svc._quant_auto_btcalts_tick(now_ms=1700000000000)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("blocked"), "dangling_btc_leg")
        self.assertEqual(len(self._calls["open"]), 0)


class TestQuantPairsBtcAltCorrGatePositiveOnly(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))

        self._orig_resolve_alt = svc._quant_pairs_btcalt_resolve_alt
        self._orig_close_series = svc._quant_pairs_close_series
        self._orig_pairstats = svc._quant_pairs_rolling_pairstats_alt_btc
        self._orig_regime_eval = svc._quant_pairs_btcalt_btc_regime_eval_aligned
        self._orig_rs_eval = svc._quant_pairs_btcalt_rs_eval
        self._orig_stationarity_gate = svc._quant_pairs_btcalt_stationarity_gate_eval
        self._orig_cost_params = svc._quant_pairs_btcalt_cost_params
        self._orig_cost_est = svc._quant_pairs_btcalt_cost_estimate
        self._orig_cost_buf = svc._quant_pairs_btcalt_cost_z_buffer
        self._orig_spread_sigma = svc._quant_pairs_btceth_latest_spread_sigma
        self._orig_cojump = svc._quant_pairs_btcalt_cojump_eval
        self._orig_funding = svc._quant_pairs_btcalt_funding_snapshot
        self._orig_corr_gate = svc._quant_pairs_btcalt_corr_gate_eval
        self._orig_op_gate = svc._quant_pairs_btcalt_operational_gate_eval
        self._orig_macro = svc._macro_btc_dir_snapshot
        self._orig_sub_pool = svc._quant_pairs_btcalt_sub_pool_snapshot
        self._orig_pf_params = svc._quant_pairs_btcalt_portfolio_params

        try:
            svc.TRACKER_STATE.clear()
        except Exception:
            pass
        svc.TRACKER_STATE.update({"quant_open_positions": {}})

        svc.CONFIG.update({
            "quant_pairs_btcalt_timeframe": "1h",
            "quant_pairs_btcalt_window_ols": 30,
            "quant_pairs_btcalt_window_z": 30,
            "quant_pairs_btcalt_entry_z": 2.0,
            "quant_pairs_btcalt_exit_z": 0.5,
            "quant_pairs_btcalt_stop_z": 4.0,
            "quant_pairs_btcalt_corr_min": 0.6,
            "entry_macro_gate_enabled": False,
            "trade_whitelist_enabled": False,
        })

        svc._quant_pairs_btcalt_resolve_alt = lambda alt0, tf, prefer_universe=True, validate=False: {
            "ok": True,
            "alt": "ETH",
            "source": "stub",
            "candidates": ["ETH"],
        }

        self._corr_last = -0.8
        self._z_last = -3.0

        def _close_series(coin: str, _tf: str, limit: int = 800, **_kwargs):
            ms = int(svc._hl_interval_to_ms("1h"))
            t0 = 1_700_000_000_000
            n = min(int(limit), 120)
            ts = [t0 + i * ms for i in range(n)]
            close = [10000.0 + float(i) for i in range(n)]
            if str(coin).upper() != "BTC":
                close = [300.0 + float(i) * 0.2 for i in range(n)]
            return ts, close

        svc._quant_pairs_close_series = _close_series

        def _pairstats(ts, btc_close, alt_close, window_ols, window_z):
            n = len(list(ts or []))
            tss = [int(x) for x in list(ts or [])]
            z = [0.0 for _ in range(n)]
            corr = [float(self._corr_last) for _ in range(n)]
            beta = [1.0 for _ in range(n)]
            spread = [0.0 for _ in range(n)]
            if n > 0:
                z[-1] = float(self._z_last)
                corr[-1] = float(self._corr_last)
            return {"ts": tss, "spread": spread, "z": z, "beta": beta, "corr": corr}

        svc._quant_pairs_rolling_pairstats_alt_btc = _pairstats

        svc._quant_pairs_btcalt_btc_regime_eval_aligned = lambda **_kwargs: {"ok": True, "latest": {"regime": "range"}}
        svc._quant_pairs_btcalt_rs_eval = lambda **_kwargs: {"ok": True, "latest": {"rs_score": 0.0}, "entry": 1.0, "exit": 0.0}
        svc._quant_pairs_btcalt_stationarity_gate_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False, "valid": True, "pass": True}
        svc._quant_pairs_btcalt_cost_params = lambda: {}
        svc._quant_pairs_btcalt_cost_estimate = lambda *_args, **_kwargs: {"ok": True}
        svc._quant_pairs_btcalt_cost_z_buffer = lambda **_kwargs: {"ok": True, "z": 0.0}
        svc._quant_pairs_btceth_latest_spread_sigma = lambda **_kwargs: 1.0
        svc._quant_pairs_btcalt_cojump_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False}
        svc._quant_pairs_btcalt_funding_snapshot = lambda **_kwargs: {"ok": True}
        svc._quant_pairs_btcalt_corr_gate_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False}
        svc._quant_pairs_btcalt_operational_gate_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False, "components": {}}
        svc._macro_btc_dir_snapshot = lambda **_kwargs: {"ok": True, "dir_h": 0, "dir_short": 0}
        svc._quant_pairs_btcalt_sub_pool_snapshot = lambda **_kwargs: {"ok": True}
        svc._quant_pairs_btcalt_portfolio_params = lambda **_kwargs: {"ok": True}

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass

        svc._quant_pairs_btcalt_resolve_alt = self._orig_resolve_alt
        svc._quant_pairs_close_series = self._orig_close_series
        svc._quant_pairs_rolling_pairstats_alt_btc = self._orig_pairstats
        svc._quant_pairs_btcalt_btc_regime_eval_aligned = self._orig_regime_eval
        svc._quant_pairs_btcalt_rs_eval = self._orig_rs_eval
        svc._quant_pairs_btcalt_stationarity_gate_eval = self._orig_stationarity_gate
        svc._quant_pairs_btcalt_cost_params = self._orig_cost_params
        svc._quant_pairs_btcalt_cost_estimate = self._orig_cost_est
        svc._quant_pairs_btcalt_cost_z_buffer = self._orig_cost_buf
        svc._quant_pairs_btceth_latest_spread_sigma = self._orig_spread_sigma
        svc._quant_pairs_btcalt_cojump_eval = self._orig_cojump
        svc._quant_pairs_btcalt_funding_snapshot = self._orig_funding
        svc._quant_pairs_btcalt_corr_gate_eval = self._orig_corr_gate
        svc._quant_pairs_btcalt_operational_gate_eval = self._orig_op_gate
        svc._macro_btc_dir_snapshot = self._orig_macro
        svc._quant_pairs_btcalt_sub_pool_snapshot = self._orig_sub_pool
        svc._quant_pairs_btcalt_portfolio_params = self._orig_pf_params

    def test_negative_corr_is_blocked_even_if_abs_high(self):
        self._corr_last = -0.85
        self._z_last = -3.0
        c = svc.app.test_client()
        r = c.get("/quant/pairs/btcalt/status?alt=ETH&timeframe=1h&limit=120&strategy_mode=C")
        self.assertEqual(r.status_code, 200)
        payload = r.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(payload.get("action"), "pause")
        self.assertEqual(payload.get("reason"), "corr_below_min")
        latest = payload.get("latest") or {}
        self.assertAlmostEqual(float(latest.get("corr")), -0.85, places=12)

    def test_positive_corr_allows_open(self):
        self._corr_last = 0.75
        self._z_last = -3.0
        c = svc.app.test_client()
        r = c.get("/quant/pairs/btcalt/status?alt=ETH&timeframe=1h&limit=120&strategy_mode=C")
        self.assertEqual(r.status_code, 200)
        payload = r.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))
        self.assertEqual(payload.get("action"), "long_alt_short_btc")


class TestArenaDiversityCorrelationPenalty(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_arena_state = dict(svc.ARENA_STATE)
        self._orig_corr_from_hist = svc._arena_corr_from_hist
        self._orig_feature_jaccard = svc._arena_feature_jaccard

        svc.ARENA_STATE.clear()
        svc.ARENA_STATE.update({"inited": True, "models": {}, "history": [{"chosen": "A"}]})

        svc.CONFIG.update({
            "arena_select_method": "weight",
            "arena_use_capital_in_selection": False,
            "arena_capital_floor_u": 0.0,
            "arena_diversity_enabled": True,
            "arena_diversity_use_recent_count": False,
            "arena_diversity_recent_k": 0,
            "arena_diversity_lambda": 0.0,
            "arena_diversity_use_feature": False,
            "arena_diversity_feature_lambda": 0.0,
            "arena_diversity_use_corr": True,
            "arena_diversity_corr_metric": "edge",
            "arena_diversity_corr_window": 200,
            "arena_diversity_corr_min_overlap": 2,
            "arena_diversity_corr_start": 0.7,
            "arena_diversity_corr_use_abs": False,
            "arena_diversity_corr_lambda": 5.0,
            "arena_diversity_corr_anti_lambda": 0.0,
            "arena_diversity_ref": "recent_top",
        })

        svc._arena_feature_jaccard = lambda *_args, **_kwargs: 0.0

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        svc.ARENA_STATE.clear()
        svc.ARENA_STATE.update(self._orig_arena_state)
        svc._arena_corr_from_hist = self._orig_corr_from_hist
        svc._arena_feature_jaccard = self._orig_feature_jaccard

    def test_positive_correlation_penalty_can_change_choice(self):
        def _stub_corr(hist, a, b, metric, window, min_overlap):
            if str(a) == "B" and str(b) == "A":
                return 0.95, 50
            return 0.0, 50

        svc._arena_corr_from_hist = _stub_corr

        arena_evt = {
            "feature_set_id": "fs",
            "models": {
                "A": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 1.0},
                "B": {"eligible": True, "capital_u": 100.0, "take": True, "weight": 1.1},
            },
        }
        chosen, _explore = svc._arena_choose_executor(arena_evt)
        self.assertEqual(chosen, "A")


class TestQuantExecutionPositionExistsSimulated(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig_gate = svc._order_gate_open
        self._orig_beta = svc._quant_pairs_btceth_latest_beta
        self._orig_open_leg = svc._pairs_quant_open_leg

        svc.CONFIG.update({
            "execute_guard_enabled": False,
            "dry_run": False,
            "live_trading_enabled": True,
            "quant_live_trading_enabled": True,
            "quant_pairs_btceth_live_enabled": True,
        })

        try:
            svc.TRACKER_STATE.clear()
        except Exception:
            pass
        svc.TRACKER_STATE.update({
            "quant_open_positions": {
                "BTC-PERP": {"pair": "BTC-PERP", "mode": "dry-run", "simulated": True, "side": "long", "notional_usdc": 100.0},
                "ETH-PERP": {"pair": "ETH-PERP", "mode": "dry-run", "simulated": True, "side": "short", "notional_usdc": 100.0},
            },
            "open_positions": {},
            "order_ts": [],
        })

        svc._order_gate_open = lambda **_kw: ({"ok": True}, None)
        svc._quant_pairs_btceth_latest_beta = lambda *_a, **_kw: {"ok": True, "ts": 1700000000000, "beta": 1.0, "btc_px": 100000.0}

        def _stub_open_leg(**_kw):
            return {"ok": False, "error": "stub_stop"}, 502

        svc._pairs_quant_open_leg = _stub_open_leg

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass
        svc._order_gate_open = self._orig_gate
        svc._quant_pairs_btceth_latest_beta = self._orig_beta
        svc._pairs_quant_open_leg = self._orig_open_leg

    def test_execute_true_ignores_simulated_quant_open_positions(self):
        c = svc.app.test_client()
        r = c.post(
            "/execution/pairs/btceth/market_open",
            json={
                "venue": "aster",
                "execute": True,
                "confirm_execute": True,
                "timeframe": "1h",
                "direction": "long_btc_short_eth",
                "notional_usdc": 100.0,
                "tag": "t",
                "strategy_id": "quant_manual",
            },
        )
        self.assertNotEqual(int(r.status_code), 409)
        op = svc.TRACKER_STATE.get("quant_open_positions") or {}
        self.assertNotIn("BTC-PERP", op)
        self.assertNotIn("ETH-PERP", op)


class TestExitFactorMath(unittest.TestCase):
    def test_sign3_deadzone(self):
        self.assertEqual(svc._sign3(0.0, deadzone=0.1), 0)
        self.assertEqual(svc._sign3(0.09, deadzone=0.1), 0)
        self.assertEqual(svc._sign3(-0.09, deadzone=0.1), 0)
        self.assertEqual(svc._sign3(0.11, deadzone=0.1), 1)
        self.assertEqual(svc._sign3(-0.11, deadzone=0.1), -1)

    def test_dcs_basic(self):
        d, cd, sp = svc._dcs(3.0, 2.0, 1.0)
        self.assertEqual(d, 1)
        self.assertEqual(cd, 0)
        self.assertAlmostEqual(sp, 0.0, places=10)

    def test_lr_slope_last_linear(self):
        if getattr(svc, "np", None) is None:
            self.skipTest("numpy_unavailable")
        y = list(range(10))
        sl = svc._lr_slope_last(y, window=5)
        self.assertAlmostEqual(sl, 1.0, places=10)


class TestConfigSetLiveSensitive(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_save = svc._save_config
        svc._save_config = lambda: None

    def tearDown(self):
        svc._save_config = self._orig_save
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)

    def test_non_sensitive_change_no_confirm_required_when_live(self):
        svc.CONFIG.clear()
        svc.CONFIG.update({
            "dry_run": False,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "elastic_vote_rule": {"mode": "strict"},
        })

        c = svc.app.test_client()
        r = c.post("/config/set", json={"elastic_vote_rule": {"mode": "loose"}})
        self.assertEqual(r.status_code, 200)
        payload = r.get_json() or {}
        self.assertTrue(bool(payload.get("ok")))

    def test_enabling_live_requires_confirm_live(self):
        svc.CONFIG.clear()
        svc.CONFIG.update({
            "dry_run": True,
            "live_trading_enabled": False,
            "execution_venue": "aster",
        })

        c = svc.app.test_client()
        r = c.post("/config/set", json={"dry_run": False})
        self.assertEqual(r.status_code, 400)
        payload = r.get_json() or {}
        self.assertEqual(payload.get("error"), "confirm_live_required")


class TestBacktestMetricsAggregation(unittest.TestCase):
    def test_bt_summaries_aggregate_basic(self):
        summaries = [
            {"key": "S1", "trades": 10, "wins": 6, "losses": 4, "draws": 0, "profit_total_pct": 1.0, "profit_total_abs": 100.0, "profit_factor": 1.5, "max_drawdown_account": 0.2},
            {"key": "S2", "trades": 5, "wins": 2, "losses": 3, "draws": 0, "profit_total_pct": -0.5, "profit_total_abs": -50.0, "profit_factor": 0.8, "max_drawdown_account": 0.4},
        ]
        out = svc._bt_summaries_aggregate(summaries)
        self.assertIsInstance(out, dict)
        self.assertEqual(out.get("n"), 2)
        self.assertEqual(out.get("trades"), 15)
        self.assertEqual(out.get("wins"), 8)
        self.assertEqual(out.get("losses"), 7)
        self.assertAlmostEqual(float(out.get("winrate")), 8.0 / 15.0, places=12)
        self.assertAlmostEqual(float(out.get("profit_total_pct_sum")), 0.5, places=12)
        self.assertAlmostEqual(float(out.get("profit_total_abs_sum")), 50.0, places=12)
        self.assertAlmostEqual(float(out.get("profit_factor_mean")), (1.5 + 0.8) / 2.0, places=12)
        self.assertAlmostEqual(float(out.get("max_drawdown_account_max")), 0.4, places=12)

    def test_bt_metrics_pick_and_slim(self):
        metrics = {
            "strategies": [
                {"key": "Strategy005", "trades": 3, "wins": 2, "losses": 1, "profit_total_pct": 0.3, "profit_factor": 1.2, "extra": "x"},
                {"key": "Other", "trades": 1, "wins": 0, "losses": 1, "profit_total_pct": -0.1, "profit_factor": 0.7},
            ]
        }
        picked = svc._bt_metrics_pick_strategy(metrics, "Strategy005")
        self.assertIsInstance(picked, dict)
        self.assertEqual(picked.get("key"), "Strategy005")
        slim = svc._bt_metrics_slim(picked)
        self.assertIsInstance(slim, dict)
        self.assertEqual(slim.get("key"), "Strategy005")
        self.assertIn("trades", slim)
        self.assertNotIn("extra", slim)


class TestQuantPairsBtcEthAddons(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig_fallback = svc._quant_pairs_btceth_adf_kpss_fallback

        try:
            svc.TRACKER_STATE.clear()
        except Exception:
            pass

        svc.CONFIG.update({
            "quant_pairs_btceth_gate_enabled": True,
            "quant_pairs_btceth_gate_k_fail": 3,
            "quant_pairs_btceth_gate_window": 30,
            "quant_pairs_btceth_gate_freq_bars": 1,
            "quant_pairs_btceth_gate_freq_bars_highvol": 1,
            "quant_pairs_btceth_gate_test_count": 1,
            "trade_whitelist_enabled": False,
            "entry_macro_gate_enabled": False,
            "entry_macro_btceth_hard_gate_enabled": False,
        })

    def tearDown(self):
        svc._quant_pairs_btceth_adf_kpss_fallback = self._orig_fallback
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass

    def test_stationarity_gate_blocks_after_k_fail(self):
        svc.adfuller = None
        svc.kpss = None

        svc._quant_pairs_btceth_adf_kpss_fallback = lambda _y, alpha_eff=None: {
            "ok": True,
            "adf": {"pass": False, "p": 0.2, "stat": 0.0},
            "kpss": {"pass": False, "stat": 1.0},
        }

        w = 30
        ms = int(svc._hl_interval_to_ms("1h"))
        t0 = 1_700_000_000_000
        blocked = False
        for i in range(3):
            ts = [t0 + (j * ms) for j in range(w + i)]
            spread = [float(j) for j in range(w + i)]
            out = svc._quant_pairs_btceth_stationarity_gate_eval("1h", ts, spread)
            blocked = bool(out.get("blocked"))
        self.assertTrue(blocked)

    def test_stationarity_gate_resets_on_pass(self):
        svc.adfuller = None
        svc.kpss = None

        svc._quant_pairs_btceth_adf_kpss_fallback = lambda _y, alpha_eff=None: {
            "ok": True,
            "adf": {"pass": False, "p": 0.2, "stat": 0.0},
            "kpss": {"pass": False, "stat": 1.0},
        }
        w = 30
        ms = int(svc._hl_interval_to_ms("1h"))
        t0 = 1_700_000_000_000
        ts1 = [t0 + (j * ms) for j in range(w)]
        sp1 = [float(j) for j in range(w)]
        out1 = svc._quant_pairs_btceth_stationarity_gate_eval("1h", ts1, sp1)
        self.assertEqual(int(out1.get("fail_count") or 0), 1)

        svc._quant_pairs_btceth_adf_kpss_fallback = lambda _y, alpha_eff=None: {
            "ok": True,
            "adf": {"pass": True, "p": 0.01, "stat": -4.0},
            "kpss": {"pass": True, "stat": 0.1},
        }
        ts2 = [t0 + (j * ms) for j in range(w + 1)]
        sp2 = [float(j) for j in range(w + 1)]
        out2 = svc._quant_pairs_btceth_stationarity_gate_eval("1h", ts2, sp2)
        self.assertEqual(int(out2.get("fail_count") or 0), 0)

    def test_cost_estimate_maker_vs_taker(self):
        cost = svc._quant_pairs_btceth_cost_params()
        e1 = svc._quant_pairs_btceth_cost_estimate(100.0, 100000.0, cost)
        self.assertTrue(bool(e1.get("ok")))
        self.assertEqual(e1.get("mode"), "maker")
        e2 = svc._quant_pairs_btceth_cost_estimate(2_000_000.0, 100000.0, cost)
        self.assertTrue(bool(e2.get("ok")))
        self.assertEqual(e2.get("mode"), "taker")

    def test_margin_status_recommends_reduce(self):
        svc.TRACKER_STATE["open_positions"] = {
            "BTC-PERP": {"unrealized_pnl_pct": -0.09},
            "ETH-PERP": {"unrealized_pnl_pct": 0.01},
        }
        out = svc._quant_pairs_btceth_margin_status()
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("recommend"), "reduce")
        legs = out.get("legs") or {}
        self.assertTrue(bool((legs.get("BTC") or {}).get("pressure")))

    def test_resample_closed_filters_unclosed_bucket(self):
        t0 = 1_700_000_000_000
        rows = []
        for i in range(13):
            ts = t0 + i * 300_000
            px = 100.0 + float(i)
            rows.append([ts, px, px + 1.0, px - 1.0, px, 1.0])

        bucket_ms = 3_600_000
        out1 = svc._resample_closed(rows, bucket_ms, now_ms=t0 + bucket_ms + 1)
        self.assertEqual(len(out1), 1)
        self.assertEqual(int(out1[0][0]), int((int(t0) // int(bucket_ms)) * int(bucket_ms)))

        out2 = svc._resample_closed(rows, bucket_ms, now_ms=t0 + 2 * bucket_ms + 1)
        self.assertEqual(len(out2), 2)

    def test_pairs_btceth_maker_timeout_rolls_back_first_leg(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_btceth_latest_beta": svc._quant_pairs_btceth_latest_beta,
            "_order_gate_open": svc._order_gate_open,
            "_aster_enabled_for_trading": svc._aster_enabled_for_trading,
            "_aster_mid": svc._aster_mid,
            "_aster_qty_from_notional": svc._aster_qty_from_notional,
            "_aster_symbol_from_coin": svc._aster_symbol_from_coin,
            "_aster_maker_price": svc._aster_maker_price,
            "_aster_limit_order_qty": getattr(svc, "_aster_limit_order_qty", None),
            "_aster_wait_fill": getattr(svc, "_aster_wait_fill", None),
            "_aster_order_cancel": getattr(svc, "_aster_order_cancel", None),
            "_aster_order_query": getattr(svc, "_aster_order_query", None),
            "_pairs_btceth_close_leg": svc._pairs_btceth_close_leg,
        }

        rollback_calls = []
        try:
            svc.CONFIG.update({
                "dry_run": False,
                "live_trading_enabled": True,
                "quant_live_trading_enabled": True,
                "aster_max_notional_usdc": 500.0,
                "quant_pairs_btceth_maker_enabled": True,
                "quant_pairs_btceth_live_enabled": True,
                "execute_guard_enabled": False,
            })
            svc.TRACKER_STATE["open_positions"] = {}

            svc._quant_pairs_btceth_latest_beta = lambda tf: {
                "ok": True,
                "timeframe": tf,
                "ts": 1_700_000_000_000,
                "btc_px": 100000.0,
                "eth_px": 3000.0,
                "beta": 1.0,
                "corr": 0.9,
                "z": 0.0,
            }
            svc._order_gate_open = lambda **_kwargs: ({"ok": True}, 200)
            svc._aster_enabled_for_trading = lambda: True
            svc._aster_mid = lambda coin, owner=None: (100000.0 if str(coin).upper() == "BTC" else 3000.0)
            svc._aster_qty_from_notional = lambda coin, notional, allow_adjust=False, mid=None, owner=None: (0.001 if str(coin).upper() == "BTC" else 0.02)
            svc._aster_symbol_from_coin = lambda coin: f"{str(coin).upper()}USDT"
            svc._aster_maker_price = lambda coin, is_buy, offset_bps=0.0, owner=None: {
                "symbol": f"{str(coin).upper()}USDT",
                "coin": str(coin).upper(),
                "is_buy": bool(is_buy),
                "source": "stub",
                "bid": None,
                "ask": None,
                "mid": float(100000.0 if str(coin).upper() == "BTC" else 3000.0),
                "offset_bps": float(offset_bps),
                "price": float(100000.0 if str(coin).upper() == "BTC" else 3000.0),
            }

            def _limit_order_qty(coin: str, side: str, qty: float, price: float, reduce_only: bool = False, post_only: bool = False, owner: str = None):
                oid = "1" if str(coin).upper() == "BTC" else "2"
                return {"resp": {"orderId": oid, "status": "NEW"}}

            def _wait_fill(symbol: str, order_id, timeout_sec: float, poll_ms: int = 250, owner: str = None):
                if str(order_id) == "1":
                    return {"ok": True, "done": True, "filled": True, "last": {"status": "FILLED", "executedQty": "0.001"}, "status": "FILLED"}
                return {"ok": True, "done": False, "filled": False, "last": {"status": "NEW", "executedQty": "0"}, "status": "NEW"}

            svc._aster_limit_order_qty = _limit_order_qty
            svc._aster_wait_fill = _wait_fill
            svc._aster_order_cancel = lambda symbol, order_id, owner=None: {"ok": True, "status": "CANCELED"}
            svc._aster_order_query = lambda symbol, order_id, owner=None: ({"status": "CANCELED", "executedQty": "0"} if str(order_id) == "2" else {"status": "FILLED", "executedQty": "0.001"})

            svc._pairs_btceth_close_leg = lambda venue, coin, execute, tag, sz=None, force=True: (rollback_calls.append({"venue": venue, "coin": coin, "execute": execute, "tag": tag, "sz": sz}) or ({"ok": True}, 200))

            r = c.post(
                "/execution/pairs/btceth/market_open",
                json={
                    "venue": "aster",
                    "direction": "long_btc_short_eth",
                    "execute": True,
                    "notional_usdc": 100.0,
                    "maker": True,
                    "maker_timeout_sec": 1.0,
                },
            )
            self.assertEqual(r.status_code, 502)
            payload = r.get_json() or {}
            self.assertEqual(payload.get("error"), "eth_leg_failed")
            self.assertEqual(len(rollback_calls), 1)
            self.assertEqual((rollback_calls[0] or {}).get("coin"), "BTC")
        finally:
            svc._quant_pairs_btceth_latest_beta = orig["_quant_pairs_btceth_latest_beta"]
            svc._order_gate_open = orig["_order_gate_open"]
            svc._aster_enabled_for_trading = orig["_aster_enabled_for_trading"]
            svc._aster_mid = orig["_aster_mid"]
            svc._aster_qty_from_notional = orig["_aster_qty_from_notional"]
            svc._aster_symbol_from_coin = orig["_aster_symbol_from_coin"]
            svc._aster_maker_price = orig["_aster_maker_price"]
            if orig["_aster_limit_order_qty"] is not None:
                svc._aster_limit_order_qty = orig["_aster_limit_order_qty"]
            if orig["_aster_wait_fill"] is not None:
                svc._aster_wait_fill = orig["_aster_wait_fill"]
            if orig["_aster_order_cancel"] is not None:
                svc._aster_order_cancel = orig["_aster_order_cancel"]
            if orig["_aster_order_query"] is not None:
                svc._aster_order_query = orig["_aster_order_query"]
            svc._pairs_btceth_close_leg = orig["_pairs_btceth_close_leg"]

    def test_pairs_btcalt_parses_ignore_flags_and_calls_open_legs(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_btcalt_resolve_alt": svc._quant_pairs_btcalt_resolve_alt,
            "_quant_pairs_btcalt_sub_pool_snapshot": svc._quant_pairs_btcalt_sub_pool_snapshot,
            "_quant_pairs_macro_trend_veto": svc._quant_pairs_macro_trend_veto,
            "_pairs_quant_open_leg": svc._pairs_quant_open_leg,
            "_check_execute_guard": svc._check_execute_guard,
        }

        calls = []
        try:
            svc.CONFIG.update({
                "execute_guard_enabled": False,
                "quant_pairs_btcalt_doge_ignore_post_close_freeze": True,
                "quant_pairs_btcalt_ignore_post_close_freeze": False,
                "quant_pairs_btcalt_ignore_cooldown": False,
            })

            svc._check_execute_guard = lambda _data: None
            svc._quant_pairs_btcalt_resolve_alt = lambda alt0, tf, prefer_universe=True, validate=True: {
                "ok": True,
                "alt": "DOGE",
                "source": "stub",
                "candidates": ["DOGE"],
                "snap": {"ok": True, "ts": 1_700_000_000_000, "timeframe": str(tf), "btc_px": 100000.0, "alt_px": 0.1, "beta": 1.0, "corr": 0.8, "z": 0.0},
            }
            svc._quant_pairs_btcalt_sub_pool_snapshot = lambda now_ms: {"ok": True, "cap_usdc": 1e9, "used_usdc": 0.0}
            svc._quant_pairs_macro_trend_veto = lambda direction, force_aster=False: {"ok": True, "blocked": False}

            def _open_leg(**kwargs):
                calls.append(dict(kwargs))
                return {"ok": True, "coin": str(kwargs.get("coin")), "side": str(kwargs.get("side")), "order": {"size": 1.0}}, 200

            svc._pairs_quant_open_leg = _open_leg

            r = c.post(
                "/execution/pairs/btcalt/market_open",
                json={
                    "venue": "aster",
                    "execute": False,
                    "alt": "DOGE",
                    "direction": "long_alt_short_btc",
                    "notional_usdc": 30.0,
                    "btc_hedge_frac": 1.0,
                },
            )
            self.assertEqual(r.status_code, 200)
            payload = r.get_json() or {}
            self.assertTrue(bool(payload.get("ok")))
            self.assertEqual(len(calls), 2)
            for it in calls:
                self.assertTrue(bool(it.get("ignore_post_close_freeze")))
        finally:
            svc._quant_pairs_btcalt_resolve_alt = orig["_quant_pairs_btcalt_resolve_alt"]
            svc._quant_pairs_btcalt_sub_pool_snapshot = orig["_quant_pairs_btcalt_sub_pool_snapshot"]
            svc._quant_pairs_macro_trend_veto = orig["_quant_pairs_macro_trend_veto"]
            svc._pairs_quant_open_leg = orig["_pairs_quant_open_leg"]
            svc._check_execute_guard = orig["_check_execute_guard"]

    def test_pairs_btcalt_doge_auto_trend_forces_range_before_trend_gate(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_btcalt_resolve_alt": svc._quant_pairs_btcalt_resolve_alt,
            "_quant_pairs_btcalt_sub_pool_snapshot": svc._quant_pairs_btcalt_sub_pool_snapshot,
            "_quant_pairs_close_series": svc._quant_pairs_close_series,
            "_quant_pairs_rolling_pairstats_alt_btc": svc._quant_pairs_rolling_pairstats_alt_btc,
            "_quant_pairs_macro_trend_veto": svc._quant_pairs_macro_trend_veto,
            "_pairs_quant_open_leg": svc._pairs_quant_open_leg,
            "_check_execute_guard": svc._check_execute_guard,
        }

        calls = []
        try:
            svc.CONFIG.update({
                "execute_guard_enabled": False,
                "quant_pairs_btcalt_doge_force_range_when_auto": True,
                "quant_pairs_btcalt_trend_follow_require_btc_trend": True,
                "quant_pairs_btcalt_trend_follow_fallback_to_range": False,
            })

            svc._check_execute_guard = lambda _data: None
            svc._quant_pairs_btcalt_resolve_alt = lambda alt0, tf, prefer_universe=True, validate=True: {
                "ok": True,
                "alt": "DOGE",
                "source": "stub",
                "candidates": ["DOGE"],
                "snap": {"ok": True, "ts": 1_700_000_000_000, "timeframe": str(tf), "btc_px": 100000.0, "alt_px": 0.1, "beta": 1.0, "corr": 0.8, "z": 0.0},
            }
            svc._quant_pairs_btcalt_sub_pool_snapshot = lambda now_ms: {"ok": True, "cap_usdc": 1e9, "used_usdc": 0.0}
            svc._quant_pairs_macro_trend_veto = lambda direction, force_aster=False: {"ok": True, "blocked": False}

            ms = int(svc._hl_interval_to_ms("1h"))
            t0 = 1_700_000_000_000
            ts = [t0 + i * ms for i in range(300)]
            btc = [10000.0 + float(i) * 1.0 for i in range(300)]
            alt = [100.0 + float(i) * 0.1 for i in range(300)]
            svc._quant_pairs_close_series = lambda coin, tf, limit=800, force_aster=False, allow_fallback=True, disable_aster=False: (ts[-int(limit):], (btc[-int(limit):] if str(coin).upper() == "BTC" else alt[-int(limit):]))
            svc._quant_pairs_rolling_pairstats_alt_btc = lambda ts, btc_close, alt_close, window_ols, window_z: {"ts": ts, "spread": [0.0] * len(ts), "z": [-3.0] * len(ts), "beta": [1.0] * len(ts), "corr": [0.9] * len(ts)}

            def _open_leg(**kwargs):
                calls.append(dict(kwargs))
                return {"ok": True, "coin": str(kwargs.get("coin")), "side": str(kwargs.get("side")), "order": {"size": 1.0}}, 200

            svc._pairs_quant_open_leg = _open_leg

            r = c.post(
                "/execution/pairs/btcalt/market_open",
                json={
                    "venue": "aster",
                    "execute": False,
                    "alt": "DOGE",
                    "direction": "auto",
                    "mode": "trend",
                    "strategy_mode": "B",
                    "timeframe": "1h",
                    "notional_usdc": 30.0,
                    "btc_hedge_frac": 1.0,
                },
            )
            self.assertEqual(r.status_code, 200)
            payload = r.get_json() or {}
            self.assertTrue(bool(payload.get("ok")))
            self.assertEqual(str(payload.get("trade_mode")), "range")
            self.assertEqual(len(calls), 2)
        finally:
            svc._quant_pairs_btcalt_resolve_alt = orig["_quant_pairs_btcalt_resolve_alt"]
            svc._quant_pairs_btcalt_sub_pool_snapshot = orig["_quant_pairs_btcalt_sub_pool_snapshot"]
            svc._quant_pairs_close_series = orig["_quant_pairs_close_series"]
            svc._quant_pairs_rolling_pairstats_alt_btc = orig["_quant_pairs_rolling_pairstats_alt_btc"]
            svc._quant_pairs_macro_trend_veto = orig["_quant_pairs_macro_trend_veto"]
            svc._pairs_quant_open_leg = orig["_pairs_quant_open_leg"]
            svc._check_execute_guard = orig["_check_execute_guard"]

    def test_pairs_btceth_wfo_run_produces_folds(self):
        ms = int(svc._hl_interval_to_ms("1h"))
        t0 = 1_700_000_000_000
        n = 220
        ts = [t0 + i * ms for i in range(n)]
        btc = [10000.0 + float(i) * 2.0 for i in range(n)]
        eth = [300.0 + float(i) * 0.5 for i in range(n)]
        btc[-1] = float(btc[-2]) * 1.05

        base = {
            "timeframe": "1h",
            "window_ols": 30,
            "window_z": 30,
            "entry_z": 2.0,
            "exit_z": 0.5,
            "stop_z": 6.0,
            "corr_min": 0.0,
            "max_hold_bars": 50,
        }
        grid = {
            "entry_z": {"values": [1.0, 2.0]},
            "exit_z": {"values": [0.3, 0.5]},
            "window_ols": {"values": [30]},
            "window_z": {"values": [30]},
        }
        out = svc._quant_pairs_btceth_wfo_run(
            ts=ts,
            btc_close=btc,
            eth_close=eth,
            base_params=base,
            grid=grid,
            is_bars=80,
            oos_bars=40,
            step_bars=80,
            embargo_bars=0,
        )
        self.assertTrue(bool(out.get("ok")))
        self.assertGreaterEqual(int((out.get("summary") or {}).get("folds") or 0), 1)

    def test_pairs_btceth_status_can_apply_wfo_selected_params(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_close_series": svc._quant_pairs_close_series,
            "_quant_pairs_btceth_stationarity_gate_eval": svc._quant_pairs_btceth_stationarity_gate_eval,
            "_quant_pairs_btceth_cost_params": svc._quant_pairs_btceth_cost_params,
            "_quant_pairs_btceth_cost_estimate": svc._quant_pairs_btceth_cost_estimate,
            "_quant_pairs_btceth_cost_z_buffer": svc._quant_pairs_btceth_cost_z_buffer,
            "_quant_pairs_btceth_cojump_eval": svc._quant_pairs_btceth_cojump_eval,
            "_quant_pairs_btceth_funding_snapshot": svc._quant_pairs_btceth_funding_snapshot,
            "_quant_pairs_btceth_margin_status": svc._quant_pairs_btceth_margin_status,
        }

        try:
            svc.CONFIG.update({
                "quant_pairs_btceth_timeframe": "1h",
                "quant_pairs_btceth_window_ols": 30,
                "quant_pairs_btceth_window_z": 30,
                "quant_pairs_btceth_entry_z": 3.0,
                "quant_pairs_btceth_exit_z": 0.5,
                "quant_pairs_btceth_stop_z": 10.0,
                "quant_pairs_btceth_corr_min": 0.0,
                "quant_pairs_btceth_max_hold_bars": 50,
                "quant_pairs_btceth_wfo_enabled": True,
                "quant_pairs_btceth_wfo_apply": True,
                "quant_pairs_btceth_wfo_is_bars": 80,
                "quant_pairs_btceth_wfo_oos_bars": 40,
                "quant_pairs_btceth_wfo_step_bars": 80,
                "quant_pairs_btceth_wfo_embargo_bars": 0,
                "quant_pairs_btceth_wfo_grid": {
                    "entry_z": {"values": [1.0]},
                    "exit_z": {"values": [0.5]},
                    "window_ols": {"values": [30]},
                    "window_z": {"values": [30]},
                    "stop_z": {"values": [10.0]},
                    "corr_min": {"values": [0.0]},
                    "max_hold_bars": {"values": [50]},
                },
                "quant_pairs_btceth_gate_enabled": False,
                "quant_pairs_btceth_cojump_enabled": False,
            })
            svc.TRACKER_STATE["open_positions"] = {}

            ms = int(svc._hl_interval_to_ms("1h"))
            t0 = 1_700_000_000_000
            n = 220
            ts = [t0 + i * ms for i in range(n)]
            btc = [10000.0 + float(i) * 2.0 for i in range(n)]
            eth = [300.0 + float(i) * 0.5 for i in range(n)]
            btc[-1] = float(btc[-2]) * 1.05

            def _series(coin: str, _tf: str, limit: int = 800, **_kwargs):
                if str(coin).upper() == "BTC":
                    return ts[-limit:], btc[-limit:]
                return ts[-limit:], eth[-limit:]

            svc._quant_pairs_close_series = _series
            svc._quant_pairs_btceth_stationarity_gate_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False}
            svc._quant_pairs_btceth_cost_params = lambda: {"slip_mu": 0.0, "slip_beta": 1e-9, "slip_alpha": 0.0, "depth_threshold_btc": 10.0, "avg_depth_btc": 10.0, "maker_fee": 0.0, "taker_fee": 0.0, "maker_timeout_sec": 10.0, "slip_quantile": 0.95}
            svc._quant_pairs_btceth_cost_estimate = lambda **_kwargs: {"ok": True, "fee_rate": 0.0, "slippage_rate": 0.0, "mode": "maker", "maker_timeout_sec": 10.0}
            svc._quant_pairs_btceth_cost_z_buffer = lambda **_kwargs: {"ok": True, "z": 0.0, "cost_total_rate": 0.0}
            svc._quant_pairs_btceth_cojump_eval = lambda **_kwargs: {"ok": True, "enabled": False, "blocked": False}
            svc._quant_pairs_btceth_funding_snapshot = lambda **_kwargs: {"ok": True}
            svc._quant_pairs_btceth_margin_status = lambda **_kwargs: {"ok": True, "recommend": "ok"}

            r = c.get("/quant/pairs/btceth/status?wfo_run=1&limit=220")
            self.assertEqual(r.status_code, 200)
            payload = r.get_json() or {}
            self.assertTrue(bool(payload.get("ok")))
            self.assertTrue(bool(((payload.get("wfo") or {}).get("enabled"))))
            self.assertTrue(bool(((payload.get("wfo") or {}).get("applied"))))
            self.assertEqual(float((payload.get("params") or {}).get("entry_z") or 0.0), 1.0)
            self.assertEqual(float((payload.get("base_params") or {}).get("entry_z") or 0.0), 3.0)
            self.assertIn(payload.get("action"), ("short_btc_long_eth", "hold", "pause"))
        finally:
            svc._quant_pairs_close_series = orig["_quant_pairs_close_series"]
            svc._quant_pairs_btceth_stationarity_gate_eval = orig["_quant_pairs_btceth_stationarity_gate_eval"]
            svc._quant_pairs_btceth_cost_params = orig["_quant_pairs_btceth_cost_params"]
            svc._quant_pairs_btceth_cost_estimate = orig["_quant_pairs_btceth_cost_estimate"]
            svc._quant_pairs_btceth_cost_z_buffer = orig["_quant_pairs_btceth_cost_z_buffer"]
            svc._quant_pairs_btceth_cojump_eval = orig["_quant_pairs_btceth_cojump_eval"]
            svc._quant_pairs_btceth_funding_snapshot = orig["_quant_pairs_btceth_funding_snapshot"]
            svc._quant_pairs_btceth_margin_status = orig["_quant_pairs_btceth_margin_status"]

    def test_pairs_btceth_status_includes_op_gate_on_not_enough_bars(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_close_series": svc._quant_pairs_close_series,
            "_quant_pairs_btceth_operational_gate_eval": getattr(svc, "_quant_pairs_btceth_operational_gate_eval", None),
        }

        try:
            ms = int(svc._hl_interval_to_ms("1h"))
            t0 = 1_700_000_000_000
            n = 60
            ts = [t0 + i * ms for i in range(n)]
            btc = [10000.0 + float(i) for i in range(n)]
            eth = [300.0 + float(i) * 0.1 for i in range(n)]

            def _series(coin: str, _tf: str, limit: int = 800, **_kwargs):
                if str(coin).upper() == "BTC":
                    return ts[-limit:], btc[-limit:]
                return ts[-limit:], eth[-limit:]

            svc._quant_pairs_close_series = _series
            svc._quant_pairs_btceth_operational_gate_eval = lambda **_kwargs: {"ok": True, "enabled": True, "blocked": False, "components": {}}

            r = c.get("/quant/pairs/btceth/status?limit=60")
            self.assertEqual(r.status_code, 200)
            payload = r.get_json() or {}
            self.assertEqual(payload.get("error"), "not_enough_bars")
            self.assertIn("op_gate", payload)
            self.assertTrue(isinstance(payload.get("op_gate"), dict))
        finally:
            svc._quant_pairs_close_series = orig["_quant_pairs_close_series"]
            if orig["_quant_pairs_btceth_operational_gate_eval"] is not None:
                svc._quant_pairs_btceth_operational_gate_eval = orig["_quant_pairs_btceth_operational_gate_eval"]

    def test_pairs_btceth_research_split_capacity_margin_stress(self):
        c = svc.app.test_client()

        orig = {
            "_quant_pairs_close_series_range": svc._quant_pairs_close_series_range,
        }

        try:
            svc.CONFIG.update({
                "quant_pairs_btceth_timeframe": "1h",
                "quant_pairs_btceth_window_ols": 30,
                "quant_pairs_btceth_window_z": 30,
                "quant_pairs_btceth_entry_z": 2.0,
                "quant_pairs_btceth_exit_z": 0.5,
                "quant_pairs_btceth_stop_z": 6.0,
                "quant_pairs_btceth_corr_min": 0.0,
                "quant_pairs_btceth_max_hold_bars": 50,
            })

            ms = int(svc._hl_interval_to_ms("1h"))
            t0 = 1_700_000_000_000
            n = 520
            ts_all = [t0 + i * ms for i in range(n)]
            btc_all = [10000.0 + float(i) * 2.0 + 50.0 * math.sin(float(i) / 20.0) for i in range(n)]
            eth_all = [300.0 + float(i) * 0.1 + 5.0 * math.sin(float(i) / 17.0) for i in range(n)]

            def _series_range(coin: str, _tf: str, start_ts_ms=None, end_ts_ms=None, limit: int = 0, **_kwargs):
                if str(coin).upper() == "BTC":
                    xs = ts_all
                    ys = btc_all
                else:
                    xs = ts_all
                    ys = eth_all
                a = 0
                b = len(xs)
                if start_ts_ms is not None:
                    try:
                        a = next((i for i, t in enumerate(xs) if int(t) >= int(start_ts_ms)), a)
                    except Exception:
                        a = a
                if end_ts_ms is not None:
                    try:
                        b = next((i for i, t in enumerate(xs) if int(t) > int(end_ts_ms)), b)
                    except Exception:
                        b = b
                xs2 = xs[a:b]
                ys2 = ys[a:b]
                if int(limit) > 0 and len(xs2) > int(limit):
                    xs2 = xs2[-int(limit):]
                    ys2 = ys2[-int(limit):]
                return xs2, ys2

            svc._quant_pairs_close_series_range = _series_range

            r1 = c.get("/quant/pairs/btceth/research/split?timeframe=1h&subset=full&window_ols=30&window_z=30&purge_bars=5&embargo_bars=5&gap_bars=0")
            self.assertEqual(r1.status_code, 200)
            p1 = r1.get_json() or {}
            self.assertTrue(bool(p1.get("ok")))
            self.assertIn("counts", p1)
            self.assertIn("ranges", p1)
            self.assertFalse(bool(p1.get("exported")))

            r2 = c.get("/quant/pairs/btceth/research/capacity?timeframe=1h&subset=full&limit=520&notionals=100,200")
            self.assertEqual(r2.status_code, 200)
            p2 = r2.get_json() or {}
            self.assertTrue(bool(p2.get("ok")))
            items = p2.get("items") or []
            self.assertEqual(len(items), 2)
            self.assertTrue(isinstance(items[0], dict))
            self.assertIn("metrics", items[0])

            r3 = c.get("/quant/pairs/btceth/research/margin_stress?timeframe=1h&lookback_bars=300&paths=500")
            self.assertEqual(r3.status_code, 200)
            p3 = r3.get_json() or {}
            self.assertTrue(bool(p3.get("ok")))
            self.assertIn("baseline", p3)
            self.assertIn("buffer_curve", p3)
        finally:
            svc._quant_pairs_close_series_range = orig["_quant_pairs_close_series_range"]


class TestServingCanaryBumpGuard(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig = {
            "_get_threshold": svc._get_threshold,
            "_get_regime": svc._get_regime,
            "_score": svc._score,
            "_calibrate": svc._calibrate,
            "_aster_preflight_notional": svc._aster_preflight_notional,
            "_hl_coin_from_pair": svc._hl_coin_from_pair,
            "_size_from_pc_atr": svc._size_from_pc_atr,
            "_strategy_live_trading_allowed": svc._strategy_live_trading_allowed,
            "_live_trading_enabled_for_owner": svc._live_trading_enabled_for_owner,
            "_order_gate_open": svc._order_gate_open,
            "_entry_macro_scope_ok": svc._entry_macro_scope_ok,
            "_aster_enabled_for_trading": svc._aster_enabled_for_trading,
            "_aster_qty_from_notional": svc._aster_qty_from_notional,
            "_aster_set_margin_type": svc._aster_set_margin_type,
            "_aster_mid": svc._aster_mid,
            "_aster_market_order_qty": svc._aster_market_order_qty,
        }

        try:
            svc.TRACKER_STATE["open_positions"] = {}
        except Exception:
            pass

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(svc, k, v)
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass

    def test_canary_bump_too_large_holds(self):
        svc.CONFIG.clear()
        svc.CONFIG.update({
            "dry_run": False,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "strategy_live_trading_policy": "inherit",
            "serving_shadow_mode": False,
            "serving_canary_enabled": True,
            "serving_canary_size_frac": 0.2,
            "serving_canary_pairs": ["BTC/USDT:USDT"],
            "aster_min_notional_usdc": 10.0,
            "aster_max_bump_ratio": 2.0,
            "entry_fixed_notional_enabled": False,
        })

        svc._get_threshold = lambda _regime: 0.0
        svc._get_regime = lambda _features, **_kwargs: "trend"
        svc._score = lambda _features, _side: 1.0
        svc._calibrate = lambda _p, **_kwargs: 1.0
        svc._strategy_live_trading_allowed = lambda *_args, **_kwargs: True
        svc._live_trading_enabled_for_owner = lambda *_args, **_kwargs: True
        svc._order_gate_open = lambda **_kwargs: ({"ok": True}, 200)
        svc._entry_macro_scope_ok = lambda **_kwargs: False
        svc._hl_coin_from_pair = lambda _pair: "BTC"
        svc._size_from_pc_atr = lambda *_args, **_kwargs: 75.0

        def _pf(coin: str, notional_usd: float):
            return {
                "ok": True,
                "will_bump": True,
                "required_notional_usdc": 90.0,
            }

        svc._aster_preflight_notional = _pf

        out, code = svc._decision_entry_impl({
            "pair": "BTC/USDT:USDT",
            "side": "long",
            "features": {"close": 100000.0, "atr_pct": 0.02},
            "tag": "unit_test",
            "ts": 0,
            "threshold": 0.0,
            "threshold_final": True,
        })

        self.assertEqual(int(code), 200)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision"), "hold")
        self.assertEqual(out.get("reason"), "canary_bump_too_large")
        canary = out.get("canary") or {}
        self.assertAlmostEqual(float(canary.get("frac")), 0.2, places=12)
        self.assertAlmostEqual(float(canary.get("max_bump_ratio")), 2.0, places=12)

    def test_canary_min_notional_bump_over_cap_but_under_pre_is_allowed(self):
        svc.CONFIG.clear()
        svc.CONFIG.update({
            "arena_enabled": False,
            "dry_run": False,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "strategy_live_trading_policy": "inherit",
            "serving_shadow_mode": False,
            "serving_canary_enabled": True,
            "serving_canary_size_frac": 0.05,
            "serving_canary_pairs": ["BTC/USDT:USDT"],
            "book_execution_account_id_by_venue": {"strategy": {"aster": "ut_strategy_aster"}},
            "aster_min_notional_usdc": 10.0,
            "aster_max_bump_ratio": 2.0,
            "entry_fixed_notional_enabled": False,
            "trade_whitelist_enabled": False,
        })

        svc._get_threshold = lambda _regime: 0.0
        svc._get_regime = lambda _features, **_kwargs: "trend"
        svc._score = lambda _features, _side: 1.0
        svc._calibrate = lambda _p, **_kwargs: 1.0
        svc._strategy_live_trading_allowed = lambda *_args, **_kwargs: True
        svc._live_trading_enabled_for_owner = lambda *_args, **_kwargs: True
        svc._hl_coin_from_pair = lambda _pair: "BTC"
        svc._order_gate_open = lambda **_kwargs: ({"ok": True}, 200)
        svc._entry_macro_scope_ok = lambda **_kwargs: False
        svc._size_from_pc_atr = lambda *_args, **_kwargs: 60.0
        svc._aster_enabled_for_trading = lambda: True
        svc._aster_set_margin_type = lambda **_kwargs: {"ok": True}
        svc._aster_mid = lambda _coin: 100000.0
        svc._aster_qty_from_notional = lambda *_args, **_kwargs: 0.001
        svc._aster_market_order_qty = lambda **_kwargs: {"resp": {"status": "FILLED", "orderId": "ut"}}
        svc._aster_preflight_notional = lambda **_kwargs: {"ok": True, "will_bump": False}

        out, code = svc._decision_entry_impl({
            "pair": "BTC/USDT:USDT",
            "side": "long",
            "features": {"close": 100000.0, "atr_pct": 0.02},
            "tag": "unit_test",
            "ts": 0,
            "threshold": 0.0,
            "threshold_final": True,
        })

        self.assertEqual(int(code), 200)
        self.assertTrue(bool(out.get("ok")))
        self.assertNotEqual(out.get("decision"), "hold")
        self.assertNotEqual(out.get("reason"), "canary_bump_too_large")


class TestDecisionEntryNotionalAndWhitelist(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig_orders = dict(getattr(svc, "ORDERS", {}))
        self._orig_events = dict(getattr(svc, "EVENTS", {}))

        self._orig = {
            "_get_threshold": svc._get_threshold,
            "_get_regime": svc._get_regime,
            "_score": svc._score,
            "_calibrate": svc._calibrate,
            "_hl_coin_from_pair": svc._hl_coin_from_pair,
            "_order_gate_open": svc._order_gate_open,
            "_entry_macro_scope_ok": svc._entry_macro_scope_ok,
            "_aster_enabled_for_trading": svc._aster_enabled_for_trading,
            "_aster_qty_from_notional": svc._aster_qty_from_notional,
            "_aster_set_margin_type": svc._aster_set_margin_type,
            "_aster_mid": svc._aster_mid,
            "_aster_market_order_qty": svc._aster_market_order_qty,
            "_strategy_live_trading_allowed": svc._strategy_live_trading_allowed,
            "_live_trading_enabled_for_owner": svc._live_trading_enabled_for_owner,
        }

        try:
            svc.TRACKER_STATE["open_positions"] = {}
        except Exception:
            pass
        try:
            svc.ORDERS.clear()
        except Exception:
            pass
        try:
            svc.EVENTS.clear()
        except Exception:
            pass

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(svc, k, v)
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass
        try:
            svc.ORDERS.clear()
            svc.ORDERS.update(self._orig_orders)
        except Exception:
            pass
        try:
            svc.EVENTS.clear()
            svc.EVENTS.update(self._orig_events)
        except Exception:
            pass

    def _force_pass_threshold(self):
        svc._get_threshold = lambda _regime: 0.0
        svc._get_regime = lambda _features, **_kwargs: "trend"
        svc._score = lambda _features, _side: 1.0
        svc._calibrate = lambda _p, **_kwargs: 1.0

    def test_entry_notional_clips_to_entry_max(self):
        svc.CONFIG.update({
            "arena_enabled": False,
            "dry_run": True,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "entry_fixed_notional_enabled": False,
            "trade_whitelist_enabled": True,
            "trade_whitelist_enforcement": "hard",
            "trade_whitelist": ["BTCUSDT"],
            "min_trade_size": 800.0,
            "max_trade_size": 1100.0,
            "aster_min_notional_usdc": 10.0,
            "aster_max_notional_usdc": 5000.0,
        })

        self._force_pass_threshold()
        svc._hl_coin_from_pair = lambda _pair: "BTC"
        svc._order_gate_open = lambda **_kwargs: ({"ok": True}, 200)
        svc._entry_macro_scope_ok = lambda **_kwargs: False

        c = svc.app.test_client()
        r = c.post(
            "/decision/entry",
            json={
                "pair": "BTC/USDT:USDT",
                "side": "long",
                "features": {"close": 100000.0, "atr_pct": 0.02},
                "size": 5000.0,
                "tag": "unit_test",
                "ts": 0,
                "threshold": 0.0,
                "threshold_final": True,
            },
        )

        self.assertEqual(int(r.status_code), 200)
        out = r.get_json() or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(out.get("decision"), "enter")
        oid = str(out.get("order_id") or "")
        self.assertTrue(bool(oid))

        r2 = c.get(f"/order/{oid}")
        self.assertEqual(int(r2.status_code), 200)
        order = ((r2.get_json() or {}).get("order") or {})
        self.assertAlmostEqual(float(order.get("size")), 1100.0, places=12)

    def test_trade_whitelist_rejects_non_whitelisted_coin(self):
        svc.CONFIG.update({
            "arena_enabled": False,
            "dry_run": True,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "entry_fixed_notional_enabled": False,
            "trade_whitelist_enabled": True,
            "trade_whitelist_enforcement": "hard",
            "trade_whitelist": ["BTCUSDT"],
            "entry_min_notional_usdc": 10.0,
            "entry_max_notional_usdc": 5000.0,
            "aster_min_notional_usdc": 10.0,
            "aster_max_notional_usdc": 5000.0,
        })

        self._force_pass_threshold()
        svc._hl_coin_from_pair = lambda _pair: "S"

        c = svc.app.test_client()
        r = c.post(
            "/decision/entry",
            json={
                "pair": "S-PERP",
                "side": "short",
                "features": {"close": 1.0, "atr_pct": 0.02},
                "size": 100.0,
                "tag": "unit_test",
                "ts": 0,
                "threshold": 0.0,
                "threshold_final": True,
            },
        )

        self.assertEqual(int(r.status_code), 200)
        out = r.get_json() or {}
        self.assertFalse(bool(out.get("ok")))
        self.assertEqual(out.get("decision"), "reject")
        self.assertEqual(out.get("reason"), "trade_whitelist_not_allowed")

    def test_qty_compute_failed_is_returned_as_decision_error(self):
        svc.CONFIG.update({
            "arena_enabled": False,
            "dry_run": False,
            "live_trading_enabled": True,
            "execution_venue": "aster",
            "strategy_live_trading_policy": "inherit",
            "entry_fixed_notional_enabled": False,
            "trade_whitelist_enabled": True,
            "trade_whitelist_enforcement": "hard",
            "trade_whitelist": ["BTCUSDT"],
            "entry_min_notional_usdc": 10.0,
            "entry_max_notional_usdc": 5000.0,
            "aster_min_notional_usdc": 10.0,
            "aster_max_notional_usdc": 5000.0,
            "book_execution_account_id_by_venue": {"strategy": {"aster": "ut_strategy_aster"}},
        })

        self._force_pass_threshold()
        svc._strategy_live_trading_allowed = lambda *_args, **_kwargs: True
        svc._live_trading_enabled_for_owner = lambda *_args, **_kwargs: True
        svc._hl_coin_from_pair = lambda _pair: "BTC"
        svc._order_gate_open = lambda **_kwargs: ({"ok": True}, 200)
        svc._entry_macro_scope_ok = lambda **_kwargs: False
        svc._aster_enabled_for_trading = lambda: True
        svc._aster_set_margin_type = lambda **_kwargs: {"ok": True}
        svc._aster_mid = lambda _coin: 100000.0
        svc._aster_qty_from_notional = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("aster_symbol_unavailable:unknown_symbol:BTCUSDT"))
        svc._aster_market_order_qty = lambda **_kwargs: {"resp": {"status": "REJECTED"}}

        c = svc.app.test_client()
        r = c.post(
            "/decision/entry",
            json={
                "pair": "BTC/USDT:USDT",
                "side": "long",
                "features": {"close": 100000.0, "atr_pct": 0.02},
                "size": 100.0,
                "tag": "unit_test",
                "ts": 0,
                "threshold": 0.0,
                "threshold_final": True,
            },
        )

        self.assertEqual(int(r.status_code), 200)
        out = r.get_json() or {}
        self.assertFalse(bool(out.get("ok")))
        self.assertEqual(out.get("decision"), "error")
        self.assertTrue(str(out.get("error") or "").startswith("qty_compute_failed:"))


class TestAgentChatLocalLLMDriver(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "_agent_outbox_append": svc._agent_outbox_append,
            "_doc_allowed_map": svc._doc_allowed_map,
            "_md_extract_section": svc._md_extract_section,
            "_agent_chat_context_snapshot": svc._agent_chat_context_snapshot,
            "_agent_llm_chat": svc._agent_llm_chat,
        }
        self._orig_config = dict(svc.CONFIG)
        self.items = []

        svc._agent_outbox_append = lambda _name, it: (self.items.append(it) or True)
        svc._doc_allowed_map = lambda: {}
        svc._md_extract_section = lambda *_args, **_kwargs: {"ok": False}
        svc._agent_chat_context_snapshot = lambda limit_chars=9000: {
            "ts": 0,
            "metrics": {"signals": 0, "orders_total": 0, "active_model": None},
            "config": {"dry_run": True, "live_trading_enabled": False, "execution_venue": "", "max_open_trades": 0, "threshold_trend": 0.0, "threshold_chop": 0.0},
        }
        svc._agent_llm_chat = lambda *_args, **_kwargs: {"ok": False, "error": "stub_failed"}

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(svc, k, v)
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)

    def _last_result(self):
        done = [x for x in self.items if isinstance(x, dict) and x.get("type") == "chat.result" and x.get("status") == "succeeded"]
        self.assertTrue(bool(done))
        return done[-1]

    def test_risk_uncertain_upgrades_to_p1(self):
        svc._agent_chat_driver_process(
            {"trace_id": "t-risk", "risk_level": "BAD", "intent": {"text": "状态怎么样"}, "tool_plan": []},
            {"enabled": False, "provider": "ollama", "model": "", "timeout_sec": 10},
        )
        res = self._last_result()
        self.assertEqual(res.get("risk_level"), "P1")
        self.assertTrue(bool((res.get("driver") or {}).get("risk_uncertain")))
        plan = res.get("tool_plan_suggested") or []
        self.assertFalse(any((s.get("tool") == "approval.request") for s in plan if isinstance(s, dict)))

    def test_busy_degraded_when_semaphore_unavailable(self):
        held = 0
        for _ in range(16):
            if not svc._AGENT_CHAT_DRIVER_SEM.acquire(blocking=False):
                break
            held += 1
        self.assertGreater(held, 0)
        try:
            svc._agent_chat_driver_process(
                {"trace_id": "t-busy", "risk_level": "P2", "intent": {"text": "解释一下"}, "tool_plan": []},
                {"enabled": False, "provider": "ollama", "model": "", "timeout_sec": 10},
            )
        finally:
            for _ in range(held):
                try:
                    svc._AGENT_CHAT_DRIVER_SEM.release()
                except Exception:
                    break
        res = self._last_result()
        self.assertEqual((res.get("driver") or {}).get("mode"), "busy_degraded")

    def test_llm_failed_degrades_to_template(self):
        svc._agent_chat_driver_process(
            {"trace_id": "t-llm", "risk_level": "P2", "intent": {"text": "回测一下"}, "tool_plan": []},
            {"enabled": True, "provider": "ollama", "model": "qwen2.5:7b-instruct", "timeout_sec": 10},
        )
        res = self._last_result()
        self.assertEqual((res.get("driver") or {}).get("mode"), "llm_failed_degraded")
        self.assertFalse(bool(res.get("parse_ok")))

    def test_final_recommendations_splits_auto_fix_and_human_review(self):
        artifacts = svc._agent_chat_fixed_workflow_artifacts(
            intent_text="系统出现重复拒单，想自动止血",
            doc_refs=[],
            doc_snippets=[{"doc_path": "交易AI Agent 技术文档2.0.md", "section": "FAQ: 拒单", "title": "FAQ"}],
            tool_results_compact=[],
            suggested_tool_plan=[
                {"tool": "pipeline.r2_param", "input": {"config_patch": {"max_daily_loss": -0.03}}, "requires_approval": True},
                {"tool": "pipeline.r3_bugfix", "input": {"reason": "needs_code_change"}, "requires_approval": True},
            ],
            assistant_analysis_text="",
            sandbox_plan=[{"tool": "sandbox.backtest", "input": {"strategy": "S", "timerange": "20240101-20240201"}}],
            sandbox_results=[{"tool": "sandbox.backtest", "result": {"ok": True, "zip": "z"}}],
        )
        fr = (artifacts.get("final_recommendations") or {}) if isinstance(artifacts, dict) else {}
        auto_fix = fr.get("auto_fix") if isinstance(fr.get("auto_fix"), dict) else {}
        eligible = auto_fix.get("eligible_actions") if isinstance(auto_fix.get("eligible_actions"), list) else []
        self.assertTrue(any(isinstance(x, dict) and x.get("type") == "pipeline.r2_param" and bool(x.get("eligible")) for x in eligible))
        self.assertTrue(any(isinstance(x, dict) and x.get("type") == "faq_runbook" and bool(x.get("eligible")) for x in eligible))

        human = fr.get("human_review") if isinstance(fr.get("human_review"), dict) else {}
        required = human.get("required_actions") if isinstance(human.get("required_actions"), list) else []
        self.assertTrue(any(isinstance(x, dict) and x.get("type") == "pipeline.r3_bugfix" for x in required))


class TestAgentOpenAICompatProvider(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = svc.urllib_request.urlopen
        self._orig_env = dict(os.environ)

        class _Resp:
            def __init__(self, payload):
                self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def _stub(req, timeout=3):
            url = getattr(req, "full_url", None) or str(req)
            if "/v1/models" in url or url.rstrip("/").endswith("/models"):
                return _Resp({"data": [{"id": "qwen3.5-4b"}]})
            if "/v1/chat/completions" in url or "/chat/completions" in url:
                return _Resp({"choices": [{"message": {"role": "assistant", "content": "{\"assistant_text\":\"pong\"}"}}]})
            raise RuntimeError("unexpected_url:" + str(url))

        svc.urllib_request.urlopen = _stub
        os.environ["AGENT_OPENAI_COMPAT_BASE_URL"] = "http://127.0.0.1:8080"

    def tearDown(self):
        svc.urllib_request.urlopen = self._orig_urlopen
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_openai_compat_llm_chat_parses_content(self):
        resp = svc._agent_llm_chat(
            provider="openai_compat",
            model="qwen3.5-4b",
            messages=[{"role": "user", "content": "ping"}],
            timeout_sec=3,
        )
        self.assertTrue(bool(resp.get("ok")))
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        self.assertEqual(str(msg.get("content") or "").strip(), "{\"assistant_text\":\"pong\"}")

    def test_openai_compat_health_endpoint_is_healthy(self):
        c = svc.app.test_client()
        r = c.get("/agent/llm/health?provider=openai_compat&model=qwen3.5-4b", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("healthy")))


class TestSmartLLMRouter(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(os.environ)
        self._orig_tcp_ok = getattr(svc, "_agent_llm_router_tcp_ok", None)

        os.environ["AGENT_LLM_ROUTER_ENABLED"] = "1"
        os.environ["AGENT_OPENAI_COMPAT_BASE_URL"] = "http://127.0.0.1:8080"
        os.environ["AGENT_DASHSCOPE_API_KEY"] = "x"

        svc._agent_llm_router_tcp_ok = lambda *_a, **_k: True

    def tearDown(self):
        if self._orig_tcp_ok is not None:
            svc._agent_llm_router_tcp_ok = self._orig_tcp_ok
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_router_defaults_to_small_openai_compat(self):
        sel = svc._agent_llm_route(
            purpose="agent.chat",
            req_provider="auto",
            req_model="",
            intent_norm={"kind": "general.assist", "text": "hello"},
            intent_level="L0",
            risk_level="P2",
            tool_plan=[],
        )
        self.assertEqual(str(sel.get("provider")), "openai_compat")
        self.assertEqual(str(sel.get("route")), "small")
        self.assertTrue(isinstance(sel.get("scores"), dict))
        self.assertTrue(isinstance(sel.get("matched_rules"), list))

    def test_router_switches_to_code_model_for_code_fix(self):
        sel = svc._agent_llm_route(
            purpose="agent.chat",
            req_provider="auto",
            req_model="",
            intent_norm={"kind": "general.assist", "text": "修复 bug：TypeError stack"},
            intent_level="L2",
            risk_level="P2",
            tool_plan=[],
        )
        self.assertEqual(str(sel.get("provider")), "ollama")
        self.assertTrue(bool(str(sel.get("model") or "").strip()))
        self.assertEqual(str(sel.get("route")), "code")
        self.assertTrue(any(isinstance(x, dict) and str(x.get("route")) == "code" for x in (sel.get("matched_rules") or [])))

    def test_router_switches_to_remote_for_explore(self):
        sel = svc._agent_llm_route(
            purpose="agent.rca",
            req_provider="auto",
            req_model="",
            intent_norm={"kind": "trade_monitor.analyze", "text": "做一次事件分析规划与归因"},
            intent_level="L1",
            risk_level="P2",
            tool_plan=[],
        )
        self.assertEqual(str(sel.get("provider")), "dashscope")
        self.assertEqual(str(sel.get("route")), "explore")


class TestSmartLLMRouterStats(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(os.environ)
        self._td = tempfile.TemporaryDirectory(prefix="router_stats_")
        os.environ["AGENT_OUTBOX_DIR"] = self._td.name

    def tearDown(self):
        self._td.cleanup()
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_route_stats_counts_top_rules(self):
        now_ms = int(svc._now_ms())
        p = os.path.join(self._td.name, "chat.jsonl")
        rows = [
            {"id": "1", "trace_id": "t1", "ts": now_ms - 1000, "type": "chat.result", "status": "succeeded", "llm_selected": {"route": "small", "provider": "openai_compat", "model": "qwen3.5-4b", "matched_rules": [{"id": "base_small", "route": "small", "delta": 10.0}]}},
            {"id": "2", "trace_id": "t2", "ts": now_ms - 900, "type": "chat.result", "status": "succeeded", "llm_selected": {"route": "code", "provider": "ollama", "model": "qwen2.5-coder:latest", "matched_rules": [{"id": "intent_level_L2", "route": "code", "delta": 110.0}, {"id": "kw_stacktrace_cn", "route": "code", "delta": 60.0}]}},
            {"id": "3", "trace_id": "t3", "ts": now_ms - 800, "type": "chat.result", "status": "succeeded", "llm_selected": {"route": "code", "provider": "ollama", "model": "qwen2.5-coder:latest", "matched_rules": [{"id": "intent_level_L2", "route": "code", "delta": 110.0}]}},
        ]
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        c = svc.app.test_client()
        r = c.get("/agent/llm/route/stats?window_sec=3600&limit=10", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        self.assertTrue(bool(out.get("ok")))
        top = out.get("top_rules") or []
        self.assertTrue(any(isinstance(x, dict) and str(x.get("id")) == "intent_level_L2" and int(x.get("count") or 0) == 2 for x in top))


class TestCarryFundingScheduleRouting(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        svc.CONFIG.update({
            "carry_trade_mode": "hedge",
            "carry_trade_venue": "hyperliquid",
        })
        self.client = svc.app.test_client()

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)

    def test_funding_schedule_defaults_to_hyperliquid_when_hedge_mode(self):
        res = self.client.get("/funding/schedule?n=6")
        self.assertEqual(int(res.status_code), 200)
        out = res.get_json() or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("venue")), "hyperliquid")
        self.assertTrue(15 * 60 * 1000 <= int(out.get("period_ms") or 0) <= 12 * 60 * 60 * 1000)
        sched = out.get("schedule") or []
        self.assertEqual(int(len(sched)), 6)
        self.assertEqual(int(sched[1] - sched[0]), int(out.get("period_ms") or 0))

    def test_funding_schedule_respects_explicit_venue_param(self):
        res = self.client.get("/funding/schedule?venue=hyperliquid&n=3")
        self.assertEqual(int(res.status_code), 200)
        out = res.get_json() or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("venue")), "hyperliquid")

    def test_funding_schedule_rejects_non_hl_venue_param(self):
        res = self.client.get("/funding/schedule?venue=aster&n=3")
        self.assertEqual(int(res.status_code), 400)
        out = res.get_json() or {}
        self.assertFalse(bool(out.get("ok", False)))

    def test_carry_config_rejects_non_hl_venue(self):
        res = self.client.post("/carry/config", json={"carry_trade_venue": "aster"})
        self.assertEqual(int(res.status_code), 400)
        out = res.get_json() or {}
        self.assertFalse(bool(out.get("ok", False)))

    def test_carry_status_keeps_venue_hyperliquid_when_hedge_mode(self):
        res = self.client.get("/carry/status")
        self.assertEqual(int(res.status_code), 200)
        out = res.get_json() or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("venue")), "hyperliquid")


class TestHyperliquidOwnerKeyIsolation(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(svc.os.environ)
        self._orig_config = dict(svc.CONFIG)
        self._orig_hl_state = dict(getattr(svc, "HL_STATE", {}))
        self._orig_info = getattr(svc, "Info", None)
        self._orig_exchange = getattr(svc, "Exchange", None)
        self._orig_account = getattr(svc, "Account", None)
        try:
            svc.HL_STATE.clear()
        except Exception:
            pass

        svc.os.environ["HYPERLIQUID_API_PRIVATE_KEY_STRATEGY"] = "pk_strategy"
        svc.os.environ["HYPERLIQUID_API_PRIVATE_KEY_QUANT"] = "pk_quant"
        svc.os.environ["HYPERLIQUID_ACCOUNT_ADDRESS_STRATEGY"] = "0x1111111111111111111111111111111111111111"
        svc.os.environ["HYPERLIQUID_ACCOUNT_ADDRESS_QUANT"] = "0x2222222222222222222222222222222222222222"
        svc.os.environ.pop("HYPERLIQUID_API_PRIVATE_KEY", None)
        svc.os.environ.pop("HYPERLIQUID_ACCOUNT_ADDRESS", None)
        svc.os.environ.pop("HYPERLIQUID_VAULT_ADDRESS", None)
        svc.os.environ.pop("HYPERLIQUID_VAULT_ADDRESS_STRATEGY", None)
        svc.os.environ.pop("HYPERLIQUID_VAULT_ADDRESS_QUANT", None)

        class _InfoStub:
            def __init__(self, *args, **kwargs):
                pass

        class _WalletStub:
            def __init__(self, pk: str):
                self.address = f"addr_{pk}"

        class _AccountStub:
            @staticmethod
            def from_key(pk: str):
                return _WalletStub(str(pk))

        class _ExchangeStub:
            def __init__(self, wallet, base_url: str = None, vault_address=None, account_address: str = None):
                self.wallet = wallet
                self.base_url = base_url
                self.vault_address = vault_address
                self.account_address = account_address

        svc.Info = _InfoStub
        svc.Account = _AccountStub
        svc.Exchange = _ExchangeStub

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.HL_STATE.clear()
            svc.HL_STATE.update(self._orig_hl_state)
        except Exception:
            pass
        svc.os.environ.clear()
        svc.os.environ.update(self._orig_env)
        svc.Info = self._orig_info
        svc.Exchange = self._orig_exchange
        svc.Account = self._orig_account

    def test_hl_env_get_for_owner_prefers_owner_specific(self):
        self.assertEqual(svc._hl_env_get_for_owner("HYPERLIQUID_API_PRIVATE_KEY", "strategy"), "pk_strategy")
        self.assertEqual(svc._hl_env_get_for_owner("HYPERLIQUID_API_PRIVATE_KEY", "quant"), "pk_quant")

    def test_hl_clients_isolated_by_owner(self):
        _, ex_s, acct_s = svc._hl_clients(owner="strategy")
        _, ex_q, acct_q = svc._hl_clients(owner="quant")
        self.assertNotEqual(acct_s, acct_q)
        self.assertNotEqual(ex_s.account_address, ex_q.account_address)
        self.assertNotEqual(ex_s.wallet.address, ex_q.wallet.address)
        self.assertIsNot(ex_s, ex_q)

    def test_hl_ping_payload_exposes_owner_key_presence(self):
        out = svc._hl_ping_payload()
        self.assertTrue(bool(out.get("has_api_key_strategy")))
        self.assertTrue(bool(out.get("has_api_key_quant")))
        self.assertFalse(bool(out.get("has_api_key_carry")))


class TestAsterOwnerKeyIsolation(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(svc.os.environ)
        svc.os.environ["ASTER_API_KEY"] = "k_strategy"
        svc.os.environ["ASTER_SECRET_KEY"] = "s_strategy"
        svc.os.environ["ASTER_API_KEY_QUANT"] = "k_quant"
        svc.os.environ["ASTER_SECRET_KEY_QUANT"] = "s_quant"
        svc.os.environ.pop("ASTER_API_KEY_CARRY", None)
        svc.os.environ.pop("ASTER_SECRET_KEY_CARRY", None)

        self._orig_aster_spot_http = svc._aster_spot_http

    def tearDown(self):
        svc.os.environ.clear()
        svc.os.environ.update(self._orig_env)
        svc._aster_spot_http = self._orig_aster_spot_http

    def test_aster_env_get_for_owner_prefers_owner_specific(self):
        self.assertEqual(svc._aster_env_get_for_owner("ASTER_API_KEY", "strategy"), "k_strategy")
        self.assertEqual(svc._aster_env_get_for_owner("ASTER_API_KEY", "quant"), "k_quant")

    def test_aster_env_get_for_owner_requires_quant_suffix(self):
        svc.os.environ.pop("ASTER_API_KEY_QUANT", None)
        self.assertEqual(svc._aster_env_get_for_owner("ASTER_API_KEY", "quant"), "")

    def test_aster_spot_market_order_forwards_owner(self):
        seen = {}

        def _stub(method: str, path: str, params=None, signed=False, timeout_sec=10.0, owner=None):
            seen["owner"] = owner
            return {"ok": True}

        svc._aster_spot_http = _stub
        svc._aster_spot_market_order("BTCUSDT", "BUY", quote_qty=1.0, owner="quant")
        self.assertEqual(str(seen.get("owner")), "quant")


class TestAsterOpenOrdersOwnerPropagation(unittest.TestCase):
    def setUp(self):
        self._orig_http = svc._aster_http
        self._orig_auth_mode = svc._aster_auth_mode

    def tearDown(self):
        svc._aster_http = self._orig_http
        svc._aster_auth_mode = self._orig_auth_mode

    def test_fetch_open_orders_forwards_owner(self):
        seen = {}

        def _http(method: str, path: str, params=None, signed=False, timeout_sec=10.0, owner=None):
            seen["owner"] = owner
            return {"data": [{"orderId": "1"}]}

        svc._aster_http = _http
        svc._aster_auth_mode = lambda owner=None: "v1"
        orders, err = svc._aster_fetch_open_orders(owner="quant")
        self.assertIsNone(err)
        self.assertEqual(str(seen.get("owner")), "quant")
        self.assertEqual(int(len(orders)), 1)


class TestAsterProtectOrdersOnOpen(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_http = svc._aster_http
        self._orig_auth_mode = svc._aster_auth_mode
        self._orig_symbol_from_coin = svc._aster_symbol_from_coin
        self._orig_symbol_filters = svc._aster_symbol_filters
        self._orig_mid = svc._aster_mid
        self._orig_qty_from_notional = svc._aster_qty_from_notional
        self._orig_market_order = svc._aster_market_order
        self._orig_live_enabled = svc._live_trading_enabled_for_owner
        self._orig_aster_enabled = svc._aster_enabled_for_trading_for_owner
        self._orig_book_iso = svc._book_isolation_enforce_exec_or_error

        svc.CONFIG.update({
            "dry_run": False,
            "live_trading_enabled": True,
            "aster_trading_enabled": True,
            "execute_guard_enabled": False,
            "aster_protect_on_open_enabled": True,
            "aster_protect_stop_loss_pct": 0.02,
            "aster_protect_take_profit_pct": 0.0,
            "aster_protect_trailing_callback_rate": 0.0,
            "aster_protect_min_distance_bps": 10.0,
        })

        svc._live_trading_enabled_for_owner = lambda _owner: True
        svc._aster_enabled_for_trading_for_owner = lambda _owner: True
        svc._book_isolation_enforce_exec_or_error = lambda **_kwargs: None

        svc._aster_auth_mode = lambda owner=None: "v1"
        svc._aster_symbol_from_coin = lambda coin: f"{str(coin).upper()}USDT"
        svc._aster_symbol_filters = lambda _symbol: {"stepSize": "0.001", "tickSize": "0.01", "status": "TRADING"}
        svc._aster_mid = lambda _coin, owner=None: 100.0
        svc._aster_qty_from_notional = lambda _coin, _notional, allow_adjust=False, mid=None, owner=None: 0.1
        svc._aster_market_order = lambda **_kwargs: {"resp": {"orderId": 123, "status": "FILLED", "avgPrice": "100.0", "executedQty": "0.1"}}

        self.calls = []

        def _http(method: str, path: str, params=None, signed=False, timeout_sec=10.0, owner=None):
            self.calls.append({"method": method, "path": path, "params": dict(params or {}), "signed": signed, "owner": owner})
            return {"orderId": 999, "status": "NEW"}

        svc._aster_http = _http

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        svc._aster_http = self._orig_http
        svc._aster_auth_mode = self._orig_auth_mode
        svc._aster_symbol_from_coin = self._orig_symbol_from_coin
        svc._aster_symbol_filters = self._orig_symbol_filters
        svc._aster_mid = self._orig_mid
        svc._aster_qty_from_notional = self._orig_qty_from_notional
        svc._aster_market_order = self._orig_market_order
        svc._live_trading_enabled_for_owner = self._orig_live_enabled
        svc._aster_enabled_for_trading_for_owner = self._orig_aster_enabled
        svc._book_isolation_enforce_exec_or_error = self._orig_book_iso

    def test_places_reduce_only_stop_market_after_open(self):
        with svc.app.test_request_context():
            resp = svc.aster_market_open_internal(
                coin="BTC",
                side="long",
                notional_usdc=20.0,
                execute=True,
                tag="t",
                strategy_id="sid",
                skip_gate=True,
                ab_owner="strategy",
            )
        self.assertIsNotNone(resp)
        stop_calls = [c for c in self.calls if (c.get("params") or {}).get("type") == "STOP_MARKET"]
        self.assertEqual(int(len(stop_calls)), 1)
        p = stop_calls[0].get("params") or {}
        self.assertEqual(str(p.get("reduceOnly")).lower(), "true")
        self.assertEqual(str(p.get("side")), "SELL")
        self.assertTrue(float(p.get("stopPrice") or 0.0) < 100.0)


class TestAsterMarketOpenIsolationEnforcement(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_book_iso = svc._book_isolation_enforce_exec_or_error
        self._orig_live_enabled = svc._live_trading_enabled_for_owner
        self._orig_aster_enabled = svc._aster_enabled_for_trading_for_owner
        self._orig_aster_mid = svc._aster_mid
        self._orig_aster_qty_from_notional = svc._aster_qty_from_notional
        self._orig_aster_market_order = svc._aster_market_order
        self._orig_aster_set_margin_type = svc._aster_set_margin_type
        self._orig_aster_update_leverage = svc._aster_update_leverage
        self._orig_entry_base_leverage = svc._entry_base_leverage_for_venue
        self._orig_entry_clip = svc._entry_hard_clip_leverage
        self._orig_exec_acct = svc._execution_account_id_for_book
        self.calls = []

        svc.CONFIG.update({
            "dry_run": False,
        })

        svc._live_trading_enabled_for_owner = lambda _owner: True
        svc._aster_enabled_for_trading_for_owner = lambda _owner: True

        def _iso(**kwargs):
            self.calls.append(dict(kwargs))
            return None

        svc._book_isolation_enforce_exec_or_error = _iso
        svc._execution_account_id_for_book = lambda book_id, venue=None: f"acct::{book_id}::{venue}"
        svc._entry_base_leverage_for_venue = lambda _venue: 1
        svc._entry_hard_clip_leverage = lambda lev: int(lev or 1)
        svc._aster_mid = lambda _coin, owner=None: 100.0
        svc._aster_qty_from_notional = lambda _coin, _notional, allow_adjust=False, mid=None, owner=None: 0.1
        svc._aster_set_margin_type = lambda **_kwargs: {"ok": True}
        svc._aster_update_leverage = lambda **_kwargs: {"ok": True}
        svc._aster_market_order = lambda **_kwargs: {"resp": {"orderId": "oid", "status": "FILLED"}}

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        svc._book_isolation_enforce_exec_or_error = self._orig_book_iso
        svc._live_trading_enabled_for_owner = self._orig_live_enabled
        svc._aster_enabled_for_trading_for_owner = self._orig_aster_enabled
        svc._aster_mid = self._orig_aster_mid
        svc._aster_qty_from_notional = self._orig_aster_qty_from_notional
        svc._aster_market_order = self._orig_aster_market_order
        svc._aster_set_margin_type = self._orig_aster_set_margin_type
        svc._aster_update_leverage = self._orig_aster_update_leverage
        svc._entry_base_leverage_for_venue = self._orig_entry_base_leverage
        svc._entry_hard_clip_leverage = self._orig_entry_clip
        svc._execution_account_id_for_book = self._orig_exec_acct

    def test_open_enforces_book_isolation_for_ab_owner(self):
        with svc.app.test_request_context():
            svc.aster_market_open_internal(
                coin="BTC",
                side="long",
                notional_usdc=20.0,
                execute=True,
                tag="t",
                strategy_id="sid",
                skip_gate=True,
                ab_owner="quant",
            )
        self.assertEqual(int(len(self.calls)), 1)
        self.assertEqual(str(self.calls[0].get("book_id")), "quant")
        self.assertEqual(str(self.calls[0].get("venue")), "aster")


class TestQuantBtcAltCapacityCap(unittest.TestCase):
    def setUp(self):
        self._orig_config = dict(svc.CONFIG)
        self._orig_universe = dict(getattr(svc, "UNIVERSE_STATE", {}))

        try:
            svc.UNIVERSE_STATE.clear()
            svc.UNIVERSE_STATE.update({
                "metadata": {
                    "candidates": [
                        {"coin": "ETH", "liq": {"turnover_7d_median": 100000.0}},
                    ],
                },
            })
        except Exception:
            pass

    def tearDown(self):
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)
        try:
            svc.UNIVERSE_STATE.clear()
            svc.UNIVERSE_STATE.update(self._orig_universe)
        except Exception:
            pass

    def test_portfolio_simulate_clips_alloc_by_turnover_cap(self):
        ms = 60 * 60 * 1000
        t0 = 1_700_000_000_000
        n = 600
        ts = [t0 + i * ms for i in range(n)]
        btc = [10000.0 + 0.5 * float(i) for i in range(n)]
        eth = [500.0 + 0.1 * float(i) for i in range(n)]

        sim = svc._quant_pairs_btcalt_portfolio_simulate(
            ts=ts,
            btc_close=btc,
            alt_close_by_coin={"ETH": eth},
            base_params={
                "timeframe": "1h",
                "window_ols": 60,
                "window_z": 60,
                "entry_z": 2.0,
                "exit_z": 0.5,
                "stop_z": 4.0,
                "corr_min": 0.0,
                "max_hold_bars": 240,
            },
            portfolio_params={
                "max_pairs_active": 1,
                "cluster_max_active": 1,
                "cluster_risk_budget_frac": 0.0,
                "pair_notional_usdc_max": 5000.0,
                "capacity_turnover_frac": 0.01,
                "risk_weight_mode": "equal",
                "net_btc_exposure_target": 0.0,
                "net_btc_exposure_max": 1.0,
                "circuit_breaker_dd_day": 1.0,
                "circuit_breaker_dd_week": 1.0,
            },
            notional_gross_usdc=10000.0,
            apply_cost=False,
            now_ms=ts[-1],
        )

        self.assertTrue(bool(sim.get("ok")))
        alloc = (sim.get("alloc_notional_alt") or {}).get("ETH")
        self.assertAlmostEqual(float(alloc), 1000.0, places=9)


class TestDiagnosticsIsolationScan(unittest.TestCase):
    def setUp(self):
        self._orig_events = dict(getattr(svc, "EVENTS", {}))
        self._orig_tracker = dict(getattr(svc, "TRACKER_STATE", {}))
        self._orig_orders_recent_candidates = getattr(svc, "_orders_recent_candidates", None)
        self._orig_book_iso_enabled = getattr(svc, "_book_isolation_enabled", None)

        try:
            svc.EVENTS.clear()
            svc.EVENTS.update({
                "e1": {
                    "id": "e1",
                    "event_id": "e1",
                    "ts": 1700000000000,
                    "ingested_ms": 1700000001000,
                    "pair": "BTC-PERP",
                    "side": "long",
                    "action": "open",
                    "strategy_id": "quant_pairs_btceth",
                    "ab_owner": "strategy",
                    "book_id": "strategy",
                    "arena": {"models": {}},
                },
            })
        except Exception:
            pass

        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update({
                "quant_open_positions": {
                    "BTC-PERP": {"system_id": "strategy", "ab_owner": "quant", "book_id": "quant", "strategy_id": "quant_pairs_btceth", "event_id": "e1"},
                },
                "open_positions": {},
                "carry_open_positions": {},
                "three_screen_open_positions": {},
            })
        except Exception:
            pass

        def _fake_orders_recent_candidates(*_args, **_kwargs):
            return [{
                "id": "o1",
                "event_id": "e1",
                "ts": 1700000002000,
                "ingested_ms": 1700000003000,
                "pair": "BTC-PERP",
                "side": "long",
                "action": "open",
                "strategy_id": "quant_pairs_btceth",
                "mode": "real",
                "ab_owner": "strategy",
                "system_id": "strategy",
                "execution_account_id": None,
                "book_id": None,
                "book_run_id": None,
                "exec": {"execute": True, "venue": "aster"},
            }]

        svc._orders_recent_candidates = _fake_orders_recent_candidates
        if callable(self._orig_book_iso_enabled):
            svc._book_isolation_enabled = lambda: False

    def tearDown(self):
        try:
            svc.EVENTS.clear()
            svc.EVENTS.update(self._orig_events)
        except Exception:
            pass
        try:
            svc.TRACKER_STATE.clear()
            svc.TRACKER_STATE.update(self._orig_tracker)
        except Exception:
            pass
        if self._orig_orders_recent_candidates is not None:
            svc._orders_recent_candidates = self._orig_orders_recent_candidates
        if self._orig_book_iso_enabled is not None:
            svc._book_isolation_enabled = self._orig_book_iso_enabled

    def test_diagnostics_isolation_scan_returns_layers(self):
        c = svc.app.test_client()
        resp = c.get("/diagnostics/isolation/scan?limit_events=10&limit_orders=10&max_findings=50&include_shadow=1&include_positions=1")
        self.assertEqual(int(resp.status_code), 200)
        j = resp.get_json() or {}
        self.assertTrue(bool(j.get("ok")))
        self.assertTrue(isinstance(j.get("layers"), dict))
        self.assertTrue("L2" in (j.get("layers") or {}))


class TestAutomationSkillIntents(unittest.TestCase):
    def setUp(self):
        self._orig_bugfix = svc.automation_system_monitor_run
        self._orig_paramopt = svc.agent_paramopt_run
        self._orig_paramopt_trigger = svc.automation_paramopt_trigger
        self._orig_gtw = svc.automation_gtw_run
        self._orig_shadow = svc.automation_shadow_loop_run
        self._orig_qwen_chat = svc._agent_llm_chat
        self._orig_qwen_enabled = svc.AUTOMATION.get("qwen_control_enabled")
        self._orig_qwen_provider = svc.AUTOMATION.get("qwen_control_provider")
        self._orig_qwen_model = svc.AUTOMATION.get("qwen_control_model")
        self._orig_qwen_allow_egress = svc.AUTOMATION.get("qwen_control_remote_allow_egress")

        def _fake_bugfix():
            data = svc.request.get_json(force=True) or {}
            return svc.jsonify({
                "ok": True,
                "trace_id": str(data.get("trace_id") or ""),
                "approval": {"approval_id": "appr-mock"},
                "confirm_live_required": True,
                "guard": {"allow_auto_exec": bool(data.get("allow_auto_exec", False))},
            })

        def _fake_paramopt():
            data = svc.request.get_json(force=True) or {}
            return svc.jsonify({
                "ok": True,
                "trace_id": str(data.get("trace_id") or ""),
                "mode": str(data.get("mode") or ""),
                "scopes": data.get("scopes") if isinstance(data.get("scopes"), list) else [],
                "confirm_apply": bool(data.get("confirm_apply", False)),
            })

        def _fake_paramopt_trigger():
            data = svc.request.get_json(force=True) or {}
            return svc.jsonify({
                "ok": True,
                "trace_id": str(data.get("trace_id") or ""),
                "confirm_live": bool(data.get("confirm_live", False)),
                "trigger_event": str(data.get("trigger_event") or ""),
            })

        def _fake_gtw():
            data = svc.request.get_json(force=True) or {}
            return svc.jsonify({
                "ok": True,
                "force": bool(data.get("force", False)),
                "trigger_event": str(data.get("trigger_event") or ""),
            })

        def _fake_shadow():
            data = svc.request.get_json(force=True) or {}
            return svc.jsonify({
                "ok": True,
                "trace_id": str(data.get("trace_id") or ""),
                "mode": str(data.get("mode") or "new"),
                "trigger_event": str(data.get("trigger_event") or ""),
            })

        svc.automation_system_monitor_run = _fake_bugfix
        svc.agent_paramopt_run = _fake_paramopt
        svc.automation_paramopt_trigger = _fake_paramopt_trigger
        svc.automation_gtw_run = _fake_gtw
        svc.automation_shadow_loop_run = _fake_shadow
        svc.AUTOMATION["qwen_control_enabled"] = True
        svc.AUTOMATION["qwen_control_provider"] = "openai_compat"
        svc.AUTOMATION["qwen_control_model"] = "qwen-test"
        svc.AUTOMATION["qwen_control_remote_allow_egress"] = True

        def _fake_qwen_chat(provider, model, messages, timeout_sec=60):
            user_txt = ""
            try:
                if isinstance(messages, list) and messages:
                    user_txt = str((messages[-1] or {}).get("content") or "")
            except Exception:
                user_txt = ""
            action = "automation.gtw.run"
            try:
                obj = json.loads(user_txt or "{}")
                action = str(obj.get("request_action") or "automation.gtw.run")
            except Exception:
                action = "automation.gtw.run"
            payload = {}
            if action == "automation.gtw.run":
                payload = {"force": True}
            if action == "automation.shadow_loop.run":
                payload = {"mode": "new"}
            if action == "automation.paramopt.trigger":
                payload = {"scenario": "E", "mode": "sandbox"}
            if action == "automation.system_monitor.run":
                payload = {"pair": "BTC-USDT", "request_approval": True}
            content = json.dumps({"action": action, "payload": payload, "reason": "qwen_plan"}, ensure_ascii=False)
            return {"ok": True, "data": {"message": {"role": "assistant", "content": content}}}

        svc._agent_llm_chat = _fake_qwen_chat

    def tearDown(self):
        svc.automation_system_monitor_run = self._orig_bugfix
        svc.agent_paramopt_run = self._orig_paramopt
        svc.automation_paramopt_trigger = self._orig_paramopt_trigger
        svc.automation_gtw_run = self._orig_gtw
        svc.automation_shadow_loop_run = self._orig_shadow
        svc._agent_llm_chat = self._orig_qwen_chat
        svc.AUTOMATION["qwen_control_enabled"] = self._orig_qwen_enabled
        svc.AUTOMATION["qwen_control_provider"] = self._orig_qwen_provider
        svc.AUTOMATION["qwen_control_model"] = self._orig_qwen_model
        svc.AUTOMATION["qwen_control_remote_allow_egress"] = self._orig_qwen_allow_egress

    def test_skills_list_contains_new_automation_intents(self):
        c = svc.app.test_client()
        r = c.get("/agent/skills/list", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        items = out.get("items") if isinstance(out.get("items"), list) else []
        names = {str(x.get("name") or "") for x in items if isinstance(x, dict)}
        self.assertTrue("bugfix.triage_and_draft" in names)
        self.assertTrue("bayes.optimize.strategy_scope" in names)
        self.assertTrue("bayes.optimize.system_scope" in names)
        self.assertTrue("nanoclaw.control.gtw_run" in names)
        self.assertTrue("nanoclaw.control.shadow_loop_run" in names)
        self.assertTrue("nanoclaw.control.paramopt_trigger" in names)
        self.assertTrue("nanoclaw.control.system_monitor_run" in names)
        self.assertTrue("qwen.control.gtw_run" in names)
        self.assertTrue("qwen.control.shadow_loop_run" in names)
        self.assertTrue("qwen.control.paramopt_trigger" in names)
        self.assertTrue("qwen.control.system_monitor_run" in names)

    def test_execute_bugfix_triage_and_draft_enforces_guardrails(self):
        c = svc.app.test_client()
        payload = {
            "trace_id": "t-bugfix-skill",
            "async": False,
            "tool_plan": [
                {"tool": "bugfix.triage_and_draft", "input": {"pair": "BTC-USDT", "lookback_days": 5}},
            ],
        }
        r = c.post("/agent/skills/execute", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        results = out.get("results") if isinstance(out.get("results"), list) else []
        self.assertEqual(int(len(results)), 1)
        res0 = results[0].get("result") if isinstance(results[0], dict) else {}
        guardrails = res0.get("guardrails") if isinstance(res0.get("guardrails"), dict) else {}
        self.assertTrue(bool(guardrails.get("request_approval")))
        self.assertFalse(bool(guardrails.get("allow_auto_exec")))
        self.assertTrue(bool(guardrails.get("confirm_live_required")))

    def test_execute_bayes_scope_rejects_apply_mode(self):
        c = svc.app.test_client()
        payload = {
            "trace_id": "t-bayes-apply",
            "async": False,
            "tool_plan": [
                {"tool": "bayes.optimize.strategy_scope", "input": {"mode": "apply"}},
            ],
        }
        r = c.post("/agent/skills/execute", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        results = out.get("results") if isinstance(out.get("results"), list) else []
        self.assertEqual(int(len(results)), 1)
        res0 = results[0].get("result") if isinstance(results[0], dict) else {}
        self.assertFalse(bool(res0.get("ok")))
        self.assertEqual(str(res0.get("error") or ""), "apply_forbidden_in_skill")

    def test_execute_bayes_system_scope_forces_quant_entry(self):
        c = svc.app.test_client()
        payload = {
            "trace_id": "t-bayes-system",
            "async": False,
            "tool_plan": [
                {"tool": "bayes.optimize.system_scope", "input": {"mode": "sandbox", "n_iter": 6}},
            ],
        }
        r = c.post("/agent/skills/execute", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        results = out.get("results") if isinstance(out.get("results"), list) else []
        self.assertEqual(int(len(results)), 1)
        res0 = results[0].get("result") if isinstance(results[0], dict) else {}
        wrapped = res0.get("result") if isinstance(res0.get("result"), dict) else {}
        scopes = wrapped.get("scopes") if isinstance(wrapped.get("scopes"), list) else []
        self.assertEqual(scopes, ["quant", "entry"])

    def test_execute_nanoclaw_control_tools_for_automation_triggers(self):
        c = svc.app.test_client()
        payload = {
            "trace_id": "t-nanoclaw-control",
            "async": False,
            "tool_plan": [
                {"tool": "nanoclaw.control.gtw_run", "input": {"force": True}},
                {"tool": "nanoclaw.control.shadow_loop_run", "input": {"mode": "new"}},
                {"tool": "nanoclaw.control.paramopt_trigger", "input": {"scenario": "E"}},
                {"tool": "nanoclaw.control.system_monitor_run", "input": {"pair": "BTC-USDT"}},
            ],
        }
        r = c.post("/agent/skills/execute", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        results = out.get("results") if isinstance(out.get("results"), list) else []
        self.assertEqual(int(len(results)), 4)
        intents = []
        for row in results:
            if not isinstance(row, dict):
                continue
            got = row.get("result") if isinstance(row.get("result"), dict) else {}
            intents.append(str(got.get("intent") or ""))
        self.assertTrue("nanoclaw.control.gtw_run" in intents)
        self.assertTrue("nanoclaw.control.shadow_loop_run" in intents)
        self.assertTrue("nanoclaw.control.paramopt_trigger" in intents)
        self.assertTrue("nanoclaw.control.system_monitor_run" in intents)

    def test_execute_qwen_control_tools_for_automation_triggers(self):
        c = svc.app.test_client()
        payload = {
            "trace_id": "t-qwen-control",
            "async": False,
            "tool_plan": [
                {"tool": "qwen.control.gtw_run", "input": {"force": True}},
                {"tool": "qwen.control.shadow_loop_run", "input": {"mode": "new"}},
                {"tool": "qwen.control.paramopt_trigger", "input": {"scenario": "E"}},
                {"tool": "qwen.control.system_monitor_run", "input": {"pair": "BTC-USDT"}},
            ],
        }
        r = c.post("/agent/skills/execute", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        results = out.get("results") if isinstance(out.get("results"), list) else []
        self.assertEqual(int(len(results)), 4)
        intents = []
        engines = []
        for row in results:
            if not isinstance(row, dict):
                continue
            got = row.get("result") if isinstance(row.get("result"), dict) else {}
            intents.append(str(got.get("intent") or ""))
            engines.append(str(got.get("engine") or ""))
        self.assertTrue("qwen.control.gtw_run" in intents)
        self.assertTrue("qwen.control.shadow_loop_run" in intents)
        self.assertTrue("qwen.control.paramopt_trigger" in intents)
        self.assertTrue("qwen.control.system_monitor_run" in intents)
        self.assertTrue(any(x == "qwen_remote" for x in engines))


class TestNanoclawUpgradeMonitor(unittest.TestCase):
    def setUp(self):
        self._orig_recent_paths = svc._agent_outbox_recent_paths
        self._orig_push_enqueue = svc._agent_push_enqueue_local
        self._orig_push_throttle = svc._agent_push_channel_throttle_ok
        self._orig_stage = svc.AUTOMATION.get("nanoclaw_upgrade_stage")
        self._orig_alert_enabled = svc.AUTOMATION.get("nanoclaw_threshold_alert_enabled")
        self._orig_auto_downgrade = svc.AUTOMATION.get("nanoclaw_threshold_auto_downgrade_enabled")
        self._orig_min_reports = svc.AUTOMATION.get("nanoclaw_threshold_min_reports")
        self._orig_min_approval = svc.AUTOMATION.get("nanoclaw_threshold_min_approval_decisions")
        self._orig_min_applied = svc.AUTOMATION.get("nanoclaw_threshold_min_applied_actions")
        self._orig_report_min = svc.AUTOMATION.get("nanoclaw_threshold_first_report_hit_rate_min")
        self._orig_approval_min = svc.AUTOMATION.get("nanoclaw_threshold_approval_pass_rate_min")
        self._orig_rollback_max = svc.AUTOMATION.get("nanoclaw_threshold_rollback_rate_max")
        self._alerts = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self._base = self._tmpdir.name
        self._now = int(svc._now_ms())

        self._p_rca = os.path.join(self._base, "rca.jsonl")
        self._p_appr = os.path.join(self._base, "approvals.jsonl")
        self._p_audit = os.path.join(self._base, "audit_actions.jsonl")

        with open(self._p_rca, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": "r1",
                "trace_id": "tr-1",
                "ts": int(self._now),
                "event_type": "system.monitor.report",
                "severity": "P2",
                "result": {"summary": {"faq_hits": ["reject_rate_spike"], "changeset_draft_id": "d1", "approval_id": "a1"}},
            }, ensure_ascii=False) + "\n")
            f.write(json.dumps({
                "id": "r2",
                "trace_id": "tr-2",
                "ts": int(self._now),
                "event_type": "system.monitor.report",
                "severity": "P3",
                "result": {"summary": {"faq_hits": [], "changeset_draft_id": None, "approval_id": None}},
            }, ensure_ascii=False) + "\n")

        with open(self._p_appr, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "a1", "trace_id": "tr-1", "ts": int(self._now), "decision": "approved"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"id": "a2", "trace_id": "tr-2", "ts": int(self._now), "decision": "rejected"}, ensure_ascii=False) + "\n")

        with open(self._p_audit, "w", encoding="utf-8") as f:
            f.write(json.dumps({"name": "governance.changeset.apply", "ts": int(self._now), "payload": {"ok": True, "approval_id": "a1"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"name": "automation.config.set", "ts": int(self._now), "payload": {"ok": True, "approval_id": "a2"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"name": "governance.changeset.rollback", "ts": int(self._now), "payload": {"ok": True, "rollback": {"ok": True}}}, ensure_ascii=False) + "\n")

        def _fake_recent_paths(stem: str, days: int, now_ms: int):
            if str(stem) == "rca":
                return [svc.Path(self._p_rca)]
            if str(stem) == "approvals":
                return [svc.Path(self._p_appr)]
            if str(stem) == "audit_actions":
                return [svc.Path(self._p_audit)]
            return []

        svc._agent_outbox_recent_paths = _fake_recent_paths
        svc._agent_push_channel_throttle_ok = lambda channel, idempotency_key, now_ms: (True, {"ok": True})

        def _fake_push_enqueue_local(*, channel, message, severity, extras=None, trace_id=None, idempotency_key=None, expires_at=None):
            self._alerts.append({
                "channel": channel,
                "message": message,
                "severity": severity,
                "extras": (extras if isinstance(extras, dict) else {}),
            })
            return {"ok": True, "queued": True, "id": "alert-mock"}

        svc._agent_push_enqueue_local = _fake_push_enqueue_local

    def tearDown(self):
        svc._agent_outbox_recent_paths = self._orig_recent_paths
        svc._agent_push_enqueue_local = self._orig_push_enqueue
        svc._agent_push_channel_throttle_ok = self._orig_push_throttle
        svc.AUTOMATION["nanoclaw_upgrade_stage"] = self._orig_stage
        svc.AUTOMATION["nanoclaw_threshold_alert_enabled"] = self._orig_alert_enabled
        svc.AUTOMATION["nanoclaw_threshold_auto_downgrade_enabled"] = self._orig_auto_downgrade
        svc.AUTOMATION["nanoclaw_threshold_min_reports"] = self._orig_min_reports
        svc.AUTOMATION["nanoclaw_threshold_min_approval_decisions"] = self._orig_min_approval
        svc.AUTOMATION["nanoclaw_threshold_min_applied_actions"] = self._orig_min_applied
        svc.AUTOMATION["nanoclaw_threshold_first_report_hit_rate_min"] = self._orig_report_min
        svc.AUTOMATION["nanoclaw_threshold_approval_pass_rate_min"] = self._orig_approval_min
        svc.AUTOMATION["nanoclaw_threshold_rollback_rate_max"] = self._orig_rollback_max
        self._tmpdir.cleanup()

    def test_monitor_endpoint_reports_expected_indicators(self):
        c = svc.app.test_client()
        r = c.get("/automation/nanoclaw/upgrade/monitor?lookback_hours=24", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        self.assertTrue(bool(out.get("ok")))
        ind = out.get("indicators") if isinstance(out.get("indicators"), dict) else {}
        self.assertAlmostEqual(float(ind.get("first_report_hit_rate")), 0.5, places=6)
        self.assertAlmostEqual(float(ind.get("approval_pass_rate")), 0.5, places=6)
        self.assertAlmostEqual(float(ind.get("rollback_rate")), 0.5, places=6)
        chain = out.get("chain_check") if isinstance(out.get("chain_check"), dict) else {}
        self.assertTrue(bool(chain.get("required_rules_ok")))

    def test_threshold_breach_triggers_alert_and_downgrades_stage(self):
        svc.AUTOMATION["nanoclaw_upgrade_stage"] = "C"
        svc.AUTOMATION["nanoclaw_threshold_alert_enabled"] = True
        svc.AUTOMATION["nanoclaw_threshold_auto_downgrade_enabled"] = True
        svc.AUTOMATION["nanoclaw_threshold_min_reports"] = 1
        svc.AUTOMATION["nanoclaw_threshold_min_approval_decisions"] = 1
        svc.AUTOMATION["nanoclaw_threshold_min_applied_actions"] = 1
        svc.AUTOMATION["nanoclaw_threshold_first_report_hit_rate_min"] = 0.8
        svc.AUTOMATION["nanoclaw_threshold_approval_pass_rate_min"] = 0.8
        svc.AUTOMATION["nanoclaw_threshold_rollback_rate_max"] = 0.2
        c = svc.app.test_client()
        r = c.get("/automation/nanoclaw/upgrade/monitor?lookback_hours=24", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        policy = out.get("threshold_policy") if isinstance(out.get("threshold_policy"), dict) else {}
        breaches = policy.get("breaches") if isinstance(policy.get("breaches"), list) else []
        self.assertTrue(len(breaches) >= 1)
        auto_downgrade = policy.get("auto_downgrade") if isinstance(policy.get("auto_downgrade"), dict) else {}
        self.assertTrue(bool(auto_downgrade.get("downgraded")))
        self.assertEqual(str(svc.AUTOMATION.get("nanoclaw_upgrade_stage") or ""), "B")
        alerting = policy.get("alerting") if isinstance(policy.get("alerting"), dict) else {}
        self.assertTrue(bool(alerting.get("emitted")))
        self.assertTrue(len(self._alerts) >= 1)
        self.assertEqual(str((self._alerts[0] or {}).get("channel") or ""), "alert")


class TestApprovalAnalystLadder(unittest.TestCase):
    def setUp(self):
        self._orig_llm_chat = svc._agent_llm_chat
        self._orig_provider_health = svc._approval_analyst_provider_health
        self._orig_probe_state = svc.TRACKER_STATE.get("approval_analyst_probe")
        self._orig_remote_provider = svc.AUTOMATION.get("approval_analyst_remote_provider")
        self._orig_remote_model = svc.AUTOMATION.get("approval_analyst_remote_model")
        self._orig_local_provider = svc.AUTOMATION.get("approval_analyst_local_provider")
        self._orig_local_model = svc.AUTOMATION.get("approval_analyst_local_model")
        self._orig_allow_remote_egress = svc.AUTOMATION.get("approval_analyst_remote_allow_egress")
        self._orig_enabled = svc.AUTOMATION.get("approval_analyst_llm_enabled")
        self._orig_timeout = svc.AUTOMATION.get("approval_analyst_llm_timeout_sec")
        svc.AUTOMATION["approval_analyst_llm_enabled"] = True
        svc.AUTOMATION["approval_analyst_remote_allow_egress"] = True
        svc.AUTOMATION["approval_analyst_remote_provider"] = "openai_compat"
        svc.AUTOMATION["approval_analyst_remote_model"] = "remote-test"
        svc.AUTOMATION["approval_analyst_local_provider"] = "ollama"
        svc.AUTOMATION["approval_analyst_local_model"] = "local-test"
        svc.AUTOMATION["approval_analyst_llm_timeout_sec"] = 30
        svc._approval_analyst_provider_health = lambda **kwargs: {
            "tier": str(kwargs.get("tier") or ""),
            "provider": str(kwargs.get("provider") or ""),
            "model": str(kwargs.get("model") or ""),
            "available": True,
            "reason": "ok",
        }
        svc.TRACKER_STATE["approval_analyst_probe"] = {"preferred_tier": "remote", "remote": {"ok": True}}

    def tearDown(self):
        svc._agent_llm_chat = self._orig_llm_chat
        svc._approval_analyst_provider_health = self._orig_provider_health
        svc.TRACKER_STATE["approval_analyst_probe"] = self._orig_probe_state
        svc.AUTOMATION["approval_analyst_remote_provider"] = self._orig_remote_provider
        svc.AUTOMATION["approval_analyst_remote_model"] = self._orig_remote_model
        svc.AUTOMATION["approval_analyst_local_provider"] = self._orig_local_provider
        svc.AUTOMATION["approval_analyst_local_model"] = self._orig_local_model
        svc.AUTOMATION["approval_analyst_remote_allow_egress"] = self._orig_allow_remote_egress
        svc.AUTOMATION["approval_analyst_llm_enabled"] = self._orig_enabled
        svc.AUTOMATION["approval_analyst_llm_timeout_sec"] = self._orig_timeout

    @staticmethod
    def _sample_approval_and_draft():
        approval = {"id": "ap-1", "draft_id": "dr-1", "trace_id": "tr-1", "action": "config.apply", "reason": "test"}
        draft_entry = {
            "id": "dr-1",
            "trace_id": "tr-1",
            "draft": {
                "trace_id": "tr-1",
                "doc_refs": [{"doc_path": "交易AI Agent 技术文档2.0.md", "section": "7.6"}],
                "gate_result": {"pass": True, "decision": "pass"},
                "change_bundle_draft": {
                    "change_id": "chg-1",
                    "change_tags": ["tighten"],
                    "config_diff": {"changes": [{"key": "x", "from": 1, "to": 2, "direction": "tighten"}]},
                    "delta_metrics": {"profit_factor": {"baseline": 1.0, "candidate": 1.1, "delta": 0.1}},
                    "governance": {"baseline_judge": {"decision": "pass"}},
                },
                "changeset": {"rollback_point_id": "rb-1", "expires_at": int(svc._now_ms()) + 3600_000},
            },
        }
        return approval, draft_entry

    def test_remote_success_used_first(self):
        def _fake_llm(provider, model, messages, timeout_sec=60):
            return {"ok": True, "data": {"message": {"role": "assistant", "content": json.dumps({"decision": "warn", "blockers": [], "reasons": ["remote"], "required_followups": []}, ensure_ascii=False)}}}

        svc._agent_llm_chat = _fake_llm
        ap, dr = self._sample_approval_and_draft()
        brief = svc._approval_brief_build(approval=ap, draft_entry=dr, now_ms=int(svc._now_ms()))
        analyst = brief.get("analyst") if isinstance(brief.get("analyst"), dict) else {}
        self.assertEqual(str(analyst.get("tier") or ""), "remote")
        self.assertEqual(str((brief.get("producer") or {}).get("engine") or ""), "llm_remote")

    def test_local_fallback_when_remote_unavailable(self):
        calls = {"n": 0}

        def _fake_llm(provider, model, messages, timeout_sec=60):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": False, "error": "remote_down"}
            return {"ok": True, "data": {"message": {"role": "assistant", "content": json.dumps({"decision": "warn", "blockers": [], "reasons": ["local"], "required_followups": []}, ensure_ascii=False)}}}

        svc._agent_llm_chat = _fake_llm
        ap, dr = self._sample_approval_and_draft()
        brief = svc._approval_brief_build(approval=ap, draft_entry=dr, now_ms=int(svc._now_ms()))
        analyst = brief.get("analyst") if isinstance(brief.get("analyst"), dict) else {}
        self.assertEqual(str(analyst.get("tier") or ""), "local")
        self.assertEqual(str((brief.get("producer") or {}).get("engine") or ""), "llm_local")

    def test_rule_fallback_when_llm_unavailable(self):
        def _fake_llm(provider, model, messages, timeout_sec=60):
            return {"ok": False, "error": "unavailable"}

        svc._agent_llm_chat = _fake_llm
        ap, dr = self._sample_approval_and_draft()
        brief = svc._approval_brief_build(approval=ap, draft_entry=dr, now_ms=int(svc._now_ms()))
        analyst = brief.get("analyst") if isinstance(brief.get("analyst"), dict) else {}
        self.assertEqual(str(analyst.get("tier") or ""), "rule")
        self.assertEqual(str((brief.get("producer") or {}).get("engine") or ""), "rule")


class TestApprovalBriefHealth(unittest.TestCase):
    def setUp(self):
        self._orig_tcp = svc._agent_llm_router_tcp_ok
        self._orig_openai_base = svc._agent_openai_compat_base_url
        self._orig_ollama_base = svc._agent_ollama_base_url
        self._orig_dash_key = svc._agent_dashscope_api_key
        self._orig_allow_egress = svc.AUTOMATION.get("approval_analyst_remote_allow_egress")
        self._orig_remote_provider = svc.AUTOMATION.get("approval_analyst_remote_provider")
        self._orig_remote_model = svc.AUTOMATION.get("approval_analyst_remote_model")
        self._orig_local_provider = svc.AUTOMATION.get("approval_analyst_local_provider")
        self._orig_local_model = svc.AUTOMATION.get("approval_analyst_local_model")
        self._orig_enabled = svc.AUTOMATION.get("approval_analyst_llm_enabled")
        svc.AUTOMATION["approval_analyst_llm_enabled"] = True
        svc.AUTOMATION["approval_analyst_remote_allow_egress"] = True
        svc.AUTOMATION["approval_analyst_remote_provider"] = "openai_compat"
        svc.AUTOMATION["approval_analyst_remote_model"] = "r-model"
        svc.AUTOMATION["approval_analyst_local_provider"] = "ollama"
        svc.AUTOMATION["approval_analyst_local_model"] = "l-model"
        svc._agent_openai_compat_base_url = lambda: "http://127.0.0.1:18080/v1"
        svc._agent_ollama_base_url = lambda: "http://127.0.0.1:11434"
        svc._agent_dashscope_api_key = lambda: ""

    def tearDown(self):
        svc._agent_llm_router_tcp_ok = self._orig_tcp
        svc._agent_openai_compat_base_url = self._orig_openai_base
        svc._agent_ollama_base_url = self._orig_ollama_base
        svc._agent_dashscope_api_key = self._orig_dash_key
        svc.AUTOMATION["approval_analyst_remote_allow_egress"] = self._orig_allow_egress
        svc.AUTOMATION["approval_analyst_remote_provider"] = self._orig_remote_provider
        svc.AUTOMATION["approval_analyst_remote_model"] = self._orig_remote_model
        svc.AUTOMATION["approval_analyst_local_provider"] = self._orig_local_provider
        svc.AUTOMATION["approval_analyst_local_model"] = self._orig_local_model
        svc.AUTOMATION["approval_analyst_llm_enabled"] = self._orig_enabled

    def test_brief_health_prefers_remote_when_reachable(self):
        svc._agent_llm_router_tcp_ok = lambda base, timeout_sec=0.25: True
        c = svc.app.test_client()
        r = c.get("/agent/approvals/brief/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("selected_tier") or ""), "remote")
        tiers = out.get("tiers") if isinstance(out.get("tiers"), dict) else {}
        remote = tiers.get("remote") if isinstance(tiers.get("remote"), dict) else {}
        self.assertTrue(bool(remote.get("available")))

    def test_brief_health_falls_back_to_local_then_rule(self):
        svc._agent_llm_router_tcp_ok = lambda base, timeout_sec=0.25: False
        c = svc.app.test_client()
        r = c.get("/agent/approvals/brief/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(int(r.status_code), 200)
        out = r.get_json(force=True) or {}
        self.assertEqual(str(out.get("selected_tier") or ""), "rule")
        tiers = out.get("tiers") if isinstance(out.get("tiers"), dict) else {}
        self.assertFalse(bool(((tiers.get("remote") if isinstance(tiers.get("remote"), dict) else {}) or {}).get("available")))
        self.assertFalse(bool(((tiers.get("local") if isinstance(tiers.get("local"), dict) else {}) or {}).get("available")))
        self.assertTrue(bool(((tiers.get("rule") if isinstance(tiers.get("rule"), dict) else {}) or {}).get("available")))


if __name__ == "__main__":
    unittest.main()

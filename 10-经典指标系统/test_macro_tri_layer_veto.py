import unittest

import ml_trade_service as svc


class TestMacroTriLayerSnapshot(unittest.TestCase):
    def setUp(self):
        self._orig_now_ms = svc._now_ms
        self._orig_std_tf = svc._entry_macro_btceth_tf_std_at
        self._orig_std_1h = svc._entry_macro_btceth_hourly_std_at
        self._orig_trend_at = svc._macro_trend_at
        self._orig_config = dict(svc.CONFIG)

        svc._now_ms = lambda: 1_700_000_000_000

        def _std_tf(ts_ms, timeframe="12h"):
            if str(timeframe) == "1d":
                return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.35}, "eth": {"dir": 1, "risk_pct": 0.30}}
            return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.40}, "eth": {"dir": 1, "risk_pct": 0.38}}

        svc._entry_macro_btceth_tf_std_at = _std_tf

        self._n = 0

        def _std_1h(_ts_ms):
            self._n += 1
            v = 0.40 + 0.05 * float(self._n)
            r = 0.30 + 0.02 * float(self._n)
            return {"ok": True, "btc": {"dir": 1, "value_pct": v, "risk_pct": r}, "eth": {"dir": 1, "value_pct": v, "risk_pct": r}}

        svc._entry_macro_btceth_hourly_std_at = _std_1h

        def _trend_at(ts_ms, coin="BTC", lookback_days=400):
            if int(ts_ms) < 1_700_000_000_000 - 12 * 3600_000:
                return {"trend_w_dir": 1, "trend_d_dir": 1, "trend_w_slope": 0.08, "trend_rate_change_dw": 0.40}
            return {"trend_w_dir": 1, "trend_d_dir": 1, "trend_w_slope": 0.10, "trend_rate_change_dw": 0.50}

        svc._macro_trend_at = _trend_at
        svc.CONFIG["quant_pairs_macro_riskd_mid_thr"] = 0.60
        svc.CONFIG["quant_pairs_macro_riskd_high_thr"] = 0.80
        svc.CONFIG["quant_pairs_macro_crash_risk1h_thr"] = 0.90
        svc.CONFIG["quant_pairs_macro_crash_chg_strength_thr"] = 0.12

    def tearDown(self):
        svc._now_ms = self._orig_now_ms
        svc._entry_macro_btceth_tf_std_at = self._orig_std_tf
        svc._entry_macro_btceth_hourly_std_at = self._orig_std_1h
        svc._macro_trend_at = self._orig_trend_at
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_config)

    def test_snapshot_has_tri_layer_fields(self):
        out = svc._macro_btc_dir_snapshot(timeframe="1h", horizon_h=12, short_n=3)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(int(out.get("dir_w") or 0), 1)
        self.assertEqual(int(out.get("dir_d") or 0), 1)
        self.assertEqual(str(out.get("risk_budget_tier")), "risk_on")
        self.assertTrue(bool(out.get("allow_open")))
        self.assertEqual(str(out.get("rule_id")), "R-A1")
        self.assertEqual(str(out.get("input_source")), "btceth_weighted")
        self.assertIn("std_1d", out.get("macro_std") or {})

    def test_extreme_riskd_maps_to_ra4(self):
        def _std_tf(ts_ms, timeframe="12h"):
            if str(timeframe) == "1d":
                return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.88}, "eth": {"dir": 1, "risk_pct": 0.86}}
            return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.40}, "eth": {"dir": 1, "risk_pct": 0.38}}

        svc._entry_macro_btceth_tf_std_at = _std_tf
        out = svc._macro_btc_dir_snapshot(timeframe="1h", horizon_h=12, short_n=3)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(str(out.get("rule_id")), "R-A4")
        self.assertEqual(str(out.get("risk_budget_tier")), "risk_off")
        self.assertFalse(bool(out.get("allow_open")))
        self.assertEqual(str(out.get("addon_pacing")), "pause")

    def test_weighted_trend_uses_btceth_mix(self):
        svc.CONFIG["quant_pairs_macro_input_w_btc"] = 0.2
        svc.CONFIG["quant_pairs_macro_input_w_eth"] = 0.8

        def _std_tf(ts_ms, timeframe="12h"):
            if str(timeframe) == "1d":
                return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.35}, "eth": {"dir": -1, "risk_pct": 0.30}}
            return {"ok": True, "btc": {"dir": 1, "risk_pct": 0.40}, "eth": {"dir": -1, "risk_pct": 0.38}}

        def _trend_at(ts_ms, coin="BTC", lookback_days=400):
            if str(coin).upper() == "BTC":
                return {"trend_w_dir": 1, "trend_d_dir": 1, "trend_w_slope": 0.10, "trend_d_slope": 0.08, "trend_rate_change_dw": 0.50}
            return {"trend_w_dir": -1, "trend_d_dir": -1, "trend_w_slope": -0.20, "trend_d_slope": -0.15, "trend_rate_change_dw": -0.60}

        svc._entry_macro_btceth_tf_std_at = _std_tf
        svc._macro_trend_at = _trend_at
        out = svc._macro_btc_dir_snapshot(timeframe="1h", horizon_h=12, short_n=3)
        self.assertTrue(bool(out.get("ok")))
        self.assertEqual(int(out.get("dir_w") or 0), -1)
        self.assertEqual(int(out.get("dir_d") or 0), -1)
        self.assertEqual(str(out.get("rule_id")), "R-A1")
        w = out.get("input_weights") or {}
        self.assertAlmostEqual(float(w.get("btc") or 0.0), 0.2, places=6)
        self.assertAlmostEqual(float(w.get("eth") or 0.0), 0.8, places=6)


class TestMacroTriLayerVeto(unittest.TestCase):
    def setUp(self):
        self._orig_cfg = dict(svc.CONFIG)
        self._orig_snap = svc._macro_btc_dir_snapshot
        svc.CONFIG["quant_pairs_macro_trend_veto_enabled"] = True

    def tearDown(self):
        svc._macro_btc_dir_snapshot = self._orig_snap
        svc.CONFIG.clear()
        svc.CONFIG.update(self._orig_cfg)

    def test_risk_budget_blocks_open(self):
        svc._macro_btc_dir_snapshot = lambda **_kwargs: {
            "ok": True,
            "dir_h": 1,
            "dir_w": 1,
            "dir_d": 1,
            "dir_short": 1,
            "chg_strength": 0.20,
            "risk_budget_tier": "risk_off",
            "crash_switch": False,
            "target_net_bias": 0.2,
            "max_net_exposure": 0.1,
            "allow_open": False,
            "allow_addon": False,
        }
        out = svc._quant_pairs_macro_trend_veto("long_alt_short_btc")
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("blocked")))
        self.assertEqual(str(out.get("blocked_reason")), "macro_risk_budget_block_open")
        self.assertEqual(int(out.get("TrendDirW") or 0), 1)
        self.assertEqual(str(out.get("RuleId")), "R-A0")

    def test_crash_switch_blocks_open(self):
        svc._macro_btc_dir_snapshot = lambda **_kwargs: {
            "ok": True,
            "dir_h": 1,
            "dir_w": 1,
            "dir_d": 1,
            "dir_short": 1,
            "chg_strength": 0.30,
            "risk_budget_tier": "risk_on",
            "crash_switch": True,
            "target_net_bias": 0.6,
            "max_net_exposure": 0.3,
            "allow_open": False,
            "allow_addon": False,
            "addon_pacing": "pause",
            "rule_id": "R-A4",
        }
        out = svc._quant_pairs_macro_trend_veto("long_alt_short_btc")
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("blocked")))
        self.assertEqual(str(out.get("blocked_reason")), "macro_crash_switch_block_open")
        self.assertTrue(bool(out.get("CrashSwitch")))
        self.assertEqual(str(out.get("AddonPacing")), "pause")
        self.assertEqual(str(out.get("RuleId")), "R-A4")

    def test_addon_blocked_when_tri_layer_disallow(self):
        svc._macro_btc_dir_snapshot = lambda **_kwargs: {
            "ok": True,
            "dir_h": 1,
            "dir_w": 1,
            "dir_d": 1,
            "dir_short": 1,
            "chg_strength": 0.30,
            "risk_budget_tier": "neutral",
            "crash_switch": False,
            "target_net_bias": 0.2,
            "max_net_exposure": 0.2,
            "allow_open": True,
            "allow_addon": False,
            "addon_pacing": "tight",
            "rule_id": "R-A2",
        }
        out = svc._quant_pairs_macro_trend_veto("addon")
        self.assertTrue(bool(out.get("ok")))
        self.assertTrue(bool(out.get("blocked")))
        self.assertEqual(str(out.get("blocked_reason")), "macro_addon_pacing_block")
        self.assertEqual(str(out.get("AddonPacing")), "tight")

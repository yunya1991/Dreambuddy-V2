"""任务① RED 测试：trailing_stop 接入 param_center

TDD 红灯阶段 — 验证 TrailingStopComponent 通过 param_center.api.get_sltp_params
获取 atr_mult_range，FAIL-OPEN 回退到配置默认值。

接入策略：
  - param_center.api.get_sltp_params(symbol) -> SLTPParams.atr_mult_range: Tuple[float, float]
  - 区间 → 标量：取中位数（atr_mult_range[0] + atr_mult_range[1]) / 2
  - FAIL-OPEN：param_center 不可用 → 回退 algo_cfg["atr_multiplier"]（默认 2.5）

运行：
  cd 16-调控系统 && python -m pytest tests/trailing_stop/test_param_center_integration.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_BASE_DIR = Path(__file__).resolve().parents[2]            # 16-调控系统
_CORE_DIR = _BASE_DIR / "core"
sys.path.insert(0, str(_CORE_DIR))


def _mock_fetch(positions_by_system):
    """构造 fetch_all_positions 返回结构。"""
    by_system = {}
    all_positions = []
    for sys_name, pos_list in positions_by_system.items():
        by_system[sys_name] = {
            "positions": pos_list,
            "equity": 150.0,
            "fallback_used": False,
        }
        for p in pos_list:
            enriched = dict(p)
            enriched.setdefault("system", sys_name)
            all_positions.append(enriched)
    return {
        "by_system": by_system,
        "positions": all_positions,
        "total_systems": len(by_system),
        "total_positions": len(all_positions),
        "total_equity": 150.0 * len(by_system),
    }


class _FakeSLTPParams:
    """轻量 stand-in for memory_l4.bcrm2.sl_tp_config.SLTPParams。"""

    def __init__(
        self,
        sl_floor=0.04,
        tp_floor=0.12,
        atr_mult_range=(4.0, 6.0),
        rr_ratio_target=3.0,
        tp_decay_floor=0.12,
        tp_decay_hours=(12, 72),
    ):
        self.sl_floor = sl_floor
        self.tp_floor = tp_floor
        self.atr_mult_range = atr_mult_range
        self.rr_ratio_target = rr_ratio_target
        self.tp_decay_floor = tp_decay_floor
        self.tp_decay_hours = tp_decay_hours


class TestParamCenterIntegration(unittest.TestCase):
    """验证 trailing_stop 通过 param_center 动态获取 ATR 倍数。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="trail_pc_test_")
        self._state_file = Path(self._tmpdir) / "state.json"
        self._cfg_file = Path(self._tmpdir) / "trailing_stop.json"
        # 配置默认 atr_multiplier=2.5（FAIL-OPEN 回退值）
        self._cfg_file.write_text(
            json.dumps({
                "version": "1.0",
                "enabled_systems": ["v15_martin", "yijing_bcrm"],
                "cache_ttl_sec": 0,
                "persist_enabled": True,
                "persist_file": str(self._state_file),
                "algorithm": {
                    "arm_threshold_pct": 0.20,
                    "atr_period": 14,
                    "atr_multiplier": 2.5,        # FAIL-OPEN 回退值
                    "min_trail_pct": 0.03,
                    "atr_fallback_pct": 0.02,
                },
                "trigger_cooldown_sec": 300,
                "auto_close_after_sec": 1_000_000,
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ----------------------------------------------------------------
    # T1（RED）: param_center 返回 atr_mult_range=(4.0, 6.0) → 使用中位数 5.0
    # ----------------------------------------------------------------
    def test_t1_uses_param_center_atr_mult_median(self):
        from trailing_stop.component import TrailingStopComponent
        from trailing_stop.types import TrailingAction, TrailingStatus

        # 100 → 104 × 5x = 20% 有效收益 → ARM
        positions = _mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })

        fake_params = _FakeSLTPParams(atr_mult_range=(4.0, 6.0))

        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ), patch(
            "param_center.api.get_sltp_params",
            return_value=fake_params,
        ) as mock_get:
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        # 验证调用了 param_center
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertEqual(call_args[0][0], "BTC-USDT")

        # peak=104, atr=104*0.02=2.08, atr_mult=5.0(中位数), trail=104 - 2.08*5.0=104-10.4=93.6
        # min_trail=104*0.03=3.12 < 10.4，取 10.4
        r = snap.by_state["v15_martin:BTC-USDT:long"]
        self.assertEqual(r.action, TrailingAction.ARM)
        self.assertEqual(r.status, TrailingStatus.ARMED)
        # trailing_stop_price 应为 93.6（用 5.0 而非 2.5）
        # 若用 2.5: trail=104 - 2.08*2.5=104-5.2=98.8
        self.assertAlmostEqual(r.trailing_stop_price, 93.6, places=1)
        # details 记录参数来源
        self.assertEqual(r.details.get("atr_multiplier"), 5.0)
        self.assertEqual(r.details.get("param_source"), "param_center")

    # ----------------------------------------------------------------
    # T2（RED）: param_center 异常 → FAIL-OPEN 回退配置默认 2.5
    # ----------------------------------------------------------------
    def test_t2_fail_open_fallback_to_config(self):
        from trailing_stop.component import TrailingStopComponent
        from trailing_stop.types import TrailingAction

        positions = _mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })

        def _raise(*args, **kwargs):
            raise RuntimeError("param_center unavailable")

        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ), patch(
            "param_center.api.get_sltp_params",
            side_effect=_raise,
        ):
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        # FAIL-OPEN：用配置默认 atr_multiplier=2.5
        # trail = 104 - 2.08*2.5 = 98.8
        r = snap.by_state["v15_martin:BTC-USDT:long"]
        self.assertEqual(r.action, TrailingAction.ARM)
        self.assertAlmostEqual(r.trailing_stop_price, 98.8, places=1)
        self.assertEqual(r.details.get("atr_multiplier"), 2.5)
        self.assertEqual(r.details.get("param_source"), "config_fallback")

    # ----------------------------------------------------------------
    # T3（RED）: 不同 symbol 路由到不同 atr_mult_range
    # ----------------------------------------------------------------
    def test_t3_per_symbol_routing(self):
        from trailing_stop.component import TrailingStopComponent

        positions = _mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
                {
                    "system": "v15_martin",
                    "symbol": "PEPE-USDT",
                    "direction": "LONG",
                    "size": 1000.0,
                    "entry_price": 0.01,
                    "leverage": 5.0,
                    "upl_ratio": 0.05,
                    "meta": {"current_price": 0.0105, "atr_pct": 0.02},
                },
            ],
        })

        # BTC → (4.0, 6.0) 中位 5.0；PEPE → (6.0, 10.0) 中位 8.0
        def _fake_get(symbol, *args, **kwargs):
            if symbol.startswith("BTC"):
                return _FakeSLTPParams(atr_mult_range=(4.0, 6.0))
            if symbol.startswith("PEPE"):
                return _FakeSLTPParams(atr_mult_range=(6.0, 10.0))
            return _FakeSLTPParams()

        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ), patch(
            "param_center.api.get_sltp_params",
            side_effect=_fake_get,
        ):
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        btc = snap.by_state["v15_martin:BTC-USDT:long"]
        # BTC trail = 104 - 2.08*5.0 = 93.6
        self.assertAlmostEqual(btc.trailing_stop_price, 93.6, places=1)
        self.assertEqual(btc.details.get("atr_multiplier"), 5.0)

        pepe = snap.by_state["v15_martin:PEPE-USDT:long"]
        # PEPE entry=0.01, current=0.0105, atr=0.0105*0.02=0.00021
        # atr_mult=8.0 → atr_distance=0.00021*8=0.00168
        # min_trail=0.0105*0.03=0.000315 → 取 0.00168
        # trail = 0.0105 - 0.00168 = 0.00882
        self.assertAlmostEqual(pepe.trailing_stop_price, 0.00882, places=5)
        self.assertEqual(pepe.details.get("atr_multiplier"), 8.0)

    # ----------------------------------------------------------------
    # T4（RED）: snapshot.extra 记录 param_center 接入状态
    # ----------------------------------------------------------------
    def test_t4_snapshot_records_param_source(self):
        from trailing_stop.component import TrailingStopComponent

        positions = _mock_fetch({
            "v15_martin": [
                {
                    "system": "v15_martin",
                    "symbol": "BTC-USDT",
                    "direction": "LONG",
                    "size": 0.1,
                    "entry_price": 100.0,
                    "leverage": 5.0,
                    "upl_ratio": 0.04,
                    "meta": {"current_price": 104.0, "atr_pct": 0.02},
                },
            ],
        })

        with patch(
            "trailing_stop.component.TrailingStopComponent._lazy_fetch_positions",
            return_value=positions,
        ), patch(
            "param_center.api.get_sltp_params",
            return_value=_FakeSLTPParams(atr_mult_range=(4.0, 6.0)),
        ):
            comp = TrailingStopComponent(config_path=self._cfg_file)
            snap = comp.evaluate()

        self.assertEqual(snap.extra.get("param_center_status"), "ok")
        self.assertIn("param_center_symbols", snap.extra)
        self.assertIn("BTC-USDT", snap.extra["param_center_symbols"])


if __name__ == "__main__":
    unittest.main()

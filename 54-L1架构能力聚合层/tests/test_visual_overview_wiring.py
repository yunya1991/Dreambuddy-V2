# -*- coding: utf-8 -*-
"""visual_overview 单资产统计取数轴回归。

D-E10 / D-E15 / D-G22 只依赖单个标的自身历史，不得被多资产公共交集截断，
否则 D-G22（min_n=250）在默认资产池下永远 empty。
"""

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

_REPO = os.path.normpath(os.path.join(_MODULE_ROOT, ".."))


def _load_visual_overview():
    script = os.path.join(_REPO, "3.1-FRONTEND", "scripts", "visual_overview.py")
    spec = importlib.util.spec_from_file_location("_vo_wiring_tests", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _days(count):
    return [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(count)]


def test_single_asset_capabilities_use_own_history(monkeypatch):
    vo = _load_visual_overview()
    base_dates = _days(400)
    other_dates = _days(180)
    raw = {
        "BTC": {day: 100.0 + i for i, day in enumerate(base_dates)},
        "ETH": {day: 50.0 + i for i, day in enumerate(other_dates)},
    }
    aligned_dates = sorted(set(base_dates) & set(other_dates))
    aligned = {name: [values[day] for day in aligned_dates] for name, values in raw.items()}

    seen = {}

    def fake_run(capability, **kwargs):
        seen[capability] = kwargs
        return {"ok": True, "data": {"capabilities": {capability: {"gate": "ok"}}}}

    def fake_build(blocks, envelopes, base, as_of, series_inputs=None):
        seen["blocks"] = blocks
        seen["series_inputs"] = series_inputs
        return []

    monkeypatch.setattr(vo, "_parse_args", lambda argv: (["BTC", "ETH"], "BTC", 1200))
    monkeypatch.setattr(
        vo,
        "_load_series",
        lambda symbols, days: (aligned, aligned_dates, base_dates[-1], [], raw),
    )
    monkeypatch.setattr(vo, "_run", fake_run)
    monkeypatch.setattr(vo, "_build_visuals", fake_build)
    monkeypatch.setattr(
        vo,
        "_run_crowding",
        lambda base: {"ok": True, "data": {"capabilities": {"D-A14": {"gate": "partial"}}}},
    )
    monkeypatch.setattr(
        vo,
        "_load_l0_flow_series",
        lambda base, days: [
            {"asset": base, "series_id": "exchanges_whales::whale_netflow_to_ex_usd", "value": 1.5}
        ],
    )
    monkeypatch.setattr(vo, "_extra_panels", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr(vo, "_recommend", lambda *args, **kwargs: [])

    from l1agg.persistence import artifacts

    monkeypatch.setattr(artifacts, "persist_visuals", lambda *args, **kwargs: {"enabled": False})

    buf = io.StringIO()
    with redirect_stdout(buf):
        vo.main()

    assert json.loads(buf.getvalue())["ok"] is True
    assert len(seen["D-E10"]["prices"]) == len(base_dates)
    assert seen["D-E10"]["dates"] == base_dates
    assert len(seen["D-E15"]["prices"]) == len(base_dates)
    assert seen["D-E15"]["dates"] == base_dates
    # D-G22 的返回序列比价格少 1 个收益点；必须 >= min_n(250)
    assert len(seen["D-G22"]["series"]) == len(base_dates) - 1
    assert seen["series_inputs"] == [
        {
            "asset": "BTC",
            "series_id": "exchanges_whales::whale_netflow_to_ex_usd",
            "value": 1.5,
        }
    ]
    assert "D-A14" in seen["blocks"]

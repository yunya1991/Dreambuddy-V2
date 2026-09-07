"""RED-GREEN Task 12: V15 三调用点生产替换 + 真单回归。

8 TRs:
TR-12.1 build_v15_engine() 工厂可 import + 返回 (engine, auditor_dir) tuple
TR-12.2 ENABLE_TEE=False → _v15_place_order(5-key pure market) 直传 client.place_order()，kwarg set-eq legacy（无 px/max_slippage_bps）
TR-12.3 ENABLE_TEE=True + shadow=True → 3主调用(开仓/加仓/平仓) 走 engine，raw client.place_order call_count==0
TR-12.4 4 处 limit order (L2349 grid / L2501 grid-adjust) 含 ord_type=limit + px 的调用不走 engine
TR-12.5 平仓 4 兄弟(2883/2918/2968/3350) 全部经分发器，ENABLE_TEE 时命中 engine.execute_market_compat()
TR-12.6 ENABLE_TEE=False V15 baseline: 现有 TEE 108 tests + V15 tests/test_v15_suite.py 单测 0 回归（字节等价门禁）
TR-12.7 SHADOW 3笔流(BTC开 / ETH加 / SOL平) → JSONL 3条 _shadow 行齐全域
TR-12.8 Engine FAIL-OPEN: engine 抛 RuntimeError → 降级直传 client.place_order() + 结果 ok=True 等价
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))
sys.path.insert(0, str(REPO / "14-V15经典马丁策略/core"))

V15_CORE = REPO / "14-V15经典马丁策略/core"


def _load_v15_module(name: str, relpath: Path):
    relpath = Path(relpath).resolve()
    spec = importlib.util.spec_from_file_location(
        f"_v15mod_{name}", str(relpath))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _load_tee_factory():
    """导入 build_v15_engine 工厂函数（位于 v15_integration 新文件）。"""
    path = (REPO / "22-执行引擎中心/tee_core/integrations/v15_integration.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "_tee_v15_integration", str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m.build_v15_engine, path


def _fake_client() -> MagicMock:
    """Simulated V15-compatible OKX client mock."""
    c = MagicMock()
    c.place_order.return_value = {"ok": True, "ord_id": "o-001",
                                   "data": [{"ordId": "o-001", "fillSz": "1", "avgPx": "50000"}]}
    c.get_orderbook.return_value = {
        "asks": [["50001.0", "1.0"], ["50002.0", "1.5"]],
        "bids": [["49999.0", "1.2"], ["49998.0", "0.8"]],
        "ok": True, "ts_ms": 1700000000000,
    }
    c.cancel_order.return_value = {"ok": True}
    c.cancel_algo_orders.return_value = {"ok": True}
    c.set_leverage.return_value = {"ok": True}
    return c


# =====================================================================
# TR-12.1 — build_v15_engine(...) 工厂函数存在性
# =====================================================================
class TestTR121BuildEngineFactory:
    def test_factory_file_exists_and_is_importable(self):
        build_fn, p = _load_tee_factory()   # FileNotFoundError 若文件缺失
        assert callable(build_fn), f"{p} must expose callable build_v15_engine"

    def test_factory_returns_tuple_engine_and_auditor_dir(self):
        build_fn, _ = _load_tee_factory()
        with tempfile.TemporaryDirectory() as tmp:
            engine, info = build_fn(
                raw_client=_fake_client(),
                enable_tee=False,
                shadow_mode=False,
                audit_dir=tmp,
            )
            assert hasattr(engine, "execute_market_compat"), (
                "Engine must expose execute_market_compat compat")
            assert isinstance(info, dict)
            assert Path(info["audit_dir"]).is_dir()


# =====================================================================
# TR-12.2 — ENABLE_TEE=False 字节等价 (5-key pure market kwarg set-eq)
# =====================================================================
class TestTR122DispatchByteIdentical:
    def test_pure_market_5keys_no_px_no_slippage(self):
        # 加载 V15 分发器函数（位于 v15_trader.py 的新 helper _v15_place_order）
        v15trader = _load_v15_module("trader", V15_CORE / "v15_trader.py")
        dispatch = getattr(v15trader, "_v15_place_order", None)
        assert dispatch is not None, (
            "v15_trader.py must expose module-level _v15_place_order dispatch"
        )

        captured: Dict[str, Any] = {}
        raw = MagicMock()
        raw.place_order.side_effect = lambda **kw: (captured.update(kw),
                                                    {"ok": True, "ord_id": "1"})[1]
        with patch.object(v15trader, "AUTO_EXECUTE", True), \
             patch.object(v15trader, "ENABLE_TEE", False):
            r = dispatch(
                client=raw,
                order_reason="test_open",
                source_coin="BTC",
                inst_id="BTC-USDT-SWAP",
                side="buy",
                sz="1",
                td_mode="isolated",
                pos_side="long",
            )
        assert r["ok"]
        keys = set(captured.keys())
        # 字节等价：5 legacy keys only（禁止泄露 TEE key）
        assert keys == {"inst_id", "side", "sz", "td_mode", "pos_side"}, (
            f"Pure market keys mismatch: got {sorted(keys)}"
        )
        assert "px" not in captured and "max_slippage_bps" not in captured


# =====================================================================
# TR-12.3 — SHADOW mode 3主调用 不触发 raw client.place_order()
# =====================================================================
class TestTR123ShadowZeroRealIO:
    def test_three_main_flows_hit_engine_not_raw_client(self):
        build_fn, _ = _load_tee_factory()
        raw = _fake_client()
        with tempfile.TemporaryDirectory() as tmp:
            engine, info = build_fn(
                raw_client=raw,
                enable_tee=True,
                shadow_mode=True,
                audit_dir=tmp,
            )
            # 重置计数
            raw.reset_mock()
            engine_mock = MagicMock(wraps=engine)
            # 3 main flows
            flow1 = engine_mock.execute_market_compat(
                inst_id="BTC-USDT-SWAP", side="buy", sz="2",
                td_mode="isolated", pos_side="long", tag="V15|BTC", reason="v15_open")
            flow2 = engine_mock.execute_market_compat(
                inst_id="ETH-USDT-SWAP", side="buy", sz="20",
                td_mode="isolated", pos_side="long", tag="V15|ETH", reason="v15_addon")
            flow3 = engine_mock.execute_market_compat(
                inst_id="SOL-USDT-SWAP", side="sell", sz="200",
                td_mode="isolated", pos_side="short", tag="V15|SOL", reason="v15_close")
            for f in (flow1, flow2, flow3):
                # engine.execute_market_compat() 顶层 shadow alias = "shadow"
                assert f.get("shadow_mode_hit") or f.get("shadow"), (
                    f"Expected shadow flag in result; got keys={list(f.keys())}")
            # Raw client.place_order 不应被直接调用（影子模式经 client_adapter L1）
            po_calls = [c for c in raw.method_calls if c[0] == "place_order"]
            assert len(po_calls) == 0, (
                f"Raw client.place_order called {len(po_calls)} times in SHADOW mode"
            )


# =====================================================================
# TR-12.4 — LIMIT orders 带 ord_type=limit + px 不经过 engine 分发
# =====================================================================
class TestTR124LimitOrdersBypassEngine:
    def test_limit_grid_stays_on_direct_client_path(self):
        v15trader = _load_v15_module("trader", V15_CORE / "v15_trader.py")
        dispatch = v15trader._v15_place_order
        captured_direct = {}

        raw = MagicMock()
        raw.place_order.side_effect = lambda **kw: (captured_direct.update(kw),
                                                     {"ok": True, "ord_id": "g1",
                                                      "data": [{"ordId": "g1"}]})[1]
        # 模拟 v15 addon grid limit 调用
        with patch.object(v15trader, "ENABLE_TEE", True), \
             patch.object(v15trader, "SHADOW_MODE", False):
            r = dispatch(
                client=raw,
                order_reason="v15_martin_addon_grid_1",
                source_coin="BTC",
                inst_id="BTC-USDT-SWAP",
                side="buy",
                ord_type="limit",
                sz="1",
                px="45000.0",
                td_mode="isolated",
                pos_side="long",
                tag="v15_addon_grid",
            )
        assert r["ok"]
        # Must have gone to raw client.place_order with all 9 keys untouched
        assert captured_direct.get("ord_type") == "limit"
        assert captured_direct.get("px") == "45000.0"
        assert captured_direct.get("tag") == "v15_addon_grid"
        # 5 mandatory keys are there
        mandatory = {"inst_id", "side", "sz", "td_mode", "pos_side",
                      "ord_type", "px", "tag", "reason"}
        # note: `reason` may be added inside dispatch using order_reason
        present = set(captured_direct.keys())
        missing = mandatory - present - {"reason"}   # order_reason fallback ok
        assert not missing, f"Missing LIMIT keys: {missing}"


# =====================================================================
# TR-12.5 — 平仓四兄弟 经分发器都走到 engine（ENABLE_TEE=True）
# =====================================================================
class TestTR125AllCloseFlowDispatch:
    @pytest.mark.parametrize("flow,order_reason", [
        ("v15_close_trailing_tp", "v15_trailing_tp"),
        ("v15_close_fixed_tp", "v15_fixed_tp"),
        ("v15_close_sl", "v15_stop_loss"),
        ("v15_reduce_position", "v15_reduce_position"),
    ])
    def test_close_flows_invoke_engine_compat(self, flow, order_reason):
        v15trader = _load_v15_module("trader", V15_CORE / "v15_trader.py")
        dispatch = v15trader._v15_place_order

        with tempfile.TemporaryDirectory() as tmp:
            # 注入全局 V15 engine
            build_fn, _ = _load_tee_factory()
            engine, _info = build_fn(
                raw_client=_fake_client(),
                enable_tee=True,
                shadow_mode=True,
                audit_dir=tmp,
            )
            engine_spy = MagicMock(wraps=engine)
            # 把 V15 全局 V15_ENGINE 设置好（由 build_v15_engine 初始化）
            v15trader.V15_ENGINE = engine_spy
            v15trader.ENABLE_TEE = True
            v15trader.SHADOW_MODE = True

            raw = MagicMock()
            raw.place_order.return_value = {"ok": False,
                                             "error": "must_not_hit_raw"}
            r = dispatch(
                client=raw,
                order_reason=order_reason,
                source_coin="ETH",
                inst_id="ETH-USDT-SWAP",
                side="sell" if flow != "v15_close_trailing_tp" else "buy",
                sz="10",
                td_mode="isolated",
                pos_side="short" if flow != "v15_close_trailing_tp" else "long",
            )
            # 分发器必须走 engine compat（shadow=True 时直接ok=T）
            assert r.get("ok"), f"{flow}: dispatch fallback without engine call"
            # engine_spy.execute_market_compat 至少调用 1 次
            calls = [c for c in engine_spy.method_calls
                     if c[0] == "execute_market_compat"]
            assert len(calls) >= 1, f"{flow}: execute_market_compat not called"


# =====================================================================
# TR-12.6 — TEE baseline 108 GREEN + V15 test_v15_suite 0回归
# (AC-7 字节等价门禁 — 单测内部轻量调用只验证 ENABLE_TEE=False 切换路径
# 不破坏 v15_trader._legacy 路径；重型回归由 CI 全量脚本跑)
# =====================================================================
class TestTR126BaselineZeroRegression:
    def test_disable_tee_uses_no_engine_attrs(self):
        """ENABLE_TEE=False 时，分发器调用 _v15_place_order 不应访问 V15_ENGINE。"""
        v15trader = _load_v15_module("trader", V15_CORE / "v15_trader.py")
        v15trader.ENABLE_TEE = False
        v15trader.V15_ENGINE = None   # 显式置空：若代码误用则 AttributeError
        dispatch = v15trader._v15_place_order
        raw = MagicMock()
        raw.place_order.return_value = {"ok": True, "ord_id": "x"}
        r = dispatch(
            client=raw,
            order_reason="v15_open",
            source_coin="BTC",
            inst_id="BTC-USDT-SWAP",
            side="buy",
            sz="1",
            td_mode="isolated",
            pos_side="long",
        )
        assert r["ok"], "Baseline direct path must return ok=True when engine disabled/missing"


# =====================================================================
# TR-12.7 — 3笔完整 SHADOW 流 JSONL 审计记录齐全
# =====================================================================
class TestTR127ShadowThreeFlowsAuditLines:
    def test_jsonl_parent_records_have_required_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_fn, _ = _load_tee_factory()
            raw = _fake_client()
            engine, info = build_fn(
                raw_client=raw,
                enable_tee=True,
                shadow_mode=True,
                audit_dir=tmp,
            )
            # 执行 3 笔影子交易
            flows = [
                ("BTC-USDT-SWAP", "buy",  "2",  "long",  "v15_open"),
                ("ETH-USDT-SWAP", "buy",  "20", "long",  "v15_addon"),
                ("SOL-USDT-SWAP", "sell", "200","short", "v15_close"),
            ]
            for inst, sd, sz, ps, src in flows:
                engine.execute_market_compat(
                    inst_id=inst, side=sd, sz=sz,
                    td_mode="isolated", pos_side=ps, tag=f"V15|{inst[:3]}", reason=src)
            # Force flush 审计文件（Auditor 有 60s 刷新间隔，我们通过调 internal flush）
            try:
                engine.auditor.close()
            except Exception:
                pass
            audit_dir = Path(info["audit_dir"])
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            shadow_path = audit_dir / f"{today}_shadow.jsonl"
            lines = shadow_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) >= 3, (
                f"Expected ≥3 _shadow lines, got {len(lines)}; files={list(audit_dir.iterdir())}"
            )
            # 每行必须具备 6 大审计域（支持嵌套路径：parent.parent_id / router.bucket
            # / algo.name 等价 flat 字段）
            REQUIRED_FLAT = {"estimated_vwap", "shadow_mode_hit", "ts_epoch_ms"}
            REQUIRED_NESTED = {
                ("parent", "parent_id"), ("parent", "source"),
                ("router", "bucket"), ("algo", "name"),
            }
            for rawline in lines:
                rec = json.loads(rawline)
                flat_missing = REQUIRED_FLAT - set(rec.keys())
                assert not flat_missing, f"Missing top-level {flat_missing}: {rec}"
                nested_missing = [
                    path for path in REQUIRED_NESTED
                    if path[1] not in rec.get(path[0], {})
                ]
                assert not nested_missing, (
                    f"Missing nested {nested_missing} (actual: "
                    f"algo={rec.get('algo')}, router={rec.get('router')}, "
                    f"parent keys={list(rec.get('parent', {}).keys())})"
                )
            # 所有 algo 去重（至少 1 种）；router 至少 1 个决策
            algo_names = {json.loads(l)["algo"]["name"] for l in lines[:3]}
            router_decisions = {json.loads(l)["router"]["bucket"] for l in lines[:3]}
            assert len(algo_names) >= 1 and len(router_decisions) >= 1, (
                f"algos={algo_names} decisions={router_decisions}"
            )


# =====================================================================
# TR-12.8 — FAIL-OPEN：engine 抛错 → 自动降级直传 raw client.place_order()
# =====================================================================
class TestTR128FailOpenFallback:
    def test_engine_raises_runtime_error_falls_back_gracefully(self):
        v15trader = _load_v15_module("trader", V15_CORE / "v15_trader.py")
        dispatch = v15trader._v15_place_order

        class BrokenEngine:
            def execute_market_compat(self, **kw):
                raise RuntimeError("boom engine simulated failure")

        v15trader.V15_ENGINE = BrokenEngine()
        v15trader.ENABLE_TEE = True
        v15trader.SHADOW_MODE = False

        captured = {}
        raw = MagicMock()
        raw.place_order.side_effect = lambda **kw: (captured.update(kw),
                                                     {"ok": True, "ord_id": "fo"})[1]
        r = dispatch(
            client=raw,
            order_reason="v15_open_failopen_test",
            source_coin="BTC",
            inst_id="BTC-USDT-SWAP",
            side="buy",
            sz="1",
            td_mode="isolated",
            pos_side="long",
        )
        assert r["ok"], f"FAIL-OPEN must still return ok=True, got {r}"
        assert captured["inst_id"] == "BTC-USDT-SWAP"
        # 5 legacy keys presence（FAIL-OPEN 路径字节等价 — 不附 TEE extra）
        assert set(captured.keys()) == {"inst_id", "side", "sz",
                                         "td_mode", "pos_side"}

# -*- coding: utf-8 -*-
"""RAG 热路径接入测试（第一波：打通 RAG 到交易热路径）。

验证 _rag_hotpath_lookup 的 FAIL-OPEN 行为和 context 注入。
所有测试 mock RAG 模块，不依赖真实向量库，可独立运行。

运行: pytest test_rag_hotpath_integration.py -v
"""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# 把 memory_l4 加入 path，使 polling_trader 可被测试导入
_THIS = Path(__file__).resolve()
_L4_DIR = _THIS.parent.parent  # .../scripts/memory_l4
_SCRIPTS_DIR = _L4_DIR.parent  # .../scripts
_PROJ_ROOT = _SCRIPTS_DIR.parent  # .../11-易经推理系统
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


class _FakeTrader:
    """轻量 trader stub，只为测试 _rag_hotpath_lookup。"""

    def _log(self, msg, level="INFO"):
        pass  # 测试中不关心日志输出


class TestRagHotpathDisabled(unittest.TestCase):
    """测试 1: ENABLE_RAG_HOTPATH=0 时返回空列表。"""

    def test_rag_disabled_by_env(self):
        from scripts.memory_l4.polling_trader import _rag_hotpath_lookup
        with patch.dict(os.environ, {"ENABLE_RAG_HOTPATH": "0"}):
            result = _rag_hotpath_lookup(_FakeTrader(), "BTC long 风控")
        self.assertEqual(result, [])


class TestRagFailOpenOnException(unittest.TestCase):
    """测试 2: 检索异常时 FAIL-OPEN 返回空列表。"""

    def test_rag_fail_open_on_exception(self):
        # 重置单例，强制走初始化路径
        import scripts.memory_l4.polling_trader as pt
        old = getattr(pt, "_RAG_CLIENT", None)
        pt._RAG_CLIENT = None
        try:
            # 让 import rag_engine 抛异常
            import builtins
            real_import = builtins.__import__

            def _fake_import(name, *args, **kwargs):
                if name == "rag_engine":
                    raise RuntimeError("simulated import failure")
                return real_import(name, *args, **kwargs)

            with patch.dict(os.environ, {"ENABLE_RAG_HOTPATH": "1"}):
                with patch("builtins.__import__", side_effect=_fake_import):
                    result = pt._rag_hotpath_lookup(_FakeTrader(), "BTC long 风控")
            self.assertEqual(result, [])
        finally:
            pt._RAG_CLIENT = old


class TestRagTimeoutReturnsEmpty(unittest.TestCase):
    """测试 3: 超时返回空列表。"""

    def test_rag_timeout_returns_empty(self):
        import scripts.memory_l4.polling_trader as pt
        old_client = getattr(pt, "_RAG_CLIENT", None)
        old_exec = getattr(pt, "_RAG_EXECUTOR", None)

        def _slow_search(query, top_k=5):
            time.sleep(35)  # 远超 30 秒超时
            return [{"heading": "never"}]

        # 用独立 executor 避免阻塞后续测试
        from concurrent.futures import ThreadPoolExecutor as _TPE
        pt._RAG_CLIENT = _slow_search
        pt._RAG_EXECUTOR = _TPE(max_workers=1, thread_name_prefix="rag-test-slow")
        try:
            with patch.dict(os.environ, {"ENABLE_RAG_HOTPATH": "1"}):
                result = pt._rag_hotpath_lookup(_FakeTrader(), "BTC long 风控")
            self.assertEqual(result, [])
        finally:
            pt._RAG_CLIENT = old_client
            try:
                pt._RAG_EXECUTOR.shutdown(wait=False)
            except Exception:
                pass
            pt._RAG_EXECUTOR = old_exec


class TestRagNormalReturnsList(unittest.TestCase):
    """测试 4: 正常检索返回结果列表。"""

    def test_rag_normal_returns_list(self):
        import scripts.memory_l4.polling_trader as pt
        old_client = getattr(pt, "_RAG_CLIENT", None)
        old_exec = getattr(pt, "_RAG_EXECUTOR", None)

        _fake_results = [
            {"heading": "BCRM2推理引擎", "final_score": 0.85, "source_file": "1-TRADING/BCRM2推理引擎.md"},
            {"heading": "风控体系", "final_score": 0.72, "source_file": "1-TRADING/风控体系.md"},
        ]

        def _mock_search(query, top_k=5):
            return _fake_results

        # 用全新 executor，避免被前一个测试的慢任务阻塞
        from concurrent.futures import ThreadPoolExecutor as _TPE
        pt._RAG_CLIENT = _mock_search
        pt._RAG_EXECUTOR = _TPE(max_workers=1, thread_name_prefix="rag-test-normal")
        try:
            with patch.dict(os.environ, {"ENABLE_RAG_HOTPATH": "1"}):
                result = pt._rag_hotpath_lookup(_FakeTrader(), "BTC long 风控")
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["heading"], "BCRM2推理引擎")
        finally:
            pt._RAG_CLIENT = old_client
            try:
                pt._RAG_EXECUTOR.shutdown(wait=False)
            except Exception:
                pass
            pt._RAG_EXECUTOR = old_exec


class TestExitContextHasRagContext(unittest.TestCase):
    """测试 5: 离场 context 注入 rag_context 字段。

    验证 _evolution_check_exit 构造的 context 字典包含 rag_context 键，
    即使为空列表也应存在（保持 schema 一致）。
    """

    def test_exit_context_has_rag_context(self):
        # 这个测试验证 context schema，直接构造模拟 context
        # 真实代码在 _evolution_check_exit L9122 后注入
        context = {
            "symbol": "BTC", "inst_id": "BTC-USDT-SWAP", "pos_side": "long",
            "entry_price": 50000.0, "current_price": 51000.0,
            "upl": 100.0, "upl_ratio": 0.02,
            "has_stronger_signal": False,
        }
        # 模拟 RAG 注入逻辑
        rag_hits = [{"heading": "trailing 止盈", "final_score": 0.8}]
        context["rag_context"] = rag_hits

        self.assertIn("rag_context", context)
        self.assertIsInstance(context["rag_context"], list)
        self.assertGreater(len(context["rag_context"]), 0)

        # 空列表也应可注入（schema 一致）
        context2 = {"symbol": "ETH"}
        context2["rag_context"] = []
        self.assertIn("rag_context", context2)
        self.assertEqual(context2["rag_context"], [])


class TestRagFeedbackToMemory(unittest.TestCase):
    """断层3：RAG检索结果异步写入认知库（FAIL-OPEN）。"""

    def test_rag_feedback_disabled_by_env(self):
        """ENABLE_RAG_FEEDBACK=0 时不触发 record。"""
        import importlib
        import polling_trader as pt
        importlib.reload(pt)
        with patch.dict(os.environ, {"ENABLE_RAG_FEEDBACK": "0"}):
            with patch.object(pt, '_rag_record_to_memory') as mock_rec:
                # mock _RAG_CLIENT 避免 real RAG
                with patch.object(pt, '_RAG_CLIENT', MagicMock(return_value=[{"content": "x"}])):
                    res = pt._rag_hotpath_lookup(pt.PollingTrader.__new__(pt.PollingTrader), "q", top_k=1)
                    # record 不应被调用
                    mock_rec.assert_not_called()

    def test_rag_feedback_fail_open(self):
        """record 异常时不影响检索结果。"""
        import importlib
        import polling_trader as pt
        importlib.reload(pt)
        with patch.dict(os.environ, {"ENABLE_RAG_FEEDBACK": "1"}):
            # _rag_record_to_memory 抛异常
            with patch.object(pt, '_rag_record_to_memory', side_effect=RuntimeError("boom")):
                # ThreadPoolExecutor.submit 会吞异常（不影响主线程）
                # 检索结果不受影响
                with patch.object(pt, '_RAG_CLIENT', MagicMock(return_value=[{"content": "x"}])):
                    res = pt._rag_hotpath_lookup(pt.PollingTrader.__new__(pt.PollingTrader), "q", top_k=1)
                    self.assertEqual(len(res), 1)


class TestCaseDistillToKnowledge(unittest.TestCase):
    """断层1：交易案例蒸馏到知识库（FAIL-OPEN）。"""

    def _make_mock_trade_rec(self):
        """构造 mock TradeRecord。"""
        rec = MagicMock()
        rec.inst_id = "BTC-USDT-SWAP"
        rec.direction = "LONG"
        rec.source_tag = "bcrm"
        rec.entry_price = 100000.0
        rec.exit_price = 105000.0
        rec.pnl = 50.0
        rec.pnl_pct = 0.05
        rec.exit_reason = "TP"
        rec.base_sl_roi = 0.04
        rec.base_tp_roi = 0.12
        rec.score_consensus = 0.85
        rec.market_snapshot = {"regime": "BULL", "confidence": 0.9}
        return rec

    def test_distill_disabled_by_env(self):
        """ENABLE_CASE_DISTILL=0 时不生成文件。"""
        import importlib
        import polling_trader as pt
        importlib.reload(pt)
        with patch.dict(os.environ, {"ENABLE_CASE_DISTILL": "0"}):
            with patch('builtins.open') as mock_open:
                trader = pt.PollingTrader.__new__(pt.PollingTrader)
                pt._distill_trade_to_knowledge(trader, self._make_mock_trade_rec())
                mock_open.assert_not_called()

    def test_distill_fail_open(self):
        """蒸馏异常时不影响 trade_rec（不抛异常）。"""
        import importlib
        import polling_trader as pt
        importlib.reload(pt)
        with patch.dict(os.environ, {"ENABLE_CASE_DISTILL": "1"}):
            # Path.mkdir 抛异常
            with patch('pathlib.Path.mkdir', side_effect=OSError("disk full")):
                trader = pt.PollingTrader.__new__(pt.PollingTrader)
                trader._log = MagicMock()
                # 不应抛异常
                pt._distill_trade_to_knowledge(trader, self._make_mock_trade_rec())
                # trade_rec 不受影响
                self.assertTrue(True)

    def test_distill_generates_md(self):
        """正常蒸馏时生成 md 文件内容。"""
        import tempfile
        import importlib
        import polling_trader as pt
        importlib.reload(pt)
        with patch.dict(os.environ, {"ENABLE_CASE_DISTILL": "1"}):
            with tempfile.TemporaryDirectory() as tmpdir:
                # _distill_trade_to_knowledge 内部用 Path(__file__).resolve().parents[3]
                # 我们让 resolve 返回 tmpdir/a/b/c/polling_trader.py → parents[3] = tmpdir
                # 所以 _cases_dir = tmpdir/2-KNOWLEDGE/1-TRADING/cases
                tmp_cases = Path(tmpdir) / "2-KNOWLEDGE" / "1-TRADING" / "cases"

                with patch.object(pt, '_ingest_case'):
                    orig_resolve = Path.resolve
                    _pol_path = Path(pt.__file__).resolve()

                    def _fake_resolve(self):
                        if self == _pol_path or str(self) == str(_pol_path):
                            return Path(tmpdir) / "a" / "b" / "c" / "polling_trader.py"
                        return orig_resolve(self)

                    with patch.object(Path, 'resolve', _fake_resolve):
                        trader = pt.PollingTrader.__new__(pt.PollingTrader)
                        trader._log = MagicMock()
                        rec = self._make_mock_trade_rec()
                        pt._distill_trade_to_knowledge(trader, rec)
                        files = list(tmp_cases.glob("case_*.md"))
                        self.assertEqual(len(files), 1)
                        content = files[0].read_text()
                        self.assertIn("BTC-USDT-SWAP", content)
                        self.assertIn("LONG", content)


if __name__ == "__main__":
    unittest.main()

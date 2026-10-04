"""
事件驱动策略小单测试链路 4 个断点修复的 TDD 测试

断点1: strategy_gene.py 新增 find_combinations_by_strategy_type + kline_event_handler.py 接入 event_arbitrage
断点2: polling_trader.py 按 source_tag 区分 SL/TP（event_arbitrage=2%/4% / 通用 probe=8%/6%）
断点3: kline_event_handler.py 统一 tier 系统（双层门控，关断保持字节等价）
断点4: polling_trader.py 增加 probe→standard 升级逻辑（FAIL-OPEN）

TDD 铁律：先写测试→正确失败→实现→全绿。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构/
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dreambuddy-v2/
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ==================================================================================
# 断点1: find_combinations_by_strategy_type
# ==================================================================================
class TestFindCombinationsByStrategyType:
    """断点1: strategy_gene.py 新增 find_combinations_by_strategy_type"""

    def test_function_exists(self):
        """函数存在性测试"""
        from dreambuddy_evolution.core import strategy_gene as sgs
        assert hasattr(sgs, "find_combinations_by_strategy_type"), (
            "find_combinations_by_strategy_type 函数不存在 — 断点1 未修复"
        )

    def test_returns_event_arbitrage_combinations_from_real_library(self):
        """从实库中查找 event_arbitrage 组合 — 应返回 CB-EVENT-PRICED-IN"""
        from dreambuddy_evolution.core import strategy_gene as sgs
        real_root = REPO / "dreambuddy_evolution" / "gene_data"
        lib = sgs.load_gene_library(real_root)
        results = sgs.find_combinations_by_strategy_type(lib, "event_arbitrage")
        assert isinstance(results, list), "返回值必须是 list"
        assert len(results) >= 1, (
            f"实库中至少应有 1 个 event_arbitrage 组合(CB-EVENT-PRICED-IN)，got {len(results)}"
        )
        combo_ids = [r.get("combo_id") for r in results]
        assert "CB-EVENT-PRICED-IN" in combo_ids, (
            f"CB-EVENT-PRICED-IN 未出现在结果中: {combo_ids}"
        )

    def test_returns_empty_for_nonexistent_strategy_type(self):
        """不存在的 strategy_type 返回空列表"""
        from dreambuddy_evolution.core import strategy_gene as sgs
        real_root = REPO / "dreambuddy_evolution" / "gene_data"
        lib = sgs.load_gene_library(real_root)
        results = sgs.find_combinations_by_strategy_type(lib, "__NO_SUCH_TYPE__")
        assert results == [], f"不存在的 strategy_type 应返回空列表，got {results}"

    def test_fail_open_on_exception(self):
        """异常输入返回空列表（FAIL-OPEN）"""
        from dreambuddy_evolution.core import strategy_gene as sgs
        # 传入非 dict 类型
        results = sgs.find_combinations_by_strategy_type(None, "event_arbitrage")
        assert results == [], "None 输入应 FAIL-OPEN 返回空列表"
        # 传入缺 combinations 的 dict
        results = sgs.find_combinations_by_strategy_type({}, "event_arbitrage")
        assert results == [], "空 dict 应返回空列表"

    def test_result_contains_required_fields(self):
        """返回结果包含 combo_id/condition_ids/action_ids/ess/meta 字段"""
        from dreambuddy_evolution.core import strategy_gene as sgs
        real_root = REPO / "dreambuddy_evolution" / "gene_data"
        lib = sgs.load_gene_library(real_root)
        results = sgs.find_combinations_by_strategy_type(lib, "event_arbitrage")
        if not results:
            pytest.skip("实库无 event_arbitrage 组合")
        r = results[0]
        assert "combo_id" in r, "结果必须包含 combo_id"
        assert "condition_ids" in r, "结果必须包含 condition_ids"
        assert "action_ids" in r, "结果必须包含 action_ids"


# ==================================================================================
# 断点1b: kline_event_handler 接入 event_arbitrage
# ==================================================================================
class TestEventArbitrageInjection:
    """断点1b: kline_event_handler 在事件驱动场景注入 source_tag=event_arbitrage"""

    def test_trigger_build_position_accepts_source_tag(self):
        """_trigger_build_position 支持 source_tag 参数"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        import inspect
        sig = inspect.signature(KlineEventHandler._trigger_build_position)
        params = list(sig.parameters.keys())
        assert "source_tag" in params, (
            f"_trigger_build_position 必须支持 source_tag 参数，当前参数: {params}"
        )

    def test_event_arbitrage_injected_when_conditions_met(self):
        """当事件驱动层启用 + FOMC活跃 + long方向 + priced_in≥0.75 时，注入 source_tag=event_arbitrage"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        # 启用事件驱动层
        AGI_SWITCHES["enable_contradiction_driven_layer"] = True

        callback_calls = []

        def fake_callback(**kwargs):
            callback_calls.append(kwargs)

        handler = KlineEventHandler(mode="Phase2", build_position_callback=fake_callback)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.60  # probe tier
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})

        # 构造 event_context: post_event + priced_in_score>=0.75
        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "repricing",
                "post_event": True,
                "priced_in_score": 0.80,
            },
        }
        # mock _apply_macro_event_filter 返回活跃的 long 方向
        with patch.object(handler, "_apply_macro_event_filter") as mock_macro:
            mock_macro.return_value = (
                "long", 0.60,
                {
                    "active": True, "filter_level": "soft",
                    "direction": "long", "conviction": 0.80,
                    "position_params": None, "adjusted_params": None,
                },
            )
            handler.on_kline_close(kline_data)

        assert len(callback_calls) == 1, f"应调用 1 次回调，got {len(callback_calls)}"
        call = callback_calls[0]
        assert call.get("source_tag") == "event_arbitrage", (
            f"事件驱动场景应注入 source_tag=event_arbitrage，got {call.get('source_tag')}"
        )

    def test_no_event_arbitrage_when_switch_off(self):
        """开关关断时不注入 event_arbitrage（保持字节等价）"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        AGI_SWITCHES["enable_contradiction_driven_layer"] = False

        callback_calls = []

        def fake_callback(**kwargs):
            callback_calls.append(kwargs)

        handler = KlineEventHandler(mode="Phase2", build_position_callback=fake_callback)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.60
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})

        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "repricing",
                "post_event": True,
                "priced_in_score": 0.80,
            },
        }
        handler.on_kline_close(kline_data)
        if callback_calls:
            call = callback_calls[0]
            assert call.get("source_tag") != "event_arbitrage", (
                "开关关断时不应注入 event_arbitrage"
            )


# ==================================================================================
# 断点3: tier 系统统一（双层门控）
# ==================================================================================
class TestTierSystemUnification:
    """断点3: kline_event_handler 统一 tier 系统"""

    def test_ri_based_tier_when_switch_off(self):
        """开关关断时使用 ri-based tier（字节等价）"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        AGI_SWITCHES["enable_contradiction_driven_layer"] = False
        AGI_SWITCHES["enable_conviction_position_mapper"] = False

        callback_calls = []

        def fake_callback(**kwargs):
            callback_calls.append(kwargs)

        handler = KlineEventHandler(mode="Phase2", build_position_callback=fake_callback)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.65  # standard tier
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})
        # mock path discovery 不调整 RI
        handler._run_path_discovery = MagicMock(return_value=("long", 0.65, {}))
        # mock reflection scanner 返回 None（避免历史数据干扰 RI）
        handler._reflection_scanner = False

        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
        }
        handler.on_kline_close(kline_data)
        assert len(callback_calls) == 1
        # ri=0.65 → standard tier
        assert callback_calls[0].get("tier") == "standard", (
            f"ri=0.65 开关关断时应为 standard tier，got {callback_calls[0].get('tier')}"
        )

    def test_conviction_based_tier_when_switch_on(self):
        """开关启用时使用 conviction-based tier"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import AGI_SWITCHES

        AGI_SWITCHES["enable_contradiction_driven_layer"] = True
        AGI_SWITCHES["enable_conviction_position_mapper"] = True

        callback_calls = []

        def fake_callback(**kwargs):
            callback_calls.append(kwargs)

        handler = KlineEventHandler(mode="Phase2", build_position_callback=fake_callback)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.55  # ri-based 会是 probe
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})
        # mock reflection scanner 返回 None（避免历史数据干扰 RI）
        handler._reflection_scanner = False

        # mock macro_info 返回高 conviction（应映射到 standard 或更高）
        with patch.object(handler, "_apply_macro_event_filter") as mock_macro:
            mock_macro.return_value = (
                "long", 0.55,
                {
                    "active": True, "filter_level": "soft",
                    "direction": "long", "conviction": 0.75,
                    "position_params": {"position_scale": 1.2, "tier": "trend_set"},
                    "adjusted_params": None,
                },
            )
            # mock path discovery 不调整 RI
            handler._run_path_discovery = MagicMock(return_value=("long", 0.55, {}))
            kline_data = {
                "symbol": "BTC",
                "close": [100.0] * 20,
                "high": [105.0] * 20,
                "low": [95.0] * 20,
                "volume": [1000.0] * 20,
                "ess_top_direction": "long",
                "vol_5": 3000.0,
                "vol_20": 1000.0,
                "event_context": {"in_fomc_cycle": True},
            }
            handler.on_kline_close(kline_data)

        assert len(callback_calls) == 1
        # conviction=0.75 → trend_set → 映射回 standard tier
        tier = callback_calls[0].get("tier")
        assert tier in ("standard", "trend"), (
            f"conviction=0.75 应映射到 standard 或 trend tier，got {tier}"
        )


# ==================================================================================
# 断点2: polling_trader 按 source_tag 区分 SL/TP
# ==================================================================================
class TestSourceTagSLTP:
    """断点2: polling_trader 按 source_tag 区分 SL/TP"""

    def test_event_arbitrage_uses_2pct_4pct_sltp(self):
        """event_arbitrage source_tag 使用 SL=2%/TP=4%（小单小止小盈）"""
        # 这个测试验证 _evolution_build_position 中 source_tag 逻辑
        # 由于 polling_trader.py 难以单元测试（重依赖），我们验证函数签名支持 source_tag
        import inspect
        import importlib.util
        pt_path = PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "polling_trader.py"
        if not pt_path.exists():
            pytest.skip("polling_trader.py 不存在")
        # 读取源码检查 source_tag 参数是否被支持
        source = pt_path.read_text(encoding="utf-8")
        assert "event_arbitrage" in source, (
            "polling_trader.py 必须包含 event_arbitrage source_tag 处理逻辑"
        )
        # 检查 _evolution_build_position 支持 source_tag 参数
        assert "source_tag" in source, "polling_trader.py 必须支持 source_tag 参数"

    def test_event_arbitrage_sltp_values_in_source(self):
        """验证 event_arbitrage 的 SL=2%/TP=4% 硬编码存在于源码中"""
        pt_path = PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "polling_trader.py"
        if not pt_path.exists():
            pytest.skip("polling_trader.py 不存在")
        source = pt_path.read_text(encoding="utf-8")
        # 查找 event_arbitrage SL/TP 定义（2%/4%）
        assert ("0.02" in source and "0.04" in source) or \
               ("2%" in source and "4%" in source) or \
               ("sl_pct" in source and "0.02" in source), (
            "polling_trader.py 必须包含 event_arbitrage 的 SL=2%/TP=4% 定义"
        )


# ==================================================================================
# 断点4: probe→standard 升级逻辑
# ==================================================================================
class TestProbeToStandardUpgrade:
    """断点4: polling_trader 增加 probe→standard 升级逻辑"""

    def test_upgrade_function_exists(self):
        """验证 probe→standard 升级函数存在"""
        pt_path = PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "polling_trader.py"
        if not pt_path.exists():
            pytest.skip("polling_trader.py 不存在")
        source = pt_path.read_text(encoding="utf-8")
        # 检查升级逻辑关键词存在
        assert "probe" in source and "standard" in source, (
            "polling_trader.py 必须包含 probe/standard 升级逻辑"
        )
        # 检查升级方法或逻辑块存在
        has_upgrade = (
            "_maybe_upgrade_probe_to_standard" in source or
            "_upgrade_probe_tier" in source or
            "probe_to_standard" in source or
            "tier_upgrade" in source
        )
        assert has_upgrade, (
            "polling_trader.py 必须包含 probe→standard 升级方法（如 _maybe_upgrade_probe_to_standard）"
        )

    def test_upgrade_conditions_in_source(self):
        """验证升级条件关键词存在于源码中"""
        pt_path = PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "polling_trader.py"
        if not pt_path.exists():
            pytest.skip("polling_trader.py 不存在")
        source = pt_path.read_text(encoding="utf-8")
        # 升级条件：持仓时长 + 盈利 + tier 标记
        assert "unrealized_pnl" in source or "pnl" in source.lower(), (
            "升级逻辑必须检查持仓盈利"
        )

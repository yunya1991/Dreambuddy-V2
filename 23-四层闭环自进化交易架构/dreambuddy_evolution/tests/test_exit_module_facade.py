# -*- coding: utf-8 -*-
"""离场模块完整化 TDD 测试

覆盖三处缺口：
- 缺口A: ExitStrategyParams 参数基因扩展 4→12
- 缺口B: ExitModuleFacade 子系统独立验证接口
- 缺口D: 回测闭环扩展（exit_engine 完整规则回测）

TDD RED → GREEN 流程
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# 缺口A: ExitStrategyParams 参数基因扩展 4→12
# ============================================================================

class TestExitStrategyParamsExpansion:
    """ExitStrategyParams 从 4 参数扩展到 12 参数"""

    def test_original_4_params_still_exist(self):
        """原 4 参数仍存在（向后兼容）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams()
        assert hasattr(p, "trailing_retrace_pct")
        assert hasattr(p, "sl_tighten_factor")
        assert hasattr(p, "tp_extend_factor")
        assert hasattr(p, "force_close_threshold")

    def test_new_param_trailing_arm_pct(self):
        """新增 trailing_arm_pct：trailing 触发阈值（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(trailing_arm_pct=0.04)
        assert p.trailing_arm_pct == 0.04

    def test_new_param_break_even_arm_pct(self):
        """新增 break_even_arm_pct：保本位触发阈值（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(break_even_arm_pct=0.02)
        assert p.break_even_arm_pct == 0.02

    def test_new_param_partial_tp_r1(self):
        """新增 partial_tp_r1：第一批止盈 R 倍数（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(partial_tp_r1=1.0)
        assert p.partial_tp_r1 == 1.0

    def test_new_param_partial_tp_pct1(self):
        """新增 partial_tp_pct1：第一批止盈比例（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(partial_tp_pct1=0.5)
        assert p.partial_tp_pct1 == 0.5

    def test_new_param_tp_decay_base_pct(self):
        """新增 tp_decay_base_pct：TP 衰减初始间距（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(tp_decay_base_pct=0.06)
        assert p.tp_decay_base_pct == 0.06

    def test_new_param_tp_decay_floor_pct(self):
        """新增 tp_decay_floor_pct：TP 衰减下限间距（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(tp_decay_floor_pct=0.015)
        assert p.tp_decay_floor_pct == 0.015

    def test_new_param_tp_decay_grace_hours(self):
        """新增 tp_decay_grace_hours：TP 衰减宽限期（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(tp_decay_grace_hours=12)
        assert p.tp_decay_grace_hours == 12

    def test_new_param_soft_vote_cooldown_sec(self):
        """新增 soft_vote_cooldown_sec：软投票冷却期（可进化）"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(soft_vote_cooldown_sec=14400)
        assert p.soft_vote_cooldown_sec == 14400

    def test_to_gene_json_has_12_params(self):
        """to_gene_json 输出 12 个参数"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams()
        gene = p.to_gene_json()
        params = gene["parameters"]
        assert len(params) == 12
        # 验证新参数都有 range
        for key, val in params.items():
            assert "value" in val
            assert "range" in val
            assert "low" in val["range"]
            assert "high" in val["range"]

    def test_defaults_match_exit_engine_constants(self):
        """默认值与 exit_engine 硬编码常量一致"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams()
        # trailing_arm_pct 默认 standard=0.04
        assert p.trailing_arm_pct == 0.04
        # break_even_arm_pct 默认 0.02
        assert p.break_even_arm_pct == 0.02
        # partial_tp_r1 默认 1.0
        assert p.partial_tp_r1 == 1.0
        # tp_decay_base_pct 默认 0.06
        assert p.tp_decay_base_pct == 0.06


# ============================================================================
# 缺口B: ExitModuleFacade 子系统独立验证接口
# ============================================================================

class TestExitModuleFacade:
    """ExitModuleFacade 暴露 decide(context) 供子系统独立验证离场模块能力"""

    def test_facade_importable(self):
        """ExitModuleFacade 可被 import"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade  # noqa: F401

    def test_facade_decide_method_exists(self):
        """ExitModuleFacade.decide() 方法存在"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade
        assert hasattr(ExitModuleFacade, "decide")

    def test_facade_decide_returns_exit_decision(self):
        """decide() 返回 ExitDecision"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade
        from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision

        facade = ExitModuleFacade()
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "position_age_sec": 120,
            "upl_ratio": 0.01,
            "current_price": 10100.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
        }
        decision = facade.decide(ctx)
        assert isinstance(decision, ExitDecision)

    def test_facade_subsystem_bcrm_context(self):
        """BCRM 子系统 context 可通过 facade 调用 decide"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade

        facade = ExitModuleFacade()
        ctx = {
            "symbol": "ETH",
            "pos_side": "long",
            "tier": "standard",
            "subsystem": "bcrm",  # 标记来源
            "position_age_sec": 7200,
            "upl_ratio": 0.03,
            "current_price": 3100.0,
            "entry_price": 3000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 2850.0,
            "current_tp_px": 3300.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
        }
        decision = facade.decide(ctx)
        assert decision is not None

    def test_facade_subsystem_bdsm_context(self):
        """BDSM 子系统 context 可通过 facade 调用 decide"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade

        facade = ExitModuleFacade()
        ctx = {
            "symbol": "SOL",
            "pos_side": "short",
            "tier": "probe",
            "subsystem": "bdsm",
            "position_age_sec": 3600,
            "upl_ratio": -0.01,
            "current_price": 99.0,
            "entry_price": 100.0,
            "ess": 0.5,
            "r_vector": {},
            "current_sl_px": 104.0,
            "current_tp_px": 88.0,
            "atr_pct": 0.03,
            "r_multiple": 0.0,
        }
        decision = facade.decide(ctx)
        assert decision is not None

    def test_facade_fail_open_on_crash(self):
        """facade 异常时 FAIL-OPEN 返回 hold ExitDecision"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade
        from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision

        facade = ExitModuleFacade()
        # 传入空 context 触发异常
        decision = facade.decide({})
        assert isinstance(decision, ExitDecision)
        assert decision.action == "hold"

    def test_facade_get_params_returns_strategy_params(self):
        """get_params() 返回当前 ExitStrategyParams"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )

        facade = ExitModuleFacade()
        params = facade.get_params()
        assert isinstance(params, ExitStrategyParams)

    def test_facade_load_gene_from_json(self):
        """load_gene(json_str) 从基因 JSON 加载参数"""
        from dreambuddy_evolution.engines.exit_engine.facade import ExitModuleFacade

        facade = ExitModuleFacade()
        gene_json = '{"trailing_arm_pct": 0.05, "break_even_arm_pct": 0.03}'
        facade.load_gene(gene_json)
        params = facade.get_params()
        assert params.trailing_arm_pct == 0.05
        assert params.break_even_arm_pct == 0.03


# ============================================================================
# 缺口D: 回测闭环扩展
# ============================================================================

class TestBacktestLoopClosure:
    """回测脚本支持 exit_engine 完整规则回测（不限于软投票）"""

    def test_backtest_runner_importable(self):
        """ExitBacktestRunner 可被 import"""
        from dreambuddy_evolution.scripts.exit_backtest_runner import (  # noqa: F401
            ExitBacktestRunner,
        )

    def test_backtest_runner_run_method_exists(self):
        """ExitBacktestRunner.run() 方法存在"""
        from dreambuddy_evolution.scripts.exit_backtest_runner import (
            ExitBacktestRunner,
        )
        assert hasattr(ExitBacktestRunner, "run")

    def test_backtest_runner_run_single_trade(self):
        """run() 对单笔交易回测返回结果 dict"""
        from dreambuddy_evolution.scripts.exit_backtest_runner import (
            ExitBacktestRunner,
        )

        runner = ExitBacktestRunner()
        trade = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "entry_price": 10000.0,
            "entry_ts": 0,
            "klines": [
                {"ts": i * 3600, "close": 10000 + i * 30, "high": 10050 + i * 30, "low": 9950 + i * 30}
                for i in range(30)
            ],
            "initial_sl_px": 9600.0,
            "initial_tp_px": 10600.0,
            "atr_pct": 0.025,
        }
        result = runner.run(trade)
        assert isinstance(result, dict)
        assert "final_pnl_pct" in result
        assert "exit_reason" in result
        assert "exit_ts" in result

    def test_backtest_runner_compare_baselines(self):
        """compare_baselines() 对比多组基因参数"""
        from dreambuddy_evolution.scripts.exit_backtest_runner import (
            ExitBacktestRunner,
        )

        runner = ExitBacktestRunner()
        trade = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "entry_price": 10000.0,
            "entry_ts": 0,
            "klines": [
                {"ts": i * 3600, "close": 10000 + i * 20, "high": 10050 + i * 20, "low": 9950 + i * 20}
                for i in range(30)
            ],
            "initial_sl_px": 9600.0,
            "initial_tp_px": 10600.0,
            "atr_pct": 0.025,
        }
        genes = [
            {"trailing_arm_pct": 0.04, "break_even_arm_pct": 0.02},
            {"trailing_arm_pct": 0.05, "break_even_arm_pct": 0.03},
        ]
        results = runner.compare_baselines(trade, genes)
        assert len(results) == 2
        for r in results:
            assert "final_pnl_pct" in r
            assert "gene" in r

    def test_backtest_runner_multi_symbol(self):
        """run_multi() 对多标的并行回测"""
        from dreambuddy_evolution.scripts.exit_backtest_runner import (
            ExitBacktestRunner,
        )

        runner = ExitBacktestRunner()
        trades = [
            {
                "symbol": "BTC",
                "pos_side": "long",
                "tier": "standard",
                "entry_price": 10000.0,
                "entry_ts": 0,
                "klines": [
                    {"ts": i * 3600, "close": 10000 + i * 30, "high": 10050 + i * 30, "low": 9950 + i * 30}
                    for i in range(30)
                ],
                "initial_sl_px": 9600.0,
                "initial_tp_px": 10600.0,
                "atr_pct": 0.025,
            },
            {
                "symbol": "ETH",
                "pos_side": "long",
                "tier": "probe",
                "entry_price": 3000.0,
                "entry_ts": 0,
                "klines": [
                    {"ts": i * 3600, "close": 3000 + i * 5, "high": 3050 + i * 5, "low": 2950 + i * 5}
                    for i in range(30)
                ],
                "initial_sl_px": 2850.0,
                "initial_tp_px": 3300.0,
                "atr_pct": 0.03,
            },
        ]
        results = runner.run_multi(trades)
        assert len(results) == 2
        assert results[0]["symbol"] == "BTC"
        assert results[1]["symbol"] == "ETH"

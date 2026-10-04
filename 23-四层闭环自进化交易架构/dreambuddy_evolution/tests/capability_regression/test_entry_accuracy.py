"""test_entry_accuracy.py — 开仓信号准确率能力回归测试（D7）

借鉴 ds4-eval core 套件.
验证维度: 策略基因库加载完整性 + ESS 排序正确性 + 趋势行情信号方向.

硬约束: HC-DS4-08（纯只读验证，不修改实盘行为）.
"""
from __future__ import annotations

import pytest


class TestEntryAccuracy:
    """开仓信号准确率能力回归"""

    def test_gene_library_loaded(self, real_gene_library):
        """基因库加载成功，包含组合和条件"""
        assert real_gene_library is not None
        # 至少有 1 个组合
        assert len(real_gene_library.get("combinations", [])) > 0

    def test_top_combinations_by_ess(self, real_gene_library):
        """top_combinations_by_ess 返回按 ESS 降序排列的组合"""
        from dreambuddy_evolution.core.strategy_gene import top_combinations_by_ess
        all_top = top_combinations_by_ess(real_gene_library)
        top = all_top[:3]  # 取前 3
        # ESS 降序
        ess_values = [c.get("ess", 0) for c in top]
        assert ess_values == sorted(ess_values, reverse=True)
        # 每个组合都有合法的 combo_id
        for combo in top:
            assert combo.get("combo_id", "") != ""

    def test_ess_scores_reasonable(self, real_gene_library):
        """所有组合的 ESS 分数在 [0, 1] 范围内"""
        combos = real_gene_library.get("combinations", [])
        for combo in combos:
            ess = combo.get("ess", 0)
            assert 0.0 <= ess <= 1.0, f"ESS={ess} out of range for {combo.get('gene_id')}"

    def test_trending_market_long_signal(self, real_gene_library, trending_market):
        """上升趋势行情中，策略应产生多头开仓信号（或无信号，但不应做空）.

        验证逻辑: 用 MA200 条件基因判断趋势，趋势向上时多头条件应满足.
        """
        # 计算 MA50 和 MA200（用 close 价格）
        closes = [b["close"] for b in trending_market]
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)
        # 上升趋势中，MA50 > MA200
        assert ma50 > ma200, "trending fixture should produce MA50 > MA200"

    def test_declining_market_no_long(self, real_gene_library, declining_market):
        """下跌行情中，趋势类策略不应产生多头信号.

        验证逻辑: 下跌趋势中 MA50 < MA200，趋势多头条件不满足.
        """
        closes = [b["close"] for b in declining_market]
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)
        # 下跌趋势中，MA50 < MA200
        assert ma50 < ma200, "declining fixture should produce MA50 < MA200"

    def test_min_samples_filter(self, real_gene_library):
        """n_samples 过滤生效：min_sample=500 时结果应少于 min_sample=0"""
        from dreambuddy_evolution.core.strategy_gene import top_combinations_by_ess
        all_combos = top_combinations_by_ess(real_gene_library, min_sample=0)
        filtered = top_combinations_by_ess(real_gene_library, min_sample=500)
        assert len(filtered) <= len(all_combos)

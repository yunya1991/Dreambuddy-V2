"""TDD-SVC-004: waterline >= 80 离场信号回测验证测试 — TDD 先红后绿。

验证 backtest_sector_valuation.py：
  - compute_backtest_stats(triggered_returns) -> Dict
    纯函数：从触发的收益率列表计算统计
  - backtest_waterline_exit(threshold, db_path) -> Dict
    主函数：遍历历史 waterline，计算触发后 30d 收益率

假设（SPEC §10 TDD-SVC-004）：
  waterline >= 80 时赛道未来 30d 收益率显著为负，可作为离场信号

test_assertion: assert backtest_waterline_exit(80)['avg_return_30d'] < 0

铁律（SPEC §0.2）：
  R4 FAIL-OPEN：数据不足不触发信号
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))


def _import_backtest():
    """辅助：延迟导入 backtest_sector_valuation 模块。"""
    from force_vector.backtest_sector_valuation import (
        compute_backtest_stats,
        backtest_waterline_exit,
    )
    return compute_backtest_stats, backtest_waterline_exit


# ---------------------------------------------------------------------------
# 纯函数测试：compute_backtest_stats
# ---------------------------------------------------------------------------

class TestBacktestImport:
    """RED: 模块与符号必须可导入。"""

    def test_module_importable(self):
        from force_vector.backtest_sector_valuation import (
            compute_backtest_stats,
            backtest_waterline_exit,
        )
        assert callable(compute_backtest_stats)
        assert callable(backtest_waterline_exit)


class TestComputeBacktestStats:
    """纯函数：从触发的收益率列表计算统计。"""

    def test_negative_avg_return(self):
        """触发收益率 [-0.10, -0.15] → avg_return=-0.125, win_rate=0.0。"""
        compute_pure, _ = _import_backtest()
        result = compute_pure([-0.10, -0.15])
        assert result["avg_return_30d"] == pytest.approx(-0.125, abs=0.01)
        assert result["win_rate"] == 0.0
        assert result["sample_count"] == 2

    def test_mixed_returns(self):
        """触发收益率 [+0.05, -0.10, +0.02] → avg_return=-0.01, win_rate=2/3。"""
        compute_pure, _ = _import_backtest()
        result = compute_pure([0.05, -0.10, 0.02])
        assert result["avg_return_30d"] == pytest.approx(-0.01, abs=0.01)
        assert result["win_rate"] == pytest.approx(2.0 / 3.0, abs=0.01)
        assert result["sample_count"] == 3

    def test_empty_returns_neutral(self):
        """空列表 → avg_return=0.0, sample_count=0（FAIL-OPEN）。"""
        compute_pure, _ = _import_backtest()
        result = compute_pure([])
        assert result["avg_return_30d"] == 0.0
        assert result["sample_count"] == 0
        assert result["win_rate"] == 0.0

    def test_all_positive_returns(self):
        """触发收益率全正 [+0.10, +0.05] → win_rate=1.0。"""
        compute_pure, _ = _import_backtest()
        result = compute_pure([0.10, 0.05])
        assert result["win_rate"] == 1.0
        assert result["avg_return_30d"] > 0

    def test_required_keys_present(self):
        """返回 dict 包含 avg_return_30d, win_rate, sample_count, max_drawdown。"""
        compute_pure, _ = _import_backtest()
        result = compute_pure([-0.10])
        required_keys = {"avg_return_30d", "win_rate", "sample_count"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# 主函数测试：backtest_waterline_exit（集成，mock 历史数据）
# ---------------------------------------------------------------------------

class TestBacktestWaterlineExit:
    """主函数：遍历历史 waterline，计算触发后 30d 收益率。"""

    def test_waterline_above_threshold_negative_return(self):
        """TDD-SVC-004 test_assertion: waterline >= 80 → avg_return_30d < 0。

        mock 历史数据：3 个时间点，waterline 分别 85/30/90，
        对应 30d 后收益率 -0.10/+0.05/-0.15。
        threshold=80 → 触发点 85/90，avg_return = (-0.10 + -0.15) / 2 = -0.125 < 0
        """
        _, backtest_fn = _import_backtest()
        # mock 历史数据获取
        historical_data = [
            {"date": "2026-01-01", "waterline": 85.0, "return_30d": -0.10},
            {"date": "2026-02-01", "waterline": 30.0, "return_30d": 0.05},
            {"date": "2026-03-01", "waterline": 90.0, "return_30d": -0.15},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_waterlines_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(threshold=80, db_path="/fake/db.db")
        assert result["avg_return_30d"] < 0  # TDD-SVC-004 断言
        assert result["sample_count"] == 2  # 85 和 90 触发
        assert result["avg_return_30d"] == pytest.approx(-0.125, abs=0.01)

    def test_no_triggers_returns_neutral(self):
        """无触发点（waterline 都 < threshold）→ avg_return=0.0。"""
        _, backtest_fn = _import_backtest()
        historical_data = [
            {"date": "2026-01-01", "waterline": 30.0, "return_30d": 0.05},
            {"date": "2026-02-01", "waterline": 50.0, "return_30d": -0.02},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_waterlines_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(threshold=80, db_path="/fake/db.db")
        assert result["avg_return_30d"] == 0.0
        assert result["sample_count"] == 0

    def test_fail_open_empty_history(self):
        """无历史数据 → 返回中性（FAIL-OPEN）。"""
        _, backtest_fn = _import_backtest()
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_waterlines_with_returns",
            return_value=[],
        ):
            result = backtest_fn(threshold=80, db_path="/fake/db.db")
        assert result["avg_return_30d"] == 0.0
        assert result["sample_count"] == 0

    def test_threshold_85_fewer_triggers(self):
        """threshold=85 比 threshold=80 触发点更少。"""
        _, backtest_fn = _import_backtest()
        historical_data = [
            {"date": "2026-01-01", "waterline": 82.0, "return_30d": -0.05},
            {"date": "2026-02-01", "waterline": 90.0, "return_30d": -0.10},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_waterlines_with_returns",
            return_value=historical_data,
        ):
            result_80 = backtest_fn(threshold=80, db_path="/fake/db.db")
            result_85 = backtest_fn(threshold=85, db_path="/fake/db.db")
        assert result_80["sample_count"] == 2  # 82 和 90 都 >= 80
        assert result_85["sample_count"] == 1  # 仅 90 >= 85

    def test_returns_dict_with_required_keys(self):
        """返回 dict 包含 avg_return_30d, win_rate, sample_count, threshold。"""
        _, backtest_fn = _import_backtest()
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_waterlines_with_returns",
            return_value=[{"date": "2026-01-01", "waterline": 85.0, "return_30d": -0.10}],
        ):
            result = backtest_fn(threshold=80, db_path="/fake/db.db")
        required_keys = {"avg_return_30d", "win_rate", "sample_count", "threshold"}
        assert required_keys.issubset(result.keys())
        assert result["threshold"] == 80


# ---------------------------------------------------------------------------
# TDD-SVC-005: waterline >= 85 + 龙头转弱 + 普遍高估 → 14d 跌幅 > 5%
# SPEC §10 TDD-SVC-005 / §5.3 三重确认 AND
# ---------------------------------------------------------------------------

def _import_overheat_short():
    """辅助：延迟导入 backtest_overheat_short + 纯函数。"""
    from force_vector.backtest_sector_valuation import (
        backtest_overheat_short,
        compute_overheat_backtest_stats,
    )
    return backtest_overheat_short, compute_overheat_backtest_stats


class TestOverheatShortImport:
    """RED: backtest_overheat_short 与 compute_overheat_backtest_stats 必须可导入。"""

    def test_overheat_short_importable(self):
        from force_vector.backtest_sector_valuation import backtest_overheat_short
        assert callable(backtest_overheat_short)

    def test_overheat_pure_fn_importable(self):
        from force_vector.backtest_sector_valuation import compute_overheat_backtest_stats
        assert callable(compute_overheat_backtest_stats)


class TestComputeOverheatBacktestStats:
    """纯函数：从触发的 14d 收益率列表计算统计。"""

    def test_negative_avg_return_14d(self):
        """触发收益率 [-0.10, -0.08] → avg_return_14d=-0.09, win_rate=0.0。"""
        _, pure_fn = _import_overheat_short()
        result = pure_fn([-0.10, -0.08])
        assert result["avg_return_14d"] == pytest.approx(-0.09, abs=0.01)
        assert result["win_rate"] == 0.0
        assert result["sample_count"] == 2

    def test_empty_returns_neutral(self):
        """空列表 → avg_return_14d=0.0（FAIL-OPEN）。"""
        _, pure_fn = _import_overheat_short()
        result = pure_fn([])
        assert result["avg_return_14d"] == 0.0
        assert result["sample_count"] == 0

    def test_required_keys_present(self):
        """返回 dict 含 avg_return_14d, win_rate, sample_count, max_drawdown。"""
        _, pure_fn = _import_overheat_short()
        result = pure_fn([-0.10])
        required_keys = {"avg_return_14d", "win_rate", "sample_count", "max_drawdown"}
        assert required_keys.issubset(result.keys())


class TestBacktestOverheatShort:
    """主函数：三重确认触发后 14d 收益率回测。

    三重确认阈值（SPEC §5.3 AND）：
      1. waterline >= 85
      2. leader_momentum < -0.1（严格小于）
      3. overvalued_ratio >= 0.6
    """

    def test_assertion_avg_return_14d_below_neg_5pct(self):
        """TDD-SVC-005 test_assertion: avg_return_14d < -0.05。

        mock 4 条历史数据：
          - 命中1: wl=90, lm=-0.15, ratio=0.7, ret_14d=-0.10
          - 命中2: wl=88, lm=-0.12, ratio=0.65, ret_14d=-0.08
          - 不命中: wl=70 (waterline 不足)
          - 不命中: lm=+0.15 (龙头未转弱)
        命中2点 → avg = (-0.10 + -0.08)/2 = -0.09 < -0.05 ✓
        """
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 90.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.7, "return_14d": -0.10},
            {"date": "2026-01-15", "waterline": 88.0, "leader_momentum": -0.12,
             "overvalued_ratio": 0.65, "return_14d": -0.08},
            {"date": "2026-02-01", "waterline": 70.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.7, "return_14d": 0.05},
            {"date": "2026-02-15", "waterline": 90.0, "leader_momentum": 0.15,
             "overvalued_ratio": 0.7, "return_14d": 0.02},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["avg_return_14d"] < -0.05  # TDD-SVC-005 断言
        assert result["sample_count"] == 2
        assert result["avg_return_14d"] == pytest.approx(-0.09, abs=0.01)

    def test_no_trigger_returns_neutral(self):
        """所有条件均不满足 → avg_return_14d=0.0。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 70.0, "leader_momentum": 0.15,
             "overvalued_ratio": 0.3, "return_14d": 0.05},
            {"date": "2026-02-01", "waterline": 75.0, "leader_momentum": 0.10,
             "overvalued_ratio": 0.4, "return_14d": -0.02},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["avg_return_14d"] == 0.0
        assert result["sample_count"] == 0

    def test_partial_trigger_not_fired(self):
        """仅 2 条件满足（waterline + ratio）但 lm=0.0 未严格<-0.1 → 不触发。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 90.0, "leader_momentum": 0.0,
             "overvalued_ratio": 0.7, "return_14d": -0.20},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["sample_count"] == 0  # lm=0.0 >= -0.1 不触发
        assert result["avg_return_14d"] == 0.0

    def test_leader_momentum_strict_less_boundary(self):
        """SPEC §5.3 严格 < -0.1：lm=-0.1 不触发（边界测试，复用编排层记忆）。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 90.0, "leader_momentum": -0.1,
             "overvalued_ratio": 0.7, "return_14d": -0.20},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["sample_count"] == 0  # lm=-0.1 不严格小于 -0.1
        assert result["avg_return_14d"] == 0.0

    def test_overvalued_ratio_boundary(self):
        """overvalued_ratio=0.6 满足 >=0.6 触发（边界含等号）。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 90.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.6, "return_14d": -0.10},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["sample_count"] == 1  # ratio=0.6 >= 0.6 触发

    def test_waterline_boundary(self):
        """waterline=85 满足 >=85 触发（边界含等号）。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 85.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.7, "return_14d": -0.10},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["sample_count"] == 1  # waterline=85 >= 85 触发

    def test_fail_open_empty_history(self):
        """空历史 → 中性（FAIL-OPEN）。"""
        backtest_fn, _ = _import_overheat_short()
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=[],
        ):
            result = backtest_fn(db_path="/fake/db.db")
        assert result["avg_return_14d"] == 0.0
        assert result["sample_count"] == 0

    def test_fail_open_db_missing(self):
        """DB 路径不存在 → 中性（FAIL-OPEN）。"""
        backtest_fn, _ = _import_overheat_short()
        # 不 mock，让真实 _fetch_historical_overheat_with_returns 走占位路径
        result = backtest_fn(db_path="/nonexistent/path/db.db")
        assert result["avg_return_14d"] == 0.0
        assert result["sample_count"] == 0

    def test_returns_dict_with_required_keys(self):
        """返回 dict 含 avg_return_14d, win_rate, sample_count, threshold。"""
        backtest_fn, _ = _import_overheat_short()
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=[{"date": "2026-01-01", "waterline": 90.0, "leader_momentum": -0.15,
                           "overvalued_ratio": 0.7, "return_14d": -0.10}],
        ):
            result = backtest_fn(db_path="/fake/db.db")
        required_keys = {"avg_return_14d", "win_rate", "sample_count", "threshold"}
        assert required_keys.issubset(result.keys())
        assert result["threshold"] == 85  # SPEC §5.3 默认 85

    def test_threshold_90_fewer_triggers(self):
        """waterline_threshold=90 比 85 触发点更少。"""
        backtest_fn, _ = _import_overheat_short()
        historical_data = [
            {"date": "2026-01-01", "waterline": 88.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.7, "return_14d": -0.10},
            {"date": "2026-02-01", "waterline": 92.0, "leader_momentum": -0.15,
             "overvalued_ratio": 0.7, "return_14d": -0.15},
        ]
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=historical_data,
        ):
            result_85 = backtest_fn(db_path="/fake/db.db", waterline_threshold=85)
            result_90 = backtest_fn(db_path="/fake/db.db", waterline_threshold=90)
        assert result_85["sample_count"] == 2  # 88 和 92 都 >= 85
        assert result_90["sample_count"] == 1  # 仅 92 >= 90

    def test_default_db_path_when_none(self):
        """db_path=None → 用 DEFAULT_DB_PATH（不报错，走占位 FAIL-OPEN）。"""
        backtest_fn, _ = _import_overheat_short()
        with patch(
            "force_vector.backtest_sector_valuation._fetch_historical_overheat_with_returns",
            return_value=[],
        ):
            result = backtest_fn(db_path=None)
        assert result["avg_return_14d"] == 0.0  # 占位返回空 → 中性

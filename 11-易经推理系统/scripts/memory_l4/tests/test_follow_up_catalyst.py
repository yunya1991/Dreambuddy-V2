"""TDD-SVC-003: 跟涨催化因子（Follow-up Catalyst）测试 — TDD 先红后绿。

验证 follow_up_catalyst.py：
  - compute_catalyst_score(leader_momentum, sector_breadth) -> float
    纯函数：catalyst = leader_momentum * sector_breadth
  - compute_follow_up_catalyst(sector, db_path) -> Dict[str, float]
    主函数：获取龙头动量 + 赛道广度 + 合成 catalyst

指标定义（SPEC §3.2 指标 3）：
  catalyst = leader_momentum × sector_breadth
    leader_momentum: 龙头 7d 收益率归一化 [-1, +1]（±20% 为满量程，线性映射）
    sector_breadth: 赛道内 7d 上涨币占比 [0, 1]

信号阈值（SPEC §3.2 指标 3）：
  catalyst > 0.3：龙头强势 + 赛道广度好 → 跟涨概率高
  catalyst < -0.3：龙头弱势 + 赛道广度差 → 回避

铁律（SPEC §0.2）：
  R5 跟涨需龙头动量确认：仅「同赛道低估」不足以买入，需叠加龙头强势
  R4 FAIL-OPEN：数据不足不触发信号

SPEC §8.1 测试用例：
  - 龙头 7d +15%，广度 0.8 → catalyst = 0.6
  - 龙头 7d -10%，广度 0.3 → catalyst = -0.15
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))


def _import_follow_up_catalyst():
    """辅助：延迟导入 follow_up_catalyst 模块。"""
    from force_vector.follow_up_catalyst import (
        compute_catalyst_score,
        compute_follow_up_catalyst,
    )
    return compute_catalyst_score, compute_follow_up_catalyst


# ---------------------------------------------------------------------------
# 纯函数测试：compute_catalyst_score
# ---------------------------------------------------------------------------

class TestCatalystScoreImport:
    """RED: 模块与符号必须可导入。"""

    def test_module_importable(self):
        from force_vector.follow_up_catalyst import (
            compute_catalyst_score,
            compute_follow_up_catalyst,
        )
        assert callable(compute_catalyst_score)
        assert callable(compute_follow_up_catalyst)


class TestComputeCatalystScore:
    """纯函数：catalyst = leader_momentum × sector_breadth。"""

    def test_positive_catalyst_strong(self):
        """SPEC §8.1: 龙头 7d +15%，广度 0.8 → catalyst = 0.6。

        leader_momentum = 0.15 / 0.20 = 0.75（线性归一化）
        catalyst = 0.75 * 0.8 = 0.6
        """
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=0.75, sector_breadth=0.8)
        assert result == pytest.approx(0.6, abs=0.01)

    def test_negative_catalyst_weak(self):
        """SPEC §8.1: 龙头 7d -10%，广度 0.3 → catalyst = -0.15。

        leader_momentum = -0.10 / 0.20 = -0.5
        catalyst = -0.5 * 0.3 = -0.15
        """
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=-0.5, sector_breadth=0.3)
        assert result == pytest.approx(-0.15, abs=0.01)

    def test_zero_momentum_zero_catalyst(self):
        """龙头动量为 0 → catalyst = 0（无催化）。"""
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=0.0, sector_breadth=0.8)
        assert result == 0.0

    def test_zero_breadth_zero_catalyst(self):
        """赛道广度为 0（无币上涨）→ catalyst = 0。"""
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=0.75, sector_breadth=0.0)
        assert result == 0.0

    def test_full_positive_catalyst(self):
        """龙头满量程 +1.0，广度 1.0 → catalyst = 1.0。"""
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=1.0, sector_breadth=1.0)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_full_negative_catalyst(self):
        """龙头满量程 -1.0，广度 1.0 → catalyst = -1.0。"""
        compute_pure, _ = _import_follow_up_catalyst()
        result = compute_pure(leader_momentum=-1.0, sector_breadth=1.0)
        assert result == pytest.approx(-1.0, abs=0.01)

    def test_catalyst_above_threshold(self):
        """catalyst > 0.3 → 跟涨概率高（SPEC §3.2 指标 3）。"""
        compute_pure, _ = _import_follow_up_catalyst()
        # leader_momentum=0.6, breadth=0.6 → catalyst=0.36 > 0.3
        result = compute_pure(leader_momentum=0.6, sector_breadth=0.6)
        assert result > 0.3

    def test_catalyst_below_negative_threshold(self):
        """catalyst < -0.3 → 回避（SPEC §3.2 指标 3）。"""
        compute_pure, _ = _import_follow_up_catalyst()
        # leader_momentum=-0.6, breadth=0.6 → catalyst=-0.36 < -0.3
        result = compute_pure(leader_momentum=-0.6, sector_breadth=0.6)
        assert result < -0.3


# ---------------------------------------------------------------------------
# 主函数测试：compute_follow_up_catalyst（集成）
# ---------------------------------------------------------------------------

class TestComputeFollowUpCatalyst:
    """主函数：从 DB 获取龙头动量 + 赛道广度 + 合成 catalyst。"""

    def test_returns_dict_with_required_keys(self):
        """返回 dict 包含 leader_momentum, sector_breadth, catalyst, leader, timestamp。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._fetch_leader_7d_momentum",
            return_value=0.75,
        ), patch(
            "force_vector.follow_up_catalyst._compute_sector_breadth",
            return_value=0.8,
        ), patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=("UNI", {"UNI": 15_000_000_000}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        required_keys = {"leader_momentum", "sector_breadth", "catalyst", "leader", "timestamp"}
        assert required_keys.issubset(result.keys())
        assert result["catalyst"] == pytest.approx(0.6, abs=0.01)
        assert result["leader"] == "UNI"

    def test_positive_catalyst_scenario(self):
        """龙头强势 + 赛道广度好 → catalyst > 0.3。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._fetch_leader_7d_momentum",
            return_value=0.75,
        ), patch(
            "force_vector.follow_up_catalyst._compute_sector_breadth",
            return_value=0.8,
        ), patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=("UNI", {"UNI": 15_000_000_000}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result["catalyst"] > 0.3
        assert result["leader_momentum"] == 0.75
        assert result["sector_breadth"] == 0.8

    def test_negative_catalyst_scenario(self):
        """龙头弱势 + 赛道广度差 → catalyst < -0.3。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._fetch_leader_7d_momentum",
            return_value=-0.5,
        ), patch(
            "force_vector.follow_up_catalyst._compute_sector_breadth",
            return_value=0.9,  # 广度好但龙头弱 → catalyst = -0.45 < -0.3
        ), patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=("UNI", {"UNI": 15_000_000_000}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result["catalyst"] < -0.3

    def test_fail_open_unknown_sector(self):
        """未知赛道 → catalyst = 0.0（FAIL-OPEN）。"""
        _, compute_fn = _import_follow_up_catalyst()
        result = compute_fn("UnknownSector", "/fake/db.db")
        assert result["catalyst"] == 0.0
        assert result["leader_momentum"] == 0.0
        assert result["sector_breadth"] == 0.0

    def test_fail_open_leader_missing(self):
        """龙头识别失败（无市值数据）→ catalyst = 0.0。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=(None, {}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result["catalyst"] == 0.0
        assert result["leader"] == ""

    def test_fail_open_leader_momentum_zero(self):
        """龙头动量数据缺失 → momentum=0 → catalyst=0。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._fetch_leader_7d_momentum",
            return_value=0.0,
        ), patch(
            "force_vector.follow_up_catalyst._compute_sector_breadth",
            return_value=0.8,
        ), patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=("UNI", {"UNI": 15_000_000_000}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert result["catalyst"] == 0.0

    def test_timestamp_is_iso_string(self):
        """timestamp 是非空 ISO 字符串。"""
        _, compute_fn = _import_follow_up_catalyst()
        with patch(
            "force_vector.follow_up_catalyst._fetch_leader_7d_momentum",
            return_value=0.75,
        ), patch(
            "force_vector.follow_up_catalyst._compute_sector_breadth",
            return_value=0.8,
        ), patch(
            "force_vector.follow_up_catalyst._identify_sector_leader",
            return_value=("UNI", {"UNI": 15_000_000_000}),
        ):
            result = compute_fn("DEX", "/fake/db.db")
        assert isinstance(result["timestamp"], str)
        assert len(result["timestamp"]) > 0


# ---------------------------------------------------------------------------
# 赛道广度测试：_compute_sector_breadth
# ---------------------------------------------------------------------------

class TestComputeSectorBreadth:
    """赛道内 7d 上涨币占比 [0, 1]。"""

    def test_partial_breadth(self):
        """3 币，2 上涨 → breadth = 2/3。"""
        from force_vector.follow_up_catalyst import _compute_sector_breadth
        with patch(
            "force_vector.follow_up_catalyst._fetch_coin_7d_returns",
            return_value={"UNI": 0.05, "CRV": -0.02, "1INCH": 0.01},
        ):
            breadth = _compute_sector_breadth("DEX", "/fake/db.db")
        assert breadth == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_all_up_breadth_one(self):
        """所有币上涨 → breadth = 1.0。"""
        from force_vector.follow_up_catalyst import _compute_sector_breadth
        with patch(
            "force_vector.follow_up_catalyst._fetch_coin_7d_returns",
            return_value={"UNI": 0.10, "CRV": 0.05, "1INCH": 0.01},
        ):
            breadth = _compute_sector_breadth("DEX", "/fake/db.db")
        assert breadth == pytest.approx(1.0, abs=0.01)

    def test_all_down_breadth_zero(self):
        """所有币下跌 → breadth = 0.0。"""
        from force_vector.follow_up_catalyst import _compute_sector_breadth
        with patch(
            "force_vector.follow_up_catalyst._fetch_coin_7d_returns",
            return_value={"UNI": -0.10, "CRV": -0.05, "1INCH": -0.01},
        ):
            breadth = _compute_sector_breadth("DEX", "/fake/db.db")
        assert breadth == 0.0

    def test_zero_return_counts_as_up(self):
        """收益率为 0（持平）→ 计为上涨（>= 0）。"""
        from force_vector.follow_up_catalyst import _compute_sector_breadth
        with patch(
            "force_vector.follow_up_catalyst._fetch_coin_7d_returns",
            return_value={"UNI": 0.0, "CRV": -0.01, "1INCH": 0.0},
        ):
            breadth = _compute_sector_breadth("DEX", "/fake/db.db")
        # UNI=0（>=0 计为涨），CRV 跌，1INCH=0 → 2/3 上涨
        assert breadth == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_empty_returns_zero(self):
        """无数据 → breadth = 0.0（FAIL-OPEN）。"""
        from force_vector.follow_up_catalyst import _compute_sector_breadth
        with patch(
            "force_vector.follow_up_catalyst._fetch_coin_7d_returns",
            return_value={},
        ):
            breadth = _compute_sector_breadth("DEX", "/fake/db.db")
        assert breadth == 0.0

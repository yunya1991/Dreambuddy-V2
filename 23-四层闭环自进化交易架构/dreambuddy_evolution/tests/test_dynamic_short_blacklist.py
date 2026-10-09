"""路径A TDD: 动态做空黑名单测试

SPEC-自进化系统做空能力疏通探讨 §4 路径A：
  将静态 SHORT_ONLY_BLACKLIST = {"ETH", "BTC"} 升级为滚动胜率驱动的动态黑名单。

核心机制:
  - 维护每个币种近 N=20 笔做空交易的滚动胜率
  - Beta-Binomial 共轭先验贝叶斯估计（Beta(4,6) 先验）
  - 胜率 < 35% → 入榜（禁空）
  - 胜率 ≥ 35% → 出榜（可做空，受其他门禁约束）
  - 样本 < 10 → 维持保守（入榜）

A.6 首次试探配额（打破冷启动死循环）:
  - 新币种满足 2 因子 + VOLATILE_DROP/ranging_down → 允许 1 笔 0.1x 试探
  - 30 天冷却，累计 3 笔上限

安全侧 FAIL-OPEN: 异常/缺失 → 入榜（保守，维持 SHORT_BAN）
开关: enable_dynamic_short_blacklist（默认 False → 回退静态 {"ETH", "BTC"}）
"""
import sys
import time
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _auto_enable_dynamic_short():
    """自动开启 enable_dynamic_short_blacklist 开关（Switch 测试类自管不受影响）

    Switch 测试内部 set_switch 会覆盖此 fixture 的设置。
    """
    from dreambuddy_evolution.agi_config import set_switch, get_switch
    _orig = get_switch("enable_dynamic_short_blacklist")
    set_switch("enable_dynamic_short_blacklist", True)
    yield
    set_switch("enable_dynamic_short_blacklist", _orig)


class TestDynamicShortBlacklistBasic:
    """路径A基础功能：动态黑名单入榜/出榜判定"""

    def test_new_symbol_blacklisted(self):
        """新币种无样本 → 入榜（保守）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        assert bl.is_blacklisted("SOL") is True

    def test_insufficient_sample_blacklisted(self):
        """样本 < 10 笔 → 入榜（保守，先验主导）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 记录 5 笔全盈（裸胜率 100%），但样本不足 → 仍入榜
        for _ in range(5):
            bl.record_trade("COIN", pnl=1.0)
        assert bl.is_blacklisted("COIN") is True

    def test_low_win_rate_blacklisted(self):
        """足够样本 + 胜率低（2/15=13%）→ 入榜"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 15 笔中 2 盈 13 亏 → 胜率 13% << 35%
        for i in range(15):
            bl.record_trade("BADCOIN", pnl=1.0 if i < 2 else -1.0)
        assert bl.is_blacklisted("BADCOIN") is True

    def test_high_win_rate_not_blacklisted(self):
        """足够样本 + 胜率高（12/15=80%）→ 出榜"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 15 笔中 12 盈 3 亏 → 胜率 80% >> 35%
        for i in range(15):
            bl.record_trade("GOODCOIN", pnl=1.0 if i < 12 else -1.0)
        assert bl.is_blacklisted("GOODCOIN") is False


class TestDynamicShortBlacklistBayesian:
    """路径A贝叶斯估计：小样本平滑过渡，防止抖动"""

    def test_small_sample_prior_dominant(self):
        """小样本（5笔3盈=60%）裸胜率高于阈值，但贝叶斯先验主导 → 入榜"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 5 笔中 3 盈（裸胜率 60% > 35%），但样本 < 10 → 先验主导
        for i in range(5):
            bl.record_trade("SMALL", pnl=1.0 if i < 3 else -1.0)
        # 小样本不出榜（后验 P(胜率>=35%) 不会 > 0.7）
        assert bl.is_blacklisted("SMALL") is True

    def test_bayesian_smooths_borderline(self):
        """贝叶斯平滑：10笔4盈=40%（略高于35%），后验不确信 → 入榜"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 10 笔中 4 盈（裸胜率 40%），后验 Beta(8,12)
        # P(胜率>=35%) 约 0.56 < 0.7 → 不确信 → 入榜
        for i in range(10):
            bl.record_trade("BORDER", pnl=1.0 if i < 4 else -1.0)
        assert bl.is_blacklisted("BORDER") is True

    def test_large_sample_data_dominant(self):
        """大样本时数据主导：20笔14盈=70% → 出榜"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        for i in range(20):
            bl.record_trade("BIGWIN", pnl=1.0 if i < 14 else -1.0)
        assert bl.is_blacklisted("BIGWIN") is False


class TestDynamicShortBlacklistRollingWindow:
    """路径A滚动窗口：只保留最近 N=20 笔"""

    def test_rolling_window_drops_old(self):
        """滚动窗口：超过 N 笔后旧记录被丢弃，胜率反映最近表现"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 先记录 15 笔全盈（旧数据）
        for _ in range(15):
            bl.record_trade("ROLL", pnl=1.0)
        # 再记录 15 笔全亏（新数据）→ 滚动窗口内最近 20 笔 = 5盈15亏
        for _ in range(15):
            bl.record_trade("ROLL", pnl=-1.0)
        # 滚动窗口 20 笔中 5 盈 15 亏 = 25% < 35% → 入榜
        assert bl.is_blacklisted("ROLL") is True

    def test_rolling_window_keeps_recent(self):
        """滚动窗口：最近 20 笔全盈 → 出榜（即使旧数据全亏）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 先记录 15 笔全亏（旧数据）
        for _ in range(15):
            bl.record_trade("RECOVER", pnl=-1.0)
        # 再记录 20 笔全盈（新数据）→ 窗口内全盈
        for _ in range(20):
            bl.record_trade("RECOVER", pnl=1.0)
        assert bl.is_blacklisted("RECOVER") is False


class TestDynamicShortBlacklistProbeQuota:
    """路径A A.6: 首次试探配额 — 打破冷启动死循环"""

    def test_probe_new_symbol_volatile_drop(self):
        """A.6: 新币种无样本 + 2因子 + VOLATILE_DROP → 允许试探"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        result = bl.can_probe(
            symbol="NEWCOIN",
            regime="VOLATILE_DROP",
            factor_count=2,
        )
        assert result is True

    def test_probe_new_symbol_ranging_down(self):
        """A.6: 新币种无样本 + 2因子 + ranging_down → 允许试探"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        result = bl.can_probe(
            symbol="NEWCOIN2",
            regime="ranging_down",
            factor_count=2,
        )
        assert result is True

    def test_probe_ranging_up_blocked(self):
        """A.6: ranging_up 下禁止试探（负期望条件）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        result = bl.can_probe(
            symbol="NEWCOIN3",
            regime="ranging_up",
            factor_count=2,
        )
        assert result is False

    def test_probe_insufficient_factors(self):
        """A.6: 仅 1 因子 → 不允许试探（分层门槛 2/3）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        result = bl.can_probe(
            symbol="NEWCOIN4",
            regime="VOLATILE_DROP",
            factor_count=1,
        )
        assert result is False

    def test_probe_has_sample_blocked(self):
        """A.6: 已有样本的币种不触发首次试探（仅新币种适用）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 记录 2 笔（已有样本，但仍 <10 → 入榜）
        bl.record_trade("HASDATA", pnl=-1.0)
        bl.record_trade("HASDATA", pnl=-1.0)
        result = bl.can_probe(
            symbol="HASDATA",
            regime="VOLATILE_DROP",
            factor_count=2,
        )
        assert result is False

    def test_probe_cooldown(self):
        """A.6: 30 天冷却期内不重复试探"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 第一次试探允许
        assert bl.can_probe("CD", "VOLATILE_DROP", 2) is True
        # 标记已试探
        bl.mark_probe_executed("CD")
        # 冷却期内不允许
        assert bl.can_probe("CD", "VOLATILE_DROP", 2) is False

    def test_probe_max_count(self):
        """A.6: 累计 3 笔试探后不再允许，进入正常动态判定"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        # 3 次试探（模拟跨越冷却期）
        for _ in range(3):
            bl.mark_probe_executed("MAXCOIN")
            # 跳过冷却期
            bl._skip_probe_cooldown("MAXCOIN")
        # 第 4 次不允许
        result = bl.can_probe("MAXCOIN", "VOLATILE_DROP", 2)
        assert result is False


class TestDynamicShortBlacklistFailOpen:
    """路径A FAIL-OPEN: 异常 → 入榜（保守，维持 SHORT_BAN）"""

    def test_none_symbol_blacklisted(self):
        """symbol=None → 入榜（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        assert bl.is_blacklisted(None) is True

    def test_empty_symbol_blacklisted(self):
        """symbol='' → 入榜（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist()
        assert bl.is_blacklisted("") is True

    def test_corrupted_store_blacklisted(self):
        """交易存储损坏 → 入榜（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        bl = DynamicShortBlacklist(trades_store="nonexistent/path/to/store.json")
        assert bl.is_blacklisted("ANYCOIN") is True


class TestDynamicShortBlacklistSwitch:
    """路径A开关控制：enable_dynamic_short_blacklist（默认 False）"""

    def test_switch_disabled_static_fallback(self):
        """开关关闭 → 回退到静态 {"ETH", "BTC"}"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        from dreambuddy_evolution.agi_config import set_switch, get_switch

        _orig = get_switch("enable_dynamic_short_blacklist")
        try:
            set_switch("enable_dynamic_short_blacklist", False)
            bl = DynamicShortBlacklist()
            # ETH/BTC 仍在黑名单（静态回退）
            assert bl.is_blacklisted("ETH") is True
            assert bl.is_blacklisted("BTC") is True
            # 其他币种不在静态黑名单 → 出榜（开关关闭时动态逻辑不生效）
            assert bl.is_blacklisted("SOL") is False
        finally:
            set_switch("enable_dynamic_short_blacklist", _orig)

    def test_switch_enabled_dynamic(self):
        """开关开启 → 动态判定生效，新币种入榜（保守）"""
        from dreambuddy_evolution.engines.dynamic_short_blacklist import (
            DynamicShortBlacklist,
        )
        from dreambuddy_evolution.agi_config import set_switch, get_switch

        _orig = get_switch("enable_dynamic_short_blacklist")
        try:
            set_switch("enable_dynamic_short_blacklist", True)
            bl = DynamicShortBlacklist()
            # 开关开启时，无样本的新币种 → 入榜（保守）
            assert bl.is_blacklisted("NEWCOIN") is True
        finally:
            set_switch("enable_dynamic_short_blacklist", _orig)

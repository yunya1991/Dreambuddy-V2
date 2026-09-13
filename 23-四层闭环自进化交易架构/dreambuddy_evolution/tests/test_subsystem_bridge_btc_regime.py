"""Phase 4.2 TDD: SubSystemBridge BTC regime 写回测试

验证 RegimeClassifier 结果能通过 set_btc_regime() 写回战略层 shadow 状态，
使 get_btc_regime() 读取到实际 regime 值（而非永远 NEUTRAL）。

硬约束: FAIL-OPEN — trader/状态缺失/异常 → 静默返回，不抛异常
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestSetBtcRegime:
    """set_btc_regime + attach_trader 测试"""

    def test_set_btc_regime_writes_shadow(self):
        """attach_trader + set_btc_regime('WEAK') → get_btc_regime()=='WEAK'"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        trader = SimpleNamespace(
            _five_domain_state_shadow=SimpleNamespace(btc_regime={}),
            _five_domain_state_cache=None,
        )
        bridge = SubSystemBridge()
        bridge.attach_trader(trader)
        bridge.set_btc_regime("WEAK")
        assert bridge.get_btc_regime() == "WEAK"

    def test_set_btc_regime_no_trader_fail_open(self):
        """trader=None → 不抛异常"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        bridge = SubSystemBridge()
        # 不调用 attach_trader，_trader 为 None
        bridge.set_btc_regime("STRONG")  # 不应抛异常
        assert bridge.get_btc_regime() == "NEUTRAL"  # FAIL-OPEN 兜底

    def test_set_btc_regime_no_fds_fail_open(self):
        """_five_domain_state_shadow=None → 静默返回"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        trader = SimpleNamespace(
            _five_domain_state_shadow=None,
            _five_domain_state_cache=None,
        )
        bridge = SubSystemBridge()
        bridge.attach_trader(trader)
        bridge.set_btc_regime("WEAK")  # 不应抛异常
        assert bridge.get_btc_regime() == "NEUTRAL"

    def test_get_btc_regime_returns_written_value(self):
        """写回 STRONG 后 get_btc_regime 读取一致"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        trader = SimpleNamespace(
            _five_domain_state_shadow=SimpleNamespace(btc_regime={}),
            _five_domain_state_cache=None,
        )
        bridge = SubSystemBridge(trader)
        bridge.set_btc_regime("STRONG")
        assert bridge.get_btc_regime() == "STRONG"

    def test_set_btc_regime_neutral_not_overwrite(self):
        """agi_btc_regime='NEUTRAL' 时不写回（避免覆盖真实值）"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        trader = SimpleNamespace(
            _five_domain_state_shadow=SimpleNamespace(btc_regime={"crypto_usdt": "WEAK"}),
            _five_domain_state_cache=None,
        )
        bridge = SubSystemBridge(trader)
        bridge.set_btc_regime("NEUTRAL")  # 不应覆盖已有的 WEAK
        assert bridge.get_btc_regime() == "WEAK"

    def test_set_btc_regime_custom_cls(self):
        """支持自定义 cls 参数"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        trader = SimpleNamespace(
            _five_domain_state_shadow=SimpleNamespace(btc_regime={}),
            _five_domain_state_cache=None,
        )
        bridge = SubSystemBridge(trader)
        bridge.set_btc_regime("WEAK", cls="btc_usd")
        # get_btc_regime 默认读 crypto_usdt，应为 NEUTRAL
        assert bridge.get_btc_regime() == "NEUTRAL"

    def test_set_btc_regime_crash_fail_open(self):
        """_five_domain_state_shadow 属性不存在 → 不抛异常"""
        from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge

        # trader 没有 _five_domain_state_shadow 属性
        trader = SimpleNamespace()
        bridge = SubSystemBridge(trader)
        bridge.set_btc_regime("WEAK")  # 不应抛异常
        assert bridge.get_btc_regime() == "NEUTRAL"

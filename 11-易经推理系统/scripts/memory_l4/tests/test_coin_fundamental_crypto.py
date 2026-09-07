"""B2: 加密货币四信号模块测试 — TDD 先红后绿。

验证四个基本面信号计算：
- revenue_stability：费用 Sharpe → 稳定→正信号
- mc_fees_mean_reversion：MC/Fees 比率 → 高估值→负信号
- tvl_growth_momentum：TVL 7d 变化率 → 增长→正信号
- revenue_quality：fees/TVL 效率 → 高效→正信号
- compute_all：组合四个信号 + FAIL-OPEN
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_crypto import (
    compute_revenue_stability,
    compute_mc_fees_mean_reversion,
    compute_tvl_growth_momentum,
    compute_revenue_quality,
    compute_supply_shrinkage_intensity,
    compute_value_capture_delta,
    compute_all,
    compute_e8_cross_sector_valuation,
    SECTOR_MAP,
)


# ---------------------------------------------------------------------------
# revenue_stability
# ---------------------------------------------------------------------------

class TestRevenueStability:
    """费用 Sharpe → 稳定→正信号。"""

    def test_revenue_stability_normal(self):
        """稳定费用流 → 正信号。"""
        fees_ts = [
            {"date": "2026-08-01", "fees_usd": 1_000_000},
            {"date": "2026-08-02", "fees_usd": 1_050_000},
            {"date": "2026-08-03", "fees_usd": 980_000},
            {"date": "2026-08-04", "fees_usd": 1_020_000},
            {"date": "2026-08-05", "fees_usd": 1_010_000},
        ]
        score = compute_revenue_stability(fees_ts)
        assert -1.0 <= score <= 1.0
        assert score > 0.0  # 稳定费用→正信号

    def test_revenue_stability_insufficient_data_returns_zero(self):
        """数据不足（<3点）→ 返回 0.0。"""
        assert compute_revenue_stability([]) == 0.0
        assert compute_revenue_stability([{"fees_usd": 100}]) == 0.0
        assert compute_revenue_stability([{"fees_usd": 100}, {"fees_usd": 200}]) == 0.0

    def test_revenue_stability_volatile_returns_negative(self):
        """波动大的费用 → 负信号。"""
        fees_ts = [
            {"date": f"2026-08-{i:02d}", "fees_usd": v}
            for i, v in enumerate([100_000, 5_000_000, 50_000, 8_000_000, 200_000], 1)
        ]
        score = compute_revenue_stability(fees_ts)
        assert score < 0.0  # 波动大→负信号


# ---------------------------------------------------------------------------
# mc_fees_mean_reversion
# ---------------------------------------------------------------------------

class TestMCFeesMeanReversion:
    """MC/Fees 比率 → 高估值→负信号。"""

    def test_mc_fees_overvalued_negative(self):
        """MC 远高于 fees_30d → 高估值 → 负信号。"""
        # market_cap=10B, fees_30d=10M → MC/Fees=1000（极高）
        score = compute_mc_fees_mean_reversion(market_cap=10_000_000_000, fees_30d=10_000_000)
        assert -1.0 <= score <= 1.0
        assert score < 0.0  # 高估值→负信号

    def test_mc_fees_undervalued_positive(self):
        """MC 相对 fees 合理 → 正信号。"""
        # market_cap=1B, fees_30d=500M → MC/Fees=2（合理）
        score = compute_mc_fees_mean_reversion(market_cap=1_000_000_000, fees_30d=500_000_000)
        assert score > 0.0  # 合理/低估→正信号

    def test_mc_fees_zero_fees_returns_zero(self):
        """fees_30d=0 → 返回 0.0（除零保护）。"""
        assert compute_mc_fees_mean_reversion(market_cap=1_000_000, fees_30d=0) == 0.0


# ---------------------------------------------------------------------------
# tvl_growth_momentum
# ---------------------------------------------------------------------------

class TestTVLGrowthMomentum:
    """TVL 7d 变化率 → 增长→正信号。"""

    def test_tvl_growth_positive(self):
        """TVL 增长 10% → 正信号。"""
        score = compute_tvl_growth_momentum(tvl_current=1_100_000_000, tvl_7d_ago=1_000_000_000)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_tvl_decline_negative(self):
        """TVL 下跌 10% → 负信号。"""
        score = compute_tvl_growth_momentum(tvl_current=900_000_000, tvl_7d_ago=1_000_000_000)
        assert score < 0.0

    def test_tvl_zero_previous_returns_zero(self):
        """tvl_7d_ago=0 → 返回 0.0（除零保护）。"""
        assert compute_tvl_growth_momentum(tvl_current=1_000, tvl_7d_ago=0) == 0.0


# ---------------------------------------------------------------------------
# revenue_quality
# ---------------------------------------------------------------------------

class TestRevenueQuality:
    """fees/TVL 效率 → 高效→正信号。"""

    def test_revenue_quality_high_efficiency(self):
        """高 fees/TVL 比率 → 正信号。"""
        # fees_30d_avg=1M/day, tvl=100M → 效率=1%
        score = compute_revenue_quality(fees_30d_avg=1_000_000, tvl=100_000_000)
        assert -1.0 <= score <= 1.0
        assert score > 0.0

    def test_revenue_quality_low_efficiency(self):
        """低 fees/TVL 比率 → 负信号。"""
        score = compute_revenue_quality(fees_30d_avg=10_000, tvl=100_000_000)
        assert score < 0.0

    def test_revenue_quality_zero_tvl_returns_zero(self):
        """tvl=0 → 返回 0.0（除零保护）。"""
        assert compute_revenue_quality(fees_30d_avg=1_000, tvl=0) == 0.0


# ---------------------------------------------------------------------------
# supply_shrinkage_intensity (E5) — 阶段识别器输入特征
# ---------------------------------------------------------------------------

class TestSupplyShrinkageIntensity:
    """供给收缩强度 → 通缩→正信号（UNI 费用开关销毁案例）。"""

    def test_supply_shrinkage_intensity_high_burn(self):
        """高锁定比例 + 有费用销毁 → 正信号。"""
        # circulating=500M, max=1B → lock_ratio=0.5, fees_30d=50M
        score = compute_supply_shrinkage_intensity(
            circulating_supply=500_000_000, max_supply=1_000_000_000, fees_30d=50_000_000
        )
        assert -1.0 <= score <= 1.0
        assert score > 0.0  # 高锁定+费用销毁→正

    def test_supply_shrinkage_intensity_no_burn_returns_zero(self):
        """无锁定（circulating=max）+ 无费用 → 0.0。"""
        score = compute_supply_shrinkage_intensity(
            circulating_supply=1_000_000_000, max_supply=1_000_000_000, fees_30d=0
        )
        assert score == 0.0

    def test_supply_shrinkage_intensity_zero_supply_returns_zero(self):
        """circulating_supply=0 → 0.0（除零保护）。"""
        assert compute_supply_shrinkage_intensity(
            circulating_supply=0, max_supply=1_000_000_000, fees_30d=1_000_000
        ) == 0.0


# ---------------------------------------------------------------------------
# value_capture_delta (E6) — 阶段识别器输入特征
# ---------------------------------------------------------------------------

class TestValueCaptureDelta:
    """价值捕获质变 delta → 费用增长超TVL→正信号（Robinhood接入盈收扩张案例）。"""

    def test_value_capture_delta_positive_on_revenue_expansion(self):
        """费用增长 20%，TVL 增长 5% → delta=15% → 正信号。"""
        score = compute_value_capture_delta(fees_growth_rate=0.20, tvl_growth_rate=0.05)
        assert -1.0 <= score <= 1.0
        assert score > 0.0  # 盈收扩张强于规模→正

    def test_value_capture_delta_negative_on_tvl_outpace(self):
        """TVL 增长 10%，费用增长 1% → delta=-9% → 负信号。"""
        score = compute_value_capture_delta(fees_growth_rate=0.01, tvl_growth_rate=0.10)
        assert score < 0.0  # 规模扩张超盈收→负

    def test_value_capture_delta_none_returns_zero(self):
        """任一增长率为 None → 0.0（FAIL-OPEN）。"""
        assert compute_value_capture_delta(fees_growth_rate=None, tvl_growth_rate=0.05) == 0.0
        assert compute_value_capture_delta(fees_growth_rate=0.05, tvl_growth_rate=None) == 0.0


# ---------------------------------------------------------------------------
# compute_all
# ---------------------------------------------------------------------------

class TestComputeAll:
    """组合六个信号。"""

    def test_compute_all_returns_six_signals(self):
        """compute_all 返回六个子信号（含 E5/E6 阶段识别器输入）。"""
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
             patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
             patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl:
            mock_fees.return_value = {
                "fees_30d": 30_000_000,
                "timeseries": [
                    {"date": f"2026-08-{i:02d}", "fees_usd": 1_000_000}
                    for i in range(1, 31)
                ],
            }
            mock_info.return_value = {
                "market_cap_usd": 1_000_000_000,
                "circulating_supply": 500_000_000,
                "max_supply": 1_000_000_000,
            }
            mock_tvl.return_value = {"tvl": 500_000_000, "tvl_7d_ago": 480_000_000}

            signals = compute_all("UNI", db_path="/fake/db.db")

            assert len(signals) == 8  # 7 原信号 + e8_cross_sector_valuation
            assert "revenue_stability" in signals
            assert "mc_fees_mean_reversion" in signals
            assert "tvl_growth_momentum" in signals
            assert "revenue_quality" in signals
            assert "supply_shrinkage_intensity" in signals  # E5
            assert "value_capture_delta" in signals  # E6
            # 稳定费用→正信号
            assert signals["revenue_stability"] > 0.0

    def test_compute_all_missing_protocol_partial_quality(self):
        """缺失 protocol slug → 原 4 信号依赖 protocol fees/tvl 兜底 FAIL-OPEN。

        （2026-09-04 BTC L1 代理分支加入前：4 信号恒=0；
        L1 代理分支加入后：_fetch_L1_chain_metrics 有二级回退(OKX K线 + 先验)，
        当 L1 HTTP 可用时 4 信号非零；当 HTTP/DB 都不可用时，二级回退 return {}，
        4 信号恒=0。本测试用 mock 强制二级回退也 return {} 模拟「L1 数据源全部不可用」
        的 FAIL-OPEN 边界，断言「无 protocol 且无 L1 任何数据 → 4 信号 0」。）
        """
        # BTC 无 protocol slug（是链不是 protocol）
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
             patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
             patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl, \
             patch("force_vector.coin_fundamental_crypto._fetch_L1_chain_metrics") as mock_l1:
            mock_fees.return_value = {}
            mock_info.return_value = {"market_cap_usd": 1_000_000_000_000}
            mock_tvl.return_value = {}
            # 强制 L1 分支也没数据
            mock_l1.return_value = {}

            signals = compute_all("BTC", db_path="/fake/db.db")

            assert len(signals) == 8  # 7 原信号 + e8_cross_sector_valuation
            # BTC 无 protocol 且无 L1 数据 → 4 个原 protocol 相关信号为 0
            assert signals["revenue_stability"] == 0.0
            assert signals["tvl_growth_momentum"] == 0.0
            assert signals["revenue_quality"] == 0.0
            # MC/Fees 信号也依赖 fees/L1 NVT，两项都缺 → 0
            assert signals["mc_fees_mean_reversion"] == 0.0

    def test_compute_all_unknown_coin_returns_zeros(self):
        """未知 coin → 全部 0.0。"""
        signals = compute_all("DOGE", db_path="/fake/db.db")
        assert len(signals) == 8  # 7 原信号 + e8_cross_sector_valuation
        assert all(v == 0.0 for v in signals.values())

    def test_compute_all_exception_returns_zeros(self):
        """任何异常 → 全部 0.0（FAIL-OPEN）。"""
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees",
                   side_effect=RuntimeError("db error")):
            signals = compute_all("UNI", db_path="/fake/db.db")
            assert all(v == 0.0 for v in signals.values())

    # ------------------------------------------------------------------
    # BTC L1 代理信号（protocol=None，但有 L1 链上指标映射）
    # 目标：BTC/ETH/SOL 等 L1 不应再 E1~E4 恒=0。
    # 映射关系：
    #   E1 revenue_stability   ← L1 miner_fees_timeseries (Sharpe)
    #   E2 mc_fees_mean_rev    ← NVT_ratio / S2F 市值估值回归
    #   E3 tvl_growth_momentum ← active_addresses_7d 增速 (替代 TVL)
    #   E4 revenue_quality     ← miner_fees_30d_avg / hashrate (每 TH/s 效率)
    # ------------------------------------------------------------------

    def test_compute_all_btc_L1_proxy_signals_are_non_zero(self):
        """RED: BTC 有 L1 链上指标时 E1~E4 均非零（不再与 protocol 强耦合）。"""
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
             patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
             patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl, \
             patch("force_vector.coin_fundamental_crypto._fetch_L1_chain_metrics") as mock_l1:
            mock_fees.return_value = {}
            mock_tvl.return_value = {}
            mock_info.return_value = {"market_cap_usd": 2_000_000_000_000,
                                      "circulating_supply": 19_700_000,
                                      "max_supply": 21_000_000}
            # L1 链上代理指标
            mock_l1.return_value = {
                # 矿工费 30 天，稳定（日均 15M USD，±10% → Sharpe 正）
                "miner_fees_timeseries": [
                    {"date": f"2026-08-{i:02d}", "fees_usd": 15_000_000 * (1 + 0.05 * (i % 3 - 1))}
                    for i in range(1, 31)
                ],
                "miner_fees_30d": 450_000_000,
                # NVT = 网络价值 / 日交易价值链上 → 低 = 低估 → 正信号
                "nvt_ratio": 18.0,       # BTC 历史 NVT 中枢 25 → 当前低估 → E2 正
                "nvt_historical_median": 25.0,
                # 活跃地址 7 日增速（替代 TVL）：7d 前 800k → 当前 900k
                "active_addresses_now": 900_000,
                "active_addresses_7d_ago": 800_000,
                # 哈希率（安全投入）：矿工费 / 每 TH/s → 效率越高 → E4 正
                "hashrate_THs": 900_000_000.0,  # 900 EH/s = 900M TH/s
            }
            signals = compute_all("BTC", db_path="/fake/db.db")
            # Assert: E1~E4 均非 0（不再被 protocol=None 卡死）
            assert signals["revenue_stability"] != 0.0, (
                f"BTC L1 miner fees 稳定但 revenue_stability=0，L1 代理分支未生效"
            )
            # NVT=18 < 中位数25 → 低估 → E2 应为正
            assert signals["mc_fees_mean_reversion"] > 0.0, (
                f"NVT=18 < 中值25 应低估正信号，实际={signals['mc_fees_mean_reversion']}"
            )
            # 活跃地址 7d +12.5% → E3 应为正
            assert signals["tvl_growth_momentum"] > 0.0, (
                f"活跃地址 +12.5% 应正信号，实际={signals['tvl_growth_momentum']}"
            )
            # 每 TH/s 矿工费效率 > 0 → E4 应为正
            assert signals["revenue_quality"] > 0.0, (
                f"矿工费/哈希率效率>0 应正，实际={signals['revenue_quality']}"
            )

    def test_compute_all_btc_L1_missing_hashrate_keeps_E4_zero_failopen(self):
        """RED: L1 缺 hashrate，E4 revenue_quality 独立 FAIL-OPEN 0，不影响 E1/E3。"""
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
             patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
             patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl, \
             patch("force_vector.coin_fundamental_crypto._fetch_L1_chain_metrics") as mock_l1:
            mock_fees.return_value = {}
            mock_tvl.return_value = {}
            mock_info.return_value = {"market_cap_usd": 2_000_000_000_000}
            # 缺 hashrate_THs / nvt 中值（但有地址 + 矿工费 ts）
            mock_l1.return_value = {
                "miner_fees_timeseries": [
                    {"date": f"2026-08-{i:02d}", "fees_usd": 10_000_000}
                    for i in range(1, 31)
                ],
                "miner_fees_30d": 300_000_000,
                "active_addresses_now": 900_000,
                "active_addresses_7d_ago": 800_000,
                # 故意缺: hashrate_THs, nvt_historical_median
            }
            signals = compute_all("BTC", db_path="/fake/db.db")
            assert signals["revenue_stability"] > 0.0       # 有矿工费 ts → 正
            assert signals["tvl_growth_momentum"] > 0.0     # 有地址增速 → 正
            # FAIL-OPEN: 缺 hashrate → E4 0 （中性兜底，不抛错不连锁）
            assert signals["revenue_quality"] == 0.0

    def test_compute_all_eth_sol_L1_also_use_L1_proxy_branch(self):
        """RED: ETH/SOL 也是 defillama_slug=None 的 L1，应同 BTC 走 L1 代理分支。
        这是 BTC 适配 bonus：现有权威池内 ETH/SOL 改善 E1~E4 从 0 变真实。
        """
        for coin in ("ETH", "SOL"):
            with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
                 patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
                 patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl, \
                 patch("force_vector.coin_fundamental_crypto._fetch_L1_chain_metrics") as mock_l1:
                mock_fees.return_value = {}
                mock_tvl.return_value = {}
                mock_info.return_value = {"market_cap_usd": 300_000_000_000,
                                          "circulating_supply": 120_000_000,
                                          "max_supply": 0}
                mock_l1.return_value = {
                    "miner_fees_timeseries": [
                        {"date": f"2026-08-{i:02d}", "fees_usd": 3_000_000 * (1 + 0.1*(i % 3 - 1))}
                        for i in range(1, 31)
                    ],
                    "miner_fees_30d": 90_000_000,
                    "nvt_ratio": 22.0,
                    "nvt_historical_median": 25.0,
                    "active_addresses_now": 500_000,
                    "active_addresses_7d_ago": 470_000,
                    "hashrate_THs": 12_000_000.0,  # ETH validators / SOL compute units proxy
                }
                signals = compute_all(coin, db_path="/fake/db.db")
                assert signals["revenue_stability"] != 0.0, (
                    f"{coin}: L1 有矿工费 ts 但 E1=0，分支未生效"
                )
                assert signals["mc_fees_mean_reversion"] != 0.0
                assert signals["tvl_growth_momentum"] != 0.0
                assert signals["revenue_quality"] != 0.0

    def test_compute_all_L1_exception_failopen_not_crash(self):
        """RED: L1 取链上指标抛任意异常 → 4 信号 0 兜底，不阻断其它。"""
        with patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees") as mock_fees, \
             patch("force_vector.coin_fundamental_crypto._fetch_coin_info") as mock_info, \
             patch("force_vector.coin_fundamental_crypto._fetch_protocol_tvl") as mock_tvl, \
             patch("force_vector.coin_fundamental_crypto._fetch_L1_chain_metrics",
                   side_effect=RuntimeError("mempool.space API 超时")):
            mock_fees.return_value = {}
            mock_tvl.return_value = {}
            mock_info.return_value = {"market_cap_usd": 2_000_000_000_000}
            # 不应抛异常
            signals = compute_all("BTC", db_path="/fake/db.db")
            # FAIL-OPEN：所有信号 0 中性兜底
            assert signals["revenue_stability"] == 0.0
            assert signals["mc_fees_mean_reversion"] == 0.0
            assert signals["tvl_growth_momentum"] == 0.0
            assert signals["revenue_quality"] == 0.0


# ---------------------------------------------------------------------------
# E8 板块横向估值信号（Cross-Sector Valuation）
# 设计：E8 = 2 - pct/50，pct = 该币 MC/Fees 在板块中的百分位
#   pct=0  → E8=+1（板块最便宜）
#   pct=50 → E8=0（板块中位）
#   pct=100 → E8=-1（板块最贵）
# FAIL-OPEN：板块成员 <3 / 不在板块 / 数据缺失 → 0.0
# ---------------------------------------------------------------------------

class TestE8CrossSectorValuation:
    """E8 板块横向估值：区分「自身高估」vs「板块共振」。"""

    def test_sector_map_has_6_sectors(self):
        """板块映射表包含 6 个板块。"""
        assert len(SECTOR_MAP) == 6
        assert "DEX" in SECTOR_MAP
        assert "Lending" in SECTOR_MAP
        assert "L1" in SECTOR_MAP
        assert "L2" in SECTOR_MAP
        assert "Meme" in SECTOR_MAP
        assert "Perp_DEX" in SECTOR_MAP

    def test_uni_in_dex_sector(self):
        """UNI 属于 DEX 板块。"""
        assert "UNI" in SECTOR_MAP["DEX"]

    @patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees")
    @patch("force_vector.coin_fundamental_crypto._fetch_coin_info")
    def test_e8_cheapest_in_sector_returns_positive(self, mock_info, mock_fees):
        """板块最便宜 → E8 接近 +1。"""
        # fees_map 用 defillama_slug 作 key；mcap_map 用 coingecko_id 作 key
        fees_map = {"uniswap": 100_000_000, "curve": 50_000_000,
                    "1inch": 30_000_000, "pancakeswap": 80_000_000}
        mcap_map = {"uniswap": 5_000_000_000, "curve-dao-token": 8_000_000_000,
                    "1inch": 3_000_000_000, "pancakeswap-token": 6_000_000_000}
        mock_fees.side_effect = lambda db, p: {"fees_30d": fees_map[p]}
        mock_info.side_effect = lambda db, c: {"market_cap_usd": mcap_map[c]}
        # UNI MC/Fees = 5B/100M = 50（最低之一）→ 板块便宜 → E8 > 0
        e8 = compute_e8_cross_sector_valuation("UNI", db_path="/fake/db.db")
        assert e8 > 0.0, f"UNI 应是 DEX 板块便宜之一，E8={e8}"

    @patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees")
    @patch("force_vector.coin_fundamental_crypto._fetch_coin_info")
    def test_e8_most_expensive_in_sector_returns_negative(self, mock_info, mock_fees):
        """板块最贵 → E8 接近 -1。"""
        fees_map = {"uniswap": 100_000_000, "curve": 50_000_000,
                    "1inch": 30_000_000, "pancakeswap": 80_000_000}
        mcap_map = {"uniswap": 50_000_000_000, "curve-dao-token": 8_000_000_000,
                    "1inch": 3_000_000_000, "pancakeswap-token": 6_000_000_000}
        mock_fees.side_effect = lambda db, p: {"fees_30d": fees_map[p]}
        mock_info.side_effect = lambda db, c: {"market_cap_usd": mcap_map[c]}
        # UNI MC/Fees = 50B/100M = 500（最高）→ 板块最贵 → E8 < 0
        e8 = compute_e8_cross_sector_valuation("UNI", db_path="/fake/db.db")
        assert e8 < 0.0, f"UNI 应是 DEX 板块最贵，E8={e8}"

    def test_e8_not_in_sector_returns_zero(self):
        """不在任何板块 → 0.0（FAIL-OPEN）。"""
        e8 = compute_e8_cross_sector_valuation("RANDOMCOIN", db_path="/fake/db.db")
        assert e8 == 0.0

    def test_e8_crcl_not_in_sector_returns_zero(self):
        """CRCL 不在板块（主网未上线）→ 0.0。"""
        e8 = compute_e8_cross_sector_valuation("CRCL", db_path="/fake/db.db")
        assert e8 == 0.0

    @patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees")
    @patch("force_vector.coin_fundamental_crypto._fetch_coin_info")
    def test_e8_missing_data_returns_zero(self, mock_info, mock_fees):
        """数据缺失 → 0.0（FAIL-OPEN）。"""
        mock_fees.return_value = {}
        mock_info.return_value = {}
        e8 = compute_e8_cross_sector_valuation("UNI", db_path="/fake/db.db")
        assert e8 == 0.0

    @patch("force_vector.coin_fundamental_crypto._fetch_protocol_fees")
    @patch("force_vector.coin_fundamental_crypto._fetch_coin_info")
    def test_e8_in_range(self, mock_info, mock_fees):
        """E8 取值范围 [-1, +1]。"""
        fees_map = {"uniswap": 100_000_000, "curve": 50_000_000,
                    "1inch": 30_000_000, "pancakeswap": 80_000_000}
        mcap_map = {"uniswap": 5_000_000_000, "curve-dao-token": 8_000_000_000,
                    "1inch": 3_000_000_000, "pancakeswap-token": 6_000_000_000}
        mock_fees.side_effect = lambda db, p: {"fees_30d": fees_map[p]}
        mock_info.side_effect = lambda db, c: {"market_cap_usd": mcap_map[c]}
        e8 = compute_e8_cross_sector_valuation("UNI", db_path="/fake/db.db")
        assert -1.0 <= e8 <= 1.0

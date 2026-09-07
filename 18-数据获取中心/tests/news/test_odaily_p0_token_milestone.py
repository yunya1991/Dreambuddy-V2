"""TDD RED → GREEN：P0 新特性
- _TOKEN_MILESTONE_KEYWORDS 新类别（9th category）
- _extract_tickers_from_title()  从标题/描述中抓取出现的代币 TICKER（CRCL/BTC/SOL…）
- compute_odaily_event_positive_strength(per-coin odaily records) → 供 polling_trader 读取
"""
from __future__ import annotations

import pytest
from data_center.collectors.news.odaily_newsflash import (
    _classify_event_type,
    _EVENT_TYPE_ENUM,
    _DECAY_HRS,
    _ATTENTION_TYPE_ENUM,
)


# ============================================================
#  T1. TOKEN_MILESTONE 第9类关键词分类（RED阶段：保证测试当前失败）
# ============================================================
class TestTokenMilestoneCategory:
    @pytest.mark.parametrize(
        "title,expected_event",
        [
            ("CRCL 宣布 9 月 16 日上线 ARC 主网并完成跨链迁移", "token_milestone"),
            ("BTC 比特币生态 Stacks 主网升级至 2.5，解锁 Nakamoto 升级", "token_milestone"),
            ("SOL 官方宣布 Q4 启动 FireDancer v3 主网迁移", "token_milestone"),
            ("ARB 代币解锁 12 亿枚（Odaily 快讯）", "token_milestone"),
            ("PEPE 审计通过 CertiK +上线 Coinbase 合规版图", "token_milestone"),
            ("ETH 坎昆升级提案通过（原 project_ecosystem 仍兼容兜底）", "token_milestone"),
        ],
    )
    def test_classify_token_milestone_category(self, title, expected_event):
        """RED阶段：_POLICY_KEYWORDS里尚无token_milestone，全部会fallback到project_ecosystem/market_sentiment"""
        event = _classify_event_type(title, "")
        assert event == expected_event, (
            f"标题「{title}」分类应为 {expected_event}，实际={event} "
            f"（EVENT_TYPE_ENUM={list(_EVENT_TYPE_ENUM)}）"
        )

    def test_token_milestone_decay_24h_like_project_ecosystem(self):
        """RED阶段：DECAY_HRS尚无key，回落到24h需仍等于project_ecosystem（即24h）以匹配行业事件半衰期共识"""
        decay = _DECAY_HRS.get("token_milestone", _DECAY_HRS.get("project_ecosystem", 24))
        assert decay == 24

    def test_token_milestone_in_event_type_enum(self):
        """RED阶段：EVENT_TYPE_ENUM不含 → 断言失败"""
        assert "token_milestone" in _EVENT_TYPE_ENUM, (
            f"_EVENT_TYPE_ENUM缺失token_milestone，当前={list(_EVENT_TYPE_ENUM)}"
        )


# ============================================================
#  T2. ticker_from_title()  — 从标题抓 TICKER 集合
# ============================================================
class TestExtractTickersFromTitle:
    def test_module_has_extract_tickers_function(self):
        """RED阶段：函数不存在，import失败"""
        from data_center.collectors.news.odaily_newsflash import _extract_tickers_from_title  # noqa: F401

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("CRCL 宣布 9 月 16 日上线 ARC 主网并完成跨链迁移", {"CRCL"}),
            ("BTC 比特币现货 ETF 获批 巨鲸增持 1000 枚 BTC ETH SOL", {"BTC", "ETH", "SOL"}),
            ("SOL 于 2026Q4 发布 v3 主网升级 + JTO MEV 解锁", {"SOL", "JTO"}),
            ("ARK Invest 出售 10 万股 COIN（注：ARK 是公司不是 ticker）", {"COIN"}),
            ("美联储维持利率不变，道指下跌", set()),
            ("", set()),
            ("LINK Chainlink 发布 CCIP v2", {"LINK"}),
            ("SAND/MANA/APE 三币联动上线 Binance 合约", {"SAND", "MANA", "APE"}),
        ],
    )
    def test_extract_tickers(self, title, expected):
        from data_center.collectors.news.odaily_newsflash import _extract_tickers_from_title
        got = set(_extract_tickers_from_title(title))
        assert got == expected, (
            f"标题「{title}」抓 ticker 期望={sorted(expected)} 实际={sorted(got)}"
        )


# ============================================================
#  T3. per-coin 快讯 → event_positive_strength [0,1]
#     用于 Score_B 注入 boost clamp[0,0.10]
# ============================================================
class TestOdailyEventPositiveStrength:
    def test_module_has_compute_function(self):
        from data_center.collectors.news.odaily_newsflash import (  # noqa: F401
            compute_coin_event_positive_strength,
        )

    def test_strength_range_0_1_and_max_boost_clamp(self):
        from data_center.collectors.news.odaily_newsflash import compute_coin_event_positive_strength
        # 伪造 2 条强正面 token_milestone 快讯（sentiment=0.92 / 重要=true）
        now_ms = 1756700000000
        fake_records = [
            {
                "metrics": {
                    "od_event_type": "token_milestone",
                    "od_policy_sentiment_0_1": 0.92,
                    "od_is_important": "true",
                    "od_decay_hl_hrs": 24,
                },
                "events": [{"event_type": "token_milestone", "importance": 2,
                            "published_ms": now_ms - 1 * 3600_000}],
                "tickers_hit": ["CRCL"],
            },
            {
                "metrics": {
                    "od_event_type": "token_milestone",
                    "od_policy_sentiment_0_1": 0.85,
                    "od_is_important": "false",
                    "od_decay_hl_hrs": 24,
                },
                "events": [{"event_type": "token_milestone", "importance": 1,
                            "published_ms": now_ms - 5 * 3600_000}],
                "tickers_hit": ["CRCL"],
            },
        ]
        strength, debug = compute_coin_event_positive_strength("CRCL", fake_records, now_ms=now_ms)
        assert 0.0 <= strength <= 1.0
        assert strength > 0.65, f"2条强正面快讯 strength 应>0.65 实际={strength:.3f} debug={debug}"
        # 10条全1.0：strength不得>1.0
        many = [
            {"metrics": {"od_event_type": "token_milestone", "od_policy_sentiment_0_1": 1.0,
                         "od_is_important": "true", "od_decay_hl_hrs": 24},
             "events": [{"event_type": "token_milestone", "importance": 2,
                         "published_ms": now_ms - 1 * 3600_000}],
             "tickers_hit": ["CRCL"]}
            for _ in range(10)
        ]
        s2, _ = compute_coin_event_positive_strength("CRCL", many, now_ms=now_ms)
        assert s2 <= 1.0 + 1e-6
        # 0条快讯 → strength=0.0
        s0, _ = compute_coin_event_positive_strength("CRCL", [], now_ms=now_ms)
        assert abs(s0 - 0.0) < 1e-6

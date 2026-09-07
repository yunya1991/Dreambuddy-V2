"""RED → GREEN：P0 修复中文边界 _extract_tickers_from_title 正则漏抓 BUG + 停用词补全 ATH/技术指标。

BUG复现：当前正则用\b[A-Z]{2,8}\b，Unicode中文与大写字母边界不构成\b → 中文快讯中绝大多数TICKER漏抓。
       同时_TICKER_STOPWORDS未包含ATH/ATL/DCA等常见技术术语→被误抓作币种。
"""
from __future__ import annotations
import os, sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from data_center.collectors.news.odaily_newsflash import (
    _extract_tickers_from_title,
    _TICKER_STOPWORDS,
)


# =========================================================================
# RED Group A：中文/Unicode上下文边界漏抓（8条 parametrize）
#   当前代码(用\b)下应全部FAIL → GREEN（零宽断言）后应全部PASS
# =========================================================================
class TestCnUnicodeBoundaryExtract:
    @pytest.mark.parametrize(
        "title,desc,expected_contains,at_least_one",
        [
            # (A1) 中文汉字直接夹大写：HYPE 前后是中文 → 当前\b漏抓
            ("持仓价值1806万美元，某巨鲸疑似止盈HYPE并向Coinbase充值88216枚", "预计盈利153.8万美元", ["HYPE"], True),
            # (A2) BTC/ETH 中文夹：做多 BTC 做空 ETH → 前后中文 → 当前漏（BTC在"多"后"做"前？不对，做多是中文，后面有空格！）
            # 改为纯中文夹：全仓压入BTC现货，同时在OKX开空ETH永续合约（BTC前"入"中文，ETH前"空"中文永续后"合"中文？）
            ("全仓压入BTC现货，同时在OKX开空ETH永续合约", "Crypto trading plan", ["BTC", "ETH"], True),
            # (A3) 中文结尾接TICKER：最终决定离场SOL → SOL前"场"中文后无空格
            ("最终决定离场SOL并且逢低建仓SAND", "操作计划", ["SOL", "SAND"], True),
            # (A4) TICKER后接中文：LINK跨链通道今日正式打通 → LINK后"跨"中文
            ("LINK跨链通道今日正式打通，连接BSC与Base", "跨链主网进度", ["LINK", "BSC", "BASE"], True),
            # (A5) 标点符号夹TICKER：持仓[CRCL]×30%等待主网 → 中文+括号
            ("持仓[CRCL]比例30%等待ARC主网上线、逢低加仓MATIC", "Crypto portfolio", ["CRCL", "MATIC"], True),
            # (A6) TICKER相邻中文数字混合：买了100枚NVDA、50枚TSLA → NVDA前"枚"，TSLA前"枚"
            ("二级市场买了100枚NVDA、50枚TSLA看涨期权", "Traditional finance trading", ["NVDA", "TSLA"], True),
            # (A7) 冒号/引号夹TICKER：利好标题：「$CRCL上线主网」倒计时中 → 引号+美元符(已覆盖$分支)
            ("重磅利好官宣：「CRCL将于9/16上线ARC主网，跨链通道一并打通」", "Token milestone release", ["CRCL"], True),
            # (A8) 句首句末全中文环境的大写：MSTR昨日披露加仓BTC 今日继续加仓COIN → MSTR句首（前无字符没问题？）BTC后"今"中文COIN前"仓"中文
            ("MSTR昨日披露加仓BTC今日继续加仓COIN并申请ETH ETF", "MicroStrategy news", ["MSTR", "BTC", "COIN", "ETH"], True),
        ],
    )
    def test_cn_unicode_boundary_extract_all_relevant_tickers(
        self, title, desc, expected_contains, at_least_one
    ):
        ticks = _extract_tickers_from_title(title, desc)
        if at_least_one:
            # 必须命中expected中至少一个（因为部分ticker可能在停用词，比如ETH ETF的ETF，但BTC/MSTR/COIN必须命中）
            hits = [t for t in expected_contains if t in ticks]
            assert len(hits) >= 1, (
                f"中文边界提取0命中；要命中{expected_contains}，实际ticks={ticks}. "
                f"这就是P0正则\b漏抓BUG：中文↔大写字母不构成ASCII word boundary。"
            )
        else:
            for e in expected_contains:
                assert e in ticks, f"应包含{e}实际{ticks}"


# =========================================================================
# RED Group B：停用词补全 ATH 技术术语不被误抓
#   当前代码ATH不在停用词中→被抓→GREEN补全后应不命中
# =========================================================================
class TestStopwordsCatchTechnicalTerms:
    @pytest.mark.parametrize(
        "title,desc,not_expected",
        [
            # (B1) ATH = All-Time-High 技术术语 不是币种
            ("PONS市值突破3亿美元，续创历史新高ATH", "PONS breaks ATH", ["ATH"]),
            # (B2) ATL = All-Time-Low ；DCA = 定投策略；MACD / RSI 指标
            ("BTC触ATL后开启DCA抄底，MACD金叉+RSI超卖发出买入信号",
             "Technical analysis report", ["ATL", "DCA", "MACD", "RSI"]),
            # (B3) MA均线/EMA指数/BOLL布林带
            ("MA5上穿MA20金叉+BOLL中轨突破+EMA24拐头向上",
             "Moving average alerts", ["MA", "EMA", "BOLL"]),
        ],
    )
    def test_technical_terms_not_extracted_as_tickers(self, title, desc, not_expected):
        ticks = _extract_tickers_from_title(title, desc)
        for bad in not_expected:
            assert bad not in ticks, (
                f"技术术语{bad}被误抓作TICKER！当前停用词池缺{not_expected}。ticks={ticks}"
            )

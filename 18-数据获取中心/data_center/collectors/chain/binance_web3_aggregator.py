"""币安 Web3 跨币聚合器 — 把数百个 BSC 小币横截面压成 1 条市场级因子记录。

为什么需要独立聚合器：
  23/40 的交易标的是 BTC/ETH/SOL 与大类锚（OKX 永续），
  而 BinanceWeb3MarketCollector 采集的是 BSC 链上的热门小币，
  两者不是同一合约。逐币记录按 symbol 对齐会造出假因子，
  因此这里只输出一条 sub_category=web3_market 的横截面聚合，
  经 19-DAL 回填写入 mm_metrics 后供 23 域因子注册表消费。

口径纪律：
  - 榜单成员每轮变化 → 用中位数 / 比率，不用 sum（横截面热度的位置比总量稳定）
  - alpha 榜（rankType=20）混入代币化股票（raw.stockCompanyName 非空），
    只计数，不进热度聚合（否则股票市值会把 crypto 热度稀释掉）
  - 全部 FAIL-OPEN：任一路失败 → 该组指标缺省，不写 key
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import median
from typing import Any

from data_center.collectors._base import BaseCollector
from data_center.collectors.chain.binance_web3_market_collector import (
    BinanceWeb3MarketCollector,
)
from data_center.core.contract import DataRecord, validate_record

_log = logging.getLogger(__name__)

_SUB_CATEGORY = "web3_market"
# risk_level 观测值域为 0 / 1 / 2.5，>=2.5 记为高风险代币
_HIGH_RISK_THRESHOLD = 2.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _put(metrics: dict, key: str, value: float | None) -> None:
    if value is not None:
        metrics[key] = value


def _values(records: list[DataRecord], key: str) -> list[float]:
    out: list[float] = []
    for rec in records:
        v = _num(rec.metrics.get(key))
        if v is not None:
            out.append(v)
    return out


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def aggregate_web3_metrics(groups: dict[str, list[DataRecord]]) -> dict[str, float]:
    """把各路榜单记录压成一条横截面指标（纯函数，无 IO）。

    groups 的 key：trending / top_search / alpha / social / smart / meme / narrative
    """
    struct = list(groups.get("trending") or []) + list(groups.get("top_search") or [])
    social = groups.get("social") or []
    smart = groups.get("smart") or []
    meme = groups.get("meme") or []
    narrative = groups.get("narrative") or []
    alpha = groups.get("alpha") or []

    if not (struct or social or smart or meme or narrative):
        return {}

    m: dict[str, float] = {}
    m["web3_structure_count"] = float(len(struct))

    # ── 筹码结构（趋势榜 + 搜索榜）────────────────────────────────
    for src_key, dst_key in (
        ("new_wallet_pct", "web3_new_wallet_pct_med"),
        ("top10_holders_pct", "web3_top10_conc_med"),
        ("dev_holding_pct", "web3_dev_holding_pct_med"),
        ("liquidity", "web3_liquidity_med"),
        ("risk_level", "web3_risk_level_med"),
    ):
        _put(m, dst_key, _median(_values(struct, src_key)))

    # sniper + bundler 逐币求和后取中位数（单币两个字段都可能缺失）
    sb: list[float] = []
    for rec in struct:
        parts = [
            v
            for v in (
                _num(rec.metrics.get("sniper_holding_pct")),
                _num(rec.metrics.get("bundler_holding_pct")),
            )
            if v is not None
        ]
        if parts:
            sb.append(sum(parts))
    _put(m, "web3_sniper_bundler_pct_med", _median(sb))

    buys = sum(_values(struct, "volume_24h_buy"))
    sells = sum(_values(struct, "volume_24h_sell"))
    if sells > 0:
        m["web3_buy_sell_vol_ratio"] = round(buys / sells, 6)

    risks = _values(struct, "risk_level")
    if risks:
        m["web3_high_risk_ratio"] = round(
            sum(1 for x in risks if x >= _HIGH_RISK_THRESHOLD) / len(risks), 6
        )

    # ── 社交热度与情绪 ────────────────────────────────────────────
    _put(m, "web3_hype_med", _median(_values(social, "social_hype")))
    sentiments = _values(social, "sentiment_score")
    if sentiments:
        m["web3_sentiment_mean"] = round(sum(sentiments) / len(sentiments), 6)

    # ── 聪明钱 ────────────────────────────────────────────────────
    inflows = _values(smart, "inflow_usd")
    if inflows:
        m["web3_smart_money_net_inflow_usd"] = round(sum(inflows), 2)
    traders = _values(smart, "smart_traders")
    if traders:
        m["web3_smart_traders"] = round(sum(traders), 2)

    # ── meme 算法评分 ─────────────────────────────────────────────
    _put(m, "web3_meme_score_med", _median(_values(meme, "score")))
    flags = [
        _num(rec.metrics.get("ai_narrative_flag"))
        for rec in meme
        if _num(rec.metrics.get("ai_narrative_flag")) is not None
    ]
    if flags:
        m["web3_ai_narrative_ratio"] = round(sum(1 for f in flags if f) / len(flags), 6)

    # ── 叙事资金流入 ──────────────────────────────────────────────
    # 用中位数：单条叙事（如某话题 230 亿）会主导 sum，且该接口个别话题的
    # topicNetInflow 量级异常，取中位数可保证横截面可比
    _put(m, "web3_narrative_net_inflow_med", _median(_values(narrative, "net_inflow_usd")))

    # ── alpha 榜口径隔离（代币化股票只计数）───────────────────────
    m["web3_alpha_stock_count"] = float(
        sum(1 for rec in alpha if (rec.raw or {}).get("stockCompanyName"))
    )
    return m


class BinanceWeb3MarketAggregator(BaseCollector):
    """Web3 榜单横截面聚合（独立 source，避免与逐币采集器在注册表撞名）。"""

    source = "binance_web3_agg"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 公开接口，无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        chain_id = str(params.get("chain_id", "56"))
        size = int(params.get("size", 30))
        period = str(params.get("period", "24h"))
        narrative_chain = str(params.get("narrative_chain_id", "CT_501"))
        ts = _now_iso()

        market = BinanceWeb3MarketCollector()
        groups: dict[str, list[DataRecord]] = {
            "trending": market._fetch_rank(chain_id, 10, size, ts),
            "top_search": market._fetch_rank(chain_id, 11, size, ts),
            "alpha": market._fetch_rank(chain_id, 20, size, ts),
            "social": market._fetch_social_hype(chain_id, ts),
            "smart": market._fetch_smart_money(chain_id, period, ts),
            "meme": market._fetch_meme_rank(chain_id, ts),
            "narrative": market._fetch_narrative(
                narrative_chain,
                int(params.get("rank_type", 30)),
                int(params.get("sort", 30)),
                ts,
            ),
        }

        metrics = aggregate_web3_metrics(groups)
        if not metrics:
            _log.warning("binance_web3 聚合无有效数据，本轮不写记录")
            return []

        rec = DataRecord(
            source=self.source,
            category=self.category,
            sub_category=_SUB_CATEGORY,
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={
                "chain_id": chain_id,
                "counts": {name: len(items) for name, items in groups.items()},
                "risk_high_threshold": _HIGH_RISK_THRESHOLD,
            },
        )
        validate_record(rec)
        return [rec]

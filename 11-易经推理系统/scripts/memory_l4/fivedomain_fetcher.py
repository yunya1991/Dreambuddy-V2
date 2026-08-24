#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainFetcher — 用数据获取中心（data_center）一次性采集五维所需全部外部数据。

输出: `Dict[asset_class, Dict[str, Any]]`，key 集合对齐 FiveDomainFeatureComputer
需要的 coin_data（分层结构）：crypto_usdt / us_stock / precious_metal。

数据来源映射（对齐 FIVE_DOMAIN_DATA_COLLECTION_DESIGN.md §二）：
  D1 联邦基金利率     → fred FEDFUNDS
  D2 M2 同比           → fred M2NS（如果需要 M2SL 也可在派生层自选）
  D3 联储总资产        → fred WALCL / 1e12 → trillion USD
  D4 CPI 同比          → fred CPIAUCSL（用与上月环比 = proxy yoy 简化）
  D5 PPI               → fred PPIACO（预留键，当前编排层只在 raw 里放）
  D6 工业产出          → fred INDPRO（↑/↓ = 美林增长 proxy）
  D7 稳定币总市值 proxy → defillama chains_summary top 链 TVL（Tron/Ethereum 最聚集稳定币）
  D8 DeFi TVL          → defillama chains_summary 总 TVL
  D9 ETH Gas           → etherscan kind=gas 的 propose_gas
  D10 政策景气度       → tavily 新闻简易情感词典打分

派生项（编排层本地计算，不占外部采集）：
  T1 美林时钟阶段 merrill_phase = 通胀↑/↓ × 增长↑/↓ 的四象限
  T4 流动性评分 liquidity_score = 0.4×利率反转 + 0.4×M2 + 0.2×WALCL 归一化
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# 兼容：11-易经推理系统/scripts/memory_l4 目录下运行，需要把 18-数据获取中心 加到 sys.path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DATA_CENTER_PKG_ROOT = os.path.join(_REPO, "18-数据获取中心")
if _DATA_CENTER_PKG_ROOT not in sys.path:
    sys.path.insert(0, _DATA_CENTER_PKG_ROOT)


ASSET_CLASSES = ("crypto_usdt", "us_stock", "precious_metal")

# 政策情绪简易词典（Tavily 标题+内容匹配，后续可换模型）
_POS_WORDS = ("宽松", "降息", "批准", "支持", "利好", "流入", "复苏", "升级",
              "easing", "cut", "approve", "inflow", "bullish", "support")
_NEG_WORDS = ("紧缩", "加息", "起诉", "处罚", "监管", "限制", "禁止", "流出", "暴跌",
              "tightening", "hike", "sue", "penalty", "crackdown", "restrict", "outflow")


class FiveDomainFetcher:
    """编排层：拉取数据 → 按类装配 coin_data → 衍生 merrill_phase / liquidity_score。

    Args:
        data_center: 任何具备 `fetch(category, source=..., **params) -> List[DataRecord]`
            方法的对象。生产环境用 `DataCenter()`，测试可传 FakeDC。
        policy_queries: 政策新闻查询词，默认对齐 D10（SEC/Fed/中国监管）。
    """

    DEFAULT_POLICY_QUERIES: Tuple[str, ...] = (
        "Fed FOMC monetary policy latest",
        "SEC CFTC crypto regulation update latest",
        "China crypto policy news latest",
    )

    def __init__(self, data_center: Any = None, policy_queries: Tuple[str, ...] = DEFAULT_POLICY_QUERIES):
        if data_center is None:
            from data_center.core.dispatcher import DataCenter
            data_center = DataCenter()
        self.dc = data_center
        self.policy_queries = tuple(policy_queries)
        # 采集结果缓存（按日期）：避免 1 天内重复打 API
        self._cache: Dict[str, Any] = {}

    # ==================================================================
    # 对外入口
    # ==================================================================
    def fetch_coin_data(self) -> Dict[str, Dict[str, Any]]:
        """一次性采集并返回三类资产的 coin_data。"""
        raw = self._collect_raw()
        result: Dict[str, Dict[str, Any]] = {}
        for cls in ASSET_CLASSES:
            result[cls] = self._build_class_coin(cls, raw)
        return result

    # ==================================================================
    # 内部：批量采集 raw（D1~D10, T2）
    # ==================================================================
    def _collect_raw(self) -> Dict[str, Any]:
        raw: Dict[str, Any] = {}
        # ── FRED 6 系列 ──
        for s in ("FEDFUNDS", "M2NS", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO"):
            raw[f"fred:{s}"] = self._safe_first_metric(
                self.dc.fetch("macro", source="fred", series=s)
            )
        # ── VIX ──
        raw["yfinance:^VIX"] = self._safe_first_metric(
            self.dc.fetch("finance", source="yfinance", symbol="^VIX")
        )
        # ── DeFiLlama chains ──
        raw["defillama:chains"] = self._safe_first(
            self.dc.fetch("chain", source="defillama", route="chains")
        )
        # ── etherscan gas ──
        raw["etherscan:gas"] = self._safe_first_metric(
            self.dc.fetch("chain", source="etherscan", kind="gas")
        )
        # ── 政策新闻 D10 ──
        policy_events: List[Any] = []
        for q in self.policy_queries:
            try:
                recs = self.dc.fetch("news", source="tavily", query=q, max_results=5)
            except Exception:
                recs = []
            for r in recs or []:
                items = (r.raw or {}).get("results") or []
                policy_events.extend(items)
        raw["policy:events"] = policy_events
        return raw

    # ==================================================================
    # 内部：按资产类装配 coin_data
    # ==================================================================
    def _build_class_coin(self, asset_cls: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        coin: Dict[str, Any] = {}

        # D1 联邦基金利率（FRED value 是百分比，如 5.25）
        coin["fedfunds_rate"] = self._val(raw.get("fred:FEDFUNDS"), "value")
        # D2 M2NS value = M2 十亿美元 → 除以 1000 是万亿。这里简化把原始值作为 M2 指数存
        m2 = self._val(raw.get("fred:M2NS"), "value")
        coin["m2_yoy_pct"] = None  # FRED M2NS 是绝对值，同比需历史对比，这里留空后续增强
        if m2 is not None:
            coin["m2_index_bln"] = m2
        # D3 WALCL → trillion（WALCL 原始是美元，除以 1e12 得万亿）
        walcl = self._val(raw.get("fred:WALCL"), "value")
        coin["fed_balance_sheet_trillion"] = round(walcl / 1e12, 4) if isinstance(walcl, (int, float)) else None
        # D4 CPIAUCSL 同比（简化：当前只记录指数值）
        coin["us_cpi_yoy_pct"] = self._val(raw.get("fred:CPIAUCSL"), "value")
        # D5 PPI 预留
        coin["us_ppi_yoy_pct"] = self._val(raw.get("fred:PPIACO"), "value")
        # D6 工业产出
        coin["us_indpro_yoy_pct"] = self._val(raw.get("fred:INDPRO"), "value")

        # ── 链上：只对 crypto_usdt 有意义 ──
        chains_rec = raw.get("defillama:chains")
        if asset_cls == "crypto_usdt":
            if chains_rec is not None:
                coin["defi_tvl_bln"] = (chains_rec.metrics or {}).get("total_tvl_bln")
                # D7 稳定币总市值 proxy = Ethereum+TRON TVL（最集中稳定币）
                try:
                    chains_map = (chains_rec.raw or {}).get("chains", {})
                    eth_tvl = chains_map.get("Ethereum", {}).get("tvl_bln", 0.0)
                    tron_tvl = chains_map.get("TRON", {}).get("tvl_bln", 0.0)
                    coin["stablecoin_mcap_bln"] = round(eth_tvl + tron_tvl, 4)
                except Exception:
                    coin["stablecoin_mcap_bln"] = None
            else:
                coin["defi_tvl_bln"] = None
                coin["stablecoin_mcap_bln"] = None
            gas_metrics = raw.get("etherscan:gas") or {}
            coin["gas_eth_gwei"] = gas_metrics.get("propose_gas") if isinstance(gas_metrics, dict) else None
        else:
            coin["defi_tvl_bln"] = None
            coin["stablecoin_mcap_bln"] = None
            coin["gas_eth_gwei"] = None

        # D10 政策景气度（只填到 crypto，其它类留 None — 后续可按资产类扩展 query）
        if asset_cls == "crypto_usdt":
            coin["policy_sentiment_score"] = self._sentiment_score(raw.get("policy:events") or [])
        else:
            coin["policy_sentiment_score"] = None

        # T2 VIX（对三类都共享）
        vix_metrics = raw.get("yfinance:^VIX") or {}
        # YFinanceCollector 输出 metrics["price"]；fallback 兼容 raw
        vix_price = None
        if isinstance(vix_metrics, dict):
            vix_price = vix_metrics.get("price") or vix_metrics.get("value")
        coin["vix_close"] = vix_price

        # T1 美林时钟（通胀（CPI proxy）× 增长（INDPRO proxy））
        coin["merrill_phase"] = self._compute_merrill(
            coin.get("us_cpi_yoy_pct"), coin.get("us_indpro_yoy_pct")
        )

        # T4 流动性评分
        coin["liquidity_score"] = self._compute_liquidity_score(
            coin.get("fedfunds_rate"),
            coin.get("m2_yoy_pct"),
            coin.get("fed_balance_sheet_trillion"),
        )

        return coin

    # ==================================================================
    # helpers
    # ==================================================================
    @staticmethod
    def _safe_first(recs: List[Any]) -> Any:
        return recs[0] if isinstance(recs, list) and recs else None

    @classmethod
    def _safe_first_metric(cls, recs: List[Any]) -> Optional[Dict[str, Any]]:
        first = cls._safe_first(recs)
        if first is None:
            return None
        m = getattr(first, "metrics", None)
        return dict(m) if isinstance(m, dict) else None

    @staticmethod
    def _val(metric: Optional[Dict[str, Any]], key: str) -> Any:
        if not isinstance(metric, dict):
            return None
        return metric.get(key)

    # ------------------------------------------------------------------
    # 衍生：美林时钟（4 象限，对齐 _MERRILL_PHASE_SCORES key）
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_merrill(cpi: Any, indpro: Any) -> Optional[str]:
        if not isinstance(cpi, (int, float)) or not isinstance(indpro, (int, float)):
            return None
        # 通胀方向：CPI > 100 视为历史上升中（简化 proxy）
        # 这里更稳妥：用 CPI 指数相对 250 的大致基准 → 粗判通胀是否偏高
        infl_up = cpi >= 250.0
        # 增长方向：INDPRO 相对 100 → >100 视为↑
        grow_up = indpro >= 100.0
        if grow_up and not infl_up: return "RECOVERY"    # 复苏
        if grow_up and infl_up:     return "OVERHEAT"    # 过热
        if not grow_up and infl_up: return "STAGFLATION" # 滞胀
        return "REFLATION"                              # 衰退/再通

    # ------------------------------------------------------------------
    # 衍生：流动性评分 [0,1]（对齐 FiveDomainFeatureComputer._compute_liquidity_cycle_score）
    # 利率低→加分；M2 高→加分；联储表扩张→加分
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_liquidity_score(
        fedfunds: Any, m2_yoy: Any, bs_trillion: Any
    ) -> Optional[float]:
        scores = []
        # 利率：0%→1.0, 6%→0.0, 线性
        if isinstance(fedfunds, (int, float)):
            scores.append(max(0.0, min(1.0, (6.0 - float(fedfunds)) / 6.0)))
        # M2 同比：-5%→0.0, +10%→1.0（简化）
        if isinstance(m2_yoy, (int, float)):
            scores.append(max(0.0, min(1.0, (float(m2_yoy) + 5.0) / 15.0)))
        # 联储表：4T→0.2, 9T→1.0
        if isinstance(bs_trillion, (int, float)):
            scores.append(max(0.0, min(1.0, (float(bs_trillion) - 4.0) / 5.0)))
        if not scores:
            return None
        # 利率权重 50%，M2 25%，联储表 25%
        if len(scores) == 1:
            return float(scores[0])
        if len(scores) == 2:
            # 缺哪一项就加权剩下的
            return float(0.5 * scores[0] + 0.5 * scores[1])
        return float(0.5 * scores[0] + 0.25 * scores[1] + 0.25 * scores[2])

    # ------------------------------------------------------------------
    # 衍生：D10 政策情绪 → [0,1]
    # ------------------------------------------------------------------
    @classmethod
    def _sentiment_score(cls, events: List[Any]) -> float:
        if not events:
            return 0.5  # 缺数据中性
        pos = 0
        total = 0
        for e in events:
            if not isinstance(e, dict):
                continue
            text = f"{e.get('title','')} {e.get('content','')}".lower()
            if not text.strip():
                continue
            total += 1
            p = sum(1 for w in _POS_WORDS if w.lower() in text)
            n = sum(1 for w in _NEG_WORDS if w.lower() in text)
            if p > n: pos += 1
            elif p < n: pass  # 中性不加分
            else: pos += 0.5   # 打平加半
        if total == 0:
            return 0.5
        return round(max(0.0, min(1.0, pos / total)), 4)

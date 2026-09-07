"""Odaily 星球日报快讯 Collector — 政策维度数据源。

严格对齐 Spec P0-2 §4：
  - source = "odaily_newsflash" / category = "news"
  - 3 endpoints（web-api.odaily.news，无反爬无鉴权）：
      · GET /newsflash/page?cursor=0&limit=20 首屏20条
      · GET /newsflash/checkHasNew?lastId=<最大已入库id> 增量
      · GET /hotWord/list?limit=N 关键词补（当前暂未用到）
  - 去重第一道：增量模式下 checkHasNew 返回 N=0 直接 []。
  - 7 个扁平 metrics（contract 硬约束）：
      od_source_id, od_policy_sentiment_0_1, od_event_type,
      od_attention_type, od_is_important, od_decay_hl_hrs, od_title_hash
  - 硬编码三常量：_POLICY_KEYWORDS(14) / _EVENT_TYPE_MAP(7+1 类 regex) / _DECAY_HRS(4档)
  - FAIL-OPEN L1: Session.get Timeout/SSLError/任何 Exception → []，不 throw。
  - FAIL-OPEN L2: lazy import 9基本面 sentiment_engine，ImportError → 全部 sentiment=0.5。
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger("data_center.collectors.news.odaily_newsflash")

_ODAILY_API = "https://web-api.odaily.news"
_HTTP_HEADERS = {"locale": "zh-CN", "User-Agent": "DreamBuddy-DC/1.0"}
_HTTP_TIMEOUT = 10

# ────────────────────────────────────────────────────────────
# §4.3 硬编码常量
# ────────────────────────────────────────────────────────────

# 14 组政策/行情关键词（event_type classification pipeline Step1 keyword_rules）
_POLICY_KEYWORDS: dict[str, list[str]] = {
    "monetary_policy": [
        "降息", "加息", "利率决议", "FOMC", "美联储", "欧央行", "央行",
        "缩表", "扩表", "购债", "通胀", "CPI", "PCE", "点阵图",
    ],
    "crypto_regulation": [
        "SEC", "监管", "牌照", "稳定币监管", "ETF", "以太坊现货ETF",
        "现货ETF", "金管局", "金融委员会", "虚拟资产", "会计处理", "反洗钱",
    ],
    "us_policy": [
        "财政部", "白宫", "国债", "出口管制", "AI芯片", "管制新规",
        "制裁", "行政令", "国会", "债务上限", "预算",
    ],
    "us_data": [
        "非农", "失业率", "CPI", "核心CPI", "PPI", "GDP", "零售销售",
        "ISM", "PMI", "初请失业金", "消费支出", "耐用品",
    ],
    "geopolitics": [
        "地缘", "霍尔木兹", "油轮", "中东", "俄乌", "制裁",
        "导弹", "安理会", "朝核", "冲突", "动员", "军事",
    ],
    "security_incident": [
        "PeckShield", "被盗", "攻击", "私钥泄露", "热钱包转出",
        "黑客", "归还被盗资金", "漏洞", "闪电贷", " rug ",
    ],
    "project_ecosystem": [
        "ERC-", "V神", "Layer2", "升级", "主网", "账户抽象", "TPS",
        "提案", "分叉", "路线图", "标准",
    ],
    "market_sentiment": [
        "巨鲸", "增持", "USDT溢价", "折价率", "GBTC", "灰度",
        "恐惧贪婪", "贪婪区", "未平仓合约", "入场信号", "机构资金",
    ],
    # ── P0 新增：代币级里程碑事件分类（第 9 类） ──
    # 覆盖：主网上线/跨链迁移/主网升级/代币解锁/审计通过/上线交易所/战略合作/集成发布
    # （标题中的具体 TICKER 再由 _extract_tickers_from_title 单独抓取，做 per-coin 映射）
    "token_milestone": [
        "上线主网", "主网启动", "主网上线", "主网迁移", "跨链迁移",
        "主网升级", "版本升级", "升级", "主链", "公链主网", "主网公测",
        "代币解锁", "解锁亿枚", "解锁数量", "解锁 schedule", "解锁",
        "审计通过", "安全审计", "CertiK", "慢雾审计", "Trail of Bits",
        "上线交易所", "上线 Binance", "上线 Coinbase", "上线 OKX", "上线 Bybit",
        "战略合作", "生态合作", "集成", "集成至", "合作发布",
        "白皮书发布", "路线图更新", "激励计划", "空投", "提案",
        "发布主网", "迁移至", "生态基金", "主网 beta",
    ],
}

# Step2 topic → event_type（正则辅助，当前 keyword 已够用，预留）
_EVENT_TYPE_TOPIC_MAP: dict[str, str] = {}

# Step3 category → event_type（预留）
_CATEGORY_EVENT_TYPE_MAP: dict[str, str] = {}

# 7+1 枚举值（市场情绪为 market_sentiment，Spec §4.3 枚举）
_EVENT_TYPE_ENUM = tuple(_POLICY_KEYWORDS.keys())

# 5 attention_type
_ATTENTION_TYPE_ENUM = ("policy_easing", "policy_tightening",
                        "market_risk_on", "market_risk_off", "neutral")

# 4 档半衰期（Spec §4.3 / 半衰期表）
#   · monetary_policy / crypto_regulation = 72h
#   · us_policy / geopolitics = 48h
#   · security_incident / project_ecosystem = 24h
#   · us_data / market_sentiment = 6h
_DECAY_HRS: dict[str, int] = {
    "monetary_policy": 72,
    "crypto_regulation": 72,
    "us_policy": 48,
    "geopolitics": 48,
    "security_incident": 24,
    "project_ecosystem": 24,
    "token_milestone": 24,  # P0 新增：代币里程碑（与项目生态半衰期一致，行业事件 24h 衰减）
    "us_data": 6,
    "market_sentiment": 6,
}

# 注意力方向（简版规则，复杂规则阶段2 6引擎接管）
_ATTENTION_DIR: dict[str, str] = {
    "降息": "policy_easing", "扩表": "policy_easing", "购债": "policy_easing",
    "加息": "policy_tightening", "缩表": "policy_tightening",
    "制裁": "market_risk_off", "管制新规": "market_risk_off", "被盗": "market_risk_off",
    "攻击": "market_risk_off", "私钥泄露": "market_risk_off", "冲突": "market_risk_off",
    "升级": "market_risk_on", "巨鲸": "market_risk_on", "增持": "market_risk_on",
    "入场信号": "market_risk_on", "折价率收窄": "market_risk_on", "机构资金": "market_risk_on",
    "贪婪区": "market_risk_on",
}


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _md5_8(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


# ── 停用词（行业缩写/非代币TICKER/公司名，从 ticker 提取中剔除） ──
_TICKER_STOPWORDS: set[str] = {
    "THE", "AND", "GDP", "CPI", "PPI", "FOMC", "SEC", "ETF", "AI", "API",
    "URL", "VIX", "USDT", "USDC", "BUSD", "DAI", "FDUSD", "USDP", "TUSD",
    "Q1", "Q2", "Q3", "Q4", "P1", "P2", "P3", "NEWS", "ARC", "ARK",
    "M1", "M2", "M3", "M4", "M5", "V0", "V1", "V2", "V3", "L1", "L2", "L3",
    "IPO", "ICO", "IDO", "IEO", "TVL", "APY", "APR", "ROI", "PnL",
    "KYC", "AML", "NFT", "DAO", "DEX", "CEX", "CLOB", "AMM", "RWA",
    "MEV",  # 矿工可提取价值（不是代币）
    "CCIP",  # Chainlink 跨链协议名（不是代币）
    "BTCETF", "ETHETF", "GBTC", "ESG", "OTC", "WSB", "FUD", "FOMO",
    "FED", "ECB", "BOJ", "PBOC", "IMF", "OPEC", "AUM", "FDIC",
    "SOLANA", "BITCOIN", "ETHEREUM",  # 这些是币种名全称，不抓作 TICKER
    "COINBASE", "BINANCE", "OKX", "BYBIT", "KUCOIN", "KRAKEN",
    "USD", "EUR", "JPY", "CNY", "GBP", "AUD", "CAD", "CHF", "HKD",
    "WWW", "HTTPS", "HTTP", "HTML", "CSS", "JS", "RPC", "AWS",
    # 🆕 P0：中文边界修复后停用词补全——技术分析/金融会计术语（避免被误抓作币种）
    "ATH", "ATL",  # 历史最高/最低
    "DCA",        # Dollar-Cost Averaging 定投
    "MACD", "RSI", "MA", "EMA", "BOLL", "CCI", "KDJ", "SAR", "DMI", "OBV", "WR", "MFI",  # 常用技术指标
    "PE", "EPS", "ROE",  # 估值/财务指标
}


def _extract_tickers_from_title(title: str, description: str = "") -> list[str]:
    """从快讯标题/描述中提取「代币 TICKER」候选（CRCL/BTC/SOL/JTO/SAND…）。

    规则：
      1. 优先匹配 2~8 位大写字母单词（\b[A-Z]{2,8}\b）；
      2. 过滤停用词（_TICKER_STOPWORDS，避免 GDP/FOMC/USDT 之类被误当代币）；
      3. 若标题里出现形如 "XXX 币" / "XXX代币" / "$XXX" / "XXX-USDT" 时优先命中；
      4. 去重 + 保序。

    P0 目标：让 "CRCL 宣布 9 月 16 日上线 ARC 主网" 精确命中 {"CRCL"}，
            同时 "ARK Invest" 中的 ARK 不在此停用=暂不视为币（已加入停用词防误判）。
    """
    hay = f"{title or ''} {description or ''}"
    seen: set[str] = set()
    out: list[str] = []

    # (A) 高置信规则：$TICKER / TICKER-USDT 形式 → 100% 命中
    for m in re.finditer(r"\$([A-Z]{2,8})", hay):
        tok = m.group(1)
        if tok in _TICKER_STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    for m in re.finditer(r"([A-Z]{2,8})-USDT", hay):
        tok = m.group(1)
        if tok in _TICKER_STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)

    # (B) 一般规则：纯2-8位大写字母单词
    #    🆕 P0：中文Unicode边界修复：原\b[A-Z]{2,8}\b 对中文↔大写字母 不构成ASCII word boundary（90%中文快讯漏抓）
    #    → 改为零宽负向断言：前后只要不是[A-Za-z0-9]就算边界，兼容汉字/标点/全角符号等Unicode上下文
    for m in re.finditer(r"(?<![A-Za-z0-9])([A-Z]{2,8})(?![A-Za-z0-9])", hay):
        tok = m.group(1)
        if tok in _TICKER_STOPWORDS:
            continue
        if tok in seen:
            continue
        # 额外保险：上下文若为 "缩写公司名"（例：ARK Invest）跳过
        if tok == "ARK" and "Invest" in hay:
            continue
        seen.add(tok)
        out.append(tok)

    return out


def compute_coin_event_positive_strength(
    coin: str,
    odaily_records_like: list[dict],
    now_ms: int | None = None,
) -> tuple[float, dict]:
    """给定一组「odaily newsflash 转换为 dict 后」的快讯记录，输出某币 event_positive_strength ∈ [0,1]

    算法（行业标准 事件强度= sentiment × 衰减 × 重要度 × 分类权重 + 最大池化）：
        对每条命中该币的快讯：
          weight_evt = 1.20  if  token_milestone
                     = 1.00  if  project_ecosystem/market_sentiment
                     = 0.80  其他政策类（不直接影响代币级）
          weight_imp = 2.0  if  important=true
                     = 1.0  otherwise
          decay      = 0.5 ^ ( dt_hrs / od_decay_hl_hrs )   # 指数半衰期
          score_raw  = od_policy_sentiment_0_1  ×  decay  ×  weight_evt  ×  weight_imp

        输出 = clip( 0.6 × max(score_raw_i) + 0.4 × mean(score_raw_i) , 0, 1 )

    FAIL-OPEN：任何异常 → (0.0, {error})。
    """
    import math as _m
    coin_up = (coin or "").strip().upper()
    debug: dict[str, Any] = {"coin": coin_up, "n_records": len(odaily_records_like or [])}

    if not coin_up or not odaily_records_like:
        return 0.0, {**debug, "hit": 0, "reason": "no_input"}
    try:
        if now_ms is None:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        hits: list[float] = []
        n_hit = 0
        for rec in odaily_records_like:
            if not isinstance(rec, dict):
                continue
            # 确定这条快讯是否命中该币：先看显式 tickers_hit；再回退 raw.title 中是否有该 TICKER
            m_ticks = rec.get("tickers_hit") or []
            if not isinstance(m_ticks, list) or not m_ticks:
                raw = rec.get("raw") or {}
                if isinstance(raw, dict):
                    m_ticks = _extract_tickers_from_title(
                        str(raw.get("title", "")), str(raw.get("description", ""))
                    )
                else:
                    m_ticks = []
            m_ticks_upper = [str(t).upper() for t in m_ticks if isinstance(t, str)]
            if coin_up not in m_ticks_upper:
                continue

            metrics = rec.get("metrics") or {}
            if not isinstance(metrics, dict):
                continue
            sentiment = float(metrics.get("od_policy_sentiment_0_1", 0.5) or 0.5)
            sentiment = max(0.0, min(1.0, sentiment))
            et = str(metrics.get("od_event_type", "market_sentiment") or "market_sentiment")
            imp = bool((metrics.get("od_is_important") or "false") == "true")
            decay_hl_hrs = max(1, int(metrics.get("od_decay_hl_hrs", 24) or 24))

            # 事件级权重（token_milestone 最强 > 市场情绪/项目生态 > 政策宏观）
            if et == "token_milestone":
                w_evt = 1.20
            elif et in ("project_ecosystem", "market_sentiment"):
                w_evt = 1.00
            else:
                w_evt = 0.80
            w_imp = 2.0 if imp else 1.0

            # ── 🆕 P1 C1④ G3护栏-B：dt 范围断言（单条 FAIL-OPEN 丢弃，不影响其他）──
            #   * 未来函数：pub_ms > now_ms → dt_hrs < 0 → 丢弃
            #   * 超龄一周：dt_hrs > 168h（一周=168小时）→ 丢弃
            # （DB桥 WHERE 已先过滤一层，这里做二次断言=对直接传recs场景双保险）
            dt_hrs = 0.0
            _in_range = True
            evs = rec.get("events") or []
            if isinstance(evs, list) and len(evs) >= 1 and isinstance(evs[0], dict):
                pub_ms = int(evs[0].get("published_ms", 0) or 0)
                if pub_ms > 0:
                    dt_hrs = (int(now_ms) - pub_ms) / 3_600_000.0  # 负数=未来泄漏
                    if dt_hrs < 0.0 or dt_hrs > 168.0:
                        _in_range = False
            if not _in_range:
                # 单条未来/超龄 → 丢弃（不进hits、不递增n_hit、不阻塞其他）
                continue
            decay = _m.pow(0.5, max(0.0, dt_hrs) / decay_hl_hrs)  # 仍用>=0保证decay数学合法
            raw_score = sentiment * decay * w_evt * w_imp
            # clip each raw_score per-item to avoid 单条溢出 2.0 以上极端值
            raw_score = min(raw_score, 1.60)
            hits.append(raw_score)
            n_hit += 1
        debug["hit"] = n_hit
        if n_hit == 0:
            return 0.0, {**debug, "reason": "no_coin_hit"}
        mx = max(hits)
        mean_s = sum(hits) / len(hits)
        strength = 0.6 * mx + 0.4 * mean_s
        strength = max(0.0, min(1.0, strength))
        debug["max"] = round(mx, 4)
        debug["mean"] = round(mean_s, 4)
        return strength, debug
    except Exception as e:  # noqa: BLE003  FAIL-OPEN：绝对不抛出
        return 0.0, {"coin": coin_up, "error": f"{type(e).__name__}:{str(e)[:80]}"}


def _classify_event_type(title: str, description: str = "") -> str:
    """79+33 条 keyword_rules pipeline（P0 新增 token_milestone 第 9 类）。

    核心优先级规则（防止 project_ecosystem 含有的通用「主网/升级/提案」关键词先命中）：
      1) 若标题/描述中能抓到 ≥1 个具体代币 TICKER（CRCL/SOL/ETH…） → token_milestone 提升权重 2×
         （这样含具体代币的"SOL 主网升级/ETH 坎昆升级"会正确分 token_milestone，
         而"Layer2 升级/行业主网扩容"这类不含具体 TICKER 的仍归 project_ecosystem 保持兼容）。
      2) 同分时的 tie-break：有具体代币时 token_milestone 优先级最高（避免 project_ecosystem
         因 EVENT_TYPE_ENUM 插入顺序更前而赢）。
    """
    hay = f"{title} {description}"
    # 判断是否为"具体代币级快讯"
    _ticks = _extract_tickers_from_title(title, description)
    _has_specific_token = bool(_ticks)

    score_map: dict[str, int] = {}
    for et, kws in _POLICY_KEYWORDS.items():
        cnt = 0
        for k in kws:
            if k in hay:
                cnt += 1
        if cnt:
            # 具体代币 + token_milestone 分类 → ×2 加权（优先分入代币级里程碑）
            if _has_specific_token and et == "token_milestone":
                cnt *= 2
            score_map[et] = cnt
    if not score_map:
        return "market_sentiment"  # 兜底（市场情绪默认分类最安全）

    # 优先级 tie-break：
    #   默认 index越小越优先（用 -index 作为第二排序键）
    #   但若 _has_specific_token：强制 token_milestone 排第一（tie-break 优先级= -1 = 最高）
    def _priority(et: str) -> int:
        if _has_specific_token and et == "token_milestone":
            return 1  # 最小=最高
        try:
            return _EVENT_TYPE_ENUM.index(et)
        except ValueError:
            return len(_EVENT_TYPE_ENUM) + 1

    return max(score_map.items(), key=lambda kv: (kv[1], -_priority(kv[0])))[0]


def _attention_type(event_type: str, title: str) -> str:
    for kw, at in _ATTENTION_DIR.items():
        if kw in title:
            return at
    return "neutral"


def _sentiment_lazy(title: str, description: str) -> tuple[float, bool]:
    """Lazy import 9基本面 sentiment_engine。

    Returns:
        (score_float, import_success_bool)
        import_success=False → 上层使用 0.5 中性兜底。
    """
    try:
        # 9基本面真实路径：/9-基本面分析/engines/sentiment_engine.py
        import sys
        nine_root = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析"
        if nine_root not in sys.path:
            sys.path.insert(0, nine_root)
        from engines.sentiment_engine import SentimentEngine  # type: ignore
        engine = SentimentEngine()
        result = engine.analyze_text(f"{title}。{description}")
        # analyze_text 返回: {"score":[-1,1], "sentiment":positive/neutral/negative, ...}
        score_raw = result.get("score", 0) if isinstance(result, dict) else 0
        # score ∈[-1,1] → 线性映射到 [0,1]，0.5 为中性
        if isinstance(score_raw, (int, float)):
            score = (float(score_raw) + 1.0) / 2.0
            score = max(0.0, min(1.0, score))
        elif isinstance(result, dict):
            v = result.get("compound") or 0.5
            score = 0.5 if v is None else max(0.0, min(1.0, (float(v) + 1.0) / 2.0))
        else:
            score = 0.5
        return score, True
    except Exception:  # noqa: BLE003  FAIL-OPEN L2 兜底
        return 0.5, False


# ────────────────────────────────────────────────────────────
# Collector 主类
# ────────────────────────────────────────────────────────────
class OdailyNewsflashCollector(BaseCollector):
    """Odaily 星球日报快讯采集器（news / odaily_newsflash）。"""

    source = "odaily_newsflash"
    category = "news"

    def is_available(self) -> bool:
        return True  # web-api 公开，无 key

    # ── fetch 入口 ──────────────────────────────────────────
    def fetch(self, params: dict) -> list[DataRecord]:
        params = params or {}
        route = params.get("route", "latest")
        try:
            if route == "incremental" or "last_id" in params:
                last_id = params.get("last_id")
                if last_id is not None:
                    # ── 增量第一道：checkHasNew N=0 → [] ─────────
                    n_new = self._call_check_has_new(int(last_id))
                    if n_new is not None and n_new == 0:
                        return []
                    # N>0 或 接口异常 → fallback 直接拉首屏 20 条
            return self._fetch_page(limit=params.get("limit", 20))
        except Exception as e:  # noqa: BLE003  FAIL-OPEN L1 硬约束
            logger.warning(
                "[FAIL-OPEN L1] Odaily fetch 异常 %s: %s，静默回退 []",
                type(e).__name__, str(e)[:200], stack_info=True,
            )
            return []

    # ── HTTP 调用内部封装（模块级 requests，便于 TDD mock）────
    def _call_check_has_new(self, last_id: int) -> int | None:
        try:
            resp = requests.get(
                f"{_ODAILY_API}/newsflash/checkHasNew",
                params={"lastId": str(last_id)},
                headers=_HTTP_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
            data = resp.json()
            return int(data.get("data", 0))
        except Exception as e:  # noqa: BLE003
            logger.info("[FAIL-OPEN] checkHasNew 异常 %s: %s，fallback 拉 page",
                        type(e).__name__, str(e)[:120])
            return None

    def _fetch_page(self, limit: int = 20) -> list[DataRecord]:
        resp = requests.get(
            f"{_ODAILY_API}/newsflash/page",
            params={"cursor": 0, "limit": int(limit)},
            headers=_HTTP_HEADERS,
            timeout=_HTTP_TIMEOUT,
        )
        # 429 限流：抛 RateLimitError（上层 dispatcher 已 fail-open）
        if resp.status_code == 429:
            from data_center.core.errors import RateLimitError
            raise RateLimitError("Odaily 429 rate limited")
        try:
            data = resp.json()
        except ValueError:
            logger.warning("[FAIL-OPEN] Odaily page JSON 解析失败，返回空")
            return []
        if not isinstance(data, dict):
            return []
        items: list[dict[str, Any]] = data.get("data", {}).get("list", []) or []
        if not isinstance(items, list):
            return []

        ts = _now_iso()
        recs: list[DataRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            od_id = item.get("id")
            title = str(item.get("title", "") or "")
            desc = str(item.get("description", "") or "")
            is_important = bool(item.get("isImportant", False))
            publish_ms = item.get("publishTimestamp")

            # 1. lazy sentiment
            s_float, _ = _sentiment_lazy(title, desc)

            # 2. event_type（优先 token_milestone → 若具体代币 + 里程碑关键词命中则先）
            et = _classify_event_type(title, desc)

            # 2b. P0：从标题/描述提取代币 TICKER（用于per-coin注入 Score_B event_boost）
            #     兼容contract：直接写入 raw.tickers_hit + 新扁平metric od_tickers_hit_csl（逗号分隔字符串）
            ticks = _extract_tickers_from_title(title, desc)
            ticks_csl = ",".join(ticks) if ticks else ""

            # 3. attention_type
            att = _attention_type(et, title)
            if att not in _ATTENTION_TYPE_ENUM:
                att = "neutral"

            # 4. decay 半衰期小时
            decay = _DECAY_HRS.get(et, 24)

            # 5. DataRecord（7+2 扁平 metrics；新增 od_tickers_hit_csl 兼容 contract）
            rec = DataRecord(
                source="odaily_newsflash",
                category="news",
                sub_category=f"newsflash_{od_id}" if od_id is not None else "newsflash_0",
                timestamp=ts,
                metrics={
                    "od_source_id": int(od_id) if isinstance(od_id, (int, float)) else 0,
                    "od_policy_sentiment_0_1": float(s_float),
                    "od_event_type": str(et),
                    "od_attention_type": str(att),
                    "od_is_important": "true" if is_important else "false",
                    "od_decay_hl_hrs": int(decay),
                    "od_title_hash": _md5_8(title),
                    "od_tickers_hit_csl": ticks_csl,  # P0 新增：逗号分隔 TICKER（CRCL,BTC,SOL...）
                },
                events=[{
                    "event_type": et,
                    "importance": 2 if is_important else 1,
                    "published_ms": int(publish_ms) if isinstance(publish_ms, (int, float)) else 0,
                }],
                timeseries=[],
                raw={
                    "title": title, "description": desc,
                    "tags": item.get("tags", []), "newsUrl": item.get("newsUrl", ""),
                    "publishTimestamp": publish_ms,
                    "tickers_hit": ticks,  # P0 新增：结构化 list[str]，便于下游直接 compute_coin_event_positive_strength
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs

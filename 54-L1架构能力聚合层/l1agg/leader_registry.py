"""跨资产龙头注册表 —— 分类口径与 40 层 `asset_classes.py` 完全统一（SSoT = 40）。

设计边界：
  - **分类不另立**：`ASSET_CLASSES` / `G1_ANCHORS` / `G0_MACRO` 直接读 40 层，
    本模块只补「该龙头在当前 DAL 里由哪条序列承载」这一层绑定；
  - **缺失诚实登记**：无数据的标的进 `UNBOUND`，附 `reason`，任何下游（align /
    相关性）遇到它必须返回 `not_collected`，禁止静默空序列；
  - **代理可标注**：如 CL 用 FRED `DCOILWTICO`、DXY 用 `DTWEXBGS`、
    US500 用 FRED `SP500`，全部标 `proxy=True`，输出时必须带出。

美股口径（用户 2026-11-14 确认）：指数以标普/纳指/道指为主，个股只要几个龙头。
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_MODULE_ROOT)
_FORTY_PATH = os.path.join(_PROJECT_ROOT, "40-周期神经网络系统", "asset_classes.py")


def _load_forty() -> Tuple[Dict, Dict, Dict]:
    """加载 40 层分类（FAIL-OPEN：缺失时返回空字典，由调用方判定）。"""
    if not os.path.isfile(_FORTY_PATH):
        return {}, {}, {}
    spec = importlib.util.spec_from_file_location("_db40_asset_classes", _FORTY_PATH)
    if spec is None or spec.loader is None:
        return {}, {}, {}
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return {}, {}, {}
    return (
        dict(getattr(mod, "ASSET_CLASSES", {}) or {}),
        dict(getattr(mod, "G1_ANCHORS", {}) or {}),
        dict(getattr(mod, "G0_MACRO", {}) or {}),
    )


ASSET_CLASSES, G1_ANCHORS, G0_MACRO = _load_forty()
# 40 的 10 个可交易/代理大类 + G0 宏观门控（增长率/通胀类序列归入 macro）
CLASS_IDS: Tuple[str, ...] = tuple(ASSET_CLASSES) + ("macro",)


@dataclass(frozen=True)
class Binding:
    """龙头 → DAL 序列绑定。"""

    symbol: str
    asset_class: str
    label: str
    sub_category: str
    metric_name: str
    unit: str = "USD"
    freq: str = "daily"
    proxy: bool = False
    note: str = ""
    # 代币化标的（OKX *-USDT-SWAP，非证券本体）：proxy 必为 True
    tokenized: bool = False

    @property
    def series_id(self) -> str:
        return f"{self.sub_category}::{self.metric_name}"


def _b(
    symbol,
    asset_class,
    label,
    sub,
    metric,
    unit="USD",
    freq="daily",
    proxy=False,
    note="",
    tokenized=False,
):
    return Binding(symbol, asset_class, label, sub, metric, unit, freq, proxy, note, tokenized)


# ── 已绑定：当前 DAL 中确有长历史的龙头（2026-11-14 核对 ≥120 天）──────────
BINDINGS: Dict[str, Binding] = {
    # crypto（G1 锚 + 类内 L2）
    "BTC": _b("BTC", "crypto", "比特币", "BTC", "close_usd", note="OKX 日收盘，1,094 点/3 年"),
    "ETH": _b("ETH", "crypto", "以太坊", "ETH", "close_usd", note="1,094 点/3 年"),
    "SOL": _b("SOL", "crypto", "Solana", "SOL", "close_usd", note="1,094 点/3 年"),
    # precious_metal
    "XAU": _b("XAU", "precious_metal", "黄金", "XAU", "close_usd", note="1,094 点/3 年"),
    # energy（G1 锚 CL 用 FRED WTI 代理）
    "CL": _b(
        "CL", "energy", "WTI 原油", "DCOILWTICO", "value", proxy=True, note="FRED 日频，1986 起"
    ),
    # us_index（标普 / 纳指 / 道指）
    "US500": _b(
        "US500",
        "us_index",
        "标普500",
        "SP500",
        "value",
        unit="点",
        proxy=True,
        note="FRED SP500，2016 起 2,521 点",
    ),
    "US100": _b(
        "US100",
        "us_index",
        "纳斯达克综合",
        "NASDAQCOM",
        "value",
        unit="点",
        proxy=True,
        note="FRED NASDAQCOM，1971 起",
    ),
    "DJIA": _b(
        "DJIA",
        "us_index",
        "道琼斯工业平均",
        "DJIA",
        "close_usd",
        proxy=True,
        note="DIA（道指 ETF）代理；Nasdaq API 无 ^DJI 历史，Yahoo 对云端 IP 429、FRED DJIA 停更",
    ),
    # us_stock（用户口径：只要几个龙头；Nasdaq 日线 752 点/3 年）
    "NVDA": _b("NVDA", "us_stock", "英伟达", "NVDA", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "AAPL": _b("AAPL", "us_stock", "苹果", "AAPL", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "MSFT": _b("MSFT", "us_stock", "微软", "MSFT", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "TSLA": _b("TSLA", "us_stock", "特斯拉", "TSLA", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "AMZN": _b("AMZN", "us_stock", "亚马逊", "AMZN", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "GOOGL": _b("GOOGL", "us_stock", "谷歌", "GOOGL", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "META": _b("META", "us_stock", "Meta", "META", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    # us_stock：OKX 代币化美股永续（历史短，<250 天禁止点亮；不得跨源择优砍掉 Nasdaq 长历史）
    "AMD": _b(
        "AMD",
        "us_stock",
        "AMD",
        "AMD",
        "close_usd",
        proxy=True,
        tokenized=True,
        note="OKX AMD-USDT-SWAP，250 点（2026-03-10 起，恰达 250 门槛）",
    ),
    "GEV": _b(
        "GEV",
        "us_stock",
        "GE Vernova",
        "GEV",
        "close_usd",
        proxy=True,
        tokenized=True,
        note="OKX GEV-USDT-SWAP，179 点（2026-05-20 起）→ history_lt_250，禁止点亮",
    ),
    "SPCX": _b(
        "SPCX",
        "us_stock",
        "SpaceX 代币化标的",
        "SPCX",
        "close_usd",
        proxy=True,
        tokenized=True,
        note="OKX SPCX-USDT-SWAP，193 点（2026-05-06 起）→ history_lt_250，禁止点亮",
    ),
    "SKHYNIX": _b(
        "SKHYNIX",
        "us_stock",
        "SK 海力士",
        "SKHYNIX",
        "close_usd",
        proxy=True,
        tokenized=True,
        note="OKX SKHYNIX-USDT-SWAP，约 158 点（listTime 2026-06-10）→ history_lt_250，禁止点亮",
    ),
    # us_etf
    "SPY": _b("SPY", "us_etf", "标普500 ETF", "SPY", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    "QQQ": _b("QQQ", "us_etf", "纳指100 ETF", "QQQ", "close_usd", note="Nasdaq 日线，752 点/3 年"),
    # precious_metal / industrial_metal（OKX 永续）
    "XAG": _b(
        "XAG",
        "precious_metal",
        "白银",
        "XAG",
        "close_usd",
        note="OKX XAG-USDT-SWAP，290 点（2026-01 起）",
    ),
    "XCU": _b(
        "XCU",
        "industrial_metal",
        "铜",
        "XCU",
        "close_usd",
        note="OKX XCU-USDT-SWAP，255 点（2026-03 起）",
    ),
    # energy（FRED 现货；CL 已在上方用 WTI）
    "BZ": _b(
        "BZ",
        "energy",
        "布伦特原油",
        "DCOILBRENTEU",
        "value",
        proxy=True,
        note="FRED 布伦特现货，1987 起",
    ),
    "NG": _b(
        "NG",
        "energy",
        "Henry Hub 天然气",
        "DHHNGSP",
        "value",
        proxy=True,
        note="FRED 天然气现货，1997 起",
    ),
    # fx（宏观序列代理）
    "DXY": _b(
        "DXY",
        "fx",
        "美元指数",
        "DTWEXBGS",
        "value",
        unit="指数",
        proxy=True,
        note="FRED 广义美元指数，2006 起",
    ),
    # rates_credit（G1 锚 TLT 用 10Y 收益率代理；信用用 HY OAS）
    "TLT": _b(
        "TLT",
        "rates_credit",
        "美债10年收益率",
        "DGS10",
        "value",
        unit="%",
        proxy=True,
        note="FRED DGS10，1962 起 16,206 点",
    ),
    # G0 门控序列（不可交易，但相关性研究必需）
    "T10Y2Y": _b(
        "T10Y2Y", "rates_credit", "10Y-2Y 利差", "T10Y2Y", "value", unit="%", note="FRED 日频"
    ),
    "HY_OAS": _b(
        "HY_OAS",
        "rates_credit",
        "高收益债利差",
        "BAMLH0A0HYM2",
        "value",
        unit="%",
        note="FRED 日频，2023 起",
    ),
    "VIX": _b(
        "VIX", "macro", "VIX 波动率", "VIXCLS", "value", unit="指数", note="FRED 日频，1990 起"
    ),
    "CPI": _b(
        "CPI", "macro", "美国 CPI", "CPIAUCSL", "value", unit="指数", note="FRED 月频，1947 起"
    ),
    "INDPRO": _b(
        "INDPRO", "macro", "美国工业生产", "INDPRO", "value", unit="指数", note="FRED 月频，1919 起"
    ),
}


# ── 诚实缺失登记：40 层有该类/该龙头，但 DAL 无足够历史序列 ──────────────
UNBOUND: Dict[str, str] = {
    # apac_index：OKX JP225-USDT-SWAP 2026-09 才上线，仅 67 天，达不到 250 天门禁
    "JP225": "历史不足（OKX 永续 2026-09 上线，67 天 < 250 天；待继续累积或换源）",
    # us_stock 代币龙头：40 已定义，DAL 尚未回填
    "COIN": "未采集（OKX COIN-USDT-SWAP 待回填）",
    "MSTR": "未采集（OKX MSTR-USDT-SWAP 待回填）",
}


# ── 默认资产池（「数据与图表」首屏 12 个，用户 2026-11-15 确认，五类覆盖）──────
# 加密 2 / 避险 2 / 大宗 3 / 美股 4（3 指数 + NVDA）/ 情绪 1；与 asset_pool.yaml
# pools.default 同口径，前端零硬编码（visual_overview 取 [:12]）。
DEFAULT_POOL: Tuple[str, ...] = (
    "BTC",
    "ETH",
    "XAU",
    "XAG",
    "CL",
    "BZ",
    "NG",
    "US500",
    "US100",
    "DJIA",
    "NVDA",
    "VIX",
)

# ── 扩展池：按类别展开时懒加载（ADR-V6）；含 OKX 代币化美股（短历史，禁止点亮）──
EXTENDED_POOL: Tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AMD",
    "GEV",
    "SPCX",
    "SKHYNIX",
    "SPY",
    "QQQ",
    "XCU",
    "T10Y2Y",
    "US10Y",
    "TLT",
    "DXY",
)

# 展示层五类视图 → 40 层大类（分类仍以 40 为 SSoT，此处只做分组）
VIEW_CLASSES: Dict[str, Tuple[str, ...]] = {
    "加密": ("crypto",),
    "避险": ("precious_metal",),
    "大宗": ("energy", "industrial_metal"),
    "美股": ("us_index", "us_stock", "us_etf"),
    "情绪": ("macro", "rates_credit"),
}


def default_pool() -> List[str]:
    """返回默认资产池（新列表，调用方可自由增删）。"""
    return list(DEFAULT_POOL)


def extended_pool() -> List[str]:
    """返回扩展池（新列表）。"""
    return list(EXTENDED_POOL)


def view_of(symbol: str) -> Optional[str]:
    """标的 → 展示层五类视图（未知返回 None）。"""
    cls = class_of(symbol)
    if cls is None:
        return None
    for view, classes in VIEW_CLASSES.items():
        if cls in classes:
            return view
    return None


def pool_by_view(pool: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """按五类视图分组默认池（保持 DEFAULT_POOL 顺序；未知类不进分组）。"""
    members = default_pool() if pool is None else list(pool)
    out: Dict[str, List[str]] = {view: [] for view in VIEW_CLASSES}
    for sym in members:
        view = view_of(sym)
        if view is not None:
            out[view].append(sym)
    return {view: syms for view, syms in out.items() if syms}


def resolve(symbol: str) -> Optional[Binding]:
    """龙头符号 → 绑定；未绑定返回 None（用 `is_bound` 区分缺失/未知）。"""
    return BINDINGS.get(str(symbol).strip().upper())


def is_bound(symbol: str) -> bool:
    return str(symbol).strip().upper() in BINDINGS


def unbound_reason(symbol: str) -> Optional[str]:
    return UNBOUND.get(str(symbol).strip().upper())


def class_of(symbol: str) -> Optional[str]:
    """标的所属 40 层大类（绑定优先，其次 40 的 SYMBOL_CLASS 反查）。"""
    sym = str(symbol).strip().upper()
    b = BINDINGS.get(sym)
    if b is not None:
        return b.asset_class
    for cls, cfg in ASSET_CLASSES.items():
        if sym in (cfg.get("members") or []):
            return cls
    a = G1_ANCHORS.get(sym)
    return a.get("class") if isinstance(a, dict) else None


def leaders_by_class() -> Dict[str, List[str]]:
    """按 40 层分类罗列龙头（含已绑定与未绑定），保持 40 的定义顺序。"""
    out: Dict[str, List[str]] = {cls: [] for cls in CLASS_IDS}
    for cls, cfg in ASSET_CLASSES.items():
        leader = cfg.get("leader")
        if leader:
            out[cls].append(leader)
    for sym in list(BINDINGS) + list(UNBOUND):
        cls = class_of(sym)
        if cls is not None and sym not in out.setdefault(cls, []):
            out[cls].append(sym)
    return out


def coverage(db_path: str, min_days: int = 250) -> List[Dict[str, object]]:
    """逐龙头核对 DAL 实际历史深度（只读，不写库）。

    状态机（SPEC §2.3.3）：0 行 → missing；0 < n < min_days → partial 且带
    degraded_reason（n<250 时固定 history_lt_250，禁止点亮）；n ≥ min_days → available。

    Returns: [{symbol, class, status, degraded_reason, sample_n, span,
               series_id, proxy, tokenized, note}]
    """
    rows: List[Dict[str, object]] = []
    conn = None
    if os.path.isfile(db_path):
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        for sym, b in BINDINGS.items():
            rec: Dict[str, object] = {
                "symbol": sym,
                "class": b.asset_class,
                "label": b.label,
                "series_id": b.series_id,
                "proxy": b.proxy,
                "tokenized": b.tokenized,
                "note": b.note,
                "sample_n": 0,
                "span": "",
                "status": "missing",
                "degraded_reason": "",
            }
            if conn is not None:
                sql = (
                    "SELECT COUNT(DISTINCT date(timestamp,'unixepoch')), "
                    "MIN(date(timestamp,'unixepoch')), MAX(date(timestamp,'unixepoch')) "
                    "FROM mm_metrics WHERE sub_category = ? AND metric_name = ?"
                )
                n, lo, hi = conn.execute(sql, (b.sub_category, b.metric_name)).fetchone()
                n = int(n or 0)
                rec["sample_n"] = n
                rec["span"] = f"{lo}~{hi}" if lo else ""
                if n == 0:
                    rec["status"] = "missing"
                elif n < min_days:
                    rec["status"] = "partial"
                    rec["degraded_reason"] = "history_lt_250" if n < 250 else "history_lt_min"
                else:
                    rec["status"] = "available"
            rows.append(rec)
        for sym, reason in UNBOUND.items():
            rows.append(
                {
                    "symbol": sym,
                    "class": class_of(sym),
                    "label": sym,
                    "series_id": "",
                    "proxy": False,
                    "tokenized": False,
                    "note": reason,
                    "sample_n": 0,
                    "span": "",
                    "status": "not_collected",
                    "degraded_reason": "not_collected",
                }
            )
    finally:
        if conn is not None:
            conn.close()
    return rows


def coverage_summary(db_path: str, min_days: int = 250) -> Dict[str, object]:
    """按类汇总 coverage，供文档体检与 L1 能力声明使用。"""
    rows = coverage(db_path, min_days)
    by_class: Dict[str, Dict[str, int]] = {}
    for r in rows:
        cls = str(r["class"] or "unknown")
        slot = by_class.setdefault(cls, {"available": 0, "missing": 0, "not_collected": 0})
        slot[str(r["status"])] = slot.get(str(r["status"]), 0) + 1
    return {
        "min_days": min_days,
        "classification_source": _FORTY_PATH if ASSET_CLASSES else "",
        "class_count": len(CLASS_IDS),
        "by_class": by_class,
        "available": sum(1 for r in rows if r["status"] == "available"),
        "not_collected": sum(1 for r in rows if r["status"] == "not_collected"),
        "as_of": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        "rows": rows,
    }

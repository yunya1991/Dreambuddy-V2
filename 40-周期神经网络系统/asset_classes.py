#!/usr/bin/env python3
"""40 周期神经网络 · 资产类型与龙头注册表（v1.0，2026-11-09）。

三层拓扑：
  G0 全球宏观层（不可交易，仅门控）
  G1 大类龙头层（6 个可交易锚，参与跨类 R 矩阵）
  G2 类内层级（类内轮动/广度）

三项已确认决策（用户 2026-11-09 确认，默认方案）：
  GOLD_DUAL_TRACK：交易/传导用 XAU-USDT-SWAP；XAUT/USDT spot 仅作宏观背离参考
  EQUITY_ALIGNMENT = "continuous_24h"：股票类永续按 OKX 24h 连续报价对齐日线
  TLT_IN_G1 = True：TLT 进入 G1 利率类锚参与 R 矩阵；DGS10/T10Y2Y/HY OAS 留在 G0

OKX instId 已于 2026-11-09 通过 GET /api/v5/public/instruments?instType=SWAP
核验 state=live（543 个永续 / 528 个基础标的）。
"""

from __future__ import annotations

# ── 三项已确认决策常量（后续代码引用，不再硬编码字符串）────────────
GOLD_DUAL_TRACK: dict[str, str] = {
    "tradable": "XAU-USDT-SWAP",
    "macro_reference": "XAUT/USDT",
    "note": "永续做交易/传导；spot 仅作宏观背离参考",
}

EQUITY_ALIGNMENT = "continuous_24h"

TLT_IN_G1 = True

# ── G0 全球宏观层（不可交易，仅门控）──────────────────────────────
G0_MACRO: dict[str, dict] = {
    "growth_inflation_clock": {
        "series": ["INDPRO", "CPI"],
        "source": "FRED",
        "tradable": False,
    },
    "dollar": {"series": ["DTWEXBGS"], "source": "FRED", "tradable": False},
    "rates": {"series": ["DGS10", "T10Y2Y"], "source": "FRED", "tradable": False},
    "credit": {"series": ["BAMLH0A0HYM2"], "source": "FRED", "tradable": False},
}

# ── G1 大类龙头层（6 个可交易锚，参与跨类 R 矩阵）─────────────────
G1_ANCHORS: dict[str, dict] = {
    "BTC": {"class": "crypto", "inst_id": "BTC-USDT-SWAP", "session": EQUITY_ALIGNMENT},
    "XAU": {"class": "precious_metal", "inst_id": "XAU-USDT-SWAP", "session": EQUITY_ALIGNMENT},
    "CL": {"class": "energy", "inst_id": "CL-USDT-SWAP", "session": EQUITY_ALIGNMENT},
    "US500": {"class": "us_index", "inst_id": "US500-USDT-SWAP", "session": EQUITY_ALIGNMENT},
    "JP225": {"class": "apac_index", "inst_id": "JP225-USDT-SWAP", "session": EQUITY_ALIGNMENT},
    "TLT": {"class": "rates_credit", "inst_id": "TLT-USDT-SWAP", "session": EQUITY_ALIGNMENT},
}

# ── 10 大资产类别（含类内层级 / 成员 / 龙头）──────────────────────
# g1_anchor=True 的类别由其龙头代表进入 G1 跨类矩阵。
ASSET_CLASSES: dict[str, dict] = {
    "crypto": {
        "leader": "BTC",
        "inst_id": "BTC-USDT-SWAP",
        "g1_anchor": True,
        "session": "continuous_24h",
        "members": ["BTC", "ETH", "SOL", "AVAX", "LINK", "ADA", "DOGE", "PEPE", "WIF"],
        "layers": {
            "L1_anchor": ["BTC"],
            "L2_major": ["ETH", "SOL"],
            "L3_growth": ["AVAX", "LINK", "ADA"],
            "L4_meme": ["DOGE", "PEPE", "WIF"],
        },
    },
    "precious_metal": {
        "leader": "XAU",
        "inst_id": "XAU-USDT-SWAP",
        "g1_anchor": True,
        "session": "continuous_24h",
        "members": ["XAU", "XAG", "XPT", "XPD"],
    },
    "industrial_metal": {
        "leader": "XCU",
        "inst_id": "XCU-USDT-SWAP",
        "g1_anchor": False,
        "session": "continuous_24h",
        "members": ["XCU"],
    },
    "energy": {
        "leader": "CL",
        "inst_id": "CL-USDT-SWAP",
        "g1_anchor": True,
        "session": "continuous_24h",
        "members": ["CL", "BZ", "NG", "USO"],
    },
    "us_index": {
        "leader": "US500",
        "inst_id": "US500-USDT-SWAP",
        "g1_anchor": True,
        "session": "continuous_24h",
        "members": ["US500", "US100", "SPX"],
    },
    "us_etf": {
        "leader": "SPY",
        "inst_id": "SPY-USDT-SWAP",
        "g1_anchor": False,
        "session": "continuous_24h",
        "members": ["SPY", "QQQ", "IWM", "SMH", "XLE", "XLV", "XBI", "URNM", "TLT"],
    },
    "apac_index": {
        "leader": "JP225",
        "inst_id": "JP225-USDT-SWAP",
        "g1_anchor": True,
        "session": "continuous_24h",
        "members": ["JP225", "KR200"],
    },
    "us_stock": {
        "leader": "NVDA",
        "inst_id": "NVDA-USDT-SWAP",
        "g1_anchor": False,
        "session": "continuous_24h",
        "members": [
            "NVDA",
            "AMD",
            "AVGO",
            "TSM",
            "ASML",
            "MU",
            "ARM",
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "META",
            "NFLX",
            "GS",
            "JPM",
            "V",
            "BRKB",
            "IBKR",
            "COIN",
            "MSTR",
            "HOOD",
            "CRCL",
            "XOM",
            "CVX",
            "OXY",
            "GE",
            "DELL",
        ],
    },
    "fx": {
        "leader": "DXY",
        "inst_id": None,
        "g1_anchor": False,
        "session": "macro_series_only",
        "members": ["DXY"],
        "proxy_series": ["DTWEXBGS", "DX-Y.NYB"],
    },
    "rates_credit": {
        "leader": "TLT",
        "inst_id": "TLT-USDT-SWAP",
        "g1_anchor": TLT_IN_G1,
        "session": "continuous_24h",
        "members": ["TLT"],
        "macro_series": ["DGS10", "T10Y2Y", "BAMLH0A0HYM2"],
    },
}

# 标的 → 大类反查表（类内去重，先到先得）
SYMBOL_CLASS: dict[str, str] = {}
for _cls, _cfg in ASSET_CLASSES.items():
    for _member in _cfg["members"]:
        SYMBOL_CLASS.setdefault(_member, _cls)

# G1 龙头归属优先于类内成员（TLT 同时是 us_etf 的债券代理，跨类以 rates_credit 计）
for _sym, _g1_cfg in G1_ANCHORS.items():
    SYMBOL_CLASS[_sym] = _g1_cfg["class"]

# G1 龙头符号（按配置顺序）
G1_ANCHOR_SYMBOLS: tuple[str, ...] = tuple(G1_ANCHORS)

# ── 纸面/验证场覆盖标的（多板块龙头，DEC-BCL-07）───────────────────
# 用途：p1 MA200 锚点与 X0 意图流的标的域，覆盖加密/贵金属/能源/
# 工业金属/美股指数/美股 ETF/美股龙头/亚太/利率。外汇（fx）只有宏观序列，
# 无 USDT 永续，不在此列。加密标的在 cycle_state 中沿用 "X/USDT" 键以兼容
# p3/p5/23/43/l1_trading 等既有消费者，其余标的使用基础符号键。
# 注意：本清单只扩大"纸面验证场"，不改变 X2 实盘白名单（40/execution/config.json）。
VALIDATION_UNIVERSE: tuple[str, ...] = (
    "BTC",  # crypto L1 锚
    "ETH",  # crypto L2
    "SOL",  # crypto L2
    "XAU",  # 贵金属/避险（金）
    "XAG",  # 贵金属/避险（银）
    "XCU",  # 工业金属（铜）
    "CL",  # 能源（WTI）
    "BZ",  # 能源（Brent）
    "NG",  # 能源（天然气）
    "US500",  # 美股指数
    "SPY",  # 美股 ETF
    "NVDA",  # 美股龙头
    "JP225",  # 亚太指数
    "TLT",  # 利率/信用
)


def normalize_symbol(symbol: str) -> str:
    """统一标的符号：XAU-USDT-SWAP / XAU/USDT:USDT → XAU。"""
    s = str(symbol)
    for suffix in ("-USDT-SWAP", "/USDT:USDT", "/USDT", "-USDT", "-SWAP"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def class_of(symbol: str) -> str | None:
    """标的所属大类；未知标的返回 None。"""
    return SYMBOL_CLASS.get(normalize_symbol(symbol))


def inst_id(symbol: str) -> str | None:
    """标的的 OKX 永续 instId；不可直交易（外汇等）返回 None。"""
    sym = normalize_symbol(symbol)
    cls = SYMBOL_CLASS.get(sym)
    if cls is None:
        return None
    if ASSET_CLASSES[cls].get("session") == "macro_series_only":
        return None
    return f"{sym}-USDT-SWAP"

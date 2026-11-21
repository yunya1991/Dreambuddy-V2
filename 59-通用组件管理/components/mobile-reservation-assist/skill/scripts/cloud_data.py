"""云端数据摘要：从 DreamBuddy 数据面板后端取数并压缩成可写进笔记的摘要。

数据来源（neodrm.com/dashboard 同源后端，经云端主机内网直连）：
- /api/fundamental/snapshot   基本面六模块（宏观/链上/情绪/估值/资金流/广度）
- /api/visual/research        数据研究（评估漏斗、推荐卡、关系分类）
- /api/visual/overview        技术图表（全市场概览、点亮投影）
- /api/data/market            基准行情快照

设计：只读、确定性裁剪（不把 200KB 原样喂给模型），失败降级为空并给出原因。
"""

from __future__ import annotations

import json
import os
import subprocess

DEFAULT_SSH_HOST = "dreambuddy-remote"
DEFAULT_API_BASE = "http://127.0.0.1:3001"

MODULES = ("macro", "onchain", "sentiment", "valuation", "flow", "breadth")
MODULE_NAMES = {
    "macro": "宏观",
    "onchain": "链上",
    "sentiment": "情绪",
    "valuation": "估值",
    "flow": "资金流",
    "breadth": "广度",
}
METRIC_LABELS = {
    "cpi_yoy": "CPI同比%",
    "fed_funds_rate": "联邦基金利率%",
    "rate_cycle": "利率周期",
    "dollar_index": "美元指数",
    "us10y_yield": "美债10年%",
    "vix": "VIX",
    "gold": "黄金",
    "sp500": "标普500",
    "mvrv_ratio": "MVRV",
    "mvrv_z_score": "MVRV-Z",
    "nvt_ratio": "NVT",
    "valuation_zone": "估值区间",
    "sopr": "SOPR",
    "nupl": "NUPL",
    "realized_price": "实现价格",
    "sentiment_index": "情绪指数",
    "sentiment_classification": "情绪分类",
    "sentiment_regime": "情绪状态",
    "social_volume": "社交讨论量",
    "etf_total_flow": "ETF净流入(百万美元)",
    "funding_rate": "资金费率",
    "long_short_ratio": "多空比",
    "flow_regime": "资金流状态",
    "whale_activity": "鲸鱼活跃度",
    "liquidation_pressure": "清算压力",
    "smart_money_direction": "聪明钱方向",
    "btc_dominance": "BTC占比%",
    "breadth_confirmation": "广度确认",
    "market_participation_index": "参与度指数",
    "global_change_24h": "全市场24h涨跌%",
    "defi_tvl_bln": "DeFi TVL(十亿)",
    "onchain_trend": "链上趋势",
    "accumulation_signal": "积累信号",
    "network_health": "网络健康",
    "active_addresses": "活跃地址",
    "tx_count_24h": "24h交易数",
    "hash_rate": "算力",
    "exchange_net_flow": "交易所净流",
}
PICK = {
    "macro": ("cpi_yoy", "fed_funds_rate", "rate_cycle", "dollar_index", "us10y_yield", "vix", "gold", "sp500"),
    "valuation": ("mvrv_ratio", "mvrv_z_score", "nvt_ratio", "valuation_zone", "sopr", "nupl", "realized_price"),
    "sentiment": ("sentiment_index", "sentiment_classification", "sentiment_regime", "social_volume"),
    "flow": ("etf_total_flow", "funding_rate", "long_short_ratio", "flow_regime", "whale_activity",
             "liquidation_pressure", "smart_money_direction"),
    "breadth": ("btc_dominance", "breadth_confirmation", "market_participation_index", "global_change_24h",
                "defi_tvl_bln"),
    "onchain": ("onchain_trend", "accumulation_signal", "network_health", "active_addresses", "tx_count_24h",
                "hash_rate", "exchange_net_flow"),
}


class CloudDataError(RuntimeError):
    """云端取数失败（网络/SSH/接口异常）。"""


def _settings() -> tuple[str, str, int]:
    host = os.environ.get("NEODRM_SSH_HOST") or DEFAULT_SSH_HOST
    base = os.environ.get("NEODRM_API_BASE") or DEFAULT_API_BASE
    try:
        timeout = int(os.environ.get("NEODRM_TIMEOUT") or 60)
    except ValueError:
        timeout = 60
    return host, base, timeout


def fetch(path: str, timeout: int | None = None) -> dict:
    """经云端主机读取后端 JSON（内网 127.0.0.1，不暴露公网登录态）。"""
    host, base, default_timeout = _settings()
    timeout = timeout or default_timeout
    url = "{}{}".format(base.rstrip("/"), path)
    cmd = [
        "ssh",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=5",
        host,
        "curl -s --max-time {} '{}'".format(max(10, timeout - 5), url),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise CloudDataError("云端取数失败：{}".format(exc)) from exc
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        raise CloudDataError("云端取数失败：{}".format((proc.stderr or "空响应").strip()[:200]))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloudDataError("云端返回非 JSON：{}".format(raw[:200])) from exc


def _module_digest(name: str, module: dict) -> dict:
    core = (module.get("metrics") or {}).get("core") or {}
    metrics = [
        {"指标": METRIC_LABELS.get(key, key), "数值": core[key]}
        for key in PICK.get(name, ())
        if core.get(key) is not None
    ]
    labels = [
        {"指标": str(item.get("label") or ""), "数值": item.get("value")}
        for item in (module.get("data") or {}).values()
        if isinstance(item, dict) and item.get("value") is not None and item.get("label")
    ][:4]
    quality = (module.get("meta") or {}).get("data_quality") or "unknown"
    return {"模块": MODULE_NAMES.get(name, name), "指标": metrics, "行情": labels, "数据质量": quality}


def digest_fundamental(snapshot: dict) -> dict:
    modules = snapshot.get("modules") or {}
    return {name: _module_digest(name, modules.get(name) or {}) for name in MODULES if name in modules}


def digest_research(research: dict) -> dict:
    latest = research.get("latest") or {}
    recommendations = []
    for item in (research.get("recommendations") or [])[:3]:
        recommendations.append(
            {
                "标的": item.get("target", ""),
                "关系": item.get("relation", ""),
                "方法": item.get("method", ""),
                "周期": item.get("horizon"),
                "rank_ic": item.get("rank_ic"),
                "胜率": item.get("hit_rate"),
                "状态": item.get("status", ""),
            }
        )
    classes = [
        {
            "分类": item.get("name", ""),
            "过门禁": item.get("gate_pass"),
            "平均rank_ic": item.get("mean_abs_rank_ic"),
            "样本": item.get("rows"),
        }
        for item in (research.get("classes") or [])[:6]
    ]
    coverage = [
        {"标的": item.get("label", ""), "样本": item.get("n"), "过门禁": item.get("gate_pass")}
        for item in (research.get("coverage") or {}).get("rows", [])[:5]
    ]
    return {
        "评估": {
            "评估时间": latest.get("eval_at", ""),
            "数据版本": latest.get("data_version", ""),
            "已评估": latest.get("evaluable"),
            "显著": latest.get("significant"),
            "样本外同号": latest.get("holdout_agree"),
            "过四门禁": latest.get("gate_pass"),
            "稳定": latest.get("stable"),
        },
        "漏斗": research.get("funnel") or [],
        "分类": classes,
        "覆盖": coverage,
        "推荐卡": recommendations,
        "降级": research.get("degraded"),
        "降级原因": research.get("reason", ""),
    }


def digest_technical(overview: dict) -> dict:
    percentile = ((overview.get("base_metrics") or {}).get("percentile") or {})
    lights = overview.get("lights") or {}
    recommended = [
        {"标题": item.get("title", ""), "理由": item.get("reason", "")}
        for item in (overview.get("recommended") or [])[:4]
    ]
    return {
        "基准": overview.get("base", ""),
        "日期": overview.get("as_of", ""),
        "历史分位": percentile.get("value"),
        "分位样本": percentile.get("sample_n"),
        "标的数": len(overview.get("assets") or []),
        "点亮投影": lights.get("answer", ""),
        "投影质量": (lights.get("quality") or {}).get("status", ""),
        "推荐图": recommended,
        "降级": overview.get("degraded"),
    }


def digest_market(market: dict) -> dict:
    return {
        "标的": market.get("symbol", ""),
        "价格": market.get("price"),
        "24h涨跌%": market.get("change24h"),
        "24h最高": market.get("high24h"),
        "24h最低": market.get("low24h"),
        "来源": market.get("source", ""),
        "时间": market.get("timestamp", ""),
    }


def digest(fundamental: dict, research: dict, overview: dict, market: dict | None = None) -> dict:
    """把四份原始响应压缩为写作用摘要（不含买卖方向/仓位建议）。"""
    return {
        "source": "DreamBuddy 数据面板 neodrm.com/dashboard",
        "as_of": (fundamental or {}).get("timestamp") or (research or {}).get("as_of") or "",
        "market": digest_market(market or {}),
        "fundamentals": digest_fundamental(fundamental or {}),
        "research": digest_research(research or {}),
        "technical": digest_technical(overview or {}),
        "caveats": "研究结论只说明相关性与证据强度，不代表未来；数据为历史统计，不构成投资建议。",
    }


def collect(timeout: int | None = None) -> dict:
    """一次取齐四份数据并压缩；单项失败不影响其余（记录 errors）。"""
    errors: list[str] = []
    payloads: dict[str, dict] = {}
    for key, path in (
        ("fundamental", "/api/fundamental/snapshot"),
        ("research", "/api/visual/research"),
        ("overview", "/api/visual/overview"),
        ("market", "/api/data/market"),
    ):
        try:
            payloads[key] = fetch(path, timeout)
        except CloudDataError as exc:
            errors.append("{}: {}".format(path, exc))
            payloads[key] = {}
    result = digest(
        payloads["fundamental"], payloads["research"], payloads["overview"], payloads["market"]
    )
    result["errors"] = errors
    return result

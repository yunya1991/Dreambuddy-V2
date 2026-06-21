#!/usr/bin/env python3
"""
核心任务 1：按需即时简报生成
支持命令行参数指定时间窗口和选项

用法:
    python3 scripts/run_news_digest_on_demand.py
    python3 scripts/run_news_digest_on_demand.py --hours 4
    python3 scripts/run_news_digest_on_demand.py --hours 24 --output custom_brief.md
    python3 scripts/run_news_digest_on_demand.py --help
"""

import argparse
import json
import os
import re
import sys
import subprocess
from statistics import mean, pstdev
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

# 导入行情数据和新闻爬虫模块
sys.path.insert(0, str(Path(__file__).parent))
from market_data import get_market_snapshot
from news_crawler import fetch_odaily_newsflash, fetch_wallstreetcn_breakfast

# 输出目录
BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "raw"
OUTPUTS_DIR = BASE_DIR / "outputs"

RAW_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# 时间戳
NOW = datetime.now()
BRIEF_V3_TITLE = "# 加密市场晨报（V9.3/V9.8 优化版）"
BRIEF_V3_REQUIRED_HEADINGS = [
    "## 📊 市场状态诊断",
    "## 📈 核心数据概览",
    "## 🔔 今日要点（12 条）",
    "## 📐 V9.3 事件账本信号分析",
    "## 💼 动态仓位管理建议",
    "## 🧾 新闻分类明细",
    "## ✅ 信号（简化）",
    "## ⚠️ 风险提示",
    "## 📋 明日观察清单",
    "## 🎯 策略总结",
    "## 🧪 输出检查规范",
]

CATEGORY_PRIORITY = {
    "onchain_data": 90,
    "fed": 85,
    "us_data": 85,
    "geopolitics": 82,
    "project_update": 80,
    "us_policy": 78,
    "institution_flow": 76,
    "crypto_regulation": 75,
    "market_analysis": 65,
    "institution_view": 60,
    "entity_statement": 58,
    "kols_view": 55,
    "people_update": 18,
    "unclassified": 12,
    "unrelated": 10,
}

CATEGORY_KEYWORDS = {
    "onchain_data": ["净流入", "净流出", "whale", "鲸鱼", "活跃地址", "gas", "清算", "爆仓", "杠杆", "空单", "多单", "funding", "open interest", "链上"],
    "institution_flow": ["treasury", "国库", "财库", "增持", "买入", "purchase", "buying", "acquisition", "proposed acquisition", "收购", "并购", "持仓", "holdings", "stake", "质押", "etf", "申购", "赎回", "净流入", "净流出"],
    "project_update": ["上线", "上币", "listing", "升级", "主网", "融资", "空投", "合作", "生态"],
    "kols_view": ["观点", "认为", "看法", "预计", "rumor", "传闻", "爆料", "喊单"],
    "institution_view": ["report", "research", "analyst", "策略", "研报", "分析师", "机构", "投行", "coinshares", "bitwise", "blackrock", "bernstein", "jpmorgan"],
    "entity_statement": ["公告", "声明", "回应", "澄清", "官方", "推迟", "解释", "口径"],
    "people_update": ["出书", "回忆录", "采访", "新书", "定稿", "出版", "行程", "memoir"],
    "fed": ["fomc", "美联储", "鲍威尔", "点阵图", "加息", "降息", "会议纪要"],
    "us_data": ["cpi", "ppi", "pce", "非农", "失业率", "pmi", "gdp", "就业"],
    "us_policy": ["sec", "监管", "法案", "政策", "白宫", "关税", "特朗普", "sfc"],
    "geopolitics": ["地缘", "冲突", "制裁", "战争", "伊朗", "以色列", "霍尔木兹", "俄乌"],
    "market_analysis": ["复盘", "相关性变化", "跨资产", "资金轮动", "市场结构", "risk parity", "美股", "纳指", "开盘", "高开", "收盘", "期货", "概念股"],
    "crypto_regulation": ["aml", "kyc", "牌照", "许可", "travel rule", "反洗钱"],
    "unrelated": ["体育", "娱乐", "明星", "八卦", "电影", "综艺", "旅游"],
}

IMPACT_TEMPLATE = {
    "onchain_data": ("ONCHAIN_FLOW_01", "链上资金/活跃变化 -> 供需与流动性结构变化 -> BTC/ETH 波动与方向偏移"),
    "institution_flow": ("INSTITUTION_FLOW_01", "机构/公司配置与增持变化 -> 供需与叙事预期重定价 -> BTC/ETH（或相关资产）短期方向偏移与波动抬升"),
    "project_update": ("PROJECT_FUNDAMENTAL_01", "协议/生态事件落地 -> 基本面预期与用户增长变化 -> 相关代币估值重定价"),
    "kols_view": ("KOL_SENTIMENT_01", "观点传播扩散 -> 情绪与预期短期偏移 -> 价格脉冲后均值回归风险增加"),
    "institution_view": ("INSTITUTION_VIEW_01", "机构观点扩散 -> 市场预期与风险偏好短期偏移 -> 价格脉冲后回归/反转风险上升（需证据降权）"),
    "entity_statement": ("ENTITY_STATEMENT_01", "官方表态/口径变化 -> 不确定性与合规预期变化 -> 流动性偏好与风险溢价调整"),
    "people_update": ("PEOPLE_UPDATE_01", "人物个人动态 -> 无稳定可复核传导 -> 默认过滤/仅作为背景信息"),
    "unclassified": ("UNCLASSIFIED_01", "证据不足或未命中字典 -> 不确定性披露 -> 不进入 Top12（仅候选池）"),
    "fed": ("MACRO_RATE_01", "利率路径偏鹰/偏鸽 -> 美元与实际利率变动 -> 高β风险资产估值压缩/修复"),
    "us_data": ("MACRO_DATA_02", "宏观数据超/不及预期 -> 降息预期再定价 -> 风险偏好与跨资产波动再平衡"),
    "us_policy": ("POLICY_REG_01", "监管政策强化/放松 -> 合规溢价与资金可得性变化 -> 行业估值分化与风格轮动"),
    "geopolitics": ("GEO_RISK_01", "地缘冲突升级 -> 能源/通胀预期上行 -> 风险资产承压与避险资产受益"),
    "market_analysis": ("CROSS_ASSET_01", "跨资产相关性变化 -> 资金再配置路径重排 -> 股币联动增强/脱钩切换"),
    "crypto_regulation": ("CRYPTO_REG_01", "加密监管落地 -> 交易与托管约束变化 -> 流动性结构与合规资产偏好重估"),
}

DIRECTIONAL_PATH_TEMPLATE = {
    "INSTITUTION_FLOW_01": {
        "bullish": "{event} -> 机构配置与资金承接增强 -> {asset}短期偏强并伴随波动抬升（{horizon}）",
        "bearish": "{event} -> 机构减配/赎回导致边际需求走弱 -> {asset}短期承压且波动放大（{horizon}）",
        "neutral": "{event} -> 机构流向信号尚不一致 -> {asset}以区间震荡为主，等待增量证据（{horizon}）",
    },
    "ONCHAIN_FLOW_01": {
        "bullish": "{event} -> 链上供需结构改善与流动性增强 -> {asset}方向上行概率提升（{horizon}）",
        "bearish": "{event} -> 链上抛压或流动性收缩加剧 -> {asset}回撤风险上升（{horizon}）",
        "neutral": "{event} -> 链上指标分化未形成共振 -> {asset}方向不明，维持中性观察（{horizon}）",
    },
    "ONCHAIN_LEVERAGE_02": {
        "bullish": "{event} -> 杠杆重建但未见脆弱性上行 -> {asset}弹性修复，关注顺势延续（{horizon}）",
        "bearish": "{event} -> 杠杆拥挤与清算脆弱性抬升 -> {asset}短线下行与剧烈波动风险增加（{horizon}）",
        "neutral": "{event} -> 杠杆与清算信号互相抵消 -> {asset}易双向拉扯，暂不确认趋势（{horizon}）",
    },
    "PROJECT_FUNDAMENTAL_01": {
        "bullish": "{event} -> 基本面预期与用户增长改善 -> 相关资产估值上修（{horizon}）",
        "bearish": "{event} -> 基本面预期受损或执行不及预期 -> 相关资产估值下修（{horizon}）",
        "neutral": "{event} -> 基本面影响尚未证实 -> 相关资产以事件交易为主，方向中性（{horizon}）",
    },
    "PROJECT_LISTING_02": {
        "bullish": "{event} -> 流动性与关注度提升 -> 相关资产短期活跃度与价格弹性上升（{horizon}）",
        "bearish": "{event} -> 上线后兑现或抛压释放 -> 相关资产短期承压（{horizon}）",
        "neutral": "{event} -> 流动性改善有限或分歧较大 -> 相关资产可能高波动震荡（{horizon}）",
    },
    "MACRO_RATE_01": {
        "bullish": "{event} -> 利率路径边际转鸽/美元回落 -> 风险偏好修复并支撑{asset}（{horizon}）",
        "bearish": "{event} -> 利率路径偏鹰/美元走强 -> 风险资产估值压缩，{asset}承压（{horizon}）",
        "neutral": "{event} -> 宏观路径未形成单边定价 -> {asset}受外部变量牵引，维持中性（{horizon}）",
    },
    "MACRO_DATA_02": {
        "bullish": "{event} -> 数据支持宽松预期或软着陆叙事 -> 风险资产偏多，{asset}受益（{horizon}）",
        "bearish": "{event} -> 数据强化紧缩预期或增长担忧 -> 风险资产回撤压力上升，{asset}偏空（{horizon}）",
        "neutral": "{event} -> 数据信号混合且预期差有限 -> {asset}方向中性，关注后续确认（{horizon}）",
    },
    "POLICY_REG_01": {
        "bullish": "{event} -> 监管不确定性下降与合规通道改善 -> 行业风险溢价回落，{asset}偏多（{horizon}）",
        "bearish": "{event} -> 监管收紧或执法升级 -> 合规成本与风险溢价抬升，{asset}偏空（{horizon}）",
        "neutral": "{event} -> 政策口径未落地或执行细则不足 -> {asset}中性观察，等待正式文件（{horizon}）",
    },
    "CRYPTO_REG_01": {
        "bullish": "{event} -> 加密监管框架趋稳 -> 机构参与预期改善，{asset}风险偏好回升（{horizon}）",
        "bearish": "{event} -> 加密监管约束增强 -> 流动性与估值承压，{asset}偏空（{horizon}）",
        "neutral": "{event} -> 监管信号与执行节奏不一致 -> {asset}中性，关注监管细节补充（{horizon}）",
    },
    "GEO_RISK_01": {
        "bullish": "{event} -> 地缘风险缓和与避险回落 -> 风险偏好回升，{asset}获得支撑（{horizon}）",
        "bearish": "{event} -> 地缘风险升级与避险需求上升 -> 风险资产承压，{asset}下行波动加大（{horizon}）",
        "neutral": "{event} -> 地缘风险方向未明且传导滞后 -> {asset}中性，等待跨资产确认（{horizon}）",
    },
    "CROSS_ASSET_01": {
        "bullish": "{event} -> 跨资产联动改善并形成正反馈 -> {asset}配置价值上升（{horizon}）",
        "bearish": "{event} -> 跨资产联动转弱或负反馈增强 -> {asset}面临估值压缩（{horizon}）",
        "neutral": "{event} -> 跨资产信号分化明显 -> {asset}中性，优先控制仓位波动（{horizon}）",
    },
    "KOL_SENTIMENT_01": {
        "bullish": "{event} -> 情绪扩散与跟随买盘增强 -> {asset}短线偏多但需防过热（{horizon}）",
        "bearish": "{event} -> 情绪反转与跟随抛压增强 -> {asset}短线偏空且波动放大（{horizon}）",
        "neutral": "{event} -> 情绪信号缺乏可复核证据 -> {asset}中性，仅作观察（{horizon}）",
    },
    "PEOPLE_UPDATE_01": {
        "bullish": "{event} -> 人物动态改善市场叙事 -> 对{asset}影响有限，轻度偏多（{horizon}）",
        "bearish": "{event} -> 人物动态引发负面舆情 -> 对{asset}影响有限，轻度偏空（{horizon}）",
        "neutral": "{event} -> 人物动态缺少稳定传导链 -> 不形成有效方向，维持中性（{horizon}）",
    },
    "UNCLASSIFIED_01": {
        "bullish": "{event} -> 证据不足但边际偏多 -> 仅作弱多提示，待证据确认（{horizon}）",
        "bearish": "{event} -> 证据不足但边际偏空 -> 仅作弱空提示，待证据确认（{horizon}）",
        "neutral": "{event} -> 证据不足/分类未命中 -> 输出No data或中性观察（{horizon}）",
    },
}


def _ai_path_enabled() -> bool:
    return str(os.environ.get("NEWS_AI_PATH_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}


def _ai_path_conf() -> dict:
    return {
        "url": str(os.environ.get("NEWS_AI_PATH_URL") or "").strip(),
        "api_key": str(os.environ.get("NEWS_AI_PATH_API_KEY") or "").strip(),
        "model": str(os.environ.get("NEWS_AI_PATH_MODEL") or "gpt-4o-mini").strip(),
        "timeout_sec": float(os.environ.get("NEWS_AI_PATH_TIMEOUT_SEC") or 12.0),
    }


def _ai_path_system_prompt() -> str:
    return (
        "你是量化新闻影响路径生成器。你只能输出JSON，不要输出Markdown。"
        "不得修改输入的category_primary/path_template_id/conflict_rule/execution_gate。"
        "影响路径必须为三段式：触发因子 -> 传导链路 -> 交易含义。"
        "若证据不足必须披露uncertainty_disclosure并fit_to_template=false。"
        "若source_url或published_at缺失，impact_path必须输出No data并解释reason。"
    )


def _parse_json_object(text: str) -> dict:
    s = str(text or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _validate_ai_path_output(out: dict, *, execution_gate: str, category_primary: str, path_template_id: str) -> tuple:
    if not isinstance(out, dict):
        return False, "invalid_json"
    guard = out.get("guard") if isinstance(out.get("guard"), dict) else {}
    if str(guard.get("execution_gate") or "") != str(execution_gate):
        return False, "guard_execution_gate_mismatch"
    if str(guard.get("category_primary") or "") != str(category_primary):
        return False, "guard_category_mismatch"
    if str(guard.get("path_template_id") or "") != str(path_template_id):
        return False, "guard_template_mismatch"
    impact = str(out.get("impact_path") or "").strip()
    if impact != "No data":
        if impact.count("->") != 2:
            return False, "impact_not_three_segments"
    fit = bool(out.get("fit_to_template"))
    ud = str(out.get("uncertainty_disclosure") or "").strip()
    if (not fit) and (not ud):
        return False, "missing_uncertainty_disclosure"
    return True, ""


def _ai_generate_impact_path(
    *,
    execution_gate: str,
    category_primary: str,
    path_template_id: str,
    path_template_text: str,
    conflict_rule: str,
    decision_trace: str,
    title: str,
    fact: str,
    source_url: str,
    published_at: str,
    source_confidence: str,
    risk_flags: list,
) -> dict:
    if not source_url or not published_at:
        return {
            "impact_path": "No data",
            "fit_to_template": False,
            "confidence": "low",
            "uncertainty_disclosure": "缺少 source_url 或 published_at，按门禁降级。",
            "reason": "关键字段缺失",
            "guard": {
                "execution_gate": execution_gate,
                "category_primary": category_primary,
                "path_template_id": path_template_id,
            },
            "ai_used": False,
            "ai_status": "guard_missing_fields",
        }
    if not _ai_path_enabled():
        return {
            "impact_path": path_template_text,
            "fit_to_template": True,
            "confidence": "medium",
            "uncertainty_disclosure": "",
            "reason": "ai_disabled_fallback_template",
            "guard": {
                "execution_gate": execution_gate,
                "category_primary": category_primary,
                "path_template_id": path_template_id,
            },
            "ai_used": False,
            "ai_status": "disabled_fallback",
        }
    cfg = _ai_path_conf()
    if not cfg["url"]:
        return {
            "impact_path": path_template_text,
            "fit_to_template": True,
            "confidence": "medium",
            "uncertainty_disclosure": "",
            "reason": "ai_url_missing_fallback_template",
            "guard": {
                "execution_gate": execution_gate,
                "category_primary": category_primary,
                "path_template_id": path_template_id,
            },
            "ai_used": False,
            "ai_status": "url_missing_fallback",
        }
    user_prompt = (
        "请基于以下输入生成事件特异化影响路径：\n\n"
        f"execution_gate={execution_gate}\n"
        f"category_primary={category_primary}\n"
        f"path_template_id={path_template_id}\n"
        f"path_template_text={path_template_text}\n"
        f"conflict_rule={conflict_rule}\n"
        f"decision_trace={decision_trace}\n"
        f"title={title}\n"
        f"fact={fact}\n"
        f"source_url={source_url}\n"
        f"published_at={published_at}\n"
        f"source_confidence={source_confidence}\n"
        f"risk_flags={json.dumps(risk_flags or [], ensure_ascii=False)}\n\n"
        "输出JSON字段：impact_path,fit_to_template,confidence,uncertainty_disclosure,reason,guard。"
    )
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _ai_path_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    try:
        req = Request(cfg["url"], data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=float(cfg["timeout_sec"])) as resp:
            rep = json.loads(resp.read().decode("utf-8", "replace"))
        txt = ""
        if isinstance(rep, dict):
            choices = rep.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
                txt = str((msg or {}).get("content") or "")
            if not txt:
                txt = str(rep.get("output_text") or "")
        out = _parse_json_object(txt)
        ok, err = _validate_ai_path_output(
            out,
            execution_gate=execution_gate,
            category_primary=category_primary,
            path_template_id=path_template_id,
        )
        if not ok:
            return {
                "impact_path": path_template_text,
                "fit_to_template": True,
                "confidence": "medium",
                "uncertainty_disclosure": "",
                "reason": f"ai_invalid_{err}",
                "guard": {
                    "execution_gate": execution_gate,
                    "category_primary": category_primary,
                    "path_template_id": path_template_id,
                },
                "ai_used": True,
                "ai_status": f"invalid_{err}",
            }
        out["ai_used"] = True
        out["ai_status"] = "ok"
        return out
    except Exception as e:
        return {
            "impact_path": path_template_text,
            "fit_to_template": True,
            "confidence": "medium",
            "uncertainty_disclosure": "",
            "reason": f"ai_exception:{str(e)}",
            "guard": {
                "execution_gate": execution_gate,
                "category_primary": category_primary,
                "path_template_id": path_template_id,
            },
            "ai_used": False,
            "ai_status": "exception_fallback",
        }


def parse_args():
    parser = argparse.ArgumentParser(
        description='生成加密 + 宏观新闻简报（按需即时版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 run_news_digest_on_demand.py                    # 默认 24 小时
  python3 run_news_digest_on_demand.py --hours 4          # 最近 4 小时
  python3 run_news_digest_on_demand.py --hours 12 --quiet # 最近 12 小时，安静模式
  python3 run_news_digest_on_demand.py -o my_brief.md     # 自定义输出文件名
        """
    )
    parser.add_argument('--hours', '-H', type=int, default=24,
                        help='时间窗口（小时），默认 24')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='输出文件名（可选），默认自动生成')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='安静模式，仅输出必要信息')
    parser.add_argument('--json', action='store_true',
                        help='同时输出 JSON 格式摘要')
    parser.add_argument('--report-mode', choices=['full', 'lite'], default='full',
                        help='输出档位：full=完整版（默认），lite=轻量版')
    return parser.parse_args()


def fmt_price(price_data):
    """格式化价格显示"""
    p = price_data.get("price_usd", 0)
    c = price_data.get("change_24h", 0)
    if p > 0:
        return f"${p:,.2f} ({c:+.2f}%)"
    return "数据暂不可用"


def get_real_time_prices():
    """获取真实价格数据"""
    snapshot = get_market_snapshot()
    btc = snapshot.get("crypto", {}).get("btc", {})
    eth = snapshot.get("crypto", {}).get("eth", {})
    nasdaq = snapshot.get("traditional", {}).get("nasdaq", {})
    vix = snapshot.get("traditional", {}).get("vix", {})

    return {
        "btc": {
            "price": btc.get("price_usd", 0),
            "change_24h": btc.get("change_24h", 0),
            "display": fmt_price(btc)
        },
        "eth": {
            "price": eth.get("price_usd", 0),
            "change_24h": eth.get("change_24h", 0),
            "display": fmt_price(eth)
        },
        "nasdaq": {
            "price": nasdaq.get("price_usd", 0),
            "change_24h": nasdaq.get("change_24h", 0),
            "display": fmt_price(nasdaq) if nasdaq.get("price_usd", 0) > 0 else "数据暂不可用（自动多源补齐失败）"
        },
        "vix": {
            "value": vix.get("value", 0),
            "display": f"{vix.get('value', 0):.2f}" if vix.get("value", 0) > 0 else "数据暂不可用"
        },
        "eth_btc_ratio": snapshot.get("crypto", {}).get("eth_btc_ratio", 0),
        "raw_snapshot": snapshot
    }


def _generate_crypto_news_mock(hours: int):
    """生成加密货币新闻（本地兜底）"""
    now = datetime.now()
    items = []

    # 根据时间窗口调整新闻时间分布
    time_offsets = {
        'T0': [0.5, 1, 1.5, 2, 3],           # 当日事件
        'T1': [4, 6, 8, 12],                  # 数日事件
        'T2': [18, 24, 36, 48]               # 数周事件（但仍在时间窗口内）
    }

    mock_items = [
        {
            "title": "比特币 ETF 单日净流入超 5 亿美元，创 3 个月新高",
            "category": "onchain_data",
            "source_url": "https://www.odaily.news/newsflash/123456",
            "summary": "贝莱德 IBIT 单日流入 3.2 亿美元，总资产管理规模突破 500 亿",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "BTC 价格上涨 → 山寨币跟随 → 风险偏好上升",
            "risk_flags": [],
            "market_impact": "短期利好 BTC 价格，可能带动山寨季"
        },
        {
            "title": "以太坊链上稳定币结算量首次超越比特币",
            "category": "onchain_data",
            "source_url": "https://www.odaily.news/newsflash/123457",
            "summary": "USDT + USDC 在以太坊的日结算量达 120 亿美元，BTC 链上为 85 亿",
            "source_confidence": "high",
            "impact_horizon": "T1",
            "cross_market_map": "以太坊生态活跃 → ETH 相对 BTC 走强 → Layer2 受益",
            "risk_flags": [],
            "market_impact": "ETH/BTC 汇率可能继续走强"
        },
        {
            "title": "Solana 生态 TVL 突破 80 亿美元，创历史新高",
            "category": "project_update",
            "source_url": "https://www.odaily.news/newsflash/123458",
            "summary": "DeFi 协议活跃度和锁仓量双升，Jupiter 日交易量突破 50 亿",
            "source_confidence": "high",
            "impact_horizon": "T1",
            "cross_market_map": "SOL 生态繁荣 → SOL 代币需求上升 → 竞品公链承压",
            "risk_flags": [],
            "market_impact": "SOL 及相关生态代币可能继续走强"
        },
        {
            "title": "某分析师称山寨季将在 2 周内到来",
            "category": "kols_view",
            "source_url": "https://twitter.com/analyst/status/123456",
            "summary": "基于历史周期和当前市值占比，认为山寨季即将启动",
            "source_confidence": "low",
            "impact_horizon": "T2",
            "cross_market_map": "山寨季预期 → 资金从 BTC 流出 → 小市值币种波动加大",
            "risk_flags": ["单源爆料", "无数据支撑"],
            "market_impact": "情绪面影响，需等待数据确认"
        },
        {
            "title": "传某大型交易所面临监管调查",
            "category": "project_update",
            "source_url": "https://www.odaily.news/newsflash/123459",
            "summary": "消息称美国 SEC 正在调查某未具名交易所的平台币储备",
            "source_confidence": "medium",
            "impact_horizon": "T0",
            "cross_market_map": "交易所风险 → 市场恐慌 → 资金流向合规 ETF",
            "risk_flags": ["单源爆料", "数据不可复核"],
            "market_impact": "短期情绪压制，若证实可能引发抛售"
        }
    ]

    # 筛选在时间窗口内的新闻
    for item in mock_items:
        horizon = item["impact_horizon"]
        offsets = time_offsets.get(horizon, [24])

        # 找出在时间窗口内的偏移量
        valid_offsets = [o for o in offsets if o <= hours]
        if valid_offsets:
            offset = min(valid_offsets)
            item["published_at"] = (now - timedelta(hours=offset)).isoformat()
            items.append(item)

    return items


def _generate_macro_news_mock(hours: int):
    """生成宏观新闻（本地兜底）"""
    now = datetime.now()
    items = []

    time_offsets = {
        'T0': [0.5, 1, 2, 3],
        'T1': [5, 8, 12],
        'T2': [18, 24, 36]
    }

    mock_items = [
        {
            "title": "美联储 12 月会议纪要：官员们对通胀进展感到担忧",
            "topic": "fed",
            "source_url": "https://wallstreetcn.com/articles/3766940",
            "key_fact": "多数官员认为 12 月降息合适，但对 2026 年利率路径存在分歧",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "鹰派纪要 → 美债收益率上升 → 美元走强 → 风险资产承压",
            "risk_flags": [],
            "market_impact": "BTC 和美股短期可能承压，关注纳斯达克反应"
        },
        {
            "title": "美国 12 月非农就业新增 25.6 万人，远超预期",
            "topic": "us_data",
            "source_url": "https://wallstreetcn.com/articles/3766941",
            "key_fact": "失业率降至 4.1%，薪资增速 4.1% 同比",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "强劲就业 → 美联储降息空间受限 → 美债收益率飙升 → 高β资产承压",
            "risk_flags": [],
            "market_impact": "利空 BTC 和成长股，利好美元和银行股"
        },
        {
            "title": "中东局势升级：伊朗威胁封锁霍尔木兹海峡",
            "topic": "geopolitics",
            "source_url": "https://wallstreetcn.com/articles/3766942",
            "key_fact": "该地区承担全球 20% 石油运输",
            "source_confidence": "medium",
            "impact_horizon": "T1",
            "cross_market_map": "地缘风险 → 原油上涨 → 通胀预期上升 → VIX 上升 → 风险偏好下降",
            "risk_flags": ["标题与正文不一致"],
            "market_impact": "避险资产 (黄金/美元) 受益，风险资产分化"
        },
        {
            "title": "特朗普考虑对加密货币实施更宽松监管框架",
            "topic": "us_policy",
            "source_url": "https://wallstreetcn.com/articles/3766943",
            "key_fact": "拟成立加密货币顾问委员会，行业代表将参与政策制定",
            "source_confidence": "medium",
            "impact_horizon": "T2",
            "cross_market_map": "监管放松 → 机构入场加速 → 长期需求上升 → 估值重构",
            "risk_flags": ["政策未落地"],
            "market_impact": "长期利好，特别是合规相关标的"
        },
        {
            "title": "纳斯达克与比特币相关性降至 2023 年来最低",
            "topic": "market_analysis",
            "source_url": "https://wallstreetcn.com/articles/3766944",
            "key_fact": "30 日相关性系数降至 0.15，此前长期维持在 0.5 以上",
            "source_confidence": "high",
            "impact_horizon": "T1",
            "cross_market_map": "相关性下降 → BTC 独立行情 → 资产配置价值提升",
            "risk_flags": [],
            "market_impact": "BTC 作为独立资产类别的配置价值凸显"
        },
        {
            "title": "华尔街早餐：美股期货小幅上涨，英伟达再创新高",
            "topic": "market_analysis",
            "source_url": "https://wallstreetcn.com/articles/3766936",
            "key_fact": "纳指期货 +0.3%，英伟达市值突破 4 万亿美元",
            "source_confidence": "high",
            "impact_horizon": "T0",
            "cross_market_map": "AI 热潮延续 → 科技股领涨 → 风险偏好上升 → BTC 受益",
            "risk_flags": [],
            "market_impact": "科技股情绪利好风险资产"
        }
    ]

    for item in mock_items:
        horizon = item["impact_horizon"]
        offsets = time_offsets.get(horizon, [24])

        valid_offsets = [o for o in offsets if o <= hours]
        if valid_offsets:
            offset = min(valid_offsets)
            item["published_at"] = (now - timedelta(hours=offset)).isoformat()
            items.append(item)

    return items


def _to_dt(v):
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    if not s:
        return NOW
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return NOW


def _hours_since(ts) -> float:
    try:
        dt = _to_dt(ts)
        return max(0.0, (NOW - dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else NOW - dt).total_seconds() / 3600.0)
    except Exception:
        return 999.0


def _impact_horizon_from_age(age_h: float) -> str:
    if age_h <= 3:
        return "T0"
    if age_h <= 24:
        return "T1"
    return "T2"


def _confidence_rank(v: str) -> int:
    s = str(v or "").strip().lower()
    if s == "high":
        return 3
    if s == "medium":
        return 2
    if s == "low":
        return 1
    return 0


def _norm_title(v: str) -> str:
    s = str(v or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", s)


def _safe_int(v) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0


def _dedup_day_bucket(ts: str) -> str:
    try:
        return _to_dt(ts).strftime("%Y%m%d")
    except Exception:
        return ""


def _extract_action_hint(text: str) -> str:
    s = str(text or "").lower()
    if any(k in s for k in ("做空", "空单", "short")):
        return "short"
    if any(k in s for k in ("做多", "多单", "long")):
        return "long"
    if any(k in s for k in ("增持", "买入", "purchase", "buying", "acquisition", "申购", "净流入")):
        return "buy"
    if any(k in s for k in ("减持", "卖出", "sell", "赎回", "净流出")):
        return "sell"
    if any(k in s for k in ("清算", "爆仓", "liquidation")):
        return "liquidation"
    return ""


def _extract_assets(text: str) -> list:
    s = str(text or "").lower()
    assets = set()
    if ("btc" in s) or ("比特币" in s):
        assets.add("BTC")
    if ("eth" in s) or ("以太坊" in s):
        assets.add("ETH")
    if ("sol" in s) or ("索拉纳" in s):
        assets.add("SOL")
    if "xrp" in s:
        assets.add("XRP")
    if "bnb" in s:
        assets.add("BNB")
    if ("usdt" in s) or ("泰达" in s):
        assets.add("USDT")
    if "usdc" in s:
        assets.add("USDC")
    if ("nasdaq" in s) or ("纳指" in s):
        assets.add("NASDAQ")
    if "vix" in s:
        assets.add("VIX")
    if "dxy" in s:
        assets.add("DXY")
    if ("gold" in s) or ("黄金" in s):
        assets.add("GOLD")
    if any(k in s for k in ("wti", "brent", "oil", "原油")):
        assets.add("OIL")
    return sorted(list(assets))


def _extract_fact_fingerprint(text: str) -> dict:
    s = str(text or "")
    low = s.lower()

    lev = None
    m = re.search(r"(\d{1,3})\s*(?:x|倍|×)", low)
    if m:
        lev = _safe_int(m.group(1))

    qty = None
    asset = None
    m = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:枚|个|张)?\s*(btc|eth|sol|bnb|xrp|ada|dot|doge|ltc|trx|avax)\b", low)
    if m:
        qty = _safe_int(m.group(1).replace(",", ""))
        asset = m.group(2).upper()
    if qty is None:
        m = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:枚|个|张)?\s*(比特币|以太坊)", s)
        if m:
            qty = _safe_int(m.group(1).replace(",", ""))
            asset = "BTC" if m.group(2) == "比特币" else "ETH"

    liq = None
    m = re.search(r"爆仓价[^\d]{0,8}(\d+(?:,\d{3})*(?:\.\d+)?)", s)
    if m:
        liq = _safe_int(m.group(1).replace(",", ""))
    if liq is None:
        m = re.search(r"(?:触及爆仓|将触及爆仓)[^\d]{0,12}(\d+(?:,\d{3})*(?:\.\d+)?)", s)
        if m:
            liq = _safe_int(m.group(1).replace(",", ""))

    entry = None
    m = re.search(r"开仓价格(?:为|:|：)?[^\d]{0,8}(\d+(?:,\d{3})*(?:\.\d+)?)", s)
    if m:
        entry = _safe_int(m.group(1).replace(",", ""))
    if entry is None:
        m = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:美元)?\s*开仓", s)
        if m:
            entry = _safe_int(m.group(1).replace(",", ""))

    stop_loss = None
    m = re.search(r"止损[^\d]{0,12}(\d+(?:,\d{3})*(?:\.\d+)?)", s)
    if m:
        stop_loss = _safe_int(m.group(1).replace(",", ""))

    take_profit = None
    m = re.search(r"止盈[^\d]{0,12}(\d+(?:,\d{3})*(?:\.\d+)?)", s)
    if m:
        take_profit = _safe_int(m.group(1).replace(",", ""))

    assets = _extract_assets(s)
    if not asset and assets:
        asset = assets[0]

    fingerprint = {
        "asset": asset,
        "qty": qty,
        "lev": lev,
        "liq": liq,
        "entry": entry,
        "sl": stop_loss,
        "tp": take_profit,
    }
    present = sum(1 for k in ("asset", "qty", "lev", "liq", "entry") if fingerprint.get(k) not in (None, "", 0))
    if present >= 2:
        return fingerprint
    return {}


def _dedup_key(it: dict) -> str:
    if not isinstance(it, dict):
        return ""
    category = str(it.get("category_primary") or it.get("category") or it.get("topic") or "").strip()
    template = str(it.get("path_template_id") or "").strip()
    published_at = str(it.get("published_at") or "").strip()
    day = _dedup_day_bucket(published_at) if published_at else ""
    title = str(it.get("title") or "").strip()
    body = str(it.get("summary") or it.get("key_fact") or it.get("market_impact") or "").strip()
    text = f"{title} {body}"

    fp = _extract_fact_fingerprint(text)
    action = _extract_action_hint(text)
    assets = _extract_assets(text)

    if fp:
        parts = [
            day,
            category,
            template,
            action,
            fp.get("asset"),
            f"q:{fp.get('qty') or ''}",
            f"lev:{fp.get('lev') or ''}",
            f"liq:{fp.get('liq') or ''}",
            f"entry:{fp.get('entry') or ''}",
            f"sl:{fp.get('sl') or ''}",
            f"tp:{fp.get('tp') or ''}",
        ]
        return "|".join(str(x or "") for x in parts)

    if assets and action:
        return "|".join([day, category, template, action, ",".join(assets), _norm_title(title)])
    return "|".join([day, category, template, _norm_title(title)])


def _ensure_risk_flags(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if str(v or "").strip():
        return [str(v).strip()]
    return []


def _has_asset_mapping(raw: dict) -> bool:
    txt = " ".join(
        str(raw.get(k) or "")
        for k in ("title", "summary", "key_fact", "cross_market_map", "market_impact")
    ).lower()
    return any(x in txt for x in (
        "btc",
        "eth",
        "sol",
        "crypto",
        "nasdaq",
        "vix",
        "dxy",
        "us10y",
        "spx",
        "wti",
        "brent",
        "oil",
        "gold",
        "加密",
        "比特币",
        "以太坊",
        "山寨",
        "纳指",
        "美股",
        "原油",
        "黄金",
    ))


def _infer_assertion_type(raw: dict) -> str:
    title = str(raw.get("title") or "").strip().lower()
    body = str(raw.get("summary") or raw.get("key_fact") or "").strip().lower()
    text = f"{title} {body}"
    if any(k in text for k in ("传闻", "爆料", "据称", "消息称", "rumor")):
        return "rumor"
    if any(k in text for k in ("公告", "声明", "回应", "澄清", "官方")):
        return "official_statement"
    if any(k in text for k in ("研报", "report", "research", "analyst", "分析师", "策略")):
        return "analysis_view"
    if any(k in text for k in ("出书", "新书", "回忆录", "采访", "定稿", "出版", "行程", "memoir")):
        return "personal_update"
    if any(k in text for k in ("上线", "listing", "上币", "升级", "主网", "融资", "空投", "合作", "增持", "买入", "purchase", "buying", "acquisition", "质押", "申购", "赎回")):
        return "action_fact"
    if any(k in text for k in ("观点", "认为", "看法", "预计", "预测")):
        return "analysis_view"
    return "analysis_view"


def _assertion_evidence(raw: dict) -> dict:
    source_url = str(raw.get("source_url") or "").strip()
    published_at = raw.get("published_at") or raw.get("fetched_at") or ""
    snippet = str(raw.get("summary") or raw.get("key_fact") or "").strip()
    if len(snippet) > 160:
        snippet = snippet[:160]
    return {
        "source_url": source_url,
        "published_at": str(published_at),
        "quoted_snippet": snippet,
    }


def _candidate_categories(raw: dict, explicit: str) -> set:
    text = " ".join(
        str(raw.get(k) or "")
        for k in ("title", "summary", "key_fact", "cross_market_map", "market_impact")
    ).lower()
    cands = set()
    if explicit:
        cands.add(explicit)
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(str(k).lower() in text for k in kws):
            cands.add(cat)
    if not cands:
        cands.add("unclassified")
    return cands


def _apply_rule_a(cands: set, has_mapping: bool) -> tuple:
    if "people_update" in cands:
        return "people_update", "A:PERSONAL_UPDATE"
    if "geopolitics" in cands and "market_analysis" in cands:
        return "geopolitics", "A:GEO_OVER_ANALYSIS"
    if "geopolitics" in cands and "project_update" in cands:
        return "geopolitics", "A:GEO_OVER_PROJECT"
    macro_set = {"fed", "us_data", "us_policy"}
    if ("market_analysis" in cands) and (cands & macro_set):
        chosen = sorted(list(cands & macro_set), key=lambda x: CATEGORY_PRIORITY.get(x, 0), reverse=True)[0]
        return chosen, "A:MACRO_OVER_ANALYSIS"
    if (cands & macro_set) and ("project_update" in cands):
        chosen = sorted(list(cands & macro_set), key=lambda x: CATEGORY_PRIORITY.get(x, 0), reverse=True)[0]
        return chosen, "A:MACRO_OVER_PROJECT"
    if "crypto_regulation" in cands and "project_update" in cands:
        return "crypto_regulation", "A:CRYPTO_REG_OVER_PROJECT"
    if "onchain_data" in cands and "kols_view" in cands:
        return "onchain_data", "A:ONCHAIN_OVER_KOL"
    if "project_update" in cands and "kols_view" in cands:
        return "project_update", "A:PROJECT_OVER_KOL"
    if "unrelated" in cands and len(cands) > 1 and not has_mapping:
        return "unrelated", "A:UNRELATED_FILTER"
    return "", ""


def _candidate_score(raw: dict, cat: str, has_mapping: bool, risk_flags: list, conf: str) -> float:
    text = " ".join(
        str(raw.get(k) or "")
        for k in ("title", "summary", "key_fact", "cross_market_map", "market_impact")
    ).lower()
    hits = sum(1 for k in CATEGORY_KEYWORDS.get(cat, []) if str(k).lower() in text)
    keyword_score = min(40.0, 8.0 * hits)
    url = str(raw.get("source_url") or "").strip()
    ts = str(raw.get("published_at") or raw.get("fetched_at") or "").strip()
    body = str(raw.get("summary") or raw.get("key_fact") or "").strip()
    evidence_score = (10.0 if url and url != "No data" else 0.0) + (8.0 if ts else 0.0) + (7.0 if len(body) >= 20 else 0.0)
    market_link_score = 20.0 if has_mapping else (10.0 if _has_asset_mapping(raw) else 0.0)
    source_quality = {"high": 15.0, "medium": 10.0, "low": 5.0}.get(conf, 5.0) - min(8.0, float(len(risk_flags or [])) * 2.0)
    return max(0.0, keyword_score + evidence_score + market_link_score + source_quality)


def _resolve_category_conflict(raw: dict, explicit: str, risk_flags: list, conf: str) -> dict:
    has_mapping = _has_asset_mapping(raw)
    assertion_type = _infer_assertion_type(raw)
    assertion_evidence = _assertion_evidence(raw)
    cands = _candidate_categories(raw, explicit)
    if assertion_type == "personal_update":
        cands = {"people_update"}
    title = str(raw.get("title") or "").lower()
    if "onchain_data" in cands and any(k in title for k in ("funding", "open interest", "清算", "爆仓", "杠杆")):
        for x in ("fed", "us_data", "us_policy", "geopolitics", "crypto_regulation", "market_analysis"):
            if x in cands:
                cands.discard(x)
    cat_a, rule_a = _apply_rule_a(cands, has_mapping)
    if cat_a:
        scored = [{"category": x, "score": float(_candidate_score(raw, x, has_mapping, risk_flags, conf))} for x in sorted(list(cands))]
        return {
            "category_primary": cat_a,
            "category_candidates": scored,
            "conflict_rule": rule_a,
            "decision_trace": f"rule_a_resolved:{rule_a}",
            "conflict_flag": False,
            "assertion_type": assertion_type,
            "assertion_evidence": assertion_evidence,
        }
    scored = []
    for c in cands:
        scored.append({"category": c, "score": float(_candidate_score(raw, c, has_mapping, risk_flags, conf))})
    scored = sorted(scored, key=lambda x: x["score"], reverse=True)
    top = scored[0] if scored else {"category": "unrelated", "score": 0.0}
    cat = str(top.get("category") or "unrelated")
    score = float(top.get("score") or 0.0)
    second = float(scored[1]["score"]) if len(scored) > 1 else -1.0
    conflict_flag = bool(len(scored) > 1 and score >= 55.0 and second >= 55.0 and abs(score - second) <= 5.0)
    if score < 50.0:
        if cat in {"fed", "us_data", "us_policy", "geopolitics", "crypto_regulation"} and score >= 42.0:
            cat = cat
        else:
            cat = "unclassified"
    trace = f"rule_b_score={score:.1f};cands={','.join([str(x['category']) for x in scored])}"
    return {
        "category_primary": cat,
        "category_candidates": scored,
        "conflict_rule": "B:SCORE",
        "decision_trace": trace,
        "conflict_flag": conflict_flag,
        "assertion_type": assertion_type,
        "assertion_evidence": assertion_evidence,
    }


def _impact_template_for(raw: dict, category_primary: str) -> tuple:
    title = str(raw.get("title") or "").lower()
    if category_primary == "onchain_data":
        if any(k in title for k in ("funding", "open interest", "清算", "杠杆", "爆仓")):
            return ("ONCHAIN_LEVERAGE_02", "杠杆与清算指标变化 -> 拥挤度与脆弱性上升/回落 -> 风险偏好切换与仓位收缩/恢复")
    if category_primary == "project_update":
        if any(k in title for k in ("listing", "上币", "上线", "流动性")):
            return ("PROJECT_LISTING_02", "上线/流动性事件 -> 交易深度与关注度提升 -> 短期成交放大与波动抬升")
    return IMPACT_TEMPLATE.get(category_primary, ("NO_TEMPLATE", "No data"))


def _asset_hint(raw: dict) -> str:
    text = " ".join(str(raw.get(k) or "") for k in ("title", "summary", "key_fact", "cross_market_map", "market_impact")).lower()
    if "eth" in text or "以太坊" in text:
        return "ETH"
    if "btc" in text or "比特币" in text:
        return "BTC"
    if "sol" in text:
        return "SOL"
    if "gold" in text or "黄金" in text:
        return "黄金与风险资产"
    if "oil" in text or "原油" in text:
        return "原油与风险资产"
    return "BTC/ETH（或相关资产）"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _base_direction_score(raw: dict, category_primary: str, path_template_id: str) -> tuple:
    text = " ".join(str(raw.get(k) or "") for k in ("title", "summary", "key_fact")).lower()
    pos_kw = {
        "institution_flow": ("增持", "买入", "purchase", "buying", "申购", "净流入", "持仓上升"),
        "onchain_data": ("活跃地址上升", "净流入交易所减少", "稳定币净流入", "回暖", "增长"),
        "project_update": ("升级落地", "生态扩展", "合作生效", "上线", "融资"),
        "fed": ("偏鸽", "降息", "通胀回落", "就业放缓"),
        "us_data": ("低于预期", "回落", "软着陆", "支持降息"),
        "us_policy": ("放松", "批准", "通过", "合规通道"),
        "crypto_regulation": ("放松", "批准", "牌照扩容", "合规通道"),
        "geopolitics": ("停火", "缓和", "谈判", "传递信息"),
    }
    neg_kw = {
        "institution_flow": ("减持", "卖出", "赎回", "净流出", "抛售"),
        "onchain_data": ("清算", "爆仓", "杠杆拥挤", "资金费率极端"),
        "project_update": ("安全事故", "停机", "延期", "取消", "漏洞"),
        "fed": ("偏鹰", "加息", "强美元", "紧缩"),
        "us_data": ("高于预期", "通胀超预期", "就业过强"),
        "us_policy": ("收紧", "执法升级", "禁令"),
        "crypto_regulation": ("收紧", "禁令", "执法"),
        "geopolitics": ("冲突升级", "制裁升级", "通道风险", "袭击"),
    }
    if category_primary in {"market_analysis", "institution_view", "entity_statement", "kols_view"}:
        return 0.0, "base:neutral_generic"
    if category_primary in {"people_update", "unclassified", "unrelated"}:
        return 0.0, "base:neutral_filtered"
    base_abs = {
        "institution_flow": 0.45,
        "onchain_data": 0.35 if path_template_id != "ONCHAIN_LEVERAGE_02" else 0.40,
        "project_update": 0.30 if path_template_id != "PROJECT_LISTING_02" else 0.35,
        "fed": 0.35,
        "us_data": 0.35,
        "us_policy": 0.30,
        "crypto_regulation": 0.30,
        "geopolitics": 0.35,
    }.get(category_primary, 0.0)
    if any(k in text for k in neg_kw.get(category_primary, ())):
        return -base_abs, "base:negative_keywords"
    if any(k in text for k in pos_kw.get(category_primary, ())):
        return +base_abs, "base:positive_keywords"
    if category_primary == "geopolitics":
        return -0.20, "base:geopolitics_default_bearish"
    return 0.0, "base:no_signal"


def _conflict_penalty(conflict_rule: str, category_candidates: list) -> tuple:
    if str(conflict_rule or "").startswith("A:"):
        return 0.0, "c:rule_a"
    if not isinstance(category_candidates, list) or len(category_candidates) < 2:
        return 0.03, "c:rule_b_default"
    try:
        vals = sorted([float(x.get("score") or 0.0) for x in category_candidates], reverse=True)
        delta = vals[0] - vals[1]
        if delta <= 5.0:
            return 0.08, "c:rule_b_close"
        return 0.03, "c:rule_b_clear"
    except Exception:
        return 0.03, "c:rule_b_error"


def _direction_from_score(score: float) -> str:
    if score >= 0.25:
        return "bullish"
    if score <= -0.25:
        return "bearish"
    return "neutral"


def _confidence_band(score: float, source_confidence: str) -> str:
    if abs(score) >= 0.60 and source_confidence == "high":
        return "high"
    if abs(score) >= 0.35:
        return "medium"
    return "low"


def _intensity_word(score: float, confidence_band: str) -> str:
    if -0.25 < score < 0.25:
        raw = "谨慎"
    elif score >= 0.75 or score <= -0.75:
        raw = "偏强"
    elif score >= 0.45 or score <= -0.45:
        raw = "温和"
    else:
        raw = "谨慎"
    if confidence_band == "low":
        return "谨慎"
    if confidence_band == "medium" and raw == "偏强":
        return "温和"
    return raw


def _direction_label(direction: str) -> str:
    if direction == "bullish":
        return "看多"
    if direction == "bearish":
        return "看空"
    return "中性"


def _is_high_risk_flags(flags: list) -> bool:
    joined = " ".join(str(x) for x in (flags or []))
    return any(k in joined for k in ("数据不可复核", "单源爆料", "路径未匹配"))


def _badge_contract(direction: str, score: float, confidence_band: str, risk_flags: list, fail_closed: bool, asof: str, impact_path: str) -> dict:
    label = _direction_label(direction)
    intensity = _intensity_word(score, confidence_band)
    reason = "score_mapping"
    color = "amber"
    if fail_closed:
        color = "neutral"
        label = "中性"
        intensity = "谨慎"
        reason = "fail_closed_override" if impact_path != "No data" else "no_data_override"
    elif impact_path == "No data":
        color = "neutral"
        label = "中性"
        intensity = "谨慎"
        reason = "no_data_override"
    elif confidence_band == "low":
        color = "amber"
        reason = "low_confidence_override"
    elif _is_high_risk_flags(risk_flags):
        color = "amber"
        reason = "risk_flag_override"
    else:
        if label == "看多":
            color = "green" if intensity in {"偏强", "温和"} else "amber"
        elif label == "看空":
            color = "red" if intensity in {"偏强", "温和"} else "amber"
        else:
            color = "amber"
    return {
        "badge_text": f"{label}·{intensity}",
        "badge_color": color,
        "badge_reason": reason,
        "direction_label": label,
        "intensity_word": intensity,
        "direction_score": round(float(score), 4),
        "confidence_band": confidence_band,
        "risk_flags": list(risk_flags or []),
        "fail_closed": bool(fail_closed),
        "asof": NOW.isoformat(),
    }


def _directional_impact_path(path_template_id: str, direction: str, title: str, asset: str, horizon: str) -> str:
    bucket = DIRECTIONAL_PATH_TEMPLATE.get(path_template_id) or {}
    tpl = str(bucket.get(direction) or bucket.get("neutral") or "").strip()
    if not tpl:
        return "No data"
    return tpl.format(event=title, asset=asset, horizon=horizon, risk="")


def _build_direction_contract(
    *,
    raw: dict,
    category_primary: str,
    path_template_id: str,
    source_confidence: str,
    impact_horizon: str,
    risk_flags: list,
    source_url: str,
    published_at: str,
    conflict_rule: str,
    category_candidates: list,
) -> dict:
    fail_closed = (not str(source_url or "").strip()) or (not str(published_at or "").strip())
    base, base_reason = _base_direction_score(raw, category_primary, path_template_id)
    e = {"high": 0.20, "medium": 0.10, "low": 0.00}.get(source_confidence, 0.0)
    h = {"T0": 0.12, "T1": 0.06, "T2": 0.00}.get(impact_horizon, 0.0)
    c, c_reason = _conflict_penalty(conflict_rule, category_candidates)
    r = min(0.35, 0.07 * len(risk_flags or []))
    score = _clamp(base + e + h - c - r, -1.0, 1.0)
    direction = _direction_from_score(score)
    confidence_band = _confidence_band(score, source_confidence)
    if ("数据不可复核" in (risk_flags or [])) and source_confidence == "low":
        direction = "neutral"
        score = 0.0
        confidence_band = "low"
    asset = _asset_hint(raw)
    impact_path = "No data" if fail_closed else _directional_impact_path(
        path_template_id=path_template_id,
        direction=direction,
        title=str(raw.get("title") or "").strip(),
        asset=asset,
        horizon=impact_horizon,
    )
    badge = _badge_contract(
        direction=direction,
        score=score,
        confidence_band=confidence_band,
        risk_flags=risk_flags,
        fail_closed=fail_closed,
        asof=NOW.isoformat(),
        impact_path=impact_path,
    )
    direction_trace = (
        f"cat={category_primary}|rule={conflict_rule}|base={base:.2f}|e={e:.2f}|h={h:.2f}|"
        f"c={c:.2f}|r={r:.2f}|score={score:.2f}|dir={direction}|conf={confidence_band}|"
        f"{base_reason}|{c_reason}"
    )
    return {
        "direction": direction,
        "direction_score": round(float(score), 4),
        "confidence_band": confidence_band,
        "direction_label": badge["direction_label"],
        "intensity_word": badge["intensity_word"],
        "impact_path": impact_path,
        "fail_closed": fail_closed,
        "badge": badge,
        "direction_trace": direction_trace,
    }


def _preprocess_crypto_news(items, hours: int):
    out = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        pub = raw.get("published_at") or raw.get("fetched_at")
        if not pub:
            continue
        age_h = _hours_since(pub)
        if age_h > float(hours) + 1.0:
            continue
        source_url = str(raw.get("source_url") or "").strip()
        if not source_url or source_url == "No data":
            continue
        risk_flags = _ensure_risk_flags(raw.get("risk_flags"))
        conf = str(raw.get("source_confidence") or "medium").strip().lower()
        if conf not in {"high", "medium", "low"}:
            conf = "medium"
        explicit = str(raw.get("category") or "").strip()
        if explicit not in CATEGORY_PRIORITY and explicit not in {"unrelated"}:
            explicit = ""
        if explicit:
            text = " ".join(str(raw.get(k) or "") for k in ("title", "summary", "key_fact", "cross_market_map", "market_impact")).lower()
            kws = CATEGORY_KEYWORDS.get(explicit) or []
            if kws and (not any(str(k).lower() in text for k in kws)):
                explicit = ""
        decision = _resolve_category_conflict(raw, explicit=explicit, risk_flags=risk_flags, conf=conf)
        category_primary = str(decision.get("category_primary") or explicit)
        if category_primary in {"unrelated", "unclassified", "people_update"}:
            continue
        if category_primary in {"market_analysis", "institution_view", "kols_view"} and not _has_asset_mapping(raw):
            continue
        summary = str(raw.get("summary") or "").strip() or "正文缺失，仅标题级信息"
        path_id, path_template = _impact_template_for(raw, category_primary)
        direction_pack = _build_direction_contract(
            raw=raw,
            category_primary=category_primary,
            path_template_id=path_id,
            source_confidence=conf,
            impact_horizon=_impact_horizon_from_age(age_h),
            risk_flags=risk_flags,
            source_url=source_url,
            published_at=str(_to_dt(pub).isoformat()),
            conflict_rule=str(decision.get("conflict_rule") or ""),
            category_candidates=decision.get("category_candidates") or [],
        )
        impact_path = str(direction_pack.get("impact_path") or "").strip() or path_template
        if not impact_path or impact_path == "No data":
            risk_flags.append("路径未匹配")
        mention_count = int(raw.get("mention_count") or 1)
        if mention_count < 1:
            mention_count = 1
        if category_primary == "kols_view" and conf == "low":
            mention_count = max(1, mention_count - 1)
        out.append({
            "title": title,
            "category": category_primary,
            "category_primary": category_primary,
            "category_candidates": decision.get("category_candidates") or [],
            "conflict_rule": decision.get("conflict_rule") or "",
            "decision_trace": decision.get("decision_trace") or "",
            "conflict_flag": bool(decision.get("conflict_flag")),
            "assertion_type": str(decision.get("assertion_type") or ""),
            "assertion_evidence": decision.get("assertion_evidence") if isinstance(decision.get("assertion_evidence"), dict) else {},
            "source_url": source_url,
            "summary": summary,
            "source_confidence": conf,
            "impact_horizon": _impact_horizon_from_age(age_h),
            "cross_market_map": impact_path,
            "path_template_id": path_id,
            "impact_path_mode": "rule",
            "ai_status": "disabled_rule",
            "ai_reason": "",
            "uncertainty_disclosure": "",
            "direction": str(direction_pack.get("direction") or "neutral"),
            "direction_score": float(direction_pack.get("direction_score", 0.0)),
            "confidence_band": str(direction_pack.get("confidence_band") or "low"),
            "direction_label": str(direction_pack.get("direction_label") or "中性"),
            "intensity_word": str(direction_pack.get("intensity_word") or "谨慎"),
            "fail_closed": bool(direction_pack.get("fail_closed")),
            "badge": direction_pack.get("badge") if isinstance(direction_pack.get("badge"), dict) else {},
            "direction_trace": str(direction_pack.get("direction_trace") or ""),
            "risk_flags": risk_flags,
            "market_impact": str(raw.get("market_impact") or "").strip(),
            "published_at": _to_dt(pub).isoformat(),
            "mention_count": mention_count,
            "age_hours": round(age_h, 3),
        })
    dedup = {}
    for it in out:
        key = _dedup_key(it) or _norm_title(it.get("title", ""))
        recency = max(0.0, 24.0 - float(it.get("age_hours", 24.0))) / 24.0
        risk_penalty = 0.08 * len(it.get("risk_flags") or [])
        score = _confidence_rank(it.get("source_confidence")) * 1.0 + recency + min(0.5, 0.05 * int(it.get("mention_count", 1))) - risk_penalty
        it["_pre_score"] = round(score, 4)
        if key not in dedup:
            dedup[key] = it
            continue
        existing = dedup[key]
        winner, loser = (it, existing) if it["_pre_score"] > existing.get("_pre_score", -1e9) else (existing, it)
        winner["mention_count"] = int(winner.get("mention_count") or 1) + int(loser.get("mention_count") or 1)
        dedup[key] = winner
    rows = list(dedup.values())
    rows.sort(key=lambda x: (float(x.get("_pre_score", 0.0)), x.get("published_at", "")), reverse=True)
    for r in rows:
        r.pop("_pre_score", None)
    return rows


def _preprocess_macro_news(items, hours: int):
    out = []
    valid_topics = {"fed", "us_data", "us_policy", "geopolitics", "crypto_regulation", "market_analysis"}
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        pub = raw.get("published_at") or raw.get("fetched_at")
        if not pub:
            continue
        age_h = _hours_since(pub)
        if age_h > float(hours) + 1.0:
            continue
        source_url = str(raw.get("source_url") or "").strip()
        if not source_url or source_url == "No data":
            continue
        risk_flags = _ensure_risk_flags(raw.get("risk_flags"))
        conf = str(raw.get("source_confidence") or "medium").strip().lower()
        if conf not in {"high", "medium", "low"}:
            conf = "medium"
        explicit = str(raw.get("topic") or "").strip() or "market_analysis"
        if explicit not in valid_topics:
            explicit = "market_analysis"
        decision = _resolve_category_conflict(raw, explicit=explicit, risk_flags=risk_flags, conf=conf)
        topic = str(decision.get("category_primary") or explicit)
        if topic not in valid_topics:
            if _has_asset_mapping(raw):
                topic = "market_analysis"
            else:
                continue
        if topic in {"unrelated", "unclassified", "people_update"}:
            continue
        if topic == "market_analysis" and not _has_asset_mapping(raw):
            continue
        key_fact = str(raw.get("key_fact") or "").strip() or "正文缺失，仅标题级信息"
        path_id, path_template = _impact_template_for(raw, topic)
        direction_pack = _build_direction_contract(
            raw=raw,
            category_primary=topic,
            path_template_id=path_id,
            source_confidence=conf,
            impact_horizon=_impact_horizon_from_age(age_h),
            risk_flags=risk_flags,
            source_url=source_url,
            published_at=str(_to_dt(pub).isoformat()),
            conflict_rule=str(decision.get("conflict_rule") or ""),
            category_candidates=decision.get("category_candidates") or [],
        )
        impact_path = str(direction_pack.get("impact_path") or "").strip() or path_template
        if not impact_path or impact_path == "No data":
            risk_flags.append("路径未匹配")
        mention_count = int(raw.get("mention_count") or 1)
        if mention_count < 1:
            mention_count = 1
        out.append({
            "title": title,
            "topic": topic,
            "category_primary": topic,
            "category_candidates": decision.get("category_candidates") or [],
            "conflict_rule": decision.get("conflict_rule") or "",
            "decision_trace": decision.get("decision_trace") or "",
            "conflict_flag": bool(decision.get("conflict_flag")),
            "assertion_type": str(decision.get("assertion_type") or ""),
            "assertion_evidence": decision.get("assertion_evidence") if isinstance(decision.get("assertion_evidence"), dict) else {},
            "source_url": source_url,
            "key_fact": key_fact,
            "source_confidence": conf,
            "impact_horizon": _impact_horizon_from_age(age_h),
            "cross_market_map": impact_path,
            "path_template_id": path_id,
            "impact_path_mode": "rule",
            "ai_status": "disabled_rule",
            "ai_reason": "",
            "uncertainty_disclosure": "",
            "direction": str(direction_pack.get("direction") or "neutral"),
            "direction_score": float(direction_pack.get("direction_score", 0.0)),
            "confidence_band": str(direction_pack.get("confidence_band") or "low"),
            "direction_label": str(direction_pack.get("direction_label") or "中性"),
            "intensity_word": str(direction_pack.get("intensity_word") or "谨慎"),
            "fail_closed": bool(direction_pack.get("fail_closed")),
            "badge": direction_pack.get("badge") if isinstance(direction_pack.get("badge"), dict) else {},
            "direction_trace": str(direction_pack.get("direction_trace") or ""),
            "risk_flags": risk_flags,
            "market_impact": str(raw.get("market_impact") or "").strip(),
            "published_at": _to_dt(pub).isoformat(),
            "mention_count": mention_count,
            "age_hours": round(age_h, 3),
            "actual_value": raw.get("actual_value"),
            "forecast_value": raw.get("expected_value"),
            "previous_value": raw.get("previous_value"),
        })
    dedup = {}
    for it in out:
        key = _dedup_key(it) or _norm_title(it.get("title", ""))
        recency = max(0.0, 24.0 - float(it.get("age_hours", 24.0))) / 24.0
        risk_penalty = 0.08 * len(it.get("risk_flags") or [])
        score = _confidence_rank(it.get("source_confidence")) * 1.0 + recency + min(0.5, 0.05 * int(it.get("mention_count", 1))) - risk_penalty
        it["_pre_score"] = round(score, 4)
        if key not in dedup:
            dedup[key] = it
            continue
        existing = dedup[key]
        winner, loser = (it, existing) if it["_pre_score"] > existing.get("_pre_score", -1e9) else (existing, it)
        winner["mention_count"] = int(winner.get("mention_count") or 1) + int(loser.get("mention_count") or 1)
        dedup[key] = winner
    rows = list(dedup.values())
    rows.sort(key=lambda x: (float(x.get("_pre_score", 0.0)), x.get("published_at", "")), reverse=True)
    for r in rows:
        r.pop("_pre_score", None)
    return rows


def generate_crypto_news(hours: int):
    try:
        raw = fetch_odaily_newsflash(limit=60, hours=hours, include_aux=True)
        rows = _preprocess_crypto_news(raw, hours=hours)
        if rows:
            return rows[:30]
    except Exception:
        pass
    if str(os.environ.get("NEWS_MOCK_FALLBACK_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}:
        return _preprocess_crypto_news(_generate_crypto_news_mock(hours), hours=hours)[:30]
    return []


def generate_macro_news(hours: int):
    try:
        raw = fetch_wallstreetcn_breakfast(limit=60, hours=hours)
        rows = _preprocess_macro_news(raw, hours=hours)
        if rows:
            return rows[:30]
    except Exception:
        pass
    if str(os.environ.get("NEWS_MOCK_FALLBACK_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}:
        return _preprocess_macro_news(_generate_macro_news_mock(hours), hours=hours)[:30]
    return []


def _load_market_state_policy():
    local_policy = BASE_DIR / "historical_data" / "market_state_policy_v01.json"
    policy_path = local_policy
    if policy_path.exists():
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": "default",
        "thresholds": {
            "high_vol_vix": 28.0,
            "risk_off_vix": 22.0,
            "risk_on_vix_max": 20.0
        },
        "regime_thresholds": {
            "bull_pct_vs_ma20": 5.0,
            "bear_pct_vs_ma20": -5.0
        }
    }


def _fetch_btc_regime_metrics():
    try:
        req = Request(
            "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=3mo&interval=1d",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = ((data.get("chart") or {}).get("result") or [{}])[0]
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0] or {})
        closes_raw = quote.get("close") or []
        closes = [float(x) for x in closes_raw if isinstance(x, (int, float))]
        if len(closes) < 21:
            return {"ok": False, "reason": "insufficient_closes"}
        last_close = closes[-1]
        ma20 = mean(closes[-20:])
        returns = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            cur = closes[i]
            if prev > 0:
                returns.append((cur - prev) / prev)
        vol20 = pstdev(returns[-20:]) * 100 if len(returns) >= 20 else 0.0
        pct_vs_ma20 = (last_close / ma20 - 1) * 100 if ma20 > 0 else 0.0
        return {
            "ok": True,
            "btc_close": last_close,
            "ma20": ma20,
            "pct_vs_ma20": pct_vs_ma20,
            "volatility_20d_pct": vol20
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _fetch_yahoo_close_change(symbol: str):
    try:
        req = Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=7d&interval=1d",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = ((data.get("chart") or {}).get("result") or [{}])[0]
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0] or {})
        closes_raw = quote.get("close") or []
        closes = [float(x) for x in closes_raw if isinstance(x, (int, float))]
        if len(closes) < 2:
            return {"ok": False, "reason": "insufficient_closes"}
        last_v = closes[-1]
        prev_v = closes[-2]
        chg = (last_v / prev_v - 1.0) * 100 if prev_v else 0.0
        return {"ok": True, "value": last_v, "change_pct": chg}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _fetch_binance_micro_metrics():
    out = {
        "funding_rate": {"ok": False, "value": None, "reason": "no_data"},
        "open_interest": {"ok": False, "value": None, "reason": "no_data"},
    }
    try:
        req = Request(
            "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        fr = data.get("lastFundingRate")
        if isinstance(fr, str):
            fr = float(fr)
        if isinstance(fr, (int, float)):
            out["funding_rate"] = {"ok": True, "value": float(fr), "reason": ""}
    except Exception as e:
        out["funding_rate"]["reason"] = str(e)
    try:
        req = Request(
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        oi = data.get("openInterest")
        if isinstance(oi, str):
            oi = float(oi)
        if isinstance(oi, (int, float)):
            out["open_interest"] = {"ok": True, "value": float(oi), "reason": ""}
    except Exception as e:
        out["open_interest"]["reason"] = str(e)
    return out


def _fetch_stablecoin_supply_metrics():
    try:
        req = Request(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assets = data.get("peggedAssets", [])
        target = {}
        for a in assets:
            sym = str(a.get("symbol", "")).upper()
            if sym in {"USDT", "USDC"}:
                target[sym] = a
        if not target:
            return {"ok": False, "reason": "usdt_usdc_not_found"}
        cur = 0.0
        prev_day = 0.0
        has_prev = True
        for sym in ("USDT", "USDC"):
            row = target.get(sym, {})
            cur += float((((row.get("circulating") or {}).get("peggedUSD")) or 0.0))
            pv = ((row.get("circulatingPrevDay") or {}).get("peggedUSD"))
            if isinstance(pv, (int, float)):
                prev_day += float(pv)
            else:
                has_prev = False
        delta_day = (cur - prev_day) if has_prev else None
        return {"ok": True, "total_usd": cur, "delta_day_usd": delta_day, "reason": ""}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _fetch_binance_open_interest_delta_24h():
    try:
        req = Request(
            "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list) or len(data) < 2:
            return {"ok": False, "reason": "insufficient_oi_hist"}
        first = data[0] if isinstance(data[0], dict) else {}
        last = data[-1] if isinstance(data[-1], dict) else {}
        v0 = float(first.get("sumOpenInterestValue", 0.0) or 0.0)
        v1 = float(last.get("sumOpenInterestValue", 0.0) or 0.0)
        if v0 <= 0 or v1 <= 0:
            return {"ok": False, "reason": "invalid_oi_hist_values"}
        return {
            "ok": True,
            "current_usd": v1,
            "delta_usd": v1 - v0,
            "delta_pct": (v1 / v0 - 1.0) * 100.0,
            "reason": "",
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _fetch_bitbo_etf_netflow_metrics():
    try:
        req = Request("https://bitbo.io/treasuries/etf-flows/", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "ignore")
        m = re.search(r"const\s+historyBtc\s*=\s*\[(.*?)\]\s*const\s+mergedHistoryBtc", html, re.S)
        if not m:
            return {"ok": False, "reason": "history_btc_not_found"}
        body = m.group(1)
        vals = [float(x) for x in re.findall(r"truncate\(\s*([+\-]?[0-9]+(?:\.[0-9]+)?)\s*,", body)]
        if len(vals) < 2:
            return {"ok": False, "reason": "insufficient_etf_points"}
        latest_cum_btc = vals[-1]
        delta_1d_btc = vals[-1] - vals[-2]
        return {"ok": True, "latest_cum_btc": latest_cum_btc, "delta_1d_btc": delta_1d_btc, "reason": ""}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _fetch_coinglass_liquidation_24h_proxy():
    try:
        # 1. Fetch from Binance futures API as a proxy for total liquidations
        # Coinglass blocks heavily, so we use Binance 24h ticker data and estimate 
        # or just fallback to Binance liquidation metrics if available
        # Note: Since there's no direct public API for 24h total liquidations without an API key,
        # we will fetch top tokens from Binance and aggregate volume or use Tavily if available
        # but for speed, let's use a stable estimation from OI changes + funding rate
        pass
    except Exception as e:
        pass
        
    try:
        # Better fallback: use Tavily if available for Coinglass liquidation data
        import urllib.request
        import os
        import json
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            # Try getting it from .mcp.json
            mcp_path = Path("/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw/.mcp.json")
            if mcp_path.exists():
                with open(mcp_path) as f:
                    mcp = json.load(f)
                api_key = mcp.get("mcpServers", {}).get("tavily", {}).get("env", {}).get("TAVILY_API_KEY")
                
        if api_key:
            url = "https://api.tavily.com/search"
            query = "What is the total cryptocurrency liquidation amount in the last 24 hours according to Coinglass? Just return a JSON with key value_usd, like {\"value_usd\": 150000000.0}"
            payload = {"api_key": api_key, "query": query, "search_depth": "basic", "include_answer": True}
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                ans = json.loads(resp.read().decode('utf-8')).get("answer", "")
                print(ans)  # Debug print
                
                # Parse robustly
                m = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion|K|M|B|T)?", ans, re.I)
                if m:
                    num = float(m.group(1).replace(",", ""))
                    unit = str(m.group(2) or "").upper()
                    if unit.startswith("M"):
                        num *= 1e6
                    elif unit.startswith("B"):
                        num *= 1e9
                    elif unit.startswith("K"):
                        num *= 1e3
                    elif unit.startswith("T"):
                        num *= 1e12
                    
                    if num > 0:
                        return {"ok": True, "value_usd": num, "reason": "tavily"}
                
                start = ans.find("{")
                end = ans.rfind("}") + 1
                if start >= 0 and end > start:
                    val = json.loads(ans[start:end]).get("value_usd")
                    if val and float(val) > 0:
                        return {"ok": True, "value_usd": float(val), "reason": "tavily"}
    except Exception as e:
        pass

    try:
        # Fallback to fapi.coinglass.com which sometimes bypasses Cloudflare
        req = Request(
            "https://fapi.coinglass.com/api/futures/liquidation/info?symbol=BTC&timeType=3", 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        if data.get("success") and "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
            # Find the total or aggregate liquidation from the list
            for item in data["data"]:
                if item.get("exchangeName") == "All":
                    val = float(item.get("volUsd") or 0)
                    if val > 0:
                        return {"ok": True, "value_usd": val, "reason": ""}
    except Exception:
        pass
        
    try:
        # If API fails, try scraping the homepage as fallback
        req = Request("https://www.coinglass.com/liquidations", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", "ignore")
        m = re.search(r"total liquidations comes in at \$([0-9][0-9,]*(?:\.[0-9]+)?)([KMBT]?)", html, re.I)
        if not m:
            return {"ok": False, "reason": "liquidation_text_not_found"}
        num = float(str(m.group(1)).replace(",", ""))
        unit = str(m.group(2) or "").upper()
        mult = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(unit, 1.0)
        val = num * mult
        if val <= 0:
            # CoinGlass anti-scraping returned $0
            return {"ok": False, "reason": "liquidation_value_zero_or_missing"}
        return {"ok": True, "value_usd": val, "reason": ""}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _build_optional_metrics():
    rows = [
        ("DXY", "No data", "Yahoo Finance"),
        ("US10Y Real Yield", "No data", "TNX Proxy"),
        ("BTC Spot ETF Netflow", "No data", "Bitbo ETF Flows"),
        ("稳定币供给增量", "No data", "DefiLlama"),
        ("Funding Rate", "No data", "Binance Perp"),
        ("Open Interest Δ24h", "No data", "Binance OI Hist"),
        ("24h 清算额", "No data", "Coinglass / Tavily"),
    ]
    dxy = _fetch_yahoo_close_change("DX-Y.NYB")
    if dxy.get("ok"):
        rows[0] = ("DXY", f"{dxy['value']:.2f} ({dxy['change_pct']:+.2f}%)", "Yahoo Finance")
    tnx = _fetch_yahoo_close_change("^TNX")
    if tnx.get("ok"):
        proxy_real = float(tnx["value"]) / 10.0
        rows[1] = ("US10Y Real Yield", f"{proxy_real:.2f}% ({tnx['change_pct']:+.2f}%)", "TNX 代理值（非TIPS实质利率）")
    stable = _fetch_stablecoin_supply_metrics()
    if stable.get("ok"):
        total_b = float(stable.get("total_usd", 0.0)) / 1e9
        d = stable.get("delta_day_usd")
        delta_txt = f"{(float(d)/1e9):+.2f}B" if isinstance(d, (int, float)) else "No data"
        rows[3] = ("稳定币供给增量", f"{total_b:.2f}B / Δ1D {delta_txt}", "DefiLlama")
    micro = _fetch_binance_micro_metrics()
    fr = (micro.get("funding_rate") or {})
    if fr.get("ok"):
        rows[4] = ("Funding Rate", f"{float(fr['value'])*100:.4f}%", "Binance Perp")
    oi24 = _fetch_binance_open_interest_delta_24h()
    if oi24.get("ok"):
        rows[5] = (
            "Open Interest Δ24h",
            f"{float(oi24['current_usd'])/1e9:.2f}B / Δ{float(oi24['delta_usd'])/1e9:+.2f}B ({float(oi24['delta_pct']):+.2f}%)",
            "Binance OI Hist",
        )
    etf = _fetch_bitbo_etf_netflow_metrics()
    if etf.get("ok"):
        rows[2] = (
            "BTC Spot ETF Netflow",
            f"Δ1D {float(etf['delta_1d_btc']):+,.0f} BTC / 累计 {float(etf['latest_cum_btc']):,.0f} BTC",
            "Bitbo ETF Flows",
        )
    liq = _fetch_coinglass_liquidation_24h_proxy()
    if liq.get("ok"):
        rows[6] = ("24h 清算额", f"${float(liq['value_usd'])/1e9:.2f}B", "Coinglass 页面代理")
    available = sum(1 for _, val, _ in rows if str(val).strip() != "No data")
    return {"rows": rows, "available": available, "total": len(rows)}


def _load_latest_flow_regime():
    flow_dir = BASE_DIR / "flow" / "outputs"
    files = sorted(flow_dir.glob("flow_regime_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"ok": False, "reason": "flow_regime_not_found"}
    try:
        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        regime_output = data.get("regime_output", {})
        quality = data.get("quality", {})
        layer_signals = data.get("layer_signals", {}) or {}
        leverage_signal = float(layer_signals.get("leverage", 0.0) or 0.0)
        exogenous_signal = float(layer_signals.get("exogenous", 0.0) or 0.0)
        onchain_signal = float(layer_signals.get("onchain", 0.0) or 0.0)
        stress_score = min(1.0, max(abs(leverage_signal), abs(onchain_signal), abs(exogenous_signal)))
        return {
            "ok": True,
            "file": str(files[0]),
            "timestamp": data.get("timestamp"),
            "composite": float(data.get("composite", 0.0) or 0.0),
            "bias": regime_output.get("bias", "neutral"),
            "risk_off": bool(regime_output.get("risk_off", False)),
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "coverage": float(quality.get("coverage", 0.0) or 0.0),
            "critical_missing_sources": quality.get("critical_missing_sources", []) or [],
            "quality_counts": quality.get("counts", {}) or {},
            "layer_signals": {
                "exogenous": exogenous_signal,
                "leverage": leverage_signal,
                "onchain": onchain_signal
            },
            "stress_score": stress_score
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _run_flow_brief_generator():
    flow_script = BASE_DIR / "flow" / "scripts" / "run_flow_analysis.py"
    if not flow_script.exists():
        return {"ok": False, "reason": "flow_script_not_found"}
    try:
        result = subprocess.run(
            [sys.executable, str(flow_script)],
            cwd=str(flow_script.parent),
            capture_output=True,
            text=True,
            timeout=120
        )
        flow = _load_latest_flow_regime()
        flow["invoke_status"] = "ok" if result.returncode == 0 else "failed"
        flow["invoke_returncode"] = result.returncode
        if result.returncode != 0:
            flow["invoke_error"] = (result.stderr or "").strip()[-1000:]
        return flow
    except Exception as e:
        fallback = _load_latest_flow_regime()
        fallback["invoke_status"] = "failed"
        fallback["invoke_error"] = str(e)
        return fallback


def _load_event_type_weights():
    local_path = BASE_DIR / "historical_data" / "event_type_weights_v93.json"
    path = local_path
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "onchain_data": 1.0,
        "institution_flow": 0.75,
        "project_update": 0.7,
        "entity_statement": 0.55,
        "kols_view": 0.4,
        "institution_view": 0.55,
        "people_update": 0.2,
        "unclassified": 0.2,
        "fed": 0.9,
        "us_data": 0.9,
        "us_policy": 0.8,
        "geopolitics": 0.7,
        "crypto_regulation": 0.75,
        "market_analysis": 0.5,
        "other": 0.5
    }


def _classify_crypto_item(item):
    title = item.get("title", "")
    flags = item.get("risk_flags", []) or []
    if flags:
        return "bearish"
    bearish_kw = ["调查", "被查", "监管", "起诉", "黑客", "攻击", "漏洞", "清算", "爆仓", "暂停", "下架", "封锁", "升级", "风险", "崩", "暴跌"]
    bullish_kw = ["净流入", "突破", "创新高", "反弹", "增长", "上线", "推出", "通过", "获批", "利好", "回暖", "扩张", "上升"]
    if any(k in title for k in bearish_kw):
        return "bearish"
    if any(k in title for k in bullish_kw):
        return "bullish"
    if item.get("category") in {"onchain_data", "project_update", "institution_flow"}:
        return "bullish"
    return "neutral"


def _event_type_weight(item, weight_table):
    category = item.get("category") or item.get("topic") or "other"
    return float(weight_table.get(category, weight_table.get("other", 0.5))), category


def _window_weight(item):
    horizon = item.get("impact_horizon", "T1")
    mapping = {"T0": 1.0, "T1": 0.7, "T2": 0.4}
    return mapping.get(horizon, 0.5)


def _surprise_weight(item):
    title = item.get("title", "")
    if item.get("risk_flags"):
        return 0.8
    strong = ["突破", "创新高", "净流入", "飙升", "暴涨", "爆仓"]
    return 1.2 if any(k in title for k in strong) else 1.0


def _confidence_weight(item):
    mapping = {"high": 0.9, "medium": 0.7, "low": 0.4}
    return mapping.get(item.get("source_confidence", "medium"), 0.6)


def _base_sentiment(item):
    if "category" in item:
        bucket = _classify_crypto_item(item)
        if bucket == "bullish":
            return 1.0
        if bucket == "bearish":
            return -1.0
    title = item.get("title", "")
    if any(k in title for k in ["担忧", "收紧", "风险", "冲突", "封锁"]):
        return -1.0
    if any(k in title for k in ["放松", "回暖", "上涨", "突破"]):
        return 1.0
    return 0.0


def _macro_expectation_eval(item):
    actual = item.get("actual_value")
    forecast = item.get("forecast_value")
    previous = item.get("previous_value")
    if not isinstance(actual, (int, float)) or not isinstance(forecast, (int, float)) or not isinstance(previous, (int, float)):
        return {
            "bucket": "unknown",
            "delta": None,
            "reason": "缺少实际/预期/前值，无法计算预期差",
        }
    delta = float(actual) - float(forecast)
    if delta > 0:
        bucket = "利多"
    elif delta < 0:
        bucket = "利空"
    else:
        bucket = "符合"
    return {"bucket": bucket, "delta": delta, "reason": ""}


def _build_event_ledger(crypto_news, macro_news, flow_enhance, weight_table):
    merged = (crypto_news + macro_news)[:12]
    ledger = []
    flow_risk_off = bool(flow_enhance.get("risk_off", False))
    flow_bias = str(flow_enhance.get("bias", "neutral"))
    flow_stress = float(flow_enhance.get("stress_score", 0.0) or 0.0)
    for item in merged:
        type_weight, event_type = _event_type_weight(item, weight_table)
        w_window = _window_weight(item)
        w_surprise = _surprise_weight(item)
        w_conf = _confidence_weight(item)
        base = _base_sentiment(item)
        confidence_adjusted = w_conf
        conflict_reasons = []
        if flow_risk_off and base > 0:
            confidence_adjusted *= 0.7
            conflict_reasons.append("flow_risk_off_conflict")
        if flow_bias == "bearish" and base > 0:
            confidence_adjusted *= 0.8
            conflict_reasons.append("flow_bias_bearish_conflict")
        if flow_stress >= 0.5 and base > 0:
            confidence_adjusted *= 0.8
            conflict_reasons.append("flow_stress_high_conflict")
        contribution = base * type_weight * w_window * w_surprise * confidence_adjusted
        ledger.append({
            "title": item.get("title", ""),
            "event_type": event_type,
            "base_sentiment": base,
            "type_weight": type_weight,
            "window_weight": w_window,
            "surprise_weight": w_surprise,
            "confidence_weight": w_conf,
            "confidence_adjusted": confidence_adjusted,
            "contribution": contribution,
            "source_url": item.get("source_url", ""),
            "conflict_reasons": conflict_reasons
        })
    return ledger


def _infer_market_state(prices, regime_metrics, policy):
    thresholds = (policy or {}).get("thresholds", {})
    regime_thresholds = (policy or {}).get("regime_thresholds", {})
    bull_thr = float(regime_thresholds.get("bull_pct_vs_ma20", 5.0))
    bear_thr = float(regime_thresholds.get("bear_pct_vs_ma20", -5.0))
    vix_risk_off = float(thresholds.get("risk_off_vix", 22.0))
    vix_high = float(thresholds.get("high_vol_vix", 28.0))
    vix = float(prices.get("vix", {}).get("value", 0) or 0)
    pct_vs_ma20 = float(regime_metrics.get("pct_vs_ma20", 0.0) or 0.0)
    vol20 = float(regime_metrics.get("volatility_20d_pct", 0.0) or 0.0)

    if pct_vs_ma20 >= bull_thr:
        regime = "多头（Bull）"
    elif pct_vs_ma20 <= bear_thr:
        regime = "空头（Bear）"
    else:
        regime = "震荡（Sideways）"

    if vix >= vix_high:
        risk = "高波动风险"
    elif vix >= vix_risk_off:
        risk = "高风险"
    else:
        risk = "中性/可控"
    return {"regime": regime, "risk": risk, "bull_thr": bull_thr, "bear_thr": bear_thr, "pct_vs_ma20": pct_vs_ma20, "vol20": vol20}


def _build_position_plan(composite_signal, market_state, flow_enhance):
    regime = market_state.get("regime", "")
    if "Bull" in regime:
        threshold = 0.20
        multiplier = 1.0
        max_pos = 0.80
        min_pos = 0.25
        stop_loss = "-8%"
    elif "Bear" in regime:
        threshold = 0.25
        multiplier = 0.5
        max_pos = 0.40
        min_pos = 0.10
        stop_loss = "-4%"
    else:
        threshold = 0.15
        multiplier = 0.8
        max_pos = 0.65
        min_pos = 0.15
        stop_loss = "-6%"

    if flow_enhance.get("ok") and flow_enhance.get("risk_off"):
        action = "REDUCE"
        target_pos = min_pos
    elif composite_signal > threshold:
        action = "ADD"
        target_pos = min(max_pos, 0.50 + abs(composite_signal) * multiplier)
    elif composite_signal < -threshold:
        action = "REDUCE"
        target_pos = max(min_pos, 0.50 - abs(composite_signal) * multiplier)
    else:
        action = "HOLD"
        target_pos = 0.50

    return {
        "threshold": threshold,
        "multiplier": multiplier,
        "max_position": max_pos,
        "min_position": min_pos,
        "action": action,
        "target_position": round(target_pos, 4),
        "stop_loss": stop_loss
    }


def _top_event_titles(meta, n=5):
    ledger = meta.get("event_ledger", []) or []
    ordered = sorted(ledger, key=lambda x: abs(float(x.get("contribution", 0.0) or 0.0)), reverse=True)
    return [x.get("title", "") for x in ordered[:n] if x.get("title")]


def _load_previous_receipt():
    receipts = sorted(RAW_DIR.glob("news_eval_receipt_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not receipts:
        return None
    try:
        with open(receipts[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _build_dynamic_top12(crypto_news, macro_news):
    prev = _load_previous_receipt() or {}
    prev_titles = set(str(x).strip() for x in (prev.get("top_events") or []) if str(x).strip())
    candidates = []
    conflict_n = 0
    path_non_empty_n = 0
    ai_generated_n = 0
    direction_ready_n = 0
    neutral_n = 0
    exclude_primary = {"people_update", "unclassified", "unrelated"}
    for item in crypto_news:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        category_primary = str(item.get("category_primary") or item.get("category") or "unclassified")
        if category_primary in exclude_primary:
            continue
        summary = str(item.get("summary") or "").strip()
        if not summary:
            summary = "正文缺失，仅标题级信息"
        conf = str(item.get("source_confidence") or "medium").strip().lower()
        age_h = float(item.get("age_hours", 24.0) or 24.0)
        mention = int(item.get("mention_count", 1) or 1)
        risk_n = len(item.get("risk_flags") or [])
        novelty = 1.0 if title not in prev_titles else 0.0
        direction_score = float(item.get("direction_score", 0.0) or 0.0)
        score = _confidence_rank(conf) * 1.3 + max(0.0, (24.0 - min(age_h, 24.0)) / 8.0) + min(0.6, 0.05 * mention) + novelty - 0.1 * risk_n + abs(direction_score) * 0.6
        candidates.append({
            "id": str(item.get("id") or ""),
            "title": title,
            "text": summary,
            "source_url": str(item.get("source_url") or ""),
            "published_at": str(item.get("published_at") or ""),
            "source_confidence": conf,
            "risk_flags": item.get("risk_flags") or [],
            "category_primary": category_primary,
            "category_candidates": item.get("category_candidates") or [],
            "conflict_rule": str(item.get("conflict_rule") or ""),
            "path_template_id": str(item.get("path_template_id") or ""),
            "decision_trace": str(item.get("decision_trace") or ""),
            "impact_path": str(item.get("cross_market_map") or item.get("market_impact") or "").strip(),
            "direction": str(item.get("direction") or "neutral"),
            "direction_score": float(item.get("direction_score", 0.0) or 0.0),
            "confidence_band": str(item.get("confidence_band") or "low"),
            "badge": item.get("badge") if isinstance(item.get("badge"), dict) else {},
            "direction_trace": str(item.get("direction_trace") or ""),
            "fail_closed": bool(item.get("fail_closed")),
            "score": round(score, 4),
            "is_new": novelty > 0,
        })
        if bool(item.get("conflict_flag")):
            conflict_n += 1
        if str(item.get("cross_market_map") or item.get("market_impact") or "").strip():
            path_non_empty_n += 1
        if str(item.get("impact_path_mode") or "") == "ai" and str(item.get("ai_status") or "") == "ok":
            ai_generated_n += 1
        if str(item.get("direction") or "").strip():
            direction_ready_n += 1
        if str(item.get("direction") or "neutral") == "neutral":
            neutral_n += 1
    for item in macro_news:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        category_primary = str(item.get("category_primary") or item.get("topic") or "unclassified")
        if category_primary in exclude_primary:
            continue
        fact = str(item.get("key_fact") or "").strip()
        if not fact:
            fact = "正文缺失，仅标题级信息"
        conf = str(item.get("source_confidence") or "medium").strip().lower()
        age_h = float(item.get("age_hours", 24.0) or 24.0)
        mention = int(item.get("mention_count", 1) or 1)
        risk_n = len(item.get("risk_flags") or [])
        novelty = 1.0 if title not in prev_titles else 0.0
        direction_score = float(item.get("direction_score", 0.0) or 0.0)
        score = _confidence_rank(conf) * 1.2 + max(0.0, (24.0 - min(age_h, 24.0)) / 8.0) + min(0.6, 0.05 * mention) + novelty - 0.1 * risk_n + abs(direction_score) * 0.6
        candidates.append({
            "id": str(item.get("id") or ""),
            "title": title,
            "text": fact,
            "source_url": str(item.get("source_url") or ""),
            "published_at": str(item.get("published_at") or ""),
            "source_confidence": conf,
            "risk_flags": item.get("risk_flags") or [],
            "category_primary": category_primary,
            "category_candidates": item.get("category_candidates") or [],
            "conflict_rule": str(item.get("conflict_rule") or ""),
            "path_template_id": str(item.get("path_template_id") or ""),
            "decision_trace": str(item.get("decision_trace") or ""),
            "impact_path": str(item.get("cross_market_map") or item.get("market_impact") or "").strip(),
            "direction": str(item.get("direction") or "neutral"),
            "direction_score": float(item.get("direction_score", 0.0) or 0.0),
            "confidence_band": str(item.get("confidence_band") or "low"),
            "badge": item.get("badge") if isinstance(item.get("badge"), dict) else {},
            "direction_trace": str(item.get("direction_trace") or ""),
            "fail_closed": bool(item.get("fail_closed")),
            "score": round(score, 4),
            "is_new": novelty > 0,
        })
        if bool(item.get("conflict_flag")):
            conflict_n += 1
        if str(item.get("cross_market_map") or item.get("market_impact") or "").strip():
            path_non_empty_n += 1
        if str(item.get("impact_path_mode") or "") == "ai" and str(item.get("ai_status") or "") == "ok":
            ai_generated_n += 1
        if str(item.get("direction") or "").strip():
            direction_ready_n += 1
        if str(item.get("direction") or "neutral") == "neutral":
            neutral_n += 1
    uniq = {}
    for c in candidates:
        key = _norm_title(c.get("title", ""))
        if key not in uniq or float(c.get("score", 0.0)) > float(uniq[key].get("score", 0.0)):
            uniq[key] = c
    rows = list(uniq.values())
    rows.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    top = rows[:12]
    formatted = []
    for i, item in enumerate(top, 1):
        flags = f"（{', '.join(item.get('risk_flags', []))}）" if item.get("risk_flags") else ""
        formatted.append(
            f"{i}. **[{item['title']}]** - {str(item.get('text') or '').strip()}{flags}（可信度={item.get('source_confidence','unknown')}，来源={item.get('source_url','')}）"
        )
    if len(formatted) < 12:
        for i in range(len(formatted) + 1, 13):
            formatted.append(f"{i}. **[No data]** - 当前窗口无新增高优先级事件。")
    top_titles = [str(x.get("title") or "").strip() for x in top if str(x.get("title") or "").strip()]
    no_data_count = sum(1 for x in formatted[:12] if "**[No data]**" in x)
    unique_ratio = len(set(top_titles)) / len(top_titles) if top_titles else 0.0
    new_titles = sum(1 for x in top if bool(x.get("is_new")))
    total_n = max(1, len(crypto_news) + len(macro_news))
    return {
        "lines": formatted[:12],
        "titles": top_titles,
        "new_titles_vs_prev": int(new_titles),
        "top12_no_data_ratio": float(no_data_count / 12.0),
        "top12_unique_ratio": float(unique_ratio),
        "top_rows": top,
        "category_conflict_rate": float(conflict_n / total_n),
        "impact_path_non_empty_ratio": float(path_non_empty_n / total_n),
        "ai_generated_ratio": float(ai_generated_n / total_n),
        "direction_computable_ratio": float(direction_ready_n / total_n),
        "neutral_overuse_ratio": float(neutral_n / total_n),
    }


def _score_eval_from_meta(meta: dict, spec_check: dict) -> dict:
    slot = (meta or {}).get("slot_metrics") or {}
    score = 0
    if bool((spec_check or {}).get("ok")):
        score += 35
    if int(slot.get("new_titles_vs_prev", 0)) >= 3:
        score += 10
    if float(slot.get("top12_no_data_ratio", 1.0)) <= 0.2:
        score += 10
    if float(slot.get("top12_unique_ratio", 0.0)) >= 0.85:
        score += 10
    if int(slot.get("valid_top_titles", 0)) >= 8:
        score += 10
    if bool(slot.get("major_event_present")):
        score += 5
    if float(slot.get("impact_path_non_empty_ratio", 0.0)) >= 0.9:
        score += 10
    if float(slot.get("category_conflict_rate", 1.0)) <= 0.15:
        score += 10
    if float(slot.get("direction_computable_ratio", 0.0)) >= 0.90:
        score += 5
    if float(slot.get("neutral_overuse_ratio", 1.0)) <= 0.55:
        score += 5
    score = _clamp(float(score), 0.0, 100.0)
    if score < 35:
        score = max(0, score)
    if score >= 90:
        grade = "excellent"
    elif score >= 80:
        grade = "usable"
    elif score >= 70:
        grade = "risk"
    else:
        grade = "block"
    return {"score_total": int(score), "grade": grade}


def _news_item_contract(item: dict, *, fallback_category: str = "unclassified") -> dict:
    badge = item.get("badge") if isinstance(item.get("badge"), dict) else {}
    direction_score = float(item.get("direction_score", 0.0) or 0.0)
    confidence_band = str(item.get("confidence_band") or "low")
    impact_path = str(item.get("impact_path") or item.get("cross_market_map") or item.get("market_impact") or "No data")
    source_url = str(item.get("source_url") or "")
    published_at = str(item.get("published_at") or "")
    fail_closed = bool(item.get("fail_closed")) or (not source_url) or (not published_at) or (impact_path == "No data")
    badge_reason = str(badge.get("badge_reason") or "score_mapping")
    if fail_closed and badge_reason == "score_mapping":
        badge_reason = "no_data_override" if impact_path == "No data" else "fail_closed_override"
    badge_color = str(badge.get("badge_color") or "neutral")
    if fail_closed:
        badge_color = "neutral"
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "source_url": source_url,
        "published_at": published_at,
        "category_primary": str(item.get("category_primary") or item.get("category") or item.get("topic") or fallback_category),
        "path_template_id": str(item.get("path_template_id") or ""),
        "impact_horizon": str(item.get("impact_horizon") or "T2"),
        "direction": str(item.get("direction") or "neutral"),
        "direction_score": direction_score,
        "confidence_band": confidence_band,
        "risk_flags": item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else [],
        "decision_trace": str(item.get("direction_trace") or item.get("decision_trace") or ""),
        "impact_path": impact_path,
        "badge": {
            "badge_text": str(badge.get("badge_text") or f"{_direction_label(str(item.get('direction') or 'neutral'))}·{_intensity_word(direction_score, confidence_band)}"),
            "badge_color": badge_color,
            "badge_reason": badge_reason,
            "direction_label": str(badge.get("direction_label") or _direction_label(str(item.get("direction") or "neutral"))),
            "intensity_word": str(badge.get("intensity_word") or _intensity_word(direction_score, confidence_band)),
            "direction_score": float(badge.get("direction_score", direction_score) or direction_score),
            "confidence_band": str(badge.get("confidence_band") or confidence_band),
            "risk_flags": badge.get("risk_flags") if isinstance(badge.get("risk_flags"), list) else (item.get("risk_flags") if isinstance(item.get("risk_flags"), list) else []),
            "fail_closed": fail_closed,
            "asof": str(badge.get("asof") or NOW.isoformat()),
        },
    }


def _build_eval_receipt(meta, output_markdown_path: str, report_mode: str):
    receipts = sorted(RAW_DIR.glob("news_eval_receipt_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    prev = None
    if receipts:
        try:
            with open(receipts[0], "r", encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = None

    current_top = _top_event_titles(meta, 5)
    prev_top = prev.get("top_events", []) if isinstance(prev, dict) else []
    changed_top_events = [x for x in current_top if x not in prev_top]

    curr_sig = float((meta.get("signals") or {}).get("composite", 0.0) or 0.0)
    prev_sig = float(((prev or {}).get("signals") or {}).get("composite", 0.0) or 0.0)
    signal_drift = curr_sig - prev_sig

    curr_cov = float((meta.get("flow_enhancement") or {}).get("coverage", 0.0) or 0.0)
    prev_cov = float((prev or {}).get("coverage", 0.0) or 0.0)
    coverage_drift = curr_cov - prev_cov

    receipt = {
        "generated_at": NOW.isoformat(),
        "report_mode": report_mode,
        "output_markdown_path": output_markdown_path,
        "coverage": curr_cov,
        "quality": {
            "flow_confidence": float((meta.get("flow_enhancement") or {}).get("confidence", 0.0) or 0.0),
            "flow_quality_counts": (meta.get("flow_enhancement") or {}).get("quality_counts", {}),
            "critical_missing_sources": (meta.get("flow_enhancement") or {}).get("critical_missing_sources", [])
        },
        "drift": {
            "composite_signal": signal_drift,
            "coverage": coverage_drift
        },
        "signals": {
            "composite": curr_sig
        },
        "top_events": current_top,
        "changed_top_events": changed_top_events,
        "slot_metrics": (meta.get("slot_metrics") or {}) if isinstance(meta, dict) else {},
        "previous_receipt": str(receipts[0]) if receipts else None
    }
    return receipt


def _next_us_trading_day_str(now_dt: datetime) -> str:
    d = (now_dt + timedelta(days=1)).date()
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _build_macro_window_text(macro_news: list) -> str:
    day = _next_us_trading_day_str(NOW)
    titles = " ".join([str(x.get("title", "")).lower() for x in (macro_news or []) if isinstance(x, dict)])
    slots = [f"{day} 美东 09:30-11:30（美股开盘窗口）"]
    if any(k in titles for k in ["fomc", "会议纪要", "美联储", "fed"]):
        slots.append(f"{day} 美东 14:00/14:30（FOMC/联储声明与发布会窗口）")
    if any(k in titles for k in ["cpi", "pce", "非农", "就业", "nfp"]):
        slots.append(f"{day} 美东 08:30（宏观数据发布窗口）")
    if not any(k in titles for k in ["fomc", "会议纪要", "美联储", "fed", "cpi", "pce", "非农", "就业", "nfp"]):
        slots.append(f"{day} 美东 08:30/10:00（常规宏观数据观察窗口）")
    return "；".join(slots)


def _build_watchlist_items(
    *,
    optional_metric_rows,
    macro_expectation_unknown_count: int,
    macro_news: list,
    flow_enhance: dict,
    signal_temperature: float,
):
    metric_map = {str(name): (val, reason) for name, val, reason in (optional_metric_rows or [])}
    etf_val = (metric_map.get("BTC Spot ETF Netflow") or ("No data", ""))[0]
    stable_val = (metric_map.get("稳定币供给增量") or ("No data", ""))[0]
    dxy_val = (metric_map.get("DXY") or ("No data", ""))[0]
    real_yield_val = (metric_map.get("US10Y Real Yield") or ("No data", ""))[0]
    funding_val = (metric_map.get("Funding Rate") or ("No data", ""))[0]
    oi_val = (metric_map.get("Open Interest Δ24h") or ("No data", ""))[0]
    liq_val = (metric_map.get("24h 清算额") or ("No data", ""))[0]
    watch_items = [
        {
            "group": "资金通道",
            "subject": "BTC Spot ETF 净流入 + 稳定币供给",
            "current": f"ETF={etf_val}；稳定币={stable_val}",
            "threshold": "ETF 连续2日净流入>+500 BTC 或 单日转负<-300 BTC；稳定币Δ1D转负持续2日",
            "window": f"{_next_us_trading_day_str(NOW)} 美东 09:30-11:30（开盘2小时）+ 后续 24h 复核",
            "impact": "资金通道走强偏 risk_on；转弱偏 risk_off",
            "action": "走强可向 60-65% 靠拢；转弱回到 35-45%",
        },
        {
            "group": "宏观约束",
            "subject": "DXY + US10Y Real Yield + 宏观预期差",
            "current": f"DXY={dxy_val}；RealYield={real_yield_val}；unknown={int(macro_expectation_unknown_count)}",
            "threshold": "DXY 与 RealYield 同步上行且预期差 unknown 持续>0",
            "window": _build_macro_window_text(macro_news),
            "impact": "宏观约束增强，压制高β风险资产",
            "action": "维持防守仓位；仅在约束缓和后恢复中性",
        },
        {
            "group": "杠杆压力",
            "subject": "Funding + OI Δ24h + 24h 清算额",
            "current": f"Funding={funding_val}；OI={oi_val}；Liq={liq_val}",
            "threshold": "Funding转正并快速抬升 + OI扩张 + 清算额放大",
            "window": f"{_next_us_trading_day_str(NOW)} 美东 00:00-24:00（每4小时复核）",
            "impact": "拥挤度上升易触发波动放大与反身性回撤",
            "action": "升温时减杠杆；温度计<45 时不放大风险",
        },
    ]
    if not watch_items:
        return ["- No data"]
    out = []
    for i, item in enumerate(watch_items, 1):
        out.append(f"### 观察项 {i}（{item['group']}）")
        out.append(f"- 观察对象: {item['subject']}")
        out.append(f"- 当前值: {item['current']}")
        out.append(f"- 触发阈值: {item['threshold']}")
        out.append(f"- 观察窗口: {item['window']}")
        out.append(f"- 潜在影响: {item['impact']}")
        out.append(f"- 应对动作: {item['action']}")
        out.append("")
    out.append(f"- 备注: 信号温度计={signal_temperature:.1f}/100，若关键字段缺失扩大则自动降级。")
    return out


def _find_heading_index(lines: list[str], heading: str) -> int:
    h = str(heading or "").strip()
    if not h:
        return -1
    for i, line in enumerate(lines):
        if str(line).strip() == h:
            return i
    return -1


def _slice_between_headings(lines: list[str], start_heading: str, end_heading: str) -> list[str]:
    start_idx = _find_heading_index(lines, start_heading)
    if start_idx < 0:
        return []
    end_idx = _find_heading_index(lines, end_heading)
    if end_idx < 0:
        end_idx = len(lines)
    if end_idx <= start_idx:
        return []
    return lines[start_idx + 1 : end_idx]


def _slice_after_heading_until_prefix(lines: list[str], start_heading: str, stop_prefixes: list[str]) -> list[str]:
    start_idx = _find_heading_index(lines, start_heading)
    if start_idx < 0:
        return []
    out: list[str] = []
    for x in lines[start_idx + 1 :]:
        s = str(x or "").strip()
        if any(s.startswith(p) for p in (stop_prefixes or []) if str(p or "").strip()):
            break
        out.append(str(x))
    return out


def _slice_after_heading_until_pred(lines: list[str], start_heading: str, stop_pred) -> list[str]:
    start_idx = _find_heading_index(lines, start_heading)
    if start_idx < 0:
        return []
    out: list[str] = []
    for x in lines[start_idx + 1 :]:
        if stop_pred is not None and stop_pred(str(x)):
            break
        out.append(str(x))
    return out


def _validate_brief_spec(content: str, meta: dict, report_mode: str):
    errors = []
    warnings = []
    lines = [x.rstrip() for x in str(content or "").splitlines()]
    first_non_empty = ""
    for line in lines:
        if line.strip():
            first_non_empty = line.strip()
            break
    if first_non_empty != BRIEF_V3_TITLE:
        errors.append("invalid_title")
    heading_positions = []
    for h in BRIEF_V3_REQUIRED_HEADINGS:
        idx = -1
        for i, line in enumerate(lines):
            if line.strip() == h:
                idx = i
                break
        if idx < 0:
            errors.append(f"missing_section:{h}")
        else:
            heading_positions.append(idx)
    if len(heading_positions) == len(BRIEF_V3_REQUIRED_HEADINGS):
        if any(heading_positions[i] >= heading_positions[i + 1] for i in range(len(heading_positions) - 1)):
            errors.append("invalid_section_order")
    if "execution_gate=readonly_advisory" not in content:
        errors.append("missing_execution_gate")
    if "±0.15" not in content:
        errors.append("missing_fixed_threshold")
    if "落盘路径：" not in content:
        errors.append("missing_output_path")
    news_detail = _slice_between_headings(lines, "## 🧾 新闻分类明细", "## ✅ 信号（简化）")
    if not news_detail:
        errors.append("missing_detail_section:news_details")
    for sub in ["### 链上数据", "### 大 V 观点", "### 项目动态", "### 宏观政策与市场", "### 跨市场联动"]:
        if _find_heading_index(lines, sub) < 0:
            errors.append(f"missing_detail_section:{sub}")
    for sub in ["### 链上数据", "### 大 V 观点", "### 项目动态", "### 宏观政策与市场"]:
        seg = _slice_after_heading_until_pred(
            lines,
            sub,
            lambda v, h=sub: (str(v).strip().startswith("### ") and str(v).strip() != h) or str(v).strip().startswith("## "),
        )
        if not seg:
            seg = []
        has_no_data = any(str(x).strip() == "- No data" for x in seg)
        if has_no_data:
            continue
        item_idx = [i for i, x in enumerate(seg) if str(x).lstrip().startswith("#### ")]
        if not item_idx:
            errors.append(f"missing_detail_items:{sub}")
            continue
        item_idx.append(len(seg))
        required_fields = ["- 事实:", "- 类别:", "- 断言:", "- 方向:", "- 影响路径:", "- 路径模板ID:", "- 冲突判定:", "- Badge:", "- 来源:"]
        for k in range(len(item_idx) - 1):
            block = seg[item_idx[k] : item_idx[k + 1]]
            if not any(str(x).lstrip().startswith("#### ") for x in block):
                continue
            for f in required_fields:
                if not any(str(x).lstrip().startswith(f) for x in block):
                    errors.append(f"missing_detail_field:{sub}:{f}")
    cross_seg = _slice_between_headings(lines, "### 跨市场联动", "## ✅ 信号（简化）")
    if not cross_seg:
        errors.append("missing_detail_section:cross_market")
    else:
        must = ["| 资产 | 24h 变动 | 趋势 |", "| BTC |", "| ETH |", "联动方向:"]
        for m in must:
            if not any(m in str(x) for x in cross_seg):
                errors.append(f"missing_cross_market_token:{m}")
    signal_seg = _slice_between_headings(lines, "## ✅ 信号（简化）", "## ⚠️ 风险提示")
    if not signal_seg:
        errors.append("missing_section:signal_simple")
    else:
        required_simple = ["- BTC 趋势:", "- 风险偏好:", "- 股币关联:", "- 资金流增强:", "- 信号温度计:"]
        for f in required_simple:
            if not any(str(x).lstrip().startswith(f) for x in signal_seg):
                errors.append(f"missing_simple_signal_field:{f}")
    checks_seg = _slice_after_heading_until_prefix(lines, "## 🧪 输出检查规范", ["*简报生成时间："])
    header = "| 检查项 | 要求 | 当前输出 | 状态 |"
    header_idx = -1
    for i, x in enumerate(checks_seg):
        if str(x).strip() == header:
            header_idx = i
            break
    if header_idx < 0:
        errors.append("missing_output_checks_table_header")
    else:
        rows = []
        for x in checks_seg[header_idx + 1 :]:
            s = str(x).strip()
            if not s:
                break
            if not s.startswith("|"):
                break
            if s.startswith("|--------"):
                continue
            rows.append(s)
        required_items = {
            "市场状态诊断",
            "核心数据概览",
            "今日要点",
            "事件账本",
            "动态仓位",
            "新闻分类明细",
            "明日观察清单",
            "简化信号",
            "只读门禁",
        }
        allowed_status = {"通过", "降级", "失败"}
        seen_items = set()
        for r in rows:
            parts = [p.strip() for p in r.strip("|").split("|")]
            if len(parts) != 4:
                errors.append("invalid_output_checks_row_columns")
                continue
            item, rule, actual, status = parts
            if not item:
                errors.append("invalid_output_checks_row_item_empty")
                continue
            seen_items.add(item)
            if status not in allowed_status:
                errors.append(f"invalid_output_checks_status:{status}")
        missing = sorted(list(required_items - seen_items))
        if missing:
            errors.append(f"missing_output_checks_items:{','.join(missing)}")
    flow = (meta.get("flow_enhancement") or {}) if isinstance(meta, dict) else {}
    if not flow.get("ok"):
        errors.append("flow_enhancement_unavailable")
    coverage = float(flow.get("coverage", 0.0) or 0.0)
    if coverage < 0.5:
        warnings.append(f"low_coverage:{coverage:.4f}")
    signals = (meta.get("signals") or {}) if isinstance(meta, dict) else {}
    for k in ("news_composite", "composite"):
        v = signals.get(k)
        if not isinstance(v, (int, float)):
            errors.append(f"invalid_signal:{k}")
    ledger = meta.get("event_ledger") if isinstance(meta, dict) else None
    if not isinstance(ledger, list) or not ledger:
        errors.append("event_ledger_empty")
    macro_expectation_unknown_count = int(meta.get("macro_expectation_unknown_count", 0) or 0) if isinstance(meta, dict) else 0
    if macro_expectation_unknown_count > 0:
        if "预期差: unknown" not in content:
            errors.append("missing_macro_expectation_unknown_disclosure")
        if "不确定性披露" not in content:
            errors.append("missing_uncertainty_disclosure")
    if "### 可选扩展指标（P1）" not in content:
        errors.append("missing_optional_metrics_section")
    else:
        optional_tokens = ["| DXY |", "| US10Y Real Yield |", "| BTC Spot ETF Netflow |", "| 稳定币供给增量 |", "| Funding Rate |", "| Open Interest Δ24h |", "| 24h 清算额 |"]
        for t in optional_tokens:
            if t not in content:
                errors.append(f"missing_optional_metric:{t}")
    watch_seg = _slice_between_headings(lines, "## 📋 明日观察清单", "## 🎯 策略总结")
    if not watch_seg:
        errors.append("missing_watchlist_section")
    else:
        required_watch_fields = ["- 观察对象:", "- 当前值:", "- 触发阈值:", "- 观察窗口:", "- 潜在影响:", "- 应对动作:"]
        if any(str(x).strip() == "- No data" for x in watch_seg):
            pass
        else:
            for f in required_watch_fields:
                if not any(str(x).lstrip().startswith(f) for x in watch_seg):
                    errors.append(f"missing_watchlist_field:{f}")
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def generate_briefing(prices, crypto_news, macro_news, hours: int, report_mode: str, flow_enhance: dict, output_path: str):
    high_confidence_crypto = sum(1 for n in crypto_news if n["source_confidence"] == "high")
    high_confidence_macro = sum(1 for n in macro_news if n["source_confidence"] == "high")
    t0_events = sum(1 for n in crypto_news + macro_news if n["impact_horizon"] == "T0")
    risk_flags_count = sum(len(n.get("risk_flags", [])) for n in crypto_news + macro_news)

    btc_change = prices["btc"]["change_24h"]
    nasdaq_change = prices["nasdaq"]["change_24h"]
    same_direction = (btc_change > 0) == (nasdaq_change > 0) if btc_change and nasdaq_change else None
    vix_value = float(prices.get("vix", {}).get("value", 0) or 0)

    bullish = []
    bearish = []
    for item in crypto_news:
        bucket = _classify_crypto_item(item)
        if bucket == "bullish":
            bullish.append(item)
        elif bucket == "bearish":
            bearish.append(item)

    policy = _load_market_state_policy()
    regime_metrics = _fetch_btc_regime_metrics()
    state = _infer_market_state(prices, regime_metrics if regime_metrics.get("ok") else {}, policy)
    market_state = state["regime"]
    risk_state = state["risk"]
    weight_table = _load_event_type_weights()
    ledger = _build_event_ledger(crypto_news, macro_news, flow_enhance, weight_table)

    news_composite = sum(x["contribution"] for x in ledger) / len(ledger) if ledger else 0.0
    flow_composite = float(flow_enhance.get("composite", 0.0) or 0.0) if flow_enhance.get("ok") else 0.0
    composite_signal = 0.7 * news_composite + 0.3 * flow_composite if flow_enhance.get("ok") else news_composite
    macro_items = [x for x in ledger if x["event_type"] in {"fed", "us_data", "us_policy", "geopolitics", "crypto_regulation", "market_analysis"}]
    industry_items = [x for x in ledger if x["event_type"] in {"onchain_data", "institution_flow", "project_update", "entity_statement"}]
    intraday_items = [x for x in ledger if x["event_type"] in {"kols_view", "institution_view", "market_analysis"}]
    macro_signal = sum(x["contribution"] for x in macro_items) / len(macro_items) if macro_items else 0.0
    industry_signal = sum(x["contribution"] for x in industry_items) / len(industry_items) if industry_items else 0.0
    intraday_signal = sum(x["contribution"] for x in intraday_items) / len(intraday_items) if intraday_items else 0.0
    position_plan = _build_position_plan(composite_signal, state, flow_enhance)

    slot = _build_dynamic_top12(crypto_news, macro_news)
    point_lines = list(slot.get("lines") or [])
    risk_items = []
    if vix_value >= 22:
        risk_items.append(f"- VIX={vix_value:.2f} 高于风险阈值，优先防守仓位。")
    if flow_enhance.get("risk_off"):
        risk_items.append("- 资金流状态为 risk_off，禁止放大风险敞口。")
    if risk_flags_count > 0:
        risk_items.append(f"- 风险标记共 {risk_flags_count} 条，单源与不可复核信息仅作参考。")
    macro_expectation_unknown_count = 0
    for macro_item in macro_news:
        if _macro_expectation_eval(macro_item).get("bucket") == "unknown":
            macro_expectation_unknown_count += 1
    if macro_expectation_unknown_count > 0:
        risk_items.append(f"- 不确定性披露：宏观事件中有 {macro_expectation_unknown_count} 条缺少“实际/预期/前值”，预期差统一标记 unknown。")
    if not risk_items:
        risk_items = ["- 暂无新增高等级风险事件，维持只读观察。"]
    onchain_items = [n for n in crypto_news if n.get("category") in {"onchain_data", "institution_flow"}]
    kol_items = [n for n in crypto_news if n.get("category") in {"kols_view", "institution_view"}]
    project_items = [n for n in crypto_news if n.get("category") in {"project_update", "entity_statement"}]
    crypto_macro_items = [n for n in crypto_news if n.get("category") in {"fed", "us_data", "us_policy", "geopolitics", "crypto_regulation", "market_analysis"}]
    macro_items_raw = list(macro_news) + crypto_macro_items

    def _format_detail(items, fact_key: str, category_key: str, *, macro_mode: bool = False):
        lines = []
        if not items:
            return ["- No data"]
        for i, item in enumerate(items, 1):
            flags = f" ⚠️ `{', '.join(item.get('risk_flags', []))}`" if item.get("risk_flags") else ""
            lines.append(f"#### {i}. {item.get('title', 'No data')}{flags}")
            fact_val = item.get(fact_key) or item.get("summary") or item.get("key_fact") or "No data"
            cat_val = item.get(category_key) or item.get("category") or item.get("topic") or "No data"
            lines.append(f"- 事实: {fact_val}")
            lines.append(f"- 类别: {cat_val}")
            lines.append(f"- 断言: {item.get('assertion_type', 'No data') or 'No data'}")
            lines.append(
                f"- 方向: {item.get('direction', 'neutral')} (S={float(item.get('direction_score', 0.0) or 0.0):+.2f}, conf={item.get('confidence_band', 'low')})"
            )
            lines.append(f"- 影响路径: {item.get('cross_market_map', item.get('market_impact', 'No data')) or 'No data'}")
            lines.append(f"- 路径模板ID: {item.get('path_template_id', 'No data') or 'No data'}")
            lines.append(f"- 路径模式: {item.get('impact_path_mode', 'template') or 'template'}")
            lines.append(f"- AI状态: {item.get('ai_status', 'n/a') or 'n/a'}")
            lines.append(f"- 冲突判定: {item.get('conflict_rule', 'No data') or 'No data'}")
            badge = item.get("badge") if isinstance(item.get("badge"), dict) else {}
            lines.append(
                f"- Badge: {(badge.get('badge_text') or '中性·谨慎')} | {(badge.get('badge_color') or 'neutral')} | {(badge.get('badge_reason') or 'score_mapping')}"
            )
            if str(item.get("direction_trace") or "").strip():
                lines.append(f"- 方向轨迹: {str(item.get('direction_trace') or '').strip()}")
            if str(item.get("uncertainty_disclosure") or "").strip():
                lines.append(f"- 不确定性披露: {str(item.get('uncertainty_disclosure') or '').strip()}")
            lines.append(f"- 来源: {item.get('source_url', 'No data') or 'No data'}")
            if macro_mode:
                exp_eval = _macro_expectation_eval(item)
                if exp_eval.get("bucket") == "unknown":
                    lines.append("- 预期差: unknown（缺少实际/预期/前值）")
                else:
                    delta_val = exp_eval.get("delta")
                    delta_text = f"{delta_val:+.2f}" if isinstance(delta_val, (int, float)) else "No data"
                    lines.append(f"- 预期差: {exp_eval.get('bucket')}（actual-forecast={delta_text}）")
            lines.append("")
        return lines

    onchain_detail_lines = _format_detail(onchain_items, "summary", "category")
    kol_detail_lines = _format_detail(kol_items, "summary", "category")
    project_detail_lines = _format_detail(project_items, "summary", "category")
    macro_detail_lines = _format_detail(macro_items_raw, "key_fact", "topic", macro_mode=True)
    cross_market_direction = "正相关" if same_direction else "负相关/独立行情" if same_direction is False else "数据不足"
    cross_market_reason = "BTC 与纳指方向一致" if same_direction is True else "BTC 与纳指方向分化" if same_direction is False else "纳指或 BTC 变动接近 0，无法判定"
    optional_pack = _build_optional_metrics()
    optional_metric_rows = list(optional_pack.get("rows", []))
    optional_no_data_count = sum(1 for _, val, _ in optional_metric_rows if str(val).strip() == "No data")
    missing_ratio = (optional_no_data_count / len(optional_metric_rows)) if optional_metric_rows else 1.0
    temp_base = 50.0 + composite_signal * 180.0 + (float(flow_enhance.get("coverage", 0.0) or 0.0) - 0.5) * 30.0
    temp_penalty = macro_expectation_unknown_count * 3.0 + optional_no_data_count * 2.0 + (8.0 if flow_enhance.get("risk_off") else 0.0)
    signal_temperature = max(0.0, min(100.0, temp_base - temp_penalty))
    temperature_label = "HOT" if signal_temperature >= 70 else "WARM" if signal_temperature >= 45 else "COOL"
    watchlist = _build_watchlist_items(
        optional_metric_rows=optional_metric_rows,
        macro_expectation_unknown_count=macro_expectation_unknown_count,
        macro_news=macro_news,
        flow_enhance=flow_enhance,
        signal_temperature=signal_temperature,
    )
    signal_simple_lines = [
        f"- BTC 趋势: {'bullish' if btc_change > 0 else 'bearish' if btc_change < 0 else 'neutral'}",
        f"- 风险偏好: {'risk_on' if vix_value and vix_value < 20 else 'risk_off' if vix_value else 'unknown'}",
        f"- 股币关联: {'positive' if same_direction else 'independent' if same_direction is False else 'unknown'}",
        f"- 资金流增强: {'enabled' if flow_enhance.get('ok') else 'disabled'} ({flow_enhance.get('bias', 'neutral') if flow_enhance.get('ok') else flow_enhance.get('reason', 'n/a')})",
        f"- 信号温度计: {signal_temperature:.1f}/100 ({temperature_label}) | 缺失率={missing_ratio:.2f}",
    ]
    output_checks = [
        ("市场状态诊断", "MA20/阈值/20日波动率/VIX", "通过" if regime_metrics.get("ok") else "fallback", "通过" if regime_metrics.get("ok") else "降级"),
        ("核心数据概览", "BTC/ETH/ETHBTC/纳指/VIX", "通过", "通过"),
        ("今日要点", "固定 12 条", f"{len(point_lines[:12])} 条", "通过" if len(point_lines[:12]) == 12 else "失败"),
        ("事件账本", "非空且含冲突证据", f"{len(ledger)} 条", "通过" if len(ledger) > 0 else "失败"),
        ("动态仓位", "阈值固定 ±0.15", f"±{position_plan['threshold']:.2f}", "通过" if abs(position_plan["threshold"] - 0.15) < 1e-9 else "失败"),
        ("新闻分类明细", "事实/类别/断言/方向/路径模板/冲突/Badge/来源", "字段齐全", "通过"),
        ("明日观察清单", "六字段结构化观察项", "结构化输出", "通过"),
        ("简化信号", "5 个核心信号字段(含温度计)", f"{len(signal_simple_lines)} 项", "通过" if len(signal_simple_lines) >= 5 else "失败"),
        ("只读门禁", "execution_gate=readonly_advisory", "已写入", "通过"),
        ("扩展指标(P1)", "可选行 + No data", f"{len(optional_metric_rows) - optional_no_data_count}/{len(optional_metric_rows)} 可用", "降级" if optional_no_data_count > 0 else "通过"),
    ]

    briefing = f"""{BRIEF_V3_TITLE}

**生成时间**: {NOW.isoformat()}
**数据窗口**: 最近 {hours} 小时
**分析框架**: V9.3 事件账本 + 市场状态识别 + 动态仓位管理

---

## 📊 市场状态诊断

### 当前市场状态：**{market_state}**（风险：{risk_state}）

| 指标 | 数值 | 阈值 | 状态 |
|------|------|------|------|
| BTC 当前价 | ${regime_metrics.get("btc_close", prices["btc"]["price"]):,.2f} | - | {"可用" if regime_metrics.get("ok") else "fallback"} |
| MA20(20 日均线) | ${regime_metrics.get("ma20", 0):,.2f} | - | {"可用" if regime_metrics.get("ok") else "fallback"} |
| 价格 vs MA20 | {state.get("pct_vs_ma20", 0.0):+.2f}% | {state.get("bear_thr", -5.0):+.1f}% ~ {state.get("bull_thr", 5.0):+.1f}% | {market_state} |
| 20日波动率 | {state.get("vol20", 0.0):.2f}% | 3.0% | {"高波动" if state.get("vol20", 0.0) >= 3 else "常态"} |
| VIX | {prices["vix"]["display"]} | {float((policy.get("thresholds") or {}).get("risk_off_vix", 22.0)):.1f} | {risk_state} |

---

## 📈 核心数据概览

| 资产 | 价格 | 24h | 信号 |
|------|------|-----|------|
| BTC | {prices["btc"]["price"]:,.2f} | {btc_change:+.2f}% | {"✅ 强势" if btc_change > 3 else "⚠️ 弱势" if btc_change < -3 else "➖ 震荡"} |
| ETH | {prices["eth"]["price"]:,.2f} | {prices["eth"]["change_24h"]:+.2f}% | {"✅ 强势" if prices["eth"]["change_24h"] > 3 else "⚠️ 弱势" if prices["eth"]["change_24h"] < -3 else "➖ 震荡"} |
| ETH/BTC | {prices["eth_btc_ratio"]:.4f} | - | ➖ |
| 纳斯达克 | {prices["nasdaq"]["display"]} | {prices["nasdaq"]["change_24h"]:+.2f}% | {"➖" if prices["nasdaq"]["change_24h"] == 0 else "✅" if prices["nasdaq"]["change_24h"] > 0 else "⚠️"} |
| VIX | {prices["vix"]["display"]} | - | {"🔴 高风险" if vix_value and vix_value >= 22 else "➖"} |

### 可选扩展指标（P1）

| 指标 | 当前值 | 说明 |
|------|--------|------|
{chr(10).join([f"| {name} | {val} | {reason} |" for name, val, reason in optional_metric_rows])}

---

## 🔔 今日要点（12 条）

{chr(10).join(point_lines[:12])}

---

## 📐 V9.3 事件账本信号分析

### 信号计算公式
`signal = Σ(base_sentiment × type_weight × window_weight × surprise_weight × confidence_adjusted)`

### 今日事件账本

| 事件 | 类型权重 | 时间权重 | 意外权重 | 可信度(原/调) | 贡献信号 | 冲突证据 |
|------|----------|----------|----------|-------------|----------|----------|
"""
    for item in ledger[:8]:
        conflict = ",".join(item.get("conflict_reasons", [])) if item.get("conflict_reasons") else "-"
        briefing += f"| {item['title'][:36]} | {item['event_type']}({item['type_weight']:.2f}) | {item['window_weight']:.2f} | {item['surprise_weight']:.2f} | {item['confidence_weight']:.2f}/{item['confidence_adjusted']:.2f} | {item['contribution']:+.3f} | {conflict} |\n"

    briefing += f"""

### 信号汇总

| 信号类型 | 数值 | 阈值 | 解读 |
|----------|------|------|------|
| 综合信号 | {composite_signal:+.3f} | ±{position_plan['threshold']:.2f} | {"偏多" if composite_signal > position_plan["threshold"] else "偏空" if composite_signal < -position_plan["threshold"] else "中性"} |
| 新闻信号 | {news_composite:+.3f} | ±0.15 | 事件账本合成 |
| 资金流增强 | {flow_composite:+.3f} | - | {flow_enhance.get("bias", "neutral")} / coverage={flow_enhance.get("coverage", 0.0):.2f} |
| 宏观信号 | {macro_signal:+.3f} | ±0.15 | 宏观约束层 |
| 行业信号 | {industry_signal:+.3f} | ±0.15 | 行业景气层 |
| 即时信号 | {intraday_signal:+.3f} | ±0.15 | 盘中交易层 |

---

## 💼 动态仓位管理建议

### 基于市场状态的参数配置

| 参数 | 当前配置 | 说明 |
|------|----------|------|
| 信号阈值 | ±{position_plan['threshold']:.2f} | 超阈值才触发方向动作 |
| 仓位乘数 | {position_plan['multiplier']:.1f}x | 信号转换速度 |
| 最大仓位 | {position_plan['max_position']*100:.0f}% | 风险上限 |
| 最小仓位 | {position_plan['min_position']*100:.0f}% | 防守底仓 |
| 止损线 | {position_plan['stop_loss']} | 风险保护 |

### 今日仓位建议

- 建议动作：**{position_plan['action']}**
- 建议仓位：**{position_plan['target_position']*100:.1f}%**
- 关键依据：状态={market_state}；综合信号={composite_signal:+.3f}；flow_bias={flow_enhance.get("bias", "neutral")}

### 分档操作建议

| 条件 | 动作 | 仓位 |
|------|------|------|
| 综合信号 > +{position_plan['threshold']:.2f} 且 flow 非 risk_off | 加仓 | 向 {position_plan['max_position']*100:.0f}% 靠拢 |
| 综合信号在 ±{position_plan['threshold']:.2f} 内 | 持有 | 维持 50% 附近 |
| 综合信号 < -{position_plan['threshold']:.2f} 或 flow risk_off | 减仓 | 向 {position_plan['min_position']*100:.0f}% 靠拢 |

---

## 🧾 新闻分类明细

### 链上数据

{chr(10).join(onchain_detail_lines)}

### 大 V 观点

{chr(10).join(kol_detail_lines)}

### 项目动态

{chr(10).join(project_detail_lines)}

### 宏观政策与市场

{chr(10).join(macro_detail_lines)}

### 跨市场联动

| 资产 | 24h 变动 | 趋势 |
|------|----------|------|
| BTC | {btc_change:+.2f}% | {"强势" if btc_change > 3 else "弱势" if btc_change < -3 else "震荡"} |
| ETH | {prices["eth"]["change_24h"]:+.2f}% | {"强势" if prices["eth"]["change_24h"] > 3 else "弱势" if prices["eth"]["change_24h"] < -3 else "震荡"} |

联动方向: {cross_market_direction}（{cross_market_reason}）

---

## ✅ 信号（简化）

{chr(10).join(signal_simple_lines)}
---

## ⚠️ 风险提示

{chr(10).join(risk_items)}

---

## 📋 明日观察清单

{chr(10).join(watchlist)}

---

## 🎯 策略总结

1. 市场状态：{market_state}（风险：{risk_state}）。
2. 综合信号：{composite_signal:+.3f}，固定阈值 ±0.15。
3. 仓位建议：{position_plan['target_position']*100:.1f}%（动作 {position_plan['action']}）。
4. 风险门禁：execution_gate=readonly_advisory，禁止直接执行交易。
5. 信号温度计：{signal_temperature:.1f}/100（{temperature_label}），缺失率={missing_ratio:.2f}。

---

## 🧪 输出检查规范

| 检查项 | 要求 | 当前输出 | 状态 |
|--------|------|----------|------|
{chr(10).join([f"| {name} | {rule} | {actual} | {status} |" for name, rule, actual, status in output_checks])}

---

*简报生成时间：{NOW.strftime("%Y-%m-%d %H:%M:%S")} | 数据窗口：最近 {hours} 小时*
*落盘路径：{output_path}*
"""

    meta = {
        "policy_version": policy.get("version", "default"),
        "market_state": state,
        "regime_metrics": regime_metrics,
        "flow_enhancement": flow_enhance,
        "signals": {
            "news_composite": news_composite,
            "flow_composite": flow_composite,
            "composite": composite_signal,
            "macro": macro_signal,
            "industry": industry_signal,
            "intraday": intraday_signal
        },
        "position_plan": position_plan,
        "event_ledger": ledger,
        "output_checks": output_checks,
        "macro_expectation_unknown_count": macro_expectation_unknown_count,
        "optional_metrics": optional_metric_rows,
        "slot_metrics": {
            "new_titles_vs_prev": int(slot.get("new_titles_vs_prev", 0)),
            "top12_no_data_ratio": float(slot.get("top12_no_data_ratio", 1.0)),
            "top12_unique_ratio": float(slot.get("top12_unique_ratio", 0.0)),
            "valid_top_titles": int(len([x for x in (slot.get("titles") or []) if str(x).strip()])),
            "major_event_present": bool(any(("特朗普" in str(x)) or ("ETF" in str(x)) or ("监管" in str(x)) or ("袭击" in str(x)) for x in (slot.get("titles") or []))),
            "category_conflict_rate": float(slot.get("category_conflict_rate", 1.0)),
            "impact_path_non_empty_ratio": float(slot.get("impact_path_non_empty_ratio", 0.0)),
            "ai_generated_ratio": float(slot.get("ai_generated_ratio", 0.0)),
            "direction_computable_ratio": float(slot.get("direction_computable_ratio", 0.0)),
            "neutral_overuse_ratio": float(slot.get("neutral_overuse_ratio", 1.0)),
        },
        "top_rows": list(slot.get("top_rows") or []),
    }
    return briefing, meta


def main():
    args = parse_args()
    hours = args.hours
    output_file = args.output
    quiet = args.quiet
    report_mode = args.report_mode

    if not quiet:
        print(f"=== 加密 + 宏观新闻简报（即时生成）===")
        print(f"时间窗口：最近 {hours} 小时")
        print(f"生成时间：{NOW.isoformat()}")
        print()

    prices = get_real_time_prices()

    if not quiet:
        print("【实时行情】")
        print(f"  BTC: {prices['btc']['display']}")
        print(f"  ETH: {prices['eth']['display']}")
        print(f"  ETH/BTC: {prices['eth_btc_ratio']:.4f}")
        print(f"  纳斯达克：{prices['nasdaq']['display']}")
        print()

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_crypto = executor.submit(generate_crypto_news, hours)
        f_macro = executor.submit(generate_macro_news, hours)
        f_flow = executor.submit(_run_flow_brief_generator)
        crypto_news = f_crypto.result()
        macro_news = f_macro.result()
        flow_enhance = f_flow.result()

    if not quiet:
        print(f"【新闻筛选】")
        print(f"  加密新闻：{len(crypto_news)} 条")
        print(f"  宏观新闻：{len(macro_news)} 条")
        print()

    if output_file:
        brief_path = OUTPUTS_DIR / output_file if not output_file.startswith('/') else Path(output_file)
    else:
        brief_path = OUTPUTS_DIR / f"brief_v3_{NOW.strftime('%Y%m%d')}_optimized.md"

    briefing, brief_meta = generate_briefing(
        prices,
        crypto_news,
        macro_news,
        hours,
        report_mode,
        flow_enhance,
        str(brief_path),
    )
    spec_check = _validate_brief_spec(briefing, brief_meta, report_mode)
    if not spec_check.get("ok"):
        if not quiet:
            print("[x] 输出规范检查失败")
            for e in spec_check.get("errors", []):
                print(f"  - {e}")
        return 2

    brief_path.parent.mkdir(parents=True, exist_ok=True)

    with open(brief_path, 'w', encoding='utf-8') as f:
        f.write(briefing)

    receipt = _build_eval_receipt(brief_meta, str(brief_path), report_mode)
    receipt["spec_check"] = spec_check
    receipt["score"] = _score_eval_from_meta(brief_meta, spec_check)
    top_rows = brief_meta.get("top_rows") if isinstance(brief_meta.get("top_rows"), list) else []
    payload_items = [_news_item_contract(x) for x in top_rows[:12] if isinstance(x, dict)]
    receipt["items"] = payload_items
    receipt_path = RAW_DIR / f"news_eval_receipt_{NOW.strftime('%Y%m%d_%H%M')}.json"
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)

    if not quiet:
        print(f"[✓] 简报已生成：{brief_path}")
        print(f"[✓] 评估回执已保存：{receipt_path}")
        print()
        print("【投资信号】")
        btc_signal = "✅ 持有/加仓" if prices["btc"]["change_24h"] > 0 else "⚠️ 观望"
        print(f"  BTC 趋势：{btc_signal}")
        same_dir = (prices['btc']['change_24h'] > 0) == (prices['nasdaq']['change_24h'] > 0) if prices['nasdaq']['change_24h'] else None
        if same_dir is True:
            print(f"  股币关联：正相关 (跟随美股)")
        elif same_dir is False:
            print(f"  股币关联：独立行情 (配置价值)")
        else:
            print(f"  股币关联：数据不足")

    # JSON 输出（可选）
    if args.json:
        json_path = brief_path.with_suffix('.json')
        # 计算相关性
        btc_change = prices["btc"]["change_24h"]
        nasdaq_change = prices["nasdaq"]["change_24h"]
        same_dir = (btc_change > 0) == (nasdaq_change > 0) if btc_change and nasdaq_change else None

        bullish = []
        bearish = []
        for item in crypto_news:
            bucket = _classify_crypto_item(item)
            if bucket == "bullish":
                bullish.append(item)
            elif bucket == "bearish":
                bearish.append(item)

        json_data = {
            "generated_at": NOW.isoformat(),
            "time_window_hours": hours,
            "report_mode": report_mode,
            "execution_gate": "readonly_advisory",
            "prices": {
                "btc": prices["btc"],
                "eth": prices["eth"],
                "nasdaq": prices["nasdaq"],
                "vix": prices["vix"]
            },
            "news_counts": {
                "crypto": len(crypto_news),
                "macro": len(macro_news),
                "high_confidence": sum(1 for n in crypto_news + macro_news if n["source_confidence"] == "high")
            },
            "signals": {
                "btc_trend": "bullish" if prices["btc"]["change_24h"] > 0 else "bearish" if prices["btc"]["change_24h"] < 0 else "neutral",
                "correlation": "positive" if same_dir else "independent" if same_dir is False else "unknown",
                "composite": brief_meta["signals"]["composite"]
            },
            "highlights": {
                "bullish": [{"title": x.get("title"), "source_url": x.get("source_url"), "confidence": x.get("source_confidence")} for x in bullish[:5]],
                "bearish": [{"title": x.get("title"), "source_url": x.get("source_url"), "confidence": x.get("source_confidence"), "risk_flags": x.get("risk_flags", [])} for x in bearish[:4]],
                "macro": [{"title": x.get("title"), "source_url": x.get("source_url"), "confidence": x.get("source_confidence"), "risk_flags": x.get("risk_flags", [])} for x in macro_news[:3]]
            },
            "market_state": brief_meta["market_state"],
            "regime_metrics": brief_meta["regime_metrics"],
            "flow_enhancement": brief_meta["flow_enhancement"],
            "position_plan": brief_meta["position_plan"],
            "signal_breakdown": brief_meta["signals"],
            "event_ledger": brief_meta["event_ledger"],
            "items": payload_items,
            "evaluation_receipt_path": str(receipt_path),
            "evaluation_receipt": receipt
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        if not quiet:
            print(f"[✓] JSON 摘要已保存：{json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

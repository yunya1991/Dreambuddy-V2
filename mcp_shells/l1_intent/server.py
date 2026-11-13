#!/usr/bin/env python3
"""mcp_shells/l1_intent/server.py — L1 意图层 MCP（P0 Phase 1，DEC-01）

零 token / 纯确定性 / 只读，复用 3.1-FRONTEND/src/lib/l1-intent-registry.ts
正则定义。shell 三段：协议解析 → 正则匹配执行 → 信封映射。

壳零业务逻辑：所有意图定义在 _INTENT_REGISTRY（Python 镜像），
任何改动须同步 TS 侧（3.1-FRONTEND）+ 本文件（测试比对即漂移门禁）。

硬约束：
  - 全只读（read_write=read / requires_mandate=false）
  - 正则匹配失败 → ok=true, data=null, meta.match=false（FAIL-OPEN）
  - 无大模型调用、不联网、不写 DB
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l1.intent.mcp"

# ── 意图注册表（Python 镜像 3.1-FRONTEND l1-intent-registry.ts） ──
# 字段：intent 名、fallback_pattern（关键词兜底正则）、required_pattern（执行前置校验）
# 与 TS 侧严格一一对应，数量/命名任何偏移视为漂移
_INTENT_REGISTRY: List[Dict[str, Any]] = [
    {
        "intent": "data_query",
        "description": "数据类查询（关键词兜底 + 数据类问法前置校验）",
        "required_pattern": re.compile(
            r"查|查询|多少|最新|现在|当前|什么价|价格|行情|指数|TVL|CPI|非农|美联储|fred|defillama|恐惧贪婪|稳定币|多空比|资金费率|链上|快讯|期权|衍生品",
            re.IGNORECASE,
        ),
    },
    {
        "intent": "data_insight",
        "description": "数据变化含义类解读",
        "required_pattern": re.compile(
            r"(?=.*(CPI|非农|恐惧贪婪|稳定币|多空比|资金费率|TVL|美联储|利率|期权|通胀|就业))"
            r"(?=.*(意味着|说明什么|什么影响|怎么解读|含义|超预期|不及预期|转向|上升|下降|增长|减少|流入|流出))"
        ),
    },
    {
        "intent": "contradiction_insight",
        "description": "矛盾维度洞察（兜底正则：关键词含矛盾/一致+维度/资金面/技术面/情绪面/宏观/主要矛盾）",
        "fallback_pattern": re.compile(
            r"(?=.*(矛盾|一致))(?=.*(维度|资金面|技术面|情绪面|宏观|主要矛盾))"
        ),
    },
    {
        "intent": "path_insight",
        "description": "最小阻力路径/综合判断",
        "fallback_pattern": re.compile(r"最小阻力|往哪走|该多还是空|交汇|综合看|综合判断|最优路径"),
    },
    {
        "intent": "technical_analysis",
        "description": "技术面/卦象/置信度",
        "fallback_pattern": re.compile(r"技术面|技术指标|卦象|置信度"),
    },
    {
        "intent": "fundamental_valuation",
        "description": "估值百分位/估值高低",
        "fallback_pattern": re.compile(r"估值|基本面分析|估值百分位|估值高不高"),
    },
    {
        "intent": "asset_class_trend",
        "description": "跨资产/资产对比趋势",
        "fallback_pattern": re.compile(
            r"跨资产|资产对比|各类资产|趋势对比|美股和加密|贵金属和加密"
        ),
    },
    {
        "intent": "event_analysis",
        "description": "事件驱动分析（FOMC/加息/降息等）",
        "fallback_pattern": re.compile(
            r"FOMC|事件驱动|这次事件|金融事件|事件分析|超预期|price in|priced_in|加息事件|降息事件"
        ),
    },
    {
        "intent": "risk_control",
        "description": "风控/止盈止损/调控/仓位状态",
        "fallback_pattern": re.compile(
            r"风控|风险度|止盈|止损|调控状态|仓位状态|持仓风控|移动止盈"
        ),
    },
    {
        "intent": "price_query",
        "description": "价格查询（兜底正则：问什么价/价格/现价/实时价/最新价/多少钱）",
        "fallback_pattern": re.compile(r"什么价|价格|现价|实时价|最新价|多少钱|现在.*价"),
    },
    {
        "intent": "event_listing",
        "description": "最近事件/快讯罗列",
        "fallback_pattern": re.compile(
            r"最近.*(事件|快讯|新闻|动态)|最新.*(事件|快讯|新闻)|"
            r".*(货币政策|监管|地缘|经济数据).*(事件|新闻|快讯)|发生了什么|.*新闻$|.*快讯$"
        ),
    },
    {
        "intent": "doc_search",
        "description": "文档/知识检索",
        "fallback_pattern": re.compile(
            r"(查|搜|找|检索|搜索).*(文档|资料|SPEC|规范|手册|指南|知识库|wiki)|"
            r"(文档|资料|SPEC|知识库).*(在哪|位置|路径)|全文检索"
        ),
    },
]

# 辅助：intent 列表（registry 使用 intent 名）
_INTENT_NAMES = [i["intent"] for i in _INTENT_REGISTRY]


def _classify(text: str) -> Dict[str, Any]:
    """对一段文本跑所有 intent 的 pattern，返回最佳匹配（零 token）。

    返回结构：
      {matched: bool, intent: null|str, confidence: float, pattern_type: null|str}

    优先级（与 3.1-FRONTEND/l1-intent-registry.ts 行为一致）：
      Pass 1 先跑所有 fallbackPattern 意图 — 命中即定案（置信度 0.8）
      Pass 2 若 fallback 未命中，再跑 requiredPattern 意图 — 命中置信度 1.0
      多命中（同 pass 内同类型）取注册表顺序第一个（deterministic）
    依据：TS 测试 "当前持仓风控状态" → risk_control（fallbackPattern），
         即使 data_query.requiredPattern（含"当前"）也会命中。
    """
    if not text or not isinstance(text, str):
        return {"matched": False, "intent": None, "confidence": 0.0, "pattern_type": None}

    # Pass 1: fallbackPattern 意图优先
    for entry in _INTENT_REGISTRY:
        fp = entry.get("fallback_pattern")
        if fp and fp.search(text):
            return {
                "matched": True,
                "intent": entry["intent"],
                "confidence": 0.8,
                "pattern_type": "fallback",
            }

    # Pass 2: requiredPattern 意图（仅当 fallback 未命中）
    for entry in _INTENT_REGISTRY:
        rp = entry.get("required_pattern")
        if rp and rp.search(text):
            return {
                "matched": True,
                "intent": entry["intent"],
                "confidence": 1.0,
                "pattern_type": "required",
            }

    return {"matched": False, "intent": None, "confidence": 0.0, "pattern_type": None}


# ── 工具实现 ──


def _handle_list_intents(args: Dict[str, Any]) -> Dict[str, Any]:
    """返回全部 12 个 L1 意图的名称 + 描述（零 token）。"""
    return {
        "intents": [
            {"intent": i["intent"], "description": i["description"]} for i in _INTENT_REGISTRY
        ],
        "total": len(_INTENT_REGISTRY),
        "source": "l1-intent-registry.ts",
    }


def _handle_classify_intent(args: Dict[str, Any]) -> Dict[str, Any]:
    """对 query 跑零 token 正则匹配，返回最佳 intent + 置信度。"""
    query = args.get("query") or args.get("text") or ""
    if not isinstance(query, str) or not query.strip():
        return {
            "ok": False,
            "error_code": "invalid",
            "reason": "query 必须是非空字符串",
        }
    result = _classify(query.strip())
    return result  # matched / intent / confidence / pattern_type


def _handle_execute_intent(args: Dict[str, Any]) -> Dict[str, Any]:
    """只读意图"执行"——零 token 正则匹配 + 结构化返回（无下游服务调用）。

    壳内零业务逻辑：execute_intent 本质是 classify_intent + 一个"候选参数"字典。
    真正的数据类/技术面执行由 3.1-FRONTEND 在前端 in-process 完成，
    MCP 壳只输出"该走哪个 L1 执行器 + 上下文"。
    """
    query = args.get("query") or args.get("text") or ""
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "error_code": "invalid", "reason": "query 必须是非空字符串"}

    cls = _classify(query.strip())
    if not cls["matched"]:
        return {
            "ok": True,
            "executed": False,
            "l1_hit": False,
            "reason": "未命中任何 L1 意图，应走 L2",
            "classification": cls,
        }

    return {
        "ok": True,
        "executed": True,
        "l1_hit": True,
        "classification": cls,
        "intent_name": cls["intent"],
        "context": {
            "query": query,
            "pattern_type": cls["pattern_type"],
        },
        "meta": {
            "source": "l1.intent.mcp",
            "zero_token": True,
        },
    }


_TOOL_DEFS = {
    "list_intents": {
        "description": "列出所有 L1 意图（12 个）及其描述；纯静态注册表读取，零 token。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    "classify_intent": {
        "description": "对一段 query 跑 L1 意图零 token 正则匹配，返回最佳 intent + 置信度 + pattern_type。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "待分类文本"},
            },
            "required": ["query"],
        },
    },
    "execute_intent": {
        "description": "只读意图执行：对 query 做 L1 正则匹配 + 结构化返回（无下游服务调用，零 token）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "待匹配文本"},
            },
            "required": ["query"],
        },
    },
}

_TOOL_HANDLERS = {
    "list_intents": _handle_list_intents,
    "classify_intent": _handle_classify_intent,
    "execute_intent": _handle_execute_intent,
}


# tools/list 所需的 tool 列表（与 _TOOL_DEFS 同源，shell_runtime.build_tool_list 自动派生）
_TOOL_LIST = [
    {
        "name": name,
        "description": defs["description"],
        "inputSchema": defs["inputSchema"],
        "annotations": defs.get("annotations", {}),
    }
    for name, defs in _TOOL_DEFS.items()
]


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """测试入口：单参数 JSON-RPC 请求分发（仿照 l1_trading/server.py L604-650）。

    不用 shell_runtime.handle_request——它是 keyword-only 签名，且内部会从 registry
    派生 tools 列表（测试环境可能找不到注册表）。此处手写 dispatch 保持确定性。
    """
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SHELL_SOURCE, "version": "0.1"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _TOOL_LIST},
        }

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        result = handler(params.get("arguments") or {})
        # handler 返回 dict → json.dumps 成 MCP content text
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, _TOOL_DEFS, _TOOL_HANDLERS)

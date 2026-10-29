# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · MCP Server（SPEC §8.3 标准封装）

将本系统核心能力封装为 MCP 标准工具，任何支持 MCP 的大模型/客户端可即插即用。

工具清单:
  - distill_aliases: 蒸馏管线（权威源校验+增量检测+可选 LLM 线索蒸馏）[写操作，需确认]
  - query_entity:    实体解析（中文别名→代号，只读）
  - training_feed:   训练样本喂入 34 系统 [写操作，需确认]
  - semantic_lookup:  金融语义查询（别名表/术语查询，只读）

协议: MCP stdio (JSON-RPC 2.0)
原则: FAIL-OPEN 贯穿所有工具，任何异常返回错误信息不崩溃。

启动: python3 mcp_server.py（由 MCP 客户端以 stdio 方式拉起）
"""
import json
import os
import re
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)
_ALIASES_PATH = os.path.join(_REPO, "3.1-FRONTEND", "scripts", "entity_aliases.json")
_DISTILL_SCRIPT = os.path.join(_THIS_DIR, "distill_aliases.py")
_TRAINING_URL = "http://localhost:3001/api/training"


def _load_aliases():
    try:
        with open(_ALIASES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def tool_query_entity(message):
    """实体解析: 从用户消息中解析金融标的代号（中文别名最长匹配优先）。"""
    aliases = _load_aliases()
    pairs = []
    for sym, names in aliases.items():
        for a in names or []:
            # 收紧：单字别名不参与子串匹配（避免『金』误命中『资金费率』等）
            if a and len(a) >= 2 and a in (message or ""):
                pairs.append((len(a), sym))
    if pairs:
        pairs.sort(reverse=True)
        return {"symbol": pairs[0][1], "matched_alias": None, "method": "alias"}
    m = re.search(r"([A-Z]{2,10})", (message or "").upper())
    if m:
        return {"symbol": m.group(1), "matched_alias": None, "method": "regex"}
    return {"symbol": None, "need_clarification": True,
            "hint": "未识别到标的，请提供币种名（如：以太坊、BTC、黄金）"}


def _load_term_tables():
    """加载九大术语表（五大域 + P-术语四类新域）。"""
    tables = {}
    for d in ("indicator", "strategy", "theory", "finance", "algorithm",
              "people", "tokenomics", "sector", "macro"):
        p = os.path.join(_SYS_DIR, f"{d}_terms.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                tables[d] = json.load(f)
        except Exception:
            tables[d] = {"terms": []}
    return tables


def tool_semantic_lookup(term):
    """语义查询: 查询术语/标的的语义信息（实体别名 + 三大术语域）。"""
    aliases = _load_aliases()
    term = (term or "").strip()
    if not term:
        return {"error": "missing term"}
    # 1) 实体命中
    if term in aliases:
        return {"symbol": term, "aliases": aliases[term], "type": "entity"}
    resolved = tool_query_entity(term)
    if resolved.get("symbol") and resolved["symbol"] in aliases:
        return {"symbol": resolved["symbol"], "aliases": aliases[resolved["symbol"]],
                "type": "entity", "matched_via": resolved.get("method")}
    # 2) 术语域命中（精确 + 包含匹配）
    tables = _load_term_tables()
    for domain, table in tables.items():
        for t in table.get("terms", []):
            if t["term"] == term:
                return {"type": "term", "domain": domain, **t}
        for t in table.get("terms", []):
            if term in t["term"] or t["term"] in term:
                return {"type": "term", "domain": domain, "matched_via": "fuzzy", **t}
    return {"symbol": None, "type": "unknown",
            "hint": f"术语『{term}』暂未入库，可作为蒸馏候选（阶段二三圈扩散触发信号）"}


def tool_distill_aliases(pool, with_llm=False):
    """蒸馏管线: 权威源校验+增量检测+可选 LLM 线索蒸馏。[写操作]"""
    cmd = [sys.executable, _DISTILL_SCRIPT]
    if pool:
        cmd += ["--pool", pool]
    if with_llm:
        cmd += ["--with-llm"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {"exit_code": r.returncode, "output": r.stdout[-2000:], "error": r.stderr[-500:]}
    except Exception as e:
        return {"exit_code": -1, "error": str(e)}


def tool_training_feed(layer, batch):
    """训练喂入: 将样本批量喂入 34 训练系统。[写操作]"""
    if not isinstance(batch, list) or not batch:
        return {"error": "batch must be non-empty list"}
    try:
        import urllib.request
        body = json.dumps({"action": "feed", "data": {"batch": batch}}).encode("utf-8")
        req = urllib.request.Request(
            f"{_TRAINING_URL}/{layer}", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e), "degraded": True}


# ── MCP 工具定义（schema）──────────────────────────────
TOOLS = [
    {
        "name": "query_entity",
        "description": "实体解析: 从用户消息中解析金融标的代号（中文别名优先，如『以太坊』→ETH）。只读。",
        "inputSchema": {"type": "object", "properties": {
            "message": {"type": "string", "description": "用户消息原文"}},
            "required": ["message"]},
    },
    {
        "name": "semantic_lookup",
        "description": "金融语义查询: 查询标的别名/技术指标/交易策略/交易理论/金融概念/交易算法/金融人物/代币机制/金融板块/宏观术语的语义信息与定义。只读。",
        "inputSchema": {"type": "object", "properties": {
            "term": {"type": "string", "description": "术语或标的名"}},
            "required": ["term"]},
    },
    {
        "name": "distill_aliases",
        "description": "蒸馏管线: 权威源校验+交易池增量检测+可选 LLM 线索蒸馏。写操作，需用户确认后执行。",
        "inputSchema": {"type": "object", "properties": {
            "pool": {"type": "string", "description": "交易池标的（逗号分隔，可选）"},
            "with_llm": {"type": "boolean", "description": "启用 LLM 线索蒸馏（默认 false，零成本）"}},
            "required": []},
    },
    {
        "name": "training_feed",
        "description": "训练喂入: 将样本批量喂入 34 训练系统指定层。写操作，需用户确认后执行。",
        "inputSchema": {"type": "object", "properties": {
            "layer": {"type": "string", "enum": ["S", "DSH", "C", "G", "LLM"], "description": "训练层"},
            "batch": {"type": "array", "description": "训练样本列表 [{message,intent_type,quality}]"}},
            "required": ["layer", "batch"]},
    },
]


def _record_reasoning_trace(tool, args, result, elapsed_ms, llm_involved=False):
    """P5 前置 M3：推理过程记录采集点（spec v0.5 §9.2）。

    记录：查询输入 → 各层语义命中 → 综合结论，落 reasoning_trace.jsonl。
    FAIL-OPEN：记录失败不影响主链路。
    """
    import time
    try:
        trace = {
            "schema_version": "0.5",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "input": {k: v for k, v in (args or {}).items() if isinstance(v, (str, bool, int, float))},
            "semantic_hits": [],
            "conclusion": {},
            "elapsed_ms": round(elapsed_ms, 2),
            "llm_involved": llm_involved,
            "token_budget_note": "distill with_llm=true 时 LLM 参与，token 预算由蒸馏管线控制" if llm_involved else None,
        }
        if isinstance(result, dict):
            # 各层语义命中提取（实体层/术语域层/匹配方式）
            if result.get("type"):
                trace["semantic_hits"].append({"layer": "result_type", "value": result.get("type")})
            if result.get("symbol"):
                trace["semantic_hits"].append({"layer": "entity", "value": result.get("symbol"), "matched_via": result.get("matched_via") or result.get("method")})
            if result.get("domain"):
                trace["semantic_hits"].append({"layer": "term_domain", "value": result.get("domain")})
            if result.get("need_clarification"):
                trace["semantic_hits"].append({"layer": "clarification", "value": result.get("hint")})
            # 综合结论（去除大字段，保留摘要）
            trace["conclusion"] = {k: v for k, v in result.items() if k in ("symbol", "type", "domain", "term", "method", "matched_via", "error", "hint", "need_clarification")}
        trace_path = os.path.join(_SYS_DIR, "reasoning_trace.jsonl")
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:
        pass  # FAIL-OPEN


def _dispatch(name, args):
    import time as _time
    _t0 = _time.time()
    if name == "query_entity":
        _r = tool_query_entity(args.get("message", ""))
    elif name == "semantic_lookup":
        _r = tool_semantic_lookup(args.get("term", ""))
    elif name == "distill_aliases":
        _llm = bool(args.get("with_llm", False))
        _r = tool_distill_aliases(args.get("pool", ""), _llm)
        _record_reasoning_trace(name, args, _r, (_time.time() - _t0) * 1000, llm_involved=_llm)
        return _r
    elif name == "training_feed":
        _r = tool_training_feed(args.get("layer", "S"), args.get("batch", []))
    else:
        _r = {"error": f"unknown tool: {name}"}
    _record_reasoning_trace(name, args, _r, (_time.time() - _t0) * 1000)
    return _r


def main():
    """MCP stdio 主循环: JSON-RPC 2.0。FAIL-OPEN: 任何异常返回错误响应不崩溃。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method", "")
        rid = req.get("id")
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mcp-server-finance-distill", "version": "0.1.0"}}
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params", {})
                result = {"content": [{"type": "text",
                                        "text": json.dumps(_dispatch(params.get("name", ""), params.get("arguments", {})), ensure_ascii=False)}]}
            else:
                resp = {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": f"method not found: {method}"}}
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
                continue
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

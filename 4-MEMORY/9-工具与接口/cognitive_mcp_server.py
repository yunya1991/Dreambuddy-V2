#!/usr/bin/env python3
"""
认知MCP服务器 — CognitiveMCPServer

将认知闭环系统封装为MCP (Model Context Protocol) server，
让任何支持MCP的开发系统（TRAE/Claude Code/Cursor）都能调用认知系统。

零外部依赖：纯Python标准库实现JSON-RPC 2.0 over stdio。
不修改cognitive_loop_entry.py任何代码（Adapter Pattern）。

暴露5个标准MCP tools:
  - recall: 检索相关记忆（任务前调用）
  - record: 记录新经验（任务后调用）
  - verify: A8校验 + 贝叶斯更新（验证后调用）
  - stats: 记忆系统统计
  - health: 健康检查

用法（MCP客户端配置）:
  在IDE的MCP配置中添加:
  {
    "mcpServers": {
      "cognitive": {
        "command": "python3",
        "args": ["/path/to/cognitive_mcp_server.py"]
      }
    }
  }

用法（手动测试）:
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python3 cognitive_mcp_server.py
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cognitive_loop_entry import CognitiveLoopEntry, get_cle, reset_cle


# ============================================================
# MCP Server Info
# ============================================================

SERVER_NAME = "cognitive-memory-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

# ============================================================
# Tool Definitions
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "recall",
        "description": "【硬约束·不可跳过】在开始任何编码/调试/分析任务前必须调用。检索相关历史经验，避免重复踩坑、复用已有解决方案。即使认为没有相关经验也必须调用一次——记忆库可能有你不知道的记录。此工具只读不写，无副作用。默认 min_quality=C 返回最多结果，按相关度排序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "任务描述或上下文关键词",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数（默认5）",
                    "default": 5,
                },
                "min_quality": {
                    "type": "string",
                    "description": "最低质量等级 (S/A/B/C/D，默认C)。C级返回最多结果，B级过滤低质量记忆。建议先用C级检索，无相关结果再收紧。",
                    "default": "C",
                },
            },
            "required": ["context"],
        },
    },
    {
        "name": "record",
        "description": "记录新的开发经验到记忆系统。在完成任务后发现新经验时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "经验内容描述",
                },
                "quality_level": {
                    "type": "string",
                    "description": "质量等级 (S/A/B/C/D，默认C)",
                    "default": "C",
                },
                "tags": {
                    "type": "string",
                    "description": "标签（逗号分隔）",
                },
                "source": {
                    "type": "string",
                    "description": "经验来源",
                    "default": "mcp",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "verify",
        "description": "验证记忆并触发贝叶斯置信度更新。在A8校验或测试完成后调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "记忆ID",
                },
                "success": {
                    "type": "boolean",
                    "description": "验证是否成功",
                    "default": True,
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "stats",
        "description": "获取记忆系统统计信息（总数、质量分布、容量等）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "health",
        "description": "记忆系统健康检查（存储状态、引擎状态、容量等）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOL_DEFINITIONS}


# ============================================================
# CognitiveLoopEntry 单例（懒加载）
# ============================================================

_cle_instance: Optional[CognitiveLoopEntry] = None


def _get_cle() -> CognitiveLoopEntry:
    return get_cle()


_skill_loader_instance = None


def _get_skill_loader():
    """SkillLoader 懒加载单例（设计节 3.3）。"""
    global _skill_loader_instance
    if _skill_loader_instance is None:
        from cognitive_superpowers import SkillLoader
        _skill_loader_instance = SkillLoader()
    return _skill_loader_instance


def _reset_cle():
    """重置单例（测试用）"""
    reset_cle()


# ============================================================
# Tool Handlers
# ============================================================

def _handle_recall(args: Dict[str, Any]) -> str:
    context = args.get("context", "")
    top_k = args.get("top_k", 5)
    min_quality = args.get("min_quality", "C")
    include_process = args.get("include_process", True)  # 默认 True（设计节 3.3）

    results = _get_cle().recall(context, top_k=top_k, min_quality=min_quality)

    response: Dict[str, Any] = {
        "memories": results,
        "count": len(results),
    }

    if include_process:
        try:
            loader = _get_skill_loader()
            proc_result = loader.retrieve(context, top_meta=2, top_applied=2)
            # retrieve 返回 {"meta": [(SuperpowersSkill, score, reason), ...], "applied": []}
            meta_list = []
            md_parts = []
            for (skill, score, reason) in proc_result.get("meta", []):
                meta_list.append({
                    "skill_id": skill.skill_id,
                    "display_name": skill.display_name,
                    "match_score": round(score, 2),
                    "match_reason": reason,
                    "hard_gates": skill.hard_gates,
                    "localized": skill.localized,
                })
                md_parts.append(
                    f"### [{skill.skill_id}] {skill.display_name}\n"
                    f"- 匹配度: {score:.2f}\n- {reason}"
                )
            applied_list = proc_result.get("applied", [])
            process_block_md = "\n\n".join(md_parts)
            response["processes"] = {
                "meta": meta_list,
                "applied": applied_list,
                "process_block_markdown": process_block_md,
            }
            # 同时写入 WorkingMemory.process_block（设计节 3.3）
            try:
                cle = _get_cle()
                if hasattr(cle, "working_memory"):
                    cle.working_memory.load_process_block(process_block_md)
            except Exception:
                pass
        except Exception as e:
            # process 检索失败不影响 memories 返回（GC6 异常隔离）
            response["processes"] = {
                "meta": [], "applied": [],
                "process_block_markdown": "", "error": str(e),
            }

    return json.dumps(response, ensure_ascii=False)


def _handle_record(args: Dict[str, Any]) -> str:
    content = args.get("content", "")
    quality_level = args.get("quality_level", "C")
    tags_str = args.get("tags", "")
    source = args.get("source", "mcp")

    tags = [t.strip() for t in tags_str.split(",")] if tags_str else []

    memory_id = _get_cle().record(
        content=content,
        quality_level=quality_level,
        confidence=0.3,
        tags=tags,
        source=source,
    )

    return json.dumps({
        "memory_id": memory_id,
        "status": "recorded",
    }, ensure_ascii=False)


def _handle_verify(args: Dict[str, Any]) -> str:
    memory_id = args.get("memory_id", "")
    success = args.get("success", True)

    result = _get_cle().verify(memory_id, success=success)

    return json.dumps(result, ensure_ascii=False)


def _handle_stats(args: Dict[str, Any]) -> str:
    result = _get_cle().stats()
    return json.dumps(result, ensure_ascii=False)


def _handle_health(args: Dict[str, Any]) -> str:
    result = _get_cle().healthcheck()
    return json.dumps(result, ensure_ascii=False)


TOOL_HANDLERS = {
    "recall": _handle_recall,
    "record": _handle_record,
    "verify": _handle_verify,
    "stats": _handle_stats,
    "health": _handle_health,
}


# ============================================================
# JSON-RPC 2.0 Handler
# ============================================================

def handle_jsonrpc(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理单个JSON-RPC 2.0请求。
    
    支持的method:
      - initialize: MCP握手
      - tools/list: 列出可用工具
      - tools/call: 调用工具
      - notifications/initialized: 初始化完成通知（无需响应）
    """
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # === initialize ===
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    # === notifications/initialized (无需响应) ===
    if method == "notifications/initialized":
        return None  # 通知不需要响应

    # === tools/list ===
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOL_DEFINITIONS,
            },
        }

    # === tools/call ===
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_NAMES:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Unknown tool: {tool_name}. Available: {sorted(TOOL_NAMES)}",
                },
            }

        try:
            handler = TOOL_HANDLERS[tool_name]
            result_text = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": result_text},
                    ],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": f"Tool execution error: {type(e).__name__}: {e}",
                },
            }

    # === 未知方法 ===
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    }


# ============================================================
# stdio Server Loop
# ============================================================

def run_server():
    """
    MCP stdio server主循环。
    从stdin读取JSON-RPC请求，向stdout写入JSON-RPC响应。
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: invalid JSON"},
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handle_jsonrpc(request)

        # 通知类消息不需要响应
        if response is None:
            continue

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def _warmup_process_cli(context: str) -> int:
    """路径 B 执行体：SessionStart hook 调用，后台预取 process_block 写入 WorkingMemory。
    不打扰原则：不输出 stdout；process_block 已有内容则跳过。"""
    cle = _get_cle()
    wm = getattr(cle, "working_memory", None)
    if wm is None:
        return 0
    if hasattr(wm, "process_block") and getattr(wm.process_block, "items", None):
        # process_block 已有内容则跳过（WorkingMemory.process_block 是 MemoryBlock，items 非空=已预热）
        return 0
    try:
        loader = _get_skill_loader()
        results = loader.retrieve(context or "general", top_meta=2, top_applied=2)
        markdown = results.get("process_block_markdown", "")
        if not markdown:
            # SkillLoader.retrieve 不返回 process_block_markdown 时，从 meta 自行拼装
            md_parts = []
            for (sk, sc, rsns) in results.get("meta", []):
                md_parts.append(f"### [{sk.skill_id}] {sk.display_name}\n- 匹配度: {sc:.2f}")
            markdown = "\n\n".join(md_parts)
        if markdown and hasattr(wm, "load_process_block"):
            wm.load_process_block(markdown)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    import sys
    # 支持 --recall-context 参数（SessionStart hook 调用）
    # 用法: python3 cognitive_mcp_server.py --recall-context "会话上下文"
    # 输出: 相关记忆的 Markdown 文本（注入到 IDE 会话上下文）
    if "--warmup_process" in sys.argv:
        # 路径 B：SessionStart hook 后台预热 process_block（设计节 3.4）
        idx = sys.argv.index("--warmup_process")
        context = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        sys.exit(_warmup_process_cli(context))
    if "--recall-context" in sys.argv:
        idx = sys.argv.index("--recall-context")
        context = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        try:
            cle = _get_cle()
            # 空上下文退化：检索最近更新的高价值记忆（按 updated_at 降序）
            if not context.strip():
                memories = cle.search(query="", top_k=5)
            else:
                memories = cle.recall(context, top_k=5, min_quality="C")
            if memories:
                print("\n## 🧠 认知系统注入的相关经验\n")
                for m in memories:
                    quality = m.get("quality_level", "?")
                    content = m.get("content", "")
                    tags = ", ".join(m.get("tags", []))
                    print(f"- **[{quality}]** {content}")
                    if tags:
                        print(f"  - 标签: {tags}")
                print("\n*(来自认知记忆系统，基于当前会话上下文自动检索)*\n")
            else:
                print("\n<!-- 认知系统：当前无相关记忆可注入。请在任务前主动调用 recall 工具。 -->\n")
        except Exception as e:
            # hook 失败不阻塞 IDE 会话
            print(f"<!-- 认知注入失败: {e} -->", file=sys.stderr)
    else:
        run_server()

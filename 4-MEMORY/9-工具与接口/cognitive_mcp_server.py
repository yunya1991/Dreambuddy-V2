#!/usr/bin/env python3
"""
认知MCP服务器 — CognitiveMCPServer

将认知闭环系统封装为MCP (Model Context Protocol) server，
让任何支持MCP的开发系统（TRAE/Claude Code/Cursor）都能调用认知系统。

零外部依赖：纯Python标准库实现JSON-RPC 2.0 over stdio。
不修改cognitive_loop_entry.py任何代码（Adapter Pattern）。

暴露7个标准MCP tools:
  - recall: 检索相关记忆（任务前调用，只读）
  - unified_search: 41/Chroma/recall 三后端统一检索（只读）
  - record: 记录新经验（写，需 host write scope）
  - verify: A8校验 + 贝叶斯更新（写，需 host write scope）
  - stats / health / l4_status: 统计、健康、L4 元认知状态（只读）

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
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cognitive_loop_entry import CognitiveLoopEntry, get_cle, reset_cle  # noqa: E402

# envelope_wrap（L0 统一信封外层包装）
_ENVELOPE_DIR = Path(__file__).resolve().parents[2] / "mcp_shells" / "_shared"
if str(_ENVELOPE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENVELOPE_DIR))
from envelope_wrap import wrap as _wrap  # noqa: E402

# 统一壳运行时（P2 全量迁移）：协议循环 + registry 派生 tools/list
_REPO_ROOT = _ENVELOPE_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from mcp_shells._shared.shell_runtime import (  # noqa: E402
    build_tool_list,
    handle_request as _runtime_handle,
    run_stdio,
)

# ============================================================
# 双模（D5 / M3⑧）：ssh 云端默认（单一事实源）+ 本地只读降级
# COGNITIVE_MCP_MODE=local → 写工具（record/verify）明确拒绝（非静默），审计留痕
# ============================================================
COGNITIVE_MCP_MODE = os.environ.get("COGNITIVE_MCP_MODE", "ssh").strip().lower()
_LOCAL_READONLY = COGNITIVE_MCP_MODE == "local"


def _write_denied(tool: str, *, reason: str | None = None,
                  error_code: str = "conflict") -> str:
    """写工具拒绝：本地只读或写 scope/principal 不满足（审计留痕 stderr）。"""
    import sys as _sys

    reason = reason or "write tool disabled in local readonly mode (D5); use ssh cloud profile for writes"
    print(
        json.dumps(
            {
                "event": "write_denied",
                "shell": "l0.cognition.mcp",
                "tool": tool,
                "mode": COGNITIVE_MCP_MODE,
                "reason": reason,
                "error_code": error_code,
            }
        ),
        file=_sys.stderr,
    )
    return json.dumps(
        _wrap(
            None,
            "cognition." + tool,
            degraded=True,
            error_code=error_code,
            meta={"reason": reason},
        ),
        ensure_ascii=False,
    )


# §5.2 C6：写主体矩阵（Worker 默认只读）
PRINCIPAL_ROLES = ("worker", "orchestrator", "verifier", "admin")
WRITE_ROLES = frozenset({"orchestrator", "verifier", "admin"})


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _write_principal(args: Dict[str, Any]) -> str:
    """解析写主体：默认由宿主 Mandate（env）注入，不信任调用方自声明。"""
    if _env_flag("COGNITIVE_MCP_ALLOW_CALLER_PRINCIPAL", default=False):
        caller = str(args.get("principal") or "").strip()
        if caller:
            return caller
    return os.environ.get("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "").strip()


def _write_gate(tool: str, args: Dict[str, Any]) -> Optional[str]:
    """写门禁（§5.2 C6）：返回 None 放行，否则返回拒绝响应 JSON。"""
    if _LOCAL_READONLY:
        return _write_denied(tool)
    if not _env_flag("COGNITIVE_MCP_WRITE_ENABLED", default=False):
        return _write_denied(
            tool,
            reason="write scope not granted (COGNITIVE_MCP_WRITE_ENABLED != true)",
            error_code="scope_denied",
        )
    principal = _write_principal(args)
    if principal not in WRITE_ROLES:
        return _write_denied(
            tool,
            reason=f"principal={principal!r} not allowed for write; "
                   f"need one of {sorted(WRITE_ROLES)}",
            error_code="principal_denied",
        )
    return None


def _trace_id(args: Dict[str, Any]) -> str:
    """§5.2 C4：trace 贯穿，优先调用方 trace_id，其次宿主环境变量。"""
    return str(args.get("trace_id") or os.environ.get("MCP_TRACE_ID", "")).strip()


def _eval_gate(args: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
    """§5.2 C5：45 评测门禁。off / shadow（默认仅记录）/ enforce（fail-closed）。"""
    mode = os.environ.get("COGNITIVE_MCP_EVAL_GATE_MODE", "shadow").strip().lower()
    eval_id = str(args.get("eval_id") or "").strip()
    if mode == "off":
        return True, {"mode": "off", "decision": "SKIP"}
    if mode == "shadow":
        return True, {
            "mode": "shadow",
            "decision": "OBSERVED" if eval_id else "SHADOW_WOULD_BLOCK",
            "eval_id": eval_id,
            "reasons": [] if eval_id else ["eval_id_missing (shadow only)"],
        }
    if not eval_id:
        return False, {"mode": "live", "decision": "BLOCK", "reasons": ["eval_id_missing"]}
    try:
        gate_dir = Path(__file__).resolve().parents[2] / "45-评测系统"
        if str(gate_dir) not in sys.path:
            sys.path.insert(0, str(gate_dir))
        from core.enforcement import Enforcer  # type: ignore[import-not-found]
        from core.gate import Gate  # type: ignore[import-not-found]
        from storage.repo import EvalRepo  # type: ignore[import-not-found]

        decision = Enforcer(Gate(EvalRepo()), shadow=False).enforce("l0_settle", eval_id)
        return bool(decision.allowed), decision.to_dict()
    except Exception as exc:
        return False, {
            "mode": "live",
            "decision": "BLOCK",
            "reasons": [f"eval_gate_unavailable: {exc}"],
        }


from envelope_wrap import wrap_merge_partial as _wrap_merge  # noqa: E402

# ============================================================
# MCP Server Info
# ============================================================

SERVER_NAME = "cognitive-memory-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"
SHELL_ID = "l0.cognition.mcp"

# ============================================================
# Tool Definitions
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "recall",
        "description": "【硬约束·不可跳过】在开始任何编码/调试/分析任务前必须调用。检索相关历史经验，避免重复踩坑、复用已有解决方案。即使认为没有相关经验也必须调用一次——记忆库可能有你不知道的记录。此工具只读不写，无副作用。默认 min_quality=C 返回最多结果，按相关度排序。",
        "annotations": {"readOnlyHint": True},
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
        "description": "记录新的开发经验到记忆系统。在完成任务后发现新经验时调用。写工具需宿主写 scope + 授权主体（默认禁用）。",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
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
                "level": {
                    "type": "string",
                    "description": "Evidence事实分级 (observation/derivation/inference/unknown，默认observation)",
                    "default": "observation",
                    "enum": ["observation", "derivation", "inference", "unknown"],
                },
                "confidence_score": {
                    "type": "number",
                    "description": "连续置信度 0.0-1.0（不传则由 quality_level 映射）",
                },
                "known_gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "已知局限列表",
                },
                "observations": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "支撑观察列表",
                },
                "external_id": {
                    "type": "string",
                    "description": "幂等键（同 key 只写 1 条，C3）",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "external_id 的同义字段（C3）",
                },
                "principal": {
                    "type": "string",
                    "enum": list(PRINCIPAL_ROLES),
                    "description": "写主体（仅当宿主允许调用方自声明时生效；默认由宿主 Mandate 注入）",
                },
                "trace_id": {
                    "type": "string",
                    "description": "链路追踪 ID（C4）",
                },
                "eval_id": {
                    "type": "string",
                    "description": "45 评测受理 ID（C5；enforce 模式必填）",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "verify",
        "description": "验证记忆并触发贝叶斯置信度更新。在A8校验或测试完成后调用。写工具需宿主写 scope + 授权主体（默认禁用）。",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
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
                "known_gaps_update": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "验证后更新的已知局限列表（仅 success=True 时生效，验证后局限可能缩小）",
                },
                "principal": {
                    "type": "string",
                    "enum": list(PRINCIPAL_ROLES),
                    "description": "写主体（仅当宿主允许调用方自声明时生效；默认由宿主 Mandate 注入）",
                },
                "trace_id": {
                    "type": "string",
                    "description": "链路追踪 ID（C4）",
                },
                "eval_id": {
                    "type": "string",
                    "description": "45 评测受理 ID（C5；enforce 模式必填）",
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "stats",
        "description": "获取记忆系统统计信息（总数、质量分布、容量等）。",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "health",
        "description": "记忆系统健康检查（存储状态、引擎状态、容量等）。",
        "annotations": {"readOnlyHint": True},
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
    """获取 CLE 单例。

    COGNITIVE_MCP_DB_PATH（或 DREAMBUDDY_COGNITIVE_DB）可显式指定共享库，
    便于多个 AI 宿主指向同一事实源，避免各自生成 4-MEMORY/data 分叉。
    """
    global _cle_instance
    db_path = (
        os.environ.get("COGNITIVE_MCP_DB_PATH")
        or os.environ.get("DREAMBUDDY_COGNITIVE_DB")
        or ""
    ).strip()
    if not db_path:
        return get_cle()
    if _cle_instance is None:
        _cle_instance = CognitiveLoopEntry(storage_path=db_path)
    return _cle_instance


def _write_policy_snapshot() -> Dict[str, Any]:
    """写治理快照：供新宿主/Agent 自诊断为何写工具不可用。"""
    return {
        "mode": COGNITIVE_MCP_MODE,
        "write_enabled": (not _LOCAL_READONLY)
        and _env_flag("COGNITIVE_MCP_WRITE_ENABLED", default=False),
        "principal": _write_principal({}),
        "eval_gate_mode": os.environ.get(
            "COGNITIVE_MCP_EVAL_GATE_MODE", "shadow"
        ).strip().lower(),
        "db_path": (
            os.environ.get("COGNITIVE_MCP_DB_PATH")
            or os.environ.get("DREAMBUDDY_COGNITIVE_DB")
            or ""
        ),
        "allowed_write_roles": sorted(WRITE_ROLES),
    }


def _optional_deps_snapshot() -> Dict[str, bool]:
    """可选依赖探测（新宿主排障用）。"""
    import importlib.util

    return {
        name: importlib.util.find_spec(name) is not None
        for name in ("networkx", "scipy", "chromadb")
    }


def _l4_snapshot() -> dict:
    """安全获取 CLE 的 L4 状态快照（dict），mock/异常时返回 {}。

    避免直接访问 _l4_state 在测试 mock 场景下返回 MagicMock 导致
    json.dumps 序列化失败。FAIL-OPEN。
    """
    try:
        state = _get_cle()._l4_state
        if isinstance(state, dict):
            return dict(state)
    except Exception:
        pass
    return {}


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
    global _cle_instance
    _cle_instance = None
    reset_cle()


# ============================================================
# P0-1: skill_indexer hooks 接线（record_hook / verify_hook）
# SPEC: SPEC-CognitiveSystem-Evolution.md §2.2.1 P0-1
# 建立 skill ↔ memory 双向关联，FAIL-OPEN
# ============================================================

_skill_indexer_module = None
_skill_indexer_loaded = False


def _load_skill_indexer():
    """延迟加载 skill_indexer 模块，FAIL-OPEN：不可用返回 None。

    skill_indexer 位于 1-ARCHITECTURE/skills/dream-skill-index-governance/，
    提供 record_hook / verify_hook / scan_skills / ALL_SKILL_ROOTS。
    """
    global _skill_indexer_loaded, _skill_indexer_module
    if _skill_indexer_loaded:
        return _skill_indexer_module
    _skill_indexer_loaded = True
    try:
        si_dir = (
            _SCRIPT_DIR.parents[1] / "1-ARCHITECTURE" / "skills" / "dream-skill-index-governance"
        )
        if str(si_dir) not in sys.path:
            sys.path.insert(0, str(si_dir))
        import skill_indexer as _si  # type: ignore[import-not-found]

        _skill_indexer_module = _si
    except Exception:
        _skill_indexer_module = None
    return _skill_indexer_module


def _find_skill_dir_by_name(skill_id: str):
    """从 ALL_SKILL_ROOTS 查找 skill_id 对应的 SKILL 目录（含 SKILL.md）。

    FAIL-OPEN：skill_indexer 不可用或未找到返回 None。
    """
    si = _load_skill_indexer()
    if si is None:
        return None
    try:
        roots = getattr(si, "ALL_SKILL_ROOTS", None)
        if not roots:
            return None
        for root in roots:
            cand = root / skill_id
            if (cand / "SKILL.md").exists():
                return cand
    except Exception:
        return None
    return None


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

    # L4: 附带元认知信号（FOK 把握度 / JOL 学习评估 / 广播计数）
    try:
        l4 = _l4_snapshot()
        response["l4"] = {
            "fok": l4.get("fok"),
            "jol": l4.get("jol"),
            "broadcast_count": l4.get("broadcast_count", 0),
        }
    except Exception:
        pass  # FAIL-OPEN

    if include_process:
        try:
            loader = _get_skill_loader()
            proc_result = loader.retrieve(context, top_meta=2, top_applied=2)
            # retrieve 返回 {"meta": [(SuperpowersSkill, score, reason), ...], "applied": []}
            meta_list = []
            md_parts = []
            for skill, score, reason in proc_result.get("meta", []):
                meta_list.append(
                    {
                        "skill_id": skill.skill_id,
                        "display_name": skill.display_name,
                        "match_score": round(score, 2),
                        "match_reason": reason,
                        "hard_gates": skill.hard_gates,
                        "localized": skill.localized,
                    }
                )
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
                "meta": [],
                "applied": [],
                "process_block_markdown": "",
                "error": str(e),
            }

    return json.dumps(_wrap(response, "cognition.recall"), ensure_ascii=False)


# ============================================================
# TAG_HOOKS — record tags → triggered_skills 自动映射
# SPEC: 1-ARCHITECTURE/SPEC-20260930-COGNITIVE-TAG-HOOKS-AUTO-LOOP.md
# 设计：tag 精确匹配，多 tag 叠加，去重，FAIL-OPEN
# ============================================================

TAG_HOOKS: Dict[str, List[str]] = {
    # 文档同步闭环
    "doc-sync": ["dream-doc-sync-workflow"],
    # Wiki 编译闭环
    "wiki-compile": ["wiki-ingest-trigger"],
    # hermes 反思 → SKILL 创建闭环
    "hermes反思": ["dream-self-iteration-workflow"],
    "SKILL": ["skill-creator"],
    # 硬约束记忆（CLAUDE.md §3）
    "硬约束": ["dream-arch-collaboration-workflow"],
    # 收尾闭环（dream-completion-evolution-workflow）
    "wrapup": ["dream-completion-evolution-workflow"],
    # 代码提交闭环
    "code-commit": ["dream-code-commit-sync-workflow"],
    # 孤儿扫描闭环
    "orphan-scan": ["dream-code-sync-orphan-scan-workflow"],
    # 知识入库闭环
    "knowledge-ingest": ["knowledge-ingest"],
    # 模块开发后验证闭环
    "post-dev-verify": ["dream-module-post-dev-verify-workflow"],
}


def _resolve_triggered_skills(tags: List[str]) -> List[str]:
    """根据 record tags 查询 TAG_HOOKS，返回去重后的 triggered_skills 列表。

    FAIL-OPEN：任何异常返回空列表，不阻塞 record 主流程。
    """
    try:
        triggered: List[str] = []
        for tag in tags:
            tag = tag.strip()
            if tag in TAG_HOOKS:
                for skill in TAG_HOOKS[tag]:
                    if skill not in triggered:  # 去重
                        triggered.append(skill)
        return triggered
    except Exception:
        return []


def _handle_record(args: Dict[str, Any]) -> str:
    denied = _write_gate("record", args)
    if denied:
        return denied
    gate_ok, eval_info = _eval_gate(args)
    if not gate_ok:
        return json.dumps(
            _wrap(
                None,
                "cognition.record",
                degraded=True,
                error_code="eval_gate_denied",
                meta={"eval_gate": eval_info},
                trace_id=_trace_id(args),
            ),
            ensure_ascii=False,
        )
    content = args.get("content", "")
    quality_level = args.get("quality_level", "C")
    tags_str = args.get("tags", "")
    source = args.get("source", "mcp")
    level = args.get("level", "observation")
    known_gaps = args.get("known_gaps") or []
    observations = args.get("observations") or []
    # L4 预测误差门控参数（可选）
    expected_outcome = args.get("expected_outcome")
    actual_outcome = args.get("actual_outcome")

    # confidence_score 不传时从 quality_level 映射
    confidence_score = args.get("confidence_score")
    if confidence_score is None:
        confidence_score = {
            "S": 0.95,
            "A": 0.70,
            "B": 0.40,
            "C": 0.20,
            "D": 0.10,
        }.get(quality_level, 0.3)

    tags = [t.strip() for t in tags_str.split(",")] if tags_str else []

    # 硬约束闸门：tags 含"硬约束"时 known_gaps 必须非空（FAIL-OPEN 填充占位）
    if "硬约束" in tags and not known_gaps:
        known_gaps = ["硬约束记忆需补充具体 known_gaps（已知局限）"]

    external_id = args.get("external_id") or args.get("idempotency_key")

    memory_id = _get_cle().record(
        content=content,
        quality_level=quality_level,
        confidence=confidence_score,
        tags=tags,
        source=source,
        level=level,
        known_gaps=known_gaps,
        observations=observations,
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome,
        external_id=external_id,
    )

    # TAG_HOOKS：查询 tags → triggered_skills（FAIL-OPEN）
    triggered_skills = _resolve_triggered_skills(tags)

    # P0-1：触发 record_hook，建立 skill↔memory 双向关联（FAIL-OPEN）
    # 对每个 triggered_skill 查找 skill_dir 并调用 record_hook，
    # 将 memory_id 写入 SKILL.md cognitive_links + apply_count++
    skill_links: list = []
    si = _load_skill_indexer()
    if si is not None and triggered_skills:
        for skill_id in triggered_skills:
            try:
                skill_dir = _find_skill_dir_by_name(skill_id)
                hook_result = si.record_hook(skill_id, memory_id, skill_dir)
                skill_links.append(hook_result)
            except Exception:
                pass  # FAIL-OPEN：单个 hook 失败不影响其他

    # P0-2：knowledge-ingest 硬标记（区别于 triggered_skills 软触发）
    # tags 含 knowledge-ingest 时，Agent 层应执行 knowledge-ingest SKILL
    # 将记忆内容 RAG 向量化入知识库，避免新经验不入知识库
    knowledge_ingest_required = "knowledge-ingest" in tags

    # P1-L1: 从 Evidence Ledger 获取 receipt_hash（FAIL-OPEN）
    receipt_hash = None
    try:
        cle = _get_cle()
        entries = cle.evidence_ledger.query(subject="record")
        for e in entries:
            if e.object == memory_id:
                receipt_hash = e.receipt_hash
                break
    except Exception:
        pass  # FAIL-OPEN

    return json.dumps(
        _wrap(
            {
                "memory_id": memory_id,
                "status": "recorded",
                "triggered_skills": triggered_skills,
                "skill_links": skill_links,
                "knowledge_ingest_required": knowledge_ingest_required,
                "receipt_hash": receipt_hash,
                "external_id": external_id,
                "principal": _write_principal(args),
                "eval_gate": eval_info,
                "l4": _l4_snapshot(),
            },
            "cognition.record",
            trace_id=_trace_id(args),
        ),
        ensure_ascii=False,
    )


def _handle_verify(args: Dict[str, Any]) -> str:
    denied = _write_gate("verify", args)
    if denied:
        return denied
    gate_ok, eval_info = _eval_gate(args)
    if not gate_ok:
        return json.dumps(
            _wrap(
                None,
                "cognition.verify",
                degraded=True,
                error_code="eval_gate_denied",
                meta={"eval_gate": eval_info},
                trace_id=_trace_id(args),
            ),
            ensure_ascii=False,
        )
    memory_id = args.get("memory_id", "")
    success = args.get("success", True)
    known_gaps_update = args.get("known_gaps_update")

    result = _get_cle().verify(
        memory_id,
        success=success,
        known_gaps_update=known_gaps_update,
    )

    # P0-1：触发 verify_hook，更新 confidence + shadow→active 升级（FAIL-OPEN）
    # 扫描 SKILL entries，反查 cognitive_links 包含 memory_id 的 SKILL，
    # 对每个关联 SKILL 调用 verify_hook。
    skill_hooks: list = []
    si = _load_skill_indexer()
    if si is not None:
        try:
            roots = getattr(si, "ALL_SKILL_ROOTS", None)
            if roots:
                entries = si.scan_skills(roots)
                for entry in entries:
                    try:
                        if memory_id in entry.cognitive_links:
                            skill_dir = _find_skill_dir_by_name(entry.name)
                            hook_result = si.verify_hook(
                                entry.name,
                                success,
                                entries,
                                skill_dir,
                            )
                            skill_hooks.append(hook_result)
                    except Exception:
                        pass  # FAIL-OPEN：单个 hook 失败不影响其他
        except Exception:
            pass  # FAIL-OPEN：扫描失败不影响 verify 主流程

    result["skill_hooks"] = skill_hooks
    result["principal"] = _write_principal(args)
    result["eval_gate"] = eval_info
    # L4: 反思裁决结果（verdict / lessons / should_record）
    try:
        result["l4"] = _l4_snapshot()
    except Exception:
        pass
    return json.dumps(
        _wrap(result, "cognition.verify", trace_id=_trace_id(args)),
        ensure_ascii=False,
    )


def _handle_stats(args: Dict[str, Any]) -> str:
    result = _get_cle().stats()
    if isinstance(result, dict):
        result["mcp_policy"] = _write_policy_snapshot()
    return json.dumps(_wrap(result, "cognition.stats"), ensure_ascii=False)


def _handle_health(args: Dict[str, Any]) -> str:
    result = _get_cle().healthcheck()
    if isinstance(result, dict):
        result["mcp_policy"] = _write_policy_snapshot()
        result["optional_deps"] = _optional_deps_snapshot()
    # C12：job_runs + 五能力 health_cmd 聚合（FAIL-OPEN，不拖垮认知基础健康）
    try:
        import os as _os
        import sys as _sys

        _repo_root = _os.path.abspath(
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")
        )
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from dreambuddy_l0.scheduling.health import collect_l0_health

        result["l0"] = collect_l0_health(repo_root=_repo_root)
    except Exception as exc:
        result["l0"] = {
            "ok": False,
            "degraded": True,
            "error_code": "l0_health_unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    return json.dumps(_wrap_merge(result, "cognition.health"), ensure_ascii=False)


def _handle_l4_status(args: Dict[str, Any]) -> str:
    """L4 元认知层状态聚合 — 供前端应用/训练系统查询。

    返回 WorkspaceBus/SelfModel/PredictionErrorGate/ReflectionNode/MetacogHarness
    的实时状态 + 最近一次 recall/record/verify 的 L4 输出。
    """
    result = _get_cle().get_l4_status()
    return json.dumps(result, ensure_ascii=False)


def _handle_unified_search(args: Dict[str, Any]) -> str:
    """C7 统一检索：经 Search port 分发三后端（41/Chroma/recall），FAIL-OPEN。"""
    import os as _os
    import sys as _sys

    _repo_root = _os.path.abspath(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")
    )
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from dreambuddy_l0.search import get_unified_search

    query = str(args.get("query", ""))
    if not query:
        return json.dumps(
            _wrap_merge(
                {"ok": False, "error_code": "invalid", "error": "missing query"},
                "search.unified",
            ),
            ensure_ascii=False,
        )
    top_k = int(args.get("top_k", 5))
    sources = args.get("sources") or None
    result = get_unified_search().search(query, sources=sources, top_k=top_k)
    # unified_search already returns a full envelope ({ok, data:{hits,...}}).
    # Do NOT wrap it again via _wrap_merge: that helper drops the nested
    # `data` field (it treats it as an envelope key), producing `data: {}`.
    if isinstance(result, dict) and "data" in result:
        result = dict(result)
        result["source"] = "search.unified"
        result.setdefault("version", "0.1")
        return json.dumps(result, ensure_ascii=False)
    return json.dumps(_wrap_merge(result, "search.unified"), ensure_ascii=False)


TOOL_DEFINITIONS.append(
    {
        "name": "unified_search",
        "description": "C7 统一检索：经 Search port 分发三后端（41-SearchAPI/ChromaDB RAG/认知 recall），分数归一化合并去重。单后端失败自动降级其余；全后端不可用返回 error_code=all_sources_unavailable。",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "返回结果数（默认5）", "default": 5},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定后端列表（search41/chroma/recall），默认全部",
                },
            },
            "required": ["query"],
        },
    }
)

TOOL_DEFINITIONS.append(
    {
        "name": "l4_status",
        "description": "L4 元认知层状态聚合：WorkspaceBus / SelfModel / PredictionErrorGate / ReflectionNode / MetacogHarness。",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    }
)

TOOL_NAMES.add("unified_search")
TOOL_NAMES.add("l4_status")
TOOL_HANDLERS = {
    "recall": _handle_recall,
    "unified_search": _handle_unified_search,
    "record": _handle_record,
    "verify": _handle_verify,
    "stats": _handle_stats,
    "health": _handle_health,
    "l4_status": _handle_l4_status,
}


# ============================================================
# JSON-RPC 2.0 Handler（P2：转交统一壳运行时）
# ============================================================

TOOL_DEFS = {
    tool["name"]: {
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
    }
    for tool in TOOL_DEFINITIONS
}

_RUNTIME_TOOLS_CACHE: Optional[List[Dict[str, Any]]] = None


def _runtime_tools() -> List[Dict[str, Any]]:
    global _RUNTIME_TOOLS_CACHE
    if _RUNTIME_TOOLS_CACHE is None:
        _RUNTIME_TOOLS_CACHE = build_tool_list(SHELL_ID, TOOL_DEFS)
    return _RUNTIME_TOOLS_CACHE


def handle_jsonrpc(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """兼容入口：保留旧 API，内部走统一壳运行时。

    部分 MCP 客户端把 arguments 序列化成 JSON 字符串，这里先归一化为 dict。
    """
    params = request.get("params")
    if isinstance(params, dict) and isinstance(params.get("arguments"), str):
        try:
            request = dict(request)
            request["params"] = dict(params, arguments=json.loads(params["arguments"]))
        except json.JSONDecodeError:
            pass

    return _runtime_handle(
        request,
        shell_id=SHELL_ID,
        tools=_runtime_tools(),
        handlers=TOOL_HANDLERS,
        server_name=SERVER_NAME,
    )


# ============================================================
# stdio Server Loop
# ============================================================


def run_server() -> None:
    """MCP stdio 主循环（统一壳运行时）。"""
    run_stdio(
        SHELL_ID,
        TOOL_DEFS,
        TOOL_HANDLERS,
        server_name=SERVER_NAME,
    )


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
            for sk, sc, _rsns in results.get("meta", []):
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
                print(
                    "\n<!-- 认知系统：当前无相关记忆可注入。请在任务前主动调用 recall 工具。 -->\n"
                )
        except Exception as e:
            # hook 失败不阻塞 IDE 会话
            print(f"<!-- 认知注入失败: {e} -->", file=sys.stderr)
    else:
        run_server()

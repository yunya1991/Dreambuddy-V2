#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_context_57.py — 57 提示词运行时上下文注入（SPEC-57 §8 P1）

单一事实源：
  - 注册表：57-Agent提示词工程/registry/prompt_registry.yaml（只登记，不复制正文）
  - 宪法：57-Agent提示词工程/PROMPT_CONSTITUTION.md（现场提取条款表，不复制正文）

本模块只做三件事：
  1. 按 prompt_id 取注册表条目，并校验资产指纹（G-P-2，失配抛 E_CONSTITUTION_DRIFT）；
  2. 按任务类生成宪法注入块（full = C-01..C-12；lite = P4 输出契约 + C-11）；
  3. 生成 L2Envelope.meta 增量字段（IF-P-3，6 字段 + constitution_tokens）。

硬约束：
  - 不改任何 prompt 资产字节；注入只发生在 system prompt 尾部的运行时拼接；
  - 不复制宪法条文正文到代码，条款文本每次从 md 提取；
  - 任何异常对业务 FAIL-OPEN：调用方拿不到 meta 时按原 prompt 继续，不阻断主流程。
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROMPT_HOME = Path(__file__).resolve().parents[1]
REPO_ROOT = PROMPT_HOME.parent
REGISTRY_PATH = PROMPT_HOME / "registry" / "prompt_registry.yaml"
CONSTITUTION_PATH = PROMPT_HOME / "PROMPT_CONSTITUTION.md"

L2_META_VERSION = "1.0"
MAX_FIXED_CONTEXT_TOKENS = 4000  # SPEC-57 §3.1

# 分类/路由类只注入 P4 输出契约 + C-11（EVAL-20261118 §4 决策 1）
LITE_TASKS = {"intent.route", "skill.guide"}
REASONING_EFFORT = {"full": "medium", "lite": "low"}

CLAUSE_RE = re.compile(r"^\|\s*\*\*(C-\d{2})\*\*\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*`([^`]+)`\s*\|")
VERSION_RE = re.compile(r"constitution@(\d+\.\d+\.\d+)")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

_LOCK = threading.Lock()
_REGISTRY_CACHE: Dict[str, Any] = {"mtime": None, "doc": None}
_CONSTITUTION_CACHE: Dict[str, Any] = {"mtime": None, "clauses": None, "version": ""}


class PromptContextError(RuntimeError):
    """E_CONSTITUTION_DRIFT / 注册表缺失等可判红异常。"""


def injection_enabled() -> bool:
    """PROMPT_CONSTITUTION_INJECT=0 时整体关闭注入（对照实验/排障用）。"""
    return os.environ.get("PROMPT_CONSTITUTION_INJECT", "1") != "0"


# ── 注册表 ────────────────────────────────────────────────────────────


def load_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        raise PromptContextError(f"注册表不存在: {REGISTRY_PATH}")
    mtime = REGISTRY_PATH.stat().st_mtime
    with _LOCK:
        if _REGISTRY_CACHE["mtime"] == mtime and _REGISTRY_CACHE["doc"] is not None:
            return _REGISTRY_CACHE["doc"]
        import yaml

        doc = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            raise PromptContextError("注册表根节点必须是映射")
        _REGISTRY_CACHE.update({"mtime": mtime, "doc": doc})
        return doc


def get_prompt(prompt_id: str) -> Dict[str, Any]:
    for item in load_registry().get("prompts") or []:
        if isinstance(item, dict) and item.get("prompt_id") == prompt_id:
            return item
    raise PromptContextError(f"prompt_id 未登记: {prompt_id}")


# ── 指纹 ──────────────────────────────────────────────────────────────


def asset_fingerprint(entry: Dict[str, Any]) -> str:
    """file = sha256(原始字节)；tree = sha256(按相对路径排序拼接 '<relpath>\\n<sha256>\\n')。"""
    asset = entry.get("asset_path")
    if not isinstance(asset, str) or not asset:
        raise PromptContextError(f"{entry.get('prompt_id')}: asset_path 非法")
    target = REPO_ROOT / asset
    if entry.get("asset_kind") == "tree":
        if not target.is_dir():
            raise PromptContextError(f"{asset}: 不是目录")
        chunks: List[str] = []
        for path in sorted(p for p in target.rglob("*") if p.is_file()):
            rel = path.relative_to(target).as_posix()
            chunks.append(f"{rel}\n{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
        return "sha256:" + hashlib.sha256("".join(chunks).encode("utf-8")).hexdigest()
    if not target.is_file():
        raise PromptContextError(f"{asset}: 不是文件")
    return "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()


def verify_fingerprint(entry: Dict[str, Any]) -> str:
    """返回实际指纹；与注册表登记不符即 E_CONSTITUTION_DRIFT。"""
    actual = asset_fingerprint(entry)
    declared = entry.get("fingerprint")
    if declared and declared != actual:
        raise PromptContextError(
            f"E_CONSTITUTION_DRIFT: {entry.get('prompt_id')} 指纹不符 "
            f"(declared={declared}, actual={actual})"
        )
    return actual


# ── 宪法 ──────────────────────────────────────────────────────────────


def load_constitution() -> Tuple[str, Dict[str, Dict[str, str]]]:
    if not CONSTITUTION_PATH.is_file():
        raise PromptContextError(f"宪法文件不存在: {CONSTITUTION_PATH}")
    mtime = CONSTITUTION_PATH.stat().st_mtime
    with _LOCK:
        if _CONSTITUTION_CACHE["mtime"] == mtime and _CONSTITUTION_CACHE["clauses"] is not None:
            return _CONSTITUTION_CACHE["version"], _CONSTITUTION_CACHE["clauses"]

        text = CONSTITUTION_PATH.read_text(encoding="utf-8")
        match = VERSION_RE.search(text)
        if not match:
            raise PromptContextError("宪法缺少 constitution@x.y.z 版本标记")
        clauses: Dict[str, Dict[str, str]] = {}
        for line in text.splitlines():
            row = CLAUSE_RE.match(line)
            if row:
                cid, requirement, criterion, code = row.groups()
                clauses[cid] = {
                    "requirement": requirement,
                    "criterion": criterion,
                    "code": code,
                }
        if not clauses:
            raise PromptContextError("宪法 §3 条款表未提取到任何条款")
        _CONSTITUTION_CACHE.update({"mtime": mtime, "clauses": clauses, "version": match.group(1)})
        return match.group(1), clauses


def constitution_version() -> str:
    return load_constitution()[0]


def persona() -> Dict[str, Any]:
    """注册表 persona 块：L2 统一人格与免责口径（P3）。"""
    item = load_registry().get("persona")
    if not isinstance(item, dict) or not item.get("disclaimer"):
        raise PromptContextError("注册表缺少 persona.disclaimer")
    return item


def build_persona_footer() -> str:
    item = persona()
    style = "、".join(item.get("style") or [])
    return f"【统一人格 persona】中文；{style}。免责尾注：{item['disclaimer']}。"


def injection_mode(entry: Dict[str, Any]) -> str:
    return "lite" if entry.get("task") in LITE_TASKS else "full"


def build_constitution_block(mode: str) -> str:
    """full = C-01..C-12；lite = P4 输出契约 + C-11；none/空 = 不注入。"""
    if mode in ("none", "", None):
        return ""
    version, clauses = load_constitution()
    if mode == "lite":
        chosen = {k: v for k, v in clauses.items() if k == "C-11"}
        header = (
            f"【源文件宪法 constitution@{version}｜P4 输出契约 + C-11｜"
            "优先级高于本文其余内容，违规由确定性校验器判定】"
        )
    elif mode == "full":
        chosen = dict(clauses)
        header = (
            f"【源文件宪法 constitution@{version}｜P0 段｜"
            "优先级高于本文其余内容，违规由确定性校验器判定】"
        )
    else:
        raise PromptContextError(f"未知注入模式: {mode!r}")

    lines = [header]
    for cid in sorted(chosen):
        item = chosen[cid]
        lines.append(
            f"- {cid} {item['requirement']}（判据：{item['criterion']}；违例码 {item['code']}）"
        )
    if mode == "full":
        lines.append(
            "- C-04 要求在输出中给出证据等级 evidence ∈ {none, partial, full}，缺省视为 none。"
        )
        lines.append("其余格式要求不变：只输出一个 JSON 对象，不含 markdown 围栏与解释文字。")
    else:
        lines.append(
            "- P4 输出契约：只输出一个 JSON 对象，不含 markdown 围栏与解释文字；"
            "不得编造输入未提供的数据。"
        )
    lines.append(build_persona_footer())
    return "\n".join(lines)


# ── 计量与 meta ────────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """确定性近似：中文为主的文本按 1 token ≈ 1.5 字符折算（仅用于预算记账）。"""
    return max(1, math.ceil(len(text) / 1.5)) if text else 0


def tool_set_fingerprint(tools: Iterable[str] = ()) -> str:
    """与 IF-7 tool_set 同源：空集也有确定指纹（sha256 of 空串）。"""
    names = sorted({str(t).strip() for t in tools if str(t).strip()})
    return "sha256:" + hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


def build_meta(
    prompt_id: str,
    *,
    tools: Iterable[str] = (),
    reasoning_effort: Optional[str] = None,
) -> Dict[str, Any]:
    """生成 L2Envelope.meta 增量字段（7 个：6 字段 + constitution_tokens）。"""
    entry = get_prompt(prompt_id)
    version = str(entry.get("version", ""))
    if not SEMVER_RE.match(version):
        raise PromptContextError(f"{prompt_id}: version 非 semver: {version!r}")

    fingerprint = verify_fingerprint(entry)
    const_version = constitution_version()
    declared_const = str(entry.get("constitution_version", ""))
    if declared_const != const_version:
        raise PromptContextError(
            f"E_CONSTITUTION_DRIFT: {prompt_id} constitution_version={declared_const} "
            f"与宪法 {const_version} 不一致"
        )

    mode = injection_mode(entry)
    block = build_constitution_block(mode)
    return {
        "prompt_id": prompt_id,
        "prompt_version": version,
        "prompt_fingerprint": fingerprint,
        "constitution_version": const_version,
        "constitution_tokens": estimate_tokens(block),
        "tool_set_fingerprint": tool_set_fingerprint(tools),
        "reasoning_effort": reasoning_effort or REASONING_EFFORT.get(mode, "medium"),
    }


def try_build_meta(
    prompt_id: str,
    *,
    tools: Iterable[str] = (),
    reasoning_effort: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """FAIL-OPEN 包装：返回 (meta|None, 宪法注入块)。失败时块为空、meta 为 None。"""
    if not injection_enabled():
        return None, ""
    try:
        entry = get_prompt(prompt_id)
        mode = injection_mode(entry)
        meta = build_meta(prompt_id, tools=tools, reasoning_effort=reasoning_effort)
        return meta, build_constitution_block(mode)
    except Exception as exc:  # noqa: BLE001 — 上下文注入不得阻断业务
        _warn(f"prompt_context disabled ({type(exc).__name__}): {exc}")
        return None, ""


def _warn(message: str) -> None:
    import sys

    print(f"[57/prompt_context] {message}", file=sys.stderr)


# ── 运行时注入 ────────────────────────────────────────────────────────


def inject_system_prompt(
    prompt_id: str,
    base_prompt: str,
    *,
    tools: Iterable[str] = (),
    reasoning_effort: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """把宪法块拼到 system prompt 尾部，返回 (system_prompt, meta|None)。"""
    meta, block = try_build_meta(prompt_id, tools=tools, reasoning_effort=reasoning_effort)
    if not block:
        return base_prompt, meta
    return f"{base_prompt}\n\n{block}", meta


class ConstitutionLLM:
    """LLMClient 装饰器：每次 chat 在 system prompt 尾部注入宪法块。

    覆盖 BaseAgent / JudgeAgent / 交叉质询全部调用点，且不改 prompt 资产。
    """

    def __init__(self, inner: Any, prompt_id: str, tools: Iterable[str] = ()):
        self._inner = inner
        self._prompt_id = prompt_id
        self._tools = tuple(tools)
        self.meta: Optional[Dict[str, Any]] = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
        prompt, meta = inject_system_prompt(self._prompt_id, system_prompt, tools=self._tools)
        if meta is not None:
            self.meta = meta
        return await self._inner.chat(prompt, user_prompt, max_tokens)


def wrap_llm(llm: Any, prompt_id: str, *, tools: Iterable[str] = ()) -> Any:
    """非阻塞包装：注入关闭或已包装时原样返回。"""
    if not injection_enabled() or isinstance(llm, ConstitutionLLM):
        return llm
    return ConstitutionLLM(llm, prompt_id, tools=tools)


def build_frontend_snapshot(prompt_id: str = "l2.app.skill") -> Dict[str, Any]:
    """给 3.1 前端生成的注册表快照（JSON），避免 TS 侧硬编码版本与免责口径。"""
    entry = get_prompt(prompt_id)
    return {
        "generated_by": "57-Agent提示词工程/runtime/emit_prompt_snapshot.py",
        "_notice": "DO NOT EDIT：由 prompt_registry.yaml 生成，改动请改注册表后重跑脚本",
        "schema_version": str(load_registry().get("schema_version", "")),
        "prompt_id": prompt_id,
        "prompt_version": str(entry.get("version", "")),
        "prompt_fingerprint": verify_fingerprint(entry),
        "constitution_version": constitution_version(),
        "persona": persona(),
        # IF-P-3 七字段：前端出口直接消费，避免只带 4 字段导致 --l2-meta 违规
        "meta": build_meta(prompt_id),
    }

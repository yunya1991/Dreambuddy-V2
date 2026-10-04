"""Context Compactor — 上下文自动压缩模块。

对标 Trae 的压缩策略：最近 N 轮保留原文，更早的轮次压缩为摘要。
当 token 用量超过阈值（默认 80%）时触发压缩。

工程约束：HC-1a（独立模块，不修改认知核心）/ FAIL-OPEN
"""
from __future__ import annotations

import json
import re
from typing import Any

# 默认配置
DEFAULT_TOKEN_THRESHOLD_PCT = 0.8  # 触发压缩的 token 用量百分比
DEFAULT_RECENT_TURNS = 8  # 保留原文的最近轮数
DEFAULT_CHARS_PER_TOKEN = 4  # 粗略估算：1 token ≈ 4 字符


def _estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数（1 token ≈ 4 字符）。"""
    if not text:
        return 0
    return len(text) // DEFAULT_CHARS_PER_TOKEN


def _summarize_turn(turn: dict[str, Any]) -> str:
    """将一轮对话压缩为摘要。

    Args:
        turn: {"role": "user"/"assistant", "content": "..."}

    Returns:
        摘要字符串
    """
    role = turn.get("role", "unknown")
    content = turn.get("content", "")
    if not content:
        return f"[{role}] (empty)"
    # 简单摘要：取前 200 字符 + 后 100 字符
    if len(content) <= 300:
        summary = content
    else:
        summary = content[:200] + " ... " + content[-100:]
    # 去除多余空白
    summary = re.sub(r"\s+", " ", summary).strip()
    return f"[{role}] {summary}"


def compact_context(
    messages: list[dict[str, Any]],
    max_tokens: int,
    recent_turns: int = DEFAULT_RECENT_TURNS,
    threshold_pct: float = DEFAULT_TOKEN_THRESHOLD_PCT,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """压缩对话上下文。

    策略：
    1. 估算当前 token 用量
    2. 若超过 threshold_pct * max_tokens，触发压缩
    3. 保留最近 recent_turns 轮原文
    4. 更早的轮次压缩为摘要块

    Args:
        messages: 对话消息列表 [{role, content}, ...]
        max_tokens: 上下文最大 token 数
        recent_turns: 保留原文的最近轮数
        threshold_pct: 触发压缩的阈值百分比
        system_prompt: 系统提示（保留在压缩块中）

    Returns:
        {
            "compacted": bool,          # 是否执行了压缩
            "messages": list,           # 压缩后的消息列表
            "summary_block": str,       # 旧轮次摘要块
            "original_tokens": int,
            "compacted_tokens": int,
            "saved_tokens": int,
        }
    """
    if not messages:
        return {
            "compacted": False,
            "messages": [],
            "summary_block": "",
            "original_tokens": 0,
            "compacted_tokens": 0,
            "saved_tokens": 0,
        }

    # 估算原始 token 数
    total_text = " ".join(m.get("content", "") for m in messages)
    original_tokens = _estimate_tokens(total_text)
    threshold = int(max_tokens * threshold_pct)

    # 未超过阈值，不压缩
    if original_tokens <= threshold:
        return {
            "compacted": False,
            "messages": messages,
            "summary_block": "",
            "original_tokens": original_tokens,
            "compacted_tokens": original_tokens,
            "saved_tokens": 0,
        }

    # 分离最近轮次和旧轮次
    recent = messages[-recent_turns:] if recent_turns > 0 else []
    old = messages[:-recent_turns] if recent_turns > 0 else messages

    if not old:
        return {
            "compacted": False,
            "messages": messages,
            "summary_block": "",
            "original_tokens": original_tokens,
            "compacted_tokens": original_tokens,
            "saved_tokens": 0,
        }

    # 压缩旧轮次为摘要块
    summary_parts = []
    if system_prompt:
        summary_parts.append(f"[系统提示] {system_prompt[:500]}")
    summary_parts.append(f"[历史摘要] 共 {len(old)} 轮对话：")
    for turn in old:
        summary_parts.append(_summarize_turn(turn))
    summary_block = "\n".join(summary_parts)

    # 构建压缩后的消息列表
    compacted_messages = [
        {"role": "system", "content": summary_block},
        *recent,
    ]

    compacted_text = " ".join(m.get("content", "") for m in compacted_messages)
    compacted_tokens = _estimate_tokens(compacted_text)
    saved_tokens = original_tokens - compacted_tokens

    return {
        "compacted": True,
        "messages": compacted_messages,
        "summary_block": summary_block,
        "original_tokens": original_tokens,
        "compacted_tokens": compacted_tokens,
        "saved_tokens": max(0, saved_tokens),
    }


def get_compaction_summary(result: dict[str, Any]) -> str:
    """生成压缩操作的可读摘要（用于记录到 episodic 记忆）。"""
    if not result.get("compacted"):
        return "上下文未压缩（未超过阈值）"
    return (
        f"上下文压缩：{result['original_tokens']} → {result['compacted_tokens']} tokens，"
        f"节省 {result['saved_tokens']} tokens，"
        f"保留最近 {len(result['messages']) - 1} 轮原文"
    )


# ── FR-C2: self 触发模式 ─────────────────────────────────────────

def compact_context_self(
    messages: list[dict[str, Any]],
    max_tokens: int,
    system_prompt: str | None = None,
    recent_turns: int = DEFAULT_RECENT_TURNS,
) -> dict[str, Any]:
    """Agent 主动触发压缩（self 模式），强制执行不检查阈值。

    与 compact_context 的区别：跳过阈值检测，直接执行压缩。
    适用于 agent 判断上下文过大需主动压缩的场景。

    Args:
        messages: 对话消息列表
        max_tokens: 上下文最大 token 数
        system_prompt: 系统提示
        recent_turns: 保留原文的最近轮数

    Returns:
        compact_context() 的返回格式
    """
    return compact_context(
        messages=messages,
        max_tokens=max_tokens,
        recent_turns=recent_turns,
        threshold_pct=0.0,  # 阈值设为 0，强制触发
        system_prompt=system_prompt,
    )


# ── FR-C3: 重试更激进压缩 ───────────────────────────────────────

def compact_with_retry(
    messages: list[dict[str, Any]],
    max_tokens: int,
    system_prompt: str | None = None,
    recent_turns: int = DEFAULT_RECENT_TURNS,
    threshold_pct: float = DEFAULT_TOKEN_THRESHOLD_PCT,
    max_retries: int = 2,
) -> dict[str, Any]:
    """压缩上下文，若 token 数未下降则重试更激进的压缩。

    每次重试减少 recent_turns（保留更少原文）以更激进地压缩。

    Args:
        messages: 对话消息列表
        max_tokens: 上下文最大 token 数
        system_prompt: 系统提示
        recent_turns: 初始保留轮数
        threshold_pct: 触发阈值
        max_retries: 最大重试次数

    Returns:
        最终压缩结果（含 retry_count 字段）
    """
    result = compact_context(
        messages, max_tokens, recent_turns, threshold_pct, system_prompt
    )

    retries = 0
    while retries < max_retries and result.get("compacted"):
        # 如果压缩后 token 仍超过 max_tokens 的 80%，重试
        if result["compacted_tokens"] <= int(max_tokens * threshold_pct):
            break
        # 更激进：减少保留轮数
        new_recent = max(2, recent_turns - 2 * (retries + 1))
        if new_recent >= recent_turns:
            break  # 无法再减少
        recent_turns = new_recent
        retries += 1
        result = compact_context(
            messages, max_tokens, recent_turns, threshold_pct, system_prompt
        )

    result["retry_count"] = retries
    return result

"""shadow_hook.py — 壳信封旁路观察接线（COMM-SHADOW 生产接线）

背景：AgentMailShadow.observe() 此前只在测试中被调用，壳进程从未接线，
导致 trajectory store 里没有真实信封（只有合成数据）。

接线方式：壳 handler 产出信封文本后调用 observe_envelope(text)，旁路落本地 JSONL。

开关（默认关闭，零行为变化）：
  - AGENT_MAIL_SHADOW=1           开启观察
  - AGENT_MAIL_SHADOW_STORE=path  覆盖落盘路径（默认 .workbuddy/agent_mail/trajectories.jsonl）
  - AGENT_MAIL_SHADOW_HEAD=1      开启 Phase B Head 推理（默认关：壳只采轨迹，不加载 torch）

硬约束（COMM-SHADOW §5.2）：
  - S1 不触发域 agent：只写本地 JSONL
  - S2 shadow- trace 前缀由 AgentMailShadow 保证
  - S3 零资源占用：默认不 import torch（head_infer=False），无 DB / 无网络 / 无子进程
  - FAIL-OPEN：任何异常吞掉，绝不影响壳主链路
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_shadow: Optional[Any] = None


def enabled() -> bool:
    return os.environ.get("AGENT_MAIL_SHADOW", "0") == "1"


def _get_shadow() -> Any:
    global _shadow
    if _shadow is None:
        from mcp_shells._shared.agent_mail_shadow import AgentMailShadow

        _shadow = AgentMailShadow(
            trajectory_store_path=os.environ.get("AGENT_MAIL_SHADOW_STORE") or None,
            head_infer=os.environ.get("AGENT_MAIL_SHADOW_HEAD", "0") == "1",
        )
    return _shadow


def observe_envelope(envelope: Any) -> None:
    """旁路观察单个信封（dict 或 JSON 文本）。FAIL-OPEN，永不抛错。"""
    if not enabled():
        return
    try:
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        if not isinstance(envelope, dict):
            return
        _get_shadow().observe(envelope)
    except Exception:  # noqa: BLE001 — FAIL-OPEN 契约
        return


__all__ = ["enabled", "observe_envelope"]

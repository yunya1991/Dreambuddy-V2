"""shadow_hook.py — 壳信封旁路观察接线（COMM-SHADOW 生产接线）

背景：AgentMailShadow.observe() 此前只在测试中被调用，壳进程从未接线，
导致 trajectory store 里没有真实信封（只有合成数据）。

接线方式：壳 handler 产出信封文本后调用 observe_envelope(text, latency_ms=..., action=...)，
旁路落本地 JSONL。信封 meta 缺失的真实字段（latency_ms / event_type / poe_score）
由本层按实测值补齐，避免轨迹退化为扁平常量（SPEC Z6/Z7 反模式）。

开关（默认关闭，零行为变化）：
  - AGENT_MAIL_SHADOW=1           显式开启（优先级最高）
  - AGENT_MAIL_SHADOW=0           显式关闭（覆盖 flag 文件）
  - <repo>/.workbuddy/agent_mail/ENABLED  运维开关（存在即开启，无需改 env）
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
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
FLAG_PATH = _REPO_ROOT / ".workbuddy" / "agent_mail" / "ENABLED"
S1_FLAG = _REPO_ROOT / ".workbuddy" / "agent_mail" / "S1_ENABLED"

_shadow: Optional[Any] = None


def flag_enabled() -> bool:
    """运维开关文件是否存在（存在即开启）。异常一律视为关闭（FAIL-CLOSED 到默认值）。"""
    try:
        return FLAG_PATH.exists()
    except Exception:  # noqa: BLE001 — 权限/路径异常不影响主链路
        return False


def enabled() -> bool:
    """开关优先级：显式 env > flag 文件 > 默认关。"""
    env = os.environ.get("AGENT_MAIL_SHADOW")
    if env is not None:
        return env.strip() == "1"
    return flag_enabled()


def _s1_enabled() -> bool:
    """S1 开关：env AGENT_MAIL_S1 优先，其次门禁写入的 S1_ENABLED flag。"""
    env = os.environ.get("AGENT_MAIL_S1")
    if env is not None:
        return env.strip() == "1"
    try:
        return S1_FLAG.exists()
    except Exception:  # noqa: BLE001
        return False


def _get_shadow() -> Any:
    global _shadow
    if _shadow is None:
        from mcp_shells._shared.agent_mail_shadow import AgentMailShadow

        _shadow = AgentMailShadow(
            trajectory_store_path=os.environ.get("AGENT_MAIL_SHADOW_STORE") or None,
            head_infer=os.environ.get("AGENT_MAIL_SHADOW_HEAD", "0") == "1",
            signature_enabled=_s1_enabled(),
        )
    return _shadow


def _enrich_meta(
    envelope: dict,
    latency_ms: Optional[float],
    action: str,
    cross_domain_refs: Optional[int],
) -> dict:
    """用壳侧实测值补齐信封 meta，不覆盖信封自带的真实值（零删零改）。"""
    raw_meta = envelope.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    if action and not (meta.get("event_type") or meta.get("action")):
        meta["event_type"] = action
    if latency_ms is not None and "latency_ms" not in meta:
        try:
            meta["latency_ms"] = round(float(latency_ms), 3)
        except (TypeError, ValueError):
            pass
    if cross_domain_refs is not None and "cross_domain_refs" not in meta:
        try:
            meta["cross_domain_refs"] = int(cross_domain_refs)
        except (TypeError, ValueError):
            pass
    # poe 质量分：真实信封以 degraded 为唯一依据（1.0 成功 / 0.0 降级），
    # 连续信号由实测 latency_ms 承载，不再造人造常量。
    if "poe_score" not in meta:
        meta["poe_score"] = 0.0 if bool(envelope.get("degraded", False)) else 1.0
    if "messages_sent" not in meta:
        meta["messages_sent"] = 1
    return meta


def observe_envelope(
    envelope: Any,
    *,
    latency_ms: Optional[float] = None,
    action: str = "",
    cross_domain_refs: Optional[int] = None,
) -> None:
    """旁路观察单个信封（dict 或 JSON 文本）。FAIL-OPEN，永不抛错。

    latency_ms / action / cross_domain_refs 为壳侧实测补充；信封 meta 已有值时以信封为准。
    """
    if not enabled():
        return
    try:
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        if not isinstance(envelope, dict):
            return
        envelope = {
            **envelope,
            "meta": _enrich_meta(envelope, latency_ms, action, cross_domain_refs),
        }
        _get_shadow().observe(envelope)
    except Exception:  # noqa: BLE001 — FAIL-OPEN 契约
        return


__all__ = ["enabled", "flag_enabled", "observe_envelope", "FLAG_PATH"]

"""策略工厂审计辅助。

27-策略治理审批系统 - 从 10-经典指标系统 audit.py 迁移。
统一审计记录格式：trace_id/stage/action/actor/ts/result。
增强能力：
1. 结构化审计事件（覆盖策略生产全链路各阶段）
2. 哈希链完整性校验（prev_hash 串联，防篡改）
3. 审计事件查询与过滤
4. 阶段流转审计（lifecycle transition）
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from governance.utils import _audit_emit_action, _audit_base_payload, _now_ms


# 27 模块审计数据目录
_AUDIT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "audit"
_AUDIT_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 审计事件分类
# ---------------------------------------------------------------------------

AUDIT_STAGES: Set[str] = {
    "draft",          # 变更包草稿
    "gate",           # 评估门控
    "approval",       # 审批
    "apply",          # 变更应用
    "pipeline",       # 流水线执行
    "registry",       # 策略库操作
    "execution",      # 执行信号
}

AUDIT_ACTIONS: Set[str] = {
    "create", "update", "delete", "query",
    "approve", "reject", "request",
    "pass", "fail", "warn",
    "deploy", "rollback", "sync",
    "entry", "exit",
}


# ---------------------------------------------------------------------------
# 哈希链完整性
# ---------------------------------------------------------------------------

def _audit_hash_chain_path() -> Path:
    """27 模块审计哈希链路径（独立于 10-经典指标系统）"""
    return _AUDIT_DATA_DIR / "audit_hash_chain.jsonl"


def _last_audit_hash() -> Optional[str]:
    p = _audit_hash_chain_path()
    if not p.exists() or not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for ln in reversed(lines):
            try:
                obj = json.loads(ln)
                h = obj.get("hash")
                if isinstance(h, str) and h:
                    return h
            except Exception:
                continue
    except Exception:
        pass
    return None


def _compute_audit_hash(event: Dict[str, Any], prev_hash: Optional[str]) -> str:
    """计算审计事件哈希（SHA-256）。"""
    payload = {
        "ts": event.get("ts"),
        "trace_id": event.get("trace_id"),
        "stage": event.get("stage"),
        "action": event.get("action"),
        "actor": event.get("actor"),
        "prev_hash": prev_hash or "",
    }
    b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# 核心审计函数
# ---------------------------------------------------------------------------

def strategy_factory_audit(
    *,
    trace_id: str,
    stage: str,
    action: str,
    actor: str = "strategy_factory",
    result: Optional[Dict[str, Any]] = None,
    strategy_id: Optional[str] = None,
    source_zip: Optional[str] = None,
) -> Dict[str, Any]:
    """记录策略工厂审计事件。

    Args:
        trace_id: 追踪 ID
        stage: 阶段（draft/gate/approval/apply/pipeline/registry/execution）
        action: 动作（create/update/delete/approve/reject/pass/fail/deploy 等）
        actor: 执行者
        result: 结果数据
        strategy_id: 策略 ID（可选）
        source_zip: 策略源码包（可选）

    Returns:
        审计事件记录（含 hash 用于完整性校验）
    """
    now_ms = int(_now_ms())
    prev_hash = _last_audit_hash()

    event: Dict[str, Any] = {
        "ts": now_ms,
        "trace_id": str(trace_id or "").strip(),
        "stage": str(stage or "").strip().lower(),
        "action": str(action or "").strip().lower(),
        "actor": str(actor or "strategy_factory").strip(),
        "result": result if isinstance(result, dict) else {},
    }
    if strategy_id:
        event["strategy_id"] = str(strategy_id).strip()
    if source_zip:
        event["source_zip"] = str(source_zip).strip()

    event_hash = _compute_audit_hash(event, prev_hash)
    event["hash"] = event_hash
    event["prev_hash"] = prev_hash

    extra: Dict[str, Any] = {
        "stage": event["stage"],
        "action": event["action"],
        "actor": event["actor"],
        "hash": event_hash,
    }
    if isinstance(result, dict):
        extra["result"] = result
    if strategy_id:
        extra["strategy_id"] = str(strategy_id).strip()
    if source_zip:
        extra["source_zip"] = str(source_zip).strip()

    try:
        _audit_emit_action(
            f"strategy_factory.{event['stage']}",
            _audit_base_payload(scope="strategy_factory", action=event["action"], trace_id=event["trace_id"], extra=extra),
        )
    except Exception:
        pass

    # 写入哈希链
    try:
        p = _audit_hash_chain_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass

    return event


def audit_lifecycle_transition(
    *,
    trace_id: str,
    strategy_id: str,
    source_zip: str,
    from_state: str,
    to_state: str,
    actor: str = "strategy_factory",
    approved: bool = True,
) -> Dict[str, Any]:
    """审计策略生命周期状态流转。"""
    return strategy_factory_audit(
        trace_id=trace_id,
        stage="registry",
        action="deploy" if approved else "reject",
        actor=actor,
        result={
            "from_state": str(from_state),
            "to_state": str(to_state),
            "approved": bool(approved),
        },
        strategy_id=strategy_id,
        source_zip=source_zip,
    )


def audit_gate_result(
    *,
    trace_id: str,
    strategy_id: str,
    source_zip: str,
    gate_name: str,
    passed: bool,
    metrics: Optional[Dict[str, Any]] = None,
    actor: str = "gate",
) -> Dict[str, Any]:
    """审计评估门控结果。"""
    return strategy_factory_audit(
        trace_id=trace_id,
        stage="gate",
        action="pass" if passed else "fail",
        actor=actor,
        result={
            "gate": str(gate_name),
            "passed": bool(passed),
            "metrics": metrics if isinstance(metrics, dict) else {},
        },
        strategy_id=strategy_id,
        source_zip=source_zip,
    )


def audit_execution_signal(
    *,
    trace_id: str,
    strategy_id: str,
    side: str,
    coin: str,
    notional: Optional[float] = None,
    executed: bool = False,
    actor: str = "freqtrade",
) -> Dict[str, Any]:
    """审计执行信号。"""
    return strategy_factory_audit(
        trace_id=trace_id,
        stage="execution",
        action="entry" if str(side).lower() in ("long", "short") else "exit",
        actor=actor,
        result={
            "side": str(side).lower(),
            "coin": str(coin).upper(),
            "notional": float(notional) if notional is not None else None,
            "executed": bool(executed),
        },
        strategy_id=strategy_id,
    )


# ---------------------------------------------------------------------------
# 审计查询
# ---------------------------------------------------------------------------

def audit_query(
    *,
    trace_id: Optional[str] = None,
    stage: Optional[str] = None,
    action: Optional[str] = None,
    strategy_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """查询审计哈希链事件。"""
    p = _audit_hash_chain_path()
    if not p.exists() or not p.is_file():
        return []
    try:
        limit_n = max(1, min(1000, int(limit)))
    except Exception:
        limit_n = 100

    trace_s = str(trace_id or "").strip() if trace_id else None
    stage_s = str(stage or "").strip().lower() if stage else None
    action_s = str(action or "").strip().lower() if action else None
    sid_s = str(strategy_id or "").strip() if strategy_id else None

    out: List[Dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for ln in reversed(lines):
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if trace_s and str(obj.get("trace_id") or "").strip() != trace_s:
                continue
            if stage_s and str(obj.get("stage") or "").strip().lower() != stage_s:
                continue
            if action_s and str(obj.get("action") or "").strip().lower() != action_s:
                continue
            if sid_s and str(obj.get("strategy_id") or "").strip() != sid_s:
                continue
            out.append(obj)
            if len(out) >= limit_n:
                break
    except Exception:
        pass
    out.reverse()
    return out


def audit_verify_chain() -> Dict[str, Any]:
    """验证审计哈希链完整性。"""
    p = _audit_hash_chain_path()
    if not p.exists() or not p.is_file():
        return {"ok": True, "total": 0, "verified": 0, "broken": 0, "message": "no_audit_chain"}

    total = 0
    verified = 0
    broken = 0
    prev_hash: Optional[str] = None
    first_prev: Optional[str] = None

    try:
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                total += 1
                stored_prev = obj.get("prev_hash")
                if total == 1:
                    first_prev = stored_prev
                if prev_hash is not None and stored_prev != prev_hash:
                    broken += 1
                    continue
                # 验证哈希
                expected = _compute_audit_hash(obj, stored_prev)
                if obj.get("hash") == expected:
                    verified += 1
                else:
                    broken += 1
                prev_hash = obj.get("hash")
    except Exception:
        pass

    return {
        "ok": broken == 0,
        "total": total,
        "verified": verified,
        "broken": broken,
        "message": "chain_intact" if broken == 0 else "chain_broken",
    }


__all__ = [
    "strategy_factory_audit",
    "audit_lifecycle_transition",
    "audit_gate_result",
    "audit_execution_signal",
    "audit_query",
    "audit_verify_chain",
    "AUDIT_STAGES",
    "AUDIT_ACTIONS",
]

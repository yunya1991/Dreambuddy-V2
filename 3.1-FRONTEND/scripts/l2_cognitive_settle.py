# -*- coding: utf-8 -*-
"""P3b.1: L2 SSE 链路认知 record_hook 接线脚本。

由 /api/task/stream 在任务完成后 fire-and-forget 调用（execFile）。
输入: JSON {task_id, intent, message, answer_preview, quality_score, l1_intent_hint?}
输出: JSON {success, memory_id?, quality_level?, degraded?, reason?}

通道: 复用 L0 认知入口（core.l0_foundation.L0Foundation._load_cle →
      cognitive_loop_entry.get_cle），与 L0 cognitive.recall scope 同构。
质量映射: quality_score >= 0.8 → B（可信执行案例），否则 → C（假设级）。
FAIL-OPEN: 认知不可用/参数非法均不抛出，degraded 返回；绝不阻塞 SSE 主链路。
"""
import json
import os
import sys

_TRAINING_SYS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "34-前端应用训练系统",
)
if _TRAINING_SYS_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_SYS_DIR)

from core.l0_foundation import get_l0

QUALITY_B_MIN = 0.8  # quality_score ≥ 0.8 → B 级记忆，否则 C 级


def settle_l2(task_id, intent, message, answer_preview,
              quality_score=0.7, l1_intent_hint=""):
    """L2 执行结果沉淀为认知记忆，返回 {success, memory_id, ...}（FAIL-OPEN）。"""
    quality_score = float(quality_score or 0.0)
    quality = "B" if quality_score >= QUALITY_B_MIN else "C"
    hint_part = f"[l1_hint={l1_intent_hint}]" if l1_intent_hint else ""
    content = (
        f"[L2执行案例][{intent}]{hint_part} 用户: {(message or '')[:120]} | "
        f"结果摘要: {(answer_preview or '')[:200]} | "
        f"quality={quality_score:.2f} | task={task_id}"
    )
    tags = f"L2执行案例,{intent or 'unknown'},P3b-record-hook"
    try:
        cle = get_l0()._load_cle()
        resp = cle.record(content=content, quality_level=quality, tags=tags)
    except Exception as e:
        return {"success": False, "degraded": True,
                "reason": f"cognitive_unavailable: {e}"}
    if isinstance(resp, dict):
        memory_id = resp.get("memory_id")
    elif isinstance(resp, str) and resp.strip():
        memory_id = resp.strip()  # cognitive_loop_entry.record 直接返回 memory_id 字符串
    else:
        memory_id = getattr(resp, "memory_id", None)
    if not memory_id:
        return {"success": False, "degraded": True,
                "reason": "record_no_memory_id", "raw": str(resp)[:200]}
    return {"success": True, "memory_id": memory_id, "quality_level": quality}


def main():
    try:
        req = json.loads(sys.argv[1]) if len(sys.argv) > 1 \
            else json.loads(sys.stdin.read() or "{}")
    except Exception:
        req = {}
    try:
        out = settle_l2(
            task_id=req.get("task_id", ""),
            intent=req.get("intent", "unknown"),
            message=req.get("message", ""),
            answer_preview=req.get("answer_preview", ""),
            quality_score=req.get("quality_score") or 0.0,
            l1_intent_hint=req.get("l1_intent_hint", "") or "",
        )
    except Exception as e:
        out = {"success": False, "degraded": True, "reason": str(e)}
    # JSON 保证在最后一行（认知系统可能向 stdout 打警告行）
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

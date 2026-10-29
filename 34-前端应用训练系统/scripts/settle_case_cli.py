#!/usr/bin/env python3
"""settle_case_cli.py — 主聊天链路案例沉淀桥接
=====================================================
供 3.1-FRONTEND /api/task spawn 调用（stdin JSON → stdout JSON）：
    echo '{"intent": "market_query", "message": "...", "success": true, "answer": "..."}' \
      | venv-trading/bin/python scripts/settle_case_cli.py

复用 l0_foundation.settle 分流（案例库 jsonl + 认知价值 record），
FAIL-OPEN：任何异常输出 {"success": false}，不阻塞调用方。
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
for _p in (_THIS_DIR, _34_DIR, os.path.join(_34_DIR, "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "invalid json"}))
        return 1
    intent = str(req.get("intent") or "").strip()
    message = str(req.get("message") or "").strip()
    if not intent or not message:
        print(json.dumps({"success": False, "error": "missing intent/message"}))
        return 1
    # 组装 settle 兼容的 result 信封（成功且非降级才写案例库）
    result = {
        "success": bool(req.get("success", True)),
        "degraded": bool(req.get("degraded", False)),
        "answer": str(req.get("answer") or "")[:300],
        "data": req.get("data"),
    }
    try:
        from l0_foundation import get_l0
        context = {"intent": intent, "message": message}
        # P1.5 扩展字段（spec §9.1）：complexity/entities 透传（可选）
        for _k in ("complexity", "entities"):
            if req.get(_k) is not None:
                context[_k] = req.get(_k)
        get_l0().settle(result, context)
        print(json.dumps({"success": True, "settled": True}, ensure_ascii=False))
        return 0
    except Exception as e:  # FAIL-OPEN
        print(json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

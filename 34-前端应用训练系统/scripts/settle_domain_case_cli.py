#!/usr/bin/env python3
"""settle_domain_case_cli.py — 各域案例沉淀桥接（P1.5，spec v0.5 §9.1）
======================================================================
供 3.1-FRONTEND 各域采集点 spawn 调用（stdin JSON → stdout JSON）：
    echo '{"case_type": "sacg_orchestration", "payload": {...}}' \
      | venv-trading/bin/python scripts/settle_domain_case_cli.py

支持的 case_type（spec §9.1 六域中除意图系统外的五域）：
  - sacg_orchestration：SACG 编排（orchestration_plan/子任务分派/各子任务结果）
  - dsh_dispatch：DSH 调度（source/case_type/质量门控结果）
  - sub_agent：子 agent 执行（agent_id/任务/执行结果/耗时）
  - finance_semantic：三层金融语义消费（语义层级/查询词/返回摘要）
  - arch_layer：三层架构任务（layer/node_id/验收结果）

写入 l1_case_store.jsonl（schema_version v2，case_type 标识域），
FAIL-OPEN：任何异常输出 {"success": false}，不阻塞调用方。
"""
import json
import os
import sys
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_CASE_STORE = os.path.join(_34_DIR, "l1_case_store.jsonl")

VALID_TYPES = {
    "sacg_orchestration", "dsh_dispatch", "sub_agent",
    "finance_semantic", "arch_layer",
}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "invalid json"}))
        return 1
    case_type = str(req.get("case_type") or "").strip()
    payload = req.get("payload")
    if case_type not in VALID_TYPES:
        print(json.dumps({"success": False, "error": f"invalid case_type: {case_type}"}))
        return 1
    if not isinstance(payload, dict) or not payload:
        print(json.dumps({"success": False, "error": "missing payload"}))
        return 1
    case = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "schema_version": "v2",
        "case_type": case_type,
        "payload": payload,
    }
    try:
        os.makedirs(os.path.dirname(_CASE_STORE), exist_ok=True)
        with open(_CASE_STORE, "a", encoding="utf-8") as f:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
        print(json.dumps({"success": True, "settled": True, "case_type": case_type}, ensure_ascii=False))
        return 0
    except Exception as e:  # FAIL-OPEN
        print(json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

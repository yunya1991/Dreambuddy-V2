#!/usr/bin/env python3
"""capability_resolve_server.py — 常驻装配器（SPEC-54 R6 性能）。

一次性 CLI（`capability_resolve.py`）每次请求都要付 ~11s 的 Python import 成本，
导致 13 张卡片并发时全部撞上 25s 超时。本脚本把 import 摊到进程启动一次，
之后每行请求只做取数 + 计算（实测 ~0.05s/次，且进程内面板缓存生效）。

协议（stdin/stdout，每行一个 JSON）：
  请求：{"id": "<任意字符串>", "capability": "D-A11", "payload": {...}}
  响应：{"id": "<同上>", ...resolve 结果...}

FAIL-OPEN：任何异常都以 `code=error` 回一行，不退出循环；stdin 关闭即退出。
"""

import json
import os
import sys
import traceback
from typing import Any, Dict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
for _p in (_SCRIPT_DIR, _L1_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_resolve as cr  # noqa: E402


def _handle(request: Dict[str, Any]) -> Dict[str, Any]:
    capability_id = str(request.get("capability") or "")
    payload = request.get("payload")
    if payload is not None and not isinstance(payload, dict):
        return {
            "ok": False,
            "code": "invalid_params",
            "capability_id": capability_id,
            "reason": "payload 必须是对象",
        }
    return cr.resolve(capability_id, payload or {})


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be object")
            req_id = request.get("id")
            result = _handle(request)
        except Exception as exc:  # noqa: BLE001 — 单条失败不影响后续请求
            traceback.print_exc(file=sys.stderr)
            result = {
                "ok": False,
                "code": "error",
                "capability_id": "",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        if req_id is not None:
            result["id"] = req_id
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

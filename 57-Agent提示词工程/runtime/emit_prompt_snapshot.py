#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emit_prompt_snapshot.py — 从注册表生成 3.1 前端 prompt 快照（SPEC-57 §8 P3）

用法：
  python3 57-Agent提示词工程/runtime/emit_prompt_snapshot.py

产物：3.1-FRONTEND/src/lib/orchestration/prompt-registry.generated.json
约束：
  - 产物是注册表的派生物，**禁止手改**；改版本/免责口径请改 prompt_registry.yaml 后重跑；
  - 前端只消费该快照，不再硬编码 prompt 版本与免责尾注。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import prompt_context_57 as pc  # noqa: E402

TARGET = (
    pc.REPO_ROOT
    / "3.1-FRONTEND"
    / "src"
    / "lib"
    / "orchestration"
    / "prompt-registry.generated.json"
)


def main() -> int:
    snapshot = pc.build_frontend_snapshot("l2.app.skill")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

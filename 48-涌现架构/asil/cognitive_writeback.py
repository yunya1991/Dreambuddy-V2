# ruff: noqa: E402
"""ASIL → 广义认知库 的真实写入适配器（P0-1）。

闭环断点修复：此前 Step⑦ 只做计数器累加，verdict 不会进入认知库。
现在 verdict 会：
1. record() 写入经验（带 idempotency_key，重跑不重复）
2. verify() 触发贝叶斯置信度更新 / 蒸馏（candidate 记成功，其余记失败）

不可用时 FAIL-OPEN 降级为本地镜像，并计入 fallbacks，绝不阻塞管道。
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COGNITIVE_LIB = _REPO_ROOT / "4-MEMORY" / "9-工具与接口"
_ASIL_EVENTS = Path(__file__).resolve().parent.parent / "events" / "asil"


class CognitiveWriteback:
    """认知库写入/验证适配器（懒加载，进程内复用 CLE 实例）。"""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        enabled: bool = True,
        enable_distill: bool = True,
        memory_lib: Optional[Path] = None,
        mirror_path: Optional[Path] = None,
    ):
        self.storage_path = (
            str(storage_path) if storage_path else os.environ.get("ASIL_WRITEBACK_STORAGE") or None
        )
        self.enabled = enabled and os.environ.get("ASIL_WRITEBACK_ENABLED", "1") != "0"
        self.enable_distill = (
            enable_distill and os.environ.get("ASIL_WRITEBACK_DISTILL", "1") != "0"
        )
        self.memory_lib = Path(memory_lib) if memory_lib else _COGNITIVE_LIB
        self.mirror_path = (
            Path(mirror_path) if mirror_path else (_ASIL_EVENTS / "writeback_fallback.jsonl")
        )
        self.records = 0
        self.verifies = 0
        self.failures = 0
        self._cle: Optional[Any] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _cle_instance(self) -> Any:
        if self._cle is None:
            if str(self.memory_lib) not in sys.path:
                sys.path.insert(0, str(self.memory_lib))
            from cognitive_loop_entry import CognitiveLoopEntry

            self._cle = CognitiveLoopEntry(
                storage_path=self.storage_path,
                enable_distill=self.enable_distill,
                poe_enforcement="off",
            )
        return self._cle

    def _mirror(self, payload: Dict[str, Any]) -> None:
        try:
            self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.mirror_path, "a") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 镜像失败也不阻塞

    @staticmethod
    def _build_content(verdict: Dict[str, Any], pipeline_id: str) -> str:
        violations = verdict.get("violations") or []
        return (
            f"[ASIL][自改进闭环] pipeline={pipeline_id} "
            f"verdict={verdict.get('verdict')} "
            f"oracle_confidence={verdict.get('oracle_confidence')} "
            f"test_coverage={verdict.get('test_coverage')} "
            f"violations={len(violations)}"
            + (
                f" 首项违规={violations[0].get('rule')}"
                if violations and isinstance(violations[0], dict)
                else ""
            )
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def record_verdict(
        self,
        verdict: Dict[str, Any],
        pipeline_id: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"backend": "disabled", "memory_id": None, "fallback": False}

        label = verdict.get("verdict")
        quality = "B" if label == "candidate" else "C"
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "record",
            "pipeline_id": pipeline_id,
            "verdict": label,
        }
        try:
            with self._lock:
                cle = self._cle_instance()
                memory_id = cle.record(
                    content=self._build_content(verdict, pipeline_id),
                    quality_level=quality,
                    confidence=0.5 if quality == "B" else 0.3,
                    tags=["ASIL", "48涌现架构", "自改进闭环", f"verdict:{label}"]
                    + list(tags or []),
                    source="asil",
                    memory_type="experience",
                    idempotency_key=f"asil-{pipeline_id}",
                )
                self.records += 1
            return {"backend": "cognitive_db", "memory_id": memory_id, "fallback": False}
        except Exception as exc:  # FAIL-OPEN
            with self._lock:
                self.failures += 1
            payload.update({"error": str(exc)})
            self._mirror(payload)
            return {
                "backend": "local_mirror",
                "memory_id": None,
                "fallback": True,
                "error": str(exc),
            }

    def verify_memory(
        self,
        memory_id: str,
        success: bool = True,
        known_gaps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled or not memory_id:
            return {"backend": "skipped", "success": success, "fallback": False}
        try:
            with self._lock:
                cle = self._cle_instance()
                result = cle.verify(
                    memory_id=memory_id,
                    success=success,
                    known_gaps_update=known_gaps,
                )
                self.verifies += 1
            return {"backend": "cognitive_db", "success": success, "result": result}
        except Exception as exc:  # FAIL-OPEN
            with self._lock:
                self.failures += 1
            self._mirror(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "kind": "verify",
                    "memory_id": memory_id,
                    "success": success,
                    "error": str(exc),
                }
            )
            return {
                "backend": "local_mirror",
                "success": success,
                "fallback": True,
                "error": str(exc),
            }

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """检索验证用：确认写入的记忆可被 recall 找回。"""
        cle = self._cle_instance()
        return cle.recall(query, top_k=top_k)

    def stats(self) -> Dict[str, Any]:
        return {
            "records": self.records,
            "verifies": self.verifies,
            "failures": self.failures,
            "backend": "cognitive_db" if self.records else "none",
        }

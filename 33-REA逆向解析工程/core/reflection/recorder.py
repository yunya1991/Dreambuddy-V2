# -*- coding: utf-8 -*-
"""分析任务记录器 — SPEC-33-反思层 v0.3 P1

分析任务（s33_rea_analyze/trace/investigate 等）执行时自动记录发现树至回放池。
设计原则：
  - 独立模块，不改动现有分析器代码（对齐 Dream-RSI『base agent 不变』）
  - FAIL-OPEN：记录失败不影响分析任务本身（异常吞掉并记日志）
  - 会话式记录：一个分析任务 = 一棵发现树，begin → record* → commit

用法：
    from core.reflection.recorder import AnalysisRecorder

    rec = AnalysisRecorder(pool_dir)
    rec.begin({"target": "/path", "task_type": "analyze"})
    rec.record("python_analyzer", params={"scope": "architecture"},
               poe_score=0.8, cost_calls=3, evidence_refs=[...])
    rec.commit()

关联：SPEC-33-反思层.md v0.3 §4.1；core/reflection/replay_simulator.py
"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.reflection.replay_simulator import (  # noqa: E402
    DiscoveryNode,
    DiscoveryTree,
    ReplayPool,
)

# 默认回放池目录
DEFAULT_POOL_DIR = os.path.join(_PROJECT_ROOT, "reflection_data", "replay_pool")


class AnalysisRecorder:
    """分析任务记录器：会话式记录发现树。

    FAIL-OPEN：所有记录操作异常均吞掉（打印 stderr），
    绝不影响分析任务本身的执行。
    """

    def __init__(self, pool_dir: str = DEFAULT_POOL_DIR):
        self._pool: Optional[ReplayPool] = None
        self._tree: Optional[DiscoveryTree] = None
        self._cursor: Optional[DiscoveryNode] = None
        try:
            self._pool = ReplayPool(pool_dir)
        except Exception:
            traceback.print_exc()

    # ---------- 会话生命周期 ----------

    def begin(self, task: Dict[str, Any]) -> bool:
        """开始记录一个分析任务：创建新发现树（含根节点）。"""
        if self._pool is None:
            return False
        try:
            self._tree = DiscoveryTree.new_tree(task=task, provenance="internal")
            self._cursor = self._tree.root
            return True
        except Exception:
            traceback.print_exc()
            self._tree = None
            self._cursor = None
            return False

    def record(
        self,
        analyzer: str,
        params: Optional[Dict[str, Any]] = None,
        poe_score: float = 0.0,
        cost_calls: int = 1,
        cost_tokens: int = 0,
        evidence_refs: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """记录一次分析器调用：追加节点到当前游标（单链路径）。"""
        if self._tree is None or self._cursor is None:
            return False
        try:
            import uuid

            node = DiscoveryNode(
                node_id=f"dn_{uuid.uuid4().hex[:16]}",
                parent_id=self._cursor.node_id,
                action={"analyzer": analyzer, "params": params or {}},
                evidence_refs=evidence_refs or [],
                poe_score=max(0.0, min(1.0, poe_score)),
                cost_calls=max(1, cost_calls),
                cost_tokens=max(0, cost_tokens),
            )
            self._tree.add_node(node)
            self._cursor = node
            return True
        except Exception:
            traceback.print_exc()
            return False

    def commit(self) -> Optional[str]:
        """提交发现树至回放池，返回 tree_id；无有效内容时返回 None。"""
        if self._pool is None or self._tree is None:
            return None
        try:
            # 仅根节点（无分析步骤）不落盘
            if len(self._tree.nodes) <= 1:
                return None
            self._pool.save(self._tree)
            return self._tree.tree_id
        except Exception:
            traceback.print_exc()
            return None
        finally:
            self._tree = None
            self._cursor = None

    # ---------- 状态查询 ----------

    @property
    def active(self) -> bool:
        return self._tree is not None and self._cursor is not None

    def pool_stats(self) -> Dict[str, Any]:
        """回放池统计（监控用）。"""
        if self._pool is None:
            return {"available": False}
        return {
            "available": True,
            "internal_count": self._pool.count("internal"),
            "external_count": self._pool.count("external"),
            "eval_ready": self._pool.eval_ready(),
        }

"""认知会话采集器 — DSH 层 P1 数据源.

扫描 .cognitive/sessions/ 会话目录,从 session.json 和 action_chain.jsonl
重构 recall→action→outcome 调用链,构造 DSH 层训练数据。

设计 (SPEC-DSH-训练数据源 v0.4 §3):
  - 扫描 CS-* 会话目录
  - session.json → recalled_memory_ids / recalled_processes / task_type / status
  - action_chain.jsonl → file_change / git_commit / task_type_evolved 等动作
  - 组装 node_sequence: session_start → recall → actions → session_end
  - FAIL-OPEN: session.json 损坏跳过,目录不存在返回空

预期: 558 个会话 → 40-80 条 (过滤无 recall 的会话)
"""
import json
import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# 默认会话目录
_DEFAULT_SESSIONS_DIR = os.path.join(_PROJECT_ROOT, ".cognitive", "sessions")


class CognitiveSessionCollector(TrainingDataProvider):
    """认知会话采集器 — DSH 层 P1 数据源。

    扫描 .cognitive/sessions/ 会话目录,重构认知调用链。
    """

    def __init__(self, sessions_dir: Optional[str] = None):
        self.sessions_dir = sessions_dir or _DEFAULT_SESSIONS_DIR

    def get_source_name(self) -> str:
        return "cognitive_session"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从认知会话目录采集训练案例。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳 (可选)

        Returns:
            训练案例列表 (FAIL-OPEN)
        """
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.sessions_dir):
            return cases

        try:
            session_dirs = sorted([
                os.path.join(self.sessions_dir, d)
                for d in os.listdir(self.sessions_dir)
                if d.startswith("CS-") and os.path.isdir(os.path.join(self.sessions_dir, d))
            ])
        except Exception:
            return cases

        for sdir in session_dirs:
            if len(cases) >= limit:
                break
            try:
                case = self._parse_session(sdir)
                if case is not None:
                    cases.append(case)
            except Exception:
                # FAIL-OPEN: 跳过损坏的会话
                continue

        return cases[:limit]

    def _parse_session(self, session_dir: str) -> Optional[TrainingCase]:
        """解析单个会话目录,构建 TrainingCase。

        Returns:
            TrainingCase 或 None (如果会话无 recall 或损坏)
        """
        session_json_path = os.path.join(session_dir, "session.json")
        action_chain_path = os.path.join(session_dir, "action_chain.jsonl")

        # 读取 session.json
        try:
            with open(session_json_path, "r", encoding="utf-8") as f:
                session = json.load(f)
        except Exception:
            return None  # FAIL-OPEN: session.json 损坏

        session_id = session.get("id", os.path.basename(session_dir))
        task_type = session.get("task_type", "unknown")
        status = session.get("status", "unknown")
        recalled_ids = session.get("recalled_memory_ids", [])
        recalled_processes = session.get("recalled_processes", [])
        action_count = session.get("action_count", 0)

        # 过滤无 recall 的会话 (无训练价值)
        if not recalled_ids and action_count == 0:
            return None

        # 构造 node_sequence
        node_seq = []

        # 1. session_start
        node_seq.append(f"session_start(task_type={task_type})")

        # 2. recall 节点
        if recalled_ids:
            node_seq.append(f"recall.query(context={task_type})")
            node_seq.append("recall.db_query(min_quality=C)")
            node_seq.append(f"recall.results(count={len(recalled_ids)})")
            # 添加前3个 recall ID 作为上下文
            for rid in recalled_ids[:3]:
                node_seq.append(f"recall.hit({rid})")
        else:
            node_seq.append("recall.query(context=task_type)")
            node_seq.append("recall.results(count=0)")

        # 3. process suggestions
        if recalled_processes:
            node_seq.append(f"recall.process_suggestions(count={len(recalled_processes)})")
            for p in recalled_processes[:3]:
                skill_id = p.get("skill_id", "?")
                node_seq.append(f"process_suggest({skill_id})")

        # 4. action_chain 节点
        actions = self._read_action_chain(action_chain_path)
        for action in actions[:10]:  # 最多10个 action 节点
            a_type = action.get("action_type", "unknown")
            detail = action.get("detail", "")
            # 截取 detail 前30字符
            detail_short = detail[:30].replace("\n", " ") if detail else ""
            node_seq.append(f"action.{a_type}({detail_short})")

        # 5. session_end
        node_seq.append(f"session_end(status={status})")

        # 派生 outcome: ended→success, 其他→partial (未完成=部分有效)
        outcome = "success" if status == "ended" else "partial"

        return TrainingCase(
            intent=f"session.{session_id}",
            actions=node_seq,
            outcome_text=outcome,
            learned=[
                f"task_type={task_type}",
                f"recall_count={len(recalled_ids)}",
                f"action_count={action_count}",
                f"node_count={len(node_seq)}",
            ],
            layer_tags=["DSH"],
            quality="B",
            confidence=0.5,
            source=f"cognitive_session:{session_id}",
            metadata={
                "outcome": outcome,  # ended→success, 否则→incomplete (走quality派生)
                "session_id": session_id,
                "task_type": task_type,
                "status": status,
                "recall_count": len(recalled_ids),
                "action_count": action_count,
                "recalled_memory_ids": recalled_ids[:5],
                "node_count": len(node_seq),
            },
        )

    def _read_action_chain(self, path: str) -> list:
        """读取 action_chain.jsonl,返回 action 列表。"""
        actions = []
        if not os.path.exists(path):
            return actions
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        action = json.loads(line)
                        actions.append(action)
                    except Exception:
                        continue
        except Exception:
            pass
        return actions

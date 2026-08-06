#!/usr/bin/env python3
"""
认知会话包裹器 — Cognitive Session Wrapper

在现有daemon+git hook之上增加"会话管理"层，将离散的文件变更和commit事件
编织成有意义的"解决路径"。

会话生命周期:
  开始: daemon检测到10分钟无活动后的首次文件变更
  中间: 记录行动链（文件变更 + MCP工具调用 + git操作）
  结束: git commit 或 30分钟无活动

会话结束时:
  1. RecallInjector: 会话开始时检索相关经验作为建议注入
  2. ActionChainLogger: 会话中记录完整行动链
  3. SolutionPathGenerator: 从行动链推断解决路径（模板+LLM可选）
  4. PostHocVerifier: 对比recall建议 vs 实际行为，贝叶斯校验
  5. PathComparison: 同一问题的不同解法对比排序

核心设计原则:
  - 建议而非约束: recall注入的经验是"建议"，AI可自由选择是否遵循
  - 事后校验: 会话结束时检查AI是否遵循了建议，根据结果更新置信度
  - 路径沉淀: 记录"怎么解决的"，不只是"什么文件变了"
  - AI工具无关: 所有数据来自文件变更+git+MCP，不依赖特定AI工具
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cognitive_loop_entry import CognitiveLoopEntry, get_cle


# ============================================================
# 会话数据模型
# ============================================================

@dataclass
class RecalledProcessItem:
    """会话内召回项（设计节 4.2）。

    kind='meta' = 原版 SKILL.md；kind='applied' = 历史 Solution Path。
    """
    kind: str  # 'meta' or 'applied'
    meta: Optional[Any]        # SuperpowersSkill 对象（meta 时）
    applied: Optional[Dict[str, Any]]  # 应用认知流程摘要（applied 时）
    match_score: float
    match_reason: str
    skill_id: Optional[str]    # 原版 Skill ID（meta 时必填；applied 时 parent_skill_id）
    applied_id: Optional[str]  # applied 的 template_id（applied 时必填）


class CognitiveSession:
    """一次认知会话的数据模型"""

    def __init__(self, session_id: Optional[str] = None):
        self.id = session_id or f"CS-{int(time.time() * 1000)}"
        self.start_time: float = time.time()
        self.end_time: Optional[float] = None
        self.status: str = "active"  # active, ended
        self.action_chain: List[Dict[str, Any]] = []
        self.recalled_memory_ids: List[str] = []  # recall注入的建议记忆ID
        self.recalled_processes: List[RecalledProcessItem] = []   # recall注入的流程（设计节 4.2 强类型）
        self.task_type: str = ""  # 从首批文件变更推断
        self.files_touched: set = set()
        # task_type演进历史: [{from, to, action_count, timestamp}]
        self.task_type_history: List[Dict[str, Any]] = []
        # 最近一次task_type检查时的action_count（控制检查频率）
        self._last_evolve_check_count: int = 0
        # 灵敏模式：接近阈值时每次 file_change 都检查，避免临界区漂过演进机会
        self._evolve_sensitive: bool = False

    def add_action(self, action_type: str, detail: str, **extra):
        """记录一个行动事件"""
        event = {
            "timestamp": time.time(),
            "session_id": self.id,
            "action_type": action_type,
            "detail": detail,
        }
        event.update(extra)
        self.action_chain.append(event)

    def to_dict(self) -> Dict[str, Any]:
        # 持久化 recalled_processes（修复：原遗漏导致跨进程丢失）
        recalled_processes_serialized = []
        for item in self.recalled_processes:
            try:
                recalled_processes_serialized.append({
                    "kind": item.kind,
                    "match_score": item.match_score,
                    "match_reason": item.match_reason,
                    "skill_id": item.skill_id,
                    "applied_id": item.applied_id,
                    "meta_skill_id": getattr(item.meta, "skill_id", None) if item.meta else None,
                    "meta_display_name": getattr(item.meta, "display_name", None) if item.meta else None,
                    "applied_summary": item.applied,
                })
            except Exception:
                continue
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "task_type": self.task_type,
            "action_count": len(self.action_chain),
            "recalled_memory_ids": self.recalled_memory_ids,
            "recalled_processes": recalled_processes_serialized,
            "files_touched": list(self.files_touched),
            "task_type_history": self.task_type_history,
        }

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveSession":
        """从持久化的session.json重建会话对象（跨进程恢复）。"""
        sess = cls(session_id=data.get("id"))
        sess.start_time = data.get("start_time", time.time())
        sess.end_time = data.get("end_time")
        sess.status = data.get("status", "active")
        sess.task_type = data.get("task_type", "")
        sess.recalled_memory_ids = data.get("recalled_memory_ids", [])
        sess.files_touched = set(data.get("files_touched", []))
        sess.task_type_history = data.get("task_type_history", [])
        # 恢复 recalled_processes（修复：原遗漏导致跨进程丢失）
        for rp in data.get("recalled_processes", []):
            try:
                sess.recalled_processes.append(RecalledProcessItem(
                    kind=rp.get("kind", "meta"),
                    meta=None,  # SuperpowersSkill 对象不反序列化（按需重新 retrieve）
                    applied=rp.get("applied_summary"),
                    match_score=rp.get("match_score", 0.0),
                    match_reason=rp.get("match_reason", ""),
                    skill_id=rp.get("skill_id"),
                    applied_id=rp.get("applied_id"),
                ))
            except Exception:
                continue
        # 兼容旧数据：反序列化后，用重载后的action_chain长度恢复检查点
        sess._last_evolve_check_count = 0
        sess._evolve_sensitive = False
        return sess

    def reload_action_chain(self, session_dir: Path):
        """从action_chain.jsonl重载完整行动链（跨进程恢复时调用）。"""
        chain_file = session_dir / "action_chain.jsonl"
        if not chain_file.exists():
            return
        try:
            with open(chain_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.action_chain.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass


# ============================================================
# task_type 动态演进配置
# ============================================================

# 演进统计窗口：看最近 N 个文件（不是全部会话历史，避免历史惯性过大）
EVOLVE_WINDOW_SIZE: int = 20
# 新 task_type 占比超过此阈值才允许演进（避免噪音切换）
EVOLVE_MAJORITY_RATIO: float = 0.5
# 另一类型占比达到此值时，启用"灵敏模式"：后续每次 file_change 都检查
# （避免临界条件附近因检查间隔而漂过演进机会）
EVOLVE_SENSITIVE_RATIO: float = 0.4
# 普通检查间隔（action_chain 累积长度差）
EVOLVE_CHECK_STD_STEP: int = 5
# 新 task_type 与当前 task_type 必须属于不同大类才演进
# （如 trading-data→trading-system 不算切换，但 trading-system→architecture-design 算）
EVOLVE_CATEGORY_GROUPS: Dict[str, str] = {
    # 交易大类
    "trading-system": "trading",
    "trading-data": "trading",
    "strategy-state": "trading",
    "risk-control": "trading",
    # P0: 交易细粒度 task_type
    "strategy-research": "trading",
    "strategy-backtest": "trading",
    "strategy-execution": "trading",
    "strategy-governance": "trading",
    # 开发大类
    "python-development": "dev",
    "frontend-development": "dev",
    # 认知/记忆大类
    "memory-system": "cog",
    "cognitive-integration": "cog",
    # 架构/文档大类
    "architecture-design": "archdoc",
    "documentation": "archdoc",
    "knowledge-management": "archdoc",
    "product-platform": "archdoc",
    # 配置
    "configuration": "config",
    "general": "other",
}


def _category_of(task_type: str) -> str:
    return EVOLVE_CATEGORY_GROUPS.get(task_type, task_type)


def _collect_recent_files(action_chain: List[Dict[str, Any]], window: int) -> List[str]:
    """从行动链中提取最近N个file_change的文件路径。"""
    recent = []
    for action in reversed(action_chain):
        if action.get("action_type") == "file_change" and action.get("file"):
            recent.append(action["file"])
            if len(recent) >= window:
                break
    return list(reversed(recent))


def _should_evolve_task_type(
    current: str,
    recent_files: List[str],
    threshold_ratio: float = EVOLVE_MAJORITY_RATIO,
) -> Optional[str]:
    """
    判断是否需要演进task_type。

    Args:
        current: 当前task_type
        recent_files: 最近的文件列表
        threshold_ratio: 新task_type占比阈值

    Returns:
        新task_type（需要演进时），None（不需要演进时）
    """
    if not recent_files:
        return None

    # 统计最近窗口内每个task_type的出现次数
    from collections import Counter
    type_counter: Counter = Counter()
    for f in recent_files:
        t = infer_task_type([f])
        type_counter[t] += 1

    total = len(recent_files)
    if total == 0:
        return None

    # 找出占比最高的类型
    best_type, best_count = type_counter.most_common(1)[0]
    best_ratio = best_count / total

    # 新类型占比不够大 → 不演进
    if best_ratio < threshold_ratio:
        return None

    # 新类型和当前一样 → 无需演进
    if best_type == current:
        return None

    # 同类别的切换（如trading-data↔trading-system）视为同一工作场景，不切换
    if _category_of(best_type) == _category_of(current):
        return None

    # 满足条件，允许演进
    return best_type


# ============================================================
# 会话管理器
# ============================================================

INACTIVITY_THRESHOLD = 600  # 10分钟无活动 → 新会话
SESSION_TIMEOUT = 1800      # 30分钟无活动 → 会话结束

# SP（Solution Path）沉淀门槛：避免每次会话超时都生成低质 C 级 SP 噪声。
# 满足任一条件才沉淀到 solution_paths 活跃目录：
#   1. 有 git commit（明确交付意图）
#   2. 行动链长度 >= SP_DEPOSIT_MIN_ACTIONS（足够的工作量）
#   3. 触及文件数 >= SP_DEPOSIT_MIN_FILES（足够的复杂度）
# 不满足时仍写 memories（C 级候选），只是不污染 SP 活跃目录。
SP_DEPOSIT_MIN_ACTIONS = 20
SP_DEPOSIT_MIN_FILES = 5


class CognitiveSessionManager:
    """
    管理认知会话的生命周期。
    
    集成到daemon中：daemon检测到文件变更时调用on_file_change()
    集成到git hook中：commit时调用on_commit()
    """

    def __init__(self, sessions_dir: Optional[str] = None):
        """
        Args:
            sessions_dir: 会话存储目录。默认使用项目根下的 .cognitive/sessions
        """
        if sessions_dir:
            self.sessions_dir = Path(sessions_dir)
        else:
            # 默认: 项目根/.cognitive/sessions （跨进程一致）
            self.sessions_dir = _SCRIPT_DIR.parent.parent / ".cognitive" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._current_session_file = self.sessions_dir / ".current"
        self.current_session: Optional[CognitiveSession] = None
        self._last_activity: float = 0.0
        # P3: Suggestions 定时刷新器（延迟初始化，避免循环 import）
        self._refresher = None
        # 跨进程恢复: 从磁盘加载未结束的会话
        self._load_current_session()

    # ---------- 跨进程会话持久化 ----------

    def _persist_current_session_id(self):
        """将当前会话ID持久化到磁盘，供其他进程（git hook）恢复。"""
        if self.current_session:
            self._current_session_file.write_text(self.current_session.id)
        else:
            self._clear_current_session_id()

    def _clear_current_session_id(self):
        """清除当前会话标记（会话结束时调用）。"""
        if self._current_session_file.exists():
            try:
                self._current_session_file.unlink()
            except OSError:
                pass

    def _load_current_session(self):
        """从磁盘恢复未结束的会话（跨进程恢复核心）。"""
        if not self._current_session_file.exists():
            return
        try:
            session_id = self._current_session_file.read_text().strip()
        except OSError:
            return
        if not session_id:
            return
        session_dir = self.sessions_dir / session_id
        meta_file = session_dir / "session.json"
        if not meta_file.exists():
            # 会话目录不存在，清理过期标记
            self._clear_current_session_id()
            return
        try:
            data = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            return
        # 只恢复未结束的会话
        if data.get("status") != "active":
            self._clear_current_session_id()
            return
        sess = CognitiveSession.from_dict(data)
        sess.reload_action_chain(session_dir)
        self.current_session = sess
        self._last_activity = sess.start_time  # 恢复后由后续活动刷新

    def on_file_change(self, filepath: str, change_type: str = "modified") -> CognitiveSession:
        """
        daemon检测到文件变更时调用。
        如果距离上次活动超过10分钟，开新会话。
        """
        now = time.time()

        # 检查是否需要开新会话
        if (self.current_session is None or
                now - self._last_activity > INACTIVITY_THRESHOLD):
            # 结束旧会话（如果有）
            if self.current_session and self.current_session.status == "active":
                self._end_session(timeout=True)

            # 开新会话
            self.current_session = CognitiveSession()
            self.current_session.files_touched.add(filepath)

            # 推断任务类型
            self.current_session.task_type = infer_task_type([filepath])

            # 执行recall注入
            self._inject_recall(self.current_session)

            # 记录行动
            self.current_session.add_action("file_change", f"{change_type}: {filepath}", file=filepath)

            # 持久化会话
            self._save_session(self.current_session)
            # 持久化当前会话ID，供git hook进程恢复
            self._persist_current_session_id()

            self._last_activity = now
            return self.current_session

        # 同一会话内的后续变更
        self.current_session.files_touched.add(filepath)
        self.current_session.add_action("file_change", f"{change_type}: {filepath}", file=filepath)
        self._last_activity = now

        # ---------- task_type 动态演进检查 ----------
        sess = self.current_session
        # 控制检查频率：
        #   1) 普通模式：每 EVOLVE_CHECK_STD_STEP 个操作检查一次
        #   2) 灵敏模式（有另一类型占比已达 EVOLVE_SENSITIVE_RATIO）：每次都检查
        #      （避免临界条件附近因检查间隔而"漂过"演进机会）
        check_span = len(sess.action_chain) - sess._last_evolve_check_count
        need_check = False
        if check_span >= EVOLVE_CHECK_STD_STEP:
            need_check = True
        elif check_span >= 1 and sess._evolve_sensitive:
            need_check = True
        if need_check:
            sess._last_evolve_check_count = len(sess.action_chain)
            recent_files = _collect_recent_files(sess.action_chain, EVOLVE_WINDOW_SIZE)
            new_type = _should_evolve_task_type(sess.task_type, recent_files)
            if new_type:
                old_type = sess.task_type
                # 记录演进历史
                sess.task_type_history.append({
                    "from": old_type,
                    "to": new_type,
                    "action_count": len(sess.action_chain),
                    "timestamp": now,
                })
                # 更新task_type
                sess.task_type = new_type
                # 记录演进行动
                sess.add_action(
                    "task_type_evolved",
                    f"{old_type} → {new_type}",
                    from_type=old_type,
                    to_type=new_type,
                    category_from=_category_of(old_type),
                    category_to=_category_of(new_type),
                )
                # 新领域的recall建议注入（覆盖/补充初始建议）
                try:
                    self._inject_recall(sess, evolved=True)
                except Exception:
                    pass
                # 演进后退出灵敏模式，回到普通间隔
                sess._evolve_sensitive = False
            else:
                # 检查是否应进入灵敏模式：非当前 task_type 的累计占比是否 ≥ 灵敏阈值
                from collections import Counter
                type_counter: Counter = Counter()
                for f in recent_files:
                    type_counter[infer_task_type([f])] += 1
                other_total = sum(v for k, v in type_counter.items() if k != sess.task_type)
                if recent_files and (other_total / len(recent_files)) >= EVOLVE_SENSITIVE_RATIO:
                    sess._evolve_sensitive = True
                else:
                    sess._evolve_sensitive = False

        # ---------- P3: Suggestions 定时刷新（TTL + 动作数双触发） ----------
        # 每次文件变更时检查是否需要刷新 suggestions.md
        # 控制频率：每 5 个动作检查一次（避免每次都 stat 文件）
        if len(sess.action_chain) % 5 == 0:
            try:
                if self._refresher is None:
                    from auto_update_trigger import SuggestionsRefresher
                    self._refresher = SuggestionsRefresher()
                # 计算自上次刷新以来的动作数
                meta_path = self.sessions_dir / sess.id / "suggestions_meta.json"
                actions_since_last = len(sess.action_chain)
                if meta_path.exists():
                    import json as _json
                    meta = _json.loads(meta_path.read_text())
                    actions_since_last = len(sess.action_chain) - int(meta.get("actions_at_last_refresh", 0))
                self._refresher.refresh_if_needed(self, actions_since_last=max(0, actions_since_last))
            except Exception:
                pass  # 刷新失败不阻塞主流程

        self._save_session(self.current_session)
        return self.current_session

    def on_tool_call(self, tool_name: str, args: dict, result_summary: str = ""):
        """MCP工具调用时记录"""
        if self.current_session and self.current_session.status == "active":
            self.current_session.add_action(
                "tool_call", f"{tool_name}({args})",
                tool=tool_name, result_summary=result_summary
            )
            self._last_activity = time.time()
            self._save_session(self.current_session)

    def on_commit(self, commit_info: Dict[str, Any]):
        """
        git commit时触发会话结束。

        跨进程恢复: git hook是独立进程，__init__时已从磁盘恢复current_session。
        若daemon未运行（无活跃会话），从commit信息创建fallback会话，确保闭环不断裂。
        """
        # 兼容 extract_commit_info 返回的 "commit_hash" 和简写 "hash" 两种key
        commit_hash = commit_info.get("commit_hash") or commit_info.get("hash", "")

        # 无活跃会话时，从commit信息创建fallback会话（daemon未运行的兜底）
        if not self.current_session or self.current_session.status != "active":
            self.current_session = CognitiveSession()
            commit_files = commit_info.get("files", [])
            self.current_session.task_type = infer_task_type(
                commit_files if commit_files else ["general"]
            )
            for f in commit_files:
                self.current_session.files_touched.add(f)
            # fallback会话也执行recall注入（获取建议）
            self._inject_recall(self.current_session)

        self.current_session.add_action(
            "git_commit", commit_info.get("message", ""),
            commit_hash=commit_hash,
            files=commit_info.get("files", []),
        )
        self._end_session(commit_info=commit_info)

    def check_timeout(self) -> bool:
        """检查会话是否超时（30分钟无活动）"""
        if (self.current_session and 
                self.current_session.status == "active" and
                time.time() - self._last_activity > SESSION_TIMEOUT):
            self._end_session(timeout=True)
            return True
        return False

    def _inject_recall(self, session: CognitiveSession, evolved: bool = False):
        """recall注入建议（知识+记忆+流程）。

        Args:
            evolved: 是否为task_type演进触发。True时追加写入suggestions文件
                     （保留原建议，避免覆盖初始内容）。
        """
        try:
            cle = get_cle()
            # 用任务类型作为检索词（阈值 C，确保有结果返回，按 score 排序）
            results = cle.recall(session.task_type, top_k=5, min_quality="C")
            new_memory_ids = [r.get("id", "") for r in results]
            if evolved:
                # 演进模式：合并，避免重复
                existing_ids = set(session.recalled_memory_ids)
                session.recalled_memory_ids.extend(
                    [mid for mid in new_memory_ids if mid not in existing_ids]
                )
            else:
                session.recalled_memory_ids = new_memory_ids

            # 检索相关流程（改造后用 SkillLoader，设计节 3.6）
            from cognitive_superpowers import SkillLoader, resolve_unit_for_task
            loader = SkillLoader()
            proc_result = loader.retrieve(session.task_type, top_meta=3, top_applied=2, task_type=session.task_type)
            new_items: List[RecalledProcessItem] = []
            for (skill, score, reason) in proc_result.get("meta", []):
                new_items.append(RecalledProcessItem(
                    kind="meta", meta=skill, applied=None,
                    match_score=score, match_reason=reason,
                    skill_id=skill.skill_id, applied_id=None,
                ))
            for a in proc_result.get("applied", []):
                new_items.append(RecalledProcessItem(
                    kind="applied", meta=None, applied=a,
                    match_score=a.get("match_score", 0.0),
                    match_reason=a.get("match_reason", ""),
                    skill_id=a.get("skill_id") or a.get("parent_skill"),
                    applied_id=a.get("applied_id"),
                ))
            # 去抖合并（设计节 3.6：稳定优先，按 skill_id/applied_id 去重，保留高分项）
            if evolved:
                existing_map = {}
                for item in session.recalled_processes:
                    key = f"P-{item.kind}-{item.skill_id or item.applied_id}"
                    existing_map[key] = item
                for item in new_items:
                    key = f"P-{item.kind}-{item.skill_id or item.applied_id}"
                    if key not in existing_map or item.match_score > existing_map[key].match_score:
                        existing_map[key] = item
                session.recalled_processes = list(existing_map.values())[:5]
            else:
                session.recalled_processes = new_items[:5]
            # 保存引用给后续沉淀使用
            session._meta_processes = [i for i in session.recalled_processes if i.kind == "meta"]  # type: ignore[attr-defined]
            session._applied_processes = [i for i in session.recalled_processes if i.kind == "applied"]  # type: ignore[attr-defined]

            # 同步写入 WorkingMemory.process_block（设计节 3.2，路径 C 后台注入）
            try:
                wm = getattr(cle, "working_memory", None)
                if wm is not None:
                    md_parts = []
                    for item in session.recalled_processes:
                        if item.kind == "meta" and item.meta is not None:
                            md_parts.append(
                                f"## [元认知] {item.meta.skill_id} · 匹配度 {item.match_score:.2f}\n"
                                f"> {item.match_reason}\n"
                                + ("\n".join(f"- {g}" for g in item.meta.hard_gates) if item.meta.hard_gates else "")
                            )
                        elif item.kind == "applied" and item.applied is not None:
                            title = item.applied.get("title", item.applied_id)
                            md_parts.append(
                                f"## [应用案例] {title}\n> 父: {item.skill_id} · {item.match_reason}"
                            )
                    if md_parts:
                        wm.load_process_block("\n\n".join(md_parts))
            except Exception:
                pass  # process_block 写入失败不阻断主链路（GC6）

            # 推断目标应用记忆单元
            unit_info = resolve_unit_for_task(session.task_type)
            session._target_unit = unit_info  # type: ignore[attr-defined]

            # 生成建议文件
            if results or session.recalled_processes:
                suggestions = self._format_suggestions(results, session.recalled_processes)
                suggestion_file = self.sessions_dir / session.id / "suggestions.md"
                suggestion_file.parent.mkdir(parents=True, exist_ok=True)
                if evolved and suggestion_file.exists():
                    # 演进时追加写入，保留原建议，标注演进时间
                    header = (
                        f"\n\n---\n"
                        f"## 🔄 演进于 {time.strftime('%Y-%m-%d %H:%M:%S')}  "
                        f"task_type → {session.task_type}\n\n"
                    )
                    existing = suggestion_file.read_text()
                    suggestion_file.write_text(existing + header + suggestions)
                else:
                    suggestion_file.write_text(suggestions)

            # 注意：不调用 cle.close()，因为 get_cle() 返回进程级单例，
            # close 后后续调用会失败（原旧代码用 CognitiveLoopEntry() 每次新实例所以无此问题）
        except Exception as e:
            logger.warning("_inject_recall 失败（不阻塞daemon）: %s", e)

    def _format_suggestions(
        self,
        memories: List[Dict[str, Any]],
        processes: Optional[List[Any]] = None,
    ) -> str:
        """格式化建议文本（知识+记忆+流程，非约束）"""
        lines = [
            "# 💡 认知系统建议（非约束，可自由选择是否遵循）",
            f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        # 流程模板部分
        if processes:
            # 检测是否为 RecalledProcessItem（新格式）或 ProcessTemplate（旧格式）
            if processes and hasattr(processes[0], "kind"):
                # RecalledProcessItem 格式（设计节 4.2）
                lines.append("## 🎯 流程建议")
                for i, item in enumerate(processes, 1):
                    if item.kind == "meta" and item.meta is not None:
                        lines.append(f"### {i}. [{item.meta.skill_id}] {item.meta.display_name}")
                        lines.append(f"   匹配度: {item.match_score:.2f} | {item.match_reason}")
                        if item.meta.hard_gates:
                            lines.append(f"   HARD-GATE: {item.meta.hard_gates[0][:80]}")
                    elif item.kind == "applied" and item.applied is not None:
                        title = item.applied.get("title", item.applied_id)
                        lines.append(f"### {i}. [应用案例] {title}")
                        lines.append(f"   父 Skill: {item.skill_id} | 匹配度: {item.match_score:.2f}")
                lines.append("")
            else:
                # 旧格式（ProcessTemplate）向后兼容
                from cognitive_superpowers import format_process_suggestions
                process_text = format_process_suggestions(processes)
                lines.append("## 🎯 流程建议")
                lines.append(process_text)
                lines.append("")

        # 记忆经验部分
        if memories:
            lines.append("## 📚 相关经验")
            lines.append(f"# 共 {len(memories)} 条")
            for i, mem in enumerate(memories, 1):
                ql = mem.get("quality_level", "?")
                content = mem.get("content", "")[:100]
                lines.append(f"{i}. [{ql}] {content}")
            lines.append("")

        lines.extend([
            "---",
            "💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。",
            "   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。",
        ])

        return "\n".join(lines)

    def _end_session(self, timeout: bool = False, commit_info: Optional[Dict] = None):
        """结束会话: 生成解决路径 + 事后校验 + 沉淀为应用认知流程"""
        if not self.current_session:
            return

        session = self.current_session
        session.end_time = time.time()
        session.status = "ended"

        # 生成解决路径
        solution_path = generate_solution_path(session, commit_info)

        # 记录到认知系统
        try:
            cle = get_cle()
            memory_id = cle.record(
                content=solution_path["content"],
                quality_level="C",
                confidence=0.3,
                tags=["solution_path", session.task_type],
                source="cognitive-session",
            )

            # 事后校验（流程+记忆+映射反馈）
            post_hoc_verify(cle, session, solution_path, memory_id)

            # 注意：不调用 cle.close()，get_cle() 返回进程级单例
        except Exception as e:
            logger.warning("_deposit_applied_template 记忆沉淀失败: %s", e)

        # 沉淀为应用认知流程（应用记忆层）
        # P5: SP沉淀门槛 — 低活跃会话不写 solution_paths 活跃目录，避免 C 级噪声堆积
        if self._should_deposit_sp(session, commit_info):
            try:
                self._deposit_applied_template(session, solution_path)
            except Exception:
                pass

        # 持久化完整会话
        self._save_session(session, final=True)
        self.current_session = None
        # 清除当前会话标记
        self._clear_current_session_id()

    def _should_deposit_sp(
        self,
        session: CognitiveSession,
        commit_info: Optional[Dict] = None,
    ) -> bool:
        """
        SP 沉淀门槛判断（P5）：是否值得将本次会话沉淀为 solution_paths 模板。

        满足任一条件即沉淀：
          1. 有 git commit（明确的交付意图）
          2. 行动链长度 >= SP_DEPOSIT_MIN_ACTIONS（足够的工作量）
          3. 触及文件数 >= SP_DEPOSIT_MIN_FILES（足够的复杂度）

        低活跃会话（如纯超时结束、零星文件改动）不沉淀，避免 C 级噪声堆积。
        注意：memories 记录不受此门槛限制，仍照常写入做 C 级候选。
        """
        if commit_info is not None:
            return True
        if len(session.action_chain) >= SP_DEPOSIT_MIN_ACTIONS:
            return True
        if len(session.files_touched) >= SP_DEPOSIT_MIN_FILES:
            return True
        return False

    def _deposit_applied_template(
        self,
        session: CognitiveSession,
        solution_path: Dict[str, Any],
    ):
        """
        将 Solution Path 沉淀为应用认知流程模板（应用记忆层）。

        改造后（设计节 4.5 + GC8）：
          1. 用 verify_skill_followed 对每个召回的 meta Skill 计算 follow_score
          2. parent_skill_ids = 所有 followed 的 Skill（多父支持）
          3. reproducible_steps = _condense_action_chain 纯结构化压缩
          4. metadata 新增 5 字段
        """
        try:
            from cognitive_superpowers import (
                ProcessTemplateRegistry,
                feedback_to_meta_template,
            )
            from skill_verifier import verify_skill_followed, FOLLOW_SCORE_THRESHOLD

            registry = ProcessTemplateRegistry()

            # 1. 对每个召回的 meta Skill 计算 follow_score（设计节 4.3）
            verify_report = {}
            parent_skill_ids = []
            parent_id = None
            meta_items = getattr(session, "_meta_processes", []) or []
            best_score = 0.0
            for item in meta_items:
                if item.kind != "meta" or item.meta is None:
                    continue
                report = verify_skill_followed(item.meta, session.action_chain)
                verify_report[item.meta.skill_id] = {
                    "score": report["score"],
                    "followed": report["followed"],
                    "checklist_matched": report["checklist_matched"],
                    "checklist_missed": report["checklist_missed"],
                    "gate_violations": report["gate_violations"],
                }
                if report["followed"]:
                    parent_skill_ids.append(item.meta.skill_id)
                    if report["score"] > best_score:
                        best_score = report["score"]
                        parent_id = item.meta.skill_id

            # 2. 没有任何 Skill 达到阈值 → custom-path（设计节 4.3 Step 3）
            if not parent_skill_ids:
                parent_skill_ids = ["custom-path"]

            # 3. 压缩行动链为 reproducible_steps（GC8 纯结构化）
            reproducible_steps = _condense_action_chain(session.action_chain)

            # 4. 推断实际步骤（从行动链，保留原逻辑兼容）
            steps = _infer_steps_from_action_chain(
                session.action_chain, parent_id
            )

            # 5. 收集 key_artifacts
            files_touched = list(session.files_touched)
            added_files = [f for f in files_touched if "test_" in f or "/tests/" in f]
            modified_files = [f for f in files_touched if f not in added_files]
            key_artifacts = {
                "added_files": added_files,
                "modified_files": modified_files,
                "debt_items": [],
            }

            # 6. 生成应用模板ID
            # P2: 交易类 task_type 用 APP-TRD- 前缀，开发类用 APP- 前缀
            _trading_types = frozenset([
                "trading-system", "trading-data", "strategy-state", "risk-control",
                "strategy-research", "strategy-backtest", "strategy-execution", "strategy-governance",
            ])
            _prefix = "APP-TRD-" if session.task_type in _trading_types else "APP-"
            applied_id = f"{_prefix}{session.id.split('-')[-1]}"
            name = f"{session.task_type} 的解决路径"

            # 7. 获取目标单元
            unit_info = getattr(session, "_target_unit", None)
            unit_id = unit_info["unit_id"] if unit_info else "MU-DEV"

            # 8. 注册并持久化（含 5 个新字段）
            registry.register_applied_from_session(
                template_id=applied_id,
                name=name,
                steps=steps,
                parent_template_id=parent_id,
                solution_path=solution_path,
                unit_id=unit_id,
                parent_skill_ids=parent_skill_ids,
                process_verify_report=verify_report,
                task_type=session.task_type,
                reproducible_steps=reproducible_steps,
                key_artifacts=key_artifacts,
            )

            # 9. 将验证结果反哺到元模板（应用→元反馈）
            success = solution_path["outcome"]["success"]
            feedback_to_meta_template(registry, applied_id, success)

            # 10. 持久化映射
            registry.mapping_registry.save()
        except Exception:
            pass

    def _save_session(self, session: CognitiveSession, final: bool = False):
        """持久化会话数据"""
        session_dir = self.sessions_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)

        # 会话元数据
        meta_file = session_dir / "session.json"
        meta_file.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False, default=str))

        # 行动链
        if session.action_chain:
            chain_file = session_dir / "action_chain.jsonl"
            with open(chain_file, "a") as f:
                f.write(json.dumps(session.action_chain[-1], ensure_ascii=False, default=str) + "\n")


# ============================================================
# 任务类型推断
# ============================================================

# 交易相关顶层目录集合（易经推理/马丁/三屏/风控/监控/调控/指标/交易脚本等）
_TRADING_DIRS = frozenset([
    "10-经典指标系统",
    "11-易经推理系统",
    "12-三屏趋势系统",
    "13-通用风控模块",
    "14-V15经典马丁策略",
    "15-监控告警系统",
    "16-调控系统",
    "6-TRADING",
    "experiments",  # P0: experiments/ab-trading/ 含 A 系列节点代码和回测
])

# P0: 交易目录细粒度 task_type 路由规则
# (顶层目录, 二级目录关键词) → task_type
# 按优先级从上到下匹配，命中即返回
_TRADING_FINEGRAIN_RULES = [
    # 调度/治理配置（.github/workflows/ 或 docs/ 下的 trigger/governance 文件）
    (".github", "workflows", "strategy-governance"),
    ("docs", None, "strategy-governance"),
    # SKILL.md 策略研究/方法论
    ("skills", None, "strategy-research"),
    # 回测目录
    ("backtest", None, "strategy-backtest"),
    # A 系列节点代码（experiments/ab-trading/core/nodes/）
    ("core", "nodes", "strategy-execution"),
]

# 交易 data 子目录（运行时数据/产物，非代码）
_TRADING_DATA_SUBDIRS = frozenset(["data", "artifacts", "memory", "signal_pool", "A系列研报"])


def infer_task_type(filepaths: List[str]) -> str:
    """从文件路径推断任务类型"""
    if not filepaths:
        return "general"

    f = filepaths[0]
    parts = Path(f).parts

    # 按顶层目录分类
    if len(parts) > 0:
        top = parts[0]
        if top == "4-MEMORY":
            return "memory-system"
        elif top in _TRADING_DIRS:
            # P0: 先检查是否为运行时数据/产物目录
            if len(parts) >= 2 and parts[1] in _TRADING_DATA_SUBDIRS:
                return "trading-data"
            # P0: 细粒度路由 — 按二级/三级目录关键词匹配
            if len(parts) >= 2:
                sub = parts[1]
                for rule_sub, rule_sub2, rule_type in _TRADING_FINEGRAIN_RULES:
                    if sub == rule_sub:
                        # 如果规则要求三级目录也匹配
                        if rule_sub2 is not None:
                            if len(parts) >= 3 and parts[2] == rule_sub2:
                                return rule_type
                        else:
                            return rule_type
            # P0: experiments/ab-trading/ 下按三级目录细分
            if top == "experiments" and len(parts) >= 2 and parts[1] == "ab-trading":
                if len(parts) >= 3:
                    third = parts[2]
                    if third == "backtest":
                        return "strategy-backtest"
                    if third == "core" and len(parts) >= 4 and parts[3] == "nodes":
                        return "strategy-execution"
                # experiments/ab-trading/ 下其他 .py 默认归 strategy-execution
                return "strategy-execution"
            # P0: 交易目录下未命中细粒度规则的 .py 代码文件归 strategy-execution
            # （如 10-经典指标系统/indicators/rsi.py 是修改策略代码）
            if Path(f).suffix == ".py":
                return "strategy-execution"
            # 默认交易系统
            return "trading-system"
        elif top == "0-系统文档管理":
            return "documentation"
        elif top == "2-KNOWLEDGE":
            return "knowledge-management"
        elif top in ("1-ARCHITECTURE",):
            return "architecture-design"
        elif top in ("3.1-FRONTEND", "3-FRONTEND"):
            return "frontend-development"
        elif top in ("7-产物中台",):
            return "product-platform"

    # 按文件类型分类
    suffix = Path(f).suffix
    if suffix == ".py":
        return "python-development"
    elif suffix == ".md":
        return "documentation"
    elif suffix in (".json", ".yaml", ".yml"):
        return "configuration"
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        return "frontend-development"

    return "general"


# ============================================================
# 解决路径生成
# ============================================================

def generate_solution_path(
    session: CognitiveSession,
    commit_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    从行动链生成结构化解决路径。
    
    当前使用模板推断（从行动模式推断思维链），不依赖外部LLM。
    未来可增强为LLM总结。
    """
    action_count = len(session.action_chain)
    file_changes = [a for a in session.action_chain if a["action_type"] == "file_change"]
    tool_calls = [a for a in session.action_chain if a["action_type"] == "tool_call"]
    commits = [a for a in session.action_chain if a["action_type"] == "git_commit"]

    # 推断问题
    if commit_info and commit_info.get("message"):
        problem = commit_info["message"].split("\n")[0][:80]
    else:
        problem = f"任务涉及 {len(session.files_touched)} 个文件"

    # 推断方案
    approach_parts = []
    if file_changes:
        approach_parts.append(f"修改了 {len(file_changes)} 次文件")
    if tool_calls:
        tool_names = set(a.get("tool", "") for a in tool_calls)
        approach_parts.append(f"使用了 {len(tool_names)} 种工具({', '.join(tool_names)})")
    if commits:
        approach_parts.append(f"提交了 {len(commits)} 次")
    approach = " | ".join(approach_parts) if approach_parts else "无明确行动"

    # 推断关键决策（从文件变更模式）
    key_decisions = []
    if session.files_touched:
        key_decisions.append(f"涉及文件: {', '.join(list(session.files_touched)[:3])}")
    if tool_calls:
        key_decisions.append(f"关键工具调用: {len(tool_calls)}次")

    # 结果
    success = bool(commits) or (commit_info is not None)  # 有commit = 成功
    commit_hash = ""
    if commits:
        commit_hash = commits[0].get("commit_hash", "")
    elif commit_info:
        # 兼容 extract_commit_info 的 "commit_hash" 和简写 "hash"
        commit_hash = commit_info.get("commit_hash") or commit_info.get("hash", "")
    outcome = {
        "success": success,
        "commit_hash": commit_hash,
        "action_count": action_count,
        "duration_minutes": round(session.duration_seconds / 60, 1),
    }

    content = (
        f"[解决路径] 问题: {problem} | "
        f"方案: {approach} | "
        f"结果: {'success' if success else 'timeout'} "
        f"({action_count}步, {round(session.duration_seconds/60,1)}min)"
    )

    return {
        "content": content,
        "problem": problem,
        "approach": {
            "description": approach,
            "key_decisions": key_decisions,
            "action_count": action_count,
            "files_touched": list(session.files_touched),
            "duration_minutes": round(session.duration_seconds / 60, 1),
        },
        "outcome": outcome,
        "recalled": session.recalled_memory_ids,
    }


# ============================================================
# 事后校验
# ============================================================

def _condense_action_chain(
    action_chain: List[Dict[str, Any]], min_steps: int = 5, max_steps: int = 15
) -> List[str]:
    """设计节 4.5 + GC8：纯结构化压缩行动链，不靠 LLM 生成。

    规则：
      1. 相邻的同文件 file_change 合并为 1 条
      2. 纯注释/空行 edit 剔除（detail 含 "comment" 且无其他实质内容）
      3. 保留关键事件：tool_call / git_commit / mcp_call 不合并
      4. 输出 5-15 条人类可读步骤，超出按时间顺序保留首尾+中间采样
    """
    raw_steps: List[str] = []
    last_file = None
    merged_detail_buf: List[str] = []

    def _flush_buf():
        nonlocal merged_detail_buf
        if merged_detail_buf:
            summary = merged_detail_buf[0] if len(merged_detail_buf) == 1 else \
                f"{merged_detail_buf[0]}（共 {len(merged_detail_buf)} 次修改）"
            raw_steps.append(summary)
            merged_detail_buf = []

    for ev in action_chain:
        atype = ev.get("action_type", "")
        detail = str(ev.get("detail", ""))
        if atype == "file_change":
            f = ev.get("file", "")
            if _is_pure_comment_edit(detail):
                continue
            if f == last_file:
                merged_detail_buf.append(detail)
            else:
                _flush_buf()
                last_file = f
                merged_detail_buf = [detail]
        elif atype == "git_commit":
            _flush_buf()
            last_file = None
            ch = str(ev.get("commit_hash", ""))[:7]
            raw_steps.append(f"提交 commit {ch}: {detail}")
        elif atype == "tool_call":
            _flush_buf()
            last_file = None
            tool = ev.get("tool", "tool")
            raw_steps.append(f"调用工具 {tool}: {detail}")
        elif atype == "mcp_call":
            _flush_buf()
            last_file = None
            raw_steps.append(f"MCP {detail}")
        else:
            _flush_buf()
            last_file = None
            if detail:
                raw_steps.append(detail)
    _flush_buf()

    if len(raw_steps) > max_steps:
        head = raw_steps[:2]
        tail = raw_steps[-2:]
        mid_count = max_steps - 4
        mid = raw_steps[2:-2]
        step = max(1, len(mid) // max(1, mid_count))
        sampled_mid = mid[::step][:mid_count]
        raw_steps = head + sampled_mid + tail
    return raw_steps[:max_steps]


def _is_pure_comment_edit(detail: str) -> bool:
    """检测是否为纯注释 edit（GC8 剔除规则：含 comment/注释 且无实质代码内容）。

    判定原则：detail 中出现 comment/注释 即认为是注释相关改动；
    但若同时出现"实质代码内容"指示词（real logic / bug / function / 逻辑 / 函数 等），
    则说明改动涉及真实代码逻辑，不算纯注释，不予剔除。
    注意：edit/add/remove 等通用动词不作为"实质内容"判据，因为它们对所有改动都成立。
    """
    d = detail.lower()
    has_comment = "comment" in d or "注释" in d
    has_substantive = any(w in d for w in [
        "real logic", "logic", "bug", "function", "class", "method",
        "算法", "逻辑", "函数", "方法", "类",
    ])
    return has_comment and not has_substantive


def _compress_thought_chain(
    action_chain: List[Dict[str, Any]],
    reasoning_log: List[Dict[str, Any]],
    session_id: str,
    task_summary: str,
    skill_ids_injected: List[str],
    outcome_metrics: Dict[str, float],
    hard_gate_violations: Optional[List[str]] = None,
) -> "EvaluationSample":
    """设计节 7.3 + GC8：思维链压缩，纯结构化提取（不靠 LLM）。

    借鉴 hermes-agent trajectory_compressor 的"相邻合并/纯注释剔除/关键决策点提取"，
    去掉其 LLM 摘要部分（GC8 消除幻觉）。

    Args:
        action_chain: 会话行动链
        reasoning_log: AI 思考过程的关键事件（recall/verify/deposit 等触发点）
        outcome_metrics: 成效指标字典
        hard_gate_violations: HARD-GATE 违反列表（可选，默认空）
        其余字段直接填入 EvaluationSample

    Returns:
        EvaluationSample（thought_chain_compressed + action_chain_compressed）
    """
    from evaluation_engine import EvaluationSample

    if hard_gate_violations is None:
        hard_gate_violations = []

    # 行动链压缩（复用 Task 18 的 _condense_action_chain）
    action_compressed = _condense_action_chain(action_chain)

    # 思维链压缩：从 reasoning_log 提取关键决策点 + 行动链关键事件
    thought_steps: List[str] = []

    # 1. 关键决策点（从 reasoning_log）
    for entry in reasoning_log:
        event = entry.get("event", "")
        ctx = entry.get("context", "")
        if event == "recall":
            thought_steps.append(f"recall 检索：{ctx}")
        elif event == "verify":
            thought_steps.append(f"verify 校验：{ctx}")
        elif event == "_deposit_applied_template":
            thought_steps.append(f"沉淀应用路径：{ctx}")
        elif event:
            thought_steps.append(f"{event}: {ctx}")

    # 2. 行动链关键事件（tool_call / git_commit / mcp_call，不含纯 file_change）
    for ev in action_chain:
        atype = ev.get("action_type", "")
        if atype == "mcp_call":
            thought_steps.append(f"MCP 调用：{ev.get('detail', '')}")
        elif atype == "tool_call":
            thought_steps.append(f"工具调用 {ev.get('tool', '')}: {ev.get('detail', '')}")
        elif atype == "git_commit":
            ch = str(ev.get("commit_hash", ""))[:7]
            thought_steps.append(f"提交 commit {ch}")

    # 3. 限制 5-15 条（设计节 7.3）
    if len(thought_steps) > 15:
        head = thought_steps[:2]
        tail = thought_steps[-2:]
        mid = thought_steps[2:-2]
        step = max(1, len(mid) // 11)
        thought_steps = head + mid[::step][:11] + tail
    thought_steps = thought_steps[:15]

    return EvaluationSample(
        session_id=session_id,
        task_summary=task_summary,
        skill_ids_injected=skill_ids_injected,
        thought_chain_compressed=thought_steps,
        action_chain_compressed=action_compressed,
        hard_gate_violations=hard_gate_violations,
        outcome_metrics=outcome_metrics,
        timestamp=int(time.time()),
    )


# ============================================================
# Task 25: 评测闭环（设计节 7.2/7.5/7.7）
# ============================================================

def _count_reworks(action_chain: List[Dict[str, Any]]) -> int:
    """统计同文件被反复修改次数（每个文件 max(0, count-1) 求和）。"""
    file_counts: Dict[str, int] = {}
    for ev in action_chain:
        if ev.get("action_type") == "file_change":
            f = ev.get("file")
            if not f:
                continue
            file_counts[f] = file_counts.get(f, 0) + 1
    return sum(max(0, c - 1) for c in file_counts.values())


def _compute_tool_efficiency(action_chain: List[Dict[str, Any]]) -> float:
    """tool_call 事件中非查询类占比；查询工具集 {"read","glob","grep","search"}；无 tool_call 返回 0.0。"""
    query_tools = {"read", "glob", "grep", "search"}
    total = 0
    non_query = 0
    for ev in action_chain:
        if ev.get("action_type") == "tool_call":
            total += 1
            tool = str(ev.get("tool", "")).lower()
            if tool not in query_tools:
                non_query += 1
    if total == 0:
        return 0.0
    return non_query / total


def _maybe_distill_supplement(
    skill_id: str,
    supplement_path: Path,
    local_experience: str,
    validation_passed: bool,
    threshold: int = 3,
) -> None:
    """设计节 7.5：同一本土经验被验证 ≥ threshold 次后写入 supplement。"""
    counter_file = supplement_path.parent / f".{skill_id}_validation_count.txt"
    count = 0
    try:
        if counter_file.exists():
            count = int((counter_file.read_text(encoding="utf-8") or "0").strip() or "0")
    except (OSError, ValueError):
        count = 0

    if validation_passed:
        count += 1
        try:
            counter_file.write_text(str(count), encoding="utf-8")
        except OSError:
            pass

    if count < threshold:
        return

    try:
        content = supplement_path.read_text(encoding="utf-8")
    except OSError:
        return

    if local_experience in content:
        return

    new_section = f"\n## 本土沉淀（自动 · 验证 {count} 次）\n- {local_experience}\n"
    if "TODO 占位" in content:
        lines = content.splitlines(keepends=True)
        for idx, line in enumerate(lines):
            if "TODO 占位" in line:
                lines[idx] = new_section
                break
        content = "".join(lines)
    else:
        content += new_section

    try:
        supplement_path.write_text(content, encoding="utf-8")
    except OSError:
        pass


def _run_evaluation_closed_loop(session: CognitiveSession, applied_id: str) -> Dict[str, Any]:
    """设计节 7.2/7.7：会话结束 → 压缩 → A/B → 决策 → 升级/告警/quarantine → 反哺 → 记录。

    所有外部调用（send_cognitive_alert、record_evaluation、update_path_advantage）
    均用 try/except 包裹，单点失败不破坏闭环返回值。
    """
    from evaluation_engine import (
        compute_path_advantage,
        decide_learning_action,
        record_evaluation,
        load_history_baseline,
    )
    from cognitive_superpowers import ProcessTemplateRegistry
    from alert_bridge import send_cognitive_alert

    # 1. 收集 gate_violations 与 follow_score
    verify_reports = getattr(session, "_verify_reports", {}) or {}
    all_violations: List[str] = []
    follow_score = 0.0
    if isinstance(verify_reports, dict):
        for report in verify_reports.values():
            if not isinstance(report, dict):
                continue
            violations = report.get("gate_violations", []) or []
            all_violations.extend(violations)
            score = report.get("score", 0.0) or 0.0
            if score > follow_score:
                follow_score = score

    # 2. outcome_metrics
    outcome_metrics: Dict[str, float] = {
        "task_completion_success": 1.0 if getattr(session, "status", "") == "ended" else 0.0,
        "hard_gate_violation_count": float(len(all_violations)),
        "rework_count": float(_count_reworks(session.action_chain)),
        "tool_call_efficiency": _compute_tool_efficiency(session.action_chain),
        "duration_minutes": session.duration_seconds / 60.0,
        "follow_score": follow_score,
    }

    # 3. 压缩思维链
    skill_ids_injected = [
        i.skill_id for i in session.recalled_processes
        if i.kind == "meta" and i.skill_id
    ]
    sample = _compress_thought_chain(
        action_chain=session.action_chain,
        reasoning_log=getattr(session, "_reasoning_log", []),
        session_id=session.id,
        task_summary=session.task_type or "unknown",
        skill_ids_injected=skill_ids_injected,
        outcome_metrics=outcome_metrics,
        hard_gate_violations=all_violations,
    )

    # 4. A/B 对比
    baseline = load_history_baseline(session.task_type)
    if baseline is not None:
        try:
            path_advantage = compute_path_advantage(sample, baseline)
        except Exception:
            path_advantage = 0.0
    else:
        path_advantage = 0.0

    # 5. 决策
    registry = ProcessTemplateRegistry()
    applied = registry.get_applied_template(applied_id) if applied_id else None
    cons_pos = getattr(applied, "consecutive_positive", 0) if applied else 0
    cons_neg = getattr(applied, "consecutive_negative", 0) if applied else 0
    action = decide_learning_action(
        path_advantage=path_advantage,
        hard_gate_violation_count=len(all_violations),
        consecutive_positive=cons_pos,
        consecutive_negative=cons_neg,
    )

    # 6. 反哺：更新 path_advantage
    if applied_id and applied is not None:
        try:
            registry.update_path_advantage(applied_id, path_advantage, action["decision"])
        except Exception:
            pass

    # 7. 告警 / quarantine
    if action["decision"] in ("alert", "quarantine"):
        skill_id_for_alert = (
            session.recalled_processes[0].skill_id
            if session.recalled_processes else None
        )
        level = "Warning" if action["decision"] == "alert" else "Critical"
        try:
            send_cognitive_alert(
                condition=f"path_advantage {action['decision']}: {path_advantage:.2f}",
                level=level,
                context={
                    "session_id": session.id,
                    "applied_id": applied_id,
                    "path_advantage": round(path_advantage, 4),
                    "hard_gate_violations": all_violations,
                    "reason": action["reason"],
                },
                skill_id=skill_id_for_alert,
            )
        except Exception:
            pass

    # 8. 记录评测
    try:
        record_evaluation(sample, path_advantage=path_advantage, decision=action["decision"])
    except Exception:
        pass

    return {
        "path_advantage": path_advantage,
        "decision": action["decision"],
        "reason": action["reason"],
        "sample": sample,
    }


def post_hoc_verify(
    cle: CognitiveLoopEntry,
    session: CognitiveSession,
    solution_path: Dict[str, Any],
    new_memory_id: str,
):
    """
    事后校验: 对比recall建议 vs 实际行为，更新置信度。
    
    包含两层校验:
      1. 记忆校验：检查是否遵循了recall注入的经验
      2. 流程校验：检查是否遵循了Superpowers流程模板
    
    逻辑:
      遵循建议 + 成功 → 置信度上升
      遵循建议 + 失败 → 置信度下降
      未遵循 + 成功  → 新路径有价值，不降级旧建议
      未遵循 + 失败  → 旧建议更可信，置信度上升
    """
    success = solution_path["outcome"]["success"]
    files_touched = set(solution_path["approach"].get("files_touched", []))

    # === 1. 记忆校验 ===
    if session.recalled_memory_ids:
        for mem_id in session.recalled_memory_ids:
            try:
                # 检索记忆内容，判断是否被遵循
                results = cle.search(mem_id, top_k=1, tags=None)
                if not results:
                    continue

                mem_content = str(results[0].get("content", "")).lower()
                was_followed = _check_if_followed(mem_content, files_touched, session.action_chain)

                if was_followed and success:
                    # 遵循建议 + 成功 → 经验置信度上升
                    cle.verify(mem_id, success=True)
                elif was_followed and not success:
                    # 遵循建议 + 失败 → 经验置信度下降
                    cle.verify(mem_id, success=False)
                elif not was_followed and not success:
                    # 未遵循 + 失败 → 旧经验更可信
                    cle.verify(mem_id, success=True)
                # 未遵循 + 成功 → 不降级旧经验，新路径已记录
            except Exception:
                pass  # 静默失败

    # === 2. 流程校验（改造后用 verify_skill_followed，设计节 4.4）===
    meta_items = [i for i in getattr(session, "_meta_processes", [])
                  if i.kind == "meta" and i.meta is not None]
    if meta_items:
        try:
            from skill_verifier import verify_skill_followed
            verify_reports = {}
            for item in meta_items:
                report = verify_skill_followed(item.meta, session.action_chain)
                verify_reports[item.meta.skill_id] = report
                # 单 Skill 违反 HARD-GATE 时记录日志
                if report["gate_violations"]:
                    try:
                        cle.logger.warning(
                            "HARD-GATE 违反 %s: %s",
                            item.meta.skill_id, report["gate_violations"]
                        )
                    except Exception:
                        pass
            session._verify_reports = verify_reports  # 供 _deposit_applied_template 读取
        except Exception:
            pass


def _check_if_followed(
    mem_content: str,
    files_touched: set,
    action_chain: List[Dict[str, Any]],
) -> bool:
    """
    启发式判断AI是否遵循了某条建议。

    当前策略: 检查建议中提到的关键文件/关键词是否出现在行动链中。
    """
    # 从记忆内容中提取文件名
    import re
    file_patterns = re.findall(r'[\w_]+\.\w{1,4}', mem_content)

    for pattern in file_patterns:
        for f in files_touched:
            if pattern in f:
                return True

    # 检查行动链中是否有关键词匹配
    action_text = " ".join(str(a.get("detail", "")) for a in action_chain).lower()
    # 提取记忆中的关键词（前5个词）
    keywords = [w for w in mem_content.split() if len(w) > 3][:5]
    for kw in keywords:
        if kw in action_text:
            return True

    return False


# ============================================================
# 行动链 → 步骤 推断
# ============================================================

def _infer_steps_from_action_chain(
    action_chain: List[Dict[str, Any]],
    parent_template_id: Optional[str] = None,
) -> List[str]:
    """
    从行动链推断实际执行的步骤。

    策略：
      1. 若有 parent_template_id，先取元模板步骤作为候选
      2. 再根据行动链中的关键事件（文件变更类型、工具调用、commit）
         标注被实际执行的步骤
      3. 补齐一个"实际验证"的收尾步骤
    """
    base_steps: List[str] = []

    # 加载元模板步骤作为参考
    if parent_template_id:
        try:
            from cognitive_superpowers import ProcessTemplateRegistry
            registry = ProcessTemplateRegistry(auto_discover=False)
            meta = registry.get_meta(parent_template_id)
            if meta:
                base_steps = list(meta.steps)
        except Exception:
            pass

    # 分析行动链
    action_types = set(a.get("action_type", "") for a in action_chain)
    details_text = " ".join(str(a.get("detail", "")) for a in action_chain).lower()

    # 若没有元模板参考，根据行动链合成步骤
    if not base_steps:
        synthesized: List[str] = []
        if "file_change" in action_types:
            synthesized.append("识别问题并修改文件")
        if "tool_call" in action_types:
            synthesized.append("调用工具进行分析/实现")
        if "git_commit" in action_types:
            synthesized.append("验证并提交代码")
        if not synthesized:
            synthesized.append("执行任务")
        synthesized.append("回顾与沉淀")
        return synthesized

    # 基于元模板步骤，筛选出真正被执行的步骤
    executed: List[str] = []
    for step in base_steps:
        step_lower = step.lower()
        matched = False
        # 直接匹配
        if step_lower in details_text:
            matched = True
        # 同义词匹配
        if not matched:
            syn_map = {
                "写测试": ["test", "测试"],
                "写代码": ["实现", "实现"],
                "重构": ["refactor", "优化"],
                "调试": ["debug", "修复"],
                "复现": ["reproduce", "重现"],
                "定位": ["定位", "根因"],
                "修复": ["fix", "修复"],
                "验证": ["verify", "validate"],
            }
            for key, syns in syn_map.items():
                if key in step_lower and any(s in details_text for s in syns):
                    matched = True
                    break
        if matched:
            executed.append(step)

    # 至少返回一些步骤
    if not executed:
        executed = base_steps[:2] if len(base_steps) >= 2 else base_steps

    # 追加"验证/沉淀"作为通用收尾
    if "验证" not in " ".join(executed):
        executed.append("验证结果")

    return executed


# ============================================================
# 路径对比
# ============================================================

def find_similar_solutions(
    problem: str,
    cle: Optional[CognitiveLoopEntry] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    检索同一问题的不同解法，按置信度排序。
    """
    own_cle = False
    if cle is None:
        cle = get_cle()
        own_cle = True

    try:
        results = cle.search(problem, top_k=top_k, tags=["solution_path"])
        # 按置信度排序
        results.sort(
            key=lambda r: r.get("metadata", {}).get("confidence", 0),
            reverse=True,
        )
        return results
    finally:
        # 注意：不调用 cle.close()，get_cle() 返回进程级单例
        pass


# ============================================================
# 主入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="认知会话包裹器")
    parser.add_argument("--status", action="store_true", help="查看当前会话状态")
    parser.add_argument("--end", action="store_true", help="强制结束当前会话")
    parser.add_argument("--sessions", action="store_true", help="列出所有会话")
    args = parser.parse_args()

    mgr = CognitiveSessionManager()

    if args.status:
        if mgr.current_session:
            s = mgr.current_session
            print(f"当前会话: {s.id}")
            print(f"状态: {s.status}")
            print(f"任务类型: {s.task_type}")
            print(f"行动数: {len(s.action_chain)}")
            print(f"涉及文件: {len(s.files_touched)}")
            print(f"recall建议: {len(s.recalled_memory_ids)}条")
        else:
            print("无活跃会话")

    elif args.end:
        if mgr.current_session:
            mgr._end_session(timeout=True)
            print("会话已结束")
        else:
            print("无活跃会话")

    elif args.sessions:
        for d in sorted(mgr.sessions_dir.iterdir()):
            if d.is_dir():
                meta = d / "session.json"
                if meta.exists():
                    s = json.loads(meta.read_text())
                    print(f"  {s['id']} | {s.get('task_type','?')} | "
                          f"{s.get('action_count',0)}步 | {s.get('status','?')}")


if __name__ == "__main__":
    main()

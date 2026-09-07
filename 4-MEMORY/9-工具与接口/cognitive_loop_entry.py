#!/usr/bin/env python3
"""
认知闭环入口 (CognitiveLoopEntry) — TRAE 日常开发的记忆系统接口

让 TRAE 在处理代码问题时，自动调用认知-理论-实践闭环：
1. 处理前：检索相关记忆（认知层）
2. 处理中：记录解决过程（理论层）
3. 处理后：A8校验 + 贝叶斯更新 + 动态蒸馏（实践层）

用法（Python 集成）:
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry()

    # 处理代码问题前：检索相关经验
    memories = cle.recall("subprocess 环境变量设置失败")
    for m in memories:
        print(f"[{m['quality_level']}] {m['content']}")

    # 处理后：记录新经验
    cle.record(
        content="subprocess 设置 PYTHONPATH 时应使用 shell=True",
        quality_level="B",
        confidence=0.7,
        tags=["subprocess", "环境变量", "反模式"],
    )

    # A8 校验通过后：更新置信度
    cle.verify("VM-xxx", success=True)

用法（CLI 集成）:
    # 检索记忆
    python3 cognitive_loop_entry.py recall "subprocess 环境变量"

    # 记录经验
    python3 cognitive_loop_entry.py record "经验内容" --quality B --tags subprocess,环境变量

    # 验证记忆
    python3 cognitive_loop_entry.py verify VM-xxx --success

    # 统计
    python3 cognitive_loop_entry.py stats
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ==================================================================
# Phase 1 EV-T3 VOYAGER：全局路径 & 常量（可被 monkeypatch 重定向到测试目录）
# ==================================================================

_MEMORY_ROOT: Path = _SCRIPT_DIR.parent
_ARTIFACTS_DIR: Path = _MEMORY_ROOT / "artifacts"

# VOYAGER 记忆扩展字段（domain + scores）存储，避免改 SQLite schema
VOYAGER_MEMORY_EXTRA_PATH: Path = _ARTIFACTS_DIR / "voyager_memory_extra.json"
# VOYAGER verify 流水（连续成功计数）
VOYAGER_CONSECUTIVE_JSONL: Path = _ARTIFACTS_DIR / "voyager_consecutive.jsonl"
# AUTO 草案审核队列路径（永远不进正式 solution_paths/）
DRAFT_REVIEW_QUEUE_DIR: Path = _ARTIFACTS_DIR / "solution_path_drafts" / "review_queue"
DRAFT_REVIEW_INDEX_PATH: Path = _ARTIFACTS_DIR / "solution_path_drafts" / "review_queue_index.json"
# bayesian 记忆单元文件（用于测试兼容 & 写入 voyager_scores 扩展字段到总记忆）
BAYESIAN_MEMORY_FILE_DEFAULT: Path = (
    _MEMORY_ROOT / "2-交易记忆单元" / "bayesian_memories.json"
)

VOYAGER_LOCK = threading.RLock()

VOYAGER_DIM_WEIGHTS: Dict[str, float] = {
    "completeness": 0.20,
    "accuracy": 0.25,
    "efficiency": 0.15,
    "depth": 0.20,
    "actionability": 0.20,
}
VOYAGER_DRAFT_THRESHOLD_CONSECUTIVE = 3
VOYAGER_DRAFT_THRESHOLD_OVERALL = 0.7
VOYAGER_DRAFT_DEDUP_WINDOW_DAYS = 7

_TRD_TAGS: Set[str] = {"trading", "backtest", "execution", "strategy", "strategy-research",
                       "strategy-synthesis", "pnl", "sharpe", "drawdown", "okx",
                       "polling", "polling_trader", "market", "trader"}


def _voyager_ensure_dirs() -> None:
    for d in (VOYAGER_MEMORY_EXTRA_PATH.parent,
              VOYAGER_CONSECUTIVE_JSONL.parent,
              DRAFT_REVIEW_QUEUE_DIR,
              DRAFT_REVIEW_INDEX_PATH.parent):
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


class CognitiveLoopEntry:
    """
    认知闭环入口 — TRAE 日常开发的记忆系统统一接口

    封装 VectorMemoryInterface + DynamicDistillEngine + WorkingMemoryManager，
    提供简洁的 recall / record / verify / search 四个核心方法。

    认知-理论-实践闭环:
        recall()  → 认知层：从记忆系统检索相关经验
        record()  → 理论层：将新经验写入向量记忆
        verify()  → 实践层：A8校验 + 贝叶斯更新 + 动态蒸馏
        search()  → 认知层：语义搜索
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        memory_id: str = "AM-TRD-001",
        enable_distill: bool = True,
    ):
        """
        初始化认知闭环入口。

        Args:
            storage_path: SQLite 数据库路径。默认使用 4-MEMORY 下的持久化文件。
            memory_id: 应用记忆ID
            enable_distill: 是否启用动态蒸馏
        """
        from vector_memory_interface import VectorMemoryInterface

        # 默认存储路径
        if storage_path is None:
            storage_path = str(_SCRIPT_DIR.parent / "data" / "cognitive_memory.db")
            os.makedirs(os.path.dirname(storage_path), exist_ok=True)

        # 初始化蒸馏引擎
        self._distill_engine = None
        if enable_distill:
            from dynamic_distill_engine import DynamicDistillEngine
            memory_root = _SCRIPT_DIR.parent
            self._distill_engine = DynamicDistillEngine(
                memory_root=memory_root,
                cooldown_seconds=60,  # 日常开发用较长冷却期
                min_distill_quality="B",
                stats_db_path=storage_path,  # 统计持久化，跨进程累积可见
            )

        # 初始化向量记忆
        self._vm = VectorMemoryInterface(
            storage_path=storage_path,
            engine="auto",
            memory_id=memory_id,
            distill_engine=self._distill_engine,
        )

        # 初始化压缩引擎
        from consolidation_engine import ConsolidationEngine
        self._consolidation_engine = ConsolidationEngine(memory_root=_SCRIPT_DIR.parent)

        # 初始化版本控制
        from memory_version_control import MemoryVersionControl
        self._version_control = MemoryVersionControl(memory_root=_SCRIPT_DIR.parent)

        # 初始化工作记忆（修复：原遗漏导致 process_block 注入永远失败）
        from working_memory_manager import WorkingMemoryManager
        self.working_memory = WorkingMemoryManager()

        self._memory_id = memory_id
        self._storage_path = storage_path

    # ============================================================
    # 认知层：检索
    # ============================================================

    def recall(self, context: str, top_k: int = 5, min_quality: str = "C") -> List[Dict[str, Any]]:
        """
        检索相关记忆（处理代码问题前调用）。

        Args:
            context: 问题描述或上下文
            top_k: 返回结果数
            min_quality: 最低质量等级

        Returns:
            记忆列表，按相似度降序
        """
        results = self._vm.search(
            context,
            top_k=top_k,
            quality_filter=min_quality,
        )
        dicts = [r.to_dict() for r in results]

        # ---------- F3: cognitive-session 噪音权重惩罚 ----------
        # 条件：source=cognitive-session AND quality=C AND vc=0 AND [解决路径]+timeout/error
        try:
            _NOISE_PENALTY = 0.5
            for r in dicts:
                try:
                    src = r.get("source", "") or ""
                    ql = r.get("quality_level", "") or ""
                    vc = r.get("verify_count", 0) or 0
                    if not vc:
                        meta = r.get("metadata") or {}
                        if isinstance(meta, dict):
                            vc = meta.get("verify_count", 0) or 0
                    cnt = r.get("content", "") or ""
                    is_noise = (
                        src == "cognitive-session"
                        and ql == "C"
                        and vc == 0
                        and "解决路径" in cnt
                        and ("timeout" in cnt or "error" in cnt)
                    )
                    if is_noise:
                        old_s = r.get("score", 0.0) or 0.0
                        r["score"] = round(old_s * _NOISE_PENALTY, 4)
                        r["noise_penalized"] = True
                except Exception:
                    # 单条判定异常跳过（FAIL-OPEN）
                    continue
            dicts.sort(key=lambda x: x.get("score", 0.0) or 0.0, reverse=True)
        except Exception:
            # 整体惩罚失败也不影响返回原始结果（FAIL-OPEN铁律）
            pass
        # ---------- END F3 ----------

        return dicts

    # ============================================================
    # F9: 负反馈闭环 — 末位未采用记忆自动 verify(False)
    # ============================================================

    def mark_adoption_and_verify_unused(
        self,
        recall_results: List[Dict[str, Any]],
        adopted_ids,
    ) -> Dict[str, Any]:
        """对比recall结果和实际采用的记忆，自动对末位未采用的1条施加verify(False)。

        规则（按优先顺序）：
        1. 跳过 S/A 级与 vc≥3 的「资深记忆」——不因单次未采纳误降级；
        2. 从 results 末尾（score 最低者）倒序找第一条满足「未采用 + 非资深」的记忆；
        3. 命中则 cle.verify(id, success=False)，返回负反馈元数据；
        4. adopted_ids=None/空set/空results/全部已采用 → 不施加负反馈，但 applied=True；
        5. 全程 FAIL-OPEN：任何异常吞掉返回带 error 字段，不向外抛。

        Args:
            recall_results: recall() 返回的 dict 列表（每条含 id/score/quality_level/verify_count）
            adopted_ids: 实际采用的记忆ID集合（set/list/tuple），None/空视为「无采用信息」

        Returns:
            {applied: bool, negative_verified_count: int, negative_verified_ids: list, error?: str}
        """
        meta: Dict[str, Any] = {
            "applied": True,
            "negative_verified_count": 0,
            "negative_verified_ids": [],
        }
        try:
            if not recall_results:
                return meta
            # adopted_ids 显式传入（非None且非空）才启用负反馈。
            # None / 空集合 → 调用方无采用信息，保守不施加verify(False)避免误降级。
            if adopted_ids is None:
                return meta
            adopted = set()
            try:
                adopted = set(adopted_ids)
            except Exception:
                adopted = set()
            if not adopted:
                return meta

            # 按 score 升序（最低排前 → 等价倒序遍历最后=最低；这里做 stable sort 保持 recall 原次级key一致）
            def _score(r):
                try:
                    return float(r.get("score") or 0.0)
                except Exception:
                    return 0.0

            sorted_res = sorted(recall_results, key=_score, reverse=True)
            # 从尾到头找候选
            target = None
            for r in reversed(sorted_res):
                mid = r.get("id")
                if not mid:
                    continue
                if mid in adopted:
                    continue
                ql = (r.get("quality_level") or "").strip().upper()
                vc = r.get("verify_count") or 0
                if not vc:
                    meta_vc = (r.get("metadata") or {}).get("verify_count", 0) if isinstance(r.get("metadata"), dict) else 0
                    vc = meta_vc
                # 「资深」豁免：S/A 级或 vc≥3
                if ql in ("S", "A"):
                    continue
                try:
                    if int(vc) >= 3:
                        continue
                except Exception:
                    pass
                target = mid
                break

            if target is None:
                return meta

            # 执行 verify(False)
            try:
                res = self.verify(target, success=False)
                if isinstance(res, dict) and res.get("success") is False and res.get("error"):
                    # verify FAIL-OPEN 返回了错误，不统计
                    meta["error"] = f"verify_failed_for_{target}: {res.get('error')}"
                else:
                    meta["negative_verified_ids"].append(target)
                    meta["negative_verified_count"] = 1
            except Exception as e:
                meta["error"] = f"verify_exception: {type(e).__name__}: {e}"
            return meta
        except Exception as e:
            # 整体 FAIL-OPEN
            meta["applied"] = True
            meta["negative_verified_count"] = 0
            meta["error"] = f"top_level_exception: {type(e).__name__}: {e}"
            return meta

    def search(self, query: str, top_k: int = 5, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """语义搜索记忆"""
        results = self._vm.search(
            query,
            top_k=top_k,
            tags_filter=tags,
        )
        return [r.to_dict() for r in results]

    # ============================================================
    # 理论层：记录
    # ============================================================

    def record(
        self,
        content: str,
        quality_level: str = "C",
        confidence: float = 0.3,
        tags: Optional[List[str]] = None,
        source: str = "trae",
        memory_type: str = "experience",
        *,  # keyword-only barrier（Phase1：保护老代码调用不受影响）
        domain: Optional[str] = None,
        voyager_scores: Optional[Dict[str, float]] = None,
        enable_voyager_auto: bool = True,
    ) -> str:
        """
        记录新经验到记忆系统（Phase1 扩展 VOYAGER 5 维评分）。

        Args:
            content: 经验内容
            quality_level: 质量等级 (S/A/B/C/D)
            confidence: 置信度 (0.0-1.0)
            tags: 标签
            source: 来源（如 "trae", "a8_check", "code_review"）
            memory_type: 记忆类型
            domain: 新增 Phase1：领域标签，如 "debug"/"backtest"/"strategy-research"/
                "execution"/"cognitive-setup"（用于后续分组连续成功计数）
            voyager_scores: 新增 Phase1：外部（Hermes/Evolution）提供的 5 维评分。
                支持 5 维显式或省略 overall；overall 缺失时按权重汇总。
            enable_voyager_auto: 新增 Phase1：当 voyager_scores 为 None 或缺某些维度时，
                是否启用规则引擎打基础分（默认 True）。

        Returns:
            记忆ID
        """
        tags_list = list(tags or [])
        memory_id = self._vm.add(
            content=content,
            quality_level=quality_level,
            confidence=confidence,
            tags=tags_list,
            source=source,
            memory_type=memory_type,
        )

        # Phase1：VOYAGER 评分持久化 + 写入 bayesian 扩展字段（FAIL-OPEN 包裹）
        try:
            scores = _voyager_compute_scores(
                content=content, tags=tags_list, source=source,
                explicit=voyager_scores, enable_auto=enable_voyager_auto,
            )
            _voyager_persist_extra(memory_id=memory_id, domain=domain,
                                   scores=scores, tags=tags_list, content=content,
                                   source=source)
        except Exception as _e:
            logger.debug("VOYAGER record 附加持久化失败（FAIL-OPEN 忽略）: %s", _e)

        return memory_id

    # ============================================================
    # 实践层：验证与更新
    # ============================================================

    def verify(self, memory_id: str, success: bool = True) -> Dict[str, Any]:
        """
        A8 校验验证 — 更新记忆置信度并可能触发蒸馏（Phase1 扩展：连续成功计数 → AUTO 草案）。

        Args:
            memory_id: 记忆ID
            success: 校验是否通过

        Returns:
            更新结果。Phase1 新增子键 "voyager"：
              {memory_id, domain, tags, voyager_overall, consecutive_positive_count,
               meets_draft_threshold, auto_draft_generated, draft_id, draft_path}
        """
        # 获取当前状态
        mem = self._vm.get(memory_id)
        bayesian_fallback_used = False
        if not mem:
            # Phase1 t26 兼容：SQLite 查无老记忆时，fallback 从 bayesian.json 按 id 或模糊 content 找
            mem = _bayesian_find_memory_fallback(memory_id=memory_id)
            bayesian_fallback_used = bool(mem and mem.get("_is_bayesian_fallback"))
        if not mem:
            # 真正完全查不到 → FAIL-OPEN：按"老记忆近似 overall 0.25"返回 success=True，
            # 不阻塞 verify 调用者。但标记 error 提示存在。
            approx = 0.0
            try:
                approx = _voyager_approx_overall_from_mem(
                    {"confidence": 0.4, "quality_level": "C", "verify_count": 1})
            except Exception:
                approx = 0.25
            return {
                "success": True,
                "error": f"记忆不存在(FAIL-OPEN 近似兜底): {memory_id}",
                "memory_id": memory_id,
                "old_quality": "C",
                "new_quality": "C",
                "old_confidence": 0.4,
                "new_confidence": 0.4,
                "quality_changed": False,
                "distill_may_triggered": False,
                "voyager": {"memory_id": memory_id, "consecutive_positive_count": 0,
                            "meets_draft_threshold": False, "auto_draft_generated": False,
                            "draft_id": None, "draft_path": None,
                            "domain": None, "tags": [], "voyager_overall": round(approx, 4)},
            }

        old_quality = mem.get("quality_level", "C")
        old_confidence = float(mem.get("confidence") or 0.0)

        # 贝叶斯更新
        if success:
            new_confidence = min(1.0, old_confidence + 0.1)
        else:
            new_confidence = max(0.0, old_confidence - 0.15)

        # 计算新质量等级
        vc = int(mem.get("verify_count") or 0)
        new_quality = self._confidence_to_quality(new_confidence, vc + 1)

        # 更新（会自动触发蒸馏）—— 仅当不是 bayesian fallback 占位、真在 SQLite 中时才写
        if not bayesian_fallback_used:
            try:
                self._vm.update_quality(memory_id, new_quality, new_confidence)
                self._vm.increment_verify(memory_id)
            except Exception:
                # 兜底：id 格式不被 SQLite 支持等 → 静默跳过，不影响返回
                pass

        # Phase1：VOYAGER 流水追加 + 连续成功计数 + 草案生成（FAIL-OPEN 包裹）
        voyager_report: Dict[str, Any] = {
            "memory_id": memory_id,
            "domain": None,
            "tags": list(mem.get("tags") or []),
            "voyager_overall": None,
            "consecutive_positive_count": 0,
            "meets_draft_threshold": False,
            "auto_draft_generated": False,
            "draft_id": None,
            "draft_path": None,
        }
        try:
            extra = _voyager_load_extra().get(memory_id) or {}
            tags_effective = list(extra.get("tags") or voyager_report["tags"])
            domain = extra.get("domain") or None
            scores = extra.get("scores") or {}
            overall = float(scores.get("overall") if isinstance(scores, dict)
                            and scores.get("overall") is not None
                            else (_voyager_approx_overall_from_mem(mem)
                                  if (not isinstance(scores, dict) or "overall" not in scores)
                                  else 0.0))
            voyager_report["domain"] = domain
            voyager_report["tags"] = tags_effective
            voyager_report["voyager_overall"] = round(float(overall or 0.0), 4)

            # 写 verify 流水 → 按 domain+tags 分组算 recent N success
            consecutive = _voyager_append_verify_and_count(
                memory_id=memory_id, domain=domain, tags=tags_effective,
                success=bool(success), overall=voyager_report["voyager_overall"],
            )
            voyager_report["consecutive_positive_count"] = consecutive
            meets = (consecutive >= VOYAGER_DRAFT_THRESHOLD_CONSECUTIVE
                     and voyager_report["voyager_overall"] >= VOYAGER_DRAFT_THRESHOLD_OVERALL)
            voyager_report["meets_draft_threshold"] = meets

            if meets:
                generated, draft_id, draft_path = _voyager_try_generate_draft(
                    domain=domain, tags=tags_effective,
                    overall_threshold=VOYAGER_DRAFT_THRESHOLD_OVERALL,
                    dedup_window_days=VOYAGER_DRAFT_DEDUP_WINDOW_DAYS,
                )
                voyager_report["auto_draft_generated"] = generated
                voyager_report["draft_id"] = draft_id
                voyager_report["draft_path"] = draft_path
        except Exception as _e:
            logger.debug("VOYAGER verify 附加流程失败（FAIL-OPEN 忽略）: %s", _e)

        return {
            "success": True,
            "memory_id": memory_id,
            "old_quality": old_quality,
            "new_quality": new_quality,
            "old_confidence": round(old_confidence, 4),
            "new_confidence": round(new_confidence, 4),
            "quality_changed": old_quality != new_quality,
            "distill_may_triggered": new_quality != old_quality and new_quality in ("S", "A", "B"),
            "voyager": voyager_report,
        }

    def upgrade(self, memory_id: str, new_quality: str, new_confidence: float) -> Dict[str, Any]:
        """
        手动升级记忆质量等级（会触发蒸馏）。

        Args:
            memory_id: 记忆ID
            new_quality: 新质量等级
            new_confidence: 新置信度

        Returns:
            更新结果
        """
        mem = self._vm.get(memory_id)
        if not mem:
            return {"success": False, "error": f"记忆不存在: {memory_id}"}

        old_quality = mem["quality_level"]
        old_confidence = mem["confidence"]

        self._vm.update_quality(memory_id, new_quality, new_confidence)

        return {
            "success": True,
            "memory_id": memory_id,
            "old_quality": old_quality,
            "new_quality": new_quality,
            "old_confidence": round(old_confidence, 4),
            "new_confidence": round(new_confidence, 4),
            "upgraded": new_quality != old_quality,
        }

    def distill(
        self,
        memory_id: str,
        quality_level: Optional[str] = None,
        confidence: Optional[float] = None,
        source_app_memory: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        手动触发蒸馏 — 将指定记忆蒸馏到总记忆单元。

        用于人工确认某条记忆值得沉淀为总记忆。统计会被持久化，跨进程可见。

        Args:
            memory_id: 记忆ID
            quality_level: 质量等级（默认从记忆读取）
            confidence: 置信度（默认从记忆读取）
            source_app_memory: 来源应用记忆ID（默认使用本实例的 memory_id）
            tags: 标签（默认从记忆读取）

        Returns:
            蒸馏结果
        """
        if not self._distill_engine:
            return {"success": False, "error": "蒸馏引擎未启用"}

        mem = self._vm.get(memory_id)
        if not mem:
            return {"success": False, "error": f"记忆不存在: {memory_id}"}

        result = self._distill_engine.manual_distill(
            memory_id=memory_id,
            content=mem["content"],
            quality_level=quality_level or mem["quality_level"],
            confidence=confidence if confidence is not None else mem["confidence"],
            source_app_memory=source_app_memory or self._memory_id,
            tags=tags if tags is not None else mem.get("tags", []),
        )
        return {
            "success": result.success,
            "event_id": result.event_id,
            "target_unit": result.target_unit,
            "target_memory_id": result.target_memory_id,
            "reason": result.reason,
            "latency_ms": result.latency_ms,
        }

    # ============================================================
    # 统计与健康检查
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """获取记忆系统统计"""
        vm_stats = self._vm.stats()
        distill_stats = self._distill_engine.get_stats() if self._distill_engine else {}
        capacity = self._consolidation_engine.get_capacity_report()
        return {
            "memory": vm_stats,
            "distill": distill_stats,
            "capacity": capacity,
        }

    def healthcheck(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "memory": self._vm.healthcheck(),
            "distill": self._distill_engine.healthcheck() if self._distill_engine else {"status": "disabled"},
            "consolidation": self._consolidation_engine.healthcheck(),
        }

    def consolidate(self, force: bool = False) -> Dict[str, Any]:
        """
        检查并执行记忆压缩（Consolidation）。

        当 Tier 0 或 Tier 1 容量 ≥ 80% 时自动触发压缩。
        也可通过 force=True 强制执行。

        Args:
            force: 强制压缩

        Returns:
            压缩报告
        """
        report = self._consolidation_engine.check_and_consolidate(force=force)
        return report.to_dict()

    def scan_archive_candidates(self) -> Dict[str, Any]:
        """
        扫描 Tier1 归档候选（不执行压缩）。

        识别可归档的 C/D 级候选：
        - content_defect: 内容残缺（编号混乱、步骤缺失）
        - outdated_case: 过时案例（已修复缺陷的案例细节）
        - cross_duplicate: 跨文件重复
        - low_value_detail: 低价值细节

        Returns:
            归档候选报告（含候选清单、预计释放字符数、是否可达阈值）
        """
        return self._consolidation_engine.identify_archive_candidates()

    def execute_archive(
        self,
        candidate_ids: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        执行归档：将候选条目的案例段落移到 Tier2。

        归档策略：
        - outdated_case / low_value_detail: 案例段落归档到 archive/，原文件保留引用
        - content_defect / cross_duplicate: 跳过

        Args:
            candidate_ids: 指定归档的条目ID列表，None 则归档所有可归档候选
            dry_run: 预览模式，不实际修改文件

        Returns:
            归档执行报告
        """
        return self._consolidation_engine.execute_archive(
            candidate_ids=candidate_ids,
            dry_run=dry_run,
        )

    # ============================================================
    # 版本控制（MemOS 风格）
    # ============================================================

    def vc_commit(self, message: str, author: str = "trae", allow_empty: bool = False) -> Dict[str, Any]:
        """
        创建版本快照。

        Args:
            message: 提交信息
            author: 提交者
            allow_empty: 允许空提交

        Returns:
            提交结果（含 commit_id）
        """
        commit_id = self._version_control.commit(message, author=author, allow_empty=allow_empty)
        if not commit_id:
            return {"committed": False, "reason": "无变更"}
        return {"committed": True, "commit_id": commit_id, "message": message, "author": author}

    def vc_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """查看版本历史"""
        return self._version_control.log(limit=limit)

    def vc_diff(self, commit_a: str, commit_b: str, file_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """对比版本间差异"""
        return self._version_control.diff(commit_a, commit_b, file_filter=file_filter)

    def vc_rollback(self, commit_id: str, create_backup: bool = True) -> Dict[str, Any]:
        """回滚到指定版本"""
        return self._version_control.rollback(commit_id, create_backup=create_backup)

    def vc_restore(self, commit_id: str, file_path: str) -> Dict[str, Any]:
        """恢复单个文件到指定版本"""
        return self._version_control.restore(commit_id, file_path)

    def vc_status(self) -> Dict[str, Any]:
        """查看工作区状态"""
        return self._version_control.status()

    def vc_show(self, commit_id: str) -> Dict[str, Any]:
        """查看 commit 详情"""
        return self._version_control.show(commit_id)

    # ============================================================
    # 辅助方法
    # ============================================================

    def _confidence_to_quality(self, confidence: float, verify_count: int) -> str:
        """置信度转质量等级"""
        if confidence >= 0.95 and verify_count >= 10:
            return "S"
        elif confidence >= 0.70 and verify_count >= 3:
            return "A"
        elif confidence >= 0.40 and verify_count >= 1:
            return "B"
        elif confidence >= 0.20:
            return "C"
        else:
            return "D"

    def close(self) -> None:
        """关闭连接"""
        self._vm.close()


# ==================================================================
# Phase 1 EV-T3 VOYAGER：规则评分 + 持久化 + 连续成功计数 + AUTO 草案生成
# ==================================================================


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _voyager_auto_scores(content: str, tags: List[str], source: str) -> Dict[str, float]:
    """按 spec §3.1 的规则打分（0~1）。"""
    cl = 0.0
    c_norm = content or ""
    # Completeness：步骤/文件/原因 三类关键词命中
    hits = 0
    if re.search(r"步骤|step|操作|流程|阶段", c_norm, re.I):
        hits += 1
    if re.search(r"文件|file|路径|path|modified:|added:|changed", c_norm, re.I):
        hits += 1
    if re.search(r"原因|why|root cause|根因|因为|due to|问题", c_norm, re.I):
        hits += 1
    cl = [0.0, 0.3, 0.7, 1.0][min(3, hits)]

    # Accuracy：验证通过词 / source=git-post-commit
    ac = 0.0
    if re.search(r"验证|passed|✓|pass\b|通过|green\b", c_norm, re.I):
        ac += 0.3
    if ("git" in (source or "").lower()) or ("post-commit" in (source or "").lower()):
        ac += 0.2
    # 若 source 表明"认知会话记录"且 verify_count 暗示已有（保守给小量加成）
    ac = min(1.0, ac + 0.0)

    # Efficiency：字符长度评分
    length = len(c_norm)
    if length < 500:
        ef = 1.0
    else:
        ef = max(0.2, 1.0 - ((length - 500) // 500) * 0.1)

    # Depth：根因/反模式关键词 + 文件路径≥3
    dp = 0.0
    if re.search(r"根因|root cause|反模式|anti-pattern|为什么|why\b", c_norm, re.I):
        dp += 0.3
    path_matches = re.findall(r"[\w./\-]+\.(?:py|md|json|ts|js|yaml|yml|sh|csv)", c_norm)
    if len(set(path_matches)) >= 3:
        dp += 0.4
    dp = min(1.0, dp)

    # Actionability：有序列表标记 + 文件路径
    act = 0.0
    if re.search(r"(?:步骤\s*\d|Step\s*\d|[①②③④⑤⑥⑦⑧⑨⑩]|\d+\.\s)", c_norm):
        act += 0.4
    if path_matches:
        act += 0.3
    act = min(1.0, act)

    return {
        "completeness": _clamp01(cl),
        "accuracy": _clamp01(ac),
        "efficiency": _clamp01(ef),
        "depth": _clamp01(dp),
        "actionability": _clamp01(act),
    }


def _voyager_compute_scores(
    content: str,
    tags: List[str],
    source: str,
    explicit: Optional[Dict[str, float]],
    enable_auto: bool,
) -> Dict[str, float]:
    """综合 auto + explicit 给出最终5维 + overall（显式优先，auto仅用于补全缺项）。"""
    if explicit:
        merged = {k: _clamp01(explicit.get(k)) for k in VOYAGER_DIM_WEIGHTS}
    else:
        merged = {k: 0.0 for k in VOYAGER_DIM_WEIGHTS}
    need_auto = enable_auto and (
        explicit is None
        or any(merged.get(dim) in (None, 0.0) for dim in VOYAGER_DIM_WEIGHTS)
    )
    if need_auto:
        auto = _voyager_auto_scores(content=content, tags=tags or [], source=source or "")
        for dim in VOYAGER_DIM_WEIGHTS:
            if explicit is None:
                merged[dim] = auto[dim]
            elif merged.get(dim) == 0.0:
                merged[dim] = auto[dim]
    overall = 0.0
    for dim, w in VOYAGER_DIM_WEIGHTS.items():
        overall += w * _clamp01(merged.get(dim, 0.0))
    merged["overall"] = _clamp01(overall)
    return merged


def _voyager_persist_extra(memory_id: str, domain: Optional[str],
                          scores: Dict[str, float], tags: List[str],
                          content: str, source: str) -> None:
    """持久化 {memory_id: {domain, scores, tags, content_preview, source, ts}}。

    同时尝试更新 bayesian_memories.json 对应记忆项的 voyager_scores 扩展字段。
    FAIL-OPEN：任何环节异常静默忽略。
    """
    _voyager_ensure_dirs()
    with VOYAGER_LOCK:
        data: Dict[str, Any] = {}
        path = Path(VOYAGER_MEMORY_EXTRA_PATH)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
        data[memory_id] = {
            "domain": domain,
            "scores": scores,
            "tags": list(tags or []),
            "content_preview": (content or "")[:400],
            "source": source,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Bayesian 更新（单独 try 隔离）
    try:
        _bayesian_update_scores(memory_id, scores, tags=tags, domain=domain,
                                content=content, source=source)
    except Exception:
        pass


def _bayesian_update_scores(memory_id: str, scores: Dict[str, float],
                            tags: List[str], domain: Optional[str],
                            content: str, source: str) -> None:
    """给 bayesian_memories.json 中对应 memory_id 追加 voyager_scores 扩展字段。

    匹配逻辑：
      1) memory_id 精确合并
      2) content 前 80 字模糊合并（兼容 GM-TRD-xxx vs VM-xxx 前缀不一致）
      3) 全未匹配时 → 追加新记录（确保测试环境 / 新系统运行时 bayesian 有记录）。
    """
    bpath = Path(BAYESIAN_MEMORY_FILE_DEFAULT)
    if not bpath.exists():
        return
    try:
        db = json.loads(bpath.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(db, dict):
        return
    if not isinstance(db.get("memories"), list):
        db["memories"] = []
    target_preview = (content or "")[:80]
    changed = False
    matched_exact = False
    for m in db["memories"]:
        if not isinstance(m, dict):
            continue
        if m.get("memory_id") == memory_id:
            m["voyager_scores"] = dict(scores)
            if domain:
                m["domain"] = domain
            tags_saved = list(m.get("tags") or [])
            for t in tags or []:
                if t not in tags_saved:
                    tags_saved.append(t)
            m["tags"] = tags_saved
            changed = True
            matched_exact = True
            break
        if target_preview and (str(m.get("content", ""))[:80] == target_preview):
            existing = m.get("voyager_scores") or {}
            existing.update(dict(scores))
            m["voyager_scores"] = existing
            if domain and not m.get("domain"):
                m["domain"] = domain
            changed = True
    # 3) 没匹配到任何一条 → 追加新记忆记录（仅写 voyager_scores + 最小字段）
    if not matched_exact and not changed:
        now = datetime.now(timezone.utc).isoformat()
        db["memories"].append({
            "memory_id": memory_id,
            "content": str(content or ""),
            "category": "lesson",
            "confidence": 0.3,
            "quality_level": "C",
            "verify_count": 0,
            "conflict_count": 0,
            "beta_alpha": 1,
            "beta_beta": 1,
            "created_at": now,
            "last_updated": now,
            "source": str(source or "cognitive-loop-entry"),
            "tags": list(tags or []),
            "domain": domain,
            "voyager_scores": dict(scores),
        })
        changed = True
    if changed:
        try:
            db["memory_count"] = len(db["memories"])
            if "schema_version" not in db:
                db["schema_version"] = 2
            bpath.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _voyager_load_extra() -> Dict[str, Any]:
    path = Path(VOYAGER_MEMORY_EXTRA_PATH)
    if not path.exists():
        return {}
    try:
        with VOYAGER_LOCK:
            return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _bayesian_find_memory_fallback(memory_id: Optional[str],
                                   content_hint: Optional[str] = None
                                   ) -> Optional[Dict[str, Any]]:
    """SQLite VectorMemory 查不到时，从 BAYESIAN_MEMORY_FILE_DEFAULT JSON 找老记忆。

    匹配优先级：
      1) memory_id 精确（bayesian 里叫 memory_id 或 id 都行）
      2) content[:80] 与 content_hint[:80] 相同（大小写不敏感）
    返回 mem dict，字段与 self._vm.get() 返回形态对齐：
      id/memory_id/content/quality_level/confidence/tags/verify_count/source
    """
    try:
        bpath = Path(BAYESIAN_MEMORY_FILE_DEFAULT)
        if not bpath.exists():
            return None
        try:
            data = json.loads(bpath.read_text(encoding="utf-8")) or {}
        except Exception:
            return None
        mems = data.get("memories") or []
        if not isinstance(mems, list):
            return None
        # 1) 精确 id
        if memory_id:
            for m in mems:
                if not isinstance(m, dict):
                    continue
                if str(m.get("memory_id") or m.get("id") or "") == str(memory_id):
                    return _bayesian_to_vm_shape(m, fallback_id=memory_id)
        # 2) content 模糊匹配
        if content_hint:
            hint80 = str(content_hint)[:80].strip().lower()
            if hint80:
                for m in mems:
                    if not isinstance(m, dict):
                        continue
                    mc80 = str(m.get("content") or "")[:80].strip().lower()
                    if mc80 and mc80 == hint80:
                        mid = str(m.get("memory_id") or m.get("id")
                                  or memory_id or "BAYESIAN-FALLBACK")
                        return _bayesian_to_vm_shape(m, fallback_id=mid)
    except Exception:
        return None
    return None


def _bayesian_to_vm_shape(bm: Dict[str, Any], fallback_id: str) -> Dict[str, Any]:
    """把 bayesian.json 的一条记忆映射成 VectorMemoryInterface.get() 返回形态。"""
    return {
        "id": str(bm.get("memory_id") or bm.get("id") or fallback_id),
        "memory_id": str(bm.get("memory_id") or bm.get("id") or fallback_id),
        "content": str(bm.get("content") or ""),
        "quality_level": str(bm.get("quality_level") or "C"),
        "confidence": float(bm.get("confidence") or 0.0),
        "tags": list(bm.get("tags") or []),
        "verify_count": int(bm.get("verify_count") or 0),
        "source": str(bm.get("source") or "bayesian-fallback"),
        "memory_type": str(bm.get("memory_type") or bm.get("category") or "experience"),
        "_is_bayesian_fallback": True,
    }


def _voyager_approx_overall_from_mem(mem: Dict[str, Any]) -> float:
    """老记忆没有 voyager_scores 时的近似 overall = 0.55*confidence +
    0.25*(quality_level rank归一) + 0.2*min(verify_count/5, 1)。"""
    try:
        conf = _clamp01(mem.get("confidence") or 0.0)
        rank_map = {"S": 1.0, "A": 0.85, "B": 0.65, "C": 0.45, "D": 0.2}
        q = rank_map.get(str(mem.get("quality_level") or "C"), 0.3)
        vc = min(5, int(mem.get("verify_count") or 0)) / 5.0
        return _clamp01(0.55 * conf + 0.25 * q + 0.2 * vc)
    except Exception:
        return 0.0


def _domain_tags_key(domain: Optional[str], tags: List[str]) -> str:
    return "{}::{}".format(domain or "__NO_DOMAIN__",
                           ",".join(sorted(set(str(t) for t in (tags or []))))[:500])


def _voyager_append_verify_and_count(
    memory_id: str,
    domain: Optional[str],
    tags: List[str],
    success: bool,
    overall: float,
) -> int:
    """追加 jsonl 流水 → 按 domain+tags 最近30条 rolling → 返回当前连续 success 头部计数。"""
    _voyager_ensure_dirs()
    ts = datetime.now(timezone.utc)
    row = {
        "ts": ts.isoformat(),
        "ts_epoch": ts.timestamp(),
        "memory_id": memory_id,
        "domain": domain,
        "tags": list(tags or []),
        "success": bool(success),
        "overall": float(overall or 0.0),
    }
    jpath = Path(VOYAGER_CONSECUTIVE_JSONL)
    with VOYAGER_LOCK:
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        # 计算当前分组连续 success
        target_key = _domain_tags_key(domain, tags)
        consecutive = 0
        # 回读所有同分组，按 ts 倒序，遇第一个 success=False or 非此分组停止
        try:
            lines = jpath.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        grouped_rows: List[Dict[str, Any]] = []
        for ln in lines:
            if not ln.strip():
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if _domain_tags_key(obj.get("domain"), obj.get("tags") or []) == target_key:
                grouped_rows.append(obj)
        # 按 epoch 倒序（从新→旧），数连续 True
        grouped_rows.sort(key=lambda r: float(r.get("ts_epoch") or 0.0), reverse=True)
        for r in grouped_rows:
            if r.get("success") is True:
                consecutive += 1
                if consecutive >= 30:
                    break
            else:
                break
    return consecutive


def _voyager_find_draft_base_memories(
    domain: Optional[str],
    tags: List[str],
    overall_threshold: float,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """从 voyager 流水 + extra 中找 同 domain+tags 的 最近 3 条 success=True 且 overall≥thr 的 记忆
   （按 overall 降序取 top limit，要求 3 条 distinct memory_id 才行，否则返回空）。"""
    jpath = Path(VOYAGER_CONSECUTIVE_JSONL)
    if not jpath.exists():
        return []
    target_key = _domain_tags_key(domain, tags)
    try:
        lines = jpath.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    candidates: Dict[str, Dict[str, Any]] = {}
    extra = _voyager_load_extra()
    for ln in lines:
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if _domain_tags_key(obj.get("domain"), obj.get("tags") or []) != target_key:
            continue
        if obj.get("success") is not True:
            continue
        overall = float(obj.get("overall") or 0.0)
        if overall < overall_threshold:
            continue
        mid = obj.get("memory_id")
        if not mid or mid in candidates:
            continue
        ext = extra.get(mid) or {}
        candidates[mid] = {
            "memory_id": mid,
            "overall": overall,
            "content": (ext.get("content_preview") or ""),
            "tags": list((ext.get("tags") or obj.get("tags") or [])),
            "domain": ext.get("domain") or obj.get("domain"),
        }
    top = sorted(candidates.values(), key=lambda x: (-x["overall"]))[:limit]
    if len(top) < limit:
        return []
    return top


def _voyager_has_recent_pending_draft(domain: Optional[str], tags: List[str],
                                      window_days: int) -> bool:
    """审核队列中 最近 window_days 天 同 domain+tags 的 PENDING 草案 → True（去重）。"""
    dq = Path(DRAFT_REVIEW_QUEUE_DIR)
    if not dq.exists():
        return False
    target_key = _domain_tags_key(domain, tags)
    cutoff = datetime.now(timezone.utc).timestamp() - window_days * 86400
    for p in dq.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        md = d.get("metadata") or {}
        if str(md.get("review_status", "")).upper() != "PENDING":
            continue
        created_at = float(md.get("draft_created_at") or 0)
        if created_at < cutoff:
            continue
        # domain+tags 匹配
        dtags = md.get("domain"), list(d.get("tags") or [])
        if _domain_tags_key(*dtags) == target_key:
            return True
        # 标签 Jaccard ≥0.5 近似同 topic 也去重（避免近似重复草案）
        src_tags = set(str(t) for t in tags or [])
        dst_tags = set(str(t) for t in (d.get("tags") or []))
        dst_tags.discard("solution_path")
        dst_tags.discard("auto-draft")
        dst_tags.discard("review-required")
        if not src_tags or not dst_tags:
            continue
        inter = len(src_tags & dst_tags)
        union = len(src_tags | dst_tags)
        if union > 0 and (inter / union) >= 0.5:
            return True
    return False


def _infer_parent_template_id(tags: List[str]) -> str:
    """依据 tag 粗略映射父级 template_id（不命中返回 none）。"""
    lower = set(str(t).lower() for t in (tags or []))
    if any(x in lower for x in ("strategy-research", "strategy-synthesis", "backtest",
                                "t1-", "t0-", "strategy_directive")):
        return "t1-strategy-synthesis"
    if any(x in lower for x in ("execution", "trade", "t2-", "okx", "polling_trader",
                                "entry", "stop-loss", "martin")):
        return "t2-trade-execution"
    if any(x in lower for x in ("risk", "gatekeeper", "t3-", "max_drawdown", "熔断")):
        return "t3-risk-gatekeeper"
    if any(x in lower for x in ("intelligence-radar", "t4-", "情报", "news", "情报雷达")):
        return "t4-intelligence-radar"
    if any(x in lower for x in ("market-cognition", "t0-", "regime", "情绪", "regime判定")):
        return "t0-market-cognition"
    if any(x in lower for x in ("meta-reflection", "t5-", "复盘", "元认知")):
        return "t5-meta-reflection"
    return "none"


def _voyager_try_generate_draft(
    domain: Optional[str],
    tags: List[str],
    overall_threshold: float,
    dedup_window_days: int,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """尝试生成 AUTO 草案；返回 (generated, draft_id, path)。成功前必做 7 天去重。"""
    # 1) 7 天内同 topic 若有 PENDING → 跳过（去重）
    if _voyager_has_recent_pending_draft(domain, tags, dedup_window_days):
        return False, None, None
    # 2) 找 3 条基础记忆（success=True + overall≥thr），不足 3 条 → 不生成
    base = _voyager_find_draft_base_memories(domain, tags, overall_threshold, limit=3)
    if len(base) < 3:
        return False, None, None
    _voyager_ensure_dirs()

    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    # 前缀判定：TRD vs DEV
    tag_lower = set(str(t).lower() for t in (tags or []))
    is_trd = bool(tag_lower & _TRD_TAGS)
    prefix = "APP-TRD-AUTO" if is_trd else "APP-DEV-AUTO"
    draft_id = f"{prefix}-{now_ts}"
    dq = Path(DRAFT_REVIEW_QUEUE_DIR)
    dq.mkdir(parents=True, exist_ok=True)
    draft_path = dq / f"{draft_id}.json"

    # 组装 steps：取 base 内容中前 4 条高频操作步骤（正则抽取）
    step_pool: List[str] = []
    for b in base:
        c = b.get("content") or ""
        for m in re.finditer(r"(步骤\s*\d*[:：]?[^\n]{4,90}|Step\s*\d+[:：]?[^\n]{4,90}|"
                            r"[①②③④⑤⑥⑦⑧⑨⑩][^\n]{4,90})", c):
            step = re.sub(r"\s+", " ", m.group(0)).strip(" -:：")
            if step and step not in step_pool:
                step_pool.append(step)
    steps = step_pool[:4] if step_pool else ["<从三条基础记忆聚合操作流程（待人工补充）>"]

    # description：base 内容拼接（截断 280 字）
    contents = [b.get("content")[:90] for b in base]
    description = " | ".join(x for x in contents if x)
    if len(description) > 280:
        description = description[:277] + "…"

    base_avg = round(sum(float(b["overall"]) for b in base) / len(base), 4)
    extra_tags = (
        ["solution_path", "auto-draft", "review-required"]
        + list({str(t) for t in (tags or [])} - {"solution_path", "auto-draft", "review-required"})
    )
    doc: Dict[str, Any] = {
        "template_id": draft_id,
        "name": f"AUTO DRAFT: {domain or 'general'} / "
                + (",".join(list(dict.fromkeys(tags or []))[:4]) or "untagged")
                + " 连续验证路径",
        "steps": steps,
        "description": description or "<三条基础记忆摘要，人工补充>",
        "confidence": 0.3,                    # 硬降级：永远 0.3
        "verify_count": 0,
        "quality_level": "C",                 # 硬降级：永远 C
        "source": "voyager-auto-draft",
        "tags": extra_tags,
        "layer": "applied",
        "parent_template_id": _infer_parent_template_id(tags),
        "metadata": {
            "auto_generated": True,
            "base_memory_ids": [b["memory_id"] for b in base],
            "base_voyager_avg_overall": base_avg,
            "draft_created_at": datetime.now(timezone.utc).timestamp(),
            "review_status": "PENDING",
            "reviewed_by": None,
            "reviewed_at": None,
            "domain": domain,
            "consecutive_positive_count": VOYAGER_DRAFT_THRESHOLD_CONSECUTIVE,
        },
        "quality_level_override": None,
        "path_advantage_history": [],
        "evaluation_count": 0,
        "last_evaluated_at": 0,
        "consecutive_positive": 0,
        "consecutive_negative": 0,
    }
    try:
        draft_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return False, None, None

    # 更新 review_queue_index.json
    try:
        ipath = Path(DRAFT_REVIEW_INDEX_PATH)
        index: Dict[str, Any] = {"entries": []}
        if ipath.exists():
            try:
                index = json.loads(ipath.read_text(encoding="utf-8")) or {"entries": []}
            except Exception:
                index = {"entries": []}
        index.setdefault("entries", [])
        index["entries"].append({
            "draft_id": draft_id,
            "path": str(draft_path),
            "domain": domain,
            "tags": list(tags or []),
            "base_memory_ids_count": len(base),
            "base_avg_overall": base_avg,
            "created_at": doc["metadata"]["draft_created_at"],
            "review_status": "PENDING",
            "is_trd": is_trd,
        })
        ipath.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return True, draft_id, str(draft_path)


# ============================================================
# CLI 接口
# ============================================================

def _format_memories(memories: List[Dict]) -> str:
    """格式化记忆列表输出"""
    if not memories:
        return "（无匹配记忆）"
    lines = []
    for m in memories:
        quality = m.get("quality_level", "?")
        score = m.get("score", 0)
        content = m.get("content", "")[:80]
        tags = ", ".join(m.get("tags", []))
        lines.append(f"  [{quality}] score={score:.3f} {content}")
        if tags:
            lines.append(f"        tags: {tags}")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="认知闭环入口 — TRAE 记忆系统接口")
    sub = parser.add_subparsers(dest="command")

    # recall
    p_recall = sub.add_parser("recall", help="检索相关记忆")
    p_recall.add_argument("context", help="问题描述或上下文")
    p_recall.add_argument("--top-k", type=int, default=5)
    p_recall.add_argument("--min-quality", default="C")

    # search
    p_search = sub.add_parser("search", help="语义搜索")
    p_search.add_argument("query", help="搜索查询")
    p_search.add_argument("--top-k", type=int, default=5)
    p_search.add_argument("--tags", help="标签过滤（逗号分隔）")

    # record
    p_record = sub.add_parser("record", help="记录新经验")
    p_record.add_argument("content", help="经验内容")
    p_record.add_argument("--quality", default="C")
    p_record.add_argument("--confidence", type=float, default=0.3)
    p_record.add_argument("--tags", default="", help="标签（逗号分隔）")
    p_record.add_argument("--source", default="trae")

    # verify
    p_verify = sub.add_parser("verify", help="A8 校验验证")
    p_verify.add_argument("memory_id", help="记忆ID")
    p_verify.add_argument("--success", action="store_true", default=True)
    p_verify.add_argument("--fail", action="store_true", help="校验失败")

    # upgrade
    p_upgrade = sub.add_parser("upgrade", help="手动升级记忆")
    p_upgrade.add_argument("memory_id", help="记忆ID")
    p_upgrade.add_argument("--quality", required=True)
    p_upgrade.add_argument("--confidence", type=float, required=True)

    # distill
    p_distill = sub.add_parser("distill", help="手动触发蒸馏（将记忆蒸馏到总记忆单元）")
    p_distill.add_argument("memory_id", help="记忆ID")
    p_distill.add_argument("--quality", help="质量等级（默认从记忆读取）")
    p_distill.add_argument("--confidence", type=float, help="置信度（默认从记忆读取）")
    p_distill.add_argument("--source", help="来源应用记忆ID（默认 AM-TRD-001）")

    # stats
    sub.add_parser("stats", help="统计信息")

    # health
    sub.add_parser("health", help="健康检查")

    # consolidate
    p_consolidate = sub.add_parser("consolidate", help="记忆压缩（Consolidation）")
    p_consolidate.add_argument("--force", action="store_true", help="强制压缩")

    # scan
    sub.add_parser("scan", help="扫描归档候选（不执行压缩）")

    # archive
    p_archive = sub.add_parser("archive", help="执行归档（案例段落到 Tier2）")
    p_archive.add_argument("--ids", help="指定条目ID（逗号分隔），默认归档所有候选")
    p_archive.add_argument("--dry-run", action="store_true", help="预览模式")
    p_archive.add_argument("--force", action="store_true", help="确认执行")

    # vc (版本控制)
    p_vc = sub.add_parser("vc", help="记忆版本控制（MemOS 风格）")
    p_vc_sub = p_vc.add_subparsers(dest="vc_command")

    p_vc_commit = p_vc_sub.add_parser("commit", help="创建版本快照")
    p_vc_commit.add_argument("-m", "--message", required=True, help="提交信息")
    p_vc_commit.add_argument("--author", default="trae", help="提交者")
    p_vc_commit.add_argument("--allow-empty", action="store_true", help="允许空提交")

    p_vc_log = p_vc_sub.add_parser("log", help="查看版本历史")
    p_vc_log.add_argument("--limit", type=int, default=20)

    p_vc_diff = p_vc_sub.add_parser("diff", help="对比版本间差异")
    p_vc_diff.add_argument("commit_a")
    p_vc_diff.add_argument("commit_b")
    p_vc_diff.add_argument("--file", help="只查看指定文件")

    p_vc_rollback = p_vc_sub.add_parser("rollback", help="回滚到指定版本")
    p_vc_rollback.add_argument("commit_id")
    p_vc_rollback.add_argument("--force", action="store_true", help="确认回滚")
    p_vc_rollback.add_argument("--no-backup", action="store_true", help="不创建备份")

    p_vc_status = p_vc_sub.add_parser("status", help="查看工作区状态")
    p_vc_show = p_vc_sub.add_parser("show", help="查看 commit 详情")
    p_vc_show.add_argument("commit_id")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    cle = CognitiveLoopEntry()

    try:
        if args.command == "recall":
            memories = cle.recall(args.context, top_k=args.top_k, min_quality=args.min_quality)
            print(f"\n🔍 检索: \"{args.context}\"")
            print(f"   结果: {len(memories)} 条\n")
            print(_format_memories(memories))

        elif args.command == "search":
            tags = args.tags.split(",") if args.tags else None
            memories = cle.search(args.query, top_k=args.top_k, tags=tags)
            print(f"\n🔍 搜索: \"{args.query}\"")
            print(f"   结果: {len(memories)} 条\n")
            print(_format_memories(memories))

        elif args.command == "record":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
            mid = cle.record(
                content=args.content,
                quality_level=args.quality,
                confidence=args.confidence,
                tags=tags,
                source=args.source,
            )
            print(f"\n✅ 记录成功")
            print(f"   ID: {mid}")
            print(f"   质量: {args.quality}")
            print(f"   置信度: {args.confidence}")
            print(f"   标签: {tags}")

        elif args.command == "verify":
            success = not args.fail
            result = cle.verify(args.memory_id, success=success)
            print(f"\n{'✅' if success else '❌'} 验证: {args.memory_id}")
            if result.get("success"):
                print(f"   质量: {result['old_quality']} → {result['new_quality']}")
                print(f"   置信度: {result['old_confidence']} → {result['new_confidence']}")
                if result.get("distill_may_triggered"):
                    print(f"   🔄 可能触发蒸馏")
            else:
                print(f"   错误: {result.get('error')}")

        elif args.command == "upgrade":
            result = cle.upgrade(args.memory_id, args.quality, args.confidence)
            print(f"\n⬆️  升级: {args.memory_id}")
            if result.get("success"):
                print(f"   质量: {result['old_quality']} → {result['new_quality']}")
                print(f"   置信度: {result['old_confidence']} → {result['new_confidence']}")
            else:
                print(f"   错误: {result.get('error')}")

        elif args.command == "distill":
            result = cle.distill(
                memory_id=args.memory_id,
                quality_level=args.quality,
                confidence=args.confidence,
                source_app_memory=args.source,
            )
            print(f"\n🔄 蒸馏: {args.memory_id}")
            if result.get("success"):
                print(f"   目标单元: {result.get('target_unit', '?')}")
                print(f"   目标记忆: {result.get('target_memory_id', '?')}")
                print(f"   原因: {result.get('reason', '')}")
                print(f"   耗时: {result.get('latency_ms', 0):.1f} ms")
            else:
                print(f"   错误: {result.get('error', result.get('reason', '未知'))}")

        elif args.command == "stats":
            stats = cle.stats()
            print(f"\n📊 记忆系统统计")
            print(f"   总记忆: {stats['memory']['total_memories']}")
            print(f"   引擎: {stats['memory']['engine']}")
            print(f"   质量分布: {stats['memory']['quality_distribution']}")
            if stats.get("distill"):
                d = stats["distill"]
                print(f"\n   蒸馏统计:")
                print(f"     事件接收: {d.get('events_received', 0)}")
                print(f"     蒸馏触发: {d.get('distill_triggered', 0)}")
                print(f"     蒸馏成功: {d.get('distill_succeeded', 0)}")
                print(f"     跳过(质量): {d.get('distill_skipped_quality', 0)}")
                print(f"     跳过(冷却): {d.get('distill_skipped_cooldown', 0)}")
                print(f"     跳过(无路由): {d.get('distill_skipped_no_route', 0)}")
                print(f"     蒸馏失败: {d.get('distill_failed', 0)}")

        elif args.command == "health":
            health = cle.healthcheck()
            print(f"\n❤️  健康检查")
            print(f"   记忆: {health['memory']['status']}")
            print(f"   蒸馏: {health['distill']['status']}")
            print(f"   压缩: {health['consolidation']['status']}")
            cap = health['consolidation']['capacity']
            print(f"   Tier 0: {cap['tier0']['chars']}/{cap['tier0']['max_chars']} ({cap['tier0']['usage']})")
            print(f"   Tier 1: {cap['tier1']['chars']}/{cap['tier1']['max_chars']} ({cap['tier1']['usage']})")

        elif args.command == "consolidate":
            report = cle.consolidate(force=args.force)
            print(f"\n📦 记忆压缩")
            print(f"   触发: {'是' if report['consolidated'] else '否'}")
            print(f"   Tier: {report['tier']}")
            if report['consolidated']:
                print(f"   压缩前: {report['before_chars']} 字符 ({report['before_usage']})")
                print(f"   压缩后: {report['after_chars']} 字符 ({report['after_usage']})")
                print(f"   扫描: {report['items_scanned']} 条")
                print(f"   保留: {report['items_kept']} 条")
                print(f"   压缩: {report['items_compressed']} 条")
                print(f"   合并: {report['items_merged']} 条")
                print(f"   归档: {report['items_archived']} 条")
            for detail in report.get('details', []):
                print(f"   {detail}")

        elif args.command == "scan":
            report = cle.scan_archive_candidates()
            print(f"\n🔍 归档候选扫描（不执行压缩）")
            print(f"   Tier1 容量: {report['tier1_chars']} 字符 ({report['tier1_usage']})")
            print(f"   扫描条目: {report['total_items_scanned']}")
            print(f"   归档候选: {report['total_candidates']}")
            print(f"   预计释放: {report['projected_saving_chars']} 字符")
            print(f"   预计压缩后: {report['projected_usage_after']}")
            print(f"   可达阈值: {'是 ✅' if report['would_resolve_threshold'] else '否 ❌'}")
            by_type = report["candidates_by_type"]
            print(f"\n   按类型:")
            print(f"     content_defect:    {len(by_type['content_defect'])} 条")
            print(f"     outdated_case:     {len(by_type['outdated_case'])} 条")
            print(f"     cross_duplicate:   {len(by_type['cross_duplicate'])} 条")
            print(f"     low_value_detail:  {len(by_type['low_value_detail'])} 条")
            if report["candidates"]:
                print(f"\n   候选清单:")
                for c in report["candidates"]:
                    print(f"     [{c['reason_type']}] {c['item_id']}: {c['title']}")
                    print(f"       {c['file_path']} | {c['current_quality']}→{c['suggested_quality']} | 可释放 {c['potential_saving']} 字符")
                    print(f"       原因: {c['reason_detail']}")

        elif args.command == "archive":
            if not args.dry_run and not args.force:
                print("❌ 执行归档需要 --force 参数确认")
                print("   建议先运行 --dry-run 预览")
                return 1
            candidate_ids = None
            if args.ids:
                candidate_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
            mode = "预览" if args.dry_run else "执行"
            print(f"\n📦 {mode}归档（案例段落到 Tier2）")
            report = cle.execute_archive(candidate_ids=candidate_ids, dry_run=args.dry_run)
            print(f"   归档前: {report['tier1_before']}")
            print(f"   归档后: {report['tier1_after']}")
            print(f"   预计释放: {report['total_saving_chars']} 字符")
            print(f"   达到阈值: {'是 ✅' if report['threshold_resolved'] else '否 ❌'}")
            print(f"   计划归档: {report['total_planned']} 条")
            print(f"   实际归档: {report['total_archived']} 条")
            print(f"   预览归档: {report['total_dry_run']} 条")
            print(f"   跳过: {report['total_skipped']} 条")
            if report["results"]:
                print(f"\n   归档详情:")
                for r in report["results"]:
                    status_icon = "✅" if r["status"] == "archived" else "👁️"
                    print(f"     {status_icon} [{r['reason_type']}] {r['item_id']}: {r['title']}")
                    print(f"        文件: {r['file']} | 释放 {r['saving_chars']} 字符")
                    if r["status"] == "archived":
                        print(f"        归档到: {r['archive_file']}")

        elif args.command == "vc":
            if not args.vc_command:
                print("用法: vc <commit|log|diff|rollback|status|show>")
                return 1

            if args.vc_command == "commit":
                result = cle.vc_commit(args.message, author=args.author, allow_empty=args.allow_empty)
                if not result.get("committed"):
                    print(f"未创建 commit: {result.get('reason', '未知原因')}")
                    return 1
                print(f"✅ 提交成功")
                print(f"   commit: {result['commit_id'][:8]}")
                print(f"   消息: {result['message']}")

            elif args.vc_command == "log":
                entries = cle.vc_log(limit=args.limit)
                if not entries:
                    print("还没有任何 commit")
                    return 1
                print(f"📚 版本历史（共 {len(entries)} 条）\n")
                for entry in entries:
                    changes = entry["changes"]
                    change_str = " ".join(
                        f"{p}{n}" for p, n in [("+", changes["added"]), ("~", changes["modified"]), ("-", changes["removed"])] if n
                    ) or "无变更"
                    print(f"  {entry['short_id']}  {entry['timestamp'][:19]}  [{entry['author']}]")
                    print(f"           {entry['message']}")
                    print(f"           文件: {entry['file_count']} | 变更: {change_str}")
                    print()

            elif args.vc_command == "diff":
                diffs = cle.vc_diff(args.commit_a, args.commit_b, file_filter=args.file)
                if not diffs:
                    print("无差异")
                else:
                    print(f"📊 差异: {args.commit_a[:8]} → {args.commit_b[:8]}\n")
                    for d in diffs:
                        icon = {"added": "➕", "modified": "📝", "removed": "➖"}.get(d["status"], "?")
                        print(f"{icon} {d['file']} ({d['status']}) +{d['added_lines']} -{d['removed_lines']}")

            elif args.vc_command == "rollback":
                if not args.force:
                    print("❌ 回滚需要 --force 参数确认")
                    return 1
                result = cle.vc_rollback(args.commit_id, create_backup=not args.no_backup)
                print(f"✅ 回滚成功")
                print(f"   目标: {result['rolled_back_to_short']}")
                print(f"   备份: {result['backup_commit_id'][:8] if result['backup_commit_id'] else '无'}")
                print(f"   恢复文件: {len(result['restored_files'])} 个")

            elif args.vc_command == "status":
                status = cle.vc_status()
                if not status.get("has_commits"):
                    print(status.get("message", "还没有任何 commit"))
                    return 1
                print(f"📊 工作区状态")
                print(f"   最新 commit: {status['latest_commit']}")
                print(f"   消息: {status['latest_message']}")
                print(f"   状态: {'✅ 干净' if status['is_clean'] else '⚠️ 有未提交变更'}")
                if status["modified"]:
                    print(f"   修改: {len(status['modified'])} 个")
                    for f in status["modified"]:
                        print(f"     ~ {f}")

            elif args.vc_command == "show":
                info = cle.vc_show(args.commit_id)
                print(f"📋 Commit 详情")
                print(f"   ID: {info['short_id']}")
                print(f"   时间: {info['timestamp'][:19]}")
                print(f"   作者: {info['author']}")
                print(f"   消息: {info['message']}")
                print(f"   文件: {info['file_count']} 个")

    finally:
        cle.close()

    return 0


# ============================================================
# 模块级单例（修复：原各调用方独立 new 实例，导致 working_memory/process_block 不同步）
# ============================================================

_cle_instance: Optional["CognitiveLoopEntry"] = None


def get_cle() -> "CognitiveLoopEntry":
    """获取 CognitiveLoopEntry 单例（进程内共享 working_memory）。"""
    global _cle_instance
    if _cle_instance is None:
        _cle_instance = CognitiveLoopEntry()
    return _cle_instance


def reset_cle():
    """重置单例（测试用）。"""
    global _cle_instance
    if _cle_instance is not None:
        try:
            _cle_instance.close()
        except Exception:
            pass
    _cle_instance = None


# ============================================================
# P3: 交易系统编程式召回 — 供 A 系列 Cron 执行前注入认知召回
# ============================================================

def trading_recall(
    context: str,
    task_type: str = "trading-system",
    top_k_mem: int = 5,
    top_meta: int = 2,
    top_applied: int = 2,
    coin: str = "",
    direction: str = "",
) -> Dict[str, Any]:
    """
    P3: 交易系统编程式召回 API。

    供交易系统（polling_trader / A 系列 Cron）在执行前直接 import 调用，
    返回 memories + processes/meta + processes/applied 三段结构，
    与 MCP recall 工具返回格式一致。

    P1-3 新增: 召回结果同时发布到 shared_memory_bus（全局广播），
    供 AB-Trading 等跨系统模块并行获取（对齐 Baars GWT 全局工作空间理论）。

    设计原则:
      - 建议而非约束: 召回结果是上下文增强，不阻断交易决策
      - 失败安全: 认知系统不可用时返回空结果，不抛异常；广播失败也不影响主流程
      - 边界清晰: 认知系统提供 API，交易系统调用，无反向依赖

    Args:
        context: 交易上下文（如 "BTC 做多 置信度0.72 震荡市场"）
        task_type: 交易 task_type（默认 trading-system，路由到 T 系列 Skill）
        top_k_mem: 经验记忆返回数
        top_meta: 元认知流程（T 系列 Skill）返回数
        top_applied: 应用认知流程（APP-TRD-*.json）返回数
        coin: 交易币种（如 "BTC-USDT-SWAP"），用于全局广播 payload
        direction: 交易方向（如 "LONG"/"SHORT"），用于全局广播 payload

    Returns:
        {
            "memories": [...],          # 经验记忆
            "count": int,
            "processes": {
                "meta": [...],          # T 系列 Skill 建议
                "applied": [...],       # 历史交易解决路径
                "process_block_markdown": "...",
            },
            "ok": bool,                 # 认知系统是否可用
        }
    """
    empty_result: Dict[str, Any] = {
        "memories": [],
        "count": 0,
        "processes": {"meta": [], "applied": [], "process_block_markdown": ""},
        "ok": False,
    }

    try:
        cle = get_cle()
        # 1) 经验记忆召回
        memories = cle.recall(context, top_k=top_k_mem, min_quality="C")

        # 2) 元认知流程（T 系列 Skill）+ 应用认知流程
        from cognitive_superpowers import SkillLoader, ProcessTemplateRegistry

        loader = SkillLoader()
        registry = ProcessTemplateRegistry()
        proc = loader.retrieve(
            context,
            top_meta=top_meta,
            top_applied=top_applied,
            applied_loader=registry,
            task_type=task_type,
        )

        # 3) meta 元组 → 可序列化 dict
        meta_list = [
            {
                "skill_id": sk.skill_id,
                "display_name": sk.display_name,
                "match_score": round(score, 2),
                "match_reason": reason,
                "hard_gates": sk.hard_gates,
                "localized": sk.localized,
            }
            for (sk, score, reason) in proc["meta"]
        ]

        # 4) 拼装 process_block_markdown
        md_parts = [
            f"### [{sk.skill_id}] {sk.display_name}\n- 匹配度: {score:.2f}\n- {reason}"
            for (sk, score, reason) in proc["meta"]
        ]
        process_block_md = "\n\n".join(md_parts)

        result = {
            "memories": memories,
            "count": len(memories),
            "processes": {
                "meta": meta_list,
                "applied": proc["applied"],
                "process_block_markdown": process_block_md,
            },
            "ok": True,
        }

        # P1-3: 全局广播——召回结果发布到 shared_memory_bus（GWT 全局工作空间）
        # 失败安全：广播异常不影响主流程
        try:
            _publish_cognitive_recall_broadcast(coin, direction, context, result)
        except Exception:
            pass  # 广播失败静默处理

        return result
    except Exception as e:
        empty_result["error"] = str(e)
        return empty_result


def _publish_cognitive_recall_broadcast(
    coin: str,
    direction: str,
    context: str,
    recall_result: Dict[str, Any],
) -> None:
    """P1-3: 将认知召回结果发布到 shared_memory_bus（全局广播）。

    对齐 Baars GWT "剧院模型"：信息进入全局工作空间后被全脑广播，
    各模块（AB-Trading 等）可并行获取。
    """
    try:
        from datetime import datetime
        # 动态导入 shared_memory_bus（避免硬依赖）
        import importlib
        bus_path = Path(__file__).resolve().parents[2] / "11-易经推理系统" / "scripts" / "memory_l4" / "shared_memory_bus.py"
        if not bus_path.exists():
            return
        spec = importlib.util.spec_from_file_location("shared_memory_bus", bus_path)
        if not spec or not spec.loader:
            return
        bus_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bus_module)

        # 构造广播 payload
        recall_summary = f"memories={recall_result.get('count', 0)}, meta={len(recall_result.get('processes', {}).get('meta', []))}"
        suggested_skills = [m.get("skill_id", "") for m in recall_result.get("processes", {}).get("meta", [])]

        bus_module.publish_shared_memory_event(
            snapshot_ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            agent_id="cognitive_recall",
            event_type="cognitive_recall_broadcast",
            payload={
                "coin": coin,
                "direction": direction,
                "context": context[:200],
                "recall_summary": recall_summary,
                "suggested_skills": suggested_skills,
            },
        )
    except Exception:
        pass  # 广播失败静默处理


if __name__ == "__main__":
    sys.exit(main())

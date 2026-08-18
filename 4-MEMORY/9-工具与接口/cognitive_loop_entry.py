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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


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
        return [r.to_dict() for r in results]

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
    ) -> str:
        """
        记录新经验到记忆系统。

        Args:
            content: 经验内容
            quality_level: 质量等级 (S/A/B/C/D)
            confidence: 置信度 (0.0-1.0)
            tags: 标签
            source: 来源（如 "trae", "a8_check", "code_review"）
            memory_type: 记忆类型

        Returns:
            记忆ID
        """
        return self._vm.add(
            content=content,
            quality_level=quality_level,
            confidence=confidence,
            tags=tags or [],
            source=source,
            memory_type=memory_type,
        )

    # ============================================================
    # 实践层：验证与更新
    # ============================================================

    def verify(self, memory_id: str, success: bool = True) -> Dict[str, Any]:
        """
        A8 校验验证 — 更新记忆置信度并可能触发蒸馏。

        Args:
            memory_id: 记忆ID
            success: 校验是否通过

        Returns:
            更新结果
        """
        # 获取当前状态
        mem = self._vm.get(memory_id)
        if not mem:
            return {"success": False, "error": f"记忆不存在: {memory_id}"}

        old_quality = mem["quality_level"]
        old_confidence = mem["confidence"]

        # 贝叶斯更新
        if success:
            new_confidence = min(1.0, old_confidence + 0.1)
        else:
            new_confidence = max(0.0, old_confidence - 0.15)

        # 计算新质量等级
        new_quality = self._confidence_to_quality(new_confidence, mem["verify_count"] + 1)

        # 更新（会自动触发蒸馏）
        self._vm.update_quality(memory_id, new_quality, new_confidence)
        self._vm.increment_verify(memory_id)

        return {
            "success": True,
            "memory_id": memory_id,
            "old_quality": old_quality,
            "new_quality": new_quality,
            "old_confidence": round(old_confidence, 4),
            "new_confidence": round(new_confidence, 4),
            "quality_changed": old_quality != new_quality,
            "distill_may_triggered": new_quality != old_quality and new_quality in ("S", "A", "B"),
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

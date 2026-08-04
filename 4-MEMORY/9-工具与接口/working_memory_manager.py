#!/usr/bin/env python3
"""
工作记忆管理器 (WorkingMemoryManager) — L0 工作记忆层

定位：AI Agent 的"大脑工作台"，管理当前会话/任务的临时上下文。
借鉴 Letta (MemGPT) 的 Core Memory 设计，增加 Token 预算管理和检查点机制。

核心设计：
1. 三分区结构：
   - task_block:    当前任务的核心状态（任务ID、目标、进度）
   - context_block: 上下文信息（当前分析的文件、使用的策略、上一步结论）
   - scratch_block: 草稿区（临时计算结果、中间变量）

2. Token 预算管理：
   - 每个分区有独立的 Token 预算
   - 超出预算时自动触发摘要压缩

3. 检查点机制：
   - 定期/手动保存到文件，防止崩溃丢失
   - 支持从检查点恢复

4. 蒸馏接口：
   - 任务结束后，将有效经验蒸馏到 L1 应用记忆

生命周期：
    任务开始 → 初始化工作记忆 → 执行任务(读写工作记忆) → 任务结束 → 蒸馏到L1 → 清空

用法：
    from working_memory_manager import WorkingMemoryManager

    wm = WorkingMemoryManager(task_id="T-001")
    wm.set_task("分析BTC持仓风险", goal="评估是否需要减仓")
    wm.set_context("current_symbol", "BTC")
    wm.set_context("strategy", "A1调研法")
    wm.set_scratch("btc_position", {"side": "long", "size": 0.5})

    # 获取注入到 System Prompt 的上下文
    prompt_context = wm.get_context()

    # 保存检查点
    wm.checkpoint()

    # 任务结束后蒸馏
    wm.distill_to_app_memory("AM-TRD-001", "BTC持仓分析完成，建议减仓50%")
"""

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MemoryBlock:
    """
    工作记忆分区
    每个分区有独立的 Token 预算，超出时触发压缩。
    """
    name: str
    max_tokens: int = 2000
    items: Dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        """设置键值对。"""
        self.items[key] = str(value)

    def get(self, key: str, default: str = "") -> str:
        """获取值。"""
        return self.items.get(key, default)

    def remove(self, key: str) -> bool:
        """删除键。"""
        if key in self.items:
            del self.items[key]
            return True
        return False

    def clear(self) -> None:
        """清空分区。"""
        self.items.clear()

    def estimate_tokens(self) -> int:
        """估算当前 Token 数（4字符≈1token）。"""
        total_chars = sum(len(k) + len(v) + 4 for k, v in self.items.items())
        return total_chars // 4

    def is_over_budget(self) -> bool:
        """是否超出 Token 预算。"""
        return self.estimate_tokens() > self.max_tokens

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "max_tokens": self.max_tokens,
            "items": dict(self.items),
            "estimated_tokens": self.estimate_tokens(),
        }


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str = ""
    title: str = ""
    goal: str = ""
    status: str = "pending"  # pending / running / completed / failed
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "goal": self.goal,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ============================================================
# 核心管理器
# ============================================================

class WorkingMemoryManager:
    """
    工作记忆管理器 (L0)

    管理 AI Agent 在单次任务/会话中的临时上下文。
    提供显式的、可控的上下文管理机制，避免依赖 LLM 的 Context Window。

    核心能力：
    1. 三分区上下文管理（task / context / scratch）
    2. Token 预算控制与自动压缩
    3. 检查点保存与恢复
    4. 任务结束后蒸馏到 L1 应用记忆
    """

    # 默认 Token 预算（可按任务调整）
    DEFAULT_BUDGETS = {
        "task": 500,       # 任务信息：精简
        "context": 2000,   # 上下文：中等
        "scratch": 1500,   # 草稿区：中等
        "process": 3000,   # 流程建议（元+应用双层），设计节 3.2
    }

    def __init__(
        self,
        task_id: Optional[str] = None,
        checkpoint_dir: Optional[Path] = None,
        budgets: Optional[Dict[str, int]] = None,
    ):
        """
        初始化工作记忆管理器。

        Args:
            task_id: 任务ID，用于检查点命名。为 None 时自动生成。
            checkpoint_dir: 检查点存储目录。默认为 4-MEMORY/0-工作记忆/checkpoints/
            budgets: 各分区的 Token 预算覆盖。如 {"context": 3000}
        """
        self.task_info = TaskInfo(
            task_id=task_id or f"T-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="running",
        )

        # 初始化三分区
        merged_budgets = {**self.DEFAULT_BUDGETS, **(budgets or {})}
        self.task_block = MemoryBlock("task", max_tokens=merged_budgets.get("task", 500))
        self.context_block = MemoryBlock("context", max_tokens=merged_budgets.get("context", 2000))
        self.scratch_block = MemoryBlock("scratch", max_tokens=merged_budgets.get("scratch", 1500))
        self.process_block = MemoryBlock("process", max_tokens=merged_budgets.get("process", 3000))
        self.process_block._readonly = True  # 只有 recall 注入能写，AI 自身不能改写

        # 检查点目录
        if checkpoint_dir is None:
            checkpoint_dir = Path(__file__).parent.parent / "0-工作记忆" / "checkpoints"
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 线程锁（保证并发安全）
        self._lock = threading.Lock()

        # 操作历史（用于蒸馏分析）
        self._operation_log: List[Dict[str, Any]] = []

    # ============================================================
    # 任务管理
    # ============================================================

    def set_task(self, title: str, goal: str = "") -> None:
        """设置任务信息。"""
        with self._lock:
            self.task_info.title = title
            self.task_info.goal = goal
            self.task_block.set("title", title)
            self.task_block.set("goal", goal)
            self._log("set_task", {"title": title, "goal": goal})

    def update_status(self, status: str) -> None:
        """更新任务状态。"""
        with self._lock:
            self.task_info.status = status
            if status in ("completed", "failed"):
                self.task_info.completed_at = datetime.now(timezone.utc).isoformat()
            self._log("update_status", {"status": status})

    # ============================================================
    # 上下文管理 (context_block)
    # ============================================================

    def set_context(self, key: str, value: Any) -> None:
        """
        设置上下文变量。

        Args:
            key: 变量名，如 "current_symbol", "strategy"
            value: 变量值，会自动转为字符串
        """
        with self._lock:
            self.context_block.set(key, value)
            self._log("set_context", {"key": key})
            self._auto_compress_if_needed(self.context_block)

    def get_context(self, key: str, default: str = "") -> str:
        """获取上下文变量。"""
        return self.context_block.get(key, default)

    def remove_context(self, key: str) -> bool:
        """移除上下文变量。"""
        with self._lock:
            return self.context_block.remove(key)

    # ============================================================
    # 草稿区管理 (scratch_block)
    # ============================================================

    def set_scratch(self, key: str, value: Any) -> None:
        """
        设置草稿变量（临时计算结果、中间变量）。

        Args:
            key: 变量名
            value: 变量值，复杂对象会 JSON 序列化
        """
        with self._lock:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            self.scratch_block.set(key, value)
            self._log("set_scratch", {"key": key})
            self._auto_compress_if_needed(self.scratch_block)

    def get_scratch(self, key: str, default: str = "") -> str:
        """获取草稿变量。"""
        return self.scratch_block.get(key, default)

    def get_scratch_json(self, key: str, default: Any = None) -> Any:
        """获取草稿变量并解析为 JSON。"""
        raw = self.scratch_block.get(key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    def remove_scratch(self, key: str) -> bool:
        """移除草稿变量。"""
        with self._lock:
            return self.scratch_block.remove(key)

    def load_process_block(self, markdown: str) -> None:
        """供 recall 写入流程建议（设计节 3.2）。

        Args:
            markdown: 可直接注入 System Prompt 的 Markdown 全文
        """
        with self._lock:
            self.process_block.set("markdown", markdown)
            self._log("load_process_block", {"chars": len(markdown)})

    # ============================================================
    # 上下文生成（注入到 System Prompt）
    # ============================================================

    def get_prompt_context(self) -> str:
        """
        生成注入到 System Prompt 的格式化上下文字符串。

        Returns:
            Markdown 格式的上下文摘要
        """
        lines = [
            "## 当前工作记忆 (Working Memory)",
            "",
            f"**任务ID**: {self.task_info.task_id}",
            f"**任务**: {self.task_info.title}",
            f"**目标**: {self.task_info.goal}",
            f"**状态**: {self.task_info.status}",
            "",
        ]

        if self.context_block.items:
            lines.append("### 上下文")
            for k, v in self.context_block.items.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        if self.scratch_block.items:
            lines.append("### 草稿区")
            for k, v in self.scratch_block.items.items():
                # 截断过长的草稿值
                display = v[:200] + "..." if len(v) > 200 else v
                lines.append(f"- **{k}**: {display}")
            lines.append("")

        if self.process_block.items:
            lines.append("---")
            lines.append("## 🎯 流程建议（非约束，可自由选择 · Dreambuddy Process Layer）")
            process_md = self.process_block.get("markdown", "")
            if process_md:
                lines.append(process_md)
            lines.append("")

        # Token 使用情况
        total = self._total_tokens()
        lines.append(f"---")
        lines.append(f"*工作记忆 Token 使用: {total} tokens*")

        return "\n".join(lines)

    # ============================================================
    # Token 预算管理
    # ============================================================

    def get_token_usage(self) -> Dict[str, int]:
        """获取各分区的 Token 使用情况。"""
        return {
            "task": self.task_block.estimate_tokens(),
            "context": self.context_block.estimate_tokens(),
            "scratch": self.scratch_block.estimate_tokens(),
            "process": self.process_block.estimate_tokens(),
            "total": self._total_tokens(),
        }

    def _total_tokens(self) -> int:
        return (
            self.task_block.estimate_tokens()
            + self.context_block.estimate_tokens()
            + self.scratch_block.estimate_tokens()
            + self.process_block.estimate_tokens()
        )

    def _auto_compress_if_needed(self, block: MemoryBlock) -> None:
        """
        当分区超出 Token 预算时，自动压缩。
        策略：保留最新的条目，对旧条目生成摘要。
        """
        if not block.is_over_budget():
            return

        items = list(block.items.items())
        # 保留后一半（较新的），前一半合并为摘要
        mid = len(items) // 2
        old_items = items[:mid]
        new_items = items[mid:]

        # 生成摘要
        summary_parts = [f"{k}={v[:50]}" for k, v in old_items]
        summary = " [压缩: " + "; ".join(summary_parts) + "]"

        block.items = dict(new_items)
        block.items["_compressed_summary"] = summary

        self._log("auto_compress", {
            "block": block.name,
            "removed_count": len(old_items),
        })

    # ============================================================
    # 检查点机制
    # ============================================================

    def checkpoint(self, name: Optional[str] = None) -> Path:
        """
        保存检查点到文件。

        Args:
            name: 检查点名称，默认用时间戳

        Returns:
            检查点文件路径
        """
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{self.task_info.task_id}_{name or timestamp}.json"
            filepath = self.checkpoint_dir / filename

            data = {
                "task_info": self.task_info.to_dict(),
                "task_block": self.task_block.to_dict(),
                "context_block": self.context_block.to_dict(),
                "scratch_block": self.scratch_block.to_dict(),
                "operation_log": self._operation_log[-50:],  # 保留最近50条
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            filepath.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self._log("checkpoint", {"filepath": str(filepath)})
            return filepath

    def restore(self, checkpoint_path: Path) -> bool:
        """
        从检查点恢复工作记忆。

        Args:
            checkpoint_path: 检查点文件路径

        Returns:
            是否成功恢复
        """
        with self._lock:
            checkpoint_path = Path(checkpoint_path)
            if not checkpoint_path.exists():
                return False

            try:
                data = json.loads(checkpoint_path.read_text(encoding="utf-8"))

                # 恢复任务信息
                ti = data["task_info"]
                self.task_info = TaskInfo(**ti)

                # 恢复分区
                tb = data["task_block"]
                self.task_block = MemoryBlock(
                    name=tb["name"],
                    max_tokens=tb["max_tokens"],
                    items=tb["items"],
                )

                cb = data["context_block"]
                self.context_block = MemoryBlock(
                    name=cb["name"],
                    max_tokens=cb["max_tokens"],
                    items=cb["items"],
                )

                sb = data["scratch_block"]
                self.scratch_block = MemoryBlock(
                    name=sb["name"],
                    max_tokens=sb["max_tokens"],
                    items=sb["items"],
                )

                self._operation_log = data.get("operation_log", [])
                self._log("restore", {"filepath": str(checkpoint_path)})
                return True

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                return False

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """列出当前任务的所有检查点。"""
        pattern = f"{self.task_info.task_id}_*.json"
        checkpoints = []
        for cp_file in sorted(self.checkpoint_dir.glob(pattern)):
            try:
                data = json.loads(cp_file.read_text(encoding="utf-8"))
                checkpoints.append({
                    "file": str(cp_file),
                    "name": cp_file.stem,
                    "saved_at": data.get("saved_at", ""),
                    "status": data.get("task_info", {}).get("status", ""),
                })
            except json.JSONDecodeError:
                continue
        return checkpoints

    # ============================================================
    # 蒸馏接口（L0 → L1）
    # ============================================================

    def distill_to_app_memory(
        self,
        target_memory_id: str,
        lesson_content: str,
        confidence: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        任务结束后，将有效经验蒸馏到 L1 应用记忆。

        这是从 L0 工作记忆到 L1 应用记忆的"下降"路径，
        与 DistillScheduler 的 L1→L2 上升路径互补。

        Args:
            target_memory_id: 目标应用记忆ID（如 "AM-TRD-001"）
            lesson_content: 经验内容
            confidence: 初始置信度
            tags: 标签列表

        Returns:
            蒸馏结果
        """
        with self._lock:
            distill_data = {
                "source_task_id": self.task_info.task_id,
                "source_task_title": self.task_info.title,
                "target_memory_id": target_memory_id,
                "lesson_content": lesson_content,
                "confidence": confidence,
                "tags": tags or [],
                "context_snapshot": {
                    "context_block": dict(self.context_block.items),
                    "task_status": self.task_info.status,
                },
                "operation_count": len(self._operation_log),
                "distilled_at": datetime.now(timezone.utc).isoformat(),
            }

            # 尝试写入目标应用记忆
            success = self._write_to_app_memory(target_memory_id, distill_data)

            self._log("distill", {
                "target": target_memory_id,
                "success": success,
            })

            return {
                "success": success,
                "distill_data": distill_data,
            }

    def _write_to_app_memory(self, memory_id: str, data: Dict) -> bool:
        """
        将蒸馏数据写入目标应用记忆。
        使用动态导入，避免硬依赖。
        """
        # 应用记忆接口路径映射
        memory_paths = {
            "AM-TRD-001": "11-易经推理系统/scripts/memory_l4/app_memory_interface.py",
            "AM-RSK-001": "13-通用风控模块/memory/app_memory_interface.py",
            "AM-OPS-001": "15-监控告警系统/memory/app_memory_interface.py",
            "AM-EXP-001": "experiments/ab-trading/memory/app_memory_interface.py",
        }

        module_path = memory_paths.get(memory_id)
        if not module_path:
            return False

        full_path = Path(__file__).parent.parent.parent / module_path
        if not full_path.exists():
            return False

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("app_memory", full_path)
            if not spec or not spec.loader:
                return False
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 尝试获取接口类（不同应用记忆的类名不同）
            interface_class = None
            for class_name in ["ExperimentMemoryInterface", "RiskMemoryInterface",
                               "OpsMemoryInterface", "AppMemoryInterface",
                               "TradingMemoryInterface"]:
                interface_class = getattr(module, class_name, None)
                if interface_class:
                    break

            if not interface_class:
                return False

            interface = interface_class()
            interface.add({
                "memory_type": "lesson",
                "content": data["lesson_content"],
                "confidence": data["confidence"],
                "tags": data["tags"],
            })
            return True

        except Exception:
            return False

    # ============================================================
    # 清理与重置
    # ============================================================

    def clear(self) -> None:
        """清空所有工作记忆（任务结束后调用）。"""
        with self._lock:
            self.task_block.clear()
            self.context_block.clear()
            self.scratch_block.clear()
            self._operation_log.clear()
            self.task_info = TaskInfo(
                task_id=f"T-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                started_at=datetime.now(timezone.utc).isoformat(),
                status="pending",
            )

    def reset(self) -> None:
        """重置工作记忆，保留任务ID。"""
        with self._lock:
            task_id = self.task_info.task_id
            self.clear()
            self.task_info.task_id = task_id
            self.task_info.started_at = datetime.now(timezone.utc).isoformat()
            self.task_info.status = "running"

    # ============================================================
    # 内部工具
    # ============================================================

    def _log(self, operation: str, details: Dict[str, Any]) -> None:
        """记录操作日志（用于蒸馏分析）。"""
        self._operation_log.append({
            "operation": operation,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_stats(self) -> Dict[str, Any]:
        """获取工作记忆统计信息。"""
        return {
            "task_id": self.task_info.task_id,
            "task_title": self.task_info.title,
            "task_status": self.task_info.status,
            "token_usage": self.get_token_usage(),
            "context_items": len(self.context_block.items),
            "scratch_items": len(self.scratch_block.items),
            "operation_count": len(self._operation_log),
            "checkpoint_count": len(self.list_checkpoints()),
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于调试和检查点）。"""
        return {
            "task_info": self.task_info.to_dict(),
            "task_block": self.task_block.to_dict(),
            "context_block": self.context_block.to_dict(),
            "scratch_block": self.scratch_block.to_dict(),
            "stats": self.get_stats(),
        }


# ============================================================
# 便捷函数
# ============================================================

def create_working_memory(
    title: str,
    goal: str = "",
    budgets: Optional[Dict[str, int]] = None,
) -> WorkingMemoryManager:
    """
    快速创建工作记忆管理器。

    Args:
        title: 任务标题
        goal: 任务目标
        budgets: Token 预算覆盖

    Returns:
        已初始化的 WorkingMemoryManager
    """
    wm = WorkingMemoryManager(budgets=budgets)
    wm.set_task(title, goal)
    return wm


# ============================================================
# 主入口（CLI 测试）
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("工作记忆管理器 (L0) — 功能验证")
    print("=" * 60)

    # 创建工作记忆
    wm = create_working_memory(
        title="分析BTC持仓风险",
        goal="评估是否需要减仓",
    )

    print(f"\n📝 任务ID: {wm.task_info.task_id}")
    print(f"📝 任务: {wm.task_info.title}")

    # 设置上下文
    wm.set_context("current_symbol", "BTC")
    wm.set_context("strategy", "A1调研法")
    wm.set_context("timeframe", "4h+1d")

    # 设置草稿
    wm.set_scratch("btc_position", {"side": "long", "size": 0.5, "entry": 65000})
    wm.set_scratch("analysis_result", "多头趋势确立，但RSI超买")

    # 获取 Token 使用
    usage = wm.get_token_usage()
    print(f"\n📊 Token 使用: {usage}")

    # 生成 Prompt 上下文
    print("\n" + "=" * 60)
    print("Prompt 上下文:")
    print("=" * 60)
    print(wm.get_prompt_context())

    # 保存检查点
    cp_path = wm.checkpoint("analysis_done")
    print(f"\n✅ 检查点已保存: {cp_path}")

    # 获取统计
    print(f"\n📈 统计: {wm.get_stats()}")

    print("\n" + "=" * 60)
    print("✅ 工作记忆管理器功能验证通过")

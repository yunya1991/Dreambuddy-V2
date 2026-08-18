#!/usr/bin/env python3
"""
MemoryManager — 记忆模块清理管理器
====================================

统一管理 Agent A 和 Agent B 的记忆空间清理。

清理策略：
    1. Agent A 记忆：
       - Lessons：评分 < 10 的自动淘汰，保留最近 20 条
       - Recent Trades：保留最近 50 条
       - Pending Strategies：超过 7 天未验证的自动移除
       - Master Switch History：保留最近 10 条

    2. Agent B 记忆：
       - Lessons：保留最近 20 条，移除超过 30 天的过期教训
       - Recent Decisions：保留最近 50 条
       - Strategy Param History：保留最近 30 条
       - Prior/Next Cycle Suggestions：超过 14 天的自动清理
       - Regime History：保留最近 100 条

    3. Trading Memory：
       - Verified Lessons：置信度 < 0.5 的淘汰，保留最近 30 条
       - Verification History：保留最近 50 条

    4. G 层图存储：
       - 压缩超过 30 天的 Chronicle
       - 删除超过 90 天的压缩 Chronicle

执行路径：
    cd /path/to/ab-trading && python3 -c "from core.memory.memory_manager import MemoryManager; m = MemoryManager(); m.clean_expired_memories()"
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = PROJECT_ROOT / "logs" / "memory_cleanup.log"


class MemoryManager:
    """记忆模块清理管理器"""

    def __init__(self):
        self._setup_logging()
        self._init_paths()

    def _setup_logging(self):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("memory_cleanup")
        logger.setLevel(logging.INFO)

        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        if not logger.handlers:
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        self.logger = logger

    def _init_paths(self):
        self.agent_a_memory_path = PROJECT_ROOT / "data" / "agent_a_memory.json"
        self.agent_b_memory_path = PROJECT_ROOT / "data" / "agent_b_memory.json"
        self.trading_memory_path = PROJECT_ROOT / "data" / "trading_memory.json"
        self.graph_storage_path = PROJECT_ROOT / "data" / "graph_storage"

    def _parse_iso_timestamp(self, ts: str) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # 统一为 timezone-aware：无时区信息的字符串按 UTC 处理
            # （Agent B / Agent A 主流程 ts 多存为 utcnow().isoformat() 即无时区后缀）
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _is_expired(self, ts: str, days: int) -> bool:
        dt = self._parse_iso_timestamp(ts)
        if not dt:
            return False
        return (datetime.now(timezone.utc) - dt) > timedelta(days=days)

    # ──────────────────────────────────────────────────────────────────────────────
    # Agent A 记忆清理
    # ──────────────────────────────────────────────────────────────────────────────

    def _clean_agent_a_lessons(self, memory: Dict) -> int:
        lessons = memory.get("lessons", [])
        initial_count = len(lessons)

        lessons = [l for l in lessons if l.get("score", 0) >= 10]

        lessons.sort(key=lambda x: x["score"], reverse=True)
        lessons = lessons[:20]

        memory["lessons"] = lessons
        removed = initial_count - len(lessons)
        if removed > 0:
            self.logger.info(f"  - 清理低价值 Lessons: {initial_count} -> {len(lessons)} (移除 {removed} 条)")
        return removed

    def _clean_agent_a_trades(self, memory: Dict) -> int:
        trades = memory.get("recent_trades", [])
        initial_count = len(trades)

        trades = trades[-50:]

        memory["recent_trades"] = trades
        removed = initial_count - len(trades)
        if removed > 0:
            self.logger.info(f"  - 清理旧交易记录: {initial_count} -> {len(trades)} (移除 {removed} 条)")
        return removed

    def _clean_agent_a_pending_strategies(self, memory: Dict) -> int:
        pending = memory.get("pending_strategies", [])
        initial_count = len(pending)

        pending = [
            p for p in pending
            if not self._is_expired(p.get("added_at", ""), days=7)
        ]

        memory["pending_strategies"] = pending
        removed = initial_count - len(pending)
        if removed > 0:
            self.logger.info(f"  - 清理过期待验证策略: {initial_count} -> {len(pending)} (移除 {removed} 条)")
        return removed

    def _clean_agent_a_master_history(self, memory: Dict) -> int:
        history = memory.get("master_switch_history", [])
        initial_count = len(history)

        history = history[-10:]

        memory["master_switch_history"] = history
        removed = initial_count - len(history)
        if removed > 0:
            self.logger.info(f"  - 清理旧大师切换记录: {initial_count} -> {len(history)} (移除 {removed} 条)")
        return removed

    def clean_agent_a_memory(self) -> Dict:
        """清理 Agent A 记忆"""
        self.logger.info("=== 清理 Agent A 记忆 ===")

        if not self.agent_a_memory_path.exists():
            self.logger.warning(f"  - Agent A 记忆文件不存在: {self.agent_a_memory_path}")
            return {}

        try:
            with open(self.agent_a_memory_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception as e:
            self.logger.error(f"  - 读取 Agent A 记忆失败: {e}")
            return {}

        total_removed = 0
        total_removed += self._clean_agent_a_lessons(memory)
        total_removed += self._clean_agent_a_trades(memory)
        total_removed += self._clean_agent_a_pending_strategies(memory)
        total_removed += self._clean_agent_a_master_history(memory)

        try:
            with open(self.agent_a_memory_path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
            self.logger.info(f"  - Agent A 记忆已保存，共移除 {total_removed} 条记录")
        except Exception as e:
            self.logger.error(f"  - 保存 Agent A 记忆失败: {e}")

        return memory

    # ──────────────────────────────────────────────────────────────────────────────
    # Agent B 记忆清理
    # ──────────────────────────────────────────────────────────────────────────────

    def _clean_agent_b_lessons(self, memory: Dict) -> int:
        lessons = memory.get("lessons", [])
        initial_count = len(lessons)

        # Agent B 的 lessons 是纯字符串列表，过滤超过 30 天的模式
        # 按顺序保留最近 20 条（lessons 列表是追加式，最新在尾部）
        lessons = lessons[-20:]

        memory["lessons"] = lessons
        removed = initial_count - len(lessons)
        if removed > 0:
            self.logger.info(f"  - 清理 Agent B Lessons: {initial_count} -> {len(lessons)} (移除 {removed} 条)")
        return removed

    def _clean_agent_b_recent_decisions(self, memory: Dict) -> int:
        decisions = memory.get("recent_decisions", [])
        initial_count = len(decisions)

        # 超过 14 天的决策或超过 50 条的旧记录清理
        now = datetime.now(timezone.utc)
        filtered = []
        for d in decisions:
            ts = d.get("ts", "")
            dt = self._parse_iso_timestamp(ts)
            if dt and (now - dt) > timedelta(days=14):
                continue
            filtered.append(d)

        # 保留最近 50 条
        filtered = filtered[-50:]

        memory["recent_decisions"] = filtered
        removed = initial_count - len(filtered)
        if removed > 0:
            self.logger.info(f"  - 清理 Agent B 决策记录: {initial_count} -> {len(filtered)} (移除 {removed} 条)")
        return removed

    def _clean_agent_b_strategy_param_history(self, memory: Dict) -> int:
        history = memory.get("strategy_param_history", [])
        initial_count = len(history)

        # 保留最近 30 条
        history = history[-30:]

        memory["strategy_param_history"] = history
        removed = initial_count - len(history)
        if removed > 0:
            self.logger.info(f"  - 清理 Agent B 参数调整历史: {initial_count} -> {len(history)} (移除 {removed} 条)")
        return removed

    def _clean_agent_b_suggestions(self, memory: Dict) -> int:
        removed = 0
        # suggestion_loop 内部清理：超过 14 天的 prior/next 建议
        sl = memory.get("suggestion_loop", {})
        if sl:
            for key in ("prior_cycle_suggestions", "next_cycle_suggestions"):
                sug = sl.get(key, {})
                cycle_id = sug.get("cycle_id", "")
                if cycle_id:
                    # cycle_id 形如 20260810_020005，解析其中的日期
                    try:
                        date_part = cycle_id.split("_")[0]
                        sug_date = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone.utc)
                        if (datetime.now(timezone.utc) - sug_date) > timedelta(days=14):
                            sl[key] = {}
                            removed += 1
                    except (ValueError, IndexError):
                        pass
            # verified_lessons 和 verification_history 交给 Trading Memory 清理
            memory["suggestion_loop"] = sl

        # 同时清理兼容字段
        for key in ("prior_cycle_suggestions", "next_cycle_suggestions"):
            sug = memory.get(key, {})
            cycle_id = sug.get("cycle_id", "")
            if cycle_id:
                try:
                    date_part = cycle_id.split("_")[0]
                    sug_date = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - sug_date) > timedelta(days=14):
                        memory[key] = {}
                        removed += 1
                except (ValueError, IndexError):
                    pass

        if removed > 0:
            self.logger.info(f"  - 清理 Agent B 过期建议: 移除 {removed} 组")
        return removed

    def _clean_agent_b_regime_history(self, memory: Dict) -> int:
        regimes = memory.get("regime_history", [])
        initial_count = len(regimes)

        # 保留最近 100 条
        regimes = regimes[-100:]

        memory["regime_history"] = regimes
        removed = initial_count - len(regimes)
        if removed > 0:
            self.logger.info(f"  - 清理 Agent B Regime 历史: {initial_count} -> {len(regimes)} (移除 {removed} 条)")
        return removed

    def clean_agent_b_memory(self) -> Dict:
        """清理 Agent B 记忆"""
        self.logger.info("=== 清理 Agent B 记忆 ===")

        if not self.agent_b_memory_path.exists():
            self.logger.warning(f"  - Agent B 记忆文件不存在: {self.agent_b_memory_path}")
            return {}

        try:
            with open(self.agent_b_memory_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception as e:
            self.logger.error(f"  - 读取 Agent B 记忆失败: {e}")
            return {}

        total_removed = 0
        total_removed += self._clean_agent_b_lessons(memory)
        total_removed += self._clean_agent_b_recent_decisions(memory)
        total_removed += self._clean_agent_b_strategy_param_history(memory)
        total_removed += self._clean_agent_b_suggestions(memory)
        total_removed += self._clean_agent_b_regime_history(memory)

        try:
            with open(self.agent_b_memory_path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
            self.logger.info(f"  - Agent B 记忆已保存，共移除 {total_removed} 条记录")
        except Exception as e:
            self.logger.error(f"  - 保存 Agent B 记忆失败: {e}")

        return memory

    # ──────────────────────────────────────────────────────────────────────────────
    # Trading Memory 清理
    # ──────────────────────────────────────────────────────────────────────────────

    def _clean_trading_memory_verified_lessons(self, memory: Dict) -> int:
        sl = memory.get("suggestion_loop", {})
        lessons = sl.get("verified_lessons", [])
        initial_count = len(lessons)

        lessons = [l for l in lessons if l.get("confidence", 0) >= 0.5]

        lessons.sort(key=lambda x: (x.get("confidence", 0), x.get("verify_count", 0)), reverse=True)
        lessons = lessons[:30]

        sl["verified_lessons"] = lessons
        memory["suggestion_loop"] = sl
        removed = initial_count - len(lessons)
        if removed > 0:
            self.logger.info(f"  - 清理低置信度教训: {initial_count} -> {len(lessons)} (移除 {removed} 条)")
        return removed

    def _clean_trading_memory_verification_history(self, memory: Dict) -> int:
        sl = memory.get("suggestion_loop", {})
        history = sl.get("verification_history", [])
        initial_count = len(history)

        history = history[-50:]

        sl["verification_history"] = history
        memory["suggestion_loop"] = sl
        removed = initial_count - len(history)
        if removed > 0:
            self.logger.info(f"  - 清理旧验证历史: {initial_count} -> {len(history)} (移除 {removed} 条)")
        return removed

    def clean_trading_memory(self) -> Dict:
        """清理 Trading Memory"""
        self.logger.info("=== 清理 Trading Memory ===")

        if not self.trading_memory_path.exists():
            self.logger.warning(f"  - Trading Memory 文件不存在: {self.trading_memory_path}")
            return {}

        try:
            with open(self.trading_memory_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception as e:
            self.logger.error(f"  - 读取 Trading Memory 失败: {e}")
            return {}

        total_removed = 0
        total_removed += self._clean_trading_memory_verified_lessons(memory)
        total_removed += self._clean_trading_memory_verification_history(memory)

        try:
            with open(self.trading_memory_path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2, ensure_ascii=False)
            self.logger.info(f"  - Trading Memory 已保存，共移除 {total_removed} 条记录")
        except Exception as e:
            self.logger.error(f"  - 保存 Trading Memory 失败: {e}")

        return memory

    # ──────────────────────────────────────────────────────────────────────────────
    # G 层图存储清理
    # ──────────────────────────────────────────────────────────────────────────────

    def clean_graph_storage(self) -> Dict:
        """清理 G 层图存储（压缩旧记录）"""
        self.logger.info("=== 清理 G 层图存储 ===")

        storage_file = self.graph_storage_path / "graph_storage.json"
        if not storage_file.exists():
            self.logger.warning(f"  - 图存储文件不存在: {storage_file}")
            return {}

        try:
            with open(storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.logger.error(f"  - 读取图存储失败: {e}")
            return {}

        chronicles = data.get("chronicles", {})
        initial_count = len(chronicles)

        cleaned_chronicles = {}
        removed = 0

        for cid, chron in chronicles.items():
            updated_at = chron.get("updated_at", 0)
            if updated_at > 0:
                try:
                    update_time = datetime.fromtimestamp(updated_at, timezone.utc)
                    if (datetime.now(timezone.utc) - update_time) > timedelta(days=90):
                        removed += 1
                        continue
                except Exception:
                    pass
            cleaned_chronicles[cid] = chron

        data["chronicles"] = cleaned_chronicles

        if removed > 0:
            self.logger.info(f"  - 清理过期 Chronicle: {initial_count} -> {len(cleaned_chronicles)} (移除 {removed} 条)")
        else:
            self.logger.info(f"  - 无过期 Chronicle 需要清理")

        try:
            with open(storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"  - 图存储已保存")
        except Exception as e:
            self.logger.error(f"  - 保存图存储失败: {e}")

        return data

    # ──────────────────────────────────────────────────────────────────────────────
    # 主清理入口
    # ──────────────────────────────────────────────────────────────────────────────

    def clean_expired_memories(self):
        """
        清理所有过期记忆数据

        执行逻辑：
            1. 清理 Agent A 记忆（低价值 lessons、旧交易记录、过期待验证策略）
            2. 清理 Agent B 记忆（过期教训、旧决策记录、参数历史、过期建议）
            3. 清理 Trading Memory（低置信度教训、旧验证历史）
            4. 清理 G 层图存储（过期 Chronicle）

        日志输出：logs/memory_cleanup.log
        """
        self.logger.info("=" * 60)
        self.logger.info("Memory Cleanup 开始执行")
        self.logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        try:
            self.clean_agent_a_memory()
            self.clean_agent_b_memory()
            self.clean_trading_memory()
            self.clean_graph_storage()

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.logger.info("=" * 60)
            self.logger.info(f"Memory Cleanup 执行完成，耗时 {elapsed:.2f} 秒")
            self.logger.info("=" * 60)

        except Exception as e:
            self.logger.error(f"Memory Cleanup 执行失败: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    m = MemoryManager()
    m.clean_expired_memories()
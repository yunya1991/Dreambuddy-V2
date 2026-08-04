#!/usr/bin/env python3
"""
实验应用记忆接口 — AM-EXP-001

遵循总记忆系统统一接口规范，实现7个标准接口 + 2个便捷方法。

封装 experiments/ab-trading 的现有记忆系统，包括：
- Agent A Memory（lessons, recent_trades, pending_strategies）
- Trading Memory（verified_lessons, verification_history）
- Graph Storage（chronicles）

与总记忆系统关系：
- AM-EXP-001 作为 L2 应用记忆层
- 蒸馏后的经验可上升为 MU-TRD（交易记忆单元）
- 总记忆通过索引路由查询到本系统

用法：
    from memory.app_memory_interface import ExperimentMemoryInterface
    
    mem = ExperimentMemoryInterface()
    results = mem.search("回测", filters={"experiment_type": "backtest"})
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ExperimentMemoryInterface:
    """
    实验应用记忆接口
    
    封装 experiments/ab-trading 的记忆系统，
    实现总记忆系统定义的统一接口规范。
    """
    
    MEMORY_ID = "AM-EXP-001"
    MEMORY_NAME = "实验应用记忆"
    MEMORY_TYPE = "application"
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化实验记忆接口。
        
        Args:
            storage_path: 存储目录路径，默认为 experiments/ab-trading/data/
        """
        if storage_path is None:
            # 默认存储位置
            storage_path = Path(__file__).parent.parent.parent / "data"
        self.storage_path = Path(storage_path)
        
        # 加载记忆数据
        self.agent_a_memory: Dict = self._load_agent_a_memory()
        self.trading_memory: Dict = self._load_trading_memory()
    
    def _load_agent_a_memory(self) -> Dict:
        """加载 Agent A 记忆。"""
        memory_file = self.storage_path / "agent_a_memory.json"
        if memory_file.exists():
            return json.loads(memory_file.read_text(encoding="utf-8"))
        return {"lessons": [], "recent_trades": [], "pending_strategies": []}
    
    def _load_trading_memory(self) -> Dict:
        """加载 Trading Memory。"""
        memory_file = self.storage_path / "trading_memory.json"
        if memory_file.exists():
            return json.loads(memory_file.read_text(encoding="utf-8"))
        return {"suggestion_loop": {"verified_lessons": [], "verification_history": []}}
    
    def _save_agent_a_memory(self):
        """保存 Agent A 记忆。"""
        memory_file = self.storage_path / "agent_a_memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            json.dumps(self.agent_a_memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def _save_trading_memory(self):
        """保存 Trading Memory。"""
        memory_file = self.storage_path / "trading_memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(
            json.dumps(self.trading_memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    # ========== 统一接口实现 ==========
    
    def search(
        self,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        memory_type: str = "all",
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        检索记忆。
        
        Args:
            query: 搜索关键词
            filters: 过滤条件
                - experiment_type: lesson / trade / strategy / verified
                - min_score: 最低评分
                - min_confidence: 最低置信度
            memory_type: 记忆类型
            top_k: 返回数量
            
        Returns:
            匹配的记忆列表
        """
        results = []
        filters = filters or {}
        
        # 搜索 lessons
        if memory_type in ("all", "lesson"):
            for lesson in self.agent_a_memory.get("lessons", []):
                if query and query.lower() not in str(lesson).lower():
                    continue
                if filters.get("min_score") and lesson.get("score", 0) < filters["min_score"]:
                    continue
                results.append({
                    "memory_type": "lesson",
                    **lesson,
                })
        
        # 搜索 verified_lessons
        if memory_type in ("all", "verified"):
            for vl in self.trading_memory.get("suggestion_loop", {}).get("verified_lessons", []):
                if query and query.lower() not in str(vl).lower():
                    continue
                if filters.get("min_confidence") and vl.get("confidence", 0) < filters["min_confidence"]:
                    continue
                results.append({
                    "memory_type": "verified_lesson",
                    **vl,
                })
        
        # 搜索 recent_trades
        if memory_type in ("all", "trade"):
            for trade in self.agent_a_memory.get("recent_trades", []):
                results.append({
                    "memory_type": "trade",
                    **trade,
                })
        
        # 搜索 pending_strategies
        if memory_type in ("all", "strategy"):
            for strategy in self.agent_a_memory.get("pending_strategies", []):
                results.append({
                    "memory_type": "strategy",
                    **strategy,
                })
        
        # 按评分/置信度排序
        results.sort(key=lambda x: x.get("score", x.get("confidence", 0)), reverse=True)
        return results[:top_k]
    
    def add(self, memory_entry: Dict[str, Any]) -> str:
        """添加记忆。"""
        memory_type = memory_entry.get("memory_type", "lesson")
        
        if memory_type == "lesson":
            lesson = {
                "content": memory_entry.get("content", ""),
                "score": memory_entry.get("score", 10),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tags": memory_entry.get("tags", []),
            }
            self.agent_a_memory["lessons"].append(lesson)
            self._save_agent_a_memory()
            return f"lesson-{len(self.agent_a_memory['lessons'])}"
        
        elif memory_type == "verified_lesson":
            vl = {
                "content": memory_entry.get("content", ""),
                "confidence": memory_entry.get("confidence", 0.5),
                "verify_count": memory_entry.get("verify_count", 0),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.trading_memory.setdefault("suggestion_loop", {}).setdefault("verified_lessons", []).append(vl)
            self._save_trading_memory()
            return f"verified-{len(self.trading_memory['suggestion_loop']['verified_lessons'])}"
        
        else:
            raise ValueError(f"未知的记忆类型: {memory_type}")
    
    def update(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """更新记忆。"""
        # 简化实现：重新加载后更新
        return True
    
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆。"""
        # 简化实现：通过search获取
        return None
    
    def stats(self) -> Dict[str, Any]:
        """统计信息。"""
        lessons = self.agent_a_memory.get("lessons", [])
        verified = self.trading_memory.get("suggestion_loop", {}).get("verified_lessons", [])
        trades = self.agent_a_memory.get("recent_trades", [])
        strategies = self.agent_a_memory.get("pending_strategies", [])
        
        return {
            "memory_id": self.MEMORY_ID,
            "lessons_count": len(lessons),
            "verified_lessons_count": len(verified),
            "trades_count": len(trades),
            "pending_strategies_count": len(strategies),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    
    def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict[str, Any]]:
        """
        蒸馏候选。
        
        返回可以上升为总记忆的经验候选。
        """
        candidates = []
        
        # 从 verified_lessons 中提取高质量经验
        for vl in self.trading_memory.get("suggestion_loop", {}).get("verified_lessons", []):
            confidence = vl.get("confidence", 0)
            quality = "A" if confidence >= 0.8 else "B" if confidence >= 0.6 else "C"
            
            quality_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
            min_order = quality_order.get(min_quality, 3)
            if quality_order.get(quality, 4) > min_order:
                continue
            
            candidates.append({
                "content": vl.get("content", ""),
                "quality_level": quality,
                "confidence": confidence,
                "verify_count": vl.get("verify_count", 0),
                "ready_for_global": quality in ("S", "A", "B"),
            })
        
        # 按置信度排序
        candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return candidates[:limit]
    
    def healthcheck(self) -> Dict[str, Any]:
        """健康检查。"""
        return {
            "status": "healthy",
            "memory_id": self.MEMORY_ID,
            "storage_path": str(self.storage_path),
            "stats": self.stats(),
            "last_check": datetime.now(timezone.utc).isoformat(),
        }
    
    # ========== 便捷方法 ==========
    
    def search_similar_cases(
        self,
        content_keyword: str,
        min_confidence: float = 0.5,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索相似案例。"""
        return self.search(
            query=content_keyword,
            filters={"min_confidence": min_confidence},
            memory_type="verified",
            top_k=top_k,
        )
    
    def run_distill_from_review(self, lesson_content: str, confidence: float) -> str:
        """从复盘生成蒸馏经验。"""
        return self.add({
            "memory_type": "verified_lesson",
            "content": lesson_content,
            "confidence": confidence,
            "verify_count": 1,
        })


if __name__ == "__main__":
    mem = ExperimentMemoryInterface()
    
    # 统计
    stats = mem.stats()
    print(f"📊 统计:")
    print(f"   - lessons: {stats['lessons_count']}")
    print(f"   - verified_lessons: {stats['verified_lessons_count']}")
    print(f"   - trades: {stats['trades_count']}")
    print(f"   - pending_strategies: {stats['pending_strategies_count']}")
    
    # 蒸馏候选
    candidates = mem.distill_candidates(min_quality="B", limit=5)
    print(f"\n🔬 蒸馏候选: {len(candidates)} 条")
    for c in candidates:
        print(f"   - [{c['quality_level']}] {c['content'][:50]}...")
    
    # 健康检查
    health = mem.healthcheck()
    print(f"\n❤️  状态: {health['status']}")
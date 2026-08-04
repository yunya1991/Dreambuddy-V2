#!/usr/bin/env python3
"""
风控应用记忆接口 — AM-RSK-001

遵循总记忆系统统一接口规范，实现7个标准接口 + 2个便捷方法。

应用记忆类型：
- case: 风控触发案例（如爆仓预警、异常交易阻断）
- review: 风控复盘分析
- distill: 提炼的风控经验
- rule: 风控规则演化历史

与总记忆系统关系：
- AM-RSK-001 作为 L2 应用记忆层
- 蒸馏后的经验可上升为 MU-TRD（交易记忆单元）的语义记忆
- 总记忆通过索引路由查询到本系统

用法：
    from memory.app_memory_interface import RiskMemoryInterface
    
    mem = RiskMemoryInterface()
    results = mem.search("爆仓预警", filters={"severity": "critical"})
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RiskCase:
    """风控案例"""
    case_id: str
    trigger_type: str  # drawdown / position / anomaly / ml_alert
    severity: str  # critical / high / medium / low
    timestamp: str
    context: Dict[str, Any]  # 交易上下文
    action_taken: str  # block / warn / adjust / allow
    outcome: str  # prevented_loss / false_positive / needs_review
    review: Optional[str] = None
    lessons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "trigger_type": self.trigger_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "context": self.context,
            "action_taken": self.action_taken,
            "outcome": self.outcome,
            "review": self.review,
            "lessons": self.lessons,
            "tags": self.tags,
        }


class RiskMemoryInterface:
    """
    风控应用记忆接口
    
    实现总记忆系统定义的统一接口规范。
    """
    
    MEMORY_ID = "AM-RSK-001"
    MEMORY_NAME = "风控应用记忆"
    MEMORY_TYPE = "application"
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化风控记忆接口。
        
        Args:
            storage_path: 存储目录路径，默认为 13-通用风控模块/memory/
        """
        if storage_path is None:
            # 默认存储位置
            storage_path = Path(__file__).parent
        self.storage_path = Path(storage_path)
        
        # 确保目录存在
        self.cases_path = self.storage_path / "cases"
        self.distill_path = self.storage_path / "distill"
        self.cases_path.mkdir(parents=True, exist_ok=True)
        self.distill_path.mkdir(parents=True, exist_ok=True)
        
        # 加载索引
        self.index: Dict[str, dict] = self._load_index()
    
    def _load_index(self) -> Dict[str, dict]:
        """加载记忆索引。"""
        index_file = self.storage_path / "memory_index.json"
        if index_file.exists():
            return json.loads(index_file.read_text(encoding="utf-8"))
        return {"cases": {}, "distill": {}, "stats": {}}
    
    def _save_index(self):
        """保存记忆索引。"""
        index_file = self.storage_path / "memory_index.json"
        index_file.write_text(
            json.dumps(self.index, indent=2, ensure_ascii=False),
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
            filters: 过滤条件（风控领域语义）
                - trigger_type: drawdown / position / anomaly / ml_alert
                - severity: critical / high / medium / low
                - outcome: prevented_loss / false_positive / needs_review
                - system: 关联的子系统（如 11-易经推理）
            memory_type: 记忆类型（case/review/distill/all）
            top_k: 返回数量
            
        Returns:
            匹配的记忆列表
        """
        results = []
        filters = filters or {}
        
        # 搜索案例
        if memory_type in ("all", "case"):
            for case_id, case_data in self.index.get("cases", {}).items():
                # 关键词匹配
                if query and query.lower() not in case_data.get("trigger_type", "").lower():
                    if not any(query.lower() in str(v).lower() for v in case_data.values()):
                        continue
                
                # 过滤条件匹配
                if not self._match_filters(case_data, filters):
                    continue
                
                results.append({
                    "memory_type": "case",
                    "case_id": case_id,
                    **case_data,
                })
        
        # 搜索蒸馏经验
        if memory_type in ("all", "distill"):
            for dist_id, dist_data in self.index.get("distill", {}).items():
                if query and query.lower() not in dist_data.get("content", "").lower():
                    continue
                results.append({
                    "memory_type": "distill",
                    "distill_id": dist_id,
                    **dist_data,
                })
        
        # 按时间戳排序，最新的在前
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results[:top_k]
    
    def _match_filters(self, data: dict, filters: dict) -> bool:
        """检查数据是否匹配过滤条件。"""
        for key, value in filters.items():
            if key in data and data[key] != value:
                return False
        return True
    
    def add(self, memory_entry: Dict[str, Any]) -> str:
        """
        添加记忆。
        
        Args:
            memory_entry: 记忆条目，需包含：
                - memory_type: case / distill
                - 其他字段根据类型而定
                
        Returns:
            记忆ID
        """
        memory_type = memory_entry.get("memory_type", "case")
        
        if memory_type == "case":
            case = RiskCase(
                case_id=memory_entry.get("case_id", f"RSK-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
                trigger_type=memory_entry.get("trigger_type", "unknown"),
                severity=memory_entry.get("severity", "medium"),
                timestamp=memory_entry.get("timestamp", datetime.now().isoformat()),
                context=memory_entry.get("context", {}),
                action_taken=memory_entry.get("action_taken", "unknown"),
                outcome=memory_entry.get("outcome", "needs_review"),
                review=memory_entry.get("review"),
                lessons=memory_entry.get("lessons", []),
                tags=memory_entry.get("tags", []),
            )
            
            # 保存案例文件
            case_file = self.cases_path / f"{case.case_id}.json"
            case_file.write_text(
                json.dumps(case.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            # 更新索引
            self.index["cases"][case.case_id] = case.to_dict()
            self._save_index()
            
            return case.case_id
        
        elif memory_type == "distill":
            dist_id = memory_entry.get("distill_id", f"DIST-{datetime.now().strftime('%Y%m%d%H%M%S')}")
            dist_data = {
                "distill_id": dist_id,
                "content": memory_entry.get("content", ""),
                "source_cases": memory_entry.get("source_cases", []),
                "quality_level": memory_entry.get("quality_level", "C"),
                "created_at": datetime.now().isoformat(),
                "tags": memory_entry.get("tags", []),
            }
            
            # 保存蒸馏文件
            dist_file = self.distill_path / f"{dist_id}.json"
            dist_file.write_text(
                json.dumps(dist_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            # 更新索引
            self.index["distill"][dist_id] = dist_data
            self._save_index()
            
            return dist_id
        
        else:
            raise ValueError(f"未知的记忆类型: {memory_type}")
    
    def update(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新记忆。
        
        Args:
            memory_id: 记忆ID
            updates: 更新字段
            
        Returns:
            是否成功
        """
        # 检查是否为案例
        if memory_id in self.index.get("cases", {}):
            case_data = self.index["cases"][memory_id]
            case_data.update(updates)
            case_data["updated_at"] = datetime.now().isoformat()
            
            # 更新文件
            case_file = self.cases_path / f"{memory_id}.json"
            case_file.write_text(
                json.dumps(case_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self._save_index()
            return True
        
        # 检查是否为蒸馏经验
        if memory_id in self.index.get("distill", {}):
            dist_data = self.index["distill"][memory_id]
            dist_data.update(updates)
            dist_data["updated_at"] = datetime.now().isoformat()
            
            dist_file = self.distill_path / f"{memory_id}.json"
            dist_file.write_text(
                json.dumps(dist_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self._save_index()
            return True
        
        return False
    
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单条记忆。
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            记忆内容，不存在返回None
        """
        if memory_id in self.index.get("cases", {}):
            case_file = self.cases_path / f"{memory_id}.json"
            if case_file.exists():
                return json.loads(case_file.read_text(encoding="utf-8"))
        
        if memory_id in self.index.get("distill", {}):
            dist_file = self.distill_path / f"{memory_id}.json"
            if dist_file.exists():
                return json.loads(dist_file.read_text(encoding="utf-8"))
        
        return None
    
    def stats(self) -> Dict[str, Any]:
        """
        统计信息。
        
        Returns:
            统计数据
        """
        cases = self.index.get("cases", {})
        distills = self.index.get("distill", {})
        
        # 按触发类型统计
        by_trigger_type = {}
        for case in cases.values():
            t = case.get("trigger_type", "unknown")
            by_trigger_type[t] = by_trigger_type.get(t, 0) + 1
        
        # 按严重程度统计
        by_severity = {}
        for case in cases.values():
            s = case.get("severity", "unknown")
            by_severity[s] = by_severity.get(s, 0) + 1
        
        # 按结果统计
        by_outcome = {}
        for case in cases.values():
            o = case.get("outcome", "unknown")
            by_outcome[o] = by_outcome.get(o, 0) + 1
        
        return {
            "memory_id": self.MEMORY_ID,
            "total_cases": len(cases),
            "total_distills": len(distills),
            "by_trigger_type": by_trigger_type,
            "by_severity": by_severity,
            "by_outcome": by_outcome,
            "last_updated": datetime.now().isoformat(),
        }
    
    def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict[str, Any]]:
        """
        蒸馏候选。
        
        返回可以上升为总记忆的经验候选。
        
        Args:
            min_quality: 最低质量等级
            limit: 最大返回数量
            
        Returns:
            候选列表
        """
        candidates = []
        
        for dist_id, dist_data in self.index.get("distill", {}).items():
            # 质量过滤
            quality = dist_data.get("quality_level", "C")
            quality_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
            if quality_order.get(quality, 4) > quality_order.get(min_quality, 3):
                continue
            
            candidates.append({
                "distill_id": dist_id,
                "content": dist_data.get("content", ""),
                "quality_level": quality,
                "source_cases": dist_data.get("source_cases", []),
                "ready_for_global": quality in ("S", "A", "B"),
            })
        
        # 按质量排序
        candidates.sort(key=lambda x: quality_order.get(x["quality_level"], 4))
        return candidates[:limit]
    
    def healthcheck(self) -> Dict[str, Any]:
        """
        健康检查。
        
        Returns:
            健康状态
        """
        return {
            "status": "healthy",
            "memory_id": self.MEMORY_ID,
            "storage_path": str(self.storage_path),
            "cases_count": len(self.index.get("cases", {})),
            "distills_count": len(self.index.get("distill", {})),
            "last_check": datetime.now().isoformat(),
        }
    
    # ========== 便捷方法 ==========
    
    def search_similar_cases(
        self,
        trigger_type: str,
        severity: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        搜索相似案例（便捷方法）。
        
        Args:
            trigger_type: 触发类型
            severity: 严重程度
            top_k: 返回数量
            
        Returns:
            相似案例列表
        """
        filters = {"trigger_type": trigger_type}
        if severity:
            filters["severity"] = severity
        
        return self.search(filters=filters, top_k=top_k)
    
    def run_distill_from_review(self, case_id: str, review_content: str) -> str:
        """
        从复盘生成蒸馏经验（便捷方法）。
        
        Args:
            case_id: 案例ID
            review_content: 复盘内容
            
        Returns:
            蒸馏经验ID
        """
        # 更新案例的复盘
        self.update(case_id, {"review": review_content})
        
        # 创建蒸馏经验
        case_data = self.get(case_id)
        dist_id = self.add({
            "memory_type": "distill",
            "content": review_content,
            "source_cases": [case_id],
            "quality_level": "C",  # 新创建的为C级，需验证
            "tags": case_data.get("tags", []) if case_data else [],
        })
        
        return dist_id


if __name__ == "__main__":
    # 演示用法
    mem = RiskMemoryInterface()
    
    # 添加案例
    case_id = mem.add({
        "memory_type": "case",
        "trigger_type": "drawdown",
        "severity": "critical",
        "context": {"system": "11-易经推理", "drawdown_pct": 15.5},
        "action_taken": "block",
        "outcome": "prevented_loss",
        "tags": ["爆仓预警", "回撤控制"],
    })
    print(f"✅ 添加案例: {case_id}")
    
    # 检索
    results = mem.search(filters={"severity": "critical"})
    print(f"🔍 检索结果: {len(results)} 条")
    
    # 统计
    stats = mem.stats()
    print(f"📊 统计: {stats['total_cases']} 案例, {stats['total_distills']} 蒸馏")
    
    # 健康检查
    health = mem.healthcheck()
    print(f"❤️  状态: {health['status']}")
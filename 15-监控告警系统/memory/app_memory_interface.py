#!/usr/bin/env python3
"""
运维应用记忆接口 — AM-OPS-001

遵循总记忆系统统一接口规范，实现7个标准接口 + 2个便捷方法。

应用记忆类型：
- incident: 故障/告警事件（如CPU飙升、服务宕机）
- resolution: 故障处理过程
- playbook: 运维预案/Playbook
- metric_baseline: 性能基线与异常模式

与总记忆系统关系：
- AM-OPS-001 作为 L2 应用记忆层
- 蒸馏后的经验可上升为 MU-DEV（开发记忆单元）的程序记忆
- 总记忆通过索引路由查询到本系统

用法：
    from memory.app_memory_interface import OpsMemoryInterface
    
    mem = OpsMemoryInterface()
    results = mem.search("CPU告警", filters={"severity": "critical"})
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Incident:
    """故障/告警事件"""
    incident_id: str
    incident_type: str  # cpu / memory / disk / network / service_down / data_quality
    severity: str  # critical / high / medium / low
    timestamp: str
    host: str  # 主机/节点名
    service: str  # 服务名
    symptoms: List[str]  # 症状描述
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    duration_minutes: Optional[int] = None
    impact: str = "unknown"  # none / minor / moderate / major / critical
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "incident_type": self.incident_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "host": self.host,
            "service": self.service,
            "symptoms": self.symptoms,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "duration_minutes": self.duration_minutes,
            "impact": self.impact,
            "tags": self.tags,
        }


@dataclass
class Playbook:
    """运维预案"""
    playbook_id: str
    name: str
    trigger_condition: str  # 触发条件
    steps: List[str]  # 处理步骤
    estimated_time_minutes: int
    required_access: List[str]  # 所需权限
    created_at: str
    last_used: Optional[str] = None
    usage_count: int = 0
    success_rate: float = 0.0
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "playbook_id": self.playbook_id,
            "name": self.name,
            "trigger_condition": self.trigger_condition,
            "steps": self.steps,
            "estimated_time_minutes": self.estimated_time_minutes,
            "required_access": self.required_access,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "tags": self.tags,
        }


class OpsMemoryInterface:
    """
    运维应用记忆接口
    
    实现总记忆系统定义的统一接口规范。
    """
    
    MEMORY_ID = "AM-OPS-001"
    MEMORY_NAME = "运维应用记忆"
    MEMORY_TYPE = "application"
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化运维记忆接口。
        
        Args:
            storage_path: 存储目录路径，默认为 15-监控告警系统/memory/
        """
        if storage_path is None:
            storage_path = Path(__file__).parent
        self.storage_path = Path(storage_path)
        
        # 确保目录存在
        self.incidents_path = self.storage_path / "incidents"
        self.playbooks_path = self.storage_path / "playbooks"
        self.baselines_path = self.storage_path / "baselines"
        
        for p in [self.incidents_path, self.playbooks_path, self.baselines_path]:
            p.mkdir(parents=True, exist_ok=True)
        
        # 加载索引
        self.index: Dict[str, dict] = self._load_index()
    
    def _load_index(self) -> Dict[str, dict]:
        """加载记忆索引。"""
        index_file = self.storage_path / "memory_index.json"
        if index_file.exists():
            return json.loads(index_file.read_text(encoding="utf-8"))
        return {"incidents": {}, "playbooks": {}, "baselines": {}}
    
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
            filters: 过滤条件（运维领域语义）
                - incident_type: cpu / memory / disk / network / service_down / data_quality
                - severity: critical / high / medium / low
                - host: 主机/节点名
                - service: 服务名
                - impact: none / minor / moderate / major / critical
            memory_type: 记忆类型（incident/playbook/baseline/all）
            top_k: 返回数量
            
        Returns:
            匹配的记忆列表
        """
        results = []
        filters = filters or {}
        
        # 搜索故障事件
        if memory_type in ("all", "incident"):
            for inc_id, inc_data in self.index.get("incidents", {}).items():
                if query:
                    query_lower = query.lower()
                    if not any(
                        query_lower in str(inc_data.get(k, "")).lower()
                        for k in ["incident_type", "host", "service", "symptoms"]
                    ):
                        continue
                
                if not self._match_filters(inc_data, filters):
                    continue
                
                results.append({
                    "memory_type": "incident",
                    "incident_id": inc_id,
                    **inc_data,
                })
        
        # 搜索运维预案
        if memory_type in ("all", "playbook"):
            for pb_id, pb_data in self.index.get("playbooks", {}).items():
                if query and query.lower() not in pb_data.get("name", "").lower():
                    continue
                
                results.append({
                    "memory_type": "playbook",
                    "playbook_id": pb_id,
                    **pb_data,
                })
        
        # 按时间戳排序
        results.sort(key=lambda x: x.get("timestamp", x.get("created_at", "")), reverse=True)
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
            memory_entry: 记忆条目
            
        Returns:
            记忆ID
        """
        memory_type = memory_entry.get("memory_type", "incident")
        
        if memory_type == "incident":
            incident = Incident(
                incident_id=memory_entry.get("incident_id", f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
                incident_type=memory_entry.get("incident_type", "unknown"),
                severity=memory_entry.get("severity", "medium"),
                timestamp=memory_entry.get("timestamp", datetime.now().isoformat()),
                host=memory_entry.get("host", "unknown"),
                service=memory_entry.get("service", "unknown"),
                symptoms=memory_entry.get("symptoms", []),
                root_cause=memory_entry.get("root_cause"),
                resolution=memory_entry.get("resolution"),
                duration_minutes=memory_entry.get("duration_minutes"),
                impact=memory_entry.get("impact", "unknown"),
                tags=memory_entry.get("tags", []),
            )
            
            inc_file = self.incidents_path / f"{incident.incident_id}.json"
            inc_file.write_text(
                json.dumps(incident.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self.index["incidents"][incident.incident_id] = incident.to_dict()
            self._save_index()
            
            return incident.incident_id
        
        elif memory_type == "playbook":
            playbook = Playbook(
                playbook_id=memory_entry.get("playbook_id", f"PB-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
                name=memory_entry.get("name", ""),
                trigger_condition=memory_entry.get("trigger_condition", ""),
                steps=memory_entry.get("steps", []),
                estimated_time_minutes=memory_entry.get("estimated_time_minutes", 0),
                required_access=memory_entry.get("required_access", []),
                created_at=datetime.now().isoformat(),
                tags=memory_entry.get("tags", []),
            )
            
            pb_file = self.playbooks_path / f"{playbook.playbook_id}.json"
            pb_file.write_text(
                json.dumps(playbook.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self.index["playbooks"][playbook.playbook_id] = playbook.to_dict()
            self._save_index()
            
            return playbook.playbook_id
        
        else:
            raise ValueError(f"未知的记忆类型: {memory_type}")
    
    def update(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """更新记忆。"""
        if memory_id in self.index.get("incidents", {}):
            inc_data = self.index["incidents"][memory_id]
            inc_data.update(updates)
            inc_data["updated_at"] = datetime.now().isoformat()
            
            inc_file = self.incidents_path / f"{memory_id}.json"
            inc_file.write_text(
                json.dumps(inc_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self._save_index()
            return True
        
        if memory_id in self.index.get("playbooks", {}):
            pb_data = self.index["playbooks"][memory_id]
            pb_data.update(updates)
            pb_data["updated_at"] = datetime.now().isoformat()
            
            pb_file = self.playbooks_path / f"{memory_id}.json"
            pb_file.write_text(
                json.dumps(pb_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            self._save_index()
            return True
        
        return False
    
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆。"""
        if memory_id in self.index.get("incidents", {}):
            inc_file = self.incidents_path / f"{memory_id}.json"
            if inc_file.exists():
                return json.loads(inc_file.read_text(encoding="utf-8"))
        
        if memory_id in self.index.get("playbooks", {}):
            pb_file = self.playbooks_path / f"{memory_id}.json"
            if pb_file.exists():
                return json.loads(pb_file.read_text(encoding="utf-8"))
        
        return None
    
    def stats(self) -> Dict[str, Any]:
        """统计信息。"""
        incidents = self.index.get("incidents", {})
        playbooks = self.index.get("playbooks", {})
        
        by_type = {}
        by_severity = {}
        by_impact = {}
        
        for inc in incidents.values():
            t = inc.get("incident_type", "unknown")
            s = inc.get("severity", "unknown")
            i = inc.get("impact", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            by_severity[s] = by_severity.get(s, 0) + 1
            by_impact[i] = by_impact.get(i, 0) + 1
        
        return {
            "memory_id": self.MEMORY_ID,
            "total_incidents": len(incidents),
            "total_playbooks": len(playbooks),
            "by_incident_type": by_type,
            "by_severity": by_severity,
            "by_impact": by_impact,
            "last_updated": datetime.now().isoformat(),
        }
    
    def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict[str, Any]]:
        """蒸馏候选。"""
        candidates = []
        
        for inc_id, inc_data in self.index.get("incidents", {}).items():
            if inc_data.get("resolution") and inc_data.get("root_cause"):
                candidates.append({
                    "incident_id": inc_id,
                    "content": f"{inc_data['incident_type']}: {inc_data['root_cause']} → {inc_data['resolution']}",
                    "source": inc_id,
                    "ready_for_global": inc_data.get("severity") in ("critical", "high"),
                })
        
        return candidates[:limit]
    
    def healthcheck(self) -> Dict[str, Any]:
        """健康检查。"""
        return {
            "status": "healthy",
            "memory_id": self.MEMORY_ID,
            "storage_path": str(self.storage_path),
            "incidents_count": len(self.index.get("incidents", {})),
            "playbooks_count": len(self.index.get("playbooks", {})),
            "last_check": datetime.now().isoformat(),
        }
    
    # ========== 便捷方法 ==========
    
    def find_playbook_for_incident(self, incident_type: str) -> List[Dict[str, Any]]:
        """
        为故障类型查找预案（便捷方法）。
        
        Args:
            incident_type: 故障类型
            
        Returns:
            匹配的预案列表
        """
        results = []
        for pb_id, pb_data in self.index.get("playbooks", {}).items():
            if incident_type.lower() in pb_data.get("trigger_condition", "").lower():
                results.append({
                    "playbook_id": pb_id,
                    **pb_data,
                })
        return results
    
    def record_incident_resolution(
        self,
        incident_id: str,
        resolution: str,
        root_cause: str,
    ) -> bool:
        """
        记录故障处理结果（便捷方法）。
        
        Args:
            incident_id: 故障ID
            resolution: 处理方案
            root_cause: 根因分析
            
        Returns:
            是否成功
        """
        return self.update(incident_id, {
            "resolution": resolution,
            "root_cause": root_cause,
            "resolved_at": datetime.now().isoformat(),
        })


if __name__ == "__main__":
    mem = OpsMemoryInterface()
    
    # 添加故障
    inc_id = mem.add({
        "memory_type": "incident",
        "incident_type": "cpu",
        "severity": "high",
        "host": "node-1",
        "service": "l3-scheduler",
        "symptoms": ["CPU使用率超过90%", "响应延迟增加"],
        "impact": "moderate",
        "tags": ["性能告警", "调度器"],
    })
    print(f"✅ 添加故障: {inc_id}")
    
    # 添加预案
    pb_id = mem.add({
        "memory_type": "playbook",
        "name": "CPU高负载处理预案",
        "trigger_condition": "cpu 使用率 > 85%",
        "steps": [
            "1. 检查进程CPU占用",
            "2. 分析是否为周期性高峰",
            "3. 降低调度频率或扩容",
        ],
        "estimated_time_minutes": 15,
        "required_access": ["ssh", "监控后台"],
        "tags": ["CPU", "性能优化"],
    })
    print(f"✅ 添加预案: {pb_id}")
    
    # 查找预案
    playbooks = mem.find_playbook_for_incident("cpu")
    print(f"🔍 找到 {len(playbooks)} 个预案")
    
    # 统计
    stats = mem.stats()
    print(f"📊 统计: {stats['total_incidents']} 故障, {stats['total_playbooks']} 预案")
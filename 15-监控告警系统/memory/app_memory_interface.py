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
    # ---- 统一接口所需元字段（质量/验证/置信度） ----
    quality_level: str = "C"
    verify_count: int = 0
    confidence: float = 0.0

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
            "quality_level": self.quality_level,
            "verify_count": self.verify_count,
            "confidence": self.confidence,
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
    # ---- 统一接口所需元字段（质量/验证/置信度） ----
    quality_level: str = "C"
    verify_count: int = 0
    confidence: float = 0.0

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
            "quality_level": self.quality_level,
            "verify_count": self.verify_count,
            "confidence": self.confidence,
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

        # 防御式：确保子目录存在（即使被外部清理也能重建）
        self.incidents_path.mkdir(parents=True, exist_ok=True)
        self.playbooks_path.mkdir(parents=True, exist_ok=True)
        self.baselines_path.mkdir(parents=True, exist_ok=True)

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
                quality_level=str(memory_entry.get("quality_level", "C")).upper(),
                verify_count=int(memory_entry.get("verify_count", 0)),
                confidence=float(memory_entry.get("confidence", 0.0)),
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
                last_used=memory_entry.get("last_used"),
                usage_count=int(memory_entry.get("usage_count", 0)),
                success_rate=float(memory_entry.get("success_rate", 0.0)),
                tags=memory_entry.get("tags", []),
                quality_level=str(memory_entry.get("quality_level", "C")).upper(),
                verify_count=int(memory_entry.get("verify_count", 0)),
                confidence=float(memory_entry.get("confidence", 0.0)),
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
    
    def distill_candidates(self, min_quality: str = "B", limit: int = 10) -> List[Dict[str, Any]]:
        """7标准接口补充：提取达阈值的 OPS 领域高价值候选，统一 8 字段返回。

        仅 incident（已解决，有 root_cause+resolution） + playbook（已用，success_rate 高） 两类。
        阈值矩阵与 DistillScheduler / VectorMemoryInterface 完全一致：
          S: verify≥10 & conf≥0.95 ;  A: ≥3 & ≥0.70 ;  B: ≥1 & ≥0.40
        """
        QUALITY_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        _TH: Dict[str, Dict[str, float]] = {
            "S": {"min_verifies": 10, "min_confidence": 0.95},
            "A": {"min_verifies": 3,  "min_confidence": 0.70},
            "B": {"min_verifies": 1,  "min_confidence": 0.40},
            "C": {"min_verifies": 0,  "min_confidence": 0.0},
            "D": {"min_verifies": 0,  "min_confidence": 0.0},
        }
        min_order = QUALITY_ORDER.get(str(min_quality).upper(), 2)

        candidates: List[Dict[str, Any]] = []

        # ---- bucket 1: incident（必须已闭环：有根因+方案） ----
        for inc_id, inc in self.index.get("incidents", {}).items():
            if not inc.get("root_cause") or not inc.get("resolution"):
                continue
            q = str(inc.get("quality_level") or inc.get("quality") or "C").upper()
            if q not in QUALITY_ORDER:
                q = "C"
            if QUALITY_ORDER[q] > min_order:
                continue
            vc = int(inc.get("verify_count") or 0)
            conf = float(inc.get("confidence") or 0.0)
            if conf <= 0.0:
                impact = str(inc.get("impact") or "").lower()
                sev = str(inc.get("severity") or "").lower()
                base = 0.40 if q == "B" else (0.70 if q == "A" else (0.95 if q == "S" else 0.25))
                # major/critical → 重大处置经验更有价值
                if impact in ("major", "critical"):
                    base = min(1.0, base + 0.15)
                if sev in ("critical", "high"):
                    base = min(1.0, base + 0.05)
                conf = base
            th = _TH.get(q) or _TH["C"]
            if q not in ("C", "D") and (vc < th["min_verifies"] or conf < th["min_confidence"]):
                continue
            content = (
                f"[{inc.get('incident_type', 'incident')}] {inc.get('root_cause', '')}"
                f" → {inc.get('resolution', '')}"
            )
            tags = list(inc.get("tags") or [])
            if inc.get("incident_type") and inc["incident_type"] not in tags:
                tags.append(str(inc["incident_type"]))
            sev = inc.get("severity")
            if sev and sev not in tags:
                tags.append(str(sev))
            source = f"AM-OPS/incident/{inc_id}"
            candidates.append({
                "id": str(inc_id),
                "content": content,
                "quality_level": q,
                "confidence": round(conf, 4),
                "verify_count": vc,
                "tags": tags,
                "memory_type": "incident",
                "source": source,
            })

        # ---- bucket 2: playbook（已实战使用且成功率≥0.6） ----
        for pb_id, pb in self.index.get("playbooks", {}).items():
            usage = int(pb.get("usage_count") or 0)
            if usage < 1:
                continue
            sr = float(pb.get("success_rate") or 0.0)
            if sr < 0.60:
                continue
            q = str(pb.get("quality_level") or pb.get("quality") or "C").upper()
            if q not in QUALITY_ORDER:
                q = "C"
            if QUALITY_ORDER[q] > min_order:
                continue
            vc = int(pb.get("verify_count") or 0)
            conf = float(pb.get("confidence") or max(sr, 0.50))
            th = _TH.get(q) or _TH["C"]
            if q not in ("C", "D") and (vc < th["min_verifies"] or conf < th["min_confidence"]):
                continue
            steps = pb.get("steps") or []
            steps_text = "; ".join(str(s) for s in steps[:6])
            content = (
                f"[playbook] {pb.get('name', '')} | 触发条件: {pb.get('trigger_condition', '')}"
                f" | 步骤: {steps_text}"
            )
            tags = list(pb.get("tags") or [])
            source = f"AM-OPS/playbook/{pb_id}"
            candidates.append({
                "id": str(pb_id),
                "content": content,
                "quality_level": q,
                "confidence": round(conf, 4),
                "verify_count": vc,
                "tags": tags,
                "memory_type": "playbook",
                "source": source,
            })

        candidates.sort(
            key=lambda c: (QUALITY_ORDER.get(c["quality_level"], 4),
                           -c["verify_count"],
                           -c["confidence"])
        )
        return candidates[: max(0, int(limit))]

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

    # ---------------- 底层辅助：供 run_distill_from_review 闭环使用 ----------------

    def increment_verify(self, memory_id: str) -> bool:
        """命中复盘关键词后 verify_count +1（A8 校验闭环）。"""
        cur = self.get(memory_id)
        if not cur:
            return False
        vc = int(cur.get("verify_count") or 0) + 1
        try:
            return self.update(memory_id, {"verify_count": vc})
        except Exception:
            return False

    def update_quality(self, memory_id: str, new_quality: str,
                       new_confidence: Optional[float] = None) -> bool:
        """调整质量等级 + 置信度（保守式）。"""
        updates: Dict[str, Any] = {"quality_level": new_quality}
        if new_confidence is not None:
            updates["confidence"] = float(new_confidence)
        try:
            return self.update(memory_id, updates)
        except Exception:
            return False

    # ========== 便捷方法 ==========
    
    def find_playbook_for_incident(self, incident_type: str) -> List[Dict[str, Any]]:
        """
        为故障类型查找预案（领域便捷方法，保留）。
        
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
        记录故障处理结果（领域便捷方法，保留）。
        
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

    # ---------------- 2 统一便捷方法（对齐 MEMORY_SYSTEM.md 签名） ----------------

    def search_similar_cases(
        self, content: str, top_k: int = 5, threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """统一签名：content/top_k/threshold，返回 id/score/metadata。"""
        try:
            raw_list = list(self.search(query=content, top_k=max(20, int(top_k) * 4)) or [])
        except Exception:
            raw_list = []

        normalized: List[Dict[str, Any]] = []
        for i, r in enumerate(raw_list):
            rid = (r.get("incident_id") or r.get("playbook_id")
                   or r.get("baseline_id") or r.get("memory_id") or str(i))
            sev = str(r.get("severity") or "").lower()
            impact = str(r.get("impact") or "").lower()
            # 评分：顺序平滑 + severity/impact 加成 + playbook usage/success_rate 加成
            base = max(0.0, 1.0 / (1.0 + i * 0.35))
            if sev == "critical":
                base = min(1.0, base + 0.12)
            elif sev == "high":
                base = min(1.0, base + 0.06)
            if impact in ("major", "critical"):
                base = min(1.0, base + 0.08)
            usage = int(r.get("usage_count") or 0)
            sr = float(r.get("success_rate") or 0.0)
            if usage >= 1 and sr >= 0.80:
                base = min(1.0, base + 0.10)
            elif usage >= 1 and sr >= 0.60:
                base = min(1.0, base + 0.05)
            if base < float(threshold):
                continue
            q = str(r.get("quality_level") or "C").upper()
            vc = int(r.get("verify_count") or 0)
            conf = float(r.get("confidence") or sr or 0.0)
            normalized.append({
                "id": str(rid),
                "score": round(base, 4),
                "metadata": {
                    "quality_level": q,
                    "confidence": conf,
                    "verify_count": vc,
                    "tags": list(r.get("tags") or []),
                    "memory_type": str(r.get("memory_type") or "incident"),
                    "raw": r,
                },
            })
            if len(normalized) >= int(top_k):
                break
        return normalized

    def run_distill_from_review(self, review_data: Dict[str, Any]) -> Dict[str, int]:
        """基于 OPS Review/A8 校验报告触发闭环，返回 processed/upgraded/skipped。"""
        import re as _re
        stats = {"processed": 0, "upgraded": 0, "skipped": 0}

        keywords: List[str] = []
        if isinstance(review_data, dict):
            for key in ("matched_patterns", "matched", "keywords", "hotspots",
                        "matched_functions", "doc_only_functions", "code_only_functions",
                        "hits", "symptoms"):
                val = review_data.get(key)
                if isinstance(val, list):
                    keywords.extend(str(v) for v in val if v)
            for txt_key in ("subsystem", "summary", "title", "focus", "review",
                            "incident_type", "severity", "impact", "host", "service",
                            "root_cause", "resolution", "content"):
                txt = review_data.get(txt_key)
                if isinstance(txt, str) and txt.strip():
                    keywords.extend(p for p in _re.split(r"\W+", txt) if len(p) >= 2)
        seen_kw: set = set()
        clean_kws: List[str] = []
        for kw in keywords:
            k = str(kw).strip()
            if len(k) < 2:
                continue
            kl = k.lower()
            if kl in seen_kw:
                continue
            seen_kw.add(kl)
            clean_kws.append(k)
        if not clean_kws:
            return stats

        unique_ids: set = set()
        hits: List[Dict[str, Any]] = []
        for kw in clean_kws:
            try:
                for r in (self.search(query=kw, top_k=3) or []):
                    rid = (r.get("incident_id") or r.get("playbook_id")
                           or r.get("baseline_id") or r.get("memory_id"))
                    if not rid or rid in unique_ids:
                        continue
                    unique_ids.add(rid)
                    hits.append(r)
            except Exception:
                continue

        upgrade_paths: Dict[str, Dict[str, Dict[str, float]]] = {
            "C": {"B": {"min_verifies": 1, "min_confidence": 0.40}},
            "B": {"A": {"min_verifies": 3, "min_confidence": 0.70}},
            "A": {"S": {"min_verifies": 10, "min_confidence": 0.95}},
        }
        target_conf = {"B": 0.50, "A": 0.78, "S": 0.96}

        for hit in hits:
            stats["processed"] += 1
            mem_id = (hit.get("incident_id") or hit.get("playbook_id")
                      or hit.get("baseline_id") or hit.get("memory_id"))
            if not mem_id:
                stats["skipped"] += 1
                continue
            if not self.increment_verify(str(mem_id)):
                stats["skipped"] += 1
                continue
            cur = self.get(str(mem_id))
            if not cur:
                stats["skipped"] += 1
                continue
            q = str(cur.get("quality_level") or cur.get("quality") or "C").upper()
            vc = int(cur.get("verify_count") or 0)
            conf = float(cur.get("confidence") or cur.get("success_rate") or 0.0)
            paths = upgrade_paths.get(q) or {}
            moved = False
            for target_q, th in paths.items():
                if vc >= th["min_verifies"] and conf >= th["min_confidence"]:
                    new_conf = max(conf, target_conf.get(target_q, conf))
                    if self.update_quality(str(mem_id), target_q, new_conf):
                        stats["upgraded"] += 1
                        moved = True
                    break
            if not moved:
                stats["skipped"] += 1
        return stats


# 别名：distill_scheduler 通过 getattr(module, "AppMemoryInterface") 查找
AppMemoryInterface = OpsMemoryInterface


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
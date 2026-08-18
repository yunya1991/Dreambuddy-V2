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
    # ---- 统一接口所需元字段（质量/验证/置信度） ----
    quality_level: str = "C"
    verify_count: int = 0
    confidence: float = 0.0

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
            "quality_level": self.quality_level,
            "verify_count": self.verify_count,
            "confidence": self.confidence,
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

        # 防御式：确保子目录存在（即使存储目录被子进程/外部清理也能重建）
        self.cases_path.mkdir(parents=True, exist_ok=True)
        self.distill_path.mkdir(parents=True, exist_ok=True)

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
                quality_level=str(memory_entry.get("quality_level", "C")).upper(),
                verify_count=int(memory_entry.get("verify_count", 0)),
                confidence=float(memory_entry.get("confidence", 0.0)),
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
                "quality_level": str(memory_entry.get("quality_level", "C")).upper(),
                "verify_count": int(memory_entry.get("verify_count", 0)),
                "confidence": float(memory_entry.get("confidence", 0.0)),
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
    
    # ---------------- 底层辅助：供 run_distill_from_review 闭环使用 ----------------

    def increment_verify(self, memory_id: str) -> bool:
        """命中复盘关键词后，verify_count +1（A8 校验闭环）。"""
        current = self.get(memory_id)
        if not current:
            return False
        vc = int(current.get("verify_count") or 0) + 1
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

    # ---------------- 7 标准接口：蒸馏候选提取（对齐 MEMORY_SYSTEM.md 签名） ----------------

    def distill_candidates(self, min_quality: str = "B", limit: int = 10) -> List[Dict[str, Any]]:
        """提取达阈值的高价值候选，统一 8 字段返回（cases + distill 双库扫描）。

        阈值矩阵（与 DistillScheduler / VectorMemoryInterface 一致）：
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
        # 合并 distill 桶 + cases 桶（案例有复盘/经验结论的也入选）
        pools: Dict[str, Dict[str, Dict[str, Any]]] = {
            "distill": self.index.get("distill", {}),
            "case": self.index.get("cases", {}),
        }
        for mtype, bucket in pools.items():
            for raw_id, raw in bucket.items():
                q = str(raw.get("quality_level") or raw.get("quality") or "C").upper()
                if q not in QUALITY_ORDER:
                    q = "C"
                if QUALITY_ORDER[q] > min_order:
                    continue
                vc = int(raw.get("verify_count") or 0)
                conf = float(raw.get("confidence") or 0.0)
                # 风控记忆 distill 可能没填 confidence：根据 severity / outcome 做兜底估值
                if conf <= 0.0:
                    sev = str(raw.get("severity") or "").lower()
                    out = str(raw.get("outcome") or "").lower()
                    base = 0.40 if q == "B" else (0.70 if q == "A" else (0.95 if q == "S" else 0.25))
                    if out == "prevented_loss":
                        base = min(1.0, base + 0.20)
                    elif out == "false_positive":
                        base = max(0.0, base - 0.15)
                    if sev == "critical":
                        base = min(1.0, base + 0.05)
                    conf = base
                th = _TH.get(q) or _TH["C"]
                if q not in ("C", "D") and (vc < th["min_verifies"] or conf < th["min_confidence"]):
                    continue
                # 内容字段：case 类取 review+lessons 合成，distill 类取 content
                if mtype == "case":
                    parts = []
                    if raw.get("review"):
                        parts.append(f"review: {raw['review']}")
                    if raw.get("lessons"):
                        parts.append("lessons: " + "; ".join(str(l) for l in raw["lessons"]))
                    if not parts:
                        # 无复盘/经验内容 → 不入选（避免噪声）
                        continue
                    content = " | ".join(parts)
                else:
                    content = str(raw.get("content") or "")
                    if len(content) < 6:
                        continue
                tags = list(raw.get("tags") or [])
                if raw.get("trigger_type") and raw["trigger_type"] not in tags:
                    tags.append(str(raw["trigger_type"]))
                source = f"AM-RSK/{mtype}/" + str(raw.get("distill_id") or raw.get("case_id") or raw_id)
                candidates.append({
                    "id": str(raw.get("distill_id") or raw.get("case_id") or raw_id),
                    "content": content,
                    "quality_level": q,
                    "confidence": round(conf, 4),
                    "verify_count": vc,
                    "tags": tags,
                    "memory_type": mtype,
                    "source": source,
                })

        candidates.sort(
            key=lambda c: (QUALITY_ORDER.get(c["quality_level"], 4),
                           -c["verify_count"],
                           -c["confidence"])
        )
        return candidates[: max(0, int(limit))]

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

    # ---------------- 2 便捷方法（对齐 MEMORY_SYSTEM.md 签名） ----------------

    def search_similar_cases(
        self, content: str, top_k: int = 5, threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """统一签名：content/top_k/threshold，返回 id/score/metadata 结构。"""
        # 用 query 全文检索（风控语义 trigger_type/severity 会自然命中 text 扫描）
        try:
            raw_list = list(self.search(query=content, top_k=max(20, int(top_k) * 4)) or [])
        except Exception:
            raw_list = []

        normalized: List[Dict[str, Any]] = []
        for i, r in enumerate(raw_list):
            rid = r.get("case_id") or r.get("distill_id") or r.get("memory_id") or str(i)
            # 评分：若 severity=critical/high → 加成，按序位置平滑
            sev = str(r.get("severity") or "").lower()
            base = max(0.0, 1.0 / (1.0 + i * 0.35))
            if sev == "critical":
                base = min(1.0, base + 0.12)
            elif sev == "high":
                base = min(1.0, base + 0.06)
            if base < float(threshold):
                continue
            q = str(r.get("quality_level") or "C").upper()
            vc = int(r.get("verify_count") or 0)
            conf = float(r.get("confidence") or 0.0)
            normalized.append({
                "id": str(rid),
                "score": round(base, 4),
                "metadata": {
                    "quality_level": q,
                    "confidence": conf,
                    "verify_count": vc,
                    "tags": list(r.get("tags") or []),
                    "memory_type": str(r.get("memory_type") or "case"),
                    "raw": r,
                },
            })
            if len(normalized) >= int(top_k):
                break
        return normalized

    def run_distill_from_review(self, review_data: Dict[str, Any]) -> Dict[str, int]:
        """基于 Review 触发 A8 蒸馏闭环，返回 processed/upgraded/skipped。"""
        import re as _re
        stats = {"processed": 0, "upgraded": 0, "skipped": 0}

        keywords: List[str] = []
        if isinstance(review_data, dict):
            for key in ("matched_patterns", "matched", "keywords", "hotspots",
                        "matched_functions", "doc_only_functions", "code_only_functions",
                        "hits", "source_cases", "lessons"):
                val = review_data.get(key)
                if isinstance(val, list):
                    keywords.extend(str(v) for v in val if v)
            for txt_key in ("subsystem", "summary", "title", "focus", "review",
                            "trigger_type", "severity", "outcome", "action_taken", "content"):
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
                    rid = r.get("case_id") or r.get("distill_id") or r.get("memory_id")
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
            mem_id = hit.get("case_id") or hit.get("distill_id") or hit.get("memory_id")
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
            conf = float(cur.get("confidence") or 0.0)
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
AppMemoryInterface = RiskMemoryInterface


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
"""
M6: 大师进化器 (Master Evolution)
基于研讨结果更新大师权重和风格
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

@dataclass
class EvolutionRecord:
    """进化记录"""
    timestamp: str
    seminar_id: str
    master_id: str
    old_weight: float
    new_weight: float
    reason: str
    adoption_rate: float = 0.0

@dataclass
class MasterEvolutionStats:
    """大师进化统计"""
    master_id: str
    total_seminars: int = 0
    avg_adoption_rate: float = 0.0
    weight_trend: str = "stable"  # increasing/stable/decreasing
    last_update: str = ""
    strong_regimes: List[str] = field(default_factory=list)
    weak_regimes: List[str] = field(default_factory=list)


class MasterEvolution:
    """
    大师进化器
    
    职责:
    1. 基于研讨结果更新大师权重
    2. 追踪大师表现
    3. 调整大师风格标签
    4. 生成进化报告
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = str(Path.home() / ".workbuddy" / "skills" / "master-seminar" / "data")
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.evolution_file = self.data_dir / "evolution_records.json"
        self.stats_file = self.data_dir / "master_stats.json"
        
        self.evolution_records = self._load_evolution_records()
        self.master_stats = self._load_master_stats()
        
        # 从大师选择器获取初始权重
        from M2_master_selector import MASTERS
        self.masters = {m.id: m for m in MASTERS.values()}
    
    def _load_evolution_records(self) -> List[Dict]:
        """加载进化记录"""
        if self.evolution_file.exists():
            return json.loads(self.evolution_file.read_text())
        return []
    
    def _load_master_stats(self) -> Dict[str, Dict]:
        """加载大师统计"""
        if self.stats_file.exists():
            return json.loads(self.stats_file.read_text())
        
        # 初始化统计
        stats = {}
        for master_id in ["soros", "druckenmiller", "buffett", "ptj", "dalio",
                         "livermore", "tharp", "oneil", "talmans", "michele"]:
            stats[master_id] = {
                "total_seminars": 0,
                "total_adoptions": 0,
                "weight_history": [1.0],
                "regime_performance": defaultdict(int)
            }
        return stats
    
    def _save_evolution_records(self):
        """保存进化记录"""
        self.evolution_file.write_text(json.dumps(self.evolution_records, indent=2, ensure_ascii=False))
    
    def _save_master_stats(self):
        """保存大师统计"""
        self.stats_file.write_text(json.dumps(self.master_stats, indent=2, ensure_ascii=False))
    
    def update(self,
              seminar_results: Dict,
              masters: List[str],
              regime: str = "") -> Dict[str, Any]:
        """
        基于研讨结果更新大师
        
        Args:
            seminar_results: 研讨结论
            masters: 参与大师列表
            regime: 当前Regime
            
        Returns:
            进化更新记录
        """
        conclusions = seminar_results.get("conclusions", {})
        adoption_rate = conclusions.get("confidence", 0.5)
        bias = conclusions.get("bias", 0)
        
        updates = {}
        
        for master_id in masters:
            if master_id not in self.masters:
                continue
            
            # 获取大师阵营
            master = self.masters[master_id]
            
            # 计算采纳率
            master_adoption = self._calculate_adoption(
                master_id, master.camp, bias, adoption_rate
            )
            
            # 更新权重
            old_weight = master.weight
            new_weight = self._adjust_weight(
                current_weight=old_weight,
                adoption_rate=master_adoption,
                camp=master.camp,
                bias=bias
            )
            
            # 记录进化
            record = {
                "timestamp": datetime.now().isoformat(),
                "seminar_id": seminar_results.get("seminar_id", ""),
                "master_id": master_id,
                "old_weight": old_weight,
                "new_weight": new_weight,
                "reason": self._get_evolution_reason(master_adoption, master.camp, bias),
                "adoption_rate": master_adoption
            }
            self.evolution_records.append(record)
            
            # 更新统计
            self._update_stats(master_id, master_adoption, regime)
            
            # 更新大师权重
            master.weight = new_weight
            
            updates[master_id] = {
                "old_weight": old_weight,
                "new_weight": new_weight,
                "change": new_weight - old_weight,
                "adoption_rate": master_adoption
            }
        
        # 保存记录
        self._save_evolution_records()
        self._save_master_stats()
        
        return updates
    
    def _calculate_adoption(self,
                           master_id: str,
                           camp: str,
                           bias: float,
                           agreement: float) -> float:
        """
        计算大师建议采纳率
        
        规则:
        - 与结论方向一致的大师 → 高采纳率
        - 与结论方向相反的大师 → 低采纳率
        - 高一致性研讨 → 大师整体采纳率高
        """
        # 阵营倾向
        camp_bias = {"bullish": 1, "neutral": 0, "bearish": -1}.get(camp, 0)
        
        # 方向一致加分
        direction_match = 1.0 if (camp_bias * bias >= 0) else 0.3
        
        # 基础采纳率 = 研讨一致性 * 方向匹配
        adoption = agreement * 0.6 + direction_match * 0.4
        
        return min(1.0, max(0.0, adoption))
    
    def _adjust_weight(self,
                      current_weight: float,
                      adoption_rate: float,
                      camp: str,
                      bias: float) -> float:
        """
        调整大师权重
        
        规则:
        - 采纳率 > 0.7 → 权重+10%
        - 采纳率 < 0.4 → 权重-10%
        - 权重范围: 0.1 ~ 2.0
        """
        if adoption_rate > 0.7:
            change = 0.1
        elif adoption_rate < 0.4:
            change = -0.1
        else:
            change = 0.0
        
        new_weight = current_weight * (1 + change)
        
        # 边界约束
        return max(0.1, min(2.0, new_weight))
    
    def _get_evolution_reason(self,
                              adoption_rate: float,
                              camp: str,
                              bias: float) -> str:
        """获取进化原因"""
        if adoption_rate > 0.7:
            return f"建议被高度采纳({adoption_rate:.0%})，权重上调"
        elif adoption_rate < 0.4:
            return f"建议采纳率低({adoption_rate:.0%})，权重下调"
        else:
            return f"建议采纳率中等({adoption_rate:.0%})，权重保持"
    
    def _update_stats(self, master_id: str, adoption_rate: float, regime: str):
        """更新大师统计"""
        if master_id not in self.master_stats:
            self.master_stats[master_id] = {
                "total_seminars": 0,
                "total_adoptions": 0.0,
                "weight_history": [1.0],
                "regime_performance": {}
            }
        
        stats = self.master_stats[master_id]
        stats["total_seminars"] += 1
        stats["total_adoptions"] += adoption_rate
        stats["avg_adoption"] = stats["total_adoptions"] / stats["total_seminars"]
        
        if regime:
            perf = stats["regime_performance"]
            if regime not in perf:
                perf[regime] = {"total": 0, "adoptions": 0.0}
            perf[regime]["total"] += 1
            perf[regime]["adoptions"] += adoption_rate
        
        # 更新权重历史
        if master_id in self.masters:
            stats["weight_history"].append(self.masters[master_id].weight)
            # 只保留最近10次
            stats["weight_history"] = stats["weight_history"][-10:]
    
    def get_master_weight(self, master_id: str) -> float:
        """获取大师当前权重"""
        if master_id in self.masters:
            return self.masters[master_id].weight
        return 1.0
    
    def get_master_stats(self, master_id: str) -> Dict:
        """获取大师统计"""
        return self.master_stats.get(master_id, {})
    
    def get_all_weights(self) -> Dict[str, float]:
        """获取所有大师权重"""
        return {mid: m.weight for mid, m in self.masters.items()}
    
    def get_weight_report(self) -> str:
        """生成权重报告"""
        lines = ["## 大师权重报告\n"]
        lines.append(f"生成时间: {datetime.now().isoformat()}\n")
        lines.append("| 大师 | 当前权重 | 状态 | 参与次数 | 平均采纳率 |")
        lines.append("|:---|:---:|:---|:---:|:---:|")
        
        for master_id in sorted(self.masters.keys()):
            master = self.masters[master_id]
            stats = self.master_stats.get(master_id, {})
            
            status = "⬆️上升" if master.weight > 1.0 else ("⬇️下降" if master.weight < 1.0 else "➡️稳定")
            total = stats.get("total_seminars", 0)
            avg = stats.get("avg_adoption", 0)
            
            lines.append(f"| {master.name} | {master.weight:.2f} | {status} | {total} | {avg:.0%} |")
        
        return "\n".join(lines)

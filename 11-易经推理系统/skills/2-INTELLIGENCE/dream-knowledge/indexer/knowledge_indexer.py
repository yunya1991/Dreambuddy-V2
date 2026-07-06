#!/usr/bin/env python3
"""
知识库索引器 | Knowledge Indexer
================================

核心功能:
1. 维护评分索引 (S/A/B/C级)
2. 快速检索
3. 知识库统计
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class KnowledgeIndexer:
    """知识索引器"""
    
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.kb_path = Path(workspace) / ".knowledge_base"
        self.scores_path = self.kb_path / "scores"
        self.scores_path.mkdir(parents=True, exist_ok=True)
        
        # 索引文件
        self.index_files = {
            "S": self.scores_path / "S_rank.json",
            "A": self.scores_path / "A_rank.json",
            "B": self.scores_path / "B_rank.json",
            "C": self.scores_path / "C_rank.json",
            "pending": self.scores_path / "pending.json",
            "all": self.scores_path / "all_index.json"
        }
        
        # 初始化
        self._init_indexes()
    
    def _init_indexes(self):
        """初始化索引文件"""
        for tier, path in self.index_files.items():
            if not path.exists():
                with open(path, "w") as f:
                    json.dump({
                        "tier": tier,
                        "updated": datetime.now().strftime("%Y-%m-%d"),
                        "entries": []
                    }, f, indent=2, ensure_ascii=False)
    
    def add_entry(self, entry: Dict) -> bool:
        """
        添加知识条目到索引
        
        Args:
            entry: {
                "id": "xxx",
                "name": "策略名",
                "type": "strategy",
                "regime": ["RANGE_BOUND"],
                "tool_type": "grid",
                "score": 75,
                "tier": "A",
                "source": "联网搜索",
                "path": "2_classic_strategies/by_regime/RANGE_BOUND/grid.md",
                "created": "2026-04-27",
                "verifications": 2
            }
        """
        tier = entry.get("tier", "C")
        
        # 更新对应等级的索引
        self._add_to_tier_index(tier, entry)
        
        # 更新总索引
        self._add_to_all_index(entry)
        
        # 更新待评估队列
        if entry.get("verifications", 0) == 0:
            self._add_to_pending(entry)
        
        return True
    
    def _add_to_tier_index(self, tier: str, entry: Dict):
        """添加到等级索引"""
        path = self.index_files.get(tier)
        if not path:
            return
        
        data = self._load_json(path)
        entries = data.get("entries", [])
        
        # 检查是否已存在
        existing_ids = [e.get("id") for e in entries]
        if entry["id"] not in existing_ids:
            entries.append(entry)
            entries.sort(key=lambda x: x.get("score", 0), reverse=True)
            data["entries"] = entries
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._save_json(path, data)
    
    def _add_to_all_index(self, entry: Dict):
        """添加到总索引"""
        path = self.index_files["all"]
        data = self._load_json(path)
        entries = data.get("entries", [])
        
        existing_ids = [e.get("id") for e in entries]
        if entry["id"] not in existing_ids:
            entries.append(entry)
            entries.sort(key=lambda x: x.get("score", 0), reverse=True)
            data["entries"] = entries
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._save_json(path, data)
    
    def _add_to_pending(self, entry: Dict):
        """添加到待评估队列"""
        path = self.index_files["pending"]
        data = self._load_json(path)
        entries = data.get("entries", [])
        
        existing_ids = [e.get("id") for e in entries]
        if entry["id"] not in existing_ids:
            entries.append(entry)
            data["entries"] = entries
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._save_json(path, data)
    
    def remove_entry(self, entry_id: str) -> bool:
        """从所有索引中移除条目"""
        for tier, path in self.index_files.items():
            data = self._load_json(path)
            entries = data.get("entries", [])
            original_len = len(entries)
            entries = [e for e in entries if e.get("id") != entry_id]
            if len(entries) < original_len:
                data["entries"] = entries
                data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                self._save_json(path, data)
        return True
    
    def update_tier(self, entry_id: str, old_tier: str, new_tier: str, new_score: int):
        """更新条目等级"""
        # 从旧等级移除
        self._remove_from_tier_index(old_tier, entry_id)
        
        # 添加到新等级
        all_data = self._load_json(self.index_files["all"])
        entry = next((e for e in all_data.get("entries", []) if e.get("id") == entry_id), None)
        if entry:
            entry["tier"] = new_tier
            entry["score"] = new_score
            self._add_to_tier_index(new_tier, entry)
    
    def _remove_from_tier_index(self, tier: str, entry_id: str):
        """从等级索引中移除"""
        path = self.index_files.get(tier)
        if not path:
            return
        
        data = self._load_json(path)
        entries = data.get("entries", [])
        entries = [e for e in entries if e.get("id") != entry_id]
        data["entries"] = entries
        data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save_json(path, data)
    
    def search(self, 
               regime: Optional[str] = None,
               tool_type: Optional[str] = None,
               min_score: int = 0,
               tier: Optional[str] = None,
               limit: int = 10) -> List[Dict]:
        """
        搜索知识条目
        
        Args:
            regime: Regime类型
            tool_type: 工具类型
            min_score: 最低分数
            tier: 指定等级
            limit: 返回数量
        
        Returns:
            匹配的知识条目列表
        """
        # 确定搜索范围
        if tier:
            data = self._load_json(self.index_files.get(tier, self.index_files["all"]))
        else:
            data = self._load_json(self.index_files["all"])
        
        results = []
        for entry in data.get("entries", []):
            # 过滤条件
            if entry.get("score", 0) < min_score:
                continue
            if regime and regime not in entry.get("regime", []):
                continue
            if tool_type and tool_type not in entry.get("tool_type", ""):
                continue
            if entry.get("status") == "deprecated":
                continue
            
            results.append(entry)
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_top_by_regime(self, regime: str, limit: int = 5) -> List[Dict]:
        """获取某Regime下的高分策略"""
        return self.search(regime=regime, min_score=60, limit=limit)
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        stats = {
            "total": 0,
            "by_tier": {"S": 0, "A": 0, "B": 0, "C": 0},
            "by_type": {"strategy": 0, "tool": 0},
            "by_regime": {},
            "pending": 0,
            "updated": ""
        }
        
        all_data = self._load_json(self.index_files["all"])
        pending_data = self._load_json(self.index_files["pending"])
        
        stats["total"] = len(all_data.get("entries", []))
        stats["pending"] = len(pending_data.get("entries", []))
        stats["updated"] = all_data.get("updated", "")
        
        for entry in all_data.get("entries", []):
            # 按等级
            tier = entry.get("tier", "C")
            if tier in stats["by_tier"]:
                stats["by_tier"][tier] += 1
            
            # 按类型
            entry_type = entry.get("type", "strategy")
            if entry_type in stats["by_type"]:
                stats["by_type"][entry_type] += 1
            
            # 按Regime
            for r in entry.get("regime", []):
                stats["by_regime"][r] = stats["by_regime"].get(r, 0) + 1
        
        return stats
    
    def generate_report(self) -> str:
        """生成索引报告"""
        stats = self.get_statistics()
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║                    知识库索引报告                             ║
╠══════════════════════════════════════════════════════════════╣
║ 总条目数: {stats['total']}
║ 待评估: {stats['pending']}
║ 最后更新: {stats['updated']}
╠══════════════════════════════════════════════════════════════╣
║ 【等级分布】
║   S级 ⭐⭐⭐: {stats['by_tier']['S']}
║   A级 ⭐⭐: {stats['by_tier']['A']}
║   B级 ⭐: {stats['by_tier']['B']}
║   C级 ❌: {stats['by_tier']['C']}
╠══════════════════════════════════════════════════════════════╣
║ 【类型分布】
║   策略: {stats['by_type']['strategy']}
║   工具: {stats['by_type']['tool']}
╠══════════════════════════════════════════════════════════════╣
║ 【Regime分布】
"""
        for regime, count in sorted(stats["by_regime"].items(), key=lambda x: -x[1]):
            report += f"║   {regime}: {count}\n"
        
        report += "╚══════════════════════════════════════════════════════════════╝"
        
        return report
    
    def _load_json(self, path: Path) -> Dict:
        """加载JSON文件"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"entries": [], "updated": ""}
    
    def _save_json(self, path: Path, data: Dict):
        """保存JSON文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ============== 主函数 ==============

def main():
    """测试索引器"""
    workspace = "/Users/zhangjiangtao/WorkBuddy/20260415144304"
    indexer = KnowledgeIndexer(workspace)
    
    # 测试添加
    test_entry = {
        "id": "test_001",
        "name": "网格策略",
        "type": "strategy",
        "regime": ["RANGE_BOUND"],
        "tool_type": "grid",
        "score": 75,
        "tier": "A",
        "source": "联网搜索",
        "path": "2_classic_strategies/by_regime/RANGE_BOUND/grid.md",
        "created": "2026-04-27",
        "verifications": 2
    }
    
    indexer.add_entry(test_entry)
    
    # 测试搜索
    results = indexer.search(regime="RANGE_BOUND", min_score=60)
    print(f"搜索结果: {len(results)}条")
    
    # 输出报告
    print(indexer.generate_report())


if __name__ == "__main__":
    main()

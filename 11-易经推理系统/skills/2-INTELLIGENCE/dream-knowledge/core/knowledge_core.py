#!/usr/bin/env python3
"""
知识库核心 | Knowledge Core
===========================

整合评分引擎和索引器，提供统一的知识管理接口
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 添加路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluator.scoring_engine import KnowledgeScorer, KnowledgeEntry
from indexer.knowledge_indexer import KnowledgeIndexer


class KnowledgeCore:
    """知识库核心"""
    
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.kb_path = Path(workspace) / ".knowledge_base"
        self.scorer = KnowledgeScorer()
        self.indexer = KnowledgeIndexer(workspace)
        
        # 路径映射
        self.path_mapping = {
            "strategy": "2_classic_strategies",
            "tool": "3_trading_tools"
        }
    
    # ============== 知识沉淀 ==============
    
    def save_knowledge(self, content: Dict) -> Tuple[bool, str]:
        """
        保存知识到知识库
        
        Args:
            content: 知识内容
            
        Returns:
            (成功标志, 报告)
        """
        # 1. 评估评分
        entry = self.scorer.evaluate_from_content(content)
        
        # 2. 确定保存路径
        base_path = self.path_mapping.get(entry.type, "2_classic_strategies")
        
        if entry.type == "strategy":
            regime_dir = entry.regime[0] if entry.regime else "UNCATEGORIZED"
            save_path = self.kb_path / base_path / "by_regime" / regime_dir / f"{entry.name}.md"
        else:
            category = content.get("category", "general")
            save_path = self.kb_path / base_path / category / f"{entry.name}.md"
        
        # 确保目录存在
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 3. 生成文档
        doc = self._generate_doc(entry)
        
        # 4. 保存文件
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(doc)
        
        # 5. 更新索引
        index_entry = {
            "id": entry.id,
            "name": entry.name,
            "type": entry.type,
            "regime": entry.regime,
            "tool_type": entry.tool_type,
            "score": entry.score,
            "tier": entry.tier,
            "source": entry.source,
            "path": str(save_path.relative_to(self.kb_path)),
            "created": entry.created,
            "verifications": entry.verifications
        }
        self.indexer.add_entry(index_entry)
        
        # 6. 生成报告
        report = f"""
✅ 知识入库成功

名称: {entry.name}
类型: {entry.type}
Regime: {', '.join(entry.regime)}
路径: {save_path}

{self.scorer.generate_report(entry)}
"""
        
        return True, report
    
    def _generate_doc(self, entry: KnowledgeEntry) -> str:
        """生成Markdown文档"""
        evidence_lines = []
        for e in entry.evidence_chain:
            evidence_lines.append(f"  - type: {e.type}")
            if e.episode_id:
                evidence_lines.append(f"    episode: {e.episode_id}")
            if e.result:
                evidence_lines.append(f"    result: {e.result}")
            evidence_lines.append(f"    date: {e.date}")
        
        doc = f"""---
name: {entry.name}
type: {entry.type}
id: {entry.id}
regime: {entry.regime}
tool_type: {entry.tool_type}
score: {entry.score}
tier: {entry.tier}
source: {entry.source}
created: {entry.created}
updated: {entry.updated}
verifications: {entry.verifications}
status: {entry.status}

scoring:
  logic_completeness: {entry.logic_completeness}/10
  parameter_clarity: {entry.parameter_clarity}/10
  executability: {entry.executability}/10
  historical_win_rate: {entry.historical_win_rate}/20
  risk_reward_ratio: {entry.risk_reward_ratio}/10
  practice_count: {entry.practice_count}/10
  regime_coverage: {entry.regime_coverage}/10
  tool_compatibility: {entry.tool_compatibility}/5
  optimization_space: {entry.optimization_space}/10
  extensibility: {entry.extensibility}/5

evidence_chain:
{chr(10).join(evidence_lines) if evidence_lines else "  []"}
---

# {entry.name}

## 评分详情

| 维度 | 得分 | 说明 |
|:---|:---:|:---|
| 逻辑完整性 | {entry.logic_completeness}/10 | 入场/出场/风控逻辑 |
| 参数明确性 | {entry.parameter_clarity}/10 | 参数是否明确 |
| 可执行性 | {entry.executability}/10 | 是否可执行 |
| 历史胜率 | {entry.historical_win_rate}/20 | 历史验证 |
| 风险收益 | {entry.risk_reward_ratio}/10 | RR比 |
| 实战次数 | {entry.practice_count}/10 | 验证次数 |

**总分**: {entry.score}/100 | **等级**: {entry.tier}级

## 策略概述

{entry.summary}

## 适用条件

- Regime: {', '.join(entry.regime) if entry.regime else '未指定'}
- 工具类型: {entry.tool_type}

## 入场规则

{entry.entry_rules}

## 出场规则

{entry.exit_rules}

## 风险管理

{entry.risk_management}

## 实践记录

{entry.practice_records}

## 优化历史

{entry.optimization_history}
"""
        return doc
    
    # ============== 知识检索 ==============
    
    def search_knowledge(self, 
                        regime: Optional[str] = None,
                        tool_type: Optional[str] = None,
                        min_score: int = 0,
                        limit: int = 5) -> List[Dict]:
        """
        检索知识
        
        Args:
            regime: Regime类型
            tool_type: 工具类型
            min_score: 最低分数
            limit: 返回数量
            
        Returns:
            匹配的知识列表
        """
        results = self.indexer.search(
            regime=regime,
            tool_type=tool_type,
            min_score=min_score,
            limit=limit
        )
        
        # 格式化输出
        formatted = []
        for r in results:
            formatted.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "regime": r.get("regime"),
                "score": r.get("score"),
                "tier": r.get("tier"),
                "source": r.get("source"),
                "path": r.get("path"),
                "verifications": r.get("verifications", 0)
            })
        
        return formatted
    
    # ============== 知识进化 ==============
    
    def evolve_knowledge(self, 
                        knowledge_id: str,
                        result: str,
                        episode_id: str = "",
                        notes: str = "") -> Tuple[bool, str]:
        """
        根据实践结果进化知识
        
        Args:
            knowledge_id: 知识ID
            result: success / partial / failure
            episode_id: 关联episode
            notes: 备注
            
        Returns:
            (成功标志, 报告)
        """
        # 查找知识
        all_data = self.indexer._load_json(self.indexer.index_files["all"])
        entry = None
        for e in all_data.get("entries", []):
            if e.get("id") == knowledge_id:
                entry = e
                break
        
        if not entry:
            return False, f"❌ 未找到知识: {knowledge_id}"
        
        # 加载完整文档
        path = self.kb_path / entry.get("path", "")
        if not path.exists():
            return False, f"❌ 文档不存在: {path}"
        
        # 更新评分
        old_score = entry.get("score", 0)
        old_tier = entry.get("tier", "C")
        
        # 模拟调整
        if result == "success":
            new_score = min(100, old_score + 5)
        elif result == "partial":
            new_score = old_score
        else:
            new_score = max(0, old_score - 10)
        
        new_tier = self.scorer._calculate_tier(new_score)
        
        # 更新索引
        self.indexer.update_tier(knowledge_id, old_tier, new_tier, new_score)
        
        # 更新文档
        content = path.read_text(encoding="utf-8")
        content = content.replace(
            f"score: {old_score}",
            f"score: {new_score}"
        )
        content = content.replace(
            f"tier: {old_tier}",
            f"tier: {new_tier}"
        )
        content = content.replace(
            f"updated: {entry.get('updated', '')}",
            f"updated: {datetime.now().strftime('%Y-%m-%d')}"
        )
        
        # 添加证据
        evidence_addition = f"""
  - type: practice
    episode_id: {episode_id}
    result: {result}
    date: {datetime.now().strftime('%Y-%m-%d')}
    notes: {notes}
"""
        content = content.replace("evidence_chain:\n  []", f"evidence_chain:\n{evidence_addition}")
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        report = f"""
✅ 知识进化成功

名称: {entry.get('name')}
ID: {knowledge_id}

评分变化: {old_score} → {new_score} ({'+' if new_score > old_score else ''}{new_score - old_score})
等级变化: {old_tier}级 → {new_tier}级

证据链已更新:
- 类型: practice
- 结果: {result}
- Episode: {episode_id}
"""
        
        return True, report
    
    # ============== 统计和维护 ==============
    
    def get_statistics(self) -> Dict:
        """获取统计"""
        return self.indexer.get_statistics()
    
    def generate_report(self) -> str:
        """生成完整报告"""
        stats = self.indexer.get_statistics()
        return self.indexer.generate_report()


# ============== 主函数 ==============

def main():
    """测试知识库核心"""
    workspace = "/Users/zhangjiangtao/WorkBuddy/20260415144304"
    core = KnowledgeCore(workspace)
    
    # 测试统计
    print(core.generate_report())
    
    # 测试检索
    print("\n=== 检索RANGE_BOUND策略 ===")
    results = core.search_knowledge(regime="RANGE_BOUND", min_score=50)
    for r in results:
        print(f"- {r['name']} (评分: {r['score']})")


if __name__ == "__main__":
    main()

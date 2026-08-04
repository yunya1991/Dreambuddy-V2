#!/usr/bin/env python3
"""
严格贝叶斯记忆更新器 — RigorousBayesianMemoryUpdater

数学严谨的三大优化：
1. Beta分布动态似然度：替代固定0.95/0.05，每次成功/失败更新α/β参数
   - E[P(成功|记忆为真)] = alpha / (alpha + beta)
   - 初始 Beta(1,1) → 均匀分布，无信息先验
   
2. 全概率公式证据P(B)：替代固定0.8/0.2
   - P(成功) = P(成功|真)×P(真) + P(成功|假)×P(假)
   - P(成功|假) = base_success_rate (默认0.5，可配置)
   
3. 指数衰减遗忘因子（基于记忆年龄）：替代经验衰减因子
   - forget_factor = exp(-λ × age / half_life),  λ=ln2
   - new_conf = ff × posterior + (1-ff) × 0.5
   - S级半衰365天，A级180天，B级90天，C级30天，D级15天

核心公式（与经典贝叶斯完全一致）：
  P(记忆为真 | 观察) = P(观察 | 记忆为真) × P(记忆为真) / P(观察)
"""

import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class MemoryEntry:
    """
    记忆条目 — 严格贝叶斯版
    
    新增字段：
      beta_alpha: int  — Beta分布α参数 (成功次数 + 1 伪计数)
      beta_beta:  int  — Beta分布β参数 (失败次数 + 1 伪计数)
      created_at: str  — 记忆创建时间ISO格式 (用于年龄遗忘计算)
    """
    memory_id: str
    content: str
    category: str  # principle / methodology / architecture / lesson
    confidence: float = 0.5  # P(记忆为真) 的点估计
    quality_level: str = "C"  # S/A/B/C/D
    verify_count: int = 0     # 成功验证次数
    conflict_count: int = 0   # 冲突/失败次数
    
    # 新字段1：Beta分布参数 (替代固定似然度)
    beta_alpha: int = 1  # α = 1 + verify_count_pseudo
    beta_beta: int = 1   # β = 1 + conflict_count_pseudo
    
    # 新字段2：记忆创建时间 (用于年龄遗忘)
    created_at: str = ""
    last_updated: str = ""
    
    source: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "category": self.category,
            "confidence": round(self.confidence, 6),
            "quality_level": self.quality_level,
            "verify_count": self.verify_count,
            "conflict_count": self.conflict_count,
            "beta_alpha": self.beta_alpha,
            "beta_beta": self.beta_beta,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "source": self.source,
            "tags": self.tags,
        }


class BayesianMemoryUpdater:
    """
    严格数学贝叶斯记忆更新器
    
    三大严格化改进：
      [1] Beta-Binomial 共轭似然度
      [2] Law of Total Probability 证据展开
      [3] Exponential Decay 指数遗忘 (基于半衰周期)
    """
    
    # ===== 等级阈值 (保持原有设计，验证次数门槛防止过拟合) =====
    QUALITY_THRESHOLDS = {
        "S": 0.95,
        "A": 0.70,
        "B": 0.40,
        "C": 0.00,
    }
    VERIFY_THRESHOLDS = {
        "S": 10,
        "A": 3,
        "B": 1,
        "C": 0,
    }
    
    # ===== 优化点3：各质量等级的半衰周期 (天) =====
    # 经验知识半衰期更长 (更稳定，不容易过时)
    HALF_LIFE_DAYS = {
        "S": 365,   # 公理级：1年 (几乎不变)
        "A": 180,   # 可信级：半年
        "B": 90,    # 待验证：3个月
        "C": 30,    # 假设级：1个月 (快速过时)
        "D": 15,    # 已证伪：2周 (快速遗忘)
    }
    
    # 遗忘公式的 lambda = ln(2)，保证 age=half_life → forget=0.5
    _FORGET_LAMBDA = math.log(2)
    
    # ===== 优化点2：记忆为假时的随机成功概率 =====
    # 即 P(观察成功 | 记忆为假) — 没有记忆指导，纯靠随机的成功率
    base_success_rate: float = 0.5
    
    def __init__(self, memory_unit_path):
        self.memory_unit_path = Path(memory_unit_path)
        self.memories: Dict[str, MemoryEntry] = {}
        self._file_lock = threading.Lock()
        self._load_memories()
    
    # ============================================================
    #  加载 / 保存 + 向后兼容 (优化点4：旧JSON自动补默认)
    # ============================================================
    
    def _load_memories(self):
        memory_file = self.memory_unit_path / "bayesian_memories.json"
        if not memory_file.exists():
            return
        
        data = json.loads(memory_file.read_text(encoding="utf-8"))
        for item in data.get("memories", []):
            # === 兼容旧版：没有 beta_alpha/beta_beta 时，用 verify/conflict 推导 ===
            verify_count = item.get("verify_count", 0)
            conflict_count = item.get("conflict_count", 0)
            
            beta_alpha = item.get("beta_alpha", None)
            if beta_alpha is None:
                # 旧版：伪计数 1 + 验证成功次数
                beta_alpha = 1 + verify_count
            
            beta_beta = item.get("beta_beta", None)
            if beta_beta is None:
                # 旧版：伪计数 1 + 失败次数
                beta_beta = 1 + conflict_count
            
            created_at = item.get("created_at", "")
            if not created_at:
                # 旧版没创建时间：用 last_updated 或当前时间兜底
                created_at = item.get("last_updated", "") or datetime.now().isoformat()
            
            # 确保 keyword 参数符合 dataclass 字段
            entry = MemoryEntry(
                memory_id=item["memory_id"],
                content=item["content"],
                category=item["category"],
                confidence=item.get("confidence", 0.5),
                quality_level=item.get("quality_level", "C"),
                verify_count=verify_count,
                conflict_count=conflict_count,
                beta_alpha=beta_alpha,
                beta_beta=beta_beta,
                created_at=created_at,
                last_updated=item.get("last_updated", ""),
                source=item.get("source", ""),
                tags=item.get("tags", []),
            )
            self.memories[entry.memory_id] = entry
    
    def _save_memories(self):
        with self._file_lock:
            memory_file = self.memory_unit_path / "bayesian_memories.json"
            data = {
                "updated_at": datetime.now().isoformat(),
                "memory_count": len(self.memories),
                "schema_version": 2,  # v2 = 严格贝叶斯版
                "memories": [m.to_dict() for m in self.memories.values()],
            }
            tmp_file = memory_file.with_suffix('.json.tmp')
            tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_file.replace(memory_file)
    
    # ============================================================
    #  添加 / 获取记忆
    # ============================================================
    
    def add_memory(
        self,
        memory_id: str,
        content: str,
        category: str = "principle",
        initial_confidence: float = 0.5,
        source: str = "",
        tags: Optional[List[str]] = None,
        initial_verify_count: int = 0,
    ) -> MemoryEntry:
        now = datetime.now().isoformat()
        entry = MemoryEntry(
            memory_id=memory_id,
            content=content,
            category=category,
            confidence=initial_confidence,
            # Beta(1, 1) = 均匀分布 (无信息先验，似然度=0.5)
            beta_alpha=1,
            beta_beta=1,
            created_at=now,
            last_updated=now,
            quality_level=self._calculate_quality_level(initial_confidence, initial_verify_count),
            source=source,
            tags=tags or [],
        )
        entry.verify_count = initial_verify_count
        self.memories[memory_id] = entry
        self._save_memories()
        return entry

    def update_confidence_simple(
        self, memory_id: str, confidence: float, verify_count: int
    ) -> bool:
        """
        简单更新置信度和验证次数（供蒸馏引擎同步 L1 状态用）。

        不触发贝叶斯 alpha/beta 更新，仅覆盖 confidence/verify_count/quality_level。
        用于同一 L1 记忆多次质量升级时，同步更新 L2 记忆的最新状态。
        """
        entry = self.memories.get(memory_id)
        if not entry:
            return False
        entry.confidence = confidence
        entry.verify_count = verify_count
        entry.quality_level = self._calculate_quality_level(confidence, verify_count)
        entry.last_updated = datetime.now().isoformat()
        self._save_memories()
        return True
    
    def get_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        return self.memories.get(memory_id)
    
    # ============================================================
    #  核心：严格贝叶斯置信度更新
    # ============================================================
    
    def update_confidence(
        self,
        memory_id: str,
        observation_success: bool,
        followed_memory: bool,
    ) -> Tuple[float, str]:
        """
        严格贝叶斯置信度更新。
        
        步骤：
        1. 获取先验 P(A) = entry.confidence
        2. 用 Beta 分布计算似然度 P(B|A)
           - 成功: P(B_success|A) = α/(α+β)
           - 失败: P(B_failure|A) = β/(α+β) = 1 - 成功似然度
           - 未遵循: 0.5 (中性)
        3. 用全概率公式计算证据 P(B)
           - P(B) = P(B|A)P(A) + P(B|¬A)P(¬A)
           - P(B_success|¬A) = base_success_rate
           - P(B_failure|¬A) = 1 - base_success_rate
        4. 贝叶斯: posterior = likelihood × prior / evidence
        5. 先更新 Beta 参数 (α+=1 or β+=1，若遵循)
        6. 基于"创建时间→年龄"计算指数遗忘因子，向 0.5 回归
        7. 质量等级判定
        """
        entry = self.memories.get(memory_id)
        if not entry:
            raise ValueError(f"记忆不存在: {memory_id}")
        
        # ---------- Step 1: 先验 ----------
        prior = entry.confidence
        prior = max(0.0001, min(0.9999, prior))  # 防止极端值导致除0
        
        # ---------- Step 2: Beta 似然度 (优化点1) ----------
        if not followed_memory:
            # 未遵循 → 无法证伪或证实 → 似然度中性 = 0.5
            likelihood_success = 0.5
            likelihood_used = 0.5 if observation_success else 0.5
            do_update_beta = False
        else:
            # 已遵循 → 真实 Beta 分布
            likelihood_success = self._calc_beta_likelihood_success(entry)
            # 成功观察用 P(成功|A)，失败观察用 P(失败|A)=1-P(成功|A)
            likelihood_used = likelihood_success if observation_success else (1.0 - likelihood_success)
            do_update_beta = True
        
        # ---------- Step 3: 全概率证据 (优化点2) ----------
        evidence = self._calc_full_evidence(
            prior=prior,
            likelihood_success=likelihood_success,
            observation_success=observation_success,
            base_rate=self.base_success_rate,
        )
        # 数值稳定：避免极小 evidence
        evidence = max(1e-9, min(1.0 - 1e-9, evidence))
        
        # ---------- Step 4: 贝叶斯公式 (与经典完全一致) ----------
        posterior = (likelihood_used * prior) / evidence
        
        # ---------- Step 5: 更新 Beta 参数 (先验更新，发生在观察之后) ----------
        if do_update_beta:
            if observation_success:
                entry.beta_alpha += 1
                entry.verify_count += 1
            else:
                entry.beta_beta += 1
                entry.conflict_count += 1
        
        # ---------- Step 6: 指数遗忘 (优化点3，基于记忆年龄) ----------
        age_seconds = self._calc_entry_age_seconds(entry)
        posterior = self._apply_age_forgetting(posterior, age_seconds, entry.quality_level)
        
        # ---------- Step 7: 数值边界 + 等级判定 ----------
        posterior = max(0.0, min(1.0, posterior))
        entry.confidence = posterior
        entry.quality_level = self._calculate_quality_level(posterior, entry.verify_count)
        entry.last_updated = datetime.now().isoformat()
        
        # ---------- 保存 ----------
        self._save_memories()
        return posterior, entry.quality_level
    
    # ============================================================
    #  优化点1：Beta分布似然度
    # ============================================================
    
    def _calc_beta_likelihood_success(self, entry: MemoryEntry) -> float:
        """
        E[P(观察成功 | 记忆为真)] = α / (α + β)
        
        Beta 分布的期望，作为 P(成功|记忆有效) 的点估计。
        初始 Beta(1,1) → 0.5 (均匀分布，无信息)
        1次成功 Beta(2,1) → 2/3 ≈ 0.6667
        10次成功 Beta(11,1) → 11/12 ≈ 0.9167 (远达不到0.95的固定值，更保守)
        """
        a = max(1, entry.beta_alpha)
        b = max(1, entry.beta_beta)
        return a / (a + b)
    
    # ============================================================
    #  优化点2：全概率公式证据
    # ============================================================
    
    def _calc_full_evidence(
        self,
        prior: float,
        likelihood_success: float,
        observation_success: bool,
        base_rate: float,
    ) -> float:
        """
        严格 Law of Total Probability：
          P(B) = P(B|A)·P(A) + P(B|¬A)·P(¬A)
        
        其中 A = "记忆为真"，B = "观察结果"
             P(B_success|A)  = likelihood_success
             P(B_success|¬A) = base_rate (无记忆时的随机成功率)
             P(B_failure|A)  = 1 - likelihood_success
             P(B_failure|¬A) = 1 - base_rate
        """
        not_prior = 1.0 - prior
        if observation_success:
            p_b_given_a = likelihood_success
            p_b_given_not_a = base_rate
        else:
            p_b_given_a = 1.0 - likelihood_success
            p_b_given_not_a = 1.0 - base_rate
        return p_b_given_a * prior + p_b_given_not_a * not_prior
    
    # ============================================================
    #  优化点3：基于年龄的指数遗忘
    # ============================================================
    
    def _get_half_life_days(self, quality_level: str) -> float:
        return self.HALF_LIFE_DAYS.get(quality_level, 60.0)  # 默认60天
    
    def _calc_entry_age_seconds(self, entry: MemoryEntry) -> float:
        """记忆从创建到现在经过的秒数。"""
        if not entry.created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(entry.created_at)
        except (ValueError, TypeError):
            return 0.0
        delta = datetime.now() - created
        return max(0.0, delta.total_seconds())
    
    def _calc_forget_factor(self, age_seconds: float, quality_level: str) -> float:
        """
        指数遗忘因子:
          ff = exp(-λ × age / half_life)
          
        边界：
          age = 0          → ff = 1.0 (不遗忘)
          age = half_life  → ff = exp(-ln2) = 0.5
          age = 2×half     → ff = 0.25
          age → ∞          → ff → 0 (完全回归0.5)
        """
        half_secs = self._get_half_life_days(quality_level) * 86400.0
        if half_secs <= 0:
            return 1.0
        ratio = age_seconds / half_secs
        ff = math.exp(-self._FORGET_LAMBDA * ratio)
        return max(0.0, min(1.0, ff))
    
    def _apply_age_forgetting(
        self,
        posterior: float,
        age_seconds: float,
        quality_level: str,
    ) -> float:
        """
        向 0.5 中心回归的加权平均：
          forgotten = ff × posterior + (1 - ff) × 0.5
        """
        ff = self._calc_forget_factor(age_seconds, quality_level)
        return ff * posterior + (1.0 - ff) * 0.5
    
    # ============================================================
    #  质量等级计算 (保留验证次数门槛)
    # ============================================================
    
    def _calculate_quality_level(self, confidence: float, verify_count: int) -> str:
        """置信度门槛 + 验证次数门槛 的双重判定。"""
        if confidence < 0.2 and verify_count == 0:
            return "D"
        for level, threshold in self.QUALITY_THRESHOLDS.items():
            if confidence >= threshold:
                required = self.VERIFY_THRESHOLDS.get(level, 0)
                if verify_count >= required or level == "C":
                    return level
        return "C"
    
    # ============================================================
    #  A8 报告处理 (保持对外 API 兼容)
    # ============================================================
    
    def process_a8_report(self, a8_report: dict) -> Dict[str, Tuple[float, str]]:
        results = {}
        summary = a8_report.get("summary", {})
        consistency_score = summary.get("consistency_score", 0)
        overall_success = consistency_score >= 80
        followed_memory = True
        
        for memory_id in list(self.memories.keys()):
            try:
                new_c, new_l = self.update_confidence(
                    memory_id=memory_id,
                    observation_success=overall_success,
                    followed_memory=followed_memory,
                )
                results[memory_id] = (new_c, new_l)
            except ValueError:
                pass
        return results
    
    # ============================================================
    #  搜索 / 统计 / 健康检查 (保持不变)
    # ============================================================
    
    def search_memories(
        self,
        query: str = "",
        min_quality: str = "C",
        max_results: int = 10,
    ) -> List[MemoryEntry]:
        quality_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        min_order = quality_order.get(min_quality, 3)
        results = []
        for entry in self.memories.values():
            if quality_order.get(entry.quality_level, 4) > min_order:
                continue
            if query:
                q = query.lower()
                if q not in entry.content.lower():
                    if not any(q in t.lower() for t in entry.tags):
                        continue
            results.append(entry)
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:max_results]
    
    def get_stats(self) -> dict:
        if not self.memories:
            return {"total": 0, "by_quality": {}, "avg_confidence": 0}
        by_q = {}
        confs = []
        for e in self.memories.values():
            by_q[e.quality_level] = by_q.get(e.quality_level, 0) + 1
            confs.append(e.confidence)
        return {
            "total": len(self.memories),
            "by_quality": by_q,
            "avg_confidence": round(sum(confs) / len(confs), 6),
            "min_confidence": round(min(confs), 6),
            "max_confidence": round(max(confs), 6),
        }
    
    def healthcheck(self) -> dict:
        memory_file = self.memory_unit_path / "bayesian_memories.json"
        return {
            "status": "healthy",
            "schema_version": 2,
            "bayesian_model": "RIGOROUS_v2 (Beta-Binomial + TotalProb + ExpForget)",
            "memory_count": len(self.memories),
            "storage_exists": memory_file.exists(),
            "base_success_rate": self.base_success_rate,
            "last_updated": self._get_last_updated(),
        }
    
    def _get_last_updated(self) -> str:
        if not self.memories:
            return "N/A"
        latest = max(e.last_updated for e in self.memories.values() if e.last_updated)
        return latest or "N/A"


# ============================================================
#  对外工具函数：创建默认记忆 (保持 API 兼容)
# ============================================================

def create_default_memories(memory_unit_path) -> BayesianMemoryUpdater:
    updater = BayesianMemoryUpdater(memory_unit_path)
    unit_name = Path(memory_unit_path).name
    
    def add(mid, content, cat, conf, src, tags_list):
        if mid not in updater.memories:
            updater.add_memory(mid, content, cat, conf, src, tags_list)
    
    if "开发" in unit_name or "DEV" in unit_name:
        add("GM-DEV-001", "代码变更必须同步更新文档，否则将导致理论与实践不一致",
            "principle", 0.85, "工程实践", ["文档同步", "A8校验"])
        add("GM-DEV-002", "新功能开发前必须先进行 A1 调研，充分了解上下文和历史决策",
            "methodology", 0.75, "A1 SKILL 实践", ["A1调研", "开发流程"])
        add("GM-DEV-003", "subprocess + shlex.split 在设置 PYTHONPATH 等环境变量时会失败，应使用 shell=True",
            "lesson", 0.6, "L3 调度器崩溃案例", ["subprocess", "环境变量", "反模式"])
    
    elif "交易" in unit_name or "TRD" in unit_name:
        add("GM-TRD-001", "趋势向上时做多(LONG)胜率更高，趋势向下时做空(SHORT)胜率更高",
            "principle", 0.7, "L4 交易系统统计", ["趋势跟随", "交易原则"])
        add("GM-TRD-002", "连续亏损后应暂停交易，检查市场状态和策略适用性",
            "lesson", 0.65, "交易复盘", ["风控", "情绪管理"])
    
    elif "文档" in unit_name or "DOC" in unit_name:
        add("GM-DOC-001", "API 文档必须与代码实现保持同步，A8 校验是确保一致性的关键机制",
            "principle", 0.8, "A8 SKILL 实践", ["文档治理", "A8校验", "SSoT"])
    
    else:
        add("GM-INF-001", "信息更新需要及时同步到相关文档和记忆单元，确保信息一致性",
            "principle", 0.6, "系统设计", ["信息同步"])
    
    return updater


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 bayesian_memory_updater.py <记忆单元路径> [--init]")
        print("示例: python3 bayesian_memory_updater.py 4-MEMORY/1-开发记忆单元 --init")
        sys.exit(1)
    
    unit_path = Path(sys.argv[1])
    init = "--init" in sys.argv
    
    if init:
        updater = create_default_memories(unit_path)
        stats = updater.get_stats()
        hc = updater.healthcheck()
        print(f"✅ 已初始化 {unit_path}")
        print(f"   模型: {hc['bayesian_model']}")
        print(f"   记忆总数: {stats['total']}")
        print(f"   质量分布: {stats['by_quality']}")
        print(f"   平均置信度: {stats['avg_confidence']}")
    else:
        updater = BayesianMemoryUpdater(unit_path)
        stats = updater.get_stats()
        hc = updater.healthcheck()
        print(f"📊 {unit_path} 记忆统计 (模型: {hc.get('bayesian_model','legacy')})")
        print(f"   记忆总数: {stats['total']}")
        print(f"   质量分布: {stats['by_quality']}")
        print(f"   平均置信度: {stats['avg_confidence']}")
        if "min_confidence" in stats:
            print(f"   置信度范围: [{stats['min_confidence']}, {stats['max_confidence']}]")
        print(f"   base_success_rate: {hc.get('base_success_rate','N/A')}")
        print(f"\n❤️  健康状态: {hc['status']}")
        print(f"   存储文件: {'存在' if hc['storage_exists'] else '不存在'}")
        print(f"   最后更新: {hc['last_updated']}")
        
        # 额外展示 Beta 分布和似然度的摘要
        if stats['total'] > 0:
            print(f"\n🧮 前5条记忆的 Beta 似然度:")
            for e in list(updater.memories.values())[:5]:
                lik = updater._calc_beta_likelihood_success(e)
                age_s = updater._calc_entry_age_seconds(e)
                age_d = age_s / 86400.0
                ff = updater._calc_forget_factor(age_s, e.quality_level)
                print(f"   {e.memory_id}: β({e.beta_alpha},{e.beta_beta}) → P(成功|A)={lik:.4f}  "
                      f"年龄={age_d:.1f}天 遗忘因子={ff:.3f}  置信度={e.confidence:.4f}({e.quality_level})")

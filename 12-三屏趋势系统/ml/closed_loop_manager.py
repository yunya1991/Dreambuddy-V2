"""闭环迭代管理器

管理"理论假设 → 算法实现 → 回测验证 → 基线锚定 → 反馈修正"的完整闭环迭代流程。

核心功能：
1. 假设管理：记录、跟踪、归档所有理论假设
2. 实验管理：记录每次实验的配置、结果、结论
3. 基线管理：v2基线锚定，版本迭代与回退
4. 知识库：成功/失败经验积累，反哺理论

设计原则：
- 假设驱动：每次迭代必须有明确的理论假设
- 可溯源：每个结论都有实验数据支撑
- 可回退：任何时候都能回退到v2基线
- 可积累：经验教训结构化存储，持续丰富理论库

文件结构：
    ml/
    ├── closed_loop_manager.py    # 本文件
    └── loop_data/                # 闭环数据存储
        ├── hypotheses/           # 假设库
        │   ├── active/           # 待验证/验证中
        │   ├── accepted/         # 已采纳（已证明有效）
        │   └── rejected/         # 已拒绝（已证明无效）
        ├── experiments/          # 实验记录
        └── baseline/             # 基线版本记录
"""

import os
import sys
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── 数据结构 ──────────────────────────────────────────────────────────

class HypothesisStatus(str, Enum):
    """假设状态"""
    PENDING = "pending"           # 待验证
    IN_PROGRESS = "in_progress"   # 验证中
    ACCEPTED = "accepted"         # 已采纳（验证通过）
    REJECTED = "rejected"         # 已拒绝（验证失败）
    ARCHIVED = "archived"         # 已归档


class ExperimentStatus(str, Enum):
    """实验状态"""
    PLANNED = "planned"           # 计划中
    RUNNING = "running"           # 运行中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败


@dataclass
class Hypothesis:
    """理论假设

    格式："在[X场景]下，[Y特征/算法]应该能[提升Z目的的指标]"
    """
    hypo_id: str                           # 唯一ID (HYP-YYYYMMDD-XXX)
    title: str                             # 简短标题
    description: str                       # 详细描述
    theory_source: str                     # 理论来源（哪个理论/经验/观察）
    objective: str                         # 目标目的 (dip_buy/top_exit/bear_short/bear_exit)
    expected_effect: str                   # 预期效果描述
    expected_metric_improvement: float     # 预期指标提升幅度（如0.1=提升10%）
    status: str = HypothesisStatus.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    tags: List[str] = field(default_factory=list)
    related_experiments: List[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


@dataclass
class Experiment:
    """实验记录"""
    exp_id: str                            # 唯一ID (EXP-YYYYMMDD-XXX)
    name: str                              # 实验名称
    hypo_id: str                           # 关联的假设ID
    objective: str                         # 目标目的
    strategy_name: str                     # 策略名称
    status: str = ExperimentStatus.PLANNED.value
    config: Dict[str, Any] = field(default_factory=dict)  # 实验配置
    result: Optional[Dict[str, Any]] = None  # 实验结果（分场景回测结果）
    composite_score: float = 0.0           # 综合评分
    conclusion: str = ""                   # 结论描述
    lessons_learned: str = ""              # 经验教训
    created_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class BaselineVersion:
    """基线版本记录"""
    version: str                           # 版本号 (v2, v2.1, v3...)
    name: str                              # 版本名称
    description: str                       # 描述
    strategy_class: str                    # 策略类名
    config_path: str                       # 配置文件路径
    metrics: Dict[str, float] = field(default_factory=dict)  # 关键指标
    is_active: bool = False                # 是否为当前生效基线
    created_at: str = ""
    released_at: str = ""
    release_notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


# ── 闭环管理器 ────────────────────────────────────────────────────────

class ClosedLoopManager:
    """闭环迭代管理器

    管理"理论假设 → 算法实现 → 回测验证 → 基线锚定 → 反馈修正"的完整流程。
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        Args:
            data_dir: 闭环数据存储目录，默认 ml/loop_data/
        """
        if data_dir is None:
            data_dir = Path(__file__).parent / "loop_data"
        self.data_dir = Path(data_dir)
        self.hypo_dir = self.data_dir / "hypotheses"
        self.exp_dir = self.data_dir / "experiments"
        self.baseline_dir = self.data_dir / "baseline"

        for d in [
            self.hypo_dir / "active",
            self.hypo_dir / "accepted",
            self.hypo_dir / "rejected",
            self.exp_dir,
            self.baseline_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        # 初始化v2基线
        self._init_v2_baseline()

    # ── 假设管理 ────────────────────────────────────────────────────

    def create_hypothesis(
        self,
        title: str,
        description: str,
        theory_source: str,
        objective: str,
        expected_effect: str,
        expected_improvement: float = 0.1,
        tags: Optional[List[str]] = None,
    ) -> Hypothesis:
        """创建一个新的理论假设

        Args:
            title: 简短标题
            description: 详细描述（"在X场景下，Y应该能提升Z"）
            theory_source: 理论来源
            objective: 目标目的
            expected_effect: 预期效果描述
            expected_improvement: 预期指标提升幅度
            tags: 标签列表

        Returns:
            Hypothesis 对象
        """
        hypo_id = self._generate_hypo_id()
        hypo = Hypothesis(
            hypo_id=hypo_id,
            title=title,
            description=description,
            theory_source=theory_source,
            objective=objective,
            expected_effect=expected_effect,
            expected_metric_improvement=expected_improvement,
            tags=tags or [],
        )
        self._save_hypothesis(hypo, "active")
        print(f"✅ 假设已创建: {hypo_id} - {title}")
        return hypo

    def get_hypothesis(self, hypo_id: str) -> Optional[Hypothesis]:
        """获取假设详情"""
        for subdir in ["active", "accepted", "rejected"]:
            path = self.hypo_dir / subdir / f"{hypo_id}.json"
            if path.exists():
                return self._load_hypothesis(path)
        return None

    def list_hypotheses(
        self,
        status: Optional[str] = None,
        objective: Optional[str] = None,
    ) -> List[Hypothesis]:
        """列出假设

        Args:
            status: 按状态过滤 (pending/in_progress/accepted/rejected)
            objective: 按目的过滤
        """
        hypos = []
        subdirs = ["active", "accepted", "rejected"]
        if status in ["accepted"]:
            subdirs = ["accepted"]
        elif status in ["rejected"]:
            subdirs = ["rejected"]
        elif status in ["pending", "in_progress"]:
            subdirs = ["active"]

        for subdir in subdirs:
            d = self.hypo_dir / subdir
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                hypo = self._load_hypothesis(f)
                if status and hypo.status != status:
                    continue
                if objective and hypo.objective != objective:
                    continue
                hypos.append(hypo)

        hypos.sort(key=lambda h: h.created_at, reverse=True)
        return hypos

    def update_hypothesis_status(self, hypo_id: str, new_status: str, notes: str = ""):
        """更新假设状态"""
        hypo = self.get_hypothesis(hypo_id)
        if not hypo:
            print(f"❌ 假设不存在: {hypo_id}")
            return

        old_status = hypo.status
        hypo.status = new_status
        hypo.updated_at = datetime.now().isoformat()
        if notes:
            hypo.notes = (hypo.notes + "\n" if hypo.notes else "") + notes

        # 移动到对应目录
        if new_status in ["accepted"]:
            target_dir = "accepted"
        elif new_status in ["rejected"]:
            target_dir = "rejected"
        else:
            target_dir = "active"

        # 删除旧位置的文件
        for subdir in ["active", "accepted", "rejected"]:
            old_path = self.hypo_dir / subdir / f"{hypo_id}.json"
            if old_path.exists() and subdir != target_dir:
                old_path.unlink()

        self._save_hypothesis(hypo, target_dir)
        print(f"🔄 假设 {hypo_id} 状态: {old_status} → {new_status}")

    # ── 实验管理 ────────────────────────────────────────────────────

    def create_experiment(
        self,
        name: str,
        hypo_id: str,
        objective: str,
        strategy_name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Experiment:
        """创建一个新实验

        Args:
            name: 实验名称
            hypo_id: 关联的假设ID
            objective: 目标目的
            strategy_name: 策略名称
            config: 实验配置

        Returns:
            Experiment 对象
        """
        exp_id = self._generate_exp_id()
        exp = Experiment(
            exp_id=exp_id,
            name=name,
            hypo_id=hypo_id,
            objective=objective,
            strategy_name=strategy_name,
            config=config or {},
        )
        self._save_experiment(exp)

        # 关联到假设
        hypo = self.get_hypothesis(hypo_id)
        if hypo:
            if exp_id not in hypo.related_experiments:
                hypo.related_experiments.append(exp_id)
                if hypo.status == HypothesisStatus.PENDING.value:
                    hypo.status = HypothesisStatus.IN_PROGRESS.value
                hypo.updated_at = datetime.now().isoformat()
            self._save_hypothesis_to_current_dir(hypo)

        print(f"🧪 实验已创建: {exp_id} - {name}")
        return exp

    def record_experiment_result(
        self,
        exp_id: str,
        result_data: Dict[str, Any],
        composite_score: float,
        conclusion: str = "",
        lessons_learned: str = "",
    ) -> Experiment:
        """记录实验结果

        Args:
            exp_id: 实验ID
            result_data: 分场景回测结果字典
            composite_score: 综合评分（>1.0优于基线）
            conclusion: 结论
            lessons_learned: 经验教训

        Returns:
            更新后的 Experiment 对象
        """
        exp = self.get_experiment(exp_id)
        if not exp:
            print(f"❌ 实验不存在: {exp_id}")
            return None

        exp.status = ExperimentStatus.COMPLETED.value
        exp.result = result_data
        exp.composite_score = composite_score
        exp.conclusion = conclusion
        exp.lessons_learned = lessons_learned
        exp.completed_at = datetime.now().isoformat()
        self._save_experiment(exp)

        # 自动更新关联假设的状态
        if exp.hypo_id:
            if composite_score > 1.0:
                status = HypothesisStatus.ACCEPTED.value
                conclusion_note = f"实验{exp_id}验证通过，综合评分{composite_score:.3f} > 1.0"
            else:
                status = HypothesisStatus.REJECTED.value
                conclusion_note = f"实验{exp_id}验证未通过，综合评分{composite_score:.3f} ≤ 1.0"

            self.update_hypothesis_status(
                exp.hypo_id, status,
                notes=f"{conclusion_note}\n结论: {conclusion}\n经验: {lessons_learned}",
            )

        print(f"📊 实验 {exp_id} 完成，综合评分: {composite_score:.3f}")
        return exp

    def get_experiment(self, exp_id: str) -> Optional[Experiment]:
        """获取实验详情"""
        path = self.exp_dir / f"{exp_id}.json"
        if path.exists():
            return self._load_experiment(path)
        return None

    def list_experiments(
        self,
        status: Optional[str] = None,
        hypo_id: Optional[str] = None,
        objective: Optional[str] = None,
    ) -> List[Experiment]:
        """列出实验"""
        exps = []
        for f in self.exp_dir.glob("*.json"):
            exp = self._load_experiment(f)
            if status and exp.status != status:
                continue
            if hypo_id and exp.hypo_id != hypo_id:
                continue
            if objective and exp.objective != objective:
                continue
            exps.append(exp)
        exps.sort(key=lambda e: e.created_at, reverse=True)
        return exps

    # ── 基线管理 ────────────────────────────────────────────────────

    def get_active_baseline(self) -> BaselineVersion:
        """获取当前生效的基线版本"""
        baselines = self.list_baselines()
        for b in baselines:
            if b.is_active:
                return b
        # 默认返回v2
        return BaselineVersion(
            version="v2",
            name="v2增强版MA200",
            description="技术分析最佳版本，三屏趋势系统基线",
            strategy_class="EnhancedMA200Strategy",
            config_path="ml/enhanced_ma200_v2_config.json",
            is_active=True,
            release_notes="初始基线，MA200牛熊经验法则增强版",
        )

    def list_baselines(self) -> List[BaselineVersion]:
        """列出所有基线版本"""
        baselines = []
        for f in self.baseline_dir.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                baselines.append(BaselineVersion(**data))
        baselines.sort(key=lambda b: b.created_at)
        return baselines

    def promote_to_baseline(
        self,
        version: str,
        name: str,
        description: str,
        strategy_class: str,
        config_path: str,
        metrics: Dict[str, float],
        release_notes: str = "",
    ) -> BaselineVersion:
        """将一个验证通过的策略提升为新的基线

        仅当综合评分 > 1.0 时才可调用此方法。
        """
        # 先把现有基线设为非激活
        for b in self.list_baselines():
            if b.is_active:
                b.is_active = False
                self._save_baseline(b)

        new_baseline = BaselineVersion(
            version=version,
            name=name,
            description=description,
            strategy_class=strategy_class,
            config_path=config_path,
            metrics=metrics,
            is_active=True,
            release_notes=release_notes,
            released_at=datetime.now().isoformat(),
        )
        self._save_baseline(new_baseline)
        print(f"🚀 新基线已发布: {version} - {name}")
        print(f"   发布说明: {release_notes}")
        return new_baseline

    def rollback_baseline(self, version: str = "v2") -> BaselineVersion:
        """回退到指定基线版本（默认回退到v2）"""
        target = None
        for b in self.list_baselines():
            if b.version == version:
                target = b
                break

        if not target:
            # v2是初始基线，总是存在
            target = BaselineVersion(
                version="v2",
                name="v2增强版MA200",
                description="技术分析最佳版本，三屏趋势系统基线",
                strategy_class="EnhancedMA200Strategy",
                config_path="ml/enhanced_ma200_v2_config.json",
                is_active=True,
                release_notes="回退到初始基线",
            )

        # 设为激活
        target.is_active = True
        target.released_at = datetime.now().isoformat()
        self._save_baseline(target)

        # 其他设为非激活
        for b in self.list_baselines():
            if b.version != version:
                b.is_active = False
                self._save_baseline(b)

        print(f"⏪ 已回退到基线: {version}")
        return target

    # ── 知识库 ──────────────────────────────────────────────────────

    def get_knowledge_summary(self) -> Dict[str, Any]:
        """获取知识库摘要

        返回：假设统计、实验统计、基线信息、核心经验教训
        """
        all_hypos = self.list_hypotheses()
        all_exps = self.list_experiments()
        baselines = self.list_baselines()
        active_baseline = self.get_active_baseline()

        # 统计各状态假设数量
        hypo_stats = {}
        for h in all_hypos:
            hypo_stats[h.status] = hypo_stats.get(h.status, 0) + 1

        # 统计各目的假设数量
        obj_hypo_count = {}
        for h in all_hypos:
            obj_hypo_count[h.objective] = obj_hypo_count.get(h.objective, 0) + 1

        # 收集已采纳假设的经验
        accepted_hypos = [h for h in all_hypos if h.status == "accepted"]
        rejected_hypos = [h for h in all_hypos if h.status == "rejected"]

        # 收集实验中的经验教训
        lessons = []
        for exp in all_exps:
            if exp.lessons_learned:
                lessons.append({
                    "exp_id": exp.exp_id,
                    "objective": exp.objective,
                    "score": exp.composite_score,
                    "lesson": exp.lessons_learned,
                })

        return {
            "baseline": {
                "active_version": active_baseline.version,
                "active_name": active_baseline.name,
                "total_versions": len(baselines),
            },
            "hypotheses": {
                "total": len(all_hypos),
                "by_status": hypo_stats,
                "by_objective": obj_hypo_count,
            },
            "experiments": {
                "total": len(all_exps),
            },
            "lessons_learned": lessons,
            "accepted_hypotheses": [
                {"id": h.hypo_id, "title": h.title, "objective": h.objective}
                for h in accepted_hypos
            ],
            "rejected_hypotheses": [
                {"id": h.hypo_id, "title": h.title, "objective": h.objective}
                for h in rejected_hypos
            ],
        }

    def print_summary(self):
        """打印闭环迭代状态摘要"""
        summary = self.get_knowledge_summary()
        print("=" * 60)
        print("三屏趋势系统 · 闭环迭代状态")
        print("=" * 60)
        b = summary["baseline"]
        print(f"\n📌 当前基线: {b['active_version']} ({b['active_name']})")
        print(f"   历史基线版本数: {b['total_versions']}")

        h = summary["hypotheses"]
        print(f"\n💡 假设库 (总计 {h['total']} 个)")
        for status, count in h["by_status"].items():
            print(f"   {status}: {count}")
        print(f"   按目的分布: {h['by_objective']}")

        e = summary["experiments"]
        print(f"\n🧪 实验记录: {e['total']} 个")

        if summary["accepted_hypotheses"]:
            print(f"\n✅ 已采纳假设:")
            for item in summary["accepted_hypotheses"]:
                print(f"   [{item['id']}] {item['title']} ({item['objective']})")

        if summary["lessons_learned"]:
            print(f"\n📚 经验教训 (最近3条):")
            for item in summary["lessons_learned"][:3]:
                print(f"   [{item['exp_id']}] {item['objective']}: {item['lesson'][:80]}...")

        print("\n" + "=" * 60)

    # ── 内部方法 ────────────────────────────────────────────────────

    def _init_v2_baseline(self):
        """初始化v2基线（如果不存在）"""
        existing = self.list_baselines()
        if not existing:
            v2 = BaselineVersion(
                version="v2",
                name="v2增强版MA200",
                description="技术分析最佳版本，三屏趋势系统基线策略",
                strategy_class="EnhancedMA200Strategy",
                config_path="ml/enhanced_ma200_v2_config.json",
                is_active=True,
                release_notes="初始基线版本。MA200牛熊经验法则增强版："
                              "BTC分层抄底+分层做空+斐波那契止盈+小币熊市禁空。",
                released_at=datetime.now().isoformat(),
            )
            self._save_baseline(v2)

    def _generate_hypo_id(self) -> str:
        """生成假设ID"""
        today = datetime.now().strftime("%Y%m%d")
        existing = len(list(self.hypo_dir.rglob(f"HYP-{today}-*.json")))
        return f"HYP-{today}-{existing + 1:03d}"

    def _generate_exp_id(self) -> str:
        """生成实验ID"""
        today = datetime.now().strftime("%Y%m%d")
        existing = len(list(self.exp_dir.glob(f"EXP-{today}-*.json")))
        return f"EXP-{today}-{existing + 1:03d}"

    def _save_hypothesis(self, hypo: Hypothesis, subdir: str):
        """保存假设到指定子目录"""
        path = self.hypo_dir / subdir / f"{hypo.hypo_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(hypo), f, ensure_ascii=False, indent=2)

    def _save_hypothesis_to_current_dir(self, hypo: Hypothesis):
        """根据假设当前状态保存到对应目录"""
        if hypo.status in ["accepted"]:
            self._save_hypothesis(hypo, "accepted")
        elif hypo.status in ["rejected"]:
            self._save_hypothesis(hypo, "rejected")
        else:
            self._save_hypothesis(hypo, "active")

    def _load_hypothesis(self, path: Path) -> Hypothesis:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Hypothesis(**data)

    def _save_experiment(self, exp: Experiment):
        path = self.exp_dir / f"{exp.exp_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(exp), f, ensure_ascii=False, indent=2)

    def _load_experiment(self, path: Path) -> Experiment:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Experiment(**data)

    def _save_baseline(self, baseline: BaselineVersion):
        path = self.baseline_dir / f"baseline_{baseline.version}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(baseline), f, ensure_ascii=False, indent=2)


# ── 便捷函数 ──────────────────────────────────────────────────────────

def get_loop_manager() -> ClosedLoopManager:
    """获取闭环管理器单例"""
    return ClosedLoopManager()


def demo_workflow():
    """演示完整的闭环工作流"""
    print("=" * 60)
    print("演示：理论假设 → 实验 → 验证 → 基线迭代 / 回退")
    print("=" * 60)

    mgr = ClosedLoopManager()

    # 1. 创建一个理论假设
    print("\n1️⃣  创建假设...")
    hypo = mgr.create_hypothesis(
        title="RSI底背离提升抄底准确率",
        description="在DIP_BUY场景下，RSI底背离信号应该能提升抄底的准确率和盈亏比",
        theory_source="三重滤网理论 + Elder-ray背离 + v2策略左侧抄底经验",
        objective="dip_buy",
        expected_effect="抄底准确率提升10%，盈亏比提升0.5",
        expected_improvement=0.1,
        tags=["rsi", "divergence", "dip_buy"],
    )

    # 2. 创建实验
    print("\n2️⃣  创建实验...")
    exp = mgr.create_experiment(
        name="RSI底背离抄底实验",
        hypo_id=hypo.hypo_id,
        objective="dip_buy",
        strategy_name="RSI_Divergence_DipBuy",
        config={"rsi_period": 14, "divergence_lookback": 20},
    )

    # 3. （模拟）实验完成，记录结果
    print("\n3️⃣  记录实验结果...")
    mock_result = {
        "overall_sharpe": 1.5,
        "overall_calmar": 3.0,
        "objectives": {
            "dip_buy": {"win_rate": 0.65, "profit_factor": 2.5}
        }
    }
    mgr.record_experiment_result(
        exp_id=exp.exp_id,
        result_data=mock_result,
        composite_score=1.15,  # >1.0 假设被采纳
        conclusion="RSI底背离确实能提升抄底准确率，符合预期",
        lessons_learned="底部区域结合RSI背离比单纯MA200抄底效果更好，但需要过滤假背离",
    )

    # 4. 打印摘要
    print("\n4️⃣  状态摘要:")
    mgr.print_summary()

    print("\n✅ 演示完成")


if __name__ == "__main__":
    demo_workflow()

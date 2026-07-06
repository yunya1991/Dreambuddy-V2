"""
M1: 研讨编排器 (Orchestrator)
主持整个大师研讨流程
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

@dataclass
class SeminarConfig:
    """研讨配置"""
    max_rounds: int = 3
    max_thesis_per_camp: int = 3
    max_questions_per_round: int = 2
    timeout_minutes: int = 10
    min_masters_per_camp: int = 1
    max_masters_per_camp: int = 4

@dataclass
class SeminarContext:
    """研讨上下文"""
    seminar_id: str = ""
    timestamp: str = ""
    trigger_type: str = ""  # REGIME_CHANGE, A5_EXECUTION, MANUAL
    source_report: str = ""
    current_regime: str = ""
    market_state: Dict[str, Any] = field(default_factory=dict)
    selected_masters: List[str] = field(default_factory=list)
    camps: Dict[str, List[str]] = field(default_factory=lambda: {
        "bullish": [], "neutral": [], "bearish": []
    })
    debate_rounds: List[Dict] = field(default_factory=list)
    conclusions: Dict = field(default_factory=dict)
    evolution_updates: Dict = field(default_factory=dict)

class MasterSeminarOrchestrator:
    """
    大师研讨编排器
    
    职责:
    1. 管理研讨生命周期
    2. 协调各模块执行顺序
    3. 管理研讨状态和上下文
    """
    
    def __init__(self, config: Optional[SeminarConfig] = None):
        self.config = config or SeminarConfig()
        self.context = SeminarContext()
        self._init_modules()
    
    def _init_modules(self):
        """初始化子模块"""
        import sys
        from pathlib import Path
        
        # 添加模块目录到路径
        module_dir = Path(__file__).parent
        if str(module_dir) not in sys.path:
            sys.path.insert(0, str(module_dir))
        
        from M2_master_selector import MasterSelector
        from M3_camp_generator import CampGenerator
        from M4_debate_engine import DebateEngine
        from M5_conclusion_extractor import ConclusionExtractor
        from M6_master_evolution import MasterEvolution
        from M7_report_writer import ReportWriter
        
        self.master_selector = MasterSelector()
        self.camp_generator = CampGenerator()
        self.debate_engine = DebateEngine(max_rounds=self.config.max_rounds)
        self.conclusion_extractor = ConclusionExtractor()
        self.evolution = MasterEvolution()
        self.report_writer = ReportWriter()
    
    def run(self, 
            trigger_type: str,
            source_report: str = "",
            current_regime: str = "",
            market_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        运行完整研讨流程
        
        Args:
            trigger_type: 触发类型 (REGIME_CHANGE/A5_EXECUTION/MANUAL)
            source_report: 源报告引用
            current_regime: 当前Regime
            market_state: 市场状态
            
        Returns:
            研讨结果字典
        """
        # 1. 初始化上下文
        self._init_context(
            trigger_type=trigger_type,
            source_report=source_report,
            current_regime=current_regime,
            market_state=market_state or {}
        )
        
        # 2. Step 1: 读取A系列报告
        a_series_reports = self._load_a_series_reports()
        
        # 3. Step 2: 选择大师
        self.context.selected_masters = self.master_selector.select(
            regime=current_regime,
            market_state=market_state,
            trigger_type=trigger_type
        )
        
        # 4. Step 3: 分配阵营
        self.context.camps = self.camp_generator.generate(
            masters=self.context.selected_masters,
            market_state=market_state
        )
        
        # 5. Step 4: 驱动辩论
        self.context.debate_rounds = self.debate_engine.run(
            camps=self.context.camps,
            reports=a_series_reports,
            market_state=market_state
        )
        
        # 6. Step 5: 提取结论
        self.context.conclusions = self.conclusion_extractor.extract(
            debate_rounds=self.context.debate_rounds,
            camps=self.context.camps
        )
        
        # 转换为dict供其他模块使用
        conclusions_dict = self.conclusion_extractor.to_dict(self.context.conclusions)
        
        # 7. 研讨后: 更新大师权重
        self.context.evolution_updates = self.evolution.update(
            seminar_results={
                "seminar_id": self.context.seminar_id,
                "conclusions": conclusions_dict
            },
            masters=self.context.selected_masters
        )
        
        # 8. 生成报告
        report = self.report_writer.generate(self.context)
        
        # 9. 归档报告
        self._archive_report(report)
        
        return {
            "status": "COMPLETED",
            "seminar_id": self.context.seminar_id,
            "conclusions": conclusions_dict,
            "evolution": self.context.evolution_updates,
            "report_path": self._get_report_path()
        }
    
    def _init_context(self,
                     trigger_type: str,
                     source_report: str,
                     current_regime: str,
                     market_state: Dict[str, Any]):
        """初始化研讨上下文"""
        now = datetime.now()
        self.context = SeminarContext(
            seminar_id=f"SEM_{now.strftime('%Y%m%d_%H%M%S')}",
            timestamp=now.isoformat(),
            trigger_type=trigger_type,
            source_report=source_report,
            current_regime=current_regime,
            market_state=market_state
        )
    
    def _load_a_series_reports(self) -> Dict[str, str]:
        """加载A系列最新报告"""
        reports = {}
        workspace = Path.home() / "WorkBuddy" / "20260415144304"
        
        # A1调研报告
        a1_reports = list((workspace / "reports").glob("a1_research_*.md"))
        if a1_reports:
            a1_reports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            reports["A1"] = a1_reports[0].read_text()[:5000]  # 限制长度
        
        # A3战略报告
        a3_reports = list((workspace / "reports" / "strategy").glob("*.md"))
        if a3_reports:
            a3_reports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            reports["A3"] = a3_reports[0].read_text()[:5000]
        
        # A5执行报告
        a5_reports = list((workspace / "reports" / "trading").glob("*.md"))
        if a5_reports:
            a5_reports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            reports["A5"] = a5_reports[0].read_text()[:5000]
        
        return reports
    
    def _get_report_path(self) -> str:
        """获取报告路径"""
        return str(Path.home() / ".workbuddy" / "skills" / "master-seminar" 
                   / "reports" / f"{self.context.seminar_id}.md")
    
    def _archive_report(self, report: str):
        """归档报告"""
        report_dir = Path.home() / ".workbuddy" / "skills" / "master-seminar" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        report_path = report_dir / f"{self.context.seminar_id}.md"
        report_path.write_text(report)
        
        # 同时归档到boss-secretary
        secretary_dir = Path.home() / ".workbuddy" / "skills" / "boss-secretary" / "reports"
        if secretary_dir.exists():
            (secretary_dir / f"seminar_{self.context.seminar_id}.md").write_text(report)


# 便捷函数
def run_seminar(trigger_type: str = "MANUAL",
                source_report: str = "",
                current_regime: str = "",
                market_state: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    运行大师研讨的便捷函数
    
    Example:
        result = run_seminar(
            trigger_type="REGIME_CHANGE",
            current_regime="TREND_BULL"
        )
    """
    orchestrator = MasterSeminarOrchestrator()
    return orchestrator.run(
        trigger_type=trigger_type,
        source_report=source_report,
        current_regime=current_regime,
        market_state=market_state
    )

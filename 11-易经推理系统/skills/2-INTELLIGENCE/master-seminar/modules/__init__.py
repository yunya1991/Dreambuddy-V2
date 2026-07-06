"""
Master-Seminar: 大师研讨SKILL
让已蒸馏的交易大师基于A系列报告分阵营辩论
"""

__version__ = "1.0.0"
__author__ = "Dream-MultiSkill System"

from .M1_orchestrator import MasterSeminarOrchestrator
from .M2_master_selector import MasterSelector
from .M3_camp_generator import CampGenerator
from .M4_debate_engine import DebateEngine
from .M5_conclusion_extractor import ConclusionExtractor
from .M6_master_evolution import MasterEvolution
from .M7_report_writer import ReportWriter

__all__ = [
    "MasterSeminarOrchestrator",
    "MasterSelector",
    "CampGenerator",
    "DebateEngine",
    "ConclusionExtractor",
    "MasterEvolution",
    "ReportWriter"
]

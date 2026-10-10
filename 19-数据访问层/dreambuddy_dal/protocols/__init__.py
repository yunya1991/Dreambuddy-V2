"""dreambuddy_dal.protocols 子包：9 个 Repository Protocol（ABC）定义"""

from dreambuddy_dal.protocols.config_repo import ConfigRepository
from dreambuddy_dal.protocols.kg_repo import KnowledgeGraphRepository
from dreambuddy_dal.protocols.market_macro_repo import MarketMacroRepository
from dreambuddy_dal.protocols.position_repo import PositionRepository
from dreambuddy_dal.protocols.risk_repo import RiskRepository
from dreambuddy_dal.protocols.trade_repo import TradeRepository
from dreambuddy_dal.protocols.cognitive_repo import CognitiveRepository
from dreambuddy_dal.protocols.skill_repo import SkillRepository
from dreambuddy_dal.protocols.knowledge_repo import KnowledgeRepository

__all__ = [
    "TradeRepository",
    "PositionRepository",
    "MarketMacroRepository",
    "RiskRepository",
    "ConfigRepository",
    "KnowledgeGraphRepository",
    "CognitiveRepository",
    "SkillRepository",
    "KnowledgeRepository",
]

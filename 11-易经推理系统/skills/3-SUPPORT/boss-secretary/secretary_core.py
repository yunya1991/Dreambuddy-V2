#!/usr/bin/env python3
"""
老板秘书核心处理逻辑
Boss Secretary - Core Processing Engine

功能:
1. 意图识别与分类
2. 实体提取
3. 目标映射
4. 二次确认决策
5. 学习记录

版本: v1.0
日期: 2026-04-18
"""

import re
import yaml
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum

# ============================================================
# 顾问团队集成 (Step3 会诊触发)
# ============================================================
ADVISOR_TEAM_ROOT = Path.home() / ".workbuddy" / "advisor-team"
ADVISOR_INTEGRATION_AVAILABLE = False
SecretaryConsultation = None
ConsultationType = None

try:
    sys.path.insert(0, str(ADVISOR_TEAM_ROOT))
    from secretary_integration import SecretaryConsultation, ConsultationType
    ADVISOR_INTEGRATION_AVAILABLE = True
except ImportError:
    pass  # 顾问团队未安装时降级运行


# ============================================================
# 常量定义
# ============================================================

SKILL_DIR = Path.home() / ".workbuddy/skills/boss-secretary"
KNOWLEDGE_DIR = SKILL_DIR / "knowledge"
LEARNING_DIR = SKILL_DIR / "learning"
PREFERENCES_DIR = SKILL_DIR / "preferences"


class IntentType(Enum):
    """意图类型枚举"""
    # 执行类
    EXECUTE_LONG = "EXECUTE_LONG"
    EXECUTE_SHORT = "EXECUTE_SHORT"
    EXECUTE_CLOSE = "EXECUTE_CLOSE"
    QUERY_POSITION = "QUERY_POSITION"
    QUERY_ORDER_STATUS = "QUERY_ORDER_STATUS"

    # 分析类
    QUOTE_PRICE = "QUOTE_PRICE"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    OPPORTUNITY_SCAN = "OPPORTUNITY_SCAN"
    DATA_QUERY = "DATA_QUERY"

    # 系统类
    PARAM_ADJUST = "PARAM_ADJUST"
    SKILL_QUERY = "SKILL_QUERY"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    SYSTEM_STATUS = "SYSTEM_STATUS"

    # 顾问类
    ADVISOR_CONSULT = "ADVISOR_CONSULT"
    ADVISOR_REVIEW = "ADVISOR_REVIEW"
    MASTER_ADVICE = "MASTER_ADVICE"
    HISTORY_RETRIEVE = "HISTORY_RETRIEVE"

    # 管理类
    PERFORMANCE_QUERY = "PERFORMANCE_QUERY"
    STATS_QUERY = "STATS_QUERY"
    LESSON_CHECK = "LESSON_CHECK"
    REPORT_GENERATE = "REPORT_GENERATE"

    # 自动化类
    AUTOMATION_CREATE = "AUTOMATION_CREATE"
    AUTOMATION_PAUSE = "AUTOMATION_PAUSE"
    AUTOMATION_LIST = "AUTOMATION_LIST"
    AUTOMATION_OPTIMIZE = "AUTOMATION_OPTIMIZE"

    # 特殊类
    CONFUSION_SIGNAL = "CONFUSION_SIGNAL"
    MULTI_INTENT = "MULTI_INTENT"
    UNKNOWN = "UNKNOWN"

    # v2.0 新增 - 日报与会议类
    DAILY_REPORT = "DAILY_REPORT"
    MEETING_START = "MEETING_START"
    MEETING_RECORD = "MEETING_RECORD"
    CRITICISM = "CRITICISM"
    SELF_CRITICISM = "SELF_CRITICISM"

    # v3.0 新增 - 风险与紧急类
    RISK_PREDICTION = "RISK_PREDICTION"
    URGENT_RISK = "URGENT_RISK"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"

    # v1.0 新增 - 数据分析类
    DATA_ANALYSIS = "DATA_ANALYSIS"           # 数据分析请求
    TREND_ANALYSIS = "TREND_ANALYSIS"         # 趋势分析
    RESISTANCE_ANALYSIS = "RESISTANCE_ANALYSIS"  # 阻力分析
    CALIBRATION_SUGGESTION = "CALIBRATION_SUGGESTION"  # 校准建议
    CHART_REQUEST = "CHART_REQUEST"           # 图表请求
    DASHBOARD_VIEW = "DASHBOARD_VIEW"         # Dashboard查看
    EPISODE_REVIEW = "EPISODE_REVIEW"         # Episode复盘


class RiskLevel(Enum):
    """风险等级"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    MIXED = "mixed"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Entity:
    """提取的实体"""
    type: str
    value: str
    normalized: Optional[str] = None
    confidence: float = 1.0


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: IntentType
    confidence: float
    entities: List[Entity]
    raw_text: str
    keywords_matched: List[str]
    requires_confirmation: bool
    risk_level: RiskLevel

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "entities": [asdict(e) for e in self.entities],
            "raw_text": self.raw_text,
            "keywords_matched": self.keywords_matched,
            "requires_confirmation": self.requires_confirmation,
            "risk_level": self.risk_level.value
        }


@dataclass
class RoutingResult:
    """路由结果"""
    primary_skill: str
    secondary_skills: List[str]
    department: str
    advisors: List[str]
    process: str
    confirmation_required: bool

    def to_dict(self) -> Dict:
        return {
            "primary_skill": self.primary_skill,
            "secondary_skills": self.secondary_skills,
            "department": self.department,
            "advisors": self.advisors,
            "process": self.process,
            "confirmation_required": self.confirmation_required
        }


@dataclass
class LearningRecord:
    """学习记录"""
    timestamp: str
    type: str  # intent_learn, routing_learn, confirmation_learn
    original: str
    recognized_intent: str
    confidence: float
    corrected: bool
    user_feedback: Optional[Dict] = None
    execution_result: Optional[str] = None
    satisfaction: Optional[int] = None


# ============================================================
# 核心引擎类
# ============================================================

class SecretaryCore:
    """老板秘书核心引擎"""

    def __init__(self):
        self.keyword_mapping = self._load_keyword_mapping()
        self.advisor_routing = self._load_advisor_routing()
        self.company_structure = self._load_company_structure()
        self.learning_log: List[LearningRecord] = []
        self.preferences = self._load_preferences()

        # 确保目录存在
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        PREFERENCES_DIR.mkdir(parents=True, exist_ok=True)

    def _load_keyword_mapping(self) -> Dict:
        """加载意图关键词映射"""
        path = KNOWLEDGE_DIR / "keyword_mapping.yaml"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get('intents', {})
        return {}

    def _load_advisor_routing(self) -> Dict:
        """加载顾问路由规则"""
        path = KNOWLEDGE_DIR / "advisor_routing.yaml"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def _load_company_structure(self) -> Dict:
        """加载公司架构"""
        path = KNOWLEDGE_DIR / "company_structure.yaml"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def _load_preferences(self) -> Dict:
        """加载老板偏好"""
        path = PREFERENCES_DIR / "boss_preferences.yaml"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}

    def _load_learning_log(self) -> List[LearningRecord]:
        """加载学习日志"""
        path = LEARNING_DIR / "intent_log.yaml"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return [LearningRecord(**r) for r in data.get('learning_log', [])]
        return []

    def _save_learning_log(self):
        """保存学习日志"""
        path = LEARNING_DIR / "intent_log.yaml"
        data = {
            'learning_log': [
                {
                    'timestamp': r.timestamp,
                    'type': r.type,
                    'original': r.original,
                    'recognized_intent': r.recognized_intent,
                    'confidence': r.confidence,
                    'corrected': r.corrected,
                    'user_feedback': r.user_feedback,
                    'execution_result': r.execution_result,
                    'satisfaction': r.satisfaction
                }
                for r in self.learning_log[-100:]  # 只保留最近100条
            ]
        }
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    # ============================================================
    # 意图识别
    # ============================================================

    def recognize_intent(self, text: str) -> IntentResult:
        """识别用户意图"""
        text_lower = text.lower().strip()

        # 先检测模糊信号
        confusion_keywords = self.keyword_mapping.get('CONFUSION_SIGNAL', {}).get('keywords', {})
        confusion_keywords_flat = (
            confusion_keywords.get('primary', []) +
            confusion_keywords.get('secondary', [])
        )
        if any(kw in text_lower for kw in confusion_keywords_flat):
            return IntentResult(
                intent=IntentType.CONFUSION_SIGNAL,
                confidence=0.5,
                entities=[],
                raw_text=text,
                keywords_matched=['模糊信号'],
                requires_confirmation=True,
                risk_level=RiskLevel.UNKNOWN
            )

        # 检测多意图
        if self._detect_multi_intent(text_lower):
            return IntentResult(
                intent=IntentType.MULTI_INTENT,
                confidence=0.6,
                entities=[],
                raw_text=text,
                keywords_matched=['多意图'],
                requires_confirmation=True,
                risk_level=RiskLevel.MIXED
            )

        # 正常意图识别
        best_intent = None
        best_score = 0
        best_keywords = []

        for intent_id, intent_config in self.keyword_mapping.items():
            if intent_id in ['CONFUSION_SIGNAL', 'MULTI_INTENT']:
                continue

            score = 0
            matched = []

            keywords = intent_config.get('keywords', {})
            primary_kw = keywords.get('primary', [])
            secondary_kw = keywords.get('secondary', [])

            # 精确匹配 primary 关键词
            for kw in primary_kw:
                if kw.lower() in text_lower:
                    score += 0.3
                    matched.append(f"[P]{kw}")

            # 部分匹配 secondary 关键词
            for kw in secondary_kw:
                if kw.lower() in text_lower:
                    score += 0.15
                    matched.append(f"[S]{kw}")

            # 置信度加成
            score += intent_config.get('confidence_boost', 0)

            if score > best_score:
                best_score = score
                best_intent = intent_id
                best_keywords = matched

        # 计算最终置信度
        base_confidence = 0.7
        final_confidence = min(0.95, base_confidence + best_score)

        # 确定风险等级和确认要求
        risk_level = self._get_risk_level(best_intent)
        requires_confirmation = self._needs_confirmation(best_intent, final_confidence, risk_level)

        # 尝试提取实体
        entities = self._extract_entities(text)

        return IntentResult(
            intent=IntentType(best_intent) if best_intent else IntentType.UNKNOWN,
            confidence=final_confidence,
            entities=entities,
            raw_text=text,
            keywords_matched=best_keywords,
            requires_confirmation=requires_confirmation,
            risk_level=risk_level
        )

    def _detect_multi_intent(self, text: str) -> bool:
        """检测多意图"""
        conflict_patterns = [
            r'.*但.*觉得.*',  # "开多但我觉得不稳"
            r'.*但.*担心.*',
            r'.*想.*又.*',
            r'.*想做.*又想.*',
        ]
        return any(re.match(pattern, text) for pattern in conflict_patterns)

    def _extract_entities(self, text: str) -> List[Entity]:
        """提取实体"""
        entities = []

        # 交易标的
        symbol_patterns = [
            (r'\b(BTC|ETH|SOL|ORDI|MATIC|AVAX)\b', {
                'BTC': 'BTC/USDT:USDT',
                'ETH': 'ETH/USDT:USDT',
                'SOL': 'SOL/USDT:USDT',
            }),
        ]
        for pattern, normalizations in symbol_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                normalized = normalizations.get(m.upper(), m)
                entities.append(Entity(
                    type='symbol',
                    value=m,
                    normalized=normalized
                ))

        # 杠杆倍数
        leverage_patterns = [
            r'(\d+)x',
            r'(\d+)倍',
            r'杠杆(\d+)',
        ]
        for pattern in leverage_patterns:
            match = re.search(pattern, text)
            if match:
                entities.append(Entity(
                    type='leverage',
                    value=match.group(1),
                    normalized=match.group(1)
                ))

        # 仓位比例
        position_patterns = [
            r'(\d+)%',
            r'(\d+)成',
            r'(\d+)U',
        ]
        for pattern in position_patterns:
            match = re.search(pattern, text)
            if match:
                entities.append(Entity(
                    type='position_size',
                    value=match.group(1),
                    normalized=match.group(1)
                ))

        return entities

    def _get_risk_level(self, intent: str) -> RiskLevel:
        """获取风险等级"""
        risk_map = {
            'EXECUTE_LONG': RiskLevel.HIGH,
            'EXECUTE_SHORT': RiskLevel.HIGH,
            'EXECUTE_CLOSE': RiskLevel.HIGH,
            'QUERY_POSITION': RiskLevel.NONE,
            'QUERY_ORDER_STATUS': RiskLevel.NONE,
            'QUOTE_PRICE': RiskLevel.NONE,
            'MARKET_ANALYSIS': RiskLevel.LOW,
            'OPPORTUNITY_SCAN': RiskLevel.LOW,
            'DATA_QUERY': RiskLevel.NONE,
            'PARAM_ADJUST': RiskLevel.MEDIUM,
            'SKILL_QUERY': RiskLevel.NONE,
            'FEATURE_REQUEST': RiskLevel.MEDIUM,
            'SYSTEM_STATUS': RiskLevel.NONE,
            'ADVISOR_CONSULT': RiskLevel.NONE,
            'ADVISOR_REVIEW': RiskLevel.LOW,
            'MASTER_ADVICE': RiskLevel.NONE,
            'HISTORY_RETRIEVE': RiskLevel.NONE,
            'PERFORMANCE_QUERY': RiskLevel.NONE,
            'STATS_QUERY': RiskLevel.NONE,
            'LESSON_CHECK': RiskLevel.LOW,
            'REPORT_GENERATE': RiskLevel.NONE,
            'AUTOMATION_CREATE': RiskLevel.MEDIUM,
            'AUTOMATION_PAUSE': RiskLevel.MEDIUM,
            'AUTOMATION_LIST': RiskLevel.NONE,
            'AUTOMATION_OPTIMIZE': RiskLevel.MEDIUM,
            # v2.0 新增
            'DAILY_REPORT': RiskLevel.NONE,
            'MEETING_START': RiskLevel.LOW,
            'MEETING_RECORD': RiskLevel.NONE,
            'CRITICISM': RiskLevel.MEDIUM,
            'SELF_CRITICISM': RiskLevel.LOW,
            # v3.0 新增
            'RISK_PREDICTION': RiskLevel.MEDIUM,
            'URGENT_RISK': RiskLevel.CRITICAL,
            'EMERGENCY_RESPONSE': RiskLevel.CRITICAL,
        }
        return risk_map.get(intent, RiskLevel.MEDIUM)

    def _needs_confirmation(self, intent: str, confidence: float, risk_level: RiskLevel) -> bool:
        """判断是否需要确认"""
        # 高风险操作必须确认
        if risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            return True

        # 置信度低于阈值
        if confidence < 0.70:
            return True

        # 执行类操作需要确认
        if intent.startswith('EXECUTE_'):
            return True

        # 自动化操作需要确认
        if intent.startswith('AUTOMATION_'):
            return True

        return False

    # ============================================================
    # 目标路由
    # ============================================================

    def route_intent(self, intent_result: IntentResult) -> RoutingResult:
        """路由到正确的部门和Skill"""
        intent = intent_result.intent.value

        # 从公司架构中获取路由规则
        routing_rules = self.advisor_routing.get('advisor_trigger_matrix', {})

        # 基础路由配置
        base_routes = {
            'EXECUTE_LONG': {
                'department': '执行部',
                'primary_skill': 'dream-multiSkill',
                'secondary_skills': ['dream-risk-position-sizing', 'dream-pretrade-gatekeeper'],
                'process': 'dream-multiSkill 8步模板',
                'advisors': ['ADVISOR-QT', 'ADVISOR-RM']
            },
            'EXECUTE_SHORT': {
                'department': '执行部',
                'primary_skill': 'dream-multiSkill',
                'secondary_skills': ['dream-risk-position-sizing', 'dream-pretrade-gatekeeper'],
                'process': 'dream-multiSkill 8步模板',
                'advisors': ['ADVISOR-QT', 'ADVISOR-RM']
            },
            'EXECUTE_CLOSE': {
                'department': '执行部',
                'primary_skill': 'okx-trade-cli',
                'secondary_skills': ['dream-posttrade-mrm-audit'],
                'process': '平仓流程 → 盘后审计',
                'advisors': ['ADVISOR-RM']
            },
            'QUERY_POSITION': {
                'department': '执行部',
                'primary_skill': 'okx-trade-cli',
                'secondary_skills': [],
                'process': '直接查询',
                'advisors': []
            },
            'QUERY_ORDER_STATUS': {
                'department': '执行部',
                'primary_skill': 'okx-trade-cli',
                'secondary_skills': [],
                'process': '直接查询',
                'advisors': []
            },
            'QUOTE_PRICE': {
                'department': '市场情报部',
                'primary_skill': 'tavily',
                'secondary_skills': ['okx-api'],
                'process': '直接返回数据',
                'advisors': []
            },
            'MARKET_ANALYSIS': {
                'department': '市场情报部 + 研究部',
                'primary_skill': 'tavily',
                'secondary_skills': ['odaily', 'technical-analyst', 'macro-monitor'],
                'process': '数据采集 → 技术分析 → 顾问评审',
                'advisors': ['ADVISOR-MR', 'ADVISOR-QT']
            },
            'OPPORTUNITY_SCAN': {
                'department': '研究部',
                'primary_skill': 'stock-analysis',
                'secondary_skills': ['technical-analyst', 'tavily'],
                'process': '多维度扫描 → 信号评分 → 顾问评审',
                'advisors': ['ADVISOR-QT', 'ADVISOR-MR']
            },
            'DATA_QUERY': {
                'department': '市场情报部',
                'primary_skill': 'neodata-financial-search',
                'secondary_skills': ['tavily', 'odaily'],
                'process': '智能路由 → 数据查询',
                'advisors': []
            },
            'PARAM_ADJUST': {
                'department': '运营总监',
                'primary_skill': 'dream-operation-director',
                'secondary_skills': ['smart-skill-manager'],
                'process': '评估 → 顾问评审 → 实施',
                'advisors': ['ADVISOR-SA', 'ADVISOR-QT']
            },
            'SKILL_QUERY': {
                'department': '基础设施部',
                'primary_skill': 'smart-skill-manager',
                'secondary_skills': [],
                'process': '直接返回文档',
                'advisors': []
            },
            'FEATURE_REQUEST': {
                'department': '运营总监 + 基础设施部',
                'primary_skill': 'smart-skill-manager',
                'secondary_skills': ['capability-evolver'],
                'process': '需求分析 → 顾问评审 → 方案设计 → 实施',
                'advisors': ['ADVISOR-SA', 'ADVISOR-QT']
            },
            'SYSTEM_STATUS': {
                'department': '基础设施部',
                'primary_skill': 'healthcheck',
                'secondary_skills': ['self-improving-agent'],
                'process': '健康检查 → 问题诊断 → 修复建议',
                'advisors': []
            },
            'ADVISOR_CONSULT': {
                'department': '顾问委员会',
                'primary_skill': 'secretary_integration',
                'secondary_skills': ['dream-multiSkill'],
                'process': '秘书Step3会诊 → 顾问并行分析 → 汇总 → Step4执行',
                'advisors': ['ADVISOR-QT', 'ADVISOR-RM']
            },
            'ADVISOR_REVIEW': {
                'department': '顾问委员会',
                'primary_skill': 'secretary_integration',
                'secondary_skills': ['dream-multiSkill'],
                'process': '顾问评审流程 → 评审报告',
                'advisors': ['ADVISOR-QT', 'ADVISOR-RM', 'ADVISOR-MR']
            },
            'MASTER_ADVICE': {
                'department': '培训部 (知识库)',
                'primary_skill': 'ADVISOR-KB',
                'secondary_skills': ['learning-recall-pack'],
                'process': '知识检索 → 大师观点整合 → 建议',
                'advisors': ['ADVISOR-KB']
            },
            'HISTORY_RETRIEVE': {
                'department': '培训部 (知识库)',
                'primary_skill': 'memory-session-index',
                'secondary_skills': ['ADVISOR-KB'],
                'process': '历史检索 → 经验召回',
                'advisors': []
            },
            'PERFORMANCE_QUERY': {
                'department': '绩效考核部',
                'primary_skill': 'dream-performance-review',
                'secondary_skills': ['learning-episode-writer'],
                'process': '数据汇总 → 绩效计算 → 报告',
                'advisors': []
            },
            'STATS_QUERY': {
                'department': '研究部',
                'primary_skill': 'learning-episode-writer',
                'secondary_skills': ['memory-session-index'],
                'process': '数据查询 → 统计计算 → 报告',
                'advisors': []
            },
            'LESSON_CHECK': {
                'department': '培训部',
                'primary_skill': 'learning-lesson-distiller',
                'secondary_skills': ['learning-recall-pack'],
                'process': '教训检索 → 经验匹配 → 建议',
                'advisors': ['ADVISOR-KB']
            },
            'REPORT_GENERATE': {
                'department': '运营总监',
                'primary_skill': 'proactive-agent',
                'secondary_skills': ['pptx-generator', 'learning-episode-writer'],
                'process': '数据收集 → 整理 → 生成',
                'advisors': []
            },
            'AUTOMATION_CREATE': {
                'department': '运营总监',
                'primary_skill': 'automation_update',
                'secondary_skills': ['smart-skill-manager'],
                'process': '配置 → 评审 → 创建',
                'advisors': ['ADVISOR-SA']
            },
            'AUTOMATION_PAUSE': {
                'department': '运营总监',
                'primary_skill': 'automation_update',
                'secondary_skills': [],
                'process': '直接执行',
                'advisors': []
            },
            'AUTOMATION_LIST': {
                'department': '运营总监',
                'primary_skill': 'automation_update',
                'secondary_skills': [],
                'process': '直接查询',
                'advisors': []
            },
            'AUTOMATION_OPTIMIZE': {
                'department': '运营总监',
                'primary_skill': 'dream-operation-director',
                'secondary_skills': ['capability-evolver'],
                'process': '分析 → 评审 → 优化',
                'advisors': ['ADVISOR-SA', 'ADVISOR-QT']
            },
            'CONFUSION_SIGNAL': {
                'department': '待定',
                'primary_skill': '需要澄清',
                'secondary_skills': [],
                'process': '需要用户澄清',
                'advisors': []
            },
            'MULTI_INTENT': {
                'department': '待定',
                'primary_skill': '需要澄清',
                'secondary_skills': [],
                'process': '需要用户选择',
                'advisors': []
            },
            # v2.0 新增 - 日报与会议
            'DAILY_REPORT': {
                'department': '运营总监',
                'primary_skill': 'daily_report_system',
                'secondary_skills': [],
                'process': '收集7部门日报 → AI分析 → 生成汇报',
                'advisors': ['ADVISOR-SA']
            },
            'MEETING_START': {
                'department': '运营总监',
                'primary_skill': 'daily_report_system',
                'secondary_skills': [],
                'process': '创建会议记录 → 开始计时',
                'advisors': []
            },
            'MEETING_RECORD': {
                'department': '运营总监',
                'primary_skill': 'daily_report_system',
                'secondary_skills': [],
                'process': '记录讨论 → 提取决策 → 行动项',
                'advisors': ['ADVISOR-QT', 'ADVISOR-KB']
            },
            'CRITICISM': {
                'department': '绩效考核部',
                'primary_skill': 'daily_report_system',
                'secondary_skills': ['dream-performance-review'],
                'process': '分析问题 → 找出根因 → 提出改进',
                'advisors': ['ADVISOR-RM', 'ADVISOR-QT']
            },
            'SELF_CRITICISM': {
                'department': '培训部',
                'primary_skill': 'daily_report_system',
                'secondary_skills': ['learning-lesson-distiller'],
                'process': '自我反思 → 教训蒸馏 → 规则更新',
                'advisors': ['ADVISOR-KB']
            },
            # v3.0 新增 - 风险与紧急
            'RISK_PREDICTION': {
                'department': '风控部 + 研究部',
                'primary_skill': 'risk_emergency_system',
                'secondary_skills': ['dream-pretrade-gatekeeper', 'macro-monitor'],
                'process': '收集数据 → 第一性原理分析 → 场景推演 → 评分',
                'advisors': ['ADVISOR-RM', 'ADVISOR-MR']
            },
            'URGENT_RISK': {
                'department': '风控部 (紧急)',
                'primary_skill': 'risk_emergency_system',
                'secondary_skills': ['dream-pretrade-gatekeeper', 'dream-multiSkill'],
                'process': '立即评估 → 决策 → 执行 (10分钟内)',
                'advisors': ['ADVISOR-RM', 'ADVISOR-QT', 'ADVISOR-EE']
            },
            'EMERGENCY_RESPONSE': {
                'department': '紧急响应小组',
                'primary_skill': 'risk_emergency_system',
                'secondary_skills': ['dream-risk-position-sizing', 'dream-execution-cost-model'],
                'process': '组装顾问团队 → 评估 → 建议 → 执行',
                'advisors': ['ADVISOR-RM', 'ADVISOR-MR', 'ADVISOR-EE', 'ADVISOR-QT', 'ADVISOR-SA', 'ADVISOR-KB']
            },
            'UNKNOWN': {
                'department': '无法识别',
                'primary_skill': '无法识别',
                'secondary_skills': [],
                'process': '无法处理',
                'advisors': []
            },
        }

        route = base_routes.get(intent, base_routes['UNKNOWN'])

        return RoutingResult(
            primary_skill=route['primary_skill'],
            secondary_skills=route['secondary_skills'],
            department=route['department'],
            advisors=route['advisors'],
            process=route['process'],
            confirmation_required=intent_result.requires_confirmation
        )

    # ============================================================
    # 确认模板生成
    # ============================================================

    def generate_confirmation(self, intent_result: IntentResult, routing_result: RoutingResult) -> str:
        """生成确认消息"""
        if intent_result.intent == IntentType.CONFUSION_SIGNAL:
            return self._generate_ambiguous_confirm(intent_result)
        elif intent_result.intent == IntentType.MULTI_INTENT:
            return self._generate_multi_intent_confirm(intent_result)
        else:
            return self._generate_high_risk_confirm(intent_result, routing_result)

    def _generate_high_risk_confirm(self, intent_result: IntentResult, routing_result: RoutingResult) -> str:
        """生成高风险确认"""
        # 加载模板
        template_path = SKILL_DIR / "templates" / "high_risk_confirm.md"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            template = self._default_high_risk_template()

        # 填充模板
        intent_desc = self._get_intent_description(intent_result.intent.value)
        plan = self._generate_execution_plan(intent_result, routing_result)
        advisor_list = self._format_advisor_list(routing_result.advisors)
        risk_warnings = self._get_risk_warnings(intent_result)
        suggestion = self._get_secretary_suggestion(intent_result)

        return template.format(
            intent_description=intent_desc,
            execute_plan=plan,
            advisor_list=advisor_list,
            risk_warnings=risk_warnings,
            secretary_suggestion=suggestion
        )

    def _generate_ambiguous_confirm(self, intent_result: IntentResult) -> str:
        """生成模糊意图确认"""
        template_path = SKILL_DIR / "templates" / "ambiguous_confirm.md"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            template = self._default_ambiguous_template()

        confidence_pct = int(intent_result.confidence * 100)

        # 生成可能的情况
        options = [
            ("感觉行情不太对", "需要市场分析", "分析下行情"),
            ("感觉仓位不太对", "需要检查持仓", "看看仓位"),
            ("感觉系统不太对", "需要健康检查", "检查下系统"),
            ("感觉策略不太对", "需要顾问评审", "评审下策略"),
        ]

        return template.format(
            confidence=confidence_pct,
            option1=options[0][0],
            keyword1=options[0][2],
            option2=options[1][0],
            keyword2=options[1][2],
            option3=options[2][0],
            keyword3=options[2][2],
            option4=options[3][0],
            keyword4=options[3][2],
            clarification_prompt="您觉得哪里不太对？"
        )

    def _generate_multi_intent_confirm(self, intent_result: IntentResult) -> str:
        """生成多意图确认"""
        template_path = SKILL_DIR / "templates" / "multi_intent_confirm.md"
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            template = self._default_multi_intent_template()

        return template.format(
            intent1="开多仓",
            conf1=78,
            intent2="对信号有疑虑",
            conf2=65,
            suggestion1="先让量化顾问评审一下信号，再决定是否开多",
            suggestion2="用小仓验证 (10-20%)，同时收集数据",
            suggestion3="暂不执行，继续观察"
        )

    def _default_high_risk_template(self) -> str:
        return """┌─────────────────────────────────────────────────────────────────────┐
│                    🔴 重大操作确认                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  🎯 我理解的是: 您想要 {intent_description}                           │
│                                                                      │
│  ⚠️ 风险提示: {risk_warnings}                                         │
│                                                                      │
│  💡 秘书建议: {secretary_suggestion}                                   │
│                                                                      │
│  [✅ 同意执行] [✏️ 修改计划] [❌ 取消]                                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘"""

    def _default_ambiguous_template(self) -> str:
        return """┌─────────────────────────────────────────────────────────────────────┐
│                    🤔 需要澄清 (置信度 {confidence}%)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  我不太确定您指的是什么。                                              │
│                                                                      │
│  可能的情况:                                                          │
│  1️⃣ {option1} → 请说 "{keyword1}"                                    │
│  2️⃣ {option2} → 请说 "{keyword2}"                                    │
│  3️⃣ {option3} → 请说 "{keyword3}"                                    │
│  4️⃣ {option4} → 请说 "{keyword4}"                                    │
│                                                                      │
│  或者您直接告诉我: {clarification_prompt}                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘"""

    def _default_multi_intent_template(self) -> str:
        return """┌─────────────────────────────────────────────────────────────────────┐
│                    ⚠️ 多意图检测                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  您同时表达了两个可能冲突的意图:                                       │
│                                                                      │
│  1️⃣ {intent1} (置信度 {conf1}%)                                     │
│  2️⃣ {intent2} (置信度 {conf2}%)                                     │
│                                                                      │
│  📋 我的建议:                                                        │
│  选项A: {suggestion1}                                               │
│  选项B: {suggestion2}                                               │
│  选项C: {suggestion3}                                               │
│                                                                      │
│  您想怎么做?                                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘"""

    def _get_intent_description(self, intent: str) -> str:
        """获取意图描述"""
        descriptions = {
            'EXECUTE_LONG': '开多仓',
            'EXECUTE_SHORT': '开空仓',
            'EXECUTE_CLOSE': '平仓',
            'PARAM_ADJUST': '调整参数',
            'AUTOMATION_CREATE': '创建自动化任务',
            'AUTOMATION_PAUSE': '暂停自动化任务',
            'AUTOMATION_OPTIMIZE': '优化自动化任务',
        }
        return descriptions.get(intent, intent)

    def _generate_execution_plan(self, intent_result: IntentResult, routing_result: RoutingResult) -> str:
        """生成执行计划"""
        lines = []
        step = 1

        # 添加实体处理步骤
        for entity in intent_result.entities:
            if entity.type == 'symbol':
                lines.append(f"{step}. 获取 {entity.normalized} 的行情数据")
                step += 1

        # 添加顾问评审步骤
        if routing_result.advisors:
            advisor_names = {
                'ADVISOR-QT': '量化顾问',
                'ADVISOR-RM': '风控顾问',
                'ADVISOR-MR': '宏观顾问',
                'ADVISOR-EE': '执行顾问',
                'ADVISOR-SA': '架构顾问',
                'ADVISOR-KB': '大师知识库'
            }
            advisors = [advisor_names.get(a, a) for a in routing_result.advisors]
            lines.append(f"{step}. 顾问评审: {', '.join(advisors)}")
            step += 1

        # 添加执行步骤
        lines.append(f"{step}. 调用 {routing_result.primary_skill}")

        return '\n'.join(f"  {line}" for line in lines)

    def _format_advisor_list(self, advisors: List[str]) -> str:
        """格式化顾问列表"""
        if not advisors:
            return "  无需顾问评审"

        advisor_names = {
            'ADVISOR-QT': '量化顾问 (信号质量)',
            'ADVISOR-RM': '风控顾问 (仓位安全)',
            'ADVISOR-MR': '宏观顾问 (方向判断)',
            'ADVISOR-EE': '执行顾问 (成交质量)',
            'ADVISOR-SA': '架构顾问 (系统安全)',
            'ADVISOR-KB': '大师知识库 (历史经验)'
        }

        lines = []
        for advisor in advisors:
            name = advisor_names.get(advisor, advisor)
            lines.append(f"  • {name}")

        return '\n'.join(lines)

    def _get_risk_warnings(self, intent_result: IntentResult) -> str:
        """获取风险提示"""
        risk_warnings = {
            RiskLevel.HIGH: [
                "这是高风险操作，请仔细确认",
                "涉及真实资金，请谨慎操作"
            ],
            RiskLevel.MEDIUM: [
                "此操作可能影响系统配置",
                "建议先了解影响范围"
            ],
            RiskLevel.LOW: [
                "风险较低，但仍建议确认"
            ],
            RiskLevel.NONE: []
        }

        warnings = risk_warnings.get(intent_result.risk_level, [])
        if not warnings:
            return "  无特殊风险"

        return '\n'.join(f"  ⚠️ {w}" for w in warnings)

    def _get_secretary_suggestion(self, intent_result: IntentResult) -> str:
        """获取秘书建议"""
        suggestions = {
            'EXECUTE_LONG': "建议先让量化顾问评审信号质量",
            'EXECUTE_SHORT': "建议先让风控顾问评估仓位",
            'EXECUTE_CLOSE': "平仓后建议进行盘后审计",
            'PARAM_ADJUST': "建议小幅度调整，观察效果后再决定",
            'AUTOMATION_CREATE': "建议先创建测试自动化，验证后再全量",
            'AUTOMATION_PAUSE': "暂停后可随时恢复",
            'AUTOMATION_OPTIMIZE': "建议先备份当前配置",
        }

        return suggestions.get(intent_result.intent.value, "请确认执行")

    # ============================================================
    # 学习记录
    # ============================================================

    def record_learning(self, intent_result: IntentResult, corrected: bool = False,
                       user_feedback: Optional[Dict] = None, execution_result: Optional[str] = None,
                       satisfaction: Optional[int] = None):
        """记录学习"""
        record = LearningRecord(
            timestamp=datetime.now().isoformat(),
            type='intent_learn',
            original=intent_result.raw_text,
            recognized_intent=intent_result.intent.value,
            confidence=intent_result.confidence,
            corrected=corrected,
            user_feedback=user_feedback,
            execution_result=execution_result,
            satisfaction=satisfaction
        )
        self.learning_log.append(record)
        self._save_learning_log()

    def auto_learn(self):
        """自动学习 - 分析学习日志，优化规则"""
        # 统计纠正率高的意图
        intent_corrections = {}
        for record in self.learning_log:
            if record.corrected:
                if record.recognized_intent not in intent_corrections:
                    intent_corrections[record.recognized_intent] = 0
                intent_corrections[record.recognized_intent] += 1

        # 找出频繁被纠正的意图
        frequently_corrected = [k for k, v in intent_corrections.items() if v >= 3]

        if frequently_corrected:
            print(f"[秘书学习] 以下意图频繁被纠正，建议优化: {frequently_corrected}")

        return frequently_corrected

    # ============================================================
    # 主处理流程
    # ============================================================

    def process(self, user_input: str) -> Tuple[IntentResult, RoutingResult, Optional[str]]:
        """
        处理用户输入

        Returns:
            (意图识别结果, 路由结果, 确认消息/None)
        """
        # 1. 意图识别
        intent_result = self.recognize_intent(user_input)

        # 2. 目标路由
        routing_result = self.route_intent(intent_result)

        # 3. 判断是否需要确认
        confirmation = None
        if intent_result.requires_confirmation:
            confirmation = self.generate_confirmation(intent_result, routing_result)

        # 4. ⭐ Step3 集成：触发顾问会诊
        consultation_result = self._trigger_consultation_if_needed(intent_result, routing_result)
        if consultation_result:
            # 将会诊结果附加到路由结果中供下游使用
            routing_result = self._enrich_routing_with_consultation(routing_result, consultation_result)

        # 5. 记录学习
        self.record_learning(intent_result)

        return intent_result, routing_result, confirmation

    # ============================================================
    # Step3 顾问会诊触发
    # ============================================================

    def _trigger_consultation_if_needed(self, intent_result: IntentResult, 
                                        routing_result: RoutingResult) -> Optional[dict]:
        """
        Step3: 根据路由结果触发顾问会诊
        
        触发条件 (SOUL.md §6.1):
        - 路由结果包含顾问列表
        - 问题严重度 >= MEDIUM 或 置信度 < 80%
        - 连续SKIP >= 7次
        - 紧急风险事件
        """
        if not ADVISOR_INTEGRATION_AVAILABLE:
            return None

        # 判断是否需要会诊
        needs_consultation = self._should_trigger_consultation(intent_result, routing_result)
        if not needs_consultation:
            return None

        # 确定会诊类型
        consultation_type = self._map_consultation_type(intent_result, routing_result)

        # 确定优先级
        priority = self._map_priority(intent_result)

        # 构建上下文
        context = {
            "problem_title": self._get_intent_description(intent_result.intent.value),
            "intent_type": intent_result.intent.value,
            "confidence": intent_result.confidence,
            "risk_level": intent_result.risk_level.value,
            "raw_input": intent_result.raw_text,
            "advisors_required": routing_result.advisors,
        }

        # 添加实体信息
        if intent_result.entities:
            context["entities"] = [asdict(e) for e in intent_result.entities]

        try:
            result = SecretaryConsultation.conduct_consultation(
                problem_id=f"INT-{datetime.now().strftime('%Y%m%d%H%M')}",
                title=context["problem_title"],
                context=context,
                consultation_type=consultation_type,
                priority=priority,
                wait_for_responses=False  # 异步模式，不阻塞
            )
            print(f"[秘书Step3] ✅ 顾问会诊已触发: {result.get('consultation_id', 'N/A')}")
            print(f"[秘书Step3]    类型: {consultation_type} | 优先级: {priority}")
            print(f"[秘书Step3]    必需顾问: {result.get('required_advisors', [])}")
            return result
        except Exception as e:
            print(f"[秘书Step3] ⚠️ 顾问会诊触发失败: {e}")
            return None

    def _should_trigger_consultation(self, intent_result: IntentResult, 
                                      routing_result: RoutingResult) -> bool:
        """判断是否需要触发顾问会诊"""
        # 1. 路由结果包含顾问 → 需要
        if routing_result.advisors and routing_result.advisors != ['按类型路由'] and routing_result.advisors != ['按请求类型']:
            return True

        # 2. 高风险意图 → 需要
        if intent_result.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            return True

        # 3. 置信度低 → 需要
        if intent_result.confidence < 0.60:
            return True

        # 4. 特定意图类型强制触发
        force_trigger_intents = {
            IntentType.ADVISOR_CONSULT,
            IntentType.ADVISOR_REVIEW,
            IntentType.RISK_PREDICTION,
            IntentType.URGENT_RISK,
            IntentType.EMERGENCY_RESPONSE,
        }
        if intent_result.intent in force_trigger_intents:
            return True

        return False

    def _map_consultation_type(self, intent_result: IntentResult, 
                                routing_result: RoutingResult) -> str:
        """将意图类型映射为会诊类型"""
        intent_to_consultation = {
            IntentType.EXECUTE_LONG: ConsultationType.SIGNAL_ASSESSMENT if ConsultationType else "SIGNAL_ASSESSMENT",
            IntentType.EXECUTE_SHORT: ConsultationType.SIGNAL_ASSESSMENT if ConsultationType else "SIGNAL_ASSESSMENT",
            IntentType.EXECUTE_CLOSE: ConsultationType.RISK_REVIEW if ConsultationType else "RISK_REVIEW",
            IntentType.MARKET_ANALYSIS: ConsultationType.MACRO_ANALYSIS if ConsultationType else "MACRO_ANALYSIS",
            IntentType.OPPORTUNITY_SCAN: ConsultationType.SIGNAL_ASSESSMENT if ConsultationType else "SIGNAL_ASSESSMENT",
            IntentType.ADVISOR_CONSULT: ConsultationType.STRATEGY_ASSESSMENT if ConsultationType else "STRATEGY_ASSESSMENT",
            IntentType.ADVISOR_REVIEW: ConsultationType.STRATEGY_REVIEW if ConsultationType else "STRATEGY_REVIEW",
            IntentType.RISK_PREDICTION: ConsultationType.RISK_REVIEW if ConsultationType else "RISK_REVIEW",
            IntentType.URGENT_RISK: ConsultationType.EMERGENCY_RESPONSE if ConsultationType else "EMERGENCY_RESPONSE",
            IntentType.EMERGENCY_RESPONSE: ConsultationType.EMERGENCY_RESPONSE if ConsultationType else "EMERGENCY_RESPONSE",
        }
        return intent_to_consultation.get(
            intent_result.intent,
            ConsultationType.SIGNAL_ASSESSMENT if ConsultationType else "SIGNAL_ASSESSMENT"
        )

    def _map_priority(self, intent_result: IntentResult) -> str:
        """将风险等级映射为会诊优先级"""
        priority_map = {
            RiskLevel.CRITICAL: "URGENT",
            RiskLevel.HIGH: "HIGH",
            RiskLevel.MEDIUM: "NORMAL",
            RiskLevel.LOW: "NORMAL",
            RiskLevel.NONE: "LOW",
        }
        return priority_map.get(intent_result.risk_level, "NORMAL")

    def _enrich_routing_with_consultation(self, routing_result: RoutingResult, 
                                           consultation_result: dict) -> RoutingResult:
        """将会诊结果附加到路由结果中"""
        # 创建新的RoutingResult，保留原有信息并附加会诊信息
        enriched = RoutingResult(
            primary_skill=routing_result.primary_skill,
            secondary_skills=routing_result.secondary_skills,
            department=routing_result.department,
            advisors=routing_result.advisors,
            process=routing_result.process,
            confirmation_required=routing_result.confirmation_required
        )
        # 将会诊信息作为额外属性存储
        enriched.__dict__['_consultation'] = consultation_result
        return enriched

    def check_consultation_status(self, consultation_id: str) -> Optional[dict]:
        """查询会诊状态（供Step4/Step5使用）"""
        if not ADVISOR_INTEGRATION_AVAILABLE:
            return None
        try:
            return SecretaryConsultation.get_consultation_status(consultation_id)
        except Exception:
            return None

    def get_consultation_summary(self, consultation_id: str) -> Optional[dict]:
        """获取会诊汇总（供Step4执行决策使用）"""
        if not ADVISOR_INTEGRATION_AVAILABLE:
            return None
        try:
            return SecretaryConsultation.get_consultation_summary(consultation_id)
        except Exception:
            return None


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        "BTC现在多少",
        "开多BTC",
        "感觉不太对",
        "开多但我觉得不稳",
        "把杠杆调到5倍",
        "帮我看看仓位",
        "有什么机会吗"
    ]

    secretary = SecretaryCore()

    print("=" * 60)
    print("🤵 老板秘书核心引擎测试")
    print("=" * 60)

    for text in test_cases:
        print(f"\n📝 输入: {text}")
        print("-" * 40)

        intent, routing, confirmation = secretary.process(text)

        print(f"🎯 意图: {intent.intent.value}")
        print(f"📊 置信度: {intent.confidence:.0%}")
        print(f"⚠️ 风险等级: {intent.risk_level.value}")
        print(f"🔍 匹配关键词: {intent.keywords_matched}")
        if intent.entities:
            print(f"🏷️ 提取实体: {[e.normalized for e in intent.entities]}")
        print(f"🏢 路由部门: {routing.department}")
        print(f"🔧 主Skill: {routing.primary_skill}")
        print(f"👥 顾问: {routing.advisors}")

        if confirmation:
            print(f"\n📋 需要确认:")
            print(confirmation)

        print("=" * 60)

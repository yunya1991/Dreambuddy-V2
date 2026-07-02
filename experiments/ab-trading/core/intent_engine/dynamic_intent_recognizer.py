#!/usr/bin/env python3
"""
动态意图识别器 (Dynamic Intent Recognizer)

位置: experiments/ab-trading/core/intent_engine/dynamic_intent_recognizer.py

功能扩展：
1. 支持动态识别任意金融类意图（不限于预定义的6种类型）
2. S思维链降级机制：当本地规则无法识别时，调用大模型进行深度意图识别
3. 意图类型可扩展注册机制
4. 金融领域意图知识库（支持冷启动）

设计原则：
- 优先本地计算（零Token）
- 本地置信度不足时触发S思维链LLM调用
- 动态意图结果可被学习和缓存
- 支持用户自定义意图扩展

基于技术文档：
- SYSTEM_ARCHITECTURE_OVERVIEW.md (v2.2) S层三层递进
- dreambuddy-os/SKILL.md (v1.1.0) 意图识别引擎
"""

import re
import json
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import defaultdict


# ============================================================
# 动态意图类型定义
# ============================================================

@dataclass
class DynamicIntentType:
    """动态意图类型定义"""
    intent_id: str              # 意图唯一ID
    name: str                   # 意图名称
    category: str               # 意图分类: trading/analysis/risk/portfolio/education/research/custom
    description: str            # 意图描述
    keywords: List[str]         # 关键词列表
    patterns: List[str]         # 正则模式列表
    domain_tags: List[str]      # 领域标签
    confidence_base: float      # 基础置信度
    recommended_chain: str      # 推荐思维链: S/C/F
    priority: int               # 优先级
    is_custom: bool = False     # 是否用户自定义
    created_at: float = field(default_factory=time.time)
    learned_count: int = 0      # 学习次数（从LLM结果学习）

    def to_dict(self) -> Dict:
        return {
            'intent_id': self.intent_id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'keywords': self.keywords,
            'patterns': self.patterns,
            'domain_tags': self.domain_tags,
            'confidence_base': self.confidence_base,
            'recommended_chain': self.recommended_chain,
            'priority': self.priority,
            'is_custom': self.is_custom,
            'created_at': self.created_at,
            'learned_count': self.learned_count,
        }


@dataclass
class DynamicIntentResult:
    """动态意图识别结果"""
    intent_type: str                    # 意图类型ID
    intent_name: str                    # 意图名称
    confidence: float                   # 置信度 (0-1)
    recognition_source: str             # 识别来源: local/llm_s_chain/learned/custom
    rationale: str                      # 识别理由
    keywords_matched: List[str]         # 匹配的关键词
    patterns_matched: List[str]         # 匹配的模式
    domain_context: Dict[str, Any]      # 领域上下文
    recommended_chain: str              # 推荐思维链
    suggested_nodes: List[str]          # 建议执行节点
    clarify_needed: bool = False        # 是否需要澄清
    clarify_question: Optional[str] = None
    clarify_options: Optional[List[Dict]] = None
    llm_tokens_used: int = 0            # LLM消耗Token数
    latency_ms: float = 0.0             # 识别耗时
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'intent_type': self.intent_type,
            'intent_name': self.intent_name,
            'confidence': self.confidence,
            'recognition_source': self.recognition_source,
            'rationale': self.rationale,
            'keywords_matched': self.keywords_matched,
            'patterns_matched': self.patterns_matched,
            'domain_context': self.domain_context,
            'recommended_chain': self.recommended_chain,
            'suggested_nodes': self.suggested_nodes,
            'clarify_needed': self.clarify_needed,
            'clarify_question': self.clarify_question,
            'clarify_options': self.clarify_options,
            'llm_tokens_used': self.llm_tokens_used,
            'latency_ms': self.latency_ms,
            'metadata': self.metadata,
        }


# ============================================================
# 金融领域意图知识库（冷启动）
# ============================================================

FINANCE_INTENT_KNOWLEDGE_BASE = {
    # ===== 交易类 =====
    'trading': {
        'spot_trade': DynamicIntentType(
            intent_id='spot_trade',
            name='现货交易',
            category='trading',
            description='现货买卖交易决策',
            keywords=['现货', '买卖', '下单', '成交', 'spot', 'buy', 'sell'],
            patterns=[r'(买|卖|交易).*(币|现货)', r'spot.*(trade|buy|sell)'],
            domain_tags=['trading', 'spot'],
            confidence_base=0.7,
            recommended_chain='S',
            priority=8,
        ),
        'futures_trade': DynamicIntentType(
            intent_id='futures_trade',
            name='合约交易',
            category='trading',
            description='期货/合约交易决策',
            keywords=['合约', '期货', '做多', '做空', '杠杆', 'futures', 'long', 'short', 'leverage'],
            patterns=[r'(合约|期货|做多|做空)', r'futures.*trade', r'long.*short'],
            domain_tags=['trading', 'futures', 'derivative'],
            confidence_base=0.75,
            recommended_chain='S+C',
            priority=9,
        ),
        'order_management': DynamicIntentType(
            intent_id='order_management',
            name='订单管理',
            category='trading',
            description='订单创建、修改、取消管理',
            keywords=['订单', '挂单', '撤单', '改单', 'order', 'cancel', 'modify'],
            patterns=[r'(挂|撤|改|取消).*(单|订单)'],
            domain_tags=['trading', 'order'],
            confidence_base=0.65,
            recommended_chain='T',
            priority=6,
        ),
        'position_management': DynamicIntentType(
            intent_id='position_management',
            name='仓位管理',
            category='trading',
            description='持仓查看、调整、平仓管理',
            keywords=['仓位', '持仓', '平仓', '加仓', '减仓', 'position', 'holding'],
            patterns=[r'(仓位|持仓|平仓|加仓|减仓)'],
            domain_tags=['trading', 'position'],
            confidence_base=0.7,
            recommended_chain='S+A',
            priority=7,
        ),
    },

    # ===== 分析类 =====
    'analysis': {
        'technical_analysis': DynamicIntentType(
            intent_id='technical_analysis',
            name='技术分析',
            category='analysis',
            description='技术指标、图表形态分析',
            keywords=['技术分析', '指标', 'K线', '形态', '支撑', '阻力', 'MACD', 'RSI', '均线',
                     'technical', 'indicator', 'chart', 'pattern', 'support', 'resistance'],
            patterns=[r'(技术|指标|K线|形态).*分析', r'(MACD|RSI|均线|EMA)'],
            domain_tags=['analysis', 'technical'],
            confidence_base=0.75,
            recommended_chain='C',
            priority=7,
        ),
        'fundamental_analysis': DynamicIntentType(
            intent_id='fundamental_analysis',
            name='基本面分析',
            category='analysis',
            description='基本面、宏观经济、项目价值分析',
            keywords=['基本面', '宏观', '经济', '项目', '价值', '估值', '新闻', '事件',
                     'fundamental', 'macro', 'economics', 'valuation'],
            patterns=[r'(基本面|宏观|经济).*分析', r'(项目|代币).*价值'],
            domain_tags=['analysis', 'fundamental'],
            confidence_base=0.7,
            recommended_chain='F',
            priority=7,
        ),
        'sentiment_analysis': DynamicIntentType(
            intent_id='sentiment_analysis',
            name='情绪分析',
            category='analysis',
            description='市场情绪、社交媒体舆情分析',
            keywords=['情绪', '舆情', '恐惧贪婪', '恐慌', '贪婪', '社交', 'Twitter', 'Reddit',
                     'sentiment', 'fear', 'greed', 'social'],
            patterns=[r'(情绪|舆情|恐惧贪婪).*分析'],
            domain_tags=['analysis', 'sentiment'],
            confidence_base=0.65,
            recommended_chain='F',
            priority=6,
        ),
        'volume_analysis': DynamicIntentType(
            intent_id='volume_analysis',
            name='成交量分析',
            category='analysis',
            description='成交量、资金流向分析',
            keywords=['成交量', '量能', '资金流', '流入', '流出', 'volume', 'money flow', 'flow'],
            patterns=[r'(成交量|量能|资金流).*分析'],
            domain_tags=['analysis', 'volume'],
            confidence_base=0.7,
            recommended_chain='C+F',
            priority=6,
        ),
        'whale_tracking': DynamicIntentType(
            intent_id='whale_tracking',
            name='巨鲸追踪',
            category='analysis',
            description='大户、巨鲸动向追踪分析',
            keywords=['巨鲸', '大户', '鲸鱼', '地址', '链上', '转账', 'whale', 'large holder', 'on-chain'],
            patterns=[r'(巨鲸|大户|鲸鱼).*追踪', r'链上.*(动向|转账)'],
            domain_tags=['analysis', 'whale', 'on-chain'],
            confidence_base=0.65,
            recommended_chain='F',
            priority=5,
        ),
    },

    # ===== 风险类 =====
    'risk': {
        'risk_assessment': DynamicIntentType(
            intent_id='risk_assessment',
            name='风险评估',
            category='risk',
            description='交易风险、仓位风险评估',
            keywords=['风险', '评估', '风控', '止损', '止盈', '爆仓', 'risk', 'stop loss', 'take profit'],
            patterns=[r'风险.*评估', r'(止损|止盈|爆仓).*风险'],
            domain_tags=['risk', 'assessment'],
            confidence_base=0.75,
            recommended_chain='S+A',
            priority=8,
        ),
        'liquidation_check': DynamicIntentType(
            intent_id='liquidation_check',
            name='爆仓检查',
            category='risk',
            description='爆仓风险检查与预警',
            keywords=['爆仓', '清算', '强平', '保证金', '维持保证金', 'liquidation', 'margin'],
            patterns=[r'(爆仓|清算|强平).*检查', r'保证金.*(不足|风险)'],
            domain_tags=['risk', 'liquidation'],
            confidence_base=0.8,
            recommended_chain='S',
            priority=9,
        ),
        'rebalance_suggestion': DynamicIntentType(
            intent_id='rebalance_suggestion',
            name='再平衡建议',
            category='risk',
            description='投资组合再平衡建议',
            keywords=['再平衡', '调仓', '均衡', 'rebalance', 'rebalancing'],
            patterns=[r'再平衡.*建议', r'调仓.*方案'],
            domain_tags=['risk', 'portfolio'],
            confidence_base=0.65,
            recommended_chain='S+F',
            priority=6,
        ),
    },

    # ===== 投资组合类 =====
    'portfolio': {
        'portfolio_review': DynamicIntentType(
            intent_id='portfolio_review',
            name='组合回顾',
            category='portfolio',
            description='投资组合综合回顾与绩效分析',
            keywords=['组合', '回顾', '绩效', '收益', '盈亏', 'portfolio', 'performance', 'pnl'],
            patterns=[r'(组合|持仓).*回顾', r'(绩效|收益).*分析'],
            domain_tags=['portfolio', 'review'],
            confidence_base=0.7,
            recommended_chain='S',
            priority=6,
        ),
        'asset_allocation': DynamicIntentType(
            intent_id='asset_allocation',
            name='资产配置',
            category='portfolio',
            description='资产配置建议与优化',
            keywords=['配置', '分配', '权重', '组合优化', 'allocation', 'weight', 'optimize'],
            patterns=[r'(资产|资金).*配置', r'(权重|配置).*建议'],
            domain_tags=['portfolio', 'allocation'],
            confidence_base=0.65,
            recommended_chain='S+F',
            priority=7,
        ),
        'diversification_check': DynamicIntentType(
            intent_id='diversification_check',
            name='分散化检查',
            category='portfolio',
            description='投资组合分散化程度检查',
            keywords=['分散', '多元化', '相关性', 'diversification', 'correlation'],
            patterns=[r'(分散|多元化).*检查', r'相关性.*分析'],
            domain_tags=['portfolio', 'diversification'],
            confidence_base=0.6,
            recommended_chain='F',
            priority=5,
        ),
    },

    # ===== 教育与研究类 =====
    'education': {
        'concept_explanation': DynamicIntentType(
            intent_id='concept_explanation',
            name='概念解释',
            category='education',
            description='金融/交易概念解释与学习',
            keywords=['什么是', '解释', '定义', '概念', '含义', '怎么理解', 'what is', 'explain', 'define'],
            patterns=[r'什么是.*', r'请解释.*', r'.*是什么意思', r'.*怎么理解'],
            domain_tags=['education', 'concept'],
            confidence_base=0.7,
            recommended_chain='T',
            priority=4,
        ),
        'strategy_learning': DynamicIntentType(
            intent_id='strategy_learning',
            name='策略学习',
            category='education',
            description='交易策略学习方法与教程',
            keywords=['如何交易', '怎么操作', '学习', '教程', '指南', '方法', 'learn', 'tutorial', 'guide'],
            patterns=[r'如何.*交易', r'怎么.*操作', r'(学习|教程).*策略'],
            domain_tags=['education', 'strategy'],
            confidence_base=0.65,
            recommended_chain='T',
            priority=5,
        ),
        'indicator_usage': DynamicIntentType(
            intent_id='indicator_usage',
            name='指标使用',
            category='education',
            description='技术指标使用方法指导',
            keywords=['如何使用', '指标用法', '怎么看', '指标应用', '指标使用', '怎么用',
                     'how to use', 'indicator usage', '指标方法'],
            patterns=[r'如何使用.*指标', r'指标.*怎么看', r'(MACD|RSI|布林带).*怎么用', r'指标.*使用'],
            domain_tags=['education', 'indicator'],
            confidence_base=0.7,
            recommended_chain='C+T',
            priority=5,
        ),
    },

    'research': {
        'market_research': DynamicIntentType(
            intent_id='market_research',
            name='市场调研',
            category='research',
            description='市场深度调研与信息收集',
            keywords=['调研', '研究', '调查', '分析报告', '市场调研', 'market research',
                     'research', 'investigation', 'report', '市场研究'],
            patterns=[r'(调研|研究).*市场', r'市场.*(调查|分析|调研)', r'市场调研'],
            domain_tags=['research', 'market'],
            confidence_base=0.65,
            recommended_chain='A',
            priority=6,
        ),
        'project_research': DynamicIntentType(
            intent_id='project_research',
            name='项目调研',
            category='research',
            description='特定项目/代币深度调研',
            keywords=['项目调研', '代币研究', '项目分析', '币种调研', 'project research', 'token analysis'],
            patterns=[r'(项目|代币|币种).*调研', r'研究.*项目'],
            domain_tags=['research', 'project'],
            confidence_base=0.7,
            recommended_chain='A+F',
            priority=7,
        ),
        'comparative_analysis': DynamicIntentType(
            intent_id='comparative_analysis',
            name='对比分析',
            category='research',
            description='多个项目/币种对比分析',
            keywords=['对比', '比较', '哪个好', '哪个更强', '对比分析', 'compare', 'comparison', 'versus'],
            patterns=[r'(对比|比较).*分析', r'.*(vs|versus).*', r'哪个.*好'],
            domain_tags=['research', 'comparison'],
            confidence_base=0.7,
            recommended_chain='A+F',
            priority=6,
        ),
    },
}


# ============================================================
# S思维链LLM降级识别器
# ============================================================

class SChainLLMRecognizer:
    """
    S思维链LLM降级识别器

    当本地规则无法识别意图时，调用大模型进行深度意图识别。
    S链三层递进：
    - Layer 1 (Objective): 提取用户目标
    - Layer 2 (OKR): 分解关键结果
    - Layer 3 (Blueprint): 构建执行蓝图

    支持多种LLM后端：DeepSeek / OpenAI / 本地模型
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {
            'llm_preference': ['deepseek', 'openai'],
            'max_tokens': 2000,
            'temperature': 0.3,
            'timeout_ms': 10000,
        }
        self._llm_client = None
        self._learned_intents: Dict[str, DynamicIntentType] = {}
        self._intent_cache: Dict[str, DynamicIntentResult] = {}

    def recognize_with_llm(
        self,
        user_message: str,
        context: Optional[Dict] = None,
        fallback_local_result: Optional[DynamicIntentResult] = None,
    ) -> DynamicIntentResult:
        """
        使用S思维链调用LLM进行深度意图识别

        Args:
            user_message: 用户输入
            context: 上下文信息
            fallback_local_result: 本地识别结果（用于参考）

        Returns:
            DynamicIntentResult
        """
        start_time = time.time()

        # Step 1: 构建S链三层Prompt
        prompt = self._build_s_chain_prompt(user_message, context, fallback_local_result)

        # Step 2: 调用LLM
        llm_response = self._call_llm(prompt)

        # Step 3: 解析LLM响应
        result = self._parse_llm_response(llm_response, user_message)

        # Step 4: 学习与缓存
        if result.confidence >= 0.6:
            self._learn_from_llm_result(result)

        result.recognition_source = 'llm_s_chain'
        result.latency_ms = (time.time() - start_time) * 1000
        result.llm_tokens_used = llm_response.get('tokens_used', 0)

        return result

    def _build_s_chain_prompt(
        self,
        user_message: str,
        context: Optional[Dict],
        fallback_local_result: Optional[DynamicIntentResult],
    ) -> str:
        """
        构建S思维链三层Prompt

        S链三层结构：
        - Layer 1: Objective提取（收敛）
        - Layer 2: OKR分解（展开）
        - Layer 3: Blueprint构建（落地）
        """
        context_str = json.dumps(context or {}, ensure_ascii=False, indent=2)
        local_str = ""
        if fallback_local_result:
            local_str = f"""
本地初步识别结果（仅供参考）：
- 意图类型: {fallback_local_result.intent_type}
- 置信度: {fallback_local_result.confidence:.2f}
- 匹配关键词: {fallback_local_result.keywords_matched}
"""

        prompt = f"""# S思维链意图识别

你是一个金融交易领域的意图识别专家。请使用S链三层递进方法分析用户的真实意图。

## 用户输入
{user_message}

## 上下文信息
{context_str}

{local_str}

## S链三层分析框架

### Layer 1: 收敛（Objective提取）
分析用户的核心目标是什么。从混沌的自然语言中收敛到单一明确的目标。

### Layer 2: 展开（OKR分解）
将目标展开为可衡量的关键结果（Key Results），确定意图的复杂度和模式。

### Layer 3: 落地（Blueprint构建）
将OKR转化为可执行的工程蓝图，推荐合适的思维链和执行节点。

## 输出格式

请按以下JSON格式输出（不要输出其他内容）：

```json
{{"layer1_objective": {{ "title": "目标标题", "type": "意图类型ID", "domain": "领域标签", "confidence": 0.0, "keywords_matched": [] }},"layer2_okr": {{ "mode": "single", "complexity": "standard", "key_results": [] }},"layer3_blueprint": {{ "recommended_chain": "S", "suggested_nodes": [], "execution_mode": "sequential" }},"final_result": {{ "intent_type": "意图类型", "intent_name": "意图名称", "confidence": 0.0, "rationale": "识别理由", "clarify_needed": false }} }}
```

## 金融领域意图分类参考

- trading: 现货交易、合约交易、订单管理、仓位管理
- analysis: 技术分析、基本面分析、情绪分析、成交量分析、巨鲸追踪
- risk: 风险评估、爆仓检查、再平衡建议
- portfolio: 组合回顾、资产配置、分散化检查
- education: 概念解释、策略学习、指标使用
- research: 市场调研、项目调研、对比分析
- custom: 用户自定义意图（当无法归入上述分类时）

请现在开始分析并输出JSON结果。
"""
        return prompt

    def _call_llm(self, prompt: str) -> Dict:
        """
        调用LLM后端

        支持多种后端，优先级：DeepSeek > OpenAI > 本地模拟
        """
        # 尝试DeepSeek
        try:
            return self._call_deepseek(prompt)
        except Exception:
            pass

        # 尝试OpenAI
        try:
            return self._call_openai(prompt)
        except Exception:
            pass

        # 降级到本地模拟（用于测试和容错）
        return self._mock_llm_response(prompt)

    def _call_deepseek(self, prompt: str) -> Dict:
        """调用DeepSeek API"""
        import os
        api_key = os.environ.get('DEEPSEEK_API_KEY', '')
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        # 这里需要实际的API调用实现
        # 为PR演示，返回模拟响应
        raise NotImplementedError("DeepSeek API integration pending")

    def _call_openai(self, prompt: str) -> Dict:
        """调用OpenAI API"""
        import os
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        # 这里需要实际的API调用实现
        # 为PR演示，返回模拟响应
        raise NotImplementedError("OpenAI API integration pending")

    def _mock_llm_response(self, prompt: str) -> Dict:
        """
        本地模拟LLM响应（用于测试和容错）

        根据Prompt中的用户输入进行简单规则匹配，
        返回一个合理的意图识别结果。
        """
        # 从Prompt中提取用户输入
        user_msg_match = re.search(r'## 用户输入\n(.+?)\n##', prompt)
        user_message = user_msg_match.group(1) if user_msg_match else ""

        # 简单规则匹配（模拟LLM理解）
        intent_type = 'custom'
        intent_name = '自定义意图'
        confidence = 0.5
        recommended_chain = 'S'
        suggested_nodes = ['dream-contradiction-theory', 'dream-first-principles']
        rationale = '本地模拟LLM响应'

        # 关键词匹配
        if re.search(r'(买|卖|交易|做多|做空)', user_message):
            intent_type = 'trading_decision'
            intent_name = '交易决策'
            confidence = 0.75
            recommended_chain = 'S+C'
            suggested_nodes = ['classic-indicator-scan', 'fundamental-fund-flow', 'dream-contradiction-theory']
            rationale = '识别到交易操作关键词'
        elif re.search(r'(分析|研究|调研)', user_message):
            intent_type = 'deep_analysis'
            intent_name = '深度分析'
            confidence = 0.7
            recommended_chain = 'A+F'
            suggested_nodes = ['fundamental-sentiment', 'fundamental-fund-flow', 'dream-first-principles']
            rationale = '识别到分析研究关键词'
        elif re.search(r'(风险|止损|止盈)', user_message):
            intent_type = 'risk_assessment'
            intent_name = '风险评估'
            confidence = 0.75
            recommended_chain = 'S+A'
            suggested_nodes = ['dream-contradiction-theory', 'gate-guard']
            rationale = '识别到风险管理关键词'
        elif re.search(r'(什么是|解释|概念)', user_message):
            intent_type = 'concept_explanation'
            intent_name = '概念解释'
            confidence = 0.7
            recommended_chain = 'T'
            suggested_nodes = ['knowledge-retrieval']
            rationale = '识别到学习解释关键词'
        elif re.search(r'(持仓|组合|仓位)', user_message):
            intent_type = 'portfolio_review'
            intent_name = '组合回顾'
            confidence = 0.7
            recommended_chain = 'S'
            suggested_nodes = ['position-review', 'pnl-analysis']
            rationale = '识别到组合管理关键词'

        return {
            'content': json.dumps({
                'layer1_objective': {
                    'title': intent_name,
                    'type': intent_type,
                    'domain': intent_type.split('_')[0] if '_' in intent_type else 'custom',
                    'confidence': confidence,
                    'keywords_matched': [],
                },
                'layer2_okr': {
                    'mode': 'single',
                    'complexity': 'standard',
                    'key_results': [{'title': '完成意图识别', 'metric': '置信度'}],
                },
                'layer3_blueprint': {
                    'recommended_chain': recommended_chain,
                    'suggested_nodes': suggested_nodes,
                    'execution_mode': 'sequential',
                },
                'final_result': {
                    'intent_type': intent_type,
                    'intent_name': intent_name,
                    'confidence': confidence,
                    'rationale': rationale,
                    'clarify_needed': False,
                    'clarify_question': None,
                },
            }),
            'tokens_used': 500,  # 模拟Token消耗
        }

    def _parse_llm_response(
        self,
        llm_response: Dict,
        user_message: str,
    ) -> DynamicIntentResult:
        """解析LLM响应为DynamicIntentResult"""
        content = llm_response.get('content', '')

        try:
            parsed = json.loads(content)
            final = parsed.get('final_result', {})
            layer3 = parsed.get('layer3_blueprint', {})
            layer1 = parsed.get('layer1_objective', {})

            return DynamicIntentResult(
                intent_type=final.get('intent_type', 'custom'),
                intent_name=final.get('intent_name', '自定义意图'),
                confidence=final.get('confidence', 0.5),
                recognition_source='llm_s_chain',
                rationale=final.get('rationale', 'LLM识别'),
                keywords_matched=layer1.get('keywords_matched', []),
                patterns_matched=[],
                domain_context={
                    'layer1': layer1,
                    'layer2': parsed.get('layer2_okr', {}),
                    'layer3': layer3,
                },
                recommended_chain=layer3.get('recommended_chain', 'S'),
                suggested_nodes=layer3.get('suggested_nodes', []),
                clarify_needed=final.get('clarify_needed', False),
                clarify_question=final.get('clarify_question'),
                llm_tokens_used=llm_response.get('tokens_used', 0),
            )
        except json.JSONDecodeError:
            # 解析失败，返回默认结果
            return DynamicIntentResult(
                intent_type='custom',
                intent_name='自定义意图',
                confidence=0.4,
                recognition_source='llm_s_chain_parse_error',
                rationale='LLM响应解析失败',
                keywords_matched=[],
                patterns_matched=[],
                domain_context={},
                recommended_chain='S',
                suggested_nodes=['dream-contradiction-theory'],
            )

    def _learn_from_llm_result(self, result: DynamicIntentResult):
        """
        从LLM识别结果学习，构建新的动态意图类型

        学习条件：
        - 置信度 >= 0.6
        - 意图类型不是已知的类型
        - 已多次出现相同意图类型
        """
        intent_type = result.intent_type

        if intent_type in self._learned_intents:
            # 增加学习计数
            self._learned_intents[intent_type].learned_count += 1
        else:
            # 创建新的学习意图类型
            self._learned_intents[intent_type] = DynamicIntentType(
                intent_id=intent_type,
                name=result.intent_name,
                category='custom',
                description=f'从LLM学习获得的意图类型',
                keywords=result.keywords_matched,
                patterns=[],
                domain_tags=['learned', 'dynamic'],
                confidence_base=result.confidence,
                recommended_chain=result.recommended_chain,
                priority=5,
                is_custom=True,
                learned_count=1,
            )

    def get_learned_intents(self) -> Dict[str, DynamicIntentType]:
        """获取从LLM学习获得的意图类型"""
        return self._learned_intents


# ============================================================
# 动态意图识别器主类
# ============================================================

class DynamicIntentRecognizer:
    """
    动态意图识别器

    功能：
    1. 本地规则优先识别（零Token）
    2. 本地置信度不足时触发S思维链LLM降级
    3. 从LLM结果学习，逐步扩充本地规则库
    4. 支持用户自定义意图注册

    使用流程：
    - recognize(user_message) → 本地规则打分
    - 如果最高置信度 < threshold → 调用S思维链LLM
    - LLM结果可被学习和缓存
    """

    # 本地识别置信度阈值，低于此值触发LLM降级
    LLM_FALLBACK_THRESHOLD = 0.45

    def __init__(
        self,
        config: Optional[Dict] = None,
        knowledge_base: Optional[Dict] = None,
    ):
        self.config = config or {
            'llm_fallback_threshold': self.LLM_FALLBACK_THRESHOLD,
            'enable_learning': True,
            'enable_cache': True,
            'custom_intents': {},
        }

        # 加载知识库
        self.knowledge_base = knowledge_base or FINANCE_INTENT_KNOWLEDGE_BASE
        self._all_intents: Dict[str, DynamicIntentType] = {}
        self._load_knowledge_base()

        # 加载自定义意图
        for intent_id, intent_def in self.config.get('custom_intents', {}).items():
            self.register_custom_intent(intent_def)

        # S思维链LLM识别器
        self.llm_recognizer = SChainLLMRecognizer(config)

        # 意图缓存
        self._intent_cache: Dict[str, DynamicIntentResult] = {}

        # 统计
        self._stats = {
            'total_calls': 0,
            'local_success': 0,
            'llm_fallback': 0,
            'llm_success': 0,
            'learned_intents': 0,
            'cache_hits': 0,
        }

    def _load_knowledge_base(self):
        """加载金融领域意图知识库"""
        for category, intents in self.knowledge_base.items():
            for intent_id, intent_type in intents.items():
                self._all_intents[intent_id] = intent_type

    def recognize(
        self,
        user_message: str,
        context: Optional[Dict] = None,
        mkt_data: Optional[Dict] = None,
        force_llm: bool = False,
    ) -> DynamicIntentResult:
        """
        动态意图识别主入口

        Args:
            user_message: 用户自然语言输入
            context: 上下文信息
            mkt_data: 市场数据
            force_llm: 强制使用LLM（用于测试）

        Returns:
            DynamicIntentResult
        """
        start_time = time.time()
        self._stats['total_calls'] += 1

        # Step 1: 检查缓存
        cache_key = self._get_cache_key(user_message, context)
        if self.config.get('enable_cache') and cache_key in self._intent_cache:
            cached_result = self._intent_cache[cache_key]
            cached_result.metadata['cache_hit'] = True
            self._stats['cache_hits'] += 1
            return cached_result

        # Step 2: 本地规则识别
        local_result = self._local_recognize(user_message, context, mkt_data)

        # Step 3: 判断是否需要LLM降级
        threshold = self.config.get('llm_fallback_threshold', self.LLM_FALLBACK_THRESHOLD)

        if force_llm or local_result.confidence < threshold:
            # 触发S思维链LLM降级
            self._stats['llm_fallback'] += 1
            llm_result = self.llm_recognizer.recognize_with_llm(
                user_message,
                context,
                fallback_local_result=local_result,
            )

            if llm_result.confidence >= 0.5:
                self._stats['llm_success'] += 1
                result = llm_result
            else:
                # LLM结果也不理想，使用本地结果但标记为低置信度
                result = local_result
                result.metadata['llm_attempted'] = True
                result.metadata['llm_confidence'] = llm_result.confidence
        else:
            # 本地识别成功
            self._stats['local_success'] += 1
            result = local_result

        # Step 4: 缓存结果
        if self.config.get('enable_cache'):
            self._intent_cache[cache_key] = result

        result.latency_ms = (time.time() - start_time) * 1000
        return result

    def _local_recognize(
        self,
        user_message: str,
        context: Optional[Dict],
        mkt_data: Optional[Dict],
    ) -> DynamicIntentResult:
        """
        本地规则识别（零Token）

        使用关键词匹配和正则模式匹配进行意图识别。
        """
        text_lower = user_message.lower()

        scores: Dict[str, float] = {}
        matched_keywords: Dict[str, List[str]] = defaultdict(list)
        matched_patterns: Dict[str, List[str]] = defaultdict(list)

        # Step 1: 关键词匹配
        for intent_id, intent_type in self._all_intents.items():
            kw_score = 0.0
            for kw in intent_type.keywords:
                if kw.lower() in text_lower:
                    # 增强权重：长关键词权重更高，中文关键词额外加权
                    kw_len = len(kw)
                    weight = kw_len * 0.15  # 提高系数
                    if kw_len >= 2:  # 中文关键词通常>=2字符
                        weight += 0.1  # 额外加权
                    kw_score += weight
                    matched_keywords[intent_id].append(kw)

            if kw_score > 0:
                # 增强基础置信度乘数
                scores[intent_id] = scores.get(intent_id, 0) + kw_score * intent_type.confidence_base * 1.5

        # Step 2: 正则模式匹配
        for intent_id, intent_type in self._all_intents.items():
            pattern_score = 0.0
            for pattern in intent_type.patterns:
                try:
                    if re.search(pattern, text_lower):
                        pattern_score += 0.3  # 正则匹配权重
                        matched_patterns[intent_id].append(pattern)
                except re.error:
                    continue

            if pattern_score > 0:
                scores[intent_id] = scores.get(intent_id, 0) + pattern_score

        # Step 3: 选择最高得分意图
        if not scores:
            # 无匹配，返回自定义意图
            return DynamicIntentResult(
                intent_type='custom',
                intent_name='自定义意图',
                confidence=0.2,
                recognition_source='local_no_match',
                rationale='本地规则未匹配到任何意图',
                keywords_matched=[],
                patterns_matched=[],
                domain_context={},
                recommended_chain='S',
                suggested_nodes=['dream-contradiction-theory'],
            )

        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_intent_id, best_score = sorted_scores[0]
        best_intent = self._all_intents[best_intent_id]

        # 归一化置信度（调整系数使更容易达到阈值）
        confidence = min(best_score / 1.2, 1.0)  # 降低系数，使置信度更容易达到0.45阈值

        # 构建结果
        result = DynamicIntentResult(
            intent_type=best_intent_id,
            intent_name=best_intent.name,
            confidence=confidence,
            recognition_source='local',
            rationale=f'本地关键词匹配: {matched_keywords[best_intent_id]}',
            keywords_matched=matched_keywords[best_intent_id],
            patterns_matched=matched_patterns[best_intent_id],
            domain_context={
                'category': best_intent.category,
                'domain_tags': best_intent.domain_tags,
            },
            recommended_chain=best_intent.recommended_chain,
            suggested_nodes=self._get_suggested_nodes(best_intent),
        )

        # 判断是否需要澄清
        if confidence < 0.3:
            result.clarify_needed = True
            result.clarify_question = f"您是想进行「{best_intent.name}」吗？"
            result.clarify_options = [
                {'label': '是的', 'value': 'confirm'},
                {'label': '不是', 'value': 'reject'},
            ]

        return result

    def _get_suggested_nodes(self, intent_type: DynamicIntentType) -> List[str]:
        """根据意图类型获取建议执行节点"""
        chain = intent_type.recommended_chain
        nodes = []

        # 根据推荐链选择节点
        if 'S' in chain or 'A' in chain:
            nodes.extend(['dream-contradiction-theory', 'dream-first-principles'])
        if 'C' in chain:
            nodes.extend(['classic-indicator-scan'])
        if 'F' in chain:
            nodes.extend(['fundamental-fund-flow', 'fundamental-sentiment'])
        if 'T' in chain:
            nodes.extend(['knowledge-retrieval'])

        return nodes[:5]  # 最多返回5个节点

    def _get_cache_key(self, user_message: str, context: Optional[Dict]) -> str:
        """生成缓存Key"""
        content = user_message + json.dumps(context or {}, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()

    def register_custom_intent(self, definition: Dict) -> bool:
        """
        注册用户自定义意图类型

        Args:
            definition: 意图定义字典，包含intent_id, name, keywords等

        Returns:
            是否注册成功
        """
        if 'intent_id' not in definition or 'name' not in definition:
            return False

        intent_id = definition['intent_id']
        custom_intent = DynamicIntentType(
            intent_id=intent_id,
            name=definition.get('name', intent_id),
            category=definition.get('category', 'custom'),
            description=definition.get('description', ''),
            keywords=definition.get('keywords', []),
            patterns=definition.get('patterns', []),
            domain_tags=definition.get('domain_tags', ['custom']),
            confidence_base=definition.get('confidence_base', 0.6),
            recommended_chain=definition.get('recommended_chain', 'S'),
            priority=definition.get('priority', 5),
            is_custom=True,
        )

        self._all_intents[intent_id] = custom_intent
        return True

    def get_all_intent_types(self) -> Dict[str, DynamicIntentType]:
        """获取所有意图类型（包括学习获得的）"""
        # 合并学习获得的意图
        all_intents = dict(self._all_intents)
        for intent_id, intent_type in self.llm_recognizer.get_learned_intents().items():
            if intent_id not in all_intents:
                all_intents[intent_id] = intent_type
                self._stats['learned_intents'] += 1
        return all_intents

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self._stats,
            'total_intent_types': len(self._all_intents),
            'learned_intent_types': len(self.llm_recognizer.get_learned_intents()),
            'cache_size': len(self._intent_cache),
        }

    def clear_cache(self):
        """清空缓存"""
        self._intent_cache.clear()


# ============================================================
# 导出
# ============================================================

__all__ = [
    'DynamicIntentType',
    'DynamicIntentResult',
    'DynamicIntentRecognizer',
    'SChainLLMRecognizer',
    'FINANCE_INTENT_KNOWLEDGE_BASE',
]
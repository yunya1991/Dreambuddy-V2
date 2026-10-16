"""动态解读意图采集器 — S 层 data_insight 意图训练数据源 (SPEC v0.7 第二层)。

查询是静态，动态变化的训练更具备价值：用户问『数据变化意味着什么』时，
S 层应识别为 data_insight 意图，结合 9-基本面分析系统的计算逻辑
（事件映射/情绪/信号/最小阻力引擎）给出金融市场含义解读。

设计（SPEC-v0.7-data-query-intent.md §3.2）:
  - 知识来源: 9-基本面分析 engines 的『数据变化模式 → 市场含义』映射
  - 样本生成: 变化模式 + 问法模板 → (message, intent_type='data_insight')
  - FAIL-OPEN: 引擎目录缺失时使用内置知识库，不阻塞训练
"""
import os
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 9-基本面分析 引擎目录（存在性检查用，知识对内置保证 FAIL-OPEN）
_FUNDAMENTAL_ENGINES = os.path.join(_PROJECT_ROOT, "9-基本面分析", "engines")

# 『数据变化模式 → 金融市场含义』知识对（对齐 9-基本面分析 计算逻辑）
# (指标, 变化模式, 市场含义解读)
_INSIGHT_KNOWLEDGE = [
    ("CPI", "超预期上行", "通胀超预期 → 加息预期升温 → 利好美元、压制风险资产，加密市场承压"),
    ("CPI", "低于预期", "通胀降温 → 降息预期升温 → 风险资产受益，加密市场偏多"),
    ("恐惧贪婪指数", "转向极度贪婪", "市场情绪过热 → 追高风险加大，警惕回调（逆向信号）"),
    ("恐惧贪婪指数", "转向极度恐惧", "市场恐慌 → 历史上常为阶段性底部区域（逆向机会信号）"),
    ("稳定币总市值", "持续增长", "场内资金流入 → 链上购买力增强，中期偏多信号"),
    ("稳定币总市值", "持续下降", "资金撤离 → 链上流动性收缩，中期偏空信号"),
    ("多空比", "多头过度拥挤", "多头拥挤 → 轧空动能不足，警惕多头踩踏下行"),
    ("多空比", "空头过度拥挤", "空头拥挤 → 轧空反弹风险上升"),
    ("DeFi TVL", "显著上升", "链上活跃度提升 → 链上经济扩张，生态代币偏多"),
    ("DeFi TVL", "显著下降", "资金撤离链上协议 → 生态收缩，偏空信号"),
    ("非农就业", "超预期强劲", "就业强劲 → 经济过热担忧 → 加息预期升温，风险资产承压"),
    ("非农就业", "大幅不及预期", "就业走弱 → 衰退担忧与降息预期并存，市场波动加大"),
    ("资金费率", "持续高正费率", "多头付费拥挤 → 杠杆过热，警惕多头清算连锁"),
    ("资金费率", "持续负费率", "空头付费拥挤 → 空头杠杆过热，轧空反弹概率上升"),
    ("比特币链上活跃度", "活跃地址激增", "链上参与度提升 → 真实需求扩张信号"),
    ("美联储利率决议", "释放鸽派信号", "鸽派 → 流动性宽松预期 → 风险资产受益"),
    ("美联储利率决议", "释放鹰派信号", "鹰派 → 流动性收紧预期 → 风险资产承压"),
    ("期权未平仓量", "看跌期权激增", "对冲需求上升 → 机构防御姿态，警惕下行"),
]

# 问法模板
_INSIGHT_TEMPLATES = [
    "{metric}{pattern}意味着什么",
    "{metric}{pattern}对市场有什么影响",
    "{metric}{pattern}说明什么",
    "怎么解读{metric}{pattern}",
    "{metric}如果{pattern}，市场会怎么走",
    "帮我分析一下{metric}{pattern}的含义",
]


class DataInsightCollector(TrainingDataProvider):
    """基于基本面变化逻辑生成 data_insight 意图训练样本。"""

    def get_source_name(self) -> str:
        return "data_insight"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        cases: List[TrainingCase] = []
        n = len(_INSIGHT_KNOWLEDGE)
        for i, (metric, pattern, meaning) in enumerate(_INSIGHT_KNOWLEDGE):
            tpl = _INSIGHT_TEMPLATES[i % len(_INSIGHT_TEMPLATES)]
            message = tpl.format(metric=metric, pattern=pattern)
            cases.append(TrainingCase(
                intent="data_insight",
                actions=[f"insight:{metric}", f"pattern:{pattern}"],
                outcome_text=message,
                learned=[f"动态解读: {metric}{pattern} → {meaning}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="data_insight",
                metadata={
                    "metric": metric,
                    "change_pattern": pattern,
                    "market_meaning": meaning,
                    "engine_hint": "9-基本面分析",
                },
            ))
            if len(cases) >= limit:
                return cases
        # 知识对不足 limit 时，用第二套问法补充（增强问法多样性）
        if len(cases) < limit:
            for i, (metric, pattern, meaning) in enumerate(_INSIGHT_KNOWLEDGE):
                tpl = _INSIGHT_TEMPLATES[(i + 2) % len(_INSIGHT_TEMPLATES)]
                message = tpl.format(metric=metric, pattern=pattern)
                cases.append(TrainingCase(
                    intent="data_insight",
                    actions=[f"insight:{metric}", f"pattern:{pattern}"],
                    outcome_text=message,
                    learned=[f"动态解读: {metric}{pattern} → {meaning}"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.5,
                    source="data_insight",
                    metadata={
                        "metric": metric,
                        "change_pattern": pattern,
                        "market_meaning": meaning,
                        "engine_hint": "9-基本面分析",
                    },
                ))
                if len(cases) >= limit:
                    break
        return cases

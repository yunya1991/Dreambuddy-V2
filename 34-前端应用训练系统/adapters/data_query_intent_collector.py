"""数据查询意图采集器 — S 层 data_query 意图训练数据源 (SPEC v0.7 第一层)。

前端最基础的能力是查询能力：用户问『某个数据是什么』时，
S 层应识别为 data_query 意图并路由到 18-数据获取中心直接取数回复。

设计（SPEC-v0.7-data-query-intent.md §3.1）:
  - 数据来源: 18 中心 data_center.db 的 records 表（source/category/sub_category）
  - 样本生成: 实际数据源目录 + 问法模板 → (message, intent_type='data_query')
  - FAIL-OPEN: 数据库不可用/表缺失时返回空列表，不阻塞训练
"""
import os
import sqlite3
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 18-数据获取中心 数据库
_DB_PATH = os.path.join(_PROJECT_ROOT, "18-数据获取中心", "data_center.db")

# 数据源 → 中文描述映射（问法模板中使用）
_SOURCE_DESC = {
    "defillama": "DeFi TVL",
    "ccxt": "交易所行情",
    "yfinance": "金融行情",
    "fear_greed": "恐惧贪婪指数",
    "fear_greed_enhanced": "恐惧贪婪指数(增强)",
    "fred": "美联储经济数据(FRED)",
    "coinglass": "Coinglass 衍生品数据",
    "deribit": "Deribit 期权数据",
    "blockchain_info": "链上数据",
    "stablecoin_transparency": "稳定币透明度",
    "long_short_ratio": "多空比",
    "gdelt": "GDELT 全球新闻事件",
    "theblockbeats_dataview": "律动BlockBeats数据",
    "odaily_newsflash": "Odaily快讯",
    "panewslab": "PANews实验室",
}

# 问法模板（{desc} 为数据源中文描述，{src} 为原始 source 名）
_QUERY_TEMPLATES = [
    "最新的{desc}是多少",
    "现在{desc}什么水平",
    "帮我查一下{desc}",
    "{desc}最新数据",
    "查一下{src}的数据",
    "当前{desc}是多少",
    "{desc}现在怎么样",
    "给我看看最新的{desc}",
]


class DataQueryIntentCollector(TrainingDataProvider):
    """从 18 中心数据源目录生成 data_query 意图训练样本。"""

    def get_source_name(self) -> str:
        return "data_query_intent"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.exists(_DB_PATH):
            return []
        try:
            conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT source, category, sub_category, COUNT(*) FROM records "
                "GROUP BY source, category, sub_category ORDER BY 4 DESC LIMIT 60"
            ).fetchall()
            conn.close()
        except Exception:
            return []

        cases: List[TrainingCase] = []
        for i, (src, category, sub_cat, cnt) in enumerate(rows):
            desc = _SOURCE_DESC.get(src, src)
            # 每个数据源目录生成 2 条问法样本，轮换模板保证多样性
            for t in range(2):
                tpl = _QUERY_TEMPLATES[(i * 2 + t) % len(_QUERY_TEMPLATES)]
                message = tpl.format(desc=desc, src=src)
                cases.append(TrainingCase(
                    intent="data_query",
                    actions=[f"query:{src}", f"category:{category or 'default'}"],
                    outcome_text=message,
                    learned=[f"数据查询意图: {desc} → 18中心 {src} 数据源"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.6,
                    source="data_query_intent",
                    metadata={
                        "data_source": src,
                        "category": category,
                        "sub_category": sub_cat,
                        "record_count": cnt,
                        "route_hint": "18-数据获取中心",
                    },
                ))
                if len(cases) >= limit:
                    return cases
        return cases

# -*- coding: utf-8 -*-
"""资产类别分析采集器 — S 层 asset_class_trend 意图训练数据源 (SPEC v0.9)。

战略层维度：跨资产趋势分析（crypto_usdt / us_stock / precious_metal）。
从 11-易经推理系统 polling_trader 最新日志的 [战略层影子] 行提取三资产类别状态，
生成 (message, intent_type='asset_class_trend') 训练案例。

FAIL-OPEN: 日志缺失/解析失败返回空列表。
"""
import glob
import json
import os
import re
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_TRADER_DIR = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", "data", "polling_trader"
)

_ASSET_DESC = {
    "crypto_usdt": "加密货币",
    "us_stock": "美股",
    "precious_metal": "贵金属",
}

_TEMPLATES = [
    "美股和加密货币趋势对比",
    "跨资产现在什么状态",
    "贵金属和加密一致吗",
    "战略层怎么看各类资产",
    "现在哪类资产趋势最好",
    "三类资产的趋势分化情况",
    "加密货币和美股走势关系",
    "帮我对比一下各类资产",
]


class AssetClassCollector(TrainingDataProvider):
    """从战略层影子日志生成 asset_class_trend 意图训练样本。"""

    def get_source_name(self) -> str:
        return "asset_class_trend"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.isdir(_TRADER_DIR):
            return []
        files = sorted(glob.glob(os.path.join(_TRADER_DIR, "trader_*.jsonl")))
        if not files:
            return []
        try:
            with open(files[-1], encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-2000:]
        except Exception:
            return []

        # 提取战略层影子行中的三资产状态
        veto_pat = re.compile(r"dimension_veto \| (.+?)$")
        asset_state = {}
        for line in lines:
            if "[战略层影子]" not in line or "dimension_veto" not in line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msg = rec.get("msg", "")
            m = veto_pat.search(msg)
            if not m:
                continue
            # 解析 crypto_usdt=[none] | us_stock=[none] | precious_metal=[none]
            for part in m.group(1).split("|"):
                kv = part.strip().split("=", 1)
                if len(kv) == 2 and kv[0] in _ASSET_DESC:
                    asset_state[kv[0]] = kv[1].strip()
        if not asset_state:
            return []

        cases: List[TrainingCase] = []
        # 生成跨资产对比问法样本
        assets = sorted(asset_state.keys())
        for idx in range(max(len(_TEMPLATES), 8)):
            if len(cases) >= limit:
                break
            tpl = _TEMPLATES[idx % len(_TEMPLATES)]
            message = tpl
            summary = "/".join(
                f"{_ASSET_DESC.get(a, a)}:{asset_state[a]}" for a in assets
            )
            cases.append(TrainingCase(
                intent="asset_class_trend",
                actions=[f"asset_class:{a}" for a in assets],
                outcome_text=message,
                learned=[f"跨资产分析: {summary}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="asset_class_trend",
                metadata={
                    "assets": {a: asset_state[a] for a in assets},
                    "engine_hint": "11-易经推理系统/战略层",
                },
            ))
        # 两两资产对比问法补充
        pairs = [("加密货币", "美股"), ("加密货币", "贵金属"), ("美股", "贵金属")]
        for a1, a2 in pairs:
            if len(cases) >= limit:
                break
            message = f"{a1}和{a2}现在的趋势对比怎么样"
            cases.append(TrainingCase(
                intent="asset_class_trend",
                actions=["asset_class:compare"],
                outcome_text=message,
                learned=[f"跨资产分析: {a1}与{a2}趋势对比"],
                layer_tags=["S"],
                quality="B",
                confidence=0.5,
                source="asset_class_trend",
                metadata={"engine_hint": "11-易经推理系统/战略层"},
            ))
        return cases

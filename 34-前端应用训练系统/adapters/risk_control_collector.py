# -*- coding: utf-8 -*-
"""调控风控采集器 — S 层 risk_control 意图训练数据源 (SPEC v1.0 L1 优先扩展)。

16-调控系统：风控计算、调控状态、仓位与风险度查询。
数据来源（已验证）:
  ① logs/trailing_runner_YYYYMMDD.log — 移动止盈评估周期
     （总持仓/IDLE/ARMED/TRIGGERED/CLOSED 状态、历史触发累计）
  ② core/capital_control — 资金控制规则（存在性参考）

生成 (message, intent_type='risk_control') 训练案例。
FAIL-OPEN: 日志缺失/解析失败返回空列表。
"""
import glob
import os
import re
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_LOG_DIR = os.path.join(_PROJECT_ROOT, "16-调控系统", "logs")

_STATE_DESC = {
    "IDLE": "待命",
    "ARMED": "已武装（接近触发）",
    "TRIGGERED": "已触发",
    "CLOSED": "已平仓",
}

_TEMPLATES = [
    "现在风控状态怎么样",
    "当前持仓风控状态",
    "移动止盈有没有触发",
    "仓位风控现在什么情况",
    "调控系统现在什么状态",
    "有没有仓位触发止盈",
    "当前风险度怎么样",
    "帮我查一下风控和持仓状态",
    "止盈武装的仓位有几个",
    "调控系统的历史触发情况",
]


class RiskControlCollector(TrainingDataProvider):
    """从 16-调控系统日志生成 risk_control 意图训练样本。"""

    def get_source_name(self) -> str:
        return "risk_control"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        if not os.path.isdir(_LOG_DIR):
            return []
        files = sorted(glob.glob(os.path.join(_LOG_DIR, "trailing_runner_*.log")))
        if not files:
            return []
        try:
            with open(files[-1], encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-500:]
        except Exception:
            return []

        # 提取最新一轮评估: 总持仓=N IDLE=n ARMED=n TRIGGERED=n CLOSED=n 历史触发累计=n
        pat = re.compile(
            r"评估完成: 总持仓=(\d+) IDLE=(\d+) ARMED=(\d+) TRIGGERED=(\d+) CLOSED=(\d+) 历史触发累计=(\d+)"
        )
        latest = None
        for line in lines:
            m = pat.search(line)
            if m:
                latest = {
                    "total": int(m.group(1)),
                    "IDLE": int(m.group(2)),
                    "ARMED": int(m.group(3)),
                    "TRIGGERED": int(m.group(4)),
                    "CLOSED": int(m.group(5)),
                    "history_triggered": int(m.group(6)),
                }
        if not latest:
            return []

        state_summary = "/".join(
            f"{_STATE_DESC.get(k, k)}{v}" for k, v in latest.items() if k != "total" and k != "history_triggered"
        )
        cases: List[TrainingCase] = []
        for idx, tpl in enumerate(_TEMPLATES):
            if len(cases) >= limit:
                break
            message = tpl
            cases.append(TrainingCase(
                intent="risk_control",
                actions=["risk_control:trailing", f"total:{latest['total']}"],
                outcome_text=message,
                learned=[
                    f"风控状态: 总持仓{latest['total']} {state_summary} 历史触发{latest['history_triggered']}"
                ],
                layer_tags=["S"],
                quality="B",
                confidence=0.6,
                source="risk_control",
                metadata={
                    "positions": latest,
                    "engine_hint": "16-调控系统/移动止盈",
                },
            ))
        # 补充变体问法
        variants = [
            f"现在有{latest['ARMED']}个仓位武装了吗",
            f"止盈历史触发了{latest['history_triggered']}次吗",
            "风控计算一下当前仓位",
        ]
        for message in variants:
            if len(cases) >= limit:
                break
            cases.append(TrainingCase(
                intent="risk_control",
                actions=["risk_control:variant"],
                outcome_text=message,
                learned=[f"风控状态查询: {state_summary}"],
                layer_tags=["S"],
                quality="B",
                confidence=0.5,
                source="risk_control",
                metadata={"positions": latest, "engine_hint": "16-调控系统"},
            ))
        return cases

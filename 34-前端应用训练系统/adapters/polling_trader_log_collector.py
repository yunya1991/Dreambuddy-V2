"""PollingTrader 日志采集器 — DSH 层 P2 补充数据源.

从 polling_trader 日志文件提取交易决策节点,构造 DSH 层训练数据。

设计 (SPEC-DSH-训练数据源 v0.4 §4):
  - 读取 trading_stdout.log 日志文件
  - 关键词匹配提取决策节点 (BCRM2.0/Score_B/BDSM/持仓同步/CBR/战略层等)
  - 按时间窗口分组为 node_sequence (8-12节点/组)
  - FAIL-OPEN: 文件不存在/空文件返回空列表

预期: 30-60 条
"""
import os
import re
import sys
from typing import List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# 默认日志路径
_DEFAULT_LOG_PATH = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", "logs", "trading_stdout.log"
)

# 决策节点关键词映射
KEYWORD_NODE_MAP = [
    # (正则模式, 节点名)
    (r"\[BCRM2\.0\]", "bcrm2_health_check"),
    (r"\[CBR\]", "cbr_case_retrieval"),
    (r"\[A7\]", "practice_gate_check"),
    (r"\[P3\]", "cognitive_recall_bridge"),
    (r"\[持仓同步\]", "position_sync"),
    (r"持仓同步.*不合理止损", "position_sl_repair"),
    (r"\[Score_B\]", "score_b_compute"),
    (r"event_boost", "event_boost_compute"),
    (r"\[BDSM\]", "bdsm_exit_scan"),
    (r"出场巡检", "bdsm_exit_inspect"),
    (r"\[战略层\]", "strategy_layer_check"),
    (r"影子", "strategy_shadow_check"),
    (r"war_state", "war_state_eval"),
    (r"total_score", "total_score_compute"),
    (r"累计进化", "evolution_step"),
    (r"LearningScheduler", "learning_scheduler_load"),
    (r"进化阈值", "evolution_threshold_load"),
    (r"微仓实盘", "micro_position_init"),
]

# 时间戳正则
_TIMESTAMP_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


class PollingTraderLogCollector(TrainingDataProvider):
    """PollingTrader 日志采集器 — DSH 层 P2 数据源。"""

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or _DEFAULT_LOG_PATH

    def get_source_name(self) -> str:
        return "polling_trader_log"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从日志文件采集训练案例。

        按时间窗口分组决策节点,每组 8-12 节点构成一条 TrainingCase。

        Returns:
            训练案例列表 (FAIL-OPEN)
        """
        cases: List[TrainingCase] = []

        if not os.path.exists(self.log_path):
            return cases

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return cases

        if not lines:
            return cases

        # 提取所有决策节点
        nodes = []
        for line in lines:
            node = self._extract_node(line)
            if node:
                nodes.append(node)

        if not nodes:
            return cases

        # 按窗口分组 (每组 8-12 节点)
        window_size = 10
        for i in range(0, len(nodes), window_size):
            if len(cases) >= limit:
                break
            window = nodes[i:i + window_size]
            if len(window) < 3:
                continue  # 太短的窗口跳过

            case = TrainingCase(
                intent=f"trader_log.window_{i // window_size}",
                actions=window,
                outcome_text="success",
                learned=[
                    f"window_start={i}",
                    f"node_count={len(window)}",
                ],
                layer_tags=["DSH"],
                quality="B",
                confidence=0.4,
                source="polling_trader_log",
                metadata={
                    "outcome": "success",  # 交易决策已执行
                    "window_index": i // window_size,
                    "node_count": len(window),
                    "log_file": os.path.basename(self.log_path),
                },
            )
            cases.append(case)

        return cases[:limit]

    def _extract_node(self, line: str) -> Optional[str]:
        """从日志行提取决策节点。

        Returns:
            节点描述字符串,或 None (如果不是决策行)
        """
        for pattern, node_name in KEYWORD_NODE_MAP:
            if re.search(pattern, line):
                # 尝试提取时间戳
                ts_match = _TIMESTAMP_RE.search(line)
                ts = ts_match.group(1) if ts_match else "unknown"
                # 截取关键信息
                # 去掉时间戳和级别,保留内容
                content = re.sub(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*\[\w+\]\s*", "", line).strip()
                content_short = content[:40].replace("\n", "")
                return f"{node_name}({content_short})"
        return None

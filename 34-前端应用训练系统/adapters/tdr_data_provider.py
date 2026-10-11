"""TDR 训练数据提供者适配器。

通过直接 Python import 调用 scripts/case_bank_server.py，
实现 TrainingDataProvider 协议，为主动训练采集器提供批量数据。

设计:
  - 直接 import case_bank_server（Python-to-Python，无 IPC 开销）
  - fetch_cases 使用 fetch_since 增量查询
  - layer_tags 扁平化：List[LayerTag] → List[str]（取 tag["layer"]）
  - FAIL-OPEN：TDR 不可用时返回空列表
"""
import os
import sys
from typing import List, Optional

# sys.path 注入：34 目录 + scripts 目录
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, os.path.dirname(_THIS_DIR), _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


class TDRTrainingDataProvider(TrainingDataProvider):
    """TDR (Training Data Repository) 数据提供者。

    从 scripts/case_bank_server.py 的 fetch_since handler 批量获取训练案例，
    供主动训练采集器使用。
    """

    def __init__(self, quality_threshold: str = "B"):
        self._quality_threshold = quality_threshold
        self._tdr = None

    def _get_tdr(self):
        """延迟 import case_bank_server，避免初始化时失败。"""
        if self._tdr is None:
            try:
                from case_bank_server import fetch_since, retrieve_cases
                self._tdr = {"fetch_since": fetch_since, "retrieve": retrieve_cases}
            except Exception:
                self._tdr = {}
        return self._tdr

    def get_source_name(self) -> str:
        return "tdr"

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        """从 TDR 增量获取训练案例。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ms 字符串)，None 或 "0" 表示全量

        Returns:
            训练案例列表（FAIL-OPEN：TDR 不可用时返回空列表）
        """
        tdr = self._get_tdr()
        if not tdr or "fetch_since" not in tdr:
            return []

        try:
            since_ts = int(since) if since else 0
            result = tdr["fetch_since"](since_ts=since_ts, limit=limit)
            if not result.get("ok"):
                return []
            return [self._convert_case(c) for c in result.get("cases", [])]
        except Exception:
            return []

    def get_quality_threshold(self) -> str:
        return self._quality_threshold

    @staticmethod
    def _convert_case(raw: dict) -> TrainingCase:
        """将 TDR SolutionCase dict 转为 TrainingCase。

        layer_tags 扁平化：List[{"layer": "DSH", ...}] → ["DSH", ...]
        """
        raw_tags = raw.get("layer_tags", [])
        if isinstance(raw_tags, list):
            layer_tags = [
                t.get("layer", "") if isinstance(t, dict) else str(t)
                for t in raw_tags
            ]
        else:
            layer_tags = []

        return TrainingCase(
            intent=raw.get("intent", ""),
            actions=raw.get("actions", []),
            outcome_text=raw.get("outcome_text", ""),
            learned=raw.get("learned", []),
            layer_tags=layer_tags,
            quality=raw.get("quality", "C"),
            confidence=raw.get("confidence", 0.3),
            source=raw.get("source", "tdr"),
            metadata={
                "id": raw.get("id", ""),
                "outcome": raw.get("outcome", "unknown"),
                "created_at": raw.get("created_at", 0),
                "tags": raw.get("tags", []),
            },
        )

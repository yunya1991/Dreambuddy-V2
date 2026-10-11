"""主动训练采集器调度器。

注册多个 TrainingDataProvider，批量采集各数据源的训练案例，
经质量门控后写入 TDR 中央训练数据仓库。

设计 (SPEC §2.2 主动训练):
  - 注册多 Provider: TDR / Cognitive / Skill / Doc / REA
  - 增量采集: per-source last_collected 时间戳
  - 质量门控: 案例 quality >= provider threshold 才入库
  - 批量写入 TDR: 调用 case_bank_server.store_case
  - FAIL-OPEN: 单个 Provider 失败不影响其他
  - 采集报告: 统计 per-source 采集/入库/跳过数

调度频率: 每日凌晨低峰期执行（不干扰用户操作）
优先级: 低（后台任务）
"""
import os
import sys
import time
from typing import Dict, List, Optional, Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _34_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 质量等级优先级（数字越大越好）
_QUALITY_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}


class ActiveTrainingCollector:
    """主动训练采集器调度器。

    管理多个数据源 Provider，批量采集训练案例，
    质量门控后写入 TDR。
    """

    def __init__(self):
        self._providers: Dict[str, TrainingDataProvider] = {}
        self._last_collected: Dict[str, str] = {}  # per-source last collected timestamp
        self._store_fn = None  # 延迟加载 store_case

    def register_provider(self, provider: TrainingDataProvider) -> None:
        """注册一个数据源 Provider。"""
        name = provider.get_source_name()
        self._providers[name] = provider

    def set_last_collected(self, source: str, timestamp: str) -> None:
        """设置某数据源的上次采集时间戳（增量采集用）。"""
        self._last_collected[source] = timestamp

    def get_last_collected(self, source: str) -> Optional[str]:
        """获取某数据源的上次采集时间戳。"""
        return self._last_collected.get(source)

    def _get_store_fn(self):
        """延迟加载 case_bank_server.store_case。"""
        if self._store_fn is None:
            try:
                from case_bank_server import store_case
                self._store_fn = store_case
            except Exception:
                self._store_fn = None
        return self._store_fn

    @staticmethod
    def _passes_quality_gate(case: TrainingCase, threshold: str) -> bool:
        """检查案例质量是否通过门控。"""
        case_level = _QUALITY_ORDER.get(case.quality, 0)
        threshold_level = _QUALITY_ORDER.get(threshold, 2)
        return case_level >= threshold_level

    @staticmethod
    def _case_to_tdr_dict(case: TrainingCase) -> dict:
        """将 TrainingCase 转换为 TDR store_case 输入格式。"""
        layer_tags = [{"layer": tag, "training_data": {}} for tag in case.layer_tags]
        return {
            "intent": case.intent,
            "actions": case.actions,
            "outcome_text": case.outcome_text,
            "learned": case.learned,
            "quality": case.quality,
            "confidence": case.confidence,
            "layer_tags": layer_tags,
            "source": case.source,
            "metadata": case.metadata,
        }

    def run_collection(self, limit_per_source: int = 100) -> Dict[str, Any]:
        """执行一轮完整的数据源采集。

        Args:
            limit_per_source: 每个数据源最大采集数

        Returns:
            采集报告 dict
        """
        report: Dict[str, Any] = {
            "total_collected": 0,
            "total_ingested": 0,
            "total_skipped": 0,
            "per_source": {},
            "collected_at": str(int(time.time() * 1000)),
        }

        store_fn = self._get_store_fn()

        for source_name, provider in self._providers.items():
            source_report: Dict[str, Any] = {
                "collected": 0,
                "ingested": 0,
                "skipped": 0,
                "error": False,
            }

            try:
                # 增量采集: 获取上次采集时间戳
                since = self._last_collected.get(source_name)

                # 调用 Provider 批量获取
                cases = provider.fetch_cases(limit=limit_per_source, since=since)
                source_report["collected"] = len(cases)

                # 质量门控 + 写入 TDR
                threshold = provider.get_quality_threshold()
                for case in cases:
                    if not self._passes_quality_gate(case, threshold):
                        source_report["skipped"] += 1
                        report["total_skipped"] += 1
                        continue

                    # 写入 TDR
                    if store_fn:
                        try:
                            tdr_case = self._case_to_tdr_dict(case)
                            result = store_fn(tdr_case)
                            if result.get("ok"):
                                source_report["ingested"] += 1
                                report["total_ingested"] += 1
                            else:
                                source_report["skipped"] += 1
                                report["total_skipped"] += 1
                        except Exception:
                            source_report["skipped"] += 1
                            report["total_skipped"] += 1
                    else:
                        # TDR 不可用，只统计不入库
                        source_report["ingested"] += 1
                        report["total_ingested"] += 1

                report["total_collected"] += source_report["collected"]

            except Exception:
                source_report["error"] = True

            # 更新上次采集时间戳
            self._last_collected[source_name] = report["collected_at"]
            report["per_source"][source_name] = source_report

        return report

    def register_all_default_providers(self) -> None:
        """注册所有默认数据源 Provider（TDR + Cognitive + Skill + Doc + REA）。"""
        try:
            from tdr_data_provider import TDRTrainingDataProvider
            self.register_provider(TDRTrainingDataProvider())
        except Exception:
            pass

        try:
            from cognitive_memory_collector import CognitiveMemoryCollector
            self.register_provider(CognitiveMemoryCollector())
        except Exception:
            pass

        try:
            from skill_system_collector import SkillSystemCollector
            self.register_provider(SkillSystemCollector())
        except Exception:
            pass

        try:
            from doc_knowledge_collector import DocKnowledgeCollector
            self.register_provider(DocKnowledgeCollector())
        except Exception:
            pass

        try:
            from rea_batch_collector import REABatchCollector
            self.register_provider(REABatchCollector())
        except Exception:
            pass

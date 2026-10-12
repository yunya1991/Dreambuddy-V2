"""20-数据清洗中心 CleaningTrace 采集器 — DSH 层原生序列数据源 (P0)。

通过调用 DataCleaningPipeline.clean() 跑多组样本批次,从 SilverRecord.trace.actions
提取 5-7 节点执行路径,专供 DSH 层 ExecutionPathTrainingLoop 训练。

设计（SPEC-DSH §1.3 方案 B - 主动调用模式,不需要补日志）:
  - 构造多组样本 DataRecord 覆盖不同清洗路径(正常/异常值/缺失/macro/news/empty)
  - 每组样本调用 pipeline.clean() 获取 SilverRecord
  - SilverRecord.trace.actions → node_sequence
  - SilverRecord.gate_passed → outcome
  - FAIL-OPEN: 样本/pipeline 异常返回空列表
"""
import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_18_DIR = os.path.join(_PROJECT_ROOT, "18-数据获取中心")
_20_DIR = os.path.join(_PROJECT_ROOT, "20-数据清洗中心")

for _p in [_THIS_DIR, _34_DIR, _18_DIR, _20_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# ============================================================
# 节点格式化 — 包含关键状态标记,使不同路径产出不同序列
# ============================================================

def _format_node(a) -> str:
    """格式化 CleanAction 为节点描述。

    包含 step 名 + 非零状态标记(clip/imp/block/rows/note_key),
    使不同清洗路径产出可区分的 node_sequence。
    """
    step = a.step
    tags = []
    if a.clipped_count > 0:
        tags.append(f"clip={a.clipped_count}")
    if a.imputed_count > 0:
        tags.append(f"imp={a.imputed_count}")
    if a.blocked_count > 0:
        tags.append(f"block={a.blocked_count}")
    if a.input_rows != a.output_rows:
        tags.append(f"rows={a.input_rows}->{a.output_rows}")
    # note 关键标记（empty_df_skip / FAIL-OPEN / QualityGateFailed 等）
    if a.note:
        note = a.note
        # 提取关键短语
        for key in ("empty_df_skip", "FAIL-OPEN", "QualityGateFailed", "fail-open"):
            if key in note:
                tags.append(key)
                break
        else:
            # 其他 note 取前 30 字符
            tags.append(note[:30])
    if tags:
        return f"{step}[{','.join(tags)}]"
    return step


# ============================================================
# 样本 DataRecord 构造（覆盖不同清洗路径）
# ============================================================

def _mk_ohlcv_records(n: int = 10, with_outliers: bool = False,
                      with_missing: bool = False) -> list:
    """构造 OHLCV 时序列样本。"""
    from data_center.core.contract import DataRecord
    rows = []
    for i in range(n):
        base = 100.0 + i
        high = base + 5.0
        low = base - 5.0
        close = base + (1.0 if i % 2 == 0 else -1.0)
        volume = 1000.0 + i * 10
        if with_outliers and i == 5:
            high = base + 500.0  # 3σ + IQR 必触发
        row = {
            "timestamp": f"2026-10-12T{str(i).zfill(2)}:00:00Z",
            "open": base,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        if with_missing and i == 3:
            row["close"] = None  # 触发 MissingImputer
        rows.append(row)
    return [DataRecord(
        source="sample_collector",
        category="finance",
        sub_category="ohlcv",
        timestamp="2026-10-12T00:00:00Z",
        metrics={"asset": "BTCUSDT"},
        events=[],
        timeseries=rows,
        raw={},
    )]


def _mk_macro_records() -> list:
    """构造宏观 CPI 样本（metrics 扁平模式）。"""
    from data_center.core.contract import DataRecord
    return [DataRecord(
        source="fred",
        category="macro",
        sub_category="cpi",
        timestamp="2026-10-12T00:00:00Z",
        metrics={"cpi": 2.5, "fetched_at": "2026-10-12T00:00:00Z"},
        events=[],
        timeseries=[],
        raw={},
    )]


def _mk_news_records() -> list:
    """构造新闻样本（events 模式,含重复行触发 DedupAlign）。"""
    from data_center.core.contract import DataRecord
    return [DataRecord(
        source="rsshub",
        category="news",
        sub_category="rss",
        timestamp="2026-10-12T00:00:00Z",
        metrics={"od_policy_sentiment_0_1": 0.8, "od_event_type": "rate"},
        events=[
            {"title": "Fed cuts rates", "timestamp": "2026-10-12T01:00:00Z"},
            {"title": "Fed cuts rates", "timestamp": "2026-10-12T01:00:00Z"},
        ],
        timeseries=[],
        raw={},
    )]


def _mk_empty_records() -> list:
    """构造空数据样本（触发 fail-open 路径）。"""
    from data_center.core.contract import DataRecord
    return [DataRecord(
        source="sample_collector",
        category="finance",
        sub_category="ohlcv",
        timestamp="2026-10-12T00:00:00Z",
        metrics={},
        events=[],
        timeseries=[],
        raw={},
    )]


# 样本批次: (label, records_fn, pipeline_cfg_kwargs, clean_kwargs)
_SAMPLE_BATCHES = [
    ("normal_ohlcv",     lambda: _mk_ohlcv_records(10),                {},
     {"category": "finance", "sub_category": "ohlcv"}),
    ("outlier_ohlcv",    lambda: _mk_ohlcv_records(10, with_outliers=True),
     {}, {"category": "finance", "sub_category": "ohlcv"}),
    ("missing_ohlcv",    lambda: _mk_ohlcv_records(10, with_missing=True),
     {}, {"category": "finance", "sub_category": "ohlcv"}),
    ("macro_cpi",        _mk_macro_records,
     {"category": "macro"}, {"category": "macro", "sub_category": "cpi"}),
    ("news_rss",         _mk_news_records,
     {"category": "news"}, {"category": "news", "sub_category": "rss"}),
    ("empty_failopen",   _mk_empty_records,
     {"fail_open": True}, {"category": "finance", "sub_category": "ohlcv"}),
]


# ============================================================
# 采集器主体
# ============================================================

class CleaningTraceCollector(TrainingDataProvider):
    """20-数据清洗中心 CleaningTrace 采集器。

    通过调用 DataCleaningPipeline.clean() 跑样本批次,从 SilverRecord.trace.actions
    提取 5-7 节点执行路径,作为 DSH 层训练数据。
    """

    def __init__(self):
        pass

    def get_source_name(self) -> str:
        return "cleaning_trace"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """跑样本批次采集 CleaningTrace 序列。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳（sandbox 模式忽略,since 仅用于去重决策）

        Returns:
            训练案例列表（FAIL-OPEN）
        """
        cases: List[TrainingCase] = []
        try:
            from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
        except Exception:
            return cases

        for label, records_fn, cfg_kw, clean_kw in _SAMPLE_BATCHES:
            try:
                records = records_fn() if callable(records_fn) else records_fn
                # 合并 fail_open=True（默认）与 cfg_kw,避免重复传参
                merged_cfg = {"fail_open": True}
                merged_cfg.update(cfg_kw)
                config = PipelineConfig(**merged_cfg)
                pipeline = DataCleaningPipeline(config=config)
                silver = pipeline.clean(records, source="sample_collector", **clean_kw)

                # 提取 node_sequence（使用 _format_node 包含状态标记）
                node_seq = [_format_node(a) for a in silver.trace.actions]
                if len(node_seq) < 2:
                    continue  # DSH 层需要 ≥2 节点

                outcome = "gate_passed" if silver.gate_passed else "gate_failed"
                category = clean_kw.get("category", "finance")

                cases.append(TrainingCase(
                    intent=f"data_cleaning.{category}",
                    actions=node_seq,
                    outcome_text=outcome,
                    learned=[f"trace_steps={len(node_seq)}",
                             f"outcome={outcome}",
                             f"clipped={silver.trace.total_clipped}",
                             f"imputed={silver.trace.total_imputed}"],
                    layer_tags=["DSH"],
                    quality="A",
                    confidence=0.8 if silver.gate_passed else 0.6,
                    source="cleaning_trace",
                    metadata={
                        "batch_label": label,
                        "category": category,
                        "bronze_id": silver.bronze_id,
                        "schema_tag": silver.schema_tag,
                        "node_count": len(node_seq),
                        "total_clipped": silver.trace.total_clipped,
                        "total_imputed": silver.trace.total_imputed,
                    },
                ))
            except Exception:
                continue  # FAIL-OPEN: 单批次失败不影响其他

        return cases[:limit]

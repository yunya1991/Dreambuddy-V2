"""18-数据获取中心 dispatcher 路由链路采集器 — DSH 层原生序列数据源 (P1)。

通过调用 DataCenter._fetch_monitored() 跑多组样本批次,从 stderr 提取
dsh_trace JSON 行,获取 4-7 节点路由链路序列,专供 DSH 层训练。

设计（SPEC-DSH §1.4 方案 - 重定向 stderr + 样本批次）:
  - EN_DSH_TRACE=true 触发 dispatcher._emit_dsh_trace 输出 JSON 行到 stderr
  - 构造多组样本覆盖不同路由路径(正常 silver+dal / 空 result / runner error)
  - 采集器重定向 stderr + 调用 _fetch_monitored + 提取 dsh_trace 日志
  - FAIL-OPEN: 样本/dispatcher 异常返回空列表

依赖 dispatcher.py 的 _emit_dsh_trace 方法（EN_DSH_TRACE=true 启用）。
"""
import io
import json
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

# 复用 cleaning_trace_collector 的样本 DataRecord 构造函数
from cleaning_trace_collector import (
    _mk_ohlcv_records, _mk_macro_records, _mk_news_records,
)


# ============================================================
# Mock runner 函数 — 模拟 collector.fetch() 返回不同类型数据
# ============================================================

def _runner_normal_ohlcv(params: dict) -> list:
    """正常 OHLCV 时序列（触发 silver + gate_pass + dal_write）。"""
    return _mk_ohlcv_records(10)


def _runner_macro(params: dict) -> list:
    """宏观 CPI metrics 模式（触发 silver + gate_pass + dal_write）。"""
    return _mk_macro_records()


def _runner_news(params: dict) -> list:
    """新闻 events 模式（触发 silver + gate_pass + dal_write）。"""
    return _mk_news_records()


def _runner_empty(params: dict) -> list:
    """空 result（不进入 silver 链路,4 节点短路径）。"""
    return []


def _runner_error(params: dict) -> list:
    """runner 抛异常（触发 collector.error,4 节点 failure 路径）。"""
    from data_center.core.errors import SourceUnavailableError
    raise SourceUnavailableError("mock runner error for DSH trace")


# 样本批次: (label, category, source, runner_fn)
_SAMPLE_BATCHES = [
    ("normal_ohlcv", "finance", "sample_ccxt",   _runner_normal_ohlcv),
    ("macro_cpi",    "macro",   "sample_fred",   _runner_macro),
    ("news_rss",     "news",    "sample_rsshub", _runner_news),
    ("empty_result", "finance", "sample_ccxt",   _runner_empty),
    ("runner_error", "finance", "sample_ccxt",   _runner_error),
]


# ============================================================
# 采集器主体
# ============================================================

class DataFetchRouteCollector(TrainingDataProvider):
    """18-数据获取中心 dispatcher 路由链路采集器。

    通过调用 DataCenter._fetch_monitored() 跑样本批次,从 stderr 提取
    dsh_trace JSON 行,获取 4-7 节点路由链路序列。
    """

    def __init__(self):
        pass

    def get_source_name(self) -> str:
        return "data_fetch_route"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """跑样本批次采集 dispatcher 路由链路序列。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳（sandbox 模式忽略）

        Returns:
            训练案例列表（FAIL-OPEN）
        """
        cases: List[TrainingCase] = []
        try:
            from data_center.core.dispatcher import DataCenter
        except Exception:
            return cases

        # 构造轻量 DataCenter 实例（跳过 __init__ 避免 collector 注册 + monitoring bundle）
        dc = DataCenter.__new__(DataCenter)
        dc.monitoring = None  # 跳过 metric 记录
        dc.config = {}
        dc.registry = None

        # 保存原环境变量,设置 EN_DSH_TRACE=true
        _old_environ = dict(os.environ)
        os.environ["EN_DSH_TRACE"] = "true"

        try:
            for label, category, source, runner_fn in _SAMPLE_BATCHES:
                try:
                    # 重定向 stderr 到 StringIO 捕获 dsh_trace 日志
                    old_stderr = sys.stderr
                    sys.stderr = io.StringIO()
                    try:
                        dc._fetch_monitored(category, source, {}, runner_fn)
                    except Exception:
                        pass  # runner_error 样本会抛 SourceUnavailableError,正常
                    finally:
                        captured = sys.stderr.getvalue()
                        sys.stderr = old_stderr

                    # 提取 dsh_trace JSON 行
                    trace = self._extract_dsh_trace(captured)
                    if not trace:
                        continue

                    node_seq = trace.get("node_sequence", [])
                    if len(node_seq) < 2:
                        continue  # DSH 层需要 ≥2 节点

                    outcome = trace.get("outcome", "success")
                    cases.append(TrainingCase(
                        intent=f"data_fetch.{category}.{source}",
                        actions=node_seq,
                        outcome_text=outcome,
                        learned=[
                            f"node_count={len(node_seq)}",
                            f"outcome={outcome}",
                            f"duration_ms={trace.get('duration_ms', 0)}",
                        ],
                        layer_tags=["DSH"],
                        quality="A",
                        confidence=0.8 if outcome == "success" else 0.4,
                        source="data_fetch_route",
                        metadata={
                            "batch_label": label,
                            "category": category,
                            "source": source,
                            "duration_ms": trace.get("duration_ms", 0),
                            "result_count": trace.get("result_count", 0),
                            "node_count": len(node_seq),
                        },
                    ))
                except Exception:
                    continue  # FAIL-OPEN: 单批次失败不影响其他
        finally:
            # 恢复环境变量
            os.environ.clear()
            os.environ.update(_old_environ)

        return cases[:limit]

    @staticmethod
    def _extract_dsh_trace(captured_stderr: str) -> dict:
        """从 stderr 输出中提取 dsh_trace JSON 行。

        dispatcher._emit_dsh_trace 输出格式:
          {"event":"dsh_trace","category":"...","source":"...",
           "node_sequence":[...],"outcome":"...","duration_ms":...,"result_count":...}
        """
        for line in captured_stderr.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
                if obj.get("event") == "dsh_trace":
                    return obj
            except json.JSONDecodeError:
                continue
        return {}

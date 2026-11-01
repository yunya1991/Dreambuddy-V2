"""L0-S 调度层的最小公共模块集合（SPEC-C C9）。

- registry：声明式任务清单（唯一事实源 = 0-系统文档管理/job_registry.yaml）
- windows：UTC 逻辑窗口 / 迟到容忍 / 跨窗切片
- job_runs：经 L0-P 的 Store/Event port 记账（禁止直连 PG/SQLite）
- cli：本地与云端链路的记账入口（只读旁路，不改实盘 ExecStart）
"""

from .job_runs import JobRunRecorder
from .registry import TaskRegistry, TaskSpec, load_registry
from .windows import is_window_closed, split_segments, window_index, window_start

__all__ = [
    "JobRunRecorder",
    "TaskRegistry",
    "TaskSpec",
    "load_registry",
    "is_window_closed",
    "split_segments",
    "window_index",
    "window_start",
]

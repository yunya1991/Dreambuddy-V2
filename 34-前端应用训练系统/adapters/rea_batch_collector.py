"""33-REA 批量逆向采集器。

扫描项目 Python 代码文件，调用 algorithm_reducer 提取算法模式，
实现 TrainingDataProvider 协议，为主动训练采集器提供批量逆向工程数据。

设计:
  - 扫描指定目录下 .py 文件
  - 调用 core.algorithm_reducer.reduce_algorithm 提取算法模式
  - 质量门控: 有 patterns 的文件才采集
  - 增量采集: 基于 mtime（since > mtime 的文件跳过）
  - FAIL-OPEN: 目录不存在/reducer 不可用时返回空列表

字段映射 (SPEC §2.2: algorithm_pattern → DSH层, dependency_graph → G层):
  - 文件名 → intent
  - 算法模式列表 → actions + learned
  - 文件路径 → outcome_text
  - imports → metadata["imports"]
  - layer_tags = ["DSH", "G"]
  - quality = "B"
  - source = "rea"
"""
import os
import sys
from typing import List, Optional, Callable, Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_REA_DIR = os.path.join(_PROJECT_ROOT, "33-REA逆向解析工程")

for _p in [_THIS_DIR, _34_DIR, _REA_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


class REABatchCollector(TrainingDataProvider):
    """33-REA 批量逆向采集器。

    扫描项目 Python 文件，调用 algorithm_reducer 提取算法模式，
    作为 DSH 层（算法模式）和 G 层（依赖图）训练数据。
    """

    def __init__(
        self,
        scan_dir: str = "",
        quality_threshold: str = "B",
    ):
        self._scan_dir = scan_dir or os.path.join(_PROJECT_ROOT, "34-前端应用训练系统")
        self._quality_threshold = quality_threshold
        self._reduce_fn: Optional[Callable] = None

    def _get_reduce_algorithm(self) -> Optional[Callable]:
        """延迟 import reduce_algorithm，避免初始化时失败。"""
        if self._reduce_fn is None:
            try:
                from core.algorithm_reducer import reduce_algorithm
                self._reduce_fn = reduce_algorithm
            except Exception:
                self._reduce_fn = None
        return self._reduce_fn

    def get_source_name(self) -> str:
        return "rea"

    def get_quality_threshold(self) -> str:
        return self._quality_threshold

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """扫描目录下 .py 文件，批量提取算法模式。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(ms)，mtime <= since 的文件跳过

        Returns:
            训练案例列表（FAIL-OPEN：目录/reducer 不可用时返回空列表）
        """
        if not os.path.isdir(self._scan_dir):
            return []

        reduce_fn = self._get_reduce_algorithm()
        if reduce_fn is None:
            return []

        since_ts = int(since) if since else 0

        try:
            cases = []
            for root, _dirs, files in os.walk(self._scan_dir):
                # 跳过隐藏目录和 __pycache__
                _dirs[:] = [d for d in _dirs if not d.startswith(".") and d != "__pycache__"]

                for fname in files:
                    if not fname.endswith(".py"):
                        continue

                    fpath = os.path.join(root, fname)
                    mtime = os.path.getmtime(fpath)
                    mtime_ms = int(mtime * 1000)

                    # 增量: 跳过旧文件
                    if since_ts and mtime_ms <= since_ts:
                        continue

                    case = self._analyze_file(fpath, fname, reduce_fn)
                    if case:
                        cases.append(case)
                        if len(cases) >= limit:
                            return cases

            return cases
        except Exception:
            return []

    @staticmethod
    def _analyze_file(
        fpath: str, fname: str, reduce_fn: Callable
    ) -> Optional[TrainingCase]:
        """分析单个 Python 文件，提取算法模式。"""
        try:
            reduced = reduce_fn(fpath)
            patterns = reduced.get("patterns", []) or []

            # 提取模式名（从 type 字段最后 token）
            pattern_names = []
            for p in patterns:
                p_type = p.get("type") or p.get("name") or str(p) if isinstance(p, dict) else str(p)
                if p_type:
                    tokens = str(p_type).split()
                    name = tokens[-1] if tokens else str(p_type)
                    if name and name not in pattern_names:
                        pattern_names.append(name)

            # 跳过无模式的文件
            if not pattern_names:
                return None

            # 提取 imports（简化版依赖图）
            imports = []
            raw = reduced.get("raw", {})
            if isinstance(raw, dict):
                raw_imports = raw.get("imports", [])
                for imp in raw_imports:
                    if isinstance(imp, dict):
                        module = imp.get("module", "")
                        if module:
                            imports.append(module)

            return TrainingCase(
                intent=fname,
                actions=pattern_names,
                outcome_text=f"Algorithm patterns: {', '.join(pattern_names)}",
                learned=pattern_names,
                layer_tags=["DSH", "G"],
                quality="B",
                confidence=0.4,
                source="rea",
                metadata={
                    "file_path": fpath,
                    "patterns": pattern_names,
                    "imports": imports,
                    "dependency_graph": {fname: imports} if imports else {},
                },
            )
        except Exception:
            return None

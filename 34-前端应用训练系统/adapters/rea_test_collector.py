"""REA 测试采集器 — DSH 层 P3 数据源.

复用 TddTestCollector 的 AST 解析逻辑,扫描 33-REA/tests/ 目录,
提取 REA 逆向工程测试调用链作为 DSH 层训练数据。

设计 (SPEC-DSH-训练数据源 v0.4 §5):
  - 委托 TddTestCollector._parse_test_file 进行 AST 解析
  - 扫描 33-REA/tests/ 22个测试文件
  - 预期 40-80 条

与 P0 TddTestCollector 的差异:
  - P0 扫描所有子系统目录 (388+文件)
  - P3 只扫描 33-REA/tests/ (22文件),专攻 REA 域
  - P0 source="tdd:xxx", P3 source="rea_test:xxx"
"""
import os
import sys
from typing import List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# 默认 REA 测试目录
_DEFAULT_REA_TEST_DIRS = [
    (os.path.join(_PROJECT_ROOT, "33-REA逆向解析工程", "tests"), "rea"),
]


class REATestCollector(TrainingDataProvider):
    """REA 测试采集器 — DSH 层 P3 数据源。

    复用 TddTestCollector 的 AST 解析,专攻 REA 测试域。
    """

    def __init__(self, scan_dirs: Optional[List[Tuple[str, str]]] = None):
        if scan_dirs is None:
            self.scan_dirs = []
            for path, domain in _DEFAULT_REA_TEST_DIRS:
                if os.path.isdir(path):
                    self.scan_dirs.append((path, domain))
        else:
            self.scan_dirs = scan_dirs
        # 委托 TddTestCollector 做实际解析
        self._delegate = None

    def _get_delegate(self):
        """延迟导入 TddTestCollector,避免循环依赖。"""
        if self._delegate is None:
            from tdd_test_collector import TddTestCollector
            self._delegate = TddTestCollector(scan_dirs=self.scan_dirs)
        return self._delegate

    def get_source_name(self) -> str:
        return "rea_test"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 REA 测试文件采集训练案例。

        委托 TddTestCollector 做 AST 解析,但替换 source 标签。

        Returns:
            训练案例列表 (FAIL-OPEN)
        """
        if not self.scan_dirs:
            return []

        delegate = self._get_delegate()
        cases = delegate.fetch_cases(limit=limit)

        # 替换 source 标签为 rea_test
        for c in cases:
            c.source = f"rea_test:{os.path.basename(c.metadata.get('file', 'unknown'))}"

        return cases

"""RED 测试：InvestigationWorkflow — 逆向调查工作流编排。

四阶段：定位(Locate)→追踪(Trace)→还原(Reduce)→标注(Annotate)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.investigation_workflow import investigate, InvestigationWorkflow
from core.evidence import Evidence


# 测试用 Python 项目
SAMPLE_PROJECT = '''
# main.py
import sys
from service import UserService
from utils import format_date

def main():
    """程序入口。"""
    svc = UserService()
    users = svc.get_users()
    for u in users:
        print(format_date(u["created_at"]))

if __name__ == "__main__":
    main()
'''

SERVICE_CODE = '''
# service.py
import axios

class UserService:
    """用户服务。"""
    def __init__(self):
        self.api = "https://api.example.com"

    def get_users(self):
        """获取用户列表。"""
        data = self._fetch("/users")
        return self._parse(data)

    def _fetch(self, endpoint):
        """发起HTTP请求。"""
        return [{"id": 1, "name": "test"}]

    def _parse(self, data):
        """解析响应。"""
        result = []
        for item in data:
            result.append(item)
        return result
'''

UTILS_CODE = '''
# utils.py
from datetime import datetime

def format_date(date_str):
    """格式化日期。"""
    dt = datetime.fromisoformat(date_str)
    return dt.strftime("%Y-%m-%d")
'''


def _setup_project(d):
    """创建测试项目结构。"""
    Path(os.path.join(d, "main.py")).write_text(SAMPLE_PROJECT.strip())
    Path(os.path.join(d, "service.py")).write_text(SERVICE_CODE.strip())
    Path(os.path.join(d, "utils.py")).write_text(UTILS_CODE.strip())


def test_investigation_returns_four_phases():
    """RED: investigate 应返回四阶段结果。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)

    assert "phases" in result
    phases = result["phases"]
    assert "locate" in phases
    assert "trace" in phases
    assert "reduce" in phases
    assert "annotate" in phases


def test_investigation_locate_phase():
    """RED: 定位阶段应检测项目类型和入口。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    locate = result["phases"]["locate"]
    assert "language" in locate or "target_type" in locate
    assert "entry_points" in locate
    assert len(locate["entry_points"]) >= 1
    assert "evidence" in locate


def test_investigation_trace_phase():
    """RED: 追踪阶段应构建调用图。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    trace = result["phases"]["trace"]
    assert "call_graph" in trace or "callers" in trace or "callees" in trace
    assert "evidence" in trace


def test_investigation_reduce_phase():
    """RED: 还原阶段应识别算法模式。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    reduce = result["phases"]["reduce"]
    assert "functions" in reduce or "patterns" in reduce
    assert "evidence" in reduce


def test_investigation_annotate_phase():
    """RED: 标注阶段应聚合所有 Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    annotate = result["phases"]["annotate"]
    assert "evidence" in annotate
    assert "summary" in annotate
    assert "known_gaps" in annotate


def test_investigation_returns_evidence():
    """RED: 顶层结果应包含 Evidence 列表。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    assert "evidence" in result
    assert len(result["evidence"]) > 0
    e = result["evidence"][0]
    assert isinstance(e, Evidence)
    assert e.provenance is not None
    assert isinstance(e.known_gaps, list)


def test_investigation_summary():
    """RED: 应返回可读摘要。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    assert "summary" in result
    assert len(result["summary"]) > 0


def test_investigation_with_feature_and_entry():
    """RED: 支持 feature + entry 参数。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d, feature="用户服务", entry="main")
    assert "feature" in result
    assert result["feature"] == "用户服务"


def test_investigation_known_gaps_aggregated():
    """RED: 标注阶段应聚合所有阶段的 known_gaps。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)
    annotate = result["phases"]["annotate"]
    assert len(annotate["known_gaps"]) > 0


def test_investigation_class_workflow():
    """RED: InvestigationWorkflow 类应可用。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        wf = InvestigationWorkflow()
        result = wf.run(d, feature="测试")

    assert "phases" in result
    assert "evidence" in result


def test_investigation_single_python_file():
    """RED: 应支持单文件分析。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "single.py")
        Path(f).write_text("def main():\n    return 42\n")
        result = investigate(f)

    assert "phases" in result
    assert len(result["evidence"]) > 0


def test_investigation_invalid_target():
    """RED: 无效目标应降级返回 + Evidence。"""
    result = investigate("/nonexistent/path/xyz")
    assert "evidence" in result
    assert len(result["evidence"]) > 0
    # 应有错误标记
    assert any("不存在" in str(e.result) or "invalid" in str(e.result).lower()
               or "not" in str(e.result).lower() for e in result["evidence"])

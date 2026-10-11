"""RED 测试：ArchitecturePatternDetector — 架构模式识别器。

Task 1 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-1.1 / TR-1.2 / TR-1.3
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 模块尚未实现，import 应失败
from core.architecture_pattern_detector import (
    ArchitecturePatternDetector,
    detect_architecture_patterns,
)


# ---------- 测试 fixture ----------

MVC_PROJECT = """
myapp/
├── models/
│   ├── __init__.py
│   └── user.py        # class User
├── views/
│   ├── __init__.py
│   └── user_view.py   # class UserView
├── controllers/
│   ├── __init__.py
│   └── user_controller.py  # class UserController
└── main.py
"""

MVC_USER_MODEL = "class User:\n    def __init__(self, name):\n        self.name = name\n"
MVC_USER_VIEW = "class UserView:\n    def render(self, user):\n        return f'User: {user.name}'\n"
MVC_USER_CTRL = "from myapp.models.user import User\nfrom myapp.views.user_view import UserView\n\nclass UserController:\n    def handle(self, name):\n        user = User(name)\n        view = UserView()\n        return view.render(user)\n"


LAYERED_PROJECT_SERVICES = "class UserService:\n    def get(self, id):\n        return {'id': id}\n"
LAYERED_PROJECT_REPOSITORIES = "class UserRepository:\n    def find(self, id):\n        return None\n"
LAYERED_PROJECT_API = "from myapp.services.user_service import UserService\n\nclass UserAPI:\n    def get_user(self, id):\n        service = UserService()\n        return service.get(id)\n"


SIMPLE_SCRIPT = "def add(a, b):\n    return a + b\n\n\nif __name__ == '__main__':\n    print(add(1, 2))\n"


# ---------- 测试用例 ----------


def test_detect_architecture_patterns_mvc_detected():
    """TR-1.1: 对 MVC fixture 项目，输出 'MVC' 模式，provenance 非空，level ∈ {observation, derivation}。"""
    with tempfile.TemporaryDirectory() as d:
        # 构造 MVC 目录结构
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)
        Path(d, "main.py").write_text("from controllers.user_controller import UserController\n")

        result = detect_architecture_patterns(d)

        assert "patterns" in result, "输出应含 patterns 字段"
        patterns = result["patterns"]
        assert isinstance(patterns, list)

        mvc_hits = [p for p in patterns if "MVC" in str(p.get("pattern", "")) or "mvc" in str(p.get("pattern", "")).lower()]
        assert len(mvc_hits) >= 1, "应检测到 MVC 模式"

        hit = mvc_hits[0]
        assert "evidence" in hit, "模式结论必须引用 Evidence (TR-1.3)"
        ev = hit["evidence"]
        assert ev.provenance, "provenance 必须非空 (TR-1.1)"
        assert ev.level.value in ("observation", "derivation"), f"level 应为 observation/derivation，实际 {ev.level}"


def test_detect_architecture_patterns_layered_detected():
    """附加测试：分层模式识别（services/repositories/api 三层目录）。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "services"))
        os.makedirs(os.path.join(d, "repositories"))
        os.makedirs(os.path.join(d, "api"))
        Path(d, "services", "__init__.py").write_text("")
        Path(d, "repositories", "__init__.py").write_text("")
        Path(d, "api", "__init__.py").write_text("")
        Path(d, "services", "user_service.py").write_text(LAYERED_PROJECT_SERVICES)
        Path(d, "repositories", "user_repository.py").write_text(LAYERED_PROJECT_REPOSITORIES)
        Path(d, "api", "user_api.py").write_text(LAYERED_PROJECT_API)

        result = detect_architecture_patterns(d)
        patterns = result["patterns"]
        layered_hits = [p for p in patterns if "layer" in str(p.get("pattern", "")).lower() or "分层" in str(p.get("pattern", ""))]
        assert len(layered_hits) >= 1, "应检测到分层模式"


def test_detect_architecture_patterns_simple_script_unknown():
    """TR-1.2: 无明确模式的简单脚本 → level=unknown 且 known_gaps 非空。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "script.py").write_text(SIMPLE_SCRIPT)
        result = detect_architecture_patterns(d)
        assert "patterns" in result

        # 无模式时应输出 unknown 级 Evidence
        evidence_list = result.get("evidence", [])
        assert len(evidence_list) > 0, "至少应有 1 条 Evidence（说明降级原因）"

        unknown_evs = [e for e in evidence_list if e.level.value == "unknown"]
        assert len(unknown_evs) >= 1, "应含 level=unknown 的 Evidence (TR-1.2)"
        assert unknown_evs[0].known_gaps, "known_gaps 必须非空 (TR-1.2)"


def test_detect_architecture_patterns_all_conclusions_have_evidence():
    """TR-1.3: 所有模式结论均引用至少 1 条 Evidence，不存在裸结论。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)

        result = detect_architecture_patterns(d)
        for p in result.get("patterns", []):
            assert "evidence" in p, "模式结论无 Evidence 引用 (TR-1.3 违反)"
            assert p["evidence"] is not None
            assert p["evidence"].provenance is not None


def test_detect_architecture_patterns_nonexistent_dir_failopen():
    """FAIL-OPEN: 不存在的目录返回 level=unknown Evidence，不抛异常。"""
    result = detect_architecture_patterns("/nonexistent/path/xyz")
    assert "patterns" in result
    assert result["patterns"] == []
    evidence_list = result.get("evidence", [])
    assert len(evidence_list) > 0
    assert any(e.level.value == "unknown" for e in evidence_list)


def test_architecture_pattern_detector_class_usable():
    """ArchitecturePatternDetector 类可直接实例化并复用。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)

        detector = ArchitecturePatternDetector()
        result = detector.detect(d)
        assert "patterns" in result
        assert len(result["patterns"]) >= 1

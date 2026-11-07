"""R0-01: 50 骨架与架构隔离测试（50 不 import 23 运行时）。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_MODULES = {"dreambuddy_evolution", "23-四层闭环自进化交易架构"}


def _iter_py_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


class TestRegistry:
    def test_registry_exists_and_schema(self):
        path = ROOT / "genes" / "registry.json"
        assert path.exists(), "genes/registry.json 缺失"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("schema_version") == "1"
        for key in ("owner", "policy", "genes"):
            assert key in data, f"registry 缺少字段 {key}"
        assert isinstance(data["genes"], list)


class TestIsolation:
    def test_no_23_import(self):
        violations: list[str] = []
        for path in _iter_py_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if any(
                        name == forbidden or name.startswith(forbidden + ".")
                        for forbidden in FORBIDDEN_MODULES
                    ):
                        violations.append(f"{path.relative_to(ROOT)}: {name}")
        assert violations == []

    def test_required_dirs(self):
        for name in ("core", "adapters", "genes", "tests"):
            assert (ROOT / name).is_dir(), f"缺少目录 {name}"

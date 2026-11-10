"""D2-B 工程方案真实实现测试。

覆盖三个模块：
- 33-REA逆向解析工程/ast_call_resolver.py（call 边 AST 精确解析）
- 0-系统文档管理/doc_coverage_checker.py（文档覆盖率/断链）
- 33-REA逆向解析工程/interface_signature_extractor.py（接口签名提取与兼容性）

加载方式遵循本目录先例：importlib.util.spec_from_file_location。
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REA_DIR = REPO_ROOT / "33-REA逆向解析工程"
DOC_DIR = REPO_ROOT / "0-系统文档管理"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


call_resolver = _load("d2b_ast_call_resolver", REA_DIR / "ast_call_resolver.py")
doc_checker = _load("d2b_doc_coverage_checker", DOC_DIR / "doc_coverage_checker.py")
sig_extractor = _load(
    "d2b_interface_signature_extractor", REA_DIR / "interface_signature_extractor.py"
)


def _write(tmp_path, rel, content):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# ast_call_resolver
# ---------------------------------------------------------------------------

DEFS_CODE = '''"""sample"""


def top(a, b):
    return a + b


class Service:
    def run(self):
        return self.helper()

    async def helper(self):
        return 1


def outer():
    def inner():
        return 0

    return inner()
'''


def test_extract_definitions_qualified_names(tmp_path):
    py = _write(tmp_path, "defs_sample.py", DEFS_CODE)
    defs = call_resolver.extract_definitions(py)
    by_qual = {d["qualified_name"]: d for d in defs}
    assert set(by_qual) == {
        "top",
        "Service.run",
        "Service.helper",
        "outer",
        "outer.inner",
    }
    assert by_qual["top"]["lineno"] == 4
    assert by_qual["Service.run"]["lineno"] == 9
    assert all(d["name"] == d["qualified_name"].split(".")[-1] for d in defs)


def test_resolve_calls_resolves_all_forms(tmp_path):
    code = (
        "foo()\n"
        "\n"
        "class Service:\n"
        "    def run(self):\n"
        "        self.helper()\n"
        "        foo()\n"
        "        obj.method()\n"
        "        mod.sub.func()\n"
        "        make().build()\n"
        "        (lambda: 1)()\n"
    )
    py = _write(tmp_path, "calls_sample.py", code)
    calls = call_resolver.resolve_calls(py)
    module_level = [c for c in calls if c["caller"] == "<module>"]
    assert {c["callee"] for c in module_level} == {"foo"}
    run_calls = [c for c in calls if c["caller"] == "Service.run"]
    callees = {c["callee"] for c in run_calls}
    assert "Service.helper" in callees  # self.x() → ClassName.x
    assert "foo" in callees
    assert "obj.method" in callees
    assert "mod.sub.func" in callees
    assert "build" in callees  # 不可点分还原时兜底为属性名
    assert all(c["lineno"] > 0 for c in calls)


def test_compute_false_dependency_rate():
    edges = [
        {"callee": "a", "candidates": 1},
        {"callee": "b", "candidates": 2},
        {"callee": "c", "candidates": 3},
        {"callee": "d", "candidates": 1},
    ]
    assert call_resolver.compute_false_dependency_rate(edges) == 0.5
    assert call_resolver.compute_false_dependency_rate([]) == 0.0
    # 非 dict 项被过滤：1 条有效边且 candidates>1 → 1.0
    assert call_resolver.compute_false_dependency_rate([None, {"candidates": 2}]) == 1.0


def test_resolve_graph_upgrades_call_edges(tmp_path):
    a = _write(tmp_path, "a.py", "def main():\n    foo(1)\n")
    b = _write(tmp_path, "b.py", "def foo(x):\n    return x\n")
    c = _write(tmp_path, "c.py", "def foo(x):\n    return x * 2\n")
    d = _write(tmp_path, "d.py", "def bar():\n    return 0\n")
    graph = {
        "nodes": [{"id": str(p), "type": "python_file"} for p in (a, b, c, d)],
        "edges": [
            {"src": str(a), "dst": str(b), "kind": "call"},
            {"src": str(a), "dst": str(c), "kind": "call"},
            {"src": str(a), "dst": str(d), "kind": "call"},
            {"src": str(b), "dst": str(c), "kind": "call"},  # b 无调用 → 不可解析
            {"src": str(a), "dst": str(b), "kind": "import"},  # 非 call 边不动
        ],
    }
    updated, stats = call_resolver.resolve_graph(graph)
    e_ab, e_ac, e_ad, e_bc, e_import = updated["edges"]
    assert e_ab["ast_resolved"] is True
    assert e_ab["resolved_callee"] == "foo"
    assert e_ab["candidates"] == 2  # foo 在 b/c 两处定义 → 重名
    assert e_ac["ast_resolved"] is True
    assert e_ad["ast_resolved"] is False  # a 未调用 d 的 bar
    assert e_bc["ast_resolved"] is False
    assert "ast_resolved" not in e_import
    assert stats["total_call_edges"] == 4
    assert stats["resolved"] == 2
    assert stats["unresolved"] == 2
    assert stats["name_collision_rate"] == 1.0
    assert stats["skipped_files"] == 0
    assert stats["definitions"] == 4


def test_resolver_fail_open_on_syntax_error(tmp_path):
    bad = _write(tmp_path, "bad.py", "def broken(:\n")
    good = _write(tmp_path, "good.py", "def ok():\n    return 1\n")
    assert call_resolver.extract_definitions(bad) == []
    assert call_resolver.resolve_calls(bad) == []
    graph = {
        "nodes": [
            {"id": str(bad), "type": "python_file"},
            {"id": str(good), "type": "python_file"},
        ],
        "edges": [{"src": str(bad), "dst": str(good), "kind": "call"}],
    }
    _, stats = call_resolver.resolve_graph(graph)  # 不抛异常
    assert stats["skipped_files"] == 1
    assert stats["resolved"] == 0
    assert graph["edges"][0]["ast_resolved"] is False


# ---------------------------------------------------------------------------
# doc_coverage_checker
# ---------------------------------------------------------------------------


def test_find_doc_for_module_same_dir(tmp_path):
    mod = _write(tmp_path, "mod/foo.py", "x = 1\n")
    assert doc_checker.find_doc_for_module(mod) is None
    readme = _write(tmp_path, "mod/README.md", "# mod\n")
    assert doc_checker.find_doc_for_module(mod) == str(readme)
    readme.unlink()
    skill = _write(tmp_path, "mod/SKILL.md", "# skill\n")
    assert doc_checker.find_doc_for_module(mod) == str(skill)
    skill.unlink()
    same_name = _write(tmp_path, "mod/foo.md", "# foo\n")
    assert doc_checker.find_doc_for_module(mod) == str(same_name)


def test_find_doc_for_module_doc_dirs(tmp_path):
    mod = _write(tmp_path, "pkg/foo.py", "x = 1\n")
    docs = tmp_path / "docs"
    assert doc_checker.find_doc_for_module(mod, [docs]) is None
    hit = _write(tmp_path, "docs/foo.md", "# foo\n")
    assert doc_checker.find_doc_for_module(mod, [docs]) == str(hit)


def test_check_coverage_aggregates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "mod_a/foo.py", "x = 1\n")
    _write(tmp_path, "mod_a/README.md", "# mod_a\n")
    _write(tmp_path, "mod_b/bar.py", "y = 2\n")
    graph = {
        "nodes": [
            {"id": "mod_a/foo.py", "type": "python_file"},
            {"id": "mod_b/bar.py", "type": "python_file"},
            {"id": "mod_a/README.md", "type": "markdown_doc"},
        ],
        "edges": [],
    }
    result = doc_checker.check_coverage(graph)
    assert result["coverage"] == 0.5
    assert result["missing_core"] == ["mod_b"]
    assert result["broken_links"] == ["mod_b/bar.py"]
    assert result["core_total"] == 2
    assert result["python_file_total"] == 2


def test_generate_doc_skeleton():
    text = doc_checker.generate_doc_skeleton("some/mod_x", ["a.py", "b.py"])
    assert text.startswith("# mod_x")
    assert "- `a.py`" in text
    assert "- `b.py`" in text
    empty = doc_checker.generate_doc_skeleton(Path("mod_y"), [])
    assert "# mod_y" in empty
    assert "（无）" in empty


def test_doc_checker_fail_open_on_empty_graph():
    for graph in ({}, {"nodes": None}, None):
        result = doc_checker.check_coverage(graph)
        assert result["coverage"] == 0.0
        assert result["broken_links"] == []
        assert result["missing_core"] == []


# ---------------------------------------------------------------------------
# interface_signature_extractor
# ---------------------------------------------------------------------------

SIG_CODE = '''"""sample"""


def public_func(x: int, y: str = "a", *args, z: float = 1.0, **kwargs) -> bool:
    return True


def _private(a):
    pass


class Cls:
    def run(self, n: int) -> None:
        pass

    def _hidden(self):
        pass
'''


def test_extract_signatures_public_only(tmp_path):
    py = _write(tmp_path, "sig_sample.py", SIG_CODE)
    sigs = sig_extractor.extract_signatures(py)
    by_name = {s["name"]: s for s in sigs}
    assert set(by_name) == {"public_func", "Cls.run"}

    func = by_name["public_func"]
    assert func["returns"] == "bool"
    args = {a["name"]: a for a in func["args"]}
    assert args["x"] == {
        "name": "x",
        "annotation": "int",
        "default": None,
        "kind": "positional",
    }
    assert args["y"]["default"] == "'a'"
    assert args["args"]["kind"] == "vararg"
    assert args["z"]["kind"] == "kwonly"
    assert args["z"]["default"] == "1.0"
    assert args["kwargs"]["kind"] == "kwargs"

    method = by_name["Cls.run"]
    assert method["returns"] == "None"
    assert [a["name"] for a in method["args"]] == ["self", "n"]


def _sig(*names, kinds=None, defaults=None):
    kinds = kinds or ["positional"] * len(names)
    defaults = defaults or [None] * len(names)
    return {
        "name": "f",
        "args": [
            {"name": n, "annotation": None, "default": d, "kind": k}
            for n, k, d in zip(names, kinds, defaults, strict=True)
        ],
        "returns": None,
    }


def test_check_call_compat():
    sig = _sig("x", "y", defaults=[None, "1"])
    assert sig_extractor.check_call_compat([1], sig) is None
    assert sig_extractor.check_call_compat([1, 2], sig) is None
    assert "参数不足" in sig_extractor.check_call_compat([], sig)
    assert "参数过多" in sig_extractor.check_call_compat([1, 2, 3], sig)
    # *args 吸收多余位置参数
    vararg_sig = _sig("x", "args", kinds=["positional", "vararg"])
    assert sig_extractor.check_call_compat([1, 2, 3, 4], vararg_sig) is None
    # **kwargs 吸收未知关键字
    kwargs_sig = _sig("x", "kw", kinds=["positional", "kwargs"])
    assert sig_extractor.check_call_compat({"args": [1], "kwargs": ["any"]}, kwargs_sig) is None
    # 未知关键字参数
    assert "未知关键字参数" in sig_extractor.check_call_compat({"args": [1], "kwargs": ["zz"]}, sig)
    # 位置与关键字重复绑定
    assert "同时被位置与关键字传入" in sig_extractor.check_call_compat(
        {"args": [1], "kwargs": ["x"]}, sig
    )
    # 必需 kwonly 参数
    kwonly_sig = _sig("x", "z", kinds=["positional", "kwonly"])
    assert "缺少必需关键字参数" in sig_extractor.check_call_compat(
        {"args": [1], "kwargs": []}, kwonly_sig
    )
    assert sig_extractor.check_call_compat({"args": [1], "kwargs": ["z"]}, kwonly_sig) is None
    # 空签名 / None 签名 FAIL-OPEN
    assert "参数过多" in sig_extractor.check_call_compat([1], None)


def test_extract_graph_signatures(tmp_path):
    good = _write(tmp_path, "good.py", "def f(a: int) -> int:\n    return a\n")
    bad = _write(tmp_path, "bad.py", "def broken(:\n")
    graph = {
        "nodes": [
            {"id": str(good), "type": "python_file"},
            {"id": str(bad), "type": "python_file"},
            {"id": "README.md", "type": "markdown_doc"},
        ],
        "edges": [],
    }
    updated = sig_extractor.extract_graph_signatures(graph)
    good_node, bad_node, doc_node = updated["nodes"]
    names = [s["name"] for s in good_node["interface_signature"]]
    assert names == ["f"]
    assert "interface_signature" not in bad_node  # parse 失败跳过
    assert "interface_signature" not in doc_node


def test_find_mismatches(tmp_path):
    b = _write(
        tmp_path,
        "b.py",
        "def foo(x):\n    return x\n\ndef bar(a, b):\n    return a + b\n",
    )
    a = _write(
        tmp_path,
        "a.py",
        "from b import bar, foo\n\n"
        "def main():\n"
        "    foo(1, 2, 3)\n"
        "    bar(1, 2)\n"
        "    undefined_func()\n"
        "    foo(1)()\n",
    )
    empty = _write(tmp_path, "empty.py", "x = 1\n")
    bad = _write(tmp_path, "bad.py", "def broken(:\n")
    graph = {
        "nodes": [{"id": str(p), "type": "python_file"} for p in (a, b, empty, bad)],
        "edges": [
            {"src": str(a), "dst": str(b), "kind": "call"},
            {"src": str(a), "dst": str(empty), "kind": "call"},  # dst 无公开签名
            {"src": str(bad), "dst": str(b), "kind": "call"},  # src parse 失败
            {"src": str(a), "dst": str(b), "kind": "import"},
        ],
    }
    mismatches = sig_extractor.find_mismatches(graph)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m["caller"].endswith("a.py::main")
    assert m["callee"].endswith("b.py::foo")
    assert "参数过多" in m["reason"]


def test_signature_parse_failure_fail_open(tmp_path):
    bad = _write(tmp_path, "bad.py", "def broken(:\n")
    assert sig_extractor.extract_signatures(bad) == []
    assert sig_extractor.find_mismatches({"nodes": [], "edges": []}) == []

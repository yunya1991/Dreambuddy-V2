"""D2-A holdout 引擎测试：选择 / 快照 / 泄漏审计 / 基线 / 评估判定。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT48 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT48))

from experiments.d2a_holdout import baselines, evaluate, holdout, leak_audit  # noqa: E402


def make_graph():
    """合成图：modA（holdout 候选，5 文件 + 文档，3 个外部入边）与若干模块。"""
    nodes = []
    for f in ["modA/a.py", "modA/b.py", "modA/c.py", "modA/d.py", "modA/README.md"]:
        nodes.append({"id": f, "type": "markdown_doc" if f.endswith(".md") else "python_file"})
    for mod in ("modB", "modC", "modD"):
        nodes.append({"id": f"{mod}/x.py", "type": "python_file"})
    edges = []
    for src in ("modB/x.py", "modC/x.py", "modD/x.py"):
        edges.append({"src": src, "dst": "modA/a.py", "kind": "import"})
    edges.append({"src": "modA/a.py", "dst": "modB/x.py", "kind": "import"})
    edges.append({"src": "modA/a.py", "dst": "modA/b.py", "kind": "import"})
    return {"nodes": nodes, "edges": edges}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    g = make_graph()
    for n in g["nodes"]:
        p = tmp_path / n["id"]
        p.parent.mkdir(parents=True, exist_ok=True)
        stem = Path(n["id"]).stem
        if n["id"].endswith(".md"):
            p.write_text(f"# {stem} 模块说明\n\n详见实现。\n", encoding="utf-8")
        else:
            # 足够长（≥20 token）且每文件唯一：避免 shingle 为空或与他文件同 hash
            body = (
                f"def handler_{stem}():\n"
                f"    v_{stem} = compute_{stem}()\n"
                f"    r_{stem} = normalize_{stem}(v_{stem})\n"
                f"    return r_{stem}\n"
            )
            p.write_text(body * 4, encoding="utf-8")
    return tmp_path


class TestSelection:
    def test_selects_qualified_module(self):
        mods, rejected = holdout.select_modules(make_graph(), max_modules=5)
        assert [m.module for m in mods] == ["modA"]
        assert mods[0].file_count == 5
        assert mods[0].inbound_source_count == 3
        assert any(r["module"] == "modB" for r in rejected)

    def test_rejects_unqualified(self):
        g = {"nodes": [{"id": "m/x.py", "type": "python_file"}], "edges": []}
        mods, rejected = holdout.select_modules(g)
        assert mods == []
        reasons = rejected[0]["reasons"]
        assert "file_count<5" in reasons and "no_doc" in reasons


class TestSnapshotAndLeakAudit:
    def test_snapshot_excludes_module_and_its_edges(self, repo: Path):
        g = make_graph()
        mod = holdout.select_modules(g)[0][0]
        built = holdout.build_snapshot(g, mod, salt="s1")
        snap, man = built["snapshot"], built["exclusion_manifest"]
        assert not any(n["id"].startswith("modA/") for n in snap["kept_nodes"])
        # 指向 holdout 模块的边即 ground truth，不得出现在输入快照中
        assert all(holdout.module_of(e["src"]) != "modA" for e in snap["kept_edges"])
        assert all(holdout.module_of(e["dst"]) != "modA" for e in snap["kept_edges"])
        assert "clue_count" not in snap
        assert man["ground_truth_edge_count"] == 3
        assert man["canary"].startswith("CANARY-")
        assert all(
            e["src"].startswith("modB")
            or e["src"].startswith("modC")
            or e["src"].startswith("modD")
            for e in man["ground_truth_edges"]
        )

    def test_audit_clean_corpus(self, repo: Path):
        g = make_graph()
        mod = holdout.select_modules(g)[0][0]
        built = holdout.build_snapshot(g, mod)
        corpus = [repo / "modB/x.py"]
        res = leak_audit.audit(repo, built["exclusion_manifest"], corpus)
        assert res["verdict"] == "clean"
        assert res["layers_run"] == ["path", "content", "hash", "canary"]

    def test_audit_detects_canary(self, repo: Path):
        g = make_graph()
        mod = holdout.select_modules(g)[0][0]
        built = holdout.build_snapshot(g, mod)
        canary = built["exclusion_manifest"]["canary"]
        leaky = repo / "leak.py"
        leaky.write_text(f"# {canary}\n", encoding="utf-8")
        res = leak_audit.audit(repo, built["exclusion_manifest"], [leaky])
        assert res["contaminated"] is True
        assert any(f["layer"] == "canary" for f in res["findings"])

    def test_audit_detects_content_copy(self, repo: Path):
        """整段内容被复制到语料 → content 层命中；仅提及路径不算泄漏。"""
        g = make_graph()
        mod = holdout.select_modules(g)[0][0]
        built = holdout.build_snapshot(g, mod)
        # 提及路径（允许的线索）
        mention = repo / "mention.md"
        mention.write_text("参见 modA/a.py 的实现\n", encoding="utf-8")
        assert leak_audit.audit(repo, built["exclusion_manifest"], [mention])["verdict"] == "clean"
        # 复制内容（真实泄漏）
        copy = repo / "copy.md"
        copy.write_text((repo / "modA/b.py").read_text(encoding="utf-8") * 3, encoding="utf-8")
        res = leak_audit.audit(repo, built["exclusion_manifest"], [copy])
        assert res["contaminated"] is True
        assert any(f["layer"] == "content" for f in res["findings"])


class TestBaselines:
    def test_tokenize_handles_cjk_module_names(self):
        toks = baselines.tokenize("0-系统文档管理/4-工具与自动化")
        assert toks and "工具" in toks  # 纯 ASCII 正则会得到空查询

    def test_predictors_return_module_level_edges(self, repo: Path):
        g = make_graph()
        mod = holdout.select_modules(g)[0][0]
        snap = holdout.build_snapshot(g, mod)["snapshot"]
        b0 = baselines.normalize_predictions(baselines.predict_b0_doc_knn(repo, snap))
        b1 = baselines.normalize_predictions(baselines.predict_b1_bm25(repo, snap))
        assert all(e[1] == "modA" for e in b0)
        assert all(e[1] == "modA" for e in b1)
        assert all(e[2] == "import" for e in b0 | b1)


class TestEvaluation:
    def test_edge_f1(self):
        truth = {("a", "m", "import"), ("b", "m", "import")}
        pred = {("a", "m", "import")}
        s = evaluate.edge_f1(pred, truth)
        assert s["tp"] == 1 and s["fp"] == 0 and s["fn"] == 1
        assert s["precision"] == 1.0 and s["recall"] == 0.5

    def test_bootstrap_and_decide(self):
        deltas = [0.1, 0.2, 0.15, 0.05, 0.3]
        ci = evaluate.cluster_bootstrap_ci(deltas, n_iter=2000)
        assert ci["n_modules"] == 5 and ci["ci_low"] > 0
        assert evaluate.decide(ci, 5)["verdict"] == "candidate"

    def test_decide_insufficient_and_falsified(self):
        assert evaluate.decide({"ci_low": 0.1, "ci_high": 0.2}, 3)["verdict"] == "insufficient_data"
        neg = evaluate.cluster_bootstrap_ci([-0.1, -0.2, -0.15, -0.05, -0.3], n_iter=2000)
        assert evaluate.decide(neg, 5)["verdict"] == "falsified"

    def test_rubric_gate(self):
        ci = {"ci_low": 0.1, "ci_high": 0.3}
        assert evaluate.decide(ci, 5, human_rubric=3.0)["verdict"] == "inconclusive"


class TestRunEndToEnd:
    def test_run_produces_artifacts(self, repo: Path, tmp_path: Path):
        gpath = tmp_path / "graph.json"
        gpath.write_text(json.dumps(make_graph()), encoding="utf-8")
        ev = __import__("experiments.d2a_holdout.run_d2a", fromlist=["run"]).run(
            gpath, tmp_path / "out", 5, "exploratory", None, root=repo
        )
        assert ev["decision"]["verdict"] == "not_run"  # 无系统预测器
        run_dir = tmp_path / "out" / ev["run_id"]
        for name in ("evaluation.json", "predictions.jsonl", "limitation.md", "prereg.json"):
            assert (run_dir / name).exists()
        mod_dir = run_dir / "modA"
        for name in ("data_snapshot.json", "exclusion_manifest.json", "leak_audit.json"):
            assert (mod_dir / name).exists()

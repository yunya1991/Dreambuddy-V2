"""tests/test_xa_real_ab.py — X-A 真实跨域 A/B 验证框架测试。

核心策略：tmp_path 造模拟 session 数据目录 → _extract_task_type/_extract_task_domain
/ _extract_metrics 解析验证 → jaccard_overlap / match_cross_domain_pairs 匹配验证
→ compute_real_gains / evaluate_real_ab 聚合验证。
"""

import importlib.util
import json
import sys
from pathlib import Path

EMERGE_ROOT = Path(__file__).resolve().parents[1]  # 48-涌现架构
XAX_DIR = EMERGE_ROOT / "experiments" / "xa_transfer"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


real_ab = _load("xa_real_ab", XAX_DIR / "real_ab.py")


def _write_session(tmp_path, rel, records):
    """往 tmp_path/rel 写 JSONL session 数据。"""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return p


# ---------------------------------------------------------------------------
# SessionRecord 解析测试
# ---------------------------------------------------------------------------


def test_extract_task_type_variants():
    # 标准字段
    rec = real_ab._extract_task_type({"task_type": "trading"})
    assert rec == "trading"
    # 驼峰
    rec = real_ab._extract_task_type({"taskType": "Engineering"})
    assert rec == "engineering"
    # tags 推断
    rec = real_ab._extract_task_type({"tags": ["intent", "frontend"]})
    assert rec == "intent"
    # 缺失 → unknown
    rec = real_ab._extract_task_type({"foo": "bar"})
    assert rec == "unknown"


def test_extract_task_domain_mapping():
    # 显式域标签
    assert real_ab._extract_task_domain({"task_domain": "a"}) == "A"
    assert real_ab._extract_task_domain({"domain": "B"}) == "B"
    # 无域标签 → task_type 映射
    assert real_ab._extract_task_domain({"task_type": "trading"}) == "trading"


def test_extract_metrics_normalized():
    rec = {
        "d1_gain": 0.5,
        "d2_gain": 1.5,  # 超界 → clip 到 1.0
        "d3_gain": -0.1,  # 超界 → clip 到 0.0
    }
    m = real_ab._extract_metrics(rec)
    assert m["d1"] == 0.5
    assert m["d2"] == 1.0
    assert m["d3"] == 0.0
    # 缺失 → 默认 0
    m = real_ab._extract_metrics({})
    assert m == {"d1": 0.0, "d2": 0.0, "d3": 0.0}


# ---------------------------------------------------------------------------
# Session 扫描
# ---------------------------------------------------------------------------


def test_scan_sessions_basic(tmp_path):
    _write_session(
        tmp_path,
        "sessions/day1.jsonl",
        [
            {
                "session_id": "s1",
                "task_type": "trading",
                "task_domain": "A",
                "d1_gain": 0.3,
                "d2_gain": 0.8,
                "d3_gain": 0.9,
            },
            {
                "session_id": "s2",
                "task_type": "engineering",
                "task_domain": "B",
                "d1_gain": 0.0,
                "d2_gain": 0.6,
                "d3_gain": 0.7,
            },
            {
                "session_id": "s3",
                "task_type": "intent",
                "task_domain": "A",
                "d1_gain": 0.2,
                "d2_gain": 0.5,
                "d3_gain": 0.8,
            },
        ],
    )
    records, stats = real_ab.scan_sessions([tmp_path])
    assert stats["records_parsed"] == 3
    assert stats["files_scanned"] == 1
    assert len(records) == 3
    assert stats["by_task_type"]["trading"] == 1
    assert stats["by_domain"]["A"] == 2


def test_scan_sessions_fail_open_bad_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"ok": 1}\nnot valid json\n{"also": 2}\n')
    records, stats = real_ab.scan_sessions([tmp_path])
    assert stats["records_parsed"] == 2
    assert stats["records_skipped"] == 1
    assert len(records) == 2


def test_scan_sessions_empty_dir(tmp_path):
    records, stats = real_ab.scan_sessions([tmp_path])
    assert records == []
    assert stats["records_parsed"] == 0
    assert stats["files_scanned"] == 0


def test_scan_sessions_nonexistent_dir():
    records, stats = real_ab.scan_sessions([Path("/nonexistent_dir_xyz_12345")])
    assert records == []
    assert stats["files_scanned"] == 0


# ---------------------------------------------------------------------------
# Jaccard & 跨域匹配
# ---------------------------------------------------------------------------


def test_jaccard_overlap():
    assert real_ab.jaccard_overlap({"a", "b"}, {"a", "b", "c"}) == 2 / 3
    assert real_ab.jaccard_overlap({"x"}, {"x"}) == 1.0
    assert real_ab.jaccard_overlap({"a"}, {"b"}) == 0.0
    assert real_ab.jaccard_overlap(set(), set()) == 0.0


def test_match_cross_domain_pairs(tmp_path):
    _write_session(
        tmp_path,
        "sessions.jsonl",
        [
            {"session_id": "a1", "task_type": "trading", "task_domain": "A"},
            {"session_id": "a2", "task_type": "engineering", "task_domain": "A"},
            {"session_id": "b1", "task_type": "trading", "task_domain": "B"},
            {"session_id": "b2", "task_type": "trading", "task_domain": "B"},
            {"session_id": "b3", "task_type": "intent", "task_domain": "B"},
        ],
    )
    records, _ = real_ab.scan_sessions([tmp_path])
    pairs = real_ab.match_cross_domain_pairs(records, "A", "B")
    # A 有 2 条、B 有 3 条 → 6 对，但 overlap=1.0 匹配的有 a1↔b1, a1↔b2（trading↔trading）
    assert len(pairs) == 6
    # overlap=1.0 的应该在前面
    assert pairs[0][2] == 1.0


def test_match_cross_domain_pairs_empty_domain(tmp_path):
    _write_session(
        tmp_path, "s.jsonl", [{"session_id": "a1", "task_type": "x", "task_domain": "A"}]
    )
    records, _ = real_ab.scan_sessions([tmp_path])
    pairs = real_ab.match_cross_domain_pairs(records, "A", "B")
    assert pairs == []  # B 域无记录


# ---------------------------------------------------------------------------
# 真实增益计算
# ---------------------------------------------------------------------------


def test_compute_real_gains_basic(tmp_path):
    _write_session(
        tmp_path,
        "sessions.jsonl",
        [
            {
                "session_id": "a1",
                "task_type": "trading",
                "task_domain": "A",
                "d1_gain": 0.4,
                "d2_gain": 0.8,
                "d3_gain": 0.6,
            },
            {
                "session_id": "b1",
                "task_type": "trading",
                "task_domain": "B",
                "d1_gain": 0.2,
                "d2_gain": 0.6,
                "d3_gain": 0.9,
            },
        ],
    )
    records, _ = real_ab.scan_sessions([tmp_path])
    pairs = real_ab.match_cross_domain_pairs(records, "A", "B")
    arms, meta = real_ab.compute_real_gains(pairs)
    assert meta["n_pairs"] == 1
    # 单对 (0.4+0.2)/2=0.3, (0.8+0.6)/2=0.7, (0.6+0.9)/2=0.75
    assert abs(meta["d1_real"] - 0.3) < 1e-6
    assert abs(meta["d2_real"] - 0.7) < 1e-6
    assert abs(meta["d3_real"] - 0.75) < 1e-6
    # 8 臂应该都在
    assert "000" in arms and "111" in arms and len(arms) == 8


def test_compute_real_gains_no_pairs():
    arms, meta = real_ab.compute_real_gains([])
    assert arms == {}
    assert meta["status"] == "no_pairs"


# ---------------------------------------------------------------------------
# evaluate_real_ab 端到端
# ---------------------------------------------------------------------------


def test_evaluate_real_ab_ok(tmp_path):
    # 造足够多 session 数据使 min_pairs=10 能满足
    import random

    rng = random.Random(42)
    records = []
    for i in range(50):
        records.append(
            {
                "session_id": f"a{i}",
                "task_type": "trading",
                "task_domain": "A",
                "d1_gain": rng.uniform(0.1, 0.5),
                "d2_gain": rng.uniform(0.5, 1.0),
                "d3_gain": rng.uniform(0.5, 1.0),
            }
        )
    for i in range(50):
        records.append(
            {
                "session_id": f"b{i}",
                "task_type": "trading",
                "task_domain": "B",
                "d1_gain": rng.uniform(0.1, 0.5),
                "d2_gain": rng.uniform(0.5, 1.0),
                "d3_gain": rng.uniform(0.5, 1.0),
            }
        )
    _write_session(tmp_path, "all.jsonl", records)

    result = real_ab.evaluate_real_ab(session_dirs=[tmp_path], min_pairs=10)
    assert result["status"] == "ok"
    assert result["verdict"] in ("candidate", "falsified", "inconclusive")
    assert "g123_real" in result
    assert "g123_bootstrap_real" in result
    assert "omega_real" in result
    assert "arms_real" in result
    assert "dimension_gains_real" in result
    assert "scan_stats" in result
    assert result["scan_stats"]["records_parsed"] == 100


def test_evaluate_real_ab_deferred_insufficient_pairs(tmp_path):
    # 只有 1 对 → min_pairs=10 → deferred
    _write_session(
        tmp_path,
        "few.jsonl",
        [
            {
                "session_id": "a1",
                "task_type": "trading",
                "task_domain": "A",
                "d1_gain": 0.3,
                "d2_gain": 0.5,
                "d3_gain": 0.6,
            },
            {
                "session_id": "b1",
                "task_type": "trading",
                "task_domain": "B",
                "d1_gain": 0.2,
                "d2_gain": 0.6,
                "d3_gain": 0.7,
            },
        ],
    )
    result = real_ab.evaluate_real_ab(session_dirs=[tmp_path], min_pairs=10)
    assert result["status"] == "deferred"
    assert result["deferred_reason"] == "insufficient_pairs"
    assert result["verdict"] == "deferred"
    assert "proxy_result" in result  # 附带代理结果


def test_evaluate_real_ab_deferred_no_data(tmp_path):
    result = real_ab.evaluate_real_ab(session_dirs=[tmp_path])
    assert result["status"] == "deferred"
    assert result["deferred_reason"] == "no_session_data"


def test_evaluate_real_ab_deferred_no_domain(tmp_path):
    # 只有一个域的 session → 跨域无匹配 → deferred
    records = [
        {"session_id": f"a{i}", "task_type": "trading", "task_domain": "A"} for i in range(20)
    ]
    _write_session(tmp_path, "only_a.jsonl", records)
    result = real_ab.evaluate_real_ab(session_dirs=[tmp_path], min_pairs=10)
    assert result["status"] == "deferred"


# ---------------------------------------------------------------------------
# 默认目录 + Jaccard
# ---------------------------------------------------------------------------


def test_default_session_dirs_contains_shadow(tmp_path, monkeypatch):
    monkeypatch.setattr(real_ab, "HOME_OVERRIDE", str(tmp_path), raising=False)
    dirs = real_ab._default_session_dirs(str(tmp_path / "custom"))
    assert any("custom" in str(d) for d in dirs)


def test_jaccard_edge_cases():
    # 相同集 → 1.0
    assert real_ab.jaccard_overlap({"a"}, {"a"}) == 1.0
    # 全不交 → 0
    assert real_ab.jaccard_overlap({"a", "b"}, {"c", "d"}) == 0.0

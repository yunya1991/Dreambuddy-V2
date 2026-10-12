"""RED 测试：P2-3/P2-4/P2-5 REA 工具修复（SPEC 维度 F）。

- P2-3: investigation_workflow evidence 按 evidence_id 去重
- P2-4: git_history 路径解析失败返回 unknown 而非静默空
- P2-5: algorithm_reducer 模式库扩展（梯度更新/相似性检索/贝叶斯更新/状态机）
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.evidence import Evidence
from core.investigation_workflow import investigate, InvestigationWorkflow
from core.git_history import trace_git_history
from core.algorithm_reducer import reduce_algorithm


# ---------------------------------------------------------------------------
# P2-3: evidence 去重
# ---------------------------------------------------------------------------

SAMPLE_PROJECT = '''
def main():
    svc = UserService()
    users = svc.get_users()
    for u in users:
        print(u)
'''


def _setup_project(d):
    Path(os.path.join(d, "main.py")).write_text(
        "from service import UserService\n\n" + SAMPLE_PROJECT.strip()
    )
    Path(os.path.join(d, "service.py")).write_text(
        "class UserService:\n"
        "    def get_users(self):\n"
        "        data = self._fetch()\n"
        "        return data\n"
        "    def _fetch(self):\n"
        "        return [1]\n"
    )


def test_investigate_top_level_evidence_no_duplicate_ids():
    """P2-3: investigate 顶层 evidence 不应有重复 evidence_id（8 条≠16 条）。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)

    ids = [e.evidence_id for e in result["evidence"]]
    assert len(ids) > 0
    assert len(ids) == len(set(ids)), (
        f"evidence 存在重复: {len(ids)} 条中仅 {len(set(ids))} 唯一"
    )


def test_phase_annotate_dedup_keeps_first_occurrence():
    """P2-3: _phase_annotate 聚合时按 evidence_id 去重且保持首次出现顺序。"""
    shared = Evidence(result="共享证据", level="observation")
    only_a = Evidence(result="仅A证据", level="observation")
    only_b = Evidence(result="仅B证据", level="observation")

    phases = {
        "locate": {"evidence": [shared, only_a]},
        "trace": {"evidence": [shared, only_b]},
    }

    wf = InvestigationWorkflow()
    annotate = wf._phase_annotate(phases, "/tmp/fake", None)

    ids = [e.evidence_id for e in annotate["evidence"]]
    assert len(ids) == len(set(ids)), "标注阶段 evidence 未去重"
    # 共享证据应只出现一次，且顺序为首次出现（locate 在前）
    assert ids[0] == shared.evidence_id
    assert set(ids) == {shared.evidence_id, only_a.evidence_id, only_b.evidence_id}


# ---------------------------------------------------------------------------
# P2-4: git_history 路径失败返回 unknown
# ---------------------------------------------------------------------------

def test_git_history_nonexistent_file_returns_unknown_level():
    """P2-4: 不存在路径应返回 level=unknown 的 Evidence 且 known_gaps 非空。"""
    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        result = trace_git_history(d, os.path.join(d, "不存在_嵌套/missing.py"))

    assert len(result["evidence"]) > 0
    unknown_evs = [
        e for e in result["evidence"]
        if (e.level.value if hasattr(e.level, "value") else str(e.level)) == "unknown"
    ]
    assert unknown_evs, "文件不存在时应返回 level=unknown 的 Evidence"
    assert any(e.known_gaps for e in unknown_evs), "unknown Evidence 的 known_gaps 应非空"
    assert any("路径解析失败" in g for e in unknown_evs for g in e.known_gaps), (
        "known_gaps 应包含 '路径解析失败' 及原因"
    )


def test_git_history_git_log_failure_returns_unknown(monkeypatch):
    """P2-4: git log 执行失败（rc!=0）应返回 unknown Evidence 而非静默空。"""
    import core.git_history as gh

    real_run = gh._run_git

    def fake_run(args, cwd):
        if "log" in args:
            return 128, "", "fatal: 路径解析失败模拟"
        return real_run(args, cwd)

    monkeypatch.setattr(gh, "_run_git", fake_run)

    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        f = os.path.join(d, "sample.py")
        Path(f).write_text("def a():\n    return 1\n")
        result = trace_git_history(d, f)

    unknown_evs = [
        e for e in result["evidence"]
        if (e.level.value if hasattr(e.level, "value") else str(e.level)) == "unknown"
    ]
    assert unknown_evs, "git log 失败时应返回 level=unknown 的 Evidence"
    assert any("路径解析失败" in g for e in unknown_evs for g in e.known_gaps)


def test_git_history_normal_path_unchanged():
    """P2-4: 正常路径行为不变（有提交历史时仍返回 observation/derivation 证据）。"""
    with tempfile.TemporaryDirectory() as d:
        import subprocess
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=d, capture_output=True)
        f = os.path.join(d, "sample.py")
        Path(f).write_text("def a():\n    return 1\n")
        subprocess.run(["git", "add", "sample.py"], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)

        result = trace_git_history(d, f)

    assert result["change_count"] >= 1
    levels = {
        (e.level.value if hasattr(e.level, "value") else str(e.level))
        for e in result["evidence"]
    }
    assert "unknown" not in levels, "正常路径不应出现 unknown 证据"


# ---------------------------------------------------------------------------
# P2-5: algorithm_reducer 模式库扩展
# ---------------------------------------------------------------------------

GRADIENT_SAMPLE = '''
def train_step(param, lr):
    grad = compute_grad(param)
    param -= lr * grad
    return param
'''

SIMILARITY_SAMPLE = '''
def retrieve(query_emb, keys, k=3):
    scores = [cosine_sim(query_emb, key) for key in keys]
    top_k = np.argsort(scores)[-k:]
    return top_k
'''

BAYES_SAMPLE = '''
def update_belief(prior, likelihood):
    posterior = likelihood * prior
    return posterior
'''

STATE_MACHINE_SAMPLE = '''
def on_event(state, event):
    if state == "idle" and event == "start":
        state = "running"
    elif state == "running" and event == "stop":
        state = "idle"
    return state
'''


def _reduce_sample(code: str, func: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.py")
        Path(f).write_text(code)
        return reduce_algorithm(f, func)


def test_pattern_library_total_at_least_7():
    """P2-5: 模式库总数应 ≥ 7（现有6种 + 新增领域模式）。"""
    recursion = '''
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
'''
    iteration = '''
def sum_list(items):
    total = 0
    for item in items:
        total += item
    return total
'''
    divide_conquer = '''
def merge_sort(items):
    if len(items) <= 1:
        return items
    mid = items[:len(items) // 2]
    return merge(merge_sort(mid), merge_sort(items[len(items) // 2:]))
'''
    dp = '''
def fib(n, memo=None):
    if memo is None:
        memo = {}
    if n in memo:
        return memo[n]
    if n <= 1:
        return n
    memo[n] = fib(n - 1, memo) + fib(n - 2, memo)
    return memo[n]
'''
    samples = [
        (recursion, "factorial"),
        (iteration, "sum_list"),
        (divide_conquer, "merge_sort"),
        (dp, "fib"),
        (GRADIENT_SAMPLE, "train_step"),
        (SIMILARITY_SAMPLE, "retrieve"),
        (BAYES_SAMPLE, "update_belief"),
        (STATE_MACHINE_SAMPLE, "on_event"),
    ]
    detected_types = set()
    for code, func in samples:
        result = _reduce_sample(code, func)
        for p in result["patterns"]:
            detected_types.add(p["type"])

    # 6 种基础模式 + 新增领域模式，可识别类型总数应 ≥ 7
    # （通过多样化样本驱动检测器，断言识别出的模式种类数）
    base = {"递归 recursion", "迭代 iteration", "累加器 accumulator",
            "条件分支 conditional_branch", "分治 divide_and_conquer",
            "动态规划 dynamic_programming"}
    new = {"梯度更新 gradient_update", "相似性检索 similarity_search",
           "贝叶斯更新 bayesian_update", "状态机 state_machine"}
    known = base | new
    unknown_types = detected_types - known
    assert not unknown_types, f"出现未知模式类型: {unknown_types}"
    # 本测试样本集至少应命中 7 种不同模式
    assert len(detected_types) >= 7, (
        f"样本集仅识别出 {len(detected_types)} 种模式: {detected_types}"
    )


def test_gradient_update_pattern_detected():
    """P2-5: 应识别梯度更新模式（param -= lr * grad 形态）。"""
    result = _reduce_sample(GRADIENT_SAMPLE, "train_step")
    types = [p["type"] for p in result["patterns"]]
    assert any("梯度更新" in t or "gradient" in t.lower() for t in types), types


def test_similarity_search_pattern_detected():
    """P2-5: 应识别相似性检索模式（cosine 相似度 + argsort top_k 形态）。"""
    result = _reduce_sample(SIMILARITY_SAMPLE, "retrieve")
    types = [p["type"] for p in result["patterns"]]
    assert any("相似性检索" in t or "similarity" in t.lower() for t in types), types


def test_bayesian_update_pattern_detected():
    """P2-5: 应识别贝叶斯更新模式（posterior = likelihood * prior 形态）。"""
    result = _reduce_sample(BAYES_SAMPLE, "update_belief")
    types = [p["type"] for p in result["patterns"]]
    assert any("贝叶斯" in t or "bayesian" in t.lower() for t in types), types


def test_state_machine_pattern_detected():
    """P2-5: 应识别状态机模式（if state == X: state = Y 形态）。"""
    result = _reduce_sample(STATE_MACHINE_SAMPLE, "on_event")
    types = [p["type"] for p in result["patterns"]]
    assert any("状态机" in t or "state_machine" in t.lower() for t in types), types


def test_new_patterns_have_line_and_description():
    """P2-5: 新模式条目应与既有模式同构（type/description/line 字段齐全）。"""
    result = _reduce_sample(STATE_MACHINE_SAMPLE, "on_event")
    for p in result["patterns"]:
        assert "type" in p and "description" in p and "line" in p


def test_new_patterns_generate_pseudo_code():
    """P2-5: 新模式命中时伪代码生成不报错且非空。"""
    for code, func in [
        (GRADIENT_SAMPLE, "train_step"),
        (SIMILARITY_SAMPLE, "retrieve"),
        (BAYES_SAMPLE, "update_belief"),
        (STATE_MACHINE_SAMPLE, "on_event"),
    ]:
        result = _reduce_sample(code, func)
        assert result["pseudo_code"], f"{func} 伪代码为空"
        assert all(isinstance(s, str) and s for s in result["pseudo_code"])

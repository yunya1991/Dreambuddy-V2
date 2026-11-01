"""C11 检索触发任务契约测试（进 G0-4 阻断 job）。

SPEC-L0 §6 C11：检索命中 → 按 task_key 排 job（去重窗口 + 并发上限 + FAIL-OPEN）；
一次检索命中可产出 1 个可追踪 job；重复检索不风暴；跨界通知不启用（P3 事件表评审前）。
"""

import os
import re
import sys
import tempfile

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

REGISTRY_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "job_registry.yaml")


def _load():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── search_triggers 映射节 ────────────────────────────────────────────────
def test_search_triggers_section_declared_and_valid():
    doc = _load()
    rules = doc.get("search_triggers")
    assert isinstance(rules, list) and rules, "job_registry.yaml 缺 search_triggers 映射节"
    keys = {t["task_key"] for t in doc["tasks"]}
    for rule in rules:
        assert rule.get("match"), f"映射缺 match: {rule}"
        assert rule.get("task_key") in keys, f"映射引用未注册 task_key: {rule}"


from dreambuddy_l0.scheduling.registry import load_registry  # noqa: E402


def test_registry_exposes_search_triggers():
    reg = load_registry(REGISTRY_PATH)
    assert reg.search_triggers, "load_registry 未解析 search_triggers"
    for rule in reg.search_triggers:
        assert rule["task_key"] in reg.task_keys()


def test_search_triggers_reject_unknown_task_key():
    doc = _load()
    doc["search_triggers"] = [{"match": "ghost/", "task_key": "ghost.task"}]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump(doc, f)
        path = f.name
    try:
        load_registry(path)
    except ValueError as exc:
        assert "ghost.task" in str(exc)
    else:
        raise AssertionError("引用未注册 task_key 的映射未被拒绝")
    finally:
        os.unlink(path)


# ── 触发语义 ───────────────────────────────────────────────────────────────
from dreambuddy_l0.fakes import FakeEvent, FakeStore  # noqa: E402
from dreambuddy_l0.scheduling.job_runs import JobRunRecorder  # noqa: E402
from dreambuddy_l0.scheduling.trigger import SearchJobTrigger  # noqa: E402

REF_A = "18-数据采集与数据中心/README.md"
REF_B = "18-数据采集与数据中心/docs/pipeline.md"


def _env():
    store, event = FakeStore(), FakeEvent()
    reg = load_registry(REGISTRY_PATH)
    rec = JobRunRecorder(store=store, event=event, registry=reg)
    trig = SearchJobTrigger(store=store, recorder=rec, registry=reg)
    return store, rec, trig


def _search_env(hits, ok=True):
    return {"ok": ok, "data": {"hits": hits}, "source": "unified_search"}


def _hit(ref, score=0.9):
    return {"ref": ref, "score": score, "sources": ["search41"]}


def test_single_hit_produces_one_trackable_pending_job():
    store, rec, trig = _env()
    now = 300 * 50 + 12
    r = trig.on_search(_search_env([_hit(REF_A)]), now=now)
    assert r["degraded"] is False and r["error_code"] == ""
    assert len(r["triggered"]) == 1
    t = r["triggered"][0]
    assert t["task_key"] == "dc.collect.local"
    assert t["run_id"] == "dc.collect.local@50"
    rows = store.query("job_runs", filters={"run_id": t["run_id"]})["rows"]
    assert len(rows) == 1
    row = rows[0]
    # 控制面只排 job（pending），由数据面执行器认领，不得冒充 running
    assert row["state"] == "pending"
    assert row["detail"]["trigger"] == "search_hit"
    assert row["detail"]["ref"] == REF_A


def test_repeat_search_same_window_does_not_storm():
    store, rec, trig = _env()
    now = 300 * 50 + 12
    trig.on_search(_search_env([_hit(REF_A)]), now=now)
    r2 = trig.on_search(_search_env([_hit(REF_A)]), now=now + 30)
    assert r2["triggered"] == []
    assert r2["skipped"][0]["reason"] == "duplicate"
    assert len(store.query("job_runs")["rows"]) == 1


def test_concurrency_cap_blocks_second_open_run():
    store, rec, trig = _env()
    now = 300 * 50 + 12
    r = trig.on_search(_search_env([_hit(REF_A), _hit(REF_B, 0.8)]), now=now)
    assert len(r["triggered"]) == 1
    reasons = {s["ref"]: s["reason"] for s in r["skipped"]}
    assert reasons[REF_B] == "concurrency_limit"
    assert len(store.query("job_runs")["rows"]) == 1


def test_retrigger_allowed_after_terminal_in_new_window():
    store, rec, trig = _env()
    now = 300 * 50 + 12
    r1 = trig.on_search(_search_env([_hit(REF_A)]), now=now)
    rec.finish(r1["triggered"][0]["run_id"], now=now + 60, state="succeeded")
    r2 = trig.on_search(_search_env([_hit(REF_A)]), now=now + 300)
    assert len(r2["triggered"]) == 1
    assert r2["triggered"][0]["run_id"] == "dc.collect.local@51"
    assert len(store.query("job_runs")["rows"]) == 2


def test_hit_without_mapping_is_skipped():
    store, rec, trig = _env()
    r = trig.on_search(_search_env([_hit("7-产物中台/x.md")]), now=300 * 50)
    assert r["triggered"] == []
    assert r["skipped"][0]["reason"] == "no_mapping"
    assert store.query("job_runs")["rows"] == []


def test_failed_search_envelope_triggers_nothing():
    store, rec, trig = _env()
    env = {
        "ok": False,
        "data": {"hits": []},
        "degraded": True,
        "meta": {"error_code": "all_sources_unavailable"},
    }
    r = trig.on_search(env, now=300 * 50)
    assert r["triggered"] == [] and r["skipped"] == []
    assert store.query("job_runs")["rows"] == []


def test_fail_open_when_store_unavailable():
    class BoomStore(FakeStore):
        def query(self, *a, **kw):
            raise RuntimeError("store down")

    store = BoomStore()
    reg = load_registry(REGISTRY_PATH)
    rec = JobRunRecorder(store=store, event=FakeEvent(), registry=reg)
    trig = SearchJobTrigger(store=store, recorder=rec, registry=reg)
    r = trig.on_search(_search_env([_hit(REF_A)]), now=300 * 50)
    assert r["degraded"] is True and r["error_code"]


# ── 落库纪律：只经 port，不直连 DB ────────────────────────────────────────
def test_trigger_module_does_not_import_db_drivers():
    banned = re.compile(r"\b(sqlite3|psycopg2?|asyncpg|pymysql|mysql\.connector)\b")
    path = os.path.join(REPO_ROOT, "dreambuddy_l0", "scheduling", "trigger.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert not banned.search(text), "trigger.py 直连数据库（违反 L0-P 约束）"

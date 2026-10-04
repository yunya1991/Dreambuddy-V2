"""EventCaseLibrary 测试 — 案例存储/检索/分类。"""
import os
import tempfile

from event_driven.event_case_library import EventCaseLibrary, EventCase


def _make_lib():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    return EventCaseLibrary(storage_path=path), path


def test_add_and_query_case():
    lib, path = _make_lib()
    case = EventCase(
        event_date="2026-09-16",
        cycle_phase="event",
        decision="hike",
        hike_prob_before=0.88,
        market_reaction={"gold": 0.02, "btc": 0.03},
        pnl_30d=0.04,
    )
    lib.add_case(case)
    results = lib.query(decision="hike")
    assert len(results) == 1
    assert results[0].event_date == "2026-09-16"
    os.unlink(path)


def test_dedup_same_date():
    lib, path = _make_lib()
    lib.add_case(EventCase(event_date="2026-09-16", cycle_phase="event", decision="hike", hike_prob_before=0.88))
    lib.add_case(EventCase(event_date="2026-09-16", cycle_phase="event", decision="hike", hike_prob_before=0.92))
    assert lib.size() == 1
    assert lib.all_cases()[0].hike_prob_before == 0.92
    os.unlink(path)


def test_classify_reaction_hike_relief():
    """加息 + 黄金涨 → relief。"""
    lib, _ = _make_lib()
    label = lib.classify_reaction("hike", {"gold": 0.02})
    assert label == "relief"


def test_classify_reaction_hike_reversal():
    """加息 + 黄金跌 → reversal。"""
    lib, _ = _make_lib()
    label = lib.classify_reaction("hike", {"gold": -0.03})
    assert label == "reversal"


def test_get_relief_ratio():
    lib, path = _make_lib()
    lib.add_case(EventCase(event_date="2026-01-01", cycle_phase="event", decision="hike",
                           hike_prob_before=0.9, relief_or_reversal="relief"))
    lib.add_case(EventCase(event_date="2026-03-01", cycle_phase="event", decision="hike",
                           hike_prob_before=0.9, relief_or_reversal="reversal"))
    lib.add_case(EventCase(event_date="2026-06-01", cycle_phase="event", decision="hike",
                           hike_prob_before=0.9, relief_or_reversal="relief"))
    ratio = lib.get_relief_ratio(cycle_phase="event")
    assert abs(ratio - 2/3) < 1e-6
    os.unlink(path)


def test_get_avg_pnl():
    lib, path = _make_lib()
    lib.add_case(EventCase(event_date="2026-01-01", cycle_phase="event", decision="hike",
                           hike_prob_before=0.9, pnl_30d=0.05))
    lib.add_case(EventCase(event_date="2026-03-01", cycle_phase="event", decision="hike",
                           hike_prob_before=0.9, pnl_30d=-0.02))
    avg = lib.get_avg_pnl(decision="hike")
    assert avg is not None
    assert abs(avg - 0.015) < 1e-6
    os.unlink(path)


def test_persistence():
    lib, path = _make_lib()
    lib.add_case(EventCase(event_date="2026-09-16", cycle_phase="event", decision="hike", hike_prob_before=0.88))
    # 重新加载
    lib2 = EventCaseLibrary(storage_path=path)
    assert lib2.size() == 1
    assert lib2.all_cases()[0].decision == "hike"
    os.unlink(path)

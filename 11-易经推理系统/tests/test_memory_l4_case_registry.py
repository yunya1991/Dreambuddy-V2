import json


def test_create_case_from_episode_minimal_fields():
    from scripts.memory_l4.case_registry import create_case_from_episode_data

    episode = {
        "trace_id": "trace_test_001",
        "ts": "2026-04-20T12:51:49+08:00",
        "inst_id": "BTC-USDT-SWAP",
        "decision": "SHORT"
    }

    case = create_case_from_episode_data(episode, case_id="TC_TEST_001")

    assert case["case_id"] == "TC_TEST_001"
    assert case["ts_start"] == episode["ts"]
    assert case["inst_id"] == episode["inst_id"]
    assert "intent" in case
    assert "execution" in case
    assert case["execution"]["episode_refs"][0]["trace_id"] == episode["trace_id"]

    json.dumps(case)


def test_create_distill_template():
    from scripts.memory_l4.distill_template import create_distill_template

    d = create_distill_template("D_TEST_1", ["TC_1"], kind="risk_signal")
    assert d["distill_id"] == "D_TEST_1"
    assert d["supporting_case_ids"] == ["TC_1"]
    assert d["kind"] == "risk_signal"


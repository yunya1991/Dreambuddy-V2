def test_web3_market_digest_slow_suite_is_guarded_by_env() -> None:
    import os

    assert str(os.getenv("RUN_SLOW_TESTS", "0")).strip() in {"0", "1"}


def test_web3_market_digest_slow_suite_has_skip_guard() -> None:
    from pathlib import Path

    p = Path("tests/test_web3_market_digest_automation.py")
    s = p.read_text(encoding="utf-8")
    assert "RUN_SLOW_TESTS" in s
    assert "pytest.mark.skip" in s

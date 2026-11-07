import pytest
from okx_venue import VenueConfig, VenueConfigError


def test_default_is_demo_only(tmp_path):
    cfg = VenueConfig(audit_path=tmp_path / "audit.jsonl")
    assert cfg.mode == "demo"
    assert cfg.read_allowed is True
    assert cfg.write_allowed is True
    assert cfg.mode_flags() == ["--profile", "demo"]


def test_live_mode_blocks_reads_by_default(tmp_path):
    cfg = VenueConfig(
        profile="okx-live",
        mode="live",
        audit_path=tmp_path / "audit.jsonl",
    )
    assert cfg.read_allowed is False
    assert cfg.write_allowed is False
    assert cfg.mode_flags() == ["--profile", "okx-live"]


def test_live_mode_allows_reads_only_with_flag(tmp_path):
    cfg = VenueConfig(
        profile="okx-live",
        mode="live",
        allow_live_read=True,
        audit_path=tmp_path / "audit.jsonl",
    )
    assert cfg.read_allowed is True
    assert cfg.write_allowed is False


def test_profile_mode_contradiction_is_rejected(tmp_path):
    with pytest.raises(VenueConfigError):
        VenueConfig(
            profile="okx-live",
            mode="demo",
            audit_path=tmp_path / "audit.jsonl",
        )
    with pytest.raises(VenueConfigError):
        VenueConfig(
            profile="demo",
            mode="live",
            audit_path=tmp_path / "audit.jsonl",
        )


def test_oauth_mode_flags(tmp_path):
    demo = VenueConfig(auth="oauth", mode="demo", audit_path=tmp_path / "audit.jsonl")
    live = VenueConfig(
        auth="oauth",
        profile="okx-live",
        mode="live",
        audit_path=tmp_path / "audit.jsonl",
    )
    assert demo.mode_flags() == ["--demo"]
    assert live.mode_flags() == []


def test_invalid_mode_is_rejected(tmp_path):
    with pytest.raises(VenueConfigError):
        VenueConfig(mode="sandbox", audit_path=tmp_path / "audit.jsonl")


def test_from_env_reads_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("OKX_VENUE_PROFILE", "demo")
    monkeypatch.setenv("OKX_VENUE_MODE", "demo")
    monkeypatch.setenv("OKX_VENUE_ALLOW_LIVE_READ", "0")
    monkeypatch.setenv("OKX_VENUE_AUDIT_PATH", str(tmp_path / "a.jsonl"))
    cfg = VenueConfig.from_env()
    assert cfg.mode == "demo"
    assert cfg.read_allowed is True

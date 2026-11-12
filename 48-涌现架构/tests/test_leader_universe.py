"""U 层龙头宇宙测试：10 大类 / 六锚 / 必备品种 / 价格主源 / point-in-time 快照。"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "registry"))

import universe as uni  # noqa: E402


@pytest.fixture
def cfg():
    return uni.load_config()


@pytest.fixture
def ac():
    return uni.load_asset_classes()


def test_config_projects_all_ten_classes(cfg, ac):
    assert len(ac.ASSET_CLASSES) == 10
    assert set(cfg["signal_coverage"]) == set(ac.ASSET_CLASSES)


def test_six_g1_anchors(cfg, ac):
    assert cfg["g1_anchors"] == ["BTC", "XAU", "CL", "US500", "JP225", "TLT"]
    assert tuple(cfg["g1_anchors"]) == ac.G1_ANCHOR_SYMBOLS


def test_required_instruments_present(cfg, ac):
    members = ac.ASSET_CLASSES
    for cls, symbols in cfg["required_symbols"].items():
        for sym in symbols:
            assert sym in members[cls]["members"], f"{cls} 缺 {sym}"


def test_config_does_not_duplicate_members(cfg):
    # SPEC §2.3 纪律 3：成员表唯一真源在 40，配置不得复制
    text = json.dumps(cfg, ensure_ascii=False)
    assert '"members"' not in text


def test_validate_passes_on_real_registry(cfg, ac):
    assert uni.validate(cfg, ac) == []


def test_validate_detects_missing_anchor(cfg, ac):
    bad = json.loads(json.dumps(cfg))
    bad["g1_anchors"] = ["BTC", "XAU", "CL"]
    assert any("六锚" in p for p in uni.validate(bad, ac))


def test_validate_detects_copied_members(cfg, ac):
    bad = json.loads(json.dumps(cfg))
    bad["classes"] = {"crypto": {"members": ["BTC"]}}
    assert any("成员表" in p for p in uni.validate(bad, ac))


def test_universe_join_keeps_source_of_truth(cfg, ac):
    u = uni.load_universe(cfg, ac)
    assert u["source_of_truth"].startswith("40-")
    assert u["classes"]["energy"]["members"] == ["CL", "BZ", "NG", "USO"]
    assert u["classes"]["fx"]["inst_id"] is None
    assert u["classes"]["crypto"]["signals"]["M"] == "direct"


def test_snapshot_is_point_in_time_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(uni, "SNAPSHOT_DIR", tmp_path / "snaps")
    monkeypatch.setattr(uni, "CHANGE_LOG_PATH", tmp_path / "change_log.jsonl")

    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    first = uni.snapshot(now=now)
    assert first["changed"] is True
    snap = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
    assert snap["universe_reviewed_at"] == "2026-11-11"
    assert snap["digest"] == first["digest"]
    assert len(snap["classes"]) == 10

    second = uni.snapshot(now=now)
    assert second["changed"] is False
    log_lines = (tmp_path / "change_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1

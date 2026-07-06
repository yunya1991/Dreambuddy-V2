import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "remote_repo_guard.py"
SPEC = importlib.util.spec_from_file_location("remote_repo_guard", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_parse_repo_input_accepts_full_url():
    assert MODULE.parse_repo_input("https://github.com/yunya1991/dream-multiskill-v2") == "yunya1991/dream-multiskill-v2"


def test_parse_repo_input_accepts_owner_repo():
    assert MODULE.parse_repo_input("yunya1991/dream-multiskill-v2") == "yunya1991/dream-multiskill-v2"


def test_validate_main_protection_passes_when_required_check_exists():
    payload = {"required_status_checks": {"checks": [{"context": "PR Gate Checks"}]}}
    ok, msg = MODULE.validate_main_protection(payload)
    assert ok is True
    assert "includes required PR gate check" in msg


def test_validate_main_protection_fails_when_required_check_missing():
    payload = {"required_status_checks": {"checks": [{"context": "Other Check"}]}}
    ok, msg = MODULE.validate_main_protection(payload)
    assert ok is False
    assert "required check missing" in msg

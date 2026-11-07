import json
import subprocess

import pytest
from okx_venue import (
    CliAuthError,
    CliInvalidResponse,
    CliNonZeroExit,
    CliNotInstalled,
    CliRunner,
    CliTimeout,
    LiveReadForbidden,
    LiveTradingForbidden,
    VenueConfig,
)
from okx_venue.runner import redact_argv


class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result
        self.exc = exc

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.exc:
            raise self.exc
        return self.result


def _cfg(tmp_path, **overrides):
    values = {
        "profile": "demo",
        "mode": "demo",
        "audit_path": tmp_path / "audit.jsonl",
    }
    values.update(overrides)
    return VenueConfig(**values)


def _completed(argv, rc=0, stdout="{}", stderr=""):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)


def test_appends_profile_and_json(tmp_path):
    rec = Recorder(_completed(["okx"], stdout='{"ok": true}'))
    runner = CliRunner(_cfg(tmp_path), run=rec)
    assert runner.run(["market", "ticker", "BTC-USDT"], operation="ticker") == {"ok": True}
    argv, kwargs = rec.calls[0]
    assert argv == [
        "okx",
        "--profile",
        "demo",
        "market",
        "ticker",
        "BTC-USDT",
        "--json",
    ]
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True


def test_audit_line_is_written(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    runner = CliRunner(
        _cfg(tmp_path, audit_path=audit_path),
        run=Recorder(_completed(["okx"], stdout='{"ok": true}')),
    )
    runner.run(["account", "balance"], operation="balance")
    line = audit_path.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["operation"] == "balance"
    assert record["ok"] is True
    assert record["profile"] == "demo"
    assert record["mode"] == "demo"
    assert record["error_code"] == ""


def test_live_write_is_rejected_without_calling_cli(tmp_path):
    rec = Recorder(_completed(["okx"]))
    runner = CliRunner(
        _cfg(tmp_path, mode="live", profile="okx-live", allow_live_read=True),
        run=rec,
    )
    with pytest.raises(LiveTradingForbidden):
        runner.run(
            ["swap", "place", "--instId", "BTC-USDT-SWAP"],
            operation="place",
            write=True,
        )
    assert rec.calls == []


def test_live_read_is_rejected_by_default(tmp_path):
    rec = Recorder(_completed(["okx"]))
    runner = CliRunner(_cfg(tmp_path, mode="live", profile="okx-live"), run=rec)
    with pytest.raises(LiveReadForbidden):
        runner.run(["account", "balance"], operation="balance")
    assert rec.calls == []


def test_auth_error_is_classified(tmp_path):
    rec = Recorder(_completed(["okx"], rc=1, stdout="", stderr="401 session expired"))
    runner = CliRunner(_cfg(tmp_path), run=rec)
    with pytest.raises(CliAuthError) as exc_info:
        runner.run(["account", "balance"], operation="balance")
    assert exc_info.value.code == "cli_auth_error"


def test_generic_nonzero_exit(tmp_path):
    rec = Recorder(_completed(["okx"], rc=2, stdout="", stderr="boom"))
    runner = CliRunner(_cfg(tmp_path), run=rec)
    with pytest.raises(CliNonZeroExit) as exc_info:
        runner.run(["account", "balance"], operation="balance")
    assert exc_info.value.code == "cli_nonzero_exit"


def test_timeout(tmp_path):
    exc = subprocess.TimeoutExpired(["okx"], 30)
    runner = CliRunner(_cfg(tmp_path), run=Recorder(exc=exc))
    with pytest.raises(CliTimeout):
        runner.run(["account", "balance"], operation="balance")


def test_cli_not_installed(tmp_path):
    runner = CliRunner(_cfg(tmp_path), run=Recorder(exc=FileNotFoundError()))
    with pytest.raises(CliNotInstalled):
        runner.run(["account", "balance"], operation="balance")


def test_invalid_json(tmp_path):
    rec = Recorder(_completed(["okx"], stdout="not-json"))
    runner = CliRunner(_cfg(tmp_path), run=rec)
    with pytest.raises(CliInvalidResponse):
        runner.run(["account", "balance"], operation="balance")


def test_redact_argv():
    assert redact_argv(["okx", "--api-key", "secret", "--secret", "s2", "market"]) == [
        "okx",
        "--api-key",
        "***",
        "--secret",
        "***",
        "market",
    ]

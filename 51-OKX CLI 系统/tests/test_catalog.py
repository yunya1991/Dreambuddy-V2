import pytest
from okx_venue.catalog import allowed_operations, validate_argv
from okx_venue.errors import CommandNotAllowed


def test_read_allowlist_accepts_market_commands():
    validate_argv(["market", "ticker", "BTC-USDT-SWAP"], write=False)
    validate_argv(
        ["market", "candles", "BTC-USDT-SWAP", "--bar", "1H", "--limit", "10"],
        write=False,
    )
    validate_argv(["account", "balance"], write=False)
    validate_argv(["account", "positions", "--instId", "BTC-USDT-SWAP"], write=False)


def test_write_action_requires_write_mode():
    with pytest.raises(CommandNotAllowed):
        validate_argv(
            [
                "swap",
                "place",
                "--instId",
                "BTC-USDT-SWAP",
                "--side",
                "buy",
                "--ordType",
                "market",
                "--sz",
                "1",
                "--tdMode",
                "cross",
            ],
            write=False,
        )


def test_write_allowlist_accepts_spot_and_swap():
    validate_argv(["spot", "place", "--instId", "BTC-USDT"], write=True)
    validate_argv(["swap", "cancel", "BTC-USDT-SWAP", "--ordId", "1"], write=True)


def test_forbidden_modules_are_rejected():
    for module in ("config", "auth", "bot", "earn", "event", "option", "futures"):
        with pytest.raises(CommandNotAllowed):
            validate_argv([module, "show"], write=False)


def test_caller_cannot_pass_profile_or_demo_flags():
    for flag in ("--profile", "--demo"):
        with pytest.raises(CommandNotAllowed):
            validate_argv(["account", "balance", flag, "live"], write=False)


def test_credential_flags_are_rejected():
    for flag in ("--api-key", "--secret", "--secret-key", "--passphrase"):
        with pytest.raises(CommandNotAllowed):
            validate_argv(["market", "ticker", "BTC-USDT", flag, "x"], write=False)


def test_shell_metacharacters_are_rejected():
    for token in ("BTC;rm", "BTC|cat", "BTC&x", "BTC$HOME", "BTC`id`", "BTC>x"):
        with pytest.raises(CommandNotAllowed):
            validate_argv(["market", "ticker", token], write=False)


def test_allowed_operations_snapshot():
    ops = allowed_operations()
    assert "market" in ops["read"]
    assert "place" in ops["write"]["swap"]
    assert "config" in ops["forbidden_modules"]

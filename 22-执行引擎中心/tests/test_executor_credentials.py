"""22 域交易所凭据库验收：加密落盘、回读、环境变量/目录覆盖、脱敏状态。

约束来源（Plan A）：OKX 密钥只允许存放在 22 域独立凭据库，禁止明文落盘，
禁止 22 读取 11 域 .env。
"""

from __future__ import annotations

import json
from pathlib import Path

from executors import credentials as cred

OKX_CFG = {
    "api_key": "test-api-key-0001",
    "secret_key": "test-secret-key-0002",
    "passphrase": "test-passphrase-0003",
    "base_url": "https://www.okx.com",
    "simulated": False,
    "dry_run": False,
    "default_inst_id": "BTC-USDT-SWAP",
    "default_leverage": 5.0,
    "td_mode": "isolated",
}


def _clear_okx_env(monkeypatch) -> None:
    for key in (
        "OKX_API_KEY",
        "OKX_SECRET_KEY",
        "OKX_PASSPHRASE",
        "OKX_BASE_URL",
        "OKX_SIMULATED",
        "OKX_DRY_RUN",
        "OKX_DEFAULT_INST_ID",
        "OKX_TD_MODE",
        "DEFAULT_LEVERAGE",
        "DEFAULT_MARGIN_USDT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_roundtrip_and_no_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    cred.save_okx_config(OKX_CFG)

    loaded = cred.load_okx_config()
    assert loaded == OKX_CFG

    enc = tmp_path / "venue" / cred.CRED_FILE
    raw = enc.read_bytes()
    for secret in ("test-api-key-0001", "test-secret-key-0002", "test-passphrase-0003"):
        assert secret.encode() not in raw, "凭据不得以明文落盘"
    assert not (tmp_path / "venue" / "config.json").exists()


def test_key_file_permission_is_600(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    cred.save_okx_config(OKX_CFG)
    mode = (tmp_path / "venue" / cred.KEY_FILE).stat().st_mode & 0o777
    assert mode == 0o600


def test_missing_store_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "absent"))
    assert cred.load_okx_config() == {}


def test_corrupted_store_returns_empty(tmp_path, monkeypatch):
    """凭据损坏时返回空 → 客户端回落 simulated=True → 下单被拒（fail-closed）。"""
    store = tmp_path / "venue"
    store.mkdir()
    (store / cred.CRED_FILE).write_text("not-a-valid-ciphertext")
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(store))
    assert cred.load_okx_config() == {}


def test_status_masks_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    cred.save_okx_config(OKX_CFG)
    status = cred.status()
    assert status["configured"] is True
    assert status["simulated"] is False
    text = json.dumps(status, ensure_ascii=False)
    assert "test-api-key-0001" not in text
    assert "test-secret-key-0002" not in text
    assert "test-passphrase-0003" not in text


def test_import_env_file(tmp_path, monkeypatch):
    """import-env 从 .env 迁移凭据，只返回脱敏摘要。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "OKX_API_KEY=test-api-key-0001",
                "OKX_SECRET_KEY=test-secret-key-0002",
                "OKX_PASSPHRASE=test-passphrase-0003",
                "OKX_SIMULATED=false",
                "OKX_DRY_RUN=false",
                "OKX_DEFAULT_INST_ID=BTC-USDT-SWAP",
                "OKX_TD_MODE=isolated",
                "DEFAULT_LEVERAGE=5",
                "DEFAULT_MARGIN_USDT=100",
                "UNRELATED=value",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    summary = cred.import_env_file(env_file)

    assert summary["configured"] is True
    assert "test-api-key-0001" not in json.dumps(summary, ensure_ascii=False)

    loaded = cred.load_okx_config()
    assert loaded["api_key"] == "test-api-key-0001"
    assert loaded["simulated"] is False
    assert loaded["dry_run"] is False
    assert loaded["default_leverage"] == 5.0
    assert loaded["default_usdt_amount"] == 500.0
    assert "UNRELATED" not in loaded


def test_save_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    try:
        cred.save_okx_config({})
    except ValueError:
        pass
    else:  # pragma: no cover - 明确失败路径
        raise AssertionError("空凭据应被拒绝")
    assert not (Path(str(tmp_path / "venue")) / cred.CRED_FILE).exists()

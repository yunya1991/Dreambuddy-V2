"""OKX 客户端下沉到 22 域后的契约验收。

验证：
1. 客户端实现位于 22 域，不再读取 11 域 .env / 不再反向引用 11 模块；
2. 配置优先级 = 环境变量 > 22 域加密凭据库 > 默认值；
3. 11 域的 okx_simulated.py 仅为转发 shim，类对象与 22 域一致。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from executors import credentials as cred
from executors import okx_client

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parent
CLIENT_SRC = Path(okx_client.__file__)

OKX_CFG = {
    "api_key": "store-api-key",
    "secret_key": "store-secret-key",
    "passphrase": "store-passphrase",
    "base_url": "https://www.okx.com",
    "simulated": False,
    "dry_run": False,
    "default_inst_id": "ETH-USDT-SWAP",
    "default_usdt_amount": 250.0,
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
        "DEFAULT_LEVERAGE",
        "DEFAULT_MARGIN_USDT",
        "OKX_TD_MODE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_client_lives_in_22_and_has_no_11_reference():
    assert CLIENT_SRC.parent == MODULE_ROOT / "executors"
    src = CLIENT_SRC.read_text(encoding="utf-8")
    assert "11-易经推理" not in src
    assert "okx_simulated" not in src
    assert "env_path" not in src, "不得再回读 11 域 .env"


def test_load_config_from_encrypted_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    _clear_okx_env(monkeypatch)
    cred.save_okx_config(OKX_CFG)

    cfg = okx_client._load_config()
    assert cfg["api_key"] == "store-api-key"
    assert cfg["simulated"] is False
    assert cfg["dry_run"] is False
    assert cfg["default_inst_id"] == "ETH-USDT-SWAP"
    assert cfg["default_usdt_amount"] == 250.0


def test_env_overrides_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "venue"))
    _clear_okx_env(monkeypatch)
    cred.save_okx_config(OKX_CFG)
    monkeypatch.setenv("OKX_API_KEY", "env-api-key")
    monkeypatch.setenv("OKX_SIMULATED", "true")

    cfg = okx_client._load_config()
    assert cfg["api_key"] == "env-api-key"
    assert cfg["simulated"] is True


def test_defaults_fail_closed_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("OKX_SIM_DATA_DIR", str(tmp_path / "data"))
    _clear_okx_env(monkeypatch)

    cfg = okx_client._load_config()
    assert cfg["api_key"] == ""
    assert cfg["simulated"] is True
    assert cfg["dry_run"] is True


def test_runtime_data_dir_defaults_into_22(monkeypatch, tmp_path):
    """客户端审计/状态目录默认落在 22 域 runtime，而不是 11 域 data。"""
    assert Path(okx_client.CONFIG_DIR) == MODULE_ROOT / "runtime" / "okx_sim"
    assert Path(okx_client.AUDIT_LOG).parent == MODULE_ROOT / "runtime" / "okx_sim"


def test_11_shim_is_alias_of_22_client(tmp_path):
    """11 域脚本继续 `from okx_simulated import OKXSimulatedClient`，实际实现来自 22 域。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(MODULE_ROOT)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT / '11-易经推理系统' / 'scripts' / 'memory_l4')!r})\n"
        "import okx_simulated\n"
        "from executors.okx_client import OKXSimulatedClient\n"
        "assert okx_simulated.OKXSimulatedClient is OKXSimulatedClient\n"
        "assert okx_simulated.CONFIG_DIR.exists()\n"
        "print('SHIM_OK')\n"
    )
    env = dict(os.environ)
    env["OKX_SIM_DATA_DIR"] = str(tmp_path / "data")
    env["OKX_CREDENTIALS_DIR"] = str(tmp_path / "venue")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "SHIM_OK" in result.stdout

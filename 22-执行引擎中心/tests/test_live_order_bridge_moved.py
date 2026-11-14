"""live_order_bridge 迁移到 22 域后的契约验收。

验证：
1. 桥脚本位于 22/executors，11 域旧脚本已删除；x1_live_executor 指向 22；
2. 桥不再读取 11/.env，凭据来自 22 域加密库；
3. simulated/dry_run、kill-switch 均 fail-closed，且不发起网络请求；
4. 审计与 kill-switch 路径落在 22 域 runtime。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from executors import credentials as cred
from executors import live_order_bridge as bridge

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_ROOT.parent
BRIDGE_PATH = MODULE_ROOT / "executors" / "live_order_bridge.py"
OLD_BRIDGE_PATH = REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "live_order_bridge.py"

OKX_CFG = {
    "api_key": "k",
    "secret_key": "s",
    "passphrase": "p",
    "base_url": "https://www.okx.com",
    "simulated": True,
    "dry_run": True,
    "default_inst_id": "BTC-USDT-SWAP",
    "default_leverage": 3.0,
    "td_mode": "isolated",
}


def _run_bridge(payload: dict, env_extra: dict) -> dict:
    env = dict(os.environ)
    env.pop("22_LIVE_KILL_SWITCH", None)
    env.pop("OKX_API_KEY", None)
    env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(BRIDGE_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(MODULE_ROOT),
    )
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def test_bridge_lives_in_22_and_old_one_removed():
    assert BRIDGE_PATH.exists()
    assert not OLD_BRIDGE_PATH.exists()

    src = BRIDGE_PATH.read_text(encoding="utf-8")
    assert "11-易经推理" not in src
    assert "okx_simulated" not in src
    assert "_load_env" not in src


def test_x1_live_executor_uses_22_bridge():
    import x1_live_executor

    assert Path(x1_live_executor._BRIDGE) == BRIDGE_PATH
    src = Path(x1_live_executor.__file__).read_text(encoding="utf-8")
    assert "11-易经推理" not in src


def test_runtime_paths_owned_by_22():
    runtime = MODULE_ROOT / "runtime"
    assert Path(bridge.AUDIT_PATH).parent == runtime
    assert Path(bridge.KILL_SWITCH_FILE).parent == runtime


def test_order_rejected_when_simulated(tmp_path, monkeypatch):
    store = tmp_path / "venue"
    monkeypatch.setenv("OKX_CREDENTIALS_DIR", str(store))
    cred.save_okx_config(OKX_CFG)

    out = _run_bridge(
        {
            "action": "order",
            "symbol": "BTC-USDT-SWAP",
            "direction": "long",
            "notional_usdt": 100,
            "leverage": 3,
            "sl_pct": 1.5,
            "tp_pct": 3.0,
        },
        {
            "OKX_CREDENTIALS_DIR": str(store),
            "OKX_SIM_DATA_DIR": str(tmp_path / "data"),
            "OKX_DRY_RUN": "true",
        },
    )
    assert out["ok"] is False
    assert out["error_code"] == "not_live"


def test_kill_switch_blocks_before_network(tmp_path):
    out = _run_bridge(
        {"action": "order", "symbol": "BTC-USDT-SWAP", "direction": "long"},
        {
            "OKX_CREDENTIALS_DIR": str(tmp_path / "absent"),
            "OKX_SIM_DATA_DIR": str(tmp_path / "data"),
            "22_LIVE_KILL_SWITCH": "1",
        },
    )
    assert out["ok"] is False
    assert out["error_code"] == "kill_switch"


def test_registry_drives_allowed_symbols_and_max_positions(monkeypatch):
    """多资产白名单与并发上限来自 config/live_symbols.json，环境变量可覆盖上限。"""
    assert {"BTC-USDT-SWAP", "XAU-USDT-SWAP", "NVDA-USDT-SWAP"} <= bridge.ALLOWED_SYMBOLS
    assert bridge._load_max_positions() == bridge._REGISTRY.get("max_positions_default")

    monkeypatch.setenv("22_MAX_POSITIONS", "9")
    assert bridge._load_max_positions() == 9

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22 执行引擎域交易所凭据库（唯一存放地）。

设计边界：
- 交易所凭据只在 22 域落盘，AES-256-GCM 加密，禁止明文 .env / config.json
- 11/14/16 等消费方通过 ``load_okx_config()`` 读取，或由客户端注入环境变量
- 读取失败时返回空配置 → 客户端回落 simulated=True/dry_run=True → 下单被拒（fail-closed）

CLI：
  python3 -m executors.credentials status
  python3 -m executors.credentials import-env --file path/to/.env
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict

CRED_FILE = "credentials.enc"
KEY_FILE = "key"
_AAD = b"dreambuddy-22-executor-venue-v1"
_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "runtime" / "venue"

OKX_FIELDS = (
    "api_key",
    "secret_key",
    "passphrase",
    "base_url",
    "simulated",
    "dry_run",
    "default_inst_id",
    "default_usdt_amount",
    "default_leverage",
    "td_mode",
)
SENSITIVE_FIELDS = ("api_key", "secret_key", "passphrase")


def _store_dir() -> Path:
    return Path(os.environ.get("OKX_CREDENTIALS_DIR") or _DEFAULT_DIR)


def _cipher():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - 依赖缺失环境
        raise RuntimeError("cryptography 未安装，无法读写 22 域凭据库") from exc
    return AESGCM


def _key() -> bytes:
    """读取或生成 32 字节主密钥，权限固定 0600。"""
    env_key = os.environ.get("OKX_CREDENTIALS_KEY")
    if env_key:
        raw = base64.urlsafe_b64decode(env_key.encode())
        if len(raw) != 32:
            raise ValueError("OKX_CREDENTIALS_KEY 必须为 32 字节的 urlsafe-base64")
        return raw

    key_path = _store_dir() / KEY_FILE
    if key_path.exists():
        return base64.urlsafe_b64decode(key_path.read_text(encoding="ascii").strip().encode())

    key_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(key_path.parent, 0o700)
    raw = secrets.token_bytes(32)
    key_path.write_text(base64.urlsafe_b64encode(raw).decode(), encoding="ascii")
    os.chmod(key_path, 0o600)
    return raw


def load_okx_config() -> Dict[str, Any]:
    """读取 OKX 配置；不存在或损坏时返回空字典（调用方按 fail-closed 处理）。"""
    cred_path = _store_dir() / CRED_FILE
    if not cred_path.exists():
        return {}
    try:
        aesgcm = _cipher()
        raw = base64.b64decode(cred_path.read_text(encoding="ascii").strip())
        nonce, token = raw[:12], raw[12:]
        plaintext = aesgcm(_key()).decrypt(nonce, token, _AAD)
        data = json.loads(plaintext.decode("utf-8"))
    except Exception:  # noqa: BLE001 - 损坏/密钥不匹配一律视为未配置
        return {}
    okx = data.get("okx") if isinstance(data, dict) else None
    return {k: v for k, v in okx.items() if k in OKX_FIELDS} if isinstance(okx, dict) else {}


def save_okx_config(cfg: Dict[str, Any]) -> None:
    """写入 OKX 配置（仅保留白名单字段，原子落盘 0600）。"""
    payload = {k: cfg[k] for k in OKX_FIELDS if cfg.get(k) not in (None, "")}
    if not payload.get("api_key") or not payload.get("secret_key") or not payload.get("passphrase"):
        raise ValueError("OKX 凭据不完整：api_key/secret_key/passphrase 必填")

    aesgcm = _cipher()
    blob = json.dumps({"okx": payload}, ensure_ascii=False).encode("utf-8")
    nonce = secrets.token_bytes(12)
    token = aesgcm(_key()).encrypt(nonce, blob, _AAD)
    encoded = base64.b64encode(nonce + token)

    store = _store_dir()
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o700)
    tmp_path = store / f".{CRED_FILE}.tmp"
    tmp_path.write_bytes(encoded)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, store / CRED_FILE)


def status() -> Dict[str, Any]:
    """脱敏状态，供运维与验收读取。"""
    cfg = load_okx_config()
    return {
        "configured": bool(cfg.get("api_key")),
        "simulated": cfg.get("simulated", True),
        "dry_run": cfg.get("dry_run", True),
        "default_inst_id": cfg.get("default_inst_id", ""),
        "store_dir": str(_store_dir()),
    }


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def import_env_file(path: Path) -> Dict[str, Any]:
    """把 .env 中的 OKX 段迁移进加密库，返回脱敏摘要（不打印明文）。"""
    values = _parse_env_file(path)
    cfg: Dict[str, Any] = {}
    if values.get("OKX_API_KEY"):
        cfg["api_key"] = values["OKX_API_KEY"]
    if values.get("OKX_SECRET_KEY"):
        cfg["secret_key"] = values["OKX_SECRET_KEY"]
    if values.get("OKX_PASSPHRASE"):
        cfg["passphrase"] = values["OKX_PASSPHRASE"]
    if values.get("OKX_BASE_URL"):
        cfg["base_url"] = values["OKX_BASE_URL"]
    if values.get("OKX_SIMULATED"):
        cfg["simulated"] = _as_bool(values["OKX_SIMULATED"])
    if values.get("OKX_DRY_RUN"):
        cfg["dry_run"] = _as_bool(values["OKX_DRY_RUN"])
    if values.get("OKX_DEFAULT_INST_ID"):
        cfg["default_inst_id"] = values["OKX_DEFAULT_INST_ID"]
    if values.get("OKX_TD_MODE"):
        cfg["td_mode"] = values["OKX_TD_MODE"]

    leverage = float(values.get("DEFAULT_LEVERAGE") or 0) or None
    if leverage:
        cfg["default_leverage"] = leverage
    margin = float(values.get("DEFAULT_MARGIN_USDT") or 0)
    if margin and leverage:
        cfg["default_usdt_amount"] = margin * leverage

    save_okx_config(cfg)
    return status()


def main() -> int:
    parser = argparse.ArgumentParser(description="22 域交易所凭据库")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="打印脱敏状态")
    import_parser = sub.add_parser("import-env", help="从 .env 迁移凭据")
    import_parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()

    if args.cmd == "status":
        print(json.dumps(status(), ensure_ascii=False))
        return 0
    if args.cmd == "import-env":
        print(json.dumps(import_env_file(args.file), ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

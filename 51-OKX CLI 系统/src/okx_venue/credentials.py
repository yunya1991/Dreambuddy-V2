"""用户 venue 凭证仓库（AES-256-GCM，落本地独立目录）。

隔离设计：
- 凭证只落在 ``51-OKX CLI 系统/runtime/user_venue/``，不写 ``~/.okx/config.toml``，
  也不进入后端 22 执行链路的任何配置。
- 调用 OKX CLI 时以环境变量注入（``OKX_API_KEY`` / ``OKX_SECRET_KEY`` / ``OKX_PASSPHRASE``），
  仅作用于本次子进程，不污染全局环境。
- 对外只返回脱敏信息（后 4 位），永不回传明文。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .adapter import _first
from .config import _MODULE_ROOT, VenueConfig
from .errors import CredentialsMissing, VenueError
from .runner import CliRunner

USER_VENUE_DIR = _MODULE_ROOT / "runtime" / "user_venue"
CRED_FILE = "credentials.enc"
KEY_FILE = "key"
_AAD = b"dreambuddy-user-venue-v1"
ENV_KEYS = {
    "api_key": "OKX_API_KEY",
    "secret_key": "OKX_SECRET_KEY",
    "passphrase": "OKX_PASSPHRASE",
}
MIN_FIELD_LEN = 8


class CredentialError(VenueError):
    code = "venue_credentials_invalid"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class UserCredentialStore:
    """Encrypted at-rest store for the product/user venue."""

    def __init__(self, root: Optional[Path] = None, *, clock=time.time) -> None:
        self.root = Path(root or USER_VENUE_DIR)
        self.cred_path = self.root / CRED_FILE
        self.key_path = self.root / KEY_FILE
        self._clock = clock

    # ── crypto ──────────────────────────────────────────────────
    def _key(self) -> bytes:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if len(raw) == 32:
                return raw
        key = secrets.token_bytes(32)
        self.key_path.write_bytes(key)
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def _cipher(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # fail-closed：宁可不存，也不明文落盘
            raise VenueError(
                "cryptography is required to store venue credentials",
                code="venue_config_error",
            ) from exc
        return AESGCM(self._key())

    # ── public API ──────────────────────────────────────────────
    def configured(self) -> bool:
        return self.cred_path.exists()

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.cred_path.exists():
            return None
        blob = json.loads(self.cred_path.read_text(encoding="utf-8"))
        try:
            nonce = base64.b64decode(blob["nonce"])
            ciphertext = base64.b64decode(blob["ciphertext"])
            plain = self._cipher().decrypt(nonce, ciphertext, _AAD)
        except VenueError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VenueError(
                "credential store is corrupted; please re-save credentials",
                code="venue_config_error",
            ) from exc
        return json.loads(plain.decode("utf-8"))

    def save(
        self,
        *,
        api_key: str,
        secret_key: str,
        passphrase: str,
        demo: bool = True,
        label: str = "user",
        permissions: str = "",
    ) -> Dict[str, Any]:
        record = self._validate(api_key, secret_key, passphrase)
        payload = {
            "exchange": "okx",
            "label": (label or "user")[:32],
            "demo": bool(demo),
            "permissions": permissions,
            "saved_at": self._clock(),
            **record,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher().encrypt(nonce, raw, _AAD)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cred_path.write_text(
            json.dumps(
                {"v": 1, "nonce": _b64(nonce), "ciphertext": _b64(ciphertext)}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        try:
            self.cred_path.chmod(0o600)
        except OSError:
            pass
        return self.public(payload)

    def delete(self) -> None:
        if self.cred_path.exists():
            self.cred_path.unlink()

    def public(self, record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = record if record is not None else self.load()
        if not record:
            return {"configured": False}
        api_key = str(record.get("api_key", ""))
        masked = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
        return {
            "configured": True,
            "exchange": record.get("exchange", "okx"),
            "label": record.get("label", "user"),
            "demo": bool(record.get("demo", True)),
            "api_key_hint": masked,
            "permissions": record.get("permissions", ""),
            "saved_at": record.get("saved_at"),
        }

    def env_for(self, record: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        record = record if record is not None else self.load()
        if not record:
            raise CredentialsMissing("user venue credentials are not configured")
        return {ENV_KEYS[key]: str(record[key]) for key in ENV_KEYS}

    # ── helpers ─────────────────────────────────────────────────
    @staticmethod
    def _validate(api_key: str, secret_key: str, passphrase: str) -> Dict[str, str]:
        values = {
            "api_key": (api_key or "").strip(),
            "secret_key": (secret_key or "").strip(),
            "passphrase": (passphrase or "").strip(),
        }
        for name, value in values.items():
            if len(value) < MIN_FIELD_LEN:
                raise CredentialError(f"{name} must be at least {MIN_FIELD_LEN} characters")
            if any(ch.isspace() for ch in value):
                raise CredentialError(f"{name} must not contain whitespace")
        return values


def probe_permissions(
    env_credentials: Dict[str, str],
    *,
    demo: bool,
    audit_path: Path,
) -> str:
    """用一组凭证调用 `account config`，返回 perm 字符串（read_only,trade,withdraw...）。"""
    config = VenueConfig(
        profile="user",
        mode="demo" if demo else "live",
        credential_source="env",
        env_credentials=env_credentials,
        allow_live_read=not demo,
        audit_path=audit_path,
    )
    payload = CliRunner(config).run(["account", "config"], operation="probe_permissions")
    return str(_first(payload).get("perm") or "")


def assert_no_withdraw(perm: str) -> None:
    normalized = (perm or "").lower()
    if "withdraw" in normalized:
        raise CredentialError(
            "该 API Key 具备提现权限，已拒绝保存；请重新创建仅含 读取+交易 权限的 Key",
        )


def build_env_credentials(record: Dict[str, Any]) -> Dict[str, str]:
    return {ENV_KEYS[key]: str(record[key]) for key in ENV_KEYS}


def env_credential_paths(root: Optional[Path] = None) -> Dict[str, str]:
    base = Path(root or USER_VENUE_DIR)
    return {"dir": str(base), "credential_file": str(base / CRED_FILE)}

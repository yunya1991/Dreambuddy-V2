"""CogSteward 本地存储层。

只使用标准库：sqlite3 / json / hashlib / pathlib / secrets / re。
状态位于用户工作区 `.cm/`，默认不保存文档正文。
"""

from __future__ import annotations

import re
import secrets
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
CM_DIR = ".cm"
CONFIG_FILE = "config.yaml"
DB_FILE = "index.db"
BACKUP_DIR = "backup"

# 退出码（供 CLI 与调用方判定）
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_INIT = 3
EXIT_DB = 4
EXIT_IO = 5

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT,
    doc_type TEXT,
    module TEXT,
    tags TEXT,
    sha256 TEXT,
    size INTEGER,
    mtime REAL,
    indexed_at REAL,
    status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    name TEXT,
    path TEXT UNIQUE NOT NULL,
    version TEXT,
    triggers_json TEXT,
    depends_on_json TEXT,
    provides_json TEXT,
    sha256 TEXT,
    indexed_at REAL,
    status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY,
    intent_signature TEXT NOT NULL,
    executed_at REAL NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_sig ON executions(intent_signature, executed_at);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    intent_signature TEXT,
    route TEXT,
    confidence REAL,
    outcome TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS intent_confirms (
    intent_signature TEXT PRIMARY KEY,
    confirmed_at REAL,
    expires_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    content_ref TEXT,
    created_at REAL,
    expires_at REAL,
    triaged_at REAL
);
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY,
    kind TEXT,
    payload_ref TEXT,
    created_at REAL,
    review_count INTEGER DEFAULT 0,
    state TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS apply_runs (
    run_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at REAL,
    mode TEXT,
    files_json TEXT,
    manifest_ref TEXT,
    rolled_back_at REAL
);
"""


class CmError(Exception):
    """带退出码的可读错误。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NotInitialized(CmError):
    def __init__(self, root):
        super().__init__(
            EXIT_NOT_INIT,
            "工作区尚未初始化：{}（请先执行 cm init）".format(root),
        )


def cm_dir(root) -> Path:
    return Path(root) / CM_DIR


def config_path(root) -> Path:
    return cm_dir(root) / CONFIG_FILE


def db_path(root) -> Path:
    return cm_dir(root) / DB_FILE


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_scalar(value: str):
    raw = value.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(item.strip()) for item in inner.split(",") if item.strip()]
    lowered = raw.lower()
    if lowered in ("true", "on", "yes"):
        return True
    if lowered in ("false", "off", "no"):
        return False
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return _strip_quotes(raw)


def parse_flat_yaml(text: str) -> dict:
    """解析扁平 key: value 子集，避免引入 PyYAML。

    支持注释、引号字符串、布尔、整数/浮点、内联列表 [a, b]。
    """
    result = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if " #" in value and not value.startswith(("'", '"')):
            value = value.split(" #", 1)[0].strip()
        if key:
            result[key] = _parse_scalar(value)
    return result


def format_flat_yaml(data: dict) -> str:
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            rendered = "[" + ", ".join(str(item) for item in value) + "]"
        else:
            rendered = str(value)
        lines.append("{}: {}".format(key, rendered))
    return "\n".join(lines) + "\n"


def load_mode(mode: str) -> dict:
    path = PACKAGE_ROOT / "scripts" / "modes" / "{}.yaml".format(mode)
    if path.exists():
        return parse_flat_yaml(path.read_text(encoding="utf-8"))
    return {"mode": mode}


def default_config(mode: str = "dev") -> dict:
    mode_cfg = load_mode(mode)
    return {
        "mode": mode_cfg.get("mode", mode),
        "apply": False,
        "signature_salt": secrets.token_hex(16),
        "high_threshold": float(mode_cfg.get("high_threshold", 0.80)),
        "low_threshold": float(mode_cfg.get("low_threshold", 0.50)),
        "session_ttl_days": int(mode_cfg.get("session_ttl_days", 7)),
        "materialize": mode_cfg.get("materialize", "stub"),
        "max_attachments": int(mode_cfg.get("max_attachments", 3)),
        "max_text_bytes": 10 * 1024 * 1024,
        "traces_summary": False,
        "weight_evidence": float(mode_cfg.get("weight_evidence", 0.35)),
        "weight_consistency": float(mode_cfg.get("weight_consistency", 0.30)),
        "weight_history": float(mode_cfg.get("weight_history", 0.20)),
        "weight_conflict": float(mode_cfg.get("weight_conflict", 0.15)),
        "confirm_ttl_days": 90,
        "ignore": [
            ".git",
            "node_modules",
            "__pycache__",
            ".cm",
            ".venv",
            ".idea",
            ".vscode",
            ".trae",
            "dist",
            "build",
        ],
    }


def write_config(root, config: dict) -> Path:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# CogSteward 工作区配置（由 cm init 生成，可手工修改）\n" + format_flat_yaml(config),
        encoding="utf-8",
    )
    return path


def load_config(root) -> dict:
    path = config_path(root)
    if not path.exists():
        raise NotInitialized(root)
    config = default_config("dev")
    config.update(parse_flat_yaml(path.read_text(encoding="utf-8")))
    return config


def _connect_raw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect(root) -> sqlite3.Connection:
    path = db_path(root)
    if not path.exists():
        raise NotInitialized(root)
    try:
        conn = _connect_raw(path)
        conn.execute("SELECT COUNT(*) FROM docs").fetchone()
        ensure_schema(conn)
        return conn
    except sqlite3.DatabaseError as exc:
        raise CmError(EXIT_DB, "索引数据库不可用：{}".format(exc)) from exc


def ensure_schema(conn: sqlite3.Connection) -> None:
    """幂等补齐表结构，旧工作区无需重新 init。"""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row and str(row["value"]).isdigit() and int(row["value"]) >= SCHEMA_VERSION:
        return
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def update_config(root, updates: dict) -> dict:
    """更新工作区 config.yaml 的指定键并返回完整配置。"""
    config = load_config(root)
    for key, value in updates.items():
        config[key] = value
    write_config(root, config)
    return config


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(path, title, tokenize='unicode61')"
        )
        return True
    except sqlite3.DatabaseError:
        return False


def init_workspace(root, mode: str = "dev", force: bool = False) -> dict:
    root = Path(root).expanduser().resolve()
    base = cm_dir(root)
    for sub in ("traces", BACKUP_DIR, "cache"):
        (base / sub).mkdir(parents=True, exist_ok=True)

    config_file = config_path(root)
    if config_file.exists() and not force:
        config = load_config(root)
        status = "existing"
    else:
        config = default_config(mode)
        write_config(root, config)
        status = "created"

    try:
        conn = _connect_raw(db_path(root))
        try:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            fts_ok = _ensure_fts(conn)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise CmError(EXIT_DB, "无法初始化索引数据库：{}".format(exc)) from exc

    return {
        "workspace": str(root),
        "cm_dir": str(base),
        "mode": config.get("mode", mode),
        "status": status,
        "fts": fts_ok,
        "schema_version": SCHEMA_VERSION,
    }

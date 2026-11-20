"""文件扫描、分类与登记。

分类规则（SPEC §4）：
- 文本白名单：抽取标题、登记全文哈希，链接入 edges
- 二进制 / 超大文件 / 未知扩展名：只登记路径、大小、哈希，不读正文
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote

from . import store

TEXT_EXTS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sql",
    ".xml",
    ".csv",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".rb",
    ".php",
    ".lua",
    ".vue",
    ".svg",
    ".tex",
    ".bat",
    ".ps1",
    ".dockerfile",
    ".makefile",
    ".gitignore",
}

BINARY_EXTS = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".ico": "image",
    ".tiff": "image",
    ".xlsx": "sheet",
    ".xls": "sheet",
    ".csvx": "sheet",
    ".docx": "doc",
    ".doc": "doc",
    ".pptx": "slide",
    ".ppt": "slide",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".7z": "archive",
    ".rar": "archive",
    ".mp4": "media",
    ".mov": "media",
    ".mp3": "media",
    ".wav": "media",
    ".db": "data",
    ".sqlite": "data",
    ".npy": "data",
    ".parquet": "data",
}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "ftp://", "data:", "javascript:")
LINK_DOC_EXT = {".md", ".markdown", ".mdx"}

DOC_TYPE_BY_EXT = {
    ".md": "doc",
    ".markdown": "doc",
    ".txt": "note",
    ".rst": "doc",
    ".yaml": "config",
    ".yml": "config",
    ".json": "config",
    ".jsonl": "config",
    ".toml": "config",
    ".ini": "config",
    ".cfg": "config",
    ".conf": "config",
    ".py": "code",
    ".sh": "code",
    ".js": "code",
    ".ts": "code",
    ".tsx": "code",
    ".jsx": "code",
    ".rs": "code",
    ".go": "code",
    ".java": "code",
}


class ScanError(store.CmError):
    def __init__(self, message):
        super().__init__(store.EXIT_IO, message)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name.lower() in (".gitignore", ".dockerfile", "makefile", "dockerfile"):
        return "text"
    return "text" if suffix in TEXT_EXTS else "binary"


def doc_type_of(path: Path, kind: str) -> str:
    suffix = path.suffix.lower()
    if kind == "binary":
        return BINARY_EXTS.get(suffix, "binary")
    name = path.name.lower()
    if name in ("index.md", "readme.md") and suffix == ".md":
        return "index" if name == "index.md" else "readme"
    if "spec" in name and suffix == ".md":
        return "spec"
    if "adr" in name and suffix == ".md":
        return "adr"
    return DOC_TYPE_BY_EXT.get(suffix, "other")


def module_of(rel_path: str) -> str:
    parts = rel_path.split("/")
    return parts[0] if len(parts) > 1 else ""


def title_of(path: Path, text: str = "") -> str:
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:200]
    return path.stem[:200]


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return store.parse_flat_yaml(text[3:end])


def _strip_code_fences(text: str) -> str:
    """去掉围栏代码块内容，避免把代码里的 x[i](arg) 误判为 Markdown 链接。"""
    out = []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        token = stripped[:3]
        if token in ("```", "~~~"):
            if fence is None:
                fence = token
                out.append("")
                continue
            if token == fence:
                fence = None
                out.append("")
                continue
        out.append("" if fence else line)
    return "\n".join(out)


def extract_links(text: str):
    return [match.group(1) for match in LINK_RE.finditer(_strip_code_fences(text))]


def resolve_link(src_rel: str, target: str, root=None):
    raw = target.strip()
    if not raw or raw.startswith("#"):
        return None
    lowered = raw.lower()
    if lowered.startswith("file://"):
        # file:///abs/path 与工作区内的绝对路径，统一换算为工作区相对路径
        raw = unquote(raw[7:]).split("#", 1)[0].split("?", 1)[0]
        if raw.startswith("/") and root is not None:
            try:
                relative = os.path.relpath(raw, str(root))
            except ValueError:
                return None
            if relative == ".." or relative.startswith("../"):
                return None
            return posixpath.normpath(relative.replace(os.sep, "/"))
        return None
    if lowered.startswith(SKIP_SCHEMES):
        return None
    if raw.startswith("/"):
        if root is None:
            return None
        try:
            relative = os.path.relpath(unquote(raw).split("#", 1)[0].split("?", 1)[0], str(root))
        except ValueError:
            return None
        if relative == ".." or relative.startswith("../"):
            return None
        return posixpath.normpath(relative.replace(os.sep, "/"))
    cleaned = raw.split("#", 1)[0].split("?", 1)[0]
    if not cleaned:
        return None
    cleaned = unquote(cleaned)
    base = posixpath.dirname(src_rel)
    resolved = posixpath.normpath(posixpath.join(base, cleaned))
    if resolved == ".." or resolved.startswith("../"):
        return None
    return resolved


def iter_files(root: Path, ignore):
    ignore_set = {str(item).lower() for item in ignore}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name.lower() not in ignore_set and not name.startswith(".cm")
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            # 运行日志持续追加，索引后必然漂移，直接跳过。
            if name.lower().endswith(".log"):
                continue
            yield path


def _upsert_doc(
    conn,
    rel_path: str,
    *,
    title: str,
    doc_type: str,
    module: str,
    sha256: str,
    size: int,
    mtime: float,
    now: float,
):
    conn.execute(
        """
        INSERT INTO docs(path, title, doc_type, module, tags, sha256, size, mtime, indexed_at, status)
        VALUES(?, ?, ?, ?, '[]', ?, ?, ?, ?, 'active')
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title, doc_type=excluded.doc_type, module=excluded.module,
            sha256=excluded.sha256, size=excluded.size, mtime=excluded.mtime,
            indexed_at=excluded.indexed_at, status='active'
        """,
        (rel_path, title, doc_type, module, sha256, size, mtime, now),
    )
    try:
        conn.execute("DELETE FROM docs_fts WHERE path=?", (rel_path,))
        conn.execute("INSERT INTO docs_fts(path, title) VALUES(?, ?)", (rel_path, title))
    except sqlite3.OperationalError:
        pass  # FTS5 不可用时自动降级，不影响核心登记


def _upsert_skill(
    conn, rel_path: str, *, name: str, version: str, triggers, sha256: str, now: float
):
    conn.execute(
        """
        INSERT INTO skills(name, path, version, triggers_json, depends_on_json, provides_json,
                           sha256, indexed_at, status)
        VALUES(?, ?, ?, ?, '[]', '[]', ?, ?, 'active')
        ON CONFLICT(path) DO UPDATE SET
            name=excluded.name, version=excluded.version, triggers_json=excluded.triggers_json,
            sha256=excluded.sha256, indexed_at=excluded.indexed_at, status='active'
        """,
        (name, rel_path, version, json.dumps(triggers, ensure_ascii=False), sha256, now),
    )


def _replace_links(conn, rel_path: str, text: str, root, now: float):
    """重建单个文档的引用边；SKILL.md 与普通文档同样参与链接检查。"""
    conn.execute("DELETE FROM edges WHERE src=? AND kind='references'", (rel_path,))
    if not rel_path.lower().endswith(tuple(LINK_DOC_EXT)):
        return
    seen = set()
    for target in extract_links(text):
        resolved = resolve_link(rel_path, target, root)
        if resolved and resolved not in seen:
            seen.add(resolved)
            conn.execute(
                "INSERT INTO edges(src, dst, kind, created_at) VALUES(?, ?, 'references', ?)",
                (rel_path, resolved, now),
            )


def scan(root, config: dict, conn, full: bool = False) -> dict:
    root = Path(root).expanduser().resolve()
    started = time.perf_counter()
    ignore = config.get("ignore") or []
    max_text = int(config.get("max_text_bytes") or 10 * 1024 * 1024)

    existing_docs = {row["path"]: row for row in conn.execute("SELECT path, size, mtime FROM docs")}
    existing_skills = {row["path"]: row for row in conn.execute("SELECT path FROM skills")}
    seen_docs, seen_skills = set(), set()

    stats = {
        "scanned": 0,
        "text": 0,
        "binary": 0,
        "skills": 0,
        "unchanged": 0,
        "errors": 0,
        "bytes": 0,
    }
    now = time.time()
    if full:
        # 全量重建时清空引用边，避免已删除/已改名文档的旧边残留。
        conn.execute("DELETE FROM edges WHERE kind='references'")

    for path in iter_files(root, ignore):
        rel_path = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except OSError:
            stats["errors"] += 1
            continue

        is_skill = path.name.lower() == "skill.md"
        if is_skill:
            if rel_path in existing_skills and not full:
                seen_skills.add(rel_path)
                stats["unchanged"] += 1
                continue
        else:
            previous = existing_docs.get(rel_path)
            if previous and not full and previous["size"] == stat.st_size:
                seen_docs.add(rel_path)
                stats["unchanged"] += 1
                continue

        try:
            digest = sha256_file(path)
        except OSError:
            stats["errors"] += 1
            continue

        stats["scanned"] += 1
        stats["bytes"] += stat.st_size
        kind = classify(path) if stat.st_size <= max_text else "binary"

        if is_skill:
            seen_skills.add(rel_path)
            text = ""
            if kind == "text":
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")[:max_text]
                except OSError:
                    text = ""
            meta = parse_frontmatter(text)
            triggers = meta.get("triggers") or []
            if isinstance(triggers, str):
                triggers = [item.strip() for item in re.split(r"[,，]", triggers) if item.strip()]
            _upsert_skill(
                conn,
                rel_path,
                name=str(meta.get("name") or path.parent.name),
                version=str(meta.get("version") or ""),
                triggers=triggers,
                sha256=digest,
                now=now,
            )
            stats["skills"] += 1
            continue

        seen_docs.add(rel_path)
        stats[kind] += 1

        if kind == "text":
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:max_text]
            except OSError:
                text = ""
            _upsert_doc(
                conn,
                rel_path,
                title=title_of(path, text),
                doc_type=doc_type_of(path, kind),
                module=module_of(rel_path),
                sha256=digest,
                size=stat.st_size,
                mtime=stat.st_mtime,
                now=now,
            )
            _replace_links(conn, rel_path, text, root, now)
        else:
            _upsert_doc(
                conn,
                rel_path,
                title=path.stem[:200],
                doc_type=doc_type_of(path, kind),
                module=module_of(rel_path),
                sha256=digest,
                size=stat.st_size,
                mtime=stat.st_mtime,
                now=now,
            )

    missing_docs = [path for path in existing_docs if path not in seen_docs]
    for rel_path in missing_docs:
        conn.execute("UPDATE docs SET status='orphan' WHERE path=?", (rel_path,))
    for rel_path in existing_skills:
        if rel_path not in seen_skills:
            conn.execute("UPDATE skills SET status='orphan' WHERE path=?", (rel_path,))

    conn.commit()
    stats["missing"] = len(missing_docs)
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return stats

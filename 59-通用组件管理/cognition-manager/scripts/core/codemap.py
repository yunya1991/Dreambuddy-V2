"""代码-文档对应检查（v0.6）：行号越界 / 无文档代码 / 文档漂移。

只读：不写数据库、不改文件。供 `cm map` 与 `cm doctor` 复用。
"""

import os
import re
from pathlib import Path
from posixpath import dirname, join, normpath

CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh"}
ANCHOR_RE = re.compile(r"\]\(([^)\s]*?)#L(\d+)(?:-L?(\d+))?\)")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _ignored(name, ignore):
    return name.lower() in ignore or name.startswith(".cm")


def walk(root, ignore, suffixes=None):
    root = Path(root)
    ignored = {str(x).lower() for x in ignore}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not _ignored(d, ignored)]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            yield path.relative_to(root).as_posix()


def _line_count(path):
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def analyze(root, config, conn):
    root = Path(root)
    ignore = config.get("ignore") or []

    anchors = []
    seen_anchor = set()
    docs = list(walk(root, ignore, {".md", ".markdown", ".mdx"}))
    for rel in docs:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in ANCHOR_RE.finditer(text):
            target, start, end = (
                match.group(1),
                int(match.group(2)),
                int(match.group(3) or match.group(2)),
            )
            resolved = normpath(join(dirname(rel), target)) if target else rel
            full = root / resolved
            if not full.exists():
                continue  # 文件缺失由断链检查负责
            total = _line_count(full)
            if start < 1 or end < start or end > total:
                key = (rel, resolved, start, end)
                if key in seen_anchor:
                    continue
                seen_anchor.add(key)
                anchors.append(
                    {
                        "doc": rel,
                        "target": target,
                        "lines": [start, end],
                        "file_lines": total,
                    }
                )

    referenced = set()
    for (dst,) in conn.execute("SELECT DISTINCT dst FROM edges WHERE kind='references'"):
        referenced.add(dst)

    module_docs = set()
    code_files = list(walk(root, ignore, CODE_EXT))
    for rel in code_files:
        module_docs.add(dirname(rel))
    documented_modules = {
        d
        for d in module_docs
        if (root / d / "INDEX.md").exists() or (root / d / "SKILL.md").exists()
    }

    text_cache = {}

    def module_text(doc_dir: str) -> str:
        if doc_dir not in text_cache:
            parts = []
            for name in ("SKILL.md", "INDEX.md", "README.md"):
                doc = root / doc_dir / name
                if doc.exists():
                    try:
                        parts.append(doc.read_text(encoding="utf-8", errors="ignore"))
                    except OSError:
                        pass
            text_cache[doc_dir] = "\n".join(parts)
        return text_cache[doc_dir]

    gaps = []
    for rel in code_files:
        module = dirname(rel)
        if module not in documented_modules or rel in referenced:
            continue
        # 同目录文档里点名（如脚本表）也算已文档化，不强制写成链接。
        if os.path.basename(rel) in module_text(module):
            continue
        gaps.append(rel)

    drift = []
    seen_drift = set()
    rows = conn.execute(
        "SELECT e.src, e.dst, d.mtime FROM edges e LEFT JOIN docs d ON d.path = e.src WHERE e.kind='references'"
    ).fetchall()
    skip_doc_names = {"changelog.md", "index.md", "engineering_index.md"}
    for src, dst, src_mtime in rows:
        if os.path.basename(src).lower() in skip_doc_names:
            continue  # 索引/变更记录天然高频更新，不纳入漂移
        if (src, dst) in seen_drift:
            continue
        full = root / dst
        if not full.exists():
            continue
        try:
            dst_mtime = full.stat().st_mtime
        except OSError:
            continue
        if src_mtime and dst_mtime - float(src_mtime) >= 3 * 86400:
            seen_drift.add((src, dst))
            drift.append(
                {
                    "doc": src,
                    "target": dst,
                    "doc_age_days": round((dst_mtime - float(src_mtime)) / 86400, 1),
                }
            )

    return {
        "metrics": {
            "anchor_out_of_range": len(anchors),
            "code_without_doc": len(gaps),
            "doc_drift": len(drift),
        },
        "details": {
            "anchor_out_of_range": anchors[:20],
            "code_without_doc": gaps[:20],
            "doc_drift": drift[:20],
        },
    }


def format_map(result, gaps_only=False):
    metrics = result["metrics"]
    lines = [
        "认知管家 · 代码-文档对应",
        "行号越界    {}".format(metrics["anchor_out_of_range"]),
        "无文档代码  {}".format(metrics["code_without_doc"]),
        "文档漂移    {}".format(metrics["doc_drift"]),
    ]
    for key, title in (
        ("anchor_out_of_range", "行号越界"),
        ("code_without_doc", "无文档代码"),
        ("doc_drift", "文档漂移"),
    ):
        items = result["details"].get(key) or []
        if not items:
            continue
        lines.append("")
        lines.append("· " + title)
        for item in items[:5]:
            if key == "code_without_doc":
                lines.append("  - " + item)
            elif key == "doc_drift":
                lines.append(
                    "  - {} → {}（文件比文档新 {} 天）".format(
                        item["doc"], item["target"], item["doc_age_days"]
                    )
                )
            else:
                lines.append(
                    "  - {} → {} 引用 L{}-L{}，文件仅 {} 行".format(
                        item["doc"],
                        item["target"],
                        item["lines"][0],
                        item["lines"][1],
                        item["file_lines"],
                    )
                )
    return "\n".join(lines)

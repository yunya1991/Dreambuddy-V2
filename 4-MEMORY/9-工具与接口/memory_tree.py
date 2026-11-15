#!/usr/bin/env python3
"""记忆树 memory_tree.py — 长期记忆的定位索引（三级：项目 / 目录 / 章节）。

设计口径见 [SPEC-ResidualMemory-Admission §3.6](../../35-广义认知系统协作模块/SPEC-ResidualMemory-Admission.md)：
  - 节点只存「关键词 + 位置指针」，**禁止**存细节内容（指针型记忆）。
  - 节点由现有索引自动生成（目录树 + 文档锚点），人工只维护 ≤150 个高频根节点。
  - 同一节点两种展开：`doc_anchors`（有文档看文档）/ `module_paths`（没文档直接 REA 解析）。

求解级联中的位置：
  D1 关键词命中树节点 → 读 doc_anchor 或调 REA 解析 module_path
  D2 上下文邻近（同项目 / 同目录兄弟）扩展，沿树遍历
  D3 / D4 成功后 **必须** 回写（upsert），否则下次无法 D1 命中

CLI:
  python3 memory_tree.py build [--repo .] [--include-unnumbered]
  python3 memory_tree.py query "数据获取 新闻快讯" [--top-k 5]
  python3 memory_tree.py walk "18-数据获取中心/backfill" [--depth 1]
  python3 memory_tree.py upsert --path "..." --keyword "..." --doc-anchor "..." --module-path "..."
  python3 memory_tree.py stats

树遍历是**确定性检索**（关键词子串匹配，可解释、可复现、无误召回），不使用向量。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TREE = Path(__file__).resolve().parents[1] / "data" / "memory_tree.json"
DEFAULT_PINS = Path(__file__).resolve().parents[1] / "data" / "memory_tree_pins.json"

PIN_BUDGET = 150  # 人工维护的高频根节点上限（硬门禁）
NOTE_LIMIT = 120  # 回写摘要上限：指针化，非细节
MAX_MD_PER_DIR = 60  # 单目录最多收录章节数，防止异常目录炸树

_NUM_RE = re.compile(r"^\d+(\.\d+)*[-_]")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.]*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
_HEADING_NOISE_RE = re.compile(r"[`*_#>\[\]()|]")
_CJK_CONNECTOR_RE = re.compile(r"[与和及、/]")
_SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "archive",
    "data",
    "logs",
    "artifacts",
    "_visual",
    ".pytest_cache",
    ".mypy_cache",
}
# 目录节点上优先作为「细节入口」的文档（不进章节层，避免 README 噪音）
_DOC_ENTRY_NAMES = (
    "README.md",
    "INDEX.md",
    "ENGINEERING_INDEX.md",
    "TECHNICAL_DESIGN.md",
    "API_SPEC.md",
    "SPEC.md",
    "SYSTEM_ARCHITECTURE_OVERVIEW.md",
)
# 中文尾缀剥离：让「数据获取中心」也能被「数据获取」命中
_CJK_SUFFIXES = (
    "系统层",
    "系统",
    "模块",
    "中心",
    "工程",
    "文档",
    "索引",
    "说明",
    "规范",
    "架构",
    "协议",
    "脚本",
    "工具",
    "服务",
    "层",
    "表",
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def tokenize(text: str) -> List[str]:
    """确定性分词：拉丁词 + 数字 + 中文连续段（含尾缀剥离），去重排序。"""
    tokens: set[str] = set()
    for m in _LATIN_RE.finditer(text or ""):
        tok = m.group(0).lower().strip(".-")
        if len(tok) >= 2 and not tok.isdigit():
            tokens.add(tok)
    for m in _CJK_RE.finditer(text or ""):
        run = m.group(0)
        if len(run) >= 2:
            tokens.add(run)
        # 连接词切分：「记忆树与求解级联」→ 记忆树 / 求解级联（提升 D1 精确命中）
        if len(run) >= 4:
            for part in _CJK_CONNECTOR_RE.split(run):
                if len(part) >= 2:
                    tokens.add(part)
        core = run
        for suf in _CJK_SUFFIXES:
            if core.endswith(suf) and len(core) > len(suf) + 1:
                core = core[: -len(suf)]
                break
        if core != run and len(core) >= 2:
            tokens.add(core)
    return sorted(tokens)


def _rel(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def heading_keywords(file: Path, max_headings: int = 30) -> List[str]:
    """从文档标题（# / ## / ###）提取关键词——只取标题，**不读正文**，保持指针化。

    章节节点若只用文件名，D1 的中文问题几乎必然落空（如 SPEC-ResidualMemory-Admission
    的文件名不含「记忆树」）。标题是结构信息，不是细节内容，符合 §3.6「节点只存关键词」。
    """
    try:
        text = file.read_text(encoding="utf-8", errors="ignore")[:20000]
    except OSError:
        return []
    tokens: set[str] = set()
    for heading in _HEADING_RE.findall(text)[:max_headings]:
        tokens.update(tokenize(_HEADING_NOISE_RE.sub(" ", heading)))
    return sorted(t for t in tokens if len(t) >= 2 and not t.isdigit())


def _doc_entry_keywords(files: Iterable[Path]) -> List[str]:
    tokens: set[str] = set()
    for f in files:
        tokens.update(heading_keywords(f, max_headings=3))
    return sorted(tokens)


def _is_project_dir(name: str) -> bool:
    return bool(_NUM_RE.match(name))


class MemoryTree:
    """三级记忆树：构建 / 查询 / 遍历 / 回写。"""

    def __init__(
        self,
        nodes: Optional[Dict[str, Dict[str, Any]]] = None,
        pins: Optional[Sequence[str]] = None,
        generated_at: str = "",
        repo: str = "",
    ) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = nodes or {}
        self.pins: List[str] = list(pins or [])
        self.generated_at = generated_at
        self.repo = repo
        self._children: Dict[str, List[str]] = {}
        self._load_err = ""
        self._build_children()

    # ---------------- 构建 ----------------

    @classmethod
    def build(
        cls, repo: Path, pins: Optional[Sequence[str]] = None, include_unnumbered: bool = False
    ) -> "MemoryTree":
        pins = list(pins or [])
        if len(pins) > PIN_BUDGET:
            raise ValueError(f"人工根节点 {len(pins)} 超过上限 {PIN_BUDGET}，请先抽象合并")
        nodes: Dict[str, Dict[str, Any]] = {}

        def add(
            path: str,
            level: int,
            parent: Optional[str],
            name: str,
            doc_anchors: Iterable[str] = (),
            module_paths: Iterable[str] = (),
            extra_keywords: Iterable[str] = (),
            origin: str = "auto",
        ) -> None:
            nodes[path] = {
                "level": level,
                "name": name,
                "parent": parent,
                "keywords": sorted(set(tokenize(name)) | {str(k) for k in extra_keywords if k}),
                "doc_anchors": sorted({a for a in doc_anchors if a}),
                "module_paths": sorted({m for m in module_paths if m}),
                "origin": origin,
            }

        for proj in sorted(p for p in repo.iterdir() if p.is_dir()):
            if proj.name.startswith(".") or proj.name in _SKIP_DIRS:
                continue
            if not (include_unnumbered or _is_project_dir(proj.name)):
                continue
            prel = _rel(proj, repo)
            proj_doc_files = [proj / n for n in _DOC_ENTRY_NAMES if (proj / n).is_file()]
            add(
                prel,
                1,
                None,
                proj.name,
                doc_anchors=[_rel(f, repo) for f in proj_doc_files],
                module_paths=[prel],
                extra_keywords=_doc_entry_keywords(proj_doc_files),
                origin="manual" if proj.name in pins else "auto",
            )

            # 项目根层的章节（直接放在项目目录下的 md，README/INDEX 已作锚点不重复）
            for md in sorted(proj.glob("*.md"))[:MAX_MD_PER_DIR]:
                if md.name in _DOC_ENTRY_NAMES:
                    continue
                add(
                    _rel(md, repo),
                    3,
                    prel,
                    md.stem,
                    doc_anchors=[_rel(md, repo)],
                    extra_keywords=heading_keywords(md),
                )

            for sub in sorted(p for p in proj.iterdir() if p.is_dir()):
                if sub.name.startswith(".") or sub.name in _SKIP_DIRS:
                    continue
                srel = _rel(sub, repo)
                sub_doc_files = [sub / n for n in _DOC_ENTRY_NAMES if (sub / n).is_file()]
                add(
                    srel,
                    2,
                    prel,
                    sub.name,
                    doc_anchors=[_rel(f, repo) for f in sub_doc_files],
                    module_paths=[srel],
                    extra_keywords=_doc_entry_keywords(sub_doc_files),
                )
                mds = [m for m in sorted(sub.glob("*.md")) if m.name not in _DOC_ENTRY_NAMES]
                for md in mds[:MAX_MD_PER_DIR]:
                    add(
                        _rel(md, repo),
                        3,
                        srel,
                        md.stem,
                        doc_anchors=[_rel(md, repo)],
                        extra_keywords=heading_keywords(md),
                    )

        tree = cls(nodes, pins, generated_at=_now(), repo=str(repo))
        return tree

    def _build_children(self) -> None:
        self._children = {}
        for path, node in self.nodes.items():
            parent = node.get("parent")
            if parent:
                self._children.setdefault(parent, []).append(path)
        for kids in self._children.values():
            kids.sort()

    # ---------------- 持久化 ----------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "generated_at": self.generated_at or _now(),
            "repo": self.repo,
            "pin_budget": PIN_BUDGET,
            "pins": self.pins,
            "stats": {**self.stats(), "generated_at": self.generated_at or _now()},
            "nodes": self.nodes,
        }

    def save(self, path: Path = DEFAULT_TREE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path = DEFAULT_TREE) -> "MemoryTree":
        if not path.exists():
            tree = cls()
            tree._load_err = f"tree_missing: {path}"
            return tree
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            tree = cls()
            tree._load_err = f"tree_unreadable: {type(exc).__name__}"
            return tree
        return cls(
            data.get("nodes") or {},
            data.get("pins") or [],
            data.get("generated_at", ""),
            data.get("repo", ""),
        )

    # ---------------- 查询（D1）----------------

    def children(self, path: str) -> List[str]:
        return list(self._children.get(path, []))

    def ancestors(self, path: str) -> List[str]:
        chain: List[str] = []
        cur = self.nodes.get(path, {}).get("parent")
        while cur and cur in self.nodes:
            chain.append(cur)
            cur = self.nodes[cur].get("parent")
        return list(reversed(chain))

    @staticmethod
    def _score(node: Dict[str, Any], query_tokens: List[str]) -> float:
        score = 0.0
        kws = [str(k).lower() for k in node.get("keywords", [])]
        path = str(node.get("name", "")).lower()
        for q in query_tokens:
            for kw in kws:
                if q == kw:
                    score += 3.0
                elif len(q) >= 2 and q in kw:
                    score += 2.0
                elif len(kw) >= 2 and kw in q:
                    score += 1.5
            if len(q) >= 2 and q in path:
                score += 1.0
        return score

    def query(self, text: str, top_k: int = 5, min_score: float = 1.5) -> List[Dict[str, Any]]:
        """D1：关键词确定性命中。无命中返回空列表（调用方应转 D3 REA，而非向量兜底）。"""
        tokens = tokenize(text)
        if not tokens:
            return []
        scored: List[Tuple[float, str]] = []
        for path, node in self.nodes.items():
            s = self._score(node, tokens)
            if s >= min_score:
                scored.append((s, path))
        scored.sort(key=lambda item: (-item[0], self.nodes[item[1]]["level"], item[1]))
        out: List[Dict[str, Any]] = []
        for s, path in scored[: max(1, top_k)]:
            node = self.nodes[path]
            out.append(
                {
                    "path": path,
                    "level": node["level"],
                    "score": round(s, 2),
                    "keywords": node.get("keywords", []),
                    "doc_anchors": node.get("doc_anchors", []),
                    "module_paths": node.get("module_paths", []),
                    "origin": node.get("origin", "auto"),
                    "next": self._next_step(node),
                }
            )
        return out

    @staticmethod
    def _next_step(node: Dict[str, Any]) -> str:
        if node.get("doc_anchors"):
            return "读 doc_anchors 细节；不足再调 REA 解析 module_paths"
        if node.get("module_paths"):
            return "无文档，直接调 REA 逆向解析 module_paths"
        return "叶节点无锚点，向父节点回退或转 D3"

    # ---------------- 遍历（D2）----------------

    def walk(self, path: str, depth: int = 1) -> Dict[str, Any]:
        node = self.nodes.get(path)
        if not node:
            return {
                "ok": False,
                "degraded": True,
                "degraded_reason": "node_not_found",
                "path": path,
            }
        result: Dict[str, Any] = {
            "ok": True,
            "path": path,
            "node": node,
            "ancestors": self.ancestors(path),
            "children": self.children(path)[: max(0, depth) * 50],
        }
        if depth > 1:
            siblings = [p for p in self.children(node.get("parent") or "") if p != path]
            result["siblings"] = siblings[:50]
        return result

    # ---------------- 回写（D3 / D4）----------------

    def upsert(
        self,
        path: str,
        keywords: Iterable[str] = (),
        doc_anchors: Iterable[str] = (),
        module_paths: Iterable[str] = (),
        note: str = "",
        origin: str = "rea",
    ) -> Dict[str, Any]:
        """D3/D4 成功后回写。缺父链自动补齐；落不到任何项目下则挂 `_orphan`。"""
        path = path.strip("/")
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError("path 不能为空")
        if len(note) > NOTE_LIMIT:
            note = note[:NOTE_LIMIT]
        # 补齐父链
        for i in range(1, len(parts) + 1):
            cur = "/".join(parts[:i])
            if cur in self.nodes:
                continue
            parent = "/".join(parts[: i - 1]) or None
            level = min(i, 3)
            self.nodes[cur] = {
                "level": level,
                "name": parts[i - 1],
                "parent": parent,
                "keywords": tokenize(parts[i - 1]),
                "doc_anchors": [],
                "module_paths": [],
                "origin": origin,
            }
        node = self.nodes[path]
        node["keywords"] = sorted(
            set(node.get("keywords", [])) | set(tokenize(" ".join(map(str, keywords))))
        )
        node["doc_anchors"] = sorted(
            set(node.get("doc_anchors", [])) | {str(a) for a in doc_anchors if a}
        )
        node["module_paths"] = sorted(
            set(node.get("module_paths", [])) | {m for m in module_paths if m}
        )
        if note:
            node["note"] = note
        self._build_children()
        return {"ok": True, "path": path, "level": node["level"], "origin": node["origin"]}

    # ---------------- 统计 ----------------

    def stats(self) -> Dict[str, Any]:
        by_level: Dict[int, int] = {1: 0, 2: 0, 3: 0}
        with_anchor = 0
        for node in self.nodes.values():
            by_level[node.get("level", 3)] = by_level.get(node.get("level", 3), 0) + 1
            if node.get("doc_anchors") or node.get("module_paths"):
                with_anchor += 1
        return {
            "nodes": len(self.nodes),
            "projects": by_level[1],
            "dirs": by_level[2],
            "chapters": by_level[3],
            "with_anchor": with_anchor,
            "pins": len(self.pins),
            "pin_budget": PIN_BUDGET,
            "pins_over_budget": len(self.pins) > PIN_BUDGET,
            "degraded": bool(self._load_err),
            "degraded_reason": self._load_err or None,
        }


# ---------------- CLI ----------------


def _load_pins(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("pins", [])
    return [str(x) for x in data if str(x).strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="记忆树（三级：项目/目录/章节）")
    ap.add_argument("--tree", default=str(DEFAULT_TREE))
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="从目录树自动生成并落盘")
    b.add_argument("--repo", default=str(DEFAULT_REPO))
    b.add_argument("--pins", default=str(DEFAULT_PINS))
    b.add_argument("--include-unnumbered", action="store_true")

    q = sub.add_parser("query", help="D1 关键词命中")
    q.add_argument("text")
    q.add_argument("--top-k", type=int, default=5)
    q.add_argument("--min-score", type=float, default=1.5)

    w = sub.add_parser("walk", help="D2 节点遍历")
    w.add_argument("path")
    w.add_argument("--depth", type=int, default=1)

    u = sub.add_parser("upsert", help="D3/D4 回写节点")
    u.add_argument("--path", required=True)
    u.add_argument("--keyword", action="append", default=[])
    u.add_argument("--doc-anchor", action="append", default=[])
    u.add_argument("--module-path", action="append", default=[])
    u.add_argument("--note", default="")
    u.add_argument("--origin", default="rea")

    sub.add_parser("stats", help="统计与降级状态")

    args = ap.parse_args(argv)
    tree_path = Path(args.tree)

    if args.cmd == "build":
        repo = Path(args.repo).resolve()
        pins = _load_pins(Path(args.pins))
        tree = MemoryTree.build(repo, pins, args.include_unnumbered)
        tree.save(tree_path)
        print(
            json.dumps(
                {"ok": True, "tree": str(tree_path), **tree.stats()}, ensure_ascii=False, indent=2
            )
        )
        return 0 if not tree.stats()["pins_over_budget"] else 3

    tree = MemoryTree.load(tree_path)
    if args.cmd == "query":
        hits = tree.query(args.text, args.top_k, args.min_score)
        payload = {
            "ok": True,
            "query": args.text,
            "hit": bool(hits),
            "count": len(hits),
            "results": hits,
        }
        if not hits:
            # 契约 C2b 同款：无命中要显式 degraded，禁止伪装成「查不到就说没有」
            payload.update(
                {
                    "degraded": True,
                    "degraded_reason": "tree_no_hit",
                    "next": "D3 直接 REA 逆向解析，勿向量兜底",
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 4
    if args.cmd == "walk":
        print(json.dumps(tree.walk(args.path, args.depth), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "upsert":
        try:
            res = tree.upsert(
                args.path, args.keyword, args.doc_anchor, args.module_path, args.note, args.origin
            )
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        tree.save(tree_path)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stats":
        print(json.dumps(tree.stats(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

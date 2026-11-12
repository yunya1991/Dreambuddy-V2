"""TS/React 项目级逆向分析器 — 目录级 Evidence-First 分析。

在单文件 TSAnalyzer 之上补齐项目级能力（零重型依赖，纯正则 + 文件系统）：
- App Router / Pages Router 路由提取（页面 + API route + HTTP 方法）
- 本地 import 依赖图（支持 tsconfig paths 别名）+ 环检测 + hub/orphan
- React 组件图 / Hook 清单 / God component（>300 行且含 JSX）
- zustand / redux store 定义与消费关系
- monorepo（packages / apps / workspaces）识别
- 前端架构模式识别（NextAppRouter / FeatureSliced / DesignSystem / Monorepo /
  StateManagement / TRPC / i18n / SSEStreaming / ContainerPresenter）

每条结论都携带 Evidence（provenance + level + confidence + known_gaps）。
FAIL-OPEN：目标无效或无源码时返回 level=unknown 的 Evidence，不抛异常。
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .analyzer_base import AnalyzerBase, AnalyzeResult
from .evidence import Evidence, EvidenceLevel

# ------------------------------------------------------------------
# 常量
# ------------------------------------------------------------------

_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

_SKIP_DIRS = {
    "node_modules",
    ".git",
    ".next",
    ".turbo",
    ".vercel",
    ".cache",
    "dist",
    "build",
    "out",
    "coverage",
    "playwright-report",
    "test-results",
}

_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_CYCLES = 20
_GOD_COMPONENT_LINES = 300
_MAX_HUBS = 10

_TEST_FILE_RE = re.compile(r"(\.(test|spec)\.|__tests__|__mocks__|\.stories\.)")
_SPECIAL_ROUTE_FILES = {
    "page",
    "layout",
    "loading",
    "error",
    "global-error",
    "not-found",
    "template",
    "default",
    "route",
}
_COMPONENT_KINDS_RE = {
    "function": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Z]\w*)\s*\(", re.MULTILINE
    ),
    "arrow": re.compile(
        r"^\s*(?:export\s+)?(?:const|let)\s+([A-Z]\w*)\s*(?::[^=]+)?=\s*"
        r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>",
        re.MULTILINE,
    ),
    "class": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Z]\w*)\s+extends\s+"
        r"(?:React\.)?(?:Pure)?Component",
        re.MULTILINE,
    ),
    "memo": re.compile(
        r"^\s*(?:export\s+)?(?:const|let)\s+([A-Z]\w*)\s*=\s*" r"(?:React\.)?memo\s*\(",
        re.MULTILINE,
    ),
}
_HOOK_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|const|let)\s+(use[A-Z]\w*)", re.MULTILINE
)
_STORE_DEF_RE = re.compile(
    r"(?:export\s+)?const\s+(use[A-Z]\w*Store|use[A-Z]\w*)\s*=\s*"
    r"(?:create|createWithEqualityFn|createStore|createSlice)\s*(?:<[^>]*>)?\s*\("
)
_STORE_USAGE_RE = re.compile(r"\b(use[A-Z]\w*Store|use[A-Z]\w*)\b")
_HTTP_METHOD_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b"
)
_JSX_HINT_RE = re.compile(r"</[A-Za-z]|/>|<>|React\.createElement\s*\(")
_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?"
    r"(?:(\*\s+as\s+\w+)|(\{[^}]*\})|(\w+))?\s*"
    r"(?:,\s*(\{[^}]*\}))?\s*(?:from\s+)?['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?:(\w+)|(\{[^}]*\}))\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*[^'\"\s)]")


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------


@dataclass
class SourceFile:
    """单个 TS/JS 源文件的解析结果。"""

    rel: str
    ext: str
    lines: int
    source: str
    imports: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    stores: list[str] = field(default_factory=list)
    has_jsx: bool = False
    is_test: bool = False
    dynamic_imports: int = 0

    @property
    def is_route_file(self) -> bool:
        name = os.path.splitext(os.path.basename(self.rel))[0]
        return name in _SPECIAL_ROUTE_FILES


class TSProjectAnalyzer(AnalyzerBase):
    """TS/React 项目级分析器。"""

    def __init__(
        self,
        target: str | None = None,
        *,
        include_tests: bool = True,
    ) -> None:
        self.target = target
        self.include_tests = include_tests
        self.files: dict[str, SourceFile] = {}
        self.aliases: list[tuple[str, list[str]]] = []
        self.base_url = "."

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def supported_targets(self) -> list[str]:
        return ["typescript-project", "react-project", "nextjs-project"]

    def analyze(self, target: str | None = None, **kwargs: Any) -> AnalyzeResult:
        root = os.path.abspath(target or self.target or ".")
        if not os.path.isdir(root):
            ev = Evidence(
                result=f"目标不是目录或不存在: {root}",
                level=EvidenceLevel.UNKNOWN,
                provenance={"target": root, "analysis": "ts_project_scan"},
                confidence=0.0,
                known_gaps=["目标路径不存在或不是目录，无法执行项目级分析"],
            )
            return AnalyzeResult(
                target=root,
                summary=f"TS/React 项目分析失败: {root}",
                evidence=[ev],
                raw={"error": "not_a_directory", "target": root},
            )

        self.files = {}
        self.aliases, self.base_url = self._load_tsconfig(root)
        self._collect_files(root)

        if not self.files:
            ev = Evidence(
                result="未找到 TS/JS 源文件",
                level=EvidenceLevel.UNKNOWN,
                provenance={"target": root, "analysis": "ts_project_scan"},
                confidence=0.0,
                known_gaps=["目录中没有 .ts/.tsx/.js/.jsx 源文件（已排除 node_modules/dist 等）"],
            )
            return AnalyzeResult(
                target=root,
                summary=f"TS/React 项目: 0 文件 ({root})",
                evidence=[ev],
                raw={"error": "no_source_files", "target": root},
            )

        graph = self._build_graph(root)
        routes = self._extract_routes()
        components = [{**c, "file": f.rel} for f in self.files.values() for c in f.components]
        hooks = sorted({h for f in self.files.values() for h in f.hooks})
        stores = self._extract_stores()
        store_consumers = self._extract_store_consumers(stores)
        god_components = self._find_god_components()
        monorepo = self._detect_monorepo(root)
        patterns = self._detect_patterns(root, graph, routes, stores, monorepo, components)
        external_deps = self._external_deps()
        stats = self._stats()

        evidence = self._build_evidence(
            root=root,
            graph=graph,
            routes=routes,
            components=components,
            hooks=hooks,
            stores=stores,
            store_consumers=store_consumers,
            god_components=god_components,
            monorepo=monorepo,
            patterns=patterns,
            external_deps=external_deps,
            stats=stats,
        )

        raw: dict[str, Any] = {
            "target": root,
            "stats": stats,
            "aliases": dict(self.aliases),
            "base_url": self.base_url,
            "routes": routes["pages"],
            "api_routes": routes["api"],
            "route_specials": routes["specials"],
            "graph": graph,
            "components": components,
            "hooks": hooks,
            "stores": stores,
            "store_consumers": store_consumers,
            "god_components": god_components,
            "monorepo": monorepo,
            "patterns": patterns,
            "external_deps": external_deps,
        }

        summary = (
            f"TS/React 项目: {stats['files']} 文件 / {stats['lines']} 行 | "
            f"路由 {len(routes['pages'])} 页面 + {len(routes['api'])} API | "
            f"组件 {len(components)} | store {len(stores)} | "
            f"依赖 {len(graph['nodes'])} 节点/{len(graph['edges'])} 边/"
            f"{len(graph['cycles'])} 环 | 模式 {len(patterns)}"
        )
        return AnalyzeResult(target=root, summary=summary, evidence=evidence, raw=raw)

    # ------------------------------------------------------------------
    # 文件收集与解析
    # ------------------------------------------------------------------
    def _collect_files(self, root: str) -> None:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if not name.endswith(_TS_EXTS):
                    continue
                if name.endswith(".d.ts") or ".min." in name:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(full) > _MAX_FILE_BYTES:
                        continue
                    source = open(full, "r", encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                is_test = bool(_TEST_FILE_RE.search(rel))
                if is_test and not self.include_tests:
                    continue
                self.files[rel] = SourceFile(
                    rel=rel,
                    ext=os.path.splitext(name)[1],
                    lines=source.count("\n") + (0 if source.endswith("\n") else 1),
                    source=source,
                    imports=self._parse_imports(source),
                    components=self._parse_components(source),
                    hooks=[m.group(1) for m in _HOOK_RE.finditer(source)],
                    stores=[m.group(1) for m in _STORE_DEF_RE.finditer(source)],
                    has_jsx=bool(_JSX_HINT_RE.search(source)),
                    is_test=is_test,
                    dynamic_imports=len(_DYNAMIC_IMPORT_RE.findall(source)),
                )

    @staticmethod
    def _parse_imports(source: str) -> list[dict[str, Any]]:
        imports: list[dict[str, Any]] = []
        for m in _IMPORT_RE.finditer(source):
            module = m.group(5) or ""
            if not module:
                continue
            names: list[str] = []
            named = m.group(2) or m.group(4) or ""
            if named:
                names = [
                    n.strip().split(" as ")[0].strip()
                    for n in named.strip("{} ").split(",")
                    if n.strip()
                ]
            default_name = m.group(3) or ""
            imports.append(
                {
                    "module": module,
                    "names": names,
                    "default_name": default_name,
                    "is_type_only": "import type" in m.group(0),
                    "line": source[: m.start()].count("\n") + 1,
                }
            )
        for m in _REQUIRE_RE.finditer(source):
            module = m.group(3) or ""
            if not module:
                continue
            named = m.group(2) or ""
            imports.append(
                {
                    "module": module,
                    "names": [
                        n.strip().split(":")[0].strip()
                        for n in named.strip("{} ").split(",")
                        if n.strip()
                    ],
                    "default_name": m.group(1) or "",
                    "is_type_only": False,
                    "line": source[: m.start()].count("\n") + 1,
                }
            )
        return imports

    @staticmethod
    def _parse_components(source: str) -> list[dict[str, Any]]:
        has_jsx = bool(_JSX_HINT_RE.search(source))
        if not has_jsx:
            return []
        found: dict[str, dict[str, Any]] = {}
        for kind, regex in _COMPONENT_KINDS_RE.items():
            for m in regex.finditer(source):
                name = m.group(1)
                found.setdefault(
                    name,
                    {
                        "name": name,
                        "kind": kind,
                        "line": source[: m.start()].count("\n") + 1,
                    },
                )
        return list(found.values())

    # ------------------------------------------------------------------
    # tsconfig 别名
    # ------------------------------------------------------------------
    def _load_tsconfig(self, root: str) -> tuple[list[tuple[str, list[str]]], str]:
        path = os.path.join(root, "tsconfig.json")
        if not os.path.isfile(path):
            return [], "."
        try:
            raw = open(path, "r", encoding="utf-8").read()
        except OSError:
            return [], "."
        text = self._strip_json_comments(raw)
        text = re.sub(r",\s*([}\]])", r"\1", text)  # 容忍尾随逗号
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [], "."
        opts = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
        base_url = opts.get("baseUrl", ".") or "."
        paths = opts.get("paths", {}) or {}
        aliases: list[tuple[str, list[str]]] = []
        if isinstance(paths, dict):
            items = [(str(k), list(v) if isinstance(v, list) else []) for k, v in paths.items()]
            # 精确键优先，其次按前缀长度降序（更具体的别名优先）
            items.sort(key=lambda kv: (("*" not in kv[0]), -len(kv[0])))
            aliases = [(k, [str(t) for t in v]) for k, v in items]
        return aliases, str(base_url)

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        """去除 JSONC 注释，但保留字符串内的 /* 与 //（如 "@/*"、"**/*.ts"）。"""
        out: list[str] = []
        i, n = 0, len(text)
        in_str = False
        quote = ""
        while i < n:
            ch = text[i]
            if in_str:
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    in_str = False
                i += 1
                continue
            if ch in ('"', "'"):
                in_str = True
                quote = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    # ------------------------------------------------------------------
    # 依赖图
    # ------------------------------------------------------------------
    def _build_graph(self, root: str) -> dict[str, Any]:
        nodes = [rel for rel, f in self.files.items() if not f.is_test]
        node_set = set(nodes)
        edges: set[tuple[str, str]] = set()
        adjacency: dict[str, list[str]] = defaultdict(list)
        unresolved_local = 0
        alias_hits = 0

        for rel in nodes:
            f = self.files[rel]
            for imp in f.imports:
                module = imp["module"]
                resolved, via_alias = self._resolve_import(rel, module, root)
                if resolved is None:
                    if module.startswith("."):
                        unresolved_local += 1
                    continue
                if via_alias:
                    alias_hits += 1
                if resolved in node_set and resolved != rel:
                    edges.add((rel, resolved))
                    adjacency[rel].append(resolved)

        for rel in nodes:
            adjacency.setdefault(rel, [])

        cycles = self._detect_cycles(adjacency)
        in_degree: dict[str, int] = defaultdict(int)
        for _, dst in edges:
            in_degree[dst] += 1
        out_degree = {rel: len(set(adjacency.get(rel, []))) for rel in nodes}
        hubs = sorted(
            ({"file": rel, "in_degree": deg} for rel, deg in in_degree.items() if deg >= 2),
            key=lambda x: (-x["in_degree"], x["file"]),
        )[:_MAX_HUBS]
        orphans = sorted(
            rel for rel in nodes if in_degree.get(rel, 0) == 0 and self._is_candidate_orphan(rel)
        )
        return {
            "nodes": sorted(nodes),
            "edges": sorted(edges),
            "adjacency": {k: sorted(set(v)) for k, v in adjacency.items()},
            "cycles": cycles,
            "out_degree": out_degree,
            "hubs": hubs,
            "orphans": orphans,
            "unresolved_local_imports": unresolved_local,
            "alias_hits": alias_hits,
        }

    def _resolve_import(self, importer_rel: str, module: str, root: str) -> tuple[str | None, bool]:
        """解析 import 到本地相对路径。返回 (rel, 是否经别名)。"""
        if module.startswith("."):
            base = os.path.normpath(os.path.join(os.path.dirname(importer_rel), module))
            hit = self._probe_module(base, root)
            return (hit, False) if hit else (None, False)

        for pattern, targets in self.aliases:
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if not module.startswith(prefix):
                    continue
                rest = module[len(prefix) :]
                for target in targets:
                    tpl = target[:-1] if target.endswith("*") else target
                    candidate = os.path.normpath(os.path.join(self.base_url, tpl + rest))
                    hit = self._probe_module(candidate, root)
                    if hit:
                        return hit, True
            elif module == pattern:
                for target in targets:
                    hit = self._probe_module(os.path.normpath(target), root)
                    if hit:
                        return hit, True
        return None, False

    def _probe_module(self, rel_path: str, root: str) -> str | None:
        rel_path = rel_path.lstrip("./") if rel_path.startswith("./") else rel_path
        rel_path = os.path.normpath(rel_path).replace(os.sep, "/")
        candidates = [rel_path]
        base, ext = os.path.splitext(rel_path)
        if ext:
            candidates.extend([base + e for e in _TS_EXTS])
        else:
            candidates.extend([rel_path + e for e in _TS_EXTS])
            candidates.extend([rel_path + "/index" + e for e in _TS_EXTS])
        for cand in candidates:
            full = os.path.join(root, cand)
            if os.path.isfile(full):
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if rel in self.files:
                    return rel
        return None

    @staticmethod
    def _detect_cycles(adjacency: dict[str, list[str]]) -> list[list[str]]:
        cycles: list[list[str]] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = defaultdict(int)

        def dfs(node: str, path: list[str], depth: int) -> None:
            if len(cycles) >= _MAX_CYCLES or depth > 200:
                return
            color[node] = GRAY
            path.append(node)
            for nb in adjacency.get(node, []):
                if color[nb] == GRAY:
                    try:
                        start = path.index(nb)
                    except ValueError:
                        continue
                    cycles.append(path[start:] + [nb])
                elif color[nb] == WHITE:
                    dfs(nb, path, depth + 1)
            path.pop()
            color[node] = BLACK

        for node in sorted(adjacency):
            if color[node] == WHITE:
                dfs(node, [], 0)
        return cycles

    @staticmethod
    def _is_candidate_orphan(rel: str) -> bool:
        name = os.path.splitext(os.path.basename(rel))[0]
        if name in _SPECIAL_ROUTE_FILES or name in {
            "index",
            "main",
            "middleware",
            "proxy",
            "instrumentation",
            "instrumentation.node",
        }:
            return False
        if _TEST_FILE_RE.search(rel):
            return False
        parts = rel.split("/")
        if len(parts) <= 2:  # 根级配置 / 入口
            return False
        return True

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def _extract_routes(self) -> dict[str, list[dict[str, Any]]]:
        pages: list[dict[str, Any]] = []
        api: list[dict[str, Any]] = []
        specials: list[dict[str, Any]] = []

        for rel, f in self.files.items():
            if f.is_test:
                continue
            parts = rel.split("/")
            if "app" not in parts:
                continue
            idx = parts.index("app")
            tail = parts[idx + 1 :]
            if not tail:
                continue
            filename = tail[-1]
            stem = os.path.splitext(filename)[0]
            if stem not in _SPECIAL_ROUTE_FILES:
                continue
            route_path = self._route_path(tail[:-1])
            if stem == "page":
                pages.append({"path": route_path, "file": rel, "router": "app"})
            elif stem == "route":
                api.append(
                    {
                        "path": route_path,
                        "file": rel,
                        "methods": sorted(set(_HTTP_METHOD_RE.findall(f.source))) or ["ANY"],
                        "has_zod": "zod" in f.source,
                    }
                )
            else:
                specials.append({"kind": stem, "path": route_path, "file": rel})

        # Pages Router 兜底（pages/ 目录，且未走 App Router）
        if not pages:
            for rel, f in self.files.items():
                if f.is_test:
                    continue
                parts = rel.split("/")
                if "pages" not in parts:
                    continue
                idx = parts.index("pages")
                tail = parts[idx + 1 :]
                if not tail:
                    continue
                stem = os.path.splitext(tail[-1])[0]
                if stem.startswith("_") or stem.startswith("api"):
                    continue
                route_path = self._route_path(tail[:-1] + [stem])
                pages.append({"path": route_path, "file": rel, "router": "pages"})

        # React Router 文件路由兜底（routes/**/index.tsx，未走 App/Pages Router）
        if not pages:
            seen_paths: set[str] = set()
            for rel, f in self.files.items():
                if f.is_test:
                    continue
                parts = rel.split("/")
                if "routes" not in parts:
                    continue
                idx = parts.index("routes")
                tail = parts[idx + 1 :]
                if len(tail) < 2:
                    continue
                stem = os.path.splitext(tail[-1])[0]
                if stem not in {"index", "page"}:
                    continue
                if any(
                    seg in {"features", "components", "hooks", "store", "stores", "utils", "types"}
                    for seg in tail[:-1]
                ):
                    continue
                if "_layout" in tail[:-1]:
                    specials.append(
                        {"kind": "layout", "path": self._route_path(tail[:-2]), "file": rel}
                    )
                    continue
                if not re.search(r"export\s+default", f.source):
                    continue
                route_path = self._route_path(tail[:-1])
                if route_path in seen_paths:
                    continue
                seen_paths.add(route_path)
                pages.append({"path": route_path, "file": rel, "router": "react-router"})

        pages.sort(key=lambda r: r["path"])
        api.sort(key=lambda r: r["path"])
        return {"pages": pages, "api": api, "specials": specials}

    @staticmethod
    def _route_path(segments: list[str]) -> str:
        cleaned: list[str] = []
        for seg in segments:
            if not seg:
                continue
            if seg.startswith("(") and seg.endswith(")"):
                continue  # route group
            if seg.startswith("_"):
                continue  # private folder
            if seg.startswith("@"):
                continue  # parallel route slot
            cleaned.append(seg)
        return "/" + "/".join(cleaned) if cleaned else "/"

    # ------------------------------------------------------------------
    # Store / 组件 / monorepo / 模式
    # ------------------------------------------------------------------
    def _extract_stores(self) -> list[dict[str, Any]]:
        stores: dict[str, dict[str, Any]] = {}
        for rel, f in self.files.items():
            if f.is_test:
                continue
            is_zustand = bool(re.search(r"from\s+['\"]zustand", f.source))
            for name in f.stores:
                if (
                    not is_zustand
                    and "create<" not in f.source
                    and "/stores/" not in rel
                    and "/store/" not in rel
                ):
                    continue
                stores.setdefault(
                    name,
                    {
                        "name": name,
                        "file": rel,
                        "library": "zustand" if is_zustand else "unknown",
                    },
                )
        return sorted(stores.values(), key=lambda s: s["name"])

    def _extract_store_consumers(self, stores: list[dict[str, Any]]) -> dict[str, list[str]]:
        names = {s["name"] for s in stores}
        owners = {s["name"]: s["file"] for s in stores}
        consumers: dict[str, list[str]] = defaultdict(list)
        # 同一文件内的 hook 名可能与 store 同名但语义不同，这里只做词面消费关系
        for rel, f in self.files.items():
            if f.is_test:
                continue
            for name in set(_STORE_USAGE_RE.findall(f.source)) & names:
                if rel == owners.get(name):
                    continue
                consumers[name].append(rel)
        return {k: sorted(v) for k, v in consumers.items()}

    def _find_god_components(self) -> list[dict[str, Any]]:
        gods = [
            {"file": rel, "lines": f.lines, "components": [c["name"] for c in f.components]}
            for rel, f in self.files.items()
            if not f.is_test and f.components and f.lines > _GOD_COMPONENT_LINES
        ]
        return sorted(gods, key=lambda g: -g["lines"])[:20]

    def _detect_monorepo(self, root: str) -> dict[str, Any]:
        packages: list[dict[str, Any]] = []
        apps: list[dict[str, Any]] = []
        for group, bucket in (("packages", packages), ("apps", apps)):
            group_dir = os.path.join(root, group)
            if not os.path.isdir(group_dir):
                continue
            for name in sorted(os.listdir(group_dir)):
                pkg_json = os.path.join(group_dir, name, "package.json")
                if not os.path.isfile(pkg_json):
                    continue
                pkg_name = f"{group}/{name}"
                try:
                    data = json.loads(open(pkg_json, "r", encoding="utf-8").read())
                    pkg_name = data.get("name", pkg_name)
                except (OSError, json.JSONDecodeError):
                    pass
                bucket.append({"name": pkg_name, "dir": f"{group}/{name}"})
        manager = "unknown"
        if os.path.isfile(os.path.join(root, "pnpm-workspace.yaml")):
            manager = "pnpm"
        elif os.path.isfile(os.path.join(root, "lerna.json")):
            manager = "lerna"
        elif os.path.isfile(os.path.join(root, "package.json")):
            try:
                data = json.loads(
                    open(os.path.join(root, "package.json"), "r", encoding="utf-8").read()
                )
                if data.get("workspaces"):
                    manager = "npm-workspaces"
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "is_monorepo": bool(packages or apps),
            "packages": packages,
            "apps": apps,
            "manager": manager,
        }

    def _detect_patterns(
        self,
        root: str,
        graph: dict[str, Any],
        routes: dict[str, list[dict[str, Any]]],
        stores: list[dict[str, Any]],
        monorepo: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        all_dirs = {os.path.dirname(rel) for rel in self.files}
        deps = self._package_deps(root)
        patterns: list[dict[str, Any]] = []

        def add(
            pattern: str,
            confidence: float,
            reason: str,
            gaps: list[str] | None = None,
        ) -> None:
            patterns.append(
                {
                    "pattern": pattern,
                    "confidence": confidence,
                    "reason": reason,
                    "provenance": {
                        "target": root,
                        "analysis": "frontend_architecture_pattern",
                        "pattern": pattern,
                        "reason": reason,
                    },
                    "known_gaps": gaps or ["基于目录/依赖/文件命名的推导，需结合调用链人工确认"],
                }
            )

        app_pages = [r for r in routes["pages"] if r.get("router") == "app"]
        rr_pages = [r for r in routes["pages"] if r.get("router") == "react-router"]
        if app_pages:
            add("NextAppRouter", 0.95, f"app/ 目录 + {len(app_pages)} 个 page 文件")
        if rr_pages:
            add("ReactRouterFileRoutes", 0.9, f"routes/ 目录 + {len(rr_pages)} 个文件路由")
        if routes["api"]:
            add("APIRoutes", 0.9, f"{len(routes['api'])} 个 route.ts API 端点")
        feature_dirs = {d for d in all_dirs if "/features" in f"/{d}"}
        if feature_dirs and (
            any("/entities" in f"/{d}" or "/shared" in f"/{d}" for d in all_dirs)
            or any("/components" in f"/{d}" for d in all_dirs)
        ):
            add("FeatureSliced", 0.8, f"features/ 分层 + {len(feature_dirs)} 个 feature 目录")
        if any(
            d.endswith("/ui") or d == "ui" or "/components/ui" in d for d in all_dirs
        ) or os.path.isdir(os.path.join(root, "packages/ui")):
            add("DesignSystem", 0.85, "存在独立 ui/ 组件目录或 packages/ui 设计系统包")
        if monorepo["is_monorepo"] and len(monorepo["packages"]) >= 2:
            add(
                "Monorepo",
                0.9,
                f"{len(monorepo['packages'])} 个 packages + {len(monorepo['apps'])} 个 apps "
                f"(manager={monorepo['manager']})",
            )
        if stores or any(
            k in deps for k in ("zustand", "jotai", "valtio", "@reduxjs/toolkit", "redux")
        ):
            lib = next(
                (
                    k
                    for k in ("zustand", "jotai", "valtio", "@reduxjs/toolkit", "redux")
                    if k in deps
                ),
                "unknown",
            )
            add("StateManagement", 0.85, f"{len(stores)} 个 store, 依赖={lib}")
        if any(k.startswith("@trpc") for k in deps) or any("/trpc" in f"/{d}" for d in all_dirs):
            add("TRPC", 0.85, "检测到 @trpc 依赖或 trpc 目录")
        locale_dirs = [d for d in all_dirs if "locales" in d or "/i18n" in d]
        if (
            any(k in deps for k in ("i18next", "react-i18next", "next-intl"))
            or len(locale_dirs) >= 2
        ):
            add("i18n", 0.8, f"i18n 依赖或 {len(locale_dirs)} 个 locales 目录")
        if any(
            "text/event-stream" in f.source or "EventSource" in f.source
            for f in self.files.values()
        ):
            add("SSEStreaming", 0.8, "存在 text/event-stream / EventSource 流式实现")
        if any("/containers" in f"/{d}" for d in all_dirs) and any(
            "/components" in f"/{d}" for d in all_dirs
        ):
            add("ContainerPresenter", 0.75, "containers/ 与 components/ 并存")
        if any(k in deps for k in ("vitest", "jest", "@jest/globals")) or any(
            f.is_test for f in self.files.values()
        ):
            test_count = sum(1 for f in self.files.values() if f.is_test)
            add(
                "AutomatedTesting",
                0.8,
                f"{test_count} 个测试文件, 依赖={[k for k in ('vitest','jest') if k in deps]}",
            )
        if components and len(components) >= 10:
            add("ComponentDriven", 0.7, f"{len(components)} 个 React 组件")
        return patterns

    @staticmethod
    def _package_deps(root: str) -> dict[str, str]:
        path = os.path.join(root, "package.json")
        if not os.path.isfile(path):
            return {}
        try:
            data = json.loads(open(path, "r", encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            return {}
        merged: dict[str, str] = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            section = data.get(key) or {}
            if isinstance(section, dict):
                merged.update({str(k): str(v) for k, v in section.items()})
        return merged

    def _external_deps(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = defaultdict(int)
        for rel, f in self.files.items():
            if f.is_test:
                continue
            for imp in f.imports:
                module = imp["module"]
                if module.startswith("."):
                    continue
                if self._resolve_import(rel, module, self.target or ".")[0] is not None:
                    continue
                parts = module.split("/")
                pkg = "/".join(parts[:2]) if module.startswith("@") else parts[0]
                counts[pkg] += 1
        return [
            {"package": pkg, "imports": n}
            for pkg, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
        ]

    def _stats(self) -> dict[str, Any]:
        all_files = list(self.files.values())
        return {
            "files": len(all_files),
            "lines": sum(f.lines for f in all_files),
            "source_files": sum(1 for f in all_files if not f.is_test),
            "test_files": sum(1 for f in all_files if f.is_test),
            "jsx_files": sum(1 for f in all_files if f.has_jsx),
            "dynamic_imports": sum(f.dynamic_imports for f in all_files),
            "by_ext": {
                ext: sum(1 for f in all_files if f.ext == ext)
                for ext in sorted({f.ext for f in all_files})
            },
        }

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    def _build_evidence(
        self,
        *,
        root: str,
        graph: dict[str, Any],
        routes: dict[str, list[dict[str, Any]]],
        components: list[dict[str, Any]],
        hooks: list[str],
        stores: list[dict[str, Any]],
        store_consumers: dict[str, list[str]],
        god_components: list[dict[str, Any]],
        monorepo: dict[str, Any],
        patterns: list[dict[str, Any]],
        external_deps: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> list[Evidence]:
        evidence: list[Evidence] = []

        evidence.append(
            Evidence(
                result=(
                    f"TS/React 项目扫描: {stats['files']} 文件 / {stats['lines']} 行 "
                    f"(源码 {stats['source_files']} / 测试 {stats['test_files']})"
                ),
                level=EvidenceLevel.OBSERVATION,
                provenance={
                    "target": root,
                    "analysis": "ts_project_scan",
                    "by_ext": stats["by_ext"],
                },
                confidence=1.0,
                known_gaps=[
                    "正则解析无法覆盖全部 TS 语法（复杂泛型/装饰器/动态语法）",
                    f"已跳过 {len(_SKIP_DIRS)} 类构建目录与 node_modules",
                ],
            )
        )

        evidence.append(
            Evidence(
                result=f"依赖图: {len(graph['nodes'])} 节点, {len(graph['edges'])} 边",
                level=EvidenceLevel.DERIVATION,
                provenance={
                    "target": root,
                    "analysis": "dependency_graph",
                    "unresolved_local_imports": graph["unresolved_local_imports"],
                    "alias_hits": graph["alias_hits"],
                    "hubs": graph["hubs"],
                },
                confidence=0.9,
                known_gaps=[
                    "仅解析静态 import / require，动态 import() 无法参与建图",
                    "monorepo 跨包 import 仅通过 tsconfig paths 别名解析",
                    f"未解析的本地相对导入: {graph['unresolved_local_imports']}",
                ],
            )
        )

        evidence.append(
            Evidence(
                result=(
                    f"循环依赖: {len(graph['cycles'])} 个"
                    + (
                        f"（如 {graph['cycles'][0][0]} ↔ {graph['cycles'][0][-1]}）"
                        if graph["cycles"]
                        else ""
                    )
                ),
                level=EvidenceLevel.INFERENCE,
                provenance={
                    "target": root,
                    "analysis": "cycle_detection",
                    "cycles": graph["cycles"],
                },
                confidence=0.85 if graph["cycles"] else 0.7,
                known_gaps=["运行时依赖注入可能形成静态分析看不到的循环"],
            )
        )

        evidence.append(
            Evidence(
                result=(
                    f"路由: {len(routes['pages'])} 个页面, {len(routes['api'])} 个 API route, "
                    f"{len(routes['specials'])} 个特殊文件(layout/loading/error)"
                ),
                level=EvidenceLevel.OBSERVATION,
                provenance={
                    "target": root,
                    "analysis": "route_extraction",
                    "pages": [r["path"] for r in routes["pages"]],
                    "api": [r["path"] for r in routes["api"]],
                },
                confidence=0.95,
                known_gaps=[
                    "动态路由段以 [param] 原样保留，未展开运行时参数",
                    "运行时生成路由（middleware rewrite / 动态 import 页面）无法静态识别",
                ],
            )
        )

        evidence.append(
            Evidence(
                result=(
                    f"React 组件: {len(components)} 个, Hook: {len(hooks)} 个, "
                    f"God component(>{_GOD_COMPONENT_LINES} 行): {len(god_components)} 个"
                ),
                level=EvidenceLevel.DERIVATION,
                provenance={
                    "target": root,
                    "analysis": "component_graph",
                    "god_components": god_components,
                },
                confidence=0.8,
                known_gaps=[
                    "组件识别基于 PascalCase + JSX 启发式，HOC/动态组件可能漏检",
                    "组件间 props 数据流未静态还原",
                ],
            )
        )

        evidence.append(
            Evidence(
                result=(
                    f"状态管理: {len(stores)} 个 store, "
                    f"{sum(len(v) for v in store_consumers.values())} 个消费引用"
                ),
                level=EvidenceLevel.DERIVATION,
                provenance={
                    "target": root,
                    "analysis": "store_graph",
                    "stores": stores,
                    "store_consumers": store_consumers,
                },
                confidence=0.85,
                known_gaps=["仅识别 zustand create(...) 形态；redux-toolkit/自研 store 可能漏检"],
            )
        )

        if monorepo["is_monorepo"]:
            evidence.append(
                Evidence(
                    result=(
                        f"Monorepo: {len(monorepo['packages'])} packages / "
                        f"{len(monorepo['apps'])} apps (manager={monorepo['manager']})"
                    ),
                    level=EvidenceLevel.OBSERVATION,
                    provenance={"target": root, "analysis": "monorepo_scan", **monorepo},
                    confidence=0.95,
                    known_gaps=["仅统计 packages/apps 一级目录，嵌套 workspace 可能漏检"],
                )
            )

        for p in patterns:
            evidence.append(
                Evidence(
                    result=f"检测到 {p['pattern']} 架构模式（{p['reason']}）",
                    level=EvidenceLevel.DERIVATION,
                    provenance=p["provenance"],
                    confidence=p["confidence"],
                    known_gaps=p["known_gaps"],
                )
            )

        if external_deps:
            evidence.append(
                Evidence(
                    result="第三方依赖 Top: "
                    + ", ".join(f"{d['package']}({d['imports']})" for d in external_deps[:8]),
                    level=EvidenceLevel.OBSERVATION,
                    provenance={"target": root, "analysis": "external_deps", "deps": external_deps},
                    confidence=0.9,
                    known_gaps=["未结合 package.json 版本判断依赖更新/漏洞"],
                )
            )

        if graph["orphans"]:
            evidence.append(
                Evidence(
                    result=f"疑似孤立模块: {len(graph['orphans'])} 个（无任何本地 import 引用）",
                    level=EvidenceLevel.INFERENCE,
                    provenance={
                        "target": root,
                        "analysis": "orphan_scan",
                        "orphans": graph["orphans"],
                    },
                    confidence=0.7,
                    known_gaps=["入口文件/动态加载模块可能被误判为孤立，需人工确认"],
                )
            )

        return evidence


def analyze_frontend_project(target: str) -> AnalyzeResult:
    """模块级便捷入口。"""
    return TSProjectAnalyzer(target).analyze()

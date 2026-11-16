"""A3-1: 只读插件图 inspect（IF-6 / ADR-10 / GAP-21 前置）。

边界
----
- **只读**：不执行插件、不启停、不写任何文件；只读 DSH profile 与本地包清单/源码。
- **不伪装**：依赖环无法用契约表达（`graph.acyclic` 只能是 `true`），检测到环直接
  fail-closed 抛 `PluginInspectError`，不产出「看起来成功」的响应。
- **静态提取**：事件通道 / 能力面来自本地插件源码正则（`ctx.on` / `ctx.emit` /
  `defineTool({name})`），只报能静态确认的事实；提取不到就留空，不猜。

事实来源
--------
1. `$DSH_HOME/profiles/<profile>/package.json`：实际安装的插件与 bundles。
2. `<repo>/1-ARCHITECTURE/dream-harness-bridge/packages/<pkg>/package.json`：本地包版本与依赖。
3. 本地包 `lib/**/*.js`：事件通道与工具名（静态正则）。

profile 不在 IF-6 请求字段内，由 `DSH_INSPECT_PROFILE`（默认 `headless`）或调用参数决定。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA_VERSION = "1.0"
DEFAULT_PROFILE = "headless"
DEFAULT_REQUEST_ID = "inspect-local"

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PACKAGES_DIR = REPO_ROOT / "1-ARCHITECTURE" / "dream-harness-bridge" / "packages"

_ON_RE = re.compile(r"ctx\.on\(\s*[\"']([^\"']+)[\"']")
_EMIT_RE = re.compile(r"ctx\.emit\(\s*[\"']([^\"']+)[\"']")
_DEFINE_TOOL_RE = re.compile(r"defineTool\(\s*\{\s*name:\s*[\"']([^\"']+)[\"']")
_REGISTER_TOOL_RE = re.compile(r"ctx\.tools\.register\(\s*\{\s*name:\s*[\"']([^\"']+)[\"']")


class PluginInspectError(ValueError):
    """inspect 前置条件不满足（拒绝产出响应）"""


# ============================================================
# 只读事实读取
# ============================================================


def dsh_home(home: Optional[Path] = None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env)
    return REPO_ROOT / "1-ARCHITECTURE" / "dream-harness-bridge" / ".dsh-home"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _profile_doc(profile: str, home: Path) -> Dict[str, Any]:
    path = home / "profiles" / profile / "package.json"
    doc = _read_json(path)
    if doc is None:
        raise PluginInspectError(f"profile 不存在或缺 package.json: {profile}（{path}）")
    return doc


def _resolve_local_package(
    name: str, spec: str, profile_dir: Path, packages_dir: Path
) -> Optional[Path]:
    """解析本地插件包目录（file: 相对 profile 目录；否则按包名到 packages/ 查）。"""
    if spec.startswith("file:"):
        candidate = (profile_dir / spec[len("file:") :]).resolve()
        return candidate if (candidate / "package.json").is_file() else None
    candidate = packages_dir / name
    return candidate if (candidate / "package.json").is_file() else None


def _plugin_dep(name: str) -> bool:
    """区分「插件依赖」与普通 npm 库：dreambuddy-* / @deepseek-ai/dsh*。"""
    return name.startswith("dreambuddy-") or name.startswith("@deepseek-ai/dsh")


def _scan_sources(pkg_dir: Path) -> Iterable[str]:
    lib = pkg_dir / "lib"
    root = lib if lib.is_dir() else pkg_dir
    for path in sorted(root.rglob("*.js")):
        try:
            yield path.read_text(encoding="utf-8")
        except OSError:
            continue


def _channels_and_capabilities(pkg_dir: Optional[Path]) -> Dict[str, Any]:
    subscribe, publish, capabilities = set(), set(), set()
    if pkg_dir is not None:
        for text in _scan_sources(pkg_dir):
            subscribe.update(_ON_RE.findall(text))
            publish.update(_EMIT_RE.findall(text))
            capabilities.update(_DEFINE_TOOL_RE.findall(text))
            capabilities.update(_REGISTER_TOOL_RE.findall(text))
    return {
        "event_channels": {
            "publish": sorted(publish),
            "subscribe": sorted(subscribe),
        },
        "capabilities": sorted(capabilities),
    }


# ============================================================
# 图构建
# ============================================================


def _detect_cycle(graph: Dict[str, List[str]]) -> Optional[List[str]]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)
    stack: List[str] = []

    def dfs(node: str) -> Optional[List[str]]:
        color[node] = GRAY
        stack.append(node)
        for dep in graph.get(node, []):
            if color.get(dep) == GRAY:
                return stack[stack.index(dep) :] + [dep]
            if color.get(dep) == WHITE:
                found = dfs(dep)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = dfs(node)
            if found:
                return found
    return None


def _build_response(
    profile: str,
    home: Path,
    packages_dir: Path,
    request_id: str,
) -> Dict[str, Any]:
    doc = _profile_doc(profile, home)
    profile_dir = home / "profiles" / profile
    dependencies = doc.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        raise PluginInspectError(f"profile {profile} 的 dependencies 不是对象")

    installed = {str(name) for name in dependencies}
    plugins: List[Dict[str, Any]] = []
    unresolved: set = set()
    graph: Dict[str, List[str]] = {}

    for name in sorted(installed):
        spec = str(dependencies.get(name) or "")
        pkg_dir = _resolve_local_package(name, spec, profile_dir, packages_dir)
        if pkg_dir is None and spec.startswith("file:"):
            # 声明安装但包不存在：不是已加载插件，只进 unresolved（不伪造节点）
            unresolved.add(name)
            continue

        pkg_doc = _read_json(pkg_dir / "package.json") if pkg_dir else None
        version = str((pkg_doc or {}).get("version") or spec or "unknown")

        declared = (pkg_doc or {}).get("dependencies") or {}
        dep_names = sorted(
            str(dep)
            for dep in (declared if isinstance(declared, dict) else {})
            if str(dep) in installed or _plugin_dep(str(dep))
        )
        for dep in dep_names:
            if dep not in installed:
                unresolved.add(dep)

        extracted = _channels_and_capabilities(pkg_dir)
        plugins.append(
            {
                "plugin_id": name,
                "version": version,
                "dependencies": dep_names,
                "event_channels": extracted["event_channels"],
                "capabilities": extracted["capabilities"],
            }
        )
        graph[name] = [dep for dep in dep_names if dep in installed]

    cycle = _detect_cycle(graph)
    if cycle:
        raise PluginInspectError("插件依赖环: " + " → ".join(cycle))

    return {
        "schema_version": SCHEMA_VERSION,
        "op": "inspect",
        "direction": "response",
        "request_id": request_id,
        "ok": True,
        "plugins": plugins,
        "graph": {"acyclic": True, "unresolved": sorted(unresolved)},
    }


# ============================================================
# 契约入口
# ============================================================


def build_inspect_request(request_id: str = DEFAULT_REQUEST_ID) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "op": "inspect",
        "direction": "request",
        "request_id": request_id,
    }


def inspect_plugins(
    profile: Optional[str] = None,
    home: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
    request_id: str = DEFAULT_REQUEST_ID,
) -> Dict[str, Any]:
    """只读生成 inspect.response（profile 缺省取 DSH_INSPECT_PROFILE / headless）。"""
    chosen = profile or os.environ.get("DSH_INSPECT_PROFILE", DEFAULT_PROFILE)
    return _build_response(
        chosen,
        dsh_home(home),
        Path(packages_dir) if packages_dir else DEFAULT_PACKAGES_DIR,
        request_id,
    )


def handle_inspect(
    request: Dict[str, Any],
    profile: Optional[str] = None,
    home: Optional[Path] = None,
    packages_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """校验 IF-6 inspect.request 后返回 inspect.response。"""
    if not isinstance(request, dict):
        raise PluginInspectError("inspect request 必须是对象")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise PluginInspectError(f"schema_version 必须为 {SCHEMA_VERSION}")
    if request.get("op") != "inspect":
        raise PluginInspectError(f"op 必须为 inspect（实际 {request.get('op')!r}）")
    if request.get("direction") != "request":
        raise PluginInspectError(f"direction 必须为 request（实际 {request.get('direction')!r}）")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or len(request_id) < 6:
        raise PluginInspectError("request_id 至少 6 字")

    return inspect_plugins(
        profile=profile,
        home=home,
        packages_dir=packages_dir,
        request_id=request_id,
    )


# ============================================================
# CLI
# ============================================================


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_inspect.py", description="A3-1 只读插件图 inspect（IF-6）"
    )
    parser.add_argument("--profile", default=None, help="DSH profile（缺省 headless）")
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument("--home", type=Path, default=None, help="DSH_HOME 覆盖")
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="响应落盘路径")
    args = parser.parse_args(argv)

    try:
        response = handle_inspect(
            build_inspect_request(args.request_id),
            profile=args.profile,
            home=args.home,
            packages_dir=args.packages_dir,
        )
    except PluginInspectError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    text = json.dumps(response, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())

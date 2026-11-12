"""前端项目逆向分析 CLI — 33-REA 项目级 TS/React 分析入口。

用法：
    python scripts/analyze_frontend.py 3.1-FRONTEND
    python scripts/analyze_frontend.py /tmp/lobehub --json-out /tmp/lobehub.json
    python scripts/analyze_frontend.py . --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ts_project_analyzer import TSProjectAnalyzer  # noqa: E402


def print_human(result, top: int) -> None:
    raw = result.raw
    print(f"\n=== {result.summary} ===")
    stats = raw.get("stats", {})
    print(f"目标: {raw.get('target')}")
    print(
        f"文件: {stats.get('files')} (源码 {stats.get('source_files')} / "
        f"测试 {stats.get('test_files')}) | 行数: {stats.get('lines')} | "
        f"JSX 文件: {stats.get('jsx_files')}"
    )

    graph = raw.get("graph", {})
    print(
        f"\n-- 依赖图 -- {len(graph.get('nodes', []))} 节点 / "
        f"{len(graph.get('edges', []))} 边 / {len(graph.get('cycles', []))} 环 "
        f"/ 未解析本地导入 {graph.get('unresolved_local_imports')} "
        f"/ 别名命中 {graph.get('alias_hits')}"
    )
    for c in graph.get("cycles", [])[:top]:
        print(f"  cycle: {' -> '.join(c)}")
    if graph.get("hubs"):
        print("  被依赖最多:")
        for h in graph["hubs"][:top]:
            print(f"    {h['in_degree']:>4}  {h['file']}")
    if graph.get("orphans"):
        print(f"  疑似孤立模块 ({len(graph['orphans'])}):")
        for o in graph["orphans"][:top]:
            print(f"    {o}")

    print(
        f"\n-- 路由 -- 页面 {len(raw.get('routes', []))} / "
        f"API {len(raw.get('api_routes', []))} / 特殊 {len(raw.get('route_specials', []))}"
    )
    for r in raw.get("routes", [])[:top]:
        print(f"    page {r['path']:<40} {r['file']}")
    for r in raw.get("api_routes", [])[:top]:
        print(f"    api  {r['path']:<40} {','.join(r['methods'])}")

    print(f"\n-- 组件 -- {len(raw.get('components', []))} 个 / Hook {len(raw.get('hooks', []))} 个")
    for g in raw.get("god_components", [])[:top]:
        print(f"    god {g['lines']:>5} 行  {g['file']}  {g['components'][:3]}")

    stores = raw.get("stores", [])
    consumers = raw.get("store_consumers", {})
    print(f"\n-- 状态管理 -- {len(stores)} store")
    for s in stores[:top]:
        print(f"    {s['name']:<30} {s['file']}  消费 {len(consumers.get(s['name'], []))} 处")

    mono = raw.get("monorepo", {})
    if mono.get("is_monorepo"):
        print(
            f"\n-- Monorepo -- packages {len(mono.get('packages', []))} / "
            f"apps {len(mono.get('apps', []))} / manager={mono.get('manager')}"
        )

    print(f"\n-- 架构模式 -- {len(raw.get('patterns', []))}")
    for p in raw.get("patterns", []):
        print(f"    {p['pattern']:<22} {p['confidence']:.2f}  {p['reason']}")

    print(f"\n-- 第三方依赖 Top {top} --")
    for d in raw.get("external_deps", [])[:top]:
        print(f"    {d['imports']:>5}  {d['package']}")

    print(f"\n-- Evidence ({len(result.evidence)}) / known_gaps --")
    for e in result.evidence:
        level = e.level.value if hasattr(e.level, "value") else e.level
        print(f"    [{level}/{e.confidence:.2f}] {e.result}")
    gaps = sorted({g for e in result.evidence for g in e.known_gaps})
    print(f"  known_gaps ({len(gaps)}):")
    for g in gaps:
        print(f"    - {g}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TS/React 项目级逆向分析")
    parser.add_argument("target", help="前端项目根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    parser.add_argument("--json-out", help="JSON 结果写入文件")
    parser.add_argument("--top", type=int, default=10, help="各段落展示条数")
    args = parser.parse_args(argv)

    result = TSProjectAnalyzer(args.target).analyze()

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(result, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())

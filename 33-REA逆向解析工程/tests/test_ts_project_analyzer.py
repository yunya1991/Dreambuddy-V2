"""RED 测试：TSProjectAnalyzer — TS/React 项目级逆向分析器。

覆盖：
- App Router 页面 / API route 提取
- 本地 import 依赖图（含 tsconfig paths 别名解析）+ 环检测
- React 组件图 / God component
- zustand store 定义与消费关系
- monorepo packages 识别
- 前端架构模式识别
- Evidence / known_gaps / FAIL-OPEN
- 与 investigation_workflow 的目录级集成
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ts_project_analyzer import TSProjectAnalyzer  # noqa: E402

BIG_COMPONENT_LINES = 320


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _build_fixture(root: Path) -> None:
    _write(
        root,
        "tsconfig.json",
        json.dumps(
            {
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {"@/*": ["./src/*"]},
                }
            }
        ),
    )
    _write(
        root,
        "package.json",
        json.dumps(
            {
                "name": "fixture-web",
                "dependencies": {"next": "14.0.0", "react": "18.0.0", "zustand": "5.0.0"},
                "devDependencies": {"vitest": "2.0.0"},
            }
        ),
    )
    _write(
        root,
        "src/app/layout.tsx",
        "import Header from '@/components/Header';\n"
        "export default function RootLayout({ children }) {\n"
        "  return (<html><body><Header />{children}</body></html>);\n"
        "}\n",
    )
    _write(
        root,
        "src/app/page.tsx",
        "import Header from '@/components/Header';\n"
        "import { useChatStore } from '@/stores/useChatStore';\n"
        "export default function HomePage() {\n"
        "  const messages = useChatStore((s) => s.messages);\n"
        "  return (<main><Header /><span>{messages.length}</span></main>);\n"
        "}\n",
    )
    _write(
        root,
        "src/app/dashboard/page.tsx",
        "import ChatPanel from '@/features/chat/ChatPanel';\n"
        "export default function DashboardPage() {\n"
        "  return (<section><ChatPanel /></section>);\n"
        "}\n",
    )
    _write(
        root,
        "src/app/api/chat/route.ts",
        "import { db } from '@/lib/db';\n"
        "export async function POST(req: Request) {\n"
        "  const body = await req.json();\n"
        "  return Response.json({ ok: await db.save(body) });\n"
        "}\n"
        "export async function GET() {\n"
        "  return Response.json({ ok: true });\n"
        "}\n",
    )
    _write(
        root,
        "src/components/Header.tsx",
        "export default function Header() {\n" "  return (<header><h1>Demo</h1></header>);\n" "}\n",
    )
    _write(
        root,
        "src/components/ui/Button.tsx",
        "export function Button({ label }: { label: string }) {\n"
        "  return <button>{label}</button>;\n"
        "}\n",
    )
    big_body = "\n".join(f"  // filler line {i}" for i in range(BIG_COMPONENT_LINES))
    _write(
        root,
        "src/features/chat/ChatPanel.tsx",
        "import { Button } from '@/components/ui/Button';\n"
        "import { useChatStore } from '@/stores/useChatStore';\n"
        "export function ChatPanel() {\n"
        "  const messages = useChatStore((s) => s.messages);\n"
        f"{big_body}\n"
        '  return (<div><Button label="send" />{messages.length}</div>);\n'
        "}\n",
    )
    _write(
        root,
        "src/stores/useChatStore.ts",
        "import { create } from 'zustand';\n"
        "export const useChatStore = create((set) => ({\n"
        "  messages: [],\n"
        "  add: (m) => set((s) => ({ messages: [...s.messages, m] })),\n"
        "}));\n",
    )
    _write(root, "src/lib/db.ts", "export const db = { save: async (x) => x };\n")
    _write(root, "src/lib/orphan.ts", "export const unused = 42;\n")
    _write(
        root, "src/lib/cycleA.ts", "import { b } from './cycleB';\nexport const a = () => b();\n"
    )
    _write(
        root, "src/lib/cycleB.ts", "import { a } from './cycleA';\nexport const b = () => a();\n"
    )
    _write(root, "packages/ui/package.json", json.dumps({"name": "@fixture/ui"}))
    _write(root, "packages/ui/src/index.ts", "export const Card = () => null;\n")
    _write(root, "packages/database/package.json", json.dumps({"name": "@fixture/database"}))
    _write(root, "packages/database/src/index.ts", "export const db = {};\n")
    _write(
        root, "src/features/chat/ChatPanel.test.tsx", "import { ChatPanel } from './ChatPanel';\n"
    )
    _write(root, "node_modules/ignored/index.ts", "export const nope = 1;\n")


def _analyze(tmp_path: Path):
    _build_fixture(tmp_path)
    return TSProjectAnalyzer(str(tmp_path)).analyze()


def test_extracts_app_router_routes(tmp_path):
    result = _analyze(tmp_path)
    routes = {r["path"] for r in result.raw["routes"]}
    assert "/" in routes
    assert "/dashboard" in routes
    api_routes = result.raw["api_routes"]
    chat = next(r for r in api_routes if r["path"] == "/api/chat")
    assert "POST" in chat["methods"]
    assert "GET" in chat["methods"]


def test_builds_local_import_graph_with_alias(tmp_path):
    result = _analyze(tmp_path)
    graph = result.raw["graph"]
    assert "src/lib/db.ts" in graph["nodes"]
    assert ("src/app/api/chat/route.ts", "src/lib/db.ts") in {tuple(e) for e in graph["edges"]}
    # node_modules 必须被排除
    assert not any("node_modules" in n for n in graph["nodes"])


def test_detects_cycles(tmp_path):
    result = _analyze(tmp_path)
    cycles = result.raw["graph"]["cycles"]
    assert cycles, "应检测到 cycleA <-> cycleB 循环依赖"
    joined = " ".join(" ".join(c) for c in cycles)
    assert "src/lib/cycleA.ts" in joined and "src/lib/cycleB.ts" in joined


def test_detects_components_and_god_component(tmp_path):
    result = _analyze(tmp_path)
    names = {c["name"] for c in result.raw["components"]}
    assert {"Header", "ChatPanel", "Button"} <= names
    god = {g["file"] for g in result.raw["god_components"]}
    assert "src/features/chat/ChatPanel.tsx" in god


def test_detects_store_and_consumers(tmp_path):
    result = _analyze(tmp_path)
    stores = {s["name"]: s for s in result.raw["stores"]}
    assert "useChatStore" in stores
    consumers = set(result.raw["store_consumers"].get("useChatStore", []))
    assert "src/features/chat/ChatPanel.tsx" in consumers
    assert "src/app/page.tsx" in consumers


def test_detects_monorepo_packages(tmp_path):
    result = _analyze(tmp_path)
    packages = {p["name"] for p in result.raw["monorepo"]["packages"]}
    assert {"@fixture/ui", "@fixture/database"} <= packages


def test_detects_frontend_architecture_patterns(tmp_path):
    result = _analyze(tmp_path)
    patterns = {p["pattern"] for p in result.raw["patterns"]}
    assert "NextAppRouter" in patterns
    assert "FeatureSliced" in patterns
    assert "DesignSystem" in patterns
    assert "Monorepo" in patterns
    assert "StateManagement" in patterns


def test_detects_orphans(tmp_path):
    result = _analyze(tmp_path)
    assert "src/lib/orphan.ts" in result.raw["graph"]["orphans"]


def test_evidence_first_contract(tmp_path):
    result = _analyze(tmp_path)
    assert result.evidence
    for e in result.evidence:
        assert e.provenance
        assert 0.0 <= e.confidence <= 1.0
        assert isinstance(e.known_gaps, list)
    dep_ev = [e for e in result.evidence if e.provenance.get("analysis") == "dependency_graph"]
    assert dep_ev, "必须输出 dependency_graph Evidence（供架构债务消费）"
    assert "节点" in str(dep_ev[0].result) and "边" in str(dep_ev[0].result)
    gaps = [g for e in result.evidence for g in e.known_gaps]
    assert any("动态" in g for g in gaps)


def test_failopen_on_non_project(tmp_path):
    result = TSProjectAnalyzer(str(tmp_path / "missing")).analyze()
    assert result.raw.get("error") or any(
        e.level in ("unknown", "UNKNOWN") for e in result.evidence
    )


def test_extracts_react_router_file_routes(tmp_path):
    """React Router 文件路由（routes/**/index.tsx）应被识别，且排除 features/。"""
    _write(
        tmp_path, "package.json", json.dumps({"dependencies": {"react": "18", "react-router": "7"}})
    )
    _write(
        tmp_path,
        "src/routes/(main)/chat/index.tsx",
        "export default function ChatPage() { return (<div>chat</div>); }\n",
    )
    _write(
        tmp_path,
        "src/routes/(main)/chat/_layout/index.tsx",
        "export default function ChatLayout({ children }) { return (<main>{children}</main>); }\n",
    )
    _write(
        tmp_path,
        "src/routes/(main)/chat/features/Panel.tsx",
        "export const Panel = () => (<div>panel</div>);\n",
    )
    result = TSProjectAnalyzer(str(tmp_path)).analyze()
    pages = {r["path"] for r in result.raw["routes"]}
    assert "/chat" in pages
    assert "/chat/features" not in pages
    assert "ReactRouterFileRoutes" in {p["pattern"] for p in result.raw["patterns"]}
    assert "NextAppRouter" not in {p["pattern"] for p in result.raw["patterns"]}


def test_workflow_integrates_ts_project(tmp_path):
    _build_fixture(tmp_path)
    from core.investigation_workflow import investigate

    report = investigate(str(tmp_path), feature="chat 前端链路")
    locate = report["phases"]["locate"]
    trace = report["phases"]["trace"]
    assert locate["language"] == "typescript"
    assert len(locate["modules"]) > 0
    assert not any("TS/JS 调用链追踪暂不支持" in str(e.result) for e in trace["evidence"])
    assert len(report["evidence"]) > 5
    assert report["summary"]

    from core.architecture_pattern_detector import detect_architecture_patterns

    detected = detect_architecture_patterns(str(tmp_path))
    assert detected["patterns"], "前端项目也应识别出架构模式"

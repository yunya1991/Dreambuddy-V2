#!/usr/bin/env python3
"""SPEC-33-D 验收：REA MCP 节点层（语言路由 / scope 分级 / 快照分页 / 缓存）。

覆盖 G-D1 ~ G-D3、G-D8：
  - T-D1 语言路由：TS/React 项目走 TSProjectAnalyzer，Python 项目仍走旧路径
  - T-D2 scope 三档：summary 有上限、full 只回 snapshot_id
  - T-D3 get_rea_snapshot 分页
  - T-D6 内容寻址缓存命中
  - T-D9 cognitive_hint 契约
"""

import json
import sys
from pathlib import Path

import pytest

_REA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402

_SUMMARY_MAX_BYTES = 16_384


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def ts_project(tmp_path: Path) -> Path:
    """最小 TS/React 工程：tsconfig 别名 + App Router 页面 + 组件 + 工具库。"""
    root = tmp_path / "ts-app"
    _write(
        root / "tsconfig.json",
        json.dumps(
            {
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {"@/*": ["./src/*"]},
                }
            }
        ),
    )
    _write(root / "package.json", json.dumps({"name": "fixture-app"}))
    _write(
        root / "src" / "app" / "page.tsx",
        'import { Button } from "@/components/Button";\n'
        "export default function Page() { return <Button />; }\n",
    )
    _write(
        root / "src" / "app" / "api" / "health" / "route.ts",
        "export async function GET() { return Response.json({ ok: true }); }\n",
    )
    _write(
        root / "src" / "components" / "Button.tsx",
        "export function Button() { return <button>hi</button>; }\n",
    )
    _write(
        root / "src" / "lib" / "util.ts",
        "export function add(a: number, b: number) { return a + b; }\n",
    )
    _write(
        root / "src" / "stores" / "counter.ts",
        'import { create } from "zustand";\n'
        "export const useCounterStore = create<{ n: number }>(() => ({ n: 0 }));\n",
    )
    return root


@pytest.fixture()
def py_project(tmp_path: Path) -> Path:
    root = tmp_path / "py-app"
    _write(root / "pkg" / "__init__.py", "")
    _write(
        root / "pkg" / "core.py",
        "def add(a, b):\n    return a + b\n",
    )
    _write(
        root / "pkg" / "app.py",
        "from pkg.core import add\n\n\ndef main():\n    return add(1, 2)\n",
    )
    return root


def test_detect_target_language(ts_project: Path, py_project: Path) -> None:
    assert dsh_nodes.detect_target_language(str(ts_project)) == "typescript"
    assert dsh_nodes.detect_target_language(str(py_project)) == "python"
    assert dsh_nodes.detect_target_language(str(ts_project / "package.json")) == "typescript"
    assert dsh_nodes.detect_target_language(str(py_project / "pkg" / "core.py")) == "python"
    assert dsh_nodes.detect_target_language(str(py_project / "nope.md")) == "unknown"
    # 子目录目标：影响面/陌生模块常以子目录为入口
    assert dsh_nodes.detect_target_language(str(ts_project / "src" / "components")) == "typescript"
    assert dsh_nodes.detect_target_language(str(py_project / "pkg")) == "python"


def test_analyze_ts_project_routes_to_ts_analyzer(ts_project: Path) -> None:
    """G-D1：TS 项目必须走项目级分析，不得返回"未找到 Python 文件"。"""
    out = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "summary"})
    assert out["ok"] is True, out
    result = out["result"]
    assert result["language"] == "typescript"
    assert result["stats"]["files"] >= 5
    assert "未找到 Python 文件" not in result["summary"]
    assert result["snapshot_id"]


def test_analyze_python_project_keeps_legacy_path(py_project: Path) -> None:
    out = dsh_nodes.S33_rea_analyze({"target": str(py_project), "scope": "summary"})
    assert out["ok"] is True, out
    result = out["result"]
    assert result["language"] == "python"
    assert result["stats"]["modules"] >= 2


def test_summary_scope_is_bounded_and_carries_hint(ts_project: Path) -> None:
    """G-D2 + G-D8：默认 summary ≤16KB，且带 cognitive_hint。"""
    out = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "summary"})
    payload = json.dumps(out["result"], ensure_ascii=False)
    assert len(payload.encode("utf-8")) <= _SUMMARY_MAX_BYTES
    assert out["result"]["scope"] == "summary"
    hint = out["result"]["cognitive_hint"]
    assert hint is not None
    assert hint["quality_level"] in ("B", "C")
    assert hint["level"] in ("observation", "derivation", "inference")
    assert hint["snapshot_id"] == out["result"]["snapshot_id"]


def test_full_scope_returns_snapshot_only(ts_project: Path) -> None:
    """G-D2：full 不内联 raw，只回 snapshot_id。"""
    out = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "full"})
    result = out["result"]
    assert result["scope"] == "full"
    assert "raw" not in result
    assert result["snapshot_id"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 4_096


def test_default_scope_is_summary(ts_project: Path) -> None:
    out = dsh_nodes.S33_rea_analyze({"target": str(ts_project)})
    assert out["result"]["scope"] == "summary"


def test_snapshot_pagination(ts_project: Path) -> None:
    """G-D2：明细必须可分页读取。"""
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "full"})
    snapshot_id = analyzed["result"]["snapshot_id"]

    page1 = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "modules", "limit": 1}
    )
    assert page1["ok"] is True
    data = page1["result"]
    assert len(data["items"]) == 1
    assert data["total"] >= 2
    assert data["next_cursor"] == 1

    page2 = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": snapshot_id, "section": "modules", "cursor": 1, "limit": 1}
    )
    assert page2["result"]["items"] != data["items"]


def test_snapshot_invalid_section(ts_project: Path) -> None:
    analyzed = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "full"})
    out = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": analyzed["result"]["snapshot_id"], "section": "not_a_section"}
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_section"


def test_cache_hit_on_second_call(ts_project: Path) -> None:
    """G-D3：同目标二次调用命中缓存。"""
    first = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "summary"})
    second = dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "summary"})
    assert first["result"]["cache_hit"] is False
    assert second["result"]["cache_hit"] is True
    assert second["result"]["snapshot_id"] == first["result"]["snapshot_id"]


def test_force_bypasses_cache(ts_project: Path) -> None:
    dsh_nodes.S33_rea_analyze({"target": str(ts_project), "scope": "summary"})
    forced = dsh_nodes.S33_rea_analyze(
        {"target": str(ts_project), "scope": "summary", "force": True}
    )
    assert forced["result"]["cache_hit"] is False


def test_trace_ts_project(ts_project: Path) -> None:
    """T-D1：TS 功能追踪走模块导入图，不再返回"暂不支持"。"""
    out = dsh_nodes.S33_rea_trace(
        {
            "target": str(ts_project),
            "feature": "Button",
            "entry": "src/components/Button.tsx",
        }
    )
    assert out["ok"] is True, out
    result = out["result"]
    assert result["language"] == "typescript"
    assert "暂不支持" not in json.dumps(result, ensure_ascii=False)
    assert result["call_chain"]["entry_chain"]
    assert result["call_chain"]["callers"]


def test_missing_target() -> None:
    out = dsh_nodes.S33_rea_analyze({})
    assert out["ok"] is False
    assert out["error"] == "missing_target"


# ---------------------------------------------------------------------------
# 四场景实测暴露的质量缺陷回归（2026-11-11）
# ---------------------------------------------------------------------------


def test_trace_ts_uses_feature_for_seeds(ts_project: Path) -> None:
    """feature 必须真正参与种子定位（此前 TS trace 只是全量图 dump）。"""
    out = dsh_nodes.S33_rea_trace({"target": str(ts_project), "feature": "button"})
    assert out["ok"] is True, out
    result = out["result"]
    assert result["matched"], result
    assert result["matched"][0]["module"] == "src/components/Button.tsx"
    assert result["matched"][0]["match"] == "path"
    callers = result["call_chain"]["callers"]
    assert "src/app/page.tsx" in callers.get("src/components/Button.tsx", [])
    assert result["stats"]["upstream"] >= 1


def test_impact_reverse_dependents_for_subdir(ts_project: Path) -> None:
    """影响面：以子目录内文件为 entry，callers 即"谁引用该子目录"。"""
    out = dsh_nodes.S33_rea_trace(
        {"target": str(ts_project), "feature": "Button", "entry": "src/components/Button.tsx"}
    )
    assert out["ok"] is True, out
    result = out["result"]
    dependents = result["call_chain"]["callers"].get("src/components/Button.tsx", [])
    assert "src/app/page.tsx" in dependents
    assert result["stats"]["seeds"] == 1


def test_python_modules_exclude_external(tmp_path: Path) -> None:
    """Python 模块数只算项目内文件，stdlib/第三方单列 external_modules。"""
    root = tmp_path / "py-ext"
    _write(root / "pkg" / "__init__.py", "")
    _write(
        root / "pkg" / "core.py", "import json\nimport os\n\n\ndef add(a, b):\n    return a + b\n"
    )
    _write(
        root / "pkg" / "app.py",
        "import argparse\nfrom pkg.core import add\n\n\ndef main():\n    return add(1, 2)\n",
    )
    out = dsh_nodes.S33_rea_analyze({"target": str(root), "scope": "summary"})
    result = out["result"]
    assert result["language"] == "python"
    assert result["stats"]["modules"] == 2
    assert result["stats"]["external_modules"] >= 3  # argparse / json / os
    assert result["stats"]["edges"] == 1  # pkg.app -> pkg（内部包前缀）
    assert "argparse" not in (result["summary"] or "")


def test_trimmed_marker_not_silent() -> None:
    """G-D2：证据被裁剪时必须留 trimmed 标记，不得静默丢弃。"""
    out = dsh_nodes.S33_rea_analyze({"target": str(_REA_ROOT), "scope": "summary"})
    result = out["result"]
    total = result["evidence_counts"]["total"]
    kept = len(result.get("evidence") or [])
    if kept < total:
        assert result.get("trimmed", {}).get("evidence") == {"kept": kept, "total": total}
    else:
        assert "trimmed" not in result or "evidence" not in result["trimmed"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= _SUMMARY_MAX_BYTES

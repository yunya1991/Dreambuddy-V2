"""SPEC-33-F T-F06 架构约束引擎测试（RED）。"""

from __future__ import annotations

import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.rules_engine import check_constraints, load_rules  # noqa: E402

# ---------------------------------------------------------------------------
# 规则加载
# ---------------------------------------------------------------------------


def test_load_rules_missing_file() -> None:
    rules = load_rules("/nonexistent/rea_rules.yaml")
    assert rules == []


def test_load_rules_valid(tmp_path: Path) -> None:
    rule_file = tmp_path / "rea_rules.yaml"
    rule_file.write_text(
        """version: 1
layers:
  ui: ["src/components/**"]
  store: ["src/stores/**"]
rules:
  - id: no-store-to-ui
    type: forbid_edge
    from: store
    to: ui
    message: "store 不得依赖 ui"
""",
        encoding="utf-8",
    )
    rules = load_rules(str(rule_file))
    assert len(rules) == 1
    assert rules[0]["id"] == "no-store-to-ui"


# ---------------------------------------------------------------------------
# forbid_edge
# ---------------------------------------------------------------------------


def test_forbid_edge_violation() -> None:
    adjacency = {
        "src/stores/cart.ts": ["src/components/Cart.tsx"],
        "src/components/Cart.tsx": [],
    }
    layers = {
        "ui": ["src/components/**"],
        "store": ["src/stores/**"],
    }
    rules = [
        {
            "id": "no-store-to-ui",
            "type": "forbid_edge",
            "from": "store",
            "to": "ui",
            "message": "store 不得依赖 ui",
        }
    ]
    violations = check_constraints(adjacency, layers, rules)
    assert len(violations) == 1
    v = violations[0]
    assert v["rule_id"] == "no-store-to-ui"
    assert v["file"] == "src/stores/cart.ts"
    assert v["evidence"]["level"] == "derivation"


def test_forbid_edge_no_violation() -> None:
    adjacency = {
        "src/stores/cart.ts": ["src/lib/util.ts"],
        "src/lib/util.ts": [],
    }
    layers = {
        "ui": ["src/components/**"],
        "store": ["src/stores/**"],
        "lib": ["src/lib/**"],
    }
    rules = [
        {
            "id": "no-store-to-ui",
            "type": "forbid_edge",
            "from": "store",
            "to": "ui",
            "message": "store 不得依赖 ui",
        }
    ]
    violations = check_constraints(adjacency, layers, rules)
    assert violations == []


# ---------------------------------------------------------------------------
# forbid_cycle
# ---------------------------------------------------------------------------


def test_forbid_cycle_detected() -> None:
    adjacency = {
        "src/a.ts": ["src/b.ts"],
        "src/b.ts": ["src/a.ts"],
    }
    layers = {"lib": ["src/**"]}
    rules = [{"id": "no-cycle", "type": "forbid_cycle", "scope": ["lib"]}]
    violations = check_constraints(adjacency, layers, rules)
    assert len(violations) >= 1
    assert violations[0]["rule_id"] == "no-cycle"


# ---------------------------------------------------------------------------
# threshold
# ---------------------------------------------------------------------------


def test_threshold_fan_out() -> None:
    adjacency = {
        "src/big.ts": [f"src/dep_{i}.ts" for i in range(30)],
    }
    layers = {"lib": ["src/**"]}
    rules = [
        {
            "id": "max-fan-out",
            "type": "threshold",
            "metric": "fan_out",
            "max": 25,
            "scope": "lib",
        }
    ]
    violations = check_constraints(adjacency, layers, rules)
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "max-fan-out"
    assert "30" in violations[0]["evidence"]["result"]


def test_threshold_ok() -> None:
    adjacency = {"src/small.ts": ["src/a.ts"]}
    layers = {"lib": ["src/**"]}
    rules = [
        {"id": "max-fan-out", "type": "threshold", "metric": "fan_out", "max": 25, "scope": "lib"}
    ]
    violations = check_constraints(adjacency, layers, rules)
    assert violations == []


# ---------------------------------------------------------------------------
# 集成：analyze 自动附加约束违例
# ---------------------------------------------------------------------------


def test_analyze_auto_constraints(tmp_path: Path) -> None:
    import dsh_nodes

    # 构造 TS 项目：store 依赖 ui（违例）
    src = tmp_path / "src"
    (src / "stores").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "stores" / "cart.ts").write_text(
        'import { Cart } from "../components/Cart";\nexport const cart = 1;\n',
        encoding="utf-8",
    )
    (src / "components" / "Cart.tsx").write_text(
        "export const Cart = () => null;\n", encoding="utf-8"
    )

    # 写 rea_rules.yaml
    (tmp_path / "rea_rules.yaml").write_text(
        """version: 1
layers:
  ui: ["src/components/**"]
  store: ["src/stores/**"]
rules:
  - id: no-store-to-ui
    type: forbid_edge
    from: store
    to: ui
    message: "store 不得依赖 ui"
""",
        encoding="utf-8",
    )

    out = dsh_nodes.S33_rea_analyze({"target": str(tmp_path), "force": True})
    assert out["ok"] is True, out
    evidence = out["result"].get("evidence") or []
    constraint_ev = [
        e for e in evidence if (e.get("provenance") or {}).get("analysis") == "rules_engine"
    ]
    assert constraint_ev, f"未找到约束违例 evidence: {len(evidence)} 条"
    assert constraint_ev[0]["provenance"]["rule_id"] == "no-store-to-ui"
    assert "store 不得依赖 ui" in constraint_ev[0]["result"]

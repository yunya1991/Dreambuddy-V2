"""P1-5 意图 SSoT 映射表加载器。

读取 `intent_ssot_mapping.json`，提供四套意图体系（6×30 SSoT /
35型前端正典 / DreamOS IntentType 12型 / D3 task_type）的查询与映射接口。

退出条件（P1-5）：单一正典 + 映射表版本化。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_MAPPING_PATH = Path(__file__).resolve().parent / "intent_ssot_mapping.json"


def load_mapping(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载映射表（含版本号与生成时间）。"""
    p = path or _MAPPING_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def get_ssot_decision(mapping: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """返回 SSoT 决策（对话意图正典 + 策略意图正典）。"""
    m = mapping or load_mapping()
    d = m["ssot_decision"]
    return {
        "dialog_intent_ssot": d["dialog_intent_ssot"],
        "dialog_intent_ssot_version": d.get("dialog_intent_ssot_version", ""),
        "strategy_intent_ssot": d["strategy_intent_ssot"],
    }


def get_6x30_secondaries(mapping: Optional[Dict[str, Any]] = None) -> List[str]:
    """获取 6×30 SSoT 的全部 30 个二级意图。"""
    m = mapping or load_mapping()
    return m["systems"]["kernel_6x30"]["secondary_count"]


def map_6x30_to_legacy(
    primary: str, secondary: str, mapping: Optional[Dict[str, Any]] = None
) -> Dict[str, Optional[str]]:
    """6×30 SSoT 二级意图 → 35型/12型 旧体系映射。"""
    m = mapping or load_mapping()
    for row in m["mappings_6x30_to_legacy"]:
        if row["primary"] == primary and row["secondary"] == secondary:
            return {"frontend_35": row.get("frontend_35"), "dreamos_12": row.get("dreamos_12")}
    return {"frontend_35": None, "dreamos_12": None}


def map_legacy_35_to_12(
    frontend_intent: str, mapping: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """35型前端正典 → DreamOS IntentType(12型) 映射。"""
    m = mapping or load_mapping()
    for row in m["legacy_mappings_35_to_12"]:
        if row.get("frontend_35") == frontend_intent:
            return row.get("dreamos_12")
    return None


def list_unmapped_frontend(mapping: Optional[Dict[str, Any]] = None) -> List[str]:
    """列出 35型正典中在 DreamOS 无直接对应的意图。"""
    m = mapping or load_mapping()
    return list(m.get("unmapped_frontend_35", []))


def validate() -> bool:
    """校验映射表结构完整性（P1-5 退出条件验证）。"""
    m = load_mapping()
    assert m["schema_version"] == "1.0"
    assert "ssot_decision" in m
    assert "systems" in m and len(m["systems"]) >= 3
    # 6×30 SSoT 必须有 6 个一级 + 30 个二级意图
    k630 = m["systems"]["kernel_6x30"]
    assert k630["primary_count"] == 6
    assert k630["secondary_count"] == 30
    assert len(k630["secondary_by_primary"]) == 6
    total_secondary = sum(len(v) for v in k630["secondary_by_primary"].values())
    assert total_secondary == 30
    # mappings_6x30_to_legacy 应覆盖全部 30 个二级意图
    assert len(m["mappings_6x30_to_legacy"]) == 30
    # legacy_mappings_35_to_12 中的类型必须存在于对应体系
    frontend_types = set(m["systems"]["frontend_35"]["types"])
    dreamos_types = set(m["systems"]["dreamos_intent_type"]["types"])
    for row in m["legacy_mappings_35_to_12"]:
        assert row["frontend_35"] in frontend_types, row
        assert row["dreamos_12"] in dreamos_types, row
    print(
        f"[intent-ssot] validate OK: "
        f"6x30={k630['primary_count']}x{k630['secondary_count']}, "
        f"mappings_6x30_to_legacy={len(m['mappings_6x30_to_legacy'])}, "
        f"legacy_35_to_12={len(m['legacy_mappings_35_to_12'])}, "
        f"unmapped_35={len(m['unmapped_frontend_35'])}"
    )
    return True


if __name__ == "__main__":
    import sys

    ok = validate()
    print("SSoT decision:", get_ssot_decision())
    sys.exit(0 if ok else 1)

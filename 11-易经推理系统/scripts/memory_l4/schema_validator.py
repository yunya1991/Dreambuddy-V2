"""TradeCase v0.3 Schema 验证器

在 register_trade_event() 和 save_case() 中自动验证，
确保所有案例符合 v0.3 格式规范。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / ".workbuddy" / "memory_l4" / "schemas" / "trade_case.schema.json"

_schema: Optional[Dict[str, Any]] = None


def _load_schema() -> Dict[str, Any]:
    """加载 schema 定义（带缓存）"""
    global _schema
    if _schema is not None:
        return _schema
    if _SCHEMA_PATH.exists():
        _schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    else:
        _schema = _build_fallback_schema()
    return _schema


def _build_fallback_schema() -> Dict[str, Any]:
    """当 schema 文件不存在时的最小回退验证"""
    return {
        "type": "object",
        "required": [
            "case_id", "version", "system_source", "source", "ts",
            "ts_start", "symbol", "direction", "decision_outcome",
            "decision_context", "environment_snapshot", "thinking_chain",
            "evidence_chain", "quadrant", "tags", "l4_status",
        ],
        "properties": {
            "case_id": {"type": "string"},
            "version": {"type": "string", "enum": ["v0.3"]},
            "system_source": {"type": "string"},
            "source": {"type": "string"},
            "ts": {"type": "string"},
            "ts_start": {"type": "string"},
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["long", "short"]},
            "decision_outcome": {"type": "object"},
            "decision_context": {"type": "object"},
            "environment_snapshot": {"type": "object"},
            "thinking_chain": {"type": "array"},
            "evidence_chain": {"type": "object"},
            "quadrant": {"type": "object"},
            "tags": {"type": "array"},
            "l4_status": {"type": "string"},
        },
    }


def validate_case(case: Dict[str, Any], strict: bool = False) -> Tuple[bool, List[str]]:
    """验证 TradeCase 是否符合 v0.3 schema

    Args:
        case: 待验证的 TradeCase 字典
        strict: 是否启用严格模式（检查额外字段）

    Returns:
        (is_valid, error_messages)
    """
    errors: List[str] = []

    schema = _load_schema()

    # 1. 检查必填字段
    required = schema.get("required", [])
    for field in required:
        if field not in case:
            errors.append(f"缺少必填字段: {field}")

    if errors and strict:
        return False, errors

    # 2. 检查字段类型和格式
    properties = schema.get("properties", {})
    for field, value in case.items():
        if field not in properties:
            if strict and schema.get("additionalProperties") is False:
                errors.append(f"未知字段: {field}")
            continue

        prop_def = properties[field]
        expected_type = prop_def.get("type")

        # 处理 type 为列表的情况（如 ["string", "null"]）
        if isinstance(expected_type, list):
            type_matched = False
            for t in expected_type:
                if _type_match(value, t):
                    type_matched = True
                    break
            if not type_matched and value is not None:
                errors.append(f"字段 {field} 类型错误: 期望 {expected_type}, 实际 {type(value).__name__}")
        elif expected_type and not _type_match(value, expected_type):
            errors.append(f"字段 {field} 类型错误: 期望 {expected_type}, 实际 {type(value).__name__}")

        # 检查 enum
        enum_vals = prop_def.get("enum")
        if enum_vals and value not in enum_vals:
            errors.append(f"字段 {field} 值非法: {value}, 允许值: {enum_vals}")

        # 检查 pattern
        pattern = prop_def.get("pattern")
        if pattern and isinstance(value, str):
            import re
            if not re.match(pattern, value):
                errors.append(f"字段 {field} 格式错误: {value}, 期望匹配: {pattern}")

    # 3. 自定义业务规则验证
    _validate_business_rules(case, errors)

    return len(errors) == 0, errors


def _type_match(value: Any, expected: str) -> bool:
    """检查值是否符合期望类型"""
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _validate_business_rules(case: Dict[str, Any], errors: List[str]) -> None:
    """业务规则验证（超出 schema 的范围）"""

    # case_id 格式
    case_id = case.get("case_id", "")
    if case_id and not case_id.startswith("tc_"):
        errors.append(f"case_id 格式错误: {case_id}, 必须以 'tc_' 开头")

    # version 必须是 v0.3
    version = case.get("version")
    if version and version != "v0.3":
        errors.append(f"版本错误: {version}, 必须是 v0.3")

    # system_source 有效性
    valid_sources = [
        "yijing_inference", "three_screen", "martin_v15",
        "agent_a", "agent_b", "dream_os", "unknown",
    ]
    source = case.get("system_source")
    if source and source not in valid_sources:
        errors.append(f"未知 system_source: {source}")

    # quadrant 结构
    quadrant = case.get("quadrant")
    if isinstance(quadrant, dict):
        x = quadrant.get("x")
        y = quadrant.get("y")
        if x is not None and not (-1 <= x <= 1):
            errors.append(f"quadrant.x 超出范围: {x}")
        if y is not None and not (-1 <= y <= 1):
            errors.append(f"quadrant.y 超出范围: {y}")

    # evidence_chain 结构（TradingAgents 增强版，包含 analyst_refs）
        ec = case.get("evidence_chain")
        if isinstance(ec, dict):
            required_ec_keys = ["market_data_refs", "signal_refs", "strategy_refs", "historical_refs", "constraint_refs", "analyst_refs"]
            for key in required_ec_keys:
                if key not in ec:
                    # analyst_refs 是可选的（向后兼容）
                    if key == "analyst_refs":
                        continue
                    errors.append(f"evidence_chain 缺少子字段: {key}")
                else:
                    refs = ec[key]
                    if not isinstance(refs, list):
                        errors.append(f"evidence_chain.{key} 必须是数组")
                    else:
                        for i, ref in enumerate(refs):
                            if not isinstance(ref, dict):
                                errors.append(f"evidence_chain.{key}[{i}] 必须是对象")
                            elif "type" not in ref or "ref" not in ref:
                                errors.append(f"evidence_chain.{key}[{i}] 必须包含 type 和 ref 字段")

    # decision_outcome
    do = case.get("decision_outcome")
    if isinstance(do, dict):
        pnl_pct = do.get("pnl_pct")
        if pnl_pct is not None and not isinstance(pnl_pct, (int, float)):
            errors.append("decision_outcome.pnl_pct 必须是数字")

    # leverage 范围
    pi = case.get("position_info", {})
    if isinstance(pi, dict):
        lev = pi.get("leverage")
        if lev is not None and not (1 <= lev <= 125):
            errors.append(f"leverage 超出范围: {lev}, 必须在 [1, 125] 之间")


def quick_validate(case: Dict[str, Any]) -> bool:
    """快速验证，只返回是否通过"""
    is_valid, _ = validate_case(case, strict=False)
    return is_valid


def validate_file(path: Path) -> Tuple[bool, List[str]]:
    """验证文件中的 TradeCase"""
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, [f"JSON 解析错误: {e}"]
    except Exception as e:
        return False, [f"文件读取错误: {e}"]
    return validate_case(case)


def batch_validate_directory(dir_path: Path) -> Dict[str, Any]:
    """批量验证目录中的所有案例文件"""
    results = {
        "total": 0,
        "valid": 0,
        "invalid": 0,
        "errors": [],
        "details": [],
    }

    if not dir_path.exists():
        return results

    for f in sorted(dir_path.glob("*.json")):
        if "_v02_backup" in f.name:
            continue
        results["total"] += 1
        is_valid, errors = validate_file(f)
        if is_valid:
            results["valid"] += 1
        else:
            results["invalid"] += 1
            for err in errors:
                results["errors"].append(f"{f.name}: {err}")
        results["details"].append({
            "file": f.name,
            "valid": is_valid,
            "errors": errors,
        })

    return results


if __name__ == "__main__":
    import sys
    from scripts.memory_l4.paths import memory_l4_cases_dir

    cases_dir = memory_l4_cases_dir()
    print(f"批量验证目录: {cases_dir}")
    results = batch_validate_directory(cases_dir)
    print(f"总计: {results['total']}, 有效: {results['valid']}, 无效: {results['invalid']}")
    if results["errors"]:
        print("\n错误详情:")
        for err in results["errors"][:20]:
            print(f"  - {err}")
        if len(results["errors"]) > 20:
            print(f"  ... 还有 {len(results['errors']) - 20} 个错误")

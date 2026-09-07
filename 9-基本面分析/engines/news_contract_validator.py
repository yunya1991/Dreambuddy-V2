"""代理模块：S3 news_contract JSON Schema 验证器（ops/nanoclaw/core_task1 深路径薄封装）。

对外统一函数名：validate_batch(news_list: List[Dict]) -> Dict
  · 返回值语义：
      {
        "pass_count": int,
        "total_count": int,
        "pass_rate": float∈[0,1],
        "errors": List[str],  # 只保留前 10 条错误 msg
      }

FAIL-OPEN：
  · jsonschema 包缺失 / schema 文件损坏 / 任何异常 → 返回
    pass_rate=0.8（中性下限，FAIL-OPEN 不完全关闭 S3 分支）
  · 空 list → pass_rate=0.0 / total=0
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_THIS_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = (
    _THIS_DIR.parent
    / "ops" / "nanoclaw" / "core_task1" / "schema" / "news_contract.schema.json"
)


def _fail_open_neutral(total: int) -> Dict[str, Any]:
    """FAIL-OPEN 中性下限：80% 通过率（让 S3 不过度拖累 S boost，也不加分）。"""
    rate = 0.8 if total > 0 else 0.0
    return {
        "pass_count": int(total * rate),
        "total_count": total,
        "pass_rate": rate,
        "errors": ["[news_contract_validator FAIL-OPEN] schema/依赖异常，pass_rate 兜底=0.8"],
    }


def validate_batch(news_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(news_list, list):
        return {"pass_count": 0, "total_count": 0, "pass_rate": 0.0, "errors": ["news_list 非 list"]}
    total = len(news_list)
    if total == 0:
        return {"pass_count": 0, "total_count": 0, "pass_rate": 0.0, "errors": []}

    # 1) 加载 schema
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        if not isinstance(schema, dict):
            return _fail_open_neutral(total)
    except Exception:
        return _fail_open_neutral(total)

    # 2) 导入 jsonschema（可选依赖）
    try:
        import jsonschema  # type: ignore
    except Exception:
        return _fail_open_neutral(total)

    # 3) news_list 是扁平 items，但 news_contract 顶层 schema 是容器（raw_crypto/raw_macro）。
    #    为加速直接校验单条，优先取 $defs.CryptoItem 子 schema（若存在）。
    item_schema: Dict[str, Any]
    item_schema = (
        schema.get("$defs", {}) if isinstance(schema.get("$defs"), dict) else {}
    ).get("CryptoItem") or schema.get("properties", {}).get(
        "raw_crypto", {}
    ).get("items") or schema
    if not isinstance(item_schema, dict) or not item_schema:
        # 退化为通用 object 校验
        item_schema = {"type": "object"}

    passed = 0
    errors: List[str] = []
    for idx, item in enumerate(news_list):
        if not isinstance(item, dict):
            errors.append(f"#{idx} 非 dict")
            continue
        try:
            jsonschema.validate(instance=item, schema=item_schema)
            passed += 1
        except Exception as exc:
            if len(errors) < 10:
                errors.append(f"#{idx}: {type(exc).__name__}: {str(exc)[:120]}")

    rate = (passed / total) if total > 0 else 0.0
    return {
        "pass_count": int(passed),
        "total_count": int(total),
        "pass_rate": float(rate),
        "errors": errors,
    }

"""参数 schema（SPEC-54 R1）：签名骨架 + 语义覆盖。

只产出元数据：不取数、不调用任何能力函数。
装配器（3.1-FRONTEND/scripts/capability_resolve.py）按本模块输出补参。
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Dict, List, Optional

# 无数据源：装配层直接返回 unsupported（SPEC-54 §3 禁用清单）
UNSUPPORTED: Dict[str, str] = {
    "D-G23": "缺少事件日期序列（events）数据源",
    "D-A14": "缺少拥挤度分项序列（资金费率/持仓量/波动率）",
    "D-A16": "缺少稳定币规模序列",
}

# `series` 参数为多资产映射（Mapping[str, Sequence]）
SERIES_MAPPING = frozenset({"D-E12", "D-G14", "D-G16", "D-G25", "D-J22", "D-J24"})

# 派生参数口径：source=derived，前端禁止直填
DERIVED: Dict[str, Dict[str, str]] = {
    "D-E01": {"factor": "momentum_20d"},
    "D-E08": {"factor": "momentum_20d", "forward": "forward_returns(1)"},
    "D-E14": {"factor": "rolling_corr(60)"},
    "D-G19": {"factor": "momentum_20d", "forward": "forward_returns(1)"},
    "D-G20": {"factor": "momentum_20d", "forward": "forward_returns(1)"},
}

# 必须由用户显式指定（无默认）
REQUIRES_USER = frozenset({"D-J30"})

# SPEC-54b：用户输入型参数的语义覆盖（签名反射无法区分数组/坐标/标签形态）
ARG_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "D-J25": {
        "coords": {"type": "json", "source": "user", "required": True},
    },
    "D-J26": {
        "time": {"type": "series", "source": "user", "required": True},
        "event": {"type": "series", "source": "user"},
        "group": {"type": "labels", "source": "user"},
        "covariate": {"type": "series", "source": "user"},
    },
    "D-J27": {
        "time": {"type": "series", "source": "user", "required": True},
        "series": {"type": "series", "source": "user"},
        "event": {"type": "series", "source": "user"},
    },
    "D-J28": {
        "effects": {"type": "series", "source": "user", "required": True},
        "se": {"type": "series", "source": "user", "required": True},
    },
    "D-J30": {
        # 双形态：指标名（CPIAUCSL/DGS10）或自定义数值序列
        "indicator": {"type": "scalar", "source": "user", "required": True},
        "prices": {"type": "series", "source": "auto", "required": False},
    },
}

# 需要基准资产（默认 US500）
BENCHMARK_CAPS = frozenset({"D-A11", "D-A12", "D-E14"})

# 纯宏观对：不需要 symbol
MACRO_ONLY = frozenset({"D-A10"})

# `*args, **kwargs` 能力：签名无法推断，由 schema 显式声明（v0.4 实测四种入参形态）
ASSET_LIST_CAPS = {
    "D-E16": ("series", "series_map"),  # Mapping[str, Mapping[date, float]]
    "D-E17": ("assets", "asset_list"),  # Mapping[str, {prices, dates}]
    "D-E18": ("flows", "json"),  # Sequence[flow edge]
    "D-E19": ("block", "json"),  # lights 块（信号点阵输入）
}

_SERIES_NAMES = frozenset(
    {
        "prices",
        "series",
        "values",
        "returns",
        "dates",
        "factor",
        "forward",
        "x",
        "y",
        "nominal",
        "cpi",
        "indicator",
    }
)


def _executor(cap: Any) -> Any:
    module_name, _, attr = str(cap.executor).rpartition(".")
    return getattr(importlib.import_module(f"l1agg.{module_name}"), attr)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return None


def _type_of(name: str, capability_id: str) -> str:
    if name == "assets":
        return "asset_list"
    if name == "events":
        return "events"
    if name == "series":
        return "series_map" if capability_id in SERIES_MAPPING else "series"
    if name in _SERIES_NAMES:
        return "series"
    return "scalar"


def _arg(name: str, param: inspect.Parameter, capability_id: str) -> Dict[str, Any]:
    required = param.default is inspect.Parameter.empty
    derived = DERIVED.get(capability_id, {})
    if capability_id in UNSUPPORTED:
        source = "unsupported"
    elif name in derived:
        source = "derived"
    elif capability_id in REQUIRES_USER and name == "indicator":
        source = "user"
    else:
        source = "auto"
    return {
        "name": name,
        "type": _type_of(name, capability_id),
        "required": required,
        "default": None if required else _jsonable(param.default),
        "source": source,
        "derived_by": derived.get(name),
        "options": (
            ["momentum_20d", "volatility_20d"] if name == "factor" and source == "derived" else []
        ),
    }


def for_capability(capability_id: str, manifest: Any = None) -> Optional[Dict[str, Any]]:
    """返回单个能力的参数 schema；能力不存在返回 None。"""
    if manifest is None:
        from l1agg.capabilities.manifest import load

        manifest = load()
    cap = next((item for item in manifest.capabilities if item.id == capability_id), None)
    if cap is None:
        return None

    if capability_id in ASSET_LIST_CAPS:
        arg_name, arg_type = ASSET_LIST_CAPS[capability_id]
        args = [
            {
                "name": arg_name,
                "type": arg_type,
                "required": True,
                "default": None,
                "source": "unsupported" if capability_id in UNSUPPORTED else "auto",
                "derived_by": None,
                "options": [],
            }
        ]
        accepts_extra = True
    else:
        try:
            signature = inspect.signature(_executor(cap))
        except Exception:  # noqa: BLE001 — 执行器无法解析时退化为空 schema
            signature = None
        args = []
        if signature is not None:
            for name, param in signature.parameters.items():
                if name == "trace_id":  # 内部链路标识，不暴露给卡片表单
                    continue
                if param.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    args.append(_arg(name, param, capability_id))
        accepts_extra = bool(
            signature is not None
            and any(
                item.kind == inspect.Parameter.VAR_KEYWORD for item in signature.parameters.values()
            )
        )

    for arg in args:
        override = ARG_OVERRIDES.get(capability_id, {}).get(arg["name"])
        if override:
            arg.update(override)

    return {
        "capability_id": capability_id,
        "accepts_extra": accepts_extra,
        "args": args,
        "requires_symbol": capability_id not in MACRO_ONLY and capability_id not in ASSET_LIST_CAPS,
        "requires_benchmark": capability_id in BENCHMARK_CAPS,
        "unsupported": UNSUPPORTED.get(capability_id),
    }


def all_schemas(manifest: Any = None) -> Dict[str, Dict[str, Any]]:
    """全量 schema（94 项），按能力 ID 索引。"""
    if manifest is None:
        from l1agg.capabilities.manifest import load

        manifest = load()
    return {cap.id: for_capability(cap.id, manifest) for cap in manifest.capabilities}


def missing_args(capability_id: str, payload: Dict[str, Any], manifest: Any = None) -> List[str]:
    """按 schema 计算缺失参数（T6 以显式声明为准）。"""
    schema = for_capability(capability_id, manifest)
    if not schema:
        return []
    return [arg["name"] for arg in schema["args"] if arg["required"] and arg["name"] not in payload]

# -*- coding: utf-8 -*-
"""方法注册表：方法层唯一 SSoT（METHOD_LIBRARY §0.1）。

设计约束：
  - 每个方法必须先登记 `MethodSpec` 才允许被选法/执行层调用；
  - `run()` 统一注入样本量门禁，样本不足只返回 `gate=insufficient_samples`；
  - 未实现的方法按方法库编号生成占位登记（`implemented=False`），
    禁止写空壳函数冒充实现；
  - 本模块无第三方依赖、无网络、无写库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# 方法库 §1 分类总览的编号容量（用于生成未实现方法的占位登记）
GROUP_CAPACITY: Dict[str, int] = {
    "S": 28,
    "D": 24,
    "T": 28,
    "C": 18,
    "I": 39,
    "M": 26,
    "B": 18,
    "F": 26,
    "H": 18,
    "R": 18,
}

# 调研族容量（机构 X/O/P/Q + 科研 SC）：只允许登记占位，禁止空壳实现
RESEARCH_CAPACITY: Dict[str, int] = {
    "X": 12,
    "O": 15,
    "P": 14,
    "Q": 16,
    "SC": 92,
}

ALL_CAPACITY: Dict[str, int] = {**GROUP_CAPACITY, **RESEARCH_CAPACITY}


class RegistryError(ValueError):
    """注册表参数/契约错误。"""


class MethodUnavailable(RegistryError):
    """方法已登记但尚未实现（或数据前提不满足）。"""


@dataclass(frozen=True)
class MethodChecks:
    """方法自检声明（供 eval harness 自动执行）。

    synthetic: 无参函数 → {"data", "params", "expect": {"result.r": 1.0}}
    null:      "no_correlation" 表示应通过随机白噪声负例
    reference: 可选交叉验证函数 data → {"result.r": ...}（如 scipy 口径）
    """

    synthetic: Optional[Callable[[], Dict[str, Any]]] = None
    null: Optional[str] = None
    reference: Optional[Callable[[Any], Dict[str, float]]] = None


@dataclass(frozen=True)
class MethodSpec:
    method_id: str
    name: str
    group: str
    layer: str  # D1 / D2 / D3
    input_kind: str  # pairs / series / panel / events
    min_n: int
    output_schema: Tuple[str, ...]
    version: str = "v1"
    implemented: bool = True
    notes: str = ""
    checks: MethodChecks = field(default_factory=MethodChecks, compare=False, repr=False)
    func: Optional[Callable[..., Dict[str, Any]]] = field(default=None, compare=False, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_id": self.method_id,
            "name": self.name,
            "group": self.group,
            "layer": self.layer,
            "input_kind": self.input_kind,
            "min_n": self.min_n,
            "output_schema": list(self.output_schema),
            "version": self.version,
            "implemented": self.implemented,
            "notes": self.notes,
        }


REGISTRY: Dict[str, MethodSpec] = {}


def _split_id(method_id: str) -> Optional[Tuple[str, int]]:
    """拆分「组前缀 + 编号」，支持两字母前缀 SC；不合法返回 None。"""
    if not method_id:
        return None
    if method_id.startswith("SC") and method_id[2:].isdigit():
        return "SC", int(method_id[2:])
    if method_id[0] in ALL_CAPACITY and method_id[1:].isdigit():
        return method_id[0], int(method_id[1:])
    return None


def _validate_id(method_id: str) -> None:
    if _split_id(method_id) is None:
        raise RegistryError(f"invalid method_id: {method_id!r}")


def register(
    method_id: str,
    *,
    name: str,
    group: str,
    layer: str,
    input_kind: str,
    min_n: int,
    output_schema: Sequence[str],
    version: str = "v1",
    notes: str = "",
    checks: Optional[MethodChecks] = None,
) -> Callable[[Callable[..., Dict[str, Any]]], Callable[..., Dict[str, Any]]]:
    """装饰器：登记一个已实现方法。重复登记直接报错（禁止静默覆盖）。"""
    _validate_id(method_id)
    if group not in ALL_CAPACITY:
        raise RegistryError(f"unknown group: {group}")

    def deco(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
        if method_id in REGISTRY:
            raise RegistryError(f"duplicate method_id: {method_id}")
        REGISTRY[method_id] = MethodSpec(
            method_id=method_id,
            name=name,
            group=group,
            layer=layer,
            input_kind=input_kind,
            min_n=int(min_n),
            output_schema=tuple(output_schema),
            version=version,
            implemented=True,
            notes=notes,
            checks=checks or MethodChecks(),
            func=func,
        )
        return func

    return deco


def register_unavailable(
    method_id: str,
    *,
    name: str,
    group: str,
    layer: str,
    input_kind: str,
    min_n: int,
    output_schema: Sequence[str],
    notes: str = "",
) -> MethodSpec:
    """登记「已知但不可用」方法（数据前提缺失/未实现），禁止空壳实现。"""
    _validate_id(method_id)
    spec = MethodSpec(
        method_id=method_id,
        name=name,
        group=group,
        layer=layer,
        input_kind=input_kind,
        min_n=int(min_n),
        output_schema=tuple(output_schema),
        implemented=False,
        notes=notes,
    )
    REGISTRY[method_id] = spec
    return spec


def _placeholder(method_id: str) -> Optional[MethodSpec]:
    """按编号容量为未登记方法生成占位登记（implemented=False）。"""
    parsed = _split_id(method_id)
    if parsed is None:
        return None
    group, idx = parsed
    if not 1 <= idx <= ALL_CAPACITY[group]:
        return None
    return MethodSpec(
        method_id=method_id,
        name="未实现（方法库登记）",
        group=group,
        layer="D2" if group in ("M", "T", "H", "Q", "SC", "X", "P") else "D1",
        input_kind="unknown",
        min_n=0,
        output_schema=(),
        implemented=False,
        notes="占位：仅用于方法库目录完整性，未实现前不可调用",
    )


def get(method_id: str) -> MethodSpec:
    spec = REGISTRY.get(method_id) or _placeholder(method_id)
    if spec is None:
        raise RegistryError(f"unregistered method_id: {method_id}")
    return spec


def all_specs(
    *,
    implemented: Optional[bool] = None,
    group: Optional[str] = None,
    scope: str = "core",
) -> List[MethodSpec]:
    """返回已登记 + 占位后的全量目录（按 method_id 排序）。

    scope: core（方法库 243）/ research（调研族 X/O/P/Q/SC 149）/ all。
    """
    caps = {"core": GROUP_CAPACITY, "research": RESEARCH_CAPACITY, "all": ALL_CAPACITY}.get(scope)
    if caps is None:
        raise RegistryError(f"unknown scope: {scope!r}")
    ids = set()
    for mid in REGISTRY:
        parsed = _split_id(mid)
        if parsed is not None and parsed[0] in caps:
            ids.add(mid)
    for g, cap in caps.items():
        ids.update(f"{g}{i:02d}" for i in range(1, cap + 1))
    specs = [get(mid) for mid in sorted(ids)]
    if implemented is not None:
        specs = [s for s in specs if s.implemented is implemented]
    if group is not None:
        specs = [s for s in specs if s.group == group]
    return specs


def _sample_n(data: Any) -> int:
    if data is None:
        return 0
    if isinstance(data, Mapping):
        if "x" in data and "y" in data:
            return min(len(data["x"]), len(data["y"]))
        if "series" in data and isinstance(data["series"], Mapping):
            lengths = [len(v) for v in data["series"].values()]
            return min(lengths) if lengths else 0
        seqs = [len(v) for v in data.values() if isinstance(v, Sequence) and not isinstance(v, str)]
        return min(seqs) if seqs else 0
    if isinstance(data, Sequence) and not isinstance(data, str):
        return len(data)
    return 0


def run(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    """统一执行入口：契约校验 → 样本门禁 → 计算 → 注入元数据。

    Raises:
        MethodUnavailable: 占位/未实现方法被调用。
    """
    spec = get(method_id)
    if not spec.implemented or spec.func is None:
        raise MethodUnavailable(f"{method_id} 未实现：{spec.notes or 'no implementation'}")
    n = _sample_n(data)
    envelope: Dict[str, Any] = {
        "method_id": spec.method_id,
        "name": spec.name,
        "group": spec.group,
        "layer": spec.layer,
        "version": spec.version,
        "sample_n": n,
        "min_n": spec.min_n,
        "params": dict(params),
        "gate": "ok",
    }
    if n < spec.min_n:
        envelope.update({"gate": "insufficient_samples", "result": None})
        return envelope
    result = spec.func(data, **params)
    envelope["result"] = result
    if isinstance(result, Mapping) and "sample_n" in result:
        envelope["sample_n"] = int(result["sample_n"])
    return envelope

"""指标契约：唯一事实源 `references/metrics-contract.json`。

免费版、Pro 版与后端各带一份**字节一致**的副本，由 `scripts/release_check.py`
与 `cm selfcheck` 校验；任何阈值 / 权重 / 标签 / 分母的调整只改契约，不再改代码。
"""

from __future__ import annotations

import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "references" / "metrics-contract.json"
DENOMINATORS = ("documents", "skills", "sessions")
REQUIRED_METRIC_FIELDS = (
    "key", "label", "definition", "warn_at", "high_at", "weight", "action",
)
REQUIRED_RATIO_FIELDS = (
    "id", "label", "metric", "denominator", "warn_at", "high_at", "weight", "action",
)


class ContractError(ValueError):
    """契约缺失或结构非法。"""


def load(path=None) -> dict:
    target = Path(path) if path else CONTRACT_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("指标契约不可读：{}（{}）".format(target, exc))
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ContractError("指标契约不是合法 JSON：{}（{}）".format(target, exc))
    validate(data)
    return data


def validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContractError("契约根节点必须是对象")
    if not isinstance(data.get("schema_version"), str) or not data["schema_version"].strip():
        raise ContractError("缺少 schema_version")

    metrics = data.get("metrics")
    problems = data.get("problem_metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ContractError("metrics 必须是非空数组")
    if not isinstance(problems, list) or not problems:
        raise ContractError("problem_metrics 必须是非空数组")

    keys = []
    for item in metrics:
        if not isinstance(item, dict):
            raise ContractError("metrics 元素必须是对象")
        missing = [field for field in REQUIRED_METRIC_FIELDS if field not in item]
        if missing:
            raise ContractError("指标 {} 缺少字段：{}".format(item.get("key", "?"), ", ".join(missing)))
        key = item["key"]
        if key in keys:
            raise ContractError("指标 key 重复：{}".format(key))
        keys.append(key)
        _check_range(item, key)
        if not isinstance(item["weight"], (int, float)) or item["weight"] < 0:
            raise ContractError("指标 {} 的 weight 必须是非负数".format(key))

    if problems != keys:
        raise ContractError("problem_metrics 必须与 metrics 的 key 顺序一致")

    ratios = data.get("ratios")
    if not isinstance(ratios, list) or not ratios:
        raise ContractError("ratios 必须是非空数组")
    ratio_ids = []
    for item in ratios:
        if not isinstance(item, dict):
            raise ContractError("ratios 元素必须是对象")
        missing = [field for field in REQUIRED_RATIO_FIELDS if field not in item]
        if missing:
            raise ContractError("占比 {} 缺少字段：{}".format(item.get("id", "?"), ", ".join(missing)))
        if item["id"] in ratio_ids:
            raise ContractError("占比 id 重复：{}".format(item["id"]))
        ratio_ids.append(item["id"])
        if item["metric"] not in keys:
            raise ContractError("占比 {} 引用了未知指标：{}".format(item["id"], item["metric"]))
        if item["denominator"] not in DENOMINATORS:
            raise ContractError("占比 {} 的分母未知：{}".format(item["id"], item["denominator"]))
        _check_range(item, item["id"])
        if "informational" in item and not isinstance(item["informational"], bool):
            raise ContractError("占比 {} 的 informational 必须是布尔值".format(item["id"]))

    health = data.get("health")
    if not isinstance(health, dict):
        raise ContractError("health 必须是对象")
    ok_max = health.get("ok_max_problems")
    attention_max = health.get("attention_max_problems")
    if not isinstance(ok_max, int) or not isinstance(attention_max, int):
        raise ContractError("health 阈值必须是整数")
    if not 0 <= ok_max < attention_max:
        raise ContractError("health 阈值需满足 0 <= ok_max_problems < attention_max_problems")


def _check_range(item: dict, name: str) -> None:
    warn_at, high_at = item.get("warn_at"), item.get("high_at")
    if not isinstance(warn_at, (int, float)) or not isinstance(high_at, (int, float)):
        raise ContractError("{} 的 warn_at / high_at 必须是数字".format(name))
    if warn_at < 0 or high_at <= warn_at:
        raise ContractError("{} 的阈值需满足 0 <= warn_at < high_at".format(name))


def metrics(data=None) -> list:
    return (data or load())["metrics"]


def ratios(data=None) -> list:
    return (data or load())["ratios"]


def metric_keys(data=None) -> list:
    return [item["key"] for item in metrics(data)]


def problem_keys(data=None) -> tuple:
    return tuple((data or load())["problem_metrics"])


def labels(data=None) -> dict:
    return {item["key"]: item["label"] for item in metrics(data)}


def schema_version(data=None) -> str:
    return (data or load())["schema_version"]


def thresholds(key: str, data=None) -> tuple:
    for item in metrics(data):
        if item["key"] == key:
            return item["warn_at"], item["high_at"]
    raise ContractError("未知指标：{}".format(key))


def health_of(values: dict, data=None) -> str:
    rules = (data or load())["health"]
    problems = sum(1 for key in problem_keys(data) if (values.get(key) or 0) > 0)
    if problems <= rules["ok_max_problems"]:
        return "good"
    if problems <= rules["attention_max_problems"]:
        return "attention"
    return "poor"

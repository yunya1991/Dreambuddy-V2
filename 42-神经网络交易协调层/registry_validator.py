#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""42 层 registry.yaml 校验器（P1-02，本地即 CI）。

对齐 42 层 SPEC §2.4 / §21.1 接入声明与 SignalSchema v1 §2.1：
- 每个 subsystem 必填字段：name / publisher / publish / subscribe / horizon / enabled
- horizon 取值必须是 SignalSchema 合法枚举：hours | days | weeks
- publisher 适配器文件必须存在（相对 42 层根目录）

用法：python3 registry_validator.py [registry.yaml 路径]
退出码：0 = 通过；1 = 存在校验错误。
"""

import os
import sys

import yaml

_42_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_REGISTRY = os.path.join(_42_ROOT, "registry.yaml")

_REQUIRED_FIELDS = ("name", "publisher", "publish", "subscribe", "horizon", "enabled")
_VALID_HORIZONS = ("hours", "days", "weeks")

# P1-05：canonical source 枚举（DEC-28 口径）。registry name 必须属于该集合；
# 旧别名（bdsm）仅作为总线信号别名兼容，不允许作为 registry 名；
# 禁止 11-strategy（strategy 不是独立 canonical source）。
CANONICAL_SOURCES = (
    "43-strategic-extension",
    "40-cycle",
    "23-contradiction",
    "29-event",
    "11-bcrm",
    "11-bcrm-tactical",
    "11-bdsm",
    "11-washout",
    "11-event-arbitrage",
)
_FORBIDDEN_SOURCES = ("11-strategy",)


def validate_registry(path: str = _DEFAULT_REGISTRY) -> list:
    """校验 registry.yaml，返回错误信息列表（空列表 = 通过）。"""
    errors = []
    try:
        with open(path, encoding="utf-8") as f:
            reg = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001
        return ["registry 加载失败: {}".format(exc)]

    if not isinstance(reg, dict) or not isinstance(reg.get("subsystems"), list):
        return ["registry 格式非法：缺少 subsystems 列表"]

    # publisher 路径相对 registry 文件所在目录解析
    base_dir = os.path.dirname(os.path.abspath(path))

    names = set()
    for i, sub in enumerate(reg["subsystems"]):
        if not isinstance(sub, dict):
            errors.append("subsystems[{}] 非对象".format(i))
            continue
        name = sub.get("name", "subsystems[{}]".format(i))

        for field in _REQUIRED_FIELDS:
            if field not in sub:
                errors.append("{}: 缺少必填字段 {}".format(name, field))

        if "horizon" in sub and sub["horizon"] not in _VALID_HORIZONS:
            errors.append(
                "{}: horizon 非法: {}（合法值 {}）".format(
                    name, sub.get("horizon"), "/".join(_VALID_HORIZONS)
                )
            )

        if "name" in sub:
            if sub["name"] in names:
                errors.append("{}: name 重复".format(name))
            names.add(sub["name"])
            # P1-05：source 枚举一致性校验
            if sub["name"] in _FORBIDDEN_SOURCES:
                errors.append(
                    "{}: 禁止的 source（DEC-28：strategy 非独立 canonical source）".format(
                        sub["name"]
                    )
                )
            elif sub["name"] not in CANONICAL_SOURCES:
                errors.append(
                    "{}: name 不在 canonical source 枚举内（合法值 {}）".format(
                        sub["name"], "/".join(CANONICAL_SOURCES)
                    )
                )

        publisher = sub.get("publisher")
        if publisher and isinstance(publisher, str):
            abs_path = os.path.join(base_dir, publisher)
            if not os.path.exists(abs_path):
                errors.append("{}: publisher 文件不存在: {}".format(name, publisher))

        publish = sub.get("publish")
        if "publish" in sub and not isinstance(publish, list):
            errors.append("{}: publish 必须是列表".format(name))

    return errors


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_REGISTRY
    errors = validate_registry(path)
    if errors:
        print("registry 校验失败（{} 条）:".format(len(errors)))
        for e in errors:
            print("  - {}".format(e))
        return 1
    print("registry 校验通过: {}".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
配置加载器 - V15经典马丁策略专用
- 支持 include 语法合并多个配置文件
- 统一管理 V15 经典马丁策略配置
"""
import os
from pathlib import Path


def load_config(strategy_type: str = "v15") -> dict:
    """
    加载配置
    :param strategy_type: "v15"（唯一支持配置）
    :return: 合并后的配置字典
    """
    config_dir = Path(__file__).parent.parent / "config"
    common_path = config_dir / ".env.common"
    strategy_path = config_dir / ".env.v15"

    config = {}

    if common_path.exists():
        config.update(_load_env_file(common_path))

    if strategy_path.exists():
        config.update(_load_env_file(strategy_path))

    str_config = {k: str(v) for k, v in config.items()}
    os.environ.update(str_config)

    return config.copy()


def _load_env_file(filepath: Path) -> dict:
    """加载单个 .env 文件，支持 include 语法"""
    config = {}

    with open(filepath, "r") as f:
        lines = f.readlines()

    config_dir = filepath.parent

    for line in lines:
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("include "):
            included_file = line.split("include ", 1)[1].strip()
            included_path = config_dir / included_file
            if included_path.exists():
                config.update(_load_env_file(included_path))
            continue

        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            value = _parse_value(value)
            config[key] = value

    return config


def _parse_value(value: str):
    """解析环境变量值"""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() == "none":
        return None

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def get_config(key: str, default=None):
    """获取配置值"""
    return os.environ.get(key, default)


def get_config_int(key: str, default=0) -> int:
    """获取整数配置"""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_config_float(key: str, default=0.0) -> float:
    """获取浮点配置"""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def get_config_bool(key: str, default=False) -> bool:
    """获取布尔配置"""
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() == "true"


def get_config_list(key: str, delimiter=",", default=None):
    """获取列表配置"""
    val = os.environ.get(key)
    if val is None:
        return default or []
    return [item.strip() for item in val.split(delimiter) if item.strip()]


if __name__ == "__main__":
    config = load_config("v15")
    print("=== V15 经典马丁策略配置 ===")
    for k, v in sorted(config.items()):
        print(f"{k}={v}")

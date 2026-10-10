"""config.py — 配置加载与解析

SPEC 第四节 config.yaml 三段配置：
- debate: 辩论参数（轮次/裁判/超时/模型/预算）
- telegram: Bot token / 群白名单 / 发送间隔
- topic_filter: 话题黑名单

关键功能：
- YAML 加载
- env:VAR 格式的环境变量解析
- 默认值填充
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("debate.config")

ENV_PREFIX = "env:"


@dataclass
class DebateConfig:
    """辩论参数配置。"""
    max_rounds: int = 2
    judge_enabled: bool = True
    pause_timeout_minutes: float = 30.0
    models: dict = field(default_factory=lambda: {
        "debater": "qwen-turbo",
        "judge": "qwen-plus",
        "marketing": "qwen-plus",
        "quality": "qwen-plus",
    })
    budget: dict = field(default_factory=lambda: {
        "monthly_limit_yuan": 50.0,
    })


@dataclass
class TelegramConfig:
    """Telegram Bot 配置。"""
    bull_token: str = ""
    bear_token: str = ""
    judge_token: str | None = None
    allowed_chat_ids: list[int] = field(default_factory=list)
    message_interval_sec: float = 1.5


@dataclass
class TopicFilterConfig:
    """话题过滤配置。"""
    blacklist_keywords: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """应用顶层配置。"""
    debate: DebateConfig = field(default_factory=DebateConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    topic_filter: TopicFilterConfig = field(default_factory=TopicFilterConfig)


def resolve_env_value(value: str | None) -> str | None:
    """解析 env:VAR 格式的环境变量引用。

    - "env:TG_BULL_TOKEN" → os.environ["TG_BULL_TOKEN"]
    - "plain_token" → "plain_token"
    - None → None

    Raises:
        KeyError: env:VAR 但环境变量未设置
    """
    if value is None:
        return None
    if isinstance(value, str) and value.startswith(ENV_PREFIX):
        var_name = value[len(ENV_PREFIX):]
        if var_name not in os.environ:
            raise KeyError(f"环境变量未设置: {var_name}")
        return os.environ[var_name]
    return value


def _resolve_dict(data: dict) -> dict:
    """递归解析字典中的 env: 引用。"""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        elif isinstance(value, list):
            resolved[key] = [
                resolve_env_value(item) if isinstance(item, str) else item
                for item in value
            ]
        elif isinstance(value, str):
            resolved[key] = resolve_env_value(value)
        else:
            resolved[key] = value
    return resolved


def load_config(path: str) -> AppConfig:
    """从 YAML 文件加载配置，填充默认值。

    Args:
        path: YAML 配置文件路径

    Returns:
        AppConfig 实例

    Raises:
        FileNotFoundError: 文件不存在
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 解析 env: 引用
    raw = _resolve_dict(raw)

    # 构建 AppConfig，填充默认值
    debate_data = raw.get("debate", {})
    telegram_data = raw.get("telegram", {})
    topic_data = raw.get("topic_filter", {})

    debate = DebateConfig(
        max_rounds=debate_data.get("max_rounds", 2),
        judge_enabled=debate_data.get("judge_enabled", True),
        pause_timeout_minutes=debate_data.get("pause_timeout_minutes", 30.0),
        models=debate_data.get("models", DebateConfig().models),
        budget=debate_data.get("budget", DebateConfig().budget),
    )

    telegram = TelegramConfig(
        bull_token=telegram_data.get("bull_token", ""),
        bear_token=telegram_data.get("bear_token", ""),
        judge_token=telegram_data.get("judge_token"),
        allowed_chat_ids=telegram_data.get("allowed_chat_ids", []),
        message_interval_sec=telegram_data.get("message_interval_sec", 1.5),
    )

    topic_filter = TopicFilterConfig(
        blacklist_keywords=topic_data.get("blacklist_keywords", []),
    )

    return AppConfig(
        debate=debate,
        telegram=telegram,
        topic_filter=topic_filter,
    )

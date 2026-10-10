"""test_config.py — 配置加载单元测试（TDD RED phase）

测试 SPEC 第四节 config.yaml 三段配置：
- debate: max_rounds / judge_enabled / pause_timeout / models / budget
- telegram: bull_token / bear_token / judge_token / allowed_chat_ids / message_interval
- topic_filter: blacklist_keywords

关键功能：
- YAML 加载
- env:VAR 格式的环境变量解析
- 默认值填充
- 必填校验
"""
from __future__ import annotations

import os

import pytest

from core.config import (
    AppConfig, DebateConfig, TelegramConfig, TopicFilterConfig,
    load_config, resolve_env_value,
)


# ─── resolve_env_value 测试 ──────────────────────────────────────

class TestResolveEnv:
    """测试 env:VAR 格式解析。"""

    def test_resolves_env_prefix(self, monkeypatch):
        """env:VAR 格式解析为环境变量值。"""
        monkeypatch.setenv("TG_BULL_TOKEN", "123:abc")
        assert resolve_env_value("env:TG_BULL_TOKEN") == "123:abc"

    def test_plain_string_passthrough(self):
        """非 env: 前缀的字符串原样返回。"""
        assert resolve_env_value("plain_token") == "plain_token"

    def test_none_passthrough(self):
        """None 原样返回。"""
        assert resolve_env_value(None) is None

    def test_env_var_not_set_raises(self, monkeypatch):
        """env:VAR 但环境变量未设置 → 抛 KeyError。"""
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        with pytest.raises(KeyError, match="MISSING_TOKEN"):
            resolve_env_value("env:MISSING_TOKEN")


# ─── 默认值测试 ──────────────────────────────────────────────────

class TestDefaults:
    """测试各配置段的默认值。"""

    def test_debate_defaults(self):
        """DebateConfig 默认值。"""
        cfg = DebateConfig()
        assert cfg.max_rounds == 2
        assert cfg.judge_enabled is True
        assert cfg.pause_timeout_minutes == 30.0

    def test_telegram_defaults(self):
        """TelegramConfig 默认值。"""
        cfg = TelegramConfig()
        assert cfg.bull_token == ""
        assert cfg.bear_token == ""
        assert cfg.judge_token is None
        assert cfg.allowed_chat_ids == []
        assert cfg.message_interval_sec == 1.5

    def test_topic_filter_defaults(self):
        """TopicFilterConfig 默认值。"""
        cfg = TopicFilterConfig()
        assert cfg.blacklist_keywords == []


# ─── YAML 加载测试 ───────────────────────────────────────────────

class TestLoadConfig:
    """测试从 YAML 文件加载配置。"""

    def test_load_full_config(self, tmp_path, monkeypatch):
        """完整配置加载。"""
        monkeypatch.setenv("TG_BULL_TOKEN", "bull123")
        monkeypatch.setenv("TG_BEAR_TOKEN", "bear456")
        yaml_content = """
debate:
  max_rounds: 3
  judge_enabled: false
  pause_timeout_minutes: 15
  models:
    debater: qwen-turbo
    judge: qwen-plus
  budget:
    monthly_limit_yuan: 100.0

telegram:
  bull_token: "env:TG_BULL_TOKEN"
  bear_token: "env:TG_BEAR_TOKEN"
  judge_token: null
  allowed_chat_ids: [-100111, -100222]
  message_interval_sec: 2.0

topic_filter:
  blacklist_keywords: ["政治", "色情"]
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml_content, encoding="utf-8")

        cfg = load_config(str(config_path))

        # debate
        assert cfg.debate.max_rounds == 3
        assert cfg.debate.judge_enabled is False
        assert cfg.debate.pause_timeout_minutes == 15
        assert cfg.debate.models["debater"] == "qwen-turbo"

        # telegram
        assert cfg.telegram.bull_token == "bull123"
        assert cfg.telegram.bear_token == "bear456"
        assert cfg.telegram.judge_token is None
        assert cfg.telegram.allowed_chat_ids == [-100111, -100222]
        assert cfg.telegram.message_interval_sec == 2.0

        # topic_filter
        assert cfg.topic_filter.blacklist_keywords == ["政治", "色情"]

    def test_load_with_judge_token(self, tmp_path, monkeypatch):
        """judge_token 非 null 时从 env 加载。"""
        monkeypatch.setenv("TG_JUDGE_TOKEN", "judge789")
        monkeypatch.setenv("TG_BULL_TOKEN", "bull")
        monkeypatch.setenv("TG_BEAR_TOKEN", "bear")
        yaml_content = """
telegram:
  bull_token: "env:TG_BULL_TOKEN"
  bear_token: "env:TG_BEAR_TOKEN"
  judge_token: "env:TG_JUDGE_TOKEN"
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml_content, encoding="utf-8")

        cfg = load_config(str(config_path))
        assert cfg.telegram.judge_token == "judge789"

    def test_load_partial_config_uses_defaults(self, tmp_path, monkeypatch):
        """部分配置缺失时用默认值填充。"""
        monkeypatch.setenv("TG_BULL_TOKEN", "bull")
        monkeypatch.setenv("TG_BEAR_TOKEN", "bear")
        yaml_content = """
telegram:
  bull_token: "env:TG_BULL_TOKEN"
  bear_token: "env:TG_BEAR_TOKEN"
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml_content, encoding="utf-8")

        cfg = load_config(str(config_path))
        # debate 用默认值
        assert cfg.debate.max_rounds == 2
        assert cfg.debate.judge_enabled is True
        # telegram 的 allowed_chat_ids 用默认值
        assert cfg.telegram.allowed_chat_ids == []
        assert cfg.telegram.message_interval_sec == 1.5
        # topic_filter 用默认值
        assert cfg.topic_filter.blacklist_keywords == []

    def test_load_missing_file_raises(self):
        """文件不存在 → 抛 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

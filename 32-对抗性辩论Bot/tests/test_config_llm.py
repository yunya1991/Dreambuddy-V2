"""config.py LLM 段测试：env 解析、缺失降级、向后兼容。"""

from pathlib import Path

from core.config import load_config


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_llm_section_env_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DEBATE_KEY", "secret")
    monkeypatch.setenv("TEST_DEBATE_MODEL", "model-x")
    path = _write(
        tmp_path,
        """
llm:
  provider: anthropic
  base_url: https://example.invalid
  api_key: env:TEST_DEBATE_KEY
  models:
    debater: env:TEST_DEBATE_MODEL
    judge: env:TEST_DEBATE_MODEL
  timeout_sec: 30
  max_retries: 1
  max_tokens:
    debater: 1234
debate:
  max_rounds: 2
telegram:
  bull_token: dummy
  bear_token: dummy
""",
    )
    config = load_config(path)
    assert config.llm.provider == "anthropic"
    assert config.llm.api_key == "secret"
    assert config.llm.models["debater"] == "model-x"
    assert config.llm.timeout_sec == 30
    assert config.llm.max_tokens["debater"] == 1234


def test_llm_env_missing_becomes_none(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
    path = _write(
        tmp_path,
        """
llm:
  provider: auto
  api_key: env:TEST_MISSING_KEY
debate: {}
telegram:
  bull_token: dummy
  bear_token: dummy
""",
    )
    config = load_config(path)
    assert config.llm.api_key is None


def test_backward_compat_without_llm_section(tmp_path):
    path = _write(
        tmp_path,
        """
debate:
  max_rounds: 3
  models:
    debater: qwen-turbo
    judge: qwen-plus
telegram:
  bull_token: dummy
  bear_token: dummy
""",
    )
    config = load_config(path)
    assert config.llm.provider == "auto"
    assert config.llm.models["debater"] == "qwen-turbo"
    assert config.debate.max_rounds == 3

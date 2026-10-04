"""LLM 工厂 — 支持 Browser Use 兼容的多 LLM 提供商

支持的 provider：
- qwen: 阿里云通义千问（通过 OpenAI 兼容接口接入）
  ⚠️ Browser Use 官方仅推荐 qwen-vl-max，非 VL 版本 action schema 格式有 bug
  文档：https://docs.browser-use.com/open-source/supported-models#qwen-example
- openai: OpenAI GPT 系列
- anthropic: Anthropic Claude 系列
- ollama: 本地 Ollama 模型（免费但受硬件限制）
- browser_use: Browser Use 自家 BU2 模型（专为浏览器优化，付费）

设计原则：
- 工厂模式，统一 create_llm() 入口
- 配置驱动，从 config.yaml 的 llm 段读取
- 环境变量优先，避免硬编码 API key
- FAIL-OPEN：未配置 provider 时返回 None，调用方决定降级策略
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("real_env.llm_factory")


# 各 provider 的默认配置
_PROVIDER_DEFAULTS = {
    "qwen": {
        # ⚠️ Browser Use 官方文档明确：only qwen-vl-max is recommended
        # 非 VL 版本（含 qwen-max）action schema 格式有 bug
        "model": "qwen-vl-max",
        # 国际版 endpoint；国内版用 https://dashscope.aliyuncs.com/compatible-mode/v1
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        # 官方文档用 ALIBABA_CLOUD 环境变量；也兼容 DASHSCOPE_API_KEY
        "api_key_env": ["ALIBABA_CLOUD", "DASHSCOPE_API_KEY"],
        "use_vision": True,  # Qwen VL 必须启用视觉
    },
    "openai": {
        "model": "gpt-4o",
        "base_url": None,  # 用 OpenAI 默认
        "api_key_env": ["OPENAI_API_KEY"],
        "use_vision": True,
    },
    "anthropic": {
        "model": "claude-sonnet-4-6",
        "base_url": None,
        "api_key_env": ["ANTHROPIC_API_KEY"],
        "use_vision": True,
    },
    "ollama": {
        "model": "llama3.1:8b",
        "base_url": "http://localhost:11434",
        "api_key_env": [],  # Ollama 无需 API key
        "use_vision": False,
    },
    "browser_use": {
        "model": "bu-2-0",  # Browser Use 自家模型
        "base_url": None,
        "api_key_env": ["BROWSER_USE_API_KEY"],
        "use_vision": True,
    },
}


def _resolve_api_key(env_vars: list) -> Optional[str]:
    """从环境变量列表中解析 API key（按顺序尝试）。"""
    for var in env_vars:
        key = os.getenv(var)
        if key:
            return key
    return None


def create_llm(config: dict) -> Any:
    """创建 LLM 实例（Browser Use 兼容的 LangChain ChatModel）。

    Args:
        config: 顶层 config 字典，需包含 "llm" 段
                llm:
                  provider: qwen  # qwen|openai|anthropic|ollama|browser_use
                  model: qwen-vl-max  # 可选，覆盖默认
                  base_url: ...  # 可选，覆盖默认
                  api_key: ...  # 可选，覆盖环境变量
                  use_vision: true  # 可选，是否启用视觉

    Returns:
        LangChain ChatModel 实例（Browser Use Agent 可直接传入）

    Raises:
        ValueError: provider 不支持或缺少必需的 API key
        ImportError: browser_use 未安装
    """
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "qwen")

    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported: {list(_PROVIDER_DEFAULTS.keys())}"
        )

    defaults = _PROVIDER_DEFAULTS[provider]
    model = llm_cfg.get("model", defaults["model"])
    base_url = llm_cfg.get("base_url", defaults["base_url"])
    use_vision = llm_cfg.get("use_vision", defaults["use_vision"])

    # API key 解析：配置 > 环境变量
    api_key = llm_cfg.get("api_key") or _resolve_api_key(defaults["api_key_env"])

    logger.info(
        "Creating LLM: provider=%s model=%s base_url=%s use_vision=%s",
        provider, model, base_url, use_vision,
    )

    try:
        from browser_use import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "browser-use is not installed. Install with: pip install browser-use"
        ) from e

    # ------------------------------------------------------------------
    # 各 provider 的具体接入
    # ------------------------------------------------------------------
    if provider == "browser_use":
        # BU2 模型用专用 ChatBrowserUse 类
        try:
            from browser_use import ChatBrowserUse
        except ImportError:
            raise ImportError(
                "ChatBrowserUse not available. Install browser-use latest version."
            )
        if not api_key:
            raise ValueError(
                "BROWSER_USE_API_KEY is required for browser_use provider. "
                "Get it from https://cloud.browser-use.com/new-api-key"
            )
        llm = ChatBrowserUse(model=model, api_key=api_key)
        logger.info("LLM created: Browser Use BU2 model=%s", model)
        return llm

    if provider == "ollama":
        try:
            from browser_use import ChatOllama
        except ImportError:
            raise ImportError("ChatOllama not available in this browser-use version.")
        llm = ChatOllama(model=model)
        logger.info("LLM created: Ollama model=%s", model)
        return llm

    if provider == "anthropic":
        try:
            from browser_use import ChatAnthropic
        except ImportError:
            # 退化到 ChatOpenAI + Anthropic 兼容
            logger.warning(
                "ChatAnthropic not available, falling back to ChatOpenAI wrapper. "
                "Install anthropic SDK for native support."
            )
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is required for anthropic provider."
                )
            llm = ChatOpenAI(
                model=model, api_key=api_key,
                base_url=base_url or "https://api.anthropic.com/v1/",
            )
        else:
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is required for anthropic provider."
                )
            llm = ChatAnthropic(model=model, api_key=api_key)
        logger.info("LLM created: Anthropic model=%s", model)
        return llm

    # qwen 和 openai 都通过 ChatOpenAI 接入（Qwen 用 OpenAI 兼容接口）
    if provider == "qwen":
        if not api_key:
            raise ValueError(
                "ALIBABA_CLOUD (or DASHSCOPE_API_KEY) environment variable is required "
                "for qwen provider. Get it from "
                "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key"
            )
        # 国内版 base_url 切换：用户配置或默认国际版
        # 国内版：https://dashscope.aliyuncs.com/compatible-mode/v1
        # 国际版：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(
            "LLM created: Qwen model=%s base_url=%s (use_vision should be True for VL)",
            model, base_url,
        )
        return llm

    if provider == "openai":
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for openai provider.")
        kwargs = {"model": model, "api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        llm = ChatOpenAI(**kwargs)
        logger.info("LLM created: OpenAI model=%s", model)
        return llm

    # 不应该到达这里
    raise RuntimeError(f"Unhandled provider: {provider}")


def get_use_vision(config: dict) -> bool:
    """获取是否启用视觉模式（从 config 读取，供 Agent 使用）。

    Browser Use 的 Agent 接受 use_vision 参数。
    对于 Qwen VL 等视觉模型必须 True；对纯文本模型可 False。
    """
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "qwen")
    defaults = _PROVIDER_DEFAULTS.get(provider, {})
    return llm_cfg.get("use_vision", defaults.get("use_vision", True))


def validate_llm_config(config: dict) -> tuple[bool, str]:
    """校验 LLM 配置是否完整（不创建实例，仅检查）。

    Returns:
        (is_valid, message)
    """
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "qwen")

    if provider not in _PROVIDER_DEFAULTS:
        return False, f"Unsupported provider: {provider}"

    defaults = _PROVIDER_DEFAULTS[provider]
    api_key = llm_cfg.get("api_key") or _resolve_api_key(defaults["api_key_env"])

    if defaults["api_key_env"] and not api_key:
        return False, (
            f"API key not found for provider '{provider}'. "
            f"Set one of: {defaults['api_key_env']}"
        )

    return True, f"OK: provider={provider} model={llm_cfg.get('model', defaults['model'])}"

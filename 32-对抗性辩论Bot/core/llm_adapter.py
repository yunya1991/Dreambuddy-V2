"""llm_adapter.py — LLM 适配器

P0-1：将 30-真实环境交互系统/core/llm_factory.py 返回的 LangChain ChatModel
包装为 core.agents.LLMClient Protocol（async chat 接口）。

LLMClient 接口：
    async def chat(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str

LangChain ChatModel 接口：
    async def ainvoke(messages: list[BaseMessage], **kwargs) -> AIMessage
        messages 支持 SystemMessage / HumanMessage
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("debate.llm_adapter")

# 将 30-真实环境交互系统/core 加入 sys.path 以复用 llm_factory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LLM_FACTORY_DIR = _PROJECT_ROOT / "30-真实环境交互系统" / "core"
if str(_LLM_FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(_LLM_FACTORY_DIR))

from llm_factory import create_llm  # noqa: E402


class LLMAdapter:
    """将 LangChain ChatModel 适配为 LLMClient Protocol。"""

    def __init__(self, chat_model: Any):
        """
        Args:
            chat_model: LangChain ChatModel 实例（需有 async ainvoke 方法）
        """
        self.model = chat_model

    async def chat(self, system_prompt: str, user_prompt: str,
                   max_tokens: int = 600) -> str:
        """调用 LLM，返回文本响应。

        Args:
            system_prompt: 系统提示词（立场锁等）
            user_prompt: 用户提示词（话题+上下文）
            max_tokens: 最大输出 token 数

        Returns:
            LLM 输出的纯文本
        """
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.model.ainvoke(messages, max_tokens=max_tokens)
        return response.content


def create_llm_adapter(
    config: dict | None = None,
    model_name: str | None = None,
) -> LLMAdapter:
    """工厂函数：基于配置创建 LLMAdapter。

    Args:
        config: 完整 config dict（含 llm 段），符合 llm_factory 格式
                例：{"llm": {"provider": "qwen", "model": "qwen-turbo"}}
        model_name: 快捷参数，仅指定模型名（默认 qwen provider）

    Returns:
        LLMAdapter 实例

    Raises:
        ValueError: config 和 model_name 都未提供
    """
    if config is None and model_name is None:
        raise ValueError("必须提供 config 或 model_name 之一")

    if config is None:
        config = {"llm": {"provider": "qwen", "model": model_name}}

    chat_model = create_llm(config)
    logger.info("LLMAdapter 创建完成: provider=%s model=%s",
                config["llm"].get("provider"),
                config["llm"].get("model"))
    return LLMAdapter(chat_model)

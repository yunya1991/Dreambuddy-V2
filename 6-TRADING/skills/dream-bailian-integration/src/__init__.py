"""
Dream-MultiSkill 百炼集成模块
"""

from .bailian_client import BailianAPIError, BailianClient, chat, create_client, embed

__version__ = "1.0.0"
__all__ = ["BailianClient", "BailianAPIError", "create_client", "chat", "embed"]

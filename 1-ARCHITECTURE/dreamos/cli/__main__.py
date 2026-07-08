"""
Dreambuddy OS CLI — 主入口模块
"""

from __future__ import annotations

import sys

# 确保命令插件被加载
from .commands import *  # noqa: F401, F403
from .analyze_commands import *  # noqa: F401, F403
from .app import get_default_app


def main() -> int:
    """CLI 主入口"""
    app = get_default_app()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())

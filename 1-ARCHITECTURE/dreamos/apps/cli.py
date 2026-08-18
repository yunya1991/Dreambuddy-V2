"""
Dreambuddy OS — CLI 命令行工具（向后兼容入口）

新代码请使用: python -m dreamos.cli
此文件保留用于向后兼容。
"""

from __future__ import annotations

import sys


def main() -> int:
    """CLI 主入口（委托给新的 CLI 架构）"""
    from dreamos.cli import get_default_app
    from dreamos.cli.commands import *  # noqa: F401, F403
    from dreamos.cli.analyze_commands import *  # noqa: F401, F403

    app = get_default_app()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())

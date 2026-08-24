"""VersionRegistry — semver 版本号管理

注册时校验：1) semver 格式合法 2) name+version 唯一
L3 Fail-Fast：不合法或重复 → 抛异常
"""
from __future__ import annotations

import re
from typing import Dict, Optional

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class VersionRegistry:
    """semver 版本注册表"""

    def __init__(self) -> None:
        self._versions: Dict[str, str] = {}

    def register(self, name: str, version: str) -> None:
        """注册模块版本

        Raises:
            ValueError: semver 格式非法 或 name+version 已注册
        """
        if not _SEMVER_RE.match(version):
            raise ValueError(
                f"invalid version '{version}' for module '{name}': "
                f"expected semver format x.y.z"
            )
        key = f"{name}@{version}"
        if key in self._versions:
            raise ValueError(
                f"module '{name}' version '{version}' "
                f"already registered"
            )
        self._versions[key] = version

    def get_version(self, name: str) -> Optional[str]:
        """查询模块最新版本"""
        matches = [v for k, v in self._versions.items() if k.startswith(f"{name}@")]
        if not matches:
            return None
        # 返回最高版本
        return sorted(matches, key=lambda v: tuple(int(x) for x in v.split(".")))[-1]

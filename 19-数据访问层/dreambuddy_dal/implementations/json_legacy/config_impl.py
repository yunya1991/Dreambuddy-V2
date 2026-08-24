"""JsonLegacyConfigRepository（P0 内存版本管理器）"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from dreambuddy_dal.protocols.config_repo import ConfigRepository


class JsonLegacyConfigRepository(ConfigRepository):
    """P0：内存 dict 管理版本号。DB 触发器（全局唯一 is_active=1）这里用 Python 简单模拟"""

    def __init__(self):
        # {config_name: {version: {"config_data": Dict, "created_by":str, "created_at":dt,
        #                           "is_active":bool, "description":str|None,
        #                           "activated_by":str|None, "activated_at":dt|None}}}
        self._store: Dict[str, Dict[int, Dict]] = {}
        self._ver_counter: Dict[str, int] = {}

    def _next_version(self, config_name: str) -> int:
        self._ver_counter[config_name] = self._ver_counter.get(config_name, 0) + 1
        return self._ver_counter[config_name]

    def get_active_version(self, config_name: str = "global") -> Optional[Dict]:
        for _v, rec in self._store.get(config_name, {}).items():
            if rec["is_active"]:
                return dict(rec["config_data"])
        return None

    def activate_version(
        self,
        config_name: str,
        version: int,
        *,
        activated_by: str = "system",
        activated_at: Optional[datetime] = None,
    ) -> bool:
        versions = self._store.get(config_name)
        if not versions or version not in versions:
            return False
        activated_at = activated_at or datetime.now(timezone.utc)
        for v, rec in versions.items():
            if v == version:
                rec["is_active"] = True
                rec["activated_by"] = activated_by
                rec["activated_at"] = activated_at
            else:
                rec["is_active"] = False
        return True

    def get_specific_version(self, config_name: str, version: int) -> Optional[Dict]:
        versions = self._store.get(config_name, {})
        if version not in versions:
            return None
        return dict(versions[version]["config_data"])

    def create_version(
        self,
        config_name: str,
        config_data: Dict,
        *,
        created_by: str = "system",
        description: Optional[str] = None,
    ) -> int:
        self._store.setdefault(config_name, {})
        v = self._next_version(config_name)
        self._store[config_name][v] = {
            "config_data": dict(config_data),
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
            "is_active": False,
            "description": description,
            "activated_by": None,
            "activated_at": None,
        }
        return v


__all__ = ["JsonLegacyConfigRepository"]

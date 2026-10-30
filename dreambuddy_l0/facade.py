"""L0 门面本体（SPEC-C C1）：scope 注册机制 + fetch_context/settle。

不一次性迁移 34 的 11 个 scope——本包提供注册框架，34 薄壳 re-export 保持行为零变化。
"""
from typing import Any, Dict, List, Optional
from .envelope import envelope, degraded


class L0Foundation:
    """L0 数据访问抽象（scope → fetcher 注册表）。"""

    _SCOPE_REGISTRY: Dict[str, str] = {}

    def __init__(self, root: Optional[str] = None):
        self._root = root
        self._fetchers: Dict[str, Any] = {}

    def register_scope(self, scope: str, fetcher) -> None:
        """注册 scope → fetcher（新代码的扩展点）。"""
        self._fetchers[scope] = fetcher

    def list_scopes(self) -> List[str]:
        return list(self._fetchers.keys())

    def fetch_context(self, scope: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """按 scope 取原始数据。任何异常均收敛为 degraded 信封（FAIL-OPEN）。"""
        fetcher = self._fetchers.get(scope)
        if fetcher is None:
            return degraded(scope, "unknown_scope", f"unknown scope: {scope}")
        try:
            return fetcher(params or {})
        except Exception as e:  # 防御纵深
            return degraded(scope, "fetch_error", f"{type(e).__name__}: {e}")

    def settle(self, result: Optional[Dict], context: Optional[Dict] = None) -> None:
        """工作后沉淀。默认空实现，由具体门面子类覆写。"""
        return None


_default: Optional[L0Foundation] = None


def get_l0() -> L0Foundation:
    """获取默认门面单例。"""
    global _default
    if _default is None:
        _default = L0Foundation()
    return _default


def load_cle():
    """公有化入口（原 34 _load_cle，SPEC-C C1：转公有并给弃用期）。"""
    import os, sys
    cog_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "4-MEMORY", "9-工具与接口")
    if cog_path not in sys.path:
        sys.path.insert(0, cog_path)
    from cognitive_loop_entry import get_cle
    return get_cle()

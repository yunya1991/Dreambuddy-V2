"""dreambuddy_l0 — L0-P 封装层公共门面包（SPEC-C C1）。

统一信封 + scope 注册机制，供新代码使用；34 系统原文件保留为薄壳 re-export。
唯一入口：get_l0() / load_cle()。
"""
from .envelope import envelope, degraded, EnvelopeVersion
from .facade import L0Foundation, get_l0, load_cle

__all__ = ["envelope", "degraded", "EnvelopeVersion", "L0Foundation", "get_l0", "load_cle"]
__version__ = "0.1.0"

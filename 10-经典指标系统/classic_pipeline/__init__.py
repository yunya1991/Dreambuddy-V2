"""经典指标系统 C0-C8 模块化包

Phase 0 (已完成): 基础设施抽取
  - core/locks    : 22 个全局锁 + _RUNTIME_CTX + _ID_LOCK
  - core/logging  : LOG logger
  - core/runtime  : _now_ms + characterization 排他状态管理
  - core/config   : 8 个 _cfg_* 函数 + set_config() 注入
  - core/http     : CORS + guards，通过 register_hooks(app) 注册

后续阶段: C0-C8 Blueprints + agents
"""

__version__ = "0.2.0"

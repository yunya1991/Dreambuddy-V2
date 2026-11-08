"""测试环境默认写门禁配置。

生产默认写工具禁用；单元测试需要验证 record/verify 主流程，
因此在测试进程内启用写 scope 并注入 admin 主体。
"""
import os

os.environ.setdefault("COGNITIVE_MCP_WRITE_ENABLED", "true")
os.environ.setdefault("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
os.environ.setdefault("COGNITIVE_MCP_EVAL_GATE_MODE", "shadow")
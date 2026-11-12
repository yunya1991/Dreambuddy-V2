"""测试环境默认写门禁配置。

生产默认写工具禁用；单元测试需要验证 record/verify 主流程，
因此在测试进程内启用写 scope 并注入 admin 主体。
"""

import os
import tempfile

os.environ.setdefault("COGNITIVE_MCP_WRITE_ENABLED", "true")
os.environ.setdefault("COGNITIVE_MCP_DEFAULT_PRINCIPAL", "admin")
os.environ.setdefault("COGNITIVE_MCP_EVAL_GATE_MODE", "shadow")
# SPEC-33-G T-G4：测试默认写临时遥测，避免污染 4-MEMORY/data/telemetry
os.environ.setdefault(
    "COGNITIVE_SECTION_TELEMETRY_PATH",
    os.path.join(tempfile.gettempdir(), "cognitive_section_telemetry_test.jsonl"),
)

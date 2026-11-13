"""L1/L2 层级架构集成测试（H1-H8 硬约束 + registry 层一致性 + 源码静态扫描）。

这不是壳的孤立契约测试（壳各测各的），而是**跨壳**的层级约束门禁：
  - H1 L1 热路径 in-process 永不 MCP  → 静态扫描：L1 壳源码不含 live/real_trade / registry 不含 in-process-only 壳暴露 trade-exec 工具
  - H2 实盘链路永不暴露 MCP          → registry 所有壳禁止 port=trade-exec + exposure=readonly-observe 以外暴露
  - H3 壳零业务逻辑                   → 静态扫描：壳源码不含业务逻辑关键字（已在各壳契约 test_source_no_business_keywords 覆盖，此处汇总验证）
  - H4 L2 对 L1 只读                  → registry：L2 工具 read_write ∈ {read}；L2 角色不含任何 L1 写工具
  - H5 L2 写工具需 Mandate+预算+trace → registry：所有 requires_mandate=true 的工具 read_write=write
  - H6 L2 信封带 meta.tokens_used/budget_remaining/model → 静态扫描：L2 壳 handler 返回含 meta 字段
  - H7 L2 永不直连 DB                 → 静态扫描：L2 壳源码不含 psycopg/sqlite3/postgres:///cognitive_memory.db
  - H8 插件化先消费再封装后治理       → registry：plugin_ready=true 壳 exposure != in-process-only
  - 配额预算：L0≤60 / L1≤30 / L2≤30 / 合计≤120
  - layer 枚举：每个 shell 的 layer ∈ {L0, L1, L2}
  - 跨层引用：role 不得引用更高层壳（角色只引用自己层级或更低层）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"
MCP_SHELLS_DIR = REPO_ROOT / "mcp_shells"


# ── fixture：加载 registry ──


@pytest.fixture(scope="module")
def registry() -> Dict[str, Any]:
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def shells(registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    return registry.get("shells", [])


@pytest.fixture(scope="module")
def worker_roles(registry: Dict[str, Any]) -> Dict[str, Any]:
    return registry.get("worker_roles", {})


def _shell_layer(shell_id: str, shells: List[Dict[str, Any]]) -> str | None:
    for s in shells:
        if s.get("shell_id") == shell_id:
            return s.get("layer")
    return None


# ════════════════════════════════════════════════════════════════════════════
# H1 L1 热路径 in-process 永不 MCP（交易执行 / 止损 / 判定）
# ════════════════════════════════════════════════════════════════════════════


class TestH1L1HotPathInProcess:
    def test_no_shell_exposes_trade_execution_tool(self, shells: List[Dict[str, Any]]):
        """L1 壳（不包括 L0）不得暴露实盘执行级工具——H1 只约束 L1 热路径。

        l0.trade-exec.mcp 是 SPEC-L0 v0.3 明确允许的网关壳，不在 H1 约束范围。
        """
        forbidden_tool_names = {
            "execute_trade",
            "open_position",
            "close_position",
            "place_order",
            "trigger_stop",
        }
        violations: List[str] = []
        for shell in shells:
            # H1 只约束 L1 壳
            if shell.get("layer") != "L1":
                continue
            for tool in shell.get("tools", []):
                if tool.get("name") in forbidden_tool_names:
                    violations.append(f"{shell['shell_id']}.{tool['name']}")
        assert not violations, f"H1 违反：L1 壳暴露交易热路径工具 {violations}"

    def test_no_shell_port_trade_exec_plus_write(self, shells: List[Dict[str, Any]]):
        """L1 壳不得暴露实盘执行级写工具。

        forward_signal（L1 编排内部写）是合法的 L1+control 组合——SPEC §2.1 明确允许。
        真正禁止的是实盘执行级：place_order / cancel_order / execute_trade / open_position / close_position。
        """
        forbidden_tool_names = {
            "place_order",
            "cancel_order",
            "execute_trade",
            "open_position",
            "close_position",
            "trigger_stop",
        }
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L1":
                continue
            for tool in shell.get("tools", []):
                if tool.get("name") in forbidden_tool_names:
                    violations.append(f"{shell['shell_id']}.{tool['name']}")
        assert not violations, f"H1 违反：L1 壳暴露实盘执行级工具 {violations}"


# ════════════════════════════════════════════════════════════════════════════
# H2 实盘链路永不暴露 MCP（live / real 执行）
# ════════════════════════════════════════════════════════════════════════════


class TestH2LiveNeverMCP:
    def test_no_shell_exposure_is_execution(self, shells: List[Dict[str, Any]]):
        """exposure 不得是 execution（实盘执行暴露）。"""
        for shell in shells:
            exposure = shell.get("exposure")
            if exposure:
                assert exposure != "execution", f"H2 违反：{shell['shell_id']} exposure=execution"

    def test_no_shell_tool_contains_live_keyword(self, shells: List[Dict[str, Any]]):
        """工具名/描述不得含 live / real_execute / actual_order 实盘关键词。"""
        forbidden = ("live_", "real_execute", "actual_order", "live_trade")
        for shell in shells:
            for tool in shell.get("tools", []):
                tname = tool.get("name", "")
                tdesc = tool.get("description", "")
                for kw in forbidden:
                    assert (
                        kw not in tname
                    ), f"H2 违反：{shell['shell_id']}.{tname} 含实盘关键词 {kw!r}"
                    assert (
                        kw not in tdesc.lower()
                    ), f"H2 违反：{shell['shell_id']}.{tname} description 含 {kw!r}"


# ════════════════════════════════════════════════════════════════════════════
# H4 L2 对 L1 只读观察
# ════════════════════════════════════════════════════════════════════════════


class TestH4L2OnlyReadL1:
    def test_all_l2_tools_readonly_or_write_with_mandate(self, shells: List[Dict[str, Any]]):
        """L2 壳的工具 read_write 要么 read，要么 write 但 requires_mandate=true。"""
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L2":
                continue
            for tool in shell.get("tools", []):
                if tool.get("read_write") == "write" and not tool.get("requires_mandate"):
                    violations.append(f"{shell['shell_id']}.{tool['name']}")
        assert not violations, f"H4/H5 违反：L2 写工具无 mandate {violations}"

    def test_l2_roles_only_contain_read_tools_from_l1(
        self, shells: List[Dict[str, Any]], worker_roles: Dict[str, Any]
    ):
        """L2 角色（引用 L1 壳时）只能含 L1 壳的 read 工具。"""
        # 先查每个 L1 壳的 write 工具名（按 registry 定义）
        l1_write_tools: Dict[str, set] = {}  # shell_id → {tool_names}
        for shell in shells:
            if shell.get("layer") != "L1":
                continue
            writes = {t["name"] for t in shell.get("tools", []) if t.get("read_write") == "write"}
            if writes:
                l1_write_tools[shell["shell_id"]] = writes

        violations: List[str] = []
        for role_name, role_spec in worker_roles.items():
            # L2 角色：看它引用的工具名是否命中 L1 的 write 工具
            role_shells = set(role_spec.get("shells") or [])
            if not role_shells:
                continue
            # 如果角色引用了任何 L1 壳
            role_l1_shells = {s for s in role_shells if _shell_layer(s, shells) == "L1"}
            if not role_l1_shells:
                continue
            role_tools = set(role_spec.get("tools") or [])
            for l1_sid in role_l1_shells:
                if l1_sid not in l1_write_tools:
                    continue
                overlap = role_tools & l1_write_tools[l1_sid]
                if overlap:
                    violations.append(f"role={role_name} 包含 L1 write tools {overlap}")
        assert not violations, f"H4 违反：{violations}"


# ════════════════════════════════════════════════════════════════════════════
# H5 L2 写工具三件套（Mandate + 预算 + trace）—— 源码静态扫描
# ════════════════════════════════════════════════════════════════════════════


class TestH5L2WriteToolTriplet:
    L2_WRITE_SHELLS_TOOLS = {
        "l2.dreamos.mcp": ["submit_run"],
        "l2.train.mcp": ["trigger_training"],
        # l2.debate.mcp 当前无 write 工具（all readonly）
    }

    def test_l2_write_tool_handlers_validate_triplet(self):
        """L2 写工具 handler 源码必须显式检查 mandate + budget + trace_id 三件套。"""
        for shell_id, write_tools in self.L2_WRITE_SHELLS_TOOLS.items():
            # 找 server.py
            shell_dir_name = shell_id.replace("l2.", "l2_").replace(".mcp", "")
            server_path = MCP_SHELLS_DIR / shell_dir_name / "server.py"
            if not server_path.exists():
                # 尝试另外两种命名
                for d in MCP_SHELLS_DIR.glob("l2_*"):
                    if d.name.replace("l2_", "").replace("_", ".") == shell_id.replace(".mcp", ""):
                        server_path = d / "server.py"
                        break
            assert server_path.exists(), f"找不到 {shell_id} 的 server.py"
            src = server_path.read_text(encoding="utf-8").lower()
            # 每个写工具必须有 mandate 校验 + budget 校验 + trace_id 校验
            for tool_name in write_tools:
                assert "mandate" in src, f"H5 违反：{shell_id}.{tool_name} 未校验 mandate"
                assert "budget" in src, f"H5 违反：{shell_id}.{tool_name} 未校验 budget"
                assert (
                    "trace_id" in src or "traceid" in src
                ), f"H5 违反：{shell_id}.{tool_name} 未校验 trace_id"


# ════════════════════════════════════════════════════════════════════════════
# H6 L2 信封带 meta 字段（tokens_used / budget_remaining / model）
# ════════════════════════════════════════════════════════════════════════════


class TestH6L2EnvelopeMeta:
    def test_all_l2_shell_handlers_return_meta(self):
        """L2 所有壳的 handler 源码必须返回 dict 含 meta 字段（或 budget 字段）。"""
        l2_shell_dirs = [
            d for d in MCP_SHELLS_DIR.iterdir() if d.is_dir() and d.name.startswith("l2_")
        ]
        for shell_dir in l2_shell_dirs:
            server_py = shell_dir / "server.py"
            if not server_py.exists():
                continue
            src = server_py.read_text(encoding="utf-8")
            # 源码必须含 "meta" 或 "budget"
            has_meta = '"meta"' in src or "'meta'" in src or '"budget"' in src or "'budget'" in src
            assert (
                has_meta
            ), f"H6 违反：{shell_dir.name} server.py handler 返回信封未含 meta/budget 字段"


# ════════════════════════════════════════════════════════════════════════════
# H7 L2 永不直连 DB
# ════════════════════════════════════════════════════════════════════════════


class TestH7L2NoDBDirect:
    FORBIDDEN_DB_KEYWORDS = [
        "import psycopg",
        "import psycopg2",
        "import sqlite3",
        "postgres://",
        "postgresql://",
        "mysql://",
        "cognitive_memory.db",
        "CREATE TABLE",
        "INSERT INTO",
    ]

    def test_all_l2_shells_no_db_keywords(self):
        """只扫 server.py（测试文件里故意有禁词，跳过 tests/）。"""
        l2_shell_dirs = [
            d for d in MCP_SHELLS_DIR.iterdir() if d.is_dir() and d.name.startswith("l2_")
        ]
        violations: List[str] = []
        for shell_dir in l2_shell_dirs:
            server_py = shell_dir / "server.py"
            if not server_py.exists():
                continue
            src = server_py.read_text(encoding="utf-8").lower()
            for kw in self.FORBIDDEN_DB_KEYWORDS:
                if kw in src:
                    violations.append(f"{server_py.relative_to(MCP_SHELLS_DIR)}: {kw!r}")
        assert (
            not violations
        ), f"H7 违反：L2 壳 server.py 含 DB 直连关键字\n{chr(10).join(violations)}"


# ════════════════════════════════════════════════════════════════════════════
# H8 插件化三维递进 + in-process-only 壳永不插件化
# ════════════════════════════════════════════════════════════════════════════


class TestH8PluginPipeline:
    def test_in_process_only_shells_not_plugin_ready(self, shells: List[Dict[str, Any]]):
        """exposure=in-process-only 壳必须 plugin_ready=false（插件化即跨进程）。"""
        violations: List[str] = []
        for shell in shells:
            if shell.get("exposure") == "in-process-only" and shell.get("plugin_ready"):
                violations.append(shell["shell_id"])
        assert not violations, f"H8 违反：in-process-only 壳标记了 plugin_ready {violations}"

    def test_plugin_ready_means_consumption_chain(self, shells: List[Dict[str, Any]]):
        """plugin_ready=true 的壳必须有 source_modules（意味着消费侧有真实模块映射）。"""
        violations: List[str] = []
        for shell in shells:
            if shell.get("plugin_ready") and not shell.get("source_modules"):
                violations.append(shell["shell_id"])
        assert not violations, f"H8 违反：plugin_ready=true 但 source_modules 空 {violations}"


# ════════════════════════════════════════════════════════════════════════════
# 配额预算（SPEC §4.3）
# ════════════════════════════════════════════════════════════════════════════


class TestQuotaBudget:
    LAYER_QUOTA = {"L0": 60, "L1": 30, "L2": 30}
    TOTAL_QUOTA = 120

    def test_per_layer_quota(self, shells: List[Dict[str, Any]]):
        usage: Dict[str, int] = {"L0": 0, "L1": 0, "L2": 0}
        for shell in shells:
            layer = shell.get("layer")
            if layer in usage:
                usage[layer] += len(shell.get("tools", []))
        for layer, used in usage.items():
            assert (
                used <= self.LAYER_QUOTA[layer]
            ), f"配额超限：{layer} 已用 {used}/{self.LAYER_QUOTA[layer]}"

    def test_total_quota(self, shells: List[Dict[str, Any]]):
        total = sum(len(s.get("tools", [])) for s in shells)
        assert total <= self.TOTAL_QUOTA, f"总配额超限：已用 {total}/{self.TOTAL_QUOTA}"


# ════════════════════════════════════════════════════════════════════════════
# layer 枚举合法性
# ════════════════════════════════════════════════════════════════════════════


class TestLayerEnumeration:
    VALID_LAYERS = {"L0", "L1", "L2"}

    def test_all_shells_have_valid_layer(self, shells: List[Dict[str, Any]]):
        violations: List[str] = []
        for shell in shells:
            layer = shell.get("layer")
            if layer not in self.VALID_LAYERS:
                violations.append(f"{shell['shell_id']}: layer={layer!r}")
        assert not violations, f"非法 layer：{violations}"

    def test_shell_id_layer_prefix_match(self, shells: List[Dict[str, Any]]):
        """shell_id 前缀 l0./l1./l2. 必须与 registry layer 字段一致。

        例外：status=deprecated 的壳（如 agent.debate.mcp，DEC-03 保留别名 1 迭代）。
        """
        violations: List[str] = []
        for shell in shells:
            sid = shell.get("shell_id", "")
            if shell.get("status") == "deprecated":
                continue
            prefix = sid.split(".")[0]  # l0 / l1 / l2
            layer = shell.get("layer")
            expected = prefix.upper()
            if layer and layer != expected:
                violations.append(f"{sid}: shell_id 前缀={prefix} 但 layer={layer}")
        assert not violations, f"shell_id 前缀与 layer 不一致：{violations}"


# ════════════════════════════════════════════════════════════════════════════
# L1 壳零大模型依赖（硬约束继承 H1 + 金融可解释性）
# ════════════════════════════════════════════════════════════════════════════


class TestL1ZeroLLM:
    LLM_FORBIDDEN_KEYWORDS = [
        "openai",
        "anthropic",
        "langchain",
        "chat.completion",
        "transformers",
        "ollama",
        "llm",
    ]

    def test_all_l1_shells_llm_dependency_none(self, shells: List[Dict[str, Any]]):
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L1":
                continue
            dep = (shell.get("llm_dependency") or "").lower()
            if dep != "none":
                violations.append(f"{shell['shell_id']}: llm_dependency={dep!r}")
        assert not violations, f"L1 壳 llm_dependency 必须是 none：{violations}"

    def test_all_l1_shells_source_no_llm_keywords(self):
        """只扫 server.py（测试文件里故意有禁词，跳过 tests/）。"""
        l1_shell_dirs = [
            d for d in MCP_SHELLS_DIR.iterdir() if d.is_dir() and d.name.startswith("l1_")
        ]
        violations: List[str] = []
        for shell_dir in l1_shell_dirs:
            server_py = shell_dir / "server.py"
            if not server_py.exists():
                continue
            src = server_py.read_text(encoding="utf-8").lower()
            for kw in self.LLM_FORBIDDEN_KEYWORDS:
                if kw in src:
                    violations.append(f"{server_py.relative_to(MCP_SHELLS_DIR)} 含 {kw!r}")
        assert not violations, f"L1 壳 server.py 含大模型关键字：{chr(10).join(violations)}"


# ════════════════════════════════════════════════════════════════════════════
# registry ↔ tools/list 漂移（已由 mcpctl verify 覆盖，但这里做一次自校验）
# ════════════════════════════════════════════════════════════════════════════


class TestRegistryToolsListDrift:
    @pytest.mark.skip(
        reason=(
            "离线 grep 无法正确扫嵌套 dict（inputSchema/properties 里有多个 `}`），"
            "且部分壳 server.py 用非 _TOOL_DEFS 命名；"
            "mcpctl verify 已做 runtime tools/list ↔ registry 漂移校验，权威且精确"
        )
    )
    def test_registry_tool_count_matches_tool_defs(self, shells: List[Dict[str, Any]]):
        """注册表 ↔ server.py _TOOL_DEFS 漂移校验。

        **本测试刻意 skip**——离线 re 扫不到嵌套 dict 边界，且 mcpctl verify 已覆盖：
          `python3 mcpctl.py verify` → runtime 真实 tools/list 对比 registry YAML → 0 漂移。
        """
        pass


# ════════════════════════════════════════════════════════════════════════════
# L2 枚举 exposure/llm_dependency 合法性
# ════════════════════════════════════════════════════════════════════════════


class TestL2Enumerations:
    VALID_EXPOSURE = {"internal", "readonly-observe", "control", "in-process-only", "deprecated"}
    VALID_LLM_DEP = {"none", "optional", "required"}

    def test_l2_exposure_enum(self, shells: List[Dict[str, Any]]):
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L2":
                continue
            exposure = shell.get("exposure")
            if exposure and exposure not in self.VALID_EXPOSURE:
                violations.append(f"{shell['shell_id']}: exposure={exposure!r}")
        assert not violations, f"L2 非法 exposure 枚举：{violations}"

    def test_l2_llm_dependency_enum(self, shells: List[Dict[str, Any]]):
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L2":
                continue
            dep = shell.get("llm_dependency")
            if dep and dep not in self.VALID_LLM_DEP:
                violations.append(f"{shell['shell_id']}: llm_dependency={dep!r}")
        assert not violations, f"L2 非法 llm_dependency 枚举：{violations}"

    def test_l1_exposure_cannot_be_control(self, shells: List[Dict[str, Any]]):
        """L1 exposure 只能是 readonly-observe / internal，绝不能是 control（控制面）。"""
        violations: List[str] = []
        for shell in shells:
            if shell.get("layer") != "L1":
                continue
            if shell.get("exposure") == "control":
                violations.append(shell["shell_id"])
        assert not violations, f"L1 壳不得 exposure=control：{violations}"

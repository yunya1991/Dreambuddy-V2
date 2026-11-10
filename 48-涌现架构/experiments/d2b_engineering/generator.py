"""
D2-B 工程方案生成器。

输入: E6 capability_gap（architecture_gap / doc_debt / interface_mismatch）
输出: ArchitectureGraph patch + DesignRationale + BuildPlan

生成策略（确定性规则引擎，对应 SPEC §4.2「DSH subagent + 33-REA + RAG」
的本地可复现代理）：根据 gap_type 与 evidence 从预注册方案模板库中选择，
结合架构图现状定制。零执行权，只产出方案文本。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


@dataclass
class BuildPlan:
    gap_id: str
    gap_type: str
    module_name: str
    architecture_graph_patch: dict
    design_rationale: str
    steps: list[str]
    dependencies: list[str]
    novelty_note: str
    code_skeleton: str = ""

    def to_dict(self) -> dict:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "module_name": self.module_name,
            "architecture_graph_patch": self.architecture_graph_patch,
            "design_rationale": self.design_rationale,
            "steps": self.steps,
            "dependencies": self.dependencies,
            "novelty_note": self.novelty_note,
            "code_skeleton": self.code_skeleton,
        }


def _skeleton(module_name: str, rationale: str, steps: list[str], entry: str) -> str:
    """生成可编译的模块骨架（门禁检测工件，非完整实现）。"""
    step_comments = "\n".join(f"#   {s}" for s in steps)
    return (
        f'"""{module_name} — D2-B 生成方案骨架。\n\n'
        f"设计依据: {rationale}\n\n"
        f"实施步骤:\n{step_comments}\n"
        f'"""\n\n'
        f"from __future__ import annotations\n\n\n"
        f"def {entry}(*args, **kwargs):\n"
        f'    """方案入口（骨架：未实现，门禁通过后按步骤实施）。"""\n'
        f"    raise NotImplementedError(\n"
        f'        "D2-B 骨架：45 门禁通过后按 design_rationale 步骤实施"\n'
        f"    )\n"
    )


def _arch_graph() -> dict:
    path = (
        PKG_ROOT / "baselines" / "artifacts" / "d2_architecture_graph" / "architecture_graph.json"
    )
    if not path.exists():
        return {"nodes": [], "edges": []}
    return json.load(open(path))


def _existing_modules(graph: dict) -> set[str]:
    return {n["id"] for n in graph.get("nodes", []) if n.get("type") == "python_file"}


def generate(gap: dict) -> BuildPlan:
    gap_type = gap.get("gap_type", "")
    gap_id = gap.get("gap_id", "")
    evidence = gap.get("evidence", {})
    expected = gap.get("expected_value", "")

    if gap_type == "architecture_gap":
        module_name = "33-REA/ast_call_resolver.py"
        patch = {
            "add_nodes": [{"id": module_name, "type": "python_file"}],
            "add_edges": [
                {"source": module_name, "target": "ast", "kind": "import"},
                {
                    "source": module_name,
                    "target": "33-REA/architecture_graph_builder.py",
                    "kind": "call",
                },
            ],
            "upgrade_edges": {"kind": "call", "from": "name_resolution", "to": "ast_precise"},
        }
        rationale = (
            f"缺口: {evidence.get('issue', '')}。预期: {expected}。"
            "方案: 用 Python ast 模块对每个 python_file 做精确函数定义解析，"
            "call 边改为 AST 节点级绑定（消除重名假依赖），并记录运行时追踪 hook。"
        )
        steps = [
            "1. 遍历 architecture_graph 中所有 python_file 节点",
            "2. 对每个 .py 文件用 ast.parse 提取 FunctionDef/AsyncFunctionDef 的 qualified name",
            "3. call 边从「函数名匹配」升级为「qualified_name + 定义位置」精确匹配",
            "4. 统计假依赖率（重名冲突数 / 总 call 边数），目标 < 5%",
            "5. 回写 architecture_graph.json 的 call 边并加 ast_resolved 标记",
        ]
        deps = ["ast", "33-REA/architecture_graph_builder.py"]
        novelty = (
            "现有架构图仅用 os.walk + 名称匹配；本方案引入 AST 精确解析，与现有 builder 无重叠"
        )

    elif gap_type == "doc_debt":
        module_name = "0-系统文档管理/doc_coverage_checker.py"
        patch = {
            "add_nodes": [{"id": module_name, "type": "python_file"}],
            "add_edges": [
                {"source": module_name, "target": "0-系统文档管理/2-文档地图", "kind": "doc_ref"}
            ],
        }
        rationale = (
            f"缺口: {evidence.get('issue', '')}。预期: {expected}。"
            "方案: 对每个 python_file 节点检查是否存在对应 markdown_doc（同目录或 docs/ 下），"
            "输出断链清单 + 覆盖率报告；核心模块自动生成 SKILL.md 骨架。"
        )
        steps = [
            "1. 加载 architecture_graph，按目录聚合 python_file 节点",
            "2. 对每个核心目录检查是否存在 README.md / SKILL.md",
            "3. 缺失文档的核心模块生成 markdown 骨架（含 import 边摘要）",
            "4. 统计覆盖率 = 有文档的核心模块数 / 核心模块总数，目标 >= 0.9",
            "5. 断链数 = 无对应 markdown_doc 的 python_file 数，目标 = 0",
        ]
        deps = ["0-系统文档管理/2-文档地图", "architecture_graph.json"]
        novelty = "现有无文档覆盖率自动化检查；本方案新增断链检测 + 骨架生成"

    elif gap_type == "interface_mismatch":
        module_name = "33-REA/interface_signature_extractor.py"
        patch = {
            "add_nodes": [{"id": module_name, "type": "python_file"}],
            "add_edges": [
                {"source": module_name, "target": "ast", "kind": "import"},
                {
                    "source": module_name,
                    "target": "33-REA/architecture_graph_builder.py",
                    "kind": "call",
                },
            ],
        }
        rationale = (
            f"缺口: {evidence.get('issue', '')}。预期: {expected}。"
            "方案: 用 ast 提取每个公开函数的签名（name + args + return annotation），"
            "写入架构图节点的 interface_signature 字段，供 interface_mismatch 检测。"
        )
        steps = [
            "1. 对每个 python_file 节点用 ast.parse 提取公开函数（非 _ 开头）",
            "2. 记录 function name + args (name, annotation, default) + return annotation",
            "3. 将 interface_signature 字段写入 architecture_graph 对应节点",
            "4. interface_mismatch 检测: 比较 call 边两端的签名兼容性",
            "5. 输出 mismatch 清单（参数数量/类型不匹配）",
        ]
        deps = ["ast", "33-REA/architecture_graph_builder.py"]
        novelty = "现有架构图仅记录 import 边；本方案新增 AST 签名提取 + 契约校验"

    elif gap_type == "backtest_evaluator_missing":
        module_name = "45-评测系统/config_backtest_evaluator.py"
        patch = {
            "add_nodes": [{"id": module_name, "type": "python_file"}],
            "add_edges": [
                {"source": module_name, "target": "45-评测系统/evaluators", "kind": "doc_ref"},
                {
                    "source": module_name,
                    "target": "experiments/e2_hypothesis/ablation_gate.py",
                    "kind": "call",
                },
            ],
        }
        rationale = (
            f"缺口: {evidence.get('issue', evidence.get('need', ''))}。预期: {expected}。"
            "方案: 新增 config 级回测评估器，输入策略结构变体（谓词/阈值组合），"
            "输出 IS/OOS 双段指标 + 分片指标，供 ablation gate 双判据使用；"
            "评估器只读历史 K 线，不触发实盘，结果写入评测系统 artifact。"
        )
        steps = [
            "1. 定义 ConfigVariant schema（谓词列表 + 阈值 + 方向 + 持有期）",
            "2. 加载 IS/OOS 时间切分与 K 线，按变体逐笔回放（复用 14-V15 回测内核）",
            "3. 输出 IS/OOS 的胜率/盈亏比/期望/最大回撤 + 分片（按币种/时段）指标",
            "4. 与 ablation gate 双判据对接：IS 通过且 OOS 不显著退化才记为有效变体",
            "5. 结果落 45-评测系统 artifact，供 E2 的 M2 比率计算",
        ]
        deps = ["45-评测系统/evaluators", "experiments/e2_hypothesis/ablation_gate.py"]
        novelty = (
            "现有 backtest_evaluator 仅评估固定策略；本方案评估 config 级结构变体，"
            "补上 IS/OOS 双段判据，与现有评估器互补"
        )

    elif gap_type == "domain_state_series_missing":
        module_name = "4-MEMORY/9-工具与接口/domain_state_series.py"
        patch = {
            "add_nodes": [{"id": module_name, "type": "python_file"}],
            "add_edges": [
                {"source": module_name, "target": "4-MEMORY/2-交易记忆单元", "kind": "doc_ref"},
            ],
        }
        rationale = (
            f"缺口: {evidence.get('issue', evidence.get('needs', ''))}。预期: {expected}。"
            "方案: 新增域状态时序采集器，按固定窗口（如 15min）落 6 域的 psi/drift 快照，"
            "带真实时间戳与去重键，供 E3 反事实 MAE 检验使用。"
        )
        steps = [
            "1. 定义 DomainStateSeries schema（ts/domain/psi/drift/version）",
            "2. 定时任务每窗口读取各域 psi/drift 当前值并追加写入 jsonl（带幂等键）",
            "3. 写入前校验 ts 单调递增，重复窗口直接跳过",
            "4. 提供 read_window(domain, start, end) 查询接口",
            "5. 导出 E3 所需的最小窗口序列（≥N 个唯一时间戳）",
        ]
        deps = ["4-MEMORY/2-交易记忆单元", "4-MEMORY/9-工具与接口/drift_detector.py"]
        novelty = (
            "现有域状态仅有单批导出（唯一时间戳极少），本方案新增时序采集与窗口查询，"
            "使 E3 反事实从 insufficient_data 转为可判定"
        )

    else:
        module_name = f"unknown_{gap_type}_handler.py"
        patch = {"add_nodes": [], "add_edges": []}
        rationale = f"未知 gap_type={gap_type}，无预注册方案模板"
        steps = []
        deps = []
        novelty = "N/A"

    entry_by_type = {
        "architecture_gap": "resolve_calls",
        "doc_debt": "check_doc_coverage",
        "interface_mismatch": "extract_signatures",
        "backtest_evaluator_missing": "evaluate_configs",
        "domain_state_series_missing": "collect_series",
    }
    skeleton = (
        _skeleton(module_name, rationale, steps, entry_by_type.get(gap_type, "run"))
        if steps
        else ""
    )

    return BuildPlan(
        gap_id=gap_id,
        gap_type=gap_type,
        module_name=module_name,
        architecture_graph_patch=patch,
        design_rationale=rationale,
        steps=steps,
        dependencies=deps,
        novelty_note=novelty,
        code_skeleton=skeleton,
    )


def load_gaps(path: str | Path) -> list[dict]:
    gaps = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                gaps.append(json.loads(line))
    return gaps


if __name__ == "__main__":
    gaps = load_gaps(PKG_ROOT / "registry" / "capability_gaps.jsonl")
    d2b_types = {
        "architecture_gap",
        "doc_debt",
        "interface_mismatch",
        "module_missing",
        "backtest_evaluator_missing",
        "domain_state_series_missing",
    }
    for g in gaps:
        if g.get("gap_type") in d2b_types:
            plan = generate(g)
            print(f"{plan.gap_id} ({plan.gap_type}): {plan.module_name}")
            print(f"  steps: {len(plan.steps)}, deps: {plan.dependencies}")

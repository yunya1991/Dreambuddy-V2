"""TDD 测试文件采集器 — DSH 层 P0 核心数据源.

通过 AST 解析 test_*.py 文件,提取测试函数的调用链作为 node_sequence,
每个测试函数(含参数化场景)生成一条 TrainingCase,专供 DSH 层训练。

设计 (SPEC-DSH-训练数据源 v0.4 §2):
  - Python ast 模块解析 test_*.py
  - 测试函数名(去 test_ 前缀) → intent
  - 遍历 ast.Call 节点提取函数调用 → node_sequence
  - 过滤框架调用 (pytest/mock/patch/MagicMock 等)
  - 解析 @pytest.mark.parametrize 装饰器 → 多条 TrainingCase
  - assert 语句作为终节点
  - FAIL-OPEN: AST 解析异常跳过该文件

预期: 388+ 测试文件 → 800-1200 条 DSH 训练数据
"""
import ast
import os
import sys
from typing import List, Optional, Tuple, Dict, Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# ============================================================
# 默认扫描目录配置 (SPEC v0.4 §2.2)
# ============================================================

DEFAULT_TEST_DIRECTORIES = [
    ("11-易经推理系统/tests", "yijing"),
    ("11-易经推理系统/scripts/memory_l4/tests", "yijing_l4"),
    ("23-四层闭环自进化交易架构/tests", "evolution"),
    ("23-四层闭环自进化交易架构/dreambuddy_evolution/tests", "evolution_core"),
    ("33-REA逆向解析工程/tests", "rea"),
    ("34-前端应用训练系统/tests", "training_system"),
]

# 配额分配 (SPEC v0.4 §2.6)
QUOTA = {
    "yijing": 0.25,
    "yijing_l4": 0.20,
    "evolution": 0.25,
    "evolution_core": 0.10,
    "rea": 0.15,
    "training_system": 0.15,
}

# 框架调用前缀过滤 (SPEC v0.4 §2.4)
FRAMEWORK_PREFIXES = (
    "pytest",
    "mock",
    "patch",
    "MagicMock",
    "tmp_path",
    "fixture",
    "unittest",
    "importlib",
    "sys.",
    "os.",
    "tempfile",
    "shutil",
    "textwrap",
    "unittest",
    "self.",
    "cls.",
    "print",
    "open(",
    "len(",
    "range(",
    "str(",
    "int(",
    "float(",
    "list(",
    "dict(",
    "set(",
    "bool(",
    "any(",
    "all(",
    "isinstance(",
    "getattr(",
    "setattr(",
    "hasattr(",
    "type(",
    "id(",
    "abs(",
    "max(",
    "min(",
    "sum(",
    "sorted(",
    "enumerate(",
    "zip(",
    "map(",
    "filter(",
    "format(",
    "repr(",
    "dir(",
    "vars(",
    "super(",
)

# 测试框架断言方法前缀 (unittest.TestCase 方法)
ASSERT_METHOD_PREFIXES = (
    "assert",
)


def _get_call_name(node) -> str:
    """从 ast.Call.func 提取调用名。

    支持简单名 (Name) 和属性链 (Attribute)。
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # 递归获取属性链: a.b.c → "a.b.c"
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        return ".".join(parts)
    return ""


def _get_assert_description(node: ast.Assert) -> str:
    """从 ast.Assert 提取简短描述。"""
    try:
        if isinstance(node.test, ast.Call):
            name = _get_call_name(node.test.func)
            # assertEqual(x, y) → "equal"
            for keyword in ("Equal", "NotEqual", "True", "False",
                            "Is", "IsNot", "IsNone", "IsNotNone",
                            "In", "NotIn", "IsInstance", "NotIsInstance",
                            "Greater", "Less", "GreaterEqual", "LessEqual",
                            "AlmostEqual", "NotAlmostEqual", "CountEqual",
                            "Raises", "Warns", "Logs"):
                if keyword.lower() in name.lower():
                    return keyword.lower()
            return name.lower() if name else "true"
        elif isinstance(node.test, ast.Compare):
            # 比较断言: x == y, x < y, etc.
            ops = []
            for op in node.test.ops:
                if isinstance(op, ast.Eq):
                    ops.append("equal")
                elif isinstance(op, ast.NotEq):
                    ops.append("not_equal")
                elif isinstance(op, ast.Lt):
                    ops.append("less")
                elif isinstance(op, ast.LtE):
                    ops.append("less_equal")
                elif isinstance(op, ast.Gt):
                    ops.append("greater")
                elif isinstance(op, ast.GtE):
                    ops.append("greater_equal")
                elif isinstance(op, ast.Is):
                    ops.append("is")
                elif isinstance(op, ast.IsNot):
                    ops.append("is_not")
                elif isinstance(op, ast.In):
                    ops.append("in")
                elif isinstance(op, ast.NotIn):
                    ops.append("not_in")
                else:
                    ops.append("compare")
            return "_".join(ops) if ops else "compare"
        elif isinstance(node.test, ast.BoolOp):
            return "boolean"
        elif isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
            return "not"
        else:
            return "true"
    except Exception:
        return "true"


def _is_framework_call(name: str) -> bool:
    """判断是否为框架调用 (应过滤掉)。"""
    if not name:
        return True
    for prefix in FRAMEWORK_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _is_test_function(node: ast.FunctionDef) -> bool:
    """判断是否为测试函数 (test_ 前缀)。"""
    return node.name.startswith("test_")


def _is_parametrize_decorator(decorator) -> bool:
    """判断是否为 @pytest.mark.parametrize 装饰器。"""
    try:
        # @pytest.mark.parametrize(...)
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Attribute):
                if func.attr == "parametrize":
                    return True
                # 可能是 mark.parametrize
                if isinstance(func.value, ast.Attribute) and func.value.attr == "mark":
                    return True
        return False
    except Exception:
        return False


def _extract_parametrize_cases(decorator) -> Optional[Tuple[List[str], List[Tuple]]]:
    """从 @pytest.mark.parametrize 提取参数名和场景列表。

    Returns:
        (param_names, cases) 或 None
        param_names: ["cont", "conf", "strength", ...]
        cases: [(0.75, 0.70, 0.0, 0.73, 0.0), ...]
    """
    try:
        if not isinstance(decorator, ast.Call):
            return None

        args = decorator.args
        if len(args) < 2:
            return None

        # 第一个参数: 参数名 (字符串或逗号分隔)
        names_node = args[0]
        if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
            param_names = [n.strip() for n in names_node.value.split(",")]
        else:
            return None

        # 第二个参数: 场景列表 (list of tuples)
        cases_node = args[1]
        if isinstance(cases_node, ast.List) or isinstance(cases_node, ast.Tuple):
            cases = []
            for elt in cases_node.elts:
                if isinstance(elt, ast.Tuple):
                    case_values = []
                    for e in elt.elts:
                        val = _extract_literal_value(e)
                        case_values.append(val)
                    cases.append(tuple(case_values))
                elif isinstance(elt, ast.Constant):
                    cases.append((elt.value,))
                else:
                    val = _extract_literal_value(elt)
                    cases.append((val,))
            if cases:
                return param_names, cases
        return None
    except Exception:
        return None


def _extract_literal_value(node) -> Any:
    """从 AST 节点提取字面值。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = _extract_literal_value(node.operand)
        if isinstance(operand, (int, float)):
            return -operand
        return operand
    if isinstance(node, ast.List):
        return [_extract_literal_value(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_extract_literal_value(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {str(_extract_literal_value(k)): _extract_literal_value(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        name = _get_call_name(node)
        return name
    if node is None:
        return None
    return None


def _extract_calls_from_function(func_node: ast.FunctionDef) -> Tuple[List[str], List[str]]:
    """从测试函数体按源码顺序提取调用链和断言描述。

    遍历语句块,提取 Call/Assign/If/For/While/Assert 节点,
    保持源码执行顺序,增加 node_sequence 长度和多样性。

    Returns:
        (call_chain, assert_descs)
        call_chain: 按源码顺序的节点列表 (含调用+赋值+分支+循环)
        assert_descs: 断言描述列表
    """
    call_chain = []
    assert_descs = []

    def _walk_stmts(stmts):
        """递归遍历语句块,保持源码顺序。"""
        for stmt in stmts:
            if isinstance(stmt, ast.Assign):
                # 赋值: x = expr → assign_x + 内部调用
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        call_chain.append(f"assign_{target.id}")
                # 赋值表达式内的调用
                _extract_calls_from_expr(stmt.value, call_chain)
            elif isinstance(stmt, ast.AugAssign):
                # +=/-= 等
                if isinstance(stmt.target, ast.Name):
                    call_chain.append(f"augassign_{stmt.target.id}")
                _extract_calls_from_expr(stmt.value, call_chain)
            elif isinstance(stmt, ast.Expr):
                # 表达式语句 (如函数调用)
                _extract_calls_from_expr(stmt.value, call_chain)
            elif isinstance(stmt, ast.Assert):
                desc = _get_assert_description(stmt)
                assert_descs.append(desc)
            elif isinstance(stmt, ast.If):
                # if 分支
                call_chain.append("if_branch")
                _extract_calls_from_expr(stmt.test, call_chain)
                _walk_stmts(stmt.body)
                if stmt.orelse:
                    call_chain.append("else_branch")
                    _walk_stmts(stmt.orelse)
            elif isinstance(stmt, ast.For):
                call_chain.append("for_loop")
                _walk_stmts(stmt.body)
                if stmt.orelse:
                    _walk_stmts(stmt.orelse)
            elif isinstance(stmt, ast.While):
                call_chain.append("while_loop")
                _walk_stmts(stmt.body)
                if stmt.orelse:
                    _walk_stmts(stmt.orelse)
            elif isinstance(stmt, ast.With):
                call_chain.append("with_block")
                _walk_stmts(stmt.body)
            elif isinstance(stmt, ast.Return):
                call_chain.append("return")
                _extract_calls_from_expr(stmt.value, call_chain)
            elif isinstance(stmt, ast.Try):
                call_chain.append("try_block")
                _walk_stmts(stmt.body)
                for handler in stmt.handlers:
                    call_chain.append("except_handler")
                    _walk_stmts(handler.body)
                if stmt.orelse:
                    _walk_stmts(stmt.orelse)
                if stmt.finalbody:
                    call_chain.append("finally_block")
                    _walk_stmts(stmt.finalbody)

    def _extract_calls_from_expr(expr, chain: list):
        """从表达式中提取业务调用 (非框架调用)。"""
        if expr is None:
            return
        for node in ast.walk(expr):
            if isinstance(node, ast.Call):
                name = _get_call_name(node.func)
                if name and not _is_framework_call(name):
                    # 断言方法过滤
                    if "." in name:
                        last_part = name.split(".")[-1]
                        if last_part.startswith("assert"):
                            assert_descs.append(_get_assert_description_from_method(last_part))
                            continue
                    chain.append(name)

    _walk_stmts(func_node.body)
    return call_chain, assert_descs


def _get_assert_description_from_method(method_name: str) -> str:
    """从断言方法名提取描述。"""
    name = method_name
    if name.startswith("assert"):
        name = name[6:]
    return name.lower() if name else "true"


class TddTestCollector(TrainingDataProvider):
    """TDD 测试文件采集器 — DSH 层 P0 核心数据源。

    通过 AST 解析 test_*.py 文件提取测试调用链,
    每个测试函数(含参数化场景)生成一条 TrainingCase。
    """

    def __init__(self, scan_dirs: Optional[List[Tuple[str, str]]] = None):
        """初始化采集器。

        Args:
            scan_dirs: [(目录路径, 域标签)] 列表。
                       None 时使用 DEFAULT_TEST_DIRECTORIES。
        """
        if scan_dirs is None:
            # 默认目录: 相对 PROJECT_ROOT 解析
            self.scan_dirs = []
            for rel_path, domain in DEFAULT_TEST_DIRECTORIES:
                abs_path = os.path.join(_PROJECT_ROOT, rel_path)
                if os.path.isdir(abs_path):
                    self.scan_dirs.append((abs_path, domain))
        else:
            self.scan_dirs = scan_dirs

    def get_source_name(self) -> str:
        return "tdd_test"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从测试文件采集训练案例。

        先扫描所有目录,再按 QUOTA 比例公平采样,确保各域都有代表。
        过滤 node_sequence 为空的 case (无训练价值)。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳 (可选,暂不实现)

        Returns:
            训练案例列表 (FAIL-OPEN)
        """
        if not self.scan_dirs:
            return []

        # 第1步: 收集所有域的 cases
        domain_cases_map: Dict[str, List[TrainingCase]] = {}
        for dir_path, domain in self.scan_dirs:
            domain_cases = self._collect_from_dir(dir_path, domain, 0)
            # 过滤空 node_sequence
            domain_cases = [c for c in domain_cases if len(c.actions) > 0]
            if domain_cases:
                domain_cases_map[domain] = domain_cases

        if not domain_cases_map:
            return []

        # 第2步: 按 QUOTA 比例分配 limit
        total_weight = sum(QUOTA.get(d, 0.1) for d in domain_cases_map.keys())
        if total_weight == 0:
            total_weight = 1.0

        cases: List[TrainingCase] = []
        remaining = limit
        domains_sorted = sorted(domain_cases_map.keys(),
                               key=lambda d: QUOTA.get(d, 0.1), reverse=True)

        for domain in domains_sorted:
            weight = QUOTA.get(domain, 0.1) / total_weight
            quota = int(limit * weight)
            domain_data = domain_cases_map[domain]
            # 如果该域数据不足配额,取全部;否则截断
            sampled = domain_data[:quota] if len(domain_data) > quota else domain_data
            cases.extend(sampled)
            remaining -= len(sampled)

        # 如果还有剩余配额,从最大域补充
        if remaining > 0 and cases:
            for domain in domains_sorted:
                domain_data = domain_cases_map[domain]
                existing = len([c for c in cases if c.metadata.get("domain") == domain])
                extra = domain_data[existing:existing + remaining]
                if extra:
                    cases.extend(extra)
                    remaining -= len(extra)
                if remaining <= 0:
                    break

        return cases[:limit]

    def _collect_from_dir(
        self, dir_path: str, domain: str, quota: int
    ) -> List[TrainingCase]:
        """扫描目录下 test_*.py 文件并采集 TrainingCase。

        扫描所有文件（不提前截断），quota 仅作为软目标。
        FAIL-OPEN: 任何异常返回空列表。
        """
        cases: List[TrainingCase] = []

        if not os.path.isdir(dir_path):
            return cases

        try:
            test_files = sorted([
                os.path.join(dir_path, f)
                for f in os.listdir(dir_path)
                if f.startswith("test_") and f.endswith(".py")
            ])
        except Exception:
            return cases

        for file_path in test_files:
            try:
                file_cases = self._parse_test_file(file_path, domain)
                cases.extend(file_cases)
            except Exception:
                # FAIL-OPEN: 跳过该文件
                continue

        return cases

    def _parse_test_file(
        self, file_path: str, domain: str
    ) -> List[TrainingCase]:
        """AST 解析单个测试文件,提取 TrainingCase。

        Returns:
            训练案例列表 (可能为空)
        """
        cases: List[TrainingCase] = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return cases

        if not source.strip():
            return cases  # 空文件

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return cases  # 语法错误,跳过
        except Exception:
            return cases  # 其他解析错误

        file_name = os.path.basename(file_path)
        # 从文件名提取模块前缀: test_score_b.py → score_b
        module_prefix = file_name
        if module_prefix.startswith("test_"):
            module_prefix = module_prefix[5:]
        if module_prefix.endswith(".py"):
            module_prefix = module_prefix[:-3]

        # 遍历 AST 提取测试函数和测试类 (只处理顶层,避免重复)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and _is_test_function(node):
                # 顶层测试函数
                case_list = self._build_cases_from_function(
                    node, module_prefix, domain, file_path, class_name=None
                )
                cases.extend(case_list)

            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                # 测试类
                class_name = node.name
                if class_name.startswith("Test"):
                    class_name = class_name[4:] if len(class_name) > 4 else class_name
                # 类名转 snake_case: ExitManager → exit_manager
                class_name = self._to_snake_case(class_name)

                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and _is_test_function(item):
                        case_list = self._build_cases_from_function(
                            item, module_prefix, domain, file_path, class_name=class_name
                        )
                        cases.extend(case_list)

        return cases

    def _build_cases_from_function(
        self,
        func_node: ast.FunctionDef,
        module_prefix: str,
        domain: str,
        file_path: str,
        class_name: Optional[str] = None,
    ) -> List[TrainingCase]:
        """从测试函数构建 TrainingCase 列表。

        支持参数化: @pytest.mark.parametrize 生成多条 case。
        """
        cases: List[TrainingCase] = []

        # 函数名去 test_ 前缀 (保留下划线)
        func_name = func_node.name
        if func_name.startswith("test_"):
            func_name = func_name[5:]

        # 构造 intent
        if class_name:
            intent = f"{class_name}.{func_name}"
        else:
            intent = func_name

        # 提取调用链和断言
        call_chain, assert_descs = _extract_calls_from_function(func_node)

        # 检查参数化装饰器
        parametrize_data = None
        for decorator in func_node.decorator_list:
            if _is_parametrize_decorator(decorator):
                parametrize_data = _extract_parametrize_cases(decorator)
                break

        if parametrize_data:
            # 参数化: 每个场景生成一条 case
            param_names, param_cases = parametrize_data
            for idx, case_values in enumerate(param_cases):
                # 构造参数描述
                param_desc = ", ".join(
                    f"{name}={val}" for name, val in zip(param_names, case_values)
                )

                # 参数附加到 node_sequence 节点
                node_seq = []
                for call in call_chain:
                    if "(" in call:
                        node_seq.append(call)  # 已有参数
                    else:
                        node_seq.append(f"{call}({param_desc})")
                # 添加 assert 终节点
                for desc in assert_descs:
                    node_seq.append(f"assert_{desc}")

                cases.append(TrainingCase(
                    intent=intent,
                    actions=node_seq,
                    outcome_text="pass",
                    learned=[
                        f"param_case_{idx}",
                        f"param_count={len(param_cases)}",
                        f"domain={domain}",
                    ],
                    layer_tags=["DSH"],
                    quality="B",
                    confidence=0.5,
                    source=f"tdd:{os.path.basename(file_path)}",
                    metadata={
                        "outcome": "success",  # 测试通过 = 决策序列有效 (ground truth)
                        "domain": domain,
                        "file": file_path,
                        "func": func_node.name,
                        "parametrize": True,
                        "param_index": idx,
                        "param_names": param_names,
                        "param_values": list(case_values),
                        "node_count": len(node_seq),
                    },
                ))
        else:
            # 非参数化: 1条 case
            node_seq = list(call_chain)
            for desc in assert_descs:
                node_seq.append(f"assert_{desc}")

            cases.append(TrainingCase(
                intent=intent,
                actions=node_seq,
                outcome_text="pass",
                learned=[
                    f"domain={domain}",
                    f"node_count={len(node_seq)}",
                ],
                layer_tags=["DSH"],
                quality="B",
                confidence=0.5,
                source=f"tdd:{os.path.basename(file_path)}",
                metadata={
                    "outcome": "success",  # 测试通过 = 决策序列有效 (ground truth)
                    "domain": domain,
                    "file": file_path,
                    "func": func_node.name,
                    "parametrize": False,
                    "node_count": len(node_seq),
                },
            ))

        return cases

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """CamelCase → snake_case。

        ExitManager → exit_manager
        ScoreBEventBoost → score_b_event_boost
        """
        if not name:
            return name
        result = []
        for i, c in enumerate(name):
            if c.isupper():
                if i > 0 and (name[i - 1].islower() or
                             (i + 1 < len(name) and name[i + 1].islower())):
                    result.append("_")
                result.append(c.lower())
            else:
                result.append(c)
        return "".join(result)

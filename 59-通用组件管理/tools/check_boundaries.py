#!/usr/bin/env python3
"""独立性闸门 G1–G7（SPEC-通用组件管理-架构重构 v0.2 §8）。

用法:
    python3 tools/check_boundaries.py              # 全量检查
    python3 tools/check_boundaries.py --json       # 机器可读
    python3 tools/check_boundaries.py --rule G3    # 只跑一条规则

退出码:
    0 全部通过（SKIP 不算失败） / 1 存在违规 / 2 契约缺失或环境不满足

P2 迁移前（components/ 不存在）:
    G1/G4–G7 记为 SKIP；G2/G3 按现有布局扫描，输出改造前违规基线。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺依赖时给出可执行提示
    print("E_ENV：需要 PyYAML（python3 -m pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

try:
    from jsonschema import ValidationError
    from jsonschema import validate as jsonschema_validate
except ImportError:  # pragma: no cover - 无 jsonschema 时降级为必填字段检查
    ValidationError = None
    jsonschema_validate = None

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
COMPONENTS = ROOT / "components"
KERNEL = ROOT / "kernel"

_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_yaml(path: Path):
    if not path.is_file():
        raise SystemExit("E_CONTRACT：缺少 {}".format(rel(path)))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("E_CONTRACT：{} 顶层必须是对象".format(rel(path)))
    return data


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i):
            out.append("(?:/.*)?")
            i += 3
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    compiled = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def is_allowed(path: Path, patterns) -> bool:
    target = rel(path)
    return any(glob_to_regex(p).match(target) for p in patterns or [])


class RuleResult:
    def __init__(self, rule_id: str, title: str) -> None:
        self.rule_id = rule_id
        self.title = title
        self.status = "pass"
        self.note = ""
        self.violations: list[dict] = []

    def fail(self, path: Path, message: str, line: int = 0) -> None:
        self.status = "fail"
        self.violations.append({"file": rel(path), "line": line, "message": message})

    def skip(self, note: str) -> None:
        if self.status != "fail":
            self.status = "skip"
            self.note = note

    def as_dict(self) -> dict:
        return {
            "rule": self.rule_id,
            "title": self.title,
            "status": self.status,
            "note": self.note,
            "violations": self.violations,
        }


class Component:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.manifest = None
        manifest_path = path / "component.yaml"
        if manifest_path.is_file():
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            self.manifest = data if isinstance(data, dict) else {}


def discover_components() -> list[Component]:
    if not COMPONENTS.is_dir():
        return []
    return [
        Component(p)
        for p in sorted(COMPONENTS.iterdir())
        if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"
    ]


def iter_scan_files(meta: dict):
    suffixes = tuple(meta.get("scan_suffixes") or (".py",))
    exclude_dirs = set(meta.get("exclude_dirs") or ())
    exclude_roots = set(meta.get("exclude_roots") or ())
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        parts = path.relative_to(ROOT).parts
        if parts[0] in exclude_roots:
            continue
        if any(part in exclude_dirs for part in parts[:-1]):
            continue
        yield path


def rule_matches_line(rule: dict, line: str) -> bool:
    kind = rule.get("match")
    if kind == "literal":
        return rule["pattern"] in line
    if kind == "regex":
        return re.search(rule["pattern"], line) is not None
    if kind == "literal_set":
        return any(p in line for p in rule.get("patterns") or [])
    return False


def import_targets(text: str):
    """返回 (import 根模块名, 解析错误)。"""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], "AST 解析失败：{}".format(exc.msg)
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module.split(".")[0])
    return targets, None


def read_frontmatter(path: Path) -> dict:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            data = yaml.safe_load("\n".join(lines[1:index]))
            return data if isinstance(data, dict) else {}
    return {}


def component_aliases(comp: Component) -> set[str]:
    """目录名 + component.yaml name + SKILL.md 的 name/slug（仅 ASCII 标识符）。"""
    manifest = comp.manifest or {}
    aliases = {comp.name, comp.name.replace("-", "_")}
    candidates = [str(manifest.get("name") or "")]
    skill_dir = comp.path / str(manifest.get("skill_dir") or "skill")
    front = read_frontmatter(skill_dir / "SKILL.md")
    candidates.extend(str(front.get(key) or "") for key in ("name", "slug"))
    for value in candidates:
        if re.fullmatch(r"[a-z][a-z0-9_-]*", value):
            aliases.add(value)
            aliases.add(value.replace("-", "_"))
    return aliases


def check_component_refs(components: list[Component]) -> RuleResult:
    result = RuleResult("G1", "组件内不得引用其他组件")
    if not components:
        result.skip("components/ 尚未迁移（P2），无组件可检")
        return result
    aliases = {comp.name: component_aliases(comp) for comp in components}
    for comp in components:
        own = aliases[comp.name]
        foreign = set()
        for other_comp in components:
            if other_comp.name != comp.name:
                foreign |= aliases[other_comp.name]
        others = sorted(foreign - own)
        for path in sorted(comp.path.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            targets, error = import_targets(text)
            if error:
                result.fail(path, error)
                continue
            for name in targets:
                if name in others:
                    result.fail(path, "import {name} 跨组件".format(name=name))
            for other in others:
                for marker in ("components/" + other, "skills/" + other):
                    if marker in text:
                        result.fail(path, "字符串写死跨组件路径 {marker}".format(marker=marker))
    return result


def check_paths(cfg: dict) -> RuleResult:
    result = RuleResult("G2", "禁止写死绝对路径")
    rules = [r for r in cfg.get("rules") or [] if r.get("gate") == "G2"]
    for path in iter_scan_files(cfg.get("meta") or {}):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule in rules:
                if is_allowed(path, rule.get("allow_globs")):
                    continue
                if rule_matches_line(rule, line):
                    message = "{} 命中 {}".format(rule["id"], rule.get("pattern"))
                    result.fail(path, message, lineno)
    return result


def check_forbidden_refs(cfg: dict) -> RuleResult:
    result = RuleResult("G3", "禁止引用黑名单条目")
    rules = [r for r in cfg.get("rules") or [] if r.get("gate") == "G3"]
    for path in iter_scan_files(cfg.get("meta") or {}):
        text = path.read_text(encoding="utf-8", errors="replace")
        for rule in rules:
            if is_allowed(path, rule.get("allow_globs")):
                continue
            if rule.get("match") == "cross_import":
                if path.suffix != ".py":
                    continue
                targets, error = import_targets(text)
                if error:
                    result.fail(path, error)
                    continue
                for name in targets:
                    if name in (rule.get("targets") or []):
                        message = "{} 跨组件 import {name}".format(rule["id"], name=name)
                        result.fail(path, message)
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rule_matches_line(rule, line):
                    message = "{} 命中 {}".format(rule["id"], rule.get("pattern") or "词表")
                    result.fail(path, message, lineno)
    return result


def check_dependency_direction(components: list[Component]) -> RuleResult:
    result = RuleResult("G4", "依赖必须单向（component → kernel → 标准库）")
    if not components:
        result.skip("components/ 尚未迁移（P2）")
        return result
    kernel_mods = {p.stem for p in KERNEL.glob("*.py") if p.stem != "__init__"}
    names = {c.name for c in components} | {c.name.replace("-", "_") for c in components}
    for comp in components:
        for dep in (comp.manifest or {}).get("kernel_deps") or []:
            if dep not in kernel_mods:
                result.fail(comp.path, "kernel_deps 引用了不存在的 kernel/{}".format(dep))
    for path in sorted(KERNEL.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        targets, error = import_targets(text)
        if error:
            result.fail(path, error)
            continue
        for name in targets:
            if name == "components" or name in names:
                result.fail(path, "kernel 反向依赖组件 {name}".format(name=name))
    return result


def check_manifests(components: list[Component]) -> RuleResult:
    result = RuleResult("G5", "component.yaml 必填字段齐全且版本一致")
    if not components:
        result.skip("components/ 尚未迁移（P2）")
        return result
    schema = json.loads((CONTRACTS / "component.schema.json").read_text(encoding="utf-8"))
    props = schema.get("properties") or {}
    for comp in components:
        manifest = comp.manifest
        if manifest is None:
            result.fail(comp.path, "缺少 component.yaml")
            continue
        for key in schema.get("required") or []:
            if key not in manifest:
                result.fail(comp.path, "缺少必填字段 {}".format(key))
        if manifest.get("name") != comp.name:
            result.fail(comp.path, "name 与目录名不一致：{}".format(manifest.get("name")))
        version = str(manifest.get("version") or "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            result.fail(comp.path, "version 不是 SemVer：{}".format(version))
        for key in ("family", "lifecycle"):
            allowed = props.get(key, {}).get("enum") or []
            if manifest.get(key) not in allowed:
                result.fail(comp.path, "{} 取值非法：{}".format(key, manifest.get(key)))
        contract = str(manifest.get("output_contract") or "")
        if not re.fullmatch(r"(data|handoff|cogsteward|reservation)\.v1", contract):
            result.fail(comp.path, "output_contract 非法：{}".format(contract))
        skill_dir = comp.path / str(manifest.get("skill_dir") or "skill")
        front = read_frontmatter(skill_dir / "SKILL.md")
        if not front:
            result.fail(comp.path, "缺少 {}/SKILL.md 或 frontmatter".format(skill_dir.name))
        elif str(front.get("version")) != version:
            result.fail(
                comp.path,
                "版本不一致：component.yaml={} / SKILL.md={}".format(version, front.get("version")),
            )
        for entry in manifest.get("entrypoints") or []:
            if not (skill_dir / entry).is_file():
                result.fail(comp.path, "入口脚本不存在：{}".format(entry))
    return result


def check_golden(components: list[Component]) -> RuleResult:
    result = RuleResult("G6", "golden 输出符合 output.schema.json profile")
    if not components:
        result.skip("components/ 尚未迁移（P2）")
        return result
    contract = json.loads((CONTRACTS / "output.schema.json").read_text(encoding="utf-8"))
    profiles = contract.get("profiles") or {}
    for comp in components:
        profile = (comp.manifest or {}).get("output_contract")
        schema = profiles.get(profile)
        golden_dir = comp.path / "tests" / "golden"
        samples = sorted(golden_dir.glob("*.json"))
        if schema is None:
            result.fail(comp.path, "output_contract 无对应 profile：{}".format(profile))
            continue
        if not samples:
            result.fail(golden_dir, "缺少 golden 输出样本（至少 1 份）")
            continue
        for sample in samples:
            try:
                payload = json.loads(sample.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                result.fail(sample, "JSON 解析失败：{}".format(exc.msg))
                continue
            if jsonschema_validate is None:
                missing = [k for k in schema.get("required") or [] if k not in payload]
                if missing:
                    result.fail(sample, "缺少必填字段 {}".format(",".join(missing)))
                continue
            try:
                jsonschema_validate(instance=payload, schema=schema)
            except ValidationError as exc:
                result.fail(sample, "schema 校验失败：{}".format(exc.message))
    return result


def check_tests(components: list[Component]) -> RuleResult:
    result = RuleResult("G7", "tests/ 非空且入口可执行")
    if not components:
        result.skip("components/ 尚未迁移（P2）")
        return result
    for comp in components:
        tests_dir = comp.path / "tests"
        files = (
            [p for p in tests_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
            if tests_dir.is_dir()
            else []
        )
        if not files:
            result.fail(tests_dir, "tests/ 为空或不存在")
        if not str((comp.manifest or {}).get("tests", {}).get("entry") or "").strip():
            result.fail(comp.path, "tests.entry 未声明测试命令")
    return result


def render_text(results: list[RuleResult]) -> None:
    width = max(len(r.title) for r in results) + 2
    for res in results:
        status = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[res.status]
        line = "{}  {:<{w}} {}".format(res.rule_id, res.title, status, w=width)
        if res.note:
            line += "  （{}）".format(res.note)
        print(line)
        for violation in res.violations[:20]:
            location = violation["file"]
            if violation["line"]:
                location += ":{}".format(violation["line"])
            print("       - {}  {}".format(location, violation["message"]))
        extra = len(res.violations) - 20
        if extra > 0:
            print("       - …另有 {} 处".format(extra))
    counts = {k: sum(1 for r in results if r.status == k) for k in ("pass", "fail", "skip")}
    print(
        "\n合计：{} 条规则，FAIL {} / PASS {} / SKIP {}，违规 {} 处".format(
            len(results),
            counts["fail"],
            counts["pass"],
            counts["skip"],
            sum(len(r.violations) for r in results),
        )
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="独立性闸门 G1–G7")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--rule", default="", help="只跑指定规则，如 G3")
    args = parser.parse_args(argv)

    for required in (
        "forbidden_refs.yaml",
        "component.schema.json",
        "output.schema.json",
        "redlines.md",
    ):
        if not (CONTRACTS / required).is_file():
            print("E_CONTRACT：缺少 contracts/{}".format(required), file=sys.stderr)
            return 2

    cfg = load_yaml(CONTRACTS / "forbidden_refs.yaml")
    components = discover_components()
    checks = [
        ("G1", lambda: check_component_refs(components)),
        ("G2", lambda: check_paths(cfg)),
        ("G3", lambda: check_forbidden_refs(cfg)),
        ("G4", lambda: check_dependency_direction(components)),
        ("G5", lambda: check_manifests(components)),
        ("G6", lambda: check_golden(components)),
        ("G7", lambda: check_tests(components)),
    ]
    wanted = args.rule.strip().upper()
    results = [fn() for rule_id, fn in checks if not wanted or rule_id == wanted]

    if args.json:
        payload = {
            "root": str(ROOT),
            "components": [c.name for c in components],
            "summary": {
                "pass": sum(1 for r in results if r.status == "pass"),
                "fail": sum(1 for r in results if r.status == "fail"),
                "skip": sum(1 for r in results if r.status == "skip"),
                "violations": sum(len(r.violations) for r in results),
            },
            "results": [r.as_dict() for r in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_text(results)

    if not components:
        print(
            "\n提示：components/ 尚未迁移（P2 未执行），G1/G4–G7 为 SKIP；"
            "G2/G3 结果为改造前违规基线。",
            file=sys.stderr,
        )
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

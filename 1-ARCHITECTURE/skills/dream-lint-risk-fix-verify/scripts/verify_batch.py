#!/usr/bin/env python3
"""批次校验器：对一批已修复文件做 AST 等价、命名空间或副作用检测。

用法：
    python3 verify_batch.py --rule I001 --files a.py b.py
    python3 verify_batch.py --rule F401 --files-from /tmp/batch.txt --mode namespace --smoke import
    python3 verify_batch.py --rule F841 --files-from /tmp/batch.txt --mode side-effect
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

IMPORT_TYPES = (ast.Import, ast.ImportFrom)
SIDE_EFFECT_ASSIGN = re.compile(r"^\s*[A-Za-z_][\w.\[\]'\"]*\s*=\s*.*\w+\s*\(")

MODE_BY_RULE = {
    "W291": "strict",
    "W292": "strict",
    "W293": "strict",
    "F541": "strict",
    "E401": "strict",
    "C401": "strict",
    "C403": "strict",
    "C408": "strict",
    "C414": "strict",
    "C416": "strict",
    "C420": "strict",
    "B009": "strict",
    "B010": "strict",
    "B033": "strict",
    "E713": "strict",
    "I001": "import-order",
    "F401": "namespace",
    "F841": "side-effect",
}

IMPORT_SNIPPET = r"""
import importlib.util
import json
import sys

path, name = sys.argv[1], sys.argv[2]
try:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    names = sorted(n for n in dir(module) if not n.startswith("_"))
    print(json.dumps({"ok": True, "names": names}))
except BaseException as exc:  # noqa: BLE001 - 冒烟需要捕获所有失败
    print(json.dumps({"ok": False, "names": [], "error": f"{type(exc).__name__}: {exc}"}))
"""


def repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 else Path.cwd()


def read_base(root: Path, rel: str, base: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{base}:{rel}"], cwd=root, capture_output=True, text=True, check=False
    )
    return proc.stdout if proc.returncode == 0 else None


def parse(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def import_key(node: ast.AST) -> str:
    module = getattr(node, "module", "") or ""
    level = getattr(node, "level", 0) or 0
    names = sorted(f"{alias.name}:{alias.asname or ''}" for alias in node.names)
    return f"{type(node).__name__}|{module}|{level}|{','.join(names)}"


class ImportOrderNormalizer(ast.NodeTransformer):
    """把连续 import 块折叠为排序后的占位语句，用于忽略导入顺序。"""

    def _normalize_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        output: list[ast.stmt] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                marker = "IMPORTS:" + ";".join(sorted(buffer))
                output.append(ast.Expr(value=ast.Constant(value=marker)))
                buffer.clear()

        for stmt in body:
            if isinstance(stmt, IMPORT_TYPES):
                buffer.append(import_key(stmt))
            else:
                flush()
                output.append(stmt)
        flush()
        return output

    def generic_visit(self, node: ast.AST) -> ast.AST:
        super().generic_visit(node)
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(x, ast.stmt) for x in value):
                setattr(node, field, self._normalize_body(value))
        return node


def dump(tree: ast.AST) -> str:
    return ast.dump(tree, include_attributes=False)


def import_order_dump(source: str) -> str | None:
    tree = parse(source)
    if tree is None:
        return None
    return dump(ImportOrderNormalizer().visit(tree))


def removed_lines(root: Path, rel: str, base: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "-U0", base, "--", rel],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line[1:]
        for line in proc.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]


def import_names(path: Path, root: Path, timeout: int) -> tuple[bool, list[str], str]:
    proc = subprocess.run(
        [sys.executable, "-c", IMPORT_SNIPPET, str(path), f"lint_smoke_{abs(hash(str(path)))}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return False, [], (proc.stderr.strip() or "导入无输出")
    return payload.get("ok", False), payload.get("names", []), payload.get("error", "")


def check_file(
    root: Path,
    path: Path,
    rule: str,
    mode: str,
    base: str,
    smoke: str,
    timeout: int,
    allow_remove: set[str],
) -> dict:
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    reasons: list[str] = []
    verdict = "pass"
    current = path.read_text(encoding="utf-8", errors="replace")
    base_source = read_base(root, rel, base)

    try:
        compile(current, rel, "exec")
    except SyntaxError as exc:
        return {"file": rel, "verdict": "block", "reasons": [f"编译失败: {exc}"]}

    if base_source is None:
        reasons.append("base 版本不存在（新文件），跳过等价校验")
        verdict = "warn"
    elif mode == "strict":
        if dump(parse(base_source) or ast.parse("pass")) != dump(
            parse(current) or ast.parse("pass")
        ):
            return {"file": rel, "verdict": "block", "reasons": ["AST 非同构，非纯格式变更"]}
    elif mode == "import-order":
        if import_order_dump(base_source) != import_order_dump(current):
            return {"file": rel, "verdict": "block", "reasons": ["非导入顺序变化"]}
    elif mode == "side-effect":
        if import_order_dump(base_source) != import_order_dump(current):
            reasons.append("非导入顺序变化，需人工核对")
            verdict = "warn"
        risky = [
            line.strip()
            for line in removed_lines(root, rel, base)
            if SIDE_EFFECT_ASSIGN.match(line)
        ]
        if risky:
            return {
                "file": rel,
                "verdict": "block",
                "reasons": [f"删除的赋值行含调用副作用: {risky[0][:80]}"],
            }
    elif mode == "namespace":
        base_ok, base_names, base_error = (False, [], "base 版本无法导入")
        if base_source is not None:
            with tempfile.TemporaryDirectory() as tmp:
                temp_path = Path(tmp) / path.name
                temp_path.write_text(base_source, encoding="utf-8")
                base_ok, base_names, base_error = import_names(temp_path, root, timeout)
        cur_ok, cur_names, cur_error = import_names(path, root, timeout)
        if not cur_ok:
            return {"file": rel, "verdict": "block", "reasons": [f"导入失败: {cur_error}"]}
        if base_ok:
            removed = sorted(set(base_names) - set(cur_names) - allow_remove)
            if removed:
                return {
                    "file": rel,
                    "verdict": "block",
                    "reasons": [f"公共命名空间减少: {', '.join(removed[:10])}"],
                }
        else:
            reasons.append(f"base 版本无法导入（{base_error}），仅校验当前版本")
            verdict = "warn"
    else:
        return {"file": rel, "verdict": "block", "reasons": [f"未知 mode: {mode}"]}

    if smoke == "import":
        ok, _, error = import_names(path, root, timeout)
        if not ok:
            return {"file": rel, "verdict": "block", "reasons": [f"导入冒烟失败: {error}"]}

    return {"file": rel, "verdict": verdict, "reasons": reasons}


def main() -> int:
    parser = argparse.ArgumentParser(description="lint 批次修复校验")
    parser.add_argument("--rule", default="", help="本批规则，如 I001/F401/F841")
    parser.add_argument("--files", nargs="*", default=[], help="待校验文件")
    parser.add_argument("--files-from", default="", help="文件列表（每行一个）")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "strict", "import-order", "namespace", "side-effect"],
    )
    parser.add_argument("--smoke", default="compile", choices=["none", "compile", "import"])
    parser.add_argument("--base", default="HEAD", help="对比基线，默认 HEAD")
    parser.add_argument("--timeout", type=int, default=15, help="单文件导入超时秒数")
    parser.add_argument("--allow-remove", default="", help="允许减少的公共名字，逗号分隔")
    parser.add_argument("--report", default="", help="JSON 报告路径")
    args = parser.parse_args()

    root = repo_root()
    files = list(args.files)
    if args.files_from:
        files.extend(Path(args.files_from).read_text(encoding="utf-8").splitlines())
    files = [item.strip() for item in files if item.strip()]
    if not files:
        parser.error("未提供文件（--files 或 --files-from）")

    mode = args.mode
    if mode == "auto":
        mode = MODE_BY_RULE.get(args.rule, "strict")
    allow_remove = {item.strip() for item in args.allow_remove.split(",") if item.strip()}

    results = []
    for item in files:
        path = Path(item).resolve()
        results.append(
            check_file(
                root, path, args.rule, mode, args.base, args.smoke, args.timeout, allow_remove
            )
        )

    summary = {}
    for result in results:
        summary[result["verdict"]] = summary.get(result["verdict"], 0) + 1
    report = {
        "rule": args.rule,
        "mode": mode,
        "smoke": args.smoke,
        "summary": summary,
        "files": results,
    }
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({"summary": summary, "mode": mode}, ensure_ascii=False))
    for result in results:
        if result["verdict"] != "pass":
            print(f"[{result['verdict']}] {result['file']}: {'; '.join(result['reasons'])}")
    return 1 if summary.get("block") else 0


if __name__ == "__main__":
    raise SystemExit(main())

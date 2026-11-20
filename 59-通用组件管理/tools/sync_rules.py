#!/usr/bin/env python3
"""由 contracts/skill-quality-rules.yaml 生成规则代码与站点数据（SPEC §5.1）。

用法:
    python3 tools/sync_rules.py --write   # 生成 rules.generated.js 与 site/data/rules.json
    python3 tools/sync_rules.py --check   # 校验结构 + 生成物一致（含 sha256）

结构校验 8 条，任一失败退出非零：
  1. id 唯一且匹配 ^(FM|DOC|EX|FAQ|SEC|PKG|PAY)[0-9]{3}$
  2. depends_on 指向存在的规则且无环
  3. 所有正则可被 JS new RegExp 编译
  4. required_by_platform 禁止 stage: gray；灰度仅限白名单规则
  5. severity/stage/weight 取值合法
  6. blocker/warn 必须有 messages.fix；patchable:false 必须有 messages.no_patch_reason
  7. changelog 末条 version == version
  8. 生成物头部 sha256 与源文件一致（仅 --check）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：需要 PyYAML（python3 -m pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "contracts" / "skill-quality-rules.yaml"
JS_OUTPUT = ROOT / "platform" / "services" / "skillhub-audit-api" / "src" / "rules.generated.js"
SITE_OUTPUT = ROOT / "platform" / "site" / "data" / "rules.json"

ID_RE = re.compile(r"^(FM|DOC|EX|FAQ|SEC|PKG|PAY)[0-9]{3}$")
SEVERITIES = {"blocker", "warn", "info"}
STAGES = {"enforce", "gray"}
GRAY_WHITELIST = {"FM007", "DOC002", "EX001", "FAQ001", "FM008"}
GENERATED_MARK = "AUTO-GENERATED"
HEADER_RE = re.compile(r"source-sha256:\s*([0-9a-f]{64})")

REQUIRED_KEYS = ("id", "title", "severity", "stage", "applies_to", "public", "messages")


class RuleError(Exception):
    pass


def load_config() -> dict:
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuleError("源文件顶层必须是映射")
    return data


def collect_patterns(rules: list) -> list:
    patterns = []
    for rule in rules:
        check = rule.get("check") or {}
        if check.get("pattern"):
            patterns.append(check["pattern"])
        for item in check.get("patterns") or []:
            patterns.append(item["pattern"] if isinstance(item, dict) else item)
        for group in check.get("groups") or []:
            patterns.extend(group)
    return patterns


def check_js_regex(patterns: list) -> None:
    """交给 Node 的 new RegExp 编译，避免 Python re 与 JS 语义差异。"""
    if not patterns:
        return
    payload = json.dumps(patterns)
    try:
        proc = subprocess.run(
            ["node", "-e", "JSON.parse(process.argv[1]).forEach((p) => new RegExp(p));", payload],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:  # pragma: no cover
        raise RuleError("E_ENV：校验正则需要 node") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise RuleError(f"正则无法编译：{detail[-1] if detail else '未知错误'}")


def validate(config: dict) -> None:
    version = config.get("version")
    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleError("rules 必须是非空列表")

    # 1. id 唯一且格式合法
    seen = set()
    for rule in rules:
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not ID_RE.match(rule_id):
            raise RuleError(f"非法规则 id：{rule_id!r}")
        if rule_id in seen:
            raise RuleError(f"规则 id 重复：{rule_id}")
        seen.add(rule_id)
        for key in REQUIRED_KEYS:
            if key not in rule:
                raise RuleError(f"{rule_id} 缺少字段 {key}")

    # 2. depends_on 存在且无环
    deps = {rule["id"]: list(rule.get("depends_on") or []) for rule in rules}
    for rule_id, items in deps.items():
        for dep in items:
            if dep not in seen:
                raise RuleError(f"{rule_id} 依赖不存在的规则 {dep}")
    state: dict = {}

    def visit(node: str) -> None:
        if state.get(node) == "visiting":
            raise RuleError(f"depends_on 存在环：{node}")
        if state.get(node) == "done":
            return
        state[node] = "visiting"
        for dep in deps[node]:
            visit(dep)
        state[node] = "done"

    for rule_id in deps:
        visit(rule_id)

    # 3. 正则可编译
    check_js_regex(collect_patterns(rules))

    # 4. 灰度限制
    for rule in rules:
        rule_id = rule["id"]
        if rule.get("required_by_platform") and rule.get("stage") == "gray":
            raise RuleError(f"{rule_id} 为平台必填，禁止 stage: gray")
        if rule.get("stage") == "gray" and rule_id not in GRAY_WHITELIST:
            raise RuleError(f"{rule_id} 不在灰度白名单内")

    # 5. 枚举与权重
    weights = (config.get("score") or {}).get("weights") or {}
    for key in ("blocker", "warn", "info"):
        value = weights.get(key)
        if not isinstance(value, int) or value <= 0:
            raise RuleError(f"score.weights.{key} 必须是正整数")
    for rule in rules:
        if rule.get("severity") not in SEVERITIES:
            raise RuleError(f"{rule['id']} severity 非法：{rule.get('severity')}")
        if rule.get("stage") not in STAGES:
            raise RuleError(f"{rule['id']} stage 非法：{rule.get('stage')}")
        if (config.get("score") or {}).get("formula") != "v2":
            raise RuleError("score.formula 必须为 v2")

    # 6. messages 完整性
    for rule in rules:
        messages = rule.get("messages") or {}
        if rule["severity"] in ("blocker", "warn") and not messages.get("fix"):
            raise RuleError(f"{rule['id']} 缺少 messages.fix")
        if rule.get("patchable") is False and not messages.get("no_patch_reason"):
            raise RuleError(f"{rule['id']} patchable:false 必须声明 messages.no_patch_reason")
        if rule.get("public") and not rule.get("site"):
            raise RuleError(f"{rule['id']} public:true 必须提供 site 展示字段")

    # 7. 版本与 changelog 对齐
    changelog = config.get("changelog") or []
    if not changelog or changelog[-1].get("version") != version:
        raise RuleError("changelog 末条 version 必须等于 version")


def render_js(config: dict, sha: str) -> str:
    payload = {
        "source_sha256": sha,
        "version": config["version"],
        "updated_at": config["updated_at"],
        "changelog": config.get("changelog") or [],
        "score": config["score"],
        "dimensions": config["dimensions"],
        "limits": config["limits"],
        "pay_markers": config["pay_markers"],
        "rules": config["rules"],
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        f"/* {GENERATED_MARK} from contracts/skill-quality-rules.yaml — 禁止手改\n"
        f" * source-sha256: {sha}\n"
        f" * rules-version: {config['version']} | score-formula: {config['score']['formula']}\n"
        f" */\n"
        "'use strict';\n\n"
        f"module.exports = {body};\n"
    )


def render_site(config: dict) -> str:
    public_rules = [rule for rule in config["rules"] if rule.get("public")]
    payload = {
        "rules_version": config["version"],
        "score_formula_version": config["score"]["formula"],
        "public_rule_count": len(public_rules),
        "public_rules": [
            {
                "id": rule["id"],
                "title": rule["title"],
                "severity": rule["severity"],
                "stage": rule["stage"],
                "category": rule["site"]["category"],
                "item": rule["site"]["item"],
                "consequence": rule["site"]["consequence"],
            }
            for rule in public_rules
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _source_sha() -> str:
    return hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def write() -> int:
    config = load_config()
    validate(config)
    sha = _source_sha()
    JS_OUTPUT.write_text(render_js(config, sha), encoding="utf-8")
    SITE_OUTPUT.write_text(render_site(config), encoding="utf-8")
    print(
        f"已生成 {JS_OUTPUT.relative_to(ROOT)}（{len(config['rules'])} 条规则）"
        f" 与 {SITE_OUTPUT.relative_to(ROOT)}（公开 {sum(1 for r in config['rules'] if r.get('public'))} 条）"
    )
    return 0


def check() -> int:
    config = load_config()
    validate(config)

    sha = _source_sha()
    errors = []

    for path, expected in ((JS_OUTPUT, render_js(config, sha)), (SITE_OUTPUT, render_site(config))):
        if not path.exists():
            errors.append(f"缺少生成物 {path.relative_to(ROOT)}，请执行 --write")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"{path.relative_to(ROOT)} 与源不一致，请执行 --write")
            continue
        if path == JS_OUTPUT:
            match = HEADER_RE.search(actual)
            if not match or match.group(1) != sha:
                errors.append("rules.generated.js 头部 sha256 与源文件不一致")

    if errors:
        for message in errors:
            print(f"[check] {message}", file=sys.stderr)
        return 1

    print(f"[check] 通过（{len(config['rules'])} 条规则，sha256 {sha[:12]}…）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="规则单一源同步器")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="生成规则代码与站点数据")
    group.add_argument("--check", action="store_true", help="校验结构与生成物一致性")
    args = parser.parse_args()

    try:
        return write() if args.write else check()
    except RuleError as exc:
        print(f"[rules] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

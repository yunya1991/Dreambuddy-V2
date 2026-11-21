#!/usr/bin/env python3
"""SkillHub 产品优化引擎 CLI。

用法:
    python3 platform/optimizer/cli.py card --check
    python3 platform/optimizer/cli.py score --all --profile legacy
    python3 platform/optimizer/cli.py score --component market-data --json /tmp/s.json
    python3 platform/optimizer/cli.py advise --component market-data --min-severity warn
    python3 platform/optimizer/cli.py gate --profile legacy --offline; echo $?
    python3 platform/optimizer/cli.py ab --dry-run --repeats 2
    python3 platform/optimizer/cli.py report --in /tmp/s.json --out /tmp/s.md

退出码：0 通过 / 1 规则或门禁失败 / 2 环境或参数缺失。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from optimizer import ab as ab_mod  # noqa: E402
from optimizer import advise as advise_mod  # noqa: E402
from optimizer import gate as gate_mod  # noqa: E402
from optimizer import loaders  # noqa: E402
from optimizer import report as report_mod  # noqa: E402
from optimizer import rules as rules_mod  # noqa: E402
from optimizer import score as score_mod  # noqa: E402

AUDIT_JS = loaders.MODULE_ROOT / "platform" / "services" / "skillhub-audit-api" / "src" / "audit.js"
ALLOWED_KINDS = {"skill_md", "mcp_tool", "product_page", "packaging"}
RULE_ID_RE = "^(RET|DIS|TRU|CON|OPE)[0-9]{3}$"


def _write_json(payload: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _collect(args) -> List[loaders.Surface]:
    if getattr(args, "all", False):
        if getattr(args, "include_draft", False):
            return loaders.all_surfaces()
        # 与 gate 保持同一口径：默认只评 active 组件的发布面
        return loaders.release_surfaces()
    product = getattr(args, "product", "") or ""
    if product:
        # 商品名与组件名常常同名（如 market-data），必须按 --product 的字面语义取商品页
        surfaces = loaders.surfaces_for_product(product)
        if not surfaces:
            raise FileNotFoundError("找不到商品：{}".format(product))
        return surfaces
    component = getattr(args, "component", "") or ""
    if component:
        surfaces = loaders.surfaces_for_component(component)
        if not surfaces:
            raise FileNotFoundError("找不到组件：{}".format(component))
        return surfaces
    raise ValueError("需要 --all 或 --component/--product")


def _print_score_text(payload: Dict[str, object]) -> None:
    summary = payload.get("summary") or {}
    print(
        "评分卡 v{} · profile={} · {} 个对象 · 平均 {} · blocker {} · warn {}".format(
            payload.get("card_version"),
            payload.get("profile"),
            summary.get("count", 0),
            summary.get("average", 0),
            summary.get("blockers", 0),
            summary.get("warnings", 0),
        )
    )
    for result in payload.get("surfaces") or []:
        surface = result["surface"]
        print(
            "  {:44} {:>6}  {}  blocker={} warn={}".format(
                surface["surface_id"],
                result["total"],
                result["grade"],
                result["blocker_count"],
                result["warning_count"],
            )
        )
    below = summary.get("below_total_warn") or []
    if below:
        print("总分低于告警线（不阻断）：")
        for item in below:
            print("  - {} {} 分（{} 级）".format(item["surface_id"], item["total"], item["grade"]))


def _audit_blockers(payload: Dict[str, object]) -> Dict[str, object]:
    """可选：对 skill_md 表面复用 skillhub-audit-api 的合规体检。"""
    node = shutil.which("node")
    if not node or not AUDIT_JS.exists():
        return {"available": False, "failures": []}
    script = (
        "const fs=require('fs');"
        "const {auditSkill}=require(process.argv[1]);"
        "const d=JSON.parse(fs.readFileSync(0,'utf8'));"
        "process.stdout.write(JSON.stringify(auditSkill(d)));"
    )
    failures: List[Dict[str, str]] = []
    for result in payload.get("surfaces") or []:
        surface = result["surface"]
        if surface["kind"] != "skill_md":
            continue
        skill_path = Path(surface["path"])
        package_dir = skill_path.parent
        files = [
            str(path.relative_to(package_dir)) for path in package_dir.rglob("*") if path.is_file()
        ]
        request = json.dumps(
            {
                "skill_md": skill_path.read_text(encoding="utf-8"),
                "files": files,
                "package_root": package_dir.name,
                "target": "free" if surface["surface_id"].endswith(":free") else "auto",
            },
            ensure_ascii=False,
        )
        try:
            completed = subprocess.run(
                [node, "-e", script, str(AUDIT_JS)],
                input=request,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return {"available": False, "failures": []}
        if completed.returncode != 0:
            return {"available": False, "failures": []}
        try:
            report = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return {"available": False, "failures": []}
        for check in report.get("checks") or []:
            if check.get("status") == "fail":
                failures.append(
                    {
                        "surface_id": surface["surface_id"],
                        "rule_id": str(check.get("id")),
                        "title": str(check.get("title")),
                        "message": str(check.get("detail") or ""),
                    }
                )
    return {"available": True, "failures": failures}


def _check_card(card: dict) -> List[str]:
    errors: List[str] = []
    version = card.get("version")
    changelog = card.get("changelog") or []
    if not changelog or changelog[-1].get("version") != version:
        errors.append("changelog 末条 version 必须等于 version（当前 {}）".format(version))
    dimensions = card.get("dimensions") or {}
    if not dimensions:
        errors.append("dimensions 不能为空")
    profiles = card.get("profiles") or {}
    for name, config in profiles.items():
        enforce = config.get("enforce") or []
        if not set(enforce) <= {"blocker", "warn", "info"}:
            errors.append("profile {} 的 enforce 取值非法".format(name))
    seen = set()
    for rule in card.get("rules") or []:
        rule_id = str(rule.get("id") or "")
        if not __import__("re").match(RULE_ID_RE, rule_id):
            errors.append("规则 id 非法：{}".format(rule_id))
        if rule_id in seen:
            errors.append("规则 id 重复：{}".format(rule_id))
        seen.add(rule_id)
        if rule.get("dimension") not in dimensions:
            errors.append("{} 的 dimension 未在 dimensions 定义".format(rule_id))
        if rule.get("severity") not in {"blocker", "warn", "info"}:
            errors.append("{} 的 severity 非法".format(rule_id))
        kinds = set(rule.get("applies_to") or [])
        if not kinds or not kinds <= ALLOWED_KINDS:
            errors.append("{} 的 applies_to 非法：{}".format(rule_id, sorted(kinds)))
        check_type = str((rule.get("check") or {}).get("type") or "")
        if check_type not in rules_mod.SUPPORTED_CHECKS:
            errors.append("{} 的 check.type 不支持：{}".format(rule_id, check_type))
        if float(rule.get("weight") or 0) <= 0:
            errors.append("{} 的 weight 必须大于 0".format(rule_id))
        messages = rule.get("messages") or {}
        if rule.get("severity") in {"blocker", "warn"} and not messages.get("advice"):
            errors.append("{} 缺少 messages.advice".format(rule_id))
    return errors


def cmd_score(args) -> int:
    card = loaders.load_scorecard()
    payload = score_mod.score_all(_collect(args), card, args.profile)
    if args.json:
        _write_json(payload, Path(args.json))
    _print_score_text(payload)
    return 0


def cmd_advise(args) -> int:
    card = loaders.load_scorecard()
    payload = score_mod.score_all(_collect(args), card, args.profile)
    items = advise_mod.advise(payload, args.min_severity)
    if args.json:
        _write_json({"items": items}, Path(args.json))
    print(advise_mod.render_text(items))
    return 0


def cmd_gate(args) -> int:
    card = loaders.load_scorecard()
    surfaces = _collect(args)
    payload = score_mod.score_all(surfaces, card, args.profile)
    blocked = gate_mod.blocking_findings(payload, card, args.profile)
    audit_failures: List[Dict[str, str]] = []
    if args.audit:
        audit = _audit_blockers(payload)
        if audit.get("available"):
            audit_failures = list(audit.get("failures") or [])
        else:
            print("提示：--audit 不可用（缺 node 或 audit.js），本次只跑优化链。", file=sys.stderr)
    print(gate_mod.render_text(blocked, payload, args.profile))
    if audit_failures:
        print("合规体检阻断项（skillhub-audit-api）：")
        for item in audit_failures:
            print("  - [{}] {} · {}".format(item["rule_id"], item["surface_id"], item["title"]))
    if args.json:
        _write_json(
            {"payload": payload, "blocked": blocked, "audit_failures": audit_failures},
            Path(args.json),
        )
    return 1 if blocked or audit_failures else 0


def cmd_card(args) -> int:
    card = loaders.load_scorecard(Path(args.path) if args.path else None)
    errors = _check_card(card)
    if errors:
        print("评分卡校验失败：")
        for error in errors:
            print("  - {}".format(error))
        return 1
    print(
        "评分卡 v{} 校验通过：{} 维 · {} 条规则".format(
            card.get("version"),
            len(card.get("dimensions") or {}),
            len(card.get("rules") or []),
        )
    )
    return 0


def cmd_ab(args) -> int:
    result = ab_mod.run_ab(
        ids=args.ids,
        catalog_fields=args.catalog_fields,
        name_style=args.name_style,
        model=args.model,
        repeats=args.repeats,
        retries=args.retries,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return int(result.get("exit_code", 2))


def cmd_report(args) -> int:
    source = Path(args.infile)
    if not source.exists():
        print("找不到评分 JSON：{}".format(source), file=sys.stderr)
        return 2
    payload = json.loads(source.read_text(encoding="utf-8"))
    markdown = report_mod.render_markdown(payload)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print("报告已写入 {}".format(out))
    else:
        print(markdown)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SkillHub 产品优化引擎")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_targets(target: argparse.ArgumentParser) -> None:
        target.add_argument("--all", action="store_true", help="评全部组件与商品")
        target.add_argument("--component", default="", help="组件名，如 market-data")
        target.add_argument("--product", default="", help="商品名，如 market-facts-daily")
        target.add_argument("--profile", choices=["new", "legacy"], default="legacy")
        target.add_argument("--json", default="", help="把结果写入 JSON 文件")
        target.add_argument(
            "--include-draft",
            action="store_true",
            help="把 draft 组件也纳入评分（默认只评 active 发布面）",
        )

    p_score = sub.add_parser("score", help="离线五维评分与证据")
    add_targets(p_score)
    p_score.set_defaults(func=cmd_score)

    p_advise = sub.add_parser("advise", help="把失败项转成改写建议")
    add_targets(p_advise)
    p_advise.add_argument("--min-severity", choices=["blocker", "warn", "info"], default="warn")
    p_advise.set_defaults(func=cmd_advise)

    p_gate = sub.add_parser("gate", help="发布门禁：blocker 硬阻断")
    add_targets(p_gate)
    p_gate.add_argument("--offline", action="store_true", help="只跑离线评分（当前默认行为）")
    p_gate.add_argument("--audit", action="store_true", help="同时跑 skillhub-audit-api 合规体检")
    p_gate.set_defaults(func=cmd_gate)

    p_card = sub.add_parser("card", help="校验评分卡结构")
    p_card.add_argument("--check", action="store_true", help="执行结构校验")
    p_card.add_argument("--path", default="", help="自定义评分卡路径")
    p_card.set_defaults(func=cmd_card)

    p_ab = sub.add_parser("ab", help="复用路由基准做单变量 A/B")
    p_ab.add_argument("--ids", default="", help="逗号分隔意图 id")
    p_ab.add_argument(
        "--catalog-fields", choices=["name", "guidance", "full", "both"], default="full"
    )
    p_ab.add_argument("--name-style", choices=["current", "r2", "legacy"], default="current")
    p_ab.add_argument("--model", default="", help="覆盖 QWEN_DEFAULT_MODEL")
    p_ab.add_argument("--repeats", type=int, default=2)
    p_ab.add_argument("--retries", type=int, default=1)
    p_ab.add_argument("--dry-run", action="store_true")
    p_ab.add_argument("--component", default="", help="仅记录，用于报告命名")
    p_ab.add_argument("--variable", default="", help="仅记录，用于报告命名")
    p_ab.set_defaults(func=cmd_ab)

    p_report = sub.add_parser("report", help="把评分 JSON 渲染为 Markdown")
    p_report.add_argument("--in", dest="infile", required=True)
    p_report.add_argument("--out", default="")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError) as exc:
        print("E_INPUT：{}".format(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print("E_ENV：{}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

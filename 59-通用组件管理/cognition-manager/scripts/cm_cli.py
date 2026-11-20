#!/usr/bin/env python3
"""认知管家（CogSteward）统一入口。

用法：
    python3 scripts/cm_cli.py init --scan --doctor
    python3 scripts/cm_cli.py scan [--full] [--json]
    python3 scripts/cm_cli.py doctor [--json]
    python3 scripts/cm_cli.py route "<描述>" [--json] [--apply] [--confirm]
    python3 scripts/cm_cli.py pack "<任务>" [--budget 2000] [--json]
    python3 scripts/cm_cli.py triage [--json] [--expire-sessions] [--drop-pending]
    python3 scripts/cm_cli.py mark-done "<描述>" [--json]
    python3 scripts/cm_cli.py rollback <run_id> [--json]
    python3 scripts/cm_cli.py config apply=on|off [--json]

零第三方依赖；所有状态写入工作区 `.cm/`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from core import (  # noqa: E402
    __version__,
    apply as apply_engine,
    codemap,
    indexer,
    pack as pack_engine,
    report,
    router,
    scanner,
    selfcheck,
    skill_lint,
    store,
    triage as triage_engine,
)

CONFIG_KEYS = {
    "apply", "high_threshold", "low_threshold",
    "session_ttl_days", "materialize", "max_attachments", "traces_summary",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cm",
        description="认知管家 CogSteward — 工作区上下文治理（M2：路由 / 打包 / 分拣 / 回滚）",
    )
    parser.add_argument("--root", default=None, help="工作区根目录（默认当前目录）")
    parser.add_argument("--version", action="version",
                        version="认知管家 CogSteward {}".format(__version__))
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="初始化工作区状态目录 .cm/")
    p_init.add_argument("--mode", choices=["dev", "office"], default="dev",
                        help="版本模式（默认 dev）")
    p_init.add_argument("--scan", action="store_true", help="初始化后立即扫描")
    p_init.add_argument("--doctor", action="store_true", help="初始化后立即体检（可配合 --scan）")
    p_init.add_argument("--full", action="store_true", help="扫描时忽略增量缓存")
    p_init.add_argument("--force", action="store_true", help="覆盖已有 config.yaml")
    p_init.add_argument("--json", action="store_true", help="输出 JSON")

    p_scan = sub.add_parser("scan", help="全量 / 增量扫描并登记文件")
    p_scan.add_argument("--full", action="store_true", help="忽略增量缓存，全部重算")
    p_scan.add_argument("--json", action="store_true", help="输出 JSON")

    p_doctor = sub.add_parser("doctor", help="工作区体检")
    p_doctor.add_argument("--json", action="store_true", help="输出 JSON")

    p_route = sub.add_parser("route", help="路由一条新信息（默认 plan，不落盘）")
    p_route.add_argument("content", nargs="+", help="待路由的内容 / 描述")
    p_route.add_argument("--json", action="store_true", help="输出 JSON")
    p_route.add_argument("--apply", action="store_true",
                         help="请求落盘（需先 cm config apply=on）")
    p_route.add_argument("--confirm", action="store_true",
                         help="写入用户确认（豁免确认，不计执行次数）")
    p_route.add_argument("--facts", default=None,
                         help="记忆准入事实 JSON，如 {\"a1\":{\"result\":\"not_derivable\"}}")

    p_pack = sub.add_parser("pack", help="按 token 预算打包上下文指针（只读）")
    p_pack.add_argument("query", nargs="+", help="检索关键词 / 任务描述")
    p_pack.add_argument("--budget", type=int, default=pack_engine.DEFAULT_BUDGET,
                        help="token 预算（默认 2000）")
    p_pack.add_argument("--json", action="store_true", help="输出 JSON")

    p_triage = sub.add_parser("triage", help="列出并处理过期会话 / 待定项")
    p_triage.add_argument("--expire-sessions", action="store_true",
                          help="把超过 TTL 的会话标记为已回收")
    p_triage.add_argument("--drop-pending", action="store_true",
                          help="复核满 3 次的待定项置 dropped，其余复核次数 +1")
    p_triage.add_argument("--json", action="store_true", help="输出 JSON")

    p_mark = sub.add_parser("mark-done", help="登记一次真实执行（D1 计数来源）")
    p_mark.add_argument("content", nargs="+", help="已完成的意图描述")
    p_mark.add_argument("--source", choices=["mark_done", "record"], default="mark_done")
    p_mark.add_argument("--json", action="store_true", help="输出 JSON")

    p_rollback = sub.add_parser("rollback", help="按备份逆序回滚一次 apply")
    p_rollback.add_argument("run_id", help="route 返回的 id，如 rt-20261119-0001")
    p_rollback.add_argument("--json", action="store_true", help="输出 JSON")

    p_config = sub.add_parser("config", help="查看 / 修改工作区配置")
    p_config.add_argument("assignments", nargs="*", help="key=value，如 apply=on")
    p_config.add_argument("--json", action="store_true", help="输出 JSON")

    p_index = sub.add_parser("index", help="索引总览（默认增量扫描后汇报）")
    p_index.add_argument("--check", action="store_true",
                         help="只读校验，不重建索引")
    p_index.add_argument("--json", action="store_true", help="输出 JSON")

    p_skill = sub.add_parser("skill", help="技能治理子命令")
    skill_sub = p_skill.add_subparsers(dest="skill_command")
    p_lint = skill_sub.add_parser("lint", help="检查技能版本 / 重名 / 触发词 / 依赖")
    p_lint.add_argument("--json", action="store_true", help="输出 JSON")

    p_map = sub.add_parser("map", help="代码-文档对应检查（行号越界 / 无文档代码 / 漂移）")
    p_map.add_argument("--gaps", action="store_true", help="只输出缺口明细")
    p_map.add_argument("--json", action="store_true", help="输出 JSON")

    p_self = sub.add_parser("selfcheck", help="安装自检：契约 / 口径 / 版本一致性")
    p_self.add_argument("--json", action="store_true", help="输出 JSON")

    return parser


def cmd_init(root: Path, args) -> int:
    init_result = store.init_workspace(root, mode=args.mode, force=args.force)
    config = store.load_config(root)
    payload = {"init": init_result}
    lines = [report.format_init(init_result)]

    if args.scan or args.doctor:
        conn = store.connect(root)
        try:
            if args.scan:
                stats = scanner.scan(root, config, conn, full=args.full)
                payload["scan"] = stats
                lines.append(report.format_scan(stats))
            if args.doctor:
                result = report.doctor(root, config, conn)
                payload["doctor"] = result
                lines.append("")
                lines.append(report.format_doctor(result))
        finally:
            conn.close()

    print(report.to_json(payload) if args.json else "\n".join(lines))
    return store.EXIT_OK


def cmd_scan(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        stats = scanner.scan(root, config, conn, full=args.full)
    finally:
        conn.close()
    print(report.to_json(stats) if args.json else report.format_scan(stats))
    return store.EXIT_OK


def cmd_doctor(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = report.doctor(root, config, conn)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_doctor(result))
    return store.EXIT_OK


def cmd_route(root: Path, args) -> int:
    config = store.load_config(root)
    facts = None
    if args.facts:
        try:
            facts = json.loads(args.facts)
        except ValueError as exc:
            raise store.CmError(store.EXIT_USAGE, "准入事实不是合法 JSON：{}".format(exc))
    content = " ".join(args.content)
    conn = store.connect(root)
    try:
        result = router.route(
            root, config, conn, content,
            apply_requested=args.apply,
            confirm=args.confirm,
            facts=facts,
        )
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_route(result))
    return store.EXIT_OK


def cmd_pack(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = pack_engine.pack(root, config, conn, " ".join(args.query),
                                  budget=args.budget)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_pack(result))
    return store.EXIT_OK


def cmd_triage(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = triage_engine.triage(
            root, config, conn,
            expire_sessions=args.expire_sessions,
            drop_pending=args.drop_pending,
        )
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_triage(result))
    return store.EXIT_OK


def cmd_mark_done(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = router.mark_done(root, config, conn, " ".join(args.content),
                                  source=args.source)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_mark_done(result))
    return store.EXIT_OK


def cmd_rollback(root: Path, args) -> int:
    conn = store.connect(root)
    try:
        result = apply_engine.rollback(root, args.run_id, conn=conn)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_rollback(result))
    return store.EXIT_OK if result.get("rolled_back") else store.EXIT_IO


def cmd_config(root: Path, args) -> int:
    updates = {}
    for item in args.assignments:
        if "=" not in item:
            raise store.CmError(store.EXIT_USAGE, "配置项格式应为 key=value：{}".format(item))
        key, _, raw = item.partition("=")
        key = key.strip()
        if key not in CONFIG_KEYS:
            raise store.CmError(
                store.EXIT_USAGE,
                "不支持的配置项：{}（允许：{}）".format(key, ", ".join(sorted(CONFIG_KEYS))),
            )
        updates[key] = store._parse_scalar(raw.strip())

    if updates.get("apply") is not None and not isinstance(updates["apply"], bool):
        raise store.CmError(store.EXIT_USAGE, "apply 只接受 on/off")
    for key in ("high_threshold", "low_threshold"):
        if key in updates and not isinstance(updates[key], (int, float)):
            raise store.CmError(store.EXIT_USAGE, "{} 需要是 0–1 的数字".format(key))

    base = store.load_config(root)
    prospective = dict(base)
    prospective.update(updates)
    if float(prospective.get("high_threshold", 0)) <= float(prospective.get("low_threshold", 0)):
        raise store.CmError(store.EXIT_USAGE, "high_threshold 必须大于 low_threshold")

    config = store.update_config(root, updates) if updates else base

    payload = {"config": config, "updated": sorted(updates)}
    if args.json:
        print(report.to_json(payload))
    else:
        print(report.format_config(config, sorted(updates)))
    return store.EXIT_OK


def cmd_index(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = indexer.index(root, config, conn, check=args.check)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else report.format_index(result))
    return store.EXIT_OK


def cmd_skill_lint(root: Path, args) -> int:
    config = store.load_config(root)
    result = skill_lint.lint(root, config)
    print(report.to_json(result) if args.json else report.format_skill_lint(result))
    return store.EXIT_OK


def cmd_map(root: Path, args) -> int:
    config = store.load_config(root)
    conn = store.connect(root)
    try:
        result = codemap.analyze(root, config, conn)
    finally:
        conn.close()
    print(report.to_json(result) if args.json else codemap.format_map(result, gaps_only=args.gaps))
    return store.EXIT_OK


def cmd_selfcheck(root: Path, args) -> int:
    result = selfcheck.run(root)
    print(report.to_json(result) if args.json else selfcheck.format_selfcheck(result))
    return store.EXIT_OK if result["ok"] else store.EXIT_USAGE


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd()

    if not args.command:
        parser.print_help()
        return store.EXIT_USAGE

    try:
        if args.command == "init":
            return cmd_init(root, args)
        if args.command == "scan":
            return cmd_scan(root, args)
        if args.command == "doctor":
            return cmd_doctor(root, args)
        if args.command == "map":
            return cmd_map(root, args)
        if args.command == "selfcheck":
            return cmd_selfcheck(root, args)
        if args.command == "route":
            return cmd_route(root, args)
        if args.command == "pack":
            return cmd_pack(root, args)
        if args.command == "triage":
            return cmd_triage(root, args)
        if args.command == "mark-done":
            return cmd_mark_done(root, args)
        if args.command == "rollback":
            return cmd_rollback(root, args)
        if args.command == "config":
            return cmd_config(root, args)
        if args.command == "index":
            return cmd_index(root, args)
        if args.command == "skill":
            if args.skill_command != "lint":
                print("用法：cm skill lint [--json]", file=sys.stderr)
                return store.EXIT_USAGE
            return cmd_skill_lint(root, args)
    except store.CmError as exc:
        print("错误：{}".format(exc.message), file=sys.stderr)
        return exc.code
    except OSError as exc:
        print("错误：文件系统访问失败：{}".format(exc), file=sys.stderr)
        return store.EXIT_IO
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130

    parser.print_help()
    return store.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())

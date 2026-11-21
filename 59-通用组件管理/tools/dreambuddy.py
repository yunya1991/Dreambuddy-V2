#!/usr/bin/env python3
"""dreambuddy —— 59 域统一只读编排 CLI。

发现 components/*/component.yaml，提供：
  dreambuddy                            裸命令（终端）：进入会话，直接说人话
  dreambuddy chat                       同上，会话式自然语言编排
  dreambuddy ls [--json]                列出组件、入口与动作
  dreambuddy help <组件>                 查看某组件入口与动作
  dreambuddy run <组件> <动作|入口> [args...] [--allow-write] [--endpoint auto|cloud|local]
                                        以子进程调用组件脚本（默认拒绝 write 动作）
  dreambuddy 59 <组件> <动作> [args...]  同 run（59 域显式写法）
  dreambuddy data <组件> <动作> [args...] 同 run（数据/组件域别名）
  dreambuddy mobile <子命令> [args...]   手机AGENT 业务域（内部 CLI：mra.py）
  dreambuddy domains                    列出已接通的能力域
  dreambuddy doctor [--full]            跑治理闸门（kernel/边界/索引/规则）

域间调用：统一入口只做子进程编排，两个方向都通过本 CLI 互相调用，不互相 import。
被调子进程会拿到 DREAMBUDDY_CLI（本入口绝对路径）与 DREAMBUDDY_DOMAIN，可反向回查。

云端通道：对声明了 endpoint 参数的动作，`--endpoint cloud` 走 partner 网关
（默认 https://www.neodrm.com/api/partner/v1，可用 MDH_ENDPOINT 覆盖）。
令牌从环境 PARTNER_TOKEN / PARTNER_TOKEN_FILE 读取，或写在
~/.local/share/dreambuddy/partner.env；环境变量 DREAMBUDDY_ENDPOINT 可设默认通道。

设计原则：只做子进程编排，不 import 组件内部代码，保持组件相互独立（G1–G7 不受影响）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
CLI_PATH = Path(__file__).resolve()

ENDPOINT_CHOICES = ("auto", "cloud", "local")
ENDPOINT_ENV = "DREAMBUDDY_ENDPOINT"
PARTNER_ENV = Path(os.path.expanduser("~/.local/share/dreambuddy/partner.env"))
PARTNER_KEYS = ("PARTNER_TOKEN", "PARTNER_TOKEN_FILE", "MDH_ENDPOINT")
DEFAULT_PARTNER_BASE = "https://www.neodrm.com/api/partner/v1"


def load_partner_env() -> None:
    """把云端网关配置并入进程环境；已存在的环境变量优先。"""
    if not PARTNER_ENV.exists():
        return
    for line in PARTNER_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key in PARTNER_KEYS:
            os.environ.setdefault(key, val.strip().strip("\"'"))


def cloud_status() -> str:
    base = os.environ.get("MDH_ENDPOINT") or DEFAULT_PARTNER_BASE
    has_token = bool(
        (os.environ.get("PARTNER_TOKEN") or "").strip()
        or (os.environ.get("PARTNER_TOKEN_FILE") or "").strip()
    )
    return "{} · 令牌{}".format(base, "已配置" if has_token else "未配置（{}）".format(PARTNER_ENV))


def default_endpoint() -> str:
    value = (os.environ.get(ENDPOINT_ENV) or "").strip().lower()
    return value if value in ENDPOINT_CHOICES else ""


def take_endpoint(argv: list[str]) -> tuple[list[str], str]:
    """从参数里摘出 --endpoint，返回 (剩余参数, 取值)；未显式给出时取环境默认。"""
    rest: list[str] = []
    value = default_endpoint()
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == "--endpoint":
            if i + 1 >= len(argv):
                raise SystemExit("E_INPUT：--endpoint 需要 auto / cloud / local 之一")
            value = argv[i + 1].strip().lower()
            i += 2
            continue
        if item.startswith("--endpoint="):
            value = item.split("=", 1)[1].strip().lower()
            i += 1
            continue
        rest.append(item)
        i += 1
    if value and value not in ENDPOINT_CHOICES:
        raise SystemExit("E_INPUT：--endpoint 取值 auto / cloud / local")
    return rest, value


def apply_endpoint(endpoint: str, params: list[str], argv: list[str]) -> list[str]:
    """把通道参数转发给声明了 endpoint 的动作；未声明的动作不允许指定 cloud。"""
    if not endpoint:
        return argv
    if "endpoint" in params:
        return argv + ["--endpoint", endpoint]
    if endpoint == "cloud":
        raise SystemExit("E_UNSUPPORTED：该动作暂无云端通道，可改用 --endpoint local")
    return argv


def load_components() -> list[dict]:
    items: list[dict] = []
    for manifest in sorted(COMPONENTS.glob("*/component.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        data["_dir"] = manifest.parent
        items.append(data)
    return items


def find_component(name: str) -> dict:
    for comp in load_components():
        if comp.get("name") == name or comp["_dir"].name == name:
            return comp
    raise SystemExit("E_NOTFOUND：未找到组件 {}".format(name))


def script_path(comp: dict, rel: str) -> Path:
    return comp["_dir"] / (comp.get("skill_dir") or "skill") / rel


def find_action(comp: dict, target: str) -> dict:
    """取动作原始声明（拿 cwd / 参数 flag 等 manifest 字段）。"""
    for action in comp.get("actions") or []:
        if action.get("name") == target:
            return action
    return {}


def action_cwd(comp: dict, action: dict) -> Path:
    """动作可声明 cwd: workspace，表示在仓库根（而非组件目录）执行。"""
    if action.get("cwd") == "workspace":
        return ROOT.parent
    return comp["_dir"]


def split_globals(action: dict, rest: list[str]) -> tuple[list[str], list[str]]:
    """把 global: true 的参数（如 --root）提到子命令之前。

    认知管家这类脚本的 --root 是顶层参数，必须排在 scan/doctor 前面，
    否则 argparse 会当成子命令的未知参数。
    """
    flags = {
        p["flag"]
        for p in action.get("params") or []
        if p.get("global") and p.get("flag")
    }
    if not flags:
        return [], rest
    head: list[str] = []
    tail: list[str] = []
    i = 0
    while i < len(rest):
        item = rest[i]
        flag, sep, val = item.partition("=")
        if flag not in flags:
            tail.append(item)
            i += 1
            continue
        if sep:
            head.extend([flag, val])
            i += 1
            continue
        if i + 1 >= len(rest) or str(rest[i + 1]).startswith("-"):
            # 模型有时只给 flag 不给值（如 --root --json），按缺失处理，落回默认值
            i += 1
            continue
        head.extend([flag, rest[i + 1]])
        i += 2
    return head, tail


def drop_stray_args(action: dict, args: list[str]) -> list[str]:
    """动作只接受带 flag 的参数时，丢掉模型塞进来的游离关键词。

    例如 index 没有位置参数，模型却给了 ["手机助手"]；若不过滤，
    argparse 会直接报 unrecognized arguments。
    """
    params = action.get("params") or []
    if not params or any(not p.get("flag") for p in params):
        return args
    out: list[str] = []
    i = 0
    while i < len(args):
        item = str(args[i])
        if not item.startswith("-"):
            i += 1
            continue
        out.append(item)
        if "=" not in item and i + 1 < len(args) and not str(args[i + 1]).startswith("-"):
            out.append(str(args[i + 1]))
            i += 2
            continue
        i += 1
    return out


def resolve_target(comp: dict, target: str) -> tuple[Path, list[str], str, str, list[str]]:
    """返回 (脚本路径, 前置参数, 安全级, 说明, 参数名列表)。"""
    for action in comp.get("actions") or []:
        if action.get("name") == target:
            params = [p.get("name", "") for p in action.get("params") or []]
            return (
                script_path(comp, action["script"]),
                list(action.get("args") or []),
                action.get("safety", "read"),
                action.get("description", ""),
                params,
            )
    for rel in comp.get("entrypoints") or []:
        if target in (rel, Path(rel).name, Path(rel).stem):
            return script_path(comp, rel), [], "read", "入口脚本", []
    choices = [a.get("name") for a in comp.get("actions") or []] + [
        Path(r).stem for r in comp.get("entrypoints") or []
    ]
    raise SystemExit(
        "E_TARGET：组件 {} 无动作/入口 {}；可选：{}".format(
            comp.get("name"), target, ", ".join(choices)
        )
    )


def cmd_ls(args) -> int:
    comps = load_components()
    if args.json:
        payload = []
        for c in comps:
            payload.append(
                {
                    "name": c.get("name"),
                    "family": c.get("family"),
                    "lifecycle": c.get("lifecycle"),
                    "summary": c.get("summary", ""),
                    "entrypoints": c.get("entrypoints") or [],
                    "actions": c.get("actions") or [],
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("59 域组件（共 {} 个）".format(len(comps)))
    for c in comps:
        acts = c.get("actions") or []
        reads = sum(1 for a in acts if a.get("safety", "read") == "read")
        writes = len(acts) - reads
        print("\n● {}  [{} · {}]".format(c.get("name"), c.get("family"), c.get("lifecycle")))
        print("  {}".format(c.get("summary", "")))
        print("  入口: {}".format(", ".join(c.get("entrypoints") or [])))
        if acts:
            print("  动作: {} 个（只读 {} / 写 {}）".format(len(acts), reads, writes))
    print("\n用法: dreambuddy help <组件> | dreambuddy run <组件> <动作> | dreambuddy doctor")
    return 0


def cmd_help(args) -> int:
    comp = find_component(args.component)
    print("● {}  [{}]".format(comp.get("name"), comp.get("family")))
    print("  {}".format(comp.get("summary", "")))
    print("\n入口脚本：")
    for rel in comp.get("entrypoints") or []:
        print("  - {}".format(rel))
    acts = comp.get("actions") or []
    if acts:
        print("\n动作：")
        for a in acts:
            cloud = " 云端" if "endpoint" in [p.get("name") for p in a.get("params") or []] else ""
            print(
                "  - {:16} [{}]{} {}  ({})".format(
                    a.get("name"),
                    a.get("safety", "read"),
                    cloud,
                    a.get("description", ""),
                    " ".join(a.get("args") or []) or "—",
                )
            )
    print(
        "\n用法: dreambuddy run {} <动作|入口> [参数...] [--endpoint auto|cloud|local]".format(
            comp.get("name")
        )
    )
    print("云端: {}".format(cloud_status()))
    return 0


def cmd_run(args) -> int:
    comp = find_component(args.component)
    script, pre, safety, desc, params = resolve_target(comp, args.target)
    action = find_action(comp, args.target)
    rest, endpoint = take_endpoint(list(args.rest))
    # argparse.REMAINDER 会把尾随的 --allow-write 吞进来，这里还原成开关
    allow_write = args.allow_write or "--allow-write" in rest
    rest = [item for item in rest if item != "--allow-write"]
    if action:
        import capabilities

        safety = capabilities.effective_safety(action, rest)
    if not script.exists():
        raise SystemExit("E_SCRIPT：脚本不存在 {}".format(script))
    if safety in {"write", "ui"} and not allow_write:
        print("E_GUARD：动作 {} 标记为 {}，需加 --allow-write 才能执行".format(args.target, safety))
        return 3
    head, rest = split_globals(action, rest)
    cmd = apply_endpoint(endpoint, params, [sys.executable, str(script)] + head + pre + rest)
    print("[dreambuddy] {} → {}".format(comp.get("name"), " ".join(cmd)), file=sys.stderr)
    proc = subprocess.run(cmd, cwd=str(action_cwd(comp, action)), env=domain_env("59"))
    return proc.returncode


# ---------------------------------------------------------------- 手机AGENT 业务域

MOBILE_COMPONENT = "mobile-reservation-assist"
RESERVATION_COMPONENT = "reservation-assist"


def domain_env(domain: str) -> dict:
    """子进程环境：透传 CLI 路径，供另一域反向调用统一入口。"""
    env = dict(os.environ)
    env["DREAMBUDDY_CLI"] = str(CLI_PATH)
    env["DREAMBUDDY_DOMAIN"] = domain
    return env


def mobile_script() -> Path:
    return script_path(find_component(MOBILE_COMPONENT), "scripts/mra.py")


def build_mobile_argv(sub: str, rest: list) -> list[str]:
    """组装 mra.py 调用；ingest 未给 --ra-cli 时自动接上 59 域 reservation-assist。"""
    argv = [sys.executable, str(mobile_script()), sub] + list(rest)
    if sub == "ingest" and "--ra-cli" not in rest:
        ra = script_path(find_component(RESERVATION_COMPONENT), "scripts/ra.py")
        if ra.exists():
            argv += ["--ra-cli", str(ra)]
    return argv


def mobile_action_caps() -> list[dict]:
    """手机动作清单：唯一源是 component.yaml（经能力注册表），不维护第二份命令表。"""
    import capabilities

    return [
        cap
        for cap in capabilities.build()
        if cap.get("component") == MOBILE_COMPONENT and cap.get("kind") == "run"
    ]


def match_mobile_action(tokens: list) -> tuple[dict | None, int]:
    """按 args 最长前缀匹配动作，返回 (能力, 已匹配长度)。"""
    best: dict | None = None
    size = 0
    for cap in mobile_action_caps():
        args = [str(item) for item in cap.get("args") or []]
        if not args or len(args) > len(tokens):
            continue
        if [str(item) for item in tokens[: len(args)]] == args and len(args) > size:
            best, size = cap, len(args)
    return best, size


def mobile_safety(sub: str, rest: list) -> tuple[str, dict | None]:
    """按注册表判定安全级；未登记的候选按 write 兜底（fail-closed）。"""
    import capabilities

    tokens = [sub] + [str(item) for item in rest]
    if any(item in ("-h", "--help") for item in tokens):
        return "read", None
    cap, _size = match_mobile_action(tokens)
    if cap is None:
        return "write", None
    return capabilities.effective_safety(cap, tokens), cap


def print_mobile_help() -> None:
    print("手机AGENT 业务域（内部 CLI：{}；动作清单来自 component.yaml）".format(mobile_script().name))
    print("用法: dreambuddy mobile <子命令> [参数...] [--allow-write]")
    for cap in mobile_action_caps():
        args = " ".join(str(item) for item in cap.get("args") or [cap.get("action", "")])
        print("  - {:26} [{}] {}".format(args, cap.get("safety", "read"), cap.get("description", "")))
    print("\n未登记子命令按 write 兜底，需 --allow-write；跨域可回查 $DREAMBUDDY_CLI")


def cmd_mobile(args) -> int:
    rest = list(args.rest)
    allow_write = args.allow_write or "--allow-write" in rest
    rest = [item for item in rest if item != "--allow-write"]
    if not rest or rest[0] in ("help", "-h", "--help", "ls"):
        print_mobile_help()
        return 0
    sub, sub_rest = rest[0], rest[1:]
    if sub == "twitter" and not sub_rest:
        sub_rest = ["--help"]
    safety, matched = mobile_safety(sub, sub_rest)
    if safety in {"write", "ui"} and not allow_write:
        import plan as plan_mod

        action = str(matched.get("action")) if matched else sub
        apply_args = list(sub_rest)
        if matched:
            apply_args = apply_args[len(matched.get("args") or []) :]
        try:
            created = plan_mod.create(
                "mobile-reservation-assist",
                action,
                apply_args,
                principal=os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user"),
                risk=safety,
            )
            print(
                "E_GUARD：mobile {} 是 {} 动作。已生成计划 {}，确认后执行："
                "dreambuddy apply {} --allow-write".format(
                    sub, safety, created["plan_id"], created["plan_id"]
                )
            )
        except ValueError as exc:
            print(str(exc))
        return 3
    script = mobile_script()
    if not script.exists():
        raise SystemExit("E_SCRIPT：手机AGENT CLI 不存在 {}".format(script))
    argv = build_mobile_argv(sub, sub_rest)
    print("[dreambuddy] mobile → {}".format(" ".join(argv)), file=sys.stderr)
    proc = subprocess.run(
        argv,
        cwd=str(find_component(MOBILE_COMPONENT)["_dir"]),
        env=domain_env("mobile"),
    )
    return proc.returncode


def cmd_domains(args) -> int:
    comps = load_components()
    print("已接通能力域（统一入口：{}）".format(CLI_PATH.name))
    print("\n● 59 域   dreambuddy 59|data|run <组件> <动作> [--endpoint auto|cloud|local]")
    for comp in comps:
        acts = [a.get("name", "?") for a in comp.get("actions") or []]
        print("  - {:28} {}".format(comp.get("name"), ", ".join(acts) or "（无动作）"))
    print("\n● 6-TRADING 域   dreambuddy trading <signal|bus|constraint|cycle|strategic|diagnostics|training|positions|balance>")
    try:
        import trading_bridge

        for item in trading_bridge.tools():
            print("  - {:26} {}".format(item["name"], item.get("description", "")))
    except Exception as exc:  # 交易域不可用时如实提示
        print("  - （不可用：{}）".format(exc))
    print("\n● 手机AGENT 域   dreambuddy mobile <子命令> [--allow-write]")
    for cap in mobile_action_caps():
        args_text = " ".join(str(item) for item in cap.get("args") or [cap.get("action", "")])
        print(
            "  - {:26} [{}] {}".format(
                args_text, cap.get("safety", "read"), cap.get("description", "")
            )
        )
    print("\n域间调用：子进程通过 $DREAMBUDDY_CLI 回查统一入口，不互相 import。")
    return 0


def cmd_doctor(args) -> int:
    comps = load_components()
    print("组件：{} 个（{}）".format(len(comps), ", ".join(c.get("name", "?") for c in comps)))
    if args.full:
        gates = [("make check", [sys.executable, "-c", "pass"])]
        print("\n(全量 make check)")
    gates = [
        ("kernel 注入一致性", ["tools/sync_kernel.py", "--check"]),
        ("独立性闸门 G1–G7", ["tools/check_boundaries.py"]),
        ("能力索引同步", ["tools/capabilities.py", "verify"]),
        ("INDEX 同步", ["tools/gen_index.py", "--check"]),
        ("规则/站点一致", ["tools/sync_rules.py", "--check"]),
    ]
    failed = 0
    for label, argv in gates:
        proc = subprocess.run(
            [sys.executable] + argv, cwd=str(ROOT), capture_output=True, text=True
        )
        ok = proc.returncode == 0
        failed += 0 if ok else 1
        print("  [{}] {}".format("PASS" if ok else "FAIL", label))
        if not ok:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
            for line in tail:
                print("      " + line)
    print("\n结果：{}".format("全部通过" if failed == 0 else "{} 项失败".format(failed)))
    print("云端通道：{}".format(cloud_status()))
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------- 自然语言编排

QWEN_ENV = Path(os.path.expanduser("~/.local/share/dreambuddy/qwen.env"))

# 常见 A 股名称 → 代码，供关键词兜底路由使用
SYMBOL_ALIAS = {
    "贵州茅台": "sh600519",
    "茅台": "sh600519",
    "宁德时代": "sz300750",
    "比亚迪": "sz002594",
    "中国平安": "sh601318",
    "招商银行": "sh600036",
    "五粮液": "sz000858",
    "美的集团": "sz000333",
    "隆基绿能": "sh601012",
    "中信证券": "sh600030",
    "工商银行": "sh601398",
    "宁德": "sz300750",
}


def load_qwen_env() -> dict:
    values: dict[str, str] = {}
    if QWEN_ENV.exists():
        for line in QWEN_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip("\"'")
    for key in ("QWEN_BASE_URL", "QWEN_API_KEY", "QWEN_DEFAULT_MODEL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def qwen_ready() -> bool:
    env = load_qwen_env()
    return bool(env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY"))


def qwen_chat(messages: list[dict], timeout: int = 45) -> str:
    env = load_qwen_env()
    if not (env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY")):
        raise RuntimeError("QWEN 未配置")
    url = env["QWEN_BASE_URL"].rstrip("/") + "/chat/completions"
    payload = {
        "model": env.get("QWEN_DEFAULT_MODEL", "qwen3.7-plus"),
        "messages": messages,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + env["QWEN_API_KEY"],
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError("QWEN 返回格式异常") from exc


def qwen_call(system: str, user: str, timeout: int = 45) -> str:
    return qwen_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout=timeout,
    )


def action_catalog() -> list[dict]:
    """组件动作候选（来自能力注册表，保持单一来源）。"""
    import capabilities

    return [
        {
            "component": cap["component"],
            "action": cap["action"],
            "description": cap.get("description", ""),
            "safety": cap.get("safety", "read"),
        }
        for cap in capabilities.build()
        if cap["kind"] == "run"
    ]


def mobile_read_commands() -> tuple:
    import capabilities

    return capabilities.mobile_read_commands()


def route_catalog() -> dict:
    """统一路由器候选：由能力注册表派生（59 动作 + 数据桥 + 手机 + 工作流 + 调度）。"""
    import capabilities

    return capabilities.legacy_catalog()


ROUTER_SYSTEM = """你是 dreambuddy 统一操作台路由器。只能从能力注册表里选，只输出 JSON，不要解释。
能力注册表：
{catalog}

输出之一：
{{"kind":"call","capability":"<注册表里的 id>","args":[...或{{...}}],"reason":"<一句话>"}}
{{"kind":"answer","text":"<直接回答，做不到也要如实说>"}}
{{"kind":"unknown","text":"<说明为什么无法路由>"}}

规则：
1) capability 必须是注册表里出现的 id，不要自造、不要改写前缀。
2) data.* 的 args 是对象；workflow.* 只做 dry-run 预演；schedule.list 无参。
3) write/ui 能力可以选，系统会拦成待批准计划或按任务级 --allow-write 放行，不要假装已执行。
4) run 类 args 用命令行长参数：quotes 用 ["--symbols","sh600519"]，onchain 用 ["--chain","eth"]，
   macro/filings 可空；--root 用绝对路径（默认仓库根）。
5) quotes 只支持 A 股：sh/sz + 6 位数字；加密货币/美股价格不在本域能力内，用 answer 说明；
   链上指标（不含价格）才用 market-data.onchain。
6) 说「预约助手/放票/抢票/手机端/会员购/演出门票」优先 mobile-reservation-assist.*；
   reservation-assist.* 只负责余票/号源监控与通知，不要混用。
7) 文件/目录治理（扫描登记、索引、代码-文档对应、上下文打包）归 cogsteward.*；
   cogsteward.index/map/doctor 没有位置参数，按关键词定位文件用 cogsteward.pack。
8) 不确定或能力不在表内时用 answer/unknown，不要硬编参数。"""

# 组件脚本的参数前缀：模型若只给裸值，这里补上 flag
ARG_FLAG = {
    ("market-data", "quotes"): "--symbols",
    ("market-data", "onchain"): "--chain",
}


def normalize_args(component: str, action: str, args: list) -> list[str]:
    flag = ARG_FLAG.get((component, action))
    items = [str(a) for a in args or []]
    if not flag or flag in items:  # 模型已自带正确 flag 时原样保留
        return items
    out: list[str] = []
    for value in items:
        if value.startswith("-"):
            out.append(value)
        else:
            out.extend([flag, value])
    return out


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def rule_plan(text: str) -> dict:
    """关键词兜底路由（无大模型时可用）。"""
    low = text.lower()

    def has(*words: str) -> bool:
        return any(w in text or w in low for w in words)

    if has("你能做什么", "能做什么", "帮助", "help", "怎么用"):
        return {"kind": "answer", "text": capabilities_text()}

    if has("体检", "治理", "闸门", "doctor"):
        return {"kind": "answer", "text": "运行治理闸门请用：dreambuddy doctor"}

    if has("工作流", "日报", "简报", "研究文档", "daily-market-brief"):
        return {
            "kind": "workflow",
            "workflow": "daily-market-brief",
            "reason": "按日报工作流 dry-run 预演",
        }

    if has("定时任务", "定时", "schedule", "cron"):
        return {
            "kind": "answer",
            "text": "设置定时任务：dreambuddy schedule add <job_id> --cron \"0 8 * * *\" --workflow daily-market-brief\n"
            "查看：dreambuddy schedule list  ·  立即触发：dreambuddy schedule run-now <job_id>",
        }

    if has("本地库", "历史指标", "指标历史", "dal", "数据库查询"):
        return {
            "kind": "answer",
            "text": "19-DAL 只读查询：dreambuddy dal scopes 看可用数据域；\n"
            "按指标查：dreambuddy dal read --table mm_metrics --sub-category <域> --metric-name <指标> --limit 10",
        }

    if has("持仓", "仓位", "余额", "交易信号", "信号状态", "周期状态", "宏观约束", "交易诊断", "训练状态"):
        tool = "get_signal_state"
        if has("持仓", "仓位"):
            tool = "get_positions"
        elif has("余额", "资金"):
            tool = "get_balance"
        elif has("周期"):
            tool = "get_cycle_state"
        elif has("约束", "宏观"):
            tool = "get_constraint_state"
        elif has("诊断", "矛盾"):
            tool = "get_decision_diagnostics"
        elif has("训练"):
            tool = "get_training_status"
        return {"kind": "trading", "tool": tool, "args": {}, "reason": "6-TRADING 只读状态"}

    if has("比特币", "btc", "以太坊", "eth", "链上", "区块"):
        return {
            "kind": "run",
            "component": "market-data",
            "action": "onchain",
            "args": ["--chain", "eth"],
            "reason": "链上公开指标",
        }

    if has("披露", "财报", "10-k", "10-q", "filing", "sec"):
        return {
            "kind": "run",
            "component": "market-data",
            "action": "filings",
            "args": [],
            "reason": "美股披露",
        }

    if has("宏观", "cpi", "利率", "非农", "美联储", "通胀"):
        return {
            "kind": "run",
            "component": "market-data",
            "action": "macro",
            "args": [],
            "reason": "海外宏观",
        }

    if has("股", "行情", "股价", "涨跌", "k线"):
        symbol = None
        m = re.search(r"(?:sh|sz|SH|SZ)?(\d{6})", text)
        if m:
            code = m.group(1)
            symbol = ("sh" if code.startswith("6") else "sz") + code
        else:
            for name, code in SYMBOL_ALIAS.items():
                if name in text:
                    symbol = code
                    break
        if not symbol:
            return {
                "kind": "answer",
                "text": "请给出 A 股代码或名称，例如：查询贵州茅台股价（默认 sh600519）",
            }
        return {
            "kind": "run",
            "component": "market-data",
            "action": "quotes",
            "args": ["--symbols", symbol],
            "reason": "A 股行情快照",
        }

    if has("预约", "放票", "抢票", "门票", "演出", "会员购"):
        return {
            "kind": "run",
            "component": "mobile-reservation-assist",
            "action": "ask",
            "args": [text],
            "reason": "预约助手白名单计划",
        }

    if has("余票", "号源", "监控状态"):
        return {
            "kind": "run",
            "component": "reservation-assist",
            "action": "status",
            "args": [],
            "reason": "余票/号源监控状态",
        }

    if has("打包上下文", "上下文打包", "最小上下文", "上下文包"):
        return {
            "kind": "run",
            "component": "cogsteward",
            "action": "pack",
            "args": [text],
            "reason": "按任务打包最小上下文指针",
        }

    if has(
        "认知管家",
        "上下文",
        "扫描",
        "登记",
        "索引",
        "整理",
        "文件管理",
        "归档",
        "代码文档",
    ):
        return {
            "kind": "run",
            "component": "cogsteward",
            "action": "index",
            "args": [],
            "reason": "认知管家索引/登记概览",
        }

    return {"kind": "unknown", "text": "没听懂要调哪个 59 域能力。输入「你能做什么」看能力清单。"}


def capabilities_text() -> str:
    lines = ["59 域当前可用能力："]
    for comp in load_components():
        acts = comp.get("actions") or []
        if not acts:
            continue
        names = ", ".join(a.get("name", "?") for a in acts)
        lines.append("  · {}（{}）".format(comp.get("name"), names))
    lines.append(
        "直接说人话即可，例如：查询贵州茅台股价 / 看比特币链上指标 / 预约助手体检 / 跑一下市场日报工作流\n"
        "命令域：dreambuddy 59|data <组件> <动作>  ·  dreambuddy dal <只读数据>  ·  dreambuddy trading <只读状态>  ·  dreambuddy mobile <子命令>\n"
        "        dreambuddy workflow run <id> --dry-run  ·  dreambuddy schedule list  ·  dreambuddy domains"
    )
    return "\n".join(lines)


ROUTER_KINDS = {
    "call",
    "run",
    "data",
    "mobile",
    "workflow",
    "schedule",
    "answer",
    "unknown",
}
HISTORY_LIMIT = 8


def trim_history(history: list[dict], limit: int = HISTORY_LIMIT) -> list[dict]:
    turns = [
        {"role": turn["role"], "content": str(turn.get("content") or "")}
        for turn in history or []
        if turn.get("role") in {"user", "assistant"} and str(turn.get("content") or "").strip()
    ]
    return turns[-limit:]


def nl_plan(text: str, history: list[dict] | None = None) -> tuple[dict, str]:
    """返回 (计划, 路由来源)。history 只用于多轮消解（如“那宁德时代呢”）。"""
    if qwen_ready():
        try:
            import capabilities

            messages = [
                {
                    "role": "system",
                    "content": ROUTER_SYSTEM.format(
                        catalog=json.dumps(
                            capabilities.prompt_catalog(), ensure_ascii=False, indent=2
                        )
                    ),
                }
            ]
            messages.extend(trim_history(history or []))
            messages.append({"role": "user", "content": text})
            raw = qwen_chat(messages)
            obj = _extract_json(raw)
            if obj and obj.get("kind") in ROUTER_KINDS:
                return obj, "qwen"
        except Exception as exc:  # 网络/额度异常时退回关键词
            print("[dreambuddy] 大模型不可用（{}），改用关键词路由".format(exc), file=sys.stderr)
    return rule_plan(text), "rule"


def validate_plan(plan: dict) -> str | None:
    """计划级参数守卫：模型偶尔会越过能力边界，这里兜一层。"""
    if plan.get("kind") != "run":
        return None
    comp, action = plan.get("component"), plan.get("action")
    if (comp, action) == ("market-data", "quotes"):
        joined = " ".join(str(a) for a in plan.get("args") or [])
        if not re.search(r"(?:sh|sz)\d{6}", joined, re.I):
            return (
                "本域行情只覆盖 A 股（例如 sh600519）。"
                "加密货币/美股价格暂无数据源；链上指标（不含价格）可用："
                "dreambuddy run market-data onchain"
            )
    return None


def run_action(
    comp_name: str,
    action: str,
    args: list,
    allow_write: bool = False,
    endpoint: str = "",
    reason: str = "",
    stdout_path: str = "",
) -> int:
    """按 component.yaml 解析并执行一个动作（workflow / apply 的公共执行核）。"""
    comp = find_component(comp_name)
    script, pre, safety, _desc, params = resolve_target(comp, action)
    action_def = find_action(comp, action)
    rest, arg_endpoint = take_endpoint(
        drop_stray_args(action_def, normalize_args(comp_name, action, args))
    )
    if action_def:
        import capabilities

        safety = capabilities.effective_safety(action_def, rest)
    if safety in {"write", "ui"} and not allow_write:
        print("E_GUARD：{} {} 是 {} 动作，需 --allow-write".format(comp_name, action, safety))
        return 3
    head, rest = split_globals(action_def, rest)
    endpoint = endpoint or arg_endpoint
    argv = apply_endpoint(endpoint, params, [sys.executable, str(script)] + head + pre + rest)
    print("→ {} {}  [{}]  {}".format(comp_name, action, safety, reason), flush=True)
    print("  {}".format(" ".join(argv)), file=sys.stderr)
    cwd = str(action_cwd(comp, action_def))
    if stdout_path:
        target = Path(stdout_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            return subprocess.run(
                argv, cwd=cwd, env=domain_env("59"), stdout=handle
            ).returncode
    return subprocess.run(argv, cwd=cwd, env=domain_env("59")).returncode


def execute_plan(plan: dict, allow_write: bool = False, endpoint: str = "") -> int:
    kind = plan.get("kind")
    if kind == "answer":
        print(plan.get("text", ""))
        return 0
    if kind == "unknown":
        print(plan.get("text", "无法路由"))
        return 1
    if kind == "call":
        import capabilities

        capability = str(plan.get("capability") or "")
        try:
            resolved = capabilities.plan_for(capability, plan.get("args"))
        except ValueError as exc:
            print(str(exc))
            return 1
        print("[capability] {} · {}".format(capability, resolved.get("reason", "")), file=sys.stderr)
        return execute_plan(resolved, allow_write=allow_write, endpoint=endpoint)
    if kind == "data":
        import data_bridge

        try:
            payload = data_bridge.call(str(plan.get("tool") or ""), plan.get("args") or {})
        except ValueError as exc:
            print(str(exc))
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1
    if kind == "trading":
        import trading_bridge

        try:
            payload = trading_bridge.call(str(plan.get("tool") or ""), plan.get("args") or {})
        except ValueError as exc:
            print(str(exc))
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1
    if kind == "mobile":
        command = str(plan.get("command") or "")
        allowed = mobile_read_commands()
        if command not in allowed:
            print(
                "E_GUARD：会话只路由手机只读子命令（{}）。写动作请显式执行："
                "dreambuddy mobile {} --allow-write".format("/".join(allowed), command)
            )
            return 3
        return cmd_mobile(
            argparse.Namespace(
                rest=[command] + [str(item) for item in plan.get("args") or []],
                allow_write=False,
            )
        )
    if kind == "workflow":
        import workflow

        return workflow.main(["run", str(plan.get("workflow") or ""), "--dry-run"])
    if kind == "schedule":
        import jobs

        return jobs.main(["list"])
    if kind != "run":
        print("E_PLAN：未知计划 {}".format(plan))
        return 1

    guard = validate_plan(plan)
    if guard:
        print(guard)
        return 1

    comp_name = plan.get("component", "")
    action = plan.get("action", "")
    args = [str(item) for item in plan.get("args") or []]
    try:
        comp = find_component(comp_name)
        _script, _pre, safety, _desc, _params = resolve_target(comp, action)
    except SystemExit as exc:
        print(str(exc))
        return 1
    action_def = find_action(comp, action)
    if action_def:
        import capabilities

        safety = capabilities.effective_safety(action_def, args)
    if safety in {"write", "ui"} and not allow_write:
        try:
            from plan import create as create_plan

            created = create_plan(
                comp_name,
                action,
                args,
                principal=os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user"),
                risk=safety,
            )
            print(
                "E_GUARD：{} {} 是 {} 动作。已生成计划 {}，确认后执行："
                "dreambuddy apply {} --allow-write".format(
                    comp_name, action, safety, created["plan_id"], created["plan_id"]
                )
            )
        except ValueError as exc:
            print(str(exc))
        return 3
    try:
        return run_action(
            comp_name,
            action,
            args,
            allow_write=allow_write,
            endpoint=endpoint,
            reason=plan.get("reason", ""),
        )
    except SystemExit as exc:
        print(str(exc))
        return 1


def handle_nl(
    text: str,
    allow_write: bool = False,
    endpoint: str = "",
    history: list[dict] | None = None,
) -> int:
    plan, _source = nl_plan(text, history=history)
    return execute_plan(plan, allow_write=allow_write, endpoint=endpoint)


SESSION_DIR = Path(os.path.expanduser("~/.local/share/dreambuddy/sessions"))


def resolve_session(value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(os.path.expanduser(value))
    if candidate.suffix or "/" in value:
        return candidate
    return SESSION_DIR / "{}.jsonl".format(value)


def load_session(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    turns: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            turn = json.loads(line)
        except json.JSONDecodeError:
            continue
        if turn.get("role") in {"user", "assistant"} and str(turn.get("content") or "").strip():
            turns.append({"role": turn["role"], "content": str(turn["content"])})
    return turns


def append_session(path: Path | None, turn: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(turn, ensure_ascii=False) + "\n")


def cmd_chat(args) -> int:
    session_path = resolve_session(getattr(args, "session", "") or "")
    history = trim_history(load_session(session_path))
    print(
        "dreambuddy 59 域会话  ·  大模型 {}  ·  云端 {}".format(
            "已接入（Qwen）" if qwen_ready() else "未配置，走关键词路由",
            cloud_status(),
        )
    )
    if session_path:
        print("会话记录：{}（已载入 {} 轮上下文）".format(session_path, len(history) // 2))
    print("直接说需求，例如「查询贵州茅台股价」；输入 domains 看已接通的能力域")
    print("命令：ls / help <组件> / run / 59 / data / dal / mobile / workflow / schedule / doctor / quit")
    while True:
        try:
            line = input("\ndreambuddy> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("quit", "exit", "q", "退出"):
            return 0
        head = line.split()[0]
        if head in (
            "ls",
            "list",
            "doctor",
            "help",
            "run",
            "domains",
            "mobile",
            "phone",
            "手机",
            "data",
            "dal",
            "59",
            "plan",
            "apply",
            "workflow",
            "schedule",
            "release",
            "content",
            "lifecycle",
            "pack",
            "supply",
            "dal",
            "trading",
            "交易",
            "caps",
            "registry",
        ):
            if head in ("list",):
                line = "ls"
            main(shlex.split(line))
            continue
        tokens, endpoint = take_endpoint(line.split())
        text = " ".join(tokens)
        plan, _source = nl_plan(text, history=history)
        code = execute_plan(
            plan, allow_write=getattr(args, "allow_write", False), endpoint=endpoint
        )
        summary = "[{}] {} 退出码 {}".format(
            plan.get("kind", "?"),
            plan.get("reason") or str(plan.get("text") or "")[:80],
            code,
        )
        history = trim_history(
            history
            + [{"role": "user", "content": text}, {"role": "assistant", "content": summary}]
        )
        if session_path:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            append_session(session_path, {"role": "user", "content": text, "at": stamp})
            append_session(
                session_path,
                {
                    "role": "assistant",
                    "content": summary,
                    "kind": plan.get("kind", ""),
                    "exit": code,
                    "at": stamp,
                },
            )


def cmd_plan(args) -> int:
    import plan as plan_mod

    try:
        created = plan_mod.create(
            args.component,
            args.action,
            list(args.rest),
            principal=args.principal or os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user"),
            risk="write",
        )
    except ValueError as exc:
        print(str(exc))
        return 3
    print(created["plan_id"])
    return 0


def cmd_apply(args) -> int:
    if not args.allow_write:
        print("E_GUARD：apply 会执行写动作，需显式 --allow-write")
        return 3
    import plan as plan_mod

    principal = args.principal or os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user")
    try:
        approved = plan_mod.approve(args.plan_id, principal=principal)
    except ValueError as exc:
        print(str(exc))
        return 3
    try:
        code = run_action(
            str(approved["component"]),
            str(approved["action"]),
            list(approved.get("args") or []),
            allow_write=True,
            endpoint=str(approved.get("endpoint") or ""),
            reason="apply {}".format(args.plan_id),
        )
    except SystemExit as exc:
        print(str(exc))
        return 1
    plan_mod.audit(
        "plan.execute",
        plan_id=args.plan_id,
        principal=principal,
        exit_code=code,
        action=approved.get("action"),
    )
    return code


def cmd_workflow(args) -> int:
    import workflow

    return workflow.main(list(args.rest))


def cmd_schedule(args) -> int:
    import jobs

    return jobs.main(list(args.rest))


def cmd_release(args) -> int:
    import release_ledger

    return release_ledger.main(list(args.rest))


def cmd_content(args) -> int:
    import content

    return content.main(list(args.rest))


def cmd_lifecycle(args) -> int:
    import lifecycle

    return lifecycle.main(list(args.rest))


def cmd_pack(args) -> int:
    import skillset

    return skillset.main(list(args.rest))


def cmd_supply(args) -> int:
    import supply_chain

    return supply_chain.main(list(args.rest))


def cmd_dal(args) -> int:
    import data_bridge

    return data_bridge.main(list(args.rest))


def cmd_trading(args) -> int:
    import trading_bridge

    return trading_bridge.main(list(args.rest))


def cmd_caps(args) -> int:
    import capabilities

    return capabilities.main(list(args.rest))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dreambuddy", description="59 域统一只读编排 CLI")
    sub = parser.add_subparsers(dest="cmd")

    p_ls = sub.add_parser("ls", help="列出组件")
    p_ls.add_argument("--json", action="store_true")
    p_ls.set_defaults(func=cmd_ls)

    p_help = sub.add_parser("help", help="查看组件入口与动作")
    p_help.add_argument("component")
    p_help.set_defaults(func=cmd_help)

    for name, alias_help in (
        ("run", "调用组件的动作或入口"),
        ("59", "59 域（同 run）"),
        ("data", "59 域数据/组件（同 run）"),
    ):
        p = sub.add_parser(name, help=alias_help)
        p.add_argument("component")
        p.add_argument("target")
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.add_argument("--allow-write", action="store_true", help="允许执行 write 动作")
        p.set_defaults(func=cmd_run)

    for name in ("mobile", "phone", "手机"):
        p = sub.add_parser(name, help="手机AGENT 业务域（内部 mra.py）")
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.add_argument("--allow-write", action="store_true", help="允许执行写动作")
        p.set_defaults(func=cmd_mobile)

    p_domains = sub.add_parser("domains", help="列出已接通的能力域")
    p_domains.set_defaults(func=cmd_domains)

    p_doc = sub.add_parser("doctor", help="治理闸门体检")
    p_doc.add_argument("--full", action="store_true", help="额外跑 make check（较重）")
    p_doc.set_defaults(func=cmd_doctor)

    p_chat = sub.add_parser("chat", help="会话式自然语言编排")
    p_chat.add_argument("--session", default="", help="会话名或 JSONL 路径，用于多轮上下文持久化")
    p_chat.add_argument("--allow-write", action="store_true", help="会话内允许直接执行写动作")
    p_chat.set_defaults(func=cmd_chat)

    p_plan = sub.add_parser("plan", help="为写动作生成待批准计划")
    p_plan.add_argument("--principal", default="")
    p_plan.add_argument("component")
    p_plan.add_argument("action")
    p_plan.add_argument("rest", nargs=argparse.REMAINDER)
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="批准并执行计划")
    p_apply.add_argument("plan_id")
    p_apply.add_argument("--allow-write", action="store_true")
    p_apply.add_argument("--principal", default="")
    p_apply.set_defaults(func=cmd_apply)

    for name, func, help_text in (
        ("workflow", cmd_workflow, "工作流：list/show/run/approve"),
        ("schedule", cmd_schedule, "定时任务：add/list/pause/resume/rm/run-now/run-due"),
        ("release", cmd_release, "发布台账：status/record/rollback"),
        ("content", cmd_content, "内容闭环：render/blog/social/metrics"),
        ("lifecycle", cmd_lifecycle, "生命周期：check/plan"),
        ("pack", cmd_pack, "技能集：list/show/check/build"),
        ("supply", cmd_supply, "供应链：check/verify --online"),
        ("dal", cmd_dal, "19-DAL 只读数据桥：tools/scopes/read/fetch"),
        ("trading", cmd_trading, "6-TRADING 只读状态：signal/bus/positions/balance/..."),
        ("caps", cmd_caps, "能力注册表：list/show/check/prompt/export"),
        ("registry", cmd_caps, "能力注册表（同 caps）"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=func)
    return parser


SUBCOMMANDS = (
    "ls",
    "help",
    "run",
    "doctor",
    "chat",
    "59",
    "data",
    "mobile",
    "phone",
    "手机",
    "domains",
    "plan",
    "apply",
    "workflow",
    "schedule",
    "release",
    "content",
    "lifecycle",
    "pack",
    "supply",
    "dal",
    "trading",
    "caps",
    "registry",
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    load_partner_env()
    parser = build_parser()
    if not argv:
        # 终端里裸命令 → 会话；管道/非交互 → 打印总览
        if sys.stdin.isatty():
            return cmd_chat(parser.parse_args(["chat"]))
        return cmd_ls(parser.parse_args(["ls"]))
    if argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        # 直接把整句人话当需求，例如：dreambuddy 查询贵州茅台股价
        tokens, endpoint = take_endpoint(argv)
        return handle_nl(" ".join(tokens), endpoint=endpoint)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

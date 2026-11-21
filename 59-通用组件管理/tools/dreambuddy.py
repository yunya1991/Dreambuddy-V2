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
    rest, endpoint = take_endpoint(list(args.rest))
    # argparse.REMAINDER 会把尾随的 --allow-write 吞进来，这里还原成开关
    allow_write = args.allow_write or "--allow-write" in rest
    rest = [item for item in rest if item != "--allow-write"]
    if not script.exists():
        raise SystemExit("E_SCRIPT：脚本不存在 {}".format(script))
    if safety in {"write", "ui"} and not allow_write:
        print("E_GUARD：动作 {} 标记为 {}，需加 --allow-write 才能执行".format(args.target, safety))
        return 3
    cmd = apply_endpoint(endpoint, params, [sys.executable, str(script)] + pre + rest)
    print("[dreambuddy] {} → {}".format(comp.get("name"), " ".join(cmd)), file=sys.stderr)
    proc = subprocess.run(cmd, cwd=str(comp["_dir"]), env=domain_env("59"))
    return proc.returncode


# ---------------------------------------------------------------- 手机AGENT 业务域

MOBILE_COMPONENT = "mobile-reservation-assist"
RESERVATION_COMPONENT = "reservation-assist"
MOBILE_WRITE = {"dispatch", "ingest", "pause", "resume"}
MOBILE_LONG = {"gateway", "chat"}
# 内容流水线：compose/trends/collect/data 不碰手机 UI；其余（scout/post/cover/memo/chain）有 UI 副作用
MOBILE_CONTENT = {"xhs", "douyin"}
MOBILE_CONTENT_READ = {"compose", "trends", "collect", "data"}
MOBILE_COMMANDS = (
    ("doctor", "read", "环境自检"),
    ("jobs", "read", "预约作业清单（--state 过滤）"),
    ("report", "read", "reservation.v1 报告"),
    ("reconcile", "read", "订单对账（order_unknown）"),
    ("knowledge", "read", "平台规则知识问答（引用+置信度）"),
    ("explore", "read", "探索录制 / 适配器草案 / 回放门禁"),
    ("devices", "read", "设备心跳与在线状态"),
    ("regression", "read", "适配器批量回归"),
    ("patrol", "read", "巡检诊断（--auto-fix 为写）"),
    ("ask", "read", "自然语言→白名单计划（--execute 为写）"),
    ("token", "read", "查看/生成网关 Token"),
    ("xhs", "ui", "小红书流水线：scout/trends/collect/data/compose/cover/post/chain"),
    ("douyin", "ui", "抖音流水线：scout/trends/collect/data/compose/cover/post/chain"),
    ("ingest", "write", "归一上游命中并入队"),
    ("dispatch", "write", "自然语言下发预约作业（--dry-run 只解析）"),
    ("pause", "write", "暂停派发"),
    ("resume", "write", "恢复派发"),
    ("gateway", "long", "启动本地 HTTP 网关（前台常驻）"),
    ("chat", "long", "会话模式（前台交互）"),
)


def domain_env(domain: str) -> dict:
    """子进程环境：透传 CLI 路径，供另一域反向调用统一入口。"""
    env = dict(os.environ)
    env["DREAMBUDDY_CLI"] = str(CLI_PATH)
    env["DREAMBUDDY_DOMAIN"] = domain
    return env


def mobile_script() -> Path:
    return script_path(find_component(MOBILE_COMPONENT), "scripts/mra.py")


def mobile_safety(sub: str, rest: list) -> str:
    if sub in MOBILE_WRITE:
        return "write"
    if sub in MOBILE_CONTENT:
        second = rest[0] if rest and not rest[0].startswith("-") else ""
        return "read" if second in MOBILE_CONTENT_READ else "ui"
    if sub == "ask" and "--execute" in rest:
        return "write"
    if sub == "patrol" and "--auto-fix" in rest:
        return "write"
    if sub in MOBILE_LONG:
        return "long"
    return "read"


def build_mobile_argv(sub: str, rest: list) -> list[str]:
    """组装 mra.py 调用；ingest 未给 --ra-cli 时自动接上 59 域 reservation-assist。"""
    argv = [sys.executable, str(mobile_script()), sub] + list(rest)
    if sub == "ingest" and "--ra-cli" not in rest:
        ra = script_path(find_component(RESERVATION_COMPONENT), "scripts/ra.py")
        if ra.exists():
            argv += ["--ra-cli", str(ra)]
    return argv


def print_mobile_help() -> None:
    print("手机AGENT 业务域（内部 CLI：{}）".format(mobile_script().name))
    print("用法: dreambuddy mobile <子命令> [参数...] [--allow-write]")
    for name, safety, desc in MOBILE_COMMANDS:
        print("  - {:10} [{}] {}".format(name, safety, desc))
    print("\n跨域：手机AGENT 子进程可用 $DREAMBUDDY_CLI 回查 59 域，例如")
    print("      $DREAMBUDDY_CLI data market-data quotes --symbols sh600519")


def cmd_mobile(args) -> int:
    rest = list(args.rest)
    allow_write = args.allow_write or "--allow-write" in rest
    rest = [item for item in rest if item != "--allow-write"]
    if not rest or rest[0] in ("help", "-h", "--help", "ls"):
        print_mobile_help()
        return 0
    sub, sub_rest = rest[0], rest[1:]
    safety = mobile_safety(sub, sub_rest)
    if safety in {"write", "ui"} and not allow_write:
        import plan as plan_mod

        action = sub
        apply_args = list(sub_rest)
        if sub in MOBILE_CONTENT and sub_rest:
            action = "{}-{}".format(sub, sub_rest[0])
            apply_args = list(sub_rest[1:])
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
    print("\n● 手机AGENT 域   dreambuddy mobile <子命令> [--allow-write]")
    for name, safety, desc in MOBILE_COMMANDS:
        print("  - {:10} [{}] {}".format(name, safety, desc))
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


def qwen_call(system: str, user: str, timeout: int = 45) -> str:
    env = load_qwen_env()
    if not (env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY")):
        raise RuntimeError("QWEN 未配置")
    url = env["QWEN_BASE_URL"].rstrip("/") + "/chat/completions"
    payload = {
        "model": env.get("QWEN_DEFAULT_MODEL", "qwen3.7-plus"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
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


def action_catalog() -> list[dict]:
    """把所有组件的 actions 摊平成路由候选。"""
    items: list[dict] = []
    for comp in load_components():
        for act in comp.get("actions") or []:
            items.append(
                {
                    "component": comp.get("name"),
                    "action": act.get("name"),
                    "description": act.get("description", ""),
                    "safety": act.get("safety", "read"),
                }
            )
    return items


ROUTER_SYSTEM = """你是 59 域组件编排路由器。只输出 JSON，不要解释。
可选动作清单（component/action/description/safety）：
{catalog}

输出之一：
{{"kind":"run","component":"<组件>","action":"<动作>","args":["<附加参数>"],"reason":"<一句话>"}}
{{"kind":"answer","text":"<直接回答，说明 59 域当前没有对应能力时也要如实说>"}}
{{"kind":"unknown","text":"<说明为什么无法路由>"}}

规则：
1) 只能选清单里的 component+action，不得编造。
2) args 是传给组件脚本的附加命令行参数，必须带前缀，例如 quotes 用 ["--symbols","sh600519"]，
   onchain 用 ["--chain","eth"]；A 股代码用 sh/sz 前缀。
3) quotes 只支持 A 股：代码必须是 sh/sz + 6 位数字（如 sh600519）。
   加密货币（BTC/ETH）价格、美股价格不在本域能力内，必须用 answer 如实说明；
   链上指标（不含价格）才用 onchain。
4) safety=write 的动作也可以选，但需用户授权，系统会拦。
5) 说「预约助手/放票/抢票/手机端/会员购/演出门票」时，优先 mobile-reservation-assist；
   reservation-assist 只负责余票/号源监控与通知，不要混用。"""

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

    if has("上下文", "登记", "索引", "扫描"):
        return {
            "kind": "run",
            "component": "cogsteward",
            "action": "selfcheck",
            "args": [],
            "reason": "上下文治理自检",
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
        "直接说人话即可，例如：查询贵州茅台股价 / 看比特币链上指标 / 预约助手体检\n"
        "命令域：dreambuddy 59|data <组件> <动作>  ·  dreambuddy mobile <子命令>  ·  dreambuddy domains"
    )
    return "\n".join(lines)


def nl_plan(text: str) -> tuple[dict, str]:
    """返回 (计划, 路由来源)。"""
    if qwen_ready():
        try:
            raw = qwen_call(
                ROUTER_SYSTEM.format(
                    catalog=json.dumps(action_catalog(), ensure_ascii=False, indent=2)
                ),
                text,
            )
            obj = _extract_json(raw)
            if obj and obj.get("kind") in ("run", "answer", "unknown"):
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
    if safety in {"write", "ui"} and not allow_write:
        print("E_GUARD：{} {} 是 {} 动作，需 --allow-write".format(comp_name, action, safety))
        return 3
    rest, arg_endpoint = take_endpoint(normalize_args(comp_name, action, args))
    endpoint = endpoint or arg_endpoint
    argv = apply_endpoint(endpoint, params, [sys.executable, str(script)] + pre + rest)
    print("→ {} {}  [{}]  {}".format(comp_name, action, safety, reason), flush=True)
    print("  {}".format(" ".join(argv)), file=sys.stderr)
    if stdout_path:
        target = Path(stdout_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            return subprocess.run(
                argv, cwd=str(comp["_dir"]), env=domain_env("59"), stdout=handle
            ).returncode
    return subprocess.run(argv, cwd=str(comp["_dir"]), env=domain_env("59")).returncode


def execute_plan(plan: dict, allow_write: bool = False, endpoint: str = "") -> int:
    kind = plan.get("kind")
    if kind == "answer":
        print(plan.get("text", ""))
        return 0
    if kind == "unknown":
        print(plan.get("text", "无法路由"))
        return 1
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


def handle_nl(text: str, allow_write: bool = False, endpoint: str = "") -> int:
    plan, source = nl_plan(text)
    if source == "rule" and plan.get("kind") == "run":
        # 关键词兜底命中也标明，方便排查大模型是否生效
        pass
    return execute_plan(plan, allow_write=allow_write, endpoint=endpoint)


def cmd_chat(args) -> int:
    print(
        "dreambuddy 59 域会话  ·  大模型 {}  ·  云端 {}".format(
            "已接入（Qwen）" if qwen_ready() else "未配置，走关键词路由",
            cloud_status(),
        )
    )
    print("直接说需求，例如「查询贵州茅台股价」；输入 domains 看已接通的能力域")
    print("命令：ls / help <组件> / run / 59 / data / mobile / doctor / quit")
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
            "59",
            "plan",
            "apply",
            "workflow",
            "schedule",
            "release",
            "content",
        ):
            if head in ("list",):
                line = "ls"
            main(shlex.split(line))
            continue
        tokens, endpoint = take_endpoint(line.split())
        handle_nl(" ".join(tokens), endpoint=endpoint)


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

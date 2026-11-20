#!/usr/bin/env python3
"""59 域可发现性路由基准。

回答一个问题：用户装了一堆 skill 时，agent 会不会首选我们、有没有选错。

用法:
    python3 platform/bench/routing/run_bench.py --dry-run
    python3 platform/bench/routing/run_bench.py --router qwen
    python3 platform/bench/routing/run_bench.py --router qwen --json /tmp/bench.json
    python3 platform/bench/routing/run_bench.py --router qwen --compare /tmp/baseline.json

指标:
    coverage_hit_rate    期望命中率（覆盖意图里选对我们的比例）
    ours_selection_rate  所有意图里选中我们的比例
    wrong_our_tool       选了我们但选错动作（假阳性，最伤体验）
    false_positive_rate  越界意图里仍选我们的比例
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

BENCH_DIR = Path(__file__).resolve().parent
MODULE_ROOT = BENCH_DIR.parents[2]  # 59-通用组件管理/
REPO_ROOT = MODULE_ROOT.parent  # dreambuddy-v2/
INTENTS_DEFAULT = BENCH_DIR / "intents.yaml"
COMPETITORS_DEFAULT = BENCH_DIR / "competitors.yaml"

# 历史命名快照：仅用于 name-only A/B 对照
NAME_ALIASES = {
    "r2": {
        "sec_filing_reader": "us_sec_filings",
        "ticket_reservation": "reservation_plan",
    },
    "legacy": {
        "a_share_quote": "market_data_quotes",
        "sec_filing_reader": "market_data_filings",
        "ticket_reservation": "mobile_reservation_assist_ask",
        "a_share_index_facts": "market_facts_daily_facts",
        "official_fed_sec_event_search": "event_context_events",
        "ticket_monitor_list": "reservation_assist_list",
        "ticket_monitor_report": "reservation_assist_report",
        "reservation_job_list": "mobile_reservation_assist_jobs",
    },
}
NAME_ALIAS_REVERSE = {
    style: {old: new for new, old in mapping.items()} for style, mapping in NAME_ALIASES.items()
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载模块：{}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_fixtures(intents_path: Path, competitors_path: Path) -> tuple[List[dict], List[dict]]:
    intents = (yaml.safe_load(intents_path.read_text(encoding="utf-8")) or {}).get("intents") or []
    competitors = (yaml.safe_load(competitors_path.read_text(encoding="utf-8")) or {}).get(
        "competitors"
    ) or []
    return intents, competitors


def our_tools() -> List[dict]:
    module = _load_module(
        "l0_components_server", REPO_ROOT / "mcp_shells" / "l0_components" / "server.py"
    )
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "when_to_use": tool.get("when_to_use", ""),
            "not_for": tool.get("not_for", ""),
            "owner": "dreambuddy",
        }
        for tool in module.build_tools("all")
    ]


def build_catalog(
    tools: List[dict],
    competitors: List[dict],
    fields: str = "both",
    name_style: str = "current",
) -> List[dict]:
    catalog: List[dict] = []
    for item in list(tools) + [
        {
            "name": competitor["name"],
            "description": competitor["description"],
            "when_to_use": "",
            "not_for": "",
            "owner": "competitor",
        }
        for competitor in competitors
    ]:
        name = item["name"]
        if name_style in NAME_ALIASES:
            name = NAME_ALIASES[name_style].get(name, name)
        catalog.append(
            {
                "name": name,
                "description": item["description"],
                "owner": item["owner"],
                "when_to_use": item.get("when_to_use", ""),
                "not_for": item.get("not_for", ""),
            }
        )
    if fields not in {"both", "name", "guidance", "full"}:
        raise ValueError("fields 必须是 both / name / guidance / full")
    return catalog


def format_catalog(catalog: List[dict], fields: str) -> str:
    if fields == "name":
        return "\n".join("- {}".format(item["name"]) for item in catalog)
    if fields == "guidance":
        lines = []
        for item in catalog:
            parts = ["- {}".format(item["name"])]
            if item.get("when_to_use"):
                parts.append("适用：{}".format(item["when_to_use"]))
            if item.get("not_for"):
                parts.append("不适用：{}".format(item["not_for"]))
            lines.append(" | ".join(parts))
        return "\n".join(lines)
    if fields == "full":
        lines = []
        for item in catalog:
            line = "- {}: {}".format(item["name"], item["description"])
            if item.get("when_to_use"):
                line += " 适用：{}".format(item["when_to_use"])
            if item.get("not_for"):
                line += " 不适用：{}".format(item["not_for"])
            lines.append(line)
        return "\n".join(lines)
    return "\n".join("- {}: {}".format(item["name"], item["description"]) for item in catalog)


def validate(intents: List[dict], competitors: List[dict], tools: List[dict]) -> List[str]:
    errors: List[str] = []
    our_names = {tool["name"] for tool in tools}
    comp_names = {item["name"] for item in competitors}
    if our_names & comp_names:
        errors.append("工具名与竞品重名：{}".format(sorted(our_names & comp_names)))
    seen: set[str] = set()
    for intent in intents:
        intent_id = intent.get("id")
        if not intent_id:
            errors.append("意图缺少 id：{}".format(intent))
            continue
        if intent_id in seen:
            errors.append("意图 id 重复：{}".format(intent_id))
        seen.add(intent_id)
        expect = intent.get("expect_tool")
        if expect and expect not in our_names:
            errors.append("{} 期望工具不存在：{}".format(intent_id, expect))
        if not str(intent.get("text") or "").strip():
            errors.append("{} 缺少 text".format(intent_id))
    return errors


ROUTER_SYSTEM = """你是 AI 工具路由器。用户给出一个需求，你只能从候选工具中选一个最合适的。
候选工具列表：
{catalog}

输出严格 JSON，不要解释：
{{"choice": "<候选 name 或 none>", "reason": "<不超过 20 字>"}}

规则：
1) choice 只能是候选里出现过的 name，或 none。
2) 必须匹配用户真正要的实体与动作，不要只因为工具名相似就选。
3) 若没有工具能完成（如实时加密货币价格、投资建议、写代码、天气），必须选 none。"""


def extract_choice(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            choice = str(obj.get("choice") or "").strip()
        except json.JSONDecodeError:
            choice = ""
    else:
        match = re.search(r"choice\s*[:=]\s*[\"']?([A-Za-z0-9_\-]+|none)", raw, re.I)
        choice = match.group(1) if match else ""
    if not choice or choice.lower() in {"none", "null", "无", "没有", "n/a"}:
        return "none"
    return choice


def normalize_choice(choice: str, name_style: str) -> str:
    return NAME_ALIAS_REVERSE.get(name_style, {}).get(choice, choice)


def score(results: List[dict], our_names: set[str]) -> Dict[str, Any]:
    covered = [item for item in results if item["expect_tool"]]
    hits = [item for item in covered if item["choice"] == item["expect_tool"]]
    ours_selected = [item for item in results if item["choice"] in our_names]
    wrong_ours = [
        item
        for item in covered
        if item["choice"] in our_names and item["choice"] != item["expect_tool"]
    ]
    out_of_scope = [item for item in results if not item["expect_tool"]]
    false_positive = [item for item in out_of_scope if item["choice"] in our_names]

    categories: Dict[str, Dict[str, int]] = {}
    for item in results:
        bucket = categories.setdefault(
            item.get("category") or "other", {"total": 0, "covered": 0, "hits": 0, "fp": 0}
        )
        bucket["total"] += 1
        if item["expect_tool"]:
            bucket["covered"] += 1
            if item["choice"] == item["expect_tool"]:
                bucket["hits"] += 1
        elif item["choice"] in our_names:
            bucket["fp"] += 1

    latency = [item["latency_ms"] for item in results if item.get("latency_ms") is not None]
    chars = [item.get("prompt_chars", 0) for item in results]
    return {
        "total": len(results),
        "covered": len(covered),
        "coverage_hits": len(hits),
        "coverage_hit_rate": round(len(hits) / len(covered), 4) if covered else 0.0,
        "ours_selected": len(ours_selected),
        "ours_selection_rate": round(len(ours_selected) / len(results), 4) if results else 0.0,
        "wrong_our_tool": len(wrong_ours),
        "out_of_scope": len(out_of_scope),
        "false_positive": len(false_positive),
        "false_positive_rate": (
            round(len(false_positive) / len(out_of_scope), 4) if out_of_scope else 0.0
        ),
        "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else 0.0,
        "avg_prompt_chars": round(sum(chars) / len(chars), 1) if chars else 0.0,
        "categories": categories,
    }


def print_report(
    metrics: Dict[str, Any], results: List[dict], our_names: set[str], model: str = ""
) -> None:
    print("\n59 域路由基准{}".format("（model={}）".format(model) if model else ""))
    print(
        "  意图 {} 条：覆盖 {} / 越界 {}".format(
            metrics["total"], metrics["covered"], metrics["out_of_scope"]
        )
    )
    print(
        "  覆盖命中率      {:.1%}  ({}/{})".format(
            metrics["coverage_hit_rate"], metrics["coverage_hits"], metrics["covered"]
        )
    )
    print(
        "  选中我们的比例  {:.1%}  ({}/{})".format(
            metrics["ours_selection_rate"], metrics["ours_selected"], metrics["total"]
        )
    )
    print("  选错我们的动作  {} 条".format(metrics["wrong_our_tool"]))
    print(
        "  越界误选率      {:.1%}  ({}/{})".format(
            metrics["false_positive_rate"], metrics["false_positive"], metrics["out_of_scope"]
        )
    )
    print("  平均时延        {:.0f} ms".format(metrics["avg_latency_ms"]))
    print("  平均 prompt     {:.0f} 字符".format(metrics["avg_prompt_chars"]))

    print("\n分类：")
    for name, bucket in sorted(metrics["categories"].items()):
        if bucket["covered"]:
            rate = bucket["hits"] / bucket["covered"]
            print(
                "  {:14} 命中 {}/{} ({:.0%}){}".format(
                    name,
                    bucket["hits"],
                    bucket["covered"],
                    rate,
                    "  越界误选 {}".format(bucket["fp"]) if bucket["fp"] else "",
                )
            )
        else:
            print("  {:14} 越界 {} 条，误选 {}".format(name, bucket["total"], bucket["fp"]))

    misses = [
        item for item in results if item["expect_tool"] and item["choice"] != item["expect_tool"]
    ]
    if misses:
        print("\n未命中明细：")
        for item in misses[:10]:
            print(
                "  [{}] {}\n      期望 {} | 实选 {} | {}".format(
                    item["id"],
                    item["text"],
                    item["expect_tool"],
                    item["choice"],
                    item.get("reason", ""),
                )
            )


def compare(metrics: Dict[str, Any], previous: Dict[str, Any]) -> None:
    print("\n对比基线：")
    for key, label in (
        ("coverage_hit_rate", "覆盖命中率"),
        ("ours_selection_rate", "选中我们的比例"),
        ("false_positive_rate", "越界误选率"),
        ("avg_latency_ms", "平均时延(ms)"),
    ):
        old = previous.get(key, 0)
        new = metrics.get(key, 0)
        if key.endswith("_rate"):
            print("  {:16} {:.1%} → {:.1%}  ({:+.1%})".format(label, old, new, new - old))
        else:
            print("  {:16} {:.0f} → {:.0f}  ({:+.0f})".format(label, old, new, new - old))


def _ensure_ssl_cert() -> None:
    """部分环境缺少系统根证书；未显式配置时用 certifi，避免整轮误判为 error。"""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="59 域可发现性路由基准")
    parser.add_argument("--intents", type=Path, default=INTENTS_DEFAULT)
    parser.add_argument("--competitors", type=Path, default=COMPETITORS_DEFAULT)
    parser.add_argument("--router", choices=["qwen"], default="qwen")
    parser.add_argument("--model", default="", help="覆盖 QWEN_DEFAULT_MODEL，用于强弱模型对照")
    parser.add_argument(
        "--catalog-fields",
        choices=["both", "name", "guidance", "full"],
        default="both",
        help="full=描述+适用/不适用（真实 MCP 面）；guidance=只给名字+边界",
    )
    parser.add_argument(
        "--name-style",
        choices=["current", "r2", "legacy"],
        default="current",
        help="r2/legacy 把当前名还原成历史名，用于 name-only A/B",
    )
    parser.add_argument("--ids", default="", help="逗号分隔意图 id，只跑这些（定向实验）")
    parser.add_argument("--dry-run", action="store_true", help="只校验夹具与候选集，不调用模型")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试）")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--retries", type=int, default=1, help="单条调用失败重试次数，避免网络抖动被算成路由退化"
    )
    parser.add_argument("--json", type=Path, default=None, help="写入完整报告 JSON")
    parser.add_argument("--compare", type=Path, default=None, help="与历史报告对比")
    args = parser.parse_args(argv)
    _ensure_ssl_cert()
    if args.model:
        os.environ["QWEN_DEFAULT_MODEL"] = args.model
    model_name = os.environ.get("QWEN_DEFAULT_MODEL", "qwen3.7-plus")

    intents, competitors = load_fixtures(args.intents, args.competitors)
    tools = our_tools()
    errors = validate(intents, competitors, tools)
    if errors:
        print("E_FIXTURE：夹具校验失败", file=sys.stderr)
        for error in errors:
            print("  - {}".format(error), file=sys.stderr)
        return 1

    catalog = build_catalog(tools, competitors, args.catalog_fields, args.name_style)
    our_names = {tool["name"] for tool in tools}
    covered = sum(1 for item in intents if item.get("expect_tool"))

    if args.dry_run:
        print(
            "夹具校验通过：{} 条意图（覆盖 {} / 越界 {}），候选工具 {} 个（我们 {} + 竞品 {}）".format(
                len(intents),
                covered,
                len(intents) - covered,
                len(catalog),
                len(tools),
                len(competitors),
            )
        )
        print(
            "模式：catalog_fields={} / name_style={}".format(args.catalog_fields, args.name_style)
        )
        for item in catalog:
            print("  - {:34} [{}] {}".format(item["name"], item["owner"], item["description"]))
        return 0

    dreambuddy = _load_module("dreambuddy_cli", MODULE_ROOT / "tools" / "dreambuddy.py")
    if not dreambuddy.qwen_ready():
        print(
            "E_ENV：Qwen 未配置。写入 ~/.local/share/dreambuddy/qwen.env "
            "（QWEN_BASE_URL / QWEN_API_KEY / QWEN_DEFAULT_MODEL），或先用 --dry-run。",
            file=sys.stderr,
        )
        return 2

    catalog_text = format_catalog(catalog, args.catalog_fields)
    system = ROUTER_SYSTEM.format(catalog=catalog_text)
    selected = intents
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        selected = [item for item in intents if item["id"] in wanted]
        missing = wanted - {item["id"] for item in selected}
        if missing:
            print("E_FIXTURE：找不到意图 id {}".format(sorted(missing)), file=sys.stderr)
            return 1
    if args.limit:
        selected = selected[: args.limit]

    results: List[dict] = []
    for index, intent in enumerate(selected, start=1):
        started = time.time()
        choice, reason = "error", ""
        for attempt in range(args.retries + 1):
            try:
                raw = dreambuddy.qwen_call(system, intent["text"], timeout=args.timeout)
                choice = normalize_choice(extract_choice(raw), args.name_style)
                reason = raw.replace("\n", " ")[:80]
                break
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响整体
                reason = "{}".format(exc)
                if attempt < args.retries:
                    time.sleep(1)
        latency_ms = int((time.time() - started) * 1000)
        results.append(
            {
                "id": intent["id"],
                "text": intent["text"],
                "category": intent.get("category", "other"),
                "expect_tool": intent.get("expect_tool"),
                "choice": choice,
                "reason": reason,
                "latency_ms": latency_ms,
                "prompt_chars": len(system) + len(intent["text"]),
            }
        )
        print(
            "  [{:02d}/{}] {} → {}".format(index, len(selected), intent["id"], choice),
            file=sys.stderr,
        )

    metrics = score(results, our_names)
    print_report(metrics, results, our_names, model_name)

    if args.compare and args.compare.is_file():
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        compare(metrics, previous.get("metrics") or {})

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "router": args.router,
                    "model": model_name,
                    "catalog_fields": args.catalog_fields,
                    "name_style": args.name_style,
                    "metrics": metrics,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("\n报告已写入：{}".format(args.json))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

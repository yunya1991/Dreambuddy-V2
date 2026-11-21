"""P1 内容闭环内置步骤：研究文档、博文草稿、社媒物料包、效果回流。

所有数字都来自 facts.json，报告与 claim_map 同步生成；任何未映射的百分数都会阻断。
不调用大模型：先用确定性模板跑通契约，LLM 只做后续润色（P1.5）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

MODULE_ROOT = Path(__file__).resolve().parents[1]
BLOG_DIR = MODULE_ROOT / "platform" / "site" / "blog" / "posts"
METRICS_PATH = MODULE_ROOT / "platform" / "ops" / "metrics.csv"

PCT_RE = re.compile(r"[-+]?\d+\.\d+%")
DISCLAIMER = "本文仅为数据研究与方法展示，不构成投资建议。"
FORBIDDEN = ("目标价", "买入", "卖出", "稳赚", "必涨", "翻倍", "内幕", "加微信", "二维码", "荐股")

METHODS = {
    "d1": ("M01", "1日涨跌"),
    "d5": ("M01", "5日涨跌"),
    "d20": ("M01", "20日涨跌"),
    "pctile": ("M02", "250日分位"),
    "vol": ("M03", "20日年化波动"),
    "mdd": ("M04", "250日最大回撤"),
    "ma60": ("M05", "60日均线偏离"),
}

METRIC_FIELDS = [
    "content_id",
    "platform",
    "url",
    "published_at",
    "impressions",
    "likes",
    "saves",
    "comments",
    "clicks",
]


class ContentError(Exception):
    pass


def _pct(value: float) -> str:
    return "{:+.2f}%".format(float(value) * 100)


def _num(value: float) -> str:
    return "{:.2f}".format(float(value))


def _format_fact(field: str, value: float) -> str:
    if field == "pctile":
        return "{:.1f}%".format(float(value) * 100)
    if field == "vol":
        return "{:.2f}%".format(float(value) * 100)
    return _pct(value)


def load_facts(path: str | Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("rows"):
        raise ContentError("E_FACTS：facts.json 缺少 rows")
    return data


def build_claims(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for row in facts.get("rows") or []:
        symbol = str(row.get("symbol") or "")
        name = str(row.get("name") or symbol)
        facts_list: List[Dict[str, Any]] = [
            {
                "fact_id": "{}.close".format(symbol),
                "field": "close",
                "value": row.get("close"),
                "formatted": _num(row.get("close") or 0),
                "unit": "点",
                "method_id": "",
                "sample_size": row.get("n"),
                "source": row.get("source"),
            }
        ]
        for key, (method_id, label) in METHODS.items():
            if row.get(key) is None:
                continue
            facts_list.append(
                {
                    "fact_id": "{}.{}".format(symbol, key),
                    "field": key,
                    "label": label,
                    "value": row.get(key),
                    "formatted": _format_fact(key, row.get(key)),
                    "unit": "%",
                    "method_id": method_id,
                    "sample_size": row.get("{}_n".format(key)) or row.get("n"),
                    "source": row.get("source"),
                }
            )
        claims.append(
            {
                "claim_id": symbol,
                "text": "{}（{}）".format(name, symbol),
                "data_date": row.get("date") or facts.get("data_date"),
                "facts": facts_list,
            }
        )
    return claims


def render_report(facts_path: str | Path, out_path: str | Path, title: str = "") -> Dict[str, Any]:
    facts = load_facts(facts_path)
    claims = build_claims(facts)
    data_date = str(facts.get("data_date") or "")
    heading = title or "{} 市场事实快报".format(data_date)
    sources = facts.get("sources") or []
    source_names = (
        "、".join(str(item.get("name")) for item in sources if item.get("name")) or "见 facts.json"
    )

    lines = [
        "# {}".format(heading),
        "",
        "> 数据日期：{} ｜ 窗口：{} 个交易日 ｜ 生成时间：{}".format(
            data_date, facts.get("window"), facts.get("generated_at")
        ),
        "> 数据来源：{}".format(source_names),
        "",
        "## 一、核心事实",
        "",
        "| 指数 | 收盘 | 1日 | 5日 | 20日 | 250日分位 | 20日年化波动 | 250日最大回撤 | 60日均线偏离 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in facts["rows"]:
        lines.append(
            "| {name} | {close} | {d1} | {d5} | {d20} | {pctile} | {vol} | {mdd} | {ma60} |".format(
                name=row.get("name"),
                close=_num(row.get("close") or 0),
                d1=_format_fact("d1", row.get("d1") or 0),
                d5=_format_fact("d5", row.get("d5") or 0),
                d20=_format_fact("d20", row.get("d20") or 0),
                pctile=_format_fact("pctile", row.get("pctile") or 0),
                vol=_format_fact("vol", row.get("vol") or 0),
                mdd=_format_fact("mdd", row.get("mdd") or 0),
                ma60=_format_fact("ma60", row.get("ma60") or 0),
            )
        )
    lines += [
        "",
        "## 二、口径与边界",
        "",
        "- 方法：M01 区间涨跌 / M02 250日分位 / M03 20日年化波动 / M04 250日最大回撤 / M05 60日均线偏离。",
        "- 样本量随指标不同（见 claim_map.json 的 sample_size），分位与回撤按各自窗口计算。",
        "- 缺失数据保留 `missing` 清单，不插值、不猜测。",
        "- {}".format(DISCLAIMER),
        "",
    ]
    report = "\n".join(lines)
    validate_report(report, claims)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    claim_path = out.with_name("claim_map.json")
    claim_path.write_text(
        json.dumps(
            {
                "schema": "report.claim_map.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data_date": data_date,
                "claims": claims,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"report": str(out), "claim_map": str(claim_path), "claims": len(claims)}


def validate_report(report: str, claims: List[Dict[str, Any]]) -> None:
    allowed = {
        fact["formatted"]
        for claim in claims
        for fact in claim.get("facts") or []
        if fact.get("formatted")
    }
    found = set(PCT_RE.findall(report))
    unmapped = sorted(token for token in found if token not in allowed)
    if unmapped:
        raise ContentError("E_CLAIM：报告含未映射数字 {}".format(", ".join(unmapped[:5])))


def blog_draft(
    report_path: str | Path,
    out_path: str | Path,
    slug: str = "",
    publish: bool = False,
) -> Dict[str, Any]:
    text = Path(report_path).read_text(encoding="utf-8")
    match = re.search(r"^#\s+(.+)$", text, re.M)
    if not match:
        raise ContentError("E_BLOG：报告缺少一级标题")
    title = match.group(1).strip()
    data_date = ""
    date_match = re.search(r"数据日期：(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        data_date = date_match.group(1)
    day = data_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slug or "market-facts-{}".format(day)
    summary = "基于 {} 的指数市场事实：覆盖区间涨跌、250日分位、20日年化波动与最大回撤，所有数字可回指 claim_map。".format(
        day
    )
    body = "\n".join(line for line in text.splitlines() if not line.startswith("# ")).strip()
    draft = (
        "---\ntitle: {}\ndate: {}\nsummary: {}\ntags: 市场研究,数据快报,指数\n---\n\n{}\n".format(
            title, day, summary, body
        )
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(draft, encoding="utf-8")
    result = {"draft": str(out), "slug": slug, "published": False}
    if publish:
        BLOG_DIR.mkdir(parents=True, exist_ok=True)
        target = BLOG_DIR / "{}.md".format(slug)
        target.write_text(draft, encoding="utf-8")
        check = subprocess.run(
            [sys.executable, str(MODULE_ROOT / "platform/site/scripts/build_site.py"), "--check"],
            cwd=str(MODULE_ROOT),
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            target.unlink(missing_ok=True)
            raise ContentError("E_BLOG：build_site --check 失败\n{}".format(check.stdout[-500:]))
        result.update(published=True, post=str(target))
    return result


def social_pack(
    report_path: str | Path,
    out_path: str | Path,
    facts_path: str = "",
    platform: str = "both",
) -> Dict[str, Any]:
    text = Path(report_path).read_text(encoding="utf-8")
    match = re.search(r"^#\s+(.+)$", text, re.M)
    title = match.group(1).strip() if match else "市场事实快报"
    facts = load_facts(facts_path) if facts_path else {}
    rows = facts.get("rows") or []
    highlights = [
        "{} 收 {}，20日 {}".format(
            row.get("name"), _num(row.get("close") or 0), _pct(row.get("d20") or 0)
        )
        for row in rows[:3]
    ] or ["数据见报告表格"]
    topic_base = ["市场研究", "指数观察", "数据复盘", "波动率", "最大回撤"]
    xhs = {
        "titles": [
            "{}：3 个数字看懂当前位置".format(title),
            "别只看涨跌，这 5 个指标更说明问题",
            "{}｜一张表看完分位与回撤".format(title),
        ],
        "body": "\n".join(
            ["今天不猜方向，只看数据。", *["- " + item for item in highlights], "", DISCLAIMER]
        ),
        "topics": topic_base,
        "cover_prompts": [
            "深色金融数据看板，三行关键指标，橙色强调",
            "极简白底表格，红绿涨跌，标题留白",
            "手机竖版信息图，K线剪影 + 大字号数字",
        ],
        "image_script": [
            "封面：标题 + 三个指标",
            "第二张：区间涨跌表",
            "第三张：250日分位",
            "第四张：20日年化波动",
            "第五张：250日最大回撤",
            "末图：口径说明与免责声明",
        ],
    }
    douyin = {
        "hook": "三个数字，看清现在的位置。",
        "beats": [
            "第一，{}".format(highlights[0]),
            "第二，看分位，不看情绪。",
            "第三，回撤决定你敢拿多久。",
            "最后，数据只描述事实，不预测方向。",
        ],
        "caption": "{}｜{}".format(title, DISCLAIMER),
        "topics": topic_base[:3],
    }
    payload = {
        "schema": "content.social_pack.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report": str(report_path),
        "platforms": {},
        "compliance": {"forbidden_hits": [], "disclaimer": DISCLAIMER, "passed": True},
    }
    if platform in {"both", "xiaohongshu"}:
        payload["platforms"]["xiaohongshu"] = xhs
    if platform in {"both", "douyin"}:
        payload["platforms"]["douyin"] = douyin

    joined = json.dumps(payload, ensure_ascii=False) + "\n" + text
    hits = [word for word in FORBIDDEN if word in joined]
    if hits:
        payload["compliance"].update(passed=False, forbidden_hits=hits)
        raise ContentError("E_COMPLIANCE：物料含违规词 {}".format(", ".join(hits)))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"pack": str(out), "platforms": sorted(payload["platforms"])}


def metrics_record(values: Dict[str, Any], path: str = "") -> Dict[str, Any]:
    target = Path(path) if path else METRICS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {key: str(values.get(key, "") or "") for key in METRIC_FIELDS}
    if not row["content_id"] or not row["platform"]:
        raise ContentError("E_METRICS：content_id/platform 必填")
    new_file = not target.exists()
    with target.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRIC_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return {"recorded": row, "path": str(target)}


def metrics_summary(path: str = "") -> Dict[str, Any]:
    target = Path(path) if path else METRICS_PATH
    if not target.exists():
        return {"rows": 0, "platforms": {}}
    with target.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    summary: Dict[str, Dict[str, float]] = {}
    for row in rows:
        platform = row.get("platform") or "unknown"
        bucket = summary.setdefault(
            platform,
            {"rows": 0, "impressions": 0, "likes": 0, "saves": 0, "comments": 0, "clicks": 0},
        )
        bucket["rows"] += 1
        for key in ("impressions", "likes", "saves", "comments", "clicks"):
            try:
                bucket[key] += float(row.get(key) or 0)
            except ValueError:
                continue
    return {"rows": len(rows), "platforms": summary}


def run_builtin(name: str, params: Dict[str, Any], out_path: str) -> Dict[str, Any]:
    """workflow 内置步骤入口；未实现的内置步骤返回 pending。"""
    if name == "research.render":
        if not params.get("facts"):
            raise ContentError("E_PARAM：research.render 需要 facts")
        return render_report(params["facts"], out_path, str(params.get("title") or ""))
    if name == "site.blog_draft":
        if not params.get("report"):
            raise ContentError("E_PARAM：site.blog_draft 需要 report")
        return blog_draft(
            params["report"],
            out_path,
            slug=str(params.get("slug") or ""),
            publish=bool(params.get("publish")),
        )
    if name == "content.social_pack":
        if not params.get("report"):
            raise ContentError("E_PARAM：content.social_pack 需要 report")
        return social_pack(
            params["report"],
            out_path,
            facts_path=str(params.get("facts") or ""),
            platform=str(params.get("platform") or "both"),
        )
    if name == "ops.metrics_record":
        if not params.get("content_id"):
            return {"pending": "等待 T+1 人工补录"}
        return metrics_record(params)
    return {"pending_builtin": name}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P1 内容闭环内置步骤")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_render = sub.add_parser("render")
    p_render.add_argument("--facts", required=True)
    p_render.add_argument("--out", required=True)
    p_render.add_argument("--title", default="")
    p_blog = sub.add_parser("blog")
    p_blog.add_argument("--report", required=True)
    p_blog.add_argument("--out", required=True)
    p_blog.add_argument("--slug", default="")
    p_blog.add_argument("--publish", action="store_true")
    p_social = sub.add_parser("social")
    p_social.add_argument("--report", required=True)
    p_social.add_argument("--out", required=True)
    p_social.add_argument("--facts", default="")
    p_social.add_argument("--platform", default="both", choices=["both", "xiaohongshu", "douyin"])
    p_metrics = sub.add_parser("metrics")
    p_metrics.add_argument("action", choices=["record", "summary"])
    p_metrics.add_argument("--path", default="")
    for field in METRIC_FIELDS:
        p_metrics.add_argument("--" + field, default="")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "render":
            print(json.dumps(render_report(args.facts, args.out, args.title), ensure_ascii=False))
        elif args.cmd == "blog":
            print(
                json.dumps(
                    blog_draft(args.report, args.out, args.slug, args.publish),
                    ensure_ascii=False,
                )
            )
        elif args.cmd == "social":
            print(
                json.dumps(
                    social_pack(args.report, args.out, args.facts, args.platform),
                    ensure_ascii=False,
                )
            )
        elif args.action == "record":
            values = {key: getattr(args, key) for key in METRIC_FIELDS}
            print(json.dumps(metrics_record(values, args.path), ensure_ascii=False))
        else:
            print(json.dumps(metrics_summary(args.path), ensure_ascii=False, indent=2))
    except ContentError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

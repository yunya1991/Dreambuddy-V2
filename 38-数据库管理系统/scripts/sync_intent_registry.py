#!/usr/bin/env python3
"""sync_intent_registry.py — 意图注册表同步通道（spec v0.5 §5⑤ P1）

职责：
1. 从权威源 intent-descriptions.ts 解析意图清单（id/name/keywords/examples）
2. UPSERT 到 38 侧 data_center.intent_registry（只读投影）
3. 一致性校验：registry 与权威源导出 diff 为空才通过
4. 生成 41 侧意图元数据文档 INTENT-REGISTRY.md 并触发索引提示

用法：
  DATA_CENTER_PG_PASSWORD=... venv-trading/bin/python sync_intent_registry.py
  密码发现与 dc_pg.py 一致（环境变量优先，回退 18 中心 .env）

FAIL-OPEN：同步失败不阻断主链路，输出告警并以非零码退出供告警系统消费。
"""
from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime, timezone

TS_PATH = "/home/luke/dreambuddy/3.1-FRONTEND/src/lib/intent/intent-descriptions.ts"
DOC_PATH = "/home/luke/dreambuddy/2-KNOWLEDGE/6-PRODUCT-BUSINESS/INTENT-REGISTRY.md"
_18_ENV = "/home/luke/dreambuddy/7-产物中台/系统研究索引体系/.env"

# 规则层独有意图（不在描述库，来自 fallback-engine.ts 类型联合）
EXTRA_INTENTS = {
    "developer": {"name": "开发者请求", "keywords": ["写", "函数", "脚本", "代码", "调试"], "examples": ["帮我写个函数计算移动平均线"], "layer": "L0"},
    "clarification_result": {"name": "澄清结果", "keywords": [], "examples": [], "layer": "L0"},
}


def discover_password() -> str:
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "")
    if pwd:
        return pwd
    try:
        with open(_18_ENV, "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return ""


def parse_authority() -> list[dict]:
    """解析权威源 intent-descriptions.ts，返回意图清单。"""
    with open(TS_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    intents = []
    # 逐意图块解析：id → name → keywords → examples
    for block in re.finditer(r"\{\s*id:\s*'([a-z_]+)',\s*name:\s*'([^']+)',.*?keywords:\s*\[([^\]]*)\].*?examples:\s*\[([^\]]*)\]", src, re.S):
        iid, name, kw_raw, ex_raw = block.groups()
        keywords = re.findall(r"'([^']+)'", kw_raw)
        examples = re.findall(r"'([^']+)'", ex_raw)
        intents.append({"id": iid, "name": name, "keywords": keywords, "examples": examples, "layer": "L0"})
    for iid, meta in EXTRA_INTENTS.items():
        intents.append({"id": iid, **meta})
    return intents


def upsert_registry(intents: list[dict]) -> None:
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
        user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
        password=discover_password(),
        dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            for it in intents:
                cur.execute(
                    """INSERT INTO intent_registry (intent_id, name, layer, keywords, examples, rule_id, status, version, updated_at)
                       VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, 'active', 'v1', now())
                       ON CONFLICT (intent_id) DO UPDATE SET
                         name = EXCLUDED.name, layer = EXCLUDED.layer,
                         keywords = EXCLUDED.keywords, examples = EXCLUDED.examples,
                         rule_id = EXCLUDED.rule_id, updated_at = now()""",
                    (it["id"], it["name"], it["layer"],
                     json.dumps(it["keywords"], ensure_ascii=False),
                     json.dumps(it["examples"], ensure_ascii=False),
                     "hc_" + it["id"]),
                )
        conn.commit()
    finally:
        conn.close()


def verify_consistency(intents: list[dict]) -> list[str]:
    """一致性校验：registry 与权威源导出 diff，返回差异列表（空 = 通过）。"""
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
        user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
        password=discover_password(),
        dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
        connect_timeout=10,
    )
    diffs = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT intent_id, name, keywords, examples FROM intent_registry WHERE status = 'active'")
            rows = {r[0]: r for r in cur.fetchall()}
        auth = {it["id"]: it for it in intents}
        for iid in set(rows) | set(auth):
            if iid not in rows:
                diffs.append(f"registry 缺失意图: {iid}")
            elif iid not in auth:
                diffs.append(f"registry 多出意图: {iid}")
            else:
                _, name, kw, ex = rows[iid]
                if name != auth[iid]["name"]:
                    diffs.append(f"{iid} name 不一致: registry={name} vs 权威源={auth[iid]['name']}")
                if list(kw) != auth[iid]["keywords"]:
                    diffs.append(f"{iid} keywords 不一致")
                if list(ex) != auth[iid]["examples"]:
                    diffs.append(f"{iid} examples 不一致")
    finally:
        conn.close()
    return diffs


def gen_doc(intents: list[dict]) -> None:
    """生成 41 侧意图元数据文档（固定路径，落入 41 索引范围）。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# 意图注册表（INTENT REGISTRY）",
        "",
        f"> 自动生成：sync_intent_registry.py（{now}）",
        "> 权威源：3.1-FRONTEND/src/lib/intent/intent-descriptions.ts（唯一权威源，本文件为只读投影）",
        "> 同步通道：spec v0.5 §5⑤（38 侧 intent_registry 表 + 41 侧本文档）",
        "",
        f"共 {len(intents)} 种意图。",
        "",
        "| 意图 ID | 名称 | 分层 | 规则 | 关键词 |",
        "|---|---|---|---|---|",
    ]
    for it in intents:
        kw = "、".join(it["keywords"][:6]) if it["keywords"] else "-"
        lines.append(f"| {it['id']} | {it['name']} | {it['layer']} | hc_{it['id']} | {kw} |")
    lines += ["", "## 示例", ""]
    for it in intents:
        if it["examples"]:
            lines.append(f"- **{it['id']}**（{it['name']}）：{'；'.join(it['examples'][:3])}")
    content = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(DOC_PATH), exist_ok=True)
    with open(DOC_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def main() -> int:
    try:
        intents = parse_authority()
        if len(intents) < 10:
            print(json.dumps({"success": False, "error": f"权威源解析异常：仅 {len(intents)} 种意图"}))
            return 1
        upsert_registry(intents)
        diffs = verify_consistency(intents)
        gen_doc(intents)
        result = {
            "success": len(diffs) == 0,
            "synced": len(intents),
            "doc_path": DOC_PATH,
            "diffs": diffs,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not diffs else 2
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

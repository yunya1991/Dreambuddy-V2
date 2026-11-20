#!/usr/bin/env python3
"""59 站点构建器：模板渲染产物 + 组件登记清单

源 / 产物分离：
  templates/{index,trial,guide}.html   唯一可手改的页面源
  index.html / trial.html / guide.html 产物，头部带 AUTO-GENERATED 注释，禁止手改
  components/*/component.yaml         → data/registry.json（只读后台清单）

产物与模板的差异只有 `<!DOCTYPE html>` 之后的一行 AUTO-GENERATED 注释。

用法：
    python3 scripts/build_site.py --write   # 渲染产物 + 生成 data/registry.json
    python3 scripts/build_site.py --check   # 逐字节校验（CI / make check）

设计约束：
- 仅用 Python 标准库
- registry.json 字段结构沿用原 build_registry.py（components 按 name 排序）
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent
MODULE_DIR = SITE_DIR.parent.parent
TEMPLATES_DIR = SITE_DIR / "templates"
COMPONENTS_DIR = MODULE_DIR / "components"
REGISTRY_PATH = SITE_DIR / "data" / "registry.json"
RULES_PATH = SITE_DIR / "data" / "rules.json"

PAGES = ("index", "trial", "guide")
GENERATED_MARK = "AUTO-GENERATED"
RULE_COUNT_TOKEN = "{{PUBLIC_RULE_COUNT}}"
RULE_TABLE_BEGIN, RULE_TABLE_END = "<!-- GEN:RULES:BEGIN -->", "<!-- GEN:RULES:END -->"
TRIAL_LIST_BEGIN, TRIAL_LIST_END = "<!-- GEN:TRIAL-RULES:BEGIN -->", "<!-- GEN:TRIAL-RULES:END -->"
TRIAL_PREVIEW = 5
HARDCODED_COUNT_RE = re.compile(r"九项|9\s*项|七项|7\s*项")

FLAT_KEYS = (
    "name",
    "display_name",
    "version",
    "family",
    "lifecycle",
    "summary",
    "output_contract",
)
LIST_KEYS = ("entrypoints", "docs", "kernel_deps")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_component_yaml(text: str) -> dict:
    """解析 component.yaml 中站点需要的字段（扁平键 + 行内/块状列表）。"""
    data: dict = {key: [] for key in LIST_KEYS}
    current_list = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        stripped = raw_line.strip()

        # 块状列表项： "  - value"
        if stripped.startswith("- "):
            if current_list:
                data[current_list].append(_unquote(stripped[2:]))
            continue

        if ":" not in stripped:
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_list = None

        if key in LIST_KEYS:
            if value.startswith("[") and value.endswith("]"):
                items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
                data[key] = [_unquote(item) for item in items]
            else:
                current_list = key
                data[key] = []
            continue

        if key in FLAT_KEYS:
            data[key] = _unquote(value)

    return data


def collect_components() -> list:
    components = []
    for yaml_path in sorted(COMPONENTS_DIR.glob("*/component.yaml")):
        parsed = parse_component_yaml(yaml_path.read_text(encoding="utf-8"))
        if not parsed.get("name"):
            print(f"[warn] 跳过缺少 name 的组件: {yaml_path}", file=sys.stderr)
            continue
        components.append(
            {
                "name": parsed.get("name", ""),
                "display_name": parsed.get("display_name") or parsed.get("name", ""),
                "version": parsed.get("version", ""),
                "family": parsed.get("family", ""),
                "lifecycle": parsed.get("lifecycle", ""),
                "summary": parsed.get("summary", ""),
                "entrypoints": parsed.get("entrypoints", []),
                "docs": parsed.get("docs", []),
                "source": f"components/{yaml_path.parent.name}/component.yaml",
            }
        )
    return sorted(components, key=lambda item: item["name"])


def build_registry() -> dict:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "59-通用组件管理/components/*/component.yaml",
        "components": collect_components(),
    }


def _header(name: str) -> str:
    return (
        f"<!-- {GENERATED_MARK} from templates/{name}.html"
        " — 禁止手改；改模板后跑 build_site.py --write -->"
    )


def load_rules() -> dict:
    if not RULES_PATH.exists():
        raise FileNotFoundError(
            "缺少 data/rules.json，请先执行 python3 tools/sync_rules.py --write"
        )
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _replace_block(text: str, begin: str, end: str, block: str) -> str:
    start = text.find(begin)
    stop = text.find(end)
    if start < 0 or stop < start:
        raise ValueError(f"模板缺少生成块标记 {begin} / {end}")
    return text[: start + len(begin)] + "\n" + block + "\n" + text[stop:]


def _rule_rows(rules: dict) -> str:
    rows = []
    for rule in rules["public_rules"]:
        rows.append(
            "        <tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(rule["category"]),
                html.escape(rule["item"]),
                html.escape(rule["consequence"]),
            )
        )
    return "\n".join(rows)


def _trial_items(rules: dict) -> str:
    count = rules["public_rule_count"]
    items = [rule["item"] for rule in rules["public_rules"][:TRIAL_PREVIEW]]
    items.append(f"共 {count} 项检查")
    return "<br>\n".join(f"            · {html.escape(item)}" for item in items)


def validate_page(name: str, text: str, rules: dict) -> None:
    """V6：承诺对齐——不得硬编码检查项数，表格行数必须等于公开规则数。"""
    if HARDCODED_COUNT_RE.search(text):
        raise ValueError(f"{name}.html 出现硬编码检查项数字（九项/9 项/七项），请改用生成块")
    count = rules["public_rule_count"]
    if name == "guide":
        rows = text.count("<tr><td>")
        if rows != count:
            raise ValueError(f"guide.html 检查项 {rows} 行，与公开规则数 {count} 不一致")
    if name == "trial" and f"共 {count} 项检查" not in text:
        raise ValueError(f"trial.html 未渲染「共 {count} 项检查」")
    if name == "index" and RULE_COUNT_TOKEN in text:
        raise ValueError("index.html 仍残留未替换的 {{PUBLIC_RULE_COUNT}}")


def render_page(name: str, template: str, rules: dict) -> str:
    """在 doctype 之后插入固定生成头，并渲染规则相关生成块。"""
    first, sep, rest = template.partition("\n")
    if not sep or first.strip().lower() != "<!doctype html>":
        raise ValueError(f"templates/{name}.html 首行必须是 <!DOCTYPE html>")

    body = rest.replace(RULE_COUNT_TOKEN, str(rules["public_rule_count"]))
    if name == "guide":
        body = _replace_block(body, RULE_TABLE_BEGIN, RULE_TABLE_END, _rule_rows(rules))
    if name == "trial":
        body = _replace_block(body, TRIAL_LIST_BEGIN, TRIAL_LIST_END, _trial_items(rules))

    rendered = f"{first}\n{_header(name)}\n{body}"
    validate_page(name, rendered, rules)
    return rendered


def _render_all(rules: dict) -> dict:
    rendered = {}
    for name in PAGES:
        template_path = TEMPLATES_DIR / f"{name}.html"
        if not template_path.exists():
            raise FileNotFoundError(f"缺少模板 {template_path}")
        rendered[name] = render_page(name, template_path.read_text(encoding="utf-8"), rules)
    return rendered


def write() -> int:
    rules = load_rules()
    rendered = _render_all(rules)
    registry = build_registry()
    for name, content in rendered.items():
        (SITE_DIR / f"{name}.html").write_text(content, encoding="utf-8")
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"已渲染 {len(rendered)} 页（{', '.join(PAGES)}），"
        f"并写入 {REGISTRY_PATH}（{len(registry['components'])} 个组件）"
    )
    return 0


def check() -> int:
    errors = []

    try:
        rules = load_rules()
        rendered = _render_all(rules)
    except (OSError, ValueError) as exc:
        print(f"[check] {exc}", file=sys.stderr)
        return 1

    for name, expected in rendered.items():
        output_path = SITE_DIR / f"{name}.html"
        if not output_path.exists():
            errors.append(f"缺少产物 {output_path}，请执行 --write")
            continue
        actual = output_path.read_text(encoding="utf-8")
        if actual == expected:
            continue
        if GENERATED_MARK not in actual:
            errors.append(
                f"{output_path.name} 缺少 {GENERATED_MARK} 头（疑似手改产物），"
                "请改 templates/ 后执行 --write"
            )
        else:
            errors.append(
                f"{output_path.name} 与模板渲染结果不一致（疑似手改产物），"
                "请改 templates/ 后执行 --write"
            )

    if REGISTRY_PATH.exists():
        current = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if current.get("components") != collect_components():
            errors.append("data/registry.json 与 component.yaml 不一致，请执行 --write")
    else:
        errors.append(f"缺少产物 {REGISTRY_PATH}，请执行 --write")

    if errors:
        for message in errors:
            print(f"[check] {message}", file=sys.stderr)
        return 1

    print(f"[check] 通过（{len(rendered)} 页产物 + registry.json 均与源一致）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="59 站点构建器（模板 → 产物）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="渲染产物 + 生成 registry.json")
    group.add_argument("--check", action="store_true", help="逐字节校验产物与源一致")
    args = parser.parse_args()

    try:
        return write() if args.write else check()
    except (OSError, ValueError) as exc:
        print(f"[build_site] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

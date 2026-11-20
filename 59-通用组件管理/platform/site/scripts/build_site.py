#!/usr/bin/env python3
"""59 站点构建器：模板渲染产物 + 商品详情页 + 组件登记清单

源 / 产物分离（SPEC §5.3）：
  templates/{index,trial,guide,product}.html  唯一可手改的页面源
  index.html / trial.html / guide.html        产物，头部带 AUTO-GENERATED 注释
  p/<family>.html                             商品详情页产物
  catalog.yaml                                展示文案与入口链接（禁止 version/price）
  products/*.yaml + components/*/component.yaml
        → data/public.json（公开）与 data/registry.json（后台，受保护）

用法：
    python3 scripts/build_site.py --write   # 渲染产物 + 生成 data/public.json 与 data/registry.json
    python3 scripts/build_site.py --check   # 逐字节校验（CI / make check）

设计约束：
- 仅用 Python 标准库（catalog/products 的 YAML 子集由本文件自带解析器读取）
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
PRODUCTS_DIR = MODULE_DIR / "products"
PRODUCT_OUT_DIR = SITE_DIR / "p"
REGISTRY_PATH = SITE_DIR / "data" / "registry.json"
PUBLIC_JSON_PATH = SITE_DIR / "data" / "public.json"
RULES_PATH = SITE_DIR / "data" / "rules.json"
CATALOG_PATH = SITE_DIR / "catalog.yaml"

PAGES = ("index", "trial", "guide")
PRODUCT_TEMPLATE = "product"
GENERATED_MARK = "AUTO-GENERATED"
RULE_COUNT_TOKEN = "{{PUBLIC_RULE_COUNT}}"
RULE_TABLE_BEGIN, RULE_TABLE_END = "<!-- GEN:RULES:BEGIN -->", "<!-- GEN:RULES:END -->"
TRIAL_LIST_BEGIN, TRIAL_LIST_END = "<!-- GEN:TRIAL-RULES:BEGIN -->", "<!-- GEN:TRIAL-RULES:END -->"
PRODUCTS_BEGIN, PRODUCTS_END = "<!-- GEN:PRODUCTS:BEGIN -->", "<!-- GEN:PRODUCTS:END -->"
CAPABILITIES_BEGIN, CAPABILITIES_END = (
    "<!-- GEN:CAPABILITIES:BEGIN -->",
    "<!-- GEN:CAPABILITIES:END -->",
)
SELECTOR_BEGIN, SELECTOR_END = "<!-- GEN:SELECTOR:BEGIN -->", "<!-- GEN:SELECTOR:END -->"
VARIANTS_BEGIN, VARIANTS_END = "<!-- GEN:VARIANTS:BEGIN -->", "<!-- GEN:VARIANTS:END -->"
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

FAMILY_KEYS = {"title", "tagline", "audience", "capabilities", "sample", "selector", "variants"}
VARIANT_KEYS = {"copy", "install", "link"}
SELECTOR_KEYS = {"question", "options"}
OPTION_KEYS = {"text", "variant"}
LIFECYCLES = {"active", "draft", "deprecated"}

CHANNEL_LABELS = {
    "workbuddy-local": "本地安装",
    "skillpay-subscription": "SkillPay 订阅",
    "skillpay-once": "SkillPay 买断",
    "skillhub-pay": "SkillHub 按次",
}


class SiteError(Exception):
    pass


# ── YAML 子集解析（映射 / 列表 / 标量，不支持锚点与多行字符串）───────────────


def _scalar(text: str):
    value = text.strip()
    if not value:
        return ""
    if value[0] in ("'", '"') and value[-1] == value[0] and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(item) for item in inner.split(",")] if inner else []
    if value in ("true", "false"):
        return value == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(?:\s+(.*))?$")


def _split_key(content: str):
    match = _KEY_RE.match(content)
    if not match:
        raise SiteError(f"无法解析的 YAML 行: {content}")
    return match.group(1), (match.group(2) or "").strip()


def parse_yaml(text: str):
    """解析本目录使用的 YAML 子集：2 空格缩进、映射、列表、内联标量列表。"""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise SiteError(f"缩进必须为 2 的倍数: {raw}")
        lines.append((indent, stripped))
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise SiteError(f"YAML 尾部存在无法归属的行: {lines[index][1]}")
    return value


def _parse_block(lines, index, indent):
    if index >= len(lines) or lines[index][0] < indent:
        return None, index
    if lines[index][1].startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_list(lines, index, indent):
    out = []
    while index < len(lines):
        level, content = lines[index]
        if level != indent or not content.startswith("- "):
            break
        item = content[2:].strip()
        index += 1
        if not item:
            child, index = _parse_block(lines, index, indent + 2)
            out.append(child if child is not None else {})
            continue
        if _KEY_RE.match(item):
            node = {}
            key, value = _split_key(item)
            if value:
                node[key] = _scalar(value)
            else:
                child, index = _parse_block(lines, index, indent + 2)
                node[key] = child if child is not None else {}
            while (
                index < len(lines)
                and lines[index][0] == indent + 2
                and not lines[index][1].startswith("- ")
            ):
                key, value = _split_key(lines[index][1])
                index += 1
                if value:
                    node[key] = _scalar(value)
                else:
                    child, index = _parse_block(lines, index, indent + 4)
                    node[key] = child if child is not None else {}
            out.append(node)
        else:
            out.append(_scalar(item))
    return out, index


def _parse_map(lines, index, indent):
    out = {}
    while index < len(lines):
        level, content = lines[index]
        if level != indent or content.startswith("- "):
            break
        key, value = _split_key(content)
        index += 1
        if value:
            out[key] = _scalar(value)
        else:
            child_indent = (
                lines[index][0] if index < len(lines) and lines[index][0] > indent else indent + 2
            )
            child, index = _parse_block(lines, index, child_indent)
            out[key] = child if child is not None else {}
    return out, index


# ── 组件登记（原有字段与排序保持不变）──────────────────────────────────────


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


def build_registry(components: list) -> dict:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "59-通用组件管理/components/*/component.yaml",
        "components": components,
    }


# ── 商品目录与分发表 ──────────────────────────────────────────────────────


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        raise SiteError("缺少 catalog.yaml")
    data = parse_yaml(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"families"}:
        raise SiteError("catalog.yaml 顶层只允许 families")
    families = data["families"]
    if not isinstance(families, dict) or not families:
        raise SiteError("catalog.yaml 的 families 必须是非空映射")
    return families


def load_products() -> dict:
    products = {}
    for path in sorted(PRODUCTS_DIR.glob("*.yaml")):
        data = parse_yaml(path.read_text(encoding="utf-8"))
        family = data.get("product")
        if not family:
            raise SiteError(f"{path.name} 缺少 product")
        if family in products:
            raise SiteError(f"product 重复: {family}")
        variants = data.get("variants")
        if not isinstance(variants, dict) or not variants:
            raise SiteError(f"{path.name} 缺少 variants")
        products[family] = {
            "file": path.name,
            "component": str(data.get("component") or ""),
            "variants": variants,
        }
    if not products:
        raise SiteError("products/ 下没有分发表")
    return products


def validate_catalog(catalog: dict, products: dict, components: list) -> None:
    by_name = {item["name"]: item for item in components}
    missing = sorted(set(products) - set(catalog))
    extra = sorted(set(catalog) - set(products))
    if missing or extra:
        raise SiteError(
            f"catalog 与 products 族集合不一致：缺少 {missing or '无'}，多余 {extra or '无'}"
        )

    for family, entry in catalog.items():
        if not isinstance(entry, dict):
            raise SiteError(f"catalog.{family} 必须是映射")
        unknown = sorted(set(entry) - FAMILY_KEYS)
        if unknown:
            raise SiteError(
                f"catalog.{family} 含未知键 {unknown}（version/price 由 products 提供）"
            )
        for key in ("title", "tagline", "audience"):
            if not entry.get(key):
                raise SiteError(f"catalog.{family} 缺少 {key}")

        product = products[family]
        component_name = Path(product["component"]).name
        component = by_name.get(component_name)
        if not component:
            raise SiteError(f"{family} 指向的组件 {component_name} 未登记")
        if component["lifecycle"] not in LIFECYCLES:
            raise SiteError(f"{family} 组件 lifecycle 非法: {component['lifecycle']}")
        if component["lifecycle"] != "active":
            raise SiteError(f"{family} 组件状态为 {component['lifecycle']}，不应出现在对外目录")

        sample = entry.get("sample") or ""
        if not sample or not (SITE_DIR / sample).is_file():
            raise SiteError(f"catalog.{family}.sample 不存在: {sample or '空'}")

        variants = entry.get("variants")
        if not isinstance(variants, dict):
            raise SiteError(f"catalog.{family} 缺少 variants 展示文案")
        if set(variants) != set(product["variants"]):
            raise SiteError(
                f"catalog.{family} 变体与分发表不一致：{sorted(set(variants) ^ set(product['variants']))}"
            )

        for key, copy in variants.items():
            if not isinstance(copy, dict):
                raise SiteError(f"catalog.{family}.variants.{key} 必须是映射")
            unknown = sorted(set(copy) - VARIANT_KEYS)
            if unknown:
                raise SiteError(f"catalog.{family}.variants.{key} 含未知键 {unknown}")
            if not copy.get("copy"):
                raise SiteError(f"catalog.{family}.variants.{key} 缺少 copy")
            channel = str(product["variants"][key].get("channel") or "")
            link = str(copy.get("link") or "")
            if channel == "workbuddy-local":
                continue
            if not link.startswith("https://"):
                raise SiteError(
                    f"catalog.{family}.variants.{key} 渠道 {channel} 必须提供 https 链接"
                )
            if channel.startswith("skillhub-") and not re.match(r"^https://skillhub\.cn/", link):
                raise SiteError(
                    f"catalog.{family}.variants.{key} 的 skillhub 链接必须指向 skillhub.cn"
                )

        selector = entry.get("selector") or []
        if not isinstance(selector, list) or len(selector) != 3:
            raise SiteError(f"catalog.{family}.selector 必须是 3 个问题")
        for index, question in enumerate(selector, start=1):
            if not isinstance(question, dict) or set(question) - SELECTOR_KEYS:
                raise SiteError(f"catalog.{family}.selector 第 {index} 问含未知键")
            if not question.get("question") or not isinstance(question.get("options"), list):
                raise SiteError(f"catalog.{family}.selector 第 {index} 问缺少问题或选项")
            for option in question["options"]:
                if not isinstance(option, dict) or set(option) - OPTION_KEYS:
                    raise SiteError(f"catalog.{family}.selector 第 {index} 问选项含未知键")
                if option.get("variant") not in product["variants"]:
                    raise SiteError(
                        f"catalog.{family}.selector 第 {index} 问指向未知变体 {option.get('variant')}"
                    )


def build_public(catalog: dict, products: dict, components: list, rules: dict) -> dict:
    by_name = {item["name"]: item for item in components}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = []
    for family in sorted(catalog):
        entry = catalog[family]
        product = products[family]
        component = by_name[Path(product["component"]).name]
        variants = []
        for key in sorted(product["variants"]):
            variant = product["variants"][key]
            copy = entry["variants"][key]
            variants.append(
                {
                    "key": key,
                    "display_name": str(variant.get("display_name") or variant.get("name") or key),
                    "channel": str(variant.get("channel") or ""),
                    "price": str(variant.get("price") or ""),
                    "link": str(copy.get("link") or ""),
                    "copy": str(copy["copy"]),
                }
            )
        items.append(
            {
                "family": family,
                "name": component["name"],
                "display_name": component["display_name"],
                "version": component["version"],
                "lifecycle": component["lifecycle"],
                "summary": component["summary"],
                "tagline": entry["tagline"],
                "sample": entry["sample"],
                "variants": variants,
            }
        )
    return {
        "schema_version": "1.0",
        "generated_at": now,
        "build": {
            "rules_version": rules["rules_version"],
            "score_formula_version": rules["score_formula_version"],
            "generated_at": now,
        },
        "components": items,
    }


# ── 页面渲染 ──────────────────────────────────────────────────────────────


def _header(name: str) -> str:
    return (
        f"<!-- {GENERATED_MARK} from templates/{name}.html"
        " — 禁止手改；改模板后跑 build_site.py --write -->"
    )


def load_rules() -> dict:
    if not RULES_PATH.exists():
        raise SiteError("缺少 data/rules.json，请先执行 python3 tools/sync_rules.py --write")
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _replace_block(text: str, begin: str, end: str, block: str) -> str:
    start = text.find(begin)
    stop = text.find(end)
    if start < 0 or stop < start:
        raise SiteError(f"模板缺少生成块标记 {begin} / {end}")
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


def _product_cards(public: dict) -> str:
    cards = []
    for item in public["components"]:
        href = f"p/{item['family']}.html"
        cards.append(
            '        <div class="card">\n'
            f'          <span class="tag">{html.escape(item["family"])}</span>\n'
            f'          <h3><a href="{href}">{html.escape(item["display_name"])}</a></h3>\n'
            f'          <p>{html.escape(item["tagline"])}</p>\n'
            f'          <p class="hint"><a href="{href}">查看版本与价格 →</a></p>\n'
            "        </div>"
        )
    return "\n".join(cards)


def _capability_cards(entry: dict) -> str:
    cards = []
    for capability in entry.get("capabilities") or []:
        cards.append(f'        <div class="card"><p>{html.escape(str(capability))}</p></div>')
    return "\n".join(cards)


def _selector_block(family: str, entry: dict) -> str:
    blocks = []
    for index, question in enumerate(entry["selector"], start=1):
        options = []
        for option in question["options"]:
            options.append(
                '            <label class="opt"><input type="radio" name="{}-q{}" data-variant-pick="{}"> {}</label>'.format(
                    html.escape(family),
                    index,
                    html.escape(str(option["variant"])),
                    html.escape(str(option["text"])),
                )
            )
        blocks.append(
            '      <div class="panel" style="margin-bottom:16px">\n'
            f"        <h3>{index}. {html.escape(str(question['question']))}</h3>\n"
            '        <div class="row">\n' + "\n".join(options) + "\n"
            "        </div>\n"
            "      </div>"
        )
    return "\n".join(blocks)


def _variant_cards(public_item: dict, entry: dict) -> str:
    cards = []
    for variant in public_item["variants"]:
        key = variant["key"]
        channel = variant["channel"] or "未声明"
        price = variant["price"] or ("免费" if channel == "workbuddy-local" else "以商品页为准")
        install = str(entry["variants"][key].get("install") or "")
        link = variant["link"]
        lines = [
            f'        <div class="card variant" data-variant="{html.escape(key)}">',
            f'          <span class="tag">{html.escape(key)} · {html.escape(CHANNEL_LABELS.get(channel, channel))}</span>',
            f'          <h3>{html.escape(variant["display_name"])}</h3>',
            f'          <p>{html.escape(variant["copy"])}</p>',
            f'          <p class="hint">价格：{html.escape(price)}</p>',
        ]
        if install:
            lines.append(
                '          <pre style="overflow:auto;background:#0b1220;color:#e2e8f0;'
                f'padding:12px;border-radius:10px;font-size:13px">{html.escape(install)}</pre>'
            )
        if link:
            lines.append(
                f'          <a class="btn btn-outline" href="{html.escape(link)}" target="_blank" rel="noopener">前往商品页</a>'
            )
        else:
            lines.append('          <p class="hint">本地安装，无需跳转商品页。</p>')
        lines.append("        </div>")
        cards.append("\n".join(lines))
    return "\n".join(cards)


def render_page(name: str, template: str, rules: dict, products_html: str = "") -> str:
    """在 doctype 之后插入固定生成头，并渲染规则/商品生成块。"""
    first, sep, rest = template.partition("\n")
    if not sep or first.strip().lower() != "<!doctype html>":
        raise SiteError(f"templates/{name}.html 首行必须是 <!DOCTYPE html>")

    body = rest.replace(RULE_COUNT_TOKEN, str(rules["public_rule_count"]))
    if name == "guide":
        body = _replace_block(body, RULE_TABLE_BEGIN, RULE_TABLE_END, _rule_rows(rules))
    if name == "trial":
        body = _replace_block(body, TRIAL_LIST_BEGIN, TRIAL_LIST_END, _trial_items(rules))
    if name == "index":
        body = _replace_block(body, PRODUCTS_BEGIN, PRODUCTS_END, products_html)

    rendered = f"{first}\n{_header(name)}\n{body}"
    validate_page(name, rendered, rules)
    return rendered


def validate_page(name: str, text: str, rules: dict) -> None:
    """V6：承诺对齐——不得硬编码检查项数，表格行数必须等于公开规则数。"""
    if HARDCODED_COUNT_RE.search(text):
        raise SiteError(f"{name}.html 出现硬编码检查项数字（九项/9 项/七项），请改用生成块")
    count = rules["public_rule_count"]
    if name == "guide":
        rows = text.count("<tr><td>")
        if rows != count:
            raise SiteError(f"guide.html 检查项 {rows} 行，与公开规则数 {count} 不一致")
    if name == "trial" and f"共 {count} 项检查" not in text:
        raise SiteError(f"trial.html 未渲染「共 {count} 项检查」")
    if name == "index" and RULE_COUNT_TOKEN in text:
        raise SiteError("index.html 仍残留未替换的 {{PUBLIC_RULE_COUNT}}")


def render_product(family: str, entry: dict, public_item: dict) -> str:
    template = (TEMPLATES_DIR / f"{PRODUCT_TEMPLATE}.html").read_text(encoding="utf-8")
    first, sep, rest = template.partition("\n")
    if not sep or first.strip().lower() != "<!doctype html>":
        raise SiteError("templates/product.html 首行必须是 <!DOCTYPE html>")

    body = (
        rest.replace("{{TITLE}}", html.escape(public_item["display_name"]))
        .replace("{{TAGLINE}}", html.escape(entry["tagline"]))
        .replace("{{AUDIENCE}}", html.escape(entry["audience"]))
        .replace("{{FAMILY}}", html.escape(family))
        .replace("{{VERSION}}", html.escape(public_item["version"]))
        .replace("{{SAMPLE}}", html.escape(entry["sample"]))
    )
    body = _replace_block(body, CAPABILITIES_BEGIN, CAPABILITIES_END, _capability_cards(entry))
    body = _replace_block(body, SELECTOR_BEGIN, SELECTOR_END, _selector_block(family, entry))
    body = _replace_block(body, VARIANTS_BEGIN, VARIANTS_END, _variant_cards(public_item, entry))

    rendered = f"{first}\n{_header(PRODUCT_TEMPLATE)}\n{body}"
    if "{{" in rendered:
        raise SiteError(f"p/{family}.html 仍有未替换的占位符")
    for asset in re.findall(r'"\.\./assets/[^"]+"', rendered):
        target = SITE_DIR / asset.strip('"').replace("../", "")
        if not target.exists():
            raise SiteError(f"p/{family}.html 引用了不存在的资源 {asset}")
    return rendered


def render_all() -> dict:
    rules = load_rules()
    catalog = load_catalog()
    products = load_products()
    components = collect_components()
    validate_catalog(catalog, products, components)
    public = build_public(catalog, products, components, rules)

    pages = {}
    for name in PAGES:
        template_path = TEMPLATES_DIR / f"{name}.html"
        if not template_path.exists():
            raise SiteError(f"缺少模板 {template_path}")
        pages[name] = render_page(
            name,
            template_path.read_text(encoding="utf-8"),
            rules,
            products_html=_product_cards(public),
        )

    details = {}
    for item in public["components"]:
        family = item["family"]
        details[family] = render_product(family, catalog[family], item)

    return {
        "rules": rules,
        "pages": pages,
        "details": details,
        "public": public,
        "registry": build_registry(components),
    }


# ── 写盘与校验 ────────────────────────────────────────────────────────────


def _strip_volatile(payload: dict) -> dict:
    copy = json.loads(json.dumps(payload))
    copy.pop("generated_at", None)
    build = copy.get("build")
    if isinstance(build, dict):
        build.pop("generated_at", None)
    return copy


def write() -> int:
    bundle = render_all()
    for name, content in bundle["pages"].items():
        (SITE_DIR / f"{name}.html").write_text(content, encoding="utf-8")
    PRODUCT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    for family, content in bundle["details"].items():
        (PRODUCT_OUT_DIR / f"{family}.html").write_text(content, encoding="utf-8")

    PUBLIC_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JSON_PATH.write_text(
        json.dumps(bundle["public"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REGISTRY_PATH.write_text(
        json.dumps(bundle["registry"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"已渲染 {len(bundle['pages'])} 页 + {len(bundle['details'])} 个商品页，"
        f"并写入 data/public.json（{len(bundle['public']['components'])} 个组件）"
        f"与 data/registry.json（{len(bundle['registry']['components'])} 个组件）"
    )
    return 0


def _check_text(path: Path, expected: str, errors: list) -> None:
    if not path.exists():
        errors.append(f"缺少产物 {path}，请执行 --write")
        return
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return
    if GENERATED_MARK not in actual:
        errors.append(
            f"{path} 缺少 {GENERATED_MARK} 头（疑似手改产物），请改 templates/ 后执行 --write"
        )
    else:
        errors.append(
            f"{path} 与模板渲染结果不一致（疑似手改产物），请改 templates/ 后执行 --write"
        )


def check() -> int:
    errors = []
    try:
        bundle = render_all()
    except (OSError, SiteError) as exc:
        print(f"[check] {exc}", file=sys.stderr)
        return 1

    for name, expected in bundle["pages"].items():
        _check_text(SITE_DIR / f"{name}.html", expected, errors)
    for family, expected in bundle["details"].items():
        _check_text(PRODUCT_OUT_DIR / f"{family}.html", expected, errors)

    expected_files = {f"{family}.html" for family in bundle["details"]}
    if PRODUCT_OUT_DIR.exists():
        for path in sorted(PRODUCT_OUT_DIR.glob("*.html")):
            if path.name not in expected_files:
                errors.append(f"{path} 不属于任何商品族（陈旧产物），请删除或补 catalog")

    if PUBLIC_JSON_PATH.exists():
        current = json.loads(PUBLIC_JSON_PATH.read_text(encoding="utf-8"))
        if _strip_volatile(current) != _strip_volatile(bundle["public"]):
            errors.append("data/public.json 与 catalog/products 不一致，请执行 --write")
    else:
        errors.append("缺少产物 data/public.json，请执行 --write")

    if REGISTRY_PATH.exists():
        current = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if current.get("components") != bundle["registry"]["components"]:
            errors.append("data/registry.json 与 component.yaml 不一致，请执行 --write")
    else:
        errors.append("缺少产物 data/registry.json，请执行 --write")

    if errors:
        for message in errors:
            print(f"[check] {message}", file=sys.stderr)
        return 1

    print(
        f"[check] 通过（{len(bundle['pages'])} 页产物 + {len(bundle['details'])} 个商品页"
        f" + public.json/registry.json 均与源一致）"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="59 站点构建器（模板 → 产物）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--write", action="store_true", help="渲染产物并生成 public.json / registry.json"
    )
    group.add_argument("--check", action="store_true", help="逐字节校验产物与源一致")
    args = parser.parse_args()

    try:
        return write() if args.write else check()
    except (OSError, SiteError) as exc:
        print(f"[build_site] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

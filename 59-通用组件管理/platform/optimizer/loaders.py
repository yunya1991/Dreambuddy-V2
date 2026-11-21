"""把发布链路上的四类对象统一加载为可评分的 Surface。

来源与单一源：
    MCP 工具     components/<name>/component.yaml 的 actions[].mcp
    SKILL.md     dist/<name>/<variant>/SKILL.md（发布态；缺失时回落 components/<name>/skill/）
    商品页       products/<product>.yaml variants.<v> + 同名 dist SKILL.md frontmatter
    定价包装     products/<product>.yaml variants.<v> 的 channel / price / entrypoints
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

MODULE_ROOT = Path(__file__).resolve().parents[2]  # 59-通用组件管理/
CONTRACTS_DIR = MODULE_ROOT / "contracts"
COMPONENTS_DIR = MODULE_ROOT / "components"
PRODUCTS_DIR = MODULE_ROOT / "products"
DIST_DIR = MODULE_ROOT / "dist"

SCORECARD_PATH = CONTRACTS_DIR / "product-scorecard.yaml"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
HEADING_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.M)
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.M)
OUTPUT_SAMPLE_RE = re.compile(r"(输出样例|输出示例|返回样例|返回示例|^#{2,4}\s*输出)", re.M)
ERROR_CODE_RE = re.compile(r"(错误码|E_ENV|E_[A-Z]+|不可用|降级|退出码)")
FIRST_RUN_RE = re.compile(r"(```\s*(?:bash|sh|python3?)|^\s*(?:python3?|bash|curl|make)\s)", re.M)

MODE_BY_CHANNEL = {
    "skillpay-subscription": "订阅制",
    "skillpay-once": "买断制",
    "skillhub-pay": "按次计费",
}


@dataclass
class Surface:
    kind: str
    surface_id: str
    path: str
    fields: Dict[str, object] = field(default_factory=dict)
    family: str = ""

    def get(self, key: str, default: object = None) -> object:
        return self.fields.get(key, default)

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "surface_id": self.surface_id,
            "path": self.path,
            "family": self.family,
            "fields": self.fields,
        }


def load_scorecard(path: Optional[Path] = None) -> dict:
    target = Path(path) if path else SCORECARD_PATH
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("评分卡顶层必须是映射")
    return data


def parse_frontmatter(text: str) -> Dict[str, object]:
    match = FRONTMATTER_RE.match(text or "")
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def analyze_skill_body(body: str) -> Dict[str, object]:
    sections = [item.strip() for item in HEADING_RE.findall(body or "")]
    bullets = [item.strip() for item in BULLET_RE.findall(body or "")]
    examples = [
        item
        for item in bullets
        if ("「" in item or "」" in item or "`" in item) and 4 <= len(item) <= 80
    ]
    return {
        "sections": sections,
        "examples": examples[:12],
        "output_sample": bool(OUTPUT_SAMPLE_RE.search(body or "")),
        "error_codes": bool(ERROR_CODE_RE.search(body or "")),
        "first_run_cmd": bool(FIRST_RUN_RE.search(body or "")),
    }


def _skill_surface(path: Path, component: str, variant: str) -> Surface:
    text = path.read_text(encoding="utf-8")
    front = parse_frontmatter(text)
    match = FRONTMATTER_RE.match(text)
    body = text[match.end() :] if match else text
    analyzed = analyze_skill_body(body)
    description = str(front.get("description") or "")
    fields: Dict[str, object] = {
        "name": front.get("name") or component,
        "title": front.get("displayName") or front.get("display_name") or "",
        "subtitle": front.get("summary") or "",
        "description": description,
        "tags": front.get("tags") or [],
        "license": front.get("license") or "",
        "version": str(front.get("version") or ""),
        "not_for": _extract_not_for(description),
        "changelog": bool(front.get("changelog")),
        "variant": variant,
    }
    fields.update(analyzed)
    return Surface(
        kind="skill_md",
        surface_id="skill:{}:{}".format(component, variant),
        path=str(path),
        fields=fields,
        family=component,
    )


def _extract_not_for(description: str) -> str:
    match = re.search(r"(不用于|不做|不查|不给|不预测)[^。；\n]*", description or "")
    return match.group(0) if match else ""


def _default_tool_name(component: str, action: str) -> str:
    return "{}_{}".format(str(component).replace("-", "_"), str(action).replace("-", "_"))


def _action_surfaces(component_dir: Path) -> List[Surface]:
    manifest = component_dir / "component.yaml"
    if not manifest.exists():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    component = str(data.get("name") or component_dir.name)
    surfaces: List[Surface] = []
    for action in data.get("actions") or []:
        mcp = action.get("mcp") or {}
        if not mcp.get("expose"):
            continue
        # 与 mcp_shells/l0_components/server.py 的投影条件保持一致
        if action.get("safety", "read") == "write" or action.get("output") != "json":
            continue
        tool_name = str(mcp.get("name") or _default_tool_name(component, action.get("name") or ""))
        description = "{}（{}）".format(
            action.get("description") or data.get("summary", ""), component
        )
        if action.get("when_to_use"):
            description += " 适用：{}".format(action["when_to_use"])
        if action.get("not_for"):
            description += " 不适用：{}".format(action["not_for"])
        surfaces.append(
            Surface(
                kind="mcp_tool",
                surface_id="mcp:{}:{}".format(component, tool_name),
                path=str(manifest),
                family=component,
                fields={
                    "name": tool_name,
                    "description": description,
                    "raw_description": action.get("description") or "",
                    "when_to_use": action.get("when_to_use") or "",
                    "not_for": action.get("not_for") or "",
                    "output": action.get("output") or "",
                    "params_count": len(action.get("params") or []),
                    "tier": mcp.get("tier") or "",
                },
            )
        )
    return surfaces


def skill_surfaces(component: str) -> List[Surface]:
    variants = sorted(path.parent.name for path in (DIST_DIR / component).glob("*/SKILL.md"))
    if variants:
        return [
            _skill_surface(DIST_DIR / component / variant / "SKILL.md", component, variant)
            for variant in variants
        ]
    fallback = COMPONENTS_DIR / component / "skill" / "SKILL.md"
    if fallback.exists():
        return [_skill_surface(fallback, component, "source")]
    return []


def _product_variants(product_path: Path) -> Dict[str, dict]:
    data = yaml.safe_load(product_path.read_text(encoding="utf-8")) or {}
    return data.get("variants") or {}


def product_surfaces(product: str) -> List[Surface]:
    product_path = PRODUCTS_DIR / "{}.yaml".format(product)
    if not product_path.exists():
        return []
    surfaces: List[Surface] = []
    for variant, config in sorted(_product_variants(product_path).items()):
        channel = str(config.get("channel") or "")
        mode = MODE_BY_CHANNEL.get(channel, channel or "")
        price = str(config.get("price") or "")
        component = _component_for_product(product_path)
        front = _front_for(component, variant) if component else {}
        tags = front.get("tags") or []
        description = str(front.get("description") or "")
        surfaces.append(
            Surface(
                kind="product_page",
                surface_id="page:{}:{}".format(product, variant),
                path=str(product_path),
                family=product,
                fields={
                    "title": config.get("display_name") or "",
                    "subtitle": front.get("summary") or "",
                    "description": description,
                    "keywords": tags,
                    "license": config.get("license") or front.get("license") or "",
                    "price": price,
                    "mode": mode,
                    "trial": config.get("trial", 0),
                    "changelog": bool(front.get("changelog")),
                },
            )
        )
        surfaces.append(
            Surface(
                kind="packaging",
                surface_id="pack:{}:{}".format(product, variant),
                path=str(product_path),
                family=product,
                fields={
                    "price": price,
                    "mode": mode,
                    "channel": channel,
                    "trial": config.get("trial", 0),
                    "product_id": config.get("product_id") or "",
                    "entrypoints": len(config.get("entrypoints") or []),
                    "free_entry": price.strip() in {"0", "0.0", "免费", "free"},
                },
            )
        )
    return surfaces


def _component_for_product(product_path: Path) -> str:
    data = yaml.safe_load(product_path.read_text(encoding="utf-8")) or {}
    rel = str(data.get("component") or "")
    return Path(rel).name if rel else ""


def _front_for(component: str, variant: str) -> Dict[str, object]:
    candidate = DIST_DIR / component / variant / "SKILL.md"
    if not candidate.exists():
        candidates = sorted((DIST_DIR / component).glob("*/SKILL.md"))
        candidate = candidates[0] if candidates else None
    if not candidate or not candidate.exists():
        return {}
    text = candidate.read_text(encoding="utf-8")
    return parse_frontmatter(text)


def component_names() -> List[str]:
    return sorted(path.name for path in COMPONENTS_DIR.iterdir() if path.is_dir())


def product_names() -> List[str]:
    return sorted(path.stem for path in PRODUCTS_DIR.glob("*.yaml"))


def surfaces_for_component(component: str) -> List[Surface]:
    return _action_surfaces(COMPONENTS_DIR / component) + skill_surfaces(component)


def surfaces_for_product(product: str) -> List[Surface]:
    return product_surfaces(product)


def all_surfaces() -> List[Surface]:
    surfaces: List[Surface] = []
    for component in component_names():
        surfaces.extend(surfaces_for_component(component))
    for product in product_names():
        surfaces.extend(surfaces_for_product(product))
    return surfaces


def target_surfaces(target: str) -> List[Surface]:
    if target in component_names():
        return surfaces_for_component(target)
    if target in product_names():
        return surfaces_for_product(target)
    raise FileNotFoundError("找不到组件或商品：{}".format(target))


def iter_targets() -> Iterable[str]:
    return list(component_names()) + list(product_names())


def lifecycle(component: str) -> str:
    manifest = COMPONENTS_DIR / component / "component.yaml"
    if not manifest.exists():
        return ""
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return str(data.get("lifecycle") or "")


def release_surfaces() -> List[Surface]:
    """发布门禁的评分范围：只评 active 组件的组件产物与其商品页。"""
    active = [name for name in component_names() if lifecycle(name) == "active"]
    surfaces: List[Surface] = []
    for component in active:
        surfaces.extend(surfaces_for_component(component))
    for product in product_names():
        product_path = PRODUCTS_DIR / "{}.yaml".format(product)
        if _component_for_product(product_path) in active:
            surfaces.extend(product_surfaces(product))
    return surfaces

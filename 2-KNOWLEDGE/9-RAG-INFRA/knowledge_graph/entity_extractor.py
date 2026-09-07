# -*- coding: utf-8 -*-
"""实体关系抽取（规则 + 模式匹配，非 LLM）。

抽取保证确定性：相同输入恒定输出，便于回归测试与增量重建。
抽取规则：
- 模块名：匹配 `NN-名称` 格式（如 11-易经推理系统、4-MEMORY）
- 文件路径：匹配 *.py / *.md
- 参数：匹配 `参数名 = 值` / `参数名: 值` / Markdown 表格 `| 参数 | 值 |`
- 算法：从内联标签抽取 #kalman #pca 等
- 数据源：匹配 URL 格式
- 模块依赖：从"关联/来源/注入/依赖/调用/供给/消费"等关键词附近抽取
- 概念：从加粗文本 **...** 抽取（排除冒号结尾的标签）

返回 {nodes: [...], edges: [...]}，节点/边均含 source_file 溯源。
"""

import re
from typing import Dict, List

try:
    from .schema import NodeType, RelationType, node_id
except ImportError:  # 直接以脚本运行时
    from schema import NodeType, RelationType, node_id


# === 正则规则 ===

# 模块名：1-2 位数字 + 连字符 + 中英文名称（名称首字符为字母或中文）
# 负向回溯排除单词/斜杠前缀，避免误匹配 URL 或路径片段
_MODULE_RE = re.compile(r"(?<![\w/])(\d{1,2}-[A-Za-z\u4e00-\u9fa5][\w\u4e00-\u9fa5\-]*)")

# 文件路径：ASCII 字母开头，可含 / 子路径，扩展名 py 或 md
_FILE_RE = re.compile(r"(?<![\w/])([a-zA-Z][a-zA-Z0-9_\-/]*\.(?:py|md))")

# 内联标签（算法）：# 紧跟词字符，且 # 前面不是 # 或词字符（排除标题/井号连写）
_TAG_RE = re.compile(r"(?<![#\w])#([A-Za-z0-9_][\w\-]*)")

# 数据源 URL
_URL_RE = re.compile(r"https?://[^\s)））,，。、|]+")

# 加粗文本 **...**（排除跨行；名称不以冒号结尾的标签如 **铁律：**）
_BOLD_RE = re.compile(r"\*\*([^*\n]{2,40}?)\*\*")

# 内联参数：name = value 或 name: value（值须为数字，含小数）
# 名称首字符须为 ASCII 字母或希腊字母（排除下划线/中文开头的页脚如 _最后更新：2026）
_INLINE_PARAM_RE = re.compile(
    r"(?<![\w])([A-Za-zθαβγδμσ][\wθαβγδμσ*]{1,})\s*[=：:]\s*(0?\.\d+|\d+\.?\d*)"
)

# Markdown 表格行：以 | 开头
_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")

# 依赖/关联关键词
_DEPEND_KW = ("依赖", "关联", "来源", "注入", "调用", "供给", "消费", "集成", "关系")


def _split_table_cells(line: str) -> List[str]:
    """拆分 Markdown 表格行单元格，去首尾空白与包裹的 |。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_numeric(val: str) -> bool:
    """判断字符串是否可解析为数字（用于参数值识别）。"""
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _is_separator_row(cells: List[str]) -> bool:
    """判断是否为表格分隔行（如 |---|---|）。"""
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip()) and any(
        c.strip() for c in cells
    )


def _clean_module_name(raw: str) -> str:
    """清理模块名：去掉行内说明括号（如 `五计庙算（战略层）` -> `五计庙算`）。"""
    # 去掉中文/英文括号及其内容
    cleaned = re.sub(r"[（(][^()（）]*[）)]", "", raw).strip()
    return cleaned or raw.strip()


def _extract_parameters(text: str, source_file: str, domain: str,
                        nodes: List[Dict], edges: List[Dict],
                        subject_id: str) -> None:
    """抽取参数节点：内联 `name = value` 与 Markdown 表格 `| name | value |`。"""
    seen = set()  # 参数名去重

    # 1) 内联参数
    for m in _INLINE_PARAM_RE.finditer(text):
        name, value = m.group(1), m.group(2)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        nid = node_id(NodeType.PARAMETER, name)
        nodes.append({
            "id": nid, "type": NodeType.PARAMETER.value,
            "name": name, "value": value,
            "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": nid, "target": subject_id,
            "relation": RelationType.CONFIGURED_BY.value,
            "source_file": source_file,
        })

    # 2) Markdown 表格参数：列含"参数"表头，取后续行的 前两列(名称|值)
    lines = text.split("\n")
    in_param_table = False
    name_col = 0
    value_col = 1
    for line in lines:
        if not _TABLE_ROW_RE.match(line):
            in_param_table = False
            continue
        cells = _split_table_cells(line)
        if _is_separator_row(cells):
            continue
        # 检测表头是否为参数表
        if not in_param_table:
            header = "".join(cells)
            if "参数" in header or "param" in header.lower():
                in_param_table = True
                # 定位名称列（含"参数"的列），值列紧跟其后
                for idx, c in enumerate(cells):
                    if "参数" in c or "param" in c.lower():
                        name_col = idx
                        value_col = idx + 1
                        break
                continue
            else:
                continue  # 非参数表，跳过
        # 参数表数据行
        if len(cells) > max(name_col, value_col):
            name = cells[name_col].strip("`* ")
            value = cells[value_col].strip()
            if name and _is_numeric(value) and name.lower() not in seen:
                seen.add(name.lower())
                nid = node_id(NodeType.PARAMETER, name)
                nodes.append({
                    "id": nid, "type": NodeType.PARAMETER.value,
                    "name": name, "value": value,
                    "source_file": source_file, "domain": domain,
                })
                edges.append({
                    "source": nid, "target": subject_id,
                    "relation": RelationType.CONFIGURED_BY.value,
                    "source_file": source_file,
                })


def _extract_dependency_modules(text: str, source_file: str, domain: str,
                                nodes: List[Dict], edges: List[Dict],
                                primary_module: str, primary_id: str,
                                known_module_names: set) -> None:
    """抽取模块依赖关系：从"与其他模块的关系"等表格与关键词附近抽取。

    区分两类关系表：
    - 模块关系表（表头含"模块"+"关系/关联/依赖/集成"）：取"模块"列作为依赖对象，
      建立 primary_module -> 依赖模块 的 DEPENDS_ON 边。
    - 数据供给表（表头含"消费方"+"供给方"）：供给方为模块或 URL，
      建立 供给方 -> primary_module 的 FEEDS_DATA 边（仅当消费方涉及主模块时）。
    """
    if not primary_module:
        return

    lines = text.split("\n")
    table_kind = None  # None | "module_rel" | "supply"
    name_col = 0

    for line in lines:
        if not _TABLE_ROW_RE.match(line):
            table_kind = None
            continue
        cells = _split_table_cells(line)
        if _is_separator_row(cells):
            continue

        if table_kind is None:
            header = "".join(cells)
            # 模块关系表
            if "模块" in header and any(
                kw in header for kw in ("关系", "关联", "依赖", "集成")
            ):
                table_kind = "module_rel"
                name_col = 0
                for idx, c in enumerate(cells):
                    if "模块" in c:
                        name_col = idx
                        break
                continue
            # 数据供给表
            elif "消费方" in header and "供给方" in header:
                table_kind = "supply"
                continue
            else:
                continue

        if table_kind == "module_rel":
            # 取 name_col 列作为依赖模块名
            if len(cells) > name_col:
                dep_name = _clean_module_name(cells[name_col])
                if dep_name and dep_name != primary_module:
                    dep_id = node_id(NodeType.MODULE, dep_name)
                    known_module_names.add(dep_name)
                    nodes.append({
                        "id": dep_id, "type": NodeType.MODULE.value,
                        "name": dep_name, "source_file": source_file, "domain": domain,
                    })
                    edges.append({
                        "source": primary_id, "target": dep_id,
                        "relation": RelationType.DEPENDS_ON.value,
                        "source_file": source_file,
                    })
        elif table_kind == "supply":
            _process_supply_row(cells, source_file, domain, nodes, edges,
                                primary_module, primary_id, known_module_names)


def _process_supply_row(cells: List[str], source_file: str, domain: str,
                        nodes: List[Dict], edges: List[Dict],
                        primary_module: str, primary_id: str,
                        known_module_names: set) -> None:
    """处理"数据供给依赖"表行：供给方向主模块供给数据。

    仅当消费方（首列）涉及主模块时建立 FEEDS_DATA 边，避免无关边。
    """
    if len(cells) < 2 or not primary_module:
        return
    consumer = cells[0]
    # 消费方须涉及主模块（名称或"战略层/BCRM"等代称）才建立边
    if primary_module not in consumer and "战略层" not in consumer and "BCRM" not in consumer:
        return
    supply_name = _clean_module_name(cells[1])
    if not supply_name or supply_name == primary_module:
        return
    # 供给方为 URL -> DataSource；否则作为 Module
    if supply_name.startswith(("http://", "https://")):
        sid = node_id(NodeType.DATA_SOURCE, supply_name)
        nodes.append({
            "id": sid, "type": NodeType.DATA_SOURCE.value,
            "name": supply_name, "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": sid, "target": primary_id,
            "relation": RelationType.FEEDS_DATA.value,
            "source_file": source_file,
        })
    else:
        sid = node_id(NodeType.MODULE, supply_name)
        known_module_names.add(supply_name)
        nodes.append({
            "id": sid, "type": NodeType.MODULE.value,
            "name": supply_name, "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": primary_id, "target": sid,
            "relation": RelationType.FEEDS_DATA.value,
            "source_file": source_file,
        })


def extract_entities(text: str, source_file: str, domain: str) -> Dict:
    """从 Markdown 文本抽取实体与关系。

    Args:
        text: Markdown 原文。
        source_file: 源文件相对路径（用于溯源）。
        domain: 所属域（如 1-TRADING）。

    Returns:
        {"nodes": [...], "edges": [...]}，节点含 id/type/name/source_file，
        边含 source/target/relation/source_file。
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []

    if not text or not text.strip():
        return {"nodes": nodes, "edges": edges}

    # 1) 当前文件节点
    file_name = source_file.rsplit("/", 1)[-1] if source_file else ""
    file_id = node_id(NodeType.FILE, file_name or source_file)
    nodes.append({
        "id": file_id, "type": NodeType.FILE.value,
        "name": file_name or source_file,
        "source_file": source_file, "extension": file_name.rsplit(".", 1)[-1] if "." in file_name else "",
        "domain": domain,
    })

    # 2) 主模块：优先取"来源/定位"引用块（文件开头 > 引用）中的首个 NN-名称
    primary_module = ""
    primary_id = ""
    # 引用块（文件开头 > 开头的若干行）
    head_lines = text.split("\n")[:6]
    head_blob = "\n".join(head_lines)
    head_mods = _MODULE_RE.findall(head_blob)
    if head_mods:
        primary_module = head_mods[0]
        primary_id = node_id(NodeType.MODULE, primary_module)
        nodes.append({
            "id": primary_id, "type": NodeType.MODULE.value,
            "name": primary_module, "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": file_id, "target": primary_id,
            "relation": RelationType.IMPLEMENTS.value,
            "source_file": source_file,
        })
    else:
        # 退化：取全文首个模块作为主模块
        all_mods = _MODULE_RE.findall(text)
        if all_mods:
            primary_module = all_mods[0]
            primary_id = node_id(NodeType.MODULE, primary_module)
            nodes.append({
                "id": primary_id, "type": NodeType.MODULE.value,
                "name": primary_module, "source_file": source_file, "domain": domain,
            })
            edges.append({
                "source": file_id, "target": primary_id,
                "relation": RelationType.IMPLEMENTS.value,
                "source_file": source_file,
            })

    # 3) H1 标题 -> 概念节点（文件主题），并连接到主模块
    h1_match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    subject_id = primary_id or file_id  # 参数等关系的默认挂载点
    concept_ids: List[str] = []
    if h1_match:
        h1 = h1_match.group(1).strip()
        h1_id = node_id(NodeType.CONCEPT, h1)
        nodes.append({
            "id": h1_id, "type": NodeType.CONCEPT.value,
            "name": h1, "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": file_id, "target": h1_id,
            "relation": RelationType.RELATES_TO.value,
            "source_file": source_file,
        })
        if primary_id:
            edges.append({
                "source": h1_id, "target": primary_id,
                "relation": RelationType.IMPLEMENTS.value,
                "source_file": source_file,
            })
        subject_id = h1_id
        concept_ids.append(h1_id)

    # 4) 加粗文本 -> 概念节点（排除冒号结尾的标签如 **铁律：**）
    h1_title = h1_match.group(1).strip() if h1_match else ""
    for m in _BOLD_RE.finditer(text):
        concept = m.group(1).strip()
        # 跳过冒号结尾的标签、纯数字、与 H1 重复
        if concept.endswith(("：", ":")) or concept.isdigit() or concept == h1_title:
            continue
        if len(concept) < 2:
            continue
        cid = node_id(NodeType.CONCEPT, concept)
        nodes.append({
            "id": cid, "type": NodeType.CONCEPT.value,
            "name": concept, "source_file": source_file, "domain": domain,
        })
        if primary_id:
            edges.append({
                "source": cid, "target": primary_id,
                "relation": RelationType.IMPLEMENTS.value,
                "source_file": source_file,
            })
        concept_ids.append(cid)

    # 5) 参数抽取（挂载到主题概念或主模块）
    _extract_parameters(text, source_file, domain, nodes, edges, subject_id)

    # 6) 文件引用（*.py / *.md），排除自身
    for m in _FILE_RE.finditer(text):
        ref = m.group(1)
        if ref == file_name:
            continue
        rid = node_id(NodeType.FILE, ref)
        nodes.append({
            "id": rid, "type": NodeType.FILE.value,
            "name": ref, "source_file": source_file,
            "extension": ref.rsplit(".", 1)[-1],
            "domain": domain,
        })
        edges.append({
            "source": file_id, "target": rid,
            "relation": RelationType.RELATES_TO.value,
            "source_file": source_file,
        })

    # 7) 算法（#tag）-> 算法节点
    for m in _TAG_RE.finditer(text):
        tag = m.group(1)
        aid = node_id(NodeType.ALGORITHM, tag)
        nodes.append({
            "id": aid, "type": NodeType.ALGORITHM.value,
            "name": tag, "source_file": source_file,
        })
        edges.append({
            "source": subject_id, "target": aid,
            "relation": RelationType.USES_ALGORITHM.value,
            "source_file": source_file,
        })

    # 8) 数据源 URL
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;)]）")
        dsid = node_id(NodeType.DATA_SOURCE, url)
        nodes.append({
            "id": dsid, "type": NodeType.DATA_SOURCE.value,
            "name": url, "source_file": source_file, "domain": domain,
        })
        edges.append({
            "source": dsid, "target": primary_id or subject_id,
            "relation": RelationType.FEEDS_DATA.value,
            "source_file": source_file,
        })

    # 9) 模块依赖关系（关系表 + 供给表）
    known = {primary_module} if primary_module else set()
    _extract_dependency_modules(text, source_file, domain, nodes, edges,
                                primary_module, primary_id, known)

    return {"nodes": nodes, "edges": edges}


__all__ = ["extract_entities"]

# -*- coding: utf-8 -*-
"""Wiki 编译核心 — 将素材"提取时编译"为结构化 Wiki 页面。

核心理念（Karpathy LLM Wiki 模式）：
    素材摄入时一次性编译为 sources/entities/concepts 页面 + [[wikilink]] 交叉引用，
    而非每次查询时从原始文档检索。

编译流程：
    1. 获取素材内容（URL 或文本）
    2. LLM 提取结构化信息（核心论点、关键要点、实体、概念、关键引文）
    3. 生成 sources/ 素材摘要页
    4. 生成 entities/ 实体页
    5. 生成 concepts/ 概念页
    6. 建立 [[wikilink]] 交叉引用
    7. 写入 2-KNOWLEDGE/wiki/ 目录

设计原则：
    - FAIL-OPEN：LLM 不可用时降级为规则提取（entity_extractor + 文本分析），不阻塞
    - 可追溯：每个页面带 sources 溯源到原始素材
    - 可演化：页面格式遵循 2-KNOWLEDGE/wiki/AGENTS.md 定义
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent          # .../9-RAG-INFRA/evolution
_RAG_INFRA_DIR = _THIS_DIR.parent                     # .../9-RAG-INFRA
_KNOWLEDGE_DIR = _RAG_INFRA_DIR.parent                # .../2-KNOWLEDGE
WIKI_ROOT = _KNOWLEDGE_DIR / "wiki"                   # .../2-KNOWLEDGE/wiki

# 页面子目录
SOURCES_DIR = WIKI_ROOT / "sources"
ENTITIES_DIR = WIKI_ROOT / "entities"
CONCEPTS_DIR = WIKI_ROOT / "concepts"
SYNTHESES_DIR = WIKI_ROOT / "syntheses"

# 确保目录存在
for d in (SOURCES_DIR, ENTITIES_DIR, CONCEPTS_DIR, SYNTHESES_DIR):
    d.mkdir(parents=True, exist_ok=True)


@dataclass
class ExtractedEntity:
    """抽取的实体"""
    name: str
    category: str = "unknown"  # person | org | product | strategy | module
    description: str = ""


@dataclass
class ExtractedConcept:
    """抽取的概念"""
    name: str
    category: str = "unknown"  # theory | method | algorithm | metric
    definition: str = ""


@dataclass
class CompileResult:
    """编译结果"""
    status: str = "ok"  # ok | degraded | failed
    source_identifier: str = ""
    source_page: str = ""          # sources/ 页面文件名
    entity_pages: List[str] = field(default_factory=list)   # entities/ 页面文件名列表
    concept_pages: List[str] = field(default_factory=list)  # concepts/ 页面文件名列表
    synthesis_page: str = ""         # syntheses/ 综合分析页文件名
    core_conclusion: str = ""      # 核心结论（用于认知记忆沉淀）
    entities: List[Dict] = field(default_factory=list)
    concepts: List[Dict] = field(default_factory=list)
    # 可观测性字段（P2-7）
    pages: List[str] = field(default_factory=list)       # 所有生成页面清单
    duration_ms: float = 0.0          # 编译耗时（毫秒）
    token_estimate: int = 0           # LLM Token 消耗估算
    error: str = ""


def _kebab_case(text: str) -> str:
    """将文本转为 kebab-case 文件名。"""
    # 移除特殊字符，空格转连字符
    text = re.sub(r"[^\w\u4e00-\u9fa5\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text.lower()


def _today_iso() -> str:
    """返回今日 ISO 日期。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yaml_escape(value: str) -> str:
    """YAML 字符串转义：含特殊字符时加引号。"""
    if any(c in value for c in ":#{}[]&*!|>'\"%@`"):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _build_frontmatter(title: str, page_type: str, sources: List[str],
                       tags: List[str], status: str = "active") -> str:
    """构建 YAML frontmatter。"""
    today = _today_iso()
    lines = [
        "---",
        f"title: {_yaml_escape(title)}",
        f"type: {page_type}",
        f"created: {today}",
        f"updated: {today}",
        "sources:",
    ]
    for s in sources:
        lines.append(f"  - {_yaml_escape(s)}")
    lines.append("tags:")
    for t in tags:
        lines.append(f"  - {_yaml_escape(t)}")
    lines.append(f"status: {status}")
    lines.append("---")
    return "\n".join(lines)


class WikiCompiler:
    """Wiki 编译器 — 将素材编译为结构化 Wiki 页面。"""

    def __init__(self, llm_client: Any = None):
        """初始化编译器。

        Args:
            llm_client: LLM 客户端（需支持 chat(messages) -> response.content）。
                        None 时尝试加载 DeepSeekLLMClient，失败则降级为规则提取。
        """
        self._llm = llm_client
        if self._llm is None:
            self._llm = self._load_default_llm()
        self._use_llm = self._llm is not None

    def _load_default_llm(self) -> Optional[Any]:
        """加载默认 LLM 客户端（DeepSeekLLMClient），失败返回 None。"""
        try:
            import sys
            dreamos_shared = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/shared")
            if str(dreamos_shared) not in sys.path:
                sys.path.insert(0, str(dreamos_shared))
            from llm_client import DeepSeekLLMClient
            client = DeepSeekLLMClient()
            # 检查是否有 API key
            if not client.api_key:
                logger.warning("DeepSeek API key 未配置，编译层降级为规则提取")
                return None
            return client
        except Exception as e:
            logger.warning(f"加载 DeepSeekLLMClient 失败: {e}，编译层降级为规则提取")
            return None

    def ingest(self, source: str, source_type: str = "auto",
               two_pass: bool = False) -> CompileResult:
        """编译素材为 Wiki 页面。

        Args:
            source: 素材内容（文本）或 URL。
            source_type: "text" | "url" | "auto"（auto 时自动判断）。
            two_pass: 是否启用两步思维链（先分析再提取，需 LLM）。

        Returns:
            CompileResult 含生成的页面文件列表和核心结论。
        """
        t0 = time.monotonic()
        result = CompileResult()
        try:
            # 1. 获取素材内容
            content, source_identifier = self._fetch_source(source, source_type)
            if not content:
                result.status = "failed"
                result.error = "无法获取素材内容"
                result.duration_ms = (time.monotonic() - t0) * 1000
                return result
            result.source_identifier = source_identifier

            # 1.5. 两步思维链：先 LLM 分析素材结构（P2-8，可选）
            analysis_hint = ""
            if two_pass and self._use_llm:
                try:
                    prompt = (
                        f"分析以下素材的结构和核心主题，给出大纲（3-5个要点），\n"
                        f"用于辅助后续实体/概念提取。\n\n素材前500字：{content[:500]}"
                    )
                    resp = self.llm.chat([LLMMessage(role="user", content=prompt)])
                    if resp and resp.content:
                        analysis_hint = resp.content.strip()[:500]
                        result.token_estimate += len(content[:500]) // 4 + len(analysis_hint) // 4
                except Exception as e:
                    logger.warning(f"两步思维链分析失败，跳过: {e}")

            # 2. 提取结构化信息
            extraction = self._extract(content, analysis_hint=analysis_hint)
            if extraction.get("status") == "failed":
                result.status = "failed"
                result.error = extraction.get("error", "提取失败")
                return result
            if extraction.get("status") == "degraded":
                result.status = "degraded"

            core_conclusion = extraction.get("core_conclusion", "")
            key_points = extraction.get("key_points", [])
            entities = extraction.get("entities", [])
            concepts = extraction.get("concepts", [])
            quotes = extraction.get("quotes", [])

            result.core_conclusion = core_conclusion
            result.entities = entities
            result.concepts = concepts

            # 3. 生成 sources/ 页面
            source_page = self._write_source_page(
                source_identifier, content, core_conclusion, key_points,
                entities, concepts, quotes
            )
            result.source_page = source_page

            # 4. 生成 entities/ 页面
            entity_pages = []
            for ent in entities:
                page = self._write_entity_page(ent, source_page, source_identifier)
                if page:
                    entity_pages.append(page)
            result.entity_pages = entity_pages

            # 5. 生成 concepts/ 页面
            concept_pages = []
            for con in concepts:
                page = self._write_concept_page(con, source_page, source_identifier)
                if page:
                    concept_pages.append(page)
            result.concept_pages = concept_pages

            # 5.5. 生成 syntheses 综合分析页（P0 改进：四类页面闭环）
            try:
                synthesis_topic = source_identifier[:50] if source_identifier else core_conclusion[:50]
                syn_page = self._write_synthesis_page(
                    topic=synthesis_topic,
                    entities=entities,
                    concepts=concepts,
                    core_conclusion=core_conclusion,
                    source_ids=[source_identifier],
                )
                result.synthesis_page = syn_page
            except Exception as e:
                logger.warning(f"生成 syntheses 页面失败（不影响编译）: {e}")
                result.synthesis_page = ""

            # 6. 更新 index.md（可选，FAIL-OPEN）
            try:
                self._update_index()
            except Exception as e:
                logger.warning(f"更新 index.md 失败（不影响编译）: {e}")

            # 7. 同步知识图谱（Task 3：复用 build_graph，全量重建，离线流程可接受）
            try:
                self._sync_knowledge_graph()
            except Exception as e:
                logger.warning(f"同步知识图谱失败（不影响编译）: {e}")

            # 8. 沉淀认知记忆（Task 4：核心结论写入认知系统）
            try:
                self._record_to_cognitive(result)
            except Exception as e:
                logger.warning(f"沉淀认知记忆失败（不影响编译）: {e}")

            # 9. 填充可观测性字段（P2-7）
            all_pages = [result.source_page] if result.source_page else []
            all_pages.extend(result.entity_pages)
            all_pages.extend(result.concept_pages)
            if result.synthesis_page:
                all_pages.append(result.synthesis_page)
            result.pages = all_pages
            result.duration_ms = (time.monotonic() - t0) * 1000
            # 粗略 Token 估算：中文 1字≈1.5 token，提取+分析 LLM 调用
            if result.token_estimate == 0:
                result.token_estimate = len(content) // 3 + len(core_conclusion) // 3

            if result.status != "degraded":
                result.status = "ok"
            return result

        except Exception as e:
            logger.exception(f"编译异常: {e}")
            result.status = "failed"
            result.error = str(e)
            result.duration_ms = (time.monotonic() - t0) * 1000
            return result

    def ingest_batch(self, sources: List[str], source_type: str = "auto",
                     two_pass: bool = False) -> List[CompileResult]:
        """批量编译多个素材（P2-9）。

        顺序处理，单个失败不影响其他。
        """
        results = []
        for src in sources:
            try:
                r = self.ingest(src, source_type=source_type, two_pass=two_pass)
                results.append(r)
            except Exception as e:
                logger.warning(f"批量编译单个素材失败: {e}")
                r = CompileResult(status="failed", error=str(e))
                results.append(r)
        return results

    def _fetch_source(self, source: str, source_type: str) -> tuple:
        """获取素材内容。

        Returns:
            (content, source_identifier)
        """
        if source_type == "text" or (source_type == "auto" and not source.startswith(("http://", "https://"))):
            # 文本素材 — 优先取第一个 H1 标题作为标识
            h1_match = re.search(r"^#\s+(.+?)\s*$", source, re.MULTILINE)
            if h1_match:
                identifier = h1_match.group(1).strip()[:50]
            else:
                identifier = source[:50].replace("\n", " ").strip()
            return source, identifier

        # URL 素材 — 尝试用 requests 获取
        try:
            import requests
            resp = requests.get(source, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DreamBuddyWikiBot/1.0)"
            })
            if resp.status_code == 200:
                # 简单 HTML 转文本（去除标签）
                text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                return text, source
        except Exception as e:
            logger.warning(f"获取 URL 失败: {e}")
        return "", source

    def _extract(self, content: str, analysis_hint: str = "") -> Dict:
        """从素材内容提取结构化信息。

        优先用 LLM 提取，失败降级为规则提取。
        analysis_hint: 两步思维链的分析大纲（可选，辅助 LLM 提取）。
        """
        # 尝试 LLM 提取
        if self._use_llm:
            try:
                result = self._llm_extract(content, analysis_hint=analysis_hint)
                if result and result.get("core_conclusion"):
                    result["status"] = "ok"
                    return result
            except Exception as e:
                logger.warning(f"LLM 提取失败，降级规则提取: {e}")

        # 降级：规则提取
        return self._rule_extract(content)

    def _llm_extract(self, content: str, analysis_hint: str = "") -> Dict:
        """用 LLM 提取结构化信息。analysis_hint 为两步思维链分析大纲。"""
        from llm_client import LLMMessage  # noqa: F401

        system_prompt = (
            "你是 DreamBuddy Wiki 编译系统的提取引擎。"
            "从给定素材中提取结构化信息，以 JSON 格式返回。"
            "JSON 字段：core_conclusion（核心论点，1句话）、"
            "key_points（关键要点列表）、entities（实体列表，每个含 name/category/description）、"
            "concepts（概念列表，每个含 name/category/definition）、"
            "quotes（关键引文列表）。"
            "只返回 JSON，不要其他文字。"
        )

        # 截断过长内容
        max_chars = 8000
        truncated = content[:max_chars] if len(content) > max_chars else content

        user_content = f"请提取以下素材的结构化信息：\n\n{truncated}"
        if analysis_hint:
            user_content += f"\n\n参考分析大纲：\n{analysis_hint}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            resp = self._llm.chat(messages, temperature=0.3, max_tokens=2000)
            text = resp.content.strip()
            # 尝试解析 JSON（可能包裹在 ```json 中）
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(text)
            return data
        except Exception as e:
            logger.warning(f"LLM 提取解析失败: {e}")
            raise

    def _rule_extract(self, content: str) -> Dict:
        """规则提取（降级方案）：基于 entity_extractor + 文本分析。"""
        try:
            # 复用 knowledge_graph 的实体抽取
            sys_path_added = False
            try:
                import sys
                kg_dir = str(_RAG_INFRA_DIR / "knowledge_graph")
                if kg_dir not in sys.path:
                    sys.path.insert(0, kg_dir)
                    sys_path_added = True
                from entity_extractor import extract_entities
                from schema import NodeType

                result = extract_entities(content, "wiki-rule-extract", "wiki")
                nodes = result.get("nodes", [])

                entities = []
                concepts = []
                for n in nodes:
                    ntype = n.get("type", "")
                    name = n.get("name", "")
                    if not name:
                        continue
                    if ntype == NodeType.MODULE.value:
                        entities.append({"name": name, "category": "module", "description": ""})
                    elif ntype == NodeType.CONCEPT.value:
                        concepts.append({"name": name, "category": "theory", "definition": ""})
                    elif ntype == NodeType.ALGORITHM.value:
                        concepts.append({"name": name, "category": "algorithm", "definition": ""})
                    elif ntype == NodeType.STRATEGY.value:
                        entities.append({"name": name, "category": "strategy", "description": ""})
            finally:
                pass  # 不清理 sys.path，避免影响后续

            # 核心结论：取第一段非空文本
            core_conclusion = ""
            for line in content.split("\n"):
                line = line.strip().lstrip("#").strip()
                if line and len(line) > 10:
                    core_conclusion = line[:200]
                    break

            # 关键要点：取 ## 开头的行（排除 H1 和常见章节标题词）
            _SECTION_NOISE = {
                "核心论点", "关键要点", "详细笔记", "涉及实体", "涉及概念",
                "关键引文", "概述", "定义", "关联实体", "关联概念", "出现于",
                "背景", "总结", "结论", "参考", "附录", "目录", "简介",
            }
            key_points = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("##") and not line.startswith("###"):
                    point = line.lstrip("#").strip()
                    if point and point not in _SECTION_NOISE and len(point) > 2:
                        key_points.append(point)

            return {
                "status": "degraded",
                "core_conclusion": core_conclusion,
                "key_points": key_points[:10],
                "entities": entities[:15],
                "concepts": concepts[:15],
                "quotes": [],
            }
        except Exception as e:
            logger.warning(f"规则提取失败: {e}")
            return {
                "status": "ok",
                "core_conclusion": content[:200],
                "key_points": [],
                "entities": [],
                "concepts": [],
                "quotes": [],
            }

    def _write_source_page(self, source_id: str, content: str, core_conclusion: str,
                           key_points: List[str], entities: List[Dict],
                           concepts: List[Dict], quotes: List[str]) -> str:
        """生成并写入 sources/ 素材摘要页。"""
        title = source_id[:50] if source_id else "untitled-source"
        filename = _kebab_case(title) + ".md"
        filepath = SOURCES_DIR / filename

        entity_links = [f"- [[{_kebab_case(e['name'])}]]" for e in entities[:10]]
        concept_links = [f"- [[{_kebab_case(c['name'])}]]" for c in concepts[:10]]

        points_md = "\n".join(f"- {p}" for p in key_points[:10]) if key_points else "- （无）"
        quotes_md = "\n".join(f"> {q}" for q in quotes[:3]) if quotes else "- （无）"

        body = f"""
## 核心论点
{core_conclusion or "（未提取到明确核心论点）"}

## 关键要点
{points_md}

## 涉及实体
{chr(10).join(entity_links) if entity_links else "- （无）"}

## 涉及概念
{chr(10).join(concept_links) if concept_links else "- （无）"}

## 关键引文
{quotes_md}
""".strip()

        frontmatter = _build_frontmatter(
            title=title,
            page_type="source",
            sources=[source_id],
            tags=["wiki", "source", "编译"],
        )
        page_content = frontmatter + "\n\n" + body + "\n"

        filepath.write_text(page_content, encoding="utf-8")
        logger.info(f"已生成 sources 页面: {filepath.name}")
        return filename

    def _write_entity_page(self, entity: Dict, source_page: str, source_id: str) -> str:
        """生成并写入 entities/ 实体页。"""
        name = entity.get("name", "").strip()
        if not name:
            return ""
        category = entity.get("category", "unknown")
        description = entity.get("description", "")

        filename = _kebab_case(name) + ".md"
        filepath = ENTITIES_DIR / filename

        # 如果页面已存在，追加来源而非覆盖（增量更新）
        if filepath.exists():
            try:
                existing = filepath.read_text(encoding="utf-8")
                if source_page not in existing:
                    # 在"出现于"部分追加
                    updated = existing.rstrip() + f"\n- [[{source_page.replace('.md', '')}]]\n"
                    # 更新 updated 日期
                    updated = re.sub(
                        r"^updated: .*$",
                        f"updated: {_today_iso()}",
                        existing, count=1, flags=re.MULTILINE
                    )
                    filepath.write_text(updated, encoding="utf-8")
                    return filename
            except Exception:
                pass

        body = f"""
## 概述
{description or f"{name}（{category}）"}

## 关联概念
- （待补充）

## 出现于
- [[{source_page.replace('.md', '')}]]
""".strip()

        frontmatter = _build_frontmatter(
            title=name,
            page_type="entity",
            sources=[source_id],
            tags=["entity", category, "编译"],
        )
        page_content = frontmatter + "\n\n" + body + "\n"
        filepath.write_text(page_content, encoding="utf-8")
        return filename

    def _write_concept_page(self, concept: Dict, source_page: str, source_id: str) -> str:
        """生成并写入 concepts/ 概念页。"""
        name = concept.get("name", "").strip()
        if not name:
            return ""
        category = concept.get("category", "unknown")
        definition = concept.get("definition", "")

        filename = _kebab_case(name) + ".md"
        filepath = CONCEPTS_DIR / filename

        # 已存在则追加来源
        if filepath.exists():
            try:
                existing = filepath.read_text(encoding="utf-8")
                if source_page not in existing:
                    updated = re.sub(
                        r"^updated: .*$",
                        f"updated: {_today_iso()}",
                        existing, count=1, flags=re.MULTILINE
                    )
                    if "## 出现于" in updated:
                        updated = updated.replace(
                            "## 出现于\n",
                            f"## 出现于\n- [[{source_page.replace('.md', '')}]]\n",
                            1
                        )
                    else:
                        updated = updated.rstrip() + f"\n\n## 出现于\n- [[{source_page.replace('.md', '')}]]\n"
                    filepath.write_text(updated, encoding="utf-8")
                    return filename
            except Exception:
                pass

        body = f"""
## 定义
{definition or f"{name}（{category}）"}

## 关联实体
- （待补充）

## 关联概念
- （待补充）

## 出现于
- [[{source_page.replace('.md', '')}]]
""".strip()

        frontmatter = _build_frontmatter(
            title=name,
            page_type="concept",
            sources=[source_id],
            tags=["concept", category, "编译"],
        )
        page_content = frontmatter + "\n\n" + body + "\n"
        filepath.write_text(page_content, encoding="utf-8")
        return filename

    def _check_similarity(self, new_content: str, existing_path: Path) -> float:
        """计算新内容与已有文件的相似度。"""
        try:
            existing = existing_path.read_text(encoding="utf-8")
            import difflib
            return difflib.SequenceMatcher(None, new_content, existing).ratio()
        except Exception:
            return 0.0

    def _write_synthesis_page(self, topic: str, entities: List[Dict],
                              concepts: List[Dict], core_conclusion: str,
                              source_ids: List[str]) -> str:
        """生成并写入 syntheses/ 综合分析页。

        Returns:
            写入的文件名（空字符串表示跳过/失败）。
        """
        topic = (topic or "").strip()
        if not topic:
            return ""

        filename = _kebab_case(topic) + ".md"
        filepath = SYNTHESES_DIR / filename

        # 构建实体/概念的 [[wikilink]] 列表
        ent_links = [f"- [[{_kebab_case(e.get('name', ''))}]] — {e.get('description', '')[:50]}"
                     for e in entities if e.get("name")]
        con_links = [f"- [[{_kebab_case(c.get('name', ''))}]] — {c.get('definition', '')[:50]}"
                     for c in concepts if c.get("name")]

        # 交叉分析：优先用 LLM 生成，降级为基于核心结论的模板
        cross_analysis = core_conclusion or "（待补充交叉分析）"
        if self._use_llm and core_conclusion:
            try:
                ent_names = [e.get("name", "") for e in entities if e.get("name")][:5]
                con_names = [c.get("name", "") for c in concepts if c.get("name")][:5]
                prompt = (
                    f"基于以下素材核心结论和提取的实体/概念，生成一段综合分析（≤300字），\n"
                    f"阐述它们之间的关联和整体洞察。\n\n"
                    f"核心结论：{core_conclusion[:500]}\n"
                    f"实体：{', '.join(ent_names)}\n"
                    f"概念：{', '.join(con_names)}\n"
                )
                resp = self.llm.chat([LLMMessage(role="user", content=prompt)])
                if resp and resp.content:
                    cross_analysis = resp.content.strip()[:800]
            except Exception as e:
                logger.warning(f"LLM 生成交叉分析失败，降级使用核心结论: {e}")

        body = f"""## 主题概述
{core_conclusion or "（综合分析主题）"}

## 关联实体
{chr(10).join(ent_links) if ent_links else "- （无）"}

## 关联概念
{chr(10).join(con_links) if con_links else "- （无）"}

## 交叉分析
{cross_analysis}

## 来源
{chr(10).join(f"- {s}" for s in source_ids) if source_ids else "- （无）"}
""".strip()

        frontmatter = _build_frontmatter(
            title=topic,
            page_type="synthesis",
            sources=source_ids,
            tags=["synthesis", "编译", "综合分析"],
        )
        page_content = frontmatter + "\n\n" + body + "\n"

        # 冲突检测：已存在且相似度 >0.7 则跳过
        if filepath.exists():
            sim = self._check_similarity(page_content, filepath)
            if sim > 0.7:
                logger.info(f"syntheses 页面已存在且相似度 {sim:.2f}>0.7，跳过: {filename}")
                return filename

        filepath.write_text(page_content, encoding="utf-8")
        logger.info(f"写入 syntheses 页面: {filename}")
        return filename

    def _update_index(self) -> None:
        """更新 index.md 目录（统计页面数量）。"""
        index_path = WIKI_ROOT / "index.md"
        src_count = len(list(SOURCES_DIR.glob("*.md")))
        ent_count = len(list(ENTITIES_DIR.glob("*.md")))
        con_count = len(list(CONCEPTS_DIR.glob("*.md")))
        syn_count = len(list(SYNTHESES_DIR.glob("*.md")))

        index_content = f"""# Wiki 内容目录

> 本文件是 DreamBuddy Wiki 编译层的内容索引，自动维护所有 Wiki 页面的清单。

## 统计

| 类型 | 数量 |
|---|---|
| sources（素材摘要页） | {src_count} |
| entities（实体页） | {ent_count} |
| concepts（概念页） | {con_count} |
| syntheses（综合分析页） | {syn_count} |
| **总计** | **{src_count + ent_count + con_count + syn_count}** |

## sources/ 素材摘要页

{self._list_pages(SOURCES_DIR)}

## entities/ 实体页

{self._list_pages(ENTITIES_DIR)}

## concepts/ 概念页

{self._list_pages(CONCEPTS_DIR)}

## syntheses/ 综合分析页

{self._list_pages(SYNTHESES_DIR)}
"""
        index_path.write_text(index_content, encoding="utf-8")

    @staticmethod
    def _list_pages(directory: Path) -> str:
        """列出目录下的页面（用于 index.md）。"""
        pages = sorted(directory.glob("*.md"))
        if not pages:
            return "_（暂无页面）_"
        return "\n".join(f"- [[{p.stem}]]" for p in pages)

    def _sync_knowledge_graph(self) -> None:
        """同步知识图谱与索引：编译完成后重建图谱和索引。

        - 幂等检查：Wiki 目录无新增/修改文件时跳过全量同步
        - build_graph: 扫描 2-KNOWLEDGE 构建知识图谱
        - build_index: 增量更新 ChromaDB 向量索引
        - build_keyword_index: 重建 Whoosh 关键词索引
        """
        # 幂等检查（P1-5）：比较 Wiki 目录最新 mtime 与上次同步时间
        last_sync_file = WIKI_ROOT / ".last_index_sync"
        try:
            latest_mtime = 0.0
            for d in (SOURCES_DIR, ENTITIES_DIR, CONCEPTS_DIR, SYNTHESES_DIR):
                for f in d.glob("*.md"):
                    latest_mtime = max(latest_mtime, f.stat().st_mtime)
            if last_sync_file.exists():
                last_sync = float(last_sync_file.read_text().strip())
                if latest_mtime <= last_sync:
                    logger.info("Wiki 目录无变更，跳过索引同步（幂等）")
                    return
        except Exception:
            pass  # 检查失败则继续同步

        try:
            import sys
            kg_dir = str(_RAG_INFRA_DIR / "knowledge_graph")
            if kg_dir not in sys.path:
                sys.path.insert(0, kg_dir)
            from build_graph import build_graph
            from schema import DEFAULT_GRAPH_PATH

            stats = build_graph(_KNOWLEDGE_DIR, graph_path=DEFAULT_GRAPH_PATH)
            logger.info(
                f"知识图谱同步完成: {stats.get('total_nodes', 0)} 节点, "
                f"{stats.get('total_edges', 0)} 边, "
                f"失败 {stats.get('failed_files', 0)} 文件"
            )
        except Exception as e:
            logger.warning(f"知识图谱同步异常: {e}")
            raise

        # 同步 ChromaDB 向量索引（增量）
        try:
            import sys
            vs_dir = str(_RAG_INFRA_DIR / "vector_store")
            if vs_dir not in sys.path:
                sys.path.insert(0, vs_dir)
            from build_index import build_index
            stats = build_index(_KNOWLEDGE_DIR)
            logger.info(
                f"向量索引同步完成: {stats.get('total_chunks', 0)} chunks, "
                f"新增 {stats.get('new_chunks', 0)}"
            )
        except Exception as e:
            logger.warning(f"向量索引同步异常: {e}")

        # 同步 Whoosh 关键词索引
        try:
            import sys
            re_dir = str(_RAG_INFRA_DIR / "rag_engine")
            if re_dir not in sys.path:
                sys.path.insert(0, re_dir)
            from keyword_search import build_keyword_index
            stats = build_keyword_index(_KNOWLEDGE_DIR)
            logger.info(
                f"关键词索引同步完成: {stats.get('total_docs', 0)} docs"
            )
        except Exception as e:
            logger.warning(f"关键词索引同步异常: {e}")

        # 更新同步时间戳
        try:
            last_sync_file.write_text(str(time.time()))
        except Exception:
            pass

    def query(self, question: str, top_k: int = 5,
              enable_write_back: bool = True) -> Dict[str, Any]:
        """Wiki 查询 + 高价值结果回写为 syntheses。

        Args:
            question: 查询问题
            top_k: 返回结果数量
            enable_write_back: 是否启用价值判定后的回写

        Returns:
            {results, write_back_performed, synthesis_page, value_score}
        """
        result: Dict[str, Any] = {
            "results": [],
            "write_back_performed": False,
            "synthesis_page": "",
            "value_score": 0.0,
        }

        # 1. 检索
        try:
            from rag_engine.hybrid_retriever import hybrid_search
            results = hybrid_search(question, top_k=top_k)
            result["results"] = results
        except Exception as e:
            logger.warning(f"wiki_query 检索失败: {e}")
            return result

        if not enable_write_back or not results:
            return result

        # 2. LLM 价值判定（0-1 分），≥0.6 才回写
        if self._use_llm:
            try:
                summary = "; ".join(
                    r.get("title", "") + ": " + r.get("content", "")[:100]
                    for r in results[:3] if isinstance(r, dict)
                )
                prompt = (
                    f'评估以下 Wiki 检索结果是否具有"综合分析价值"，值得沉淀为永久 syntheses 页面。\n'
                    f'返回 JSON：{{"score": 0.0-1.0, "reason": "一句话理由"}}\n\n'
                    f"查询：{question}\n结果摘要：{summary[:800]}\n"
                    f"判定标准：结果覆盖多个实体/概念且有交叉洞察=高分；单一事实/低关联=低分。"
                )
                resp = self.llm.chat([LLMMessage(role="user", content=prompt)])
                if resp and resp.content:
                    import re as _re
                    m = _re.search(r'"score"\s*:\s*([\d.]+)', resp.content)
                    if m:
                        score = float(m.group(1))
                    else:
                        score = 0.5
                    result["value_score"] = min(max(score, 0.0), 1.0)
            except Exception as e:
                logger.warning(f"价值判定失败，默认不回写: {e}")
                result["value_score"] = 0.0

        if result["value_score"] < 0.6:
            return result

        # 3. 回写为 syntheses 页面
        try:
            # 从检索结果提取实体/概念名称
            ent_names = []
            con_names = []
            for r in results[:5]:
                if isinstance(r, dict):
                    src = r.get("source", "")
                    if "/entities/" in src:
                        ent_names.append(r.get("title", ""))
                    elif "/concepts/" in src:
                        con_names.append(r.get("title", ""))
            entities = [{"name": n} for n in ent_names if n]
            concepts = [{"name": n} for n in con_names if n]

            synthesis_page = self._write_synthesis_page(
                topic=question[:50],
                entities=entities,
                concepts=concepts,
                core_conclusion=f"查询回写：{question}",
                source_ids=[f"query:{question[:30]}"],
            )
            if synthesis_page:
                result["write_back_performed"] = True
                result["synthesis_page"] = synthesis_page
                logger.info(f"Query 回写 syntheses: {synthesis_page}")
        except Exception as e:
            logger.warning(f"Query 回写失败: {e}")

        return result

    def _record_to_cognitive(self, result: CompileResult) -> None:
        """将编译核心结论沉淀为认知记忆。

        记忆格式：[Wiki编译] source=<素材> | [核心结论] <结论> | entities=... | concepts=...
        tags: wiki,编译,<域>，source: wiki-compiler
        """
        if not result.core_conclusion:
            return

        ent_names = [e.get("name", "") for e in result.entities[:5] if e.get("name")]
        con_names = [c.get("name", "") for c in result.concepts[:5] if c.get("name")]

        content = (
            f"[Wiki编译] source={result.source_identifier} | "
            f"[核心结论] {result.core_conclusion[:500]} | "
            f"entities={','.join(ent_names)} | "
            f"concepts={','.join(con_names)}"
        )

        tags = "wiki,编译," + (result.entities[0].get("category", "unknown") if result.entities else "general")

        try:
            memory_id = self._cognitive_record(content, tags)
            if memory_id:
                logger.info(f"认知记忆已沉淀: {memory_id}")
            else:
                logger.warning("认知记忆沉淀返回空（认知系统可能不可用）")
        except Exception as e:
            logger.warning(f"认知记忆沉淀异常: {e}")
            raise

    def _cognitive_record(self, content: str, tags: str) -> Optional[str]:
        """调用认知系统 record 接口（FAIL-OPEN）。

        优先通过 cognitive_loop_adapter，降级直接调用 cognitive_loop_entry。
        """
        # 尝试 1: cognitive_loop_adapter（Harness 桥接层）
        try:
            import sys
            bridge_dir = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/integration"
            if bridge_dir not in sys.path:
                sys.path.insert(0, bridge_dir)
            from cognitive_loop_adapter import CognitiveLoopAdapter
            adapter = CognitiveLoopAdapter()
            mid = adapter.record(content=content, tags=tags, quality_level="C")
            if mid:
                return mid
        except Exception as e:
            logger.debug(f"cognitive_loop_adapter 不可用: {e}")

        # 尝试 2: 直接调用 cognitive_loop_entry
        try:
            import sys
            cog_dir = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口"
            if cog_dir not in sys.path:
                sys.path.insert(0, cog_dir)
            from cognitive_loop_entry import CognitiveLoopEntry
            entry = CognitiveLoopEntry()
            result = entry.record(content=content, tags=tags.split(","), source="wiki-compiler")
            if isinstance(result, dict):
                return result.get("memory_id")
            return result
        except Exception as e:
            logger.debug(f"cognitive_loop_entry 直接调用失败: {e}")

        return None


# === 便捷函数 ===

_compiler_instance: Optional[WikiCompiler] = None


def get_compiler() -> WikiCompiler:
    """获取 WikiCompiler 单例。"""
    global _compiler_instance
    if _compiler_instance is None:
        _compiler_instance = WikiCompiler()
    return _compiler_instance


def ingest(source: str, source_type: str = "auto") -> CompileResult:
    """便捷函数：编译素材。"""
    return get_compiler().ingest(source, source_type)


__all__ = [
    "WikiCompiler", "CompileResult", "ingest", "get_compiler",
    "WIKI_ROOT", "SOURCES_DIR", "ENTITIES_DIR", "CONCEPTS_DIR", "SYNTHESES_DIR",
]

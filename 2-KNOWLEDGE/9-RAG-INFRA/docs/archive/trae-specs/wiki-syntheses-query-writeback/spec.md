# Wiki Syntheses 页面生成 + Query 回写机制 - Product Requirements Document

## Overview
- **Summary**: 在现有 Wiki 编译层基础上，补齐 syntheses（综合分析页）生成能力，并为 wiki_query 增加 LLM 价值判定后的回写机制，实现 Karpathy LLM Wiki 模式的"知识复利"闭环。
- **Purpose**: 千问评估指出当前实现缺少 syntheses 页面生成与 Query 回写（综合评分 8.2/10，P0 改进项）。补齐后四类页面（sources/entities/concepts/syntheses）完整闭环，高价值查询可沉淀为永久 Wiki 页面。
- **Target Users**: DreamBuddy AI Agent（通过 Harness wiki_ingest/wiki_query 工具）、开发者。

## Goals
- ingest 编译时自动生成 syntheses 综合页，聚合本次实体/概念/核心结论
- wiki_query 检索后由 LLM 判定综合价值，超阈值时回写为 syntheses 页面
- syntheses 页面写入遵循 AGENTS.md 模式文件规范（frontmatter + [[wikilink]]）
- 冲突处理：相似度 >0.7 跳过，≤0.7 覆盖更新，避免重复与膨胀
- 保持 FAIL-OPEN：LLM 不可用时 syntheses 生成降级跳过，不影响编译主流程

## Non-Goals
- 不实现跨源聚合 syntheses（多 source 引用触发聚合留待后续）
- 不修改 polling_trader 交易热路径
- 不修改认知系统核心代码
- 不实现 syntheses 页面的人工审核工作流

## Functional Requirements

- **FR-1**: ingest() 编译时，在 entities/concepts 生成后、index 更新前，新增 syntheses 页面生成步骤
- **FR-2**: syntheses 页面内容包含：主题概述、关联实体列表（[[wikilink]]）、关联概念列表（[[wikilink]]）、交叉分析、来源溯源
- **FR-3**: syntheses 页面写入 `2-KNOWLEDGE/wiki/syntheses/` 目录，使用 `_build_frontmatter()` 构建 YAML frontmatter（type=synthesis）
- **FR-4**: CompileResult 增加 `synthesis_page` 字段记录生成的 syntheses 页面文件名
- **FR-5**: wiki_query 增加 `enable_write_back` 参数（默认 true），检索后由 LLM 评估结果综合价值（0-1 分）
- **FR-6**: 综合价值 ≥0.6 阈值时，将查询主题 + 检索结果综合生成一篇 syntheses 页面并写入知识库
- **FR-7**: syntheses 写入前执行冲突检测：目标文件已存在时用 difflib.SequenceMatcher 计算内容相似度，>0.7 跳过，≤0.7 覆盖更新
- **FR-8**: LLM 不可用时 syntheses 生成与 Query 回写均降级跳过，返回 status=degraded

## Non-Functional Requirements

- **NFR-1 (FAIL-OPEN)**: syntheses 生成失败或 LLM 不可用时不阻塞 ingest/query 主流程
- **NFR-2 (不侵入)**: 不修改现有 sources/entities/concepts 生成逻辑，仅新增步骤
- **NFR-3 (可追溯)**: syntheses 页面 frontmatter 的 sources 字段溯源到原始素材
- **NFR-4 (幂等)**: 同一素材重复编译，syntheses 页面内容稳定（确定性生成或相似度跳过）

## Constraints
- **Technical**: 复用现有 DeepSeekLLMClient、_build_frontmatter()、_kebab_case()、wiki 目录结构
- **Business**: syntheses 只记录综合分析（≤800字），不复制 source 全文，避免知识库膨胀
- **Dependencies**: 依赖 `2-KNOWLEDGE/9-RAG-INFRA/evolution/wiki_compiler.py`、`1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py` 的 wiki_query IPC 方法

## Assumptions
- 现有 _extract() 返回的 entities/concepts/core_conclusion 足够支撑 syntheses 生成
- LLM 客户端可支持两次连续调用（提取 + syntheses 生成）
- difflib 相似度检测对中文文本有效

## Acceptance Criteria

### AC-1: ingest 生成 syntheses 页面
- **Type**: `rule`
- **Given**: 调用 ingest(素材) 且 LLM 可用
- **When**: 编译完成
- **Then**: `2-KNOWLEDGE/wiki/syntheses/` 下新增 ≥1 个 .md 文件，frontmatter type=synthesis，含 ≥2 个 [[wikilink]]
- **Pass Condition**: syntheses/ 目录新增文件，文件含 type: synthesis 和实体/概念交叉引用
- **Evidence**: 检查文件系统 + 文件内容

### AC-2: CompileResult 含 synthesis_page
- **Type**: `rule`
- **Given**: ingest 成功生成 syntheses
- **When**: 读取 CompileResult
- **Then**: result.synthesis_page 非空，指向 syntheses/ 下的文件名
- **Pass Condition**: synthesis_page 字段有值
- **Evidence**: 单元测试输出

### AC-3: wiki_query 回写 syntheses
- **Type**: `rule`
- **Given**: wiki_query 返回结果且 LLM 判定综合价值 ≥0.6
- **When**: 查询完成
- **Then**: syntheses/ 下新增以查询主题命名的 .md 文件
- **Pass Condition**: 高价值查询后 syntheses/ 新增对应页面
- **Evidence**: 文件系统检查

### AC-4: 冲突检测（相似度跳过）
- **Type**: `rule`
- **Given**: syntheses/ 下已存在同名页面且内容相似度 >0.7
- **When**: 再次写入同主题 syntheses
- **Then**: 跳过写入，不覆盖已有文件
- **Pass Condition**: 已有文件内容不变
- **Evidence**: 文件内容对比

### AC-5: 冲突检测（低相似度覆盖）
- **Type**: `rule`
- **Given**: syntheses/ 下已存在同名页面且内容相似度 ≤0.7
- **When**: 再次写入同主题 syntheses
- **Then**: 覆盖更新已有文件
- **Pass Condition**: 文件内容更新为新版本
- **Evidence**: 文件内容对比

### AC-6: LLM 不可用时降级
- **Type**: `rule`
- **Given**: LLM 客户端不可用
- **When**: 调用 ingest 或 wiki_query
- **Then**: syntheses 生成/回写跳过，返回 status=degraded，不抛异常
- **Pass Condition**: 降级返回，无异常
- **Evidence**: 无 API key 时的调用结果

### AC-7: syntheses 页面规范性
- **Type**: `rubric`
- **Dimension**: syntheses 页面的 frontmatter 完整性与交叉引用覆盖
- **Scale**: 1-5
- **Anchors**: 1 = 无 frontmatter 无交叉引用；3 = 有 frontmatter 基础交叉引用；5 = frontmatter 完整 + 实体/概念 [[wikilink]] 全覆盖 + source 溯源
- **Pass Threshold**: >= 4
- **Evidence**: 抽样检查生成的 syntheses 页面

### AC-8: Query 回写价值判定准确性
- **Type**: `rubric`
- **Dimension**: LLM 价值判定对低价值查询的过滤效果
- **Scale**: 1-5
- **Anchors**: 1 = 所有查询都回写（无过滤）；3 = 部分过滤但阈值不合理；5 = 高价值查询回写、低价值查询跳过，阈值合理
- **Pass Threshold**: >= 4
- **Evidence**: 多组查询测试的回写行为

## Open Questions
- [ ] syntheses 页面的综合价值阈值 0.6 是否合理？需通过实测调整
- [ ] Query 回写的 syntheses 是否需要区别于 ingest 生成的 syntheses（如 type=synthesis-query）？

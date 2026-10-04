# Wiki 编译层系统关系修复 SPEC

> **日期**：2026-09-24
> **版本**：v1.0
> **状态**：待审阅
> **来源**：Wiki 编译层系统关系调研 + 4 维交叉验证
> **5 维评分**：8.6 / 10

---

## 一、背景与问题陈述

### 1.1 背景

dreambuddy-v2 已实现基于 **Karpathy LLM Wiki Gist 模式** 的知识编译层（`wiki_compiler.py`），通过 DSH Harness plugin（`cordis-plugin-knowledge-wiki`）暴露 `wiki_ingest` / `wiki_query` / `wiki_lint` 三个工具，实现"素材→结构化 Wiki 页面→RAG 索引→认知记忆"的完整编译链路。

### 1.2 问题

调研发现 Wiki 编译层与项目文档治理体系、认知系统、doc-sync 工作流之间存在 **5 个系统关系缺口**：

| # | 缺口 | 严重度 | 影响 |
|---|------|:---:|------|
| F1 | 主 profile (web) 未挂载 Wiki plugin | 中 | web 端 Agent 无法调用 wiki_ingest/query/lint，能力仅 headless 可用 |
| F2 | Wiki 页面不被 doc_lint / link_checker 覆盖 | 中 | Wiki 成为文档治理盲区，命名/链接质量无门禁 |
| F3 | Wiki 不被 dream-doc-sync-workflow 路由 | 低 | Wiki 索引变更不会触发 doc-sync 同步 |
| F4 | 认知→Wiki 无反向触发 | 低 | 认知经验无法自动编译为 Wiki 页面，知识单向流动 |
| F5 | Wiki 未纳入 2-KNOWLEDGE 总 INDEX | 低 | wiki/ 是知识库"隐藏"子目录，不在总索引中体现 |

### 1.3 约束

| 约束 | 说明 |
|------|------|
| HC-1a | 不修改 4-MEMORY/dreamos 核心代码 |
| HC-9 | 只做编排，不做交易决策 |
| FAIL-OPEN | 任何异常降级，不阻塞主流程 |
| 零回归 | 现有测试全部通过 |
| 模块化开关 | 新增能力必须可独立关断 |

---

## 二、4 维调研结论

### 2.1 实际代码需求（已完成）

| 组件 | 路径 | 关键发现 |
|------|------|---------|
| doc_lint.py | `0-系统文档管理/4-工具与自动化/` | 扫描目标目录所有 .md；`IGNORED_DIRS` 不含 wiki；命名规则为"大写+下划线"，Wiki 的 kebab-case 会产生 false positive |
| doc_coverage.py | 同上 | 仅扫描 `NN-*/` 子系统 + L3_MODULES，检查 5 文档标准；Wiki 不适用此标准，**不应纳入** |
| link_checker.py | 同上 | 提取 markdown 链接 `[text](path)`；Wiki 用 `[[wikilink]]` 语法，LINK_RE 无法匹配；可检查 Wiki 中的 markdown 外链 |
| wiki_compiler.py | `2-KNOWLEDGE/9-RAG-INFRA/evolution/` | ingest 后调用 `build_index(_KNOWLEDGE_DIR)` 同步 RAG；`_record_to_cognitive()` 写入认知记忆（source=wiki-compiler） |
| 主 profile | `.dsh-home/profiles/web/package.json` | bundles 仅 dsh-base/dsh-web-app/browser-skill，**无 wiki plugin** |
| headless profile | `dream-harness-bridge/.dsh-home/profiles/headless/` | 通过 `file:../../../packages/cordis-plugin-knowledge-wiki` 引用，cordis.patch.yml 中 enabled: true |
| 2-KNOWLEDGE/INDEX.md | `2-KNOWLEDGE/` | 目录结构列 1-TRADING~8-AI-COGNITION，**无 wiki/**；进度表无 wiki 条目 |

### 2.2 模块化模式（已完成）

- Wiki plugin 挂载复用 headless profile 的 `file:` 引用模式 + cordis.patch.yml 启用模式
- doc-sync 域路由复用 dream-doc-sync-workflow 的"路径前缀→domain→INDEX"映射模式
- 认知 hook 复用已落地的 `TAG_HOOKS` 字典模式（doc-sync→dream-doc-sync-workflow）

### 2.3 传统金融 / github 代码

不适用——本修复为工程架构整合，非金融/算法问题。

---

## 三、修复方案设计

### F1：主 profile 挂载 Wiki plugin（P0）

**问题**：web 端 Agent 无法调用 wiki_ingest/query/lint。

**设计**：在主 profile 中复用 headless 的挂载模式。

**改动清单**：

| 文件 | 改动 |
|------|------|
| `.dsh-home/profiles/web/package.json` | dependencies 新增 `"dreambuddy-knowledge-wiki": "file:../../1-ARCHITECTURE/dream-harness-bridge/packages/cordis-plugin-knowledge-wiki"` |
| `.dsh-home/profiles/web/cordis.patch.yml` | 新增 plugin 启用配置（复用 headless 的 `dreambuddy-knowledge-wiki` 配置块） |

**cordis.patch.yml 配置块**（复用 headless）：

```yaml
plugins:
  dreambuddy-knowledge-wiki:
    enabled: true
    pythonEntry: ../1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py
    methods:
      - wiki_ingest
      - wiki_ingest_batch
      - wiki_query
      - wiki_lint
    timeoutMs: 90000
```

**验收标准**：
- web profile 启动后，`wiki_ingest` / `wiki_query` / `wiki_lint` 工具可调用
- 调用 wiki_ingest 成功编译一个测试素材，返回 pages > 0
- headless profile 不受影响（回归验证）

**FAIL-OPEN**：plugin 加载失败时，DSH 启动不崩溃，wiki 工具不可用但其他工具正常。

---

### F2：Wiki 纳入 doc_lint / link_checker 覆盖（P1）

**问题**：Wiki 页面命名/链接质量无门禁。

**设计**：

**doc_lint**：
- 扩展 `IGNORED_DIRS` 不变（wiki 不在忽略列表）
- 新增 `WIKI_NAMING_SKIP` 规则：路径含 `2-KNOWLEDGE/wiki/` 时，跳过"大写+下划线"命名检查（Wiki 用 kebab-case）
- 保留版本头检查、禁止命名检查、README/INDEX 并存检查

**link_checker**：
- 扩展 `LINK_RE` 或新增 `WIKILINK_RE` 支持 `[[wikilink]]` 语法校验
- `[[wikilink]]` 校验逻辑：将 `[[target]]` 解析为 `2-KNOWLEDGE/wiki/<target>.md`，检查文件是否存在
- 保留原 markdown 链接校验逻辑不变

**改动清单**：

| 文件 | 改动 |
|------|------|
| `doc_lint.py` | 新增 `WIKI_PATH_RE = re.compile(r'2-KNOWLEDGE/wiki/')`；命名检查时若路径匹配则跳过 UPPER_UNDERSCORE 检查 |
| `link_checker.py` | 新增 `WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')`；`extract_links` 中同时提取 wikilink；`resolve_link` 中对 wikilink 目标拼接 wiki 目录路径 |

**验收标准**：
- `python doc_lint.py 2-KNOWLEDGE/wiki` 不报 kebab-case 命名违规（仅报真实违规）
- `python link_checker.py 2-KNOWLEDGE/wiki` 能检测到断链的 `[[wikilink]]`
- 现有 doc_lint/link_checker 测试零回归

**FAIL-OPEN**：wikilink 解析异常时跳过该链接，不中断整体扫描。

**不纳入 doc_coverage**：Wiki 不适用 5 文档标准（README/ENGINEERING_INDEX/...），强行纳入会产生大量无意义的"缺失"项。

---

### F3：Wiki 纳入 dream-doc-sync 域路由（P1）

**问题**：Wiki 页面变更不会触发 doc-sync 同步。

**设计**：在 dream-doc-sync-workflow 的域路由表中新增 `wiki` 域，路由到 `2-KNOWLEDGE/wiki/index.md`。

**关键约束**：`wiki/index.md` 由编译器自动维护页面列表，doc-sync **只更新元数据区**（如最后同步时间、页面统计），不修改编译器维护的页面列表区。

**改动清单**：

| 文件 | 改动 |
|------|------|
| `.trae/skills/dream-doc-sync-workflow/SKILL.md` | 域路由表新增 `2-KNOWLEDGE/wiki/` → domain=wiki → `2-KNOWLEDGE/wiki/index.md` |
| `1-ARCHITECTURE/skills/dream-doc-sync-workflow/SKILL.md` | 同步更新 |

**wiki/index.md 元数据区约定**：

```markdown
<!-- doc-sync-meta-start -->
> 最后同步：2026-09-24 | 页面数：22 | 来源：dream-doc-sync-workflow
<!-- doc-sync-meta-end -->
```

doc-sync 只替换 `<!-- doc-sync-meta-start -->` 和 `<!-- doc-sync-meta-end -->` 之间的内容。

**验收标准**：
- doc-sync 处理 `2-KNOWLEDGE/wiki/` 路径变更时，domain 判定为 wiki
- 更新 wiki/index.md 时只修改元数据区，不破坏编译器维护的页面列表
- 双位置 SKILL.md 内容一致

---

### F4：认知→Wiki 反向触发（P2，可选）

**问题**：认知经验无法自动编译为 Wiki 页面。

**设计**：复用认知 `TAG_HOOKS` 模式，新增 `wiki-compile` tag → 触发 wiki_ingest。

**但有一个关键限制**：认知系统只能发信号（`triggered_skills`），不能直接调用 wiki_ingest（需 DSH IPC）。实际触发链路为：

```
record(tags含"wiki-compile")
    → triggered_skills: ["wiki-ingest-trigger"]
    → 上层 Agent 识别信号
    → Agent 调用 wiki_ingest(content=经验内容, source="cognitive-memory")
```

**改动清单**：

| 文件 | 改动 |
|------|------|
| `cognitive_mcp_server.py` | `TAG_HOOKS` 新增 `"wiki-compile": "wiki-ingest-trigger"` |
| `dream-doc-sync-workflow/SKILL.md`（或新建轻量触发说明） | 说明 wiki-compile tag 的触发链路 |

**注意**：此修复点为 P2 可选，因为：
1. 认知经验质量参差不齐，自动编译可能产生低质量 Wiki 页面
2. 需要 Agent 主动介入判断是否值得编译
3. 当前 Wiki→认知单向已满足主要需求

**验收标准**（若实施）：
- record tags 含 `wiki-compile` 时，返回值包含 `triggered_skills: ["wiki-ingest-trigger"]`
- 不影响现有 doc-sync hook

---

### F5：Wiki 纳入 2-KNOWLEDGE 总 INDEX（P1）

**问题**：wiki/ 不在 2-KNOWLEDGE/INDEX.md 中体现。

**设计**：在 2-KNOWLEDGE/INDEX.md 的目录结构和进度表中补充 wiki/。

**改动清单**：

| 文件 | 改动 |
|------|------|
| `2-KNOWLEDGE/INDEX.md` | 目录结构新增 `├── wiki/ # AI 编译知识网络（自动维护）`；进度表新增 `\| wiki \| 22 \| ✅ 编译器自动维护 \|` |

**验收标准**：
- 2-KNOWLEDGE/INDEX.md 目录结构包含 wiki/ 条目
- 进度表包含 wiki 统计行
- 不修改 wiki/ 下的任何文件

---

## 四、交叉验证

### 4.1 5 维评分

| 维度 | 评分 | 说明 |
|------|:---:|------|
| 完整性 | 9/10 | 5 个修复点全覆盖，实际代码需求维已深度调研 |
| 可落地性 | 9/10 | 每个修复点给出文件级改动清单 + 验收标准 |
| 工程适配性 | 8/10 | 复用现有模式（file: 引用、TAG_HOOKS、域路由），FAIL-OPEN 合规 |
| 风险识别 | 8/10 | 识别 false positive、编译器维护区冲突、认知经验质量等风险 |
| 创新性 | 7/10 | 主要是整合现有能力，无重大创新 |
| **综合** | **8.2/10** | |

### 4.2 矛盾项清单

| 矛盾项 | 立场 A | 立场 B | 倾向结论 |
|--------|--------|--------|---------|
| Wiki 是否纳入 doc_coverage | 纳入可统一治理 | Wiki 不适用 5 文档标准，会产生噪音 | **不纳入**（F2 设计已排除） |
| doc-sync 是否修改 wiki/index.md | 应统一索引 | 编译器自动维护页面列表，手动修改会冲突 | **只改元数据区**（F3 设计） |
| 认知→Wiki 是否自动触发 | 自动闭环更智能 | 认知经验质量参差，自动编译可能降质 | **P2 可选，Agent 判断**（F4 设计） |

---

## 五、风险与待验证

| 风险 | 等级 | 缓解措施 |
|------|:---:|---------|
| F1: web profile 挂载 wiki plugin 后启动冲突 | 中 | 先在 headless 已验证的配置复用，启动后验证 25 个 IPC 方法全链路 |
| F2: doc_lint 扩展引入回归 | 中 | 新增 WIKI_PATH_RE 判断，仅影响 wiki 路径，现有测试全跑 |
| F2: link_checker 的 wikilink 解析遗漏边缘 case | 低 | wikilink 格式统一（`[[target]]`），解析逻辑简单 |
| F3: doc-sync 修改 wiki/index.md 破坏编译器维护区 | 中 | 用 `<!-- doc-sync-meta-start/end -->` 锚点限定修改范围 |
| F4: 认知经验自动编译产生低质量 Wiki | 低 | P2 可选，默认不开启，由 Agent 判断 |

**待验证**：
1. F1：web profile 挂载后 wiki_ingest 是否能正常调用 python-server（路径相对关系需验证）
2. F2：link_checker 对 `[[wikilink]]` 的锚点（`[[target#section]]`）处理
3. F3：wiki/index.md 编译器重写时是否会覆盖 doc-sync-meta 区

---

## 六、实施优先级与里程碑

| 优先级 | 修复点 | 预计工作量 | 依赖 |
|:---:|------|:---:|------|
| P0 | F1 主 profile 挂载 Wiki plugin | 0.5d | 无 |
| P1 | F5 Wiki 纳入 2-KNOWLEDGE 总 INDEX | 0.2d | 无 |
| P1 | F2 Wiki 纳入 doc_lint/link_checker | 1d | 无 |
| P1 | F3 Wiki 纳入 doc-sync 域路由 | 0.5d | F2 |
| P2 | F4 认知→Wiki 反向触发（可选） | 0.5d | F1 |

**建议实施顺序**：F1 → F5 → F2 → F3 → (F4)

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-09-24 | 初始版本，5 个修复点 + 4 维调研 + 交叉验证 + 优先级 |

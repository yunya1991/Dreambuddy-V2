# SPEC — 41-文件索引系统

> **版本**: v0.9 (2026-10-22)
> **状态**: 完整版（P0/P1 项全部闭环；v0.6 存储层迁移 PostgreSQL；v0.7 补充 Dream OS SACG 对接设计；v0.8 补充 L0/L1/L2 能力分层架构归属与对接设计；v0.9 补充 DSH 子 Agent 体系与 Wiki 编译层协同设计）
> **定位**: dreambuddy 的文件系统层通用索引底座（不做业务语义组织）
> **上游关联**: 前端搜索优化方案（3.1-FRONTEND/docs/前端搜索优化方案.md）
> **变更记录**:
> - v0.2 补充『与既有模块的边界与互补』章节（基于 2026-10-21 系统内模块调研）
> - v0.3 补充『与 2-KNOWLEDGE 案例库』『与中信建投三层体系借鉴』两节；L2 索引引入语义分块
> - v0.4 按系统完整性清单闭环全部 P0 项：C1 中文分词方案 / C2 schema 版本管理 / C3 并发写入模式 / A1 部署形态 / M1 两段式链路语义澄清 / M2 TDR 豁免条款
> - v0.5 按系统完整性清单闭环全部 P1 项：C4 增量触发机制决断 / C5 权限模型细化 / C6 可观测性与测试计划章节 / A2 分块兜底策略细化
> - v0.6 存储层由 SQLite 迁移至 PostgreSQL（复用 dreambuddy-pg 容器，独立 fis 数据库）：§4.1 存储设计重写（连接池/MVCC 并发写/schema 版本管理），同步修订 §1.3/§3.1/§3.2/§7.5/§9/§11 相关引用
> - v0.7 基于 Dream OS SACG 系统调研（2026-10-22），新增 §7.9『与 Dream OS SACG 系统的边界与增强』、§5.6 L1 文件清单查询接口，细化 §10 实施路线 P2/P3，补充 §11 风险对策
> - v0.8 基于 L0/L1/L2 能力分层架构调研（2026-10-22，34 号模块 SPEC v1.3），新增 §7.10『与 L0/L1/L2 能力分层架构的归属与对接』：固化 41 归属 L0、L1 doc_search 意图封装、fetchContext/settle 对接设计，细化 §10 实施路线 P2，补充 §11 风险对策
> - v0.9 基于 DSH 子 Agent 体系与 Wiki 编译层调研（2026-10-22），新增 §7.11『与 DSH 子 Agent 体系及 Wiki 编译层的协同』：固化 wiki 豁免定性、wiki 页面纳入索引范围（§6 同步修订）、DSH 节点文件定位供给与素材召回设计，补充 §11 风险对策

---

## 0. 文档定位

本文档定义 **41-文件索引系统** 的完整设计规格。它承接前端搜索优化方案的阶段二/三诉求，为全项目提供统一的文件/文档索引构建、增量更新与检索能力，作为前端全局搜索、Agent 代码检索、文档管理的统一索引底座。

核心价值：**给调用方一个查询词，返回带来源证据的文件/文档命中结果，支撑『搜得到、跳得转、可追溯』。**

**职责边界声明**：本系统是**文件系统层的通用索引底座**（元数据 + 全文倒排 + 预留语义索引），不承担业务语义组织（产物关系链路、投递路由、view-model 装配等职责归 7-产物中台），也不做 Q-Learning 语义精排（归案例库检索链路）。详见第 7 章。

---

## 1. 背景与动机

### 1.1 问题

dreambuddy 当前面临以下检索痛点：

- 前端仅报告页有 taskId 精确匹配，无全局搜索入口（见前端搜索优化方案现状分析）
- 项目模块已达 40+ 个，文档/报告/策略/记忆分散在各模块目录，人工翻找成本高
- Agent（DSH 链路）需要检索工程文件时，只能逐目录遍历，效率低且不可复用
- 后端 case-retriever 检索能力未与文件/文档检索打通

### 1.2 现有方案的不足

| 方案 | 不足 |
|---|---|
| 文件系统遍历 | 每次全量扫描，慢且无相关性排序 |
| 前端内存索引 | 数据量增长后内存膨胀，多端不共享 |
| 直接引入 Meilisearch | 当前数据规模下运维成本偏高，应作为演进选项 |

### 1.3 设计目标

1. **统一索引底座**：一次构建，多端消费（前端全局搜索、Agent 检索、文档管理）
2. **增量更新**：基于 mtime/hash 的变更检测，避免全量重建
3. **Evidence-First**：每条命中结果带来源（路径+行号/片段+得分），与 33-REA 工程哲学一致
4. **轻量可控**：Python 原生实现，PostgreSQL 存储（复用既有 dreambuddy-pg 实例，独立 fis 数据库），零新增重型运维面
5. **可演进**：预留 Meilisearch/向量检索适配器接口，对齐中信建投三层融合体系（见 7.7）

---

## 2. 核心设计哲学

### 2.1 Evidence-First（证据优先）

每条检索结果必须包含：

- **source**: 来源（文件路径、行号或片段定位）
- **score**: 相关性得分（0.0-1.0）
- **snippet**: 命中上下文片段
- **indexed_at**: 索引时间戳（判断新鲜度）

### 2.2 分层索引

| 层级 | 内容 | 更新频率 |
|---|---|---|
| L1 元数据索引 | 路径/文件名/类型/mtime/size | 按需惰性校验 + 每小时定时对账（见 2.3） |
| L2 内容索引 | 标题/摘要/正文分词（倒排，语义分块） | 变更时增量 |
| L3 语义索引（预留） | 向量嵌入 | 按需构建 |

**L2 语义分块要求（v0.5 闭环 A2，三级兜底策略）**：

分块边界优先级：
1. **标题层级**（首选）：markdown 标题（#/##/###）作为块边界
2. **空行段落**（次选）：无标题文档按连续空行分隔的段落切分
3. **固定行数窗口**（兜底）：无结构文本按 256 行窗口切分，窗口间重叠 16 行（保证跨窗口语义连续）

代码文件分块规则：按函数/类定义行切分，正则识别 `def /class /function /export /const xxx = (`；单块超过 512 行时再按 256 行窗口二次切分。

禁止固定 token 长度机械切分——该经验来自中信建投知识库体系（15 万文档规模验证，见 7.7）。

**L2 分词方案（v0.4 闭环 C1）**：

- 默认分词器：**jieba 精确模式**（中文）
- 英文：空白分隔 + 驼峰拆分（camelCase / PascalCase）
- 归一化：全部小写；全角/半角统一；去除停用词（内置中英文停用词表）
- 分词器接口可替换（预留 HanLP 适配位），分词逻辑独立于 chunker

### 2.3 增量触发机制（v0.5 闭环 C4）

决断为**『按需惰性校验 + 定时对账兜底』**，不引入 fs 事件监听（watchdog 依赖与跨平台成本高于收益）：

| 机制 | 触发时机 | 行为 | 耗时预算 |
|---|---|---|---|
| 惰性校验 | 每次 search/recall 调用前 | mtime 快速比对索引范围内文件，变更文件触发增量更新 | <10ms/千文件（仅 stat，不读内容） |
| 定时对账 | 每小时（cron/launchd） | 全量 mtime+hash 对账，修复惰性校验遗漏（如重命名） | 全量对账 <60s（万文件级） |

- 惰性校验超预算（>50ms）时降级为跳过校验直接检索，差异留给定时对账修复
- 对账结果写入 status() 的对账差异输出

---

## 3. 系统架构

```
41-文件索引系统/
├── SPEC-文件索引系统.md        # 本文档
├── 系统完整性清单.md            # 修订执行依据与验收清单
├── core/
│   ├── scanner.py              # 文件扫描器（遍历+过滤规则）
│   ├── chunker.py              # 语义分块器（三级兜底：标题>段落>窗口）
│   ├── tokenizer.py            # 分词器（jieba 精确模式，接口可替换）
│   ├── indexer.py              # 索引构建（L1/L2）
│   ├── incremental.py          # 增量更新（惰性校验+定时对账）
│   └── searcher.py             # 检索引擎（倒排匹配+打分，BM25 式召回）
├── adapters/
│   ├── meilisearch_adapter.py  # Meilisearch 适配器（预留）
│   └── vector_adapter.py       # 向量检索适配器（预留，对齐中信建投向量化层）
├── api/
│   └── search_api.py           # 统一检索接口（Python 库直调 + Next.js API Route 封装）
├── config/
│   └── index_rules.yaml        # 索引范围/排除规则
├── scripts/
│   ├── rebuild_index.py        # 全量重建入口
│   └── reconcile_cron.py       # 每小时定时对账入口
└── tests/
```

### 3.1 数据流

```
文件系统 → scanner（过滤）→ chunker（语义分块）→ tokenizer（分词）→ indexer（倒排）→ PostgreSQL 索引库（fis）
                                                                                ↓
前端全局搜索 / Agent 检索 / 案例库补充候选 ← search_api（打分+片段） ← searcher
```

### 3.2 部署形态（v0.4 闭环 A1）

双形态，不独立部署 Python HTTP 服务：

| 消费方 | 接入方式 | 说明 |
|---|---|---|
| 内部 Agent / 脚本 / 7 号中台 | Python 库直调（进程内 import） | 零网络开销，无新增运维面 |
| 前端（3.1-FRONTEND） | Next.js API Route 封装 search_api | 前端不直连 PostgreSQL，经 API Route 代理 |

---

## 4. 数据结构

### 4.1 索引存储（PostgreSQL，v0.6 迁移）

**存储实例约定**：复用既有 dreambuddy-pg 容器（postgres:16-alpine，127.0.0.1:5432），创建独立数据库 **fis**（与 dreambuddy/data_center 业务库隔离）；连接参数经环境变量注入（FIS_PG_HOST/FIS_PG_PORT/FIS_PG_DB/FIS_PG_USER/FIS_PG_PASSWORD），密码不落盘明文。

**并发写入模式（v0.6 修订，替代 v0.4 C3 的 SQLite 单写队列）**：PostgreSQL MVCC 天然支持并发读写，v0.4 的 WAL 模式/单写队列/busy_timeout/跨进程 .lock 文件锁机制**全部废止**；写操作改为事务级隔离（写事务内先删后插，事务提交原子生效）；连接统一经连接池（psycopg_pool，进程内池化，min=1/max=10）；读操作并发无限制。

**schema 版本管理（v0.4 闭环 C2，v0.6 适配 PostgreSQL）**：meta 表记录 schema_version；search_api 初始化时校验版本——不兼容版本触发自动全量重建（rebuild），重建在事务内 TRUNCATE 后重导，失败自动回滚（替代 SQLite 的 .bak 文件保留机制）；兼容版本走增量迁移（ALTER TABLE / DDL 事务）；status() 返回 schema_version。

表结构：

- **meta** 表：key, value（含 schema_version）
- **files** 表：id, path, type, mtime, size, hash, indexed_at
- **chunks** 表：id, file_id, heading, position, boundary_kind（heading/paragraph/window/code，v0.5 新增）
- **tokens** 表：token, chunk_id, positions, tf
- **documents** 表：file_id, title, summary, lang

### 4.2 检索结果结构

```json
{
  "query": "搜索词",
  "hits": [
    {
      "source": {"path": "...", "line": 12},
      "score": 0.87,
      "snippet": "...命中上下文...",
      "type": "report|strategy|memory|doc|code|case",
      "indexed_at": "2026-10-21T22:00:00Z"
    }
  ],
  "total": 42,
  "took_ms": 18
}
```

---

## 5. 接口设计

### 5.1 统一检索接口

```
search(query, filters?, limit=20) -> SearchResult
```

- **filters**: 按类型（报告/策略/记忆/文档/代码/案例）、模块、时间范围过滤
- **limit**: 默认 20，上限 100

### 5.2 索引管理接口

```
rebuild(scope?) -> Stats        # 全量重建（schema 不兼容时自动触发）
update(paths) -> Stats          # 增量更新
status() -> IndexStatus         # 索引健康度（文件数/新鲜度/耗时/对账差异/schema_version）
```

### 5.3 与前端的对接

- 前端通过 Next.js API Route 代理调用 search_api（部署形态见 3.2）
- 结果结构与前端搜索优化方案 3.2 阶段二的 /api/search 对齐

### 5.4 候选召回接口（供案例库精排）

```
recall(query, topK=50) -> Chunk[]   # BM25 式候选召回，供 case-retriever 补充候选注入
```

### 5.5 权限模型（v0.5 闭环 C5）

调用方分两类，过滤在 search_api 入口统一执行，索引层不过滤：

| 调用方 | 身份来源 | 可见范围 | 凭证机制 |
|---|---|---|---|
| 前端用户 | NextAuth 会话（API Route 层解析后传入 user_id） | 按用户可见范围过滤（私有报告/策略仅本人，公开内容全员） | 会话 Cookie（NextAuth 既有机制） |
| 内部 Agent | DSH 链路调用凭证 | 全量可见 | 内部凭证：环境变量 FIS_AGENT_TOKEN，Bearer 方式传递，进程内直调可豁免 |

- 凭证校验失败 → 返回 401 语义错误（degraded 模式返回空结果并记录日志，不抛异常，对齐 case-bank-client FAIL-OPEN 原则）
- 可见范围规则表存 config/index_rules.yaml 的 visibility 段，与索引范围规则同文件维护

### 5.6 L1 文件清单查询接口（v0.7 新增，供 SACG DocIndexView 消费）

```
list_files(root?, type?, category?) -> FileList   # L1 元数据清单查询（files 表）
```

- **用途**：替代 SACG /api/docs/index 的实时 rglob 扫描（每次请求 spawn Python 进程 + 全量扫描，秒级耗时），切换为 PostgreSQL 索引查询（毫秒级）
- **参数**：root（根目录名过滤，如 0-系统文档管理/2-KNOWLEDGE）、type（doc/memory/case 等类型过滤）、category（SACG 分类，由 type + 路径推导）
- **返回**：path/root/category/last_synced(=indexed_at)/size_bytes，字段结构与 SACG DocItem 对齐，前端零改造切换
- **降级**：41 不可达时 SACG 路由回退原有实时扫描（FAIL-OPEN，见 §7.9）

---

## 6. 索引范围与规则（初始）

| 范围 | 类型标记 |
|---|---|
| 各模块 SPEC/README/docs（*.md） | doc |
| 报告产物（reports/、artifacts/） | report |
| 策略定义与配置 | strategy |
| 记忆/案例库条目（含 2-KNOWLEDGE/5-CASE-STUDY） | memory / case |
| Wiki 知识网络页面（2-KNOWLEDGE/wiki/**/*.md，v0.9 新增） | wiki |
| 源码（*.py/*.ts/*.tsx，仅元数据+标题级） | code |

排除：node_modules、.git、__pycache__、.next、日志、二进制文件。

---

## 7. 与既有模块的边界与互补

> 本章基于 2026-10-21 对系统内既有索引/检索类模块的调研，固化职责划界，防止实施时职责漂移。

### 7.1 与 7-产物中台（冲突最高，需划界）

- **重叠点**：7 号中台承担『统一索引、组织、检索系统研究沉淀的产物』职责，且有可运行的 Next.js 实现（系统研究索引体系）。本系统 report/strategy 类型索引与其存在重叠风险。
- **划界**：
  - 7-产物中台管**业务层**：产物的组织、关系链路、投递路由、view-model 装配
  - 41-文件索引系统管**文件系统层**：通用元数据 + 全文倒排索引底座
  - 7 的检索请求可下沉到 41 的 search_api（Python 库直调，见 3.2），避免两套全文索引并行维护

### 7.2 与 0-系统文档管理（中度重叠，转化为对账互补）

- **重叠点**：0 号系统的 INDEX.md 是全项目文档索引（机器可读目录树），与本系统 L1 元数据索引覆盖同一批文档，存在双份索引不一致风险。
- **互补约定**：
  - 0 的 INDEX.md 是人工维护的 SSoT（回答『在哪找』），本系统是自动构建的检索索引（回答『搜什么』）
  - 本系统将 INDEX.md 作为权威数据源校验基准，索引新鲜度对账以 0 为准
  - status() 增加与 INDEX.md 的对账差异输出

### 7.3 与 4-MEMORY（无实质冲突，天然互补）

- 4 号是 AI 上下文索引（蒸馏摘要，面向 Agent），本系统是文件级全文索引（面向检索），不同层。
- **互补链路**：4 的记忆条目作为本系统 memory 类型数据源；本系统的检索能力为 4 的记忆召回提供底座，形成『文件检索 → 记忆命中 → 上下文注入』链路。

### 7.4 与 24-图结构上下文压缩（无冲突，互补明确）

- 24 号面向 LLM 上下文的图压缩检索，与文件检索不同域。
- **互补约定**：24 压缩后的图节点可注册进本系统预留的 L3 语义索引；本系统的检索结果可作为 24 的上下文召回来源。

### 7.5 与 38-数据库管理系统（无冲突，需协调）

- 本系统使用 PostgreSQL（dreambuddy-pg 实例，独立 fis 数据库）存储索引库，纳入 38 的冷热分层与归档治理：索引库属热数据；冷数据降级为 L1 元数据索引（VACUUM/归档策略由 38 统一治理）。

### 7.6 与 2-KNOWLEDGE 案例库（补充注入式两段链路）

案例库索引系统由三部分组成，与本系统划界如下：

- **知识层**：`2-KNOWLEDGE/5-CASE-STUDY`（精选深度案例，人工维护 INDEX.md 表格索引，dream-doc-sync-workflow 自动对齐巡检）+ `1-TRADING/cases/`（自动化标准案例库）。
- **运行时层**：前端 `case-bank-client.ts`（TDR 训练数据仓库，独立 SQLite 库 solution_case_bank.db）+ `case-retriever.ts`（Memento 架构 Soft Q-Learning 五因子精排：codebook 匹配度/语义相似度/质量权重/成功率/时间衰减）。
- **划界与互补**：
  - 案例库是**语义级检索**（embedding + Q-Learning 排序），本系统是**文件级全文检索**，不同层
  - 本系统**不做** Q-Learning 精排（归案例库），只做 BM25 式候选召回（recall 接口，见 5.4）
  - **两段式链路语义（v0.4 闭环 M1，澄清为补充注入）**：CaseBankClient.retrieve 仍为案例库**主候选源**（结构化 TDR 记录）；本系统 recall() 的结果（案例文档 md 命中）作为**补充候选**注入精排池，**不替代主链路**；两路候选在 Soft Q 打分前合并去重（按案例 id / 文档路径）
  - 5-CASE-STUDY 的案例文档纳入本系统 case 类型索引范围（见第 6 章）

### 7.7 与中信建投三层体系借鉴（演进对齐）

> 依据：`2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/risk-models/中信建投知识库管理体系调研.md`（RAG + 向量检索 + 知识图谱三层融合，15 万文档规模验证，幻觉率 38% → 4-7%）

- **架构对齐**：中信建投三层融合（RAG 层 / 向量检索层 / 知识图谱层）中，本系统 L2 对应其『全文检索』通道，L3 对应其『向量检索层』；知识图谱层不在本系统职责内（图结构归 24 号模块）。
- **吸收的经验**：
  - **语义分块**：L2 索引采用语义分块（非固定 token 切分），chunker.py 承担该职责
  - **多路召回 + 重排**：本系统提供 BM25 式召回通道，与案例库语义精排组成补充注入式两段链路（见 7.6），对齐其『多路召回+重排序』第二代 RAG 模式
  - **持续进化闭环**：索引新鲜度对账（与 0 号 INDEX.md）+ 增量更新，对齐其『采集→清洗→标注→索引→反馈→进化』闭环
- **演进约束**：L3 向量层实施时直接参考其六层技术模型（数据接入→语义分块→向量化→混合存储→多路召回→生成），避免重复调研。

### 7.8 总体数据流约定

```
文件系统 → 41（通用索引底座）→ 各业务模块（0/4/7/案例库）消费检索能力
```

- 各业务模块保留业务索引，统一消费 41 的检索能力，形成单向数据流
- **禁止范围精确定义（v0.4 闭环 M2）**：禁止业务模块**对文件系统文档构建第二份全文倒排索引**；以下场景豁免——
  - **TDR 豁免**：solution_case_bank.db 属**结构化业务数据存储**（案例记录的存取与统计），非全文索引，不在禁止范围
  - 业务模块自持的语义精排（Q-Learning/embedding 重排）不属全文索引，不在禁止范围
- 语义精排由各业务模块自持，41 只到召回为止

### 7.9 与 Dream OS SACG 系统（v0.7 新增，基于 2026-10-22 调研）

> 依据：3.1-FRONTEND/docs/v3-frontend-architecture.md（SACG 四层架构口径）+ /api/docs/index、doc_index_adapter.py、/api/skills/index 源码调研

**SACG 系统现状**：WorkBuddy OS 新 SACG 四层架构（S=认知驱动规划入口 / A=OKR 节点验收 / C=执行驱动 / G=压缩沉淀），前端 3.1-FRONTEND 独立端口 3001 部署。与索引相关的三个子系统：文档索引（/api/docs/index + DocIndexView，实时 rglob 扫描 .md 清单）、文档同步（/api/docs/sync → 认知库 record，生成 memory_id）、技能索引（/api/skills/index，技能生命周期状态）。前端目前无全局搜索路由（仅 /api/cognitive/recall 认知召回）。

**冲突定性：低（无架构性冲突，存在性能性重叠）**：

- SACG 文档索引是**实时目录清单**（无倒排索引/无分词/无全文检索），不属 §7.8 禁止的『第二份全文倒排索引』，与 TDR 豁免同类
- 但 SACG 每次请求全量 rglob 扫描与 41 的 L1 元数据索引覆盖同一批文件（0-系统文档管理 + 2-KNOWLEDGE 均在 41 索引范围内），形成**双份元数据来源**，且 spawn 开销随文件量增长成为瓶颈

**增强方案（P2 对接设计）**：

1. **DocIndexView 数据源切换**：/api/docs/index 从实时扫描改为调用 41 的 list_files 接口（§5.6），扫描耗时从秒级降至毫秒级；SACG 的 category 字段由 41 的 type + 路径推导，返回字段结构对齐 DocItem，前端零改造
2. **FAIL-OPEN 回退**：41 不可达时 SACG 路由回退原有实时扫描（保留 doc_index_adapter.py 作为降级路径），对齐 case-bank-client FAIL-OPEN 原则
3. **cognitive_linked 链路保留**：/api/docs/sync 的认知库 record 链路（memory_id 标记）不受影响——41 只替代『扫描』环节，不替代『认知沉淀』环节，与 §7.3（4-MEMORY 互补）划界一致
4. **全局搜索新建 /api/search**：按前端搜索优化方案阶段二设计，Next.js API Route 封装 41 的 search_api，补齐前端无全局搜索入口的缺口；NextAuth 会话解析 user_id，权限过滤对齐 §5.5
5. **recall 补充注入（P3）**：case-retriever 精排池接入 41 的 recall()（BM25 式召回），按案例 id/文档路径合并去重，不替代 CaseBankClient 主链路（对齐 §7.6）
6. **对账基准统一**：SACG 文档索引的 last_synced 与 41 的 indexed_at 对齐，status() 的 reconcile_diff 作为 SACG 记忆管理页新鲜度展示来源（对齐 §7.2 以 0 号 INDEX.md 为 SSoT 基准）

### 7.10 与 L0/L1/L2 能力分层架构（v0.8 新增，基于 2026-10-22 调研）

> 依据：34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md（分层原则/L0 三支柱/接口契约）+ 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md（C3 路由层/Agentic RAG）

**架构现状**：前端能力分层按『是否依赖大模型』划分——L0 基础能力层（数据库系统/广义认知系统/逆向工程三支柱，零 token 双向层）、L1 基础智能层（10 意图零 token 秒级，意图注册表+路由器+置信度门控）、L2 大模型驱动层（DreamOS C 层+DSH+子 Agent）。L0 经 fetchContext（工作前取数）/settle（工作后沉淀，按案例/认知/流程/文档四路分流）被 L1/L2 调用，不直接对外路由。

**层归属（主体唯一·形态可降级）**：41 是确定性文件检索（零 token、本地倒排+BM25），按判据『确定性+本地检索→L1 层级能力；组件归属→L0 供给』，**41 唯一归属 L0**，作为 L0 的文档/知识检索供给组件；其检索能力以**降级形态**封装为 L1 意图对外（doc_search，见下）——形态可降级，归属始终唯一。

**冲突定性：低（无架构性冲突）**：

- 41 的 fis 库与 18-数据获取中心 data_center 库同在 dreambuddy-pg 实例，纳入 38 统一治理（§7.5 已有约定）
- L1 意图注册表、Intent-Engine 召回均为意图级路由，非文件全文索引，与 41 不同域，不违反 §7.8 M2 禁令
- L1 暂缓清单第 8 项（REA 工程分析）若未来扩展源码文本检索，应下沉到 41 的 code 类型索引，避免业务模块自建文件检索

**对接设计（六项增强）**：

1. **L1 doc_search 意图封装**：41 的 search 是零 token 确定性检索，完全符合 L1 判据——在 L1 意图注册表新增 doc_search 意图（数据来源标注 41-文件索引系统），补齐 L1 十意图中缺失的文档检索能力；与 /api/search 路由同入口实施（意图注册表消费）
2. **fetchContext 的 docs scope 提供者**：L0 接口规范落地（阶段二/三）时，41 的 recall() 作为 fetchContext 文档 scope 的实现——L1/L2 工作前从 41 召回相关 SPEC/文档片段作为上下文输入，对齐『L1 确定性结论作为 L2 推理的上下文输入』
3. **settle 文档沉淀链路自动化**：settle 分流中『文档沉淀』目前依赖人工触发——41 的增量更新（惰性校验+定时对账）自动感知文档变化并刷新索引，形成『文档变更 → 41 自动重索引 → 0 号 INDEX.md 对账』闭环
4. **C3 路由层召回增强**：Intent-Engine 加权召回当前基于认知库记忆——41 的 recall()（BM25 式）作为其文档通道补充召回源（合并去重，不替代主链路，对齐 §7.6 补充注入模式）
5. **L2 Agentic RAG 文档通道**：C-drive 的 Agentic RAG（fast-path/SKILL 调研）需要文档检索底座——41 的 search/recall 直接作为其 RAG 检索通道，避免 L2 自建文件遍历
6. **置信度门控信号补强**：C4 元认知门控（FOK/JOL）评估『用户问题↔认知库』匹配度——41 的检索命中数（文档命中密度）作为辅助信号维度，零成本增强路由质量

### 7.11 与 DSH 子 Agent 体系及 Wiki 编译层（v0.9 新增，基于 2026-10-22 调研）

> 依据：34 号模块 SPEC-DSH-训练数据源 v0.4/v0.5（采集器族与决策序列格式）+ 33-REA dsh_nodes.py（8 节点 IPC 契约）+ 2-KNOWLEDGE/wiki/AGENTS.md（编译层理念与页面规范）

**两大体系现状**：

- **DSH 架构（执行路径训练层）**：L2 层执行路径骨架——各模块封装 DSH 节点函数（stdin NDJSON IPC 契约，如 33-REA 提供 rea_analyze/rea_trace/rea_compare 等 8 节点）；训练数据源 9 个采集器从 TDD 测试文件（AST 解析）、.cognitive/sessions 会话、6-TRADING A0-A9 交易哲学资产中提取 task→node_sequence→outcome 决策序列
- **Wiki 编译层（2-KNOWLEDGE/wiki）**：核心理念『提取时编译，而非查询时检索』——素材摄入时编译为结构化交叉引用知识网络（四类页面：sources/entities/concepts/syntheses，YAML frontmatter + [[双链]] + lint 校验），查询时直接基于已编译网络回答

**冲突定性：低（无架构性冲突，存在协同空位）**：

- **Wiki 豁免定性**：wiki 是 LLM 编译的**结构化知识网络**（实体/概念/综合页），非文件系统全文倒排索引——与 TDR 豁免同类，属『业务模块自持语义组织』，不在 §7.8 M2 禁止范围
- **DSH 采集器豁免**：采集器做 AST 解析与结构化提取（决策序列），非全文检索，不在禁止范围
- **重叠点一**：wiki 的 index.md（目录页）与 41 的 L1 元数据覆盖同一批 wiki 页面文件——但 wiki index 是编译层目录页（含双链语义），41 是文件级检索，粒度不同，互补大于冲突
- **重叠点二**：DSH 子 Agent（如 rea_trace）需定位源码文件，当前各自实现文件遍历——41 的 code 类型索引可供给，且 DSH 节点是静态分析（AST/依赖图）非文本检索，不构成索引冲突

**协同设计（六项增强）**：

1. **Wiki 页面纳入索引范围**：wiki 四类页面（.md）纳入 41 索引范围并标记新类型 **wiki**（§6 已同步修订）——41 提供文件级全文检索，wiki 编译层提供结构化知识网络，形成『41 搜文件 → wiki 页面命中 → 双链跳转知识网络』两级检索体验
2. **Wiki lint 对账联动**：wiki 的 lint-reports（交叉引用校验）与 41 的定时对账联动——41 检测 wiki 页面变更（mtime/hash）后可触发 lint 重跑提示，status() 的 reconcile_diff 增加 wiki 页面维度
3. **DSH 子 Agent 文件定位供给**：DSH 节点函数（如 rea_trace/rea_investigate）需按功能名定位相关源码文件——41 的 search（code 类型过滤）作为其前置文件定位通道，替代各节点自建目录遍历；进程内直调形态（§3.2）零开销接入
4. **DSH 训练数据源素材召回**：v0.5 采集器（6-TRADING session/大师研讨/做梦部日志）需按主题召回相关素材——41 的 recall()（BM25 式）作为采集器的素材预筛通道，降低 LLM 辅助解析的 token 成本
5. **Wiki 编译层素材发现**：wiki 编译新素材时需发现已有相关页面建立交叉引用——41 的 search 供给『相关页面候选』（按素材主题检索 wiki 页面），降低编译层全量扫描成本
6. **DSH node_sequence 的 Evidence 溯源**：33-REA 节点输出带 Evidence（provenance+confidence）——41 的检索结果（source.path+line）作为 DSH 决策序列节点的 provenance 来源之一，对齐 Evidence-First 哲学

---

## 8. 可观测性（v0.5 闭环 C6）

### 8.1 索引健康度指标

| 指标 | 来源 | 暴露方式 |
|---|---|---|
| indexed_files | files 表计数 | status() 输出 |
| index_freshness | 最近对账时间与差异文件数 | status() 输出 |
| reconcile_diff | 与 0 号 INDEX.md 对账差异 | status() 输出 |
| search_p95_ms | 检索耗时 P95（滑动窗口 1000 次） | status() 输出 + 日志 |
| recall_p95_ms | 召回耗时 P95 | status() 输出 + 日志 |
| schema_version | meta 表 | status() 输出 |

### 8.2 日志

- 结构化日志（JSON 行），写入模块 logs/ 目录
- 级别：INFO（索引更新/对账结果）、WARN（惰性校验超预算降级）、ERROR（凭证校验失败/schema 不兼容重建）
- 日志按天滚动，保留 14 天

---

## 9. 测试计划（v0.5 闭环 C6）

沿用工程 pytest 体系（Python 侧）+ Jest 体系（前端对接层）：

| 层级 | 覆盖内容 | 关键用例 |
|---|---|---|
| 单元测试 | chunker 三级兜底分块 | 有标题/无标题纯文本/超长代码文件/窗口重叠边界 |
| 单元测试 | tokenizer 分词 | 中英混合/驼峰/全角半角/停用词 |
| 单元测试 | searcher 打分 | BM25 排序正确性/类型过滤/limit 截断 |
| 单元测试 | 权限过滤 | 前端用户私有内容不可见/Agent 凭证校验/FAIL-OPEN 降级 |
| 集成测试 | 增量更新 | mtime 变更触发/重命名靠对账修复/惰性校验超预算降级 |
| 集成测试 | schema 迁移 | 版本不匹配自动重建/事务回滚保护/兼容版本增量迁移 |
| 集成测试 | 并发 | 多读多写并发/连接池耗尽降级/事务原子性 |
| 集成测试 | 对账 | 与 0 号 INDEX.md 差异输出 |
| 端到端 | 案例库补充注入链路 | recall 结果注入精排池/合并去重/主链路不受影响 |

验收基线：全部测试通过率 100%，核心路径（分块/分词/检索/权限）行覆盖率 ≥ 85%。

---

## 10. 实施路线

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | scanner + L1 元数据索引 + 基础检索 | 全项目文件可按名检索，<100ms |
| P1 | chunker 语义分块 + tokenizer 分词 + L2 内容倒排索引 + 增量更新 + search_api | 全文检索可用，变更文件 5s 内可检索 |
| P2 | 前端对接（v0.7/v0.8 细化，见 §7.9/§7.10）：① 41 侧 list_files 接口（§5.6）→ ② SACG /api/docs/index 数据源切换（含 FAIL-OPEN 回退）→ ③ 新建 /api/search 全局搜索路由（NextAuth 会话 + 权限过滤）+ L1 doc_search 意图注册（同入口，见 §7.10）→ ④ 前端全局搜索 UI（Cmd+K 入口 + 类型过滤） | SACG 文档清单毫秒级返回；前端全局搜索走本系统；L1 doc_search 意图零 token 可用 |
| P3 | recall 候选召回接口 + 案例库补充注入链路对接（case-retriever 精排池接入 recall()，按案例 id/文档路径合并去重，不替代主链路） | 案例库精排补充候选来自 41 召回，主链路不受影响 |
| P4 | 与 7-产物中台检索下沉对接 + 与 0 号 INDEX.md 对账 | 单一全文索引源，对账差异可查询 |
| P5 | Meilisearch/向量适配器（按需，对齐中信建投六层模型） | 数据量超阈值或语义检索需求触发 |

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 索引与文件不一致 | mtime+hash 双重校验，status() 暴露新鲜度 |
| 索引库膨胀 | PostgreSQL 分表+定期 VACUUM，冷数据降级为 L1 |
| 检索越权 | search_api 层按调用方身份过滤（权限模型见 5.5） |
| 与 7-产物中台职责漂移 | 以第 7 章划界为准，业务语义组织归 7，索引底座归 41 |
| 与 0 号 INDEX.md 双份索引不一致 | 对账机制以 0 为 SSoT 基准（见 7.2） |
| 与案例库检索链路混淆 | 41 只做召回不做精排，补充注入语义以 7.6 为准 |
| 语义分块质量不稳定 | 三级兜底策略（标题>段落>窗口）+ 窗口重叠 16 行；单测覆盖分块边界用例 |
| schema 升级数据丢失 | 版本校验 + 事务内重建自动回滚（见 4.1） |
| 并发写冲突 | MVCC 事务隔离 + 连接池（见 4.1） |
| PostgreSQL 连接失败 | 连接池重试 + FAIL-OPEN 降级返回空结果并记日志（对齐 5.5） |
| jieba 分词效果不达预期 | 分词器接口可替换，预留 HanLP 适配位（见 2.2） |
| 惰性校验拖慢检索 | 超预算（>50ms）降级跳过，差异由定时对账修复（见 2.3） |
| Agent 凭证泄露 | FIS_AGENT_TOKEN 仅环境变量注入，不写入代码与日志 |
| SACG 双份元数据来源不一致 | P2 数据源切换后以 41 files 表为单一来源；切换期保留实时扫描降级（见 §7.9） |
| SACG 切换期 41 不可达 | FAIL-OPEN 回退 doc_index_adapter.py 实时扫描，功能不中断（见 §7.9） |
| L1/L2 层职责漂移 | 41 归属 L0 供给层，L1 仅以 doc_search 意图消费；层归属以 §7.10『主体唯一·形态可降级』为准 |
| fetchContext/settle 对接期 41 不可达 | FAIL-OPEN 渐进可用（对齐 L0 无大模型降级原则），缺 docs scope 不阻塞 L1/L2 主链路 |
| Wiki/DSH 职责漂移 | wiki 编译层自持语义组织、DSH 采集器自持结构化提取，均不属全文索引（§7.11 豁免定性）；41 只做文件级检索供给 |
| wiki 页面高频变更导致索引抖动 | 增量更新按 mtime+hash 双重校验仅重索引变更页；lint 联动仅提示不阻塞（§7.11） |

---

## 12. 参考

- 33-REA逆向解析工程 SPEC（Evidence-First 哲学与文档格式）
- 3.1-FRONTEND/docs/前端搜索优化方案.md（上游需求）
- 0-系统文档管理 / 4-MEMORY / 7-产物中台 / 24-图结构上下文压缩 / 38-数据库管理系统 各模块 README（边界调研依据）
- 2-KNOWLEDGE/5-CASE-STUDY/INDEX.md + 3.1-FRONTEND/src/lib/case-bank-client.ts / case-retriever.ts（案例库调研依据）
- 2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/risk-models/中信建投知识库管理体系调研.md（三层融合体系借鉴依据）
- 系统完整性清单.md（v0.4/v0.5 修订执行依据）
- Meilisearch / Typesense 官方文档（演进选型依据）

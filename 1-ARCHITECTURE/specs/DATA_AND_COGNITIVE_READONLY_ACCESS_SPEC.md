# 基础数据 + 大认知系统只读访问层 SPEC

> **版本**: v1.0
> **日期**: 2026-10-10
> **状态**: 待评审
> **关联**: COGNITIVE_SYSTEM_INTEGRATION_SPEC, ARCH_OPTIMIZATION_INDUSTRY_BENCHMARK_SPEC

---

## 1. 背景与目标

### 1.1 问题陈述

当前 DreamOS 大模型分析存在两个核心缺陷：

1. **数据依赖子系统**：大模型无法直接访问基础市场数据（资金费率、链上指标、宏观数据），只能依赖子系统输出。当子系统输出简陋时，LLM 无法生成高质量分析。
2. **认知能力未消费**：大认知系统（认知/SKILL/知识库/索引）的只读能力未被大模型直接利用，导致"越用越聪明"的优势无法体现。

### 1.2 目标

- **大模型直接访问基础数据**：通过统一只读 API 层，大模型在分析前可并行拉取所需市场/链上/宏观数据，注入 prompt。
- **大认知系统只读消费**：大模型可直接检索认知记忆、SKILL 索引、知识库、文档索引，增强分析深度。
- **安全边界**：前端+大模型只读，写入严格走后端工作流。

### 1.3 架构原则

| 原则 | 说明 |
|------|------|
| 数据分层 | 18-数据获取中心（采集）→ 19-数据访问层（Protocol）→ /api/data/*（只读API）→ 大模型 |
| 只读优先 | 大模型+前端只准读，写入必须走后端工作流（skill/knowledge-ingest/auto_sync） |
| 统一网关 | 所有访问通过 Next.js API Route，不直接暴露底层存储 |
| FAIL-OPEN | API 失败时降级返回空数据+degraded 标记，不阻塞主流程 |

---

## 2. 系统架构

### 2.1 整体分层

```
┌─────────────────────────────────────────────────────────┐
│                      大模型 (LLM)                         │
│         分析前并行拉取数据 → 注入 prompt → 生成分析          │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
    ┌──────────▼──────────┐   ┌───────────▼───────────┐
    │  /api/data/*        │   │  /api/cognitive/*     │
    │  基础数据只读API     │   │  大认知系统只读API      │
    │  (市场/链上/宏观)    │   │  (认知/SKILL/知识/索引) │
    └──────────┬──────────┘   └───────────┬───────────┘
               │                          │
    ┌──────────▼──────────┐   ┌───────────▼───────────┐
    │  19-数据访问层       │   │  MCP Server / Adapter  │
    │  Protocols:          │   │  - cognitive_mcp       │
    │  MarketMacroRepo     │   │  - skill_index_adapter │
    │  KnowledgeGraphRepo  │   │  - knowledge RAG       │
    └──────────┬──────────┘   └───────────┬───────────┘
               │                          │
    ┌──────────▼──────────┐   ┌───────────▼───────────┐
    │  18-数据获取中心     │   │  4-MEMORY / 2-KNOWLEDGE │
    │  采集器+SQLite       │   │  skills/ / INDEX.md    │
    └─────────────────────┘   └───────────────────────┘
```

### 2.2 读写边界

| 系统 | 读（前端+LLM可直接） | 写（必须走流程） |
|------|---------------------|-----------------|
| 基础数据 | ✅ query_* / get_* | ❌ upsert_*（仅18-数据获取中心） |
| 认知系统 | ✅ recall / stats / health | ❌ record / verify（后端工作流） |
| SKILL系统 | ✅ list / query / search | ❌ register / update（skill-creator） |
| 知识库 | ✅ search / retrieve | ❌ ingest / vectorize（knowledge-ingest） |
| 索引系统 | ✅ search / list | ❌ update（auto_sync_dispatcher） |

---

## 3. API 设计

### 3.1 基础数据只读 API（/api/data/*）

#### 3.1.1 /api/data/market — 市场数据

**GET** 查询指定标的的市场指标集合。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 标的，如 BTC-USDT |
| metrics | string | 否 | 逗号分隔指标列表，默认全部 |

**响应**:
```json
{
  "symbol": "BTC-USDT",
  "price": 67150.5,
  "funding_rate": 0.0001,
  "open_interest": 12500000000,
  "liquidation_24h": { "long": 5000000, "short": 3000000 },
  "fear_greed": 72,
  "fear_greed_classification": "Greed",
  "timestamp": "2026-10-10T08:30:00Z",
  "source": "okx",
  "degraded": false
}
```

**可用 metrics**: price, funding_rate, open_interest, liquidation, fear_greed

#### 3.1.2 /api/data/chain — 链上数据

**GET** 查询指定标的的链上指标。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 标的 |
| metrics | string | 否 | 指标列表 |

**响应**:
```json
{
  "symbol": "BTC",
  "active_addresses_24h": 1200000,
  "large_transfers_24h": 45,
  "exchange_inflow_24h": 8000,
  "exchange_outflow_24h": 9500,
  "timestamp": "...",
  "source": "glassnode",
  "degraded": false
}
```

#### 3.1.3 /api/data/macro — 宏观数据

**GET** 查询宏观经济指标。

**响应**:
```json
{
  "dxy": 104.5,
  "us10y_yield": 4.25,
  "vix": 18.3,
  "gold": 2650.8,
  "sp500": 5800.5,
  "timestamp": "...",
  "degraded": false
}
```

### 3.2 大认知系统只读 API（/api/cognitive/*）

> 注：认知系统 API 已有 `/api/cognitive/recall`、`/api/skills/index`、`/api/docs/index`。本 SPEC 补充缺失的知识库检索和统一查询。

#### 3.2.1 /api/cognitive/knowledge — 知识库检索

**GET** 向量检索+全文检索知识库。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 检索 query |
| top_k | int | 否 | 默认 5 |
| method | string | 否 | vector / fts / hybrid，默认 hybrid |

**响应**:
```json
{
  "results": [
    { "content": "...", "score": 0.85, "source": "2-KNOWLEDGE/...", "chunk_id": "..." }
  ],
  "method": "hybrid",
  "degraded": false
}
```

#### 3.2.2 /api/cognitive/unified — 统一认知查询

**GET** 一次性查询认知记忆+SKILL+知识库+索引。

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 查询文本 |
| top_k | int | 否 | 每个系统默认 3 |
| systems | string | 否 | cognitive,skill,knowledge,index，默认全部 |

**响应**:
```json
{
  "cognitive": [{ "content": "...", "score": 0.8 }],
  "skills": [{ "id": "...", "name": "...", "score": 0.75 }],
  "knowledge": [{ "content": "...", "score": 0.7 }],
  "index": [{ "path": "...", "title": "...", "score": 0.65 }],
  "degraded": false
}
```

---

## 4. 大模型数据注入机制

### 4.1 注入时机

在 `task-manager.ts` 的 `executeTask` 中，**LLM 汇总前**并行拉取：

```
executeTask()
  ├─ 子系统执行（已有）
  ├─ fetchMarketData()（已有，价格）
  ├─ fetchMarketMetrics()  ← 新增：资金费率/持仓/爆仓/恐惧贪婪
  ├─ fetchChainMetrics()   ← 新增：链上指标
  ├─ fetchMacroData()      ← 新增：宏观指标
  ├─ fetchCognitiveContext() ← 新增：认知记忆+SKILL+知识库
  └─ 构建 LLM prompt（注入以上数据）
```

### 4.2 注入格式

```markdown
--- 实时市场数据（直接注入）---
当前价格: $67,150 | 24h涨跌: +2.35%
资金费率: 0.01% | 持仓量: $12.5B | 24h爆仓: 多$5M/空$3M
恐惧贪婪: 72 (贪婪)

--- 链上数据 ---
活跃地址: 1.2M | 大额转账: 45笔 | 交易所净流出: +1500 BTC

--- 宏观环境 ---
DXY: 104.5 | 美债10Y: 4.25% | VIX: 18.3 | 黄金: $2,650

--- 认知记忆（相关历史经验）---
[VM-xxx] BTC突破前高后通常有15-20%回调...
[VM-yyy] 恐惧贪婪>70时追多胜率仅45%...

--- 相关 SKILL ---
dream-screen1-first: 入场条件验证...
dream-risk-position-sizing: 仓位风控...
```

### 4.3 effort_level 路由

| effort | 数据注入范围 |
|--------|------------|
| light | 仅价格 |
| standard | 价格 + 市场指标 |
| deep | 价格 + 市场 + 链上 + 宏观 + 认知记忆 |

---

## 5. 数据访问层 Protocols 扩展

### 5.1 现有 Protocols（复用）

| Protocol | 用途 | 只读方法 |
|----------|------|---------|
| MarketMacroRepository | 市场+宏观 | query_funding_by_time, query_open_interest_by_time, query_fear_greed_by_time |
| KnowledgeGraphRepository | 知识图谱 | fts_search_entities, query_subgraph_by_entity |

### 5.2 新增 Protocols（19-数据访问层）

#### CognitiveRepository（认知系统只读）
```python
class CognitiveRepository(ABC):
    @abstractmethod
    def recall(self, context: str, top_k: int, min_quality: str) -> List[dict]: ...
    @abstractmethod
    def stats(self) -> dict: ...
    @abstractmethod
    def health(self) -> dict: ...
```

#### SkillRepository（SKILL只读）
```python
class SkillRepository(ABC):
    @abstractmethod
    def list_skills(self, category: str = None) -> List[dict]: ...
    @abstractmethod
    def search_skills(self, query: str, top_k: int) -> List[dict]: ...
    @abstractmethod
    def get_skill(self, skill_id: str) -> dict: ...
```

#### KnowledgeRepository（知识库只读）
```python
class KnowledgeRepository(ABC):
    @abstractmethod
    def vector_search(self, query: str, top_k: int) -> List[dict]: ...
    @abstractmethod
    def fts_search(self, query: str, top_k: int) -> List[dict]: ...
    @abstractmethod
    def hybrid_search(self, query: str, top_k: int) -> List[dict]: ...
```

---

## 6. 安全与权限

### 6.1 只读强制

- 所有 `/api/data/*` 和 `/api/cognitive/*`（除已有 record/verify）只允许 GET
- POST/PUT/DELETE 返回 405 Method Not Allowed
- 后端调用 19-数据访问层时只调用 query_* 方法，不调用 upsert_*

### 6.2 写入流程

| 写入操作 | 触发方式 | 执行路径 |
|---------|---------|---------|
| 认知 record/verify | 后端工作流 | cognitive_mcp_server.py（前端不可直接调用） |
| SKILL 注册 | skill-creator SKILL | auto_sync_dispatcher.py |
| 知识入库 | knowledge-ingest SKILL | build_index.py |
| 索引更新 | git commit | post-commit hook |

### 6.3 限流与缓存

- 每个 API 端点 100 req/min（IP 级）
- 市场数据缓存 10s，链上数据缓存 60s，宏观数据缓存 300s
- 认知查询缓存 5s

---

## 7. 实施计划

### P0（核心闭环）
1. **/api/data/market** — 复用 MarketMacroRepository，暴露资金费率/持仓/爆仓/恐惧贪婪
2. **大模型注入** — task-manager.ts 在 deep 模式下拉取市场指标并注入 prompt

### P1（认知消费）
3. **/api/cognitive/knowledge** — 知识库向量+全文检索
4. **/api/cognitive/unified** — 统一认知查询
5. **大模型认知注入** — deep 模式下注入相关认知记忆+SKILL

### P2（完善）
6. **/api/data/chain** — 链上数据 API
7. **/api/data/macro** — 宏观数据 API
8. **19-数据访问层 Protocols** — 新增 CognitiveRepository/SkillRepository/KnowledgeRepository

---

## 8. 验收标准

| ID | 验收项 | 通过条件 |
|----|--------|---------|
| F1 | /api/data/market 返回真实数据 | 调用返回 OKX 真实资金费率/持仓/爆仓数据 |
| F2 | 大模型分析引用市场指标 | LLM 输出包含资金费率/恐惧贪婪等具体数值 |
| F3 | /api/cognitive/knowledge 可检索 | 返回知识库相关 chunk |
| F4 | deep 模式注入认知记忆 | LLM 输入包含 recall 返回的相关记忆 |
| F5 | 只读强制 | POST /api/data/market 返回 405 |
| F6 | FAIL-OPEN | 数据源不可用时返回 degraded:true 不阻塞 |
| F7 | 缓存生效 | 10s 内重复请求命中缓存 |

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 18-数据获取中心数据不全 | FAIL-OPEN 返回空+degraded，LLM 标注数据不足 |
| 大模型 prompt 过长 | 按 effort_level 裁剪，deep 模式限制总 token |
| 认知检索不相关 | 提升 top_k 阈值，只返回 score>0.5 的结果 |
| API 性能 | 并行拉取+缓存，单端点超时 3s |

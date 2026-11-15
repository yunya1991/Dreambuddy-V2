# REVIEW — 残差记忆准入与遗忘治理（SPEC v0.4 评审）

> **评审日期**: 2026-11-16
> **被评审**: [SPEC-ResidualMemory-Admission.md](./SPEC-ResidualMemory-Admission.md) v0.4
> **评审方式**: 独立评审人（非作者）+ 作者复核关键证据
> **总判定**: **`APPROVE_WITH_CHANGES`** — 第一性原理与形态设计成立，但存在 3 个 P0 阻断，须先修订后开工
> **用户已定决策**: 向量库**保留但清空重建**（只留真实残差，几十到几百条），不继续维护 315K

---

## 0. 总评

方向判断（不可再推导准入 / 减记忆增能力 / 记忆树导航 / REA 为默认求解器）经独立评审认为**成立且优于原设计**。问题全部集中在**工程落地层**：三处会导致「治理看起来完成、实际双向失效」。

---

## 1. P0 阻断（不修不能开工）

### P0-1｜F-0 根因判断错误，修复落在错误位置

| 项 | 内容 |
|---|---|
| SPEC 原判断 | `record()` 只写主表、不维护向量索引 |
| **实际根因** | `record()` 经 `VectorMemoryInterface.add()`，engine=`sqlite_vec` 时**同事务写 vec 表**。真实根因是**引擎/向量化器静默降级**：写者进程 engine=numpy 时跳过 vec 写入（`vector_memory_interface.py:512-517` 仅 warning）；fastembed 加载失败时静默退化为哈希 256 维（`:298-306`） |
| 证据（作者复核 ✅） | `length(vector)` 分布：**2048 字节（512 维）314,310 条** / **1024 字节（256 维）1,188 条**；`meta.embed_dim=512`。本次新写的 4 条硬约束落在 256 维 → 与 512 维索引不匹配 → 0 条可检索 |
| 影响 | SPEC 的「record 同步写索引」是**空操作**；G0 仅校验 count 差，即使归零仍会因维度错配继续失联 |
| 修订要求 | ① engine / embed_model 不一致即 **fail-loud**，禁止静默降级；② 强制注入统一 `COGNITIVE_EMBED_MODEL`；③ 巡检从「count 差」升级为「`meta.embed_dim` 与 vector 长度直方图一致性」 |

**这是本次评审最重要的发现：F-0 不是「忘了写」，而是「写成了另一个维度」。**

### P0-2｜只清 vec 表不清 `memories.vector`，双路径必挂

| 项 | 内容 |
|---|---|
| 证据 | `_search_numpy` 全表扫描 `memories.vector`，**无 source 过滤**（`:782,801`）；维度不符者静默丢弃（`:811`）。当前 MCP 写者正是 numpy 路径 |
| 影响 | 清空 vec 表后，numpy 路径**仍会召回 `[RAG检索]`** → G2 必然 FAIL；反之 1,188 条真实记忆在 512 维路径永久不可见 → 「双向失效」未被消除 |
| 修订要求 | ① 强制单一 sqlite_vec 路径；② 归一 `memories.vector`（重嵌或置空）；③ **G2 断言必须覆盖两条检索路径** |

### P0-3｜无 recall 质量基线就一次性移出 30 万条（顺序倒置）

| 项 | 内容 |
|---|---|
| 证据 | SPEC §6 自认「有效命中率 / 现拆成功率 / p95 延迟 = 未统计」；P1 验收仅「trading query 无 `[RAG检索]`」；memory_tree 从 0 节点起步 |
| 影响 | 若 D0-D2 + 9,541 条不足，系统会**静默「什么都查不到」**；回滚需重建 31.5 万条向量 |
| 修订要求 | ① P0 先落 **20 条金标 query 基线**（命中率 / 延迟 / 内容正确性）；② 先 **10% 灰度移出**，观察后再全量 |

---

## 2. P1 应修（开工前完成）

| # | 问题 | 证据 | 建议动作 |
|---|---|---|---|
| P1-4 | **体量目标不成立** | `memories` 1,233 MB + vec 613 MB + freelist 1,190 MB；保留 315K 行与 vector 列，VACUUM 后仍约 1.2 GB | SPEC 写的「数十 MB」不可能达成。必须明确**冷存落点**（独立库/表）与目标字节，否则会滑向「删行」，违反「不删数据」原则 |
| P1-5 | **重建脚本与 P1 自相矛盾** | `rebuild_vector_index.py` 参数只有 `--db/--model/--batch-size/--threads/--limit/--swap`，**无 `--exclude-source`**（作者复核 ✅）；且 DROP→CREATE→INSERT 非事务（`:147-155`） | 会把你刚移出的噪音重新灌回；中途崩溃即 recall 全盲。需加排除参数 + **影子表原子切换** + 副本冒烟 |
| P1-6 | **容量假设「项目≤10」先破** | 顶层编号目录实测 **58 个**（作者复核 ✅），md 文件 10,154 个；10×12×3=150 节点覆盖率 <5% | 树节点应由**现有索引自动生成**，人工只维护 ≤150 个高频根节点 |
| P1-7 | **重复造轮子（三处）** | 已有 `0-系统文档管理/INDEX.md`(39KB)、`2-KNOWLEDGE/INDEX.md`、REA `graph_query.py`/`call_chain_tracer.py`/`incremental_index.py`、`rag_engine/keyword_search.py`(BM25+中文分词)；已有 `48-涌现架构/registry/capability_gaps.jsonl` + `capability_gaps.py`（open→claimed→resolved 状态机，`gap_audit`/`d2b_adapter` 已消费，作者复核 ✅） | `memory_tree.py` / `capability_gap_ledger.py` / `rea_routing_table.yaml` 全部改为**薄适配层**，禁止新建平行存储 |
| P1-8 | **指标不可验收** | 残差率需逐条「可再推导」标签，`memories` schema 无此字段；现拆成功率无起止埋点；级联分布无埋点（现有 SectionTelemetry 仅 section+hit） | G8 / G9 目前是**空指标**，需先加埋点或降级为「人工抽样」并写明 |
| P1-9 | **契约冲突** | 新增准入门与 C5「45 评测门禁」双门，优先级未定；§9 称「不改变 record 语义」但默认拒绝改变了可观察行为；C2b 主功能禁 FAIL-OPEN | 准入作为 C5 的 **pre-filter**，复用统一信封；清空后 recall 返回 0 命中必须置 `degraded` |
| P1-10 | **与用户决策不符** | 用户口径「只留几十到几百条」，而 G2 接受 ≤10,000、且只清 rag-bridge，仍保留 l0.scheduler / l1_router / mcp 约千条 + 988 条 D 级 | P1 改为**四残差白名单重建**，而不是 source 黑名单 |

---

## 3. P2 可接受

| # | 问题 | 建议 |
|---|---|---|
| P2-11 | P0 同时塞入 memory_tree 新架构层与关闸，1 天窗口不现实 | 拆为 **P0a（关闸 + 基线）** / **P0b（树）** |

---

## 4. 对我原方案的修正表

| 原方案 | 评审后 | 理由 |
|---|---|---|
| 「record 未写索引」→ 加同步写 | 「引擎静默降级 + 混维」→ **fail-loud + 维度巡检** | 实测 1,188 条 256 维，索引 512 维 |
| 清空 vec 表即完成瘦身 | 必须**双路径同时清** + 归一 vector 列 | `_search_numpy` 无 source 过滤 |
| 直接全量移出 305,930 条 | 先 **20 条金标基线 + 10% 灰度** | 否则回滚代价 31.5 万条 |
| 「数十 MB」 | 明确冷存落点与目标字节 | freelist 1,190 MB 不释放 |
| 新建 memory_tree / gap_ledger / routing | 改为**薄适配层**复用 `capability_gaps.jsonl` 与现有 INDEX / keyword_search | 重复造轮子 |
| 树 = 10×12×3 | 节点**自动生成** + 人工维护 ≤150 高频根节点 | 实测 58 个顶层目录 |
| P1 按 source 黑名单清 | 按**四残差白名单**重建 | 符合用户「只留几十到几百条」 |

---

## 5. 待用户裁定

| # | 决策点 | 选项 |
|---|---|---|
| D1 | 向量库定位 | A. 保留为 D2.5 兜底，清空重建（用户已倾向）｜B. 彻底退役 |
| D2 | 冷存落点 | A. 独立归档库 `cognitive_archive.db`｜B. 同库归档表 |
| D3 | 白名单重建范围 | A. 仅四残差（预计几十~几百条）｜B. 四残差 + A/B 级验证记忆（预计 <2,000 条） |
| D4 | 金标 query 由谁定 | A. 用户给 20 条｜B. 从 9,541 条反推 20 条高频场景 |
| D5 | 树节点自动生成 vs 人工 | A. 自动生成 + 人工维护 ≤150 根（评审推荐）｜B. 全人工 |

---

## 6. 下一步（待 D1-D5 裁定后执行）

1. 出 SPEC **v0.5**：修 P0-1~P0-3，落实 P1-4/5/8/10，`memory_tree` 改适配层。
2. 再评审一轮（只审 v0.5 的 diff，不重审全文）。
3. 通过后按 **P0a（fail-loud + 金标基线 + 关闸）→ P0b（树）→ P1（白名单重建）** 开工。

---

## 7. 二审结论（v0.5 → v0.6）

**判定：`APPROVE_WITH_CHANGES`**。一审 3 个 P0 的修正被确认成立；同时发现 **2 个新 P0**。

### 7.1 遗留 P1 逐项

| 编号 | 二审结论 | v0.6 处理 |
|---|---|---|
| P1-5 | 部分解决 | 已改为 `rebuild_vector_index.py` 增 `--source/--ids/--where` + `BEGIN IMMEDIATE` 包住 DROP→CREATE→INSERT（提为 P0） |
| P1-6 | 未解决 | 已改为「节点由现有索引自动生成 + 人工维护 ≤150 高频根」，删除「项目 ≤10」静态假设 |
| P1-7 | 未解决 | 已改为薄适配层 `capability_gap_adapter.py` 复用 `48-涌现架构/registry/capability_gaps.py` |
| P1-8 | 未解决 | 已补 §3.7「生效前置」：先加 `access_count`/`last_used_at` + recall 回写，否则 TTL 不启用 |
| P1-9 | 未解决 | **未关闭** — `degraded`/`ok=false` 与「准入作为 C5 pre-filter」留待 v0.7 |

### 7.2 新 P0

| 编号 | 问题 | 证据 | v0.6 处理 |
|---|---|---|---|
| **R1** | 升级路径不可达，7 天 TTL 会连真实教训一起删 | `memories` schema 无 `access_count`/`last_used_at`；`cognitive_loop_entry.py` 全文无 `UPDATE memories`；C 级占 97.9% 且 98.4% `verify_count=0` | 已修：§3.7 生效前置 1-2（先建字段+回写；未就绪前 TTL 只对 `rag-bridge/l0.scheduler/l1_router` 生效） |
| **R2** | 级联删除缺失，会产生 vec 孤儿 | `VectorMemoryInterface.delete:955-958` 仅 `engine=="sqlite_vec"` 时删 vec 行；`memory_ttl_manager` 无 DB 删除实现 | 已修：§3.7 生效前置 3-4（两阶段淘汰 + 统一经 `delete` 级联 + 变更后巡检） |

### 7.3 内部矛盾（已消除）

§3.7 原写「删除」，与 §2.2「遗忘=检索失败不擦除」、§5 P3「B 级及以上不自动衰减」直接冲突。v0.6 统一为：**两阶段（移出索引 → 宽限 7 天 → 物理删除 + 归档清单）**，P3 与 G2 措辞同步。

### 7.4 仍开放

- **P1-9**：`degraded`/`ok=false` 语义 + 准入与 C5 双门优先级 → v0.7
- **D2 冷存落点**：仍未裁定（影响 800MB 目标是否可达）

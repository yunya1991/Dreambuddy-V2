# 文档分类体系 — DOC_CLASSIFICATION

> **版本**: v1.0 | **更新日期**: 2026-07-25
> **定位**: 定义 DreamBuddy-V2 全项目文档的分级体系与角色分类
> **关联**: [DOC_STANDARD.md](./DOC_STANDARD.md)（规范）· [INDEX.md](../INDEX.md)（索引）

---

## 1. 文档分级体系（L0-L3）

DreamBuddy-V2 文档按影响范围分为 4 级：

```
L0 元文档层       — 管文档本身的文档（0-系统文档管理/）
    ↓
L1 顶层架构层     — 跨子系统的架构与治理文档
    ↓
L2 子系统层       — 单个子系统的完整文档集（docs/）
    ↓
L3 辅助模块层     — 实验性/辅助模块的文档
```

### 1.1 L0 — 元文档层

**定位**：管文档本身的文档，全项目文档体系的治理中枢。

**位置**：`0-系统文档管理/`

| 文档 | 职责 |
|------|------|
| README.md | 总入口 |
| INDEX.md | 全项目文档索引 |
| 1-规范体系/ | 文档编写规范、分类体系、模板 |
| 2-文档地图/ | 系统地图、主题地图、架构地图 |
| 3-文档治理/ | 生命周期、质量审计、文档债务 |
| 4-工具与自动化/ | 自动化校验工具 |

### 1.2 L1 — 顶层架构层

**定位**：跨子系统的架构设计、治理合规、知识体系。

**位置**：根目录的 `1-ARCHITECTURE/`、`2-GOVERNANCE/`、`2-KNOWLEDGE/`、`4-MEMORY/`、`5-BUSINESS/`、`6-TRADING/`、`3-FRONTEND/`

| 类型 | 示例 |
|------|------|
| 架构设计 | 1-ARCHITECTURE/README.md、SYSTEM_ARCHITECTURE_OVERVIEW.md |
| 治理合规 | 2-GOVERNANCE/GOVERNANCE_CHARTER.md |
| 知识库 | 2-KNOWLEDGE/INDEX.md 及子目录 |
| 系统设计 | 4-MEMORY/MEMORY_SYSTEM.md、6-TRADING/TRADING_SYSTEM.md |

### 1.3 L2 — 子系统层

**定位**：单个子系统的完整文档集，遵循 [DOC_STANDARD.md](./DOC_STANDARD.md) 规范。

**位置**：`NN-系统名称/docs/`

**强制文档**：
- ENGINEERING_INDEX.md — 工程索引
- TECHNICAL_DESIGN.md — 技术设计
- API_SPEC.md — 接口规格（有对外接口时）
- CHANGELOG.md — 变更日志
- README.md — 用户文档（在子系统根目录）

**当前 L2 子系统**：10、11、12、13、14、16 共 6 个。

### 1.4 L3 — 辅助模块层

**定位**：实验性、辅助性模块的文档，不强制遵循 L2 规范，但应有基本 README。

**当前 L3 模块**：3-EVOLUTION、6-图结构上下文压缩、7-产物中台、15-监控告警系统、experiments/、1-ARCHITECTURE/dreamos

---

## 2. 文档角色分类

按文档承担的角色分为 7 类：

| 角色 | 缩写 | 强制级别 | 模板 |
|------|------|----------|------|
| **工程索引** | IDX | L2 强制 | [ENGINEERING_INDEX_TEMPLATE.md](./TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md) |
| **技术设计** | TDD | L2 强制 | [TECHNICAL_DESIGN_TEMPLATE.md](./TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md) |
| **接口规格** | API | L2 有接口时强制 | [API_SPEC_TEMPLATE.md](./TEMPLATES/API_SPEC_TEMPLATE.md) |
| **变更日志** | CHG | L2 强制 | [CHANGELOG_TEMPLATE.md](./TEMPLATES/CHANGELOG_TEMPLATE.md) |
| **用户文档** | RDM | L2 强制 | [README_TEMPLATE.md](./TEMPLATES/README_TEMPLATE.md) |
| **运营文档** | OPS | 可选 | 无固定模板 |
| **知识文档** | KB | L1 | 无固定模板（见 2-KNOWLEDGE/） |

---

## 3. 命名规范

### 3.1 文件命名

| 类型 | 命名规则 | 示例 |
|------|---------|------|
| L0/L1 文档 | 大写+下划线 | `DOC_STANDARD.md`、`GOVERNANCE_CHARTER.md` |
| L2 强制文档 | 固定名 | `ENGINEERING_INDEX.md`、`TECHNICAL_DESIGN.md` |
| L2 用户文档 | 固定名 | `README.md` |
| L3 文档 | 自由命名但需清晰 | `SPEC.md`、`IMPLEMENTATION.md` |
| 知识库文档 | 中文标题 | `风控体系.md`、`三屏系统架构.md` |

### 3.2 禁止命名

- ❌ `技术文档2.0.md`（应为 `TECHNICAL_DESIGN.md`，版本号在文档头部）
- ❌ `新技术文档.md`、`最终版文档.md`（含主观形容词）
- ❌ `doc1.md`、`temp.md`（无意义命名）
- ❌ 同一目录下 `README.md` 和 `INDEX.md` 并存（二选一，L2 用 README，L1 用 INDEX）

---

## 4. 版本规范

### 4.1 文档版本号

所有 L0/L2 文档必须在头部标注版本：

```markdown
> **版本**: vX.X | **更新日期**: YYYY-MM-DD
```

- 主版本号（X）：重大结构变更
- 次版本号（X）：内容增补或修订

### 4.2 变更日志版本

CHANGELOG.md 的版本号应与对应文档版本保持同步：

```
## [v2.9] - 2026-07-25
### 新增
- **变更内容**: ...
```

---

## 5. 文档关系图

```
0-系统文档管理/（L0 元文档）
    │
    ├── 规范 → 约束 ──┐
    │                 ↓
    │           NN-子系统/docs/（L2 子系统文档）
    │                 │
    │                 ├── ENGINEERING_INDEX ← 引用 → 代码文件
    │                 ├── TECHNICAL_DESIGN ← 描述 → 架构
    │                 ├── API_SPEC ← 描述 → 接口
    │                 └── CHANGELOG ← 记录 → 变更
    │
    ├── 地图 → 索引 → L1 顶层文档
    │              → L2 子系统文档
    │              → L3 辅助模块文档
    │
    └── 治理 → 跟踪 → 文档债务
           → 审计 → 文档质量
           → 管理 → 文档生命周期
```

---

**文档版本**: v1.0
**最后更新**: 2026-07-25

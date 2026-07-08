# Dream-MultiSkill SKILL标准规范 v1.0

> **文件编号**: DREAM-SKILL-STANDARDS-001
> **版本**: v1.0
> **创建日期**: 2026-04-29
> **维护部门**: 运营总监 (COO)
> **关联文档**: GOVERNANCE_CHARTER.md, COMPLIANCE_MANUAL.md

---

## 一、SKILL设计标准

### 1.1 SKILL文件结构

每个SKILL必须包含以下文件：

```
dream-xxx/
├── SKILL.md              # 核心SKILL文件（必须）
├── README.md             # 使用说明（可选）
├── scripts/              # 脚本目录（可选）
│   ├── main.py
│   └── utils.py
└── references/          # 参考文档（可选）
    └── examples.md
```

### 1.2 SKILL.md 必须包含的章节

```markdown
# Dream-MultiSkill [SKILL名称] SKILL vX.X

> **文件编号**: DREAM-XXX-001
> **版本**: vX.X
> **创建日期**: YYYY-MM-DD
> **维护部门**: [部门名称]

---

## 一、定位与核心能力

## 二、功能列表

## 三、使用方法

## 四、触发词

## 【合规要求】    ← ★ 必须章节

### §X 问题处理流程
> ⚠️ 合规约束

### §Y 常见问题索引
| 问题类型 | FAQ位置 | 备注 |

### §Z 违规处理
| 违规类型 | 判定条件 | 处罚 |

---

## 五、版本历史

## 六、关联文档
```

---

## 二、合规章节标准模板

### 2.1 【合规要求】章节模板

```markdown
---

## 【合规要求】

### §问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| V001 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| V002 FAQ缺失 | 问题存在但未查阅 | 警告 |
| V003 FAQ未更新 | FAQ无解但未补充 | 通知 |
| V004 归档缺失 | 问题解决但未归档 | 记录 |

---

```

### 2.2 合规章节检查清单

| 检查项 | 要求 | 权重 |
|:---|:---|:---:|
| 【合规要求】章节存在 | 必须 | 🔴 |
| §问题处理流程存在 | 必须 | 🔴 |
| Step 1-4完整 | 必须 | 🔴 |
| FAQ索引表存在 | 必须 | 🟠 |
| 违规处理表存在 | 必须 | 🟠 |
| 治理文档路径正确 | 必须 | 🟠 |
| 触发词包含"合规" | 推荐 | 🟡 |

---

## 三、SKILL命名规范

### 3.1 命名规则

| 类型 | 格式 | 示例 |
|:---|:---|:---|
| SKILL目录 | dream-xxx | dream-tactical-validator |
| SKILL主文件 | SKILL.md | SKILL.md |
| 触发词 | 关键词 | 战术验证、情景验证 |
| 文件编号 | DREAM-XXX-001 | DREAM-A4-001 |

### 3.2 SKILL分类

| 分类 | 前缀 | 示例 |
|:---|:---|:---|
| 交易类 | dream-trading-* | dream-tactical-validator |
| 监控类 | dream-intelligence-* | dream-intelligence-monitor |
| 治理类 | dream-governance-* | dream-governance-manager |
| 运营类 | dream-operation-* | dream-operation-director |
| 学习类 | learning-* | learning-episode-writer |

---

## 四、SKILL版本管理

### 4.1 版本号规则

```
主版本.次版本.修订号
  │      │      │
  │      │      └── 修订：文档修正、格式调整
  │      └──────── 次版本：新功能、小优化
  └─────────────── 主版本：重大架构变更
```

### 4.2 版本历史格式

```markdown
## 版本历史

| 版本 | 日期 | 变更内容 | 维护人 |
|:---|:---|:---|:---|
| v1.0 | 2026-04-29 | 初始版本 | COO |
| v1.1 | 2026-05-15 | 添加FAQ索引 | COO |
| v2.0 | 2026-06-01 | 重大架构升级 | COO |
```

---

## 五、SKILL合规改造检查表

### 5.1 已安装SKILL改造状态

| SKILL | 合规章节 | FAQ索引 | 违规处理 | 状态 | 改造日期 |
|:---|:---:|:---:|:---:|:---:|:---|
| dream-tactical-validator | ⬜ | ⬜ | ⬜ | 待改造 | - |
| dream-tactical-executor | ⬜ | ⬜ | ⬜ | 待改造 | - |
| dream-intelligence-monitor | ⬜ | ⬜ | ⬜ | 待改造 | - |
| dream-multiSkill | ⬜ | ⬜ | ⬜ | 待改造 | - |
| boss-secretary | ⬜ | ⬜ | ⬜ | 待改造 | - |
| auto-repair | ✅ | ✅ | ✅ | ✅已改造 | 2026-04-29 |
| dream-knowledge | ⬜ | ⬜ | ⬜ | 待改造 | - |
| dream-oneirology | ⬜ | ⬜ | ⬜ | 待改造 | - |

### 5.2 改造优先级

| 优先级 | SKILL | 原因 |
|:---:|:---|:---|
| P0 | dream-tactical-validator | 涉及交易执行 |
| P0 | dream-tactical-executor | 涉及交易执行 |
| P1 | dream-intelligence-monitor | 涉及监控告警 |
| P1 | dream-multiSkill | 核心调度SKILL |
| P2 | boss-secretary | 秘书系统 |
| P2 | dream-knowledge | 知识管理系统 |
| P3 | dream-oneirology | 洞察生成系统 |

---

## 六、SKILL质量标准

### 6.1 SKILL质量检查表

| 检查项 | 要求 | 权重 |
|:---|:---|:---:|
| 文档完整性 | SKILL.md包含所有必须章节 | 20 |
| 合规章节 | 包含完整【合规要求】章节 | 20 |
| FAQ关联 | 关联正确的FAQ文件 | 15 |
| 版本管理 | 有清晰的版本历史 | 10 |
| 触发词 | 有明确的触发词列表 | 15 |
| 关联文档 | 有完整的关联文档列表 | 10 |
| 示例代码 | 有使用示例 | 10 |

### 6.2 质量评分

| 分数 | 评级 | 说明 |
|:---:|:---:|:---|
| 90-100 | 🟢 优秀 | 完全符合标准 |
| 70-89 | 🟡 良好 | 基本符合，有小缺陷 |
| 50-69 | 🟠 一般 | 需要改进 |
| <50 | 🔴 不合格 | 必须重写 |

---

## 七、SKILL生命周期

### 7.1 生命周期阶段

```
创建 → 评审 → 上线 → 监控 → 迭代 → 归档
  │       │       │      │      │      │
  └───────┴───────┴──────┴──────┴──────┘
              (治理管理部监管全过程)
```

### 7.2 各阶段要求

| 阶段 | 要求 | 责任人 |
|:---|:---|:---|
| **创建** | 遵循SKILL标准规范 | SKILL创建者 |
| **评审** | 通过治理管理部评审 | COO |
| **上线** | 添加到技能清单 | 运营总监 |
| **监控** | 定期检查运行状态 | 治理管理部 |
| **迭代** | 遵循版本管理规范 | SKILL维护者 |
| **归档** | 保留最后版本文档 | 治理管理部 |

---

## 八、附则

### 8.1 生效日期

本规范自2026-04-29起生效。

### 8.2 解释权

本规范解释权归运营总监（COO）。

### 8.3 更新频率

- 每季度审查一次
- 重大变更需COO批准

---

**最后更新**: 2026-04-29
**更新人**: 运营总监

---
name: "dream-scattered-file-cleanup"
description: "散落文件治理工作流（金融级+盆景式）：双维度分类→状态机判断→索引登记→三态决策→认知闭环5步流程。Invoke when 处理散落文件、隐藏目录排查、标号目录根层文件清理、或需统一文档管理时。"
---

# 散落文件治理工作流（金融级+盆景式）

> **位置**：`.trae/skills/dream-scattered-file-cleanup/SKILL.md`（TRAE 调用入口）
> **双副本**：`1-ARCHITECTURE/skills/dream-scattered-file-cleanup/SKILL.md`（项目级索引发现，本文件）
> **调研基础**：传统金融（Bloomberg/Goldman/SOX/Basel III）+ 科技公司（Google/Amazon/Linux Kernel/K8s Diátaxis/Microsoft Purview）

## 核心原则

1. **盆景式修剪**（Google）：文档如盆景，活着但持续修剪，而非一次性大扫除
2. **Default to archive**（Google+金融合规）：价值判断拿不准时默认归档而非保留在线，降低认知噪音
3. **保留≠不管**（VM-1790764767530 经验）：保留的文件必须纳入索引+定期review
4. **WORM 归档**（SEC 17a-4）：归档目录只读，git history 即天然 WORM
5. **销毁需审批**（DA/T79）：删除前登记造册，需人工确认

## 触发条件

- 用户要求"逐个文件调查/核对/排查"
- 用户要求"清理散落文件/保持系统干净"
- 用户要求"检查是否被索引系统包含"
- 用户要求"归档到系统文件管理"
- 处理标号目录根层散落文件
- 处理隐藏目录（.dotfiles）内容
- 定期文档治理（Scheduled Review）

## 5步流程

### Step 1: 双维度分类调查

用 `ls -la` 列出目标目录全部文件，按**受众×类型**双维度分类：

**受众轴**（借鉴 Linux Kernel）：
| 受众 | 说明 | 典型落位 |
|------|------|----------|
| User | 面向使用者 | `0-系统文档管理/` 或子系统 README |
| Dev | 面向开发者 | 子系统 `docs/` 或 `1-ARCHITECTURE/` |
| Maintainer | 面向维护者 | `1-ARCHITECTURE/skills/` 或治理目录 |
| Internal | 内部研究/临时 | `.trae/documents/` 或归档 |

**类型轴**（借鉴 K8s Diátaxis）：
| 类型 | 文件名特征 | 典型处置 |
|------|-----------|----------|
| Concept(概念) | design/architecture/overview | 保留（SSoT候选） |
| Task(任务) | plan/impl/task/TODO | 归档（判断是否已执行） |
| Tutorial(教程) | guide/tutorial/howto | 保留 |
| Reference(参考) | spec/api/ref/standard | 归档（判断是否已落地） |
| Temporary(临时) | input/output/qwen/draft/debug | 删除（已消费） |

**双维度矩阵**：每个文件落位到 `受众×类型` 的一个桶位，索引登记时即可判断归属。

### Step 2: 状态机价值判断

对每个文件打标 **Status**（借鉴 Linux Kernel MAINTAINERS）：

| Status | 含义 | 处置 |
|--------|------|------|
| `Active` | 活跃使用中，有owner | 保留原位+纳入索引 |
| `Maintained` | 维护中，定期更新 | 保留原位+纳入索引 |
| `Obsolete` | 已过时，有更优替代 | 归档（标注被谁替代） |
| `Orphan` | 无owner，代码已删/接口已变 | 归档或删除（需人工确认） |
| `Hold` | 未闭环任务/未结调研 | **保护：cleanup跳过**（对标 Litigation Hold） |

**判断流程**：
1. 读取前20行了解内容
2. Grep搜索主仓库是否有引用/落地
3. 检查是否有owner（文件头 frontmatter / @author / 责任人）
4. 检查是否属于未闭环任务（SPEC tasks.md 有 pending 项 → Hold）
5. 打标 Status

**保留期分层**（对标金融合规 SOX/FINRA/反洗钱）：
| 文档类型 | 保留期 | 依据 |
|----------|--------|------|
| S级记忆/硬约束 | 永久 | 系统核心 |
| 决策记录/审计 | 10年 | 对标反洗钱客户记录 |
| 技术文档/SPEC | 7年 | 对标 SOX 802 审计底稿 |
| 研究报告 | 3年 | 对标 FINRA 默认 |
| 临时笔记/AI输出 | 删除或30天 | 已消费 |
| 未分类 | 默认保留 | 不确定时不删 |

### Step 3: 索引登记

**核心原则：保留的文件必须纳入索引系统统一管理，可被快速定位。**

在 `0-系统文档管理/INDEX.md` 中登记：
- 目标目录管理详情子节
- 子目录文件数+用途+管理机制
- **必填字段**：文件名 + Status + owner + 上次更新时间 + 保留策略
- **去重检查**（Google "Duplication is Evil"）：仅保留单一权威源

### Step 4: 三态决策执行

对每个文件按**保留期三态矩阵**执行（借鉴 Microsoft Purview）：

| 决策 | 适用Status | 执行操作 |
|------|-----------|----------|
| `retain-only`（永久留档） | Active/Maintained + S级/硬约束 | 保留原位+纳入索引+WORM保护 |
| `retain-then-delete`（保留N天后清理） | Obsolete + 研究报告 | 归档到 `0-系统文档管理/archive/` + 标注清理日期 |
| `delete-only`（即时删除） | Orphan + Temporary + 已消费AI输出 | 删除+登记造册+人工确认 |

**Hold 保护**：Status=Hold 的文件，cleanup 跳过，标注"等待闭环"。

**WORM 归档**（SEC 17a-4）：
- 归档目录设为只读（`chmod -R a-w` 或 git-readonly）
- 归档操作记入 INDEX.md 的不可变日志
- git history 即天然 WORM

**销毁审批**（DA/T79）：
- 删除前生成"销毁清单"（文件名+大小+理由）
- 需用户人工确认后才执行删除
- 删除后认知 record 记录审计 trail

### Step 5: 认知闭环 + 定期Review

**审计 trail**：
```
record(content="散落文件清理经验", quality_level="B", tags="散落文件,文档治理,doc-sync")
verify(memory_id="VM-xxx", success=true)
```

**Scheduled Review**（对标文档生命周期）：
- 保留文件每季度 review 一次（Status 是否变化）
- 归档文件每年 review 一次（保留期是否到期）
- review 结果更新 INDEX.md

## 处置规则速查

### 保留条件（Active/Maintained + retain-only）：
- 纯研究报告，仍有参考价值
- 进行中任务（SPEC/计划未完成 → Hold）
- 运行时必需配置（mcp.json/.env）
- 运行时加载位置（.trae/skills/）
- S级记忆/硬约束决策

### 归档条件（Obsolete + retain-then-delete）：
- 已落地的实施计划/SPEC
- 已修复的修复方案
- 已消费的研究输出
- 已完成的任务SPEC

### 删除条件（Orphan/Temporary + delete-only）：
- AI输入输出文档（已消费，无独立价值）
- 缓存目录（__pycache__/.pytest_cache/.ruff_cache）
- 重复文件（已有SSoT副本 → Duplication is Evil）
- 空文件/临时文件

## 双副本管理机制

`.trae/skills/` 与 `1-ARCHITECTURE/skills/` 保持双副本：
- `.trae/skills/` — Trae 平台运行时加载位置
- `1-ARCHITECTURE/skills/` — 主仓库 SSoT 归档位置
- 两个位置的 SKILL.md 可有"本文件"标注差异（合理设计）
- `_registry/` 和治理工具集仅在 SSoT

## 前置约束

- 任务开始前必须调用 `recall` 检索相关经验
- 编码/文档变更后必须调用 `dream-doc-sync-workflow` 同步索引
- 硬约束决策必须 `record` 写入认知库
- 删除操作必须用户人工确认（销毁审批）

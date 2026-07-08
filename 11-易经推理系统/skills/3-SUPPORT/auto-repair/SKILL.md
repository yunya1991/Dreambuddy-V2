---
name: auto-repair
slug: auto-repair
version: 2.1.0
description: |
  Dream-MultiSkill 系统健康自动修复与提案落地工具 v2.1。
  
  **核心功能**：
  - 账户隔离监控：确保系统不混淆实盘和模拟盘
  - 三邮箱状态检查：秘书/调研部/待修复邮箱（顾问已内嵌SKILL，物理邮箱已废弃）
  - ⭐ 提案落地执行：检查完邮箱后负责落地提案
  - 72小时定时健康检查：自动检测并修复系统问题
  - ⭐ 合规检查：检测各SKILL合规性，违规记录与处罚
  
  **触发词**：
  - "auto-repair"、"系统健康"、"健康检查"、"自动修复"
  - "账户隔离"、"账户监控"、"检查实盘"、"检查模拟盘"
  - "邮箱检查"、"三邮箱"、"秘书邮箱"
  - "提案归档"、"提案落地"、"提案执行"、"待处理提案"
  - "72小时"、"定时检查"、"健康报告"
  - "落地提案"、"执行提案"、"处理全部提案"
  - "运营健康检查"、"治理检查"、"合规检查"、"检测违规"
---

# Auto-Repair 系统健康自动修复与提案落地工具 v2.0

**目标**：保障系统安全，账户隔离，确保AI不会误操作实盘账户，并在检查完邮箱后负责落地提案。

---

## 【合规要求】

### §合规问题处理流程

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

### §合规常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

## 依赖 SKILL

- **dream-task-creator**: 任务创建专家（v2.0）
  - **调用时机**：需要创建定时任务或临时任务时
  - **调用方式**：`use_skill("dream-task-creator")`
  - **核心功能**：
    - 快速创建各类自动化任务（定时/一次性）
    - 提供完整的工作流：创建 → 验证 → 压力测试
    - 支持 RRule 模板库（每小时/每天/每周等）
  - **注意**：必须使用直接写入 TOML 文件的方式，不使用 automation_update 的 suggested create 模式
  - **路径**：`~/.workbuddy/skills/dream-task-creator/SKILL.md`

---

## 🛡️ Auto-Repair 检查清单（行为规范）

> **强制执行**：每次健康检查必须按顺序执行以下检查项

### 第一阶段：账户隔离检查 🔒

| 检查项 | 优先级 | 检查方法 | 通过标准 |
|:---|:---:|:---|:---|
| 1.1 账户策略一致性 | P0 | `account_monitor.py --check policy` | 单一活跃账户 |
| 1.2 OKX配置检查 | P0 | `account_monitor.py --check config` | 无配置冲突 |
| 1.3 账户混淆风险 | P1 | `account_monitor.py --scan` | 历史记录合理 |
| 1.4 实盘持仓状态 | P1 | 检查A5账户（若启用） | 止损已设置 |

### 第二阶段：三邮箱状态检查 📬

| 检查项 | 优先级 | 检查方法 | 通过标准 |
|:---|:---:|:---|:---|
| 2.1 秘书邮箱 | P1 | `mailbox_monitor.py` | 4h内有新报告 |
| 2.2 调研部邮箱 | P2 | `mailbox_monitor.py` | 24h内有新报告 |
| ~~2.3 顾问邮箱~~ | - | ~~已废弃(2026-04-26)~~ | 顾问已内嵌SKILL直接调用 |
| 2.3 待修复邮箱 | P1 | `mailbox_monitor.py` | 无积压任务 |
| **2.5 提案邮箱检查** ⭐ | P0 | 检查今日提案 | **落地执行触发点** |

### 第三阶段：⭐ 提案落地检查 📋

> **核心升级**：检查完邮箱后，必须执行提案落地

| 检查项 | 优先级 | 检查方法 | 通过标准 |
|:---|:---:|:---|:---|
| 3.1 今日提案状态 | P0 | 检查 `reports/proposals/dream_proposal_*.md` | **全部标注处理状态** |
| 3.2 历史提案归档 | P1 | 检查归档目录 | 无积压未归档提案 |
| 3.3 P0提案落地 | P0 | 检查 `proposals/*001*.md` | 已实施或标注推迟 |
| 3.4 待落地提案 | P0 | 检查待处理提案 | **立即执行落地** |
| 3.5 提案状态标注 | P0 | 更新 `PROPOSAL_STATUS_*.md` | 全部提案已标注 |

### 第四阶段：系统配置检查 ⚙️

| 检查项 | 优先级 | 检查方法 | 通过标准 |
|:---|:---:|:---|:---|
| 4.1 Skill冲突 | P1 | 扫描 `~/.workbuddy/skills/` | 无同名触发词 |
| 4.2 记忆文件 | P1 | 检查 `memory/` | 无状态冲突 |
| 4.3 自动化配置 | P2 | 检查cron/automation | 状态正确 |

### 第五阶段：OKX/Bot相关检查 🤖

> **硬约束**: OKX/Bot问题 → 先查FAQ → 再查官方文档

| 检查项 | 优先级 | 检查方法 | 通过标准 |
|:---|:---:|:---|:---|
| 5.1 OKX API状态 | P1 | CLI测试 `okx market ticker` | 正常响应 |
| 5.2 API密钥配置 | P0 | 检查 `~/.okx/config.toml` | profile正确 |
| 5.3 FAQ匹配 | P0 | 查 `.workbuddy/faq/OKX_FAQ.md` | 优先使用FAQ方案 |

---

## ⭐ 提案落地执行流程 v2.0

> **核心职责**：检查完邮箱后，自动执行提案落地

```
┌─────────────────────────────────────────────────────────────────┐
│                    提案落地执行流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ① 扫描今日提案                                                  │
│     ↓                                                           │
│  ② 分类提案状态                                                  │
│     ├─ ✅ 可立即落地 → 执行落地                                   │
│     ├─ ⏸️ 需等待条件 → 标注推迟+记录前置条件                        │
│     └─ ⚠️ 需人工确认 → 加入待修复邮箱                              │
│     ↓                                                           │
│  ③ 落地执行                                                      │
│     ├─ 更新SKILL → 写入决策规则/触发条件                           │
│     ├─ 更新内存   → 写入MEMORY.md                                 │
│     └─ 标注提案   → 添加落地状态说明                               │
│     ↓                                                           │
│  ④ 验证落地                                                      │
│     ├─ 确认SKILL更新成功                                         │
│     └─ 生成落地报告                                               │
│     ↓                                                           │
│  ⑤ 更新提案状态                                                  │
│     ├─ 写入 PROPOSAL_STATUS_YYYYMMDD.md                          │
│     └─ 归档历史提案                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 提案落地决策矩阵

| 提案类型 | 落地条件 | 行动 |
|:---|:---|:---|
| **Skill升级** | Skill文件存在 | 直接更新SKILL.md |
| **流程规范** | 逻辑清晰 | 更新相关Skill或MEMORY |
| **风险控制** | 无实盘持仓 | 可立即落地 |
| **止损/熔断** | A5暂停中 | ⏸️ 推迟，标注前置条件 |
| **数据修复** | 公式/参数正确 | 立即更新MEMORY |
| **OKX/Bot** | FAQ匹配 | 查FAQ后再决策 |

### 落地状态标注规范

```markdown
## 落地状态 (YYYY-MM-DD HH:MM)

**状态**: ✅ 已落地 | ⏸️ 推迟 | ⚠️ 待处理

**落地位置**: 
- SKILL: `dream-xxx/SKILL.md`
- 记忆: `.workbuddy/memory/MEMORY.md`

**执行动作**:
1. [具体执行项]
2. [具体执行项]

**前置条件** (若推迟):
- 条件1
- 条件2
```

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Auto-Repair 引擎 v2.0                              │
├─────────────┬─────────────┬─────────────┬─────────────┬──────────────────────┤
│ 账户监控器 │ 邮箱检查器  │ 提案扫描器  │ 落地执行器  │ 健康报告生成器        │
│ Account    │ Mailbox     │ Proposal    │ Executor    │ Report               │
│ Monitor    │ Checker     │ Scanner     │             │ Generator            │
├─────────────┼─────────────┼─────────────┼─────────────┼──────────────────────┤
│ 扫描报告    │ 报告新鲜度  │ 提案状态    │ Skill更新   │ 问题汇总              │
│ 日志文件    │ 积压检测    │ 落地优先级  │ 记忆更新    │ 修复建议              │
│             │             │ 触发落地    │ 状态标注    │ 提案状态报告          │
└─────────────┴─────────────┴─────────────┴─────────────┴──────────────────────┘
```

---

## 核心功能

### 1️⃣ 账户隔离监控（Account Isolation）

**目标**：防止AI混淆实盘和模拟盘操作。

**扫描范围**：
- `reports/` - 每日交易报告
- `.workbuddy/memory/` - 记忆文件
- `.workbuddy/skills/` - Skill配置文件

**关键词检测**：

| 类型 | 关键词 |
:|------|--------|
| 实盘 | live, main, A5, 实盘, 实盘账户, 实盘持仓 |
| 模拟盘 | demo, dreamdemo, 模拟盘, 模拟账户, 模拟持仓, 测试 |

**混淆风险检测**：
- 同一文件中同时出现实盘和模拟盘关键词 → 🔴 高风险
- 报告中声明了冲突的账户监控状态 → ⚠️ 需确认

**配置管理**：

用户可通过修改配置文件来管理监控账户：
```yaml
# ~/.workbuddy/skills/auto-repair/account_monitor_config.yaml
monitored_accounts:
  live:
    profile: A5
    status: disabled  # 启用: active | 禁用: disabled
    note: "A5实盘，2026-04-24暂停监控"
  demo:
    profile: dreamdemo
    status: active
    note: "当前唯一监控账户"
```

---

### 2️⃣ ⭐ 提案落地执行（Proposal Execution）

**触发条件**：
1. 四邮箱检查完成后自动触发
2. 手动调用 auto-repair 时执行
3. 72小时定时健康检查时执行

**扫描范围**：
```
reports/proposals/
├── dream_proposal_*.md          # 今日提案
├── archive/                     # 历史归档
│   └── dream_proposal_*.md
└── PROPOSAL_STATUS_*.md         # 状态报告
```

**落地优先级**：

| 优先级 | 标识 | 提案类型 | 落地时限 |
|:---|:---:|:---|:---|
| P0 | 🔴 | 清算价/杠杆/止损 | **立即落地** |
| P1 | 🟡 | 监控升级/流程优化 | 24h内落地 |
| P2 | 🔵 | 文档整理/规范完善 | 72h内落地 |

**落地动作清单**：

| 动作 | 说明 | 目标文件 |
|:---|:---|:---|
| 更新Skill | 写入决策规则/触发条件 | `~/.workbuddy/skills/*/SKILL.md` |
| 更新记忆 | 写入核心教训/参数 | `.workbuddy/memory/MEMORY.md` |
| 标注提案 | 添加落地状态 | `dream_proposal_*.md` |
| 生成报告 | 更新状态总报告 | `PROPOSAL_STATUS_*.md` |
| 归档提案 | 移动到archive目录 | `archive/` |

---

### 3️⃣ 72小时健康检查

**检查项目**：

| 检查项 | 优先级 | 说明 |
|--------|--------|------|
| 账户隔离 | P0 | 实盘/模拟盘配置一致性 |
| 提案落地 | P0 | 检查未落地提案并执行 |
| Skill冲突 | P1 | 检查多Skill间的配置冲突 |
| 记忆文件 | P1 | 状态一致性、过期数据 |
| 自动化配置 | P2 | cron/automation状态 |
| 待执行任务 | P2 | pending_tasks清理 |

**问题分级**：

| 级别 | 标识 | 含义 | 处理方式 |
|------|------|------|----------|
| P0 | 🔴 | 账户混淆风险 / 未落地P0提案 | 立即告警+落地 |
| P1 | 🟡 | 配置问题 / 待落地P1提案 | 建议修复 |
| P2 | 🔵 | 轻微问题 / 待落地P2提案 | 可选优化 |

---

### 4️⃣ 自动修复能力

**可自动修复**：
- 清理过期的临时文件
- 整理记忆文件结构
- 更新状态标记
- ⭐ **更新提案落地状态**
- ⭐ **更新Skill落地规范**

**需人工确认**：
- 配置文件冲突
- 账户状态变更
- Skill卸载/安装
- P0提案需跳过时

---

## 使用方法

### 执行完整健康检查+提案落地

```bash
# ⭐ 推荐：完整检查+提案落地
python3 ~/.workbuddy/skills/auto-repair/scripts/full_health_check.sh

# 快速检查（含提案状态）
bash ~/.workbuddy/skills/auto-repair/scripts/quick_check.sh

# 仅检查提案落地状态
python3 ~/.workbuddy/skills/auto-repair/scripts/proposal_check.sh
```

### 单独执行提案落地

```bash
# 扫描今日提案
python3 ~/.workbuddy/skills/auto-repair/scripts/proposal_check.sh --scan

# 执行提案落地
python3 ~/.workbuddy/skills/auto-repair/scripts/proposal_check.sh --execute

# 更新提案状态报告
python3 ~/.workbuddy/skills/auto-repair/scripts/proposal_check.sh --report
```

### 传统检查项

```bash
# 账户隔离检查
python3 ~/.workbuddy/skills/auto-repair/scripts/account_monitor.py --scan

# 四邮箱状态检查
python3 ~/.workbuddy/skills/auto-repair/scripts/mailbox_monitor.py

# OKX配置检查
python3 ~/.workbuddy/skills/auto-repair/scripts/account_monitor.py --check config
```

---

## 自动化调度

**建议调度频率**：每72小时（3天）一次

**自动化配置示例**：

```toml
# 72小时健康检查+提案落地
[automation]
name = "dream-auto-repair"
prompt = "执行auto-repair完整健康检查，检查完邮箱后执行提案落地，生成报告"
schedule = "FREQ=HOURLY;INTERVAL=72"
cwds = "/Users/zhangjiangtao/WorkBuddy/20260415144304"
status = "ACTIVE"
```

---

## 输出示例

### ⭐ 完整检查+提案落地报告

```markdown
# 🔧 Auto-Repair 健康检查+提案落地报告

## 📅 执行时间: 2026-04-24 20:40

---

## 🔒 第一阶段：账户隔离检查

| 检查项 | 状态 | 备注 |
|:---|:---:|:---|
| 账户策略一致性 | ✅ | 单一活跃账户: demo |
| OKX配置检查 | ✅ | profile正确 |
| 账户混淆风险 | ✅ | 0个风险项 |

---

## 📬 第二阶段：四邮箱状态检查

| 邮箱 | 状态 | 最新报告 |
|:---|:---:|:---|
| 秘书 | ✅ | 2h前 |
| 调研部 | ✅ | 12h前 |
| 顾问 | ✅ | 无积压 |
| 待修复 | ✅ | 无积压 |

**触发**: 提案落地检查

---

## 📋 第三阶段：⭐ 提案落地检查

### 今日提案状态

| 编号 | 标题 | 状态 | 落地动作 |
|:---|:---|:---:|:---|
| 001 | 清算价公式 | ⏸️ 推迟 | A5重启后验证 |
| 002 | 熔断线执行 | ⏸️ 推迟 | A5重启后配置 |
| 003 | 杠杆超限 | ✅ 已落地 | pretrade-gatekeeper |
| 004 | USDT窗口 | ⏸️ 推迟 | A5重启后评估 |
| 005 | 费率翻转 | ✅ 已落地 | intelligence-monitor |
| 006 | 梦游惯性 | ✅ 已落地 | episode-writer |

### 历史提案

| 日期 | 总数 | 已落地 | 待处理 |
|:---|:---:|:---:|:---:|
| 4/21 | 3 | 3 | 0 |
| 4/22 | 5 | 3 | 2 |
| 4/23 | 5 | 3 | 2 |
| 4/24 | 6 | 3 | 3 |
| **合计** | **19** | **12** | **7** |

---

## ✅ 落地执行结果

### 已落地 (3个)
- P003: ✅ 已更新 `dream-pretrade-gatekeeper/SKILL.md`
- P005: ✅ 已更新 `dream-intelligence-monitor/SKILL.md`
- P006: ✅ 已更新 `learning-episode-writer/SKILL.md`

### 推迟 (3个)
- P001/P002/P004: ⏸️ A5重启后处理

---

## 📊 统计汇总

| 类别 | 数量 | 状态 |
|:---|:---:|:---|
| 今日提案 | 6 | ✅ 全部处理 |
| 历史提案 | 16 | ⚠️ 7个待处理 |
| Skill更新 | 3 | ✅ 完成 |
| 状态标注 | 22 | ✅ 全部 |

---

## 💡 后续建议

1. ⏸️ A5实盘重启后验证P001-P002
2. ⚠️ 历史提案待人工确认
3. ✅ 系统健康状态良好
```

---

## 配置文件位置

| 文件 | 说明 |
|------|------|
| `~/.workbuddy/skills/auto-repair/scripts/account_monitor.py` | 账户监控脚本 |
| `~/.workbuddy/skills/auto-repair/scripts/mailbox_monitor.py` | 邮箱检查脚本 |
| `~/.workbuddy/skills/auto-repair/scripts/proposal_check.sh` | ⭐ 提案落地脚本 |
| `~/.workbuddy/skills/auto-repair/account_monitor_config.yaml` | 账户配置 |

---

## 踩坑经验

- **账户关键词检测**：使用大小写不敏感匹配，避免遗漏
- **配置解析**：OKX配置使用TOML格式，需正确解析disabled标记
- **策略一致性**：强制要求单一活跃账户，避免多账户同时监控
- **⭐ 提案落地**：检查完邮箱后必须执行提案落地，不可遗漏
- **⭐ 落地优先级**：清算价/杠杆/止损类P0提案必须立即落地

---

*v2.1.0 - 2026-04-29 - 新增合规检查功能与治理文档关联*

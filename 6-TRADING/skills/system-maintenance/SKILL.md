---
name: system-maintenance
description: |
  🔧 系统维护 SKILL - 基于架构文档的系统健康检查与修复

  核心能力：
  1. 架构健康检查：对照架构文档检查各模块实现状态
  2. 问题追踪：识别实现与规划的偏差
  3. 维护报告：生成定期维护报告
  4. 修复流程：按架构规划执行修复或触发开发任务

  触发词：
  - 系统维护、架构检查、健康检查、周维护、月度维护
  - 检查架构、查看进度、更新状态、架构同步
  - 发现问题、修复计划、迭代规划

version: 1.0.0
created: 2026-06-25
updated: 2026-06-25
license: Internal
---

# 🔧 System Maintenance SKILL (v1.0)

> 基于架构文档的系统健康检查与维护，参考 SYSTEM_ARCHITECTURE_OVERVIEW.md

---

## 🎯 SKILL 目标

1. **架构一致性**: 确保代码实现与架构文档同步
2. **健康监控**: 定期检查各模块实现状态
3. **问题追踪**: 识别偏差并生成修复计划
4. **闭环修复**: 按架构规划执行修复或触发开发任务

---

## 📋 维护检查清单

### 1. 架构层检查（对应架构文档章节）

| 检查项 | 架构章节 | 检查内容 | 状态 |
|--------|---------|---------|:----:|
| 三链定义 | 第二章 | S/C/F 链步骤定义完整性 | |
| SKILL库 | 第五章 | A/C/F 系列技能实现状态 | |
| 动态执行 | 第六章 | 反思引擎+5种决策实现 | |
| BAC图结构 | 第三章 | 数据模型+压缩展开算法 | |
| ChainPlanner | 第四章 | 四维规划逻辑实现 | |
| 三链交叉验证 | 第四章 | 投票计算器+交叉验证器 | |
| 进化系统 | 第七章 | 记忆/知识库/索引系统 | |
| DZE开发链 | 第八章 | D/Z/E三链+门禁实现 | |
| Dream-Agent | 第九章 | 四大角色+账本+Token | |

### 2. 实现进度检查（对应架构文档第十三章）

**进度等级定义**:
- 🟢 90-100%: 功能完整，可投入使用
- 🟡 50-89%: 部分实现，需要完善
- 🔴 0-49%: 早期阶段，需要大量工作

**检查维度**:
- 代码实现完整性
- 单元测试覆盖
- 文档完整性
- 与其他模块的集成度

### 3. 依赖关系检查

```
前端展示层
    ↓ 依赖
后端执行层
    ↓ 依赖
图压缩模块
    ↓ 依赖
BAC数据模型
    ↓ 依赖
知识库/记忆/索引
    ↓ 依赖
进化系统
    ↓ 触发
Dream-Agent协作
    ↓ 产出
DZE开发链
    ↓ 产出
代码落地
```

---

## 🔍 健康检查流程

### Phase 1: 数据采集

```yaml
check_modules:
  - module: "骨架层（三链）"
    path: "6-图结构上下文压缩/planner/step-types.ts"
    checks:
      - file_exists: true
      - s_chain_steps_defined: true
      - c_chain_steps_defined: true
      - f_chain_steps_defined: true

  - module: "SKILL库"
    path: "6-图结构上下文压缩/planner/skills-registry.ts"
    checks:
      - file_exists: true
      - skill_count: ">30"
      - chain_mapping_complete: true

  - module: "知识库"
    path: "2-KNOWLEDGE/"
    checks:
      - index_exists: true
      - knowledge_file_count: ">20"
      - rag_implementation: true

  - module: "记忆系统"
    path: "3-FRONTEND/dream-universal-gateway/src/lib/memory/"
    checks:
      - intent_memory_exists: true
      - user_preference_memory_exists: true

  - module: "DZE开发链"
    path: "3-CHAIN-DEVELOPMENT/"
    checks:
      - d_chain_docs: true
      - z_chain_docs: true
      - e_chain_docs: true
      - chain_guard_exists: true

  - module: "Dream-Agent"
    path: "/Users/zhangjiangtao/WorkBuddy/DREAM-AGENT/"
    checks:
      - ledger_exists: true
      - token_design_exists: true
      - constitution_exists: true
```

### Phase 2: 状态对比

```
采集到的状态 vs 架构文档记录的期望状态
    ↓
识别偏差
    ↓
分类:
  - 🔴 严重偏差: 实现完全缺失或方向错误
  - 🟡 中度偏差: 部分实现但不完整
  - 🟢 轻微偏差: 细节差异，可接受
```

### Phase 3: 报告生成

**维护报告结构**:
```yaml
maintenance_report:
  timestamp: "ISO时间戳"
  period: "本周/本月"
  overall_health: "A/B/C/D"

  checks:
    - module: "模块名"
      expected: "期望状态"
      actual: "实际状态"
      status: "🟢/🟡/🔴"
      action: "无需处理/待完善/需紧急修复"

  summary:
    total_modules: N
    healthy: N  # 🟢
    warning: N  # 🟡
    critical: N # 🔴

  next_actions:
    - priority: "high/medium/low"
      issue: "问题描述"
      action: "建议操作"
      trigger: "自动修复/手动修复/触发开发任务"

  trend:
    last_week: "上周期评分"
    this_week: "本周期评分"
    direction: "↑改善/↓恶化/→持平"
```

---

## 📊 维护报告模板

```markdown
# 🔧 系统维护报告

**维护周期**: 2026-06-25 ~ 2026-07-01
**维护时间**: {timestamp}
**维护人**: System

---

## 一、整体健康度

| 维度 | 健康度 | 趋势 |
|------|--------|------|
| 骨架层（三链） | A | ↑ |
| 血肉层（SKILL） | B | → |
| 灵魂层（执行） | B | ↑ |
| 进化系统 | C | → |
| DZE开发链 | B | ↑ |
| Dream-Agent | B | → |

**综合评分**: 78/100 (B级)

---

## 二、各模块检查详情

### 2.1 骨架层（三链定义）
- **状态**: 🟢 90%
- **检查项**: S/C/F三链步骤定义
- **结果**: 完整实现
- **待处理**: F链技能部分待补充

### 2.2 血肉层（SKILL库）
- **状态**: 🟡 75%
- **检查项**: A/C/F系列技能
- **结果**: A系列较完整，C/F系列部分实现
- **待处理**: 约40+技能

...

---

## 三、问题清单

| 优先级 | 问题 | 建议操作 |
|--------|------|---------|
| 🔴 高 | ChainPlanner四维优化不完整 | 触发开发任务 |
| 🟡 中 | F链技能缺失较多 | 补充实现 |
| 🟡 中 | 进化系统端到端未打通 | 制定打通计划 |
| 🟢 低 | 文档细节待完善 | 下周迭代 |

---

## 四、下周计划

1. 【高优】完善 ChainPlanner 四维优化
2. 【高优】打通进化系统端到端闭环
3. 【中优】补充 F链 技能实现

---

## 五、签名确认

- [ ] 已检查所有模块
- [ ] 问题已确认
- [ ] 计划已制定
- [ ] 需要人工介入: 是/否

**确认人**: _______________
**确认时间**: _______________
```

---

## ⚙️ 自动化配置

### Cron 调度（每周一 09:00）

```yaml
cron:
  schedule: "0 9 * * 1"  # 每周一 09:00
  timezone: "Asia/Shanghai"
  notification:
    feishu: true  # 飞书通知
    email: false
```

### 触发方式

1. **定时触发**: 每周一自动执行
2. **手动触发**: `skill system-maintenance run`
3. **事件触发**: 大版本更新后自动检查

---

## 🔗 相关文档

- 架构总览: [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)
- 实现进度: [第十三章 - 实现进度总览](#十三-实现进度总览)
- 维护记录: [第十四章 - 维护记录](#十四-维护记录)

---

## 📌 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-06-25 | 初始版本 |

---

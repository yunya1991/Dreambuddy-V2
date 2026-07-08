---
name: "dream-exit-skill-v2"
description: >
  A9 离场决策 v2.2 - 四层离场决策链 + 风险库(21事件) + A6联动 +
  OKX TP/SL联动 + MEMORY日志 + 自动推送 + 参数优化。
  触发词：离场决策、A9、风险检查、强制离场、参数优化、停止损失、
  移动止损、分批离场、风险事件、A6联动、MEMORY日志
version: "v2.2"
created: "2026-05-05"
updated: "2026-05-06"
status: "active"
---

# A9 离场决策 v2.2

## 定位

**A9 = 离场决策执行者**，基于A4验证报告 + A6情报 + 风险库(21事件)，
综合判断并执行离场决策。

## 四层决策链

```
Layer 1: 技术离场（TP/SL/ trailing）
Layer 2: 风险事件离场（21风险事件匹配）
Layer 3: A6情报联动离场（P0/P1事件强制触发）
Layer 4: 强制审计离场（定时检查，最后防线）
```

## 产物投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将产物写入交易邮箱 + 前端产物中心。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 离场决策部 (A9) |
| **双通道** | 秘书邮箱 + 前端产物中心 |
| **秘书邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **前端产物路径** | `~/.workbuddy/artifacts/trading/` |
| **投递方式** | 脚本自动投递（Python生成 `.md` + `.json`） |
| **文件名格式** | `a9_exit_check_{YYYYMMDD}_{HHMMSS}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 + 前端产物中心（`artifact-alignment-manager` SKILL §一） |

> 前端产物中心文件frontmatter完整模板（双通道均需包含）：
> ```yaml
> ---
> title: "A9 离场检查 BTC-USDT-SWAP YYYY-MM-DD"
> department: trading
> chain_phase: A9
> date: "YYYY-MM-DDTHH:MM:SS"
> type: exit_decision
> status: completed
> tags: "a9 exit-skill 离场检查"
> by_a_phase: A9
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单
- [ ] `.md` 和 `.json` 文件写入 `reports/trading/` 目录
- [ ] `.md` 文件包含完整 YAML frontmatter（含 tags, by_a_phase）
- [ ] `.md` 和 `.json` 文件写入 `artifacts/trading/` 目录
- [ ] `artifacts/trading/index.json` 已更新（含 chain_phase + tags）
- [ ] 投递后通过 `curl -s -o /dev/null -w "%{http_code}" http://localhost:3456/feed/trading/a9_exit_check_...` 验证返回200
- [ ] **调用 `artifact-alignment-manager` SKILL 验证双通道**

### 投递后验证（强制调用AD SKILL）

完成秘书邮箱投递后，必须调用 `artifact-alignment-manager` SKILL 执行双通道验证：

1. **调用方式**: 触发词「产物投递验证」或加载 `artifact-alignment-manager` SKILL
2. **验证内容**:
   - ✅ 秘书邮箱文件存在 + frontmatter完整（含 tags, by_a_phase）
   - ✅ 前端产物中心文件存在（`~/.workbuddy/artifacts/trading/`）
   - ✅ `index.json` 已更新（含 `chain_phase` + `tags`）
   - ✅ 前端详情页返回 200
3. **不通过**: 按 AD SKILL 第四章步骤修复，重新验证
4. **通过**: 投递完成

> ⚠️ 没有 AD SKILL 验证通过 = 投递未完成

### 代码入口

- **离场检查脚本**: `~/.workbuddy/skills/dream-exit-skill-v2/exit_skill_automation.py`
- **自动投递**: 脚本内 `_save_and_return()` 函数自动生成 `.md` + `.json` 并写入双通道
- **查看产物**: `ls -la ~/.workbuddy/skills/boss-secretary/reports/trading/a9_*`
- **验证前端**: `curl http://localhost:3456/feed/trading/a9_exit_check_...`

---

## 四层决策链详细规范

（此处保留A9原有核心逻辑，详见 exit_skill_automation.py）

### Layer 1: 技术离场
...（保留原有逻辑）

### Layer 2: 风险事件离场
...（保留原有逻辑，21风险事件）

### Layer 3: A6情报联动
...（保留原有逻辑）

### Layer 4: 强制审计
...（保留原有逻辑）

---

## 版本历史

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v2.2 | 2026-05-06 | 增加双通道投递规范 + AD SKILL验证 + frontmatter完整7字段 |
| v2.1 | 2026-05-05 | 四层决策链 + 风险库 + A6联动 + MEMORY日志 |

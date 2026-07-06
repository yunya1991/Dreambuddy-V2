---
title: "资源效率分析报告 — 2026-04-28"
department: governance
type: health_report
date: "2026-04-28T11:44:00"
status: completed
---

# 资源效率分析报告 — 2026-04-28

> **执行时间**: 2026-04-28 11:44 CST  
> **分析周期**: 72小时（上次: 2026-04-25 → 本次: 2026-04-28）  
> **分析师**: 资源效率分析师 (automation-6)  
> **系统健康评分**: **62/100** ⬇️ (上次68, -6分)

---

## 一、系统全局概况

| 指标 | 本次 | 上次(04-25) | 变化 |
|:---|:---|:---|:---|
| 工作区总大小 | 41MB | ~37MB | ⬆️ +10.8% |
| reports/ 总文件 | 590个 (453md+91json+46html) | ~540个 | ⬆️ +9.3% |
| reports/ 占用 | 5.5MB | ~3.3MB | ⬆️ +67% ⚠️ |
| sandbox/ 占用 | 4.9MB | 4.8MB | ≈持平 (未清理) |
| MEMORY.md | **8.2KB** | 5.0KB | ⬆️ **超硬限8KB** 🚨 |
| episodes/ | 372KB / 71文件 | ~72文件 | ≈持平 |
| 邮箱积压 | 0封 (全空) | - | ✅ 正常 |
| 根目录散落文件 | 17md + 15html = **32个** | ~31个 | ≈未改善 |

---

## 二、自动化任务清单与资源消耗

### 2.1 用户级任务 (~/.workbuddy/automations, 12个活跃)

| 任务名 | 频率 | 72h执行次数 | 状态评估 |
|:---|:---|:---:|:---|
| secretary-workflow-processor | 每2h | **36次** | ⚠️ 频率偏高，邮箱持续为空 |
| pending-actions-processor | 每8h | 9次 | 🟡 上次建议降至12h，未执行 |
| research-workflow-processor | 每8h | 9次 | 🟡 可合并或降频 |
| auto-repair-processor | 每24h | 3次 | ✅ 已按建议降频 |
| chain-validation-processor | 每24h | 3次 | ✅ 合理 |
| **pressure-test-1** | **每1h** | **72次** | 🚨 **高危空转** - 仅验证并发创建能力，无实际意义 |
| pressure-test-2 | 每日09:00 | 3次 | ⚠️ 测试任务长期ACTIVE |
| pressure-test-3 | 每周一 | ~0.4次 | 🟡 低频但无实际产出 |
| pressure-test-4 | 每周五 | ~0.4次 | 🟡 低频但无实际产出 |
| pressure-test-5 | 每日21:00 | 3次 | ⚠️ 测试任务长期ACTIVE |
| stress-test-processor | 每日21:00 | 3次 | ⚠️ 与pressure-test-5重叠 |
| dream-production-consultation-actuator | 每日20:35 | 3次 | ✅ 合理，有实际产出 |

> **说明**: `~/.workbuddy/automations/` 中12个有toml配置的任务，其余均为无配置的目录（ghost目录）

### 2.2 项目级任务 (.codebuddy/automations, 47个目录)

经检查，47个目录中**仅少数有实际toml配置**，大量为历史遗留ghost目录（如 a8、a8-2、advisor-inbox-poller、brainstorm-daily 等均无 automation.toml）。  
**实际活跃配置**: ~12个（见上方用户级 + 部分项目级）

### 2.3 "幽灵目录"清单（有目录无toml配置）

`.codebuddy/automations/` 中以下方向存在无配置ghost目录（占47个中的大多数）：
- a8, a8-2, advisor-inbox-poller, auto-repair-scheduler
- brainstorm-daily, cost-monitor, dream-first-principles-2
- dream-insight-processor, dream-intelligence-monitor, dream-multiskill
- dream-multiskill-2, dream-oneirology, dream-proposal-generator
- dream-rollback-actuator, dream-shadow-verification, dream-strategy-designer
- dream-strategy-research, dream-tactical-executor-2, dream-tactical-validator-2
- gate, hr, knowledge-sync, learning-lesson-distiller-batch
- market-research, memory-distiller, mrm-audit-offhours
- p0-alert-responder, p0-shadow-verification-executor, performance-review
- secretary-agent, secretary-alert-router, secretary-workflow-trigger
- stress-test-1-hourly, test-task-creator-verification, test-task-creator-verification-2

**建议**: 清理无用ghost目录以减少混乱（低风险，只删空目录）

---

## 三、报告文件膨胀分析

### 3.1 reports/ 高频产出类型（近72h新增204个文件 🚨）

| 文件类型 | 累计数量 | 近72h新增 | 平均大小 | 问题 |
|:---|:---:|:---:|:---|:---|
| intelligence_briefing | 79 | ~10个 | ~8-12KB | ⚠️ A6每次运行产出，已积累过多 |
| market_heatmap | 46 | 0 | ~40KB | 🟡 最新为04-24，已停止生成✅ |
| a4_scout | 10 | ~7个 | ~14KB | ✅ 正常，交易验证报告 |
| a6_execution_log | 8 | ~4个 | ~8KB | 🟡 与intelligence_briefing重叠 |
| dream_proposal / dream_production | 8+8 | ~4个 | ~10KB | ✅ 正常产出 |

### 3.2 reports/ 历史堆积分析

| 日期 | 文件数 |
|:---|:---:|
| 04-15（启动初期） | **337** 🚨 |
| 04-25~28 | 170 |
| 04-22~24 | 74 |
| 04-19~21 | 65 |

> **04-15日期的337个文件为最大堆积来源**，可能是批量生成的压力测试/回测结果，建议归档或清理。

---

## 四、关键问题诊断

### 🚨 P0级问题（立即处理）

**P0-1: pressure-test-1 每小时空转，资源浪费严重**
- 现状：`FREQ=HOURLY;INTERVAL=1`，每小时执行，72h运行72次
- 任务内容：仅验证并发创建能力（`压力测试任务1：每小时执行。验证并发创建能力。`）
- 实际产出：reports/下仅有12个stress_test文件，大量空转无记录
- **建议**：立即PAUSED，或至少改为每周执行一次

**P0-2: MEMORY.md 超硬限（8.2KB > 8KB 硬限）**
- 现状：8200 bytes，超过8KB硬限
- 风险：内存污染、召回错误
- **建议**：立即触发memory-distiller蒸馏，目标压缩至≤6KB

**P0-3: sandbox/ 4.9MB 废弃文件长期未清理（第3次告警）**
- 现状：4.9MB，内含04-19日期的simulation目录，上次建议清理未执行
- **建议**：删除 sandbox/simulation/ 旧数据（请确认后执行）

### 🟡 P1级问题（72h内处理）

**P1-1: secretary-workflow-processor 每2h运行但邮箱持续为空**
- 邮箱全部为空（secretary/research/pending/archive/trading/advisor 均0封）
- 36次/72h 执行但无实际工作，纯空转
- **建议**：改为每4h执行，节省50%算力

**P1-2: stress-test-processor 与 pressure-test-5 同时间重叠**
- 两个任务均在每日21:00执行，功能重叠（均为压力测试写报告）
- **建议**：合并为一个任务，废弃 stress-test-processor 或 pressure-test-5

**P1-3: pressure-test-2/3/4/5 长期ACTIVE（测试任务未清理）**
- 5个pressure-test全部仍为ACTIVE状态
- 测试阶段任务应在验证完成后PAUSED
- **建议**：压测相关任务全部PAUSED，保留配置但停止执行

**P1-4: reports/04-15 337个文件堆积**
- 占reports总文件的57%，为系统启动初期批量产出
- **建议**：创建 reports/archive/20260415/ 归档，保持工作区整洁

**P1-5: 47个.codebuddy/automations ghost目录需清理**
- 大量历史遗留空目录（约35个无配置）
- 干扰任务管理和排查
- **建议**：保留有memory.md或automation.toml的，其余可清理

### 📋 P2级建议（下次周期处理）

**P2-1: research-workflow-processor + pending-actions-processor 可合并评估**
- 两者均为8h频率，处理邮箱任务
- 当前邮箱长期为空，考虑是否仍需分开运行

**P2-2: 根目录散落32个文件（17md + 15html）**
- 连续3次出现在告警中，建议统一归档到 reports/ 或单独整理目录

**P2-3: episodes/ 71个文件，最新为04-22**
- 近6天无新episode写入，A7 episode-writer可能未正常运行
- 建议检查 episode_counter.json 和 episode-writer skill 状态

---

## 五、上次建议执行追踪

| 建议 | 优先级 | 状态 |
|:---|:---:|:---|
| MEMORY瘦身（04-25建议） | P0 | ⚠️ 已从5KB增至8.2KB，反而膨胀 |
| Pending降至8h | P0 | ✅ 已执行（当前INTERVAL=8） |
| Auto-Repair降至24h | P0 | ✅ 已执行（当前INTERVAL=24） |
| 删除p0-alert-responder | P0 | ⚠️ 目录仍存在（无toml，是ghost） |
| sandbox清理 | P1 | ❌ **未执行**，仍4.9MB |
| 归档旧reports | P1 | ❌ **未执行**，继续增长 |
| 根目录清理 | P1 | ❌ **未执行**，32个散落文件 |

**上次建议执行率：29%** ⬇️（较上次50%下降）

---

## 六、ROI 评估矩阵

| 任务 | 执行次数/72h | 有效产出 | ROI评级 |
|:---|:---:|:---|:---:|
| dream-production-consultation-actuator | 3 | 做梦洞察→提案→验证→落地 | ⭐⭐⭐ 高 |
| auto-repair-processor | 3 | 系统自愈修复 | ⭐⭐⭐ 高 |
| chain-validation-processor | 3 | 链路健康验证 | ⭐⭐ 中 |
| research-workflow-processor | 9 | 调研报告（邮箱空时为零产出） | ⭐ 低 |
| secretary-workflow-processor | 36 | 邮箱路由（持续空运行） | ⭐ 极低 |
| pending-actions-processor | 9 | 待办处理（邮箱空时为零产出） | ⭐ 低 |
| **pressure-test-1** | **72** | **仅验证并发，无业务价值** | **💀 负ROI** |
| pressure-test-2/5 | 3+3 | 测试验证（已完成，应停止） | 💀 负ROI |
| stress-test-processor | 3 | 与pressure-test重叠 | 💀 负ROI |

---

## 七、降本增效行动计划

### 立即行动（今日执行）

```
ACTION 1: PAUSED pressure-test-1 (每小时空转任务)
- 预期节省: 72次/72h → 0次，消除最高频无效任务

ACTION 2: 触发memory-distiller蒸馏MEMORY.md
- 目标: 8.2KB → ≤6KB，解除硬限告警

ACTION 3: PAUSED pressure-test-2/3/4/5 + stress-test-processor
- 预期节省: ~12次/72h，清理测试残留
```

### 72小时内（本周内）

```
ACTION 4: secretary-workflow-processor 从2h改为4h
- 当前邮箱持续为空，降频50%不影响业务

ACTION 5: 清理 sandbox/simulation/ 旧数据 (4.9MB)
- 已连续3次告警，确认无用后清理

ACTION 6: reports/04-15 文件归档到 reports/archive/20260415/
- 337个历史文件→归档，减少主目录混乱
```

### 下周（持续优化）

```
ACTION 7: 清理.codebuddy/automations/ ghost目录 (约35个空目录)

ACTION 8: 根目录32个散落文件统一整理到 reports/archive/root/

ACTION 9: 检查episode-writer运行状态 (6天无新episode)

ACTION 10: 评估 research + pending processor 是否可合并
```

---

## 八、系统健康评分详情

| 维度 | 得分 | 满分 | 说明 |
|:---|:---:|:---:|:---|
| 磁盘健康 | 10 | 20 | reports膨胀+sandbox未清+根目录散落 |
| 任务质量 | 10 | 25 | 5个无效压测任务持续运行 |
| 内存质量 | 10 | 20 | MEMORY.md超硬限，episides停更 |
| 邮箱流通 | 12 | 15 | 邮箱清空良好，但空转问题 |
| 架构整洁 | 10 | 10 | ghost目录问题，但核心架构稳定 |
| 建议执行率 | 10 | 10 | 本次29%较低 |
| **总计** | **62** | **100** | ⬇️ 较上次68分下降 |

---

## 九、关键指标趋势

```
系统健康评分:  72 → 68 → 62  📉 连续下滑
MEMORY.md:     6.7KB → 5.0KB → 8.2KB  📉 反弹超限
reports/文件:  ~267 → 540 → 590  📈 持续增长
建议执行率:    50% → 29%  📉 执行力下降
压测任务清理:  0/5  ❌ 从未清理
sandbox清理:   0次  ❌ 连续3次未执行
```

---

*报告生成时间: 2026-04-28 11:44 CST*  
*下次执行: 2026-05-01 约11:44 CST (72h后)*

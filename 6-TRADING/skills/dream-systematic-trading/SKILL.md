---
title: "系统交易策略 SKILL v2.0 (协调器)"
summary: "三屏交易体系总入口/调度器 - 编排第一屏+第二屏+第三屏的完整执行流程"
trigger:
  - "系统交易"
  - "马丁策略"
  - "三屏交易"
  - "开始交易"
  - "执行策略"
  - "完整分析"
---

# 系统交易策略 SKILL v2.0 (dream-systematic-trading)

> **SKILL 定位**: 三屏交易体系的**协调器 / 总入口**
>
> **核心变更 (v1.0 → v2.0)**:
> - ~~第一屏/第二屏内联实现~~ → **委托给独立SKILL**
> - **本SKILL负责**: 调度编排 + 第三屏(执行层) + 全局风控
>
> **版本**: v2.0 | 最后更新: 2026-05-16

---

## 一、v2.0 架构变革

### 1.1 从"单体"到"微服务化"

```
┌─────────────────────────────────────────────────────────────┐
│                  v1.0 (旧) - 单体架构                         │
│                                                             │
│  dream-systematic-trading (660行巨石)                       │
│    ├── 第一节: 第一屏实现 (200行)                            │
│    ├── 第二节: 第二屏实现 (250行)                            │
│    └── 第三节: 第三屏实现 (210行)                            │
│                                                             │
│  问题: 难以独立调用、难以单独优化、修改互相影响               │
└─────────────────────────────────────────────────────────────┘

                          ↓ 拆分重构

┌─────────────────────────────────────────────────────────────┐
│                  v2.0 (新) - 协调器架构                       │
│                                                             │
│  dream-systematic-trading (本文件 - 协调器)                 │
│    │                                                       │
│    ├──→ ★委派★ dream-screen1-first   (独立SKILL, 可单调用)   │
│    │     第一屏: 周线决策 (战略层)                           │
│    │                                                       │
│    ├──→ ★委派★ dream-screen2-second  (独立SKILL, 可单调用)   │
│    │     第二屏: 日线预设 (战术层)                           │
│    │                                                       │
│    └──→ ★保留★ 第三屏: 实时监控 (执行层)                     │
│          A4验证 + A5执行 + A6监控 + A9离场                   │
│                                                             │
│  支撑模块 (被第一/二屏内部调用):                              │
│    • dream-backtest       回测引擎                          │
│    • dream-bayesian-opt    贝叶斯优化                        │
│    • artifact-alignment-manager  AAM投递                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 SKILL 清单总览

| SKILL | 路径 | 状态 | 可独立调用? |
|:------|:-----|:-----|:-----------|
| **dream-systematic-trading** | skills/.../ | 协调器(v2.0) | ✅ 完整流程 |
| **dream-screen1-first** | skills/.../screen1-first/ | ★ 新建 | ✅ 是 |
| **dream-screen2-second** | skills/.../screen2-second/ | ★ 新建 | ✅ 是 |
| **dream-backtest** | skills/.../backtest/ | ★ 新增 | 仅被调用 |
| **dream-bayesian-opt** | skills/.../bayesian-opt/ | ★ 新增 | 仅被调用 |
| **artifact-alignment-manager** | ~/.workbuddy/skills/... | 已有 | 统一投递 |

### 1.3 核心创新点 (继承自 v1.0/v3.0)

1. **弱信号不下漏趋势**: 弱信号轻仓试探（30%仓位）
2. **默认多头**: 无明确信号时默认多头
3. **强度值资金控制**: 仓位 = 基础 × (强度/100) × 风险系数 × 回测修正
4. **最大回撤约束**: 马丁策略最大回撤 ≤ 20%
5. **A9 L1分层执行**: 加仓期仅硬止损，满仓后启用完整止盈止损
6. **★ v2.0新增**: 回测数据支撑 + 贝叶斯参数优化 + AAM统一投递

---

## 二、协调器调度逻辑

### 2.1 完整三屏流程 (协调器模式)

```yaml
协调器完整执行流程:

  触发: "系统交易" / "三屏交易" / "开始交易"

  ════════════════════════════════════════════
  STAGE 1: 委派第一屏 ★
  ════════════════════════════════════════════
  
  调用: 读取 dream-screen1-first SKILL 并按协议执行
  
  本协调器的职责:
    - 传递触发参数 (symbol, 手动/自动模式)
    - 接收第一屏输出 (周线方向 + 策略类型)
    - 校验输出完整性
    
  第一屏自主完成:
    - Phase 1: 过去一周交易记录调取 (OKX API + Episodes)
    - Phase 2: A1(周线) → A2(周线) → A3(周线) 分析流水线
    - Phase 3: 决策输出 + AAM投递到 screen1/
    
  输出传递给第二屏:
    - screen1_output.yaml (或等效JSON)
    
  ⚠️ 如果第一屏失败:
    → 使用上周有效缓存 (标记"降级")
    → 如果无缓存 → 终止并报错

  ════════════════════════════════════════════
  STAGE 2: 委派第二屏 ★
  ════════════════════════════════════════════
  
  调用: 读取 dream-screen2-second SKILL 并按协议执行
  
  前置条件: 必须有有效的第一屏输出
  
  第二屏自主完成:
    - Phase 0: 接收并校验第一屏输入
    - Phase 1: 日线数据采集 + 交易记录
    - Phase 2: A1(日线) → A2(日线) → A3(日线)
    - Phase 3: ★ 回测验证 + 贝叶斯参数优化 ★
    - Phase 4: 三大预设输出 + AAM投递到 screen2/

  输出传递给第三屏:
    - screen2_output.yaml (含三大预设价位表)

  ════════════════════════════════════════════
  STAGE 3: 第三屏 (本协调器直接执行) ★
  ════════════════════════════════════════════
  
  第三屏不拆分 — 保留在协调器中 (见第三节)

  输入:
    - 第二屏三大预设
    - A4验证报告
    - A6情报监控数据
    
  执行:
    - A4战术验证 (入场前二次确认)
    - A5决策执行 (发出入场指令)
    - A6情报监控 (实时市场雷达)
    - A9离场决策 (四层离场链)
```

### 2.2 快捷模式：仅执行某一屏

```yaml
快捷调用:

  仅第一屏:
    触发词: "周线分析" / "第一屏" / "weekly decision"
    行为: 直接调用 dream-screen1-first，跳过第二、三屏
    
  仅第二屏:
    触发词: "日线预设" / "第二屏" / "daily preset"
    行为: 直接调用 dream-screen2-second，自动读取最新第一屏
    
  仅第三屏 (实时监控):
    触发词: "实时监控" / "当前状态" / "调整仓位"
    行为: 在协调器中执行A4/A5/A6/A9，读取最新第二屏预设
    
  完整流程:
    触发词: "系统交易" / "三屏交易" / "开始交易"
    行为: 按顺序 Stage 1 → 2 → 3 全部执行
```

---

## 三、第三屏：实时监控 (执行层) ★ 保留在本SKILL

### 3.1 核心功能

**四大核心功能** (保留在协调器中):
1. **入场时机调整** (A4+A5)
2. **加仓时机调整** (A4+A5)
3. **止盈止损调整** (A6+A9)
4. **紧急离场** (A9)

### 3.2 监控流程

```yaml
第三屏执行流程:

  输入:
    - 第二屏预设 (来自 dream-screen2-second)
    - A4验证报告
    - A6情报
    
  处理: ★ A4+A5+A6+A9 ★
  ────────────────────────────────────────────────────────────
    
  【A4 战术验证】★ 入场前二次确认 ★★★★★
    • 调用: dream-tactical-validator SKILL
    • 验证第二屏预设是否合理
    • 三层索引体系 (信号索引/策略索引/风险索引)
    • 输出: A4验证报告 + PASS/FAIL 判定
    
  【A5 决策执行】★ 发出入场指令 ★★★☆☆
    • 调用: dream-tactical-executor SKILL
    • A5 = A4验证报告 + A6情报 + 综合判断 → 执行下单
    • 输出: 交易执行结果 + 执行确认
    
  【A6 情报监控】★ 实时监控 ★★★★☆
    • 调用: dream-intelligence-monitor SKILL
    • 监控市场状态变化 + 异常信号 + 战略环境变更
    • 输出: A6情报报告 + 调整建议 + 紧急告警
    
  【A9 离场决策】★ 四层离场决策 ★★★★★
    • 调用: dream-exit-skill-v2 SKILL
    • L1: 技术止盈止损（分层执行）
    • L2: 信号反转
    • L3: 风险事件触发 (21事件库)
    • L4: 参数优化
    • 输出: 离场执行 + A9离场报告
  ────────────────────────────────────────────────────────────
  
  输出:
    - 执行信号: [挂单/撤单/调整止盈止损/平仓]
    - 调整信号: [无/加仓/止盈调整/止损调整/紧急离场]
```

### 3.3 A9 离场决策详细设计

```yaml
A9 离场决策系统:

  四层离场决策链:
    
    L1: 技术止盈止损
      加仓期 (Level 0-2):
        - 仅硬性保护止损（防止爆仓）
        - 不止盈（给市场波动空间）
        - 止损位: 基于支撑位和波动率
        - 最大回撤约束: ≤20%
        
      三层加满后 (Level 3):
        - 启用完整止盈止损
        - 移动止盈: 盈利超10% → 移动止盈到成本价
        - 分批离场: 盈利超20%/30%/50% → 分别离场30%/30%/40%
        
    L2: 信号反转
      - A4/A5信号反转
      - 日线与周线严重背离
      - 趋势动力消失
      
    L3: 风险事件触发 (21事件库)
      - 黑天鹅事件
      - 监管政策突变
      - 交易所异常
      - 流动性危机
      
    L4: 参数优化
      - 止盈止损动态调整
      - 加仓阶梯优化
      - 仓位管理优化
      
  离场执行:
    强制离场: L3风险事件触发
    条件离场: L1/L2信号触发
    分批离场: 盈利超20%/30%/50% → 分别离场30%/30%/40%
```

---

## 四、依赖与调用关系

### 4.1 完整 SKILL 依赖图

```yaml
SKILL 依赖关系 (v2.0):

  【协调器 - 本SKILL】dream-systematic-trading
    │
    ├──→ [委派] dream-screen1-first (第一屏)
    │     ├─→ dream-contradiction-theory (A1)
    │     ├─→ dream-first-principles (A2)
    │     ├─→ dream-tactical-validator (A3)
    │     ├─→ dream-backtest (回测数据)
    │     ├─→ dream-bayesian-opt (概率校准)
    │     └─→ artifact-alignment-manager (投递)
    │
    ├──→ [委派] dream-screen2-second (第二屏)
    │     ├─→ dream-contradiction-theory (A1日线)
    │     ├─→ dream-first-principles (A2日线)
    │     ├─→ dream-tactical-validator (A3日线)
    │     ├─→ dream-backtest (回测验证)
    │     ├─→ dream-bayesian-opt (参数优化)
    │     └─→ artifact-alignment-manager (投递)
    │
    └──→ [内置] 第三屏 (A4/A5/A6/A9)
          ├─→ dream-tactical-validator (A4验证)
          ├─→ dream-tactical-executor (A5执行)
          ├─→ dream-intelligence-monitor (A6监控)
          ├─→ dream-exit-skill-v2 (A9离场)
          ├─→ dream-risk-position-sizing (仓位)
          ├─→ dream-pretrade-gatekeeper (门禁)
          └─→ dream-constitution (宪法)
```

### 4.2 A1-A3 明确调用声明 ★ 用户要求

| 分析类型 | 第一屏中的调用 | 第二屏中的调用 | SKILL名称 |
|:---------|:-------------|:-------------|:----------|
| **A1 矛盾调查** | ✅ 周线级 | ✅ 日线级 (继承方向框架) | `dream-contradiction-theory` |
| **A2 第一性原理** | ✅ 周线级 | ✅ 日线级 (阻力方向+价位) | `dream-first-principles` |
| **A3 沙盘推演** | ✅ 周线级 (多情景概率) | ✅ 日线级 (关键价位概率) | `dream-tactical-validator` |

**调用规范**: 
- 每个屏的SKILL必须显式声明 `★ 调用方式: 读取 XXX SKILL 并执行`
- 不得跳过A1-A3任一步骤
- 必须将调用结果写入输出的 `A1-A3摘要` 字段

---

## 五、风险管理与最大回撤约束

### 5.1 最大回撤约束 (全局)

```yaml
最大回撤约束 — 全三屏通用规则:

  硬性约束: 马丁策略最大回撤 ≤ 20%

  监控机制:
    • 实时计算当前回撤 = (当前权益 - 历史最高权益) / 历史最高权益
    • 回撤 ≥ 15%: 触发警告，暂停加仓
    • 回撤 ≥ 20%: 强制止损，全部平仓

  资金管理规则:
    • 单层级仓位 ≤ 账户 20%
    • 累计马丁仓位 ≤ 账户 60%
    • 预留至少 40% 作为安全垫

  仓位计算公式 (v2.0 增强):
    实际仓位 = 基础仓位 × (信号强度 / 100) × 风险系数 × 回测修正系数
    
    其中回测修正系数 (★ 新增):
    - 回测通过: 1.0
    - 回测警告: 0.7 (降级)
    - 回测优秀(Sharpe>2): 1.1 (可小幅提升)
```

---

## 六、自动化任务映射

### 6.1 自动化任务与新SKILL对应关系

| 自动化任务 | ID | 调用的SKILL | Prompt 写法 |
|:-----------|:---|:------------|:------------|
| 第一屏-周度方向确定 | automation-1778908488411 | **dream-screen1-first** | `读取 dream-screen1-first SKILL 并按协议执行` |
| 第二屏-日线订单设置 | automation-1778908528830 | **dream-screen2-second** | `读取 dream-screen2-second SKILL 并按协议执行` |
| 6-TRADING邮箱扫描器 | automation-1778908569973 | mailbox_scanner.py | 不变 |
| 交易工作流监控 | automation-1778908570394 | 巡检脚本 | 不变 |

---

## 七、使用说明

### 7.1 触发方式

**触发词**:
- **完整流程**: "系统交易"、"三屏交易"、"开始交易"、"完整分析"
- **仅第一屏**: "周线分析"、"第一屏"、"direction decision"
- **仅第二屏**: "日线预设"、"第二屏"、"order setup"
- **仅第三屏**: "实时监控","current status","adjust position"

### 7.2 执行建议

1. **首次使用**: 先执行第一屏确认方向，再执行第二屏
2. **日常运行**: 通过自动化任务分别调度第一屏(周一)和第二屏(每日)
3. **手动干预**: 可随时单独调用任意一屏
4. **最大回撤监控**: 实时关注回撤，≥20%强制止损

---

## 八、版本历史

| 版本 | 日期 | 修改内容 |
|:------|:------|:---------|
| v1.0 | 2026-05-16 | 初始单体版本，三屏内联实现 (660行) |
| **v2.0** | **2026-05-16** | **★ 重构为协调器**：第一/二屏拆分为独立SKILL；新增回测/贝叶斯/AAM集成；保留第三屏；明确A1-A3调用关系 |

---

## 九、迁移说明 (v1.0 → v2.0)

### 9.1 文件变更清单

```
新建文件:
  skills/dream-screen1-first/SKILL.md        ★ 第一屏 (独立)
  skills/dream-screen1-first/docs/first-screen.md
  skills/dream-screen1-first/templates/first-screen-output.yaml
  skills/dream-screen2-second/SKILL.md       ★ 第二屏 (独立)
  skills/dream-screen2-second/docs/second-screen.md
  skills/dream-screen2-second/templates/second-screen-output.yaml
  skills/dream-backtest/SKILL.md            ★ 回测引擎 (新增)
  skills/dream-bayesian-opt/SKILL.md         ★ 贝叶斯优化 (新增)

修改文件:
  skills/dream-systematic-trading/SKILL.md   → v2.0 协调器 (本文件)

保留不变 (docs/templates/examples 仍在原目录作为参考):
  docs/third-screen.md
  docs/martingale-strategy.md
  docs/realtime-monitoring.md
  templates/third-screen-output.yaml
  templates/a9-exit-report.yaml
```

### 9.2 向后兼容

- 原 `docs/first-screen.md` 和 `docs/second-screen.md` 仍保留在原目录作为参考
- 新的第一/二屏 SKILL 各自带独立的 docs/ 和 templates/ 目录
- 自动化任务的 prompt 需要更新为调用新的 SKILL 名称

---

**SKILL结束**

> **独立SKILL**: 第一屏 → `dream-screen1-first`; 第二屏 → `dream-screen2-second`
> **支撑模块**: 回测 → `dream-backtest`; 贝叶斯 → `dream-bayesian-opt`; 投递 → `artifact-alignment-manager`

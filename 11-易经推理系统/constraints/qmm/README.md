# QMM 记忆量化模块规范目录

本目录用于集中管理 QMM（Quantitative Memory Model）记忆量化系统的底层约束与设计规范。

QMM 是 L4 记忆系统的**可插拔量化内核**，不是替代 L1-L4 的新总架构。
- L4 = 认知层（事件→复盘→蒸馏→统计），产出 TradeCase/Review/Distill/Stats
- QMM = 量化内核，只读 L4 产出物，提炼数学信号输出固定契约

## 双轨演进策略

### 总览

QMM 分两条线并行推进，Phase A 完成后按收敛判断决定后续方向。

```
Phase A (并行 2-3 周)
┌────────────────────────────┐    ┌────────────────────────────┐
│ 保守线: V2 基线            │    │ 激进线: V5 原型            │
│                            │    │                            │
│ 实现 phase-1 最小集        │    │ 用 numpy/sklearn 快速搭    │
│ data_prep + triple_screen  │    │ 完整链路:                  │
│ + mrd → 输出 JSON          │    │ EventEncoder → VectorSpace │
│                            │    │ → SignalGen → LRC          │
│ 目标: 零依赖，可运行        │    │                            │
│ 输出固定契约               │    │ 目标: 一次完整 walk-forward│
│ 产物: 合入 main            │    │ 回测，验证胜率是否 >55%    │
│                            │    │ 产物: qmm-v5 prototype 分支│
└────────────────────────────┘    └────────────────────────────┘
              ↓                                   ↓
Phase B (收敛判断)
┌─────────────────────────────────────────────────────────┐
│ V5 原型 walk-forward 回测结果                            │
├─────────────────────────────┬───────────────────────────┤
│ 胜率 >55% 且稳定            │ 胜率 ≤55% 或显著过拟合    │
├─────────────────────────────┼───────────────────────────┤
│ → 放弃 V3→V4 分阶段计划     │ → 走 V2→V3→V4 保守路线    │
│ → 直接在 V2 引入 V5 核心    │ → V5 退回为远景文档       │
│   ML 组件                   │ → 按 phase-2/3/4 逐步推进  │
└─────────────────────────────┴───────────────────────────┘
```

### 各阶段定位

| 轨道 | 文档 | 定位 | 依赖 | 合入状态 |
|------|------|------|------|----------|
| V2 基线 | `phase-1.md` / `phase-2.md` | 确定性底线，零外部依赖 | math/statistics | Phase A 目标 |
| V5 原型 | `qmm-v5-vision.md` | 激进验证，快速端到端跑通 | numpy/sklearn | Phase A 原型分支 |
| V3→V4 | `phase-3.md` / `phase-4.md` | Phase B 收敛后的备选路径 | numpy→完整ML栈 | 暂不启动 |

## 文件索引

### 总架构
- `architecture.md`：QMM 总架构设计（修正版，消除所有矛盾点）

### 阶段设计
- `phase-1.md`：Stage 1 — QMM 离线内核（V2 仓库，纯 math/statistics）→ **Phase A 目标**
- `phase-2.md`：Stage 2 — QMM 在线门禁（V2 仓库，回测验证 + A 系列消费）→ **Phase A 目标**
- `phase-3.md`：Stage 3 — V3 仓库 + ML 训练闭环（numpy/sklearn）→ **Phase B 备选**
- `phase-4.md`：Stage 4 — V4 仓库 + QMM V2 内核（完整量化内核）→ **Phase B 备选**
- `execution-plan.md`：双轨 Phase A/B 执行计划 + 收敛判断标准

### 基础规范
- `version-triple-spec.md`：版本三元组规范（data_version / feature_def_version / qmm_version）

### 远景
- `qmm-v5-vision.md`：QMM V5 终极愿景（原 PR #48，不受约束的完整设计空间探索）

## 主从映射

- 顶层总架构（主）：`constraints/qmm/architecture.md`
- 双轨执行计划（主）：`constraints/qmm/execution-plan.md`
- 阶段设计（主）：`constraints/qmm/phase-{1,2,3,4}.md` + `qmm-v5-vision.md`
- 实现代码（从）：V2 `scripts/memory_l4/qmm/` → V5 prototype 独立分支

## 与 L4 的关系

- L4 工程架构：`constraints/workflows-spec/l4-memory/architecture-and-workflow-design.md`
- QMM 不修改 L4 schema，不接管 L1-L4 主链路
- QMM 只读 L4 产出物（cases/distills/stats/index），输出到独立 `qmm/` 目录
- A 系列通过可选 import 消费 QMM 信号，不改变现有 entrypoint 逻辑

## QMM 输出契约（固定）

```
trend_state          趋势状态 (UP / DOWN / FLAT / TRANSITIONING)
trend_change_point   趋势变化点 (ACCELERATING / DECELERATING / REVERSING / STABLE)
mrd_vector           阻力最小方向向量 {direction, resistance_up, resistance_down, confidence}
uncertainty          不确定性量化 (0-1)
reason_codes         原因代码 (英文大写枚举，如 BULLISH_ALIGNMENT, HIGH_UNCERTAINTY)
evidence_refs        证据引用 (指向 TradeCase/Distill ID)
```

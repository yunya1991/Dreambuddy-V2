# 23-四层闭环自进化交易架构

> 观察→推断→实验→反思→回馈四层闭环自进化交易策略系统

---

## 概述

23-四层闭环自进化交易架构是 DreamBuddy-V2 的**自进化策略引擎**，通过"观察→推断→实验→反思→回馈"四层闭环实现交易策略的持续进化。核心能力包括：

- **矛盾论驱动**：识别主要矛盾、计算最小阻力路径、弹性约束求解
- **三层准入基因库**：策略知识→候选区→影子验证→实盘基因库，安全渐进
- **事件驱动策略**：宏观事件（FOMC/CPI/非农）+ 链上事件的交易决策
- **多引擎协同**：趋势跟踪、网格交易、独立离场引擎、涟漪扩散、反思引擎
- **自进化闭环**：CS 一致性评分 + ESS 奖惩 + 权重自动调整

> **架构 SSoT**: [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)
> **设计文档**: [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md)
> **工程索引**: [docs/ENGINEERING_INDEX.md](docs/ENGINEERING_INDEX.md)

---

## 目录结构

```
23-四层闭环自进化交易架构/
├── docs/                               # 文档目录
│   ├── README.md                       # 文档索引（对齐 DOC_STANDARD L3 五件套）
│   ├── ENGINEERING_INDEX.md            # 工程索引（文件级）
│   ├── TECHNICAL_DESIGN.md             # 技术设计（三层准入架构）
│   ├── API_SPEC.md                     # 接口规格
│   ├── CHANGELOG.md                    # 变更日志
│   ├── entry_bcrm_soft_weight_design.md  # BCRM 软权重设计
│   ├── 三维度矛盾论理论框架.md          # 矛盾论 v3.0 理论升级（被 6 个 core/*.py 引用）
│   └── audit_reports/                  # 审计报告归档（20 份，Sep 12-16）
├── dreambuddy_evolution/               # 核心代码包
│   ├── evolution_pipeline.py           # 主入口（四层闭环编排）
│   ├── agi_config.py                   # AGI 开关配置
│   ├── core/                           # 核心算法（矛盾论/因果/反事实/HJB）
│   ├── engines/                        # 引擎层
│   │   ├── kline_event_handler.py      # K线事件处理器
│   │   ├── reflection_engine.py        # 反思引擎（CS+ESS）
│   │   ├── exit_engine/                # 独立离场决策引擎
│   │   ├── trend_following/            # 趋势跟踪引擎
│   │   ├── grid_trading/               # 网格交易引擎
│   │   └── ...                         # 15+ 引擎
│   ├── adapters/                       # 适配器层（外部系统桥接）
│   ├── gene_data/                      # 基因库数据（candidates/genes/shadow）
│   ├── schemas/                        # JSON Schema
│   ├── scripts/                        # 回测/训练脚本
│   └── tests/                          # 测试套件（60+）
├── .workbuddy/trade_index/             # 系统级交易索引库运行时数据
│   └── all_trades_index.jsonl          # Active（被 trade_index_builder.py 引用）
├── gene_data/                          # ShadowRL 样本运行时数据
│   └── shadow_rl_samples.jsonl         # Active（被 evolution_pipeline.py 引用）
├── SPEC-AGI升级蓝图.md                  # AGI 5 Phase 升级蓝图（Active）
├── SPEC-数据管线打通与能力落地.md        # 数据管线 SPEC（Active）
├── SPEC-金融思维链层FTC设计.md          # FTC 设计 SPEC（Active）
├── SPEC-趋势跟踪正金字塔与网格策略落地.md # 趋势跟踪+网格 SPEC（Active）
├── SPEC-主要矛盾识别与最小阻力路径设计.md # 待评审 v1（Hold 保护）
├── SPEC-矛盾论实现断裂修复与阻力场升级.md # 待评审 v1（Hold 保护）
├── SPEC-美国宏观事件驱动交易策略.md      # v2.0 深度调研（Hold 保护）
├── SPEC-非线性多阶段最优路径理论调研框架.md # 理论调研 v0.5（Hold 保护）
└── README.md                           # 本文件
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖：`pip install -r requirements.txt`（23 号复用项目根依赖）

### 2. 配置

```bash
# AGI 开关配置
vim dreambuddy_evolution/agi_config.py
# 关键开关：
#   ENABLE_EVOLUTION_PIPELINE   四层闭环总开关
#   ENABLE_CONTRADICTION_DRIVEN 矛盾论驱动层
#   ENABLE_SHADOW_VALIDATION     影子验证（不干预实盘）
```

### 3. 运行

```python
# 四层闭环主入口
from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

pipeline = EvolutionPipeline()
pipeline.run()  # 观察→推断→实验→反思→回馈
```

```bash
# K线事件驱动
python -c "from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler; KlineEventHandler().run()"

# 影子回测
python dreambuddy_evolution/scripts/shadow_backtest.py
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| 四层闭环进化 | 观察→推断→实验→反思→回馈 | `EvolutionPipeline.run()` |
| 主要矛盾识别 | 多维度矛盾检测 + 最小阻力路径 | `primary_contradiction_detector.py` |
| 三层基因准入 | 候选→影子验证→实盘基因库 | `strategy_gene.py` + `ftc_gene_innovation.py` |
| 事件驱动策略 | 宏观/链上事件交易决策 | `event_driven_strategy.py` + `kline_event_handler.py` |
| 趋势跟踪 | Donchian 突破 + 正金字塔加仓 | `engines/trend_following/` |
| 网格交易 | ATR 自适应间距网格 | `engines/grid_trading/` |
| 独立离场引擎 | 多选民离场决策（超时/ARBITRATOR） | `engines/exit_engine/` |
| 反思引擎 | CS 一致性评分 + ESS 奖惩 | `reflection_engine.py` |
| 权重自动调整 | 胜率驱动的基因权重升降 | `auto_weight_adjuster.py` |

---

## 硬约束

1. **策略知识不进 CS 公式**：CS = 0.4·cos(d*) + 0.3·cos(ESS) + 0.3·sign_match(CBR)
2. **不改变 BCRM2/力向量决策条件**：策略基因仅作为 condition gene 参与 FTC 组合
3. **FAIL-OPEN 铁律**：基因准入全链路异常不阻塞交易
4. **影子模式红线**：影子验证区基因只记录不干预参数

---

## 测试

```bash
cd 23-四层闭环自进化交易架构
python -m pytest dreambuddy_evolution/tests/ -v
```

测试覆盖：矛盾论/因果/反事实/反思引擎/事件驱动/离场引擎/权重调整/基因准入等 60+ 用例。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引（15+ 引擎/适配器/核心算法）
- [技术设计](./docs/TECHNICAL_DESIGN.md) — 三层准入架构设计
- [接口规格](./docs/API_SPEC.md) — API 文档
- [变更日志](./docs/CHANGELOG.md) — 版本历史
- [项目文档索引](../0-系统文档管理/INDEX.md) — 全项目导航

---

**维护者**: DreamBuddy v2

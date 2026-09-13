# 策略知识→基因库三层准入技术设计

> **版本**: v1.3 | **创建日期**: 2026-09-10 | **最后更新**: 2026-09-11
> **定位**: L2 级子系统技术设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **关联**: [KNOWLEDGE_STORAGE_BOUNDARY_MAP.md](../../0-系统文档管理/2-文档地图/KNOWLEDGE_STORAGE_BOUNDARY_MAP.md) · [EVOLUTION_BOUNDARY_MAP.md](../../0-系统文档管理/2-文档地图/EVOLUTION_BOUNDARY_MAP.md) · [SPEC-交易知识构建双通道方案.md](../../2-KNOWLEDGE/_analysis/SPEC-交易知识构建双通道方案.md)
> **硬约束**: 策略知识不进 CS 评分公式；不改变 BCRM2/力向量决策条件；FAIL-OPEN 铁律

---

## 1. 概述

### 1.1 系统定位

将经典交易策略知识（Livermore/Wyckoff/Darvas/ICT 等）转化为可验证的策略基因，通过三层准入机制（候选区→影子验证→实盘基因库）逐步验证并激活，解决自进化系统冷启动样本不足的问题。

### 1.2 设计目标

- **冷启动**：用 BTC 回测数据（~297 笔信号）快速驱动影子验证，不等实盘慢积累
- **安全渐进**：影子模式不干预交易参数，验证通过才进实盘
- **知识→基因**：把 7 篇经典模式文档的规则转化为 condition gene JSON
- **与现有系统兼容**：不改 CS 公式、不改 BCRM2、不改力向量

### 1.3 业务边界

| 职责 | 归属 |
|:---|:---|
| 策略知识文档编写与蒸馏 | 2-KNOWLEDGE（知识库系统 A） |
| 策略知识→GeneCandidate 转换 | 本模块（基因准入层） |
| 候选区基因管理 | 本模块 |
| 影子验证区样本记录 | 本模块 + polling_trader |
| 实盘基因库管理 | strategy_gene.py + ftc_gene_innovation.py（现有） |
| CS 一致性评分 | ReflectionEngine（不改动） |
| RAG 检索权重反哺 | weight_feedback（独立路径，不进 CS） |

### 1.4 硬约束

1. **策略知识不进 CS 公式**：CS = 0.4·cos(d*) + 0.3·cos(ESS) + 0.3·sign_match(CBR)，不增加 RAG/知识项维度
2. **不改变 BCRM2/力向量决策条件**：策略基因只作为 condition gene 参与 FTC 组合，不直接修改 BCRM 参数
3. **FAIL-OPEN 铁律**：基因准入全链路异常不阻塞交易
4. **影子模式红线**：影子验证区基因只记录不干预参数（与 CBR shadow 一致）

---

## 2. 架构设计

### 2.1 三层准入架构

```
┌──────────────────────────────────────────────────────────────────┐
│                     策略知识源                                     │
│  2-KNOWLEDGE/1-TRADING/经典模式/                                   │
│  Livermore · Wyckoff · Darvas · ICT · 动量反转 · VWAP · 形态       │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 规则提取
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 0: 候选区 (candidates/)                                    │
│                                                                    │
│  · GeneCandidate JSON，status="candidate"                          │
│  · N=0，不参与交易决策                                              │
│  · 来源：策略知识文档→expression 转换                                │
│  · 准入门槛：无（转成 expression 即入）                               │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 回测/实盘触发 ≥ N_min_shadow
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: 影子验证区 (shadow_validation/)                          │
│                                                                    │
│  · status="shadow"，影子模式（只记录不干预参数）                      │
│  · 样本来源：① BTC 回测 ② 实盘自然积累                                │
│  · 准入→实盘：N≥10 且 影子胜率≥50% 且 平均PnL>0                      │
│  · 淘汰：N≥10 且 胜率<30%，或连续5笔亏损                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 验证通过
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 2: 实盘基因库 (strategy_genes/) — 现有不变                    │
│                                                                    │
│  · status="active"，参与 FTC 组合                                    │
│  · 准入：N≥100 且 ESS≥0.5（现有 L2 门槛不变）                         │
│  · 激活：top_combinations_by_ess() 自动排名                           │
│  · 淘汰：ESS 持续下降→gmax×0.5（现有机制不变）                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
2-KNOWLEDGE (策略知识)
       │
       ▼
knowledge_to_gene_converter.py  ← 新增
       │
       ▼
gene_data/candidates/           ← Layer 0
       │
       ▼
shadow_validator.py             ← 新增
       │                  ↕
       │          BTC回测引擎 + polling_trader
       │                  (样本来源)
       ▼
gene_data/shadow_validation/    ← Layer 1
       │
       ▼
ftc_gene_innovation.py          ← 现有（write_gene_to_library）
       │
       ▼
gene_data/strategy_genes/      ← Layer 2（现有，不变）
```

---

## 3. 核心算法

### 3.1 候选基因生成（策略知识→GeneCandidate）

**输入**：经典模式文档中的触发条件
**输出**：GeneCandidate JSON

**转换规则**：

| 经典策略 | expression | category | tags |
|:---|:---|:---|:---|
| Livermore 关键点 | `price_break_20d_high AND vol_ratio > 1.5` | trend | livermore, pivotal_point, breakout |
| Wyckoff Spring | `price_swing_low_below_range AND vol_ratio < 0.8 AND rsi_14 < 35` | reversal | wyckoff, spring, accumulation |
| Darvas Box | `donchian_20_high_break AND atr < 1.5 * ma_atr` | trend | darvas, box, breakout |
| ICT Order Block | `price_return_to_ob AND fvg_exists AND killzone_active` | reversal | ict, order_block, fvg |
| 头肩顶 | `head_is_highest AND shoulders_symmetric AND neck_break` | reversal | chart_pattern, head_shoulders |
| VWAP 回归 | `zscore_price_vwap < -2 AND rsi_2 < 5` | reversal | vwap, mean_reversion |
| 动量突破 | `roc_20d > 0.05 AND vol_20d_quantile > 0.8` | momentum | momentum, breakout |

**伪代码**：
```python
def convert_knowledge_to_candidate(doc_path: Path) -> GeneCandidate:
    """从策略知识文档提取触发条件，转为基因候选"""
    md = read_markdown(doc_path)
    trigger_rules = extract_trigger_section(md)  # 从"触发条件"章节提取
    expression = rules_to_expression(trigger_rules)
    return GeneCandidate(
        gene_id=f"CD-KNOW-{slug(doc_path.stem)}",
        gene_type="condition",
        category=classify_category(trigger_rules),
        condition_type="indicator",
        description=extract_summary(md),
        expression=expression,
        parameters=extract_parameters(trigger_rules),
        source="knowledge_distill",
        tags=["knowledge", doc_path.stem],
    )
```

### 3.2 影子验证逻辑

**准入判断**：
```python
def check_shadow_promotion(gene_id: str, samples: list) -> dict:
    """检查影子基因是否达到准入标准"""
    n = len(samples)
    if n < SHADOW_MIN_SAMPLES:  # 10
        return {"promote": False, "reason": f"N={n} < {SHADOW_MIN_SAMPLES}"}
    
    wins = sum(1 for s in samples if s["pnl"] > 0)
    win_rate = wins / n
    avg_pnl = sum(s["pnl"] for s in samples) / n
    consecutive_losses = max_consecutive(samples, lambda s: s["pnl"] <= 0)
    
    # 淘汰条件
    if win_rate < SHADOW_MIN_WIN_RATE:  # 0.30
        return {"promote": False, "retire": True, "reason": f"win_rate={win_rate:.0%} < 30%"}
    if consecutive_losses >= SHADOW_MAX_CONSEC_LOSS:  # 5
        return {"promote": False, "retire": True, "reason": f"consecutive_losses={consecutive_losses}"}
    
    # 准入条件
    if win_rate >= SHADOW_PROMOTE_WIN_RATE and avg_pnl > 0:  # 50%, >0
        return {"promote": True, "win_rate": win_rate, "avg_pnl": avg_pnl}
    
    return {"promote": False, "reason": f"win_rate={win_rate:.0%} < 50%"}
```

### 3.3 BTC 回测驱动样本

**方式**：不是重跑 BCRM 回测，而是对候选基因做独立的模式触发回测

```python
def backtest_gene_candidates(
    kline_data: pd.DataFrame,  # BTC 1440根4h K线
    candidates: list[GeneCandidate],
) -> dict[str, list[dict]]:
    """对每个候选基因逐bar计算是否触发，记录模拟交易结果"""
    results = {}
    for gene in candidates:
        triggers = []
        for i in range(LOOKBACK, len(kline_data)):
            bar = kline_data.iloc[i]
            if eval_expression(gene.expression, bar):
                # 模拟开仓：入场价=close，固定持有N根bar后平仓
                entry = bar["close"]
                exit_bar = kline_data.iloc[i + HOLD_BARS]
                pnl_pct = (exit_bar["close"] - entry) / entry
                triggers.append({"entry_time": bar["timestamp"], "pnl": pnl_pct, ...})
        results[gene.gene_id] = triggers
    return results
```

---

## 4. 数据流

### 4.1 主数据流

```
策略知识md → 知识转换器 → candidates/*.json → 影子验证器 → shadow_validation/*.json
                                                                  │
                                                     ┌────────────┴────────────┐
                                                     │                         │
                                              BTC回测样本                   实盘影子样本
                                              (快速积累N)                   (自然积累N)
                                                     │                         │
                                                     └────────────┬────────────┘
                                                                  ▼
                                                        准入判断(N≥10,胜率≥50%)
                                                                  │
                                                    ┌─────────────┼─────────────┐
                                                    ▼             ▼               ▼
                                               准入→Layer2      继续验证        淘汰→retired
                                               write_gene_to
                                               _library()
```

### 4.2 数据结构

**Layer 0 候选基因 JSON**：

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `gene_id` | str | `CD-KNOW-{SLUG}` |
| `status` | str | `candidate` |
| `category` | str | trend/reversal/momentum |
| `expression` | str | 触发条件表达式 |
| `parameters` | dict | 参数定义+范围 |
| `source_doc` | str | 策略知识文档路径 |
| `tags` | list | 策略标签 |
| `created_at` | str | 创建时间 |
| `n_samples` | int | 已触发次数（初始0） |

**Layer 1 影子验证 JSON**：

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `gene_id` | str | 同候选基因 |
| `status` | str | `shadow` / `promoted` / `retired` |
| `samples` | list | 触发样本列表 |
| `n_samples` | int | 样本总数 |
| `win_rate` | float | 影子胜率 |
| `avg_pnl` | float | 平均盈亏 |
| `consecutive_losses` | int | 当前连续亏损数 |
| `promoted_at` | str | 准入实盘时间（或null） |
| `retired_reason` | str | 淘汰原因（或null） |

**Layer 2 实盘基因**：使用现有 `strategy_genes/conditions/*.json` 格式，不修改。

---

## 5. 接口设计

### 5.1 内部接口

| 函数 | 签名 | 说明 |
|:---|:---|:---|
| `convert_knowledge_to_candidate` | `(doc_path: Path) → GeneCandidate` | 从策略知识文档生成候选基因 |
| `check_shadow_promotion` | `(gene_id: str, samples: list) → dict` | 检查影子基因准入/淘汰 |
| `backtest_gene_candidates` | `(kline_data, candidates) → dict` | BTC回测驱动样本 |
| `promote_to_active` | `(gene_id: str) → bool` | 影子验证通过→写正式基因库 |

### 5.2 与现有系统的接口

| 现有模块 | 交互方式 | 说明 |
|:---|:---|:---|
| `ftc_gene_innovation.py` | 调用 `write_gene_to_library()` | 准入时写入正式基因库 |
| `strategy_gene.py` | 调用 `load_gene_library()` | 加载时自动包含新基因 |
| `reflection_engine.py` | **不改动** | CS 公式不增加知识维度 |
| `weight_feedback.py` | 独立路径 | 策略知识权重反哺走 RAG 路径 |
| `polling_trader.py` | 记录影子样本 | 模式触发时记录到 shadow_validation |

---

## 6. 状态管理

### 6.1 状态文件

| 文件 | 作用 | 格式 |
|:---|:---|:---|
| `gene_data/candidates/` | 候选基因 JSON 文件 | 每基因一个 JSON |
| `gene_data/shadow_validation/` | 影子验证基因+样本 | 每基因一个 JSON |
| `gene_data/shadow_validation/{gene_id}_samples.jsonl` | 触发样本逐条记录 | JSONL |
| `gene_data/strategy_genes/conditions/` | 实盘基因（现有） | 现有格式不变 |

### 6.2 基因状态机

```
candidate → shadow → promoted (进入实盘基因库)
                 ↘ retired (淘汰)
```

### 6.3 目录结构

```
gene_data/
├── candidates/                    ← Layer 0 (新增)
│   ├── CD-KNOW-LIVERMORE-PP.json
│   ├── CD-KNOW-WYCKOFF-SPRING.json
│   ├── CD-KNOW-DARVAS-BOX.json
│   ├── CD-KNOW-ICT-ORDERBLOCK.json
│   ├── CD-KNOW-HEAD-SHOULDERS.json
│   ├── CD-KNOW-VWAP-REVERSION.json
│   └── CD-KNOW-MOMENTUM-BREAK.json
├── shadow_validation/            ← Layer 1 (新增)
│   ├── CD-KNOW-LIVERMORE-PP.json
│   ├── CD-KNOW-LIVERMORE-PP_samples.jsonl
│   └── ...
├── strategy_genes/               ← Layer 2 (现有，不变)
│   ├── conditions/
│   ├── actions/
│   └── gene_index.json
├── strategy_combinations/
│   └── library.json
└── evolution_snapshots.json
```

---

## 7. 配置管理

| 配置项 | 默认值 | 说明 |
|:---|:---|:---|
| `SHADOW_MIN_SAMPLES` | 10 | 影子验证最少样本数 |
| `SHADOW_PROMOTE_WIN_RATE` | 0.50 | 影子准入胜率门槛 |
| `SHADOW_MIN_WIN_RATE` | 0.30 | 影子淘汰胜率下限 |
| `SHADOW_MAX_CONSEC_LOSS` | 5 | 连续亏损淘汰数 |
| `L2_MIN_SAMPLES` | 100 | 实盘基因库准入N（现有不变） |
| `L2_MIN_ESS` | 0.5 | 实盘基因库准入ESS（现有不变） |
| `BACKTEST_HOLD_BARS` | 12 | 回测模拟持有bar数（4h×12=48h） |
| `BACKTEST_LOOKBACK` | 20 | 计算指标所需回看bar数 |

---

## 8. 错误处理

### 8.1 异常场景

| 场景 | 处理策略 |
|:---|:---|
| 策略文档格式不合规 | skip + log，不阻塞其他文档 |
| expression 解析失败 | 标记 `status="parse_error"`，不进候选区 |
| 回测数据不足 | 记录 N=触发次数，不够时不准入 |
| 影子验证写入失败 | FAIL-OPEN，不影响交易 |
| 基因入库写入失败 | FAIL-OPEN，基因留在影子区 |

### 8.2 降级机制

```
BTC回测可用 → 快速积累样本 → 正常流程
     ↓ 不可用
实盘自然积累 → 慢速但安全 → 正常流程
     ↓ RAG不可用
策略知识不影响交易 → 交易正常运行 → 无降级需要
```

---

## 9. 扩展性设计

### 9.1 如何添加新策略知识基因

1. 在 `2-KNOWLEDGE/1-TRADING/经典模式/` 新增策略文档（含触发条件章节）
2. 运行 `convert_knowledge_to_candidate()` 生成 JSON 到 `candidates/`
3. 等待回测或实盘触发，样本自动记录到 `shadow_validation/`
4. 达到门槛后自动准入或淘汰

### 9.2 与 RAG 检索的协同

未来可在 RAG 检索到经典策略文档时，同时触发对应候选基因的样本计数+1，实现"知识检索→基因验证"联动。当前不实现，留后续波次。

---

## 10. 与传统金融的对应

| 量化流程 | 本系统对应 | 评估 |
|:---|:---|:---|
| 因子假设 | 策略知识文档 | 百年验证的经典理论 |
| 因子工程化 | GeneCandidate expression | 规则量化为可计算表达式 |
| 纸面交易验证 | 影子验证区（影子模式） | 只记录不干预，安全 |
| 小仓位实盘试错 | 影子验证通过→实盘基因库 | ESS 权重自动调整 |
| 正式因子配置 | top_combinations_by_ess | 按 ESS 降序自动排名 |
| 因子退役 | gmax×0.5 | ESS 持续下降自然淘汰 |

---

## 11. 执行计划

| 阶段 | 内容 | 前置条件 |
|:---|:---|:---|
| **Step 1** | RAG 代码确认完好（无需恢复） | ✅ 已完成 |
| **Step 2** | 创建 7 个候选基因 JSON（candidates/） | ✅ 已完成 |
| **Step 3** | 用 BTC 回测数据跑影子验证 | ✅ 已完成（1500 bar，8 个月） |
| **Step 4** | 通过影子验证的基因→实盘影子模式 | ✅ 5 个基因已 promote |
| **Step 5** | 积累到 N≥100→正式入库 | ⏳ 自然积累 |
| **Step 6** | ShadowRL Phase3 自动激活 | ✅ 3104 样本≥2000，已激活 |
| **Step 7** | REINFORCE 策略训练 | ✅ train_policy 已实现 |
| **Step 8** | 趋势跟踪+网格+RegimeGate 落地 | ✅ 665 测试全绿 |

### 11.1 影子验证回测结果（2026-09-11 更新）

BTC 4H 1500 bar 回测（2026-01-04 至 2026-09-11，8 个月），总样本 3104：

| 基因 | N | 胜率 | 平均PnL | 方向 | 状态 |
|:---|:---|:---|:---|:---|:---|
| CD-ADX-GT25-TREND | 888 | 47% | +0.08% | long | ⏳ |
| CD-BOLL-WIDTH-NARROW | 757 | 50% | -0.20% | long | ⏳ |
| CD-ADX-LT25-RANGE | 491 | 50% | -0.15% | long | ⏳ |
| CD-ATR-EXPANDING | 303 | 53% | +0.75% | long | ✅ promote |
| CD-DONCHIAN-10-BREAK | 177 | 42% | -0.21% | long | ⏳ |
| CD-DONCHIAN-20-BREAK | 112 | 39% | -0.19% | long | ⏳ |
| CD-DONCHIAN-55-BREAK | 67 | 31% | -0.36% | long | ⏳ |
| CD-KNOW-ICT-ORDERBLOCK | 100 | 55% | +0.46% | long | ✅ promote |
| CD-NECKLINE-BREAK | 62 | 53% | +1.14% | short | ✅ promote |
| CD-KNOW-HEAD-SHOULDERS | 45 | 56% | +0.78% | short | ✅ promote |
| CD-KNOW-DARVAS-BOX | 43 | 30% | -0.08% | long | ⏳ |
| CD-KNOW-LIVERMORE-PP | 23 | 39% | +0.25% | long | ⏳ |
| CD-KNOW-VWAP-REVERSION | 19 | 37% | -1.00% | long | ⏳ |
| CD-KNOW-MOMENTUM-BREAK | 17 | 59% | +2.64% | long | ✅ promote |
| CD-KNOW-WYCKOFF-SPRING | 0 | - | - | long | ⏳ |

关键发现：
- 5 个基因已 promote（ATR 扩张、ICT OrderBlock、颈线跌破、头肩顶、动量突破）
- 颈线跌破做空信号 PnL +1.14%（顶部下跌识别有效）
- 动量突破 PnL +2.64%（最高收益）
- ShadowRL Phase3 已激活（3104 样本≥2000 阈值）

### 11.2 ShadowRL 训练闭环验证（2026-09-11）

| 能力 | 状态 | 说明 |
|:---|:---|:---|
| 样本记录 | ✅ | 3104 条 (s,a,R,s') 样本 |
| Phase3 自动激活 | ✅ | ≥2000 样本触发 |
| REINFORCE 训练 | ✅ | SimplePolicy 纯 numpy 实现 |
| 策略预测 | ✅ | predict() → 动作概率 |
| Beta 参数更新 | ✅ | alpha=985, beta=1017 |
| Thompson 采样 | ✅ | Beta 分布采样 |
| gmax 变异 | ✅ | ±0.01~0.05 随机扰动 |
| FAIL-OPEN | ✅ | 训练异常→降级返回 |

### 11.3 RAG 热路径状态确认

| 组件 | 行号 | 状态 |
|:---|:---|:---|
| `_RAG_CLIENT` / `_RAG_EXECUTOR` | L95-97 | ✅ 存在 |
| `_rag_hotpath_lookup()` | L386-429 | ✅ 存在 |
| `_rag_record_to_memory()` | L432-446 | ✅ 存在 |
| `_distill_trade_to_knowledge()` | L453-496 | ✅ 存在 |
| `_rag_feedback_on_close()` | L523-583 | ✅ 存在 |
| 接入点A: `[RAG-PRE-OPEN]` | L13208 | ✅ 今日26次调用 |
| 接入点B: `[RAG-PRE-EVO-OPEN]` | L8924 | ✅ 今日1次调用 |
| 接入点C: `[RAG-PRE-EXIT]` | L9535 | ✅ 今日351次调用 |

daemon PID=75911，12:11 PM 启动，今日 RAG 378 次调用零异常。

---

## 12. L3 路径计算层 — HJB/变分法最优路径求解器（v1.5 新增）

### 12.1 模块定位

L3 路径计算层是自进化系统 AGI Core 的数学核心，对齐架构图"L3 路径计算层（新增·多路径+最优）"设计。本章节记录 Phase 2.6 HJB/变分法求解器的技术实现。

**代码路径**: `dreambuddy_evolution/core/hjb_solver.py`

### 12.2 架构层级

```
L3 路径计算层
├── 多路径蒙特卡洛采样 (PathIntegralEngine.sample_paths)  — 已有
├── 路径阻力计算 (PathIntegralEngine.compute_action)      — 已有
├── 最优路径求解
│   ├── Level 1: HJBPathSolver.solve()                    — v1.5 新增
│   ├── Level 2: VariationalPathOptimizer.optimize()     — v1.5 新增
│   └── Level 3: PathIntegralEngine.find_least_resistance_path() — 已有 argmin 兜底
└── 统一入口: solve_optimal_path() 三级降级链 (HC-AGI-17)  — v1.5 新增
```

### 12.3 HJBPathSolver 数学原理

**HJB PDE 离散化**:

```
连续: ∂V/∂t + min_u { L(s,u) + ∇V·f(s,u) } = 0
离散: V(p,t) = min_u { L(p,u)·dt + Σ_{p'} P(p→p'|u)·V(p',t+dt) }
```

- **状态空间**: 价格 p ∈ [p_min, p_max] × 时间 t ∈ [0, T]
- **策略空间**: u ∈ {long, short, wait}
- **终端条件**: V(:, T) = 0（无仓位代价为 0）
- **转移概率**: GBM 对数收益率高斯窗 ±2σ 截断
- **Lagrangian**: 对齐 level0_path_cost.py 的 R_up/R_down/R_smooth·R_reflexivity

### 12.4 VariationalPathOptimizer 数学原理

**变分法梯度下降**:

```
作用量: S[γ] = Σ_i L(γ_i, Δγ_i)
梯度:   ∂S/∂γ_i ≈ (S(γ+ε·e_i) - S(γ-ε·e_i)) / (2ε)    （中心差分）
更新:   γ_{k+1} = γ_k - η·∇S
约束:   起点 anchoring γ[0]=const, 价格 clip(p_min, p_max)
```

- `compute_action` 严格复用 PathIntegralEngine 公式（α·成本+β·风险+γ·不确定性）
- 梯度裁剪 [-10, 10] 防爆炸

### 12.5 硬约束

| 约束 | 含义 | 代码位置 |
|:---|:---|:---|
| HC-AGI-15 | HJB 网格分辨率下限（价格≥32, 时间≥16） | `HJBPathSolver.MIN_PRICE_GRID/MIN_TIME_GRID` |
| HC-AGI-16 | 收敛阈值 1e-6 持续≥3轮 | `CONVERGENCE_TOL/CONVERGENCE_ROUNDS` |
| HC-AGI-17 | 异常强制降级到 argmin（FAIL-OPEN 不可跳过） | `solve_optimal_path()` 三级降级链 |

### 12.6 集成点

| 集成位置 | 文件 | 行号 | 说明 |
|:---|:---|:---|:---|
| DeepReasoningEngine | `engines/deep_reasoning_engine.py` | L302-347 | `find_min_resistance_path` 优先 HJB，FAIL-OPEN 降级 argmin |
| EvolutionPipeline | `evolution_pipeline.py` | L590-620 | `_select_optimal_path` 注入 HJB 值函数（30% 权重） |
| AGI 开关 | `agi_config.py` | L49-50 | `enable_hjb_solver` + `enable_variational_opt` |

### 12.7 哲学差距分析 — "主要矛盾→阻力最小"逻辑链

**哲学逻辑链**: 多路径(矛盾) → 识别主要矛盾 → 趋势延续性 → 回测/小仓验证 → 最小阻力

| 环节 | 实现度 | 差距 |
|:---|:---:|:---|
| ①多路径=多矛盾 | 85% | 路径间并行收集，无对抗/共振分析 |
| ②识别主要矛盾 | **30%** | **核心断裂**: 独立评分取最高，非矛盾间比较识别主导者 |
| ③趋势延续性 | 40% | trend_strength/ADX 未回流路径发现层 |
| ④回测+小仓验证 | 50% | 验证结果未回流闭环 |
| ⑤最小阻力计算 | 70% | HJB Lagrangian 未融入矛盾强度调制 |

**核心结论**: 数学算法层完备，但哲学意图层存在核心断裂 — 当前是"所有矛盾平均化下求最小阻力"，不是"识别出的主要矛盾下求最小阻力"。

**完善方案**: 详见 [SPEC-主要矛盾识别与最小阻力路径设计.md](../SPEC-主要矛盾识别与最小阻力路径设计.md)

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|:---|:---|:---|
| v1.0 | 2026-09-10 | 初始版本：三层准入设计、知识→基因转换、影子验证逻辑、BTC回测驱动 |
| v1.1 | 2026-09-10 | 补充：影子验证回测结果、RAG热路径状态确认、执行计划更新 |
| v1.2 | 2026-09-11 | 更新：1500 bar 扩展数据（8个月）、3104 样本 ShadowRL Phase3 激活、REINFORCE 训练闭环、5 基因 promote、趋势跟踪+网格+RegimeGate 落地、665 测试全绿 |
| v1.3 | 2026-09-11 | 更新：P2 CBR 扩展（pattern+case_type）、P3 AGI 模块懒初始化接入 pipeline（CausalEngine/SignatureEngine/PathIntegralEngine/UncertaintyQuantifier/MetaCognitionGate）、692 测试全绿、技术债务全部清零 |
| v1.5 | 2026-09-11 | 新增：§12 L3 路径计算层 HJB/变分法最优路径求解器、HC-AGI-15/16/17 硬约束、哲学差距分析、715 测试全绿 |

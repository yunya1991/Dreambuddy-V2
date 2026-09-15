# 代码结构分析图（Z1）：DreamOS OS自进化 — Hermes监督层 + 自动回滚执行 + 编排审计补全

> **任务**: 给 DreamOS OS 自进化补齐三块缺口 G-A/G-B/G-C
> **Z1身份**: 架构师 · 四维扫描法 · 工具 read_file/search_files（只读）
> **覆盖说明**: `_plan/` 含 8-29 上一任务残留产物(z1~z4)，本报告为当前任务 Z1 权威产出，覆盖旧 `z1-scan-report.md`。
> **前置任务**: `_plan/feedback-e2.md` 不存在 → 跳过跨链反馈前置，正常扫描。

---

## 〇、核心结论（先给答案）

| 缺口 | 真实现状（✅坐实） | 精确缺口 | 风险 |
|:---|:---|:---|:---:|
| **G-A** Hermes监督 | DreamOS→Hermes 仅有"T3委托深度分析"(complexity_classifier)；`scheduler.py:L419 use_hermes=False` | **反向监督链路全缺**：无 Hermes 旁路观测 evolve/编排进化/审计 | 低(只读) |
| **G-B** 自动回滚 | `save_model_version`(L278)存版本✓ + `check_rollback_candidates`(L855)识别候选✓ + `record_evolution_event`记审计✓，每小时`run_hourly_sacg`(L874)在跑 | **只"建议"不"执行"**：无 restore/activate 切换 active 版本的动作；model_versions.status 字段有但无切换方法 | **高(涉交易)** |
| **G-C** 编排审计 | 子系统模型进化审计**完整且LIVE**(model_evolution表 L761，record_evolution_event L788) | **OS编排进化无审计**：`update_from_evolution`(L332)只写 orchestration_memory.json，不落任何审计表 | 中 |

> ⚠️ **Z1 修正记录**：初判"model_evolution/performance_snapshots 缺表→致命崩溃死代码"，经全仓 grep CREATE 推翻——两表在 L761/L773 由 `BCRM2EvolutionObserver` 建，且 L874 每小时实际调用。**审计+回滚检查是 LIVE 链路**。误判未入报告。

---

## 一、涉及模块（模块树）

```
DreamOS OS层 (被观测/被补全)
├── evolution/engine.py ............... 进化引擎 evolve()→调 update_from_evolution(~L177)
│   └── 依赖: lesson_distiller / gap_analyzer / node_optimizer / .types(EvolutionReport)
├── core/memory/orchestration_memory.py  编排记忆 (G-C核心)
│   ├── update_from_evolution(L332) .... 写 scenarios[id]={best_pattern,nodes,score,confidence,sparse,evolved_at}
│   ├── select / save / load ........... scenarios 进化状态读写
│   └── _default_path(L68) → orchestration_memory.json (同目录)
├── core/memory/scenario_backtester.py . 影子验证(_sandbox_validate) 依赖 orchestration_memory
└── cli/bcrm2_scheduler.py ............. 子系统 (G-B/G-C参照, LIVE)
    ├── class BCRM2Scheduler ........... 建 trades/model_versions/analysis_logs/performance_stats; save_model_version(L278)
    ├── class BCRM2EvolutionObserver ... 建 model_evolution(L761)/performance_snapshots(L773)
    │   ├── record_evolution_event(L788) 写 model_evolution
    │   ├── snapshot_performance(L809)  写 performance_snapshots
    │   ├── get_performance_trend(L842) 读 performance_snapshots
    │   └── check_rollback_candidates(L855) 读trend→返回"建议"dict(不执行)
    └── run_hourly_sacg(L874) .......... 每小时入口: snapshot→check_rollback→record_evolution(rollback_warning)

Hermes监督层 (G-A 全新建)
└── [新模块] 旁路只读观测器 → 观测 orchestration_memory.json + bcrm_trades.db + evolve输出 → 审计闸/告警(不阻断上线)
    接入点: Hermes cron / gateway (待定, Z2划分)

数据层
├── core/memory/orchestration_memory.json  (编排scenarios状态 — G-A观测源/G-C写入点)
└── data/bcrm_trades.db (L110) ............. SQLite 6表: trades/model_versions/analysis_logs/performance_stats/model_evolution/performance_snapshots
```

---

## 二、影响图（依赖 + 波及范围）

```
【DreamOS 内部自进化 — 当前全自动, 无Hermes介入】

  engine.evolve()
      │ (影子验证 _sandbox_validate 通过→自动上线, 不需审批 ✓符合MEMORY)
      ▼
  orchestration_memory.update_from_evolution(L332)
      │
      ▼
  orchestration_memory.json[scenarios]  ◄─── ❌G-C缺口: 此路径不落审计表
                                                 (子系统模型进化有model_evolution审计, 编排进化没有)

  run_hourly_sacg(L874, 每小时)
      ├─► observer.snapshot_performance ─► performance_snapshots表
      ├─► observer.check_rollback_candidates(L855)
      │       └─ win_rate<0.4 or sharpe<0.0 → 返回{"recommendation":"建议回滚"} 
      │                                            │
      │                                            ▼ ❌G-B缺口: 只 logger.warning + record_evolution_event
      └─► observer.record_evolution_event ─► model_evolution表    (无 restore/activate 真正切换版本)

【G-A 新建 — 旁路只读, 反向监督】

  Hermes监督器 ══(只读)══► orchestration_memory.json (scenarios进化)
              ══(只读)══► bcrm_trades.db (model_evolution审计 / performance_snapshots绩效)
              ══(只读)══► engine.evolve输出 (EvolutionReport)
              └─► 审计闸 + 告警 (旁路观测, 不阻断上线 ✓符合MEMORY"监督者非审批者")

【波及高风险路径】
  G-B回滚执行 → 切换 model_versions.status='active' → auto_trader(L392 import) 加载新模型 → 实盘交易
       ⚠️ 与 MEMORY"子系统交易参数进化需审批/V9基线不可改" 冲突 → G-B执行必须带审批门禁
```

---

## 三、文件清单

### 修改文件
| 文件 | 变更类型 | 规模 | 复杂度 | 风险 |
|:---|:---|:---:|:---:|:---:|
| `cli/bcrm2_scheduler.py` | G-B: 补回滚执行器(restore/activate version_id + 版本定位 version_from→to) | 中 | 中 | **高**(涉auto_trader交易) |
| `core/memory/orchestration_memory.py` 或 `evolution/engine.py` | G-C: update_from_evolution(L332)进化时落审计(复用model_evolution event_type='orchestration_evolve' 或新表) | 小 | 低 | 中 |
| `[Hermes新模块]` (G-A) | 旁路只读观测器(读json+db+evolve输出→审计闸/告警) | 中 | 中 | 低(只读旁路) |

### 参考文件（只读不改）
| 文件 | 用途 | 说明 |
|:---|:---|:---|
| `evolution/engine.py` | evolve触发/update_from_evolution调用(~L177) | G-C接入参照 |
| `core/memory/orchestration_memory.json` | scenarios进化状态 | G-A观测源(运行时) |
| `data/bcrm_trades.db` | model_evolution(L761)/performance_snapshots(L773) | G-A观测源/G-C审计参照 |
| `core/sense/complexity_classifier.py` | 现有Hermes委托模式(T3 delegate_hermes) | G-A接入风格参照(方向相反) |
| `cli/scheduler.py` | use_hermes开关(L419=False) | G-A潜在接入点 |

---

## 四、配置/数据影响

- **orchestration_memory.json** (`core/memory/`, L68): scenarios 进化状态。G-A 只读观测；G-C 若在 update_from_evolution 加审计字段→可能扩 schema。
- **bcrm_trades.db** (`data/`, L110): 6表已存在且在写。G-C 给编排进化补审计 → 复用 `model_evolution`(event_type 区分) 或新建编排审计表（Z2 决策）。
- **硬编码常量**（需提取/关注）:
  - `check_rollback_candidates`: `min_win_rate=0.4` / `min_sharpe=0.0` (L856-857)
  - `update_from_evolution`: `is_sparse = sample_count < 10` (L348)
  - `MIN_TRADES_FOR_EVAL` / `GRAPH_PATTERNS`(5种编排模式) — engine 层
- **无新 config/env**: G-A 旁路读现有文件，不引入新配置。

---

## 五、扫描可信度

| 维度 | 可信度 | 已坐实(✅直接证据) | 未验证项(⚠️/❌) |
|:---|:---:|:---|:---|
| 入口 | ✅高 | run_hourly_sacg(L874)/update_from_evolution(L332)/check_rollback(L855)/save_model_version(L278)/record_evolution_event(L788) read_file坐实 | evolve()的3个外部触发点(auto_trader等)本轮未重读，依赖前轮⚠️ |
| 结构 | ✅高 | 4文件 import 依赖链 read_file | Hermes新模块未建，cron/gateway接入点待Z2定⚠️ |
| 数据 | ✅高 | 全仓grep CREATE坐实6表(含L761/L773)；json/db路径坐实 | orchestration_memory.json 运行时实际内容未读⚠️ |
| 历史 | ❌低 | — | git log 近30天对3文件**空**：无法判断演进史/回退记录❌ |

---

## 六、冲突检测

1. ⚠️ **认知修正(已处理)**: "缺表致命Bug"误判被全仓grep推翻(L761/L773建表+L874实际调用)。审计/回滚检查为LIVE链路。
2. **_plan残留冲突**: 8-29上任务z1~z4产物在`_plan/`，本报告覆盖z1；z2/z3/z4旧文件待各阶段覆盖（旧任务已完成）。
3. 🔴 **G-B审批边界冲突(关键, Z2须处理)**: 自动回滚=切换active模型→auto_trader(L392)实盘交易。与MEMORY"子系统交易参数进化需审批/V9基线不可改"冲突。**G-B回滚执行必须带审批门禁**，不可像OS编排进化(evolve)那样自动上线。→ G-B 与 G-A/G-C 风险层级不同。
4. **双进化审计不统一(G-C核心决策)**: 子系统模型进化有 model_evolution 审计；OS编排进化(update_from_evolution)只写json无审计。G-C须明确：复用 model_evolution(event_type='orchestration_evolve') vs 新建编排审计表。
5. **G-A方向反转**: 现有 DreamOS→Hermes(T3委托分析)；G-A 是 Hermes→DreamOS(旁路观测进化)，反向新链路，无现成集成点(仅 use_hermes=False 开关)。

---

## Z1 自检三问
- [x] 每维≥3点（入口5函数 / 结构4文件import / 数据6表+json+3硬编码 / 历史git log 3文件）
- [x] 影响图标注波及路径（engine→orchestration_memory→json；run_hourly→observer→db；**G-B回滚→auto_trader交易**高风险）
- [x] 标注直接证据vs推断（✅read_file/grep坐实 vs ❌git历史弱 vs ⚠️修正的误判）
- [x] 前置查 feedback-e2.md（不存在→正常扫描；发现_plan残留→冲突#2记录）

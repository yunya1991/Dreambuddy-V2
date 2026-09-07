# 9基本面 7 引擎 S/A 级 · dao/tian 乘法增量 Shadow Boost Spec

> **版本**: v1.0
> **日期**: 2026-08-29
> **状态**: 📝 Draft（待用户 Review → ✅ Approved → 🏗️ 落地）
> **定位**: 11-易经推理系统 L0 五计层增量增强（9基本面 6 大算法资产库 7 引擎全量挂载，S/A 分层 Shadow 模式）
> **优先级**: P0-4（战略层 thaw_count 持续 0 的根本修复第二弹，接 P0-3 Odaily 集成后的深度量化增强）
> **关联规范**:
> - [0-系统文档管理/1-规范体系/DOC_STANDARD.md](../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) v2.0
> - [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.5（七层决策栈 L0 五计）
> - 先例 Odaily：[2026-08-29-odaily-policy-tian-integration-spec.md](./2026-08-29-odaily-policy-tian-integration-spec.md) v1.0 ✅ Approved（已生产应用 17 TC GREEN）
> - 先例 CBR Shadow：[2026-08-23-cbr-ema-winprob-enhancement-spec.md](./2026-08-23-cbr-ema-winprob-enhancement-spec.md)（方案 C 8 开关 + Shadow 模式）
> - **配套文档**：[Tasks](./2026-08-29-fundamental-7engines-daotian-boost-tasks.md) / [CheckList](./2026-08-29-fundamental-7engines-daotian-boost-check_list.md)

---

## 🎯 Executive Summary（执行摘要）

### 三句话结论
1. **现状（定量）**：P0-3 Odaily 阶段 2 完工并 shadow 验证后，dao/tian 乘法因子 4 个乘法位（×(1+_pn)×(1+_od)）仅利用了「派生字段 7 个 + 基础情绪政策三 delta」；9基本面 算法资产库里 6 大 S/A 级引擎（SentimentEngine / EventLedger / NewsContract Schema / EventMappingPolicy / NarrativeAnalyzer 5 件 S 级 + SignalEngine._adaptive_weight + ThreeDimensionalResistance 2 件 A 级，共 **7 件**）尚未实际发挥作用，**真五维 dao 政策量化深度缺口** 约 60%。
2. **方案路径（6 项关键决策已全部用户审批）**：
   - **注入策略 = 方案 B**：S/A 分两个独立乘法因子：S 级 5 件 δ∈[-0.1, +0.1] + A 级 2 件 δ∈[-0.05, +0.05]，与现有 pn×od 乘法独立叠加：`×(1+_pn)×(1+_od)×(1+_fd_S)×(1+_fd_A)` → 联合顶≈1.5246 倍，clamp [0, 100]
   - **Shadow 策略 = 方案 A（独立双开关双 JSONL 双门槛）**：新增 `enable_fundamental_7engines_boost=False`（类属性红线，env FUND_7ENGINES_BOOST=1 打开）；新增独立 `fundamental_7engines_records.jsonl`；新增 **7 门槛 G1-G7**（hit_rate≥60%、thaw_acc≥70%、sharpe≥1.05、IMPORT_FAIL=0、S_ACCURACY≥75%、A_CONSISTENCY≥60%、SCHEMA_PASS_RATE≥95%）；样本≥1500 后才允许评估；7 日历天观察期。
   - **S 级 5 delta 聚合 = 方案 A（加权求和 clamp [-0.1, +0.1]，对齐 Odaily §5.2.3 三 delta 范式）**：dao D1~D5 / tian T1~T5 各自加权求和后独立 clamp；单引擎异常→该引擎 delta=0（FAIL-OPEN 隔离）。
   - **A 级 2 delta 聚合 = 方案 A（语义绑定）**：ThreeDimensionalResistance → 只注入 dao（`sign(direction) × (0.01 + |v|×0.02 + |a|×0.01) × conf ∈ [-0.04, +0.04]`）；SignalEngine._adaptive_weight → 只注入 tian（`(w_ratio - 1) × 0.03 clamp [-0.02, +0.02]`）；两者天然满足 A 级±0.05 外边界。
   - **op 脚本 4 引擎 import = 方案 A（9基本面/engines/ 建 4 薄封装代理模块）**：新建 `event_ledger_engine.py / event_mapping_engine.py / narrative_engine.py / news_contract_validator.py` 四个代理，sys.path.insert 注入 ops/nanoclaw 子目录路径，FiveDomainFeatureComputer 内统一 `from engines.xxx import Yyy` 调用（与现有 Sentiment/Signal/3D 三引擎同一 import 模式）。
   - **news_list 输入 = 方案 A（boost 方法内 SQLite 读 records 72h）**：`_fd_S_xxx_boost()` 内部 SELECT category='news' 72h 倒序 LIMIT 200，把 record.raw JSON 拼成 engines 用的 `news_list[dict]`；**不改变 compute(coin_data, system_state) 函数签名**（影响面最小）；DB/I/O 异常→FAIL-OPEN S/A delta 全 0。
3. **预期数值级改善**：S 级 5 引擎平均贡献 dao/tian ≈ ±0.05（中线 0.025 正）+ A 级 ±0.015，叠加 pn×od 后 **Day 7 庙算总分从 58 提升 2-3 分 → Day 10~12 跨 60 解冻阈值**；F→A 首点 7 日收益均值 +4.17%（上一轮已验证，本 Spec 旨在让首点更早到来且置信度更高）。

### 验收总纲（硬指标）
```
□ 阶段1（≈15 TC RED→GREEN）：
    ▶ 4 代理模块创建：event_ledger_engine / event_mapping_engine / narrative_engine / news_contract_validator
    ▶ 4 boost 方法：_fd_S_dao_boost / _fd_S_tian_boost / _fd_A_dao_boost / _fd_A_tian_boost
    ▶ 2 行乘法守卫（dao + tian ×(1+S)(1+A)）字节正确
    ▶ 红线关时 enable_fundamental_7engines_boost=False → 五维结果字节等价于 7 引擎不存在
    ▶ fx_r3_sample 命中：S_dao ∈[0.04,0.10] / S_tian ∈[0.04,0.10] / A_dao ∈[0.01,0.04] / A_tian ∈[0.01,0.02]
    ▶ FAIL-OPEN 单引擎隔离：4 引擎 ImportError 独立 → delta=0，不影响其他

□ 阶段2（≈10 TC RED→GREEN）：
    ▶ 红线默认 False TC：enable=False → 0 import 9基本面 / JSONL 0B / result 字节一致
    ▶ JSONL 9+字段 schema 齐全（ts_ms / asset_class_cnt / coin_classes / S_dao_boost_mean /
      S_tian_boost_mean / A_dao_boost_mean / A_tian_boost_mean / shadow_reason_code /
      import_fail_count / engine_detail）
    ▶ 原因码 5 枚举 TC 全覆盖：FD_OK / FD_NO_NEWS_BATCH / FD_IMPORT_ERROR /
      FD_PERMISSION / FD_GENERIC_ERR
    ▶ fd7engines_hitrate_eval.py 退出码三态正确：样本不足=2 / 门槛FAIL=1 / 全PASS=0

□ 7 日历天观察（polling_trader 注入 env FUND_7ENGINES_BOOST=1 后）：
    ▶ JSONL 累积 ≥1500 条（7 天 × 288 笔/天 ≈ 2016，75% = 1500）
    ▶ G1 hit_rate_effective ≥ 60%
    ▶ G2 thaw_accuracy      ≥ 70%
    ▶ G3 sharpe_annual      ≥ 1.05
    ▶ G4 IMPORT_FAIL_total  = 0
    ▶ G5 S_ACCURACY         ≥ 75%  （S1~S5 内部方向一致率）
    ▶ G6 A_CONSISTENCY      ≥ 60%  （3D vs Signal 符号一致率）
    ▶ G7 SCHEMA_PASS_RATE   ≥ 95%  （engine_detail S3_pass_rate 均值）
    ▶ 7 门槛全 PASS → PR + CR → enable_fundamental_7engines_boost 默认 True
```

---

## 1. 背景与问题陈述

### 1.1 现状（定量根因）
- **P0-3 完工后的乘法链**：dao/tian `×(1+_pn)×(1+_od)` 两因子，odaily_* 覆盖率 Day7≈40% → 真五维 tian≈49、dao≈51 → 总分≈52-56 → war_state 仍 FREEZE（或刚回冻 58 档），距解冻 3×60 门槛仍差 4-8 分/日。
- **9基本面 算法资产库利用率 < 10%**：7 大引擎中仅 SentimentEngine（Odaily collector 内轻量调用 1 次/条）与 least_resistance 3D 有少量离线脚本引用；EventLedgerGenerator / EventMapping / NarrativeAnalyzer / NewsContract Schema / SignalEngine._adaptive_weight 5 件在真实交易热路径中 0 次调用。
- **数据根因与信号深度**：Odaily 的 `_od_*_boost` 是「3 delta 基础浅层政策信号」（仅依赖 coin_data 7 个派生字段，无引擎结构化调用）；7 引擎挂载后提供的是「政策叙事生命周期 + 事件账本严重度/紧急度 + 合规通过率 + 政策类型分布 + 3D 物理趋势 + 模块自身贝叶斯准确率」6 个维度的结构化深度信号（平均比 Odaily 三 delta 深 3~4 层）。

### 1.2 复用资产（已 VERBOSE 定位 + API 签名确认）

| # | 引擎名 | 等级 | 位置 | import 方式 | 返回结构（确认）|
|---|---|---|---|---|---|
| S1 | SentimentEngine.analyze_text | **S** | `9-基本面分析/engines/sentiment_engine.py` | ✅ 直接 import | `{score∈[-1,1], sentiment, categories, matches}` |
| S2 | EventLedgerGenerator.generate_ledger(news_list) | **S** | `9-基本面分析/ops/nanoclaw/core_task1/scripts/event_ledger_generator.py` | 🆕 代理模块 | `List[EventLedgerEntry(13字段: severity/urgency/risk_action ...)]` |
| S3 | news_contract.schema.json 验证 | **S** | `9-基本面分析/ops/nanoclaw/core_task1/schema/news_contract.schema.json` | 🆕 代理模块（jsonschema.Draft7Validator） | pass_rate ∈ [0,1] |
| S4 | map_event_type(topic,cat,title,body) | **S** | `9-基本面分析/ops/nanoclaw/core_task1/scripts/event_mapping_policy.py` | 🆕 代理模块 | str ∈ 7 类枚举（monetary_policy/crypto_reg/us_policy/us_data/geopolitics/security/project） |
| S5 | NarrativeAnalyzer.build_narratives | **S** | `9-基本面分析/ops/nanoclaw/core_task1/narrative/scripts/narrative_analyzer.py` | 🆕 代理模块 | `List[Narrative(id,name,evidence_score,trajectory_strength∈[-1,1])]` |
| A6 | compute_resistance_3d(raw_score, history) | **A** | `9-基本面分析/engines/least_resistance.py` ✅ 直接 import | ✅ 直接 import | `{direction∈{up/neutral/down}, velocity=tanh∈(-1,1), acceleration=tanh∈(-1,1), confidence∈[0,1], data_points, trend_summary}` |
| A7 | SignalEngine._adaptive_weight(module_name) | **A** | `9-基本面分析/engines/signal_engine.py` ✅ 直接 import | ✅ 直接 import | float ∈ `[0.3×base, 2.0×base]` → w_ratio ∈ [0.3, 2.0] |

**3 直接 + 4 代理，合计 7 件，S 5 + A 2 ✅ 已确认。**

### 1.3 硬约束（不可违反，H1~H15 承接项目记忆 + 本 Spec 新增）
| # | 硬约束 | 来源 |
|---|---|---|
| H1 | FAIL-OPEN 铁律：热路径异常→中性兜底+6层堆栈日志，不阻塞交易；5min≥3 次 Lark 告警 | 项目 memory |
| H2 | 乘法因子独立叠加，顺序固定 `×(1+_pn)×(1+_od)×(1+_fd_S)×(1+_fd_A)`，不可合并为加法 | 本 Spec §2 方案 B 用户确认 |
| H3 | S 级 clamp [-0.1, +0.1]，A 级 clamp [-0.05, +0.05]（不可越界）| 本 Spec §3 设计 |
| H4 | enable_fundamental_7engines_boost 类属性默认 **False**（红线），7 门槛 + 样本≥1500 后，通过 PR+CR 才改 True | 本 Spec §4 Shadow A |
| H5 | Shadow 审计只读不改：`_fd_7engines_shadow_compute()` 绝对不修改 compute() 返回值 | 本 Spec H8 继承 |
| H6 | 9基本面 顶层采集层 (data_collector.py / flow_collector.py) 已 deprecated → 严禁扩展，新数据走 18-数据中心（本轮无新采集依赖，仅读 SQLite）| 项目 memory R1 |
| H7 | 战略层开关关断时，结果字节等价于开关不存在（乘法守卫跳过） | 项目 memory H3 |
| H8 | FAIL-OPEN **6 层**（L6→L1）：L6 顶层乘法守卫 / L5 shadow 大 try / L4 boost 方法 try / L3 DB try / L2 import try / L1 单引擎 delta try | 本 Spec §5.1 |
| H9 | 代码改动 PR + Code Review，非紧急不得直推 main | 项目 memory |
| H10 | 战略层代码修改后必须重启交易进程（清内存缓存 five_domain_state.json） | 项目 memory |
| H11 | SQLite records 查询必须 forward fill + max_gap=4hr（本 Spec 读 72h LIMIT 200）| 项目 memory H4 |
| H12 | 方案 C 8 开关（SW-C1~C8）默认 True（保持不变，本轮不涉及）| 项目 memory H2 |
| H13 | PnL 回写闭环（Agent B）不得因 7 引擎注入被破坏（无耦合，注入只读）| 项目记忆 PnL 闭环修复 |
| H14 | CBR/KNN θ_match*=0.71 shadow（并行独立 JSONL，与 7 引擎无关）| 项目记忆 |
| H15 | 7 门槛 G1-G7 必须**全部** PASS + 样本≥1500，缺一不可开开关（AND 逻辑非 OR）| 本 Spec §4.4 |

---

## 2. 方案对比与选择

> 6 项澄清问题已全部 6/6 用户审批通过（方案 B + AAAAA），下为选择理由汇总（不重新对比）。

| 维度 | 已选方案 | 关键选择理由 |
|---|---|---|
| 注入策略 | 方案 B（S/A 分两个乘法因子） | 避免了 S 级「政策大方向」与 A 级「验证信号」混为一谈；S 影响 ±10% 主方向，A 仅辅助 ±5% 微调，语义清晰 |
| Shadow 策略 | 方案 A（独立双开关双 JSONL 双门槛） | 与 Odaily 完全独立关断：可单独审计/单独关/单独上线；Oday 观察未完不影响 7 引擎进展 |
| S 级 5 delta | 方案 A（加权求和 clamp，对齐 Odaily） | 代码可直接从 `_od_dao_boost/_od_tian_boost` 复制改造，节省 200 行；FAIL-OPEN 语义工程级一致 |
| A 级 2 delta | 方案 A（3D→dao / Signal→tian 语义绑定） | 3D 物理趋势验证方向（dao=方向维度）；SignalEngine 模块准确率 = tian 政策可信度，语义映射自然 |
| 代理模块 | 方案 A（engines/ 建 4 薄封装） | sys.path.insert + import 统一模式，与 Odaily SentimentEngine 修复先例一致，import 错误易定位 |
| news_list 输入 | 方案 A（boost 内 SQLite 72h 查） | 不改 compute 签名（影响面 0）；DB 查询独立 try，FAIL-OPEN 自然隔离 |

---

## 3. 设计 Section 1：架构总览 + 乘法公式 + 4 因子范围

### 3.1 三层架构总览图（文字版）
```
┌──────────────────────────────────────────────────────────────────┐
│  ③ 审计层（Shadow 审计 · 默认关闭红线）                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ enable_fundamental_7engines_boost = False (类属性红线)    │    │
│  │   ↓ env FUND_7ENGINES_BOOST=1 才 True                   │    │
│  │ _fd_7engines_shadow_compute()  → 只读不改result           │    │
│  │   ↓ append JSONL                                          │    │
│  │ runtime/fundamental_7engines_records.jsonl (9+字段)      │    │
│  │   ↓ 7日历天后 fd7engines_hitrate_eval.py 算 G1-G7 7门槛   │    │
│  └─────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  ② 特征注入层（FiveDomainFeatureComputer · 乘法叠加）             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ compute_dao_raw()  compute_tian_raw()                    │    │
│  │   ×(1+_pn_boost)      ∈ [-0.20, +0.20]  ← 已有(不变)    │    │
│  │   ×(1+_od_boost)      ∈ [-0.10, +0.10]  ← 已有(不变)    │    │
│  │   ×(1+_fd_S_boost)    ∈ [-0.10, +0.10]  ← ✨新增S级5引擎 │    │
│  │   ×(1+_fd_A_boost)    ∈ [-0.05, +0.05]  ← ✨新增A级2引擎 │    │
│  │   clamp[0, 100]                                           │    │
│  │                                                           │    │
│  │ 新增4方法（签名对齐 _pn_*_boost / _od_*_boost）：         │    │
│  │   _fd_S_dao_boost(coin_data, system_state) → float       │    │
│  │   _fd_S_tian_boost(coin_data, system_state) → float      │    │
│  │   _fd_A_dao_boost(coin_data, system_state) → float       │    │
│  │   _fd_A_tian_boost(coin_data, system_state) → float      │    │
│  └─────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  ① 数据层（SQLite news + 9基本面7引擎 + 4代理模块）               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ SQLite data_center.db records 表                         │    │
│  │   WHERE category='news' AND ts >= now()-72h              │    │
│  │   ORDER BY ts DESC LIMIT 200 → news_list[dict]          │    │
│  │                                                           │    │
│  │ 9-基本面分析/engines/ (7件 → 3直接 + 4代理)              │    │
│  │   ├ sentiment_engine.py       (S1 ✅直接import)          │    │
│  │   ├ signal_engine.py          (A7 ✅直接import)          │    │
│  │   ├ least_resistance.py       (A6 ✅直接import)          │    │
│  │   ├ event_ledger_engine.py    (S2 🆕代理→ops/nanoclaw)  │    │
│  │   ├ event_mapping_engine.py   (S4 🆕代理→ops/nanoclaw)  │    │
│  │   ├ narrative_engine.py       (S5 🆕代理→ops/nanoclaw)  │    │
│  │   └ news_contract_validator.py(S3 🆕代理→schema验证)    │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 乘法总公式（dao / tian 对称）
```python
boost_pn   = _pn_dao_boost()          # 已有 ∈ [-0.20, +0.20]
boost_od   = _od_dao_boost()          # 已有 ∈ [-0.10, +0.10]，守卫 if enable_odaily_engine_boost
boost_fd_S = _fd_S_dao_boost()        # 🆕 新增 ∈ [-0.10, +0.10]
boost_fd_A = _fd_A_dao_boost()        # 🆕 新增 ∈ [-0.05, +0.05]

multiplier = 1.0
multiplier *= (1 + boost_pn)                                          # 恒启用
if self.enable_odaily_engine_boost:
    multiplier *= (1 + boost_od)                                      # Odaily 红线
if self.enable_fundamental_7engines_boost:
    multiplier *= (1 + boost_fd_S) * (1 + boost_fd_A)                # 7 引擎红线

dao_final = max(0.0, min(100.0, dao_raw * multiplier))               # clamp
```

### 3.3 4 因子范围表 + 联合顶/底校验
| 因子 | 来源 | 值域下限 | 值域上限 | 乘法守卫开关 |
|---|---|---|---|---|
| boost_pn | pn_* 字段派生（已有） | **-0.20** | **+0.20** | 恒启用（字段存在即注入） |
| boost_od | Odaily 引擎 3 delta（P0-3 完工） | **-0.10** | **+0.10** | `enable_odaily_engine_boost`（默认 False，env ODAILY_ENGINE_BOOST=1） |
| **boost_fd_S** | **S级 5 引擎 delta 加权和** 🆕 | **-0.10** | **+0.10** | `enable_fundamental_7engines_boost`（默认 False，env FUND_7ENGINES_BOOST=1） |
| **boost_fd_A** | **A级 2 引擎 delta 语义绑定** 🆕 | **-0.05** | **+0.05** | 与 fd_S 同一红线共进退 |

- **联合顶**：`1.2×1.1×1.1×1.05 = 1.5246` → 最终 clamp 截顶为 100 ✅
- **联合底**：`0.8×0.9×0.9×0.95 = 0.6156` → 单项 dao/tian 最低 ≥ 61.56% raw，不过压 ✅

---

## 4. 设计 Section 2：S/A 级 7 引擎 delta 详细算法

### 4.1 公共前置：news_list 拉取 + 引擎实例懒加载
`_fetch_news_72h_limit200()`：
```python
def _fetch_news_72h_limit200(self) -> List[Dict[str, Any]]:
    try:
        import sqlite3, json, time
        db_path = getattr(self, "_db_path", None) or _DEFAULT_DB_PATH
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        since = int(time.time()) - 72*3600
        cur.execute("""SELECT timestamp, metrics, raw FROM records
                       WHERE category='news' AND timestamp >= ?
                       ORDER BY timestamp DESC LIMIT 200""", (since,))
        rows = cur.fetchall()
        out = []
        for ts, metrics, raw in rows:
            try:
                raw_dict = json.loads(raw) if isinstance(raw, str) else (raw or {})
                item = {"timestamp": ts}
                if isinstance(raw_dict, dict):
                    for k in ("title", "description", "body", "source_id", "source_category"):
                        if k in raw_dict: item[k] = raw_dict[k]
                # metrics 里的关键词字段也带上
                if isinstance(metrics, str):
                    try: item.update(json.loads(metrics))
                    except: pass
                out.append(item)
            except:
                continue
        conn.close()
        return out
    except Exception:
        return []
```

- news_list 长度 < 10 时，S_dao / S_tian 直接 return 0.0（数据不足不扰动）；原因码 `FD_NO_NEWS_BATCH`（Shadow）。
- 7 引擎实例：`self._eng: Dict[str, Any]` 懒加载 dict，Key = "S1"/"S2"/"S3"/"S4"/"S5"/"A6"/"A7"；每个 try import，失败→None，对应 delta 全方法内始终=0。

### 4.2 S 级 5 delta：dao 维度（`_fd_S_dao_boost` → clamp [-0.1, +0.1]）
| # | 引擎 | 输入 | delta 公式 | 值域范围 | 设计说明 |
|---|---|---|---|---|---|
| D1 | S1 SentimentEngine | news_list 批分析 title+body → 加权均值 `s_mean ∈ [-1,+1]` | **D1 = s_mean × 0.06** | [-0.06, +0.06] | 整体市场情绪偏多/空，力度保守；对齐 Odaily D1 `(s-0.5)×0.16`（量级匹配 [-0.08, +0.08]） |
| D2 | S2 EventLedger | risk_diff = r_pos - r_neg ∈ [-1,1]；severity_weighted_mean ∈ [1,5] | **D2 = r_diff × 0.03 + (3 - severity_weighted_mean) × (-0.008)** | [-0.07, +0.06] | r_diff 正加分负减分；严重度均值超 3 越扣分（severity=5 时 -0.016） |
| D3 | S3 NewsContract Validator | pass_rate ∈ [0, 1] | **D3 = max(0, pass_rate - 0.80) × 0.02** | [0.0, +0.004] | 数据质量守卫：仅当 pass_rate>80% 微幅正向奖励（最高 0.004，质量差不减分只不加分） |
| D4 | S4 EventMappingPolicy | crypto_reg_ratio、monetary_ratio ∈ [0,1] | **D4 = (crypto_reg_ratio - 0.25) × (-0.08) + (monetary_ratio-0.15) × sign(s_mean) × 0.05** | [-0.06, +0.05] | 监管关注高峰(>25%)→-0.06；货币政策类>15%随情绪方向放±0.05 |
| D5 | S5 NarrativeAnalyzer | t_mean（trajectory_strength 加权）；n_cnt 叙事数 | **D5 = t_mean × 0.05 × min(1.0, n_cnt/3)** | [-0.05, +0.05] | 叙事越一致越跟随方向；n_cnt<3 压缩（孤证不成立） |

**聚合（对齐 Odaily 范式）：**
```python
deltas = [D1, D2, D3, D4, D5]
total = sum(deltas)
return max(-0.1, min(0.1, round(total, 6)))
```
顶/底校验：`上=0.224→截0.10；下=-0.24→截-0.10` ✅

### 4.3 S 级 5 delta：tian 维度（`_fd_S_tian_boost` → clamp [-0.1, +0.1]）
| # | 引擎 | 输入 | delta 公式 | 值域范围 | 设计说明 |
|---|---|---|---|---|---|
| T1 | S1 SentimentEngine | 仅政策类新闻（monetary/crypto_reg/us_policy）子集均值 `s_policy_mean`；p_cnt | **T1 = s_policy_mean × 0.08 × min(1.0, p_cnt/3)** | [-0.08, +0.08] | 政策类新闻权重更高（tian 管政策维度）；p_cnt<3 压缩 |
| T2 | S2 EventLedger | urgent_ratio（urgency≥4 ∨ severity≥4）；avoid_ratio（risk_action=hold/avoid） | **T2 = -urgent_ratio × 0.05 - avoid_ratio × 0.03** | [-0.08, 0.0] | 紧急事件 & 规避建议 → 防守减分（无加分，仅保守惩罚） |
| T3 | S3 NewsContract Validator | pass_rate ∈ [0,1] | **T3 = max(0, pass_rate - 0.80) × 0.02** | [0.0, +0.004] | 与 dao D3 同，数据质量微幅正向 |
| T4 | S4 EventMappingPolicy | 72h 事件数 / 7d 3batch 均值 - 1 → event_growth_ratio clamp [-1,1] | **T4 = clamp(event_growth_ratio, -1, 1) × 0.04** | [-0.04, +0.04] | tian 管「时效热度」：暴涨→政策频出→减；萎缩→平静→加 |
| T5 | S5 NarrativeAnalyzer | reg_traj（regulation_policy 类叙事 trajectory_strength）；evidence_score | **T5 = reg_traj × 0.04 × evidence_score** | [-0.04, +0.04] | 精准绑定「监管政策叙事生命周期」：叙事未成型(score 低)→压缩 |

**聚合（同范式，clamp [-0.1, +0.1]）**：`上=0.164→截0.10；下=-0.24→截-0.10` ✅

### 4.4 A 级 delta：dao 维度（仅 A6 3D → `_fd_A_dao_boost`）
语义绑定：dao = 方向维度，3D 阻力最小方向物理验证 → 只注入 dao，不碰 tian。

```python
# 输入：system_state._by_class[crypto_usdt].dao_history_14 最近 14 次 dao_raw 序列
# 退化：len<3 → A_dao_boost=0.0
r3d = compute_resistance_3d(raw_score, historical_scores)
dir_sign = +1 if r3d["direction"] == "up" else (-1 if r3d["direction"] == "down" else 0)
v = abs(float(r3d.get("velocity", 0)))      # tanh ∈ [0, 1)
a = abs(float(r3d.get("acceleration", 0)))  # tanh ∈ [0, 1)
conf = float(r3d.get("confidence", 0))       # ∈ [0, 1]
D6 = dir_sign * (0.01 + v*0.02 + a*0.01) * conf
D6 = max(-0.05, min(0.05, D6))  # 硬保险（天然顶 ±0.04）
return round(D6, 6)
```
值域：±0.04 ✅ 天然∈ [-0.05, +0.05]

### 4.5 A 级 delta：tian 维度（仅 A7 SignalEngine → `_fd_A_tian_boost`）
语义绑定：SignalEngine._adaptive_weight 是算法模块自身贝叶斯准确率 → 映射 tian 政策可信度（算法越准，政策维度子项加分，不准则谨慎减分）。

```python
se = self._signal_engine_singleton()   # try/except，失败返回 None→0.0
if se is None:
    return 0.0
w = se._adaptive_weight("five_domain_tian_policy")
w_ratio = w / 1.0                      # base=1.0，w ∈ [0.3, 2.0]
T7 = (w_ratio - 1.0) * 0.03
T7 = max(-0.02, min(0.02, T7))         # 独立 clamp ±0.02
return round(T7, 6)
```
值域：`w_ratio=2.0 → 0.03→截+0.02`；`w_ratio=0.3 → -0.021→截-0.02` ✅

---

## 5. 设计 Section 3：Shadow 审计层（独立 JSONL + 7 门槛）

### 5.1 红线开关命名 & 激活方式
- 类属性（写在 FiveDomainFeatureComputer 类定义下，与 enable_odaily_engine_boost 两行并行）：
  ```python
  class FiveDomainFeatureComputer:
      enable_odaily_engine_boost: bool = False
      enable_fundamental_7engines_boost: bool = False   # 🆕 红线默认关
  ```
- `__init__` 环境变量覆写：
  ```python
  env_val = os.environ.get("FUND_7ENGINES_BOOST", "")
  if env_val.strip().lower() in ("1", "true", "yes", "on"):
      self.enable_fundamental_7engines_boost = True
  ```
- compute() 顶层守卫（return 前，与 Odaily 守卫双行）：
  ```python
  if self.enable_fundamental_7engines_boost:
      try:
          self._fd_7engines_shadow_compute(coin_data, system_state, result)
      except Exception:  # noqa: BLE001  Shadow 永远 fail-open
          pass
  ```

### 5.2 JSONL 9+ 字段 schema
- **文件**：`scripts/runtime/fundamental_7engines_records.jsonl`（空占位 size=0B 初始）
- **每行 1 JSON 对象，sort_keys=True**

| # | 字段名 | 类型 | 含义 |
|---|---|---|---|
| 1 | `ts_ms` | int | 毫秒时间戳 |
| 2 | `asset_class_cnt` | int | result 资产类数量（通常 3） |
| 3 | `coin_classes` | List[str] | 资产类列表（升序） |
| 4 | `S_dao_boost_mean` | float | 跨类 S_dao_boost 均值（round 6） |
| 5 | `S_tian_boost_mean` | float | 跨类 S_tian_boost 均值 |
| 6 | `A_dao_boost_mean` | float | 跨类 A_dao_boost 均值 |
| 7 | `A_tian_boost_mean` | float | 跨类 A_tian_boost 均值 |
| 8 | `shadow_reason_code` | str | 原因码（见 5.3） |
| 9 | `import_fail_count` | int | 7 引擎中 import 失败件数（0~7） |
| 10 | `engine_detail` | Dict[str, Any] | 7 引擎细分诊断（S1_sent_mean/S2_r_diff/S3_pass_rate/S4_crypto_reg_ratio/S5_reg_traj + S5_n_cnt + A6_direction_sign + A6_confidence + A7_w_ratio + news_batch_size）|

### 5.3 原因码 5 枚举（FD_* 前缀，优先级覆盖顺序）
| 枚举 | 含义 | 触发 | import_fail_count |
|---|---|---|---|
| `FD_OK` | 正常 | 7 引擎 import OK + news≥10 + S/A delta 无异常 | 0 |
| `FD_NO_NEWS_BATCH` | 新闻批次 <10 | SQLite 72h 新闻 <10（数据供给）| 0 |
| `FD_IMPORT_ERROR` | 7 引擎任一 import 失败 | 3 直接 + 4 代理，≥1 失败 | ≥1（具体件数） |
| `FD_PERMISSION` | JSONL 写权限失败 | open(jsonl, "a") 抛 PermissionError | 0 |
| `FD_GENERIC_ERR` | 未知异常兜底 | shadow_compute 最外层大 except 命中 | 0 |

### 5.4 7 门槛 G1-G7（AND 逻辑，必须全 PASS）
| # | 门槛 | 阈值 | 计算方式 |
|---|---|---|---|
| G1 | **hit_rate_effective** | ≥ **60%** | `FD_OK数 / (总行数 - FD_NO_NEWS_BATCH数) ≥ 0.60`（减空窗分母，避免误伤） |
| G2 | **thaw_accuracy** | ≥ **70%** | FD_OK 中日级 (S_dao+S_tian+A_dao+A_tian)/4 连续 3 日≥0.005 的窗口，war_state thaw_count 真值命中率 ≥ 70%（缺解冻标签时用连续 3 日正贡献窗口率代理） |
| G3 | **sharpe_annual** | ≥ **1.05** | 日级四 boost 均值 / 标准差 × √252 ≥ 1.05（标准差 +1e-9 防除 0） |
| G4 | **IMPORT_FAIL_total** | = **0** | JSONL 全量 `import_fail_count` 累加和 = 0 |
| **G5 🆕** | **S_ACCURACY** | ≥ **75%** | FD_OK + news_batch_size≥20 行中，S1_sent_mean / S2_r_diff / S5_reg_traj 三符号全一致（全正 or 全负）的比率 ≥ 75%（S 级内部方向共识度） |
| **G6 🆕** | **A_CONSISTENCY** | ≥ **60%** | FD_OK 行中，A6_direction_sign 与 sign(A7_w_ratio - 1.0) 符号一致率 ≥ 60%（中性自动算一致） |
| **G7 🆕** | **SCHEMA_PASS_RATE** | ≥ **95%** | 全部 FD_OK 行 engine_detail.S3_pass_rate 算术均值 ≥ 0.95（Odaily/BlockBeats/Panewslab 结构稳定性门禁） |

**退出码（脚本 fd7engines_hitrate_eval.py）：**
- exit=0 ✅：7 门槛全 PASS & 样本≥1500 → PR+CR 开开关
- exit=1 ❌：样本≥1500 但门槛有 FAIL → 继续观察/修复
- exit=2 ⏳：样本<1500（观察期不够）→ 继续累积

---

## 6. 设计 Section 4：FAIL-OPEN 分层 6 级 + TDD TC 矩阵

### 6.1 FAIL-OPEN 6 级分层（顶层到底层隔离）
```
L6 compute() 顶层守卫：开关关 → S/A 不乘 → 字节等价 7 引擎不存在
  │  实现：if enable_fundamental_7engines_boost 才 ×(1+S)(1+A) 和 shadow_compute
L5 _fd_7engines_shadow_compute() 大 try 吞
  │  实现：整函数体一个大 try/except Exception → reason=FD_GENERIC_ERR
L4 boost 方法各自外层 try 吞（S_dao / S_tian / A_dao / A_tian 4 方法独立）
  │  实现：每方法开头 try: ... except Exception: return 0.0
L3 SQLite news_list 查询 try 吞（嵌入 S_dao / S_tian 内）
  │  实现：_fetch_news_72h_limit200() 内部 try sqlite3 → []；shadow reason FD_NO_NEWS_BATCH
L2 7 引擎 import 级 try 吞
  │  实现：7 引擎各自独立 try import/构造，失败→该引擎方法内 delta 一直=0；计数≥1→FD_IMPORT_ERROR
L1 单引擎 delta 内部 try 吞（S1~S5/A6/A7 各独立 try/except）
     实现：每个 D1~D5/D6/T7 局部 try/except，异常→delta=0；其他 6 个照常
```

### 6.2 TDD TC 矩阵（约 25 TC = 阶段1 15 + 阶段2 10）

#### 阶段1：`tests/test_fd7engines_stage1.py`（15 TC）
| TC | 名称 | 关键断言 |
|---|---|---|
| 1 | `fx_None / 空 news_list → S_dao=0 / S_tian=0` | `_fd_S_dao_boost(None, {}) == 0.0`；S_tian 同理 |
| 2 | 红线关字节一致 | enable=False → compute() 结果与 baseline 字节 == |
| 3 | S_dao 正向命中（fx_positive_news） | `0.03 ≤ S_dao ≤ 0.10` |
| 4 | S_dao 负向命中（fx_negative_news） | `-0.10 ≤ S_dao ≤ -0.02` |
| 5 | S_tian 政策情绪命中（政策类≥5 条） | `0.03 ≤ S_tian ≤ 0.10` |
| 6 | S_tian 紧急事件惩罚（urgent_ratio≥0.4） | `-0.08 ≤ S_tian ≤ -0.01` |
| 7 | S 级 clamp 边界（正极端=0.10，负极端=-0.10） | `== pytest.approx(0.10, abs=1e-6)` / `-0.10` |
| 8 | A_dao 正（dao_history_up） | `0.005 ≤ A_dao ≤ 0.04` |
| 9 | A_dao 负（dao_history_down） | `-0.04 ≤ A_dao ≤ -0.005` |
| 10 | A_dao neutral（全 50） | `≈ 0.0 (abs ≤ 0.001)` |
| 11 | A_tian 正（SignalEngine 准，w_ratio=1.8） | `0.015 ≤ A_tian ≤ 0.02` |
| 12 | A_tian 负（SignalEngine 不准，w_ratio=0.4） | `-0.02 ≤ A_tian ≤ -0.01` |
| 13 | 乘法联合 clamp 上限（pn=+0.2/od=+0.1/S=+0.1/A=+0.05）→ dao_raw=80 → `dao_final=100` 精确 | `assert dao_final == 100` |
| 14 | 单引擎 FAIL-OPEN 隔离（S3 ImportError mock）→ 该 delta=0，S_dao ∈ [-0.1, 0.1] 不抛 | 无 Exception，S_dao 正常区间 |
| 15 | **fx_r3_sample 双点命中**：正向 news + dao_hist_up + 信号准 → S_dao ∈ [0.04, 0.10] / A_dao ∈ [0.01, 0.04] / S_tian ∈ [0.04, 0.10] / A_tian ∈ [0.01, 0.02]；乘法差 ≤ 1e-6 | 4 区间 + 乘法精确 |

#### 阶段2：`tests/test_fd7engines_shadow_stage2.py`（10 TC）
| TC | 名称 | 关键断言 |
|---|---|---|
| 1 | 红线默认 False：类属性 `is False`；enable=False 不写 JSONL；result 字节相等 | 文件未创建；`result == baseline` |
| 2 | enable=True + fx_r3_sample → JSONL 字段齐全：9+字段全含；reason=`FD_OK`；`import_fail_count=0` | 字段存在校验 |
| 3 | FD_NO_NEWS_BATCH：DB 查询返回 5 条 → reason=FD_NO_NEWS_BATCH；S/A mean=0 | 原因码正确 |
| 4 | FD_IMPORT_ERROR：monkeypatch 挡 event_ledger 代理 import → reason=FD_IMPORT_ERROR；`import_fail_count ≥ 1` | 原因码正确 |
| 5 | FD_PERMISSION：mock open("a") 抛 PermissionError → compute 不抛；字节稳定 | 不崩 |
| 6 | FD_GENERIC_ERR：mock `_fetch_news_72h` 抛 RuntimeError → 仍写 1 条 JSONL（reason=FD_GENERIC_ERR）| 原因码正确 |
| 7 | Shadow 只读验证：enable=True vs False → `result_true == result_false`（字节完全一致）| 结果一致 |
| 8 | engine_detail 字段齐全：S3_pass_rate∈[0,1]；A6_direction_sign∈{-1,0,1}；A7_w_ratio∈[0.3,2.0] | 合法范围 |
| 9 | 7门槛脚本退出码=2（样本不足）：10 条 JSONL 喂脚本 → `returncode == 2` | exit=2 |
| 10 | 7门槛脚本 G4 FAIL（import_fail=1，样本 2000）→ returncode == 1；stdout G4 ❌ FAIL | exit=1 + grep FAIL |

### 6.3 TDD 6 大硬约束
1. **NO PROD CODE WITHOUT FAILING TEST FIRST**：每个 GREEN 之前必须先有对应 TC RED（pytest FAIL 证据）
2. **红线类属性永不默认 True**：Spec通过 + PR+CR + 7天样本+7门槛全 PASS 前，永远 False
3. **阶段1→阶段2 顺序推进**：阶段1 15 TC GREEN → 才允许阶段2 TCs
4. **25 TC 通过 ≠ 可上生产**：仍需 7 天观察 + eval exit=0
5. **4 代理模块 NOT EXISTS 是 RED 证据**：阶段1 TC-14 前先断言 Path 不存在
6. **FAIL-OPEN L1~L6 每层至少 1 TC**：L6=TC-2 / L5=TC-6 / L4=TC-1 / L3=TC-3 / L2=TC-4 / L1=TC-14（6 层全覆盖 ✅）

---

## 7. 变更文件清单（按阶段）

### 7.1 阶段1（新建/修改）
| # | 操作 | 路径 | 说明 |
|---|---|---|---|
| 1 | 🆕 新建 | `9-基本面分析/engines/event_ledger_engine.py` | 代理：sys.path.insert + `from ops.nanoclaw...event_ledger_generator import EventLedgerGenerator`；封装 `generate_ledger(news_list)` → try/except→[] |
| 2 | 🆕 新建 | `9-基本面分析/engines/event_mapping_engine.py` | 代理：封装 `map_event_type(title, body)` → try/except→"market_analysis" |
| 3 | 🆕 新建 | `9-基本面分析/engines/narrative_engine.py` | 代理：封装 `build_narratives(news_list)` → try/except→[] |
| 4 | 🆕 新建 | `9-基本面分析/engines/news_contract_validator.py` | 代理：加载 news_contract.schema.json → `validate_batch(news_list) → pass_rate` |
| 5 | ✏️ 修改 | `11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py` | (a) 新增 `enable_fundamental_7engines_boost: bool = False` 类属性；(b) `__init__` 读 env FUND_7ENGINES_BOOST；(c) 新增 `_fetch_news_72h_limit200()`；(d) 新增 4 boost 方法（§4 算法）；(e) compute() dao 乘法加 `×(1+S)(1+A)` 守卫；(f) compute() tian 乘法加 `×(1+S)(1+A)` 守卫 |
| 6 | 🆕 新建测试 | `11-易经推理系统/tests/test_fd7engines_stage1.py` | TDD 阶段1 15 TC |

### 7.2 阶段2（新建/修改）
| # | 操作 | 路径 | 说明 |
|---|---|---|---|
| 7 | ✏️ 修改（同上文件） | `five_domain_feature_computer.py` | (g) 新增 `_fd_7engines_shadow_compute()`（§5.2-5.3 流程 + JSONL append）；(h) compute() return 前加 shadow 守卫 if enable + try/except 吞；(i) 懒加载 7 引擎 dict；(j) 暴露 `_fd_shadow_jsonl_path` 可覆写属性（TC 用 tmp_path） |
| 8 | 🆕 空占位 | `11-易经推理系统/scripts/runtime/fundamental_7engines_records.jsonl` | 0B 空文件（touch），.gitignore 若 runtime 已 ignore 则跳过 |
| 9 | 🆕 新建测试 | `11-易经推理系统/tests/test_fd7engines_shadow_stage2.py` | TDD 阶段2 10 TC |
| 10 | 🆕 新建脚本 | `11-易经推理系统/scripts/memory_l4/fd7engines_hitrate_eval.py` | 7 门槛评估脚本（退出码 0/1/2 + 表格输出 + 报告 JSON） |

### 7.3 运维注入 + 收尾（eval 通过后）
| # | 操作 | 路径 | 说明 |
|---|---|---|---|
| 11 | ✏️ 修改 | `start_trading.sh` / `polling_trader_live_300s.sh` | export FUND_7ENGINES_BOOST=1（7 天观察期开始） |
| 12 | 运维重启 | polling_trader 进程 | 清 five_domain_state.json + 重启（战略层代码改后 H10） |
| 13 | PR+CR（7 门槛全 PASS 后） | `five_domain_feature_computer.py` | 改 `enable_fundamental_7engines_boost: bool = True`，附带评估报告链接 |
| 14 | 文档更新（T-DOC） | CHANGELOG / ENGINEERING_INDEX / README / DOC_DEBT_INDEX | 5 文档销项（对齐 P0-3 T40 先例） |

---

## 8. 风险与回滚

### 8.1 风险清单
| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| 4 代理模块 import 路径错（ops/nanoclaw 深目录）| 中 | FD_IMPORT_ERROR=4，S delta 恒 0，A delta 仍工作 | 阶段1 TC-14 已隔离；Shadow G4 IMPORT_FAIL=0 是硬门槛，上线前必然发现 |
| SQLite records 表 schema 变更导致 raw 解析失败 | 低 | news_list=[] → S delta=0，A 仍工作；reason FD_NO_NEWS_BATCH | _fetch_news 内每条 try/except，单条失败不影响其余 |
| 7 门槛 G5/G6 阈值过严导致迟迟过不了 | 中 | 开关延迟 7-14 天打开（可接受） | 可手动执行 fd7engines_hitrate_eval.py 定期看每项实际值；若连续 21 天 ≥55% 但 <60%，可通过 Spec v1.1 修订降低阈值（必须 PR+CR） |
| 3D 历史 dao_history_14 不存在（旧 system_state）| 中 | A_dao=0（非致命） | 退化链：用 `system_state._by_class[cls].get("dao_history_14") or system_state.by_dims.get("dao_score_roll_7") or []`；len<3 则 A_dao=0 |
| 联合乘法极端 1.5246 让 dao 常到 100 顶 | 极低 | 影响微弱（clamp 后 100 顶正确）| 设计阶段已验证 clamp 不超；TC-13 精确覆盖 |

### 8.2 回滚方案（1 分钟无损）
1. 紧急关断：`unset FUND_7ENGINES_BOOST`，重启 polling_trader → 红线恢复 False → S/A 乘法守卫立即跳过，结果字节等价未上线 ✅
2. 代码回滚（PR 级）：`git revert <commit_sha>` → 代码撤回类属性和 4 方法 → 不影响 data_center.db 存量数据（仅读不写） ✅
3. Shadow 数据保留：fundamental_7engines_records.jsonl 不移除，供事后审计失败根因 ✅

---

## 9. 验收总纲（总 Checklist 20+ 项，详见 -check_list.md）

```
阶段1（15 TC）✅   → 阶段2（10 TC）✅  → 7天观察 JSONL ≥1500 → 7门槛全 PASS
       ↓                    ↓                 ↓                   ↓
    4代理+4boost+2乘法  红线+Shadow+脚本  FUND_7ENGINES_BOOST=1   PR+CR 默认True
```

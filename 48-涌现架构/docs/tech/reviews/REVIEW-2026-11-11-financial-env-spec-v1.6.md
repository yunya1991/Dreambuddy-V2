# 评审报告 — SPEC-EMERGENCE-FINANCIAL-ENV v1.6（第二轮六维）

- 评审日期：2026-11-11
- 评审对象：[SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md](../SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md)（内容版本 v1.6，本轮修复后 v1.7）
- 评审依据：[REVIEW-CHECKLIST-v0.1.md](../REVIEW-CHECKLIST-v0.1.md) 六维检查清单
- 上轮报告：[REVIEW-2026-11-11-financial-env-spec-v1.1.md](./REVIEW-2026-11-11-financial-env-spec-v1.1.md)（结论：不通过，P0×4 / P1×3）
- 评审方式：文档 vs 仓库现实（逐项 grep/ls/sqlite 核验，不采信文档自述）
- 结论：**文档层「有条件通过」/ 工程准入「不通过」**。首轮 P0-1/P0-3/P0-4 已关闭；P0-2（数据前置）仍阻塞；新发现 5 处文档一致性问题，已当场修复（v1.6 → v1.7）。

---

## 0. 一句话结论

> 修复后的 SPEC 在**设计与引用层已经站得住**（45 统计函数、40 资产分类、9 域事件契约、VIX 双源全部实测存在且描述准确）；但**数据前置仍然不达标**——F&G 只有 36 天且最新数据停在 `2026-10-29`，S 层日级因子 13 天，40 读的 SQLite 也停在 `10-29`。`factor_gate.py` / `trials.jsonl` / `trace_id` 三段均未实现。**文档可以进入实施，v1 验收不可开始。**

---

## 1. 六维逐项结论

| 维度 | 上轮 | 本轮 | 关键证据 |
|---|---|---|---|
| 1 引用存在性 | ✅（1 处失真） | ✅ **通过** | 本轮 10 项引用全部实测命中（见 §2） |
| 2 数据资产健康度 | ❌ | ❌ **仍不通过** | F&G 36 天（`09-09→10-29`，落后 13 天）；S 层 13 天；SQLite 停在 `10-29` |
| 3 模型-数据版本一致性 | ❌ | ⚠️ **条件通过** | 本地代码 = 文档（P0-F 已落地）；云端实际运行版本仍未验证 |
| 4 存量资产盘点 | ❌ | ✅ **通过** | 45 统计函数 8/8 存在；`accumulation_gate.py` 职责已区分 |
| 5 门禁强制等级 | ⚠️ | ⚠️ **设计完备 / 实现 open** | `factor_gate.py`、`trials.jsonl`、CI 检查均不存在 |
| 6 主链可观测性 | ⚠️ | ⚠️ **契约完备 / 实现 open** | §7.7 已定义；`48-涌现架构/runtime/` 目录不存在，39 事件无 `sentiment` 键 |

**判定规则**：维度 2 为 ❌ 即工程准入不通过（与上轮一致，`insufficient_data` 是 §7.5 的硬判定）。

---

## 2. 维度 1：引用存在性 ✅

本轮重新核验（命令 + 结果）：

```
OK  18/.../chain/panewslab_collector.py:68      → ("fred", "VIXCLS", "VIX 波动率")
OK  9/.../scripts/market_data.py:175            → def fetch_vix()
OK  48-涌现架构/registry/accumulation_gate.py   → def check_e1() / def check_e4b()
OK  45/evaluators/finance/backtest.py           → probabilistic_sharpe_ratio / expected_max_sharpe
                                                 / deflated_sharpe_ratio / pbo_cscv
OK  45/evaluators/common/split.py               → embargo_length / purged_kfold / walk_forward
                                                 / verify_no_leakage
OK  18/.../chain/fear_greed_collector.py:31     → limit = params.get("limit", 0)  # 0 = 全部历史
OK  9/.../schema/news_contract.schema.json      → 存在
OK  9-基本面分析/engines/event_ledger_engine.py  → 存在
OK  9-基本面分析/engines/event_mapping_engine.py → 存在
OK  40-周期神经网络系统/asset_classes.py:55      → ASSET_CLASSES: dict[str, dict]
```

**上轮误判已纠正**：v1.1 称"VIX 未入 18 主采集链"是错的；实际 18 已采 FRED `VIXCLS`，与 nanoclaw Yahoo `^VIX` 构成两套口径。v1.6 §1.1 / G5 / §5.2.1 已如实改写。

**新增核验（本轮）**：`grep -rn "def .*vix"` 全仓仅 `market_data.py:175` 一处实现 → §5.2.1「全仓仅 1 处」的验收口径当前成立（但该实现还在 9 域，未按计划迁到 18）。

---

## 3. 维度 2：数据资产健康度 ❌（唯一阻塞项）

| 对象 | SPEC 表述 | 实测 | 判定 |
|---|---|---|---|
| crypto F&G | 36 天 | `COUNT(DISTINCT date)=36`，`MIN=2026-09-09`，`MAX=2026-10-29` | ❌ 样本不足 + 落后 13 天 |
| S 层日级因子 | 13 天 | 13 天（上轮结论未变） | ❌ |
| 39 语义事件 | 20927 条、100% `trader.log`、无 `sentiment` | 实测 keys = `[raw, source, symbol, term, timestamp, values]`；source 分布 `[('trader.log', 20927)]` | ✅ 描述准确 |
| Odaily 正文 | 3048 条中 2096 条缺 `description` | `odaily_newsflash` 3048 条 | ✅ 描述准确（缺正文数未重算） |
| 40 龙头 K 线 | 原写「产出物停滞 11-05」 | 实测 `asset_rotation/cycle_state/cross_asset_matrix` 的 `generated_at=2026-11-10` | ⚠️ **原表述已过期**（本轮已修，见 R2-04） |
| 数据后端 | 「云端 18 写 PG / 40 读 SQLite」 | 18 `sink_postgres.py` 默认 `postgres`；40 `scripts/db_access.py` 默认也是 `postgres`（`DATA_CENTER_BACKEND` 可切）；但本地 `data_center.db` 最新记录 `2026-10-29` | ⚠️ 代码层两端一致，**是否为云端 env 错配仍需上云核验** |

**结论**：P0-2 保持 open。§10.0 已把 D1-D5 与五道质量门禁文档化，方向正确；但**文档化不等于数据达标**，`D 的验收报告必须先于任何 factor verdict` 这条纪律必须保留。

---

## 4. 维度 3：模型-数据版本一致性 ⚠️

**本地侧 ✅**：
- `sentiment_engine.py` 已含 `FINBERT_ZH_LABEL_CONTRACTS`、`_FINBERT_ZH_DEFAULT_MODEL_ID = yiyanghkust/finbert-tone-chinese`、`_build_label_map_from_pipe()`，跨语言 fallback 已删除（`self._last_model = "unavailable"; return None`）。
- 与 SPEC P-4/G11/§10.1 P0-F 描述一致。

**云端侧 ⚠️（无法本地验证）**：
- SPEC 写「云端中文模型 = `yiyanghkust/finbert-tone-chinese`」，但本轮无云端访问证据。上轮 P0-3 的关闭依据是"用户在云端确认模型存在 + 本地代码已能正确映射"，**云端实际加载成功的证据仍缺**（需一次远端 `analyze_text(with_meta=True)` 回显 `model`）。
- 新增发现 R2-05：§7.7 硬约束 2 要求 `model` 只取四值，但实现 `_last_model` 返回的是完整 model id / 本地路径（`sentiment_engine.py:470/473`）→ **契约与实现不一致**。已在 §7.7 明确「归一化在 P0-A 落库层完成」，但需要在 P0-A 落地时补单测。

---

## 5. 维度 4：存量资产盘点 ✅

| 计划新建 | 存量核验 | 处置 |
|---|---|---|
| 统计函数（DSR/PBO/purged CV） | 45 评测系统 8 个函数全部存在 | ✅ 已改为接线复用（§7.5） |
| 因子 verdict 门禁 | `registry/` 已存在 `accumulation_gate.py`（`check_e1` / `check_e4b`） | ✅ 已区分职责：积累量 vs 统计显著性，禁止合并（§7.6.1） |
| 事件记录契约 | 9 域三套契约全部存在 | ✅ 方案 C：canonical = EventLedger entry（§3.0） |
| 龙头宇宙 | 40 `ASSET_CLASSES` 已定义 10 大类 | ✅ 投影而非另立（§2.3） |

**新增风险（P1）**：§7.6.4 的 E-2「外部模块无写权限」当前**无法成立**——48 域已有 10+ 个模块直接写 `verdict`（[emergence_metrics.py](../../../metrics/emergence_metrics.py)、[verdict_dashboard.py](../../../metrics/verdict_dashboard.py)、`experiments/*/evaluate.py`）。E-2 必须配合 E-4 的 CI 检查一起上线，否则"唯一入口"只是新增了第 11 个写入口。

---

## 6. 维度 5：门禁强制等级 ⚠️

**设计侧 ✅ 完备**：§7.5 七道关 + §7.6 唯一入口 / 五态 verdict / `trials.jsonl` / 四强制点 / 可审计绕过。

**实现侧 ❌ open**：

```
ls 48-涌现架构/registry/factor_gate.py   → No such file
ls 48-涌现架构/runtime/trials.jsonl      → No such file
ls 48-涌现架构/runtime/                  → No such directory
```

→ P0-D 未开工。在 `factor_gate.py` 落地前，任何"因子通过"的结论都不可信（含上轮引用的 F&G IC 结论）。

---

## 7. 维度 6：主链可观测性 ⚠️

**契约侧 ✅**：§7.7 五段 trace_id 透传表 + 三条硬约束 + 「3 次 grep 追到原始 URL」验收标准，设计合格。

**实现侧 ❌ open**：

| 环节 | 现状 | 证据 |
|---|---|---|
| E 采集 | 无 `event_id` / `available_at` 列 | 39 事件 keys 无这两个字段 |
| S 打分 | 无 `sentiment` 块 | `semantic_events.jsonl` keys = 6 个基础字段 |
| M/P 聚合 | 无 `runtime/dim_signals/` | 目录不存在 |
| J 因子 | 无 `runtime/factor_values/` | 目录不存在 |
| verdict | 无 `gate_version` / `trial_id` | `factor_gate.py` 不存在 |

**结论**：可观测性目前是"纸面契约"，需与 P0-A/P0-D 同批实现，否则后补成本更高（事件已落盘后补 `trace_id` 等于重跑）。

---

## 8. 本轮新发现与修复（v1.6 → v1.7）

| ID | 级别 | 问题 | 位置 | 处置 |
|---|---|---|---|---|
| R2-01 | P1 | 版本头仍写 `v1.0（提案稿，待用户裁决 P0 决策点）`，与 §13 v1.6 矛盾 | 文件头 L4 | ✅ 改 `v1.7（第二轮评审修订稿）` |
| R2-02 | P1 | 示例 `"model": "finbert2-zh"` 与 §7.7 四值契约 + P0-F 冲突（§3.4 示例 1 处、§4.1 硬约束 3 还有 1 处） | §3.4 / §4.1 | ✅ 两处均改 `finbert-tone-chinese` |
| R2-03 | P1 | `_last_model` 返回完整 id/本地路径，与「只接受四值」契约不一致 | §7.7 约束 2 | ✅ 明确归一化在落库层，引擎不改 |
| R2-04 | P1 | 「40 产出物停滞 11-05」已过期（实测 `generated_at=2026-11-10`）；未说明 SQLite 停在 10-29 | §10.0 D5 | ✅ 按实测改写 |
| R2-05 | P2 | §10.0 D1 只写「36 天」，未写数据区间与滞后 | §10.0 D1 | ✅ 补 `2026-09-09→10-29（落后 13 天）` |
| R2-06 | P2 | §0.1「现有情绪（ProsusAI/finbert）」未反映双模型现状 | §0.1 | ✅ 改为双 FinBERT |

---

## 9. P0 / P1 处置状态总表

| ID | 首轮结论 | 本轮状态 | 关闭条件 |
|---|---|---|---|
| P0-1 事件契约冲突 | open | ✅ **文档关闭**（§3.0 方案 C） | 实施时以 `event_schema_allowlist.txt` + CI 兜底 |
| P0-2 数据样本不足 | open | ❌ **仍 open** | F&G ≥2500 天、S 层 ≥250 天、D5 后端统一 |
| P0-3 中文→英文静默打分 | open | ✅ **代码关闭**（P0-F） | 需一次云端 `model` 回显作为运行证据 |
| P0-4 门禁无强制点 | open | ✅ **文档关闭**（§7.6） | `factor_gate.py` + `trials.jsonl` + CI 检查落地 |
| P1-1 VIX 双口径 | — | ✅ 文档关闭（§5.2.1） | 实现迁移到 18 后复验「仅 1 处」 |
| P1-2 无 trace 链路 | — | ⚠️ 契约关闭 / 实现 open | 与 P0-A/P0-D 同批 |
| **P1-3（新）** | — | ❌ open | 48 域 10+ 模块直写 verdict，E-2 必须配 E-4 CI 才成立 |

---

## 10. 准入判定

| 问题 | 回答 |
|---|---|
| 文档能否作为实施依据？ | **能**。引用真实、契约自洽、存量复用已核验；本轮 5 处一致性问题已修 |
| 能否开始 P0-D / P0-E 实施？ | **能**（这正是当前排期） |
| 能否开始任何因子 verdict 产出？ | **不能**。P0-2 未关闭，`factor_gate.py` 不存在 |
| 下一轮评审触发条件 | ① `factor_gate.py` + `trials.jsonl` + CI 检查落地；② D1/D5 回填完成并出质量报告；③ 云端 `model` 回显证据 |

---

## 11. 复现命令（供下一轮复核）

```bash
# 引用存在性
grep -n "VIXCLS" 18-数据获取中心/data_center/collectors/chain/panewslab_collector.py
grep -n "def fetch_vix" 9-基本面分析/ops/nanoclaw/core_task1/scripts/market_data.py
grep -n "^def " 48-涌现架构/registry/accumulation_gate.py

# 数据健康度
sqlite3 18-数据获取中心/data_center.db \
  "SELECT COUNT(DISTINCT substr(timestamp,1,10)),MIN(timestamp),MAX(timestamp) FROM records WHERE source='fear_greed';"
python3 -c "import json,collections;print(collections.Counter(json.loads(l)['source'] for l in open('39-金融语义蒸馏系统/semantic_events.jsonl') if l.strip()))"

# 门禁 / 可观测性实现
ls 48-涌现架构/registry/factor_gate.py 48-涌现架构/runtime 2>&1
grep -rln '"verdict"' 48-涌现架构 --include="*.py"
```

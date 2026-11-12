# 评审报告 — SPEC-EMERGENCE-FINANCIAL-ENV v2.8（第三轮）

- 评审日期：2026-11-12
- 评审对象：[SPEC-EMERGENCE-FINANCIAL-ENV-v2.8.md](../SPEC-EMERGENCE-FINANCIAL-ENV-v2.8.md)（文件名 v1.0 → 本轮重命名为 v2.8，内容版本 v2.8）
- 评审依据：[REVIEW-CHECKLIST-v0.1.md](../REVIEW-CHECKLIST-v0.1.md) 六维检查清单
- 上轮报告：[REVIEW-2026-11-11-financial-env-spec-v1.6.md](./REVIEW-2026-11-11-financial-env-spec-v1.6.md)（结论：文档层有条件通过 / 工程准入不通过）
- 评审方式：文档 vs 仓库现实（逐项 grep / ls / sqlite / 云端 PG 实测，不采信文档自述）
- 结论：**有条件通过**。v1.6→v2.8 期间 P0-A~P0-F、P1-A~P1-D、P2 真实数据首跑全部落地；原列 4 项阻断中 1 项经核实不成立（G14）、2 项本轮已修复（版本号 / leader_form.py）、1 项待决策（云端 venv）。因子全部 `inconclusive` 属如实记录，非缺陷。

---

## 0. 一句话结论

> v2.8 的代码与文档已对齐：G10 价格源统一、G14 F&G 接入 `records` 表（经核实**不是**读不存在的 `crypto_fear_greed` 表）、G15 S 层自动加载均已实现并实测；P 层形态 33 列、M 层 VIX+F&G、S 层语义事件、E 层事件四层齐备。**剩余唯一工程准入问题是云端测试环境（无 venv / pandas），需决策建 venv 或标注 dev-verified。** 因子全部 inconclusive 是 S/E 层历史覆盖不足的如实记录，符合 §7.5 统计纪律。

---

## 1. 六维逐项结论

| 维度 | 上轮(v1.6) | 本轮(v2.8) | 关键证据 |
|---|---|---|---|
| 1 引用存在性 | ✅ | ✅ **通过** | G14 `records(source='fear_greed')` 两端实测命中（见 §2） |
| 2 数据资产健康度 | ❌ | ⚠️ **条件通过** | F&G 本地 3203 天 / 云端 3825 行（2018-02-01~2026-11-12）；S 层 68 个标的×日期；E 层 74+231 事件；P 层依赖 11 域 kline 缓存 |
| 3 模型-数据版本一致性 | ⚠️ | ✅ **通过** | 本地代码 = 文档；leader_form.py 已同步云端 |
| 4 存量资产盘点 | ✅ | ✅ **通过** | 48 tests 326 passed（开发端）；regime / align / validate 三模块单测全绿 |
| 5 门禁强制等级 | ⚠️ | ✅ **通过** | `factor_gate.assert_gate()` + `trials.jsonl` + `factor_preregistration.json` 齐备；E-1~E-4 静态检查就位 |
| 6 主链可观测性 | ⚠️ | ⚠️ **条件通过** | `trace_id` 五段透传契约在；`runtime/` 目录存在；云端实测待 venv 建好后验证 |

**判定规则**：维度 2 为 ⚠️（F&G/S 层覆盖仍不足以支撑统计显著，但已如实记录为 inconclusive，不伪造结论），工程准入受维度 3/6 云端验证阻塞。

---

## 2. 维度 1：引用存在性 ✅（G14 专项核实）

**G14 原评审阻断**："regime.py 读不存在的 `crypto_fear_greed` 表"。

**本轮核实**（开发端 + 云端双侧）：

| 端 | 查询 | 结果 |
|---|---|---|
| 开发端 sqlite | `SELECT COUNT(*) FROM records WHERE sub_category='crypto_fear_greed'` | 3698 行（2018-02-01~2026-11-12） |
| 开发端 regime.py | `load_crypto_fng_history()` 实跑 | 3203 天（同日去重后），sample `2026-11-10 = {value:32.0}` |
| 云端 PG | `SELECT COUNT(*) FROM records WHERE sub_category='crypto_fear_greed'` | 3825 行（2018-02-01~2026-11-12） |
| 云端 PG | `SELECT DISTINCT source FROM records WHERE source LIKE '%fear%'` | `fear_greed` / `fear_greed_enhanced` |

**结论**：regime.py 实际 SQL 为 `SELECT timestamp, metrics FROM records WHERE sub_category = 'crypto_fear_greed'`（[regime.py:232-235](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/48-涌现架构/metrics/regime.py#L232-L235)），**读取的是 `records` 表的 `sub_category` 字段，不是独立的 `crypto_fear_greed` 表**。原阻断系文档 G14 描述"读 `crypto_fear_greed`"措辞歧义导致误判，**代码本身正确，两端均能正常工作**。

**已修复**：G14 描述与 §13 v2.8 变更记录均改为"读 `records` 表（`sub_category='crypto_fear_greed'`）"。

---

## 3. 维度 2：数据资产健康度 ⚠️

| 对象 | SPEC 表述 | 实测 | 判定 |
|---|---|---|---|
| crypto F&G | `records` 表 `sub_category='crypto_fear_greed'` | 开发端 3698 行 / 3203 天；云端 3825 行 | ✅ 覆盖充足（近 3 年 coverage 0.9991） |
| S 层语义事件 | 39 `semantic_events.jsonl` | 68 个（标的×日期）行 | ⚠️ 覆盖不足（仅 68 行，不足以支撑截面 IC 显著性） |
| E 层事件 | `events.jsonl` | sec_edgar 69 + macro_calendar 4 + fed_calendar 1 + 中文 231 | ⚠️ 传统金融事件仅 74 条，样本不足 |
| P 层形态 | 21 `leader_form.compute` 33 列 | 开发端 leader_form.py 存在；云端已同步 | ✅ 代码就位，数据依赖 11 域 kline 缓存 |
| VIX | 18 `vix_collector` FRED `VIXCLS` + CBOE `VIX3M` | 30 天 observed=22/gaps=[]/ok=true | ✅ |

**结论**：F&G 与 VIX 覆盖充足；S/E 层覆盖不足是事实，但 v2.8 已如实将因子判为 `inconclusive`（而非伪造显著性），符合 §7.5 统计纪律。**不构成阻断，构成"数据待回填"开放项。**

---

## 4. 维度 3：模型-数据版本一致性 ✅

**本轮修复项**：

1. **版本号统一**：文件名 `SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md` → `SPEC-EMERGENCE-FINANCIAL-ENV-v2.8.md`（`git mv` 保留历史）；同步更新 [README.md](../../README.md)、[factor_preregistration.json](../../configs/factor_preregistration.json)、[SPEC-9DOMAIN-HISTORY-CONTEXT-v1.1.md](../SPEC-9DOMAIN-HISTORY-CONTEXT-v1.1.md) 三处引用。reviews 历史报告与 `architecture_graph.json`（自动生成 artifact）不手动修改。

2. **leader_form.py 同步云端**：开发端 `21-特征工程中心/feature_hub/modules/leader_form.py`（7542B）→ 云端同路径，属主 `luke:luke`。`financial_env_validate.py` 通过 `sys.path.append(_LEADER_FORM_ROOT)` + `from leader_form import compute` 动态导入，FAIL-OPEN 降级。

---

## 5. 维度 4：存量资产盘点 ✅

- 48 tests：开发端 326 passed（含 `test_regime_schema` / `test_financial_env_align` / `test_financial_env_validate` / `test_factor_gate` / `test_no_direct_verdict_write`）
- `factor_gate.py`：`assert_gate()` 七步短路 + `record_trial` + `register_factor` + `write_verdict`，16 条单测
- `factor_preregistration.json`：`financial-env-prereg-v1`，L-A 5 条 + L-B 3 条，声明注册时未跑真实数据
- `trials.jsonl` / `factor_verdicts.jsonl`：存在于 `runtime/`

---

## 6. 维度 5：门禁强制等级 ✅

- 唯一入口 `assert_gate()`，五态 verdict（`candidate` / `candidate_weak` / `inconclusive` / `falsified` / `insufficient_data`）
- 四强制点：预注册检查、样本量 `MIN_N_OBS`、前视审计 `audit_lookahead()`、verdict 只能来自 `assert_gate()`
- 静态守护：`test_no_direct_verdict_write.py` 扫描禁止手写 verdict 字面量
- 可审计绕过：bypass 留痕

---

## 7. 维度 6：主链可观测性 ⚠️（云端验证阻塞）

**契约层 ✅**：`trace_id` 五段透传（spec §7.7），`runtime/regime/*.json` 285 日已回写，`financial_env_report.json` 含 `price_source` 溯源块。

**云端验证 ⚠️**：云端无 `venv-trading`、无 `pandas`，48 tests collection error。**待决策**：
- 方案 A：云端建 venv + 安装依赖，跑完整测试套件
- 方案 B：标注测试声明为 `dev-verified`（开发端 326 passed 已验证，云端不跑测试）

---

## 8. 阻断项处置汇总

| # | 原阻断 | 核实结果 | 处置 |
|---|---|---|---|
| 1 | 版本号不一致（文件名 v1.0 / 内容 v2.8） | 属实 | ✅ 已修复：重命名为 v2.8 + 更新 3 处引用 |
| 2 | G14 引用不存在的 `crypto_fear_greed` 表 | ❌ **不成立** — 代码读 `records` 表 `sub_category`，两端实测命中 | ✅ 已修复：文档描述改为 `records` 表（`sub_category='crypto_fear_greed'`） |
| 3 | leader_form.py 云端缺失 | 属实 | ✅ 已修复：scp 同步云端，属主 luke:luke |
| 4 | 云端无 venv 测试无法跑 | 属实 | ⚠️ 待决策：建 venv（A）或标注 dev-verified（B） |

---

## 9. 开放项（非阻断）

1. **S/E 层历史覆盖不足**：S 层仅 68 个标的×日期，E 层传统金融事件仅 74 条 → 因子全部 `inconclusive`。需云端回填 39 语义事件与 18 传统金融事件采集。
2. **本地 fear_greed 粒度混合**：495 条小时级旧行与日级行混合（36 天重复），待清理（破坏性操作未获授权）。
3. **architecture_graph.json 引用旧路径**：自动生成 artifact 含 8 处 `v1.0` 引用，下次 `build_d2_architecture_graph.py` 重跑即更新。
4. **reviews 历史报告断链**：`REVIEW-2026-11-11-financial-env-spec-v1.1.md` 与 `v1.6.md` 引用 `../SPEC-EMERGENCE-FINANCIAL-ENV-v1.0.md`，重命名后链接失效。历史报告不改（保留评审时的真实引用），建议在 v1.1/v1.6 报告头部加一行"注：被评审文件已重命名为 v2.8"。

---

## 10. 评审结论

**有条件通过**。条件：

1. 维度 6 云端测试环境决策（建 venv 或标注 dev-verified）须在 v2.9 前落地
2. S/E 层历史回填作为独立开放项跟踪，不阻塞 v2.8 通过
3. G14 文档描述修正已并入 v2.8，不再列为阻断

v2.8 可进入实施与云端真实数据重跑阶段；因子 verdict 在 S/E 层覆盖达标前保持 `inconclusive`，符合统计纪律。

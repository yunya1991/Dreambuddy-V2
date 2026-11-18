# SPEC：11 域 1H 推理模型重训与 5 折 Walk-Forward 验收

> 版本：v1.1（评审修订版）
> 日期：2026-11-18
> 状态：P0 已完成；P1 已完成「归档/清空/权重等权/云端重启」，本文档定义 P1 剩余「5 折对比 + 验收」口径
> v1.1 修订：依据 2026-11-18 评审，修复数据不可达、基线不对称、全序列统计泄漏、统计显著性缺失四类问题
> 上游依据：[2026-11-18 推理周期调研](reports/2026-11-18-inference-timeframe-audit.md) §5–§7
> 关联变更：`docs/CHANGELOG.md` v4.6.0 / v4.6.1

---

## 一 · 背景与已发生事实

### 1.1 已确认结论

1. 生产推理使用的是 **1H K 线 + 300s 轮询**，不是 5m K 线；「5 分钟」只是轮询间隔。
2. 低胜率的真实来源不是周期本身，而是：
   - 未收盘 1H bar 参与推理（重绘）；
   - 特征窗口 200 根，远短于训练窗口；
   - 模型缓存键随首尾 bar 变化，导致频繁重训；
   - 战略层把风格锁死（已于 2026-11-18 删除）；
   - `ExitManager` 占位链旁路真实离场策略（已修复）；
   - 跨资产 BTC 参考数据陈旧，导致非 BTC 币特征冻结（已修复）。
3. 旧模型 369 个（其中 245 个为 4H）已归档至
   `scripts/data/bcrm2_models_archive_20261118/`，活动目录 `bcrm2_models/` 已清空。
4. 清理前完成 OOS 评估：78 个 1H 加密模型中 45 个胜率 >50%，但同期 always-long 基线为 47%~61%，
   多数「>50%」只是行情 beta。真实相对优势集中在 INJ 80.0%（基线 47.7%）、SOL 71.1%（51.1%）、
   BTC 75.0%（51.7%）、AAVE 73.0%、GRT 73.3%；最新模型明显退化（ETH 42.9%、SOL 51.7%、INJ 53.3%）。
5. 29 个相对占优模型已保留为基准：`scripts/data/bcrm2_models_keep/SHORTLIST.json`。
6. 五域权重文件已回退等权并留档（代码已无引用）。
7. 云端 `yijing-polling-trader.service` 已于 2026-11-18 11:35:31 CST 重启，HEAD=`42539155d4`，
   正在按 1H 已收盘数据冷启动重训。

### 1.2 尚未完成

- 5 折 walk-forward 对比（P1 第 2、3 项）；
- 云端冷启动重训完成后的模型数量/信号一致性验收；
- 结论回写文档与提交。

---

## 二 · 目标与非目标

### 2.1 目标

1. 用**已收盘 1H 数据**重训并做 5 折 walk-forward，回答「1H 口径下模型是否具备超过行情 beta 的稳定优势」。
2. 给出与 **always-long 基线**、**保留的 29 个 OOS 基准模型**同表对比的胜率、单笔期望、PF、最大回撤、样本数。
3. 以预注册门禁决定：模型可保留 / 需继续 shadow / 应判为无优势并停止扩池。
4. 产出可复现脚本、JSON 结果、报告与 CHANGELOG。

### 2.2 非目标

- 不改推理周期（不改 5m/4H），不引入新特征族。
- 不重置 `bcrm_trades.db`、`paca_performance_cache.json` 等真实成交/胜率证据。
- 不在本阶段切换实盘仓位参数（`--confidence 0.7955 --position-pct 0.20` 保持不变）。
- 不评价 43 域战略推演层（已独立）。

---

## 三 · 范围

### 3.1 第一阶段（必做）

| 项 | 值 |
|---|---|
| 币种 | BTC、ETH、SOL |
| 周期 | 1H，仅 `confirm=1` 已收盘 bar |
| 历史长度 | 目标 30000 根（≈3.4 年），最低 12000 根；抓取必须支持按页重试 + 断点续传，分轮补齐 |
| 特征模块 | 主口径只启用因果滚动模块（bagua / classic_exp / fibonacci / pivot / rsi / wdh / cross_asset）；market_cap、merrill、cycle 暂禁用 |
| 折数 | 5 折 anchoring walk-forward（训练集扩展，测试集不重叠） |
| 初始训练比例 | 70%，剩余 30% 均分 5 折 |
| 交易模拟 | 下一根开盘入场；TP=3×ATR，SL=2×ATR，`max_hold=60`；fee=0.05%，slippage=0.1% |
| 置信度阈值 | 主口径 `T_res=0.40`（与既有 baseline 可比，完整重训/模拟）；生产阈值 `T_prod=0.7955` 从同一批交易中按 confidence 后验过滤，仅作可达性参考 |
| 跨资产参考 | BTC 1H，新鲜度 ≤2 根，缺失/陈旧时 fail-open 并记录 |

### 3.2 第二阶段（条件触发）

第一阶段 BTC/ETH/SOL 中 **≥2 个通过 G3**，才扩展到其余加密池
（UNI、PUMP、HYPE、AAVE、ZEC、ARB、OKB、BNB、XRP、DOGE 等，以云端实际注册表为准）。
未达标则停止扩池，仅保留结论与基准。

### 3.3 产出物

| 产出 | 路径 |
|---|---|
| 评测脚本（新增） | `11-易经推理系统/scripts/memory_l4/bcrm2/eval_1h_walkforward.py` |
| 机器可读结果 | `11-易经推理系统/data/eval/walkforward_1h_20261118.json` |
| 人类可读报告 | `11-易经推理系统/docs/reports/2026-11-18-p1-1h-walkforward.md` |
| 变更记录 | `11-易经推理系统/docs/CHANGELOG.md` v4.6.2 |

> 脚本复用既有 `bcrm2.walk_forward_backtester.WalkForwardBacktester`（已实现 5 折重训），
> 不重复实现特征工程与标签器；新增 only：数据门禁、双阈值、always-long 基线、门禁判定、结果落盘。

---

## 四 · 评估口径（预注册）

### 4.1 指标定义

| 指标 | 定义 |
|---|---|
| 胜率 WR | 单笔净收益 >0 的笔数 / 总笔数 |
| 单笔期望 E | 所有交易净收益的算术平均（含 fee、slippage），并给出 95% bootstrap CI |
| 期望 CI 下界 | bootstrap 2000 次，E 的 2.5% 分位；G3 要求 >0 |
| 盈亏比 PF | 总盈利 / 总亏损绝对值 |
| 最大回撤 MDD | 测试段权益曲线最大峰谷回撤 |
| 样本数 N | 全部折的有效交易数；同时报告每折 N |
| always-long 基线 | 同一测试段、同一 TP/SL/持有期/冷却规则下「无模型、每根 bar 只做多」的结果 |

### 4.2 基线对照

| 基线 | 用途 | 是否门禁 |
|---|---|---|
| B0 buy-and-hold（每个测试窗口一次往返） | 给出行情 beta 的绝对水平 | 否（仅报告） |
| B1 always-long（同测试段、同 TP/SL/持有期规则、每根 bar 只做多） | 剥离行情 beta，检验模型是否真有方向 alpha | 是 |
| B2 `bcrm2_models_keep/SHORTLIST.json`（29 个旧模型 OOS） | 参考「旧模型相对水平」 | 否（样本窗口不同，且旧评估受陈旧 ref 缓存影响） |
| B3 随机方向（与模型完全相同的离场栈，20 seeds 均值） | 剥离方向 alpha，作为 G3 主比较对象 | 是 |

### 4.3 防多重比较

- 主指标预注册为：**`T_res=0.40` 下、5 折合并的 `E`（单笔期望）**。
- 胜率、PF、MDD、`T_prod` 结果均为次要指标，只用于解释，不用于挑选「最好看的一折」。
- 报告中必须同时给出 5 折逐折结果；禁止只报最佳折。

### 4.4 已知风险与处理

| 风险 | 处理 |
|---|---|
| 抓取不可达/中途断连 | `fetch_okx_klines` 单页 3 次指数退避；`after_ts` 断点续传只补更早历史；每次运行最多 3 轮补齐；仍不足则 G0 失败并明确报错 |
| 特征在切分前对全序列计算，可能存在非因果统计 | 已知 `market_cap` 用全序列 `median(close)/std(returns)` 决定模块开关；主口径禁用 market_cap / merrill / cycle，仅保留因果滚动模块；后续再逐模块审计 |
| 本地 CSV 含未收盘最后一根 | 载入后统一剔除 `close_time > now` 的最后一根；日志打印首尾时间 |
| 陈旧缓存导致 ref 冻结 | 复用 `get_klines(max_age_bars=2)`；失败则 fail-open 并在结果中标记 `ref_stale=true` |
| 阈值 0.7955 导致样本不足 | 主口径固定 0.40；0.7955 仅对同一批交易做后验过滤，报告 `n` 并标注 `post-hoc`，不用于门禁 |
| 基线不对称 | B1 仅作 beta 参考；G3 主比较对象改为 B3（随机方向 + 同一 `_simulate_trades` 离场栈，20 seeds） |
| 5 折训练耗时 | 先三币串行；单币超时则降为 3 折并显式标注 `n_folds=3`（不得静默降级） |

---

## 五 · 验收门禁（G0–G5）

| 门 | 判定 | 不通过处理 |
|---|---|---|
| **G0 数据** | 全部 bar `confirm=1`；BTC/ETH/SOL ≥12000 根；最后一根已收盘；ref 新鲜或已标记；抓取经重试/续传后仍不足即失败 | 终止该币评测，不产出结论 |
| **G0.5 泄漏** | 主口径只启用因果滚动模块；market_cap / merrill / cycle 关闭并记录 | 配置不符则本轮结果作废 |
| **G1 可复现** | 结果 JSON 含 git SHA、配置哈希、随机种子、数据 hash、数据首尾时间、macro 开关 | 重跑并补齐 |
| **G2 样本** | 主口径总 N≥150，且 ≥4/5 折 N≥20；每折 N≥10 | 判 `INSUFFICIENT`，扩历史或降折数后重跑 |
| **G3 经济性** | `E>0` 且 `E` 的 95% CI 下界 >0；`PF≥1.2`；`MDD≤15%`；`MDD ≤ B3_MDD×1.10`；`E ≥ B3_E+0.05` | 该币不通过，不得宣称模型有效 |
| **G4 稳健性** | ≥3/5 折 `E>0`；最好一折贡献的交易占比 <60% | 判「不稳健」，仅保留 shadow |
| **G5 云端** | shadow 24h 无异常开仓；日志中推理 bar 均为已收盘；同一 1H 内信号不漂移 | 回滚到重启前配置并记录 |

**总判定**：

- `PASS`：三币中 ≥2 币通过 G0–G4，且 G5 通过 → 模型方案保留，进入第二阶段扩池。
- `CONDITIONAL`：G3 通过但 G4 未通过（仅 1 币或稳健性不足）→ 仅保留 shadow，不扩池。
- `FAIL`：G3 未通过 → 1H 重训不作为收益来源，保留既有 29 个基准，等待 P2 特征/标签层复核。

---

## 六 · 实施步骤

| 步骤 | 内容 | 完成判据 |
|---|---|---|
| S1 | `eval_1h_walkforward.py`：数据门禁 + 断点续传 + 因果模块 + B0/B1/B3 基线 + CI + JSON/报告输出 | 冒烟跑通，输出含 G0/G0.5 结果 |
| S2 | 分轮补齐 BTC/ETH/SOL 到 ≥12000（目标 30000），核对数据 hash 与首尾时间 | 三币 G0 通过，日志可核对翻页/续传 |
| S3 | 跑 BTC、ETH、SOL 5 折 | 三币齐全，逐折结果与 B3 均值可读 |
| S4 | 生成报告并按 G0–G4 判定 | 报告含 PASS/CONDITIONAL/FAIL 结论 |
| S5 | 云端观测：模型数量、推理 bar、信号一致性、CPU/日志 | 24h 内无新增异常 |
| S6 | 更新 CHANGELOG v4.6.2，提交；必要时再重启云端 | commit + push + 云端 HEAD 一致 |

---

## 七 · 回滚与安全边界

1. 评测脚本只读行情与模型，不写活动模型目录；失败不影响线上。
2. 云端如需回滚：`git revert` 对应 commit → 重启 `yijing-polling-trader`；模型目录可从
   `bcrm2_models_archive_20261118/` 恢复。
3. 不删除 `bcrm2_models_keep/` 与 `SHORTLIST.json`，作为长期基准。
4. 不以「单折高胜率」触发任何实盘参数调整；实盘切换需 G5 通过并单独评审。

---

## 八 · 附：关键文件

- `scripts/memory_l4/polling_trader.py`：推理主循环（P0 已改）
- `scripts/memory_l4/yijing_trainer.py`：`_load_kline_from_okx(closed_only=True)`
- `scripts/memory_l4/bcrm2/data_fetcher.py`：`get_klines(max_age_bars=...)`、confirm 过滤
- `scripts/memory_l4/bcrm2_adapter.py`：`_fetch_ref_df` 新鲜度缓存
- `scripts/memory_l4/bcrm2/walk_forward_backtester.py`：5 折重训回测引擎（复用）
- `scripts/memory_l4/bcrm2/exit_manager.py`：真实离场策略恢复
- `scripts/data/bcrm2_models_keep/SHORTLIST.json`：29 个基准模型
- `docs/reports/2026-11-18-inference-timeframe-audit.md`：上游调研

---

## 九 · 评审记录（2026-11-18）

### 9.1 评审结论

v1.0 判定 **BLOCK**：方向正确，但存在 3 个 P0，按原版执行只能得到「全部 ERROR」或「虚高结论」。

### 9.2 实测证据

| 币 | 实际根数 | 结果 |
|---|---|---|
| BTC | 8199 | ERROR `bars<12000` |
| ETH | 9299 | ERROR `bars<12000` |
| SOL | 9599 | ERROR `bars<12000` |

抓取在 page 22 / 94 / 97 被远端断开，`proxies={}`，原实现单页失败即 `break`。

### 9.3 P0 与修订

| 编号 | 问题 | 修订 |
|---|---|---|
| P0-1 | 数据门禁不可达，抓取无重试/续传 | `fetch_okx_klines` 单页 3 次指数退避；新增 `after_ts` 断点续传；评测脚本最多 3 轮补齐 |
| P0-2 | B1 always-long 与模型离场栈不对称，G3 可被行情差刷过 | 新增 B3：随机方向 + 同一 `_simulate_trades` 离场栈，20 seeds 均值；G3 主比较对象改为 B3，并加绝对 MDD 上限 15% |
| P0-3 | `market_cap` 用全序列 `median/std` 决定模块开关，构成未来数据泄漏 | 主口径关闭 market_cap / merrill / cycle，仅保留因果滚动模块；新增 G0.5 |

### 9.4 P1 修订

- G3 增加 `E` 的 95% bootstrap CI 下界 >0；
- G1 增加数据 hash 与 macro 开关记录；
- `CONDITIONAL` 收紧为「G3 通过但 G4 未通过」；
- B1 仅作 beta 参考，不再作为 G3 门禁；
- 明确主口径为「模型 alpha 评估」，不等同于生产 PnL（pentagon 关闭、T_prod 为后验过滤）。

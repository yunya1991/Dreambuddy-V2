# 54-L1 MERS S3 全量真实数据验收报告（#35）

## 基本信息

- 验收时间：2026-11-15 21:32–22:07（CST，云端 43.160.201.117）
- 验收对象：MERS S3 固定 180 单元网格（6 transforms × 10 methods × 3 horizons）、BH-FDR、状态机、幂等注册表在**真实全量数据**上的表现
- 规划依据：`SPEC-54-L1架构能力聚合层.md` §14（MERS）；`docs/TECHNICAL_DESIGN.md` §6.4.4/§6.4.5 #35
- 关联 commit：执行器 `53952864c2`（`scripts/mers_eval.py`）；缺陷修复 `2b5b8b8a59`（B11 空桶）
- 代码来源：本地 → GitHub → 云端 `git pull --ff-only`（云端位于 `2b5b8b8a`），未使用 rsync/scp 传代码
- 数据边界：DAL `19-数据访问层/data/dreambuddy_core.db` **只读**（`file:...?mode=ro`）；registry 是 54 自有产物目录 `54-.../data/mers/registry.db`（`data/` 已 gitignore），不写任何 `mm_*` 生产表
- 执行方式：`systemd-run --collect --unit=mers-accept3`（luke 身份），SSH 会话断开后进程继续；单轮 CPU ≈ 5 分 18 秒

## 验收范围与网格口径

| 项 | 值 |
|---|---|
| job 数 | 29 = 20 个 `close_1d` 资产（signal=prices=close）+ 9 个宏观/情绪/资金费率指标（对齐到 BTC 日轴） |
| 宏观指标 | DGS10 / NASDAQCOM / SP500 / VIXCLS / T10Y2Y / DCOILWTICO / DTWEXBGS / crypto_fear_greed / funding_rate |
| 单元数 | 5,220 = 29 × 180 |
| 样本门禁 | 每 job ≥250 个对齐点（不足计入 `skipped`，本次 0 条） |
| grid_hash | `cb544b9c4626c609ede781731cd4ae72bd77fa3b84140eaddb14d6e5aca7bc00` |
| 真实样本跨度 | BTC/ETH 3,377 天；APT 1,488 天；funding_rate 1,096 天 |

## 验收中发现并修复的缺陷

**症状**：修复前全量首跑 95/5,220 单元 `method_gate=failed`，错误文本全部为 `float() argument must be a string or a real number, not 'NoneType'`，集中在 B11（分箱单调性）。

**根因**：真实数据存在大量并列值（价格不变、宏观指标整数化），`_bucket_by_quantile` 的分位边界塌缩产生空桶，`b16_group_stats` 对空桶返回 `mean=None`；`b11_monotonic` 直接 `float(x["mean"])` 崩溃。`prebinned` 分支本已过滤空桶，非 prebinned 分支漏了同一守卫。

**修复**（`2b5b8b8a59`，2 文件 +27/-1）：非 prebinned 分支同样过滤 `n>0 且 mean is not None` 的桶；非空桶 <2 个时显式 `ValueError("factor 在 k=… 下非空分箱不足 2 个")`。补 2 条回归测试（并列值塌缩、单桶拒绝）。

**修复效果**：`method_gate failed` 95 → **0**；门禁通过 1,028 → **1,057**（+29 单元）。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | PASS | `repro_after.log` §0 vs §1：failed 95→0，`gate_pass` 1,028→1,057；`test.log` 新增 2 例专测并列值塌缩 | 原错误文本不再出现 |
| 日志/运行证据 | PASS | `repro_after.log` §1–§3 三轮 journal 原文：`jobs=29, units=5220, gate_pass=1057, gate_pass_rate=0.2025`，`idempotency added=0` | 非仅进程存活，逐轮打印真实汇总 |
| 回归测试 | PASS | `test.log`：54-L1 全量 **1,192 passed / 0 failed**；目标+边界 35 passed；ruff/black 通过；`method_audit --scope all` → `catalog=243 implemented=392 passed=392 failed=0` | 审计口径未变，未新增方法 ID |
| 影响面 | PASS | `fix.diff` 仅 `l1agg/methods/conditional.py` + `tests/test_methods_s3.py`；未触碰 11/18/23/41/48/50 等域；未提交并行 LTL-16 文件 | 方法层口径只在空桶退化路径改变 |
| 边界验证 | PASS | R03/R04/F19 恒 `not_applicable`（1,566 单元，缺日历/事件上下文不伪造输入）；样本 <250 的 job 全部 `skipped` 且如实披露；单桶输入显式报错 | 无静默输出 |

## 真实数据结果

### 门禁与显著性

| 指标 | 值 |
|---|---|
| 单元总数 | 5,220 |
| `gate_pass` | **1,057（20.25%）**，三轮完全一致 |
| `method_gate` | `ok` 3,654 ／ `not_applicable` 1,566 ／ `failed` **0** |
| `p_adj` 区间 | 2.03e-44 ～ 0.99961（BH-FDR，alpha=0.05） |
| top3 显著单元 | 44（同时满足 `p_adj<0.05` 与 `gate_pass`） |

job 级门禁通过数（每 job 上限 180）：BTC 77、XLM 77、ETH/LTC/UNI/XRP 70、BNB/ETC/LINK/AVAX 56、TRX 49、BCH/SOL/NEAR 42、DOGE 35、ADA/ATOM 28、FIL 21、DOT 7、APT 0；宏观：SP500 42、NASDAQCOM 28、T10Y2Y 28、DCOILWTICO 7，DGS10/VIXCLS/DTWEXBGS/crypto_fear_greed/funding_rate 均为 0。

### 状态机（三轮连续版本）

| 状态 | 单元数 | streak |
|---|---|---|
| `stable` | 1,057 | `pass_streak=3` |
| `candidate` | 4,163 | `fail_streak=3` |
| `decayed` / `retired` | 0 | 只能由 `stable` 进入，符合契约 |

三轮采用同一数据快照、以 `data_version=accept-20261115-r1/r2/r3` 模拟连续版本推进（口径与「每日一版」一致，无时间穿越）。`RelationshipRegistry.record()` 以 `relationship_state` 为 previous 计算状态，因此跨轮可推进；`evaluate_grid` 内的 `previous=None` 只影响返回值副本，落库行以注册表状态为准。

### 幂等

| 轮次 | 第一遍行数 | 第二遍行数 | 新增 |
|---|---|---|---|
| r1 | 5,220 | 5,220 | 0 |
| r2 | 10,440 | 10,440 | 0 |
| r3 | 15,660 | 15,660 | 0 |

同 `data_version` 复跑命中 `get_eval(eval_id)` 直接返回缓存行（在 `_evaluate_unit` 之前短路），不重算、不推进 streak；跨轮新增行来自 `data_version` 变化生成的新 `eval_id`，属预期。

## 红旗与限制

1. **`stable` 不跨数据版本维持**：`transition_state` 规定 stable 遇 `data_version` 变化回退 candidate（并从 0 重新计数），因此 stable 表达的是「最近连续 3 个版本通过」。这是冻结契约，不是缺陷，但意味着**必须每日运行**才能维持稳定态，否则状态会周期性回退。
2. **网格可评估率仅 70%**：R03/R04/F19 各 522 单元（合计 1,566，30%）恒为 `not_applicable`（缺交易日历/事件上下文）；要让这部分进入评估需先接日历/事件源，属后续工作。
3. **注册表按版本追加**：每日 5,220 行（≈190 万行/年）。v2.54 已落地保留策略：`RelationshipRegistry.prune_before()` + `--prune-days 90`，只清 `relationship_eval` 历史行（90 天 ≈47 万行封顶），`relationship_state` 永久保留。
4. **周期调度已上线（v2.54）**：`dreambuddy-mers.{service,timer}` 已安装并 `enable --now`，`OnCalendar=*-*-* 08:20:00`（CST，实际含 ≤300s 随机抖动）、`Persistent=true`、`--prune-days 90`；首次手动触发 exit=0，`totals{29 job,5220 单元,gate_pass 1057}`、`added=0`、`retention{pruned_rows:0}` 与验收口径一致。按契约 `stable` 遇 `data_version` 变化回退 candidate，本轮（`data_version=2026-11-15`）结束后 state 全部为 candidate（`pass_streak=1`），需连续 3 个交易日通过才会重新进入 stable。
5. **S5 仍关闭**：MERS 结论只在本验收注册表内，未开放 `relationship_recommend`；walk-forward/Discovery 仍属 #37。

## 验收结论

**PASS**。全量真实数据（29 job / 5,220 单元）门禁、BH-FDR、状态机与幂等四项均产生非空且可复现的证据：三轮 `gate_pass` 完全一致（1,057，20.25%），状态机在真实数据上推进到 `stable=1,057`，每轮复跑 `added=0`；验收过程中发现的 B11 空桶崩溃已定位根因、修复并回归（failed 95→0）。周期调度与 90 天保留策略随后于 v2.54 上线（首次手动触发 exit=0、结果与验收口径一致）。

AI 验收：2026-11-15
用户确认：待确认

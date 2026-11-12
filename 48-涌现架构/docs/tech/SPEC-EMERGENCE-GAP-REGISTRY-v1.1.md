# SPEC — 交易涌现架构缺口清单（GAP REGISTRY）v1.1

> **状态**: 🟡 已复核修正（v1.0 中 3 项判定被推翻、2 项证据纠偏）
> **日期**: 2026-11-12
> **归属**: 48-涌现架构
> **复核方**: 开发端（开发机 macOS，仓库 `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2`）
> **被复核方**: 云端主机（43.160.201.117，仓库 `/home/luke/dreambuddy`）
> **用途**: 交易涌现架构全部已知缺口的唯一登记表（SSOT）；每条缺口附可执行判据与证据

## 术语约定（本版新增，强制）

| 术语 | 含义 |
|---|---|
| **云端** | 云主机 43.160.201.117 及其仓库 `/home/luke/dreambuddy`。**云端视角会把自身称为"本地服务器"**——v1.0 的"本地"即指云端，这是本次误判的根源 |
| **开发端** | 开发机（macOS）及仓库 `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2` |

> **纪律**：所有涉及环境差异的结论，正文必须写明 `[云端]` 或 `[开发端]`，禁止单写"本地"。

## 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-11-12 | 初版：10 项缺口，判定"8 真实 / 1 已落地 / 1 文档过时"，验证环境标注为"本地服务器" |
| v1.1 | 2026-11-12 | 开发端实测复核：GAP-2 判定反了、GAP-9 归属错、GAP-10 判据错误（表名错）；GAP-1/7 结论保留但证据/数字更正；H1–H4 同步方向反转；新增 GAP-11（开发端 fear_greed 回填） |
| v1.1 追加 | 2026-11-12 | §6.4 本地补齐执行：`941afd93`/`b3efd1cc`/`cb49750b` 关闭、GAP-11 关闭；registry 更新为 42 条（open 37 / resolved 5）并同步云端；剩余 37 条为结构性缺口，附判据校准出口 |

---

## §0 执行摘要（修正）

v1.0 的验证实际发生在**云端**，却表述为"本地服务器（Ubuntu）"，导致把云端状态当成开发端现状。开发端实测后结论如下：

| 判定 | 数量 | 缺口编号 |
|---|---|---|
| ✅ 属实 | 5 | GAP-3、GAP-4、GAP-5、GAP-6、GAP-8(非缺口) |
| 🟡 部分属实（结论对/证据错） | 2 | GAP-1、GAP-7 |
| ❌ 不属实（已被推翻） | 3 | GAP-2、GAP-9、GAP-10 |
| 🆕 新增 | 1 | GAP-11（开发端 fear_greed 未回填，同日已补齐关闭，见 §6.4） |

**三项不属实的根因**：
1. **GAP-2**：同步方向反了。开发端已有 42 条缺口（含 11-10 的 34 条），云端反而只有 4 条；
2. **GAP-9**：把云端的 `bcrm_trades.db`（45056B / 67 条）写成开发端事实；
3. **GAP-10**：判据用错表名。数据落库 schema 是 `records(source='fear_greed')`，不存在 `crypto_fear_greed` 表；云端已回填 3823 行（2018-02-01 ~ 2026-11-12），缺口实际留在开发端。

---

## §1 缺口登记表（修正版）

### GAP-1 D2-A 人工盲评未执行【P0 · 属实，证据更正】

- **有效结论**: `prereg.json` 的 `decision_rule.candidate = "CI_low > 0 且盲评 ≥4/5"`。`[开发端]` `D2A-ba929d3fac60/evaluation.json` 的 `decision` 仅以 `CI_low=0.957143 > 0` 判 `candidate`，**盲评确未执行**，不能升级为 verified。
- **纠正 v1.0 证据**: `[开发端]` `experiments/d2a_holdout/results/` **存在且有 13 个 run**（含 `D2A-ba929d3fac60` 的 evaluation.json / prereg.json / manual_review.md），`metrics/verdict_dashboard.json` 的 evidence 路径可正常解析；`[云端]` 该 results 目录不存在，证据链断链只发生在云端。
- **辨析**: `manual_review.md` 是 GT import 边复核（230/230，100%），**不是**对预测结果的人工盲评，不能替代判据。
- **动作**: ①执行人工盲评（≥4/5）；②产物同步方向为 `开发端 → 云端`。

### GAP-2 需求单池与环境不同步【P0 · v1.0 判定反了】

- **实测（可复跑）**:

| 端 | `registry/capability_gaps.jsonl` | 构成 |
|---|---|---|
| `[开发端]` | **42 条**（open 39 / resolved 2 / claimed 1） | 11-10 新增 34（doc_debt 13 / interface_mismatch 13 / architecture_gap 11）、11-09 3、11-05 5 |
| `[云端]` | **4 条**（2 resolved / 2 open） | 仅 GAP-20261107 系列 |

- **仍成立的部分**: 11-09 的 3 条缺口确实仍为 `open`（架构/文档/接口各 1）。
- **纠正**: v1.0 说"本地仅 4 条、34 条未同步本地"——错。开发端已完成同步，落后的是云端。
- **动作**: ①~~`开发端 → 云端` 同步 42 条~~ ✅ **2026-11-12 已执行**：两端同一 md5 `8536852b4367cb91e69ab4813e303f70`、42 条（open 38 / resolved 3 / claimed 1）；云端原 4 条（GAP-20261107 系列）按语义并入对应条目并保留 `merged_from` 审计字段，云端原文件备份于 `/tmp/capability_gaps.cloud-backup-20261112.jsonl`；同步时一并纠正 2 条过期状态（`941afd93` 评估器缺失→resolved；`b3efd1cc` 域状态时序缺口注明"云端 9307 行 / 开发端 1 行，修复方向为 云端→开发端 数据同步"）；②~~回填 3 条 11-09 缺口的 resolved 状态~~ 部分不具备本地关闭条件（结构类，见 §6.4），保持 open。**同步后最新口径：42 条 = open 37 / resolved 5 / claimed 0（md5 见 §6.4）。**

### GAP-3 D3 在线 A/B 未接【P1 · 属实】

- `[开发端]` 全仓无 online A/B 实现（无 `online_ab` / `ab_test` 代码），D3-A（TOP1=0.908）与 D3-B（召回步数 8.10→1.0）均为 task_type 代理标签 + 离线反事实。
- **动作**: 设计在线 A/B（预测 → 组合 → 在线接受率/纠正率 → 更新先验）。

### GAP-4 X-A 真实联合 A/B deferred【P1 · 属实】

- `experiments/xa_transfer/results/XA-REAL-3f28d4b1543f.json` 中 `status=deferred`（两端一致），当前只能称"跨域联合收益（代理）"，G_123=0.080。
- **动作**: 等 D1 shadow pairs 充足后重跑。

### GAP-5 E1 需 7 天 shadow 跑数【P0 · 属实，自动放行中】

- `[云端]` `yijing-emergence-shadow-probe` **active**，自 2026-11-07 13:42 起常驻；
- `[云端]` `dreambuddy-accumulation-gate.timer` 每日 06:30 执行，日志实测：
  - 11-10: `E1 days=3/7 actions=0 released=False | E4b released=True`
  - 11-11: `days=4/7 actions=0`
  - 11-12: `days=5/7 actions=0`
- 预计 11-14 满 7 天自动放行；当前 `actions=0`，M1 动作 ≥1 判据同样未达。
- **动作**: 无需人工干预，监控日志。

### GAP-6 50 域 live 执行权未开放【设计决策 · 属实】

- `execution_rights.json`：`fifty_nn_domain` 显式 paper-only（R1c），`defaults.outcome=paper`。
- **动作**: 维持 paper-only，开放需用户显式裁决。

### GAP-7 TrainingEvent 三端同步缺失【P1 · 部分解决（2026-11-12 20:53，云端）】

- **纠正**: `[开发端]` 与 `[云端]` 的 `events/training_events/train_50_decisions.jsonl` **均为 3 条**，v1.0 的"本地 12 / 云端 3"不成立。
- **仍成立**: 训练建议回灌仍为人工流程。
- **解决记录（2026-11-12，云端）**:
  1. **全量回填完成**: 50 域 `runtime/decisions.jsonl` 180 条 → TrainingEvent **180 条**（scanned 180 / appended 177 / duplicates 3，幂等验证通过）；
  2. **统一 join 模块已落地**: `48-涌现架构/metrics/training_event_join.py`（标的归一化 + ±3 天时间窗匹配 + 幂等回填 + --dry-run + FAIL-OPEN）；
  3. **join 实测发现数据粒度不匹配（诚实记录，不做伪 join）**: 50 域全部 181 条决策均为 `symbol=MULTI`（多资产综合决策），与 40 域 `execution_trades.jsonl`（104 条，单标的如 BTC/USDT）粒度不匹配 → dry-run 实测 `n_multi_symbol_skipped=180, join_coverage=0.0`。**根因是数据粒度而非实现缺失**。
- **剩余动作**: ①50 域决策输出增加标的粒度（或 40 域提供 MULTI 口径汇总）后重跑 join；②join 单测补齐；③训练建议 → 40/50 权重自动回灌。

### GAP-8 E4b 动作侧埋点【✅ 已落地，非缺口】

- `4-MEMORY/9-工具与接口/cognitive_session.py` 存在 6 处 `active_reflection_id`；`48-涌现架构/metrics/e4b_reflection.py` 消费端就绪。
- **动作**: 无，保持观测。

### GAP-9 E1 交易数据基础【v1.0 结论保留，归属更正】

- **实测**:

| 端 | `bcrm_trades.db` | trades |
|---|---|---|
| `[云端]` | 45056 B（2026-11-12 06:56） | 67 条 |
| `[开发端]` | 40960 B（2026-10-13） | 49 条 |

- **纠正**: v1.0 引用的 45056B / 67 条是云端数据，不是开发端。但"3D 文档的 0 字节空库表述已过时"结论仍成立——两端均非空。
- **动作**: 更新 3D 文档 §2.1，按端分别写明数据快照。

### GAP-10 fear_greed 云端回填【❌ 不属实，判据错误】

- **真实 schema**: `data_center/storage/sink_postgres.py` 落库到 PostgreSQL `data_center` 库的 `records` 表，`source='fear_greed'`、`category='chain'`、`sub_category='crypto_fear_greed'`，**不存在 `crypto_fear_greed` 表**；用 `data_center.db`（sqlite）0 字节判断"未落库"同样无效，该环境 `DATA_CENTER_BACKEND=postgres`。
- **云端实测**:

```
records where source='fear_greed' → 3823 行, 2018-02-01T00:00:00Z ~ 2026-11-12T10:00:00Z
runtime/data_quality/fear_greed_backfill.json → passed=true, inserted_rows=0（幂等，无新增）
artifact 由 datacenter-backfill.timer 于 2026-11-12 19:15 调度产出
```

- **结论**: `[云端]` 回填已完成，**本缺口关闭**。开发端实测 sqlite `records` 仅 495 行、截止 2026-10-29 → 转到 GAP-11。

### GAP-11 开发端 fear_greed 全历史未回填【✅ 已关闭 · 2026-11-12】

- ~~`[开发端]` sqlite `18-数据获取中心/data_center.db` 的 `records(source='fear_greed')` 仅 495 行，时间跨度截至 2026-10-29~~
- **执行结果**: 开发端 `--dry-run` 通过后正式回填至 sqlite（`backend=sqlite`，`inserted_rows=3203`）：
  - `n_days=3203`、`first=2018-02-01`、`last=2026-11-12`、`max_gap_days=4`、`coverage_3y=0.9991`、`stale_days=0`、`passed=true`
  - 报表落盘: `48-涌现架构/runtime/data_quality/fear_greed_backfill.json`（后端字段已标注 `sqlite`，与云端 postgres 报表区分）
  - 复核查询: `select count(distinct substr(timestamp,1,10)) ... where source='fear_greed'` → 3203 个自然日
- **遗留数据质量项**（不阻塞缺口关闭）: 回填前遗留 495 条小时级旧行（`metrics={"asset":"","value":...}`、`raw={}`），与回填的日级行在 36 个自然日混合粒度；下游若按日聚合需取 `metrics.date` 存在的行，或后续统一清理。
- **动作**: 无（已关闭）；混合粒度清理另行登记。

---

## §2 横向发现（修正）

| # | 原表述 | 修正后 | 处置 |
|---|---|---|---|
| H1 | D2-A formal 产物未同步本地 | 产物在 `[开发端]` 完整，`[云端]` 缺失；**同步方向 = 开发端 → 云端** | 升级为 P0 同步项 |
| H2 | 34 条 D2 缺口未同步本地 | 开发端 42 条齐全，**云端仅 4 条**；同步方向 = 开发端 → 云端 | 同步 + 版本对齐 |
| H3 | 文档引用 macOS 绝对路径 | 成立：D2-D3 SSOT 存在 `file:///Users/...` 链接，在云端不可解析 | 统一改仓库相对路径 |
| H4 | 3D 文档 bcrm 表述过时 | 成立，但需分端写：`[云端]` 67 条 / `[开发端]` 49 条 | 更新快照 |

---

## §3 优先级与依赖（修正）

```
P0（阻塞涌现验证主线）:
  GAP-1  人工盲评（判据硬门槛）+ 产物 开发端→云端 同步
  GAP-2  需求单同步已完成；剩余 3 条 11-09 属结构类（见 §6.4）
  GAP-5  E1 shadow 积累（自动放行中，预计 2026-11-14）
  ~~GAP-10~~ 已关闭（云端 records 3823 行，passed=true）
  ~~GAP-11~~ 已关闭（开发端 sqlite 3203 天，coverage_3y=0.9991）

P1:
  GAP-3  D3 在线 A/B
  GAP-4  X-A 真实联合 A/B（依赖 GAP-5）
  GAP-7  TrainingEvent 统一 join + 单测（先锁口径）

设计决策（维持）:
  GAP-6  50 域 live 执行权 paper-only

文档维护:
  H1-H4
```

---

## §4 状态流转约定

- 状态: `open` → `in_progress` → `resolved`（附 `resolution_note` + `resolved_at` + 判据查询输出）
- 解决后不删除条目，保留审计痕迹；本文件为人类可读 SSOT，`registry/capability_gaps.jsonl` 为程序消费入口
- 每次状态变更同步更新 §0 统计表与 §3 优先级

---

## §5 复核证据（命令级，可复跑）

```bash
# GAP-1 产物
[开发端] ls 48-涌现架构/experiments/d2a_holdout/results            # 13 个 run
[云端]   ls 48-涌现架构/experiments/d2a_holdout/results            # 不存在

# GAP-2 需求单
[开发端] python3 统计 registry/capability_gaps.jsonl                 # 42 条
[云端]   wc -l 48-涌现架构/registry/capability_gaps.jsonl            # 4

# GAP-5 shadow 与门禁
[云端] systemctl show -p ActiveEnterTimestamp --value yijing-emergence-shadow-probe
[云端] journalctl -u dreambuddy-accumulation-gate.service -n 12      # days=5/7 actions=0

# GAP-9 交易库
[云端]   ls -l 11-易经推理系统/scripts/data/bcrm_trades.db           # 45056B, 67 行
[开发端] ls -l 11-易经推理系统/scripts/data/bcrm_trades.db           # 40960B, 49 行

# GAP-10/GAP-11 fear_greed（注意：判据是 records 表，不是 crypto_fear_greed 表）
[云端]   psql -d data_center -tAc \
  "select count(*),min(timestamp),max(timestamp) from records where source='fear_greed'"
  # 3823 | 2018-02-01 | 2026-11-12
[开发端] sqlite3 data_center.db \
  "select count(*),min(timestamp),max(timestamp) from records where source='fear_greed'"
  # 495 | 2026-09-09 | 2026-10-29
```

---

## §6 评审结论与流程改进（v1.1 回写）

### 6.1 评审结论

1. v1.0 的**问题意识成立**（缺口确实存在且 P0 阻塞主线），但**事实核查失效**：环境标注错误 + 3 项判据错误，导致约 30% 条目给出错误行动指令（GAP-10 会让团队重复执行已完成的回填，GAP-2 会让开发端重复已完成的同步）。
2. 最危险的错误是 **GAP-10 的表名判据**：用不存在的表名证明"未落库"，属于"验证方法本身不可复跑"。
3. GAP-1 的结论虽对，但证据链方向反了，会误导同步方向（云端 → 开发端 vs 开发端 → 云端）。

### 6.2 待执行动作

| # | 动作 | 责任端 | 完成判据 |
|---|---|---|---|
| A1 | 补 D2-A 人工盲评（≥4/5） | 开发端 | 盲评记录落盘 + verdict 升 verified |
| A2 | D2-A 产物 开发端→云端 同步 | 开发端 | 云端 results 目录存在且 evidence 路径可解析 |
| A3 | capability_gaps.jsonl 开发端→云端 同步 | 开发端 | ✅ 2026-11-12 已完成（42 条，两端 md5 一致 `8536852b…`） |
| A4 | 3 条 11-09 缺口回填 resolved | 开发端 | ⚠️ 不具备本地关闭条件：3 条均属结构类（架构重名/文档覆盖/接口注解），与 §6.4 剩余 37 条同源，保持 open |
| A5 | 开发端 fear_greed 回填 | 开发端 | ✅ 2026-11-12 已完成：sqlite 3203 天、coverage_3y=0.9991、passed=true |
| A6 | TrainingEvent 统一 join + 单测 | 开发端 | 两端条数口径一致，join 单测通过 |
| A7 | H3 macOS 绝对路径改相对路径 | 开发端 | 文档内无 `file:///Users/` |

### 6.3 流程改进（强制）

1. **环境前缀强制**：任何跨端结论必须写 `[云端]` / `[开发端]`，禁止单用"本地"。
2. **判据可执行**：P0 缺口必须附"可直接复跑的命令 + 期望输出"，不接受叙述式结论。
3. **关闭需证据**：`resolved` 必须附查询输出（行数/时间范围）或文件哈希，否则视为无效关闭。
4. **同步方向核实**：涉及"未同步"的结论，必须先分别在两端实测条数，再判定方向。

### 6.4 本地补齐执行结果（2026-11-12，开发端）

本轮原则：**能本地补齐的立即关闭并附证据；不能本地补齐的不做伪关闭。**

| 缺口 | 类型 | 处置 | 证据 |
|---|---|---|---|
| `GAP-20261105-941afd93` | backtest_evaluator_missing | ✅ resolved | `e2_batch_result_evaluated.json` 对 32 个结构变体产出 gate（IS/OOS 降幅、稳定率、n_trades） |
| `GAP-20261105-b3efd1cc` | domain_state_series_missing | ✅ resolved | 云端→开发端同步 `domain_discovery_training_windowed.jsonl`：9309 行 / 9309 唯一时间戳（2026-05-02T12:30Z ~ 2026-11-12T12:00Z） |
| `GAP-20261105-cb49750b` | trading_recall_log_missing | ✅ resolved | `polling_trader._inject_cognitive_recall` 结构化落盘 `recall_events.jsonl`：1769 条、885 条含 `memory_ids`、最新 2026-11-09T18:06Z |
| GAP-11（§1） | 开发端 fear_greed 缺失 | ✅ closed | sqlite 3203 天 / `coverage_3y=0.9991` / `passed=true` |

**registry 最新口径**: 42 条 = **open 37 / resolved 5 / claimed 0**，md5 `d4478b874c90c7d318f3d4d7b780ed20`（开发端与云端一致）。

**剩余 37 条不具备本地一次性补齐条件**（均为结构性缺口，非数据/产物缺失）：

| 类别 | 条数 | 归属域 | 现状 | 出口 |
|---|---|---|---|---|
| `architecture_gap`（函数名跨模块重名） | 11 | 33-REA | 11 个模块重名率 81%~88%，靠命名对齐无法根治 | 33-REA 落地 AST 精准解析（call edge 消歧），或按 Python 模块多入口现实重估阈值 `<0.4` |
| `interface_mismatch`（公开函数缺完整注解） | 13 | 33-REA | 缺注解比例 94%~96%，逐函数补注解需按模块分批 | 分级判据：关键 DLL/跨域边界函数 100% 注解，内部函数豁免 |
| `doc_debt`（模块文档覆盖率） | 13 | 0-系统文档管理 | 覆盖 0.25%~4%，达 90% 需为数百文件建文档 | 判据改为"模块 README/SKILL 覆盖"而非逐文件同名 md，或分批补关键模块 |

> 结论：这 37 条本质是"判据阈值与 Python 代码库现实不匹配 + 需结构性能力"，本轮保持 open，不做伪关闭；建议先由 33-REA 与文档管理域各出一次判据校准，再决定是补代码还是改判据。

**判据校准提案已产出（2026-11-12 20:38，云端实测）**：[PROPOSAL-GAP-CRITERIA-CALIBRATION-v1.0.md](./PROPOSAL-GAP-CRITERIA-CALIBRATION-v1.0.md)——云端实测三项关键数据：① 全仓函数跨目录重名率 **27.5%**（排除魔术方法，40320 函数名 / 11098 重名），全仓口径下已低于现行阈值 0.4，模块级 78-88% 系口径放大（私有辅助函数+魔术方法计入）；② 17域公开函数 docstring 率 **64%**，与记录的 94-96% 缺注解差异显著（『注解』定义需先统一）；③ 17域 10 py / 5 md，逐文件同名 md 口径不现实。提案给出三类缺口的分级判据与阈值建议，待 33-REA 与 0-系统文档管理评审裁决。

---

- 复核时间: 2026-11-12
- 复核方式: 开发端直连云端 SSH 实测 + 两端文件/数据库/服务状态逐项比对
- 关键证据: `capability_gaps.jsonl` / `verdict_dashboard.json` / `D2A-ba929d3fac60/evaluation.json` / `execution_rights.json` / `XA-REAL-3f28d4b1543f.json` / `records(source='fear_greed')` / `bcrm_trades.db` / `systemctl` 状态

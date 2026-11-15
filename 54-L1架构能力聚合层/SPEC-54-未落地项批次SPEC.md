# SPEC-54 未落地项批次（Batch SPEC）

- **版本**: v0.2
- **日期**: 2026-11-15
- **状态**: 🟢 前五批已收口（B-00…B-46 全部落地，B-47 部分关闭）；新登记第六批（B-49…B-58：L1 统计交易信号层与交付物收口）
- **上游**（唯一事实源，不另立口径）：
  - [TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) §6.4.5/§6.4.6 里程碑（总计 40 项：✅ 37 / 待办 3）、§3 能力 → L0 scope 映射
  - [SPEC-54-统计图表化能力.md](./SPEC-54-统计图表化能力.md) §12.2 台账（L1S-03…06）
  - [SPEC-54-L1架构能力聚合层.md](./SPEC-54-L1架构能力聚合层.md) §3 S1–S5 / B1–B3
  - [SPEC-54-L1交易层.md](./SPEC-54-L1交易层.md) §13 LTL 台账（v0.16，**v0.2 新增上游**）
  - [capability_manifest.yaml](./capability_manifest.yaml)（能力出口唯一事实源，**实测 93 条**；`git show HEAD` 为 50 条，差额 43 条仍未提交，见 §4）
- **下游**: `l1agg/capabilities/*`、`l1agg/trading/*`、`scripts/*`、`3.1-FRONTEND`、`33-REA`/`48-涌现`（T4 消费）

> **一句话**：把「已登记但未接线 / 未落盘 / 未对齐」的存量缺口按批次收口，不改任何已验收的冻结口径。

---

## §0 纪律（硬约束）

1. **本地只写代码与测试**；生产库写入一律云端 `sudo -u luke`（认知库 `VM-1794645392149-4d591ef0`）。
2. **代码同步三段式**：本地 → GitHub → 云端 `git pull --ff-only`；禁止 rsync/scp 直传代码（`VM-1794711111945-20af9235`）。
3. **完成判定**：单测/实跑证据 + 本 SPEC 状态改 ✅ + §3 追加一行推进记录；未验收不得改状态。
4. **不改冻结口径**：`dr-1.1.0` 四轴、`trading.db` 五表、`handoff` 契约、`AXES` 四轴、`lt` 阈值（`0.764706/0.572400`）。
5. **不顺手做清单外的事**（防范围蔓延）；发现新缺口只在 §4 登记，不在本批实施。

---

## §1 批次清单

状态图例：`⬜ 待办` · `🟡 进行中` · `✅ 已验收` · `⛔ 阻塞`

### 1.1 第一批：文档与制品牌（本地可做、风险低）

| 编号 | 来源 | 事项 | 前置 | 验收标准（可复测） | 状态 |
|---|---|---|---|---|---|
| B-00 | L1S-06 | SPEC/技术设计「出口数」与 `capability_manifest.yaml` 实测（50）全量对齐 | — | 文档中不再出现 48；三处数字 = `len(manifest.capabilities)` | ✅ |
| B-01 | L1S-04 | T1–T3 制品落盘 `artifacts/visual/<capability>/<as_of>.json`（ADR-V12） | B-00 | 重复执行字节一致；幂等单测 | ✅ |
| B-02 | L1S-05 | T4 反思消费接线（33/48 读最新制品并回显 capability 列表） | B-01 | 读侧 smoke 通过 | ✅ |
| B-03 | L1S-03 | 新闻纳入 L1-S 统一出口（只读、无方向措辞） | — | 统一信封 `capability/as_of/source/items` + 禁用词扫描 | ✅ |

### 1.2 第二批：数据契约与最小能力出口

| 编号 | 来源 | 事项 | 前置 | 验收标准（可复测） | 状态 |
|---|---|---|---|---|---|
| B-04 | TD §3 / §2.1 | 新增 `datacenter.percentile` scope + **D-A05** z-score 出口 | B-00 | manifest 52 条；`zscore/mean/std`；winsorize p1/p99；单测 | ✅ |
| B-05 | TD §3 | 新增 `datacenter.correlation` scope（D-A11/A12 声明迁移） | B-04 | scope 表与 manifest 一致；A11/A12 仍全绿 | ✅ |
| B-06 | 母 SPEC B3 | `config/discovery_space.yaml` 落地（全项目当前不存在） | — | 文件存在且被 discovery 加载校验 | ✅ |
| B-07 | TD §2.7 | D-K01 方法推荐 / D-K02 发现查询（只读预计算，FAIL-OPEN） | — | manifest **54** 条（B-04 后又 +2）；产物缺失回落默认顺序 | ✅ |

### 1.3 第三批：机构统计 G 组（15 项）

D-G01 / 02 / 03 / 04 / 05 / 06 / 07 / 10 / 11 / 12 / 13 / 15 / 18 / 21 / 24 —— 逐项接线，每项独立单测；顺序按 P2→P3、依赖少的先做。

| 编号 | 事项 | 状态 |
|---|---|---|
| B-08 | D-G01 横截面 z-score / rank | ✅ |
| B-09 | D-G04 横截面离散度 / 市场宽度 | ✅ |
| B-10 | D-G05 同向率矩阵 | ✅ |
| B-11 | D-G07 序列算子族（15 个） | ✅ |
| B-12 | D-G02 组内中性化 | ✅ |
| B-13 | D-G03 分位组合与多空价差 | ✅ |
| B-14 | D-G10 逆波动权重 | ✅ |
| B-15 | D-G12 风险贡献分解 | ✅ |
| B-16 | D-G06 因子暴露 / 特质收益（P3） | ✅ |
| B-17 | D-G11 等风险贡献权重（P3） | ✅ |
| B-18 | D-G13 协方差收缩 Ledoit-Wolf（P3） | ✅ |
| B-19 | D-G15 PCA 风险分解（P3） | ✅ |
| B-20 | D-G18 Brinson 归因（P3） | ✅ |
| B-21 | D-G21 Fama-MacBeth（P3） | ✅ |
| B-22 | D-G24 因子拥挤度（P3） | ✅ |

### 1.4 第四批：科研统计 J 组（24 项）

D-J01 / 03 / 06 / 07 / 08 / 09 / 10 / 11 / 12 / 13 / 14 / 15 / 16 / 17 / 18 / 19 / 20 / 21 / 23 / 25 / 26 / 27 / 28 / 29 —— 逐项接线，每项独立单测。

| 编号 | 事项 | 方法绑定 | 状态 |
|---|---|---|---|
| B-23 | D-J01 趋势检验 Mann-Kendall + Sen | SC52/SC53 | ✅ |
| B-24 | D-J03 异常点识别 AO/LS/TC | SC92 | ✅ |
| B-25 | D-J10 熵 / 互信息 / KL | SC55/SC56/SC58 | ✅ |
| B-26 | D-J12 复杂度（LZ/样本熵/排列熵） | SC59/SC60/SC61 | ✅ |
| B-27 | D-J13 DFA / Hurst | SC62 | ✅ |
| B-28 | D-J15 不确定度合成 GUM | SC11 | ✅ |
| B-29 | D-J16 预测 / 容忍 / 共形区间 | SC10/SC12 | ✅ |
| B-30 | D-J19 ANOVA / ANCOVA / 事后比较 | SC25/SC30 | ✅ |
| B-31 | D-J20 回归诊断（VIF/BP/White/DW/Cook） | SC20–SC24 | ✅ |
| B-32 | D-J29 缺失机制与插补 | SC84–SC87 | ✅ |
| B-33 | D-J06 小波 / 滤波平滑（P3） | SC42/SC44/SC45 | ✅ |
| B-34 | D-J07 Hilbert 包络 / 瞬时相位（P3） | SC42/SC46 | ✅ |
| B-35 | D-J08 Kalman 状态估计（P3） | SC47 | ✅ |
| B-36 | D-J09 互谱相干（P3） | SC43/SC48 | ✅ |
| B-37 | D-J11 传递熵（P3） | SC57 | ✅ |
| B-38 | D-J14 极值拟合 GEV/GPD（P3） | SC63/SC64/SC65 | ✅ |
| B-39 | D-J17 功效与样本量（P3） | SC01 | ✅ |
| B-40 | D-J18 等效性检验 TOST（P3） | SC03 | ✅ |
| B-41 | D-J21 稳健 / 分位回归（P3） | SC17/SC18 | ✅ |
| B-42 | D-J23 聚类与轮廓系数（P3） | SC36–SC38 | ✅ |
| B-43 | D-J25 空间自相关 / 变异函数（P3） | SC67–SC69 | ✅ |
| B-44 | D-J26 生存分析（P3） | SC73–SC76 | ✅ |
| B-45 | D-J27 可靠性 / 控制图（P3） | SC77/SC78 | ✅ |
| B-46 | D-J28 Meta 分析与异质性（P3） | SC79–SC83 | ✅ |

**验收证据（2026-11-15 复跑，非历史记录）**：`pytest tests/test_research_stats.py` **43 passed**（24 项正向断言 + 可选分支 + 11 项短样本 fail-open 参数化 + JSON 确定性 + `method_binding=compute`），每项均输出方法列表与「不构成买卖信号」类免责句；`pytest tests/test_capabilities.py` 执行覆盖 `coverage == 1.0`（24 个 executor 白名单 + 25 条 scenario，`research_stats.run_method` 已纳入 monkeypatch）；54-L1 全量 **1312 passed**。`capabilities/research_stats.py` 33 个函数；`stats.py` 路由 **30** 个 `D-J*`（含本批之外的 J02/J04/J05/J22/J24/J30）；manifest `D-J*` 共 30 条。

**已知缺口**：无（`tests/_smoke_j.py` 已删除，J 组回归改由 `tests/test_research_stats.py` 覆盖，见 B-57）。

### 1.5 第五批：母 SPEC 阶段收口

| 编号 | 来源 | 事项 | 状态 |
|---|---|---|---|
| B-47 | 母 SPEC §3 | S2/S3/S4 由 🟡 收口（补验收证据） | ✅ 已收口（2026-11-15，母 SPEC → v1.56）：**S3 → 🟢**（§3 阶段表 + 阶段验收表两处同步 `5e692267` 全量验收 29 job/5,220 单元、`gate_pass=1,057`、`failed=0`、三轮幂等，及 v2.54 每日调度）；**S4 → 🟡 + 明确未闭环项**（二维 T2 需每资产 ≥4,000 日，当前 BTC/ETH 3,377 天；F1–F12 PIT 状态特征未完成）；**S2 保持 🟡**（方法/出口已就绪，剩余为完整四类榜单契约 + 因子池限制，非本批可关闭） |
| B-48 | 母 SPEC §3 | S5 回测排名立项（样本外 IC + walk-forward，复用 23 `FactorICSelector`） | 🟡 已立项（2026-11-15，见 §5 立项卡；未开工，前置 3 项缺陷未修） |

### 1.6 第六批（v0.2 新增）：L1 统计交易信号层 + 交付物收口

来源：[SPEC-54-L1交易层.md](./SPEC-54-L1交易层.md) §13 LTL 台账。**这批此前完全不在本批次 SPEC 内**，是「已规划、已部分落地、但无批次归属」的缺口。

| 编号 | 来源 | 事项 | 状态 |
|---|---|---|---|
| B-49 | LTL-09 | `config/weights.yaml` `mode: on`（`off` 保留回滚） | ⬜ 未落地 |
| B-50 | LTL-10 | 反思进化树制品 + 33/48 读侧 smoke（对齐 B-01/B-02 的制品链路，但作用于交易层） | ⬜ 未落地 |
| B-51 | LTL-11 | 优化反馈（DSR/SPA 晋升 + `chart_weights` 复盘） | ⬜ 未落地（依赖 B-48 的 S5 口径） |
| B-52 | LTL-15 | 龙头动态排名 `pool_version` 入 `params_hash`（B-LT4） | ⬜ 未落地（当前仅静态 `DEFAULT/EXTENDED_POOL`，无 `us_stock` 成交额打分） |
| B-53 | LTL-17 剩余 | D-E19 `conflict` 旗标三源：`curve_inverted` 需 `T10Y2Y` 进首屏池、Brent−WTI 价差、NG 库存代理、DGS10 变化率 | 🟡 仅 VIX 两旗标（`vix_pct_ge_0.90` / `vix_divergence`）已接 |
| B-54 | LTL-18 | I36 `dispersion` 进 `foresight` **强度** | 🟡 只接证据 + `forward_dispersion_wide` 旗标；进强度需先建 dispersion 历史（逐 `as_of` 落 `symbol/as_of/dispersion/pairs`）+ 自身分位归一 + 回归标定 |
| B-55 | LTL-14 尾项 | 云端回填 AMD/GEV/SPCX/SKHYNIX（本地只读副本仍 `MISSING`） | 🟡 代码已闭合（per-anchor `min_rows`），数据待云端回填 |
| B-56 | 母 SPEC v1.49 | 「金融价尺系统」子 SPEC（`SPEC-54-金融价尺系统.md` + 评审报告，均未跟踪）落地 | ⏸️ **暂不纳入落地项**（2026-11-15 用户决定：仍在探讨阶段；本批次不排期、不实施） |
| B-57 | §1.4 缺口 | 补 `tests/test_research_stats.py`（J 组 24 项 pytest 断言，替换不被收集的 `_smoke_j.py` 脚本） | ✅ 已落地：43 passed；`_smoke_j.py` 已删除 |
| B-58 | §0.2 纪律 | 前五批交付物提交与三段式同步（`git show HEAD` manifest 仍 50 条，云端无 J/G/E20/A05/K 组与交易层改动） | ⬜ 阻塞级：不提交则上述 ✅ 在云端均不生效 |

---

## §2 执行顺序

`B-00 → B-01 → B-02 → B-03 → B-04 → B-05 → B-06 → B-07 → B-08…B-22（G）→ B-23…B-46（J）→ B-47/B-48 → B-58（提交与同步，阻塞级优先）→ B-49…B-57`

理由：先对齐文档事实数（避免后续每加一项都要改两处），再落制品（解锁 T4 消费），再补数据契约（解锁 A05 与 K 组），最后批量接线能力出口。**v0.2 追加两条纪律**：① B-58 虽是最后编号，但必须先做——未提交/未 pull 的 ✅ 在云端等于不存在；② 交易层（B-49…B-55）与统计层共用同一 manifest，接线前必须先确认 `method_binding` 与出口计数同步，避免两线各改一处数字。

---

## §3 推进记录

| 日期 | 编号 | 变更 | 证据 |
|---|---|---|---|
| 2026-11-15 | — | 立批：清单 49 项（B-00…B-48），来源与验收标准逐项锚定上游文档 | 本文件 §1 |
| 2026-11-15 | B-00 | **L1S-06 关闭**：机检确认 manifest 实测 50 条（ID 唯一），`TECHNICAL_DESIGN.md` 头部 + §2.5 三处「50」、母 SPEC §588「manifest 共 50 条能力声明」全部一致；`stats.py` 编排函数 47 = manifest `stats.*` 引用 47。文档正文无需修改 | `pytest tests/test_capabilities.py` 全绿；`SPEC-54-统计图表化能力.md` L1S-06 → ✅ + §12.3 新增记录 |
| 2026-11-15 | B-01 | **L1S-04 关闭**：新增 `l1agg/persistence/artifacts.py`（规范 JSON / `os.replace` 原子写 / token 白名单 / `L1_ARTIFACTS_ENABLED` FAIL-OPEN / 幂等跳过重写），`visual_overview.py` 产图后按 `source_capability` 分组落盘并回显 `artifacts` | `pytest tests/test_artifacts.py` **14 passed**；实跑 `--days 400` 首次写 `D-E10/E12/E15/E16/E17/E18/T3`（7 个），二次执行 **7 个全部 `unchanged`**，`artifacts/visual/` 落盘 7 文件 |
| 2026-11-15 | B-02 | **L1S-05 关闭**：`artifacts.py::consume_latest`（逐能力取最新 / 全局 `as_of` / 空态 `ok=True`）+ `33-REA.../core/reflection/thought_tree.py::load_l1_visual_artifacts`（sys.path 桥接 + FAIL-OPEN） | `pytest tests/test_artifacts.py` **16 passed**、`33-REA/tests/test_l1_artifacts_smoke.py` **2 passed**；真实制品回显 `D-E10/E12/E15/E16/E17/E18/T3`、`as_of=2026-11-11` |
| 2026-11-15 | B-03 | **L1S-03 关闭**：新增 **D-E20** 新闻统一出口（manifest 50 → **51**）；`capabilities/news.py::news_digest` 只读 `mm_metrics.social_volume` 观测 → 统一信封，零重算、不做情绪打分；`scan_forbidden` 命中禁用词即抛 `ValueError`；无新闻条目表不编造标题/正文/链接；`as_of` 严格截断；<2 天 empty / 条数缺失 partial；`stats.py` 登记调度 + `supported()` 含 D-E20；TD 头部/§2.5 三处、母 SPEC 头部/§588/§6.4 #34/#39 计数同步为 51 并新增 #40 边界条目 | `pytest tests/test_news_digest.py` **7 passed**；真实库 `as_of=2026-11-14` → `ok=True / good / 38 条 / 缺失 0 天`；54 模块全量 `pytest tests -q` EXIT=0 |
| 2026-11-15 | B-04 | **`datacenter.percentile` scope + D-A05 关闭**：`capabilities/stats.py::zscore`（复用方法层 **S26**：winsorize p1/p99、`min_n=30`、`std=0 → z=None`），能力层只做窗口切片与参数校验；新增 `MIN_ZSCORE=30`/`MIN_ZSCORE_LOOKBACK=60`；三档降级 `lookback_truncated` / `short_lookback` / `zero_variance`（`z=None`，不伪造 0）；manifest 51 → **52 条**；TD 头部 + §2.5 三处（52 个出口 / 52 条 / 48 个编排函数 / 出口清单含 D-A05）+ §6.1 新增 v2.52 表 + §3 scope `datacenter.percentile` → ✅；母 SPEC v1.49 → **v1.50**（第 34 条 52 个、新增第 41 条边界、§十二 v1.50 三条） | `pytest tests/test_zscore.py` **6 passed**；`pytest tests/test_capabilities.py` **189 passed**（executor 白名单 + scenario 补 D-A05）；实测常量序列 `z=None/mean=0.01/std=0.0/winsorized=True`、递增序列 `z=1.67276` |
| 2026-11-15 | B-05 | **`datacenter.correlation` scope 关闭**：manifest D-A11/D-A12 `data_scope` 由 `datacenter.series` 迁到 `datacenter.correlation`，`stats.py::rolling_correlation` / `lead_lag_correlation` 的 `quality.sources` 同步改为 `datacenter.correlation`；顺带把 D-A04（`percentile_rank`）scope 对齐到 `datacenter.percentile`（B-04 已声明该 scope）；TD §3 scope 表：`datacenter.correlation` → ✅、`datacenter.percentile` 支撑能力收敛为 D-A04/05、`market.candles` 补 D-A07；母 SPEC → v1.52（v1.51 已被 MERS S3 验收占用，本次顺延） | `pytest tests/test_capabilities.py` **全绿**（4 处 `data_scope` 断言同步更新）；D-A11/D-A12 行为用例未改动仍通过 |
| 2026-11-15 | B-06 | **Discovery 搜索空间预注册落地**：新增 `config/discovery_space.yaml`（16 序列 = 8 资产池 + 8 宏观白名单 / 6 变换 / 20 方法 / h∈{1,5,20} / 70-30 分段 / BH-FDR α=0.05 / 去重 0.95 / 预算 5,000 单元）与 `l1agg/discovery.py::load_space`（冻结项机器校验 + `space_hash` + 预算估算）；资产序列必须能解析到 `asset_pool.yaml` 的 `anchors[].storage.sub_category` | `pytest tests/test_discovery_space.py` **13 passed**：哈希确定性、方法均在 `REGISTRY`、资产可解析、9 类篡改（seed / 变换 / 未登记方法 / 越出子集 / 未知资产 / 重复序列 / 预算超限 / 关闭 FDR / 分段非 70-30 / 26 序列 325 对超 300）全部拒绝 |
| 2026-11-15 | B-07 | **D-K01/D-K02 评估层只读出口关闭**：新增 `capabilities/eval_exports.py`。D-K01 只读 `relationship_registry.db`（`file:...?mode=ro`），`gate_pass=1` 且 `status∈(stable,candidate)`，RankIC 绝对值 Top3；Top1 candidate → `partial`+`candidate_only`，缺表 → `empty`。D-K02 只读最近一期 `reports/discovery/<YYYYMMDD-HHMM>/`，恒标 `candidate`，0 候选 → `partial`+`no_findings`，目录缺失 → `empty`。manifest 52 → **54 条**；TD 头部 + §2.5 三处 + §2.7 两行 + §3 两个 scope 行 + §6.1 v2.55 表；母 SPEC v1.52 → **v1.54**（§2.7 第 43/44 条 + §十二 v1.54 五条） | `pytest tests/test_eval_exports.py` **9 passed**（缺表/无匹配空态、candidate 降级、stable 提级、gate_pass=0 排除、最新报告优先、无候选降级、调度器路由）；54-L1 全量 **1244 passed** |
| 2026-11-15 | B-08…B-22 | **G 组 15 项一次性接线关闭**：新增 `capabilities/institutional.py`（15 个出口 + `_panel_of`/`_series_of`/`_call`/`_latest_map`/`_empty`/`_quality` 辅助），全部经 `l1agg.methods.run` 调方法层，零重算。方法映射：G01=X01+X02、G02=X03、G03=X04+X05、G04=X06+X07、G05=X08、G06=X09+X10、G07=O01–O15、G10=P03、G11=P04、G12=P05、G13=P06、G15=P08、G18=P12、G21=Q05、G24=P13+P14。`stats.py` 登记 15 个执行器 + 意图；manifest 54 → **69 条**（全部 `method_binding: compute`、`mode: deterministic`） | `pytest tests/test_institutional.py` **25 passed**（信封契约、methods ⊆ manifest、非 good 必含「样本」、确定性、空态降级、O09/O10 双序列路径）；`pytest tests -q` **1269 passed** |
| 2026-11-15 | B-23…B-46 | **J 组 24 项核验关闭（v0.2 复核，非新写代码）**：`capabilities/research_stats.py`（33 函数，1,469 行）经 `l1agg.methods.run` 调方法层，`stats.py` 已登记 30 个 `D-J*` 执行器与意图；manifest `D-J*` 30 条全部 `method_binding: compute` | 首验用 `tests/_smoke_j.py` **24/24 `ok=True/quality=good`**（该脚本已删除，现由 `tests/test_research_stats.py` 43 passed 取代，见下一行）；`yaml` 实测 manifest 总 **93 条**（唯一 ID 93） |
| 2026-11-15 | B-47 | **S3 收口确认**：母 SPEC `S3 🟡` 行文案已过期（仍写「待全量真实数据验收及云端周期调度」），实际由 #35 全量验收（`5e692267`）+ 每日调度（`87c4e1205c`/`f1b869078b`）关闭；S2/S4 未收口原因分别登记为因子池回填与 Tier A 样本纵深 | TD §6.4.5 #35 行 ✅（v2.54）；`deploy/systemd/dreambuddy-mers.timer` + `last_summary.json`（29 job / 5,220 单元 / gate_pass 1,057 / added=0 / prune 90 天） |
| 2026-11-15 | 台账修数 | **header 事实数纠正**：原文「实测 50 条」→ **93 条**；`git show HEAD:capability_manifest.yaml` = **50 条**（差额 43 条全在工作区未提交）；TD 里程碑总数口径由「42 项 ⬜/🟡」更正为「40 项：✅37 / 待办 3」 | `git diff --stat capability_manifest.yaml` → 432 insertions / 3 deletions；`git status --porcelain` 见 §4 |
| 2026-11-15 | B-56 | **范围冻结**：用户决定「金融价尺系统」仍处探讨阶段，暂不纳入落地项；本批 §1.5 B-56 状态 ⬜ → ⏸️，子 SPEC 头部加 ⏸️ 标注，母 SPEC v1.49 历史行加注，§4 登记解冻条件 | `SPEC-54-金融价尺系统.md` 头部状态已改；`l1agg/fns/` 未创建任何文件（`git status` 无该目录） |
| 2026-11-15 | B-47 / B-48 | **第五批收口**：B-47 关闭——母 SPEC §3 阶段表与阶段验收表两处 S3 由 🟡 → 🟢（写入 `5e692267` 全量验收：29 job / 5,220 单元、`gate_pass=1,057`、`failed=0`、三轮幂等 `added=0`；及 v2.54 每日调度），S4 由 ⬜ → 🟡 并显式列出未闭环项（二维 T2 需每资产 ≥4,000 日，当前 BTC/ETH 3,377 天；F1–F12 PIT 特征），S2 保持 🟡（方法/出口已就绪，剩完整四类榜单契约）；B-48 立项——新增 §5 立项卡（DoD / P1–P3 前置缺陷 / In-Out 范围 / G1–G5 门禁 / 依赖顺序与风险），状态 🟡 已立项未开工 | 母 SPEC v1.56 §3 两处已同步；本文件 §1.5 状态列 + §4 两条「已关闭」+ §5 立项卡 |
| 2026-11-15 | B-23…B-46 / B-57 | **J 组回归转为 pytest 门禁（替换人工脚本）**：新增 `tests/test_research_stats.py`（24 项正向 `_assert_contract`、可选分支 J10/J15/J16/J26、11 项短样本 fail-open 参数化、JSON 确定性、`method_binding=compute` 且 `mode=deterministic`、methods 排序去重）；`tests/test_capabilities.py` 执行覆盖新增 24 个白名单 + 25 条 scenario（J16 单/双序列两条，J15 带 `components`、J26 带 group+covariate、J10 带 `other`）+ `research_stats.run_method` monkeypatch；修复 D-J17 场景改用显式 `effect_size=0.3` 使 SC02 收敛；删除 `tests/_smoke_j.py` | `pytest tests/test_research_stats.py` **43 passed**；`pytest tests/test_capabilities.py` 全绿（`coverage == 1.0`）；54-L1 全量 **1312 passed**；TD v2.57 与母 SPEC v1.56 已同步计数与 24 行状态 |

---

## §4 清单外新发现（只登记，不在本批实施）

| 日期 | 发现 | 建议 |
|---|---|---|
| 2026-11-15 | **B-56「金融价尺系统」冻结**：用户决定仍在探讨阶段，暂不纳入落地项；本批次 §1.5 已标 ⏸️，母 SPEC v1.49 的历史行同步加注 | 待主线（统计层 → 图表输出 → 信号层）跑通后再复审；解冻前不得在 `l1agg/fns/` 建任何代码，避免半成品入口混入 manifest 计数 |
| 2026-11-15 | **交付物全部未提交（阻塞级）**：`git show HEAD:capability_manifest.yaml` 仅 **50** 条，工作区 **93** 条（+432 行）；未跟踪文件含 `capabilities/{institutional,research_stats,news,eval_exports}.py`、`discovery.py`、`persistence/artifacts.py`、`config/discovery_space.yaml`、`scripts/{calibrate_light,light_history}.py` 及 9 个测试文件；已修改未提交含 `capability_manifest.yaml` / `lights.py` / `stats.py` / `chart_weights.yaml` / 三份 SPEC / TD。即 B-00…B-46 的 ✅ 全部只存在于本地，云端仍是最早 50 条版本 | 按 B-58 一次性精确 `git add` + 分段 commit + push + 云端 `pull --ff-only`；提交前先确认并行线（LTL-16/交易层）已停手，避免 manifest 与 `lights.py` 冲突 |
| 2026-11-15 | **J 组无 pytest 覆盖**（已关闭）：`tests/_smoke_j.py` 以 `_` 开头，pytest 不收集；`tests/test_capabilities.py` 仅引用 6 个 `D-J*`。当时 24 项能力靠人工跑脚本回归 | ✅ B-57 已补 `tests/test_research_stats.py`（43 passed）并扩展执行覆盖到 24 项，`_smoke_j.py` 已删除 |
| 2026-11-15 | **D-A14（`crowding`）manifest `data_scope: [mm_metrics]`，但 TD §3 scope 表无 `mm_metrics` 行** | 单独立项补 §3 `mm_metrics` scope 行（勿在本批顺手加） |
| 2026-11-15 | **母 SPEC §3 `S3 🟡` 行文案过期**（已关闭，B-47）：§3 阶段表与阶段验收表两处已同步为 🟢 并写入 `5e692267` / v2.54 调度证据；S4 同步为 🟡 + 明确未闭环项 | ✅ 已随母 SPEC v1.56 同步，冻结口径未改 |
| 2026-11-15 | **交易层与统计层共用 manifest 但无双线合并纪律**：`D-E15…D-E19`（交易层，`method_binding: display`）与 `D-G/D-J`（统计层，`compute`）写同一文件，两线并行时出口计数（54/69/93）各执一词（TD 头部 69、manifest 93、交易层 SPEC 写 48） | 以 `len(manifest.capabilities)` 为唯一机器校验值，三份文档只引用不手写；建议在 `tests/test_capabilities.py` 增一条「文档声明的出口数 == manifest 实测」断言 |

---

## §5 B-48 立项卡：S5 回测排名（样本外 IC + walk-forward）

**立项理由**：S1–S4 已进入「可交付 + 有验收证据」状态（S3 🟢 / S4 🟡 仅差样本纵深），S5 是唯一完全未动的阶段；且 `23-FactorICSelector` 已有可复用实现，缺口是「样本外 + walk-forward + 前置缺陷」。

**目标（DoD）**：
1. 对因子池输出**样本外 IC / ICIR**（训练段拟合、held-out 段评估），并给出 walk-forward 逐窗排名与稳定性；
2. 排名结果落只读制品（复用 B-01 `persistence/artifacts.py`），可被 L1 `D-K*` 或 T4 反思消费；
3. 全部结论带 `n/window/p_adj/segment`，随机数据负例不得产生稳定排名。

**前置缺陷（必须先修，缺一不可开工）**：

| # | 缺陷 | 位置 | 修复口径 |
|---|---|---|---|
| P1 | `forward_returns` 多位移 `h-1`（h>1 前瞻收益错位） | 23 `FactorICSelector` | 统一改用 54 `l1agg/align.py::forward_returns` 同口径，或按 `shift(-h)` 修正并加回归用例 |
| P2 | `ic_ir` 对 5 个 horizon 混算，属伪口径 | 23 `FactorICSelector` | 按 horizon 分别计算 ICIR，不跨 horizon 聚合 |
| P3 | `price_path` 绕过 19 数据访问层直连文件 | 23 `FactorICSelector` | 改为经 `19-数据访问层` Repo 只读接口，禁止直读 |

**范围（In）**：因子排名评估器 + walk-forward 分段 + 制品落盘 + 单测/负例。
**范围（Out）**：不开放 `relationship_recommend` 对外推荐（归 S5 后续）、不改 MERS 注册表状态机、不做自动交易决策。

**验收门禁（G1–G5）**：
- G1 前置缺陷 P1–P3 各有回归用例（红→绿）；
- G2 样本外 IC 与训练段 IC 分离报告，`segment=train/holdout` 显式；
- G3 walk-forward 逐窗结果可复现（同 seed 同输入字节一致）；
- G4 随机白噪声负例：稳定排名数 = 0；
- G5 制品幂等（二次运行 `unchanged`）。

**依赖与顺序**：B-58（提交/同步）→ P1–P3 → 评估器实现 → 制品接线 → 负例与文档。
**风险**：23 与 54 双实现口径漂移 → 以 54 `align.py` 为唯一 SSoT；walk-forward 窗数不足 → 强制披露 `insufficient_windows` 并降级为单段样本外。

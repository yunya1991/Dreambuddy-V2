# 9基本面 7 引擎 S/A 级 dao/tian Shadow Boost · 验收 Checklist

- 关联 Spec: [2026-08-29-fundamental-7engines-daotian-boost-spec.md](./2026-08-29-fundamental-7engines-daotian-boost-spec.md) v1.0 📝 Draft
- 关联 Tasks: [2026-08-29-fundamental-7engines-daotian-boost-tasks.md](./2026-08-29-fundamental-7engines-daotian-boost-tasks.md) v1.0
- 版本: v1.0
- 生效日期: 2026-08-29
- 维护者: DreamBuddy · 战略层集成组

---

## 一、总验收 Checklist（Spec §9 汇总，分 4 大类，约 25 项）

> 顺序: 阶段1(9) → 阶段2(8) → 阶段3 运维观察(4) → 收尾开开关(4) = **25 项**

### 1.1 阶段1：4 代理模块 + S/A 4 方法 + 2 乘法守卫（9 项）
| # | 验收项 | 达标标准 | 验证命令 / 方法 | 状态 |
|---|---|---|---|---|
| A1 | 4 代理模块创建且 import 成功 | engines/event_ledger_engine.py / event_mapping_engine.py / narrative_engine.py / news_contract_validator.py 均存在；`python -c "from engines.event_ledger_engine import generate_ledger; print(generate_ledger([]))"` 4 件无 ImportError | cd 9基本面 → 4 命令各 exit 0 | [ ] |
| A2 | 4 代理模块 sys.path.insert 正确 | 每个代理模块头 import sys + os.path.join("ops/nanoclaw/core_task1") 路径正确（相对路径拼接不写死用户名）| `grep sys.path.insert 9-基本面分析/engines/*_engine.py` → 4 条输出 | [ ] |
| A3 | 阶段1 15 TC 全绿 | `pytest tests/test_fd7engines_stage1.py -v` → **15 passed, 0 failed** | `cd 11-易经推理系统 && python -m pytest tests/test_fd7engines_stage1.py -v` | [ ] |
| A4 | S 级 delta clamp 精确 ±0.10 | TC-7 两个断言：正极端=0.10 abs≤1e-6；负极端=-0.10（可 monkeypatch 强制 sum=0.25 验证 clamp）| 读 TC-7 运行结果 log | [ ] |
| A5 | A 级 delta 顶 ±0.04 / ±0.02 | A_dao 极值 monkeypatch 强制 v=1/a=1/conf=1 → +0.04 精确；A_tian w_ratio=2.0 → (1)×0.03=0.03→clamp到+0.02 精确 | 手工 monkeypatch 运行断言 | [ ] |
| A6 | 乘法联合顶 dao_raw=80 → dao_final=100 精确 | TC-13 断言 dao_final=100（联合乘数 1.5246×80=121.968→clamp 100） | 同 A3 运行结果 | [ ] |
| A7 | 红线关字节一致 | enable=False 下 compute() 结果与 baseline（未实施版本）字节 deep_equal（TC-2）| TC-2 PASS | [ ] |
| A8 | 单引擎 FAIL-OPEN 隔离生效 | 单独把 S3 schema_validator 抛 ImportError → 方法不抛，返回值仍 float 合法区间，非 None（TC-14 3 场景）| TC-14 PASS | [ ] |
| A9 | 三文件回归（阶段1 + Odaily 两文件）无破坏 | pytest 3 个文件合计 15+7+6 = 28 passed，0 failed | 命令见 Tasks T16 | [ ] |

### 1.2 阶段2：Shadow 红线 + JSONL 9+字段 + 7门槛脚本（8 项）
| # | 验收项 | 达标标准 | 验证方法 | 状态 |
|---|---|---|---|---|
| B1 | 类属性红线默认 False | `FiveDomainFeatureComputer.enable_fundamental_7engines_boost is False` 断言 TC-1 GREEN | TC-1（阶段2）PASS | [ ] |
| B2 | 阶段2 10 TC 全绿 | `pytest tests/test_fd7engines_shadow_stage2.py -v` → **10 passed, 0 failed** | 运行 pytest | [ ] |
| B3 | JSONL 9+字段 schema 齐全 | FD_OK line 读：9 主字段全存在 + engine_detail 10 子字段全存在且数值合法（S3_pass_rate[0,1]、A6_sign{-1,0,1}、A7_ratio[0.3,2.0]）| TC-2 / TC-8 PASS | [ ] |
| B4 | 原因码 5 枚举全覆盖 TC | TC-2 FD_OK / TC-3 FD_NO_NEWS_BATCH / TC-4 FD_IMPORT_ERROR / TC-5 FD_PERMISSION / TC-6 FD_GENERIC_ERR → 5 原因码全部至少 1 条 GREEN | 5 个对应 TC 各 1 PASS | [ ] |
| B5 | Shadow 只读不改结果 | enable=True vs False → `result_true == result_false` 字节完全相等（TC-7）| TC-7 PASS | [ ] |
| B6 | fd7engines_hitrate_eval.py 退出码三态正确：(a) 10 条 → rc=2 样本不足；(b) 2000 条含 1 IMP_FAIL → rc=1 FAIL；(c) 2000 条完美 → rc=0 PASS | TC-9 / TC-10 / T28 GREEN（3 场景） | 运行脚本 subprocess 返回值验证 | [ ] |
| B7 | runtime JSONL 空占位创建 | `scripts/runtime/fundamental_7engines_records.jsonl` 存在且 size=0B | `ls -la / wc -c` | [ ] |
| B8 | 四文件总回归（阶段1+2 + Odaily×2）无破坏 | 15+10+7+6 = **38 passed, 0 failed** | 合并 pytest 四文件 | [ ] |

### 1.3 阶段3：运维 + 7 日历天观察（4 项）
| # | 验收项 | 达标标准 | 验证方法 | 状态 |
|---|---|---|---|---|
| C1 | FUND_7ENGINES_BOOST=1 注入成功 | `grep export start_trading.sh polling_trader_live_300s.sh` 两行；`ps eww <PID> | grep -o FUND_7ENGINES_BOOST=1`（检查运行时 env） | 2 处检查 | [ ] |
| C2 | Shadow 生产 7 天 ≥ 1500 条 JSONL；原因码分布 ≥ 80% FD_OK | `wc -l JSONL ≥ 1500`；python 统计分布 Counter，FD_OK / 总数 ≥ 0.80 | `tail JSONL + Counter` | [ ] |
| C3 | G4 IMPORT_FAIL_total = 0（必须）| 7 天全量 `import_fail_count` 累加 = 0 | eval 脚本 G4 项 | [ ] |
| C4 | 7 门槛 G1~G7 全 PASS → fd7engines_hitrate_eval.py 退出码=0（必须）| eval 脚本 stdout 7 行均 ✅ PASS；returncode=0；报告 JSON ALL_PASS=true | 脚本运行 stdout + JSON | [ ] |

### 1.4 收尾：开开关 + 文档 + Day14 观测（4 项）
| # | 验收项 | 达标标准 | 验证方法 | 状态 |
|---|---|---|---|---|
| D1 | PR+CR 通过后，类属性 enable_fundamental_7engines_boost: bool = True 已合 main | `grep enable_fundamental_7engines_boost five_domain_feature_computer.py | head -1` → 行末 = True | grep 输出 True | [ ] |
| D2 | 重启后 Day 1 生产 4 boost 实际值非 0（开启生效）| compute() 实际 dao/tian 与 enable=False baseline 差值 ≥ 1 分（非零，验证乘法守卫真的乘了 S/A） | 手工 python 脚本跑两次对比 | [ ] |
| D3 | 5 文档更新 + Spec 三件套状态更新 | CHANGELOG / ENGINEERING_INDEX / DOC_DEBT_INDEX / README / Spec 头部均更新为 ✅ Approved / 🏗️ 已落地 | 5+3=8 处 git diff 存在 | [ ] |
| D4 | Day14 thaw_count ≥ 3 & war_state = ALLOW（cap ≥ 50%）| five_domain_state.json 中 thaw_count=3 或更高；_by_class.crypto_usdt.war_state=ALLOW；cap ∈ [0.50, 0.80]（解冻档位）；未出现 war_state 长时间 FREEZE 不动 | cat 状态文件 | [ ] |

---

## 二、分阶段详细 Checklist（按 Tasks DAG 顺序打勾）

### 2.1 阶段1 TDD · 15 TC（T01 ~ T19，19 Tasks = 15TC 含 CR）
- [ ] T01 阶段1 测试脚手架 + 10 fixture（fx_positive_news / fx_negative_news / fx_dao_up / fx_dao_down / fx_signal_accurate / fx_signal_inaccurate / fx_r3_sample / fx_news_empty / mock_sqlite_news / 路径 import）
- [ ] T02 RED 证据：4 代理模块 NOT EXISTS → pytest 启动时 4 断言 FAIL（证明代码未先写）
- [ ] T03 新建 4 代理模块薄封装（sys.path.insert + 对外函数签名 + try/except→[]）
- [ ] T04 pytest 4 NOT EXISTS 现在 PASS；fixture 加载无 SyntaxError
- [ ] T05 TC-1 None/Empty → 0.0（RED）→ _fd_S_dao/_fd_S_tian 骨架 + try/except（GREEN）
- [ ] T06 TC-2 红线关字节一致（RED）→ dao L244 + tian L349 两行乘法守卫（GREEN）
- [ ] T07 TC-3 S_dao 正命中（RED）→ §4.2 D1~D5 算法逐项实现（GREEN）
- [ ] T08 TC-4 S_dao 负 / TC-5 S_tian 政策正 / TC-6 S_tian 紧急负（RED → GREEN × 3）
- [ ] T09 TC-7 S 级 clamp ±0.10 精确（RED → GREEN；含 monkeypatch sum 强制超界验证 clamp）
- [ ] T10 TC-8/9/10/11/12 A 级 5 项（RED → GREEN × 5，_fd_A_dao / _fd_A_tian 两方法完成）
- [ ] T11 TC-13 乘法联合顶 dao_raw=80 → 100 精确（RED → GREEN）
- [ ] T12 TC-14 单引擎 FAIL-OPEN 隔离 × 3 场景（RED → GREEN）
- [ ] T13 TC-15 fx_r3_sample 四点命中 + 乘法精确差 ≤ 1e-6（RED → GREEN，必要时 Spec v1.0.1 系数微调补丁）
- [ ] T14 代码风格 CR：签名 / isinstance 守卫 / deltas list sum / round 6 / clamp / 外层 except 全部对齐 _od_dao_boost 写法
- [ ] T15 FAIL-OPEN L1~L6 全覆盖清单核对 +（可选）pytest-cov 新增行 ≥ 90%
- [ ] T16 三文件 28 TC 总回归全 GREEN（阶段1 + Odaily stage1/2）
- [ ] T17 阶段1 验收 4 项归档（C1~C4 Checklist 对照打勾）
- [ ] T18 Spec §7.1 7 个文件变更逐项核对（代理4个 / FC.py 修改 / test_file）→ 7/7
- [ ] T19 6 张 RED→GREEN 关键截图归档 spec_evidence 目录

### 2.2 阶段2 TDD · 10 TC（T20 ~ T32，13 Tasks = 10TC + 收尾）
- [ ] T20 阶段2 脚手架 + 9 fixture（_mk_computer 构造器 / fd_r3_sample / news_5items / monkeypatch_import_err / monkeypatch_permission / monkeypatch_runtime_err / fd_2000_ok / fd_2000_fail_g4 / fd_10items）
- [ ] T21 TC-1 红线默认 False + JSONL 不写 + 字节一致（RED → GREEN：类属性 False + env FUND_7ENGINES_BOOST 读取）
- [ ] T22 TC-2 JSONL 9+字段齐全 + FD_OK（RED → GREEN：实现 _fd_7engines_shadow_compute 主函数 ~200 行 + 9 字段 + engine_detail 10 子键）
- [ ] T23 TC-3 FD_NO_NEWS_BATCH 原因码（RED → GREEN：len(news)<10 分支覆盖）
- [ ] T24 TC-4 FD_IMPORT_ERROR + import_fail_count ≥ 1（RED → GREEN：7 引擎 import 存在性检查）
- [ ] T25 TC-5 FD_PERMISSION 吞异常不抛（RED → GREEN：JSONL append try/except OSError）
- [ ] T26 TC-6 FD_GENERIC_ERR（顶层大 try）+ TC-7 Shadow 只读字节相等 + TC-8 engine_detail 数值合法（RED → GREEN × 3）
- [ ] T27 TC-9 eval 脚本 exit=2 样本不足 / TC-10 G4 FAIL exit=1（RED → GREEN × 2，新建 fd7engines_hitrate_eval.py）
- [ ] T28 exit=0 完美样本（2000 条超阈值）验证（G1~G7 全 PASS 报告 JSON ALL_PASS=true）
- [ ] T29 创建空占位 JSONL 0B；.gitignore 检查
- [ ] T30 四文件 38 TC 总回归（15+10+7+6 = 38 passed）
- [ ] T31 完美样本 PASS 日志 + 总回归截图归档（2 张）
- [ ] T32 阶段2 PR CR + Merge main

### 2.3 阶段3 运维观察（T33 ~ T40，8 天）
- [ ] T33 JSONL 空占位确认（wc -c = 0）
- [ ] T34 start_trading.sh & polling_trader_live_300s.sh 各加一行 export FUND_7ENGINES_BOOST=1
- [ ] T35 清 five_domain_state.json + 重启 polling_trader（战略层代码改后 H10 重启）；新 PID 稳定 300s 不崩
- [ ] T36 Day 1 检查：Shadow JSONL ≥1；reason 第一行 FD_OK；import_fail_count=0；S3_pass_rate ≥ 0.90；odaily shadow 并行增长（两条流水线独立 ✅）
- [ ] T37 Day 3：wc ≥ 400；IMPORT_FAIL_total=0；FD_OK 分布 ≥ 70%（留 10% 给 Day 5）
- [ ] T38 Day 5：预跑 eval 脚本 → 记录 7 门槛实际值（若样本≥1500 就 exit=1/2/0，否则 2），归档报告 JSON
- [ ] T39 Day 7：正式评估 exit=0/1/2 → 归档 Day7 最终 JSON 报告
- [ ] T40 判定：
  - [ ] exit=0 → 收尾 T41
  - [ ] exit=1 → 发 issue + 延 7 天循环 T36-T39
  - [ ] exit=2 → 延 2 天重跑 T39
  - [ ] 连续 21 天 exit=1 → Spec v1.1 修订 PR（G5/G6 阈值降低，CR 批准后重试）

### 2.4 收尾（T41 ~ T47，7 Tasks）
- [ ] T41 PR1：Day5 + Day7 双报告 + 原因码分布 + 样本统计（纯文档 PR，不改代码）→ CR 通过
- [ ] T42 PR2：开开关 `enable_fundamental_7engines_boost: bool = True`（附报告路径注释）→ CR 通过 → Merge main
- [ ] T43 部署：清 five_domain_state.json + 重启 polling_trader（H10 再次重启）；新 PID 稳定
- [ ] T44 Day 1 生产真开启：4 boost 实际生效非 0；dao/tian 差值 ≥ 1 分
- [ ] T45 文档 5 处更新 + Spec/Tasks/CheckList 三件套头部状态更新（📝 Draft → ✅ Approved → 🏗️ 已落地，附 PR 号与完工日期）
- [ ] T46 Day14 观测：thaw_count ≥ 3 / war_state = ALLOW / cap ∈ [0.50, 0.80]（若仍 FREEZE 则延 3 天）
- [ ] T47 A/B 复盘报告：pn×od 基线 vs pn×od×fd_S×fd_A 真开启，14 天对比 dao/tian/总分/thaw_count/war_state × 4 维度；附时间序列折线图（或表格）→ 11/CHANGELOG v4.5.2 附录

---

## 三、FAIL-OPEN 6 层级验证 Checklist（L1~L6 各至少 1 TC 覆盖）

| 层级 | 故障语义 | 对应验收项 | 验证方法 | 状态 |
|---|---|---|---|---|
| L6 | 顶层乘法守卫（enable=False 字节一致） | TC-2（阶段1）/ TC-1（阶段2） | enable=False → result == baseline ✅ | [ ] |
| L5 | shadow_compute 大 try 吞（未知异常） | TC-6（阶段2 FD_GENERIC_ERR）| 抛 RuntimeError → 仍写 JSONL，顶层不崩 ✅ | [ ] |
| L4 | 4 boost 方法外层 try 吞（方法整体异常） | TC-1（阶段1 None/Empty）| 方法整体异常 → return 0.0 ✅ | [ ] |
| L3 | SQLite news 查询 DB 异常（news_list 空） | TC-3（阶段2 NO_NEWS_BATCH）+ TC-1（阶段1 Empty）| DB 挂 → news_list=[] → S=0，A 仍工作，原因码 NO_NEWS ✅ | [ ] |
| L2 | 7 引擎 import 级错误 | TC-4（阶段2 IMPORT_ERROR）+ T03 代理创建 4 NOT EXISTS 验证 | 4 代理缺 → import_fail_count≥1，仍不崩，S/A=0 ✅ | [ ] |
| L1 | 单引擎 delta 内部异常（非 import，入参错等） | TC-14（阶段1 3 场景隔离）| 单独挡 1 引擎抛错 → 其他 6 个正常，总和仍合法区间 ✅ | [ ] |

---

## 四、7 门槛 G1-G7 PASS 记录位（7日历天后填，**必须全打勾才可开开关**）

| 门槛 | 阈值 | 实际值（Day7） | PASS？| 备注 |
|---|---|---|---|---|
| G1 hit_rate_effective | ≥ 0.60 | ____ | [ ] | FD_OK / (总 - NO_NEWS_BATCH) |
| G2 thaw_accuracy | ≥ 0.70 | ____ | [ ] | 连续 3 日正贡献窗口率（缺解冻标签代理）|
| G3 sharpe_annual | ≥ 1.05 | ____ | [ ] | 日级 boost 均值 / std × √252 |
| G4 IMPORT_FAIL_total | = 0 | ____ | [ ] | 全量 JSONL import_fail_count 累加 |
| G5 S_ACCURACY | ≥ 0.75 | ____ | [ ] | S1/S2/S5 三符号一致率 |
| G6 A_CONSISTENCY | ≥ 0.60 | ____ | [ ] | A6 方向 vs A7 w_ratio-1 一致率 |
| G7 SCHEMA_PASS_RATE | ≥ 0.95 | ____ | [ ] | engine_detail S3_pass_rate 均值 |
| 样本量 N | ≥ 1500 | ____ | [ ] | `wc -l JSONL` |
| 退出码 exit | = 0（全 PASS）| ____ | [ ] | **exit=0 才能进入 T41+T42 收尾流程** |

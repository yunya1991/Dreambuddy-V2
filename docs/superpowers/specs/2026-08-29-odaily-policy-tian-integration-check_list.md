# Odaily 政策维度 · 天（tian）子项集成 · 验收清单

- 关联 Spec: [2026-08-29-odaily-policy-tian-integration-spec.md](./2026-08-29-odaily-policy-tian-integration-spec.md)
- 关联 Tasks: [2026-08-29-odaily-policy-tian-integration-tasks.md](./2026-08-29-odaily-policy-tian-integration-tasks.md)
- 版本: v1.0
- 生效日期: 2026-08-29
- 维护者: DreamBuddy · 战略层集成组

---

## 一、总验收 Checklist（Spec §9 汇总，共 20 项）

> 顺序: P0-1(6) → P0-2(7) → P0-3 阶段1(4) → P0-3 阶段2(3+开关 1=4) = **20 项**

### 1.1 P0-1 launchd 调度器托管（6 项）

| # | 验收项 | 达标标准 | 验证命令 / 方法 | 状态 |
|---|--------|----------|-----------------|------|
| A1 | launchd PID 存活 ≥24h | `launchctl list` 中 PID ≠ -，持续 24h 不变 | `launchctl list | grep com.dreambuddy.dc-scheduler` + `ps -p <PID> -o etime=` | [ ] |
| A2 | panewslab 日采集 ≥48 行 | SQLite records 表 sub_category=panewslab，今日 ≥48 | `/opt/anaconda3/bin/sqlite3 data_center.db "SELECT COUNT(*) FROM records WHERE sub_category='panewslab' AND date(timestamp/1000,'unixepoch')=date('now','localtime');"` | [ ] |
| A3 | stablecoin 日采集 ≥12 行 | records 表 sub_category=stablecoin，今日 ≥12 | `/opt/anaconda3/bin/sqlite3 data_center.db "SELECT COUNT(*) FROM records WHERE sub_category LIKE 'stablecoin%' AND date(timestamp/1000,'unixepoch')=date('now','localtime');"` | [ ] |
| A4 | pn_* 覆盖率 Day7 ≥86% | FiveDomainSqliteReader 派生 pn_* 字段，非空率 ≥36/42 | 运行 `python -c "from five_domain_sqlite_reader import FiveDomainSqliteReader as R; r=R().read(); import pandas as pd; p=r[[c for c in r.columns if c.startswith('pn_')]]; print((p.notna().sum()/len(p)).mean())"` | [ ] |
| A5 | quality.py 24h 零严重违规 | CONTRACT_INVALID + DUPLICATE issue = 0 | `cat logs/quality_issue.log \| grep -E 'CONTRACT_INVALID\|DUPLICATE' \| tail -n 200` | [ ] |
| A6 | polling_trader ≥12h 不崩溃 | 主交易进程 PID 持续 ≥12h，无 `compute()` throw | `ps aux \| grep polling_trader \| grep -v grep` + `grep -c 'Traceback\|Exception' logs/polling_trader.err.log == 0` | [ ] |

### 1.2 P0-2 Odaily 采集器 + Reader 派生（7 项）

| # | 验收项 | 达标标准 | 验证命令 / 方法 | 状态 |
|---|--------|----------|-----------------|------|
| B1 | Collector 5 TC 全绿 | pytest 返回 5 passed, 0 failed | `cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心 && /opt/anaconda3/bin/python3 -m pytest tests/news/test_odaily_collector.py -v` | [ ] |
| B2 | Registry 发现 + 采集 15~20 条 | list_collectors 含 odaily；--once 结果 ∈[15,20] | `python -c "from data_center.core.dispatcher import Dispatcher; print(Dispatcher().list_collectors())"`；`python data_center_scheduler.py --once --task odaily_newsflash_latest` | [ ] |
| B3 | 9 odaily_* 派生字段齐全 + policy_sentiment 非极端 | 9 字段 SELECT 非空；policy_sentiment ∈[0.35,0.65] | `sqlite3 data_center.db "PRAGMA table_info(records);"` + `python -c "from five_domain_sqlite_reader import FiveDomainSqliteReader as R; r=R().read(); print(r[['odaily_policy_sentiment_3d','odaily_crypto_reg_ratio_3d']].describe())"` | [ ] |
| B4 | 增量去重 三态验证（有→无→插假有） | 首次≥15 → 二次=0 → 插假 max_id-1 后≥1 | 3 次 `--once`，中间 `sqlite3 data_center.db "INSERT INTO records (timestamp,sub_category,asset,key) VALUES (9999999999999,'newsflash_99999999','ALL','newsflash_99999999');"` | [ ] |
| B5 | FAIL-OPEN: sentiment_engine 缺失仍 SUCCESS + 全 0.5 | `mv sentiment_engine.py sentiment_engine_bak.py` 后 --once，status=SUCCESS，sentiment=0.5 全行 | 运行 `--once` + `sqlite3 data_center.db "SELECT metrics FROM records WHERE sub_category LIKE 'newsflash_%' LIMIT 5;"` 查 od_policy_sentiment_0_1=0.5 | [ ] |
| B6 | policy_sentiment_score 极值保护 + 优先级 | odaily∈[0.2,0.8] 时 odaily 覆盖；否则 blockbeats → pn → None 回退链正确 | `python -c "from five_domain_sqlite_reader import FiveDomainSqliteReader as R; r=R().read(); print(r['policy_sentiment_score'].value_counts()[:5])"` | [ ] |
| B7 | 质量门禁 4 类 issue = 0（Odaily 专属） | quality_issue.log 无 odaily 相关的 4 类违规 | `grep odaily logs/quality_issue.log \| wc -l == 0` | [ ] |

### 1.3 P0-3 阶段1 基础 Boost（_od_*_boost）（4 项）

| # | 验收项 | 达标标准 | 验证命令 / 方法 | 状态 |
|---|--------|----------|-----------------|------|
| C1 | 阶段1 7 TC 全绿 | pytest 7 passed, 0 failed | `cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统 && /opt/anaconda3/bin/python3 -m pytest tests/test_odaily_booster_stage1.py -v` | [ ] |
| C2 | R3 Sample boost 值命中区间 | _od_dao_boost = +0.028±0.005；_od_tian_boost = +0.034±0.005 | `python -c "from five_domain_feature_computer import FiveDomainFeatureComputer as F; f=F(); coin_data = ...R3 sample dict...; print(f._od_dao_boost(coin_data), f._od_tian_boost(coin_data))"` | [ ] |
| C3 | None 字节一致性 | odaily_* 列全部 None 时，五维总分、子项、war_state 与实施前 diff=0 | `python -c "对比 run1(旧代码/无 odaily) vs run2(新代码/odaily=None) 的 result dict，assert deep_equal"` | [ ] |
| C4 | 代码风格 CR 通过 | _od_*_boost 方法签名、clamp、try/except、日志行与 _pn_*_boost 写法一致；od∈[-0.1,0.1] 更保守 | 人工 CR diff；`grep -n '_od_.*boost\|clamp.*0.1' five_domain_feature_computer.py` | [ ] |

### 1.4 P0-3 阶段2 Shadow Engine（4 项 + 开关 1 项 = 5 项合并 #20 为 #20 开关）

| # | 验收项 | 达标标准 | 验证命令 / 方法 | 状态 |
|---|--------|----------|-----------------|------|
| D1 | 阶段2 6 TC 全绿 | pytest 6 passed, 0 failed | `cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统 && /opt/anaconda3/bin/python3 -m pytest tests/test_odaily_engine_shadow_stage2.py -v` | [ ] |
| D2 | enable=False 生产红线三重 | (i) shadow import 0 次；(ii) JSONL 文件大小 = 0B；(iii) compute() result 与旧代码 diff=0 | TC-32 执行；`wc -c scripts/runtime/odaily_engine_boost_records.jsonl` | [ ] |
| D3 | 7 日历天 Shadow JSONL ≥1500 条 | `wc -l` ≥1500，每 300s 一笔 3 资产类 × 7 天 ≈ 2016 | `wc -l scripts/runtime/odaily_engine_boost_records.jsonl`；`grep -c 'IMPORT_FAIL' *.jsonl == 0` | [ ] |
| D4 | 4 门槛全 PASS | 脚本返回 4 PASS：(i) 命中率≥60%；(ii) 解冻准确率≥70%；(iii) 夏普≥1.05；(iv) IMPORT_FAIL=0 | `python scripts/memory_l4/odaily_shadow_hitrate_eval.py` 输出 4 `PASS` | [ ] |
| D5 | 默认开关切换 + Day14 解冻观测 | enable_odaily_engine_boost 默认改 True → PR 合并；重启后 Day14 thaw_count=3，war_state=ALLOW | 改类属性默认值 → CR → 合 main；清 five_domain_state.json → 重启进程；Day14 查 `cat scripts/runtime/five_domain_state.json \| grep thaw_count` | [ ] |

---

## 二、分阶段详细 Checklist（按 Tasks DAG）

### 2.1 P0-1 运维（T01 ~ T06）6 Tasks

- [ ] T01 环境预检: `/usr/bin/sw_vers -productVersion` → 版本号 ≥13 → 用 bootstrap；`/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0,'/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心'); import data_center; print('OK')"` → OK；logs 目录存在；DB chmod 644
- [ ] T02 --once 前台验证: `python data_center_scheduler.py --once` → 任务数 ≥8；panewslab 记录 ≥60；stablecoin ≥2；quality issue = 0
- [ ] T03 plist 拷贝: `cp /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/launchd/com.dreambuddy.data-center-scheduler.plist ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist` → 成功无报错
- [ ] T04 plist 加载: macOS≥13 → `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist`；<13 → `launchctl load ...`；回滚命令存在
- [ ] T05 健康检查 3 次（每 5 分钟）: PID≠-；日志含 WAKEUP 行；err.log <1KB
- [ ] T06 热路径安全: polling_trader PID 前后一致；`grep -c 'Traceback\|five_domain' logs/polling_trader.err.log = 0`

### 2.2 P0-2 Odaily 采集器（T07 ~ T20）14 Tasks

- [ ] T07 TDD 脚手架 5 fixture: HTTP 20 条 mock / lastId 增量 mock / policy_batch 20 条分类 / Session monkeypatch / ImportError monkeypatch
- [ ] T08 TC-1 正常 20 条: contract 7 字段齐全 + 7 metrics 范围校验（先红后绿）
- [ ] T09 TC-2 lastId=0 增量空: checkHasNew 返回 N=0 → 空 list
- [ ] T10 TC-3 event_type 分布: 7 类 Counter 与关键词命中数一致（14 关键词 + 7 类 regex）
- [ ] T11 TC-4 网络 Timeout: Session.get → raise Timeout → 返回 [] 不抛
- [ ] T12 TC-5 ImportError: lazy import 缺失 → sentiment=0.5 中性全行
- [ ] T13 重构 lint: 与 GdeltCollector 风格对齐；5 TC 仍全绿
- [ ] T14 Registry: `_register_defaults.register("news","odaily_newsflash", OdailyNewsflashCollector)` + import
- [ ] T15 sources.yaml: news 块末尾 `odaily_newsflash: enabled: true`
- [ ] T16 Scheduler.default_tasks: 加 `CollectionTask(name="odaily_newsflash_latest", ..., interval_sec=14400)`
- [ ] T17 --once 采集验证: records_count ∈[15,20]
- [ ] T18 Reader 三处改: SELECT IN 加源；§ODAILY 9 字段派生；policy_sentiment_score 覆盖写 + 极值保护 [0.2,0.8]
- [ ] T19 增量去重 3 次: 15→0→插假 max_id 记录→≥1
- [ ] T20 FAIL-OPEN L3: mv sentiment_engine → SUCCESS + 全 0.5；5 TC 全绿

### 2.3 P0-3 阶段1 _od_*_boost（T21 ~ T30）10 Tasks

- [ ] T21 TDD 脚手架 7 fixture: None / R3sample / warm / cold+严监管 / 货币宽松 / geo≥3 / pn_max×od_max / 类型错
- [ ] T22 TC-1 None→0.0: 传 None → return 0.0（先红→骨架→绿）
- [ ] T23 TC-2 dao 正 delta: sentiment=0.7 → boost ∈(0.02, 0.08]
- [ ] T24 TC-3 dao 负 delta: s=0.3, crh_ratio=0.4 → ∈[-0.1, -0.02)
- [ ] T25 TC-4 tian 货币宽松 + TC-5 geo≥3: rp_ratio=0.2, s>0.6 → +0.03~+0.06；geo≥3 → 负 delta
- [ ] T26 TC-6 乘法上限 + TC-7 类型错: pn=+0.2 × od=+0.1 → 1.32 倍 + _normalize_0_100 clamp；类型错→0.0
- [ ] T27 R3 sample boost 验证: dao=+0.028±0.005 / tian=+0.034±0.005
- [ ] T28 None 字节一致性: odaily_*=None 五维结果 diff=0
- [ ] T29 代码风格 CR: 签名/clamp/try-except 与 _pn_*_boost 一致；od∈[-0.1,0.1]
- [ ] T30 7 TC 全绿 + C1~C4 4 项验收归档

### 2.4 P0-3 阶段2 Shadow Engine（T31 ~ T42）12 Tasks

- [ ] T31 TDD 脚手架 6 fixture: enable 开关 / ImportError mock / 4 引擎 mock / PermissionError mock / JSONL 临时文件 / 7 日历天模拟
- [ ] T32 TC-1 enable=False 红线: 0 import / 0B JSONL / result diff=0
- [ ] T33 TC-2 enable=True+ImportError: JSONL IMPORT_FAIL；_shadow_import_blocked_until_ts = now+86400；result 不变
- [ ] T34 TC-3 enable=True+4 引擎 mock OK: JSONL 1 行 8 键；result 不变
- [ ] T35 TC-4 lifecycle growing vs emerging + TC-5 three_dee stress: growing 高 2~5 分；stress=0.8 → 0.6 倍减半
- [ ] T36 TC-6 JSONL PermissionError: compute() 正常返回不抛
- [ ] T37 6 TC 全绿 + 生产红线三重验证（enable=False）
- [ ] T38 新建 runtime 目录 + 空占位 JSONL: `odaily_engine_boost_records.jsonl` size=0B
- [ ] T39 新建 odaily_shadow_hitrate_eval.py: 4 门槛脚本（命中率≥60% / 解冻准确率≥70% / 夏普≥1.05 / IMPORT_FAIL=0）
- [ ] T40 5 文档更新: 11-易经推理 CHANGELOG + ENGINEERING_INDEX；18-数据获取中心 CHANGELOG + ENGINEERING_INDEX；DOC_DEBT_INDEX 销项
- [ ] T41 7 日历天观察: JSONL ≥1500 条；脚本 4 门槛 PASS/FAIL
- [ ] T42 改 enable 默认 True: PR + CR → 清 five_domain_state.json + 重启 polling_trader → Day14 观察 thaw_count=3, war_state=ALLOW

---

## 三、里程碑状态总览

| 里程碑 | 验收项数 | 通过数 | 通过率 | 状态标签 |
|--------|----------|--------|--------|----------|
| P0-1 launchd | 6 | /6 | - | ⬜ Not Started |
| P0-2 Odaily 采集 | 7 | /7 | - | ⬜ Not Started |
| P0-3 Stage1 Boost | 4 | /4 | - | ⬜ Not Started |
| P0-3 Stage2 Shadow | 5 | /5 | - | ⬜ Not Started |
| **Total** | **22**（含 D5） | /22 | - | ⬜ Not Started |

> 注: 20 项为 Spec §9 汇总（将 D5 计入阶段2 算 1 项）；本表拆分为 22 行以显式 D5 开关动作。

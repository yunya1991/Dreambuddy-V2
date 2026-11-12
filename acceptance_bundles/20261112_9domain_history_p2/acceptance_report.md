# 9 域各维历史统计 P2 本地实现验收报告

## 基本信息
- 验收对象：fear_greed 长历史旁路、云端回填入口、48 域 trend_20d P 层接入。
- 验收时间：2026-11-12。
- 验收人：AI。
- 关联 SPEC：SPEC-9DOMAIN-HISTORY-CONTEXT v1.3 §1.6/§1.7/§7.3/§9/§12.2。
- 关联 commit：无（用户未要求 commit）。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | 通过 | repro_after.log：`observed=p2_smoke`，800 观测，1y=0.9317、3y=0.9206，trend_rows=781 | 隔离 mock DAL + 临时目录，非真实云端回填 |
| 日志证据 | 通过 | SPEC→代码→运行的 JSON metrics 非空；persistent_local_backfill=false | 证明本地只验证链路，未伪造真实回填 |
| 回归测试 | 有既有红旗 | test.log：P2-A 22、48 域 46、18 域 22 均 exit=0；9 域全量 88 passed/5 skipped/2 failed | 两个失败均为 SPEC §12.1 已记录的缺失文件，非 P2 引入 |
| 影响面 | 通过 | fix.diff：仅 9 域、48 域对应实现/测试/SPEC，无依赖扩散 | 8 个实现相关文件均 untracked，未 stage/commit |
| 边界验证 | 通过 | 缺日期/非法值、重复回填、dry-run、<20 观测、缺历史、未预注册因子等测试全绿 | 覆盖 FAIL-CLOSED 写与 FAIL-OPEN 读 |

## 红旗清单
- 9 域全量套件仍有两个既有 FileNotFoundError：`ml_trade_service.py`、`ops/launchd/fundamental_stack.sh`。
- 云端真实 fear_greed 回填尚未执行；不能宣称 SPEC §9 的「云端回填完成」判据已达成。
- 当前实现文件尚未纳入 git 跟踪；本报告不代表已提交或已部署。

## 验收结论
- P2 本地实现：通过（保留上述既有全量回归红旗）。
- 云端真实回填与真实分位验收：待执行。
- 后续云端判据：`lookback_days >= 750`、`pct_rank_1y/3y` 非空、重跑行数不增加。

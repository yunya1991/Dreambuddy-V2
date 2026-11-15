# 验收报告：宏观事件历史回填通道（解除 D-E04/D-E09 数据阻塞）

- 日期：2026-11-15
- 范围：`18-数据获取中心` 采集 + `19-数据访问层` 入库 + 54-L1 文档状态纠偏
- 结论：**PASS**（通道可用、幂等、窗口隔离；D-E04/D-E09 仍待云端入库后接线，不宣称能力已交付）

## 一、症状复测

| 症状 | 复测结果 |
|---|---|
| `mm_events` 仅 16 行、`events.jsonl` 只留滚动窗口，事件研究无样本 | 回填实测 **542 条 / 2015–2026**，`failed_years=[]`；fomc 101、cpi 143、nfp 155 均 ≥30 门禁 |
| 日常 sync 可能清空历史行 | `DELETE` 收窄为 `event_time BETWEEN lo AND hi`；回归用例证明 2016 历史行与 2026 窗口行共存 |
| 重复执行是否膨胀 | `append_events` 按 `event_id` 幂等 + DAL `INSERT OR REPLACE`；第二次运行 `appended=0 / db_row_count` 不变 |

证据：`repro_after.log`

## 二、运行/日志证据

- 实网采集：FOMC 官方日历（`fomccalendars.htm` + `fomchistorical{2015..2020}.htm`）与 BLS 年度日历，`wayback_years=[]`（直连可用，Wayback 仅作 403 兜底）。
- 入库：`upserted=542`，两次运行 `db_row_count=542`。
- 目标用例 5 例、DAL 全量 166 例通过；ruff / black / py_compile 全 0。

证据：`test.log`

## 三、回归

- `19-数据访问层`：**166 passed**。
- `18-数据获取中心`：**666 passed / 4 failed**，4 例均为既有环境问题——`fred_collector` 因环境存在可用 API key（用例断言"无 key 返回空"）、`news_factor_mapping` 因本地语料 51866 行 < 10 万行；两处均不 import 本轮新增模块，与本次改动无调用关系。
- 54-L1 代码本轮未改动，其 698 例基线不受影响。

## 四、影响面

| 文件 | 性质 |
|---|---|
| `18/data_center/collectors/tradefin/macro_history_backfill.py` | 新增采集器（复用 `extract_rows`/`classify_release`/`append_events`，未改共享逻辑） |
| `18/data_center/cli/backfill_macro_calendar.py` | 新增 CLI |
| `18/tests/test_macro_history_backfill.py` | 新增 5 例 |
| `19/scripts/backfill_events_history.py` | 新增入库脚本（复用 `sync_events_to_dal._DDL/_INDEX`） |
| `19/scripts/sync_events_to_dal.py` | **行为变更 1 行**：全表 `DELETE` → 窗口内 `DELETE`（防止清空历史） |
| `18/docs/*`、`54-L1/docs/TECHNICAL_DESIGN.md`、`54-L1/SPEC-*.md` | 文档状态纠偏，不提前宣称 D-E04/D-E09 已交付 |

事件字段沿用 §3.1 枚举（`fomc`/`cpi`/`nfp`/`macro_other`），`available_at = event_time`（会议/发布日程本身公开，不构成前视）。

## 五、边界

- 仅覆盖官方日历事件（FOMC/CPI/NFP/PPI），不含新闻类事件；新闻事件仍走 `events.jsonl` 滚动通道。
- 本地只做合成/临时目录验证：`/tmp/macro_evidence.jsonl`、`/tmp/events_evidence.db`；**未访问或写入云端生产库**。
- 生产入库按分工在云端 `43.160.201.117` 执行（`sudo -u luke`，写前 `sqlite3 .backup` 到 `19-数据访问层/data/backups/`）。
- 回填入库后仍需接线 D-E04/D-E09 能力并以真实数据复测，才可改状态为 ✅。
- D-A14 仍受 `level` 阈值未冻结阻塞；MERS 真实验收仍在云端；S5 保持关闭。
- `fix.diff` 为归档 patch，不含验收包自身；`git diff --cached --check` 需排除该文件（其 `+ ` 空行非源码格式问题）。

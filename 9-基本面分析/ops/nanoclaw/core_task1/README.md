# NanoClaw 核心任务 1 - 使用手册

## 版本策略（2026-03）

- 主策略基线：V9.3（生产与验收默认对照口径）
- 研究与灰度叠加：优先 V9.8 Onchain（增量因子层，不替代基线）
- 次优灰度方案：V9.7 Direct（用于与 V9.8 做观点型增益对比）
- 输出模板基线：V9.3（brief/raw/event_ledger/methodology 同构模板）

## 快速开始

### 1. 生成 V2.0 优化版简报（推荐）

```bash
cd /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1

# 生成 V2.0 简报（含传统金融分析）
python3 scripts/news_digest_v2.py --hours 24 --json --use-ollama --ollama-model qwen2.5:7b-instruct
```

### 2. 历史回测验证

```bash
# 下载 90 天 BTC 历史价格
python3 scripts/fetch_historical_prices.py --days 90

# 生成匹配的历史新闻
python3 scripts/generate_historical_news.py --days 90

# 运行回测验证
python3 scripts/run_backtest_real_news.py
```

---

## 两种执行模式

### 模式 1：定时任务（自动）

每日早晨 8:00 自动生成简报（适合开盘前阅读）

```bash
crontab -e
```

添加以下行：

```
# 核心任务 1：每日 8:00 生成加密 + 宏观简报
0 8 * * * cd /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1 && ./run.sh >> /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1/logs/cron.log 2>&1
```

### 模式 2：按需即时生成（手动）

支持命令行动态指定时间窗口

## 即时生成命令

### 基本用法

```bash
cd /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1

# 生成每日简报（24 小时）
./smart_run.sh

# 生成最近 4 小时简报
./smart_run.sh hours 4

# 生成最近 12 小时简报
./smart_run.sh hours 12

# 显示帮助
./smart_run.sh help
```

### 高级选项

```bash
# 最近 4 小时 + JSON 摘要
./smart_run.sh hours 4 -j

# 最近 2 小时 + 自定义输出文件名
./smart_run.sh hours 2 -o my_brief.md

# 指定本地模型（默认已是 qwen2.5:7b-instruct）
./smart_run.sh hours 6 --model qwen2.5:7b-instruct

# 组合使用
./smart_run.sh hours 8 -j --model qwen2.5:7b-instruct -o morning_brief.md
```

### Python 脚本直接调用

```bash
# 使用 V2 Python 脚本（默认本地模型）
python3 scripts/news_digest_v2.py --hours 4 --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/news_digest_v2.py --hours 24 --json --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/news_digest_v2.py --hours 24 --use-ollama --ollama-model qwen2.5:7b-instruct -o custom.md
```

### Legacy 脚本（仅兼容保留，不建议使用）

- `scripts/run_news_digest.py`
- `scripts/run_news_digest_on_demand.py`

上述两个脚本保留用于旧流程兼容，不再作为默认入口。团队日常请统一使用：
- `./run.sh`
- `./smart_run.sh`
- `scripts/news_digest_v2.py`

## V3.1 模板与规范检查（新增）

按需生成 V3.1（full/lite）：

```bash
python3 scripts/run_news_digest_on_demand.py --hours 24 --report-mode full --json
```

输出前会执行规范检查（章节完整性、资金流增强可用性、事件账本非空、核心信号字段有效）；未通过将直接失败退出，不落盘无效简报。

新增产物：

- `raw/news_eval_receipt_YYYYMMDD_HHMM.json`（含 coverage/quality/drift/changed_top_events/spec_check）
- `historical_data/event_type_weights_v93.json`（事件类型权重参数表）

## 命令速查表

| 命令 | 说明 | 输出文件 |
|------|------|----------|
| `./smart_run.sh` | 每日简报（24h，本地模型） | `brief_v2_YYYYMMDD_HHMM.md` |
| `./smart_run.sh --ledger-version auto` | 每日简报（自动：主账本 V9.3 + 灰度账本 V9.8） | `brief_v2_*.md` + `event_ledger_*.jsonl` + `event_ledger_overlay_9.8_onchain_*.jsonl` |
| `./smart_run.sh hours 4` | 最近 4 小时（本地模型） | `brief_v2_YYYYMMDD_HHMM.md` |
| `./smart_run.sh hours 12 -j` | 最近 12 小时+JSON | `brief_v2_*.md` + `brief_v2_*.json` |
| `./smart_run.sh hours 2 --model qwen2.5:7b-instruct` | 指定模型运行 | `brief_v2_YYYYMMDD_HHMM.md` |
| `./run.sh` | 定时任务脚本（本地模型） | `brief_v2_YYYYMMDD_HHMM.md` |
| `./run.sh --ledger-version auto` | 定时任务脚本（自动：主账本 V9.3 + 灰度账本 V9.8） | `brief_v2_*.md` + `event_ledger_*.jsonl` + `event_ledger_overlay_9.8_onchain_*.jsonl` |

## 日志查看

```bash
# 查看定时任务日志
tail -50 logs/cron.log

# 实时跟踪日志
tail -f logs/cron.log
```

## 首轮灰度验证清单（可执行）

### 0) 预设环境（test 模式）

- [ ] 已在 NanoClaw 运行环境配置：`REPORT_PUSH_MODE=test`
- [ ] 已配置：`REPORT_API_BASE_TEST`、`INTERNAL_API_KEY`
- [ ] `ops/nanoclaw/jobs.local.json` 中包含 `market_news_digest_push_hourly`

### 1) 一键验收命令（灰度）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1

export REPORT_PUSH_MODE=test
export REPORT_API_BASE_TEST="http://8.209.238.108/api/v1"
export INTERNAL_API_KEY="替换为测试库 key"

python3 scripts/news_digest_v2.py --hours 2 --update-mode auto --use-ollama --ollama-model qwen2.5:7b-instruct

LATEST_MD="$(ls -t outputs/brief_v3_*_optimized.md outputs/brief_v2_*.md 2>/dev/null | head -n 1)"
[ -n "$LATEST_MD" ] && echo "[PASS] artifact_path=$LATEST_MD" || { echo "[FAIL] 未找到简报产物"; exit 1; }
```

### 1.1) 生产推送命令（按 report-api-guide）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1

export REPORT_PUSH_MODE=prod
export REPORT_API_BASE_PROD="http://8.209.238.108/api/v1"
export INTERNAL_API_KEY="替换为生产 key"

python3 scripts/news_digest_v2.py --hours 2 --update-mode auto --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/push_report_api.py --api-base "$REPORT_API_BASE_PROD"
```

### 1.2) 自动开机生效（一次配置，后续免 export）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1
bash scripts/setup_report_push_env.sh --mode prod --api-base-prod "http://8.209.238.108/api/v1"
```

执行后会写入 `ops/nanoclaw/core_task1/.env`（权限 600）。`push_report_api.py` 会自动读取该文件中的：

- `REPORT_PUSH_MODE`
- `REPORT_API_BASE_PROD`
- `REPORT_API_BASE_TEST`
- `INTERNAL_API_KEY`
- `REPORT_PUSH_STATE_FILE`
- `REPORT_PUSH_RECEIPT_FILE`

### 1.3) 启动前自检命令（开机巡检）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1
bash scripts/preflight_report_push.sh
```

该命令会输出 JSON，检查项：

- `.env` 是否存在
- `INTERNAL_API_KEY` 是否非空
- `REPORT_API_BASE_PROD/TEST` 对应 API 是否可达

### 2) 成功判据

- [ ] 产物存在：`artifact_path` 非空，且文件可读
- [ ] 推送成功：目标 API 返回 `code=0` 且拿到 `report_id`
- [ ] outbox 已写入回执，且包含字段：`report_id`、`trace_id`、`artifact_path`
- [ ] 回执包含辅助审计字段：`push_mode`、`http_status`、`attempts`、`pushed_at`

### 3) 回执字段检查（样例命令）

```bash
python3 - <<'PY'
import json
from pathlib import Path

base = Path("/Users/zhangjiangtao/ft_userdata")
candidates = sorted(base.glob("**/*outbox*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
if not candidates:
    print("[WARN] 未找到 outbox jsonl，请按你实际 outbox 路径执行同样字段检查")
    raise SystemExit(0)

target = candidates[0]
print(f"[INFO] 检查文件: {target}")
line = ""
with target.open("r", encoding="utf-8", errors="replace") as f:
    for row in f:
        row = row.strip()
        if row:
            line = row
if not line:
    print("[FAIL] outbox 为空")
    raise SystemExit(1)

obj = json.loads(line)
required = ["report_id", "trace_id", "artifact_path"]
extra = ["push_mode", "http_status", "attempts", "pushed_at"]
miss_required = [k for k in required if not obj.get(k)]
miss_extra = [k for k in extra if k not in obj]
print("[INFO] latest receipt keys:", sorted(obj.keys()))
if miss_required:
    print("[FAIL] 缺少必填字段:", miss_required)
    raise SystemExit(1)
if miss_extra:
    print("[FAIL] 缺少审计字段:", miss_extra)
    raise SystemExit(1)
print("[PASS] 回执字段检查通过")
PY
```

### 4) 失败判据与回滚

- [ ] `401`：立即失败，不重试；检查并更换 `INTERNAL_API_KEY`，保持 `REPORT_PUSH_MODE=test`
- [ ] `5xx/超时`：仅允许指数退避重试（10s/30s/90s）；超限后判定失败
- [ ] 灰度失败回滚：临时禁用 job `market_news_digest_push_hourly` 或将其 `cron` 改为非触发值
- [ ] 失败期间保留落盘，不清理 `raw/outputs`，用于审计回放

### 5) 切生产闸门

- [ ] 最近连续 3 次灰度推送成功（含回执字段检查通过）
- [ ] 无 `401`，且 `5xx/超时` 重试后成功率达到预期
- [ ] 切换：`REPORT_PUSH_MODE=prod` + `REPORT_API_BASE_PROD` + 生产 `INTERNAL_API_KEY`
- [ ] 切换后首轮继续执行本清单第 2/3 步做生产验收

### 6) 回执样例（字段口径）

```json
{
  "report_id": 123,
  "trace_id": "news_digest_push_20260411_1300",
  "artifact_path": "ops/nanoclaw/core_task1/outputs/brief_v3_20260411_optimized.md",
  "push_mode": "test",
  "http_status": 200,
  "attempts": 1,
  "pushed_at": "2026-04-11T13:00:12Z"
}
```

## 输出位置

- **原始数据**: `ops/nanoclaw/core_task1/raw/`
  - `raw_crypto_YYYYMMDD_HHMM.json` - 加密新闻原始数据
  - `raw_macro_YYYYMMDD_HHMM.json` - 宏观新闻原始数据
  - `crawl_meta_YYYYMMDD_HHMM.json` - 抓取元数据（时间窗/数量）

- **最终简报**: `ops/nanoclaw/core_task1/outputs/`
  - `brief_v2_YYYYMMDD_HHMM.md` - V2.0 优化版简报
  - `brief_v2_YYYYMMDD_HHMM.json` - 机器可读摘要

- **历史数据**: `ops/nanoclaw/core_task1/historical_data/`
  - `btc_daily_prices.json` - BTC 历史价格
  - `historical_news/news_YYYY-MM-DD.json` - 历史新闻存档
  - `backtest_result.json` - 回测结果

- **文档报告**:
  - `BACKTEST_VALIDATION_REPORT.md` - 回测验证报告
  - `REAL_CRAWLER_BACKTEST_SUMMARY.md` - 真实爬虫回测总结

## 使用场景

| 场景 | 推荐命令 |
|------|----------|
| 每日开盘前阅读 | 定时任务（每日 8:00） |
| 突发新闻后查看 | `./smart_run.sh hours 2` |
| 午休时查看上午动态 | `./smart_run.sh hours 4` |
| 周末复盘一周行情 | `./smart_run.sh hours 168`（7 天） |
| 重要事件跟踪 | `./smart_run.sh hours 1` |

## 环境变量（可选）

本地模型默认使用 `qwen2.5:7b-instruct`，可通过环境变量覆盖：

```bash
export OLLAMA_MODEL="qwen2.5:7b-instruct"
```

如需使用更精确的行情数据，可设置 API Key：

```bash
# 添加到 ~/.zshrc 或 ~/.bashrc
export ALPHA_VANTAGE_API_KEY="你的免费 API key"
```

获取免费 API key: https://www.alphavantage.co/support/#api-key

## 示例输出

```
=== 加密 + 宏观新闻简报（即时生成）===
时间窗口：最近 4 小时

【实时行情】
  BTC: $67,208.00 (+0.00%)
  ETH: $1,941.90 (+0.00%)
  ETH/BTC: 0.0289

【新闻筛选】
  加密新闻：4 条
  宏观新闻：3 条

[✓] 简报已生成：outputs/brief_v2_YYYYMMDD_HHMM.md

【投资信号】
  BTC 趋势：观望
```

## 锚点增量模式（新增）

支持“早餐锚点 + 日内增量修订”：

```bash
# 首次运行或开盘前：生成锚点
python3 scripts/news_digest_v2.py --hours 24 --update-mode anchor --use-ollama --ollama-model qwen2.5:7b-instruct

# 盘中增量更新
python3 scripts/news_digest_v2.py --hours 2 --update-mode delta --use-ollama --ollama-model qwen2.5:7b-instruct

# 自动模式（当天无锚点则 anchor，否则 delta）
python3 scripts/news_digest_v2.py --hours 2 --update-mode auto --use-ollama --ollama-model qwen2.5:7b-instruct
```

新增参数：

- `--update-mode {auto,anchor,delta,reset}`
- `--anchor-date YYYY-MM-DD`
- `--anchor-session {auto,apac,eu,us}`
- `--force-anchor`

新增产物：

- `raw/anchor_registry.jsonl`
- `raw/delta_registry.jsonl`
- `raw/anchor_snapshot_*.json`
- `raw/delta_update_*.json`
- `raw/anchor_delta_view_*.json`

策略配置：

- `historical_data/anchor_delta_policy_v1.json`（EMA、多锚点时段、自适应阈值）

## 新文档

- `ANCHOR_DELTA_TECHNICAL_DESIGN.md`
- `news_anchor_delta_skill_plan.md`
- `NEWS_ANCHOR_DELTA_SOP.md`
- `schema/anchor_registry.schema.json`
- `schema/delta_registry.schema.json`

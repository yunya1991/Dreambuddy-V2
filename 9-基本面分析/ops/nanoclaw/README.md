# NanoClaw 本地落地（控制面）

目标：在不触碰交易执行面的前提下，落地四大能力：多渠道入口、容器隔离、联网与定时任务、Agent Swarms。

## 1. 目录与资产

- `ops/nanoclaw/bootstrap.sh`：初始化本地 NanoClaw 工作区与最小边界配置。
- `ops/nanoclaw/check_boundary.sh`：检查挂载边界与关键目录权限。
- `ops/nanoclaw/setup_local.sh`：生成本地任务与 swarms 配置。
- `ops/nanoclaw/claude_with_proxy.sh`：用本机代理启动 Claude（用于 Anthropic 连通性问题）。
- `ops/nanoclaw/jobs.sample.json`：定时任务样例。
- `ops/nanoclaw/swarms.sample.json`：多 agent 分工样例。
- `ops/nanoclaw/env.providers.template`：DashScope/Kimi/智谱 三套可切换 `.env` 模板。

## 2. 一键初始化

```bash
bash "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/bootstrap.sh"
```

初始化会生成：

- `user_data/nanoclaw/`
  - `workspace/`（容器可读写工作区）
  - `state/`（状态目录）
  - `logs/`（日志目录）
  - `mounts_ro.txt`（只读挂载清单）
  - `mounts_rw.txt`（读写挂载清单）
  - `env.nanoclaw.local`（本地环境变量模板）
- `user_data/agent_repo/nanoclaw`（NanoClaw 仓库）

若外网暂时不可达，仓库目录会生成 `CLONE_FAILED.txt`，网络恢复后执行：

```bash
git clone https://github.com/qwibitai/nanoclaw.git "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw"
```

## 3. 启动与技能安装

```bash
cd "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw"
claude
```

如果暂时还没接入 Telegram/Slack 等渠道，可先用本地对话通道启动（已内置）：

```bash
cd "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw"
npm run dev
```

启动后在终端看到 `local>` 提示符，直接输入任务即可进行对话编排。  
若要关闭该本地通道：`NANO_LOCAL_CONSOLE_ENABLED=0 npm run dev`。

进入 Claude Code 后执行：

- `/setup`
- `/add-telegram`
- `/add-slack`
- `/add-discord`
- `/add-gmail`
- `/add-whatsapp`

建议把“主频道”只用于管理动作，群组频道用于业务对话，保持上下文隔离。

若出现 `Unable to connect to Anthropic services` 或 `ERR_BAD_REQUEST`，先改用代理启动：

```bash
cd "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw"
../../../ops/nanoclaw/claude_with_proxy.sh auth login
```

随后用同一脚本启动会话：

```bash
cd "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/agent_repo/nanoclaw"
../../../ops/nanoclaw/claude_with_proxy.sh
```

若希望改为国产 OpenAI 兼容平台（例如 DashScope/OpenRouter 兼容网关），可在项目 `.env` 增加：

```bash
NANO_MODEL_BACKEND=openai_compat
OPENAI_COMPAT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=qwen-plus
```

也可直接参考：

- `ops/nanoclaw/env.providers.template`

只需要改 4 个变量即可切换供应商：`NANO_MODEL_BACKEND`、`OPENAI_COMPAT_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。

说明：
- `openai_compat` 模式可用于联网研究与问答。
- 该模式不提供 Claude Agent SDK 的完整能力（例如 Claude skills、agent teams 原生能力）。
- 若需要完整 Swarms/skills，仍建议使用 Claude 路径。

## 4. 与交易系统的连接边界

- 只读数据来源：
  - `user_data/agent_outbox/`
  - `user_data/agent_outbox/*.jsonl`
- 写入动作限制：
  - 仅允许调用本系统“提交申请/入队”类接口。
  - 任何生产变更必须走 `approval_id + trace_id + confirm_live_required`。
- 禁止项：
  - 禁止把交易所密钥、下单 API key、配置写入 token 挂载到 NanoClaw 容器。

## 5. 容器隔离建议

- macOS 优先 Apple Container；Linux/macOS 可选 Docker。
- 运行时选择：
  - Apple Container：`CONTAINER_RUNTIME=container npm run dev`
  - Docker（默认）：`npm run dev`
- 默认只挂载：
  - RO：`user_data/agent_outbox`、只读报告目录
  - RW：`user_data/nanoclaw/state`、`user_data/nanoclaw/workspace`
- 通过 `check_boundary.sh` 每次启动前检查。

## 6. 联网与定时任务

- 任务模板见 `ops/nanoclaw/jobs.sample.json`。
- 本地配置生成：

```bash
bash "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/setup_local.sh"
```

- 生成后使用：
  - `ops/nanoclaw/jobs.local.json`
  - `ops/nanoclaw/swarms.local.json`
- 建议任务类型：
  - 市场新闻抓取与摘要
  - 风险监控日报
  - 异常事件回顾
- 所有任务输出应写回 outbox 或审计接口，保留 trace_id。

### 6.1 新闻简报推送首轮灰度验收清单（统一口径）

#### 预设环境（test 模式）

- [ ] 已在 NanoClaw 运行环境配置：`REPORT_PUSH_MODE=test`
- [ ] 已配置：`REPORT_API_BASE_TEST`、`INTERNAL_API_KEY`
- [ ] `ops/nanoclaw/jobs.local.json` 中包含 `market_news_digest_push_hourly`

#### 一键验收命令（灰度）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1

export REPORT_PUSH_MODE=test
export REPORT_API_BASE_TEST="http://8.209.238.108/api/v1"
export INTERNAL_API_KEY="替换为测试库 key"

python3 scripts/news_digest_v2.py --hours 2 --update-mode auto --use-ollama --ollama-model qwen2.5:7b-instruct

LATEST_MD="$(ls -t outputs/brief_v3_*_optimized.md outputs/brief_v2_*.md 2>/dev/null | head -n 1)"
[ -n "$LATEST_MD" ] && echo "[PASS] artifact_path=$LATEST_MD" || { echo "[FAIL] 未找到简报产物"; exit 1; }
```

#### 生产推送命令（按 report-api-guide）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1
export REPORT_PUSH_MODE=prod
export REPORT_API_BASE_PROD="http://8.209.238.108/api/v1"
export INTERNAL_API_KEY="替换为生产 key"
python3 scripts/news_digest_v2.py --hours 2 --update-mode auto --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/push_report_api.py --api-base "$REPORT_API_BASE_PROD"
```

#### 自动开机生效（一次配置）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1
bash scripts/setup_report_push_env.sh --mode prod --api-base-prod "http://8.209.238.108/api/v1"
```

完成后，`push_report_api.py` 会自动加载 `ops/nanoclaw/core_task1/.env`，无需每次手动 `export`。

#### 启动前自检命令（开机巡检）

```bash
cd /Users/zhangjiangtao/ft_userdata/基本面分析_fundamental/ops/nanoclaw/core_task1
bash scripts/preflight_report_push.sh
```

返回 JSON，包含：`env_exists`、`api_key_present`、`api_reachable`、`api_status`。

#### 成功判据

- [ ] 产物存在：`artifact_path` 非空，且文件可读
- [ ] 推送成功：目标 API 返回 `code=0` 且拿到 `report_id`
- [ ] outbox 已写入回执，且包含字段：`report_id`、`trace_id`、`artifact_path`
- [ ] 回执包含辅助审计字段：`push_mode`、`http_status`、`attempts`、`pushed_at`

#### 回执字段检查（样例命令）

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
if miss_required:
    print("[FAIL] 缺少必填字段:", miss_required)
    raise SystemExit(1)
if miss_extra:
    print("[FAIL] 缺少审计字段:", miss_extra)
    raise SystemExit(1)
print("[PASS] 回执字段检查通过")
PY
```

#### 失败判据与回滚

- [ ] `401`：立即失败，不重试；检查并更换 `INTERNAL_API_KEY`，保持 `REPORT_PUSH_MODE=test`
- [ ] `5xx/超时`：仅允许指数退避重试（10s/30s/90s）；超限后判定失败
- [ ] 灰度失败回滚：临时禁用 job `market_news_digest_push_hourly` 或将其 `cron` 改为非触发值
- [ ] 失败期间保留落盘，不清理 `raw/outputs`，用于审计回放

#### 切生产闸门

- [ ] 最近连续 3 次灰度推送成功（含回执字段检查通过）
- [ ] 无 `401`，且 `5xx/超时` 重试后成功率达到预期
- [ ] 切换：`REPORT_PUSH_MODE=prod` + `REPORT_API_BASE_PROD` + 生产 `INTERNAL_API_KEY`
- [ ] 切换后首轮继续执行上方“成功判据+回执字段检查”

#### 回执样例（字段口径）

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

#### 详细版入口

- 同步版 checklist：`ops/nanoclaw/core_task1/README.md` 中“首轮灰度验证清单（可执行）”

## 7. Agent Swarms 规划

- 分工模板见 `ops/nanoclaw/swarms.sample.json`。
- 推荐角色：
  - sentiment_agent（舆情）
  - macro_agent（宏观）
  - onchain_agent（链上）
  - strategy_review_agent（策略复盘）
  - ops_guard_agent（运维守护）

## 8. 生产前检查

```bash
bash "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/check_boundary.sh"
```

通过后再启动 NanoClaw 控制面。

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

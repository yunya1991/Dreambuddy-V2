# CHANGELOG — mobile-reservation-assist

## v0.2.0 (2026-11-21)

P1 大模型接入（阿里 Qwen）+ 白名单执行 + 巡检自愈：

- 新增 `brain.py`：复用 `~/.local/share/dreambuddy/qwen.env`，OpenAI 兼容 `/chat/completions`；仅标准库，无第三方依赖，不打印密钥。
- CLI 新增子命令：
  - `chat`：会话模式，唤醒助手后多轮自然语言对话；大模型负责决策、程序按白名单流程执行。
  - `ask`：自然语言 → 白名单计划 JSON（`--execute` 为人工授权执行，属"例外二"）。
  - `dispatch`：自然语言 → 下发一条预约作业（`--dry-run` 只解析），支持"自然语言下发预约"。
  - `patrol`：采集证据（doctor/作业状态/agent.log）→ 大模型诊断；`--auto-fix` 为告警接管修复并验证（属"例外一"）。
- 白名单动作：`doctor/jobs/report/pause/resume/dispatch/reset_stuck`；红线词（支付/锁座/代抢/破解验证码等）一律拒绝。
- 新测试 `tests/test_brain.py`：JSON 抽取、白名单拒绝、计划/参数解析、dispatch 幂等，共 9 例（离线）。

## v0.1.0 (2026-11-20)

P0 首版（骨架 + 治理全绿 + FakeAgent 全链路）：

- 组件骨架：`component.yaml`（family=reservation-assist / output_contract=reservation.v1）。
- 内核脚本：`ingest / store / gateway / executor / notify / security / mra`。
- 本地 HTTP 指令网关（Token 鉴权 / 原子认领 / 回执落库）。
- 6 平台手机动作定义占位（railway/damai/bilibili/maoyan/medical/gov），结构性禁止支付/锁座。
- 手机端 Auto.js 常驻 Agent 骨架 `agent/reservation_agent.js`。
- 测试：contract/store/ingest/gateway/executor/architecture + golden + fixtures。

未做（P1）：真机选择器细化、launchd 托管、真机联调。

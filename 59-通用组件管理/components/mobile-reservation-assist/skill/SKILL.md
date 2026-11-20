---
name: mobile-reservation-assist
slug: dreambuddy-mobile-reservation-assist
displayName: 手机预约助手 Mobile Reservation Assist
version: 0.2.0
summary: 消费预约助手命中，经本地 HTTP 网关把预约动作下发到手机端 Agent（Auto.js）执行，停在官方下单页、不代付不锁座。
license: MIT
allowed-tools: Bash, Read
---

# 手机预约助手（mobile-reservation-assist）

## 0. 一句话

**把上游"余票/号源命中"转成"手机端预约动作"：本地网关做指令中转，手机端常驻 Agent 拉取并执行，最终停在官方下单页，最后一步人工确认与支付。**

## 1. 定位与边界

- 上游：消费 `reservation-assist` 的命中（只读其公开 CLI：`report --json` / `watch list --json`，`reservation.v1`），**不 import 上游、不写死其路径**。
- 本层：把命中归一为"预约作业"，经本地 HTTP 网关派发给手机端 Agent。
- 手机端：复用 Auto.js 常驻脚本 `agent/reservation_agent.js` 轮询拉指令、执行、回传结果。
- 红线：不代抢、不转售、不破解验证码、不锁座占座、不托管支付；终态停在官方下单页并预填，**最终确认/支付由人工完成**。

## 2. 数据流

```
reservation-assist 命中
   └─(ra report --json + ra watch list --json)──► mra ingest
        └─► 本地 SQLite：预约作业（按 task_id+fingerprint 去重）
             └─► mra gateway（本地 HTTP，Token 鉴权）
                  ├─ GET  /commands  手机拉取待执行作业
                  └─ POST /results   手机回传执行结果
                       └─► 落库 + 通知 + mra report（reservation.v1）
```

## 3. 命令表

```bash
# 归一上游命中并生成预约作业（来源可为上游 CLI 或本地 feed 文件）
python3 scripts/mra.py ingest [--ra-cli <path-to-ra.py>] [--source file:<path>]

# 查看作业
python3 scripts/mra.py jobs [--json] [--state pending|dispatched|done|failed|unknown|cooldown]

# 启动本地指令网关（前台；生产由 launchd KeepAlive 托管）
python3 scripts/mra.py gateway [--host 127.0.0.1] [--port 8765]

# 打印/生成网关 Token（tty）
python3 scripts/mra.py token [--show]

# 环境自检 / 报告 / 开关
python3 scripts/mra.py doctor [--json]
python3 scripts/mra.py report [--json]      # reservation.v1
python3 scripts/mra.py pause | resume

# 大模型（阿里 Qwen）驱动：自然语言 → 白名单计划 → 工具执行
python3 scripts/mra.py chat                                   # 会话模式：唤醒助手，多轮自然语言 → 程序按流程执行
python3 scripts/mra.py ask "<自然语言>" [--json] [--execute]   # --execute=人工授权执行
python3 scripts/mra.py dispatch "<自然语言预约>" [--dry-run]    # 自然语言下发预约作业
python3 scripts/mra.py patrol [--auto-fix] [--resume]          # 巡检诊断；--auto-fix=告警接管修复并验证
```

退出码：`0` 成功 / `2` 参数错误 / `3` 门禁拒绝 / `5` 上游不可达。

## 4. 安全门禁

| 门禁 | 条件 | 失败行为 |
|---|---|---|
| 执行开关 | `MRA_ALLOW_EXECUTE != "0"` | 不下发（`GateDenied("env")`） |
| 全局暂停 | 未 `pause` | 不下发 |
| 一次性 | `(task_id, fingerprint)` 无终态记录 | 拒绝重复 |
| 无支付 | 动作序列禁止含支付/锁座步骤 | 构建指令即拒绝 |
| 风控冷却 | 回执为验证码/风控 | 该作业 `cooldown`，不重试 |

手机端 Agent 只执行到"打开官方 App → 定位目标 → 进入下单页并预填"，遇到验证码/支付一律停下并回传 `needs_human`。

## 5. 隐私

- 状态目录 `~/.mobile-reservation-assist/`（0700），SQLite 存作业/结果/事件。
- 网关 Token 存状态目录 `gateway_token`（0600），请求头 `X-MRA-Token` 或查询参数 `token` 校验。
- 日志/事件/报告统一 `redact()`：证件号、手机号（保留后 4）、cookie/token、地址。

免责声明：本组件仅做流水线编排与手机端辅助操作，不构成购买建议，不承诺成功率。

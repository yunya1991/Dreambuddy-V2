# CHANGELOG — mobile-reservation-assist

## v0.20.0 (2026-11-22)

能力注册补全（P1）：explore / regression / caps 8 个动作入库。

- 只读：`caps show`、`explore list`、`explore show`、`regression list`。
- 写动作（会创建状态，按 write 登记）：`explore start`、`explore stop`、`explore baseline`、`regression add`。
- 手机 CLI 叶子命令覆盖率 64/72 → **72/72**；`mra.py` 现有全部叶子命令均有注册动作。

## v0.19.0 (2026-11-22)

能力注册补全（P0）：小红书 / 抖音 / 推特链路 12 个缺失动作入库。

- 小红书：新增 `xhs collect` / `xhs data` / `xhs memo add` / `xhs memo list` / `xhs run` 登记；`collect --memo` 动态升为 ui。
- 抖音：新增 `douyin chain` / `douyin collect` / `douyin data` / `douyin memo add` / `douyin memo list` 登记；`collect --memo` 动态升为 ui。
- 推特：新增 `twitter login`（write，凭证只留本机浏览器 profile）/ `twitter run-due`（write，发布到点推文）登记。
- 登记后手机 CLI 叶子命令覆盖率 52/72 → 64/72；剩余 `explore` / `regression` / `caps show` 8 项留待 P1。

## v0.18.0 (2026-11-22)

跨域能力注册表 P1：发布合并索引 + 双向调度入口。

- 新增 `skill/scripts/registry.py`：只读消费 59 域 `dreambuddy.capabilities.v2` 索引（`DREAMBUDDY_REGISTRY` → `~/.local/share/dreambuddy/registry/capabilities.json`），不 import 59 代码。
- 新增 CLI `mra caps list|show`：跨域发现能力（按 kind 过滤，输出索引生成时间）。
- 新增 CLI `mra cross <capability_id> [args...] [--allow-write]`：按索引把能力翻译成 `dreambuddy run/dal/workflow/schedule` 子进程；执行前按索引 `safety + escalate` 复核，write/ui 需显式 `--allow-write`；本域能力直接拒绝。
- CLI 路径解析：`DREAMBUDDY_CLI` → `~/.config/dreambuddy/dreambuddy.path` → 默认 59 域入口。
- `component.yaml` 新增 `caps` / `cross` 两个只读动作声明，供 59 域总控台与 MCP 投影识别。
- `data.*` 跨域：按 schema/路由把 `--json` / `key=value` / 原生 flag 翻译成 `dreambuddy dal read|fetch|scopes`，`filters` 自动扁平化为 `--sub-category` / `--metric-name` / `--start-ts` / `--end-ts`。
- 依赖：使用前需在 59 域执行 `dreambuddy caps sync` 发布索引；`dreambuddy doctor` 会校验索引是否漂移。

## v0.17.0 (2026-11-21)

新增推特定时发布通道（桌面 Playwright，独立于手机端）。

- 新增 `skill/scripts/twitter.py`：持久化 profile（`<state_dir>/twitter/profile`）+ **本机 Chrome cookie 导入**（Keychain `Chrome Safe Storage` 解密，兼容 v10/v11 与 SHA256(host) 前缀），`login` 默认走 Chrome、`--manual` 兜底；发布用常规 Chrome UA 规避 X 对 HeadlessChrome 的拦截。
- `schema_version=9`：新增 `twitter_posts` 队列表与 `claim_due_twitter_post / finish_twitter_post / cancel_twitter_post / recover_stale_twitter`；单条原子认领 `pending → posting`，杜绝并发重复发推。
- 新增 CLI `mra twitter login|status|post|schedule|list|cancel|run-due|install-schedule|uninstall-schedule`。
- 定时采用本地队列 + launchd 每分钟 tick（`com.mra.twitter-scheduler`），`--at "YYYY-MM-DD HH:MM"` / `--at "HH:MM"` / `--in 30m` 三种写法。
- 复用 `content_guard` 做发布前金融风控；`posting` 超 15 分钟收敛 `failed` 并提示人工核对，禁止自动重发。
- 大模型入口：`brain.ALLOWED_ACTIONS` 新增 `twitter_post / twitter_schedule / twitter_list / twitter_status`，`mra ask`/`chat` 可用自然语言发推、定时发推、查队列；`ask` 默认只出计划，`--execute` 才执行（发布为人工授权动作）；`--at` 支持 `明天 09:00` 相对日期写法。
- 59 域总控台接入：`components/mobile-reservation-assist/skill/scripts/mra.py` 改为代理壳（`MOBILE_AGENT_CLI` → `~/.config/dreambuddy/mobile_agent.path` → 默认主仓），`dreambuddy` 新增 `twitter` 命令与读写分级；两处 CLI 共用同一实现与状态，不再维护副本。实测 `dreambuddy mobile twitter status/list` 通过，写动作默认被门禁拦截并生成计划。
- 测试：新增 `tests/test_twitter.py`（22 例，队列 / 认领 / 收敛 / 时间解析 / run-due / Chrome cookie 解密 / 计划白名单与预检）；全量 355 项通过。
- 已知限制：需本机开机且已完成一次 `twitter login`；X 网页结构改版时选择器需同步更新。

## v0.16.0 (2026-11-21)

设备端补真机接单，并加独立开关（默认关闭，关闭时由用户自主接单）。

- 新增 `autojs/modules/accept_helper.js`：按 `route_start/route_end/price` 定位订单卡片，只点该卡片内的接单按钮；点击后读页面提取订单号。
- 三平台 `didi/dida/hello` 的 `acceptOrder(orderId, target, options)` 改为调用 helper，接单前自动回到订单大厅。
- `autojs/main.js`：`case "accept"` 接入 `handleAcceptCommand`；新增 `config.accept.enabled` 开关、`max_per_day` 上限、工作时段与价格下限校验；`status` 返回开关与当日接单数。
- `config` 指令新增 `accept_enabled` / `max_accept` 热更新，落盘 `config.json`。
- `config.json` 新增 `accept` 段（`enabled=false`、`max_per_day=1`、`confirm_texts`）。
- 桥接 target 补充 `route_start/route_end`，便于设备端按路线兜底定位订单。
- 测试：新增 `tests/test_device_accept.py`（4 例）；全量 280 项通过。

## v0.15.0 (2026-11-21)

顺风车抢单接入新架构（服务端桥接，不改手机端 JS）。

- 新增 `phone_adapters/carpool.py`：`platform=didi|dida|hello`，序列 `open_app → goto_order_hall → list_orders → parse_orders →（授权时）accept_order → capture_screenshot → stop`。
- L3 注册表新增 `goto_order_hall / list_orders / parse_orders / accept_order`；接单授权门禁写在 `describe`（授权、`max_accept`、价格下限、`order_id`）。
- 新增 `src/services/mra_bridge.py`：`map_heartbeat_commands / apply_legacy_result / observe_order`，`/phone/heartbeat`、`/phone/command/result`、`/phone/order` 三端点接入。
- `schema_version=8`：新增 `phone_job_links`（`command_id → job_id/trace_id`）与 `count_today_accept()`；`executor.ORDER_STAGES` 增加 `accept`。
- 新增 CLI `mra carpool start/refresh/accept/stop/status`；`accept` 必须显式 `--accept`。
- 开关：`MRA_PHONE_BRIDGE`（默认开）、`MRA_ACCEPT_ENABLE`（默认关）。
- 测试：新增 `tests/test_carpool_adapter.py`（9 例）、`tests/test_phone_bridge.py`（11 例）。
- 已知限制：设备端 `autojs/main.js` 的 `accept` 仍为空实现，无 `order_id` 时挂 `pending_human`。

## v0.12.0 (2026-11-21)

P2 第 4 项：回归任务集（P2 完成）。

- 新增 `regression.py`：用例 = 基线 + 录制 + 期望（兼容/不兼容），批量执行 `explore.check_compatibility`。
- 新增表 `regression_cases`、`regression_runs`（`schema_version=7`）；每次运行落库 `regression.v1` 报告。
- 判定：结果与期望一致 → pass；不一致 → fail；基线/快照缺失 → error；空用例集视为不通过。
- 新增 CLI：`regression add/list/run`；`run` 失败或错误退出码 3；支持 `--tag` 分组、`--threshold`。
- 测试：新增 `tests/test_regression.py`（用例存储/期望反转/异常基线/标签/CLI 11 例）。

## v0.11.0 (2026-11-21)

P2 第 3 项：多设备并发。

- 新增 `devices` 表与心跳：`/commands`、`/results`、`/snapshots`、`/explore` 自动刷新 `last_seen`；新增 `mra devices [--offline-after]`。
- 作业设备亲和：`jobs.preferred_device` + `mra ingest --device-id`；绑定作业仅目标设备可认领。
- 认领并发安全：`claim_pending` 增加设备过滤、`UPDATE ... AND state='pending'` 行数校验、认领即 `attempts+1`。
- 掉线回收：`store.requeue_stale()`；`/commands` 领取前自动回收（设备 90s 无心跳或作业超时）。
  - 有订单证据 → `order_unknown`（等待对账，绝不重派）；
  - `attempts ≥ 2` → `failed`；
  - 其余回到 `pending` 并清空 `device_id/dispatched_at`。
- `schema_version=6`；新增事件 `device_stale_reset / device_stale_failed / order_unknown_pending_reconcile`。
- 测试：新增 `tests/test_multidevice.py`（心跳/亲和/跨实例并发认领/回收 14 例）。

## v0.10.0 (2026-11-21)

P2 第 2 项：视觉兜底（OCR 文本块定位）。

- 新增 `vision.py`：OCR 块（文本/坐标/置信度）→ `vision.v1`（`best/candidates/source/reason`）。
- 过滤空文本、置信度 < 0.5、非法坐标；打分 = 规则分 × `(0.5 + 0.5 × 置信度)`。
- 支付红线复用 `locator`：意图/块文本含支付类词即拒绝。
- 网关新增 `POST /vision/locate`（Token 鉴权；缺 intent/blocks 返回 400）。
- Auto.js：`ocrFallback` 使用 AutoJs6 内置 `ocr.detect`，无 OCR 能力时静默跳过；调用顺序 选择器 → /locate → /vision/locate。
- 测试：新增 `tests/test_vision.py`（排序/置信度/坐标校验/红线/网关 12 例）。

## v0.9.0 (2026-11-21)

P2 第 1 项：本地小模型定位兜底。

- 新增 `locator.py`：意图 + 无障碍节点树 → `locator.v1`（`best/candidates/source/reason`）。
- 规则排序：精确文本 > 包含 > 字符重合率；不可点击节点降权；阈值 0.3。
- 本地小模型（可选，OpenAI 兼容）：`MRA_LOCAL_MODEL_URL/NAME/KEY/TIMEOUT`；只允许在给定节点下标内选择，越界/异常/超时静默回退规则。
- 红线：意图或节点命中支付/提交/锁座词 → `source=guard`，不返回任何目标。
- 网关新增 `POST /locate`（Token 鉴权，400 缺 intent/nodes）。
- Auto.js：`locateFallback/clickLocated` 接入 `clickByTexts`，选择器全部失败后兜底重定位，仍受支付红线约束。
- 测试：新增 `tests/test_locator.py`（规则/红线/模型回退/网关 17 例）。

## v0.8.0 (2026-11-21)

P1 第 3 项：回放兼容门禁（P1 完成）。

- 新增 `explore.build_baseline / check_compatibility`：把一次录制固化为基线（步骤 + 逐帧签名断言），平台改版后与新录制比对。
- 判定规则：断言命中（签名相等，或期望文本重叠 ≥ 2/3）比例 ≥ 阈值（默认 0.8），且步骤取值（检索词/场次/价位）仍出现在新页面。
- 新增表 `adapter_baselines`（`schema_version=5`，按 name 幂等覆盖）。
- 新增 CLI：`explore baseline --id --name`、`explore check --name --id [--threshold]`；不兼容退出码 3。
- 事件：`explore_baseline_saved`、`explore_gate`（含覆盖率与失效步骤数）。
- 测试：新增 `tests/test_replay_gate.py`（存储/基线/命中率/阈值/CLI 共 10 例）。

## v0.7.0 (2026-11-21)

P1 第 2 项：探索录制 `mra explore`。

- 新增 `explore.py`：快照序列 → `explore.draft.v1` 草案（步骤/选择器证据/页面签名断言/告警），并可渲染为 L4 适配器源码草案。
- 新增表：`explorations`（录制会话）、`snapshots`（页面快照），`schema_version=4`。
- 网关新增 `GET /explore?device_id=` 与 `POST /snapshots`（Token 鉴权；仅 recording 状态接收快照，重复页面标记 duplicate）。
- 新增 CLI：`explore start|stop|list|show|draft`；`draft` 默认只输出 JSON，`--out` 才落盘。
- Auto.js：新增录制模式（`pollExplore/dumpNodes/nodeBrief/currentPage`），页面签名变化才上传；录制期间暂停预约作业执行。
- 纪律：草案只编排 `phone_tools` 已登记工具；支付/提交/锁座节点只记 warning，永不生成步骤。
- 测试：新增 `tests/test_explore.py`（存储/签名/草案/渲染/网关/CLI 共 21 例）。

## v0.6.0 (2026-11-21)

P1 第 1 项：千问知识标准化 `knowledge.ask`。

- 新增 `knowledge.py`：三段式提问模板（结论/依据/置信度）→ 解析为 `knowledge.v1` 结构化结果（`answer / citations / confidence / side_effect`）。
- 引用：优先提取 URL，其次取「依据」原文；无引用时置信度封顶 0.6。
- 安全：答案含支付/提交类指令 → 行级遮蔽 + `unsafe_actions_detected=true` + 置信度封顶 0.3。
- 缓存：新增 `knowledge_cache` 表（`schema_version=3`），按 `(app, question)` 指纹 TTL 缓存，默认 7 天；`--no-cache` 可强制实时。
- 新增 `mra knowledge ask "<问题>" [--app X] [--max-age N] [--no-cache] [--json]`。
- 修复 consult 幂等：`task_id` 改为 `consult:<指纹>`（原为时间戳，导致同问题可重复入队）；命中已有咨询时直接复用上次答案，`--no-cache` 则加时间戳强制重问。
- 白名单动作新增 `knowledge_ask`，并在红线词校验中与 `consult` 同等豁免（问题本身可含"支付/验证码"）。
- 测试：新增 `tests/test_knowledge.py`（解析/置信度/安全/缓存/传输 18 例）。

## v0.5.0 (2026-11-21)

P0 稳定性与安全（对应架构总览第 10 节 P0 四项）：

- **工具分层**：新增 L3 语义工具层 `phone_tools/`（工具 spec：入参/副作用/风险等级，含 `pay/submit_order/lock_seat` 禁止工具）；`phone_adapters/` 降为 L4 平台编排，只允许调用已登记工具，构建即校验。
- **状态机**：新增 `pending_human / takeover / order_unknown`；`needs_human→pending_human`、`takeover/needs_login→takeover`；`unknown` 仅保留给未映射回执。
- **订单对账 + 幂等**：新增 `store.reconcile / list_order_unknown / has_order_evidence` 与 `mra reconcile` 子命令；`order_unknown/pending_human/takeover` 禁止迁回 `pending/dispatched`；`_reset_stuck` 对已有订单证据的作业不再重派，转 `order_unknown`。
- **禁止「响应不确定就重试」**：下单阶段（order_confirm/cashier/submit/pay）报错或超时一律判 `order_unknown`，须人工对账收敛为 done/failed。
- **结构化回执**：指令携带 `trace_id` 与 `receipt.schema=mra.receipt.v1`；回执统一 `trace_id/stage/screenshot/page_text/order_id`，`results` 表新增结构化列（老库自动补列）。
- **回执幂等**：同一 `trace_id` + 同一归一状态重复回传只记一次，避免设备重试导致状态翻转。
- Auto.js Agent：新增 `collectPageText / findOrderId / buildReceipt`，超时按阶段判 `order_unknown`。
- 测试：新增 `test_state_machine / test_receipt / test_phone_tools / test_reconcile`（全部离线）。

## v0.4.0 (2026-11-21)

重建丢失的 Python 能力，并接入千问咨询通道：

- **AI 验收官**：`brain.verify` / `normalize_verdict`；`ask --execute` 与 `chat` 执行后统一验收，不合格按白名单补救复检（最多 2 轮）。
- **执行前预检**：`brain.precheck` / `precheck_plan`，缺 adapter/target_id/session/价格/问题直接拦下（EXIT 2）。
- **异步回执验收**：`patrol --stuck-seconds 180 --max-retries 2`，超时无回执复位重派，超限置 failed；`--consult` 自动问千问。
- **模型分档路由 + 遥测**：plan/verify/extract 分档，`model_calls.jsonl` 记录延迟与成败（不含提示词）。
- **千问咨询通道**：新增 `consult` 命令与 `qianwen` 适配器（非预约类），`consult` 进入白名单且豁免支付词拦截。
- **支付授权**：dispatch 支持 `pay_authorized`（默认 false，仅用户明确授权时置 true）。
- 新增运行手册 `skill/references/agent-flow-runbook.md`。

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

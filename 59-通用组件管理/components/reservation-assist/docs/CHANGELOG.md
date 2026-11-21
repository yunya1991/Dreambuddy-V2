# CHANGELOG — reservation-assist

## 0.11.2 — 2026-11-20

- 修复：`security -w` 对含中文的值返回十六进制，导致 `inbox show` 解析失败、去重失效；新增 `_decode_value` 自动还原
- 测试：十六进制解码、明文透传（85 项）

## 0.11.1 — 2026-11-20

- 增加同义命令：`开始预约`（等同 `开启预约` / `start`）、`停止预约`（等同 `关闭预约` / `stop`）
- 测试：同义命令解析

## 0.11.0 — 2026-11-20

- 中文开关命令：`ra 开启预约`（解除暂停 + 启动两个 agent）、`ra 关闭预约`（置暂停 + bootout 两个 agent）、`ra 状态`
- 英文别名 `start / stop / switch-status`；`watch pause-all / resume-all` 保留
- `inbox pull` 也遵守全局暂停开关，关闭后不再读群
- 测试：中文/英文命令解析（82 项）

## 0.10.0 — 2026-11-20

- 新增第二个 launchd 任务 `com.reservation-assist.inbox`：每 120s 执行 `inbox pull`，自动接收群里的参观人信息
- `ra install` 一次安装 watch + inbox 两个 agent；`ra uninstall` 一并卸载；`launchd.status()` 分别显示加载状态
- 模板仍用 `__HOME__/__PYTHON__/__COMPONENT__` 占位，`RA_ALLOW_SUBMIT=0`
- 测试：inbox 模板 120s 间隔与参数断言、双 agent 安装/卸载（80 项）

## 0.9.0 — 2026-11-20

- 新增入站实验：`ra inbox pull` 轮询指定飞书群（只读，`im:message` 权限），解析「姓名 + 身份证（可选手机）」写入 Keychain `com.reservation-assist.visitors`，回群只发脱敏摘要
- `ra inbox show` 默认脱敏展示；游标存 `meta.inbox_cursor`，重复消息按证件号去重
- 明确边界：仅存储与提醒，**不做自动提交**；完整证件号不出本机、不落盘、不进日志
- 测试：解析/脱敏/Keychain 往返/增量拉取与去重（9 项）

## 0.8.0 — 2026-11-20

- 新增 `feishu_app` 通道：用飞书自建应用 tenant token 向指定群发消息，凭据（app_id/app_secret/chat_id）存 Keychain `com.reservation-assist.feishu-app`
- 相比 webhook 更适合内部群：无需在群里加自定义机器人，机器人加群即可
- 测试：通道未配置报错、两次调用顺序（取 token → 发消息）、注册表

## 0.7.0 — 2026-11-20

- 飞书通知：webhook 支持从登录钥匙串读取（`com.reservation-assist.feishu`），不回显、不写入 plist
- 新增 `ra auth feishu`（stdin 读入并校验官方 webhook 前缀）与 `ra watch notify <task_id> --channels`
- `ra notify test --channel feishu` 可直接验证通道
- 测试：新增 webhook 读取/缺失、任务通知通道变更

## 0.6.0 — 2026-11-20

- gov 适配器支持状态型 JSON：接口返回 `data.timelist` 时按「开放时段变化」生成一条命中（`tier=status`），非 JSON 响应不再抛异常
- 首个真实试验对象：中国国家博物馆（`appapi.chnmuseum.cn/api/home/ticketinfo`），已验证真实请求 → 命中 → 本地通知 → 落库全链路
- `ra watch run` 修复：状态目录 chmod 失败不再中断（只读/受策略保护的目录）
- 新增 fixture `gov/status`

## 0.5.0 — 2026-11-20

- 新增 `ra auth set | status | clear`：Cookie 从 stdin 读入并写入 Keychain，不回显、不进 shell history
- `auth status --json` 输出各平台 `set / missing / public`（不含凭据值）
- 说明：浏览器 Cookie 目录受 macOS 隐私保护、Keychain 读取需用户授权，工具不尝试绕过

## 0.4.0 — 2026-11-20（P3 实验脚手架）

- 新增 `drills` 表（schema_version 2）：记录登录态采样与不付款演练证据
- 新增 `ra drill login | submit | check`：只记录与判定，不发任何网络请求；未达标退出码 3
- 判定门槛：登录态 ≥3 个自然日且 ≥30 次采样、演练 ≥20 次、0 次错目标/重复单、0 次需人工验证
- 通过后仍需人工把适配器 `SUBMIT_READY` 改为 True 并登记 `references/adapters.md`（代码不自动开启）
- 测试：新增 `test_readiness.py`（证据门槛/异常演练/CLI 判定），存储测试覆盖 drills
- 未包含：真实落单实现（P3 正式阶段，需先完成就绪实验）

## 0.3.0 — 2026-11-20（P2）

- 医疗/政务监控接入统一循环：`medical`（≥3000ms，需登录态）与 `gov`（≥5000ms，公开页面轮询，`REQUIRES_LOGIN=False`）
- `ra doctor` 新增每适配器 Cookie 状态检查（仅提示，不阻断自检）
- 测试：A4 回归扩展到全部 6 个适配器（各 100 次探测 + 重启后仅通知一次）；补充 medical/gov 间隔下限断言
- 未包含：真实平台联调（需账号与网络）、提交（P3）

## 0.2.0 — 2026-11-20（P1）

- 登录态：新增 Keychain Cookie 读取/写入（`security.load_cookie` / `store_cookie`），探测请求自动注入 `Cookie` 头
- 监控：`ra watch run` 启动时加载一次登录态；缺失写 `login_missing` 并通知，登录失效写 `auth_expired` 并通知，均不发起未登录探测
- launchd：`install(load=False)` 支持只落盘不加载；新增渲染/校验/安装/卸载测试（`plutil -lint` 校验）
- 测试：新增 `test_auth.py`、`test_launchd.py`；`test_adapters.py` 增加四适配器「100 次探测 + 进程重启后仅通知一次」回归（A4）
- 未包含：真实平台联调与 launchd 人工 5 步（A3b）、医疗/政务监控（P2）、提交（P3）

## 0.1.0 — 2026-11-20（P0）

- 新增组件骨架：`component.yaml` / `skill/SKILL.md` / `docs/` / `tests/`
- 内核：`ra.py` CLI、`scheduler.py`（对时/虚拟时钟/退避/唤醒）、`store.py`（SQLite DDL/幂等/TTL）、`notify.py`（通道 + 只通知一次）、`security.py`（redact/grant/门禁）、`launchd.py`
- 六个适配器：railway / damai / bilibili / maoyan / medical / gov，全部 `SUBMIT_READY=False`
- 契约：新增 `reservation.v1` profile；`component.schema.json` 放开 `family` 与 `output_contract`；`data-sources.yaml` 登记 DC-2 六条内部例外
- 测试：契约、存储、调度、提交门禁、隐私、架构、适配器回放，共 7 个测试文件 + golden
- 未包含：真实平台探测与 launchd 联调（P1）、医疗/政务监控（P2）、就绪实验与提交（P3）

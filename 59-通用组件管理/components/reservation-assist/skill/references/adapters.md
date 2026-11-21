# 适配器手册

> 平台协议变化只改 `skill/scripts/adapters/<平台>.py`；本文件记录探测点、失效特征与 `SUBMIT_READY` 实验状态。

## 1. 通用约定

| 项 | 规则 |
|---|---|
| 登录态 | 复用用户在浏览器中已登录的 Cookie，由 `security` 从 Keychain 读取；不存明文 |
| 探测 | `probe(target, transport)` 只读；一次请求只拉一个目标的场次/号源摘要 |
| 匹配 | `match(snapshot, rule)` 纯函数：余量 > 0、价格 ≤ `max_price`、票档命中 |
| 深链 | `handoff(hit)` 返回官方页面 URL，用于通知与人工下单 |
| 失败 | 401/403 → `AuthExpired`；429 → `RateLimited`；5xx → `TransportError`；页面结构变化 → `PlatformChanged` |
| 间隔 | 取「请求值 / 默认值 / 下限 / 平台最低间隔」最大值，见 SPEC §7 |

### 登录态配置

Cookie 只存 Keychain，服务名固定为 `com.reservation-assist.<adapter>`：

```bash
# 写入/更新（值来自浏览器已登录会话，勿落盘到仓库）
security add-generic-password -U -s com.reservation-assist.railway -a railway -w '<cookie>'

# 自检
security find-generic-password -s com.reservation-assist.railway -w
```

`ra watch run` 启动时通过 `security load_cookie` 读取一次并注入 `Cookie` 头；读取失败或为空时写 `login_missing` 事件并通知一次，**不发起未登录探测**。平台返回 401/403 时写 `auth_expired` 并通知，任务保留待用户更新 Cookie。

## 2. 平台矩阵

| 适配器 | 探测点 | 最低间隔 | 失效特征 | `SUBMIT_READY` |
|---|---|---|---|---|
| railway | 余票/候补页面 | 1500ms | 登录跳转、排队页、验证码 | False |
| damai | H5 场次接口 | 1000ms | 签名失效、滑块、风控页 | False |
| bilibili | 会员购 H5 接口 | 1000ms | 实名校验、设备异常、滑块 | False |
| maoyan | H5/浏览器 | 1500ms | 设备绑定、短信校验 | False |
| medical | 医院 H5 | 3000ms | 登录失效、号源结构变化 | False |
| gov | 页面轮询 | 5000ms | 一次性表单、图形验证码 | False |

`gov` 为公开预约时段页面只读轮询（`REQUIRES_LOGIN=False`），无需 Keychain Cookie；其余适配器需要账号登录态，缺失时跳过探测并通知一次。

`gov` 支持两种响应形态：
- `{"slots": [...]}`：号源列表，按 `left>0` 命中（字段 `site/date/period/fee/left/link`）
- `{"status":1,"data":{"timelist":{...}}}`：状态型接口，按开放时段变化命中（`tier=status`，`session=<opened>-<closed>`）

已接入真实试验：中国国家博物馆 `https://appapi.chnmuseum.cn/api/home/ticketinfo?p=wxmini`（每日 17:00 放票，监控任务窗口 16:55–17:05）。

## 3. `SUBMIT_READY` 就绪实验（P3 前置，当前全部未通过）

每个适配器独立进行，记录在此：

1. 连续 3 天每 2h 采样 `login_state`，平均有效时长 ≥ 任务窗口 + 30min
2. 提交步骤无不可自动处理的验证码/人脸
3. 20 次演练（真实页面、不付款）0 次错目标、0 次重复单
4. 通过后由用户手动把适配器类的 `SUBMIT_READY` 改为 `True`，并在本文件追加记录

证据用 `ra drill` 记账，判定用 `ra drill check`（只读，不发请求）：

```bash
ra drill login  --adapter railway --state ok
ra drill submit --adapter railway --result ok --captcha none --order-ref <演练单号>
ra drill check  --adapter railway          # 未达标退出码 3；--json 输出 reservation.v1
```

| 适配器 | 采样天数 | 演练次数 | 结论 | 记录人/日期 |
|---|---|---|---|---|
| railway | 0 | 0 | 未开始 | — |
| damai | 0 | 0 | 未开始 | — |
| bilibili | 0 | 0 | 未开始 | — |
| maoyan | 0 | 0 | 未开始 | — |
| medical | 0 | 0 | 未开始 | — |
| gov | 0 | 0 | 未开始 | — |

> `SUBMIT_READY=False` 时 `submit()` 直接抛 `GateDenied("adapter_not_ready")`，不会发出任何下单请求。

## 4. fixture 回放

```
tests/fixtures/<adapter>/<case>/
├── request.json   # {"url": "...", "status": 200}
├── response.txt   # 脱敏后的响应体
└── expected.json  # {"hits": [{"fingerprint": "...", ...}]}
```

fixture 不得包含真实 Cookie、手机号、证件号。

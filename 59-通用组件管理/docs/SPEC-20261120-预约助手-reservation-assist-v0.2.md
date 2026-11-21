# SPEC — 预约助手 reservation-assist v0.2

> **版本**: v0.2（待评审） | **日期**: 2026-11-20
> **上一版**: [v0.1](./SPEC-20261120-预约助手-reservation-assist-v0.1.md)（已被本版取代）
> **评审依据**: [REVIEW-20261120-SPEC-预约助手-reservation-assist-v0.1.md](./REVIEW-20261120-SPEC-预约助手-reservation-assist-v0.1.md)（8 阻断 + 10 重要）
> **范围**: 新增组件 `components/reservation-assist/`；修改 `contracts/component.schema.json`、`contracts/output.schema.json`、`contracts/data-sources.yaml`
> **定位**: 内部自用的本地预约/余票监控与辅助下单工具，CLI + launchd 常驻，不对外发布

---

## 0. 本版修订摘要

| 评审项 | 修订 |
|---|---|
| R-01/R-02/R-03 契约与闸门 | 新增 `reservation.v1` profile；`component.schema.json` 同步放开 `family` 与 `output_contract`；补 `docs/`、`test_privacy.py`、`tests/golden/report.json` |
| R-04 适配器协议 | 协议补 transport 注入、错误类型、fixture 契约、注册表；平台拆分为 6 个文件 |
| R-05/R-06 对时与节拍 | 改为 ms 级 `serverTime` + 虚拟时钟；API/浏览器两档间隔 + 平台最低间隔 |
| R-07 提交门禁 | `RA_ALLOW_SUBMIT` 降级为「只能否决」；改为 tty 一次性 grant（≤2h，绑任务+目标指纹） |
| R-08 四类可提交 | 保留：四类适配器都实现 `submit()`；但每个适配器有独立 `submit_ready`，须通过就绪实验才启用 |
| I-01…I-10 | 全部落入 §4/§7/§8/§9/§12/§13 |

**新增决策**：D5 自动提交保持四类开放（代码层不设白名单）；D6 一次性 grant；D7 报告新增 `reservation.v1`。

---

## 1. 背景与问题

现有 59 组件全部是"取数—加工—交付"的只读能力，没有**随时间推进的常驻任务**能力。刚需场景（火车票余票、演出开售、医院放号、政务/签证/场馆预约）有三个共性：

| # | 共性 | 现有缺口 |
|---|---|---|
| P1 | 目标在特定时刻出现 | 无调度器、无对时、无常驻进程 |
| P2 | 目标短暂可抢 | 无"探测 → 命中 → 通知 → 动作"状态机 |
| P3 | 需要登录态与个人信息 | 无凭据管理、无敏感信息最小化规范 |

GitHub 成熟项目证明能力可做，也证明平台协议会持续失效：**易变协议隔离在适配器，稳定能力（调度、存储、通知、门禁）做成内核**。

---

## 2. 目标与非目标

### 2.1 目标（可机器判定）

| # | 目标 | 判定 |
|---|---|---|
| G1 | 常驻监控可用 | 离线单测断言状态机在注入"重启/唤醒"信号后重算且不重复通知；另有人工 5 步清单（装 plist → `kill -9` → ≤15s running） |
| G2 | 平台协议变化只改适配器 | `tests/test_architecture.py` 扫描 `skill/scripts/`（排除 `adapters/`）平台词表，命中即失败；6 个适配器各自 fixture 回放通过 |
| G3 | 命中稳定通知且只通知一次 | 同一指纹重复探测 100 次，`FakeNotifier.calls == 1`；跨进程重启后仍为 1（`notified_at` 持久化） |
| G4 | 自动提交默认不可触发 | 无 grant 时 `submit` 抛 `GateDenied`；`RA_ALLOW_SUBMIT=0` 时即使有 grant 也拒绝；每次提交留审计事件 |
| G5 | 敏感信息不外泄 | `test_privacy.py` 扫描日志/事件/报告/`--json` 输出，证件号与 cookie 0 命中 |
| G6 | 测试期零外网 | 单测全部 `FakeTransport` / `FakeNotifier`；运行期才允许真实通道 |
| G7 | 报告符合契约 | `ra report --json` 通过 `reservation.v1` schema 校验 |

### 2.2 非目标

- 不做代抢、转售、加价；不做多账号；不做代理池与验证码破解
- 不托管支付；不调用锁座/占座接口
- 不做云端部署（检测到容器/云主机直接拒绝 submit）
- 不做 GUI；不做 SkillHub 商品化
- 不复制 PolyForm Noncommercial 项目代码

---

## 3. 决策记录

| 编号 | 决策 | 影响 |
|---|---|---|
| D1 | 允许自动提交（默认关闭） | 三重门禁 + grant（§8） |
| D2 | 首批四类平台全列 | 按难度分 P1/P2；四类均实现 submit，但需各自就绪实验 |
| D3 | 本地 CLI + launchd | 无服务端；launchd 模板 + `ra install` |
| D4 | 内部自用，暂不发布 | 不建 products；`data-sources.yaml` 走内部例外登记 |
| D5 | 自动提交**四类全部开放**，代码层不设平台白名单 | 以 `submit_ready` 替代白名单，避免"文档禁止、代码可绕" |
| D6 | 确认机制为 tty 一次性 grant（≤2h） | launchd 无人值守时永不提交 |
| D7 | 报告契约新增 `reservation.v1` | 三处契约同步修改 |

---

## 4. 目标结构

```
components/reservation-assist/
├── component.yaml
├── docs/                          # ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG
├── skill/
│   ├── SKILL.md                   # 版本与 component.yaml 一致（G5）
│   ├── scripts/
│   │   ├── ra.py                  # CLI：watch / grant / notify / doctor / reconcile / report / install
│   │   ├── scheduler.py           # 虚拟时钟、对时、退避、熔断、唤醒恢复
│   │   ├── store.py               # SQLite + DDL + 迁移 + TTL
│   │   ├── notify.py              # Channel 协议 + 真实通道 + FakeNotifier（测试）
│   │   ├── security.py            # Keychain、redact、consent
│   │   ├── launchd.py             # plist 渲染/安装/卸载/自检
│   │   └── adapters/
│   │       ├── base.py            # Protocol / 注册表 / 错误类型 / FixtureCase
│   │       ├── railway.py         # 12306
│   │       ├── damai.py           # 大麦
│   │       ├── bilibili.py        # B站会员购
│   │       ├── maoyan.py          # 猫眼
│   │       ├── medical.py         # 医院挂号 / 疫苗
│   │       └── gov.py             # 签证 / 车管所 / 场馆
│   ├── templates/
│   │   └── com.reservation-assist.watch.plist.tpl   # 占位符 __HOME__，禁止 /Users/
│   └── references/
│       ├── adapters.md            # 登录态获取、探测点、失效特征、submit_ready 实验记录
│       ├── compliance.md          # 红线与免责
│       └── methods.md             # 统计方法 ID（T01…）
└── tests/
    ├── test_contract.py           # 组件/SKILL 版本、入口、docs 登记
    ├── test_store.py              # DDL、幂等、指纹、TTL
    ├── test_scheduler.py          # 对时、虚拟时钟、唤醒、退避、熔断
    ├── test_submit_gate.py        # 默认拒绝、grant、unknown、价格上限
    ├── test_privacy.py            # redact 回归
    ├── test_architecture.py       # 平台词表扫描
    ├── test_adapters.py           # 6 个适配器 fixture 回放
    ├── golden/report.json         # 通过 reservation.v1
    └── fixtures/<adapter>/        # request/response/expected_hits，无真实凭据
```

**契约改动（P0 必做，三处）**：

1. `component.schema.json`：`family` 枚举加 `reservation-assist`；`output_contract` pattern 改为 `^(data|handoff|cogsteward|reservation)\.v1$`
2. `output.schema.json`：新增 `reservation.v1`，required = `schema_version / command / generated_at / tasks / hits / events / limits`；`limits` 非空（R10）
3. `data-sources.yaml`：新增 DC-2 内部例外登记（`12306 / damai / bilibili_mall / maoyan / hospital_h5 / gov_portal`，`status: active`、`commercial_use: exception`、`scope` 限 reservation-assist 内部自用、`restrictions` 含不再分发与限速）

**零内核依赖**：`kernel_deps: []`。现有 kernel 是云端取数—付费链路，与本组件无关；G4 对空列表直接通过。

---

## 5. 分层架构与数据流

```
launchd(KeepAlive) ──► ra watch run（每个平台单例 flock）
   ├─ scheduler：对时 → 虚拟时钟 → T-60s 预热 → 窗口内轮询 → 唤醒/跳变重算
   ├─ adapter.probe(target, transport) → Snapshot
   ├─ adapter.match(snapshot, rule) → [Hit]（纯函数）
   ├─ store.upsert_hit：UNIQUE(task_id, fingerprint)，返回是否首次
   ├─ notify：首次命中推送（含官方深链）；notified_at 持久化
   └─ submit（可选）：校验 grant → 二次校验目标/价格 → 下单/回填 → stopped at official page
          └─ events：submit_attempt / submit_ok / submit_denied / submit_unknown
```

**任务状态机**：`armed → probing → hit → notified → (submitting → submitted | unknown) → closed`；异常分支 `login_expired / rate_limited / platform_changed / cooldown / expired / cancelled`。`unknown` 只能由 `ra reconcile` 人工关闭，不自动重放。

---

## 6. 适配器协议与平台矩阵

```python
class Adapter(Protocol):
    NAME: str
    MIN_INTERVAL_MS: int          # 平台最低探测间隔
    SUBMIT_READY: bool            # 由就绪实验决定，默认 False
    def login_state(self, ctx) -> Literal["ok", "expired", "unknown"]: ...
    def probe(self, target: dict, transport: Transport) -> Snapshot: ...
    def match(self, snap: Snapshot, rule: dict) -> list[Hit]: ...
    def handoff(self, hit: Hit) -> str: ...
    def submit(self, hit: Hit, grant: Grant, transport: Transport) -> SubmitResult: ...
```

- `Transport`：`fetch(req) -> Response`，测试注入 `FakeTransport`；浏览器实现为可选 `BrowserTransport`
- 错误类型：`GateDenied / AuthExpired / RateLimited / PlatformChanged / TransportError / SubmitUnknown`
- `SubmitResult`：`state ∈ {ok, unknown, rejected}` + `official_order_ref`（可空）+ `detail`
- 注册表：`ADAPTERS = {"railway": Railway, ...}`；`--adapter` 必须命中注册表
- fixture 契约：`fixtures/<adapter>/<case>/request.json + response.txt + expected.json`

| 适配器 | 探测 | API 最低间隔 | 浏览器最低间隔 | submit 可行性 | submit_ready 初始 |
|---|---|---|---|---|---|
| railway | 余票/候补页面 | 1500ms | 5000ms | 低（队列+验证码） | False |
| damai | H5 接口 / 浏览器 | 1000ms | 5000ms | 低—中（签名+登录态） | False |
| bilibili | H5 接口 | 1000ms | 5000ms | 低—中（实名+设备+滑块） | False |
| maoyan | H5 / 浏览器 | 1500ms | 5000ms | 低（设备绑定+短信） | False |
| medical | 医院 H5 | 3000ms | 8000ms | 低—中（实名+号源） | False |
| gov | 页面轮询 | 5000ms | 10000ms | 低（一次性表单） | False |

**`submit_ready` 就绪实验**（每个适配器独立，记录在 `references/adapters.md`）：

1. 连续 3 天每 2h 采样 `login_state`，平均有效时长 ≥ 任务窗口 + 30min
2. 提交步骤无不可自动处理的验证码/人脸
3. 20 次演练（真实页面、不付款）0 次错目标、0 次重复单
4. 通过后由用户手动把 `SUBMIT_READY` 改为 True 并提交记录

> D5 保留四类可提交；`SUBMIT_READY=False` 时 `submit()` 抛 `GateDenied("adapter_not_ready")`，与白名单的区别是：它可被实验与人工确认打开，且过程留痕。

---

## 7. 对时、节拍与恢复

| 项 | 规则 |
|---|---|
| 时间源 | 优先平台返回的 ms 级 `serverTime`；次选 ms 级公共时间接口；`sntp` 仅作交叉校验（不依赖 sudo） |
| 采样 | 5 次，取 RTT 最小的 3 次；离散度 ≤50ms 且 RTT ≤300ms 才采信 |
| 虚拟时钟 | `t_v = monotonic + offset`；倒计时一律用 `t_v`；offset 每 300s 刷新 |
| 置信度 | 置信区间 >1.5s → 降级为盲轮询 + 告警；**禁止**因偏差长期拒绝冲刺 |
| 唤醒 | 每 tick 比对 `Δwall − Δmono > 5s` 判为休眠唤醒 → 立即重对时；窗口已过则立即探测一次并通知 |
| 预热 | T-60s 校验登录态、解析票档/号源结构；失败即通知 |
| 节拍 | API 默认 1000ms / 下限 500ms；浏览器默认 5000ms / 下限 3000ms；平台 `MIN_INTERVAL_MS` 取三者最大 |
| `--unsafe-interval` | 不得低于上述下限；仅允许演出票适配器使用 |
| 退避/熔断 | 1s/2s/4s/8s，20 次失败熔断 300s；识别到验证码/风控页 → 该任务冷却 24h 并通知，不重试不降级 |
| 开售改期 | `rule.recheck_every=600s` 重读页面时间；变更即通知并重算窗口 |

---

## 8. 自动提交门禁（D5 + D6）

**提交前置条件（全部满足才放行）**：

| 门禁 | 条件 | 失败行为 |
|---|---|---|
| 环境 | 非容器/云主机；`RA_ALLOW_SUBMIT != "0"` | `GateDenied("env")` |
| 适配器 | `SUBMIT_READY is True` | `GateDenied("adapter_not_ready")` |
| 任务 | `submit_enabled=1`、`max_orders=1`、价格上限已填、观演人/就诊人已选 | `GateDenied("task_config")` |
| Grant | 存在未过期 grant，且 `grant.fingerprint == 当前目标指纹` | `GateDenied("grant")` |
| 幂等 | 该 `(task_id, fingerprint)` 无 `submitted/unknown` 记录 | `GateDenied("already_submitted")` |

**grant 签发**：`ra watch grant <task_id>`

- 必须在 tty（`sys.stdin.isatty()`），否则拒绝
- 打印目标摘要（平台/场次/票档/价格上限/就诊人后 4 位），要求输入指纹末 6 位确认
- 落库：`grant_id / task_id / fingerprint / issued_at / expires_at（≤2h）/ hmac`；只存 hmac，不存明文
- 撤销：`ra watch revoke <task_id>`；`ra watch rm` 级联删除

**其它硬约束**：

- 不自动支付；终态 = **停在官方下单页并回填目标**，**禁止调用锁座/占座接口**（`test_submit_gate.py` 负向断言）
- 超时 / 5xx / 412 / 风控页 / 响应不可解析 → `unknown`；**不重试提交**；`ra reconcile` 只读官方订单列表，人工关闭
- 仅明确业务错误码（如"票已售罄"）允许重试 1 次
- 每次尝试写 `events`，payload 仅存摘要（场次 ID、票档 ID、结果码），不含身份信息

---

## 9. 存储、凭据与隐私

**DDL（`store.py` 内嵌，带 `schema_version`）**：

```sql
tasks(id TEXT PK, adapter TEXT, target_json TEXT, rule_json TEXT,
      window_start INTEGER, window_end INTEGER, interval_ms INTEGER,
      submit_enabled INTEGER DEFAULT 0, max_orders INTEGER DEFAULT 1, created_at INTEGER)
hits(id INTEGER PK, task_id TEXT, fingerprint TEXT, at INTEGER,
     snapshot_digest TEXT, notified_at INTEGER, submit_state TEXT,
     UNIQUE(task_id, fingerprint))
events(id INTEGER PK, at INTEGER, level TEXT, code TEXT, task_id TEXT, payload_json TEXT)
grants(id TEXT PK, task_id TEXT, fingerprint TEXT, issued_at INTEGER, expires_at INTEGER, hmac TEXT)
```

- 指纹 = `sha256(adapter|target_id|date|session|price_tier)`，`date` 按 Asia/Shanghai 自然日归一
- `snapshot_digest` 只存摘要，不存原始 HTML；调试快照需 `--debug-snapshot` 且经 `redact()`
- 并发：`journal_mode=WAL`、`busy_timeout=5000`、`synchronous=NORMAL`；写事务用 `BEGIN IMMEDIATE`，冲突重试 3 次
- TTL：hits 30d、events 90d，启动时清理；`PRAGMA secure_delete=ON`，每月 `VACUUM`
- 凭据：只用 Keychain（`security add-generic-password -U`）；`doctor` 执行 `timeout 3 security find-generic-password`，失败则**禁用 submit**，不降级明文/AES
- 目录：`~/.reservation-assist/`（0700），`ra doctor` 检查是否被 Time Machine/iCloud 排除
- redact：证件号、手机号（保留后 4）、cookie/token（整段）、地址；覆盖日志、events、`--json`、report

---

## 10. 契约适用域（评审 R-02）

| 红线 | 适用 | 说明 |
|---|---|---|
| R1 禁方向词 | ✅ | 通知与报告文案过词表；"机会/推荐/预计"等一律不得出现 |
| R2 禁外推 | ✅ | 不预测"能否抢到"，只报当前观测 |
| R3 缺失不填充 | ✅ | 探测失败写 `missing[]` + 原因码，不用 0/上期值替代 |
| R4 每个数字可复核 | ⚠️ 部分 | 仅统计量（命中次数、平均探测延迟）需 `method_id`（T 系列，登记 `references/methods.md`）+ `n` |
| R5 数据源授权 | ✅ | 走 `data-sources.yaml` 的 DC-2 内部例外，不得扩大用途 |
| R6 禁再分发原始数据 | ✅ | 不存/不输出原始页面，只输出场次/票档摘要与深链 |
| R7 通道失败不静默降级 | ✅ | 云端通道不适用；通知失败重试 2 次后落 `missing[]` 并告警 |
| R8 跨组件边界 | ✅ | 不引用任何其它组件路径 |
| R9 不越界写盘 | ✅ | 只写 `~/.reservation-assist/` 与 `~/Library/LaunchAgents/` |
| R10 免责不可省 | ✅ | `limits` 非空；报告固定含方法/来源/许可/缺失 |

---

## 11. CLI 契约

```
ra watch add   --adapter <name> --target <json|@file> --rule <json|@file>
               --window "<start>/<end>" [--interval ms] [--notify feishu,local] [--submit]
ra watch list  [--json]
ra watch rm    <task_id>
ra watch grant <task_id>          # 必须 tty；签发 ≤2h grant
ra watch revoke <task_id>
ra watch run   [--task <task_id>] [--foreground]
ra watch pause-all | resume-all   # 全局刹车
ra notify test --channel <name>
ra doctor      [--json] [--purge]
ra reconcile   <task_id>          # 人工对账，关闭 unknown
ra report      [--date YYYY-MM-DD] [--json]   # reservation.v1
ra install | uninstall            # launchd 渲染与安装
```

退出码：`0` 成功；`2` 参数错误；`3` 门禁拒绝；`4` 登录态失效；`5` 平台不可达；`6` 需人工对账。

`reservation.v1` 字段：`schema_version / command / generated_at / tasks[] / hits[] / events[] / missing[] / limits`；`tasks` 项含 `id/adapter/status/window_start/window_end`，`hits` 项含 `task_id/fingerprint/at/result`。

---

## 12. 测试与验收

| # | 验收项 | 方法 |
|---|---|---|
| A1 | 闸门全绿 | `make check`（sync_kernel + G1–G7 + gen_index） |
| A2 | 单测离线全绿 | `python3 -m unittest discover -s tests -v`，`FakeTransport`/`FakeNotifier` |
| A3a | 恢复语义 | 单测注入重启/唤醒信号，断言状态重算且不重复通知 |
| A3b | launchd 恢复 | 人工 5 步：`ra install` → `launchctl print` → `kill -9` → ≤15s running → `ra uninstall` |
| A4 | 去重与通知一次 | 重复命中 100 次 + 进程重启，`notified` 次数 == 1 |
| A5 | 提交默认拒绝 | 无 grant / env=0 / 非 tty / 适配器未就绪 4 组负向 + 1 组正向（fixture） |
| A6 | 隐私回归 | 扫描日志、events、report、`--json` |
| A7 | 报告契约 | `golden/report.json` 与 `ra report --json` 均通过 `reservation.v1` |
| A8 | 时钟跳变 | wall/mono 差 1800s，断言重对时且不误判命中 |
| A9 | 架构约束 | 平台词表 0 命中；6 个适配器 fixture 齐全 |
| A10 | 无锁座断言 | 代码扫描 `lock|occupy|hold_seat` 相关调用为 0 |

---

## 13. 分阶段计划

| 阶段 | 交付 | 验收 |
|---|---|---|
| P0 | 契约三处改动 + 骨架（CLI/store/scheduler/notify/security/launchd）+ golden + 全量单测 | A1/A2/A3a/A6/A7/A8/A9 |
| P1 | `damai` / `bilibili` / `maoyan` / `railway` 监控与通知；`ra install` 可用 | A3b/A4 |
| P2 | `medical` / `gov` 监控与通知 | A4 |
| P3 | 六个适配器就绪实验 → 逐个置 `SUBMIT_READY`；grant + submit + reconcile | A5/A10 |

每阶段跑 `make check` + 全量单测；P3 前不写任何落单代码路径（只留协议与 `GateDenied`）。

---

## 14. 风险与回滚

| 风险 | 概率 | 缓解 | 回滚 |
|---|---|---|---|
| 平台协议变更 | 高 | 适配器隔离 + `doctor` 探活 + 失效通知 | 停用单适配器 |
| 账号被风控 | 中 | 平台最低间隔、抖动、单账号、默认无 grant | `ra watch pause-all` |
| 误下错单 | 中 | grant 绑指纹、价格上限、`max_orders=1`、不支付 | `rm` + `reconcile` 审计 |
| 凭据泄露 | 低 | 仅 Keychain、redact、失败禁用 submit | `doctor --purge` |
| 休眠/时钟跳变误判 | 中 | 虚拟时钟 + 唤醒检测 + A8 | 前台模式 `--foreground` |
| 磁盘不足（实测 1.9GiB） | 中 | 默认不装 Playwright；浏览器 Transport 需显式安装并检查剩余空间 | 纯 API 模式 |

---

## 15. 决策关闭（2026-11-20）

| 编号 | 决策 |
|---|---|
| D8 | `data-sources.yaml` 新增 DC-2 内部例外登记（6 条，`commercial_use: exception`，仅 reservation-assist 内部自用，禁止再分发，限速） |
| D9 | 默认通知通道：飞书 + macOS 本地通知（`--notify feishu,local`） |
| D10 | 接受自动提交就绪实验前置：3 天登录态采样 + 20 次演练，通过后才置 `SUBMIT_READY=True` |

无剩余待确认项；下一阶段为 P0 落地。

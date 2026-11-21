# SPEC — 预约助手 reservation-assist v0.1

> **版本**: v0.1（待评审） | **日期**: 2026-11-20
> **范围**: 新增组件 `components/reservation-assist/`；扩展 `contracts/component.schema.json` 的 `family` 枚举；新增 `docs/` 文档
> **依据**: [RESEARCH-20261120-预约与抢票工具-GitHub调研-v0.1.md](./RESEARCH-20261120-预约与抢票工具-GitHub调研-v0.1.md) + 2026-11-20 用户决策
> **不改动**: 现有 4 个组件的代码与契约、`products/*.yaml`、`platform/`
> **定位**: 内部自用的本地预约/余票监控与辅助下单工具，以 CLI + launchd 常驻，不对外发布

---

## 1. 背景与问题

现有 59 组件全部是"取数—加工—交付"的只读能力，没有任何**随时间推进的常驻任务**能力。用户的高频刚需场景（火车票余票、演出开售、医院放号、政务/签证/场馆预约）具有三个共性：

| # | 共性 | 现有组件的缺口 |
|---|---|---|
| P1 | 目标在**特定时刻**出现（开售、放号） | 无调度器、无对时、无常驻进程 |
| P2 | 目标**短暂可抢**（秒级窗口） | 无"探测 → 命中 → 通知 → 动作"状态机 |
| P3 | 需要**登录态与个人信息**（联系人、就诊人、观演人） | 无凭据管理、无敏感信息最小化规范 |

GitHub 成熟项目证明这套能力可做，但也证明**平台适配会持续失效**：架构必须把"易变的平台协议"隔离在适配器里，把"稳定的调度、存储、通知、门禁"做成内核。

---

## 2. 目标与非目标

### 2.1 目标（可验收）

| # | 目标 | 判定 |
|---|---|---|
| G1 | 常驻监控可用：任务在 launchd 托管下持续运行，崩溃自动拉起 | `ra doctor` 显示守护进程与任务状态；手动 kill 后 60s 内恢复 |
| G2 | 四类平台均有适配器落地，协议变化只改适配器 | 四类适配器各自契约测试通过；内核代码 0 处平台分支 |
| G3 | 开售/放号命中可**稳定通知**，且只通知一次 | 同一命中重复探测 100 次，通知次数 == 1 |
| G4 | 自动提交受门禁约束，默认不可触发 | 默认配置下负向测试：`submit` 被拒绝；开启后每次提交均留审计事件 |
| G5 | 敏感信息不外泄 | 日志/事件/报告全文扫描 0 命中证件号、cookie、token |
| G6 | 无外网依赖也能验收 | 全部单测基于 fixtures，运行期 0 外网请求 |

### 2.2 非目标

- 不做多账号、不做代抢、不做转售、不做代理池与验证码破解
- 不托管支付：任何场景都不自动付款，最多创建订单/占座
- 不做云端部署：默认只在本机运行（云端 IP 多账号抢公共资源属红线）
- 不做 GUI（本轮）；不做 SkillHub 商品化（本轮）
- 不复制 PolyForm Noncommercial 项目的代码；只借鉴设计

---

## 3. 决策记录（2026-11-20 用户确认）

| 编号 | 决策 | 影响 |
|---|---|---|
| D1 | 功能边界：**允许自动提交** | 需完整提交门禁（§8），默认关闭 |
| D2 | 首批平台：12306、演出票（大麦/B站/猫眼）、医疗预约、政务/签证/场馆**四类全列** | 按适配难度分 P1/P2 两批落地，属排序而非缩范围 |
| D3 | 载体：**本地 CLI + launchd** | 无 Web 服务、无数据库服务端 |
| D4 | 发布：**内部自用，暂不发布** | 不建 `products/*.yaml`、不做许可隔离包装；免责声明仍写入 SKILL |

---

## 4. 目标结构

```
components/reservation-assist/
├── component.yaml                 # name/version/family=reservation-assist/entrypoints/tests
├── skill/
│   ├── SKILL.md                   # 版本与 component.yaml 一致（G5）
│   ├── scripts/
│   │   ├── ra.py                  # CLI 入口：watch / notify / doctor / report
│   │   ├── scheduler.py           # 对时、倒计时、退避、熔断、flock 单例
│   │   ├── store.py               # SQLite（tasks / hits / events）
│   │   ├── notify.py              # 通道：本地通知 / 飞书 / 企业微信 / 邮件
│   │   └── adapters/
│   │       ├── base.py            # Adapter 协议与快照/规则/命中数据结构
│   │       ├── railway.py         # 12306
│   │       ├── performance.py     # 大麦 H5 / B站会员购 / 猫眼
│   │       ├── medical.py         # 医院挂号 / 疫苗放号
│   │       └── gov.py             # 签证 / 车管所 / 场馆预约
│   └── references/
│       ├── adapters.md            # 每平台登录态获取、探测点、失效特征
│       └── compliance.md          # 红线与免责（SKILL 必读）
└── tests/
    ├── test_contract.py           # component/SKILL 版本一致、入口存在
    ├── test_store.py              # SQLite 幂等、去重、并发锁
    ├── test_scheduler.py          # 对时误差、退避、熔断、时间窗
    ├── test_submit_gate.py        # 默认拒绝、审计留痕、单任务单订单
    ├── test_adapters.py           # 四类适配器 fixture 回放
    └── fixtures/                  # 录制的 HTML/JSON，不含真实凭据
```

**零内核依赖**：`kernel_deps: []`。现有 kernel 是"取数—分装—付费"链路，与本组件无关；强行复用会把云端通道带进本地常驻进程。

**契约扩展**：`contracts/component.schema.json` 的 `family` 枚举新增 `reservation-assist`。这是唯一需要改的既有契约，其余闸门（G1–G7）无需放宽。

---

## 5. 分层架构与数据流

```
launchd(KeepAlive) ──► ra watch run（单例 flock）
                         │
                         ├─ scheduler：多源对时 → T-60s 预热 → 时间窗内轮询
                         │
                         ├─ adapter.probe()  只读快照（无副作用）
                         │        └─► adapter.match(rule)  →  [Hit]
                         │
                         ├─ store：hit 去重落库（task_id + 指纹 唯一）
                         ├─ notify：首次命中推送（含官方深链）
                         └─ submit（可选，门禁后）：创建订单/占座，停在下单页
                                  └─► events 审计（时间、参数摘要、结果码）
```

与成熟项目的对应：py12306 的"多任务 + 通知矩阵"、tickets 的"后台任务与自动校时"、biliTickerBuy 的"分层与退避"在此收敛为**一个内核 + 四个适配器**。

---

## 6. 适配器矩阵

| 适配器 | 平台 | 探测方式 | 自动提交可行性 | 风险 | 批次 |
|---|---|---|---|---|---|
| `railway` | 12306 | 官方余票/候补页面（登录态浏览器） | 低：排队+验证码，建议只做到"候补辅助 + 提醒" | 高（平台明确反第三方工具） | P1 |
| `performance` | 大麦 H5、B站会员购、猫眼 | H5 接口（登录态）或浏览器 | 中高：B站/大麦有成熟链路可参照 | 中高（ToS + 风控） | P1 |
| `medical` | 医院挂号、疫苗放号 | 医院 H5/公众号接口 | 中：实名 + 号源紧张，提交需逐次确认 | 高（号源属公共资源） | P2 |
| `gov` | 签证中心、车管所、场馆 | 页面轮询为主 | 低：多为一次性表单，建议只提醒+跳转 | 中 | P2 |

**统一协议（`adapters/base.py`）**：

```
login_state() -> "ok" | "expired" | "unknown"
probe(target) -> Snapshot            # 只读，必须可被 fixtures 回放
match(snapshot, rule) -> list[Hit]   # 纯函数，无 I/O
handoff(hit) -> str                  # 官方深链（默认动作）
submit(hit, gate) -> SubmitResult    # 可选；gate 未通过必须抛 GateDenied
```

**约束**：内核不得出现平台名分支；新增平台 = 新增一个文件 + 在 `adapters.md` 登记探测点与失效特征。

---

## 7. 调度、对时与限速

| 项 | 规则 |
|---|---|
| 对时 | 至少 2 个时间源（平台时间接口 + 本机 NTP），采样 5 次取最小 RTT；偏差 > 500ms 告警并拒绝进入最后 10s 冲刺 |
| 预热 | 开售前 60s 完成登录态校验、票档/号源结构解析，失败即提前通知 |
| 轮询间隔 | 默认 1000ms；下限 300ms（需 `--unsafe-interval` 显式开启）；上限受平台限速约束 |
| 抖动 | 每次间隔 ±15% 随机，避免固定节拍 |
| 退避 | 连续失败按 1s/2s/4s/8s 指数退避，20 次失败熔断 300s 并通知 |
| 单例 | 每个平台同时只允许 1 个任务进程（flock），避免自造并发 |
| 时间窗 | 任务必须声明 `window_start/window_end`，窗口外不探测 |

---

## 8. 自动提交门禁（D1 的核心）

自动提交是**默认关闭**的三重门禁能力，任一门禁不满足即拒绝：

| 门禁 | 条件 |
|---|---|
| 环境门禁 | 本地运行（检测到云端/容器环境直接拒绝）；`RA_ALLOW_SUBMIT=1` |
| 任务门禁 | 任务显式 `submit.enabled: true` + `max_orders: 1` + 明确的观演人/就诊人 |
| 逐次确认 | 交互模式：每次提交弹出确认；非交互（launchd）：必须 `--i-understand-risk` 且 24h 内同平台 ≤1 单 |

其它硬约束：

- **不自动支付**，最多创建订单/占座，终态必须由用户完成
- 提交前二次校验目标（场次/票档/价格上限/就诊人），不匹配即中止
- 响应不确定（超时、风控页）**不得重试提交**，转为人工核对官方订单
- 全量写 `events`：`submit_attempt / submit_ok / submit_denied / submit_unknown`，不含证件号

---

## 9. 凭据与数据安全

| 项 | 规则 |
|---|---|
| 存储位置 | `~/.reservation-assist/`（0700）；数据库 `ra.db`（0600） |
| 凭据 | 优先 macOS Keychain（`security` CLI）；无法使用时 AES-GCM 加密文件，口令不落盘 |
| 最小化 | 只存必要字段；证件号/手机号仅保留后 4 位用于展示 |
| 日志 | 白名单字段；写盘前经 `redact()`；`test_privacy.py` 用正则回归 |
| 清理 | `ra watch rm` 级联删除任务、命中、凭据引用；`ra doctor --purge` 全清 |

---

## 10. 合规红线（写入 SKILL 与 `references/compliance.md`）

1. 禁止代抢、转售、加价；本工具只服务账号所有者本人。
2. 禁止验证码破解、风控绕过、代理池对抗、多账号批量抢占。
3. 禁止在云端/多 IP 环境运行；默认仅本机。
4. 医疗与政务类只做**号源监控与提醒**；自动提交仅在用户逐次确认下对自约场景开放。
5. 平台协议普遍禁止自动化访问：任务创建时必须展示一次性风险确认，用户确认后才落库。
6. 明确"不保证成功、不承担因使用导致的账号或法律风险"。

---

## 11. CLI 契约

```
ra watch add  --adapter <name> --target <json|@file> --rule <json|@file>
              --window "2026-11-21T10:00:00+08:00/2026-11-21T10:10:00+08:00"
              [--interval 1000] [--notify feishu,wecom,local] [--submit]
ra watch list [--json]
ra watch rm   <task_id>
ra watch run  [--task <task_id>] [--foreground]
ra notify test --channel <name>
ra doctor     [--json] [--purge]
ra report     [--date 2026-11-20] [--json]
```

退出码：`0` 成功；`2` 参数错误；`3` 门禁拒绝；`4` 登录态失效；`5` 平台不可达。

`ra report --json` 遵循 `contracts/output.schema.json` 的 `data.v1` 外壳。

---

## 12. 测试与验收

| # | 验收项 | 方法 |
|---|---|---|
| A1 | 独立性闸门全绿 | `make check`（sync_kernel + G1–G7 + gen_index） |
| A2 | 单测全绿且零外网 | `python3 -m unittest discover -s tests -v`，fixtures 回放 |
| A3 | 守护可恢复 | 安装 plist → kill 进程 → 60s 内 `ra doctor` 恢复 running |
| A4 | 去重与通知一次 | `test_store.py` 重复命中 100 次断言 1 次通知 |
| A5 | 提交默认拒绝 | `test_submit_gate.py` 全部负向通过；开启后才允许 |
| A6 | 隐私回归 | `test_privacy.py` 扫描日志/事件/报告 0 命中 |
| A7 | 报告契约 | `ra report --json` 通过 `data.v1` schema 校验 |

---

## 13. 分阶段计划

| 阶段 | 交付 | 验收 |
|---|---|---|
| P0 | 骨架：CLI、store、scheduler、notify、doctor、launchd 模板、fixtures 测试 | A1/A2/A3/A6 |
| P1 | `performance`（大麦/B站）+ `railway`（监控与候补提醒）；只读+通知 | A4 |
| P2 | `medical` + `gov`（监控+提醒）；自动提交门禁接入 | A5 |
| P3 | 演出票自动提交（逐次确认）+ `report` 复盘 | A7 |

每阶段完成跑 `make check` + 全量单测；阶段间不合并提交。

---

## 14. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| 平台改协议导致适配器失效 | 高 | 单平台失效 | 适配器隔离 + `doctor` 探活 + 失效即通知 | 停用该 adapter，不影响其它任务 |
| 账号被风控/封禁 | 中 | 用户损失 | 限速、抖动、单账号、默认关闭提交 | 提供"暂停全部任务"开关 |
| 自动提交误下错单 | 中 | 资金/纠纷 | 价格上限、目标二次校验、max_orders=1、不自动支付 | 任务级 `rm` + 审计回放 |
| 凭据泄露 | 低 | 严重 | Keychain、redact、最小化 | 一键 `doctor --purge` |
| launchd 权限问题 | 中 | 守护不启动 | `doctor` 检测 plist 状态与日志路径 | 提供前台模式 `--foreground` |

---

## 15. 待评审确认

1. D2 的批次拆分（P1 演出+12306，P2 医疗+政务）是否接受
2. 12306 是否只做"监控 + 候补辅助"，不做自动提交（建议如此）
3. 通知首选通道是否用飞书（与现有 lark 能力一致）
4. 凭据存储是否接受 Keychain 优先、加密文件兜底

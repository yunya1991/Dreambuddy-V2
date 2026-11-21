# RESEARCH-20261120 — 预约与抢票工具 GitHub 成熟项目调研 v0.1

> **状态**：调研完成，待用户确认边界与形态后再转 SPEC
> **目的**：为 `59-通用组件管理` 新增「预约助手（余票监控·开售提醒）」组件做技术选型与合规前置评估
> **调研日期**：2026-11-20

---

## 0. 结论摘要

1. **没有可直接拿来用的"通用抢票框架"**。GitHub 上的成熟项目全部是**单平台垂直**实现（12306 / 大麦 / B站会员购 / 约苗），通用能力沉淀在 6 个可抽象层（见 §2），值得借鉴的是**分层设计**而不是代码。
2. **代码复用受许可强约束**：星标最高的 `testerSunshine/12306` 已归档（34.0k★，MIT）；活跃的 `pjialin/py12306` 为 Apache-2.0（15.0k★）；最活跃的 B 站项目 `mikumifa/biliTickerBuy` 使用 **PolyForm Noncommercial 1.0.0**（约 4.2k★），**禁止商用，只能借鉴设计，不能复制代码**。若要作为 SkillHub 商品分发，必须自研实现。
3. **技术路线已收敛为四类**：API 直连（快但脆、ToS 风险最高）、无头浏览器（稳、像人）、安卓 adb/模拟器（抗风控、工程最重）、半自动监控+通知（合规风险最低）。**建议默认走第四类，自动提交列为需要用户逐次确认的可选能力。**
4. **最大风险不是技术，是合规**：代抢/转售、绕过验证码与风控、云端多账号抢占公共号源，均可能触发平台追责与法律责任；医疗号源尤其敏感。产品定位必须落在「个人余票监控 + 提醒 + 官方渠道跳转」，而不是「代抢」。
5. **对本模块的落地建议**：新建组件 `reservation-assist`（对外名「预约助手」），复用现有 `kernel/`（headers/endpoint/pay_gate/handoff）与 `data.v1` 输出契约，按 `products/*.yaml` 构建免费/Pro 变体；仅需扩展 `contracts/component.schema.json` 的 `family` 枚举。

---

## 1. 项目清单（核实到 2026-11-20）

| 项目 | 场景/平台 | 技术栈 | Star | 许可 | 活跃度 | 可借鉴点 |
|---|---|---|---|---|---|---|
| [testerSunshine/12306](https://github.com/testerSunshine/12306) | 12306 火车票 | Python + requests | 34.0k | MIT | **已归档**（最后提交 2023-04） | 抢票状态机、排队/验证码/订单流程；接口早已失效，仅作历史参考 |
| [pjialin/py12306](https://github.com/pjialin/py12306) | 12306 火车票 | Python + Django Web | 15.0k | Apache-2.0 | 活跃（2026-10 有提交） | 多账号/多任务/多线程、Redis 分布式集群与主从切换、通知矩阵（邮件/微信/TG/钉钉/语音）、代理池、Web 管理页 |
| [mikumifa/biliTickerBuy](https://github.com/mikumifa/biliTickerBuy) | B站会员购 | Python（tyro CLI + Gradio UI） | 约 4.2k | **PolyForm Noncommercial 1.0.0** | 活跃（2026-09） | 六层分层、开售对时与重试退避、任务状态机、CLI/GUI 双入口；分布式版 biliTickerStorm、Skill 版 biliTickerSkill 可参考产品化路径 |
| [shiyutim/tickets](https://github.com/shiyutim/tickets) | 大麦 H5、B站会员购 | Tauri + Rust + Vue 3 | — | — | 活跃 | 多账号 Cookie 管理、后端常驻任务（切页不影响）、余票监控、微信提醒、自动校时（多源采样取最小 RTT）、订单异常分类 |
| [ClassmateLin/dm-ticket](https://github.com/ClassmateLin/dm-ticket) | 大麦 | Python + Selenium | — | — | — | 浏览器自动化下单链路与重试策略 |
| DamaiHelper | 大麦 | Python + Selenium | — | — | — | 页面元素定位、异常场景兜底 |
| [williechan2015/damai-mcp-ts](https://github.com/williechan2015/damai-mcp-ts) | 大麦/猫眼/飞猪 | TypeScript + adb 安卓模拟器 + MCP | — | — | 活跃 | 把抢票动作封装为 **MCP 工具**给 AI 调用；真机/模拟器路径规避 Web 风控 |
| Gitee `BuyingSpree_HPV` / `seckill` / `hpv4g` | 约苗/秒苗 九价 HPV | Python / JS | — | — | — | 抓包导入 cookie/token、成员档案、开售前定时并发、成功后人工选接种时段 |
| EMIAС slot hunter（polinalamponi） | 俄公立医院挂号 | 浏览器用户脚本（Tampermonkey） | — | MIT | — | **号源释放监控 + 改约更早时段**；纯浏览器内运行、无服务端，合规形态最轻 |

> 星标以 GitHub API 实测为准；`—` 表示未核实，不作为结论依据。

---

## 2. 成熟项目的能力分层（可直接映射为组件内部结构）

| 层 | 职责 | 典型实现 | 复用建议 |
|---|---|---|---|
| L1 会话/凭证 | 扫码登录、Cookie/token 导入与刷新、多账号隔离 | tickets 按平台存 Cookie；py12306 用户状态恢复 | 本地 Keychain/加密 SQLite 存凭据，**不上云** |
| L2 平台适配 | 登录态探测、余票/号源查询、目标匹配、下单提交 | 每平台一个 adapter | 定义统一 `Adapter` 协议，禁止跨平台 if/else 堆叠 |
| L3 时间/调度 | 开售倒计时、对时、预热、重试退避、并发上限 | py12306 多线程；tickets 自动校时；biliTickerBuy 重试间隔 | 多源时间采样取最小 RTT，本地单调时钟计倒计时 |
| L4 监控 | 轮询间隔、库存 diff、去重、首次命中即停 | 三者皆同构 | 统一 `probe → diff → hit` 流水，事件落 SQLite |
| L5 通知 | 微信/飞书/邮件/TG/钉钉/语音 | py12306 通知矩阵；tickets ClawBot 微信 | 复用本模块 `kernel/handoff` + 既有飞书/企微通道 |
| L6 人机确认与支付 | 支付不托管，人工确认；失败分类与停止条件 | tickets 下单响应不确定时提示核对官方订单 | **默认不实现自动支付**；提交动作要求逐次确认 |
| L7 可观测 | 任务状态、操作日志、截图/录屏、失败归因 | tickets 的 SQLite 操作日志与筛选导出 | 统一 JSON 事件 + 日志，便于复盘与评测 |

---

## 3. 技术路线对比

| 路线 | 速度 | 稳定性 | 风控/ToS 风险 | 工程复杂度 | 适用 |
|---|---|---|---|---|---|
| API 直连（逆向私有接口） | 最高 | 低（接口一变即失效） | **最高** | 中 | 不建议作为默认 |
| 无头浏览器（Playwright 持久化上下文） | 中 | 高 | 中 | 中 | **监控 + 预填 + 跳转**首选 |
| 安卓 adb/模拟器（MCP 封装） | 中 | 中 | 较低 | **最高** | 仅自用、单设备 |
| 半自动（只读监控 + 通知 + 官方深链） | — | 最高 | **最低** | 低 | **默认形态** |

---

## 4. 合规红线（必须写入组件 SKILL 与产品文案）

1. **禁止代抢、转售、加价**：可能触及倒卖有价票证/非法经营，平台亦可民事追责；产品不得提供代抢服务。
2. **禁止绕过验证码、破解风控、代理池对抗封禁**：这类能力不实现、不接入第三方打码服务。
3. **禁止云端多账号批量抢占公共资源**：医疗号源、公共场馆预约尤其敏感；本组件默认**单用户、本地运行**。
4. **敏感个人信息最小化**：证件号、就诊人、观演人信息本地加密存储，不上云、不外传、不进日志。
5. **平台用户协议普遍禁止自动化访问**：默认只做「只读监控 + 官方渠道跳转」；自动提交必须逐次人工确认，并在 SKILL 与商品页明示「非代抢工具，不保证成功」。
6. **许可隔离**：PolyForm Noncommercial 项目的代码不得进入商用产物；MIT/Apache 项目也只借鉴设计，不整段搬运。

---

## 5. 落地建议（待确认后转 SPEC）

### 5.1 组件定义

- 组件名：`reservation-assist`；对外名：**预约助手（余票监控·开售提醒）**
- 目录：`components/reservation-assist/{component.yaml, skill/, tests/, docs/}`
- `family`: `reservation-assist`（需在 `contracts/component.schema.json` 的 `family` 枚举中新增；`build_product.py` 本身按 `products/*.yaml` 驱动，无需改动）
- 运行时依赖：Python 标准库 + 可选 Playwright；复用 `kernel/{headers,endpoint,pay_gate,handoff}`
- 输出契约：`data.v1`（沿用 `contracts/output.schema.json`）

### 5.2 CLI 草案

```
watch add|list|rm      # 监控任务（平台、目标、时间窗、轮询间隔）
watch run              # 常驻运行（launchd / 前台）
notify test            # 通知通道自检
doctor                 # 环境自检：浏览器、时区、网络、登录态
report                 # 当日任务与命中记录（data.v1）
```

### 5.3 Adapter 协议（默认只读）

```
login_state() -> 已登录/失效/未知
probe(target) -> 余票/号源快照（只读）
matches(snapshot, rule) -> [命中项]
notify(hit) -> 通道投递
handoff(hit) -> 官方页面深链（默认动作）
submit(hit) -> 可选，需显式开启且逐次人工确认
```

### 5.4 分阶段

| 阶段 | 范围 | 合规等级 |
|---|---|---|
| P0 | 只读监控 + 通知：12306 余票/候补提醒 + 1 个演出平台（大麦或 B站） | 低风险 |
| P1 | 半自动：预填观演人/就诊人 + 一键跳官方页面 + 任务复盘 | 中低 |
| P2 | 可选自动提交（本地、单账号、逐次确认），默认关闭 | 中，需单独评审 |

### 5.5 商品形态（初步）

- 免费版：1 个监控任务、基础通知
- Pro：多任务/多平台、历史命中复盘、自定义轮询节奏（受平台限速约束）

---

## 6. 未决问题（需用户拍板）

1. 功能边界：只读监控提醒 / 监控+半自动辅助（预填、跳转） / 允许自动提交（默认关闭）
2. 首批平台：12306、演出票（大麦/B站/猫眼）、医疗预约、政务/签证类预约，优先级如何排
3. 载体形态：本地 CLI + launchd 守护 / 桌面 GUI / 两者（先 CLI 后 GUI）
4. 是否作为 SkillHub 商品对外发布（决定许可隔离强度与免责声明措辞）

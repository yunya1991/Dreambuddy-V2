# REVIEW — SPEC-预约助手 reservation-assist v0.1

> **评审日期**: 2026-11-20
> **评审对象**: [SPEC-20261120-预约助手-reservation-assist-v0.1.md](./SPEC-20261120-预约助手-reservation-assist-v0.1.md)
> **方法**: 三视角独立评审（架构与契约 / 合规与法律 / 工程可行性）+ 主审合并去重
> **结论**: **修改后接受**。架构方向成立，但当前版本有 8 项阻断，直接开工会在 `make check`、对时、提交门禁三处返工。

---

## 一、评审摘要

| 视角 | 结论 | 阻断 | 重要 | 次要 |
|---|---|---|---|---|
| 架构与契约 | 修改后接受 | 4 | 6 | 5 |
| 合规与法律 | 需修改后接受 | 3 | 4 | — |
| 工程可行性 | 有条件可行 | 4 | 7 | — |
| **合并去重后** | **修改后接受** | **8** | **10** | **6** |

**一句话结论**：分层设计与适配器隔离方向正确；问题集中在「验收闸门没对齐、对时与节拍不可行、提交门禁只是开关不是不变量、医疗/政务口径自相矛盾」四处，全部可在 SPEC 层修完，不需要推翻架构。

---

## 二、阻断项（写代码前必须修 SPEC）

| ID | 位置 | 问题 | 证据 | 修复建议 |
|---|---|---|---|---|
| R-01 | §12 A1 | 新增组件必然挂 G6：必须有 `tests/golden/*.json` 且通过 `data.v1` 的 9 个必填字段校验；SPEC 的 tests 布局没有 golden | [check_boundaries.py#L349-L381](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/tools/check_boundaries.py#L349-L381)、[output.schema.json#L8-L18](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/contracts/output.schema.json#L8-L18) | 二选一：①新增 `reservation.v1` profile（推荐，语义最贴切）；②产出符合 `data.v1` 的 `tests/golden/report.json`。同时把 A1 改为逐条列出将要跑的闸门 |
| R-02 | §4 注释、§11 | 未声明 `component.yaml` 的 8 个必填字段；未声明 `contracts/redlines.md` R1/R4/R5/R10 对内部组件是否适用。R5 要求数据源在 `data-sources.yaml` 登记，平台页面显然未登记 | [component.schema.json#L8-L34](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/contracts/component.schema.json#L8-L34)、[redlines.md#L44-L50](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/contracts/redlines.md#L44-L50) | SPEC 增加「契约适用域」小节：逐条写 R1/R2/R3/R4/R5/R10 的适用/豁免与理由；豁免必须写进 SKILL，不能只写在 SPEC |
| R-03 | §4 | `tests/` 缺 `test_privacy.py`（§9 与 A6 引用）；缺新增组件后的 `gen_index --write` 与 INDEX 重生成步骤；组件级 `docs/` 缺失（cogsteward 先例在 `component.yaml.docs` 登记） | [cogsteward/component.yaml#L17-L22](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/components/cogsteward/component.yaml#L17-L22) | 目录补齐 `tests/test_privacy.py`、`docs/`；P0 交付明确「建 component.yaml → gen_index --write → make check」顺序 |
| R-04 | §6 | Adapter 协议缺 `transport` 注入、分页/多目标、超时与异常语义、`SubmitResult` 字段、fixture 回放契约；`performance.py` 单文件装 3 个平台，与「新增平台=新增一个文件」和 `--adapter <name>` 冲突 | SPEC §6 | 平台拆为 `damai / bilibili / maoyan / railway / medical / gov`；`base.py` 定义 Protocol + `NAME` 注册表 + 错误类型 + `FixtureCase`；`probe(target, transport)` 强制注入 |
| R-05 | §7 | 对时方案不可行：macOS `sntp -s`/`systemsetup` 需 root/admin；HTTP `Date` 只有秒级精度；「偏差>500ms 拒绝冲刺」会变成永久拒绝 | 工程视角实测 | 主源改为平台 ms 级 `serverTime`（3 次一致且 RTT≤300ms 才采信）；用虚拟时钟 `t_v = now + offset` 倒计时；仅在置信区间 >1.5s 时降级为盲轮询+告警，禁止无限期拒绝 |
| R-06 | §7 | 单一下限 300ms 不现实：Playwright 单次 goto+抽取典型 800–2500ms；对 12306/医院/政务做 300ms 轮询有干扰风险 | 工程视角实测 | 拆两档并写进适配器元数据：API 探测默认 1000ms / 下限 500ms；浏览器探测默认 5000ms / 下限 3000ms；`--unsafe-interval` 只对演出票生效；railway≥1500ms、medical≥3000ms、gov≥5000ms |
| R-07 | §8 | 「自动提交」门禁是开关不是不变量：`RA_ALLOW_SUBMIT=1` 写进 plist 后长期有效；`--i-understand-risk` 写进 plist 即永久确认，自动提交路径无人在环 | 合规视角 | 改为**一次性 grant**：`ra watch grant <task_id>` 在 tty 内签发，绑定任务+目标指纹，有效期 ≤2h 并存库；env 只能否决不能授权；launchd 非交互路径一律 `GateDenied` |
| R-08 | §6 vs §10.4/§13 | 医疗/政务口径矛盾：§2.2 与 §10.4 说只监控，§6 与 §13 又说「提交需逐次确认」「自动提交门禁接入」 | SPEC 内部 | 在代码里写死白名单 `submit_supported = {performance: True, railway: False, medical: False, gov: False}`，非白名单抛 `GateDenied`，环境变量与配置均不可覆盖；同时修正 §6 表格与 §13 |

---

## 三、重要项（应在 P0/P1 修）

| ID | 位置 | 问题 | 修复建议 |
|---|---|---|---|
| I-01 | §2.1 G2 | 「内核 0 处平台分支」无法机器判定 | 新增 `tests/test_architecture.py`：扫描 `scripts/`（排除 `adapters/`）平台词表；适配器由注册表驱动，缺协议或 fixture 即失败 |
| I-02 | §11 | `ra report --json` 只说符合 `data.v1`，没给字段映射；`doctor --json` 外壳未定 | 若采用 `reservation.v1`，给出 required 字段与 golden；`doctor --json` 复用同一 profile |
| I-03 | §8 | 提交幂等缺状态支撑：超时/风控页如何判定「未提交」与「已提交但响应丢失」 | 三态 `sent → ok / unknown`；超时、5xx、风控页一律 `unknown`；恢复时只读官方订单对账，`ra reconcile` 人工关闭；仅明确业务错误码可重试 1 次 |
| I-04 | §5、§9 | 存储设计缺 DDL、去重指纹、并发参数、留存期限 | 指纹 = `sha256(adapter|target_id|date|session|price_tier)`（date 按 Asia/Shanghai 归一）；`UNIQUE(task_id, fingerprint)`；`WAL + busy_timeout=5000 + synchronous=NORMAL`；hits 30d / events 90d，`secure_delete=ON` |
| I-05 | §5/§8 | 终态「创建订单/占座」边界不清 | 终态改为「停在官方下单页并回填目标」；禁止锁座/占座接口，加负向断言测试 |
| I-06 | §2.1 G6 | 「运行期 0 外网请求」与真实通知通道冲突 | 措辞改为「测试期 0 外网」；定义 `Channel` 协议 + `FakeNotifier`，断言 `len(calls)==1` |
| I-07 | §8 | 未定「云端/容器」判定口径 | 列明判定项（`/.dockerenv`、云厂商元数据 IP、环境变量白名单）并加负向测试 |
| I-08 | §7 | 未处理 Mac 休眠唤醒、时钟步进、开售改期 | 目标存 epoch；每 tick 比对 `Δwall − Δmono`，>5s 判为唤醒 → 立即重对时；`rule.recheck_every=600s` |
| I-09 | §9 | Keychain 在 launchd 会话可能弹 GUI 授权；AES 兜底与「口令不落盘」矛盾 | 只用 `security add-generic-password -U` 创建；`doctor` 用 `timeout 3` 自检，失败则禁用 submit 而非降级明文；删除 AES 兜底 |
| I-10 | §10.5 | 一次性勾选不足以覆盖敏感个人信息场景，且无留证 | consent 落库（版本+哈希+时间+任务指纹）；首次运行打印完整披露；医疗/政务逐任务确认、7d 失效 |

**次要项**：退出码与 `missing[].code` 对齐；`family` 与组件同名是否成族；时间窗跨日/DST；fixtures 体积与 `.gitignore`；日志轮转（5MB×3）与解释器绝对路径（3.12）。

---

## 四、主审裁定（三视角分歧）

| 分歧 | 裁定 | 理由 |
|---|---|---|
| 合规视角主张「医疗/政务/12306 自动提交应直接禁止」，与用户 D1「允许自动提交」冲突 | **保留能力，但代码硬白名单只开 `performance`**；其余三类恒 `GateDenied` | 既满足 D1 的可用性，又把公共资源类风险关进代码而非文档 |
| 工程视角主张「演出票自动提交可行性高估，全部改低」 | **接受降级**：B站/大麦/猫眼标注为「低（仅提醒+预填+跳转）」；自动提交列为 P3 实验能力，不作为首批验收 | 登录态寿命、滑块、设备绑定未验证，不能写进 P1 承诺 |
| 架构视角建议直接复用 `data.v1` | **不采纳，新增 `reservation.v1`** | `data.v1` 的 `sources.license`、`method_ids` 语义是行情/事件数据，套在预约任务上会逼出假字段 |

---

## 五、SPEC v0.2 修订清单

1. §2.1 目标 G2/G6 改写为可机器判定；新增 G7「测试期零外网 + 真实通道可注入」
2. §4 目录：补 `docs/`、`tests/test_privacy.py`、`tests/golden/report.json`、适配器拆分为 6 个文件
3. §4 新增「契约适用域」小节（R1/R2/R3/R4/R5/R10 逐条适用或豁免）
4. §6 重写 Adapter 协议（transport 注入、错误类型、fixture 契约、注册表）；平台可行性全部下调
5. §7 重写对时与节拍：虚拟时钟、ms 级时间源、两档间隔、平台最低间隔、休眠唤醒处理
6. §8 重写提交门禁：grant 机制、硬白名单、删除非交互确认、`unknown` 三态与 `reconcile`
7. §9 补 DDL/指纹/TTL/Keychain 自检/备份排除
8. §11 新增 `reservation.v1` profile 与字段映射；`doctor --json` 同 profile
9. §12 验收改写：A3 拆 A3a/A3b；新增 A8 时钟跳变、A9 架构词表扫描
10. §13 阶段调整：P1 只做只读监控；自动提交整体后移到 P3

---

## 六、需要用户拍板（修订前）

1. **自动提交范围**：接受「仅演出票可自动提交，12306/医疗/政务恒拒绝」吗？
2. **确认方式**：接受取消 `--i-understand-risk`，改为 tty 内一次性 grant（≤2h，绑任务+目标）吗？这意味着 launchd 无人值守时永不自动提交。
3. **报告契约**：接受新增 `reservation.v1` profile（而非复用 `data.v1`）吗？需要同时改 `contracts/output.schema.json`。

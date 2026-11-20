# PLAN — SkillHub 评测优化与本地沙箱测试（v0.1）

> **状态**: Phase 1–4 已完成（沙箱 16/16 通过）；Phase 5 待打包发版与平台复测
> **日期**: 2026-11-20
> **评测来源**: https://skillhub.cn/dashboard → 各 Skill「评测报告」（作者可见版）
> **范围**: `market-data-pro`、`event-context-pro`、`cogsteward-pro`（SkillHub 已上线的三个付费/专业版）
> **沙箱落点**: `59-通用组件管理/platform/sandbox/`（新建，不改现有 Skill 包）

---

## 1. 评测结论汇总

| Skill | 线上版本 | 评测时间 | 总分 | T 可信任 | R 可靠性 | A 适用性 | C 规范性 | E 有效性 |
|---|---|---|---|---|---|---|---|---|
| market-data-pro | 1.0.1 | 2026/11/20 01:15 | **4.4** / 优秀 | 4.5 | 4.3 | 4.9 | 4.0 | 4.4 |
| cogsteward-pro | 1.0.0 | 2026/11/20 01:45 | **4.5** / 优秀 | 4.9 | 4.0 | 4.8 | 4.5 | 4.4 |
| event-context-pro | 1.0.0 | 2026/11/20 01:45 | **4.5** / 优秀 | 4.8 | 4.3 | 4.9 | 4.0 | 4.3 |

补充事实：

- `cogsteward`（免费版，线上 0.5.0）**暂无评测报告**；本地已是 0.7.0，未重新发版。
- 三个包的安全性扫描均为 **5.0（双实验室交叉验证，无 P0/P1）**，不是优化重点。
- 三项最低子分集中在 **C·反模式与FAQ（3.3 / 3.5 / 3.5）**，其次为 **R·异常处理（4.0–4.3）**、**C·文档质量（3.5 / 3.8）**。

---

## 2. 问题清单（按评测子项 → 代码证据 → 动作）

### 2.1 共性 P0：断网 / 超时直接抛栈

**证据**：三个付费客户端 `pay.py` 同一写法，只捕获 `HTTPError`：

```python
try:
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    ...
```

`URLError`（断网/DNS）、`socket.timeout`、`ssl.SSLError`、200 但非 JSON 的 `json.JSONDecodeError` 均未处理 → 用户看到 Python traceback。

**对应评测**：R·异常处理 4.0–4.3「断网或超时可能直接失败」；R·运行稳定性 4.0「重复操作没有自动恢复」。

**动作（P0-B）**：
1. 统一异常映射：`E_NET` / `E_TIMEOUT` / `E_SSL` / `E_HTTP_<code>` / `E_JSON`，中文一句话 + 下一步动作，退出码沿用 0/1/2。
2. 有限重试：仅对幂等场景重试——**无 proof 的首次调用会产生新订单，不可自动重试**；**带 proof 的重试是幂等的**（服务端 `already_fulfilled`），可重试 2 次、指数退避。
3. 新增 `--timeout`（默认 60s）与 `--retries`；`--retries` 对无 proof 调用强制为 0 并给出说明。

### 2.2 共性 P0：参数被静默吞掉

**证据**：`market-data-pro/scripts/pay.py` 与 event-context-pro 同构：

```python
args, extra = p.parse_known_args(argv)
...
if key and key in COMMANDS[args.cmd]:
    params[key] = token
```

后果：
- `--seris DGS10`（拼错）→ 参数直接丢弃，服务端按空参数返回，用户以为是数据问题；
- `--cmd macro` 不带 `--series` → 本地不校验，白跑一次 402；
- **`--latest` 是布尔开关，但解析器按「键 + 下一个 token 作为值」读取**，命令末尾的 `--latest` 没有值 → 被丢弃。这正是评测 E·输出准确性 4.5 指出的「最新事件示例无法真正生效」，也是 event-context-pro「开箱即用度 4.0」的直接原因。

**对应评测**：R·功能完善性 4.5「参数写法单一，写错时不一定及时提醒」；event-context-pro「最新事件示例写法有误，查询条件未生效」。

**动作（P0-C）**：
1. 改为 `add_argument` 显式声明每个 cmd 的参数（含类型、互斥、必填），未知参数由 argparse 直接报错；
2. `--latest` 改为 `store_true` 布尔标志；
3. 本地校验规则：
   - `events` 必填 `subject`；
   - `event-context` 必须 `subject` 或 `event-id` 之一，且 `--latest` 与二者互斥；
   - `--since` / `--limit` / `--blocks` 为正整数；`--types` 白名单校验；
   - 校验失败退出码固定（建议 1）且**不发网络请求**。
4. 校验错误文案带「正确写法示例」。

### 2.3 共性 P0：支付履约路径不完整

**证据**：服务端 402 响应体只有 `out_trade_no / amount / currency / goods_name / resource_id / pay_before`（`app.js`），**没有支付链接或二维码**；客户端只打印金额、订单号、截止时间。

**对应评测**：E·内容完整度 4.0「从收到付款提示到最终完成付款的步骤还不够完整」；cogsteward-pro「支付凭证从哪里获得仍不够清楚」；开箱即用度 4.0–4.3。

**动作（P0-A）**：
1. 402 时解析并展示 `Payment-Needed`（base64url 签名账单）中的 `goods_name / resource_id / seller`，明确「付什么、付给谁、付多少」；
2. 打印**可复制的三条获取凭证路径**：① Agent/支付宝按量付费凭据；② 平台订单页；③ 已完成支付后从服务端回调/邮件取 proof；
3. 新增 `--describe`（只读打印本次将发送的 payload，不联网）与 `--status`（按 `out_trade_no` 查订单状态，若服务端无该接口则先列为待补依赖，README 标注）；
4. 502（`FULFILLMENT_CONFIRM_FAILED` / `VERIFY_UPSTREAM_ERROR`）文案明确「结果可能已生成，请用同一 proof 重试，不会重复扣费」。

### 2.4 规范性 P1：零返回样例 + 零 FAQ

**证据**：三个 SKILL.md 均无成功返回样例；`market-data-pro` 的「支持的命令」表还漏了代码里已实现的 `context` 命令（`COMMANDS` 五项，文档只写四项）。

**对应评测**：C·反模式与FAQ 3.3–3.5（三项最低）、C·文档质量 3.5–3.8。

**动作（P1-D）**：
1. 每包新增 `references/examples.md`（成功返回脱敏样例 + 字段解释）与 `references/faq.md`（常见错误表：402 / 凭证过期 / 502 / 断网 / 重复扣费 / 参数错误 / 数据不可用）；
2. SKILL.md 主文只保留触发、命令、一条示例，深度内容外链 → 同时改善「渐进式披露」与「内容集中在一页」的扣分；
3. 补齐 `context` 命令文档，或从代码中移除（二选一，禁止继续不一致）。

### 2.5 认知管家 P1：输入不校验 +「缺测填 0」与承诺矛盾

**证据**：`report.py` 直接信任 `--metrics`：

- 未知 key 静默忽略（拼错 `broken_link` → 不报错、不减分）；
- 值为字符串/负数/`null` 时不校验，`value >= high_at` 可能直接抛 `TypeError`；
- `findings` 只输出前 3 条（`findings[:3]`），其余只给总数。

**承诺矛盾**：SKILL.md 声明「未采集的指标标记为 unavailable」，但只有 `orphan_files` 有 `coverage` 机制；`index_drift / stale_sessions / pending_backlog` 却被要求「无法确定时填 0」→ 缺测被当成健康项，评分虚高。这正是评测「少数安全承诺和实际表现并不完全一致」与「数据检查不够完善」的来源。

**动作（P1-E）**：
1. 按 `metrics-contract.json` 做 schema 校验：类型、非负、未知 key 警告；
2. 缺测统一走 `coverage.<metric>="unavailable"`，不参与评分（与 orphan 一致），把「填 0」从文档删除；
3. 新增 `--format json` 与全量 `findings`（`--top N` 控制展示条数）；
4. 明确「按次版上传、订阅版本地」的差异，避免安全承诺被跨包误读。

### 2.6 版本 / 命名治理 P1

| 问题 | 证据 | 动作 |
|---|---|---|
| market-data-pro 版本漂移 | SKILL.md 写 1.0.2，INDEX 与线上均 1.0.1 | 发版时统一三处；或回退本地版本号 |
| cogsteward-pro 线上落后 | 本地 1.1.0，线上 V1.0.0 | 重新打包发版 |
| 按次版与订阅版**同名** | 两包 frontmatter 均为 `name: cogsteward-pro` | 按次版改 `name: cogsteward-pro-pay`，并加安装互斥说明（该重名本身就会触发自家 `skill_conflicts` 指标） |
| 免费版未评测 | 线上 0.5.0，本地 0.7.0 | 发 0.7.0 后触发重新评测 |

---

## 3. 本地沙箱测试环境（59 内构建）

### 3.1 设计原则

1. **协议同源**：Mock 服务按 `platform/services/skillhub-audit-api` 的真实契约实现（402 body 字段、`Payment-Needed` 头、400/413/502 形状、`already_fulfilled`），不自造协议。
2. **零侵入**：不改 Skill 包；沙箱通过既有环境变量把客户端指向本地：`MDP_ENDPOINT` / `ECP_ENDPOINT` / `COGSTEWARD_ENDPOINT`。
3. **样本来自真实环境**：fixtures 从云端 `49.233.123.96` 的订单库 `service_result` 导出脱敏副本（只读，不新增订单），保证返回结构与线上一致。
4. **故障可注入**：断网、超时、502、非法 JSON、慢响应，全部由 mock 开关控制。

### 3.2 目录结构

```
platform/sandbox/
├── README.md                  # 运行方式与场景说明
├── mock/paid_api.py           # 复刻 402/验付/200/400/413/502/延迟/断连
├── fixtures/
│   ├── macro.json  quotes.json  filings.json  onchain.json  context.json
│   ├── events.json  event-context.json
│   └── cogsteward_report.json
├── cases/cases.json           # 场景矩阵：argv / env / 注入 / 期望退出码 / 断言
├── run_cases.py               # 起 mock → 逐案例执行 → 断言 → 汇总
├── BASELINE-20261120.md       # 优化前基线（6/16 通过）
└── workspace_fixture/         # 认知管家采集样本：断链 / 孤儿 / 重名 / 行号越界 / 漂移
    ├── INDEX.md
    ├── docs/broken.md
    ├── skills/a/SKILL.md
    ├── skills/b/SKILL.md      # 与 a 同名、triggers 重叠
    └── src/no_doc.py
```

### 3.3 场景矩阵（验收基线）

| # | 场景 | 注入方式 | 期望 |
|---|---|---|---|
| 1 | 首次调用 | 无 proof | 退出码 2；输出金额/订单/截止/资源名；**无 traceback** |
| 2 | 正确凭证 | `Payment-Proof: sbx-ok` | 退出码 0；返回含 `rows/missing/data_date/sources/method_ids` |
| 3 | 重复凭证 | 同一 proof 二次 | 退出码 0；提示「幂等重放，未重复扣费」 |
| 4 | 凭证无效/过期 | `sbx-invalid` | 退出码 2；中文提示 + 重新获取凭证指引 |
| 5 | 断网 | mock 端口关闭 | 退出码 1；`E_NET` 提示；无 traceback |
| 6 | 超时 | mock 延迟 > `--timeout` | 退出码 1；`E_TIMEOUT` 提示 |
| 7 | 服务 502 | mock 返回 502 | 退出码 1；提示「同一 proof 重试不重复扣费」 |
| 8 | 非法 JSON 200 | mock 返回 `<html>` | 退出码 1；`E_JSON` 提示 |
| 9 | 参数缺失 | `--cmd macro` 无 `--series` | 退出码 1；本地拦截，**零请求** |
| 10 | 参数拼错 | `--seris DGS10` | 退出码 1；argparse 报错并给正确写法 |
| 11 | `--latest` | `event-context --subject AAPL --latest` | 请求体含 `latest=true`（当前为丢失） |
| 12 | 认知管家正常 | 合法 9 指标 | 等级/评分/占比与契约一致 |
| 13 | 认知管家未知 key | 拼错指标名 | 警告并指出未知 key |
| 14 | 认知管家缺测 | 省略 3 项 | 三项标 `unavailable`，不参与评分 |
| 15 | 工作区样本采集 | `workspace_fixture/` | 断链 1 / 重名 1 / 孤儿 ≥1，等级符合预期 |

执行：`python3 platform/sandbox/run_cases.py --suite market-data-pro`，输出通过/失败计数与非零退出。
**基线先行**：先对当前代码跑一遍，把场景 1/5/6/9/10/11/13/14 的失败固化为「优化前证据」，再进入实现。

### 3.4 与真实环境的对应关系

| 沙箱要素 | 真实环境来源 |
|---|---|
| 402 / 验付 / 履约确认 | `platform/services/skillhub-audit-api/src/app.js` + `alipay.js` |
| 数据返回结构 | 云端订单表 `service_result` 脱敏导出 |
| 认知管家契约 | `components/cogsteward/variants/pro/references/metrics-contract.json`（三端逐字节一致） |
| 端点覆盖 | 各 SKILL 已支持的 `*_ENDPOINT` 环境变量 |

---

## 4. 落地阶段（本轮只到 Phase 0）

| 阶段 | 内容 | 产出 | 是否改 Skill 代码 |
|---|---|---|---|
| **Phase 0** | 本方案确认 | 本文件 + INDEX 登记 | 否 |
| Phase 1 | 沙箱骨架 + 16 场景基线报告 | `sandbox/` + `BASELINE-20261120.md`（6/16） | 否 |
| Phase 2 | P0-A/B/C：支付闭环、异常映射、参数校验 | 三个 `pay.py` | ✅ 已完成（16/16） |
| Phase 3 | P1-D：examples / faq + SKILL.md 收敛 | `references/*.md` | ✅ 已完成 |
| Phase 4 | P1-E：认知管家校验与 unavailable 口径 | `report.py` + SKILL.md | ✅ 已完成 |
| Phase 5 | 版本/命名治理 → 重新打包发版 → 平台复测 | 版本三处一致 + 复测分项 | 🟡 待发版 |

---

## 5. 验收标准

1. 15 个沙箱场景全部通过，且**任何场景不出现 Python traceback**；
2. 三个付费客户端对 `E_NET / E_TIMEOUT / E_JSON / E_HTTP` 均有中文提示与下一步动作；
3. `--latest` 在请求体中真实生效（请求体断言 `latest=true`）；
4. 每个 SKILL 包含成功返回样例与 ≥6 条 FAQ；
5. 认知管家未知指标 / 缺测指标行为符合契约，评分不再因缺测偏高；
6. 版本号在 SKILL.md / INDEX / 线上三处一致；
7. 平台重测预期：C·反模式与FAQ ≥4.3，R·异常处理 ≥4.5，R·运行稳定性 ≥4.5，总分 ≥4.7。

---

## 6. 风险与边界

- **不改服务端**：`--status` 依赖订单查询接口；若后端不提供，Phase 2 只做「本地打印订单信息 + 重试指引」，不新增端点。
- **重试语义**：无 proof 的 POST 会在服务端创建新订单，禁止自动重试，避免制造脏订单。
- **独立性闸门**：抽公共客户端库会破坏「单包自包含」，本期采用「各包内含同构实现 + 同源测试用例」，不引入跨包 import。
- **评测为 AI 自动检测**：分项分数存在波动，验收以沙箱断言 + 平台复测双重确认。

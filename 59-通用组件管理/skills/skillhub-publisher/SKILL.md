---
name: skillhub-publisher
description: "SkillHub（skillhub.cn）发布交互：先判定免费 Skill 还是 SkillPay 付费 Skill；检查账号/实名/商户入驻/API Token；校验 Skill 包；CLI 发布免费 Skill，网页发布 Pay Skill；跟踪审核、付费预检与失败恢复。用于发布/上架/更新 Skill、上架 SkillPay、查审核状态、处理 401/403/409/429 及付费预检失败。"
slug: dreambuddy-skillhub-publisher
displayName: SkillHub 发布交互
version: 1.1.0
summary: 面向 Agent 的 SkillHub 发布协议：免费走 CLI，付费走 SkillPay 网页流程；先校验、再发布、结果可复核。
license: MIT
allowed-tools: Read, Write, Glob, Grep, Bash
---

# SkillHub 发布交互

## 0. 一句话

**先判定「免费 Skill」还是「Pay Skill」，再选通道：免费走 CLI，付费走 SkillPay 网页向导；付费必须先有真实可用的收费后端，不能只改文案。**

任何「发布成功」都必须有 `skillId/status`、付费预检结果或页面状态作为证据。

---

## 1. 触发与边界

**使用**：
- 发布、上架、更新 Skill 到 SkillHub
- 上架 SkillPay / Pay Skill、配置按次计费
- 查询审核状态、发布记录、详情页链接
- 排查 `command not found: skillhub`、`401`、`403`、`409`、`429`、付费预检 `compliance=fail`
- 生成可发布包（补齐 frontmatter、清理垃圾文件、做预检）

**不使用**：
- 找技能、装技能 → `find-skills`
- 从零设计技能内容 → `skill-creator`
- 企业入驻、合同、发票、分成结算 → 人工流程，不在本技能内代办

---

## 2. 发布类型判定（第一步，禁止跳步）

| 类型 | 适用 | 收费 | 发布通道 | 必需前置 |
|---|---|---|---|---|
| 免费 Skill | 工具、流程、开放能力 | 免费 | CLI 或网页 | 实名 + API Token |
| Pay Skill（个人） | 有真实后端服务的付费能力 | 按次 | **仅网页向导** | SkillPay 个人入驻 + 支付宝 AI 按量付费改造 |
| Pay Skill（企业） | 企业服务、微信生态 | 按次 | **仅网页向导** | 企业认证 + 微信商户号绑定 + 微信 AI 专属卡改造 |

**硬规则**：
1. 用户说「上架 SkillPay / 付费 / 按次收费」时，默认目标是 Pay Skill，**不得用 CLI 发成免费 Skill**。
2. `skillhub publish` 的 payload 不包含价格、计费模式、支付渠道，**CLI 只能发免费 Skill**。
3. Pay Skill 必须有**真实可用的收费后端**（返回 402、验付、履约），不能只在 `SKILL.md` 写支付文案。
4. 付费 Skill **不可降级**为免费；发布前确认定价与模式。

---

## 3. 平台事实（2026-11-19 已核实）

| 项 | 值 |
|---|---|
| 站点 | `https://skillhub.cn` |
| 发布页 | `https://skillhub.cn/dashboard/publish` |
| 商户中心 | `https://skillhub.cn/dashboard/merchant` |
| API Key 管理 | `https://skillhub.cn/dashboard/keys` |
| SkillPay 介绍 | `https://skillhub.cn/skillpay` |
| 官方使用指南 | `https://skillhub.cn/tutorials` |
| 官方 Agent 发布规范 | `https://skillhub.cn/ai/release.md` |
| API Host | `https://api.skillhub.cn` |
| CLI 安装 | `curl -fsSL https://skillhub.cn/install/install.sh \| bash -s -- --cli-only` |
| CLI 实测版本 | `skillhub 2026.8.5`（`verify` 需要较新版本） |
| 凭证文件 | `~/.skillhub/credentials.json`（`user.token`） |
| 免费 Skill 上传限制 | 必须含 `SKILL.md`；最多 200 个文件；总大小 ≤ 10 MB |
| 付费价格 | 平台展示价 0.01–100 元/次；支付宝服务登记价 0.01–50 元/次，三处价格必须一致 |
| 付费审核 | 内容合规 + 安全扫描 + 支付宝/微信付费改造预检 |

### 3.1 账号状态检查（只读）

优先在网页「商户中心」查看；需要脚本判断时读取本地凭证调用 API，**不要把 Token 写进命令行**：

- `GET /api/v1/auth/me` → 登录身份
- `GET /api/v1/aipay/status` → 个人 SkillPay / 支付宝入驻状态；`{"onboarded":true,"status":"onboarded"}` 表示已入驻
- `GET /api/v1/merchant/info` → 企业商户状态；`403 ENTERPRISE_NOT_VERIFIED` 表示企业认证未完成、微信通道不可用

---

## 4. 免费 Skill 发布（CLI 优先）

### 4.1 包结构

- 根目录必须有 `SKILL.md`（大小写不敏感，但统一用大写）
- 允许子目录：`references/`、`scripts/`、`assets/` 等
- 禁止把仓库根目录直接发布；只发技能目录
- 禁止：`.env`、Token、私钥、客户数据、内部绝对路径、交易域私有 schema

### 4.2 Frontmatter（CLI 必填三项）

```yaml
---
slug: your-skill-slug
displayName: 对外展示名称
version: 1.1.0
summary: 一句话简介
description: 较长描述
tags: [tag1, tag2]
license: MIT
homepage: https://example.com
---
```

| 字段 | 要求 |
|---|---|
| `slug` | 全网唯一；小写字母/数字/连字符；**2–128 字符**；不能以连字符开头或结尾 |
| `version` | 合法 SemVer，如 `1.0.0`、`1.2.0-beta.1` |
| `displayName` | 不能为空 |
| `summary` / `description` / `tags` / `license` / `homepage` | 建议填写 |

> SkillHub CLI 只支持简单 `key: value` 与 `key: [a, b]`，不要用多行 `>` / `|` 折叠语法。

### 4.3 包卫生与预检

```bash
find <skill-dir> -type f | wc -l     # ≤200
du -sh <skill-dir>                   # ≤10MB
find <skill-dir> -name '.env*' -o -name '*.pem' -o -name '*.key'

export PATH="$HOME/.local/bin:$PATH"
skillhub publish <skill-dir> --dry-run
# 期望：✓ Dry-run passed: <slug>@<version>
```

CLI 自动排除：`.git`、`.idea`、`.vscode`、`node_modules`、`__pycache__`、`*.pyc`、`.DS_Store`、`Thumbs.db`；软链接跳过。不要依赖自动排除隐藏敏感内容。

### 4.4 登录与发布

```bash
command -v skillhub || \
  curl -fsSL https://skillhub.cn/install/install.sh | bash -s -- --cli-only

skillhub auth whoami     # userId / handle / role
skillhub publish <skill-dir> --changelog "首次发布" --json
```

期望：`status=pending_review`，返回 `skillId`；有 `publicUrl` 就记录。

Token 解析优先级：`--token` > `SKILLHUB_TOKEN` > `~/.skillhub/credentials.json`。**禁止回显 `skillhub auth token`。**

### 4.5 更新

slug 不变，先提升 `SKILL.md` 的 `version`，再发布：

```bash
skillhub publish <skill-dir> --changelog "修复 xxx，新增 yyy" --json
```

---

## 5. Pay Skill 发布（SkillPay，网页向导）

### 5.1 前置门禁（缺一不可）

**个人（支付宝）**：
1. 完成实名认证
2. 完成 SkillPay 个人入驻（商户中心 → SkillPay 个人入驻 → 手机号验证）
3. 开通支付宝「AI 按量付费」收款产品
4. 有可运行的业务 API，且公网 HTTPS 可达
5. 服务已在支付宝注册，拿到 `API_` 开头的 `serviceId`
6. 完成生产部署与线上自测（402 / 验付 / 履约 / 幂等）

**企业（微信）**：
1. 企业认证通过
2. 绑定微信商户号入驻 SkillPay
3. 完成微信支付 AI 专属卡改造
4. 有可运行的业务 API 与云端沙箱验证

> 账号状态用 §3.1 检查。个人入驻已通过 ≠ 已有收费后端；两者要分别确认。

### 5.2 收费后端硬指标

Skill 包只负责「发起请求 + 调官方支付能力 + 展示结果」，**后端源码独立部署，不进 Skill 包**。后端必须实现：

| 指标 | 通过标准 |
|---|---|
| 402 账单 | 未付款返回 HTTP 402 与 `Payment-Needed` 响应头 |
| 凭证重试 | 付款后携 `Payment-Proof` 重试，原请求参数一致 |
| 服务端验付 | 校验凭证与订单；无效/过期不交付资源 |
| 履约确认 | 返回资源后发送履约确认，失败可重试 |
| 订单与幂等 | 订单状态可恢复，不重复扣费或交付 |
| 地址 | 公网 HTTPS；登记地址与实际请求一致 |
| 价格 | 支付宝登记价 = 服务端 402 账单金额 = SkillHub 展示价 |

### 5.3 付费改造预检（发布前）

网页向导会把 `SKILL.md` 提交到预检接口：

```text
POST /api/v1/community/skills/precheck-alipay   (multipart: file=SKILL.md)
```

返回：

- `compliance`: `pass` / `partial` / `fail`
- `missing_features`: 常见为 `402账单下发`、`携带凭证重试`、`验付调用`、`履约确认`、`订单持久化与幂等`

> 预检通过不等于最终审核通过；预检偏关键词与结构检查，**不能替代真实可用的后端服务**。

### 5.4 发布向导步骤

1. 登录 SkillHub →「发布 Skill」→ 选择「发布付费 Skill」
2. 「Pay Skill 改造」：确认支付接入方式、支付确认链路、支付触发标识
3. 「上传基本信息」：上传含 `SKILL.md` 的文件夹或 ZIP；填 Slug、显示名称、版本、描述、分类、图标
4. 「完善计费」：选择按次计费，填单次价格；保持三处价格一致
5. 「验证 & 案例」：完成线上验证，补使用效果案例（可选）
6. 提交 → 内容审核 + 安全扫描 + 付费预检 → 审核通过后上架

**付费模式一旦提交不可降级为免费**，价格与模式需用户明确确认。

### 5.5 网页操作纪律

1. 每步先 `browser_snapshot` 读取表单，不要硬编码 ref / CSS 选择器
2. 上传后核对文件名、文件数与 `SKILL.md` 根层位置
3. 提交前汇总「slug / 名称 / 版本 / 分类 / 免费或付费 / 价格 / 支付渠道」给用户确认
4. 价格、付费模式、公开发布必须用户明确同意
5. 提交后以页面「审核中 / 已通过 / 未通过」为证据
6. 登录墙（手机号 + 短信验证码）交还用户完成

---

## 6. 审核与买家验证

- 审核状态看 `https://skillhub.cn/dashboard` → 我的 Skill，或 `publicUrl`
- **审核期间详情页 404 属正常**，不要重复发布
- Pay Skill 上架后建议做一次买家验证：安装上架版本 → 触发 → 核对价格 → 付款 → 收到结果 → 卖家查到交易
- 图标、分类、付费计费、案例只能网页配置；CLI 发布不会上传图标

---

## 7. 错误与恢复

| 现象 | 原因 | 处理 |
|---|---|---|
| `command not found: skillhub` | PATH 未加载 | `export PATH="$HOME/.local/bin:$PATH"` |
| 401 / `invalid api key` | Token 失效 | 到 `/dashboard/keys` 重建并重新登录 |
| 403 / 请先完成实名认证 | 未实名 | 完成实名认证 |
| 403 `ENTERPRISE_NOT_VERIFIED` | 企业认证未完成 | 走个人支付宝通道，或完成企业认证 |
| `MERCHANT_NOT_BOUND` | 收款渠道未绑定 | 商户中心完成支付宝/微信绑定 |
| 409 / slug 冲突 | slug 被占用 | 换成全网唯一 slug；不要抢注 |
| 429 / 请求过于频繁 | 限频 | 按 `retryAfter` 等待后重试 |
| 400 / 请求失败 (code=...) | frontmatter 或 payload 不合法 | 先 `--dry-run`，再核对字段 |
| 发布后详情页 404 | 审核未完成 | 等审核，不要重复发布 |
| `compliance=fail` | 付费改造缺失 | 按 `missing_features` 补真实后端能力，不要只加文案 |
| 定价未生效 | 支付宝定价未写入 | 网页重新设置价格，核对三处一致 |
| 付费选项不可选 | 未完成创作者/商户入驻 | 先到 `/dashboard/merchant` 入驻 |
| 图标/内容审核未通过 | 违规或被拒 | 按通知修改后提升版本重发 |
| 网络超时 | 上传中断 | 先查「我的 Skill」是否已出现该版本，再决定是否重发 |

---

## 8. 安全红线

1. 不打印、不记录、不提交完整 Token；对话中只出现 `skh_***`
2. 不发布含密钥、客户数据、内部路径、私有 schema 的包
3. 不擅自修改价格、付费模式、可见范围
4. 公开提交前必须让用户确认发布摘要
5. 发布超时后先核对状态，再决定是否重发
6. 不代替用户完成实名、人脸核身、商户签约、支付宝/微信开通
7. 不用「只写支付文案」的方式通过付费预检

---

## 9. 输出模板

```text
SkillHub 发布结果
- Skill: <displayName> (<slug>)
- Version: <version>
- 类型: 免费 / Pay Skill（支付宝 / 微信）
- Status: <pending_review / approved / rejected / precheck_fail>
- URL: <publicUrl 或 我的 Skill 页面>
- 证据: dry-run / publish 输出 / precheck 结果 / 页面状态
- 下一步: <等审核 / 补收费后端 / 补图标分类 / 改内容重发>
```

---

## 10. 首次接入清单

- [ ] 手机号注册并登录
- [ ] 完成实名认证
- [ ] `/dashboard/keys` 创建 API key
- [ ] 安装 CLI 并加入 PATH
- [ ] `skillhub login --key ... --host https://api.skillhub.cn`
- [ ] `skillhub auth whoami` 通过
- [ ] 免费发布：`--dry-run` 通过
- [ ] 付费发布：商户入驻 + 收费后端 + 支付宝/微信联调通过 + 预检 `pass`

---

## 11. 本技能自身的发布参数

本技能是**发布工具**，默认按免费 Skill 发布；除非另有真实收费后端，不得标记为 Pay Skill。

```bash
skillhub publish <本目录> --changelog "v1.1.0：补齐 SkillPay 付费发布流程与预检门禁" --dry-run
skillhub publish <本目录> --changelog "v1.1.0：补齐 SkillPay 付费发布流程与预检门禁"
```

- slug：`dreambuddy-skillhub-publisher`
- version：`1.1.0`
- license：`MIT`
- 若 409：改为 `<handle>-skillhub-publisher` 后重发

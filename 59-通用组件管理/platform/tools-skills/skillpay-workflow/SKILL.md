---
name: skillpay-workflow
description: "SkillHub 发布 + 支付宝开放平台运维 + SkillPay 订阅制商品发版的一体化工作流：用封装脚本与固定检查单替代逐条查文档/点网页。skillhub CLI 发免费 Skill；alipay-cli 查应用审核、注册服务、签约；skillhub-audit-api 提供 402 按量付费收款；创作者中心网页新建订阅商品与上传新版本（含四个必查坑）。用于发布/更新 Skill、发新版本、查审核状态、改服务地址、跑 402 冒烟、重启收费后端。"
slug: dreambuddy-skillpay-workflow
displayName: SkillPay 工作流
version: 1.1.0
summary: 三条链路的脚本化入口：SkillHub 发布（CLI）、支付宝运维（alipay-cli）、402 收费后端（audit-api）。
license: MIT
allowed-tools: Read, Write, Bash
---

# SkillPay 工作流

## 0. 一句话

**能用脚本就不要读文档：先跑 `scripts/*.sh <子命令>` 拿状态，再决定动作。**

三条链路：
| 链路 | 入口 | 干什么 |
|---|---|---|
| 发布 | `scripts/skillhub.sh` | 预检、发布免费 Skill、看身份 |
| 平台运维 | `scripts/alipay.sh` | 登录、查审核、注册服务、签约、调 MCP |
| 收费后端 | `scripts/audit.sh` | 健康检查、402 冒烟、隧道地址、重启 |

所有脚本默认输出**单行摘要**，需要细节加 `--json`。

---

## 1. 关键常量（改这里，别改脚本正文）

| 项 | 值 |
|---|---|
| 支付宝 AppID | `2016122204500401` |
| 服务 ID | `API_019D3B514ACE4D53` |
| 商户 PID | `2088612515762353` |
| 单价 | `0.99` 元/次（支付宝登记价、后端 `PRICE_YUAN`、SkillHub 展示价三处一致） |
| 网关 | `https://openapi.alipay.com/gateway.do` |
| 后端 | `49.233.123.96:/opt/skillhub-audit/app`，systemd `skillhub-audit-api`，监听 `127.0.0.1:8788` |

---

## 2. 开工顺序（默认路径）

```bash
cd 59-通用组件管理/platform/tools-skills/skillpay-workflow

# ① 平台侧状态（一条命令看清：登录态 + 应用审核状态）
bash scripts/alipay.sh status

# ② 收费后端是否活着（本地 + 公网 + 402 金额）
bash scripts/audit.sh probe

# ③ 发布免费 Skill（付费 Skill 只能走网页向导，见 §5）
bash scripts/skillhub.sh preflight <skill-dir>
bash scripts/skillhub.sh publish <skill-dir> --changelog "首次发布"
```

---

## 3. alipay-cli 事实（2026-11-19 实测 0.2.0）

- 安装：`curl -fsSL https://opengw.alipay.com/alipaycli/install | bash`（装到 `~/.local/bin/alipay-cli`，带 SHA256 校验）
- 登录：OAuth 设备码；`auth login --non-interactive --json` 拿 `verification_url`，浏览器扫码授权后 `auth login --complete --json` 变 `logged_in`
- **token 有效期仅约 1 小时**，长任务前先 `whoami` 判断
- 业务全走 `mcp call <server>.<tool> -d '<json>' --json`；已确认服务：
  - `apprelease`：应用查询/创建/提审（`queryApplicationInfo`）
  - `a2a-pay-service`：`saveBazaarServiceForMcp` / `discoverBazaarServicesForMcp`
  - `ar-sign`：`previewFormView` / `apply`（签约）
- **CLI 不含 `precreate` / `verify`**，402 收款仍由 `skillhub-audit-api` 调 SDK 完成

---

## 4. 状态语义

| 值 | 含义 | 下一步 |
|---|---|---|
| `status=AUDIT` | 应用审核中（平台承诺 1 天内） | 等；期间可做发布包 |
| `status=ONLINE` | 已上线，可正式调接口 | 跑 §6 真实付款 |
| `isv.not-online-app` | 应用未上线 | 同上，不是密钥问题 |
| `401 / 未登录` | token 过期 | `bash scripts/alipay.sh login` |

---

## 5. 免费 vs 付费（硬规则，不许跳）

1. `skillhub publish` 只能发**免费** Skill；payload 里没有价格和计费模式。
2. 用户说「上架 SkillPay / 收费」→ 默认 Pay Skill，**只能走 SkillHub 网页向导**，且必须已有真实 402 后端。
3. 付费 Skill 不可降级为免费。
4. 价格三处必须一致：支付宝服务登记价 / 后端 `PRICE_YUAN` / SkillHub 展示价。

---

## 6. 验收标准（缺一不算完成）

| 检查 | 命令 | 期望 |
|---|---|---|
| 应用上线 | `bash scripts/alipay.sh status` | `status=ONLINE` |
| 402 冒烟 | `bash scripts/audit.sh probe` | `402` + `amount=0.99` + 有 `payment-needed` 头 |
| 真实付款 | 支付宝 AI 付客户端调用资源 | `200` + `Payment-Validation` |
| 发布结果 | `bash scripts/skillhub.sh publish ...` | `status=pending_review` + `skillId` |

---

## 7. 红线

- 不把私钥、Token、`~/.alipay-cli/credentials`、短信验证码写进仓库或回显
- 不代用户实名/签约/人脸；扫码授权由用户本人完成
- 隧道域名（`*.trycloudflare.com`）重启即变，变了必须同步支付宝服务地址，否则线上收款断

---

## 8. 订阅制商品：新建与发版（创作者中心网页）

> 入口 `https://skillpay.alipay.com/creator/products`。付费商品只能走网页向导，CLI 不管这一段。

### 8.0 三条硬约束（先记住，再动手）

| 约束 | 后果 |
|---|---|
| 买断制 / 订阅制选定后**不可更改** | 选错只能新建商品 |
| 一个商品只能选**一个**订阅周期（每周/每月/每季度） | 月付 ¥19.9 与季付 ¥49.9 无法共存于同一商品，必须拆成两个商品 |
| 平台明示**不支持自动续费** | 到期不会自动扣款，需人工续费；若自建令牌，有效期按「周期 + 缓冲」设计 |

### 8.1 新建商品（七步）

1. 商品管理 → 上架新商品
2. 上传 `.zip`（平台会解析包内 `SKILL.md`）
3. **先填中文商品名**——上传后名称会被 `SKILL.md` 的 `name` 覆盖成英文 slug
4. 商品描述 ≤500 字，禁出现方向/评级/推荐类词
5. 售卖模式选「订阅制」（选定不可改）
6. 价格 2.99–50 元、最多两位小数；免费试用 **≥5 次**
7. **取消「报名参加比赛」的默认勾选** → 提交审核

### 8.2 发新版本（已上架商品）

1. 商品管理 → 目标商品 → 「编辑商品信息」
2. 「Skill 文件」区点垃圾桶删除旧 zip → 上传新 zip
3. 填「版本修改说明」（**必填，≤200 字**，空着提交不生效）
4. 上传新包后商品名会**再次**被重置成英文 slug → 改回中文
5. 提交 → 页面提示「新版本审核中…不影响当前销售商品」

### 8.3 五个必查坑（全部真实踩过）

| # | 坑 | 表现 | 处置 |
|---|---|---|---|
| P1 | 版本修改说明为空 | 点提交没反应/失败 | 必填 ≤200 字，提交前核对字数不为 0 |
| P2 | 商品名被包内 `name` 覆盖 | 从「市场事实日报」变成 `market-facts-daily` | 上传后立即改回中文，提交前再核一次 |
| P3 | 黑客松报名默认勾选 | 不取消等于被报名 | 每次提交前取消 |
| P4 | 版本页 DOM 快照超时 | `product-new?state=version…` 的 document readiness 永不完成，snapshot/evaluate 报 30s 超时 | 新建标签页打开同一 URL 可绕过（已实测）；仍失败则改用截图定位、人工点击 |
| P5 | SkillHub Pay Skill 版本号改不动 | 网页输入框改成 1.0.1，快照又回到 1.0.0；提交报「版本 X 已存在」 | **平台版本号取自 zip 内 SKILL.md 的 `version`**：直接改包内版本号重新打包上传，不要在网页上改（JS 赋值不触发 React 状态） |

### 8.4 状态语义

| 状态 | 含义 | 可购买 |
|---|---|---|
| 销售中 | 已通过审核 | ✅ |
| 审核中 | 首次提交待审 | ❌ 仅自己可见 |
| 新版本审核中 | 新版本待审，旧版本继续卖 | ✅（旧版本） |

审核承诺 1–3 分钟，实测常更久；通过后版本号自动 +1（`v1 → v2`），与包内 `version` 字段是两套编号。

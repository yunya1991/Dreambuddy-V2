# 59 站点（platform/site）

59 通用组件管理的对外站点：产品介绍、Skill 上架体检（免费额度 + 按次付费）、
使用说明、只读管理后台。

> 定位：59 内部的一个交付层目录，**不是**新开的同级模块（不会出现 `60-xxx/`）。
> 依赖的收费/体检能力仍由 `platform/services/skillhub-audit-api` 提供，本目录不重复实现业务逻辑。

## 目录结构

```
platform/site/
├── templates/
│   ├── index.html        产品介绍源
│   ├── trial.html        免费体检源
│   ├── guide.html        使用说明源
│   └── product.html      商品详情页源（一模板渲染全部 p/<family>.html）
├── index.html            产物（模板渲染，带 AUTO-GENERATED 头，勿手改）
├── trial.html            产物
├── guide.html            产物
├── p/<family>.html       商品详情页产物（定位、版本/价格、选择器、变体卡）
├── catalog.yaml          商品展示文案与入口链接（唯一手改源，禁止 version/price）
├── admin.html            只读管理后台（手写，仅 8082 可达）
├── privacy.html          隐私说明（手写，不属模板）
├── assets/
│   ├── style.css
│   ├── site.js           试用逻辑（含 zip 解析）、选择器高亮、报告导出、埋点、后台渲染
│   ├── logo.jpg
│   └── samples/          3 个示例 SKILL.md（合规 / 告警 / 阻断），供样例回归测试
├── data/public.json      公开商品清单（由 build_site 生成，勿手改）
├── data/registry.json    组件登记清单（由脚本生成，勿手改）
├── data/rules.json       公开体检规则摘要（由 tools/sync_rules.py 生成）
├── scripts/build_site.py 模板渲染 + 商品页 + public.json + registry.json（--write / --check）
└── nginx/site.conf       8081 公网站点 + 8082 后台（Basic Auth + 8789 token）
```

> 页面只改 `templates/`；`p/` 与根目录的三页都是构建产物，头部带 `AUTO-GENERATED`
> 注释，手改会被 `--check` 拦下。检查项数量与说明表来自 `data/rules.json`，
> 源头是 `contracts/skill-quality-rules.yaml`，页面不得硬编码「九项 / 9 项 / 七项」。
>
> 商品页的版本与价格只从 `products/*.yaml` + `components/*/component.yaml` 读取；
> `catalog.yaml` 只写文案与链接，出现 `version` / `price` 或未声明键会被 `--check` 判失败。

## 页面与接口

| 路径 | 说明 | 鉴权 |
|---|---|---|
| `/` | 产品介绍 + 下载引流 | 公开（8081） |
| `/trial.html` | 免费体检，`POST /api/trial` | 公开（8081） |
| `/guide.html` | 使用说明 | 公开（8081） |
| `/p/<family>.html` | 商品详情：定位、版本/价格、三问选择器、变体卡 | 公开（8081） |
| `/privacy.html` | 隐私说明 | 公开（8081） |
| `/admin.html` | 只读总览：健康 + 统计 + 组件清单 | 8082：Basic Auth |
| `/data/registry.json` | 组件登记清单 | 8082：Basic Auth |
| `/api/health` | audit-api 健康（8082 反代 `:8789/health` 并注入 token） | 8082：Basic Auth |
| `/api/stats` | 运行统计（30 秒缓存，8082 反代 `:8789/api/stats`） | 8082：Basic Auth |
| `/api/trial` | 免费体检（额度内；阻断项全出 + 前 6 条建议，含 `patch_count`） | 公开（8081） |
| `/api/audit` | 完整报告（HTTP 402 按次付费，含 `patches[]` / `remediation_plan` / `skipped[]`） | 公开（8081，匿名限流） |
| `/api/beacon` | 匿名埋点（JSON ≤2KB，Origin 白名单） | 公开（8081） |

> 8081 显式拒绝 `/admin.html` 与 `/data/`，后台只从 loopback 的 8082 进入；
> 8789 自身还要求 `X-Admin-Token`，形成「Basic Auth + token」双层。

## 本地预览

```bash
cd 59-通用组件管理/platform/site
python3 -m http.server 8099
# 打开 http://127.0.0.1:8099/index.html
# 试用页需要 /api/trial，本地无后端时提交会提示请求失败，属预期
```

## 部署状态（49.233.123.96）

> 2026-11-20 已完成 S0/S1 上线；V10b 运行时验收（8082 未认证 401、8081 后台路径非 200）
> 已在云端通过，外网浏览器确认仍待完成（见「待办」）。

| 项 | 值 |
|---|---|
| 已部署提交 | `2fc59248`（部署克隆 `2c9c5ac`，含 S2 商品页与 patches；2026-11-20 部署，服务端验证通过） |
| SSH | `ubuntu@49.233.123.96`（免密 sudo） |
| 后端目录 | `/opt/skillhub-audit/app`，systemd `skillhub-audit-api`（8788 公开 / 8789 管理） |
| 站点目录 | `/opt/dreambuddy-59-site`（由本目录同步） |
| 入口 | 公网 `http://49.233.123.96:8081`；后台 `127.0.0.1:8082`（Basic Auth） |
| nginx | `/etc/nginx/sites-available/dreambuddy-59-site` → `sites-enabled` |
| 后端 env | `/etc/skillhub-audit/audit.env`（644，含全部下表变量） |
| 部署克隆 | `/home/ubuntu/deploy-src/dreambuddy`（GitHub 抖动时停在 `26b41bd`，恢复后 `fetch + merge --ff-only` 即可） |
| 备份 | `/home/ubuntu/deploy-backups/` |
| token | `/root/.59-admin-token`（ADMIN_TOKEN，勿打印内容） |
| 后台口令 | 用户名 `59admin`，密码见 `/root/59-admin-credentials.txt`；htpasswd `/etc/nginx/.htpasswd-59site` |

`nginx/site.conf` 仓库内仍保留 `REPLACE_WITH_ADMIN_TOKEN` 占位符；**线上文件已替换为真实
token**，不要用仓库版本直接覆盖线上配置。轮换 token 时：

```bash
# 1) 生成新 token 并写入 env
ssh ubuntu@49.233.123.96 'sudo sh -c "openssl rand -hex 32 > /root/.59-admin-token"'
# 2) 用新 token 替换线上 site.conf 两处占位值，再校验并 reload
ssh ubuntu@49.233.123.96 'sudo sed -i "s/X-Admin-Token \"[^\"]*\"/X-Admin-Token \"$(sudo cat /root/.59-admin-token)\"/g" \
  /etc/nginx/sites-available/dreambuddy-59-site && sudo nginx -t && sudo systemctl reload nginx'
# 3) 更新 audit.env 的 ADMIN_TOKEN 并重启后端
ssh ubuntu@49.233.123.96 'sudo sed -i "s/^ADMIN_TOKEN=.*/ADMIN_TOKEN=$(sudo cat /root/.59-admin-token)/" /etc/skillhub-audit/audit.env \
  && sudo systemctl restart skillhub-audit-api'
```

日常发布：

```bash
# 站点（静态产物，不带动源码依赖；先把 templates 渲染成产物）
rsync -av --delete 59-通用组件管理/platform/site/ \
  ubuntu@49.233.123.96:/opt/dreambuddy-59-site/

# 后端（GitHub 为中转：本地 push → 云端克隆 pull → 重启）
ssh ubuntu@49.233.123.96 'cd /home/ubuntu/deploy-src/dreambuddy \
  && git fetch --depth 2 origin main && git merge --ff-only origin/main \
  && sudo systemctl restart skillhub-audit-api'
```

回滚：站点用上一次 `/opt/dreambuddy-59-site` 备份覆盖；后端 `git revert` 后按上面的
「后端」流程重新 pull + 重启；数据库新增表对旧代码无影响（SPEC §7）。

**待办（TLS）**

- 外网 `http://49.233.123.96:8081` 已于 2026-11-20 放行并复核：四页 + 4 个 `p/` 详情页 200，
  `/data/`、`/admin.html` 404，trial 参数校验 400、`/api/audit` 402（带 `Payment-Needed`）、
  beacon 同源 204 / 异源 403；8082、8789 公网仍不可达。
- `8082` 只能走 SSH 隧道：`ssh -L 8082:127.0.0.1:8082 ubuntu@49.233.123.96`。
- 公网正式启用前必须切 HTTPS（SPEC §5.7），本轮未执行。

## 环境变量（audit-api）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_PATH` | `/var/lib/skillhub-audit/orders.db` | SQLite 路径（额度、订单） |
| `TRIAL_DAILY_QUOTA` | `5` | 每日每网段额度；`<=0` 关闭 |
| `TRIAL_IP_SALT` | 无 | 启用体检时必填，≥16 字符 |
| `TRIAL_GLOBAL_DAILY` | `200` | 全站每日上限 |
| `ANON_RATE_LIMIT` | `20` | 匿名调用/小时/IP |
| `ADMIN_PORT` | `8789` | 管理监听端口（仅 loopback） |
| `ADMIN_TOKEN` | 无 | 未设置则不启动管理监听 |
| `SITE_ORIGIN` | 无 | 埋点主 Origin，如 `https://59.example.com` |
| `SITE_ORIGIN_ALLOW` | `http://127.0.0.1:8099` | 逗号分隔的额外 Origin |
| `BEACON_LOG_PATH` | DB 同目录 `events.jsonl` | 埋点 JSONL |
| `PUBLIC_JSON_PATH` | 无 | 可选，用于 stats 读取站点构建时间 |

## 免费额度接口（audit-api 新增）

`POST /api/trial`

```json
{ "skill_md": "---\nname: demo\n---\n...", "files": [{ "path": "SKILL.md", "size": 123 }] }
```

- 额度：默认每日每网段 5 次（`TRIAL_DAILY_QUOTA`，`0` 表示关闭该路由），全站每日 200 次（`TRIAL_GLOBAL_DAILY`）。
- 计数持久化在 SQLite 的 `trial_usage(ip_hash, day, count)`，重启不恢复；自然日固定 UTC+8。
- IP 只信 nginx 注入的 `X-Real-IP`（不解析可伪造的 `X-Forwarded-For`），落库前做 `sha256(IP + TRIAL_IP_SALT)` 取前 16 字节；IPv6 按 `/64` 归并。启用体检时 `TRIAL_IP_SALT` 必填且 ≥16 字符，否则服务启动失败。
- 超出额度返回 `429 { code: "TRIAL_QUOTA_EXCEEDED", remaining: 0, daily_quota, retry_after, scope }` 并带 `Retry-After` 头；`retry_after` 按下一个 UTC+8 零点计算。
- 全局上限由单事务 `db.transaction(...).immediate()` 原子判定，并写入 `trial_global_cap` 埋点。
- 返回内容为完整报告的结构化裁剪版：全部阻断项 + 前 6 条建议（不足用通过项补足）+ `patch_count`；
  `patches[]`、完整 `remediation_plan` 与 `skipped[]` 明细只在付费 `/api/audit` 报告中出现。
- 前端支持「复制报告」（Markdown 摘要）与「下载 JSON」，导出在浏览器本地完成，服务端不存储报告。
- 本地调试：`TRIAL_DAILY_QUOTA=0` 可关闭；本地无 `X-Real-IP` 时按 socket 地址计数。

## 管理后台与限流

- `ADMIN_TOKEN` 未设置时，8789 管理监听不启动；`ADMIN_PORT` 默认 8789，仅绑定 `127.0.0.1`。
- 8082 反代时必须把 `site.conf` 中的 `REPLACE_WITH_ADMIN_TOKEN` 改成与 `audit.env` 一致的值。
- 匿名调用 `/api/audit`、`/api/data`、`/api/cogsteward` 共享 20 次/小时/IP 内存滑窗（`ANON_RATE_LIMIT`），返回 `429 RATE_LIMITED`；带 `Payment-Proof` 不限流。该限流依赖单实例部署。
- `/health` 返回 `rules_version / score_formula_version / rate_limit_mode`，不再返回订单统计。

## 埋点与隐私

- `site.js` 通过 `navigator.sendBeacon` 上报 `page_view / trial_submit / trial_success / cta_skillhub / guide_view`；服务端补 `trial_quota_exceeded / trial_global_cap`。
- 服务端只写白名单字段 `{event, page, ref_host, ts, rules_version, rules_changed}`，不记 IP/UA/正文；JSONL 默认与数据库同目录（`BEACON_LOG_PATH` 可覆盖），保留 30 天。
- `Origin/Referer` 必须匹配 `SITE_ORIGIN` 或 `SITE_ORIGIN_ALLOW`（默认含 `http://127.0.0.1:8099`），否则 403。
- 隐私页 `/privacy.html` 说明内存处理、IP 哈希、网段额度与 30 天删除策略。

## 维护

- 改页面：只改 `templates/*.html`，然后 `python3 scripts/build_site.py --write`。
- 改商品文案或链接：改 `catalog.yaml`（不写版本与价格），再 `build_site.py --write`；
  族集合必须与 `products/*.yaml` 一致，`skillhub-*` 渠道的链接必须是 `https://skillhub.cn/`。
- 新增商品族：先建 `products/<family>.yaml` 与 `components/<family>/component.yaml`（`lifecycle: active`），
  再在 `catalog.yaml` 补文案与三问选择器，最后 `build_site.py --write` 生成 `p/<family>.html`。
- 改检查项文案：改 `contracts/skill-quality-rules.yaml` → `python3 tools/sync_rules.py --write` → `python3 scripts/build_site.py --write`。
- 组件增删或改版本后：`python3 scripts/build_site.py --write`，`data/public.json` 与后台清单随之更新。
- 发版前校验：`make check`（kernel/边界/INDEX + `sync_rules --check` + `build_site --check` + 全部 API 测试，
  含样例回归、`patches[]`、并发上限与 8 SKU 基线门禁）。
- 后台只读，不做写操作；登记信息一律以 `components/*/component.yaml` 为唯一源。
- 规则或权重变更后若基线测试失败：确认差异是预期后，把规则 id 写进
  `platform/services/skillhub-audit-api/test/baseline/baseline-20261120.json` 的 `allowed_changes`，
  并在 SPEC/CHANGELOG 记录原因；禁止直接改基线分数。

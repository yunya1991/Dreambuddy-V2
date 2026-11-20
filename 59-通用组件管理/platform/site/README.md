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
│   └── guide.html        使用说明源
├── index.html            产物（模板渲染，带 AUTO-GENERATED 头，勿手改）
├── trial.html            产物
├── guide.html            产物
├── admin.html            只读管理后台（手写，仅 8082 可达）
├── privacy.html          隐私说明（手写，不属模板）
├── assets/
│   ├── style.css
│   ├── site.js           试用逻辑（含 zip 解析）、埋点、后台渲染
│   └── logo.jpg
├── data/registry.json    组件登记清单（由脚本生成，勿手改）
├── data/rules.json       公开体检规则摘要（由 tools/sync_rules.py 生成）
├── scripts/build_site.py 模板渲染 + registry 生成（--write / --check）
└── nginx/site.conf       8081 公网站点 + 8082 后台（Basic Auth + 8789 token）
```

> 页面只改 `templates/`；`index/trial/guide.html` 是构建产物，头部带 `AUTO-GENERATED`
> 注释，手改会被 `--check` 拦下。检查项数量与说明表来自 `data/rules.json`，
> 源头是 `contracts/skill-quality-rules.yaml`，页面不得硬编码「九项 / 9 项 / 七项」。

## 页面与接口

| 路径 | 说明 | 鉴权 |
|---|---|---|
| `/` | 产品介绍 + 下载引流 | 公开（8081） |
| `/trial.html` | 免费体检，`POST /api/trial` | 公开（8081） |
| `/guide.html` | 使用说明 | 公开（8081） |
| `/privacy.html` | 隐私说明 | 公开（8081） |
| `/admin.html` | 只读总览：健康 + 统计 + 组件清单 | 8082：Basic Auth |
| `/data/registry.json` | 组件登记清单 | 8082：Basic Auth |
| `/api/health` | audit-api 健康（8082 反代 `:8789/health` 并注入 token） | 8082：Basic Auth |
| `/api/stats` | 运行统计（30 秒缓存，8082 反代 `:8789/api/stats`） | 8082：Basic Auth |
| `/api/trial` | 免费体检（额度内） | 公开（8081） |
| `/api/audit` | 完整报告（HTTP 402 按次付费） | 公开（8081，匿名限流） |
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

## 部署（49.233.123.96）

```bash
# 1) 同步站点（只同步静态产物，不带源码依赖）
rsync -av --delete 59-通用组件管理/platform/site/ \
  ubuntu@49.233.123.96:/opt/dreambuddy-59-site/

# 2) 首次创建后台口令（用户名 59admin）
ssh ubuntu@49.233.123.96 \
  'sudo htpasswd -c /etc/nginx/.htpasswd-59site 59admin'

# 3) 安装站点配置
ssh ubuntu@49.233.123.96 '
  sudo cp /opt/dreambuddy-59-site/nginx/site.conf /etc/nginx/sites-available/dreambuddy-59-site &&
  sudo ln -sf /etc/nginx/sites-available/dreambuddy-59-site /etc/nginx/sites-enabled/ &&
  sudo nginx -t && sudo systemctl reload nginx'
```

> 8081 端口在 2026-11-20 清退 `ollama-proxy` 后已释放，可直接复用。
>
> 后台只监听 `127.0.0.1:8082`，需要从服务器本地或 SSH 隧道访问：
> `ssh -L 8082:127.0.0.1:8082 ubuntu@49.233.123.96`。
> 上线前把 `nginx/site.conf` 中两处 `REPLACE_WITH_ADMIN_TOKEN` 换成 `ADMIN_TOKEN`。

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
- 返回内容为完整报告的结构化裁剪版（总分 + 结论 + 前 6 条检查项），完整报告仍需付费获取。
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
- 改检查项文案：改 `contracts/skill-quality-rules.yaml` → `python3 tools/sync_rules.py --write` → `python3 scripts/build_site.py --write`。
- 组件增删或改版本后：`python3 scripts/build_site.py --write`，后台清单随之更新。
- 发版前校验：`make check`（含 `sync_rules --check`、`build_site --check` 与规则测试）。
- 后台只读，不做写操作；登记信息一律以 `components/*/component.yaml` 为唯一源。

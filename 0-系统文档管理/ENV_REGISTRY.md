# 环境变量与密码登记表 — ENV_REGISTRY

> **版本**: v1.2 | **更新日期**: 2026-11-18 | **数据来源**: 云端 `dreambuddy-remote` (43.160.201.117) 只读实测 + P0/P1 整改复验 + 22 域加密凭据库补录
> **定位**: 全系统密钥/凭据的**唯一查询入口**。只登记「变量名 + 用途 + 存放在哪」，**不存放任何明文值**。
> **适用**: AI 与人工排查时先查本表定位文件，再按需 SSH 读取；禁止把值回显到聊天、提交到 git。

---

## 一、怎么用（AI 查密码标准动作）

```bash
# 1) 在下方「二、环境文件清单」找到目标文件
# 2) 只取需要的单个键，避免整文件输出
ssh -o ConnectTimeout=15 dreambuddy-remote 'sudo -n grep "^<KEY>=" <文件路径>'

# 3) 报告时只说「已配置 / 未配置 / 长度 N」，不粘贴明文
```

**硬性规则**

1. 新增任何密钥：**先登记本表，再写实际文件**；只改文件不登记视为违规。
2. 轮换密钥：改值后按「引用方」列重启对应 systemd 服务。
3. 本表可进 git；任何 `.env` 实体文件一律不进 git（`.gitignore` 已覆盖）。
4. 禁止 `cat` 整个 `.env` 输出到会话或日志。

---

## 二、环境文件清单（云端 14 处）

| # | 路径 | 权限 | 属主 | 变量数 | 用途 | 被谁引用 |
|---|---|---|---:|---|---|---|
| 1 | `/etc/dreambuddy-pg.env` | 600 | root:root | 3 | 数据库口令（主库） | `datacenter-backfill` `datacenter-scheduler` `etl-worker` `index-reconcile` `product-hub` |
| 2 | `/etc/dreambuddy-admin.env` | 600 | root:root | 9 | 管理面 / 治理鉴权 | `product-hub-audit-flush` |
| 3 | `/etc/dreambuddy/worker-launcher.env` | 600 | root:root | 10 | D3 worker 调度 | `dreambuddy-worker-launcher` |
| 4 | `/etc/dreambuddy-monitoring/monitoring.env` | 600 | root:root | 8 | 监控告警 / 飞书推送 | `dreambuddy-feishu-receiver` `dreambuddy-metrics-exporter` |
| 5 | `/home/luke/.hermes/.env` | 600 | luke:luke | 8 | Hermes 网关（飞书机器人 + LLM） | Hermes 进程（非 systemd 托管） |
| 6 | `/home/luke/.dreambuddy-pg.env` | 600 | luke:luke | 1 | 本地兜底 DB 口令 | 手工运维脚本 |
| 7 | `/home/luke/.config/dreambuddy/.env.cloud` | 600 | luke:luke | 24 | **云端全量模板（最全的一份）** | 未被 unit 直接引用，作为部署参考 |
| 8 | `/home/luke/dreambuddy/18-数据获取中心/.env` | 600 | luke:luke | 1 | 数据获取中心 DSN | 18 模块进程 |
| 9 | `/home/luke/dreambuddy/11-易经推理系统/.env` | 600 | luke:luke | 5 | 易经推理（LLM + OKX 只读） | 11 模块进程 |
| 10 | `/home/luke/dreambuddy/41-文件索引系统/.env` | 600 | luke:luke | 1 | 文件索引 DB 口令 | 41 模块进程 |
| 11 | `/home/luke/dreambuddy/3.1-FRONTEND/.env.production` | 600 | luke:luke | 19 | 前端认证 / DB / MinIO / Redis | Next.js 构建与运行（自动加载） |
| 12 | `/home/luke/.okx/config.toml` | 600 | luke:luke | — | OKX CLI 交易所凭证 | `okx-venue-bridge.service` |
| 13 | `/home/luke/dreambuddy/51-OKX CLI 系统/runtime/audit/bridge_token` | 600 | luke:luke | 1 | venue bridge 内部 token（44 字节） | `okx-venue-bridge.service` |
| 14 | `/home/luke/.git-credentials` | 600 | luke:luke | 1 | GitHub HTTPS token | `git fetch/pull` |
| 15 | `/home/luke/dreambuddy/22-执行引擎中心/runtime/venue/credentials.enc` | 600 | luke:luke | 1（加密包） | **OKX 交易凭据唯一存放地**（AES-256-GCM，非明文） | 22 网关；23 经 `load_okx_config()` 读取 |
| 16 | `/home/luke/dreambuddy/22-执行引擎中心/runtime/venue/key` | 600 | luke:luke | 1 | 上述凭据库主密钥 | 同上 |

> **查 OKX 凭据状态（不打印明文）**：
> `cd /home/luke/dreambuddy/22-执行引擎中心 && /home/luke/venv-trading/bin/python -m executors.credentials status`
> 2026-11-18 实测：`configured=true, simulated=false, dry_run=false` → 真实盘。

**已处理的失效引用（P0，2026-11-18）**

`dreambuddy-entry23` / `dreambuddy-exit23` 原先各写了两行指向**不存在文件**的 `EnvironmentFile=-`，因 `-` 前缀被静默跳过。经确认两个服务 `active + enabled`、日志正常、主链路不依赖 env（`FRED_API_KEY` 仅测试脚本有硬编码兜底），判定为死引用，**已从云端 unit 与仓库模板同步删除**，服务未重启、PID 未变。

| 原路径 | 原状态 | 处置 |
|---|---|---|
| `/home/luke/dreambuddy/.env` | 不存在 | 删除引用行 |
| `23-四层闭环自进化交易架构/.env` | 不存在 | 删除引用行 |

---

## 三、变量总表（按类别）

### 3.1 数据库

| 变量 | 用途 | 存放位置 | 本地对应 | 密钥 |
|---|---|---|---|---|
| `DATABASE_URL` | 主库连接串（含口令） | `/etc/dreambuddy-pg.env`、`3.1-FRONTEND/.env.production`、`18-数据获取中心/.env` | 项目内 `.env` | ✅ |
| `DATA_CENTER_PG_PASSWORD` | 数据中心库口令 | `/etc/dreambuddy-pg.env`、`/home/luke/.dreambuddy-pg.env` | - | ✅ |
| `FIS_PG_PASSWORD` | 文件索引库口令 | `/etc/dreambuddy-pg.env`、`41-文件索引系统/.env` | - | ✅ |
| `POSTGRES_USER/PASSWORD/DB` | Docker 场景 PG 账号 | `/home/luke/.config/dreambuddy/.env.cloud` | - | ✅ |
| `EVAL_PG_DSN` | 评测库 DSN | systemd unit 内联 `Environment=` | - | ✅ |
| `DREAMBUDDY_CORE_DB` / `DREAMBUDDY_COGNITIVE_DB` / `DAL_DB_PATH` | 库文件路径 | systemd unit / 代码默认 | 项目内 | ❌ |

### 3.2 LLM 与数据源 API

| 变量 | 用途 | 存放位置 | 本地对应 | 密钥 |
|---|---|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 主力模型 | `.env.cloud`、`11-易经推理系统/.env`、`3.1-FRONTEND/.env.production` | `~/.hermes/.env` | ✅ |
| `DASHSCOPE_API_KEY` | 阿里百炼 | `/home/luke/.hermes/.env` | `~/.hermes/.env` | ✅ |
| `OPENAI_API_KEY` | OpenAI 兼容端点 | `/home/luke/.hermes/.env` | `~/.hermes/.env` | ✅ |
| `TAVILY_API_KEY` | 联网检索 | `.env.cloud`、`11-易经推理系统/.env`、`3.1-FRONTEND/.env.production` | 项目内 | ✅ |
| `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL` | 通义千问（百炼 token-plan，`cn-beijing`，`qwen3.8-max`）**已配置但未启用**：云端到阿里云 cn-beijing 出网超时，2026-11-18 决定仅用 DeepSeek | `/home/luke/dreambuddy/6-TRADING/scripts/.env`（2026-11-18 新建，未被任何服务引用） | `6-TRADING/scripts/.env`、`experiments/ab-trading/config/.env` | ✅ |
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` | Anthropic 兼容 | **未发现** | 项目内可能有 | ✅ |
| `FRED_API_KEY` | 宏观数据 | **未发现** | - | ✅ |
| `COINGLASS_API_KEY` / `CG_API_KEY` | 链上数据 | **未发现** | - | ✅ |

### 3.3 交易所 / 链上

| 变量 | 用途 | 存放位置 | 密钥 |
|---|---|---|---|
| `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` | OKX 交易凭证 | **`22-执行引擎中心/runtime/venue/credentials.enc`（交易唯一真源）**；`/home/luke/.okx/config.toml` 为 OKX CLI 自用副本 | ✅ |
| `OKX_BASE_URL` / `OKX_DRY_RUN` / `OKX_SIMULATED` | OKX 运行模式 | `11-易经推理系统/.env` | ❌ |
| `BINANCE_SPOT_API_KEY` / `BINANCE_SPOT_API_SECRET` | 币安现货 | **未发现** | ✅ |
| `ASTER_USER` / `ASTER_SIGNER` / `ASTER_SIGNER_PRIVATE_KEY` | Aster 签名账户 | **未发现** | ✅ |
| `ETHERSCAN_API_KEY` | 链上查询 | **未发现** | ✅ |

### 3.4 飞书 / Lark

| 变量 | 用途 | 存放位置 | 密钥 |
|---|---|---|---|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | Hermes 飞书机器人 | `/home/luke/.hermes/.env`、`/etc/dreambuddy-monitoring/monitoring.env` | ✅ |
| `LARK_APP_ID` / `LARK_APP_SECRET` | 前端 Lark 登录 | `.env.cloud` | ✅ |
| `FEISHU_CHAT_DESK` / `_MANAGEMENT` / `_RISK` | 告警群 ID | `monitoring.env` | ❌ |
| `FEISHU_APPROVAL_SECRET` / `_CODE` / `_KEY_ID` | D3D 审批 Grant 签名、审批定义 Code、签名 key | `~/.hermes/.env` 或审批服务环境 | ✅ |
| `FEISHU_REQUESTER_USER_ID` / `FEISHU_APPROVER_USER_ID` | 审批发起人 / 兜底审批人 | 同上 | ❌ |
| `APPROVAL_OUTBOX_TOKEN` | 前端 outbox 消费 API 鉴权（可选） | 服务环境 | ✅ |
| `GATEFLOW_APPROVAL_OUTBOX` / `APPROVAL_OUTBOX_STATE` | approval outbox 与其消费游标路径 | 服务环境 | ❌ |
| `GATEFLOW_APPLY_URL` | 授权后立即触发前端 outbox 消费的 URL | 服务环境 | ❌ |

### 3.5 认证 / 加密 / 对象存储

| 变量 | 用途 | 存放位置 | 密钥 |
|---|---|---|---|
| `AUTH_SECRET` / `NEXTAUTH_SECRET` | 会话签名 | `.env.cloud`、`3.1-FRONTEND/.env.production` | ✅ |
| `ENCRYPTION_KEY` | 字段加密 | 同上 | ✅ |
| `AUTH_URL` / `NEXTAUTH_URL` / `AUTH_TRUST_HOST` | 回调地址 | `3.1-FRONTEND/.env.production` | ❌ |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | MinIO 管理员 | `.env.cloud` | ✅ |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_ENDPOINT` | 前端对象存储 | `3.1-FRONTEND/.env.production` | ✅ |
| `REDIS_URL` | 缓存连接串 | `3.1-FRONTEND/.env.production` | ✅ |

### 3.6 内部服务 Token

| 变量 | 用途 | 存放位置 | 密钥 |
|---|---|---|---|
| `ADMIN_AUTH_SECRET` / `ADMIN_CONFIRM_SECRET` / `ADMIN_INTERNAL_TOKEN` | 管理面鉴权 | `/etc/dreambuddy-admin.env` | ✅ |
| `GOVERNANCE_ADMIN_TOKEN` | 治理服务 | `/etc/dreambuddy-admin.env` + unit 内联 | ✅ |
| `STRATEGY_LIB_ADMIN_TOKEN` | 策略库管理 | systemd unit 内联 `Environment=` | ✅ |
| venue bridge token | OKX bridge 内部鉴权 | `51-OKX CLI 系统/runtime/audit/bridge_token` | ✅ |
| `WEBHOOK_EXECUTE_TOKEN` / `MAINTENANCE_TOKEN` / `CONFIG_TOKEN` | Webhook / 维护 / 配置 | **未发现** | ✅ |
| `GATE_SKILLS_API_KEY` / `GATE_SKILLS_API_SECRET` / `GATE_API_SECRET` | 闸门服务 | **未发现** | ✅ |

### 3.7 监控与 Git

| 变量 | 用途 | 存放位置 | 密钥 |
|---|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | Grafana 管理员 | `monitoring.env` | ✅ |
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub API | `/home/luke/.git-credentials`（HTTPS 形式） | ✅ |

---

## 四、现存问题（按优先级）

| 级别 | 问题 | 证据 | 状态 / 处置 |
|---|---|---|---|
| P0 | `dreambuddy-entry23` / `dreambuddy-exit23` 引用的两个 env 文件都不存在 | unit 写 `EnvironmentFile=-/home/luke/dreambuddy/.env` 与 `23-.../.env`，实测 both missing | ✅ **已修复 2026-11-18**：确认为死引用，云端 unit + 仓库模板同步删除；服务未重启，PID 不变 |
| P1 | 权限过宽 | `worker-launcher.env` 644、`.env.production` 664 | ✅ **已修复 2026-11-18**：均收敛为 600，已验 `systemd(root)` / `luke` 可读、3 个相关服务仍 active |
| P1 | 旧密钥残留 | `3.1-FRONTEND/.env.production.bak.20261115`、`.bak.202611130225` | ✅ **已修复 2026-11-18**：移入 `/home/luke/deploy-backups/env-bak-20261118/`（目录 700、文件 600），前端目录已清空 |
| P2 | 同一密钥多处重复 | `TAVILY_API_KEY`×3、`DEEPSEEK_API_KEY`×3、`FEISHU_APP_SECRET`×2、`DATABASE_URL`×2、`FIS_PG_PASSWORD`×2；OKX 凭据另有 `.okx/config.toml` 副本与 `credentials.enc` 并存 | ⬜ 待处理：轮换时逐项核对「引用方」列，或后续收敛为单一主 `.env` |
| P2 | 代码引用但云端无定义 | 3.2/3.3/3.6 中标「未发现」的 15 组变量 | ⬜ 待处理：逐项确认是「功能未启用」还是「缺失」，结论回填本表 |

---

## 五、本地对应位置（供本地调试参照）

| 本地文件 | 说明 |
|---|---|
| `~/.hermes/.env` | 本地 Hermes 主环境 |
| `3.1-FRONTEND/.env`、`3.1-FRONTEND/.env.local` | 前端本地 |
| `10-经典指标系统/.env` | 经典指标（含 `.env.example` / `.env.template` 模板） |
| `11-易经推理系统/.env` | 易经 |
| `12-三屏趋势系统/.env` | 三屏趋势 |
| `19-数据访问层/.env` | DAL |
| `31-分布式计算部署/.env` | 部署脚本 |
| `32-对抗性辩论Bot/.env` | 辩论 Bot |
| `9-基本面分析/.env.example` / `.env.template` | 基本面（仅模板） |

---

## 六、维护约定

- 本表由**实测**驱动：任何「新增/迁移/删除 env 文件」都要重跑一次盘点并更新日期。
- 盘点命令（只取键名，不取值）：

```bash
ssh dreambuddy-remote 'for f in <文件列表>; do echo "=== $f"; sudo -n grep -oE "^[A-Za-z_][A-Za-z0-9_]*=" "$f" | tr -d "=" | sort -u; done'
ssh dreambuddy-remote 'for u in /etc/systemd/system/*.service; do ef=$(grep -oE "EnvironmentFile=-?[^ ]+" "$u"); [ -n "$ef" ] && echo "$(basename $u): $ef"; done'
```

- 表与 `31-分布式计算部署/docs/SERVICE_INVENTORY.md` 互补：那份管「服务与端口」，本表管「密钥在哪」。

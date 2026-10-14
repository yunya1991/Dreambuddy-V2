# Dreambuddy V2 — 子系统部署待配置清单

> **状态**：全量已上线（V15 + 易经 + 前端 + 数据层 + 产物中台 + 数据管道 + 认知/编排 + Hermes + M25~M28）
> **目标**：6大子交易系统 + 全量子系统在云端（43.160.201.117）全量运行，本地并行保留
> **更新日期**：2026-10-14

---

## 一、6大子交易系统部署状态

| # | 子系统 | 代码位置 | 入口命令 | 云端状态 | 优先级 |
|---|--------|---------|---------|---------|--------|
| 1 | **V15 经典马丁策略** | `14-V15经典马丁策略/` | `python3 run.py orchestrator/poll_light/api` | ✅ 已上线 | P0 |
| 2 | **BCRM2.0 推理引擎** | `11-易经推理系统/scripts/memory_l4/` | 集成在 polling_trader | ✅ 已上线 | P0 |
| 3 | **战略层（五计庙算）** | `11-易经推理系统/scripts/memory_l4/strategy_algo_layer.py` | 集成在 polling_trader | ✅ 已上线 | P0 |
| 4 | **BDSM 快照** | `11-易经推理系统/scripts/memory_l4/` | 集成在 polling_trader | ✅ 已上线 | P1 |
| 5 | **事件驱动策略** | `29-事件驱动策略系统/event_driven/` | 集成在 polling_trader | ✅ 已上线 | P1 |
| 6 | **自进化系统** | `23-四层闭环自进化交易架构/` | `evolution_pipeline.py` | ⏳ 线下运行 | P2 |

> **关键发现**：BCRM2 + 战略层 + BDSM + 事件驱动 共享 `11-易经推理系统/scripts/memory_l4/polling_trader.py` 入口，300秒轮询一次，是综合交易引擎。已部署为 systemd 服务 `yijing-polling-trader.service`。

---

## 二、后端 API 服务部署状态

| # | 服务 | 代码位置 | 端口 | 前端页面 | 云端状态 |
|---|------|---------|------|---------|---------|
| 1 | V15 API | `14-V15经典马丁策略/` | 8771/8770 | classic, trade | ✅ 已上线 |
| 2 | 易经数据服务 | `11-易经推理系统/data_server_fixed.py` | 8765 | three-screens, bdsm | ✅ 已上线 |
| 3 | 产物中台 | `7-产物中台/系统研究索引体系/` | 3456 | ranking | ✅ 已上线 |
| 4 | 基本面数据服务 | `9-基本面分析/ml_trade_service_v2.py` | 9094 | fundamental | ✅ 已上线 |
| 5 | M27 策略治理审批 | `27-策略治理审批系统/app.py` | 8094 | classic (pipeline/approvals/gate) | ✅ 已上线 |
| 6 | M26 策略管理模块 | `26-策略管理模块/app.py` | 8093 | classic (strategy upsert) | ✅ 已上线 |
| 7 | M28 信号触发模块 | `28-策略信号触发模块/app.py` | 8096 | signal-trigger | ✅ 已上线 |
| 8 | M25 用户策略生成 | `25-用户策略生成系统/app.py` | 8095 | classic (strategy generation) | ✅ 已上线 |

> **部署脚本**: `31-分布式计算部署/phase2/deploy.sh`（一键部署 8765 + 3456 + Nginx + 前端重构建）
> **Hub(3467) 说明**: 网关中台为设计文档服务，无实现。ops/market/feed API routes 已添加 `mock:true` 降级返回 200。
> **经典系统模块化**: 旧单体 8092 (ml_trade_service.py) 已拆分为 M25/M26/M27/M28。前端通过 Next.js rewrites (`/api/m25`~`/api/m28`) 代理到本机端口，浏览器端不再直连 127.0.0.1。

---

## 三、待配置项清单

### 3.1 云端环境配置

| 配置项 | 状态 | 说明 |
|--------|------|------|
| Python venv | ✅ 已建 | `/home/luke/venv-trading` (Python 3.12) |
| 依赖包 | ✅ 已装 | requests, pandas, numpy, ccxt, python-dotenv, fredapi, scikit-learn, lightgbm |
| 代理配置 | ✅ 无需 | 云端新加坡节点直连 OKX/Hyperliquid |

### 3.2 11-易经推理系统（BCRM2 + 战略层 + BDSM + 事件驱动）

| 配置项 | 状态 | 当前值 | 说明 |
|--------|------|-------|------|
| 运行入口 | ✅ 已确认 | `python3 -m scripts.memory_l4.polling_trader` | systemd 服务 |
| 轮询间隔 | ✅ 已确认 | `--interval 300` (5min) | |
| 监控币种 | ✅ 已确认 | 19 tokens | 可裁剪 |
| 置信度阈值 | ✅ 已确认 | `--confidence 0.7955` | |
| 最大持仓 | ✅ 已确认 | `--max-positions 5` | |
| 仓位比例 | ✅ 已确认 | `--position-pct 0.20` | |
| 交易模式 | ✅ 已确认 | OKXSimulatedClient (paper) | 安全，非实盘 |
| 飞书通知 | ⚠️ 待迁移 | FEISHU_APP_ID / SECRET | 需填入 |
| 交易凭据 | ⚠️ 待确认 | OKX API Key | paper 模式可选 |

### Phase 2: 易经推理系统上云（BCRM2 + 战略层 + BDSM）
1. 安装 miniconda + 创建环境
2. 扫描并安装依赖
3. 创建 systemd service（polling_trader）
4. 配置飞书通知 + 交易凭据
5. Nginx 反代易经 API（如有）
6. 功能验证

### Phase 3: 事件驱动 + 前端接入
1. 确认事件驱动部署方式
2. 前端各页面后端依赖梳理
3. Nginx 路由配置
4. 端到端功能验证

### Phase 4: 自进化协同
1. 设计线下→云端模型同步机制
2. MinIO 模型仓库
3. 云端热加载 + 灰度切换

---

## 四、风险与注意事项

1. **Conda 环境**：易经系统深度依赖 Anaconda，云端用 miniconda 替代，需验证兼容性
2. **代理问题**：本地用 127.0.0.1:7890，云端新加坡节点应可直连 OKX/Hyperliquid
3. **多币种监控**：19个币种轮询，云端4C8G需评估性能
4. **交易凭据安全**：OKX API Key 需加密存储，不能明文
5. **飞书凭据**：已在本地 plist 中，需安全迁移到云端 .env

---

## 五、全量一致性修复记录（2026-10-14）

> 背景：云端存储充足 → 决策「云端全量运行、本地并行保留」。本轮核查发现 5 处缺口（G1~G5），已全部修复并回读远端实况验证。

| 缺口 | 现象 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| G1 | `dreambuddy-frontend` 崩溃循环(:3001) | 手工 `next start`（stray pid）占用 3001 | 停单元→kill stray 进程树→restart | `active`、cgroup=`dreambuddy-frontend.service`、HTTP 307、NRestarts=0 |
| G2 | `yijing-data-server` 崩溃循环(:8765) | 手工 `nohup python3 data_server_fixed.py` 占用 8765 | 停单元→kill stray→restart | `active`、cgroup=`yijing-data-server.service`、HTTP 200 |
| G3 | Hermes 三件套无 systemd 单元 | 远端缺 hermes 运行时与 lark-cli | venv 装 `hermes-agent==0.19.0`（镜像最新）+ 同步 config/.env/skills/memories/cron + `@larksuite/cli` + 注册三单元 | `hermes-gateway`/`group-poller`/`hermes-dashboard` 均 `active`，Feishu websocket 已连接，dashboard :9119 |
| G4 | 远端代码落后 1 提交 | 本地 610fea04 未 pull；远端有未提交改动（内容与提交逐字节相同） | 备份→丢弃冲突路径→`pull --ff-only` | HEAD=`610fea04ba…`，`main...origin/main` 同步，3 文件 md5 与本地一致 |
| G5 | M25 走 PM2，与 M26~M28 不一致 | PM2 残留 m25 | 新建 `m25-strategy-generation.service`(:8095)→`pm2 delete` | `active`、cgroup=`m25-strategy-generation.service`、`/health`=200、PM2 列表已空 |

### 关键约定（云端）
- **写操作必须** `sudo -u luke -H`（repo 属主 luke，ubuntu 直连 logs/ 会 PermissionError）；**sqlite 读**也须以 luke 身份。
- Hermes 单元 `ExecStart` 指向 `/usr/local/bin/hermes`（已建软链 → `~/.hermes/.venv/bin/hermes`）；单元 `StandardOutput` 写 `*.out.log`，应用自身日志写 `gateway.log`，避免 systemd(root) 与 app(luke) 争抢同一日志文件。
- SSH 偶发 `Permission denied` → 重试 1~2 次即可（认证并发限制）。

### 当前云端运行清单（已核对 active）
- **systemd 服务**：dreambuddy-frontend(:3001) · yijing-data-server(:8765) · product-hub(:3456) · fundamental(:9094) · m25-strategy-generation(:8095) · m26-strategy-lib(:8093) · m27-governance(:8094) · m28-signal-trigger(:8096) · v15-api(:8771) · v15-capital-api(:8770) · yijing-polling-trader · datacenter-scheduler · cognitive-daemon · dreamos-scheduler · dreamos-dynamic-evaluator · hermes-gateway · group-poller · hermes-dashboard(:9119) · nginx
- **timers**：v15-orchestrator · v15-poll-light · datacenter-backfill · dal-backup · dal-rotate · dal-integrity · yijing-monitor · ranking-trigger · dreambuddy-snapshot
- **Docker**：dreambuddy-pg / dreambuddy-redis / dreambuddy-minio（healthy）
- **PM2**：已清空（M25 迁 systemd）。

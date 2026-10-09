# Dreambuddy V2 — 子系统部署待配置清单

> **状态**：Phase 1+2 已上线（V15 + 易经轮询引擎 + 前端 + 数据层 + Nginx）
> **目标**：推进6大子交易系统 + 前端功能接入云端
> **更新日期**：2026-10-10

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

> **部署脚本**: `31-分布式计算部署/phase2/deploy.sh`（一键部署 8765 + 3456 + Nginx + 前端重构建）

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

# PROP-20260828A：DreamOS × 基本面全链路打通（P1-P5）

> 日期：2026-08-28 ｜ 状态：已实施（P1-P5 全部落地，待 02:30 实盘编排周期注入验证）｜ 分类：trading（系统升级，已审批）
> 触发：用户指示「打通 数据收集中心→基本面分析→能力模块化→DreamOS调用→前端展示 完整链路」（D+Z 已授权，用户选 a 全量 P1-P5）

## 1. 背景与现状（D 调研结论）

链路 80% 已建成——采集在跑、F链节点已写、前端 8 个基本面页面组件齐全——但核心服务与接线缺失，断的是"最后一公里"。

### 现状拓扑

```
18-数据收集中心 ──✅每4h bridge──▶ 9-基本面分析 ──❌:9094未启动──▶ 前端:3000 (503)
  (M1已建成,守护未跑)                 (采集✅/服务❌)
                                          │
                                          ▼
                                    DreamOS F链 ◀── 前端代理期望 :9094
                                    (节点✅/注入❌)
```

### 断点清单

| # | 断点 | 证据 | 严重度 |
|---|---|---|---|
| B1 | `ml_trade_service_v2.py`（Flask :9094）代码完整但**进程未启动**，前端 `api/fundamental/[...path]` 代理 → 127.0.0.1:9094 全部 503，8 个 fundamental 页面（flow/macro/onchain/sentiment/news/narrative/calendar/overview）无数据 | 端口无监听；端点定义与前端调用完全匹配 | 致命 |
| B2 | `orchestrator_v2.run_cycle` 未调用 `FundamentalDataInjector`（仅未运行的 trading_agent 调用）→ F 层读空字段，injector 注释自证「F2-F5 恒输出 HOLD/0.3」 | grep 调用方；scheduler `_orchestrate` 管道为 A→B→C→D→E | 严重 |
| B3 | 18-数据收集中心 `data_center_scheduler.py` 守护未运行（无 data_center.db），采集器产能未释放 | 进程/文件检查 | 中 |
| B4 | core_task1 brief 生成（`ops/nanoclaw/core_task1/scripts/brief_v2_generator.py`）无排程，最后 8/27 01:06 手工跑 | crontab 检查 | 中 |
| B5 | 前端 `/api/market/snapshot` 走被封的 OKX CLI（`--profile dreamdemo` 参数语法错 + 网络封锁），必然失败并写递归错误对象入日志（已致 11GB 日志事故，已 truncate） | /tmp/next-start.log 根因分析 | 中 |

### 已就绪资产（无需重建）

- 采集：`run_fundamental_collect.py` crontab 每4h 正常（最近 8/28 00:00，10模块29事件，真实数据）
- F链节点：`f1_news~f5_macro_analysis.py` 全部实现并在 nodes.yaml 注册
- 注入器：`fundamental_injector.py`（1h缓存、静默降级）+ `free_fundamental_provider.py`（免费源降级）
- 服务代码：`ml_trade_service_v2.py` 端点与前端调用一一对应；venv 已装 flask 3.1.3

## 2. 方案（P1-P5）

### P1 基本面 API 服务守护化（解 B1，零代码改动）
- 新建 systemd user service `fundamental-api.service`：
  - ExecStart: `~/.hermes/hermes-agent/venv/bin/python3 ml_trade_service_v2.py --port 9094 --host 127.0.0.1`
  - Restart=always，日志走 journald（不落 /tmp 防膨胀）
- 前端 8 个基本面页面立即复活
- 验证：`/fundamental/health`、`/fundamental/overview`、`/fundamental/{module}/snapshot` 冒烟 + 前端页面截图

### P2 DreamOS 编排管道注入基本面（解 B2）
- `orchestrator_v2.run_cycle` 前置调用 `FundamentalDataInjector().inject(market_data, symbol)`（沿用 trading_agent 既有调用范式，~20行）
- 语义：注入失败/数据过期 → 静默降级，不阻断编排周期（与 injector 既有降级语义一致）
- 生效需重启 DreamOS 守护进程（先 pgrep 防双进程）；交易所侧 TP/SL 不受影响
- 验证：回归测试 + 周期日志确认 market_data 注入字段数 >0、F 层不再恒 HOLD/0.3

### P3 数据收集中心守护化（解 B3）
- `data_center_scheduler.py` 建 systemd user service（Restart=always），sqlite 落库启用
- `cron_bridge.sh` 每4h 桥接保留不动（双通道互补）
- 验证：data_center.db 生成 + 调度循环日志 + 39 项测试不回归

### P4 core_task1 brief 排程（解 B4）
- crontab 新增 `30 */4 * * *`（错开 00 分采集，消费最新 raw）运行 `brief_v2_generator.py` 入口（E 阶段先冒烟确认命令行参数）
- 验证：首个周期产物生成 + 退出码 0

### P5 前端行情数据源修复（解 B5，防日志再膨胀）
- `3-FRONTEND/dream-universal-gateway` `/api/market/snapshot` route：OKX CLI → Hyperliquid API（本机可达）+ alternative.me 降级
- 失败路径改为结构化短错误（杜绝递归错误对象写日志）
- 验证：端点返回真实行情 + 日志体积稳定

## 3. 实施顺序与依赖

```
P1(服务) → P5(前端) 可并行；P2(注入) 独立；P3(收集) 独立；P4(brief) 依赖采集节奏
顺序：P1 → P2 → P3 → P4 → P5，每 P 独立 commit 可单独 revert
```

## 4. 风险与回滚

| 风险 | 缓解 |
|---|---|
| P2 改动触及实盘编排路径 | 静默降级语义+回归测试通过后才重启守护进程；交易所侧持仓防护不受影响 |
| 新服务占用资源 | 三个守护进程均为轻量 Python（<100MB），Lighthouse 余量充足 |
| 回滚 | 每 P 独立 git commit；服务类 `systemctl --user stop/disable` 即回滚；P5 单文件 revert |

## 5. 审批记录

- 2026-08-28 D 调研完成，回报三选项（a 全量 P1-P5 / b 核心 P1+P2 / c 仅 P1）
- 2026-08-28 用户飞书选择：**a（全量 P1-P5）**
- 2026-08-28 审批实例创建：`0E0F0A27-E7FA-4A3A-B3C4-D98D91229967`（交易系统审批旧V1模板，审批人=用户，实例在飞书客户端不可见）
- 2026-08-28 用户在飞书聊天明确口头批准：**「我同意，直接开发吧」**→ E 链启动（审批实例留档，未走客户端点击）

## 6. 实施记录（E 链，2026-08-28）

| P | 动作 | 验证结果 | 提交 |
|---|---|---|---|
| P1 | `deploy/systemd/fundamental-api.service` 守护化（`--no-collect`，采集交给既有 crontab；规避 background_collector 无 sleep 死循环隐患） | /fundamental/health 10 模块 ok；前端代理 200；overview 复合信号 confidence=0.89 | commit①（docs+service） |
| P2 | orchestrator_v2.run_cycle Layer A 前注入：env 开关（默认启用）+ 懒加载单例 + 1h 缓存 + 静默降级 | 实测注入字段数=46，source=free_only(derivatives+sentiment+onchain+okx_derivatives+defillama)；回归 6/7（第 7 个 phase6 集成测试挂起为历史问题，关闭注入同样挂起）；守护进程已重启（PID 367258，setsid 脱离） | commit②（仅 P2 hunk，8/19 遗留持仓管理改动保持未提交） |
| P3 | `deploy/systemd/data-center.service` 守护化 | 调度器运行中；data_center.db 五表落库（defillama 已入库）；fred 需 API key/yfinance 限流/binance 被墙为已知环境限制，任务级容错 | commit③ |
| P4 | crontab `15 */4 * * *` brief_v2_generator（PROP 原案 :30，实际取 :15 紧随 :00 采集；venv python） | 冒烟生成 brief_v2_20260828_0145.md（35 条） | crontab（非仓库文件） |
| P5 | snapshot route 重写：OKX CLI → Hyperliquid(metaAndAssetCtxs+candleSnapshot) + alternative.me(BTC) 降级 + 结构化 502；修复 XAU 映射；重建重启 | BTC 80429/+2.45%、ETH 2518.2 实时；ZZZZ→502 结构化错误；黄金 mock 正常；12.3GB 递归错误日志已清理且根因消除 | commit④ |

### 待办与遗留
- 02:30 实盘编排周期注入验证：一次性 no_agent cron（02:32 自动播报）
- `ml_trade_service_v2.py` background_collector 无 sleep 死循环：未修（P1 用 --no-collect 规避），建议后续小 PROP 修复
- 18-数据收集中心：fred 任务需 FRED_API_KEY 才能真正产出宏观数据
- orchestrator_v2.py 中 8/19 遗留的持仓管理 +20 行改动仍在工作区未提交，归属待用户确认


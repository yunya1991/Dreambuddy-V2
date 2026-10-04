# 变更记录 — 15-监控告警系统

> **版本**: v1.0 | **更新日期**: 2026-09-30

---

## 版本变更记录

| 版本 | 日期 | 变更内容 | 影响范围 |
|------|------|----------|----------|
| v1.0 (文档补建) | 2026-09-30 | 补建 `docs/API_SPEC.md`、`docs/CHANGELOG.md`，完善模块文档体系 | 文档 |
| v1.0 | 2026-08-02 | 补建 `docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`，对齐 DOC_STANDARD L3 模块文档建设规范 | 文档 |
| — | 2026-07-27 | 模块运行中，产生首个故障事件记录 `INC-20260727111511.json` | 运行数据 |

---

## 详细变更

### v1.0 (文档补建) — 2026-09-30

**文档建设**
- 新建 `docs/API_SPEC.md`：覆盖核心层（UnifiedMonitor/MonitorAdapter/MonitorResult/MonitorStatus）、适配器层（5 个 MonitorAdapter 子类）、告警层（send_alert + 13 个 notify_* 业务函数）、持仓同步层（PositionSyncService/PositionSyncAdapter + 3 个 SyncAdapter 子类）、调度层（run_monitor/run_position_sync/main/shadow_resistance_gene_mvp）、记忆层（OpsMemoryInterface 14 个方法）的全部公开接口签名、参数表、示例、错误处理
- 新建 `docs/CHANGELOG.md`：本文件

### v1.0 — 2026-08-02

**文档建设**
- 新建 `docs/ENGINEERING_INDEX.md`：模块定位、目录地图、6 层文件清单（调度/核心/适配器/告警/持仓同步/记忆）、核心流程索引、配置参数索引、测试体系、技术债务、快速导航
- 新建 `docs/TECHNICAL_DESIGN.md`：概述、6 层架构、5 个核心算法（告警路由/健康检查优先级短路/BCRM2.0 双维度自检/双层调度/外部平仓二次确认）、数据流、接口设计、状态管理、配置管理、错误处理、扩展性设计

---

## 代码能力清单（按模块）

> 以下为当前代码已实现的能力清单，供变更追溯参考。

### 核心层（monitor_core.py）
- `MonitorStatus` 四级状态枚举（healthy/warning/critical/unknown）
- `MonitorResult` 结果对象（to_dict / is_healthy）
- `MonitorAdapter` 适配器基类（check_health + 4 个可选维度方法）
- `UnifiedMonitor` 统一管理器（三级配置回退 / 5 适配器实例化 / monitor_all / get_all_metrics / send_alerts）

### 适配器层（adapters/__init__.py）
- `YijingAdapter`：心跳 + 风控 + 性能 + BCRM2.0 双维度自检（日志扫描 6 关键字 + 模型缓存 48h 新鲜度）
- `V15Adapter`：心跳超时 + 连续亏损 ≥5 警告
- `ScreenAdapter`：心跳超时 + 三屏趋势指标
- `AgentAAdapter` / `AgentBAdapter`：日志时间戳心跳 + 记忆指标

### 告警层（feishu_alert.py）
- `send_alert` 通用入口 + 飞书 schema 2.0 卡片构建
- 13 个业务告警函数（heartbeat/process_error/trading_halted/consecutive_losses/model_error/position_close/system_error/performance_degrade/status_summary/trade_execution/system_start/system_stop）
- 四级路由（critical/error→risk, warning→trading, info→management）
- 凭证缺失降级（FEISHU_CREDENTIALS_VALID）

### 持仓同步层（position_sync.py）
- `PositionSyncService`：OKX 客户端延迟加载、外部平仓二次确认（窗口 + 次数）、API 故障保护、自动备份
- 3 个同步适配器（V15/Yijing/Screen）
- dry_run 只读模式

### 调度层（scheduler.py）
- 双层调度（60min 完整监控 + 5min 持仓同步）
- dreambuddy-v2 MVP L1×L2 影子调度（UTC 00:05，FO-7 熔断 ≥5 次失败）

### 记忆层（memory/app_memory_interface.py）
- `OpsMemoryInterface`（AM-OPS-001）：incident/playbook 增删改查、蒸馏候选、健康检查、相似案例检索

---

**文档版本**: v1.0
**最后更新**: 2026-09-30

# 工程索引 — 15-监控告警系统

> **版本**: v1.0 | **更新日期**: 2026-08-02
> **定位**: 模块级工程索引（L3 辅助模块），对齐 [DOC_STANDARD.md](../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.1 / §4

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 15 |
| 模块名称 | 15-监控告警系统 |
| 模块层级 | **L3 辅助模块**（运行中模块，遵循 README + ENGINEERING_INDEX + TECHNICAL_DESIGN 三文档建设规划） |
| 核心职责 | 以旁路方式对 5 个交易子系统进行健康巡检、指标采集与飞书告警推送，自身不参与交易决策 |
| 主入口 | `scheduler.py`（常驻调度）/ `monitor_core.py`（单次手动执行） |
| 依赖关系 | 上游：被监控子系统状态文件（11-易经推理系统 / 12-三屏趋势系统 / 14-V15经典马丁策略 / experiments/ab-trading Agent A、Agent B）；下游：飞书 OpenAPI（告警通道） |
| 外部依赖 | `requests`（飞书 OpenAPI 调用）、`schedule`（定时调度） |
| 凭证依赖 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET`（`start_monitor.sh` 注入） |
| 运行状态 | ✅ 运行中 |
| 文档状态 | ✅ 完整（README + ENGINEERING_INDEX + TECHNICAL_DESIGN） |

**被监控子系统列表**：

| 被监控系统 | 适配器 | 读取的状态文件 | 心跳阈值 |
|------------|--------|----------------|----------|
| 11-易经推理系统 | `YijingAdapter` | `.workbuddy/memory_l4/guardian/heartbeat.json`、`risk/risk_state.json`、`stats/performance.json`、`data/polling_trader/*.jsonl`、`data/bcrm2_models/*` | 30 分钟 |
| 14-V15经典马丁策略 | `V15Adapter` | `data/v15_state.json` | 240 分钟 |
| 12-三屏趋势系统 | `ScreenAdapter` | `data/screen_trade_state.json`、`data/screen_evolution_state.json` | 240 分钟 |
| Agent A | `AgentAAdapter` | `logs/agent_a/*.json`、`data/agent_a_memory.json` | 240 分钟 |
| Agent B | `AgentBAdapter` | `logs/agent_b/*.json`、`data/agent_b_memory.json` | 240 分钟 |

---

## 2. 目录地图

```
15-监控告警系统/
├── docs/                        # 文档目录
│   ├── ENGINEERING_INDEX.md     # 本文件 — 工程索引
│   └── TECHNICAL_DESIGN.md      # 技术设计
├── adapters/                    # 适配器层
│   └── __init__.py              # 5 个系统监控适配器实现
├── config/                      # 配置文件
│   └── monitor_config.json      # 主配置（系统/告警/调度/持仓同步/日志）
├── memory/                      # 事件记忆模块（AM-OPS-001）
│   ├── app_memory_interface.py  # 运维应用记忆接口
│   ├── memory_index.json        # 记忆索引
│   ├── incidents/               # 故障事件记录
│   │   └── INC-20260727111511.json
│   └── playbooks/               # 处置预案
│       └── PB-20260727111511.json
├── README.md                    # 用户文档
├── scheduler.py                 # 调度层 — 双层定时调度入口
├── monitor_core.py              # 核心层 — UnifiedMonitor + MonitorAdapter + MonitorResult
├── feishu_alert.py              # 告警层 — 飞书卡片构建与发送
├── position_sync.py             # 持仓同步层 — 5分钟轻量轮询
├── start_monitor.sh             # 入口层 — 后台启动脚本
├── logs/                        # 运行日志（运行时生成，monitor_core.py / position_sync.py 自动创建）
└── backups/                     # 持仓同步状态备份（运行时生成）
    └── position_sync/
```

**代码统计**：共 6 个核心 Python 文件，`def` 总数 138（monitor_core.py 22 + adapters/__init__.py 33 + feishu_alert.py 18 + position_sync.py 47 + scheduler.py 3 + memory/app_memory_interface.py 15）。

---

## 3. 文件清单与职责

### 3.1 调度层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `scheduler.py` | 3 | 双层定时调度入口，编排 60 分钟完整监控与 5 分钟持仓同步任务 | `run_monitor()`, `run_position_sync()`, `main()` |

### 3.2 核心层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `monitor_core.py` | 22 | 监控核心抽象：状态枚举、结果对象、适配器基类、统一管理器、配置加载、JSON 工具 | `UnifiedMonitor.__init__()`, `UnifiedMonitor._load_config()`, `UnifiedMonitor._default_config()`, `UnifiedMonitor._init_adapters()`, `UnifiedMonitor.monitor_all()`, `UnifiedMonitor.get_all_metrics()`, `UnifiedMonitor.send_alerts()`, `MonitorAdapter.check_health()`, `MonitorResult.to_dict()`, `MonitorResult.is_healthy()`, `load_json()`, `save_json()`, `_log()`, `main()` |

### 3.3 适配器层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `adapters/__init__.py` | 33 | 5 个子系统监控适配器实现，将异构状态文件归一为 `MonitorResult` | `YijingAdapter.check_health()`, `YijingAdapter._check_bcrm2_health()`, `YijingAdapter.get_performance()`, `YijingAdapter.get_risk_status()`, `YijingAdapter.get_core_metrics()`, `V15Adapter.check_health()`, `V15Adapter.get_performance()`, `ScreenAdapter.check_health()`, `ScreenAdapter.get_trading_stats()`, `AgentAAdapter.check_health()`, `AgentAAdapter._get_latest_log_time()`, `AgentBAdapter.check_health()`, `AgentBAdapter._get_latest_log_time()` |

### 3.4 告警层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `feishu_alert.py` | 18 | 飞书卡片构建、级别判定、群组路由与 OpenAPI 调用 | `send_alert()`, `get_token()`, `send_message()`, `card()`, `md()`, `hr()`, `notify_heartbeat_timeout()`, `notify_trading_halted()`, `notify_status_summary()`, `notify_system_error()`, `notify_position_close()`, `notify_consecutive_losses()`, `notify_process_error()`, `notify_model_error()`, `notify_performance_degrade()`, `notify_trade_execution()`, `notify_system_start()`, `notify_system_stop()` |

### 3.5 持仓同步层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `position_sync.py` | 47 | 持仓状态同步：对比交易所真实持仓、更新盈亏、外部平仓二次确认、自动备份 | `PositionSyncService.__init__()`, `PositionSyncService._init_okx_client()`, `PositionSyncService.register_adapter()`, `PositionSyncService.register_default_adapters()`, `PositionSyncService._backup_state_file()`, `PositionSyncService.get_exchange_positions()`, `PositionSyncService._check_close_confirmation()`, `PositionSyncService.sync()`, `PositionSyncService.sync_all()`, `V15SyncAdapter.get_coins()`, `V15SyncAdapter.load_local_state()`, `YijingSyncAdapter.get_state_positions()`, `ScreenSyncAdapter.remove_position()`, `_load_config()`, `_get_sync_config()`, `run_position_sync()` |

### 3.6 记忆层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `memory/app_memory_interface.py` | 15 | 运维应用记忆接口（AM-OPS-001），实现 incident/playbook 的增删改查与蒸馏 | `OpsMemoryInterface.__init__()`, `OpsMemoryInterface._load_index()`, `OpsMemoryInterface._save_index()`, `OpsMemoryInterface.search()`, `OpsMemoryInterface.add()`, `OpsMemoryInterface.update()`, `OpsMemoryInterface.get()`, `OpsMemoryInterface.stats()`, `OpsMemoryInterface.distill_candidates()`, `OpsMemoryInterface.healthcheck()`, `OpsMemoryInterface.find_playbook_for_incident()`, `OpsMemoryInterface.record_incident_resolution()`, `Incident.to_dict()`, `Playbook.to_dict()` |

### 3.7 入口层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `start_monitor.sh` | — (shell) | 后台启动调度器，注入飞书凭证，日志重定向到 `../logs/monitor_scheduler.log` | — |

### 3.8 配置层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `config/monitor_config.json` | — (JSON) | 全量运行配置：systems / alert / scheduler / position_sync / logging 五大节 | — |

---

## 4. 核心流程索引

### 4.1 调度启动流程

```
start_monitor.sh
  └─→ scheduler.py → main()
       ├─→ 读取 config/monitor_config.json 取 interval_minutes / sync_interval_minutes
       ├─→ run_position_sync()   （启动时立即执行一次）
       ├─→ run_monitor()         （启动时立即执行一次）
       └─→ schedule.every(N).minutes.do(...)  进入 while 循环
```

- 调度启动: `15-监控告警系统/start_monitor.sh` → `scheduler.py` → `main()`
- 完整监控任务: `15-监控告警系统/scheduler.py` → `run_monitor()`
- 持仓同步任务: `15-监控告警系统/scheduler.py` → `run_position_sync()`

### 4.2 完整监控主流程（60 分钟周期）

```
run_monitor()  (scheduler.py)
  └─→ UnifiedMonitor.__init__()  (monitor_core.py)
       ├─→ _load_config()        加载 config/monitor_config.json 或回退 _default_config()
       └─→ _init_adapters()      按 config.systems 实例化 5 个适配器
            └─→ monitor_all()    遍历适配器调用 check_health()
                 ├─→ YijingAdapter.check_health()    (adapters/__init__.py)
                 │    └─→ _check_bcrm2_health()      BCRM2.0 日志扫描 + 模型缓存检查
                 ├─→ V15Adapter.check_health()       (adapters/__init__.py)
                 ├─→ ScreenAdapter.check_health()    (adapters/__init__.py)
                 ├─→ AgentAAdapter.check_health()    (adapters/__init__.py)
                 │    └─→ _get_latest_log_time()
                 └─→ AgentBAdapter.check_health()    (adapters/__init__.py)
                      └─→ _get_latest_log_time()
            └─→ send_alerts(results)  按 status 分发告警
                 ├─→ notify_heartbeat_timeout()  (feishu_alert.py)
                 ├─→ notify_trading_halted()    (feishu_alert.py)
                 ├─→ notify_system_error()      (feishu_alert.py)
                 └─→ notify_status_summary()    (feishu_alert.py)  全局汇总
                      └─→ send_alert() → card() → send_message() → get_token()
```

- 配置加载: `15-监控告警系统/monitor_core.py` → `UnifiedMonitor._load_config()`
- 适配器注册: `15-监控告警系统/monitor_core.py` → `UnifiedMonitor._init_adapters()`
- 健康巡检: `15-监控告警系统/monitor_core.py` → `UnifiedMonitor.monitor_all()`
- 告警分发: `15-监控告警系统/monitor_core.py` → `UnifiedMonitor.send_alerts()`
- 告警发送: `15-监控告警系统/feishu_alert.py` → `send_alert()`
- 飞书 OpenAPI: `15-监控告警系统/feishu_alert.py` → `send_message()` / `get_token()`

### 4.3 持仓同步流程（5 分钟周期）

```
run_position_sync()  (scheduler.py)
  └─→ run_position_sync()  (position_sync.py)
       ├─→ _get_sync_config()              读取 position_sync 配置
       ├─→ PositionSyncService.__init__()  初始化 OKX 客户端
       ├─→ register_default_adapters()     注册 V15/Yijing/Screen 三个同步适配器
       └─→ sync_all()
            └─→ sync(name)
                 ├─→ adapter.load_local_state()           读本地状态
                 ├─→ get_exchange_positions(coins)        查交易所真实持仓
                 ├─→ _check_close_confirmation()          外部平仓二次确认
                 ├─→ adapter.update_position_with_exchange()  更新盈亏
                 ├─→ _backup_state_file()                 备份 state
                 └─→ adapter.save_local_state()           写回状态
```

- 同步入口: `15-监控告警系统/position_sync.py` → `run_position_sync()`
- 平仓确认: `15-监控告警系统/position_sync.py` → `PositionSyncService._check_close_confirmation()`
- 交易所查询: `15-监控告警系统/position_sync.py` → `PositionSyncService.get_exchange_positions()`
- 状态备份: `15-监控告警系统/position_sync.py` → `PositionSyncService._backup_state_file()`

---

## 5. 配置参数索引

### 5.1 主配置文件 `config/monitor_config.json`

| 配置路径 | 默认值 | 说明 |
|----------|--------|------|
| `systems.<name>.enabled` | `true` | 是否启用该系统监控 |
| `systems.<name>.base_dir` | 各子系统绝对路径 | 被监控系统的根目录 |
| `systems.<name>.max_idle_minutes` | yijing=30，其余=240 | 心跳超时阈值（分钟） |
| `systems.<name>.adapter` | — | 适配器类名字符串（如 `YijingAdapter`） |
| `systems.<name>.description` | — | 系统描述 |
| `alert.enabled` | `true` | 告警总开关 |
| `alert.feishu_enabled` | `true` | 飞书告警开关 |
| `alert.alert_on_warning` | `true` | warning 是否触发告警 |
| `alert.alert_on_critical` | `true` | critical 是否触发告警 |
| `alert.summary_interval_minutes` | `180` | 状态汇总间隔（分钟） |
| `alert.channels.critical` | `risk` | critical 级别路由群组 |
| `alert.channels.error` | `risk` | error 级别路由群组 |
| `alert.channels.warning` | `trading` | warning 级别路由群组 |
| `alert.channels.info` | `management` | info 级别路由群组 |
| `scheduler.enabled` | `true` | 调度器开关 |
| `scheduler.interval_minutes` | `60` | 完整监控间隔（分钟） |
| `scheduler.sync_interval_minutes` | `5` | 持仓同步间隔（分钟） |
| `scheduler.start_immediately` | `true` | 启动时立即执行一次 |
| `position_sync.dry_run` | `true` | 持仓同步只读模式 |
| `position_sync.close_confirm_count` | `2` | 平仓确认次数 |
| `position_sync.close_confirm_window_minutes` | `10` | 平仓确认窗口（分钟） |
| `position_sync.max_backups` | `20` | 状态备份最大保留份数 |
| `position_sync.skip_close_on_api_error` | `true` | API 异常时跳过删除 |
| `logging.level` | `INFO` | 日志级别 |
| `logging.log_dir` | `logs` | 日志目录 |
| `logging.max_files` | `30` | 日志最大保留文件数 |

### 5.2 环境变量（飞书凭证）

| 变量 | 默认值 | 说明 | 注入方式 |
|------|--------|------|----------|
| `FEISHU_APP_ID` | `cli_aa9442bde4b89be9`（代码硬编码 fallback） | 飞书应用 ID | `start_monitor.sh` 导出 |
| `FEISHU_APP_SECRET` | 代码硬编码 fallback | 飞书应用密钥 | `start_monitor.sh` 导出 |

### 5.3 代码内置常量

| 文件 | 常量 | 值 | 说明 |
|------|------|----|------|
| `position_sync.py` | `CLOSE_CONFIRM_WINDOW_MINUTES` | `10` | 平仓确认窗口（fallback） |
| `position_sync.py` | `CLOSE_CONFIRM_COUNT` | `2` | 平仓确认次数（fallback） |
| `position_sync.py` | `DEFAULT_DRY_RUN` | `True` | 默认只读模式（fallback） |
| `position_sync.py` | `MAX_BACKUPS` | `20` | 备份最大份数（fallback） |
| `feishu_alert.py` | `CHAT_IDS` | 4 个 chat_id | 飞书群组 ID（risk/management/trading/research） |
| `feishu_alert.py` | `CHANNEL_MAP` | 4 级映射 | 告警级别→群组路由（critical/error→risk，warning→trading，info→management） |
| `feishu_alert.py` | `ALERT_COLOR_MAP` | 4 色 | 级别→卡片颜色（critical→#ff4d4f 等） |
| `feishu_alert.py` | `ALERT_EMOJI` | 4 emoji | 级别→图标（critical→🔴 等） |
| `feishu_alert.py` | `TOKEN_URL` / `MSG_URL` | — | 飞书 OpenAPI 端点 |
| `adapters/__init__.py` | `BCRM2_FAILURE_KEYWORDS` | 6 个关键字 | BCRM2.0 降级/失败扫描词 |

### 5.4 加载优先级

```
环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET （start_monitor.sh 导出）
    ↓ 覆盖
feishu_alert.py 代码硬编码 fallback （os.environ.get 第二参数）
    ↓ 独立链路
config/monitor_config.json （主配置，scheduler / monitor_core / position_sync 共用）
    ↓ 覆盖
代码内置默认值 （UnifiedMonitor._default_config / position_sync 模块常量 / scheduler 60&5）
```

各模块配置加载链路：

| 模块 | 加载函数 | 优先级 |
|------|----------|--------|
| `monitor_core.py` | `UnifiedMonitor._load_config()` | ① 显式 `config_path` 参数 → ② `config/monitor_config.json` → ③ `_default_config()` 硬编码 |
| `position_sync.py` | `_get_sync_config()` → `_load_config()` | ① `config/monitor_config.json` 的 `position_sync` 节 → ② 模块常量（`CLOSE_CONFIRM_COUNT` 等） |
| `scheduler.py` | `main()` 内联读取 | ① `config/monitor_config.json` 的 `scheduler` 节 → ② 硬编码 `60` / `5` |
| `feishu_alert.py` | 模块级 `os.environ.get()` | ① 环境变量 → ② 代码硬编码默认值 |

---

## 6. 测试体系

| 文件 | 测试内容 |
|------|----------|
| — | 待建设（当前无 `tests/` 目录） |

> `memory/app_memory_interface.py` 末尾含 `__main__` 自测代码块（添加故障/预案并统计），可作为冒烟测试参考，但未形成独立测试套件。

**运行命令**（待建设后）：
```bash
python -m pytest tests/ -v
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 无测试套件 | 中 | 缺少 `tests/` 目录，适配器健康检查、告警路由、持仓同步确认逻辑均无自动化测试 |
| 飞书凭证硬编码 | 高 | `feishu_alert.py` 与 `start_monitor.sh` 内含明文 `FEISHU_APP_SECRET` fallback，存在凭证泄露风险 |
| 持仓同步 OKX 客户端跨模块依赖 | 中 | `position_sync.py` 通过 `sys.path.insert` 引用 `14-V15经典马丁策略/lib/okx_client.py`，耦合 V15 模块路径 |
| `alert.summary_interval_minutes` 未生效 | 低 | 配置项存在但 `send_alerts()` 每轮均发送全局汇总，未按间隔去重 |
| `scheduler.start_immediately` 未读取 | 低 | 配置项存在但 `main()` 无条件立即执行首轮 |
| 记忆模块未接入主流程 | 中 | `app_memory_interface.py` 已实现完整接口，但 `monitor_core.py` / `feishu_alert.py` 未调用，事件未沉淀 |

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 用户文档 | [../README.md](../README.md) |
| 技术设计 | [./TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 项目文档索引 | [../../../0-系统文档管理/INDEX.md](../../../0-系统文档管理/INDEX.md) |
| 文档规范 | [../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md](../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) |
| 标杆参照 | [../../../14-V15经典马丁策略/docs/ENGINEERING_INDEX.md](../../../14-V15经典马丁策略/docs/ENGINEERING_INDEX.md) |

---

**文档版本**: v1.0
**最后更新**: 2026-08-02

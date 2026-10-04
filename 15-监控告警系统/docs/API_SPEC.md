# API 规范 — 15-监控告警系统

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 模块接口规范，对齐 DOC_STANDARD §3.3

---

## 1. 接口概览

本模块为旁路监控组件，不对外暴露 HTTP/RPC 接口，对外交互通过飞书 OpenAPI（输出告警）与 OKX REST API（查询持仓）。内部提供 Python 类/函数接口。

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python 类 | 10 | UnifiedMonitor / MonitorAdapter / MonitorResult / MonitorStatus / 5 个 MonitorAdapter 子类 / PositionSyncService / PositionSyncAdapter(抽象) / 3 个 SyncAdapter 子类 / OpsMemoryInterface / Incident / Playbook |
| Python 函数 | 20+ | feishu_alert 系列 / load_json / save_json / run_position_sync 等 |
| 对外通道 | 2 | 飞书 OpenAPI（输出）、OKX REST API（输入） |
| CLI 入口 | 3 | `python3 monitor_core.py` / `python3 position_sync.py` / `bash start_monitor.sh` |

### 1.2 对外通道

| 通道 | 协议 | 方向 | 说明 |
|------|------|------|------|
| 飞书告警 | 飞书 OpenAPI（HTTP POST） | 输出 | `feishu_alert.send_message()` → 飞书群组卡片消息 |
| 子系统状态文件 | 文件系统（JSON/JSONL） | 输入 | 各适配器读取被监控子系统状态文件 |
| OKX 交易所 | OKX REST API | 输入 | `position_sync.get_exchange_positions()` 查询真实持仓 |

---

## 2. 认证方式

### 2.1 飞书凭证

| 凭证 | 环境变量 | 默认 fallback | 说明 |
|------|----------|---------------|------|
| 飞书应用 ID | `FEISHU_APP_ID` | `cli_aa9442bde4b89be9` | `feishu_alert.py` 模块级 `os.environ.get` |
| 飞书应用密钥 | `FEISHU_APP_SECRET` | `dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70` | `feishu_alert.py` 模块级 `os.environ.get` |

`start_monitor.sh` 通过 `export` 注入上述环境变量。凭证有效性由 `FEISHU_CREDENTIALS_VALID = bool(FEISHU_APP_ID and FEISHU_APP_SECRET)` 判定，无效时告警函数打印 WARN 日志并返回 `None`，不抛异常。

### 2.2 OKX 凭证

持仓同步通过 `14-V15经典马丁策略/lib/okx_client.py` 的 `OKXSimulatedClient` 访问 OKX，凭证由该客户端管理（跨模块依赖）。

---

## 3. 接口详情

### 3.1 核心层（monitor_core.py）

#### `MonitorStatus`（状态枚举）

| 常量 | 值 | 说明 |
|------|----|------|
| `HEALTHY` | `'healthy'` | 健康 |
| `WARNING` | `'warning'` | 警告 |
| `CRITICAL` | `'critical'` | 严重 |
| `UNKNOWN` | `'unknown'` | 未知（监控异常降级） |

#### `MonitorResult`（监控结果对象）

**构造函数**

```python
def __init__(self, system: str, status: str, message: str, detail: Dict = None)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system` | `str` | — | 系统名称 |
| `status` | `str` | — | 状态（MonitorStatus 取值） |
| `message` | `str` | — | 状态描述 |
| `detail` | `Dict` | `{}` | 详细指标 |

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `to_dict` | `() -> Dict` | 序列化为字典（含 timestamp ISO 字符串） |
| `is_healthy` | `() -> bool` | 是否健康（status == HEALTHY） |

#### `MonitorAdapter`（适配器基类）

```python
class MonitorAdapter:
    def __init__(self, system_name: str, config: Dict)
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `check_health` | `() -> MonitorResult` | 健康检查（子类必须实现） |
| `get_performance` | `() -> Dict` | 性能指标（默认返回 `{}`） |
| `get_trading_stats` | `() -> Dict` | 交易统计（默认返回 `{}`） |
| `get_risk_status` | `() -> Dict` | 风险状态（默认返回 `{}`） |
| `get_core_metrics` | `() -> Dict` | 核心运行态（默认返回 `{}`） |

#### `UnifiedMonitor`（统一监控管理器）

```python
class UnifiedMonitor:
    def __init__(self, config_path: Optional[str] = None)
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `_load_config` | `(config_path: Optional[str]) -> Dict` | 三级回退加载配置：①显式路径 ②config/monitor_config.json ③内置默认 |
| `_default_config` | `() -> Dict` | 内置默认配置（5 系统 + alert + scheduler） |
| `_init_adapters` | `()` | 按 config.systems 实例化 5 个适配器 |
| `monitor_all` | `() -> Dict[str, MonitorResult]` | 监控所有已配置系统（单系统异常降级为 UNKNOWN） |
| `get_all_metrics` | `() -> Dict[str, Dict]` | 获取所有系统 5 维度指标（health/performance/trading/risk/core） |
| `send_alerts` | `(results: Dict[str, MonitorResult]) -> None` | 按状态分发告警到飞书 |

**示例**

```python
from monitor_core import UnifiedMonitor

monitor = UnifiedMonitor()
results = monitor.monitor_all()
monitor.send_alerts(results)
```

#### 工具函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_json` | `(path: Path, default: dict = None) -> dict` | 安全加载 JSON（文件不存在或解析失败返回默认值） |
| `save_json` | `(path: Path, data: dict) -> None` | 保存 JSON（自动创建父目录） |
| `_log` | `(msg: str, system: str = 'monitor') -> None` | 日志（stdout + logs/monitor.log） |
| `main` | `() -> None` | 单次执行入口 |

### 3.2 适配器层（adapters/__init__.py）

所有适配器继承自 `MonitorAdapter`（实际为鸭子类型，未显式继承），均实现 `check_health()` + 4 个可选维度方法。

#### `YijingAdapter`（易经推理系统）

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(system_name: str, config: Dict)` | base_dir / max_idle_minutes（默认 30） |
| `check_health` | `() -> MonitorResult` | 优先级短路：交易暂停→心跳超时→进程异常→BCRM2.0 异常/警告→正常 |
| `_check_bcrm2_health` | `() -> Dict` | BCRM2.0 双维度自检：日志扫描（6 关键字）+ 模型缓存新鲜度（48h） |
| `get_performance` | `() -> Dict` | total_trades / win_rate / total_pnl / sharpe / max_drawdown |
| `get_trading_stats` | `() -> Dict` | trading_halted / consecutive_losses / daily_pnl / positions |
| `get_risk_status` | `() -> Dict` | halted / consecutive_losses / max_consecutive_losses / status |
| `get_core_metrics` | `() -> Dict` | pid / status / model_version=BCRM 2.0 / confidence_threshold=0.60 / margin_mode=isolated / monitored_coins=29 / interval_seconds=3600 |

读取文件：`heartbeat.json` / `risk_state.json` / `performance.json` / `data/polling_trader/trader_<date>.jsonl` / `data/bcrm2_models/`

#### `V15Adapter`（V15经典马丁策略）

| 方法 | 说明 |
|------|------|
| `check_health` | 心跳超时（240min）→ CRITICAL；连续亏损 ≥5 → WARNING；否则 HEALTHY |
| `get_performance` | total_trades / win_rate / consecutive_losses / positions |
| `get_trading_stats` | positions / total_trades / direction=long-short |
| `get_risk_status` | consecutive_losses / max_consecutive_losses=5 / status |
| `get_core_metrics` | model_version=V15 Classic Martin / direction_gate=MA128+BTC趋势 / coin_count=30 / margin_mode=isolated / confidence_threshold=0.5 |

读取文件：`data/v15_state.json`

#### `ScreenAdapter`（三屏趋势系统）

| 方法 | 说明 |
|------|------|
| `check_health` | 心跳超时（240min）→ CRITICAL；否则 HEALTHY |
| `get_performance` | trade_history_count / evolution_count / closed_trades |
| `get_trading_stats` | active / direction / symbol / total_size |
| `get_risk_status` | addon_pct=8.0 / tp_pct=4.0 / vol_mult=1.0 / status |
| `get_core_metrics` | model_version=Screen Trend System / strategy=Three-Screen / ml_model=LightGBM / screen_count=3 / interval_seconds=300 |

读取文件：`data/screen_trade_state.json` / `data/screen_evolution_state.json`

#### `AgentAAdapter` / `AgentBAdapter`

| 方法 | 说明 |
|------|------|
| `check_health` | 日志最新时间超时（240min）→ CRITICAL；否则 HEALTHY |
| `_get_latest_log_time` | `(log_dir: Path) -> datetime` 解析日志文件名时间戳或 mtime |
| `get_core_metrics` | Agent A: current_master / strategy=Memory-based Trading；Agent B: strategy=Full Cycle Trading |

读取文件：`logs/agent_a|b/*.json` / `data/agent_a|b_memory.json`

### 3.3 告警层（feishu_alert.py）

#### 模块级常量

| 常量 | 值 | 说明 |
|------|----|------|
| `CHAT_IDS` | risk/management/trading/research 4 个 chat_id | 飞书群组 ID |
| `CHANNEL_MAP` | critical/error→risk, warning→trading, info→management | 级别→群组路由 |
| `ALERT_COLOR_MAP` | critical=#ff4d4f, error=#ff7875, warning=#faad14, info=#1890ff | 卡片颜色 |
| `ALERT_EMOJI` | critical=🔴, error=🟠, warning=🟡, info=🔵 | 告警图标 |
| `TOKEN_URL` | `https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal` | 获取 tenant_access_token |
| `MSG_URL` | `https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id` | 发送消息 |

#### 核心函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_token` | `() -> str` | 获取飞书 tenant_access_token（每次重新获取，不缓存） |
| `send_message` | `(chat_id: str, msg_type: str, content: dict) -> dict` | 发送飞书消息，返回 API 响应 |
| `card` | `(title: str, level: str, elements: list) -> dict` | 构建 schema 2.0 卡片 |
| `md` | `(text: str) -> dict` | 构建 markdown 元素 |
| `hr` | `() -> dict` | 构建分割线元素 |
| `send_alert` | `(alert_type: str, level: str, message: str, details: Dict = None, system: str = '') -> Optional[str]` | 通用告警入口，返回 message_id；凭证无效返回 None |

**`send_alert` 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `alert_type` | `str` | 告警类型：heartbeat/trading/model/position/system/performance |
| `level` | `str` | 级别：critical/error/warning/info |
| `message` | `str` | 告警消息 |
| `details` | `Dict` | 详情键值对（dict/list 截断 200 字符） |
| `system` | `str` | 系统名称（卡片标题前缀） |

#### 业务告警函数

| 函数 | 签名 | 级别判定 |
|------|------|----------|
| `notify_heartbeat_timeout` | `(system: str, idle_minutes: float, threshold: float = 30)` | `idle_minutes > threshold*2` → critical，否则 error |
| `notify_process_error` | `(system: str, error_message: str, context: str = '')` | critical（heartbeat 类型） |
| `notify_trading_halted` | `(system: str, reason: str, consecutive_losses: int, daily_pnl: float = 0)` | critical（trading 类型） |
| `notify_consecutive_losses` | `(system: str, symbol: str, count: int, max_count: int = 5)` | `count >= max_count` → critical，否则 warning |
| `notify_model_error` | `(system: str, error_message: str, symbol: str = '')` | error（model 类型） |
| `notify_position_close` | `(system: str, symbol: str, reason: str, pnl: float = 0, pnl_pct: float = 0)` | `pnl_pct < -10` → critical，`< 0` → warning，否则 info |
| `notify_system_error` | `(system: str, error_message: str, component: str = '')` | critical（system 类型） |
| `notify_performance_degrade` | `(system: str, metric: str, current: float, threshold: float, direction: str = 'below')` | `direction=='below' and current < threshold*0.5` → critical，否则 warning |
| `notify_status_summary` | `(system: str, health: bool, status: str, detail: Dict)` | `health` → info，否则 critical（固定发往 management 群组） |
| `notify_trade_execution` | `(system: str, action: str, symbol: str, price: float, pnl: float = 0, pnl_pct: float = 0)` | `action=='CLOSE' and pnl_pct < -10` → critical，`< 0` → warning，否则 info |
| `notify_system_start` | `(system: str, config: Dict = None)` | info |
| `notify_system_stop` | `(system: str, reason: str = '')` | warning |

### 3.4 持仓同步层（position_sync.py）

#### `PositionSyncAdapter`（抽象基类）

| 抽象方法 | 签名 | 说明 |
|----------|------|------|
| `get_system_name` | `() -> str` | 系统名称 |
| `get_coins` | `() -> List[str]` | 监控币种列表 |
| `load_local_state` | `() -> Dict` | 加载本地持仓状态 |
| `save_local_state` | `(state: Dict) -> None` | 保存本地状态 |
| `get_state_positions` | `(state: Dict) -> Dict[str, Dict]` | 提取持仓字典 |
| `update_position_with_exchange` | `(local_pos: Dict, exchange_pos: Dict) -> Dict` | 用交易所数据更新本地持仓（current_price/unrealized_pnl/upl_ratio/profit_pct） |
| `remove_position` | `(state: Dict, coin: str) -> Dict` | 移除指定币种持仓 |
| `get_additional_info` | `() -> Dict` | 系统额外信息 |

#### `PositionSyncService`

```python
class PositionSyncService:
    def __init__(self, okx_client=None, dry_run: bool = None,
                 close_confirm_count: int = None, close_confirm_window_minutes: int = None,
                 max_backups: int = None, skip_close_on_api_error: bool = None)
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `_init_okx_client` | `()` | 延迟加载 OKX 客户端（从 `14-V15经典马丁策略/lib/okx_client`） |
| `register_adapter` | `(name: str, adapter: PositionSyncAdapter) -> None` | 注册同步适配器 |
| `register_default_adapters` | `()` | 注册 V15/Yijing/Screen 三个默认适配器 |
| `_backup_state_file` | `(adapter, adapter_name) -> None` | 修改前备份 state 文件（最多 max_backups 份） |
| `get_exchange_positions` | `(coins: List[str]) -> Tuple[Dict[str, Dict], bool]` | 查询交易所真实持仓，返回 (positions, api_healthy) |
| `_check_close_confirmation` | `(adapter_name: str, coin: str) -> bool` | 外部平仓二次确认（窗口内累计 close_confirm_count 次） |
| `sync` | `(adapter_name: str) -> Dict` | 同步指定系统持仓 |
| `sync_all` | `() -> List[Dict]` | 同步所有已注册系统 |

**`sync()` 返回字段**：status / system / dry_run / total_positions / externally_closed_total / externally_closed_confirmed / externally_closed_pending / skipped_close_due_to_api / externally_opened / synced / coins / api_healthy

#### 同步适配器子类

| 类 | get_coins | 状态文件 |
|----|-----------|----------|
| `V15SyncAdapter` | 读 `config/.env.v15` 的 V15_COINS，默认 BTC/ETH/SOL/ARB/OP/UNI | `14-V15经典马丁策略/data/v15_state.json` |
| `YijingSyncAdapter` | BTC/ETH/SOL/BNB/XRP/DOGE | `11-易经推理系统/data/okx_sim/config.json`（fallback: risk_state.json） |
| `ScreenSyncAdapter` | BTC/ETH/SOL/ARB/OP/UNI | `12-三屏趋势系统/data/screen_trade_state.json` |

#### 模块级函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `_load_config` | `() -> Dict` | 加载 config/monitor_config.json |
| `_get_sync_config` | `() -> Dict` | 获取 position_sync 节配置（含默认值回退） |
| `run_position_sync` | `() -> None` | 持仓同步入口（用于定时调度） |

### 3.5 调度层（scheduler.py）

| 函数 | 签名 | 说明 |
|------|------|------|
| `run_monitor` | `()` | 执行完整监控任务（实例化 UnifiedMonitor → monitor_all → send_alerts） |
| `run_position_sync` | `()` | 执行持仓同步任务（调用 position_sync.run_position_sync） |
| `shadow_resistance_gene_mvp` | `()` | dreambuddy-v2 MVP L1×L2 影子调度（UTC 00:05 每日，FO-7 熔断） |
| `main` | `()` | 调度器入口：读取配置 → 立即执行一轮 → schedule.every 注册定时任务 → while 循环 |

**调度配置**：从 `config/monitor_config.json` 的 `scheduler` 节读取 `interval_minutes`（默认 60）和 `sync_interval_minutes`（默认 5）。

### 3.6 记忆层（memory/app_memory_interface.py）

#### `OpsMemoryInterface`（AM-OPS-001）

```python
class OpsMemoryInterface:
    MEMORY_ID = "AM-OPS-001"
    MEMORY_NAME = "运维应用记忆"
    MEMORY_TYPE = "application"

    def __init__(self, storage_path: Optional[str] = None)
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `search` | `(query='', filters=None, memory_type='all', top_k=10) -> List[Dict]` | 检索记忆（incident/playbook/baseline/all） |
| `add` | `(memory_entry: Dict) -> str` | 添加记忆，返回 ID（incident 或 playbook） |
| `update` | `(memory_id: str, updates: Dict) -> bool` | 更新记忆 |
| `get` | `(memory_id: str) -> Optional[Dict]` | 获取单条记忆 |
| `stats` | `() -> Dict` | 统计信息（按类型/严重度/影响分组） |
| `distill_candidates` | `(min_quality='B', limit=10) -> List[Dict]` | 蒸馏候选（S/A/B 阈值矩阵） |
| `healthcheck` | `() -> Dict` | 健康检查 |
| `find_playbook_for_incident` | `(incident_type: str) -> List[Dict]` | 为故障查找预案 |
| `record_incident_resolution` | `(incident_id: str, resolution: str, root_cause: str) -> bool` | 记录故障处理结果 |
| `search_similar_cases` | `(content: str, top_k=5, threshold=0.3) -> List[Dict]` | 相似案例检索（统一签名） |
| `run_distill_from_review` | `(review_data: Dict) -> Dict` | 基于 Review 报告触发蒸馏闭环 |
| `increment_verify` | `(memory_id: str) -> bool` | verify_count +1 |
| `update_quality` | `(memory_id: str, new_quality: str, new_confidence=None) -> bool` | 调整质量等级 |

#### `Incident` / `Playbook` 数据类

两者均实现 `to_dict()` 方法，字段详见 `TECHNICAL_DESIGN.md` §4.3。

### 3.7 CLI 入口

| 命令 | 说明 |
|------|------|
| `bash start_monitor.sh` | 后台启动调度器，注入飞书凭证，日志重定向到 `../logs/monitor_scheduler.log` |
| `python3 monitor_core.py` | 单次执行完整监控（不进入调度循环） |
| `python3 position_sync.py` | 单次执行持仓同步 |
| `python3 memory/app_memory_interface.py` | 记忆模块冒烟自测 |

---

## 4. 错误码

本模块遵循"降级而非崩溃"原则，无数字错误码，以异常 + 日志 + 返回值表达：

| 错误场景 | 处理方式 | 实现位置 |
|----------|----------|----------|
| 配置文件缺失 | 回退到 `_default_config()` 内置默认值 | `UnifiedMonitor._load_config` |
| 适配器加载失败 | 记录 error 日志并跳过，不影响其他系统 | `UnifiedMonitor._init_adapters` |
| 单系统监控异常 | 降级为 `MonitorResult(name, UNKNOWN, '监控异常: {e}')` | `UnifiedMonitor.monitor_all` |
| 飞书凭证缺失 | `send_alert` / `notify_status_summary` 打印 WARN 并返回 None | `feishu_alert` |
| 飞书 API 失败 | `get_token` / `send_message` 抛 `RuntimeError`，由 scheduler 捕获 | `feishu_alert` |
| 状态文件读取失败 | `load_json` 返回空 dict → 空闲时间 inf → CRITICAL 告警 | `monitor_core.load_json` |
| OKX API 异常 | `get_exchange_positions` 返回 `api_healthy=False` → 跳过删除操作 | `position_sync` |
| 调度器主循环异常 | 捕获后 `sleep(60)` 继续 | `scheduler.main` |

**RuntimeError 消息格式**：
- `get_token`: `token error: {response_data}`
- `send_message`: `send error: {response_data}`

---

## 5. 版本管理

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-30 | 初始 API 规范版本，覆盖核心层/适配器层/告警层/持仓同步层/调度层/记忆层全部公开接口 |

> 变更以 `CHANGELOG.md` 为准。飞书 chat_id 与凭证属于运行时配置，不属于 API 版本管理范围。

---

**文档版本**: v1.0
**最后更新**: 2026-09-30

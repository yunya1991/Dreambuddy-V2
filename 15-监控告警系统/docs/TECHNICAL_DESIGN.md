# 技术设计 — 15-监控告警系统

> **版本**: v2.2 | **更新日期**: 2026-11-17
> **定位**: 子系统技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **v2.2 说明**: 一期范围收敛为「23 推理信号链」；新增第 12 章：23 模块全景、信号契约差异、8 步生命周期、信号 SLO 与落地审计。40 神经网络顺延二期。
> **v2.0 说明**: 新增第 10 章「云端全链路监控目标架构」。第 1–9 章保留为本地 v1.0 适配器实现（仅覆盖 5 个老系统），**不再作为云端监控的权威口径**；云端架构以第 10 章为准。调研证据与选型过程见 [RESEARCH-全链路监控体系调研-v0.2.md](./RESEARCH-全链路监控体系调研-v0.2.md)。

---

## 1. 概述

### 1.1 系统定位

15-监控告警系统是 DreamBuddy-V2 人机协作信息层的监控告警组件，以"旁路监控"方式对 5 个交易子系统（11-易经推理系统、12-三屏趋势系统、14-V15经典马丁策略、experiments/ab-trading Agent A、Agent B）进行健康巡检、指标采集与飞书告警推送。本模块为只读监控层，不直接干预各子系统交易逻辑（持仓同步模块在 `dry_run` 模式下同样不执行交易），通过适配器模式屏蔽各子系统状态文件差异，向统一的告警通道（飞书）输出标准化事件。

### 1.2 设计目标

- **统一接入**：通过 `MonitorAdapter` 适配器模式屏蔽各子系统状态文件差异，所有系统对外暴露相同的监控接口。
- **双层调度**：5 分钟轻量轮询（持仓同步）+ 60 分钟完整监控（健康检查 + 指标采集 + 告警发送）。
- **分级告警**：按 critical / error / warning / info 四级路由到不同飞书群组。
- **只读不写**：监控层只读取状态文件，不修改子系统数据；持仓同步默认 `dry_run`，不执行交易。
- **可降级**：飞书凭证缺失时自动跳过告警发送而非崩溃；配置文件缺失时回退到内置默认配置。

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| 读取各子系统状态文件（heartbeat/risk/perf/state） | 本模块（`adapters/`） |
| 健康状态判定（心跳超时/交易暂停/BCRM2.0 异常） | 本模块（`adapters/`） |
| 告警级别判定与飞书卡片发送 | 本模块（`feishu_alert.py`） |
| 持仓状态对比与盈亏更新（dry_run 只读） | 本模块（`position_sync.py`） |
| 双层定时调度编排 | 本模块（`scheduler.py`） |
| 交易决策与下单 | 各交易子系统（本模块不参与） |
| 状态文件写入/维护 | 各交易子系统（本模块仅读取） |
| 运维事件记忆沉淀 | 本模块（`memory/`，已实现接口但未接入主流程） |

---

## 2. 架构设计

### 2.1 分层架构

```
+-----------------------------------------------------------------------+
|                          调度层 (scheduler.py)                          |
|   +-----------------------+        +---------------------------+       |
|   |  60 分钟完整监控任务   |        |  5 分钟持仓同步任务       |       |
|   |  run_monitor()        |        |  run_position_sync()      |       |
|   +-----------+-----------+        +-------------+-------------+       |
+-----------------|------------------------------|----------------------+
                  |                              |
+-----------------v------------------------------v----------------------+
|                          核心层 (monitor_core.py)                      |
|   +----------------------------------------------------------------+   |
|   |  UnifiedMonitor  统一监控管理器                                  |   |
|   |  - _load_config()    加载/回退默认配置                          |   |
|   |  - _init_adapters()  按配置实例化适配器                          |   |
|   |  - monitor_all()     遍历调用 check_health()                    |   |
|   |  - get_all_metrics() 汇总各维度指标                             |   |
|   |  - send_alerts()     按状态分发告警                              |   |
|   +-----+---------------------+-------------------+----------------+   |
|         |                     |                   |                    |
|   +-----v-------+      +------v------+      +----v-----------+        |
|   | MonitorResult|     | MonitorStatus|     | MonitorAdapter  |       |
|   | (结果对象)    |     | (状态枚举)   |     | (适配器基类)    |       |
|   +--------------+     +--------------+     +----------------+        |
+-----------------------------------------------------------------------+
                  | 实例化（adapter_map 映射）
+-----------------v-----------------------------------------------------+
|                       适配器层 (adapters/__init__.py)                   |
|   +-----------+ +-----------+ +-----------+ +-----------+ +---------+ |
|   | Yijing    | | V15       | | Screen    | | AgentA    | | AgentB  | |
|   | Adapter   | | Adapter   | | Adapter   | | Adapter   | | Adapter | |
|   +-----+-----+ +-----+-----+ +-----+-----+ +-----+-----+ +----+----+ |
+---------|-------------|-------------|-------------|--------------|-----+
          | 读取状态文件 |             |             |              |
+---------v-------------v-------------v-------------v--------------v-----+
|                      被监控子系统状态层                                |
|   heartbeat.json / v15_state.json / screen_trade_state.json / ...     |
+-----------------------------------------------------------------------+
                  | 告警事件
+-----------------v-----------------------------------------------------+
|                       告警层 (feishu_alert.py)                          |
|   +-------------------+   +------------------+   +-------------------+  |
|   | send_alert()      |-->| card() / md()    |-->| send_message()    |  |
|   | notify_* 系列     |   | (卡片构建)        |   | (飞书 OpenAPI)    |  |
|   +-------------------+   +------------------+   +-------------------+  |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
|                    持仓同步层 (position_sync.py)                        |
|   +---------------------+   +-------------------+   +---------------+   |
|   | PositionSyncService |-->| PositionSyncAdapter|-->| OKX 客户端    |   |
|   | sync_all() / sync() |   | (V15/Yijing/Screen)|   | (盈亏对比)    |   |
|   +---------------------+   +-------------------+   +---------------+   |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
|                    记忆层 (memory/app_memory_interface.py)              |
|   OpsMemoryInterface (AM-OPS-001) — incident/playbook 记忆（待接入）   |
+-----------------------------------------------------------------------+
```

### 2.2 模块关系

| 层 | 模块 | 职责 | 关键依赖 |
|----|------|------|----------|
| 调度层 | `scheduler.py` | 定时触发监控与持仓同步任务，双层节奏编排 | `schedule` 库、`monitor_core`、`position_sync` |
| 核心层 | `monitor_core.py` | 统一管理器、适配器基类、结果对象、状态枚举、配置加载 | `adapters`、`feishu_alert` |
| 适配器层 | `adapters/__init__.py` | 各子系统具体监控逻辑实现，将异构状态文件归一为 `MonitorResult` | `monitor_core`（基类与结果对象） |
| 状态层 | 各子系统目录 | 心跳、风控、性能、持仓等 JSON / JSONL 状态文件 | — |
| 告警层 | `feishu_alert.py` | 告警级别判定、卡片构建、飞书群组路由、OpenAPI 调用 | `requests`、飞书 OpenAPI |
| 持仓同步层 | `position_sync.py` | 对比交易所真实持仓、更新盈亏、外部平仓二次确认 | `14-V15经典马丁策略/lib/okx_client.py`（跨模块） |
| 记忆层 | `memory/app_memory_interface.py` | 运维事件记忆（incident/playbook），实现总记忆系统统一接口 | — |

**调用关系**：`scheduler` → `monitor_core` → `adapters`（健康检查）+ `feishu_alert`（告警）；`scheduler` → `position_sync`（持仓同步）；`monitor_core.send_alerts()` 按状态关键字路由到 `feishu_alert.notify_*` 系列。

---

## 3. 核心算法

### 3.1 告警级别判定与去重路由

`UnifiedMonitor.send_alerts()` 根据各适配器返回的 `MonitorResult.status` 分发告警。CRITICAL 事件通过 `result.message` 关键字进一步细分路由到专用告警函数。

**路由规则**：

```
result.status == CRITICAL:
    if "心跳" in message or "空闲" in message:
        → notify_heartbeat_timeout(system, idle_minutes, max_idle_minutes)
    elif "暂停" in message:
        → notify_trading_halted(system, message, consecutive_losses, daily_pnl)
    else:
        → notify_system_error(system, message)

result.status == WARNING and alert_on_warning:
    → notify_status_summary(system, health=False, message, detail)

# 全局汇总（每轮均发送，固定发往 management 群组）
→ notify_status_summary("全局", overall_health, "{healthy}/{total} 系统正常", summary_detail)
```

**伪代码**：

```python
def send_alerts(results):
    if not alert_config.enabled:
        return
    for name, result in results.items():
        if result.status == CRITICAL:
            if "心跳" in result.message or "空闲" in result.message:
                notify_heartbeat_timeout(name, result.detail.get("idle_minutes", 0),
                                         adapters[name].max_idle_minutes)
            elif "暂停" in result.message:
                notify_trading_halted(name, result.message,
                                      result.detail.get("consecutive_losses", 0),
                                      result.detail.get("daily_pnl", 0))
            else:
                notify_system_error(name, result.message)
        elif result.status == WARNING and alert_config.get("alert_on_warning"):
            notify_status_summary(name, False, result.message, result.detail)
    # 全局汇总
    healthy_count = sum(1 for r in results.values() if r.is_healthy())
    overall_health = healthy_count == len(results)
    notify_status_summary("全局", overall_health, f"{healthy_count}/{len(results)} 系统正常", {...})
```

**告警级别二次判定**（`feishu_alert.py` 内业务函数动态决定 level）：

| 业务函数 | 判定逻辑 | 输出级别 |
|----------|----------|----------|
| `notify_heartbeat_timeout()` | `idle_minutes > threshold * 2` | critical / 否则 error |
| `notify_consecutive_losses()` | `count >= max_count` | critical / 否则 warning |
| `notify_position_close()` | `pnl_pct < -10` | critical / `pnl_pct < 0` warning / 否则 info |
| `notify_status_summary()` | `health == True` | info / 否则 critical |
| `notify_performance_degrade()` | `direction=="below" and current < threshold*0.5` | critical / 否则 warning |

### 3.2 阈值判断（健康检查优先级短路）

各适配器 `check_health()` 采用优先级短路策略，按严重程度从高到低依次判定，命中即返回。以 `YijingAdapter` 为例（最复杂，含 BCRM2.0 双维度自检）：

**伪代码**：

```python
def check_health(self):  # YijingAdapter
    heartbeat = load_json(heartbeat.json)
    risk = load_json(risk_state.json)
    perf = load_json(performance.json)
    bcrm2_status = self._check_bcrm2_health()    # 双维度自检

    idle_minutes = (now - heartbeat.ts) / 60 if heartbeat.ts else inf

    # 优先级1：交易暂停（最严重）
    if risk.get("trading_halted", False):
        return MonitorResult(CRITICAL, f"交易暂停: {risk['halt_reason']}", detail)

    # 优先级2：心跳超时
    if idle_minutes > self.max_idle_minutes:
        return MonitorResult(CRITICAL, f"心跳超时！已空闲 {idle_minutes:.0f} 分钟", detail)

    # 优先级3：进程状态异常
    if heartbeat.get("status") in ("error", "stopped"):
        return MonitorResult(CRITICAL, f"进程状态异常: {heartbeat['status']}", detail)

    # 优先级4：BCRM2.0 健康检查
    if bcrm2_status["status"] == "critical":
        return MonitorResult(CRITICAL, f"BCRM2.0 异常: {bcrm2_status['detail']}", detail)
    if bcrm2_status["status"] == "warning":
        return MonitorResult(WARNING, f"BCRM2.0 警告: {bcrm2_status['detail']}", detail)

    # 全部通过
    return MonitorResult(HEALTHY, f"心跳正常，空闲 {idle_minutes:.0f} 分钟 ...", detail)
```

其他适配器（V15/Screen/AgentA/AgentB）采用简化版：心跳超时 → CRITICAL，连续亏损达阈值 → WARNING，否则 HEALTHY。

### 3.3 BCRM2.0 双维度健康自检

`YijingAdapter._check_bcrm2_health()` 通过两个维度评估 BCRM2.0 健康状态：

**维度1（日志扫描）**：读取 `data/polling_trader/trader_<date>.jsonl` 最后 500 行，匹配 `BCRM2_FAILURE_KEYWORDS`（6 个关键字），命中即判 critical。

**维度2（模型缓存）**：检查 `data/bcrm2_models/` 目录文件新鲜度，空目录判 warning，最新修改超过 48 小时判 warning。

**伪代码**：

```python
def _check_bcrm2_health(self):
    log_file = base_dir / "data" / "polling_trader" / f"trader_{today}.jsonl"
    models_dir = base_dir / "data" / "bcrm2_models"

    # 维度1：扫描日志失败关键字
    failure_count = 0
    if log_file.exists():
        lines = log_file.readlines()[-500:]      # 只读最后 500 行
        for line in lines:
            entry = json.loads(line)
            if any(kw in entry["msg"] for kw in BCRM2_FAILURE_KEYWORDS):
                failure_count += 1

    if failure_count > 0:
        return {"status": "critical", "detail": f"当天检测到 {failure_count} 次降级/失败"}

    # 维度2：模型缓存新鲜度
    model_files = list(models_dir.glob("*"))
    if not model_files:
        return {"status": "warning", "detail": "模型缓存目录为空"}

    latest_mtime = max(f.stat().st_mtime for f in model_files)
    age_hours = (now - latest_mtime) / 3600
    if age_hours > 48:
        return {"status": "warning", "detail": f"模型缓存已 {age_hours:.0f}h 未更新"}

    return {"status": "healthy", "detail": f"模型缓存正常 ({len(model_files)} 个文件)"}
```

### 3.4 调度策略

`scheduler.py` 采用双层调度，启动时立即执行一次，之后按间隔循环：

**伪代码**：

```python
def main():
    config = load_json(config/monitor_config.json)
    monitor_interval = config.scheduler.interval_minutes    # 默认 60
    sync_interval = config.scheduler.sync_interval_minutes  # 默认 5

    run_position_sync()    # 启动立即执行
    run_monitor()          # 启动立即执行

    schedule.every(sync_interval).minutes.do(run_position_sync)
    schedule.every(monitor_interval).minutes.do(run_monitor)

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"调度器异常: {e}")
            time.sleep(60)    # 异常后等待 60s 继续，避免退出
```

### 3.5 持仓同步外部平仓二次确认

`PositionSyncService._check_close_confirmation()` 通过"首次记录 + 窗口内累计确认"机制防止误删：

**伪代码**：

```python
def _check_close_confirmation(self, adapter_name, coin):
    now = datetime.now(utc)
    pending = self._pending_closes[adapter_name]

    if coin in pending:
        first_ts, count = parse(pending[coin])    # "iso_ts|count"
        elapsed = (now - first_ts).total_seconds() / 60

        if elapsed <= self.close_confirm_window_minutes:    # 默认 10 分钟
            count += 1
            if count >= self.close_confirm_count:            # 默认 2 次
                del pending[coin]
                return True     # 确认通过，允许删除
            pending[coin] = f"{first_ts}|{count}"
            return False        # 继续等待
        else:
            pending[coin] = f"{now}|1"    # 超窗口，重置
            return False
    else:
        pending[coin] = f"{now}|1"        # 首次检测
        return False
```

---

## 4. 数据流

### 4.1 完整监控数据流（60 分钟周期）

```
[scheduler: 60min 触发]
        |
        v
run_monitor()  (scheduler.py)
        |
        v
UnifiedMonitor.__init__()  (monitor_core.py)
   |-- _load_config()  --> config/monitor_config.json (或 _default_config 内置)
   |-- _init_adapters() --> adapters/__init__.py 实例化 5 个适配器
        |
        v
monitor.monitor_all()
        |
        +-- for each adapter:
        |       |-- YijingAdapter.check_health()  --> 读 heartbeat/risk/perf/bcrm2 日志
        |       |-- V15Adapter.check_health()      --> 读 v15_state.json
        |       |-- ScreenAdapter.check_health()   --> 读 screen_trade_state.json
        |       |-- AgentAAdapter.check_health()   --> 读 logs/agent_a/*.json
        |       |-- AgentBAdapter.check_health()   --> 读 logs/agent_b/*.json
        |       |
        |       v
        |   MonitorResult{system, status, message, detail, timestamp}
        |
        v
Dict[str, MonitorResult]  -->  monitor.send_alerts(results)
        |
        v
feishu_alert.notify_*  -->  send_alert()  -->  card()  -->  send_message()
        |                                                  |
        |                                                  v
        |                                       飞书 OpenAPI (token + IM)
        v
各群组收到卡片消息: risk / trading / management
```

### 4.2 持仓同步数据流（5 分钟周期）

```
[scheduler: 5min 触发]
        |
        v
run_position_sync()  (position_sync.py)
        |
        v
PositionSyncService.sync_all()
        |-- adapter.load_local_state()       读本地 state（持仓/方向/入场价）
        |-- get_exchange_positions(coins)    查 OKX 交易所真实持仓（mark_px/upl）
        |-- 对比 local_keys vs exchange_keys
        |       |-- 交集: update_position_with_exchange()  更新 current_price/unrealized_pnl/profit_pct
        |       |-- local - exchange: 外部平仓 → _check_close_confirmation() 二次确认
        |       |-- exchange - local: 外部开仓 → 仅记录日志
        |-- _backup_state_file()             修改前备份（最多 max_backups 份）
        |-- adapter.save_local_state()        写回 state（dry_run 模式跳过）
        v
backups/position_sync/  (备份状态)
```

### 4.3 数据结构

| 结构 | 字段 | 说明 |
|------|------|------|
| `MonitorResult` | `system`, `status`, `message`, `detail`, `timestamp` | 监控结果对象，`status` 取值 healthy/warning/critical/unknown |
| `MonitorStatus` | `HEALTHY`, `WARNING`, `CRITICAL`, `UNKNOWN` | 状态枚举常量 |
| `Incident` | `incident_id`, `incident_type`, `severity`, `timestamp`, `host`, `service`, `symptoms`, `root_cause`, `resolution`, `duration_minutes`, `impact`, `tags` | 故障事件（记忆层） |
| `Playbook` | `playbook_id`, `name`, `trigger_condition`, `steps`, `estimated_time_minutes`, `required_access`, `created_at`, `last_used`, `usage_count`, `success_rate`, `tags` | 运维预案（记忆层） |
| 飞书卡片 | `schema`, `config`, `header{title,template}`, `body{elements}` | schema 2.0 interactive 卡片 |

---

## 5. 接口设计

### 5.1 内部接口

#### 5.1.1 核心层接口（`monitor_core.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `UnifiedMonitor.__init__` | `def __init__(self, config_path: Optional[str] = None)` | 初始化，加载配置并实例化适配器 |
| `UnifiedMonitor._load_config` | `def _load_config(self, config_path: Optional[str]) -> Dict` | 三级回退加载配置 |
| `UnifiedMonitor._init_adapters` | `def _init_adapters(self)` | 按 config.systems 实例化适配器 |
| `UnifiedMonitor.monitor_all` | `def monitor_all(self) -> Dict[str, MonitorResult]` | 监控所有已配置系统 |
| `UnifiedMonitor.get_all_metrics` | `def get_all_metrics(self) -> Dict[str, Dict]` | 获取所有系统核心指标 |
| `UnifiedMonitor.send_alerts` | `def send_alerts(self, results: Dict[str, MonitorResult])` | 根据监控结果发送告警 |
| `MonitorAdapter.check_health` | `def check_health(self) -> MonitorResult` | 健康检查（子类必须实现） |
| `MonitorAdapter.get_performance` | `def get_performance(self) -> Dict` | 性能指标（可选） |
| `MonitorAdapter.get_trading_stats` | `def get_trading_stats(self) -> Dict` | 交易统计（可选） |
| `MonitorAdapter.get_risk_status` | `def get_risk_status(self) -> Dict` | 风险状态（可选） |
| `MonitorAdapter.get_core_metrics` | `def get_core_metrics(self) -> Dict` | 核心运行态（可选） |
| `MonitorResult.to_dict` | `def to_dict(self) -> Dict` | 序列化为字典 |
| `MonitorResult.is_healthy` | `def is_healthy(self) -> bool` | 是否健康 |
| `load_json` | `def load_json(path: Path, default: dict = None) -> dict` | 安全加载 JSON（失败返回默认值） |
| `save_json` | `def save_json(path: Path, data: dict)` | 保存 JSON |
| `main` | `def main()` | 单次执行入口 |

#### 5.1.2 告警层接口（`feishu_alert.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `send_alert` | `def send_alert(alert_type: str, level: str, message: str, details: Dict = None, system: str = "")` | 通用告警入口 |
| `get_token` | `def get_token() -> str` | 获取飞书 tenant_access_token |
| `send_message` | `def send_message(chat_id: str, msg_type: str, content: dict) -> dict` | 发送飞书消息 |
| `card` | `def card(title: str, level: str, elements: list) -> dict` | 构建 schema 2.0 卡片 |
| `notify_heartbeat_timeout` | `def notify_heartbeat_timeout(system: str, idle_minutes: float, threshold: float = 30)` | 心跳超时告警 |
| `notify_trading_halted` | `def notify_trading_halted(system: str, reason: str, consecutive_losses: int, daily_pnl: float = 0)` | 交易暂停告警 |
| `notify_status_summary` | `def notify_status_summary(system: str, health: bool, status: str, detail: Dict)` | 状态汇总（固定发往 management） |
| `notify_system_error` | `def notify_system_error(system: str, error_message: str, component: str = "")` | 系统错误告警 |
| `notify_position_close` | `def notify_position_close(system: str, symbol: str, reason: str, pnl: float = 0, pnl_pct: float = 0)` | 平仓告警 |
| `notify_consecutive_losses` | `def notify_consecutive_losses(system: str, symbol: str, count: int, max_count: int = 5)` | 连续亏损告警 |

#### 5.1.3 持仓同步层接口（`position_sync.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `PositionSyncService.sync` | `def sync(self, adapter_name: str) -> Dict` | 同步指定系统持仓 |
| `PositionSyncService.sync_all` | `def sync_all(self) -> List[Dict]` | 同步所有已注册系统 |
| `PositionSyncService.get_exchange_positions` | `def get_exchange_positions(self, coins: List[str]) -> Dict[str, Dict]` | 查询交易所真实持仓（返回 positions + api_healthy） |
| `PositionSyncService._check_close_confirmation` | `def _check_close_confirmation(self, adapter_name: str, coin: str) -> bool` | 外部平仓二次确认 |
| `PositionSyncService.register_adapter` | `def register_adapter(self, name: str, adapter: PositionSyncAdapter)` | 注册同步适配器 |
| `PositionSyncAdapter.load_local_state` | `def load_local_state(self) -> Dict`（抽象） | 加载本地持仓状态 |
| `PositionSyncAdapter.update_position_with_exchange` | `def update_position_with_exchange(self, local_pos: Dict, exchange_pos: Dict) -> Dict`（抽象） | 用交易所数据更新本地持仓 |
| `run_position_sync` | `def run_position_sync()` | 持仓同步入口（用于定时调度） |

#### 5.1.4 记忆层接口（`memory/app_memory_interface.py`）

| 函数 | 签名 | 说明 |
|------|------|------|
| `OpsMemoryInterface.search` | `def search(self, query: str = "", filters: Optional[Dict] = None, memory_type: str = "all", top_k: int = 10) -> List[Dict]` | 检索记忆 |
| `OpsMemoryInterface.add` | `def add(self, memory_entry: Dict[str, Any]) -> str` | 添加记忆（返回 ID） |
| `OpsMemoryInterface.update` | `def update(self, memory_id: str, updates: Dict[str, Any]) -> bool` | 更新记忆 |
| `OpsMemoryInterface.get` | `def get(self, memory_id: str) -> Optional[Dict[str, Any]]` | 获取单条记忆 |
| `OpsMemoryInterface.stats` | `def stats(self) -> Dict[str, Any]` | 统计信息 |
| `OpsMemoryInterface.distill_candidates` | `def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict]` | 蒸馏候选 |
| `OpsMemoryInterface.healthcheck` | `def healthcheck(self) -> Dict[str, Any]` | 健康检查 |
| `OpsMemoryInterface.find_playbook_for_incident` | `def find_playbook_for_incident(self, incident_type: str) -> List[Dict]` | 为故障查找预案 |
| `OpsMemoryInterface.record_incident_resolution` | `def record_incident_resolution(self, incident_id: str, resolution: str, root_cause: str) -> bool` | 记录故障处理结果 |

### 5.2 对外接口

本模块为旁路监控组件，不对外暴露 HTTP/RPC/CLI 接口。对外交互方式：

| 对外通道 | 协议 | 方向 | 说明 |
|----------|------|------|------|
| 飞书告警 | 飞书 OpenAPI（HTTP） | 输出 | `feishu_alert.send_message()` → 飞书群组卡片消息 |
| 子系统状态文件 | 文件系统（JSON/JSONL） | 输入 | 各适配器读取被监控子系统状态文件 |
| OKX 交易所 | OKX REST API | 输入 | `position_sync` 查询真实持仓 |

---

## 6. 状态管理

### 6.1 状态文件

| 文件 | 作用 | 格式 | 维护方 |
|------|------|------|--------|
| `config/monitor_config.json` | 主配置（系统/告警/调度/持仓同步/日志） | JSON | 人工维护 |
| `memory/memory_index.json` | 记忆索引（incidents/playbooks/baselines 三节） | JSON | `OpsMemoryInterface._save_index()` |
| `memory/incidents/INC-*.json` | 故障事件记录 | JSON | `OpsMemoryInterface.add()` |
| `memory/playbooks/PB-*.json` | 处置预案 | JSON | `OpsMemoryInterface.add()` |
| `logs/monitor.log` | 监控核心运行日志 | 文本 | `monitor_core._log()` |
| `../logs/monitor_scheduler.log` | 调度器 stdout/stderr 重定向 | 文本 | `start_monitor.sh` nohup |
| `backups/position_sync/*.json` | 持仓同步状态备份（最多 max_backups 份） | JSON | `PositionSyncService._backup_state_file()` |

### 6.2 运行时状态

| 状态 | 存储位置 | 说明 |
|------|----------|------|
| 适配器注册表 | `UnifiedMonitor.adapters: Dict[str, MonitorAdapter]` | 内存，每轮 `monitor_all()` 重建 |
| 待确认平仓 | `PositionSyncService._pending_closes: Dict[str, Dict[str, str]]` | 内存，跨轮次保留（`"iso_ts\|count"` 格式） |
| 飞书凭证有效性 | `feishu_alert.FEISHU_CREDENTIALS_VALID` | 模块级常量，启动时计算 |
| 记忆索引 | `OpsMemoryInterface.index: Dict[str, dict]` | 内存 + `memory_index.json` 持久化 |

### 6.3 状态机（监控结果状态流转）

```
                    check_health()
各子系统 ──────────────────────────────► MonitorResult
   │                                       │
   │  适配器内部优先级短路判定              │
   │   交易暂停 ──────────────────────► CRITICAL
   │   心跳超时 ──────────────────────► CRITICAL
   │   进程异常 ──────────────────────► CRITICAL
   │   BCRM2.0 失败 ─────────────────► CRITICAL
   │   BCRM2.0 警告 / 连续亏损 ───────► WARNING
   │   正常 ─────────────────────────► HEALTHY
   │   适配器抛异常 ──────────────────► UNKNOWN（monitor_all 捕获降级）
   │                                       │
   │                            send_alerts() 分发
   │                                       │
   │       CRITICAL ──► notify_heartbeat_timeout / notify_trading_halted / notify_system_error
   │       WARNING ──► notify_status_summary(health=False)
   │       全局     ──► notify_status_summary(health=overall)
   v                                       v
子系统状态文件                        飞书群组卡片消息
```

---

## 7. 配置管理

配置加载由 `UnifiedMonitor._load_config()` 统一处理，采用三级回退策略：

```
function _load_config(config_path):
    if config_path:                              # 优先级1：显式传入路径
        return load_json(config_path)
    if CONFIG_DIR/monitor_config.json.exists():  # 优先级2：默认配置文件
        return load_json(default_config)
    return _default_config()                      # 优先级3：内置硬编码默认值
```

### 7.1 关键配置项说明

| 配置路径 | 默认值 | 说明 | 加载模块 |
|----------|--------|------|----------|
| `systems.<name>.enabled` | `true` | 是否启用该系统监控 | `monitor_core._init_adapters()` |
| `systems.<name>.base_dir` | 各子系统路径 | 被监控系统根目录 | 各适配器 `__init__` |
| `systems.<name>.max_idle_minutes` | yijing=30，其余=240 | 心跳超时阈值 | 各适配器 `check_health()` |
| `systems.<name>.adapter` | — | 适配器类名字符串 | `monitor_core._init_adapters()` |
| `alert.enabled` | `true` | 告警总开关 | `monitor_core.send_alerts()` |
| `alert.feishu_enabled` | `true` | 飞书告警开关 | — |
| `alert.alert_on_warning` | `true` | warning 是否触发告警 | `monitor_core.send_alerts()` |
| `alert.alert_on_critical` | `true` | critical 是否触发告警 | — |
| `alert.summary_interval_minutes` | `180` | 状态汇总间隔（⚠️ 未生效） | — |
| `alert.channels.*` | critical/error→risk, warning→trading, info→management | 级别→群组映射 | — |
| `scheduler.interval_minutes` | `60` | 完整监控间隔 | `scheduler.main()` |
| `scheduler.sync_interval_minutes` | `5` | 持仓同步间隔 | `scheduler.main()` |
| `scheduler.start_immediately` | `true` | 启动立即执行（⚠️ 未读取，无条件执行） | — |
| `position_sync.dry_run` | `true` | 持仓同步只读模式 | `position_sync._get_sync_config()` |
| `position_sync.close_confirm_count` | `2` | 平仓确认次数 | `PositionSyncService._check_close_confirmation()` |
| `position_sync.close_confirm_window_minutes` | `10` | 平仓确认窗口 | `PositionSyncService._check_close_confirmation()` |
| `position_sync.max_backups` | `20` | 状态备份最大份数 | `PositionSyncService._backup_state_file()` |
| `position_sync.skip_close_on_api_error` | `true` | API 异常跳过删除 | `PositionSyncService.sync()` |
| `logging.level` | `INFO` | 日志级别 | — |
| `logging.log_dir` | `logs` | 日志目录 | — |
| `logging.max_files` | `30` | 日志最大文件数 | — |

### 7.2 飞书群组路由

| 配置 key | chat_id | 用途 |
|----------|---------|------|
| `risk` | `oc_20fcedf0c35035568ea8fa947380f75d` | critical / error 告警 |
| `trading` | `oc_36c8543cea823b7546fcaad55d111f9f` | warning 告警 |
| `management` | `oc_9cf9f141613b4e6a0f34651843cf8b9b` | info 通知 / 状态汇总 |
| `research` | `oc_36c575b6f39a8df3dd75057a96685a21` | 研究相关 |

路由由 `feishu_alert.py` 中 `CHANNEL_MAP` 决定：`critical`/`error` → risk，`warning` → trading，`info` → management。`notify_status_summary()` 固定发往 management。

### 7.3 加载优先级

```
环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET （start_monitor.sh 导出）
    ↓ 覆盖
feishu_alert.py 代码硬编码 fallback （os.environ.get 第二参数）
    ↓ 独立链路
config/monitor_config.json （主配置，scheduler / monitor_core / position_sync 共用）
    ↓ 覆盖
代码内置默认值 （UnifiedMonitor._default_config / position_sync 模块常量 / scheduler 60&5）
```

---

## 8. 错误处理

系统遵循"降级而非崩溃"原则，主要错误处理策略如下：

### 8.1 异常场景

| 场景 | 处理策略 | 实现位置 |
|------|----------|----------|
| 配置文件缺失 | `_load_config()` 回退到 `_default_config()` 内置默认值，监控系统仍可启动 | `monitor_core.py` |
| 适配器加载失败 | `_init_adapters()` 中单个适配器实例化抛异常时，仅记录 error 日志并跳过，不影响其他系统 | `monitor_core.py` |
| 单系统监控异常 | `monitor_all()` 中某适配器 `check_health()` 抛异常时，该系统降级为 `MonitorResult(name, UNKNOWN, "监控异常: {e}")`，不中断后续巡检 | `monitor_core.py` |
| 飞书凭证缺失 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 任一为空时，`FEISHU_CREDENTIALS_VALID = False`，`send_alert()` 与 `notify_status_summary()` 打印 WARN 日志并返回 `None`，不抛异常 | `feishu_alert.py` |
| 飞书 API 调用失败 | `get_token()` / `send_message()` 内 `requests` 调用失败或返回 `code != 0` 时抛 `RuntimeError`，由 `scheduler.run_monitor()` try/except 捕获并打印日志，调度器继续下一轮 | `feishu_alert.py` / `scheduler.py` |
| 持仓同步异常 | `run_position_sync()` 被 try/except 包裹，异常仅打印日志，不影响调度器主循环 | `scheduler.py` |
| 状态文件读取失败 | `load_json()` 在文件不存在或解析失败时返回默认值（空 dict），不抛异常；适配器据此将系统判为 `inf` 空闲时间 → CRITICAL，实现"文件丢失即告警" | `monitor_core.py` |
| OKX API 异常 | `get_exchange_positions()` 返回 `api_healthy=False`，`sync()` 据此跳过所有删除操作（`skip_close_on_api_error`），防止误删 | `position_sync.py` |
| 调度器主循环异常 | 捕获 `KeyboardInterrupt` 优雅退出；捕获其他异常后 `sleep(60)` 继续，避免单次异常导致调度器退出 | `scheduler.py` |

### 8.2 降级机制

```
主流程 ──异常──► 降级流程
─────────────────────────────────────────────────
配置加载失败     → 内置 _default_config()
适配器实例化失败 → 跳过该适配器，其余继续
check_health 异常 → MonitorResult(UNKNOWN)
飞书凭证缺失     → 跳过告警发送（WARN 日志）
飞书 API 失败    → 抛 RuntimeError → scheduler 捕获 → 下一轮重试
OKX API 异常     → 跳过平仓删除（防误删）
状态文件丢失     → 空闲时间=inf → CRITICAL 告警
```

> **注意**：飞书 API 失败时无主动重试机制，依赖调度器下一轮（60 分钟后）自然重试。`get_token()` 每次调用均重新获取 token，不缓存。

---

## 9. 扩展性设计

### 9.1 如何添加新 MonitorAdapter

接入新子系统的监控，只需 3 步：

1. **新增适配器类**：在 `adapters/__init__.py` 中新增 `XxxAdapter` 类，继承 `MonitorAdapter` 接口契约（至少实现 `check_health()`，可选实现 `get_performance()` / `get_trading_stats()` / `get_risk_status()` / `get_core_metrics()`）。

```python
class XxxAdapter:
    def __init__(self, system_name: str, config: Dict):
        self.system_name = system_name
        self.config = config
        self.base_dir = Path(config["base_dir"])
        self.max_idle_minutes = config.get("max_idle_minutes", 240)

    def check_health(self) -> MonitorResult:
        state = load_json(self.base_dir / "data" / "xxx_state.json", {})
        # ... 健康检查逻辑
        return MonitorResult(self.system_name, MonitorStatus.HEALTHY, "运行正常", detail)
```

2. **注册到 adapter_map**：在 `monitor_core.py` 的 `UnifiedMonitor._init_adapters()` 中将类名加入 `adapter_map`。

```python
adapter_map = {
    ...
    "XxxAdapter": XxxAdapter,
}
```

3. **添加配置项**：在 `config/monitor_config.json` 的 `systems` 下新增一项，指定 `adapter`、`base_dir`、`max_idle_minutes`。

```json
"xxx": {
    "enabled": true,
    "base_dir": "/path/to/xxx-system",
    "max_idle_minutes": 240,
    "adapter": "XxxAdapter",
    "description": "XXX 系统"
}
```

### 9.2 如何添加新 PositionSyncAdapter

1. 在 `position_sync.py` 中新增 `XxxSyncAdapter` 类，继承 `PositionSyncAdapter`（抽象基类），实现 8 个抽象方法：`get_system_name()` / `get_coins()` / `load_local_state()` / `save_local_state()` / `get_state_positions()` / `update_position_with_exchange()` / `remove_position()` / `get_additional_info()`。
2. 在 `PositionSyncService.register_default_adapters()` 中注册新适配器。

### 9.3 如何添加新告警类型

1. 在 `feishu_alert.py` 中新增 `notify_xxx()` 函数，调用 `send_alert(alert_type, level, message, details, system)`。
2. 如需在监控主流程触发，在 `monitor_core.send_alerts()` 中增加对应 status / message 关键字的路由分支。

### 9.4 如何接入记忆模块（待办）

当前 `memory/app_memory_interface.py` 已实现完整接口但未接入主流程。接入步骤：

1. 在 `monitor_core.send_alerts()` 发送告警后调用 `OpsMemoryInterface.add()` 沉淀 incident。
2. 在告警触发前调用 `OpsMemoryInterface.find_playbook_for_incident()` 查找匹配预案。
3. 故障恢复后调用 `OpsMemoryInterface.record_incident_resolution()` 记录处理结果。

---

## 10. 云端全链路监控目标架构（v2.0，权威口径）

> 本章为 2026-11-17 调研后的目标架构与决策记录。**云端是系统核心，架构以云端实测为准**；第 1–9 章描述的是本地 v1.0 适配器实现，仅覆盖 yijing/v15/screen/agent_a/agent_b 五个老系统。
> 证据与选型细节：[RESEARCH-全链路监控体系调研-v0.2.md](./RESEARCH-全链路监控体系调研-v0.2.md)

### 10.1 定位与边界

| 项 | v1.0（第 1–9 章，现状） | v2.0（本章，目标） |
|---|---|---|
| 运行位置 | 本地 macOS | 云端 `43.160.201.117`（Linux/systemd + Docker） |
| 监控对象 | 5 个老系统的状态文件 | 主机/容器/端口 + 40/42/43/50/23/48 全链路产物与决策 |
| 判定方式 | 心跳/空闲时长轮询 | Prometheus 规则 + 业务新鲜度 + SLO |
| 告警通道 | 15 内置飞书函数 | Alertmanager → feishu-receiver（复用本模块凭证） |
| 自动动作 | 无 | 仅"冻结/收紧"，无下单权 |

**职责边界**
- 本模块负责：采集、判定、路由、留痕、演练。
- 本模块不负责：交易决策、下单、撤单策略、风控阈值制定；自动冻结只写标记文件，由 13/22/50 既有语义消费。

### 10.2 云端实测基线（2026-11-17）

| 项 | 事实 |
|---|---|
| 主机 | `VM-0-5-ubuntu`，4 vCPU / 15.6GB（可用 10.5GB）/ 178GB（61%），load ≈ 7 |
| 运行时 | nginx；前端 3001/3002；Docker：PG16 / Redis7 / MinIO；约 40 个 systemd 服务 |
| 40 日更 | cron `02:00`；x0 `00:10`；x1 `00:25` |
| 42 总线 | cron `*/15` |
| 43 承接 | systemd timer 每 30min，`CYCLE_STATE_BRIDGE=1` |
| 50 影子 | cron `7,22,37,52` |
| 50 live + 22 | systemd timer 每 5min；最近一轮 `executed=0, skipped=20` |
| 健康检查 | `dreambuddy-healthcheck.timer` 每 5min，11 项检查，连续 3 次失败回滚 |
| 关键缺口 | 健康检查无飞书通知；Redis 恒 `SKIP`；不检查业务产物；无指标栈；15 未在云端部署 |

### 10.3 目标架构

```text
已有 cron / systemd（不改调度）
   ├─ push ──────────────> Pushgateway ─┐
node_exporter（主机）───────────────────┤
blackbox_exporter（HTTP/TCP 探针）──────┼─> Prometheus(9090, 15s)
business-metrics-exporter（只读 JSON）──┘        │
                                                 ├─ rules ─> Alertmanager(9093)
                                                 │              │
                                                 │              └─> feishu-receiver ─> 飞书群
                                                 └─> Grafana(3000，只读，不做告警)
```

**组件职责**

| 组件 | 职责 | 不做什么 |
|---|---|---|
| Prometheus | 采集、时序存储、告警规则判定（唯一判定源） | 不负责通知路由 |
| Alertmanager | 分组、去重、抑制、静默、`repeat_interval`、升级 | 不做业务判定 |
| Grafana | 排障面板、历史趋势 | 不配置告警规则（避免双引擎） |
| node_exporter | CPU/内存/磁盘/负载/文件系统 | 不读业务文件 |
| blackbox_exporter | HTTP/TCP 黑盒探针（3001/3002/8093-8099/8771/8765/PG/Redis） | 不做业务语义校验 |
| Pushgateway | 接收 oneshot/cron 任务的成功、耗时、记录数 | 不替代长期指标 |
| business-metrics-exporter | 只读扫描 40/42/43/50/23/48 产物，暴露 `/metrics` | 不写交易文件、不触发交易 |
| feishu-receiver | 解析 Alertmanager webhook，复用 `feishu_alert.py` 发卡片 | 不自行判定级别 |

**部署约束**：Docker Compose，镜像固定版本；除 Grafana（nginx 子路径 + 认证）外全部绑定 `127.0.0.1`；配置与规则纳入 git。

### 10.4 探针分层

| 层 | 探针 | 典型指标 |
|---|---|---|
| L0 主机/容器 | node_exporter、cAdvisor（可选） | CPU、内存、磁盘、容器重启次数 |
| L1 端口/接口 | blackbox_exporter | `probe_success`、响应时间、证书剩余天数 |
| L2 调度/任务 | Pushgateway | `push_time_seconds`、`job_duration_seconds`、`job_records_total` |
| L3 业务产物 | business-metrics-exporter | `artifact_age_seconds`、`artifact_records`、`schema_violations` |
| L4 决策/交易 | business-metrics-exporter + PG | `decision_count_24h`、`order_reject_rate`、`reconcile_break`、`notional_over_domain_cap` |
| L5 元监控 | Watchdog 规则 + 外部心跳 | 监控自身心跳缺失、规则加载失败 |

### 10.5 新鲜度 TTL 矩阵（云端节奏）

| 链路 | 节奏 | TTL | 未达判定 |
|---|---|---|---|
| 40 日更 / x0 / x1 | 每日 00:02 / 00:10 / 00:25 | 26h | 03:00 未成功 → P1；48h → P0 |
| 42 总线 | 15min | 45min | 连续 2 周期无推送 → P1 |
| 43 承接 | 30min | 90min | 连续 2 周期无产物 → P1 |
| 50 影子 | 15min | 60min | 连续 2 周期无决策 → P1 |
| 50 live + 22 | 5min | 15min | 连续 3 轮无运行 → P0 |
| 健康检查 | 5min | 15min | 心跳缺失 → P0 |
| 48 指标 | 每日 06:10 | 26h | 缺更 → P2 |

### 10.6 告警分级与治理

| 级别 | 语义 | 路由 | 响应 | 升级 |
|---|---|---|---|---|
| P0 | 资金/合规/失控或监控自身死亡 | Trading-RiskControl + @all | 5min 确认 | 10min 未确认重发（≤3 次）→ 电话 |
| P1 | 链路断点/决策受损 | Trading-Desk | 30min | 2h 未处理升级 |
| P2 | 降级/漂移/趋势 | Trading-Desk | 当日 | 次日复盘 |
| P3 | 摘要/周报 | Trading-Management | 无需即时 | 周会 |

**治理规则**
1. 指纹去重：30min 冷却；未恢复每 6h 复报；恢复发"已恢复"。
2. 静默窗口：发布/维护可静默 P2/P3，**P0 永不禁默**。
3. Runbook 强绑定：无 runbook 的规则不得进 P0/P1。
4. 单出口：告警只能经 Alertmanager → feishu-receiver；`6-TRADING/scripts/feishu_notify.py` 仅业务通知。
5. 元监控：每 5min 外发心跳，缺失即 P0。

### 10.7 决策记录（D1–D6）

| # | 决策 |
|---|---|
| D1 | 云端单机标准栈：Prometheus + Alertmanager + Grafana + node_exporter + blackbox_exporter + Pushgateway；不自研底座、不引入第二套调度 |
| D2 | 自动动作只覆盖"重复下单/未授权 live/对账不平>15min/越界名义"，写冻结标记交 13/22/50 既有 kill-switch 消费；前 4 周只告警 |
| D3 | TTL 与"没跑"判定按 §10.5，统一用 `push_time_seconds` |
| D4 | 告警单出口；业务通知与告警以 `channel=alert|business` 区分 |
| D5 | 23 与 50 保留分域名义上限，不强行统一；统一配置、下单前校验、越界 P0 |
| D6 | 单人最小 on-call，不建轮值表；依靠自动冻结降低即时人工依赖 |

### 10.8 实施阶段与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0（Day 1–2） | Compose 起标准栈；node/blackbox 接入；基线面板 | 主机/端口异常 5min 内可见 |
| P1（Day 3–5） | business-metrics-exporter；40/42/43/50/23 产物探针；Pushgateway 接入 cron | 停 40 流水线、停 15、伪造对账不平，三类告警均触发 |
| P2（第 2 周） | 12 条规则 + 路由 + feishu-receiver；三次演练；调阈值 | P0 端到端 <5min；误报率 <5% |
| P3（后续） | 模型漂移（Evidently）、TCA、对账归因 | IC/PSI 入看板；单笔可归因到 decision_id |

**首批 12 条规则**：元监控心跳、NN live 未运行、40 日更失败/迟到、产物 stale、总线源缺失、metrics 不一致、50 决策静默、degraded 洪水、对账 break、名义越界、日回撤越限、模型性能衰减。

### 10.9 与现有代码的关系

| 变更 | 是否触碰交易代码 |
|---|---|
| 新增 Compose/规则/面板/feishu-receiver/exporter | 否 |
| 各 cron/systemd 任务末尾推送一次指标 | 极小（追加一行 curl） |
| `health-check.sh` 扩展业务产物检查、Redis 容器内探测、失败通知 | 小（本模块职责内） |
| 自动冻结标记的消费 | 复用 50 `50_KILL_SWITCH`、13 fail-closed、22 执行器既有逻辑，不新增权限 |

### 10.10 已知缺口（本章落地前）

1. 云端 `15-监控告警系统` 未部署，飞书凭证与告警路由需在云端配置。
2. `dreambuddy-healthcheck` 无通知、Redis 恒 SKIP，需先修。
3. 50 生产账本存在测试 symbol（`BTC-FLAP-PAYLOAD`），需在 exporter 侧做 symbol 白名单与告警。
4. 23 `1600 USDT` 名义是否为预期待确认；未确认前按 P1 观察。

---

## 11. 3+3 全景监控架构（分期演进，v2.1）

> 口径引用：[3+3 架构模块映射](../../1-ARCHITECTURE/3+3架构模块映射.md) v1.2（L0/L1/L2 × 交易/训练/产品三链）。本模块（15）自身位于 **L1-C 确定性服务层**，同时承担全矩阵的监控平台职责。

### 11.1 监控对象矩阵（3 层 × 3 链 + 横切）

| | 交易框架链（49） | 模型训练链（34+48） | 产品能力链（3.1/52/6/7/8/53） |
|---|---|---|---|
| **L0 基础能力** | 18–21 数据、9/10/39 输入、4 记忆 | 样本/特征/PIT、48 事件流 | 7 产物中台、8 飞书、0/2 文档知识 |
| **L1 基础智能** | 11/12/14/17/29、40/43、42、50/23、13/16/22/51、**15** | 回测/评估指标、54 L1 聚合 | 6 中台、7 产物、8 飞书、10 查询 |
| **L2 大模型驱动** | 1 SACG→DSH、32 辩论、25 策略生成、48 涌现、23 LLM 分支 | 34 训练编排、3-EVOLUTION | 3.1 前端、52/53、30 E2E |

**横切**（不占格）：0 文档、2 知识/治理、4 记忆、5 业务、47 MCP 治理。

### 11.2 分期覆盖

| 期 | 范围 | 判定标准 |
|---|---|---|
| **一期（当前，2026-11）** | **23 推理信号链**：信号生成→契约→提交→22 网关→13 风控→成交/回报；含 18 数据入口 | 信号生命周期 8 步全部可观测，交易格 ≥ M3；23 信号 schema 一致率 ≥99% |
| **二期** | **40 主神经网络闭环**（48→40→43→42→50→执行→反馈） | 节点级新鲜度、总线契约、决策可用率；详见 §4.1 与 §10.5 |
| 三期 | 训练链（34/48/23 进化训练与基因准入） | 样本新鲜度、训练成功率、影子一致率、晋升门禁 |
| 四期 | 产品链（3.1/6/7/8/53） | 核心接口时延/错误率、关键用户旅程、飞书送达 |
| 五期 | 横切治理（0/2/4/5/47） | 文档索引健康、认知服务、MCP 注册表 |

一期**不覆盖 40/42/50 的深度业务监控**（只保留 L0 存活探针），避免与二期重复建设；40 的新鲜度与链路契约顺延到二期。

一期**不追求全矩阵深度**：非交易格只做"存在性 + 存活 + 新鲜度"，避免监控本身膨胀。

### 11.3 可管理机制（核心）

1. **单一注册表**：[config/domains.yaml](../config/domains.yaml)。每个格登记 `id / chain / layer / owner / phase / criticality / maturity / modules / probes / slo / dashboards / runbook`；新增覆盖 = 改注册表 + 加探针 + 加规则，不改告警代码。
2. **统一标签**：所有业务指标带 `chain / layer / cell / module`；与 OpenTelemetry 对齐（`service.namespace=chain`、`service.name=cell`），便于后续接 trace/log 时不改口径。
3. **成熟度分档**（按格推进，不按整系统推进）：
   `M0 未接入 → M1 存活 → M2 新鲜度 → M3 契约 → M4 业务 SLO → M5 模型与进化`
4. **一格一 owner**：告警路由按 `cell` 映射到飞书群；避免后期全局覆盖时重排路由。
5. **三张链看板 + 一张 3×3 热力图**：`dreambuddy_cell_health` 由 exporter 按 maturity 与未恢复告警计算，热力图 `max by (cell)`。
6. **治理节奏**：月度覆盖率核对（注册表 vs 实际探针）、季度 SLO 复盘；变更写入 `CHANGELOG.md`。

参考实践：服务目录与 owner 单点登记、按域汇总 SLO、告警策略版本化（[SUSE Observability Architecture](https://www.suse.com/ko-kr/blogs/2025/10/what-is-observability-architecture-and-how-do-you-build-it/)）；语义约定 `service.name/service.namespace`（[OpenTelemetry Service](https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/)）。

### 11.4 与已建骨架的关系（不过度设计）

- Compose、Prometheus 规则、Alertmanager 路由**不变**；一期只新增 `config/domains.yaml` 与 exporter 的 4 个标签。
- 当前规模（单机、<50 任务）手工维护 job 与规则即可；当格数/探针数翻倍后，再由注册表生成 Prometheus `file_sd` 与规则，不提前引入服务网格或多级联邦。
- 明确不做：多 Prometheus 联邦、自研 CMDB、第二套告警引擎、非交易域的深度业务探针。

### 11.5 一期验收（在 §10.8 之上追加）

1. `domains.yaml` 中 9 格 + 横切全部有 owner、phase、maturity。
2. 交易列三格（L0/L1/L2.trade）均 ≥ M3，且对应告警可在演练中触发。
3. 3×3 热力图能显示每格健康度与最后更新时间。
4. 新增一个格（示例：L2.train）只需改注册表 + 加一个探针即可出现，无需改告警代码。

---

## 12. 一期：23 推理信号监控（v2.2）

> 依据：`23-四层闭环自进化交易架构/docs/TECHNICAL_DESIGN.md`、`docs/ENGINEERING_INDEX.md`、`49-交易框架协议/contracts/final_decision_signal.v1.1.json`，以及 2026-11-17 代码与云端实测。
> 定位：一期只监控 **23 的信号生命周期与执行落地**；40 主神经网络闭环顺延二期（§11.2）。

### 12.1 23 模块全景（监控边界）

| 层 | 模块/职责 | 关键文件 | 监控关注 |
|---|---|---|---|
| L1 状态空间 | 观察行情、矛盾样本、案例 | `evolution_pipeline.py`、`core/*` | 样本新鲜度、样本增长率 |
| L2 推断/路径 | 矛盾识别、最小阻力、路径发现、WFO/配置 | `core/primary_contradiction_detector.py`、`path_discovery_service.py`、`dominance.py` | 路径数、冠军路径、降级次数 |
| L3 实验/影子 | Shadow-RL、影子验证、自动放量门禁 | `core/shadow_rl.py`、`shadow_activation_gate.py` | 样本增量、Phase3 激活、门禁推进 |
| L4 反思/回馈 | CS/ESS、权重调整、基因准入 | `engines/reflection_engine.py`、`auto_weight_adjuster.py`、`ftc_gene_innovation.py` | CS 分布、权重变更、基因晋升/淘汰 |
| 执行出口 | 构造并提交 FinalDecisionSignal | `execution/decision_signal.py`、`outbox.py`、`entry_loop.py`、`exit_loop.py` | **一期核心**：信号生成、提交、状态机 |
| 数据入口 | 18 行情 + 19 DAL 衍生数据 | `scripts/entry_runner.py`、`scripts/backfill_*.py` | 数据新鲜度、空数据、fallback |
| 引擎族 | 趋势/网格/离场/事件驱动 | `engines/trend_following|grid_trading|exit_engine|kline_event_handler.py` | 引擎心跳、离场触发 |

### 12.2 推理信号契约（v1.1）与实测差异

**契约要求**（`49-交易框架协议/contracts/final_decision_signal.v1.1.json` L8-20、L78-92）：顶层必填 `signal_id/source/ts/symbol/direction/confidence/horizon/risk_exposure_hint/expires_at/mode/payload`；`source∈{23-evolution,50-nn,l1-chart}`；23/50 的 `payload` 必填 `action/position_tier/position_mult/d_star/ri/l4_v/regime/primary_contradiction/contradiction_shift/elastic_result/cross_validation/path`。

**23 实际输出**（`execution/decision_signal.py` L108-133、L154-173）：

| 契约字段 | 23 实际 | 结论 |
|---|---|---|
| `horizon` | 缺失 | ❌ 不符合 |
| `risk_exposure_hint` | 缺失 | ❌ 不符合 |
| `mode` | 缺失 | ❌ 不符合 |
| `payload.position_tier/position_mult` | 用 `tier` 代替 | ❌ 命名与语义漂移 |
| `payload.d_star/ri/l4_v/regime` | 缺失 | ❌ 不符合 |
| `payload.primary_contradiction/contradiction_shift/elastic_result/cross_validation/path` | 缺失 | ❌ 不符合 |
| `action/pos_side/sl_px/tp_px` | 放在顶层 | 🟡 执行扩展，未按契约进 payload |
| `decision_id` | 顶层 + payload 双写 | ✅ 符合（22 硬前置依赖） |

**结论**：23 当前是"可执行扁平信号"，不是 v1.1 契约信号。22 网关 `FinalDecisionSignal`（L43-107）也只映射核心字段，且**未做 JSON Schema 校验**，因此契约漂移不会被任何一层拦截。这是本期监控必须补的第一类"契约监控"。

### 12.3 信号生命周期 8 步与监控点

| # | 阶段 | 代码/产物 | 监控指标 |
|---|---|---|---|
| S1 | 数据就绪 | 18 `data_center.db`、19 DAL | `data_age_s`、`rows_delta`、`empty_ratio` |
| S2 | 推理产出 | `build_entry_decision` / `build_exit_decision` | `signal_generated_total{symbol,action}`、`confidence` 分布 |
| S3 | 契约校验 | 当前**缺失**（建议新增） | `signal_schema_valid_ratio`、`missing_fields` |
| S4 | 审计落盘 | `runtime/execution_decisions.jsonl`（仅 `stage=submit`） | `audit_lag_s`、`audit_rows`、`audit_write_fail` |
| S5 | 发件箱 | `runtime/execution_outbox.db`（SQLite：pending/submitting/submitted/filled/failed） | `outbox_stuck_s`、`retry_exhausted_total`、`duplicate_total` |
| S6 | 网关提交 | `EvolutionSignalDispatcher.dispatch` → 22 `submit()` | `signal_to_gateway_latency_p95`、`precheck_reject_total` |
| S7 | 风控与成交 | 13 `PreTradeGate` → 16 → 22 → 51 | `risk_reject_total`、`rules_evaluated=0`、`filled_ratio`、`slippage_bps` |
| S8 | 回报与反馈 | 成交/PnL → 23/48 | `decision_fill_join_ratio`、`pnl_feedback_age_s` |

**关键缺口**：S3 无校验、S4 只记录提交不记录结果、S5 状态在 SQLite 不可直接 tail。监控侧需新增只读导出（SQLite 查询 + audit 双写），不改交易逻辑。

### 12.4 信号级 SLO 与告警（一期首批）

| 指标/告警 | 判定 | 级别 |
|---|---|---|
| `SignalSchemaViolation` | 任一信号缺 v1.1 必填字段 | P1（观察期）/ 阻断待定 |
| `SignalSilence` | 交易时段 30min 无新信号（`entry23` active 且非空仓） | P1 |
| `SignalExpiredAtSubmit` | `expires_at < now` 仍提交 | P1 |
| `DryRunMismatch` | 期望 live 但 `--dry-run`/`EVOLUTION_ENTRY23_ENABLED=off` | P0（若已宣称实盘） |
| `GatewayRejectSpike` | 15min 拒绝率 >5% | P1 |
| `RiskGateEmpty` | `rules_evaluated=0` 仍放行 | P0 |
| `OutboxStuck` | `submitting` 超过 5min | P1 |
| `DuplicateDecisionSpike` | 15min 重复 decision_id >1% | P2 |
| `DecisionFillJoinLow` | 成交→decision_id join <95% | P1 |
| `ConfidenceDegenerate` | 置信度方差≈0 或长期 <0.3 | P2 |
| `SignalToOrderLatency` | p95 >2s（同机应 <200ms） | P2 |
| `NotionalOverDomainCap` | 23 名义 > 配置上限 | P0 |

SLO 建议：信号 schema 一致率 ≥99%；信号→网关 p95 ≤2s；成交 join ≥95%；对账 15min 清零。

### 12.5 实现一致性审计（文档 vs 代码，2026-11-17）

| 声明 | 代码证据 | 状态 |
|---|---|---|
| 18 行情 → 23 pipeline | `23/dreambuddy_evolution/scripts/entry_runner.py` L4-5、L30、L43、L85-104 引用 `18-数据获取中心/data_center.db` 与 `market_compat` | ✅ 已落地 |
| 19 DAL 衍生数据供 23 | `scripts/backfill_funding_rate.py`、`backfill_etf_flow.py`、`backfill_stablecoin_tvl.py` 写 `19-DAL mm_metrics` | 🟡 仅回补脚本可见，运行时消费需另证 |
| 23 产出 FinalDecisionSignal 并提交 22 | `execution/decision_signal.py` L176-238 `EvolutionSignalDispatcher.dispatch → gateway.submit` | ✅ 已落地 |
| 全部 live 下单强制经 13 风控 | `22/trade_execution_gateway.py` L259-270、L746-756；`_CLOSE_ACTIONS` 例外仅平仓 | ✅ 已落地 |
| 23 信号符合 v1.2 | `build_entry_decision/build_exit_decision` 已输出 `ts/horizon/risk_exposure_hint/mode` 与 payload 12 字段；顶层 7 个执行扩展已在 v1.2 登记；契约测试通过 | ✅ 已落地（2026-11-17） |
| 22 校验 v1.2 契约 | 22 仍只做 `decision_id` + `expires_at` 前置，无 JSON Schema；`from_dict` 已兼容 payload 回退 | ❌ 未落地（下阶段） |
| 42 总线校验 v1.2 | `42/signal_bus.py` 要求 `horizon/risk_exposure_hint`；23 现已具备但直连 22，不经过 42 | 🟡 键已具备，通路未接 |
| 成交必须回带 decision_id | 22 dataclass 保留 `decision_id`（L55-57）；23 审计已携带完整 signal 与 decision_id（L206-220） | ✅ 已落地 |
| 云端 23 实盘运行 | 2026-11-17 12:18 已切换：unit 去掉 `--dry-run`、`EVOLUTION_ENTRY23_ENABLED=on`；凭据库 `simulated=false/dry_run=false`；切换前权益 2118 USDT、可用 919 USDT、持仓 0 | ✅ **live（前 2 周仅告警）** |
| 23 运行时活跃 | 云端 `runtime/execution_decisions.jsonl` 252KB，mtime 2026-11-17 12:06 | ✅ 活跃 |
| 50 决策符合 v1.1 | `50/runtime/decisions.jsonl` 最新 `symbol=BTC-FLAP-PAYLOAD`，缺 `risk_exposure_hint` | ❌ 测试数据 + 契约漂移 |

**最危险的 3 个偏差**
1. **契约已补齐但无人阻断**：23 生产者已按 v1.2 输出完整字段，22 仍只查两个前置；监控可发现漂移，但执行层不会拦截。
2. **静默失败不可见**：23 入口过去长期 `--dry-run`，但缺少"期望模式 vs 实际模式"指标，容易被误判为"实盘在跑"（已于 2026-11-17 切换 live 并纳入 `DryRunMismatch`）。
3. **审计链路不闭环**：只有 `submit` 阶段，没有 `rejected/filled` 结果；outbox 在 SQLite，文件监控看不到状态机。

**2026-11-17 实盘切换记录**
- 变更：`dreambuddy-entry23.service` 移除 `--dry-run`，`EVOLUTION_ENTRY23_ENABLED=off → on`；凭据库本就为真实模式（`simulated=false`、`dry_run=false`）。
- 切换前预检：账户权益 2118.10 USDT，可用 919.05 USDT，冻结 1200.19 USDT，永续持仓 0；23 单笔名义硬顶 2000 USDT，日志近期均为 `action=WAIT`。
- 监控策略：2026-11-17 至 2026-12-01 为 **alert_only**，不自动冻结/不阻断；到期复核误报率后再决定是否启用自动动作。

### 12.6 一期验收（在 §11.5 上收敛）

1. 23 信号 8 步全部有指标；`SignalSchemaViolation` 能对现有扁平信号触发。
2. 能区分 `dry-run / paper / live`，并发出 `DryRunMismatch`。
3. outbox 任一状态停留 >5min 可见；重复 decision_id 可见。
4. 一笔信号可完整追溯：`decision_id → 审计 → 网关 → 13 风控 → 成交 → join`。
5. 40 链只保留存活探针，不纳入一期告警路由。

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-08-02 | 初始版本：按 DOC_STANDARD §3.2 补建技术设计文档，覆盖概述/架构/算法/数据流/接口/状态/配置/错误处理/扩展性 9 章节 |
| v2.6 | 2026-11-17 | 23 契约补齐 v1.2：ts/horizon/risk_exposure_hint/mode + payload 12 字段；v1.2 登记顶层执行扩展并扩展 action 枚举；审计携带完整 signal；导出器按 payload 校验并消除无信号误报 |
| v2.0 | 2026-11-17 | 新增第 10 章「云端全链路监控目标架构」：云端实测基线、Prometheus 标准栈、TTL 矩阵、P0–P3 治理、D1–D6 决策、实施阶段；第 1–9 章降级为本地 v1.0 现状描述 |
| v2.1 | 2026-11-17 | 新增第 11 章「3+3 全景监控架构」：三层×三链矩阵、四期覆盖、`config/domains.yaml` 注册表、M0–M5 成熟度与一格一 owner |
| v2.2 | 2026-11-17 | 一期收敛为 23 推理信号链；新增第 12 章：23 模块全景、v1.1 契约与实测差异、8 步生命周期、12 条信号告警、落地审计（含 22 无 Schema 校验、云端 dry-run、审计不闭环） |

---

**文档版本**: v2.2
**最后更新**: 2026-11-17

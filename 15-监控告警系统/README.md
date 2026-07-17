# 15-监控告警系统

## 概述

统一监控告警系统，为所有交易子系统提供统一的健康监控和飞书告警推送能力。

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      统一监控告警系统                           │
├─────────────────────────────────────────────────────────────────┤
│  scheduler.py       ── 定时调度器（每60分钟执行）               │
├─────────────────────────────────────────────────────────────────┤
│  monitor_core.py    ── 监控核心                               │
│  ├── UnifiedMonitor  ── 统一监控管理器                        │
│  ├── MonitorResult   ── 监控结果对象                          │
│  └── MonitorAdapter  ── 监控适配器基类                        │
├─────────────────────────────────────────────────────────────────┤
│  feishu_alert.py    ── 飞书告警模块                           │
│  ├── send_alert()        ── 通用告警                          │
│  ├── notify_heartbeat_timeout()                              │
│  ├── notify_trading_halted()                                 │
│  ├── notify_position_close()                                 │
│  ├── notify_system_error()                                   │
│  └── notify_status_summary()                                 │
├─────────────────────────────────────────────────────────────────┤
│  adapters/__init__.py  ── 系统适配器                          │
│  ├── YijingAdapter   ── 易经推理系统                         │
│  ├── V15Adapter      ── V15经典马丁策略                      │
│  ├── ScreenAdapter   ── 三屏趋势系统                         │
│  ├── AgentAAdapter   ── Agent A                             │
│  └── AgentBAdapter   ── Agent B                             │
├─────────────────────────────────────────────────────────────────┤
│  config/monitor_config.json  ── 监控配置                      │
└─────────────────────────────────────────────────────────────────┘
```

## 监控系统列表

| 系统 | 适配器 | 状态文件 | 心跳阈值 |
|------|--------|----------|----------|
| yijing | YijingAdapter | guardian/heartbeat.json | 30分钟 |
| v15 | V15Adapter | data/v15_state.json | 240分钟 |
| screen | ScreenAdapter | data/screen_trade_state.json | 240分钟 |
| agent_a | AgentAAdapter | logs/agent_a/*.json | 240分钟 |
| agent_b | AgentBAdapter | logs/agent_b/*.json | 240分钟 |

## 告警级别

| 级别 | 颜色 | 推送群组 | 触发条件 |
|------|------|----------|----------|
| critical | 🔴 | 风控审批 | 心跳超时/交易暂停/进程异常 |
| error | 🟠 | 风控审批 | 模型异常/系统错误 |
| warning | 🟡 | 交易台 | 连续亏损/性能下降 |
| info | 🔵 | 管理看板 | 状态汇总/正常通知 |

## 核心指标

每个系统监控以下核心指标：

- **健康状态**：进程运行/心跳时间/空闲时长
- **性能指标**：交易数/胜率/盈亏比/夏普比率
- **交易统计**：持仓数/方向/标的
- **风险状态**：连续亏损/风控暂停/参数配置
- **运行态**：模型版本/策略类型/运行模式

## 配置

```json
{
  "systems": {
    "yijing": {
      "enabled": true,
      "base_dir": "/path/to/11-易经推理系统",
      "max_idle_minutes": 30,
      "adapter": "YijingAdapter"
    }
  },
  "alert": {
    "enabled": true,
    "feishu_enabled": true
  },
  "scheduler": {
    "enabled": true,
    "interval_minutes": 60
  }
}
```

## 启动

```bash
cd 15-监控告警系统
bash start_monitor.sh
```

## 手动执行

```bash
python3 monitor_core.py
```

## 飞书群组

| 群组 | chat_id | 用途 |
|------|---------|------|
| 风控审批 | oc_20fcedf0c35035568ea8fa947380f75d | critical/error 告警 |
| 交易台 | oc_36c8543cea823b7546fcaad55d111f9f | warning 告警 |
| 管理看板 | oc_9cf9f141613b4e6a0f34651843cf8b9b | info 通知/状态汇总 |
| 研究 | oc_36c575b6f39a8df3dd75057a96685a21 | 研究相关 |

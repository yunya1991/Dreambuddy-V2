# 15-监控告警系统

> **状态（2026-11-17）**
> - 本 README 与下方架构描述的是**本地 v1.0**：仅覆盖 yijing/v15/screen/agent_a/agent_b，最后运行日志为 2026-08-07。
> - **云端全链路监控目标架构以 [docs/TECHNICAL_DESIGN.md 第 10 章](docs/TECHNICAL_DESIGN.md) 为准**（Prometheus 标准栈 + 业务新鲜度 + 飞书单出口）。
> - 调研证据与 D1–D6 决策：[docs/RESEARCH-全链路监控体系调研-v0.2.md](docs/RESEARCH-全链路监控体系调研-v0.2.md)。

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

## 每日监控日报（23 核心链路）

云端每日 09:00（Asia/Shanghai）由 systemd timer 自动汇总最近 24h 的 23 推理链监控数据，先用规则引擎识别确定性异常，再调用大模型做归因分析，最后推送飞书并落盘报告。本地只做开发验证，手动执行、不装定时。40 周期神经网络链路为预留项，接口已保留但本期不启用。

```bash
# 手动生成（滚动 24h）
python3 scripts/daily_insight.py --push

# 指定自然日
python3 scripts/daily_insight.py --date 2026-11-17 --no-llm

# 仅规则分析，不调用大模型
python3 scripts/daily_insight.py --no-llm
```

| 项 | 路径/配置 |
|---|---|
| 聚合与规则 | `scripts/daily_insight.py` |
| 阈值/LLM/预留链路 | `config/daily_insight.json`（`enabled_chains: ["23"]`，加入 `"40"` 即启用） |
| 报告 | `logs/daily-insight/YYYY-MM-DD.md` + `.json` |
| 本地执行 | 仅手动验证，不安装定时 |
| 云端定时（生产） | `deploy/systemd/dreambuddy-daily-insight.service/.timer`（09:00 Asia/Shanghai） |
| 大模型 | DeepSeek（`DEEPSEEK_API_KEY`，优先环境变量/`/etc/dreambuddy-monitoring/monitoring.env`，其次仓库 `.env`） |
| 推送 | 优先本地 receiver `:9098`，不可用时直连飞书 management 群 |

## 模型用量告警（LLM 余额/消耗）

云端每小时抓取 DeepSeek 余额接口（覆盖全部调用方的真实消耗，不依赖埋点），推算 24h 消耗、7 日均消耗与可用天数，异常推飞书；同一告警 6h 内去重。本地手动验证。

```bash
# 检查并按需推送
python3 scripts/model_usage_check.py --push

# 只检查（不推送、不写去重状态）
python3 scripts/model_usage_check.py --dry-run --json
```

| 告警 | 级别 | 触发条件 |
|---|---|---|
| `*_unavailable` | P1 | 余额接口 401/不可用、所有候选 key 失效、`is_available=false` |
| `*_balance_low` | P1 | 余额 ≤ `min_balance`（默认 ¥10） |
| `*_balance_warn` | P2 | 余额 ≤ `warn_balance`（默认 ¥20） |
| `*_days_remaining` | P2 | 按 7 日均消耗可用天数 < 3 天 |
| `*_burn_spike` | P2 | 24h 折算消耗 ≥ 7 日均值 3x（需 ≥3 天基线） |

| 项 | 路径/配置 |
|---|---|
| 检查脚本 | `scripts/model_usage_check.py` |
| 阈值/供应商 | `config/model_usage.json`（新增供应商按 `type` 扩展；Qwen 无余额接口待接埋点） |
| 余额快照 | `logs/model-usage/balance-<provider>-YYYYMMDD.jsonl`（保留 14 天） |
| 云端定时 | `deploy/systemd/dreambuddy-model-usage.service/.timer`（每小时） |
| 凭证 | 环境变量/`/etc/dreambuddy-monitoring/monitoring.env` 优先，其次按 `env_files` 顺序回退，401 自动跳过失效 key |

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

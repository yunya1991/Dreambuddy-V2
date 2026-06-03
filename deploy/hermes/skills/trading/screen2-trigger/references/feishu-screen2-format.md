# feishu_notify.py screen2 格式要求

## 依赖文件

`feishu_notify.py screen2` 读取以下文件：

### 1. meta.json（必需，session 根目录）
```json
{
  "session_id": "YYYYMMDD-BTC-SCREEN2",
  "screen1_direction": "SHORT",
  "screen1_price": 73349,
  "screen1_score": 48,
  "btc_price_at_analysis": 72000,
  "date": "YYYY-MM-DD"
}
```
- `session_id`: 用于生成 GitHub URL 和卡片标题
- `screen1_direction`: 回退字段，当 daily-presets.json 缺少 `direction` 时使用

### 2. team-a/screen2/daily-presets.json（必需）
feishu 读取字段（通过 presets.get 链式回退）:
| feishu 读取 | 第一选择 | 第二选择 | 回退 |
|------------|---------|---------|------|
| direction | presets.direction | — | meta.screen1_direction |
| entry | presets.entry_price | presets.entry | "?" |
| tp | presets.take_profit | presets.tp | "?" |
| sl | presets.stop_loss | presets.sl | "?" |
| layers | grid.max_layers | presets.max_layers | "?" |
| interval | grid.interval_pct | presets.interval_pct | "?" |

### 3. team-a/screen2/martingale-grid.json（必需）
需要字段:
- `max_layers`: 马丁格层数
- `interval_pct`: 加仓间隔百分比

## 输出目标
- 推送群: 交易部-交易台 (chat_id 硬编码在脚本中)
- 卡片模板: `purple` (screen2 使用紫色主题)

## 常见故障

| 错误 | 原因 | 修复 |
|------|------|------|
| `No such file or directory: '.../meta.json'` | meta.json 未创建 | 在 session 根目录写入 meta.json |
| 卡片字段显示 `?` | daily-presets.json 缺少关键字段 | 确保包含 direction, entry_price, take_profit, stop_loss |
| `[ERROR] screen2:` + 文件未找到 | session_dir 路径错误 | 使用相对于 Dreambuddy-V2 根目录的路径 |

## feishu_notify.py task 模式
```
python feishu_notify.py task screen2_done <session_dir>
```
- 创建飞书任务 "[Screen2] 日线预设 — {session_id}"
- session_dir 格式同 screen2 模式

## 通信故障排查

如果飞书通知不工作或 Hermes Bot 无法通信，参考 `feishu-hermes-debug` SKILL 中的完整诊断流程。

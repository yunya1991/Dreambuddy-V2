# Trading Episodes 多维表格字段定义

App Token: `CMlnbvAKYafUL0sxLpFcxNfVnoc`
Table ID: `tblSDdfk2sbBAVsr`
URL: https://icnic28nu1x5.feishu.cn/base/CMlnbvAKYafUL0sxLpFcxNfVnoc

---

## 字段清单

| 字段名 | Field ID | 类型 | 说明 | 写入时机 |
|--------|----------|------|------|---------|
| Session ID | `fld6JmeIZa` | 文本 | 主键，如 20260602-BTC-SCREEN1 | Screen1/3 完成 |
| Episode ID | `fldyEVv4dE` | 文本 | Hermes session ID | Screen3 完成 |
| Date | `flduqhxPcM` | 日期 | 执行日期 | Screen1 完成 |
| Direction | `fld5ycAKVc` | 单选 | SHORT/LONG | Screen1 完成 |
| Gate C Result | `fldjlMjT5A` | 单选 | PASS/SKIP/FAIL | Screen3 完成 |
| Clock Stage | `fld1TMgHWn` | 单选 | 美林时钟象限 | Screen1 完成 |
| Screen1 Score | `fldCUmkrEy` | 数字 | 0-100 | Screen1 完成 |
| Skill Regime | `fldILBDcSW` | 单选 | WEAK_BEAR 等 | Screen1 完成 |
| Entry Price | `fldqKUNReS` | 数字 | 入场价 USDT | Screen3 入场 |
| Signal Score | `fldNsqESJL` | 数字 | 8维信号评分 % | Screen3 完成 |
| Martin Layers | `fldxlUW9y8` | 数字 | 马丁层数 | Screen3 入场 |
| Position Cap USDT | `fld5HYNLCb` | 数字 | 仓位上限 | Screen2 完成 |
| Exit Price | `fldQaw2TOI` | 数字 | 离场价 | A9 离场 |
| Realized PnL | `fldTGOgxVR` | 数字 | 已实现盈亏 USDT | A9 离场 |
| PnL Pct | `fldDm6cMhX` | 数字 | 盈亏百分比 % | A9 离场 |
| Exit Reason | `fldWLnuhrx` | 文本 | 离场原因 | A9 离场 |
| A8 Score | `fldjiK1euP` | 数字 | 复盘得分 0-100 | ProcessD 完成 |
| Red Team Flag | `fldtD5QX1S` | 复选框 | 红队触发标志 | Screen1 完成 |
| Notes | `fld7bavHDa` | 文本 | 备注 | 任意时机 |
| GitHub URL | `fldndmNMLM` | 超链接 | Session 文件链接 | Screen1 完成 |

## 自动化 Workflow

| 触发 | 条件 | 动作 | 目标群 |
|------|------|------|-------|
| 新增记录 | 无 | 发消息（Session ID + 方向 + Gate-C + Score） | Trading-Desk |
| 记录更新 | Exit Price 不为空 | 发消息（PnL + A8 + 离场原因） | Trading-Management |

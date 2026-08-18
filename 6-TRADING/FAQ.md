# 6-TRADING 常见问题 (FAQ)

> **版本**: v2.0
> **日期**: 2026-05-16
> **范围**: 配置、策略、自动化、回测、SKILL、工程

---

## 一、配置问题

### Q1: 如何配置API Key？

详见 **[API_CONFIG_GUIDE.md](API_CONFIG_GUIDE.md)**

核心环境变量:
```bash
export TAVILY_API_KEY="tvly-xxxxxxxxxxxx"  # A1调研
export OKX_API_KEY="your_okx_api_key"      # OKX实盘
export OKX_SECRET_KEY="your_okx_secret_key"
export OKX_PASSPHRASE="your_passphrase"
```

### Q2: Tavily搜索失败怎么办？

1. 检查环境变量: `echo $TAVILY_API_KEY`
2. 验证API Key有效性: 访问 [Tavily Dashboard](https://app.tavily.com)
3. 检查额度: 免费版每天1000次
4. 降级方案: 切换到 Odaily（SSL超时率约30%，不推荐）

### Q3: OKX实盘如何配置？

**方式1: 前端配置（推荐）**
```
localhost:3000/dashboard → 交易设置 → API配置 → 填写OKX API Key
```

**方式2: Bridge API**
```bash
curl -X POST http://127.0.0.1:3847/api/config/okx \
  -H "Content-Type: application/json" \
  -d '{"api_key":"xxx","secret_key":"xxx","passphrase":"xxx"}'
```

**方式3: 环境变量**（见Q1）

### Q4: 如何获取账户余额？

前端自动获取流程: 选择交易所 → 选择账户类型(实盘/模拟盘) → 自动调用API获取余额

手动验证:
```bash
# Bridge API
curl http://127.0.0.1:3847/api/trade/balance?exchange=okx&environment=live&symbol=USDT

# OKX CLI
python scripts/okx_cli.py --profile paper balance
```

---

## 二、策略问题

### Q5: 三屏交易体系是什么？

| 屏幕 | 周期 | 职责 | 输出 |
|:-----|:-----|:-----|:-----|
| 第一屏 | 周线 | 方向+策略选择 | 强多头/弱多头/观望/空头 |
| 第二屏 | 日线 | 预设（不执行） | 入场/加仓/止盈止损价位表 |
| 第三屏 | 小时/分钟 | 调整+执行 | 实时信号+执行指令 |

详见: [TRADING_SYSTEM.md](TRADING_SYSTEM.md) 或 `docs/TRADING_WORKFLOW_SPEC_v1.md`

### Q6: v2.0策略修正了什么？

| 旧逻辑 | v2.0修正 | 理由 |
|:-------|:---------|:-----|
| 观望(WAIT)=禁止开仓 | 观望=弱多头LONG(20%仓位上限) | 空仓浪费大量时间 |
| 止损=ATR倍数 | 止损=固定20%（硬约束） | ATR止损在低波动时过窄 |
| 止盈=单一目标 | 止盈=三级(2x/3x/5x ATR) | 分批止盈更稳健 |
| 需要评分≥20才开仓 | 取消门槛，方向为LONG/SHORT即可 | 避免有效信号被过滤 |
| 第三屏需完整A4→A5→A6→A9 | 各SKILL独立运行，置信度驱动 | 避免单点阻塞 |

### Q7: 马丁策略的仓位规则？

| 规则 | 值 | 说明 |
|:-----|:---|:-----|
| 单层级仓位 | ≤ 账户20% | 每次加仓最大比例 |
| 累计马丁仓位 | ≤ 账户60% | 初始+3次加仓总和 |
| 安全垫 | ≥ 40% | 预留资金 |
| 加仓次数 | 最多3次 | 4层：初始+3次加仓 |
| 最大回撤 | ≤ 20% | 硬约束，触发强制平仓 |

### Q8: 回测结果如何？

| 指标 | 200U资金 | 10kU资金 |
|:-----|:---------|:---------|
| 年化收益 | -1.28% | -1.28% |
| 最大回撤 | 7.06% | 7.06% |
| 胜率 | 66.7% | 66.7% |
| 交易次数 | 3次/17月 | 3次/17月 |
| 风控违规 | 0次 | 0次 |

线性缩放验证通过（百分比结果一致）。低交易频率因20%止损过宽+高止盈门槛导致。

---

## 三、自动化问题

### Q9: 有哪些自动化任务？

| 任务 | 频率 | 说明 |
|:-----|:-----|:-----|
| 第一屏-周度方向确定 | 每周一 08:00 | 产出第一屏方向报告 |
| 第二屏-日线订单设置 | 每日 09:00 | 产出三大预设价位表 |
| 6-TRADING邮箱扫描器 | 每小时 | 扫描A4/A5/A6/A9信号产物 |
| 交易工作流监控 | 每4h | 监控自动化运行状态 |

### Q10: 6-TRADING邮箱路径？

```
~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/
├── screen1/          # 第一屏产物
├── screen2/          # 第二屏产物
├── signals/          # A4/A5/A6/A9信号
├── orders/           # 订单记录
└── execution_log/    # 执行日志
```

扫描器: `scripts/mailbox_scanner.py`（每小时自动运行）

---

## 四、工程问题

### Q11: Bridge API无法启动？

```bash
# 检查端口占用
lsof -i :3847

# 启动（在 6-TRADING 目录下）
python bridge/run_server.py

# 健康检查
curl http://127.0.0.1:3847/health
```

### Q12: 前端在哪里？如何同步？

- **位置**: `../3-FRONTEND/dream-universal-gateway/`
- **启动**: `cd ../3-FRONTEND/dream-universal-gateway && pnpm dev`
- **同步**: `./scripts/sync_frontend.sh`

### Q13: 如何运行回测？

```bash
# 运行回测（200U初始资金，在 6-TRADING 目录下）
python scripts/backtest_engine.py

# 输出: reports/backtest_result_v2.json
```

### Q14: OKX行情无数据？

1. 检查OKX CLI: `python scripts/okx_cli.py ticker BTC-USDT-SWAP`
2. 验证API权限: 需要"读取"权限
3. 检查交易对: 确认inst_id格式正确（如 `BTC-USDT-SWAP`）
4. 检查网络: 确认可访问 `https://www.okx.com`

### Q15: 模拟盘 vs 实盘？

| 模式 | 前端选择 | API配置 |
|:-----|:---------|:---------|
| **模拟盘** | environment=demo | demo API Key |
| **实盘** | environment=live | 实盘 API Key |

---

## 五、SKILL问题

### Q16: SKILL在哪个目录？

| 级别 | 路径 | 说明 |
|:-----|:-----|:-----|
| **用户级** | `~/.workbuddy/skills/` | 跨项目可用（如 dream-multiSkill, boss-secretary） |
| **项目级** | `6-TRADING/skills/` | 仅本项目（22个skill） |

### Q17: SKILL无法调用？

1. 检查SKILL是否存在: `ls skills/` 或 `ls ~/.workbuddy/skills/`
2. 检查SKILL名称是否正确（区分用户级/项目级）
3. 查看SKILL触发词: 读取对应 `SKILL.md` 的 `trigger:` 字段

### Q18: A9离场信号不触发？

检查项:
1. A6情报监控是否运行中
2. 21事件库配置是否正确（`skills/dream-exit-skill-v2/`）
3. OKX TP/SL联动是否配置
4. 回撤监控是否启用（≥20%应强制触发）

---

## 六、系统状态检查

### Q19: 如何查看系统状态？

```bash
# Bridge健康
curl http://127.0.0.1:3847/health

# OKX连接
python scripts/okx_cli.py --profile paper ticker BTC-USDT-SWAP

# 环境变量
env | grep -E "TAVILY|OKX|BAILIAN"

# 自动化任务状态
# 使用 /tasks 命令查看（在 Claude Code 中）
```

### Q20: 如何查看记忆系统？

| 记忆文件 | 路径 | 说明 |
|:---------|:-----|:-----|
| 核心记忆 | `.workbuddy/memory/MEMORY.md` | 长期记忆（v2.7） |
| 今日日志 | `.workbuddy/memory/YYYY-MM-DD.md` | 当日工作记录 |
| Episode记录 | `data/episodes/` | 交易决策记录（11个） |

---

*最后更新: 2026-05-16*

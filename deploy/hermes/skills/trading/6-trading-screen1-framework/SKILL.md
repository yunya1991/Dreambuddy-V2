---
name: 6-trading-screen1-framework
description: Screen1 七维牛熊检测框架。以 MA200 三日确认为方向锚，七维度加权评分（技术指标检测器 40分 + 减半周期/矿工经济/链上估值/宏观金融/跨市场），输出 BULL/BEAR/NEUTRAL。
triggers:
  - "Screen1"
  - "第一屏"
  - "牛熊检测"
  - "七维"
  - "MA200 基线"
  - "技术指标检测器"
---

# 6-TRADING Screen1 牛熊检测框架

## 核心原则

- **MA200 三日确认为唯一方向锚**——价格连续3日收盘>MA200 = BULL，<MA200 = BEAR
- 其他指标不翻转 MA200 给出的方向，只在锚的方向上叠加/削弱
- 更早识别为优，不确定则回退基线

## 七维架构

| 维度 | 权重 | 核心指标 |
|------|------|---------|
| 技术指标检测器 | 40 | MA200三日 + 月线RSI/MACD + 辅助验证 |
| 减半周期 | 15 | 减半后天数 → 库存周期阶段 |
| 矿工经济 | 15 | 生产成本 vs BTC价格 + Hash Ribbon |
| 链上估值 | 15 | MVRV Z-Score + NUPL + RHODL |
| 宏观金融 | 10 | Fed周期 + 全球M2 + DXY + ETF流 |
| 跨市场周期 | 5 | 美林时钟 + 资产轮动 |

## 技术指标检测器（独立模块）

```
第一层：MA200基线（唯一方向锚）
  价格连续3日收盘 > MA200  →  BULL
  价格连续3日收盘 < MA200  →  BEAR
  价格在 MA200 附近震荡    →  NEUTRAL

第二层：动量预警（只在锚的方向上叠加）
  仅 BULL锚时:  RSI<30(+2) / Fear<25(+1) / MACD金叉(+2)
  仅 BEAR锚时:  RSI>70(+2) / MACD死叉(+2)

第三层：辅助验证（乘数调节）
  ADX>25=有效 / ADX<20=减半 / OBV同向=确认 / CMF同向=确认
```

## 常见陷阱

### TRAP: 门禁工具不可用
若 `run_annotation_gate` 工具不存在或调用失败，降级为 BASELINE，手动检查各注释文件的 `generated_at` 和 `freshness_days` 字段判断新鲜度。检查代码：
```python
import json, os, glob
from datetime import datetime
for f in glob.glob("screen1_*_annotation.json"):
    d = json.load(open(f))
    age = (datetime.now() - datetime.strptime(d['generated_at'][:10], "%Y-%m-%d")).days
    fresh = age < d.get('freshness_days', 7)
```

### TRAP: Tavily 搜索不可用
若 `mcp__tavily__tavily-search` 不可用，使用 `web_search` 作为替代。维度技能（screen1-*.md）中包含硬编码的市场数据可作为兜底参考。

### TRAP: Screen间价格漂移未检测
Screen1 完成后必须检查已存在的 Screen2 presets 是否因价格漂移而失效：
- 漂移 >10%：强制重新触发 Screen1，然后重新 Screen2
- 漂移 5-10%：在输出中标注 PRICE_DRIFT_WARNING
- 漂移 <5%：正常继续

### TRAP: 链上维度与技术维度矛盾时过度坚持技术方向
当 MVRV Z/NUPL/RHODL/STH-MVRV 四指标全部指向底部，而技术面（MA200）仍在空头时，这是 ETF 时代底部积累的经典特征，不是信号失效。链上领先技术 2-4 个月，方向仍以 MA200 为锚但信心分应显著下调。
- 优化在此之上叠加，不替换
- 先调研后设计，设计通过再落地
- MA200 是"价格 vs MA200"，不是金死叉
- 三日收盘确认有效突破/跌破

## Phase-2 合成链（A1→A2→A3）

当五个维度注释文件齐全后，由编排 Agent 直接执行 A1→A2→A3 三步合成。
详细流程与加权公式见参考文件。

## 参考文件

- `references/seven-dimensions-detail.md` — 七维完整评分细则
- `references/miner-economics-bottom-theory.md` — 矿工经济底部理论
- `references/onchain-valuation-theory.md` — 链上估值理论
- `references/macro-finance-theory.md` — 宏观金融传导机制
- `references/cross-market-cycle-theory.md` — 跨市场周期与多策略配置
- `references/screen1-synthesis-flow.md` — A1→A2→A3 合成执行流程与加权公式

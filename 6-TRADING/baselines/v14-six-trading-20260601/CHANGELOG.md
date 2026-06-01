# 6-TRADING v14.0 改动说明

## 版本: v14.0 — BTC牛市信号增强 + ETH波动率自适应

---

## 方案A: BTC 牛市 Sharpe 提升 (目标 0.85 → 1.5+)

### A1: 牛市溢价分 (backtest_strategy.py ~L876)
```
触发条件: STRONG_BULL + LONG + RSI ∈ [50, 75]
效果: signal_score +8 分
逻辑: 只在健康牛市区间给奖励，RSI>75不给（防追高）
预期: MEDIUM(0.7) → STRONG(1.0) 转换增加 → 仓位 10.5%→15%
```

### A2: RSI过热减仓 (backtest_strategy.py ~L939)
```
触发条件: STRONG_BULL + LONG + RSI > 75
效果: single_layer_pct × 0.5
逻辑: 追高就半仓，减少高位马丁链损失规模
预期: 减少3次亏损交易的损失金额
```

### 不改动的场景:
- 非 STRONG_BULL 完全不触发（等价 V13）
- RSI<50 不触发 A1（非健康牛市）
- SOL/ETH 不触发（条件仅限 LONG+BTC）

---

## 方案B: ETH 长周期扭亏 (目标 -3.88% → 正收益)

### B1: vol_mult 地板 1.30 → 1.50 (backtest_strategy.py ~L240)
```
加仓间隔: 10.4% → 12% (8%×1.50)
止盈:     5.2% → 6%   (4%×1.50)
势能门槛: 1.95 ATR → 2.25 ATR
Regime:   26% → 30% (STRONG_BEAR门槛)
效果: 链变稀疏，同等跌幅少触发加仓
```

### B2: L2c SHORT 阈值 1.20 → 1.25 (backtest_strategy.py ~L1081)
```
触发条件: ETH + SHORT + Level≥1
效果: avg×1.25 止链 (原 avg×1.20)
逻辑: 给 ETH 空头链多 5% 呼吸空间
```

### ETH 示例 ($2000 入场):
```
            V13           v14.0
L1加仓:     $1,792        $1,760
L2加仓:     $1,605        $1,549
L3加仓:     $1,438        $1,363
止盈:       $2,104        $2,120
L2c止链:    $2,150        $2,200 (avg=$1,760×1.25)
```

---

## 修改文件清单

| 文件 | 行号 | 改动 |
|------|------|------|
| backtest_strategy.py | L240 | ETH vol_mult 1.30→1.50 |
| backtest_strategy.py | L876-879 | A1: 牛市溢价分 |
| backtest_strategy.py | L939-942 | A2: RSI过热减仓 |
| backtest_strategy.py | L1009 | check_exit_signals 新增 inst_id 参数 |
| backtest_strategy.py | L1081-1082 | B2: ETH L2c 动态阈值 |
| backtest_engine_main.py | L448 | 传入 inst_id 给 check_exit_signals |

---

## 回测运行

```bash
cd /mnt/c/tmp
bash run_v14_backtest.sh
```

运行 9 组测试（3币种×3周期），结果保存到 v14_results/
汇总表自动打印。

---

## 预期 vs V13 基线

| 币种 | 周期 | 指标 | V13 | v14.0 预期 |
|------|------|------|-----|-----------|
| BTC | 牛市 | Sharpe | 0.85 | ↑ (A1提仓位,A2减亏损) |
| BTC | 牛市 | 收益率 | +2.49% | ↑ |
| BTC | 熊市 | 全部 | — | 持平 (无STRONG_BULL) |
| ETH | 长周期 | 收益率 | -3.88% | ↑ (B1拉宽间隔) |
| ETH | 长周期 | MaxDD | 18.43% | ↓ (B2减少止链) |
| ETH | 熊市/牛市 | Sharpe | 2.03/2.04 | ≈持平或略↑ |
| SOL | 全部 | 全部 | — | 完全持平 (无改动) |

---

## 失败回退

如需回退到 V13:
```bash
git checkout -- backtest_strategy.py backtest_engine_main.py
```

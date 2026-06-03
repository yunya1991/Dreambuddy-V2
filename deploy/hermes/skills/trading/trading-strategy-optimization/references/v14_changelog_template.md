# v{version} Changelog Template

## 版本: v{version} — {short_description}

---

## 方案A: {proposal_a_name}

### A1: {change_name} ({file} ~L{line})
```
触发条件: {regime} + {direction} + {indicator_condition}
效果: {before} → {after}
逻辑: {reasoning}
```

### A2: {change_name} ({file} ~L{line})
```
触发条件: ...
效果: ...
```

---

## 方案B: {proposal_b_name}

### B1: {change_name} ({file} ~L{line})
...
### B2: {change_name} ({file} ~L{line})
...

---

## 修改文件清单

| 文件 | 行号 | 改动 |
|------|------|------|
| backtest_strategy.py | Lxxx | ... |
| backtest_engine_main.py | Lxxx | ... |

---

## 回测结果 vs 基线

| 币种 | 周期 | 指标 | V{old} | v{new} | Δ | 判定 |
|------|------|------|--------|--------|---|------|
| ... | ... | ... | ... | ... | ... | ... |

---

## 失败回退

```bash
git checkout -- backtest_strategy.py backtest_engine_main.py
```

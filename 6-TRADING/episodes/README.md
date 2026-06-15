# 6-TRADING/episodes/ — 交易执行训练数据

> 此目录存储A5(战术执行器)每次执行的episode记录，
> 作为A7实践论门禁 INDEPENDENT_AUTO 验证的基础数据源。

## 目录用途

- **A5门禁C2(认识修正)**: 从episodes中提取历史执行数据→验证实践结果→修正认识
- **A5门禁C5(反馈机制)**: episodes提供反馈链路的输入→输出可审计追溯
- **学习闭环**: 每笔交易执行后生成episode→复盘分析→更新理论

## 文件命名规范

```
EP_{YYYYMMDD}_{HHMM}_{track_name}.json
```

示例: `EP_20260614_1405_track1_recon.json`

## Episode 模板

```json
{
  "episode_id": "EP_YYYYMMDD_HHMM_XXX",
  "timestamp": "ISO8601",
  "track_id": "TrackN",
  "action": "ENTRY|EXIT|SKIP|NO_ENTRY|RECON",
  "direction": "LONG|SHORT|NONE",
  "entry_price": null,
  "exit_price": null,
  "pnl_usdt": null,
  "pnl_pct": null,
  "reason_code": "R1-R9",
  "contradiction_id": "CX_XXX",
  "a7_gate_result": "PASS|FAIL|SKIP",
  "independent_auto": {
    "c1_verification": "PASS|FAIL",
    "c2_learning": "PASS|FAIL",
    "c3_discipline": "PASS|FAIL",
    "c4_risk": "PASS|FAIL",
    "c5_feedback": "PASS|FAIL"
  },
  "market_context": {
    "btc_price": null,
    "fgi": null,
    "regime": null,
    "blackout": false
  },
  "notes": ""
}
```

---

*由 A8 自检验证部自动创建 | 2026-06-14*

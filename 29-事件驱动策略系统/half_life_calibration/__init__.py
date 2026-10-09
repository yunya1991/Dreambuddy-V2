"""Phase 3 半衰期校准模块。

SPEC-Phase2 §5.2 (M4): 4 个半衰期（tech_upgrade/fed_speech/sec_deadline/congressional_hearing）
为经验假设 v0，待 Phase 3 回测验证后用贝叶斯优化校准。

子模块:
  - event_study: 事件研究法，计算事件后 CAR（累计超额收益）
  - synthetic_data: 生成已知 true_half_life 的合成事件+K线（验证框架正确性）
  - calibrator: Optuna 贝叶斯优化，独立优化每个事件类型的 τ
"""

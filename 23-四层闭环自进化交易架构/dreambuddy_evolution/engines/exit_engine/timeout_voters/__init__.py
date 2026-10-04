"""timeout_voters — 规则3a 软投票仲裁层

四方案择优 + 贝叶斯升级，取代原固定阈值强平。

 Voters:
   A. VCPVoter_A          — 结构化止损（Minervini VCP）
   B. ATRStandardVoter_B  — ATR 标准化
   C. WyckoffSupportVoter_C — 支撑位保护（Wyckoff）
   D. MurphyDecayVoter_D  — 时间衰减式（Murphy）

仲裁：
   TimeoutVoteArbitrator — 软投票仲裁层 + 贝叶斯权重持久化
"""
from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
    TimeoutVoteArbitrator,
)
from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
    TimeoutVoter,
    VoteTicket,
)
from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
    ATRStandardVoter_B,
    MurphyDecayVoter_D,
    VCPVoter_A,
    WyckoffSupportVoter_C,
)

__all__ = [
    "TimeoutVoter",
    "VoteTicket",
    "TimeoutVoteArbitrator",
    "VCPVoter_A",
    "ATRStandardVoter_B",
    "WyckoffSupportVoter_C",
    "MurphyDecayVoter_D",
]

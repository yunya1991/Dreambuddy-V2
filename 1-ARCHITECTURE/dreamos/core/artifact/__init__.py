"""产物中台 (M1) — 统一管理 DreamOS 各类产物

产物类型 (artifact_type):
    - insight_card: 洞察卡片
    - mood_board: 情绪板
    - bull_bear_debate: 多空辩论记录
    - briefing: 每日简报
    - report: 深度分析报告
    - chart: 图表产物

存储路径: scheduler_data/artifacts/{artifact_type}/{artifact_id}.json
"""

from .store import ArtifactStore, ArtifactType, ArtifactMeta

__all__ = ["ArtifactStore", "ArtifactType", "ArtifactMeta"]

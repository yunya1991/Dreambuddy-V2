"""
dreambuddy_dal.implementations.json_legacy — 现状存储薄适配（P0 阶段：内存 dict 薄实现）
- P0 目标：所有 @abstractmethod 被 override（保证 Protocol 可实例化），简单 add/get 行为不崩溃
- P1 目标：真正接入现有 25+ JSON / 18 散库
"""

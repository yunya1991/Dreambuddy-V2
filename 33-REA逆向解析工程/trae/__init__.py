"""Trae 逆向采集器（bundle / manifest / interaction）。

定位：33-REA 的「采集前置层」。REA 负责证据分级与结构化推断；
本包只做本地只读取证，不执行目标程序、不解析凭据、不破解加密数据。
"""

from .bundle_miner import run_bundle_miner
from .interaction_miner import run_interaction_miner
from .manifest_miner import run_manifest_miner

__all__ = ["run_bundle_miner", "run_interaction_miner", "run_manifest_miner"]

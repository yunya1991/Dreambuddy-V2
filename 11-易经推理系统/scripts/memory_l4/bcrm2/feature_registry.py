"""FeatureRegistry — 特征模块注册表，回测/实盘共用唯一入口

设计目标：
1. 消除回测(walk_forward_backtester)和实盘(bcrm2_adapter)的特征拼接不一致
2. 新增模块只需在文件底部 @register，无需修改回测/实盘代码
3. 支持模块间依赖传递（如 merrill_clock 依赖 cycle 的输出）

使用方式：
    # 在模块文件底部注册
    from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
    FeatureRegistry.register("bagua", factory=BaguaFeatureEngine, participates_in_gua=True)

    # 在回测/实盘中调用
    features, feature_names_by_gua = FeatureRegistry.compute_all(
        df=df, ref_df=ref_df, symbol="BTC",
    )
"""
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass, field
import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# Enabled Sets：配置化的特征启用集合（一键启用组合）
# ============================================================
ENABLED_SETS: Dict[str, List[str]] = {
    "btc_morphology": ["morphology_core", "breadth_market"],   # Phase 0 12 项形态+广度特征
    "default_all": None,  # None = 启用所有 default_enabled=True 的模块
}


@dataclass
class FeatureModuleSpec:
    """特征模块规格定义"""
    name: str                                       # 注册名
    factory: Callable                               # 工厂函数/类 → 实例
    participates_in_gua: bool = False               # 是否参与卦象推导（8卦维度）
    requires_ref_df: bool = False                   # 是否需要参考资产(如BTC)
    requires_macro_df: bool = False                 # 是否需要宏观数据(P1)
    requires_symbol: bool = False                   # 构造函数是否需要 symbol
    requires_cycle_phase: bool = False              # 是否需要 cycle 模块输出
    default_enabled: bool = True                    # 默认是否启用
    # 子模块 feature_names_by_gua 拆分规则（如 wdh 按前缀拆 4 个子 key）
    sub_key_splitter: Optional[Callable[[List[str]], Dict[str, List[str]]]] = None
    # bagua 特殊：feature_names_by_gua 来自实例属性而非拆分器
    uses_instance_gua_map: bool = False


# ============================================================
# 子模块拆分器（wdh 和 cycle 用）
# ============================================================
def _wdh_sub_key_splitter(columns: List[str]) -> Dict[str, List[str]]:
    """wdh 按前缀拆为 4 个子 key"""
    return {
        "wdh_weekly_accum": [c for c in columns if c.startswith("wa_")],
        "wdh_daily_confirm": [c for c in columns if c.startswith("dc_")],
        "wdh_hourly_timing": [c for c in columns if c.startswith("ht_")],
        "wdh_qual_trigger": [c for c in columns if c.startswith("qt_")],
    }


def _cycle_sub_key_splitter(columns: List[str]) -> Dict[str, List[str]]:
    """cycle 按前缀拆为 4 个子 key"""
    return {
        "cycle_halving": [c for c in columns if c.startswith("hc_")],
        "cycle_ath": [c for c in columns if c.startswith("ath_")],
        "cycle_inventory": [c for c in columns if c.startswith("ic_")],
        "cycle_long_term": [c for c in columns if c.startswith("lt_")],
    }


class FeatureRegistry:
    """特征模块注册表，回测/实盘共用同一注册表"""

    _registry: Dict[str, FeatureModuleSpec] = {}
    _order: List[str] = []  # 保持注册顺序

    @classmethod
    def register(cls, name: str, factory: Callable, **kwargs) -> None:
        """注册特征模块

        Args:
            name: 模块名（snake_case，如 "bagua", "macro"）
            factory: 工厂函数或类，调用后返回模块实例
            participates_in_gua: 是否参与卦象推导（8卦维度）
            requires_ref_df: 是否需要参考资产(如BTC)
            requires_symbol: 构造函数是否需要 symbol 参数
            requires_cycle_phase: 是否需要 cycle 模块输出
            default_enabled: 默认是否启用
            sub_key_splitter: 子模块 feature_names_by_gua 拆分函数
            uses_instance_gua_map: feature_names_by_gua 来自实例属性（bagua 专用）
        """
        spec = FeatureModuleSpec(name=name, factory=factory, **kwargs)
        if name in cls._registry:
            logger.debug(f"FeatureRegistry: 模块 '{name}' 已注册，覆盖")
            cls._order.remove(name)
        cls._registry[name] = spec
        cls._order.append(name)

    @classmethod
    def compute_all(
        cls,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "BTC",
        config: Optional[dict] = None,
        enabled: Optional[List[str]] = None,
        enabled_set: Optional[str] = None,
        coins_closes: Optional[dict] = None,
        verbose: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """计算所有启用模块的特征

        Args:
            df: K线 OHLCV 数据
            ref_df: 参考资产（如BTC）的 OHLCV，用于跨资产特征
            macro_df: 宏观数据 DataFrame（P1），已对齐到 df.index
            symbol: 交易标的符号
            config: 配置字典（如 wdh_weekly_only, cycle_halving 等开关）
            enabled: 启用的模块名列表。None 表示根据 enabled_set / default_enabled 决定
            enabled_set: 启用集合名（如 "btc_morphology"）。若 enabled 未提供，则通过该集合名查找 enabled 列表
            coins_closes: dict[coin] → list[float] newest-first；用于广度特征（breadth_market）
            verbose: 是否打印详细日志

        Returns:
            (features, feature_names_by_gua):
                features: 合并后的特征 DataFrame
                feature_names_by_gua: {模块名/子模块名: [特征名列表]}
        """
        ctx = {
            "df": df,
            "ref_df": ref_df,
            "macro_df": macro_df,
            "symbol": symbol,
            "config": config or {},
            "coins_closes": coins_closes,
        }

        # 确定 enabled_list 优先级: explicit enabled > enabled_set → default_all
        if enabled is None and enabled_set is not None:
            enabled = ENABLED_SETS.get(enabled_set)
            if enabled is None:
                logger.warning(f"FeatureRegistry: enabled_set='{enabled_set}' 未在 ENABLED_SETS 中注册，回退为所有 default_enabled=True")

        # 确定启用列表
        if enabled is None:
            enabled_list = [n for n in cls._order
                           if cls._registry[n].default_enabled]
        else:
            enabled_list = [n for n in cls._order if n in enabled]

        features = pd.DataFrame(index=df.index)
        feature_names_by_gua: Dict[str, List[str]] = {}
        cycle_feats: Optional[pd.DataFrame] = None  # 用于 merrill 依赖

        for name in enabled_list:
            spec = cls._registry.get(name)
            if spec is None:
                logger.warning(f"FeatureRegistry: 模块 '{name}' 未注册，跳过")
                continue

            # 检查 ref_df 依赖
            if spec.requires_ref_df:
                if ref_df is None or len(ref_df) < 200:
                    if verbose:
                        print(f"  跳过 {name}: ref_df 不足")
                    continue

            # 检查 macro_df 依赖
            if spec.requires_macro_df:
                if macro_df is None or macro_df.empty:
                    if verbose:
                        print(f"  跳过 {name}: macro_df 缺失")
                    continue

            # 创建实例
            if spec.requires_symbol:
                instance = spec.factory(symbol=symbol)
            else:
                instance = spec.factory()

            # 调用 compute（根据模块类型传递不同参数）
            try:
                if name == "bagua":
                    feats = instance.compute(df)
                    # bagua 的 feature_names_by_gua 来自实例属性（8卦维度）
                    feature_names_by_gua.update(dict(instance.feature_names_by_gua))
                elif name == "wdh":
                    weekly_only = ctx["config"].get("wdh_weekly_only", False)
                    feats = instance.compute(df, weekly_only=weekly_only)
                elif name == "cycle":
                    cycle_cfg = {
                        "enable_halving": ctx["config"].get("cycle_halving", True),
                        "enable_ath": ctx["config"].get("cycle_ath", True),
                        "enable_inventory": ctx["config"].get("cycle_inventory", True),
                        "enable_long_term": ctx["config"].get("cycle_long_term", True),
                    }
                    feats = instance.compute(df, **cycle_cfg)
                    cycle_feats = feats  # 保存给 merrill 用
                elif name == "market_cap":
                    feats = instance.get_mcap_features(symbol, df)
                elif name == "cross_asset":
                    # CrossAssetFeatureWrapper.compute(df, ref_df, symbol)
                    feats = instance.compute(df, ref_df, symbol=symbol)
                elif name == "merrill_clock":
                    cycle_phase = cycle_feats if cycle_feats is not None else None
                    feats = instance.compute(df, ref_df=ref_df, cycle_phase=cycle_phase)
                elif name == "breadth_market":
                    # 广度模块：透传 coins_closes
                    feats = instance.compute(df, coins_closes=ctx["coins_closes"])
                elif spec.requires_macro_df:
                    # 提取 macro_ 前缀的维度开关配置传给宏观特征模块
                    macro_config = {k: v for k, v in ctx["config"].items() if k.startswith("macro_")}
                    feats = instance.compute(df, macro_df=macro_df, config=macro_config)
                else:
                    feats = instance.compute(df)
            except Exception as e:
                logger.warning(f"FeatureRegistry: 模块 '{name}' 计算失败: {e}")
                continue

            # 跳过空结果
            if feats is None or len(feats.columns) == 0:
                continue

            # 拼接特征
            features = pd.concat([features, feats], axis=1)

            # 注册 feature_names_by_gua
            if spec.sub_key_splitter:
                feature_names_by_gua.update(spec.sub_key_splitter(list(feats.columns)))
            elif spec.uses_instance_gua_map:
                pass  # bagua 已在上面处理
            else:
                feature_names_by_gua[name] = list(feats.columns)

            if verbose:
                print(f"  {name}: {len(feats.columns)}个特征")

        if verbose:
            print(f"  特征总数: {len(features.columns)}")

        return features, feature_names_by_gua

    @classmethod
    def list_modules(cls) -> List[str]:
        """列出所有已注册模块名（按注册顺序）"""
        return list(cls._order)

    @classmethod
    def get_spec(cls, name: str) -> Optional[FeatureModuleSpec]:
        """获取模块规格"""
        return cls._registry.get(name)

    @classmethod
    def clear(cls) -> None:
        """清空注册表（仅用于测试）"""
        cls._registry.clear()
        cls._order.clear()


# ============================================================
# sys.modules 别名同步：消除「bcrm2.feature_registry」和
# 「scripts.memory_l4.bcrm2.feature_registry」两条导入路径
# 带来的「两个独立 module → 两个独立 FeatureRegistry 类」问题。
# 当任一路径先被 import 后，会自动把另一路径也指向本 module，
# 从而保证 FeatureRegistry 的类变量（注册表）全局唯一。
# ============================================================
def _sync_module_aliases():
    import sys as _sys
    # 当前文件真实路径形式：module.__name__ =
    #   "scripts.memory_l4.bcrm2.feature_registry"  或
    #   "bcrm2.feature_registry"
    this_mod = _sys.modules.get(__name__)
    if this_mod is None:
        return
    candidates = [
        "bcrm2.feature_registry",
        "scripts.memory_l4.bcrm2.feature_registry",
    ]
    for alias in candidates:
        existing = _sys.modules.get(alias)
        if existing is None:
            _sys.modules[alias] = this_mod
        elif existing is not this_mod:
            # 已经加载了另一个 module：把它的 FeatureRegistry 类也同步
            # 为「同一个 FeatureRegistry 类（this_mod 的）」。
            # 注意：我们同步类属性引用到外部类，防止外部类的注册表实例
            # 继续在错误的字典上操作。
            other_cls = getattr(existing, "FeatureRegistry", None)
            our_cls = getattr(this_mod, "FeatureRegistry", None)
            if other_cls is not None and our_cls is not None and other_cls is not our_cls:
                other_cls._registry = our_cls._registry
                other_cls._order = our_cls._order
                other_cls.ENABLED_SETS = our_cls.ENABLED_SETS


_sync_module_aliases()
del _sync_module_aliases

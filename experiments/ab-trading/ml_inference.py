#!/usr/bin/env python3
"""
ML推理模块 — 三屏趋势策略实盘ML信号

职责：
1. 加载模型（读 models/current.json 指针，版本变化自动热加载，回落 baseline）
2. 获取最新K线数据
3. 生成特征并预测
4. 返回ML信号（方向 + 置信度）

接入点：screen_executor.py 的 check_and_execute()
作用：作为第三屏（AI屏），用ML预测修正五大算法决策的置信度
- ML预测与趋势同向：置信度增强
- ML预测与趋势反向：置信度削弱
"""

import hashlib
import json
import os
import sys
import time
from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:
    import pandas as pd

# 路径设置
TREND_SYSTEM_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统"
if TREND_SYSTEM_PATH not in sys.path:
    sys.path.insert(0, TREND_SYSTEM_PATH)

ML_DIR = os.path.join(TREND_SYSTEM_PATH, "ml")
MODELS_DIR = os.path.join(ML_DIR, "models")

# 模块级缓存
_ml_module = None
_model_cache = {}
_last_load_time = 0
_MODEL_TTL = 3600  # 缓存上限1小时；current.json 版本变化时立即 reload（SPEC 4.3）
_POINTER_FILE = os.path.join(MODELS_DIR, "current.json")


def _load_ml_modules():
    """延迟导入ML模块（避免启动时依赖问题）"""
    global _ml_module
    if _ml_module is not None:
        return _ml_module

    try:
        from ml.feature_engineer import TrendFeatureEngineer
        from ml.version_manager import ModelVersionManager

        _ml_module = {
            "TrendFeatureEngineer": TrendFeatureEngineer,
            "ModelVersionManager": ModelVersionManager,
        }
        return _ml_module
    except Exception as e:
        print(f"[ML推理] 模块导入失败: {e}", flush=True)
        return None


def _read_pointer() -> Tuple[Optional[str], Optional[str]]:
    """读取 models/current.json 热加载指针（SPEC 4.3）。缺失或损坏 → (None, None)。"""
    if not os.path.isfile(_POINTER_FILE):
        return None, None
    try:
        with open(_POINTER_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("version"), payload.get("checksum")
    except Exception as e:
        print(f"[ML推理] current.json 读取失败，回落到基线: {e}", flush=True)
        return None, None


def _sha256_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def _load_old_model(reason: str):
    """加载失败时保留旧模型 + 告警（FAIL-OPEN）"""
    old = _model_cache.get("model")
    if old is not None:
        print(f"[ML推理] {reason}，保留旧模型 {_model_cache.get('version')}", flush=True)
        return old, _model_cache.get("fe"), _model_cache.get("features")
    print(f"[ML推理] {reason}", flush=True)
    return None, None, None


def _load_model():
    """加载模型（缓存 + current.json 版本热加载）

    - current.json 版本变化 → 立即 reload（不等 TTL）
    - 版本未变且在 TTL 内 → 复用缓存
    - 新版本加载失败 → 保留旧模型 + 告警（FAIL-OPEN）
    - 无 current.json（未 promote 过）→ 回落到 baseline_version
    """
    global _last_load_time

    now = time.time()
    pointer_version, pointer_checksum = _read_pointer()
    cached_version = _model_cache.get("version")

    if _model_cache.get("model") is not None:
        if pointer_version == cached_version and (now - _last_load_time) < _MODEL_TTL:
            return _model_cache.get("model"), _model_cache.get("fe"), _model_cache.get("features")
        if pointer_version and pointer_version != cached_version:
            print(
                f"[ML推理] 检测到版本变更 {cached_version} → {pointer_version}，触发热加载",
                flush=True,
            )

    modules = _load_ml_modules()
    if not modules:
        return _load_old_model("ML 模块导入失败")

    try:
        vm = modules["ModelVersionManager"](MODELS_DIR)
        target_version = pointer_version or vm.registry.get("baseline_version")
        if not target_version:
            return _load_old_model("registry 无可用版本")

        model = vm.load_version(target_version)
        if model is None:
            return _load_old_model(f"版本 {target_version} 加载为空")

        # 从元数据获取特征配置
        meta = vm.get_version_meta(target_version) or {}
        selected_features = meta.get("feature_engineer_config", {}).get("selected_features", [])
        if not selected_features:
            return _load_old_model(f"版本 {target_version} 元数据缺 selected_features")

        # checksum 比对：指针与实际 artifact 不一致 → 告警不阻塞
        if pointer_checksum:
            actual = _sha256_file(os.path.join(vm.versions_dir, target_version, "model.pkl"))
            if actual and actual != pointer_checksum:
                print(
                    f"[ML推理] ⚠ checksum 不一致: {target_version} "
                    f"pointer={pointer_checksum[:12]} actual={actual[:12]}",
                    flush=True,
                )

        # 创建特征工程师
        fe = modules["TrendFeatureEngineer"](
            views=["direction", "change", "velocity", "power", "hierarchy"]
        )
        fe.feature_names = selected_features

        _model_cache["model"] = model
        _model_cache["fe"] = fe
        _model_cache["features"] = selected_features
        _model_cache["version"] = target_version
        _last_load_time = now

        print(
            f"[ML推理] 模型加载成功: {target_version}, 特征数={len(selected_features)}", flush=True
        )
        return model, fe, selected_features

    except Exception as e:
        return _load_old_model(f"模型加载失败: {e}")


def _fetch_candles(inst_id: str, bar: str = "1D", limit: int = 300) -> "pd.DataFrame":
    """获取K线数据并转为DataFrame"""
    try:
        import pandas as pd
        from data.market_data import fetch_candles

        candles = fetch_candles(inst_id, bar, limit)
        if not candles:
            return None

        df = pd.DataFrame(candles)
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.rename(
            columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
        )
        df = (
            df[["date", "open", "high", "low", "close", "volume"]]
            .sort_values("date")
            .reset_index(drop=True)
        )
        return df

    except Exception as e:
        print(f"[ML推理] 数据获取失败: {e}", flush=True)
        return None


def get_ml_signal(inst_id: str = "BTC-USDT") -> Dict:
    """获取ML预测信号

    参数:
        inst_id: 交易对，如 "BTC-USDT"

    返回:
        {
            "direction": "BULL" / "BEAR" / "NEUTRAL",
            "confidence": float,  # 0.0 ~ 1.0
            "prob_up": float,     # 上涨概率
            "prob_down": float,   # 下跌概率 = 1 - prob_up
            "error": str or None,
        }
    """
    # 1. 加载模型
    model, fe, selected_features = _load_model()
    if model is None:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.5,
            "prob_up": 0.5,
            "prob_down": 0.5,
            "error": "模型未加载",
        }

    # 2. 获取K线数据
    df = _fetch_candles(inst_id, "1D", 300)
    if df is None or len(df) < 100:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.5,
            "prob_up": 0.5,
            "prob_down": 0.5,
            "error": f"数据不足({0 if df is None else len(df)}<100)",
        }

    # 3. 生成特征
    try:
        features_df = fe.create_features(df, label_lookahead=7)
        if len(features_df) == 0:
            return {
                "direction": "NEUTRAL",
                "confidence": 0.5,
                "prob_up": 0.5,
                "prob_down": 0.5,
                "error": "特征工程无有效输出",
            }

        # 取最新一行
        latest = features_df.iloc[[-1]][selected_features]
        if latest.isna().any().any():
            return {
                "direction": "NEUTRAL",
                "confidence": 0.5,
                "prob_up": 0.5,
                "prob_down": 0.5,
                "error": "最新特征含NaN",
            }

        # 4. 预测
        prob_up = float(model.predict_proba(latest)[0])
        prob_down = 1.0 - prob_up

        # 方向判断
        if prob_up > 0.58:
            direction = "BULL"
        elif prob_up < 0.42:
            direction = "BEAR"
        else:
            direction = "NEUTRAL"

        # 置信度 = 偏离0.5的幅度 × 2
        confidence = abs(prob_up - 0.5) * 2.0

        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "prob_up": round(prob_up, 4),
            "prob_down": round(prob_down, 4),
            "error": None,
        }

    except Exception as e:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.5,
            "prob_up": 0.5,
            "prob_down": 0.5,
            "error": f"预测异常: {e}",
        }


def adjust_decision_with_ml(decision: Dict, ml_signal: Dict, ml_weight: float = 0.15) -> Dict:
    """用ML信号调整决策置信度

    参数:
        decision: 原始决策 {"action": "OPEN_BULL"/"OPEN_BEAR"/"WAIT", "confidence": float, ...}
        ml_signal: ML信号 {"direction": "BULL"/"BEAR"/"NEUTRAL", "confidence": float, ...}
        ml_weight: ML影响权重 (0~0.3)

    返回:
        调整后的决策

    逻辑:
        - ML与决策同向：置信度 += ml_conf * ml_weight * 100
        - ML与决策反向：置信度 -= ml_conf * ml_weight * 100
        - ML中性：不变
    """
    if ml_signal.get("error"):
        return decision

    ml_dir = ml_signal.get("direction", "NEUTRAL")
    ml_conf = ml_signal.get("confidence", 0.5)

    if ml_dir == "NEUTRAL":
        return decision

    action = decision.get("action", "WAIT")
    if action == "OPEN_BULL":
        decision_dir = "BULL"
    elif action == "OPEN_BEAR":
        decision_dir = "BEAR"
    else:
        return decision

    original_conf = decision.get("confidence", 50.0)
    adjustment = ml_conf * ml_weight * 100  # 最大约15%

    if ml_dir == decision_dir:
        # 同向增强
        new_conf = min(95.0, original_conf + adjustment)
        decision["confidence"] = round(new_conf, 1)
        decision["ml_boost"] = f"+{adjustment:.1f}%"
        decision["ml_direction"] = ml_dir
    else:
        # 反向削弱
        new_conf = max(0.0, original_conf - adjustment)
        decision["confidence"] = round(new_conf, 1)
        decision["ml_boost"] = f"-{adjustment:.1f}%"
        decision["ml_direction"] = ml_dir

    return decision


if __name__ == "__main__":
    # 测试
    print("=== ML推理模块测试 ===\n")

    # 1. 模型加载
    print("[1] 加载基线模型...")
    model, fe, features = _load_model()
    if model:
        print(f"  模型加载成功, 特征数={len(features)}")
    else:
        print("  模型加载失败")
        sys.exit(1)

    # 2. 获取BTC信号
    print("\n[2] 获取BTC-USDT ML信号...")
    signal = get_ml_signal("BTC-USDT")
    print(f"  方向: {signal['direction']}")
    print(f"  置信度: {signal['confidence']}")
    print(f"  上涨概率: {signal['prob_up']}")
    print(f"  下跌概率: {signal['prob_down']}")
    if signal.get("error"):
        print(f"  错误: {signal['error']}")

    # 3. 模拟决策调整
    print("\n[3] 模拟决策调整...")
    test_decision = {"action": "OPEN_BULL", "confidence": 65.0, "mode": "five_algo"}
    adjusted = adjust_decision_with_ml(test_decision, signal)
    print(f"  原始: action={test_decision['action']}, confidence={test_decision['confidence']}%")
    print(f"  调整: action={adjusted['action']}, confidence={adjusted['confidence']}%")
    if adjusted.get("ml_boost"):
        print(f"  ML调整: {adjusted['ml_boost']} (ML方向={adjusted['ml_direction']})")

    print("\n=== 测试完成 ===")

"""LLM 辩证推理模块

当 LightGBM 集成模型置信度不足（处于不确定区间）时，
调用 LLM 对五大算法的矛盾信号做辩证推理。

触发条件：
- 集成模型置信度 < 40（低置信度）
- 集成模型置信度在 40-60 之间（不确定区间）
- 五大算法内部存在矛盾（趋势一致但贝叶斯方向不一致等）

不触发条件：
- 集成模型置信度 > 60 且方向明确（直接用集成模型结果）
- 趋势完全不一致（直接 WAIT，不需要 LLM 浪费 token）

与 screen_executor.py 的 _llm_decision_deepseek 的区别：
- 那个是交易执行器的 LLM，接收 Screen1/Screen2/Screen3 和研报数据
- 本模块是推理层的 LLM，接收五大算法的完整输出 + 集成模型预测
- 本模块聚焦于"矛盾信号辩证分析"，不直接生成交易指令
- 本模块的输出会被 screen_executor.py 的决策链路参考

隔离声明：
- 本模块属于三屏趋势系统的推理层，不引用 11-易经推理系统 的任何代码
- LLM 调用使用 DeepSeek API（与 screen_executor.py 共享配置）
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


# ── 配置加载 ─────────────────────────────────────────────────────────────

# 支持从多个位置加载 .env（可选，不强制）
# 优先级：进程环境变量 > experiments/ab-trading/config/.env > 12-三屏趋势系统/.env
def _try_load_dotenv() -> None:
    """尝试从常见位置加载 .env（如果 dotenv 可用且环境变量未设置时）"""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return  # 已有配置，跳过
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    base = Path(__file__).parent.parent  # 12-三屏趋势系统/
    candidates = [
        base.parent / "experiments" / "ab-trading" / "config" / ".env",
        base / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p)
            if os.environ.get("DEEPSEEK_API_KEY"):
                break


_try_load_dotenv()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# LLM 触发阈值
LLM_TRIGGER_LOW = 40.0     # 低于此值必触发
LLM_TRIGGER_HIGH = 60.0    # 高于此值不触发（除非有矛盾）
LLM_DAILY_LIMIT = 50       # 每日 LLM 调用上限


# ── 触发判断 ──────────────────────────────────────────────────────────────

def should_trigger_llm(ensemble_pred: dict, full_signal: dict) -> tuple:
    """判断是否需要触发 LLM 辩证推理

    参数:
        ensemble_pred: predict_ensemble() 的返回值
        full_signal: compute_full_trading_signal() 的返回值

    返回:
        (should_trigger: bool, reason: str)
    """
    confidence = ensemble_pred.get("confidence", 50.0)
    source = ensemble_pred.get("source", "fallback")

    # 集成模型不可用时，直接 fallback 不需要 LLM
    if source == "fallback":
        return False, "ensemble_model_not_available"

    # 置信度很高，不需要 LLM
    if confidence >= LLM_TRIGGER_HIGH:
        return False, "high_confidence"

    # 检查五大算法内部矛盾
    contradictions = _detect_contradictions(full_signal)

    # 置信度很低，必须 LLM 介入
    if confidence < LLM_TRIGGER_LOW:
        return True, f"low_confidence_{confidence:.1f}"

    # 中等置信度 + 有矛盾 → 触发
    if contradictions:
        return True, f"uncertain_with_contradictions_{confidence:.1f}"

    # 中等置信度但无矛盾 → 不触发
    return False, f"uncertain_no_contradictions_{confidence:.1f}"


def _detect_contradictions(full_signal: dict) -> list:
    """检测五大算法内部的矛盾信号

    返回:
        矛盾描述列表
    """
    contradictions = []

    tc = full_signal.get("trend_consistency", {})
    bc = full_signal.get("bayesian_confidence", {})
    cc = full_signal.get("classic_indicator_confidence", {})
    tff = full_signal.get("technical_fundamental_fusion", {})
    fs = full_signal.get("final_signal", {})

    # 1. 趋势不一致
    if not tc.get("consistent", True):
        weekly_dir = tc.get("weekly", {}).get("final_direction", "N/A")
        daily_dir = tc.get("daily", {}).get("final_direction", "N/A")
        contradictions.append(f"趋势不一致: 周线{weekly_dir} vs 日线{daily_dir}")

    # 2. 贝叶斯方向与最终信号方向不一致
    bayes_dir = bc.get("direction", "NEUTRAL")
    final_dir = fs.get("direction", "NEUTRAL")
    if bayes_dir != "NEUTRAL" and final_dir != "NEUTRAL" and bayes_dir != final_dir:
        contradictions.append(f"贝叶斯方向{bayes_dir}与最终方向{final_dir}不一致")

    # 3. 经典指标趋势不一致
    if not cc.get("trend_consistent", True):
        s1_dir = cc.get("screen1_weekly", {}).get("direction", "N/A")
        s2_dir = cc.get("screen2_daily", {}).get("direction", "N/A")
        contradictions.append(f"经典指标不一致: 周线{s1_dir} vs 日线{s2_dir}")

    # 4. 技术面与基本面不一致
    if not tff.get("consistent", True):
        tech_conf = tff.get("technical", {}).get("confidence", 0)
        fund_conf = tff.get("fundamental", {}).get("confidence", 0)
        contradictions.append(f"技术面({tech_conf:.0f})与基本面({fund_conf:.0f})不一致")

    # 5. 逆转信号
    weekly_reversal = tc.get("weekly", {}).get("reversal_score", 0)
    daily_reversal = tc.get("daily", {}).get("reversal_score", 0)
    if weekly_reversal > 50 or daily_reversal > 50:
        contradictions.append(
            f"逆转信号偏高: 周线{weekly_reversal:.0f} 日线{daily_reversal:.0f}"
        )

    return contradictions


# ── 提示词构建 ────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """构建系统提示词"""
    return """你是三屏趋势系统的辩证推理引擎，负责在五大算法信号矛盾时做最终裁决。

你的任务：
1. 识别五大算法之间的矛盾点
2. 分析矛盾产生的原因（市场状态切换、噪声干扰、指标滞后等）
3. 权衡各算法的可靠性（趋势一致性 > 贝叶斯 > 经典指标 > 基本面）
4. 给出最终方向和置信度

输出严格 JSON 格式，不要任何解释：
{
  "direction": "BULL" | "BEAR" | "NEUTRAL",
  "confidence": 0-100的整数,
  "contradiction_analysis": "矛盾分析（一句话）",
  "reasoning": "推理过程（2-3句话）",
  "risk_note": "风险提示",
  "trust_weight": {"trend": 0-1, "bayes": 0-1, "classic": 0-1, "fundamental": 0-1}
}

推理原则：
- 趋势一致性是第一优先级：周线日线不一致时倾向 NEUTRAL
- 逆转信号 > 50 时降低置信度
- 贝叶斯概率极端（>0.8 或 <0.2）时可信度高
- 技术面与基本面矛盾时，以技术面为主（权重60%）
- 不确定时宁可 WAIT（NEUTRAL），不要猜方向"""


def _build_reasoning_prompt(full_signal: dict, ensemble_pred: dict,
                            contradictions: list) -> str:
    """构建推理提示词"""
    tc = full_signal.get("trend_consistency", {})
    bc = full_signal.get("bayesian_confidence", {})
    cc = full_signal.get("classic_indicator_confidence", {})
    tff = full_signal.get("technical_fundamental_fusion", {})
    vr = full_signal.get("value_risk_assessment", {})
    fs = full_signal.get("final_signal", {})
    ft = full_signal.get("freqtrade_signals", {})

    weekly = tc.get("weekly", {})
    daily = tc.get("daily", {})

    prompt = f"""【集成模型预测】
方向: {ensemble_pred.get('direction', 'N/A')}
置信度: {ensemble_pred.get('confidence', 0):.1f}
上涨概率: {ensemble_pred.get('prob_up', 0):.4f}
下跌概率: {ensemble_pred.get('prob_down', 0):.4f}

【检测到的矛盾】
{chr(10).join(f'- {c}' for c in contradictions) if contradictions else '- 无明显矛盾'}

【五大算法完整输出】

--- 算法1: 趋势一致性 ---
周线: 方向={weekly.get('final_direction', 'N/A')} 置信={weekly.get('confidence', 0):.1f} 逆转={weekly.get('reversal_score', 0):.1f}
      速度={weekly.get('avg_speed', 0):.1f} 加速度={weekly.get('avg_acceleration', 0):.1f}
      多={weekly.get('bull_count', 0)} 空={weekly.get('bear_count', 0)}
日线: 方向={daily.get('final_direction', 'N/A')} 置信={daily.get('confidence', 0):.1f} 逆转={daily.get('reversal_score', 0):.1f}
      速度={daily.get('avg_speed', 0):.1f} 加速度={daily.get('avg_acceleration', 0):.1f}
      多={daily.get('bull_count', 0)} 空={daily.get('bear_count', 0)}
一致性: {'是' if tc.get('consistent') else '否'} (置信度={tc.get('consistency_confidence', 0):.1f})

--- 算法2: 贝叶斯置信度 ---
方向: {bc.get('direction', 'N/A')} 置信={bc.get('confidence', 0):.1f}
多概率: {bc.get('bull_probability', 0):.4f} 空概率: {bc.get('bear_probability', 0):.4f}

--- 算法3: 经典指标置信度 ---
Screen1(周线): 方向={cc.get('screen1_weekly', {}).get('direction', 'N/A')} 置信={cc.get('screen1_weekly', {}).get('confidence', 0):.1f}
Screen2(日线): 方向={cc.get('screen2_daily', {}).get('direction', 'N/A')} 置信={cc.get('screen2_daily', {}).get('confidence', 0):.1f}
综合: 方向={cc.get('overall_direction', 'N/A')} 置信={cc.get('overall_confidence', 0):.1f}
指标一致: {'是' if cc.get('trend_consistent') else '否'}

--- 算法4: 技术面+基本面融合 ---
技术面: 置信={tff.get('technical', {}).get('confidence', 0):.1f}
基本面: 置信={tff.get('fundamental', {}).get('confidence', 0):.1f}
融合一致: {'是' if tff.get('consistent') else '否'} 冲突级别={tff.get('conflict_level', 0):.2f}

--- 算法5: 价值风险评估 ---
波动率比: {vr.get('volatility', {}).get('vol_ratio', 0):.2f}
风险收益比: {vr.get('take_profit_stop_loss', {}).get('risk_reward', {}).get('rr_ratio', 0):.2f}
价值>风险: {'是' if vr.get('value_gt_risk') else '否'}

--- Freqtrade信号 ---
1h: {ft.get('1h', {}).get('signal', 'N/A')} (置信={ft.get('1h', {}).get('confidence', 0):.1f})
4h: {ft.get('4h', {}).get('signal', 'N/A')} (置信={ft.get('4h', {}).get('confidence', 0):.1f})

--- 最终信号(五大算法原始决策) ---
方向: {fs.get('direction', 'N/A')} 置信={fs.get('confidence', 0):.1f}
趋势一致: {'是' if fs.get('trend_consistent') else '否'}
融合一致: {'是' if fs.get('fusion_consistent') else '否'}
Freqtrade一致: {'是' if fs.get('freqtrade_consistent') else '否'}

请进行辩证推理，给出最终裁决（仅输出JSON）："""
    return prompt


# ── LLM 调用 ──────────────────────────────────────────────────────────────

def _call_deepseek(prompt: str, system: str, max_tokens: int = 1000) -> Optional[str]:
    """调用 DeepSeek API

    与 screen_executor.py 的 _call_deepseek 使用相同的 API 配置，
    但本函数独立定义，避免循环依赖。
    """
    if not DEEPSEEK_API_KEY:
        return None
    try:
        import requests
        s = requests.Session()
        s.trust_env = False
        r = s.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception:
        return None


def _parse_llm_response(reply: str) -> Optional[dict]:
    """解析 LLM 返回的 JSON"""
    if not reply:
        return None
    try:
        json_str = reply
        if "```json" in reply:
            json_str = reply.split("```json")[1].split("```")[0]
        elif "```" in reply:
            json_str = reply.split("```")[1].split("```")[0]

        result = json.loads(json_str.strip())

        # 校验字段
        direction = result.get("direction", "NEUTRAL")
        if direction not in ("BULL", "BEAR", "NEUTRAL"):
            direction = "NEUTRAL"

        confidence = int(result.get("confidence", 50))
        confidence = max(0, min(100, confidence))

        return {
            "direction": direction,
            "confidence": confidence,
            "contradiction_analysis": result.get("contradiction_analysis", ""),
            "reasoning": result.get("reasoning", ""),
            "risk_note": result.get("risk_note", ""),
            "trust_weight": result.get("trust_weight", {}),
            "source": "llm_reasoning",
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


# ── 主入口 ────────────────────────────────────────────────────────────────

def reason_with_llm(full_signal: dict, ensemble_pred: dict) -> dict:
    """LLM 辩证推理主入口

    当集成模型置信度不足或检测到矛盾信号时，调用 LLM 做辩证推理。
    如果 LLM 不可用或调用失败，回退到集成模型结果。

    参数:
        full_signal: compute_full_trading_signal() 的返回值
        ensemble_pred: predict_ensemble() 的返回值

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "source": "llm_reasoning" | "ensemble_fallback",
            "contradiction_analysis": str,
            "reasoning": str,
            "risk_note": str,
            "trust_weight": dict,
            "contradictions": list,
        }
    """
    # 检测矛盾
    contradictions = _detect_contradictions(full_signal)

    # 构建提示词
    system_prompt = _build_system_prompt()
    user_prompt = _build_reasoning_prompt(full_signal, ensemble_pred, contradictions)

    # 调用 LLM
    reply = _call_deepseek(user_prompt, system_prompt, max_tokens=1000)
    result = _parse_llm_response(reply)

    if result is None:
        # LLM 不可用，回退到集成模型
        return {
            "direction": ensemble_pred.get("direction", "NEUTRAL"),
            "confidence": ensemble_pred.get("confidence", 50.0),
            "source": "ensemble_fallback",
            "contradiction_analysis": "; ".join(contradictions) if contradictions else "无",
            "reasoning": "LLM不可用，回退到集成模型结果",
            "risk_note": "",
            "trust_weight": {},
            "contradictions": contradictions,
        }

    # LLM 结果带上矛盾列表
    result["contradictions"] = contradictions
    return result


def reason_if_needed(full_signal: dict, ensemble_pred: dict) -> dict:
    """按需触发 LLM 推理

    自动判断是否需要 LLM 介入：
    - 高置信度且无矛盾 → 直接返回集成模型结果
    - 低置信度或有矛盾 → 调用 LLM 辩证推理

    参数:
        full_signal: compute_full_trading_signal() 的返回值
        ensemble_pred: predict_ensemble() 的返回值

    返回:
        推理结果 dict，source 字段标识来源
    """
    should_trigger, reason = should_trigger_llm(ensemble_pred, full_signal)

    if not should_trigger:
        # 不需要 LLM，直接返回集成模型结果
        return {
            "direction": ensemble_pred.get("direction", "NEUTRAL"),
            "confidence": ensemble_pred.get("confidence", 50.0),
            "source": "ensemble_direct",
            "contradiction_analysis": "",
            "reasoning": f"集成模型置信度充足({ensemble_pred.get('confidence', 0):.1f})，无需LLM",
            "risk_note": "",
            "trust_weight": {},
            "contradictions": [],
            "trigger_reason": reason,
        }

    # 需要 LLM 介入
    result = reason_with_llm(full_signal, ensemble_pred)
    result["trigger_reason"] = reason
    return result

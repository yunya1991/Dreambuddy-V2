#!/usr/bin/env python3
"""
Agent A 专用 LLM 客户端 — 四级回退机制
优先级：千问 3.8 MAX → Trae (免费额度) → DeepSeek V4 → 基本规则引擎

每日配额控制：超出后自动回落下一级，系统不中断。

四级回退：
  1. 千问 3.8 MAX (阿里云百炼) — 主力模型，最高优先级
  2. Trae (trae.ai) — 免费额度，备用
  3. DeepSeek V4 (api.deepseek.com) — 付费备用
  4. 基本规则引擎 — 硬编码兜底（0 Token）
"""
import os, json, time, requests, ssl, warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib3.util.ssl_ import create_urllib3_context

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# ── 配置 ─────────────────────────────────────────────────────────────────
# 千问 3.8 MAX（最高优先级）
QWEN_API_KEY  = os.environ.get("QWEN_API_KEY", "")
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL    = os.environ.get("QWEN_MODEL", "qwen3.8-max")

TRAE_API_KEY     = os.environ.get("TRAE_API_KEY", "")
TRAE_BASE_URL    = os.environ.get("TRAE_BASE_URL", "https://api.trae.ai/v1")
TRAE_MODEL       = os.environ.get("TRAE_MODEL", "claude-sonnet-4-5")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE    = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL   = os.environ.get("DEEPSEEK_MODEL_V4", "deepseek-chat")

DAILY_LIMIT_QWEN     = int(os.environ.get("AGENT_A_QWEN_DAILY_LIMIT",     "60"))
DAILY_LIMIT_TRAE     = int(os.environ.get("AGENT_A_TRAE_DAILY_LIMIT",     "12"))
DAILY_LIMIT_DEEPSEEK = int(os.environ.get("AGENT_A_DEEPSEEK_DAILY_LIMIT", "24"))

QUOTA_FILE = Path(__file__).parent.parent / "data" / "agent_a_llm_quota.json"
SKILL_PATH = Path(__file__).parent.parent / "skills" / "agent-a-trading" / "SKILL.md"

# ── TLS 1.2 强制 Session（解决 macOS LibreSSL TLS 1.3 兼容性）─────────────
class TLS12Adapter(requests.adapters.HTTPAdapter):
    """强制 TLS 1.2 的 HTTPAdapter，避免 macOS LibreSSL TLS 1.3 握手失败"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

def _tls12_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.mount("https://", TLS12Adapter())
    return s

# ── 配额管理 ──────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_quota() -> dict:
    if QUOTA_FILE.exists():
        try:
            with open(QUOTA_FILE) as f:
                d = json.load(f)
            if d.get("date") == _today():
                return d
        except Exception:
            pass
    return {
        "date":          _today(),
        "qwen":          0,
        "trae":          0,
        "deepseek":      0,
        "rule_fallback": 0,
    }


def _save_quota(q: dict):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)


def _record_usage(provider: str):
    q = _load_quota()
    q[provider] = q.get(provider, 0) + 1
    _save_quota(q)


def _can_use(provider: str) -> Tuple[bool, str]:
    q = _load_quota()
    if provider == "qwen":
        if not QWEN_API_KEY:
            return False, "未配置 QWEN_API_KEY"
        if q.get("qwen", 0) >= DAILY_LIMIT_QWEN:
            return False, f"千问日配额已满({DAILY_LIMIT_QWEN}次)"
        return True, "ok"
    elif provider == "trae":
        if not TRAE_API_KEY:
            return False, "未配置 TRAE_API_KEY"
        if q.get("trae", 0) >= DAILY_LIMIT_TRAE:
            return False, f"Trae日配额已满({DAILY_LIMIT_TRAE}次)"
        return True, "ok"
    elif provider == "deepseek":
        if not DEEPSEEK_API_KEY:
            return False, "未配置 DEEPSEEK_API_KEY"
        if q.get("deepseek", 0) >= DAILY_LIMIT_DEEPSEEK:
            return False, f"DeepSeek日配额已满({DAILY_LIMIT_DEEPSEEK}次)"
        return True, "ok"
    return False, "unknown provider"


def get_quota_status() -> dict:
    """查询当日用量"""
    q = _load_quota()
    return {
        "date":          q["date"],
        "qwen":          f"{q.get('qwen',0)}/{DAILY_LIMIT_QWEN}",
        "trae":          f"{q.get('trae',0)}/{DAILY_LIMIT_TRAE}",
        "deepseek":      f"{q.get('deepseek',0)}/{DAILY_LIMIT_DEEPSEEK}",
        "rule_fallback": q.get("rule_fallback", 0),
    }


def get_available_provider() -> str:
    """返回当前可用的最高优先级 provider"""
    if _can_use("qwen")[0]:
        return "qwen"
    if _can_use("trae")[0]:
        return "trae"
    if _can_use("deepseek")[0]:
        return "deepseek"
    return "rule"

# ── LLM 调用实现 ──────────────────────────────────────────────────────────

def _call_qwen(prompt: str, system: str, max_tokens: int) -> str:
    """调用千问 3.8 MAX API（兼容 OpenAI 格式），内置 TLS 1.2 + SSL 重试"""
    for attempt in range(3):
        try:
            s = _tls12_session()
            resp = s.post(
                f"{QWEN_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":       QWEN_MODEL,
                    "messages":    [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    "max_tokens":  max_tokens,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2 and ("SSL" in str(e) or "EOF" in str(e)):
                time.sleep(1)
                continue
            raise


def _call_trae(prompt: str, system: str, max_tokens: int) -> str:
    s = requests.Session()
    s.trust_env = False
    resp = s.post(
        f"{TRAE_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {TRAE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model":       TRAE_MODEL,
            "messages":    [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens":  max_tokens,
            "temperature": 0.3,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_deepseek(prompt: str, system: str, max_tokens: int) -> str:
    s = requests.Session()
    s.trust_env = False
    resp = s.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model":       DEEPSEEK_MODEL,
            "messages":    [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens":  max_tokens,
            "temperature": 0.3,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _load_skill_content() -> str:
    """加载 SKILL 文档内容作为 system prompt 的一部分"""
    try:
        if SKILL_PATH.exists():
            with open(SKILL_PATH) as f:
                return f.read()
    except Exception:
        pass
    return ""

# ── 主入口：四级回退 ─────────────────────────────────────────────────────

def agent_a_llm_decide(
    market_data: dict,
    memory: dict,
    account_data: dict,
    max_tokens: int = 8000,
) -> Tuple[dict, str]:
    """
    Agent A 交易决策主入口
    四级回退：千问 3.8 MAX → Trae → DeepSeek → 基本规则

    返回: (decision_dict, provider_used)
    provider_used: "qwen" / "trae" / "deepseek" / "rule"
    """
    skill_content = _load_skill_content()

    system_prompt = f"""你是 Agent A — 一位顶级加密货币合约交易大师。
你严格按照以下 SKILL 框架进行每一轮交易决策。

【SKILL 框架】
{skill_content}

【重要】
- 严格按照 SKILL 中第九节的 JSON 格式输出，不要输出任何其他内容
- 从市场数据出发，结合记忆中的教训和当前大师风格做决策
- 不要编造数据，只使用提供的市场数据
- 如果信号不明确，选择 HOLD
"""

    user_prompt = _build_user_prompt(market_data, memory, account_data)

    # ── Level 1: 千问 3.8 MAX（最高优先级）──────────────────────────
    ok, reason = _can_use("qwen")
    if ok:
        try:
            reply = _call_qwen(user_prompt, system_prompt, max_tokens)
            decision = _parse_llm_output(reply)
            if decision and decision.get("action") in ("LONG", "SHORT", "HOLD"):
                _record_usage("qwen")
                return decision, "qwen"
        except Exception as e:
            err = str(e)
            if any(c in err for c in ["429", "quota", "credit", "rate limit"]):
                pass
            else:
                _record_usage("qwen")

    # ── Level 2: Trae ──────────────────────────────────────────────
    ok, reason = _can_use("trae")
    if ok:
        try:
            reply = _call_trae(user_prompt, system_prompt, max_tokens)
            decision = _parse_llm_output(reply)
            if decision and decision.get("action") in ("LONG", "SHORT", "HOLD"):
                _record_usage("trae")
                return decision, "trae"
        except Exception as e:
            err = str(e)
            if any(c in err for c in ["429", "quota", "credit", "rate limit"]):
                pass
            else:
                _record_usage("trae")

    # ── Level 3: DeepSeek V4 ───────────────────────────────────────
    ok, reason = _can_use("deepseek")
    if ok:
        try:
            reply = _call_deepseek(user_prompt, system_prompt, max_tokens)
            decision = _parse_llm_output(reply)
            if decision and decision.get("action") in ("LONG", "SHORT", "HOLD"):
                _record_usage("deepseek")
                return decision, "deepseek"
        except Exception as e:
            err = str(e)
            if any(c in err for c in ["429", "quota", "credit", "rate limit"]):
                pass
            else:
                _record_usage("deepseek")

    # ── Level 3: 基本规则引擎（兜底）───────────────────────────────
    decision = _rule_based_decision(market_data, memory, account_data)
    _record_usage("rule_fallback")
    return decision, "rule"


def _build_user_prompt(mkt: dict, memory: dict, acct: dict) -> str:
    """构建用户 prompt，包含市场数据、记忆、账户信息、A系列研报"""
    coins = mkt.get("coins", {})

    # ── 读取 A系列研报（Top3币种）────────────────────────────────────
    a1_a6_section = ""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "nodes"))
        from a1_research import _load_latest_a1_report, _load_latest_a6_report

        # 按24h涨跌幅绝对值排序，选Top3币种加载研报
        sorted_coins = sorted(
            coins.items(),
            key=lambda x: abs(x[1].get("ch24", 0)),
            reverse=True
        )
        top3_for_report = [name for name, _ in sorted_coins[:3]]
        if "BTC" not in top3_for_report:
            top3_for_report.append("BTC")

        for report_coin in top3_for_report[:3]:
            reasoning = []
            a1 = _load_latest_a1_report(report_coin, reasoning)
            if a1:
                a1_a6_section += f"""
【A1战略研报 - {report_coin}】（本地 {a1.get('report_time', '')}）
- 方向: {a1.get('direction', 'N/A')}
- 置信度: {a1.get('confidence', 0):.0%}
- 市场状态: {a1.get('market_regime', 'N/A')}
- 核心信号: {a1.get('core_signals', 'N/A')}"""

            a6 = _load_latest_a6_report(report_coin, reasoning)
            if a6:
                a1_a6_section += f"""
【A6情报监控 - {report_coin}】（本地 {a6.get('report_time', '')}）
- 方向: {a6.get('direction', 'N/A')}
- 风险等级: {a6.get('risk_level', 'N/A')}
- 告警: {a6.get('risk_warning', '无')}"""
        if reasoning:
            a1_a6_section += "\n---\n" + "\n".join(reasoning)
    except Exception:
        pass  # 读取失败不影响主流程

    coins_info = ""
    for coin, d in coins.items():
        coins_info += f"""
  - {coin}: 价格=${d.get('price', 0):.2f}, 24H={d.get('ch24', 0):+.2f}%, 4H={d.get('ch4h', 0):+.2f}%, 量比={d.get('vol_ratio', 1):.2f}x, RSI={d.get('rsi14', 50):.0f}"""

    opp_info = ""
    for coin, o in mkt.get("opp_map", {}).items():
        fr = o.get("funding", 0)
        opp_info += f"  - {coin}: 资金费率={fr*100:.4f}%\n"

    lessons_str = ""
    for i, lesson in enumerate(memory.get("lessons", [])[:10]):
        lessons_str += f"  {i+1}. {lesson.get('content', '')} (score={lesson.get('score', 0)})\n"

    recent_trades = ""
    for t in memory.get("recent_trades", [])[-5:]:
        recent_trades += (
            f"  - {t.get('timestamp','')[:10]} {t.get('coin','')} {t.get('action','')} "
            f"PnL={t.get('pnl_pct',0):+.2f}% master={t.get('master','')}\n"
        )

    evolution_params = memory.get("evolution", {}).get("adopted_params", {})
    evolution_str = ""
    if evolution_params:
        evolution_str = "\n".join(
            f"  - {k}: {v}" for k, v in evolution_params.items()
        )

    return f"""
【账户状态】
- 权益: ${acct.get('equity', 0):.2f} USDC
- 当前持仓: {list(acct.get('positions', {}).keys()) if acct.get('positions') else '无'}
- 连胜: {memory.get('win_streak', 0)} | 连败: {memory.get('loss_streak', 0)}
- 总交易数: {memory.get('total_trades', 0)}

【当前大师风格】
{memory.get('current_master', 'Jesse Livermore')}

【教训列表（Top 10）】
{lessons_str or '  暂无教训'}

【近期交易记录（最近5笔）】
{recent_trades or '  暂无记录'}

【进化系统采纳参数】
{evolution_str or '  暂无已采纳的进化参数'}

{a1_a6_section}

【市场扫描 — 所有标的】
{coins_info}

【资金费率信号】
{opp_info or '  无数据'}

【决策要求】
1. 必须遍历上面所有 {len(coins)} 个币种，逐一评估其交易机会
2. 对每个币种给出评分（0-100分），明确做多/做空/观望方向
3. 选择评分最高的币种作为最终决策标的
4. 不要默认选择BTC，必须基于数据客观评估每个币种的机会
5. 如果当前已有持仓，优先评估持仓币种的离场条件，再评估其他币种的新开仓机会
6. 严格按照 SKILL 框架的六维分析进行决策

【输出 JSON 格式】
{{
  "action": "LONG/SHORT/HOLD",
  "coin": "币种名称",
  "confidence": 0.0-1.0,
  "entry_price": 0,
  "stop_loss_price": 0,
  "take_profit_price": 0,
  "position_size_usdt": 0,
  "leverage": 3,
  "market_regime": "TREND_UP/TREND_DOWN/RANGE",
  "decision_rationale": "决策理由简述",
  "reasoning_steps": ["步骤1", "步骤2", ...],
  "per_coin_scores": {{
    "BTC": {{"score": 60, "direction": "LONG/SHORT/HOLD", "reason": "理由"}},
    "ETH": {{"score": 55, "direction": "HOLD", "reason": "理由"}},
    ...（所有币种）
  }},
  "current_master": "大师名称",
  "new_lesson": "",
  "lesson_score_universal": 3,
  "lesson_score_importance": 3,
  "master_switch_reason": "",
  "exit_suggestions": [
    {{"coin": "BTC", "reason": "离场原因"}}
  ],
  "update_exit_levels": [
    {{"coin": "BTC", "new_stop_loss": 0, "new_take_profit": 0}}
  ]
}}
"""


def _parse_llm_output(reply: str) -> Optional[dict]:
    """解析 LLM 输出的 JSON"""
    if not reply:
        return None

    text = reply.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 尝试提取 ```json ... ``` 块
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        try:
            return json.loads(text[start:end].strip())
        except Exception:
            pass

    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        try:
            return json.loads(text[start:end].strip())
        except Exception:
            pass

    # 尝试找到第一个 { 和最后一个 }
    if "{" in text and "}" in text:
        start = text.index("{")
        end = text.rindex("}") + 1
        try:
            return json.loads(text[start:end].strip())
        except Exception:
            pass

    return None

# ── 基本规则引擎（兜底）─────────────────────────────────────────────────

def detect_market_regime(mkt: dict) -> str:
    """
    基于市场统计判断整体市场状态（趋势 vs 震荡）。

    设计目标：规则兜底路径不再硬编码 regime，让 maybe_switch_master 的
    RANGE 分支能真正生效（此前 regime 永为 TREND_UP/DOWN，导致震荡市
    风格切换永不触发）。

    判断维度（取主流币聚合，避免单币噪声）：
      1. 动量强度：24h涨跌幅绝对值中位数（弱动量→震荡）
      2. EMA 结构：|ema20-ema50|/price 中位数（缠绕→震荡，拉开→趋势）
      3. RSI 分布：RSI 落在 40-60 中性区的占比（>=50%→震荡）
      4. 方向一致性：样本中上涨币种占比

    返回: "TREND_UP" / "TREND_DOWN" / "RANGE"
    """
    coins = mkt.get("coins", {})
    if not coins:
        return "RANGE"

    # 优先用主流币判断，避免小币噪声主导
    majors = [c for c in ["BTC", "ETH", "SOL"] if c in coins]
    sample = majors if majors else list(coins.keys())[:5]

    abs_ch24 = sorted([abs(coins[c].get("ch24", 0)) for c in sample])
    median_mom = abs_ch24[len(abs_ch24) // 2] if abs_ch24 else 0.0

    ema_spreads = []
    for c in sample:
        d = coins[c]
        p = d.get("price", 0)
        e20, e50 = d.get("ema20", 0), d.get("ema50", 0)
        if p > 0 and e20 > 0 and e50 > 0:
            ema_spreads.append(abs(e20 - e50) / p)
    median_spread = sorted(ema_spreads)[len(ema_spreads) // 2] if ema_spreads else 0.0

    rsi_vals = [coins[c].get("rsi14", 50) for c in sample]
    neutral_rsi_ratio = (sum(1 for r in rsi_vals if 40 <= r <= 60) / len(rsi_vals)) if rsi_vals else 0.0

    up_count = sum(1 for c in sample if coins[c].get("ch24", 0) > 0)
    up_ratio = up_count / len(sample) if sample else 0.5

    # 强震荡信号：动量弱 + EMA缠绕 + RSI中性
    if median_mom < 1.5 and median_spread < 0.01 and neutral_rsi_ratio >= 0.5:
        return "RANGE"
    # 弱动量且方向不一致 → 震荡
    if median_mom < 2.0 and not (up_ratio >= 0.67 or up_ratio <= 0.33):
        return "RANGE"
    # 方向一致且动量足够 → 趋势
    if up_ratio >= 0.67 and median_mom >= 1.5:
        return "TREND_UP"
    if up_ratio <= 0.33 and median_mom >= 1.5:
        return "TREND_DOWN"
    # 介于之间，默认偏震荡（保守）
    return "RANGE"


def _rule_based_decision(mkt: dict, memory: dict, acct: dict) -> dict:
    """
    基本规则引擎 — 当所有 LLM 都不可用时的兜底策略
    多因子：动量 + 量价 + 资金费率反向 + RSI + EMA
    支持进化系统动态调整参数
    """
    coins   = mkt.get("coins", {})
    opp_map = mkt.get("opp_map", {})
    reasoning = []

    evo_params = memory.get("evolution", {}).get("adopted_params", {})
    momentum_threshold = float(evo_params.get("momentum_threshold", 0.02))
    volume_threshold = float(evo_params.get("volume_threshold", 1.2))
    rsi_oversold = float(evo_params.get("rsi_oversold", 40))
    rsi_overbought = float(evo_params.get("rsi_overbought", 60))
    use_ema_cross = bool(evo_params.get("use_ema_cross", True))
    take_profit_pct = float(evo_params.get("take_profit_pct", 0.08))
    stop_loss_pct = float(evo_params.get("stop_loss_pct", 0.04))

    best_coin  = None
    best_score = 0
    best_side  = "LONG"
    best_info  = {}

    for coin, d in coins.items():
        score = 0
        side  = "LONG"

        ch24 = d.get("ch24", 0)
        ch4  = d.get("ch4h", 0)
        vr   = d.get("vol_ratio", 1.0)
        rsi  = d.get("rsi14", 50)
        ema20 = d.get("ema20", 0)
        ema50 = d.get("ema50", 0)
        price = d.get("price", 0)

        mom_ch24 = momentum_threshold * 100
        mom_ch4 = momentum_threshold * 25

        if ch24 > mom_ch24 and ch4 > mom_ch4:
            score += 2; side = "LONG"
        elif ch24 < -mom_ch24 and ch4 < -mom_ch4:
            score += 2; side = "SHORT"
        elif abs(ch24) > mom_ch24 * 0.5:
            score += 1; side = "LONG" if ch24 > 0 else "SHORT"

        if vr > volume_threshold:
            score += 1
        elif vr > volume_threshold * 0.67:
            score += 0.5

        opp = opp_map.get(coin, {})
        fr = opp.get("funding", 0)
        if abs(fr) > 0.0002:
            score += 1
            side = "SHORT" if fr > 0 else "LONG"

        if rsi < rsi_oversold:
            score += 1; side = "LONG"
        elif rsi > rsi_overbought:
            score += 1; side = "SHORT"

        if use_ema_cross and price > 0 and ema20 > 0 and ema50 > 0:
            if ema20 > ema50:
                score += 1; side = "LONG"
            elif ema20 < ema50:
                score += 1; side = "SHORT"

        loss_streak = memory.get("loss_streak", 0)
        if loss_streak >= 3:
            score = max(0, score - 1)

        if score > best_score:
            best_score = score
            best_coin  = coin
            best_side  = side
            best_info  = d

    min_score = 2 if memory.get("loss_streak", 0) >= 3 else 1

    if best_score < min_score or best_coin is None:
        reasoning.append("全市场无明确信号，观望")
        return {
            "action": "HOLD",
            "coin": None,
            "confidence": 0.4,
            "leverage": 1,
            "position_size_usdt": 0,
            "entry_price": None,
            "stop_loss_price": None,
            "take_profit_price": None,
            "market_regime": "RANGE",
            "current_master": memory.get("current_master", "Jesse Livermore"),
            "master_switch_reason": "",
            "decision_rationale": "规则引擎：信号不足，观望",
            "reasoning_steps": reasoning,
            "new_lesson": "",
            "lesson_score_universal": 0,
            "lesson_score_importance": 0,
        }

    confidence = min(0.5 + best_score * 0.07, 0.80)
    equity = min(acct.get("equity", 60.0), 60.0)
    pos_usdt = max(round(equity * 0.05, 2), 5.0)
    leverage = min(5, max(1, int(confidence * 5)))

    px = best_info.get("price", 0)
    sl = round(px * (1 - stop_loss_pct) if best_side == "LONG" else px * (1 + stop_loss_pct), 2)
    tp = round(px * (1 + take_profit_pct) if best_side == "LONG" else px * (1 - take_profit_pct), 2)

    # regime 基于市场整体统计判断（而非硬编码为方向），震荡市可输出 RANGE
    regime = detect_market_regime(mkt)

    reasoning.append(f"[规则引擎] 扫描 {len(coins)} 个标的")
    reasoning.append(f"市场状态: {regime}（基于主流币动量/EMA/RSI统计）")
    reasoning.append(f"最优标的: {best_coin} score={best_score}")
    reasoning.append(f"方向: {best_side} | 24H={best_info.get('ch24',0):+.1f}% 4H={best_info.get('ch4h',0):+.1f}%")
    reasoning.append(f"量比: {best_info.get('vol_ratio',1):.2f}x")
    reasoning.append(f"仓位: {pos_usdt} USDC × {leverage}x = {pos_usdt*leverage:.0f} 名义")
    if evo_params:
        reasoning.append(f"进化参数: {evo_params}")

    return {
        "action":             best_side,
        "coin":               best_coin,
        "confidence":         round(confidence, 3),
        "leverage":           leverage,
        "position_size_usdt": pos_usdt,
        "entry_price":        px,
        "stop_loss_price":    sl,
        "take_profit_price":  tp,
        "market_regime":      regime,
        "current_master":     memory.get("current_master", "Jesse Livermore"),
        "master_switch_reason": "",
        "decision_rationale": f"[规则引擎] {best_coin} {best_side} score={best_score} conf={confidence:.0%}",
        "reasoning_steps":    reasoning,
        "new_lesson":         "",
        "lesson_score_universal": 0,
        "lesson_score_importance": 0,
    }


# ── 快速测试 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Agent A LLM 客户端测试 ===")
    print(f"可用 Provider: {get_available_provider()}")
    print(f"配额状态: {get_quota_status()}")
    print()

    test_mkt = {
        "coins": {
            "BTC": {"price": 65000, "ch24": 3.5, "ch4h": 1.2, "vol_ratio": 1.8},
            "ETH": {"price": 3500,  "ch24": 5.2, "ch4h": 2.1, "vol_ratio": 2.2},
        },
        "opp_map": {
            "BTC": {"funding": 0.0001},
            "ETH": {"funding": -0.0002},
        },
    }
    test_mem = {
        "current_master": "Jesse Livermore",
        "lessons": [],
        "recent_trades": [],
        "win_streak": 0,
        "loss_streak": 0,
        "total_trades": 0,
    }
    test_acct = {"equity": 60.0, "positions": {}}

    decision, provider = agent_a_llm_decide(test_mkt, test_mem, test_acct)
    print(f"使用 Provider: {provider}")
    print(f"决策: {decision.get('action')} {decision.get('coin')} conf={decision.get('confidence'):.0%}")
    print(f"理由: {decision.get('decision_rationale')}")
    print()
    print(f"调用后配额: {get_quota_status()}")

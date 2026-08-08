#!/usr/bin/env python3
"""
LLM 客户端 — 精打细算版
优先级：千问 3.8 MAX → Trae(免费额度) → Claude → DeepSeek → 规则降级
每日配额控制：超出后自动回落规则引擎，系统不中断

每日上限（可在 .env 中覆盖）：
  LLM_DAILY_QWEN_LIMIT     = 60  次  (千问 3.8 MAX - 主力最高优先级)
  LLM_DAILY_TRAE_LIMIT     = 24  次  (Trae 免费额度)
  LLM_DAILY_CLAUDE_LIMIT   = 10  次
  LLM_DAILY_DEEPSEEK_LIMIT = 20  次

只在以下核心节点调用 LLM（由调用方声明 purpose）：
  "a3_seminar"    — 大师研讨，每次交易最多1次
  "a1_research"   — 深度调研，UNCERTAIN意图时才触发
  "a8_governance" — 治理环，每日最多1次
  "a9_exit"       — 智能离场评估
"""
import os, json, time, requests, ssl, warnings
from pathlib import Path
from datetime import datetime, timezone
from urllib3.util.ssl_ import create_urllib3_context

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# ── 配置 ─────────────────────────────────────────────────────────────────
# 千问 3.8 MAX（最高优先级 - 主力模型）
QWEN_KEY       = os.environ.get("QWEN_API_KEY", "")
QWEN_BASE      = os.environ.get("QWEN_BASE_URL", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL     = os.environ.get("QWEN_MODEL", "qwen3.8-max")

TRAE_KEY       = os.environ.get("TRAE_API_KEY", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
DEEPSEEK_KEY   = os.environ.get("DEEPSEEK_API_KEY", "")

TRAE_BASE      = os.environ.get("TRAE_BASE_URL", "https://api.trae.ai/v1")
TRAE_MODEL     = os.environ.get("TRAE_MODEL", "claude-sonnet-4-5")
DEEPSEEK_BASE  = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
ANTHROPIC_BASE = "https://api.anthropic.com/v1"
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"

QWEN_DAILY_LIMIT     = int(os.environ.get("AGENT_B_QWEN_DAILY_LIMIT",   os.environ.get("LLM_DAILY_QWEN_LIMIT",     "60")))
TRAE_DAILY_LIMIT     = int(os.environ.get("LLM_DAILY_TRAE_LIMIT",     "24"))
CLAUDE_DAILY_LIMIT   = int(os.environ.get("LLM_DAILY_CLAUDE_LIMIT",   "10"))
DEEPSEEK_DAILY_LIMIT = int(os.environ.get("LLM_DAILY_DEEPSEEK_LIMIT", "20"))

QUOTA_FILE = Path(__file__).parent.parent / "data" / "llm_quota.json"

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

# 每个 purpose 的每日最大调用次数（硬限）
PURPOSE_LIMITS = {
    "a3_seminar":    6,   # 最多6次/天（每4H一轮）
    "a1_research":   4,   # 最多4次/天（UNCERTAIN才触发）
    "a8_governance": 1,   # 每天1次治理分析
    "default":       3,   # 其他用途
}


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
    # 新的一天，重置
    return {
        "date":    _today(),
        "qwen":    0,
        "trae":    0,
        "claude":  0,
        "deepseek": 0,
        "by_purpose": {},
    }


def _save_quota(q: dict):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(q, f, indent=2)


def _can_use(provider: str, purpose: str) -> tuple[bool, str]:
    """返回 (是否可用, 原因)"""
    q = _load_quota()

    # 检查 provider 日总量
    if provider == "qwen" and q["qwen"] >= QWEN_DAILY_LIMIT:
        return False, f"千问日配额已满({QWEN_DAILY_LIMIT}次)"
    if provider == "trae" and q["trae"] >= TRAE_DAILY_LIMIT:
        return False, f"Trae日配额已满({TRAE_DAILY_LIMIT}次)"
    if provider == "claude" and q["claude"] >= CLAUDE_DAILY_LIMIT:
        return False, f"Claude日配额已满({CLAUDE_DAILY_LIMIT}次)"
    if provider == "deepseek" and q["deepseek"] >= DEEPSEEK_DAILY_LIMIT:
        return False, f"DeepSeek日配额已满({DEEPSEEK_DAILY_LIMIT}次)"

    # 检查 purpose 专项配额
    purpose_limit = PURPOSE_LIMITS.get(purpose, PURPOSE_LIMITS["default"])
    purpose_used  = q.get("by_purpose", {}).get(purpose, 0)
    if purpose_used >= purpose_limit:
        return False, f"{purpose}今日配额已满({purpose_limit}次)"

    return True, "ok"


def _record_usage(provider: str, purpose: str):
    q = _load_quota()
    q[provider] = q.get(provider, 0) + 1
    by_p = q.get("by_purpose", {})
    by_p[purpose] = by_p.get(purpose, 0) + 1
    q["by_purpose"] = by_p
    _save_quota(q)


def get_quota_status() -> dict:
    """供监控页查询当日用量"""
    q = _load_quota()
    return {
        "date":      q["date"],
        "qwen":      f"{q.get('qwen',0)}/{QWEN_DAILY_LIMIT}",
        "trae":      f"{q.get('trae',0)}/{TRAE_DAILY_LIMIT}",
        "claude":    f"{q.get('claude',0)}/{CLAUDE_DAILY_LIMIT}",
        "deepseek":  f"{q.get('deepseek',0)}/{DEEPSEEK_DAILY_LIMIT}",
        "by_purpose": q.get("by_purpose", {}),
    }


# ── LLM 调用 ─────────────────────────────────────────────────────────────

def _call_qwen(prompt: str, system: str, max_tokens: int) -> str:
    """调用千问 3.8 MAX API（兼容 OpenAI 格式），内置 TLS 1.2 + SSL 重试"""
    for attempt in range(3):
        try:
            s = _tls12_session()
            resp = s.post(
                f"{QWEN_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {QWEN_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model":       QWEN_MODEL,
                    "messages":    [{"role": "system", "content": system},
                                    {"role": "user",   "content": prompt}],
                    "max_tokens":  max_tokens,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2 and ("SSL" in str(e) or "EOF" in str(e)):
                time.sleep(1)
                continue
            raise


def _call_trae(prompt: str, system: str, max_tokens: int) -> str:
    s = requests.Session(); s.trust_env = False
    resp = s.post(
        f"{TRAE_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {TRAE_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model":       TRAE_MODEL,
            "messages":    [{"role": "system", "content": system},
                            {"role": "user",   "content": prompt}],
            "max_tokens":  max_tokens,
            "temperature": 0.3,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_deepseek(prompt: str, system: str, max_tokens: int) -> str:
    s = requests.Session(); s.trust_env = False
    resp = s.post(
        f"{DEEPSEEK_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model":       DEEPSEEK_MODEL,
            "messages":    [{"role": "system", "content": system},
                            {"role": "user",   "content": prompt}],
            "max_tokens":  max_tokens,
            "temperature": 0.3,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_claude(prompt: str, system: str, max_tokens: int) -> str:
    s = requests.Session(); s.trust_env = False
    resp = s.post(
        f"{ANTHROPIC_BASE}/messages",
        headers={"x-api-key": ANTHROPIC_KEY,
                 "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json={
            "model":    CLAUDE_MODEL,
            "system":   system,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


# ── 主入口 ────────────────────────────────────────────────────────────────

def llm_chat(prompt: str,
             system: str = "你是专业加密货币交易分析师，回答简洁，中文输出。",
             max_tokens: int = 300,
             purpose: str = "default") -> str:
    """
    调用 LLM，内置五层保障：
      1. 配额检查（超出 → 直接返回空，不调用）
      2. 千问 3.8 MAX（主力模型，最高优先级）
      3. Trae fallback（免费额度）
      4. Claude fallback
      5. DeepSeek fallback
      6. 四者都不可用/超配额 → 返回空（调用方走规则降级）

    purpose 参数控制专项配额：
      "a3_seminar" / "a1_research" / "a8_governance" / "a9_exit" / "default"
    """
    # ── 尝试 千问 3.8 MAX（最高优先级 - 主力）──────────────────────────
    if QWEN_KEY:
        ok, reason = _can_use("qwen", purpose)
        if ok:
            try:
                reply = _call_qwen(prompt, system, max_tokens)
                _record_usage("qwen", purpose)
                return reply
            except Exception as e:
                err = str(e)
                if not any(c in err for c in ["429", "529", "quota", "credit", "overloaded", "rate limit"]):
                    _record_usage("qwen", purpose)

    # ── Fallback: Trae（免费额度）─────────────────────────────────────
    if TRAE_KEY:
        ok, reason = _can_use("trae", purpose)
        if ok:
            try:
                reply = _call_trae(prompt, system, max_tokens)
                _record_usage("trae", purpose)
                return reply
            except Exception as e:
                err = str(e)
                if not any(c in err for c in ["429", "529", "quota", "credit", "overloaded"]):
                    _record_usage("trae", purpose)

    # ── Fallback: Claude ──────────────────────────────────────────────
    if ANTHROPIC_KEY:
        ok, reason = _can_use("claude", purpose)
        if ok:
            try:
                reply = _call_claude(prompt, system, max_tokens)
                _record_usage("claude", purpose)
                return reply
            except Exception as e:
                err = str(e)
                if not any(c in err for c in ["429", "529", "quota", "credit", "overloaded"]):
                    _record_usage("claude", purpose)

    # ── Fallback: DeepSeek ───────────────────────────────────────────
    if DEEPSEEK_KEY:
        ok, reason = _can_use("deepseek", purpose)
        if ok:
            try:
                reply = _call_deepseek(prompt, system, max_tokens)
                _record_usage("deepseek", purpose)
                return reply
            except Exception as e:
                err = str(e)
                if not any(c in err for c in ["429", "quota", "credit"]):
                    _record_usage("deepseek", purpose)

    # ── 完全降级：返回空，调用方走规则引擎 ──────────────────────────────
    return ""


def llm_available() -> str:
    """当前可用提供商（不考虑配额）"""
    if QWEN_KEY:        return "qwen"
    if TRAE_KEY:        return "trae"
    if ANTHROPIC_KEY:   return "claude"
    if DEEPSEEK_KEY:    return "deepseek"
    return "none"


def llm_quota_ok(purpose: str = "default") -> bool:
    """快速检查当前 purpose 是否还有配额（供 ChainPlanner 预判）"""
    if QWEN_KEY:
        ok, _ = _can_use("qwen", purpose)
        if ok: return True
    if TRAE_KEY:
        ok, _ = _can_use("trae", purpose)
        if ok: return True
    if ANTHROPIC_KEY:
        ok, _ = _can_use("claude", purpose)
        if ok: return True
    if DEEPSEEK_KEY:
        ok, _ = _can_use("deepseek", purpose)
        if ok: return True
    return False


if __name__ == "__main__":
    print("配额状态:", get_quota_status())
    print("可用LLM:", llm_available())
    print("a3_seminar配额:", llm_quota_ok("a3_seminar"))

    reply = llm_chat(
        "BTC当前RSI=65，24H涨3%，用一句话判断方向",
        max_tokens=60, purpose="a3_seminar"
    )
    print("回复:", reply or "(无，规则降级)")
    print("调用后配额:", get_quota_status())

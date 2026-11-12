"""
情绪分析引擎 v2.0
P1 升级：规则引擎 ← (FAIL-OPEN 3层回退) ← 双FinBERT模型（ProsusAI/finbert 英文 + yiyanghkust/finbert-tone-chinese 中文）

接口**完全不变**（字节兼容）：
    SentimentEngine.analyze_text(text: str) -> Dict[str, Any]
        返回 dict 必须含 4 键:
            score       : float ∈ [-1, +1]
            sentiment   : str ∈ {positive, neutral, negative}
            categories  : List[str]（∈ {监管政策,项目动态,市场数据,社区热话} 子集，可空）
            matches     : Dict[str, int]（键 positive/negative，正整数或 0）
"""

import math
import os
import re
import warnings
from typing import Any, Dict, List, Optional


# ===========================================================================
# 公共辅助函数 1：指数时间衰减权重（TC-7 测）
# ===========================================================================
def time_decay_weight(age_hours: float, tau_hours: float = 24.0) -> float:
    """w = exp(-age_hours / tau_hours)
    - age_hours ≤ 0（含 ts=0 解析失败 fail-open）→ w = 1.0，字节等价旧等权
    - 默认 τ = 24h：
        age =  0h → 1.0000
        age = 24h → 0.3679 (1/e)
        age = 72h → 0.0498 (1/e³)
    """
    if age_hours <= 0.0:
        return 1.0
    safe_tau = max(1e-6, float(tau_hours))
    safe_age = max(0.0, float(age_hours))
    return math.exp(-safe_age / safe_tau)


# ===========================================================================
# 公共辅助函数 2：CJK 占比（双语路由用，可被 TC monkeypatch 强制走指定引擎）
# ===========================================================================
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def chinese_ratio(text: str) -> float:
    """CJK 字符占比（排除空白做分母）；空串返回 0.0；
    >= 0.30 判定为中文主体，走 finbert-tone-chinese。
    """
    if not text:
        return 0.0
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    cjk_count = sum(1 for c in non_ws if _CJK_RE.match(c))
    return cjk_count / len(non_ws)


# ===========================================================================
# 关键词（与旧实现一致，不增不减；用于规则引擎 fallback + categories 检测 + matches）
# ===========================================================================

# 正面关键词
POSITIVE_KEYWORDS = [
    "bullish",
    "rally",
    "surge",
    "approval",
    "inflow",
    "positive",
    "adoption",
    "上涨",
    "利好",
    "突破",
    "机构",
    "流入",
    "买入",
    "看涨",
    "做多",
    "approval",
    "ETF",
    "批准",
    "通过",
    "吸筹",
    "增持",
    "创新高",
]

# 负面关键词
NEGATIVE_KEYWORDS = [
    "bearish",
    "crash",
    "selloff",
    "ban",
    "hack",
    "fraud",
    "liquidation",
    "outflow",
    "reject",
    "negative",
    "下跌",
    "利空",
    "暴跌",
    "监管",
    "清算",
    "卖出",
    "看跌",
    "做空",
    "爆仓",
    "减持",
    "创新低",
    "被禁",
    "风险",
    "抛售",
]

# 分类关键词映射（保留结构；FinBERT 模式下 categories 仍由正则算，零开销结构对齐）
CATEGORY_KEYWORDS = {
    "监管政策": [
        "SEC",
        "CFTC",
        "FED",
        "美联储",
        "监管",
        "政策",
        "法案",
        "条例",
        "批准",
        "禁令",
        "ETF批准",
        "ETF通过",
    ],
    "项目动态": [
        "发布",
        "更新",
        "升级",
        "合并",
        "分叉",
        "空投",
        "上线",
        "下架",
        "合作",
        "partnership",
    ],
    "市场数据": [
        "流入",
        "流出",
        "交易量",
        "持仓",
        "爆仓",
        "杠杆",
        "资金费率",
        "多空比",
        "MVRV",
        "SOPR",
    ],
    "社区热话": ["病毒式传播", "热点", "FOMO", "社区", "推特", "讨论", "关注", "热度", "meme"],
}


# ===========================================================================
# §3.3 常量：两模型 label → 极性映射（未知 label 默认回旧规则，不猜）
# ===========================================================================

# ProsusAI/finbert 官方三档（+ LABEL_0/1/2 前缀兼容包装版）
FINBERT_EN_LABEL_MAP: Dict[str, float] = {
    "positive": +1.0,
    "POSITIVE": +1.0,
    "LABEL_1": +1.0,
    "LABEL_POSITIVE": +1.0,
    "negative": -1.0,
    "NEGATIVE": -1.0,
    "LABEL_2": -1.0,
    "LABEL_NEGATIVE": -1.0,
    "neutral": 0.0,
    "NEUTRAL": 0.0,
    "LABEL_0": 0.0,
    "LABEL_NEUTRAL": 0.0,
}

# yiyanghkust/finbert-tone-chinese 的 label 契约（模型只输出 LABEL_0/1/2）
# 0=Neutral / 1=Positive / 2=Negative（config.id2label 已确认）
FINBERT_ZH_LABEL_CONTRACTS: Dict[str, Dict[str, float]] = {
    "finbert-tone-chinese": {"LABEL_0": 0.0, "LABEL_1": +1.0, "LABEL_2": -1.0},
}
_FINBERT_ZH_DEFAULT_MODEL_ID = "yiyanghkust/finbert-tone-chinese"

# finbert-tone-chinese（中文金融情绪）— 中文 label 名兼容 + LABEL_* 前缀兼容
FINBERT_ZH_LABEL_MAP: Dict[str, float] = {
    "positive": +1.0,
    "POSITIVE": +1.0,
    "利好": +1.0,
    "POS": +1.0,
    "看涨": +1.0,
    "negative": -1.0,
    "NEGATIVE": -1.0,
    "利空": -1.0,
    "NEG": -1.0,
    "看跌": -1.0,
    "neutral": 0.0,
    "NEUTRAL": 0.0,
    "Neutral": 0.0,
    "中性": 0.0,
    "NEU": 0.0,
    "持平": 0.0,
    "Positive": +1.0,
    "Negative": -1.0,
    "LABEL_0": 0.0,
    "LABEL_1": +1.0,
    "LABEL_2": -1.0,
}


# ===========================================================================
# 情绪引擎主类
# ===========================================================================
class SentimentEngine:
    """情绪分析引擎 v2：规则 ←(3层回退)← 双 FinBERT 模型懒加载。"""

    # 公开固定常量（供下游测试/调参）
    SCORE_THRESH_POS = 0.2
    SCORE_THRESH_NEG = -0.2
    ZH_RATIO_THRESHOLD = 0.30  # CJK 占比 ≥ 30% → 中文模型
    MAX_TEXT_LEN = 512  # BERT 512 token 限制

    # 英文 FinBERT 本地模型目录（9-基本面分析/models/finbert）：
    # 存在则优先本地加载（离线可用、免联网下载）；env FINBERT_EN_MODEL_PATH 可覆盖
    _FINBERT_EN_LOCAL_DIR: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models",
        "finbert",
    )
    # 中文 FinBERT 本地模型目录（18 域现役 finbert-tone-chinese）；env FINBERT_ZH_MODEL_PATH 可覆盖
    _FINBERT_ZH_LOCAL_DIR: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "18-数据获取中心",
        "models",
        "finbert-tone-chinese",
    )

    # 进程级共享模型（类属性）：SentimentEngine 每次 new 都重新 load 模型代价极高
    # （caller 如 odaily_newsflash 逐条 new 引擎 → 每条新闻重复 load 400MB 模型）。
    # ready=True 后所有实例复用同一 pipeline 对象。
    _SHARED_ENGINES: Dict[str, Any] = {
        "ready": False,
        "en": None,
        "zh": None,
        "en_id": "",
        "zh_id": "",
    }

    # 垃圾文本过滤（保守高置信，避免误杀正经金融新闻；gdelt 实测垃圾率 ~1.4%）：
    # 规则1 SEO导航/注册引流 = 导航词 + 行动词 同时出现（单词不杀，如诈骗报道是有效负面新闻）
    _GARBAGE_SEO_NAV = re.compile(r"official\s+(?:website|site)|官网", re.IGNORECASE)
    _GARBAGE_NAV_ACTION = re.compile(
        r"how\s+to|beginner|registration|register|sign\s*up|login|登录|注册", re.IGNORECASE
    )
    # 规则2 广告推广优惠码（单词即高置信垃圾）
    _GARBAGE_PROMO = re.compile(
        r"promotional\s+offer|promo\s+code|coupon\s+code|referral\s+code|invite\s+code"
        r"|bonus\s+code|邀请码|优惠码|注册码",
        re.IGNORECASE,
    )

    def __init__(self):
        # --- 旧规则编译（保留，FAIL-OPEN 用） ---
        self.positive_pattern = self._build_pattern(POSITIVE_KEYWORDS)
        self.negative_pattern = self._build_pattern(NEGATIVE_KEYWORDS)
        self.category_patterns: Dict[str, re.Pattern] = {
            cat: self._build_pattern(kws) for cat, kws in CATEGORY_KEYWORDS.items()
        }

        # --- 环境变量 L0：USE_FINBERT=0 → 全程旧规则 ---
        self._use_finbert_env_ok: bool = os.environ.get("USE_FINBERT", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
            "",
        )

        # --- L1：模型懒加载占位（首次 analyze_text 调用时初始化；__init__ 绝不加载） ---
        self._eng_ready: bool = False
        self._en_pipe: Optional[Any] = None  # ProsusAI/finbert
        self._zh_pipe: Optional[Any] = None  # yiyanghkust/finbert-tone-chinese
        self._en_model_id: str = "ProsusAI/finbert"
        self._zh_model_id: str = _FINBERT_ZH_DEFAULT_MODEL_ID
        self._last_model: str = "rule_fallback"
        self._last_confidence: float = 0.0
        self._en_label_map: Dict[str, float] = dict(FINBERT_EN_LABEL_MAP)
        self._zh_label_map: Dict[str, float] = dict(FINBERT_ZH_LABEL_MAP)

    # ---------------------------------------------------------------- utils
    def _build_pattern(self, keywords: List[str]) -> re.Pattern:
        """构建正则表达式模式（与 v1 完全一致，零行为变化）。"""
        escaped = [re.escape(kw) for kw in keywords]
        pattern = "|".join(escaped)
        return re.compile(pattern, re.IGNORECASE)

    # =========================================================
    # 旧规则实现（原 analyze_text 原样迁入，改名私有，TC-6 fallback 走这里）
    # 修复：空文本 "" 时 matches 原来是 []（List），修正为 {"positive":0,"negative":0}（Dict）
    #       （TC-1 RED 捕获此 bug；其他行为一字不动）
    # =========================================================
    def _analyze_text_rule(self, text: str) -> Dict[str, Any]:
        if not text:
            # 修复：空返回 matches 改为 Dict（类型对齐），其他字段与旧版同值
            return {
                "score": 0.0,
                "sentiment": "neutral",
                "categories": [],
                "matches": {"positive": 0, "negative": 0},
            }

        positive_matches = self.positive_pattern.findall(text)
        negative_matches = self.negative_pattern.findall(text)

        pos_count = len(positive_matches)
        neg_count = len(negative_matches)
        total = pos_count + neg_count

        if total == 0:
            score = 0.0
            sentiment_label = "neutral"
        else:
            score = float(pos_count - neg_count) / float(total)
            if score > self.SCORE_THRESH_POS:
                sentiment_label = "positive"
            elif score < self.SCORE_THRESH_NEG:
                sentiment_label = "negative"
            else:
                sentiment_label = "neutral"

        # 分类检测（正则，零模型依赖）
        categories: List[str] = []
        for cat, pattern in self.category_patterns.items():
            if pattern.search(text):
                categories.append(cat)

        return {
            "score": round(float(score), 4),
            "sentiment": sentiment_label,
            "categories": categories,
            "matches": {"positive": int(pos_count), "negative": int(neg_count)},
        }

    # =========================================================
    # L1 懒加载：首次需要模型时才 import + 构造 pipeline
    # 任何异常 → _eng_ready=False（后续所有调用自动走旧规则，不重试）
    # =========================================================
    def _ensure_engines(self) -> None:
        if self._eng_ready:
            return
        if not self._use_finbert_env_ok:
            # L0：env 已关闭，永不加载模型
            self._eng_ready = False
            return
        shared = SentimentEngine._SHARED_ENGINES
        if shared.get("ready"):
            self._en_pipe = shared.get("en")
            self._zh_pipe = shared.get("zh")
            self._en_model_id = shared.get("en_id") or self._en_model_id
            self._zh_model_id = shared.get("zh_id") or self._zh_model_id
            if self._zh_pipe is not None:
                self._zh_label_map.update(
                    self._build_label_map_from_pipe(self._zh_pipe, self._zh_model_id)
                )
            self._eng_ready = True
            return
        try:
            from transformers import pipeline as _hf_pipeline  # type: ignore
        except Exception:
            # transformers 未安装 / sentencepiece 缺失（中文 tokenizer 需要）等 → 回旧
            self._eng_ready = False
            return
        try:
            # 英文：ProsusAI/finbert（truncation=True 显式防长文本）
            # 模型源优先级：env FINBERT_EN_MODEL_PATH → 本地 models/finbert → HF repo_id 联网下载
            en_model: Any = "ProsusAI/finbert"
            env_path = os.environ.get("FINBERT_EN_MODEL_PATH", "").strip()
            if env_path and os.path.isdir(env_path):
                en_model = env_path
            elif os.path.isdir(self._FINBERT_EN_LOCAL_DIR):
                en_model = self._FINBERT_EN_LOCAL_DIR
            self._en_model_id = self._normalize_model_id(en_model)
            self._en_pipe = _hf_pipeline(
                "text-classification",
                model=en_model,
                truncation=True,
                max_length=self.MAX_TEXT_LEN,
            )
        except Exception:
            self._en_pipe = None
        try:
            # 中文：yiyanghkust/finbert-tone-chinese（18 域现役本地模型，离线可用）
            # 模型源优先级：env FINBERT_ZH_MODEL_PATH → 18/models/finbert-tone-chinese → HF repo_id
            zh_model: Any = _FINBERT_ZH_DEFAULT_MODEL_ID
            zh_env_path = os.environ.get("FINBERT_ZH_MODEL_PATH", "").strip()
            if zh_env_path and os.path.isdir(zh_env_path):
                zh_model = zh_env_path
            elif os.path.isdir(self._FINBERT_ZH_LOCAL_DIR):
                zh_model = self._FINBERT_ZH_LOCAL_DIR
            self._zh_model_id = self._normalize_model_id(zh_model)
            self._zh_pipe = _hf_pipeline(
                "text-classification",
                model=zh_model,
                truncation=True,
                max_length=self.MAX_TEXT_LEN,
            )
            if self._zh_pipe is not None:
                self._zh_label_map.update(
                    self._build_label_map_from_pipe(self._zh_pipe, self._zh_model_id)
                )
        except Exception:
            self._zh_pipe = None

        # 至少一个引擎加载成功才算 ready（两都失败 → 回旧规则，但不阻塞）
        self._eng_ready = (self._en_pipe is not None) or (self._zh_pipe is not None)
        shared.update(
            ready=self._eng_ready,
            en=self._en_pipe,
            zh=self._zh_pipe,
            en_id=self._en_model_id,
            zh_id=self._zh_model_id,
        )

    # ---------------------------------------------------------------- labels
    def _normalize_model_id(self, model_ref: Any) -> str:
        """本地绝对路径 → 稳定模型标识（契约键优先，其次目录名），避免把机器路径写进产物。"""
        ref = str(model_ref or "").strip()
        if not ref:
            return ""
        if os.path.isdir(ref):
            key = self._model_contract_key(ref)
            return key or os.path.basename(ref.rstrip(os.sep))
        return ref

    def _model_contract_key(self, model_id: str) -> str:
        """把 model_id / 本地路径归一为 label 契约键（如 finbert-tone-chinese）。"""
        mid = str(model_id or "").lower()
        for key in FINBERT_ZH_LABEL_CONTRACTS:
            if key in mid:
                return key
        return ""

    def _build_label_map_from_pipe(self, pipe: Any, model_id: str) -> Dict[str, float]:
        """从 pipeline 的 config.id2label + 已知模型契约构建 label→polarity 映射。

        finbert-tone-chinese 只输出 LABEL_0/1/2，不解析契约就会全部落空 → 静默回中性。
        """
        mapping: Dict[str, float] = {}
        cfg = getattr(getattr(pipe, "model", None), "config", None)
        id2label = getattr(cfg, "id2label", None) or {}
        for _idx, name in id2label.items():
            key = str(name)
            # LABEL_* 是通用占位名，语义只能由模型契约确定，不能凭编号猜
            if key.upper().startswith("LABEL_"):
                continue
            if key in FINBERT_ZH_LABEL_MAP:
                mapping[key] = FINBERT_ZH_LABEL_MAP[key]
        contract = FINBERT_ZH_LABEL_CONTRACTS.get(self._model_contract_key(model_id))
        if contract:
            mapping.update(contract)
        if not mapping:
            warnings.warn(
                f"中文模型 {model_id} 的 label 未映射，将回退规则引擎",
                RuntimeWarning,
                stacklevel=2,
            )
        return mapping

    # =========================================================
    # 垃圾文本检测（保守：只拦高置信 SEO 导航/引流/广告，宁漏勿杀）
    # =========================================================
    def _is_garbage_text(self, text: str) -> bool:
        """SEO 导航/注册引流/优惠码广告 → True；正经新闻（含诈骗报道等负面新闻）→ False。"""
        if not text:
            return False
        # 规则1：导航词 + 行动词 同时出现（如 "How to Access the OKX Official Website ... Registration"）
        if self._GARBAGE_SEO_NAV.search(text) and self._GARBAGE_NAV_ACTION.search(text):
            return True
        # 规则2：广告优惠码类（如 "Promotional Offer" / "referral code"）
        if self._GARBAGE_PROMO.search(text):
            return True
        return False

    # =========================================================
    # L2：单条 FinBERT 推理（一条异常 → None → 本条回旧规则）
    # =========================================================
    def _try_pipe_score(self, text: str) -> Optional[float]:
        """
        返回 ∈ [-1,+1] 的极性化分数（polarity × confidence）；
        任何异常 / 未知 label / 模型不存在 → None，由调用方回旧规则。
        """
        self._ensure_engines()
        if not self._eng_ready:
            return None

        safe_text = text[: self.MAX_TEXT_LEN] if text else ""
        if not safe_text.strip():
            return None

        # 路由：中文比例 ≥ 阈值 → zh，否则 en
        zh_rate = chinese_ratio(safe_text)
        if zh_rate >= self.ZH_RATIO_THRESHOLD:
            pipe, label_map = self._zh_pipe, self._zh_label_map
            model_id = self._zh_model_id
        else:
            pipe, label_map = self._en_pipe, self._en_label_map
            model_id = self._en_model_id

        if pipe is None:
            # 路由目标模型不可用（如中文模型未装）→ 回旧规则（关键词打分），
            # 不再跨语言回退：英文模型对中文文本恒输出 neutral，等于伪造中性信号。
            self._last_model = "rule_fallback"
            return None

        try:
            out = pipe(safe_text)
        except Exception:
            self._last_model = "unavailable"
            return None
        # pipeline 标准返回：List[Dict]，取第一条
        if not isinstance(out, list) or not out:
            self._last_model = "unavailable"
            return None
        item = out[0]
        if not isinstance(item, dict):
            self._last_model = "unavailable"
            return None
        label = str(item.get("label") or "")
        conf = item.get("score")
        if not isinstance(conf, (int, float)):
            conf = 0.5  # 未知置信度 → 中性保守
        conf = max(0.0, min(1.0, float(conf)))
        polar = label_map.get(label)
        if polar is None:
            # 未知 label → 不猜，回旧规则（fail-safe）
            self._last_model = "rule_fallback"
            return None
        # 极性 × 置信度 → [-1,1]
        raw = polar * conf
        self._last_model = model_id
        self._last_confidence = round(float(conf), 4)
        return max(-1.0, min(1.0, float(raw)))

    # =========================================================
    # 主入口（对外签名 100% 不变 → Dict 四键齐全）
    # 流程：L0 env → L1 懒加载 → L2 推理（FAIL→旧规则）→ 归一映射
    # =========================================================
    def analyze_text(self, text: str, with_meta: bool = False) -> Dict[str, Any]:
        """
        分析单条文本的情绪（接口字节兼容 v1）。

        Args:
            text: 待分析的文本 str
            with_meta: False（默认）→ 仅返回 4 键（字节兼容旧调用方）；
                       True → 追加 model（finbert-tone-chinese / ProsusAI/finbert /
                       rule_fallback / unavailable）与 confidence 溯源字段。

        Returns:
            dict，键：
                score       float ∈ [-1, +1]
                sentiment   str   ∈ {positive, neutral, negative}（阈值 ±0.2 与旧规则一致）
                categories  List[str]（正则检测 categories，零模型依赖）
                matches     Dict[str,int]（键 positive/negative → 正/负命中计数）
                model       str（仅 with_meta=True）
                confidence  float（仅 with_meta=True）
        """

        def _out(payload: Dict[str, Any], model: str, confidence: float) -> Dict[str, Any]:
            if not with_meta:
                return payload
            payload["model"] = model
            payload["confidence"] = round(max(0.0, min(1.0, float(confidence))), 4)
            return payload

        # 先就算规则规则结果（categories + matches 永远走正则，零模型依赖，结构对齐TC-1）
        rule = self._analyze_text_rule(text)
        # 垃圾文本（SEO 导航/引流/广告）→ 强制中性（四键结构对齐，score=0 不产生情绪信号）
        if self._is_garbage_text(text or ""):
            return _out(
                {
                    "score": 0.0,
                    "sentiment": "neutral",
                    "categories": list(rule["categories"]),
                    "matches": dict(rule["matches"]),
                },
                "rule_fallback",
                0.0,
            )
        # L0：USE_FINBERT=0 → 完全走旧规则（字节等价）
        if not self._use_finbert_env_ok:
            return _out(rule, "rule_fallback", abs(float(rule["score"])))

        # L1/L2：尝试 FinBERT；失败 → rule_score 兜底
        pipe_score = self._try_pipe_score(text)
        if pipe_score is None:
            return _out(rule, self._last_model or "rule_fallback", abs(float(rule["score"])))

        # 有模型分数 → 替换 score 和 sentiment；保留 categories + matches（正则计算）
        score_raw = float(pipe_score)
        score_clamped = max(-1.0, min(1.0, score_raw))
        if score_clamped > self.SCORE_THRESH_POS:
            sent = "positive"
        elif score_clamped < self.SCORE_THRESH_NEG:
            sent = "negative"
        else:
            sent = "neutral"
        return _out(
            {
                "score": round(score_clamped, 4),
                "sentiment": sent,
                "categories": list(rule["categories"]),
                "matches": dict(rule["matches"]),
            },
            self._last_model,
            self._last_confidence,
        )

    # ==================================================================
    # 批量分析（保留原 analyze_batch API 行为不变：内部调 analyze_text，天然升级）
    # ==================================================================
    def analyze_batch(self, texts: List[str]) -> Dict[str, Any]:
        """
        批量分析文本（与 v1 字节等价：同样逐个调 analyze_text）。
        返回: dict 键：score / sentiment / sentiment_index / count /
                    positive_count / negative_count / category_distribution
        """
        if not texts:
            return {
                "score": 0.0,
                "sentiment": "neutral",
                "count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "category_distribution": {},
                "sentiment_index": 50,
            }

        results = [self.analyze_text(t) for t in texts]

        total_score = sum(float(r["score"]) for r in results)
        avg_score = total_score / float(len(results))

        pos_count = sum(1 for r in results if r["sentiment"] == "positive")
        neg_count = sum(1 for r in results if r["sentiment"] == "negative")

        cat_dist: Dict[str, int] = {}
        for r in results:
            for cat in r["categories"]:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

        if avg_score > self.SCORE_THRESH_POS:
            sentiment = "positive"
        elif avg_score < self.SCORE_THRESH_NEG:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # 0-100 指数（与 v1 公式完全一致）
        sentiment_index = int((float(avg_score) + 1.0) * 50.0)

        return {
            "score": round(float(avg_score), 4),
            "sentiment": sentiment,
            "sentiment_index": sentiment_index,
            "count": len(texts),
            "positive_count": int(pos_count),
            "negative_count": int(neg_count),
            "category_distribution": cat_dist,
        }

    # ==================================================================
    # 恐惧/贪婪映射（与 v1 完全一致，零改动）
    # ==================================================================
    def get_fear_greed_estimate(self, sentiment_index: int) -> str:
        if sentiment_index >= 75:
            return "extreme_greed"
        elif sentiment_index >= 60:
            return "greed"
        elif sentiment_index >= 40:
            return "neutral"
        elif sentiment_index >= 25:
            return "fear"
        else:
            return "extreme_fear"


# ===========================================================================
# 工厂函数（与 v1 签名完全一致）
# ===========================================================================
def create_sentiment_engine() -> SentimentEngine:
    """创建情绪分析引擎实例（保留 v1 工厂函数）。"""
    return SentimentEngine()

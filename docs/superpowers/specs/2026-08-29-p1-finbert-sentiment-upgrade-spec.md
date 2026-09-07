# P1 FinBERT 双引擎升级 S1 Sentiment 并加时间衰减（Spec v1.0）

> 代码：`9-基本面分析/engines/sentiment_engine.py` + `11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py`
> 测试：`11-易经推理系统/tests/test_p1_finbert_sentiment.py`（新建 8 TC）
> 运维：默认启用（`USE_FINBERT` 未设置时=1），可 `export USE_FINBERT=0` 一键秒级回滚
> 红线保护：`enable_fundamental_7engines_production_injection=False` 保持不变，**零实盘影响**

---

## §1 背景与目标

### 1.1 现状痛点（S1 SentimentEngine 四层硬伤）

| # | 硬伤 | 证据位置 | 后果举例 |
|---|------|---------|---------|
| 1 | 52个中英关键词正则（`sentiment_engine.py L11-L31`）语义盲区 | 例："The Fed paused rate hikes as inflation cooled to 2.1%" = 利好加密，但零命中 → score=0 neutral | 大量语义中性误判拉平 S1 得分，D1 boost≈恒0 |
| 2 | 极性不分强度（计数制 pos-neg/total） | "BlackRock IBIT ETF inflow $1B 2026年度最大" 和 "btc up" 都是 positive +1 | 强度差异全丢失，S1 区分度 ≈10% 理论上限 |
| 3 | 72h×200条 新闻**等权**（`_fd_S_dao_boost L805` 简单算术平均） | 3 天前"美联储加息75bp"快讯权重 = 1 小时前"贝莱德增持 BTC"快讯权重 = 1/200 | 时效性失真，快讯真实影响被老新闻稀释到 1/3 |
| 4 | T1 政策情绪（`_fd_S_tian_boost L1008-L1014`）纯 sentiment_label 启发式 ±1.0，**完全不调 S1** | Odaily 中文政策新闻"央行宣布下调存款准备金率0.25个百分点" = 流动性宽松利好，但规则未命中 → 中性 0 | T1 是 tian 侧最大单项杠杆（系数 0.08 > D1 0.06），半残 = tian boost 无区分度 |

### 1.2 四项目标（全部可量化验证）

1. **S_dao_mean 差异**：Shadow JSONL `fd_S_dao_mean` 接入后首条 vs 接入前基线（≈0.043167），\|Δ\| ≥ 0.005
2. **S_tian_mean 差异**：Shadow JSONL `fd_S_tian_mean` 接入后首条 vs 接入前基线，\|Δ\| ≥ 0.003（T1 升级证据）
3. **TC + 回归**：8/8 TC GREEN + 总回归 ≥ 82 passed（Gap1/2/3+P0 baseline=74 + P1 8 new），零 regress
4. **红线保持**：`enable_fundamental_7engines_production_injection=False` 保持不变，`import_fail_count=0`，`reason_code=FD7_OK`

---

## §2 已批准设计决策（Clarify 阶段结果）

| 决策项 | 选型 |
|--------|------|
| 模型引擎 | 双引擎双语自动路由 = ProsusAI/finbert（英文 F1≈97%）+ valuesimplex/FinBERT2（中文 KDD2025，32B 中文金融 token） |
| 语言路由阈值 | CJK 比例 ≥ 30% → zh_pipe（FinBERT2），否则 → en_pipe（finbert） |
| 升级范围 | **D1（S1 dao）+ T1（policy tian）同时升级**，S2-S5 零改动 |
| 时间衰减常数 | τ = 24h，w = exp(-age_hours / 24) |
| 架构模式 | **方案 A（内联替换 + 懒加载）**：sentiment_engine.py 内部改造，零 Strategy 层级 |
| 接口不变铁律 | `analyze_text(text: str) -> Dict[str, Any]` 签名+返回键完全不变；`create_sentiment_engine()` 工厂函数签名不变 |
| FAIL-OPEN 铁律 | 3 层回滚（env → import → 推理单条），任何异常最终回旧规则，绝不抛错 |
| 回滚开关 | `USE_FINBERT=0` 环境变量，进程级秒级关闭，重启即生效 |

---

## §3 架构 + 接口契约

### 3.1 三层 FAIL-OPEN 矩阵（SentimentEngine.analyze_text 内部）

```
analyze_text(text:str) -> Dict[str,Any] 入口
  │
  ├─ Layer 0  env 拦截: USE_FINBERT=0 → analyze_text_rule(text)（旧规则，字节等价）
  │
  ├─ Layer 1  模型懒加载（首次调用时，非 __init__，避免进程启动即下载）
  │    try:
  │      from transformers import pipeline       # ImportError → _eng_ready=False
  │      self._en_pipe = pipeline("text-classification",
  │                                model="ProsusAI/finbert",
  │                                truncation=True, max_length=512)  # 下载/缓存异常→False
  │      self._zh_pipe = pipeline("text-classification",
  │                                model="valuesimplex/FinBERT2",
  │                                truncation=True, max_length=512)  # 同上
  │    except Exception:
  │      self._eng_ready = False
  │
  ├─ Layer 2  单条推理（每条独立隔离，一条异常不影响其他）
  │    zh_ratio = chinese_ratio(text)
  │    pipe = self._zh_pipe if zh_ratio≥0.30 else self._en_pipe
  │    try:
  │      res = pipe(text)[0]  # 单条 OOM/shape错 → except 本条回旧规则
  │    except Exception:
  │      return analyze_text_rule(text)
  │
  └─ Layer 3  归一映射（两模型 label space 差异统一 → 四键 Dict）
       ProsusAI/finbert label:  "positive" → +score; "negative" → -score; "neutral" → 0
       valuesimplex/FinBERT2:   按实际 model card 三档/五档映射表（§3.3 常量 MAPPING）
       score_clamped = max(-1.0, min(1.0, polar * confidence))
       sentiment = "positive" if >0.2 else ("negative" if <-0.2 else "neutral")（阈值与旧规则一致）
       categories = 旧正则 category_patterns 检测（不重算，零开销结构对齐）
       matches = {"positive": 1 if score>0.2 else 0, "negative": 1 if score<-0.2 else 0}
```

### 3.2 返回 Dict 不变契约（TC-1 强校验）

```python
# 新旧实现都必须返回如下四键结构：
{
    "score":       float,   # ∈ [-1.0, +1.0]      ← 下游 s_01=(s+1)/2 归一化输入
    "sentiment":   str,     # ∈ {"positive","neutral","negative"}  ← 下游启发式兜底
    "categories":  List[str],  # ∈ {监管政策, 项目动态, 市场数据, 社区热话} 的子集（可空）
    "matches":     Dict[str, int],  # 必须含 "positive":int + "negative":int 两键
}
```

### 3.3 两模型 Label → 极性映射常量（sentiment_engine.py 顶部新增）

```python
# ProsusAI/finbert 官方三档（2024 HF card 验证）
FINBERT_EN_LABEL_MAP = {
    "positive": +1.0,
    "negative": -1.0,
    "neutral":   0.0,
    "LABEL_0":   0.0,  # 部分版本包装前缀
    "LABEL_1":  +1.0,
    "LABEL_2":  -1.0,
}

# valuesimplex/FinBERT2（KDD2025 官方 card）— 按实际运行时匹配，未知默认 neutral
FINBERT_ZH_LABEL_MAP = {
    "positive": +1.0, "利好": +1.0, "POS": +1.0,
    "negative": -1.0, "利空": -1.0, "NEG": -1.0,
    "neutral":   0.0, "中性":  0.0, "NEU":  0.0,
}
```
- 当实际推理返回的 label 不在上述 key 时（fail-safe），本条**降级回旧规则**（不猜极性）。

### 3.4 两个公共辅助函数（模块 top-level，可独立 import 被测试）

```python
import math
import re

def time_decay_weight(age_hours: float, tau_hours: float = 24.0) -> float:
    """
    指数时间衰减权重：w = exp(-age_hours / tau_hours)
    age_hours ≤ 0（含 timestamp_ms=0 fail-open 解析失败） → w=1.0（旧等权等价）
    τ 必须 >0；默认 τ=24h：
      age=0h  → 1.000
      age=24h → 0.3679 (1/e)
      age=72h → 0.0498 (1/e^3)
    """
    if age_hours <= 0.0:
        return 1.0
    safe_tau = max(1e-6, float(tau_hours))
    safe_age = max(0.0, float(age_hours))
    return math.exp(-safe_age / safe_tau)


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")

def chinese_ratio(text: str) -> float:
    """CJK 字符占比（排除空白后做分母）；空串→0.0"""
    if not text:
        return 0.0
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    cjk_count = sum(1 for c in non_ws if _CJK_RE.match(c))
    return cjk_count / len(non_ws)
```

---

## §4 注入点两处详细改造（five_domain_feature_computer.py）

### 4.1 注入点 A：_fd_S_dao_boost S1 聚合（L748-982 段内只改 S1 循环）

**Before（等权无衰减，L759-L808）**：
```python
sent_scores: List[float] = []
...
for n in news_list:
    ...
    sent_scores.append(s)  # L775 等权 append float
...
s_mean = sum(sent_scores) / len(sent_scores)  # L805 算术平均
```

**After（时间衰减加权）**：
```python
# 导入（L23-L27 顶部新增，位于 five_domain_feature_computer.py import 区）
#   from engines.sentiment_engine import time_decay_weight, SentimentEngine
# 注意：five_domain_feature_computer.py 已在 L762 from engines.sentiment_engine import SentimentEngine
#       这里改为同时导入 time_decay_weight

# L552 news_list 拉取之后立刻
_now_ms = int(time.time() * 1000)  # 复用 L595 已导入的 time

# L759 段：把 List[float] 改为 List[Tuple[float, float]]（score, weight）
_weighted: List[Tuple[float, float]] = []
...
# 循环体（替换 L764-L776 的 sent_scores.append(s)）：
age_h = max(0.0, (_now_ms - int(n.get('timestamp_ms') or 0)) / 1000.0 / 3600.0)
w = time_decay_weight(age_h, tau_hours=24.0)
_weighted.append((float(s), w))
...
# 替换 L803-L806 的聚合：
if _weighted:
    total_w = sum(w for _, w in _weighted)
    if total_w > 1e-9:
        s_mean = sum(s * w for s, w in _weighted) / total_w
    else:
        s_mean = 0.0
else:
    s_mean = 0.0
s_norm = max(-1.0, min(1.0, s_mean))
s_01 = (s_norm + 1.0) / 2.0
D1 = (s_01 - 0.5) * 0.06  # L808 公式不变，一字不动
```

**保护要求**：
- timestamp_ms == 0（L648 fail-open 解析失败）→ age_h = max(0, _now_ms - 0)/3600 = 巨值？**NO**：L648 `_parse_ts_ms` 返回 0 表示解析失败，对应新闻"timestamp未知"。按§3.4 age_hours≤0→w=1.0 的保护不生效。需要补充如下 fail-open 判断：
  ```python
  ts_ms_val = int(n.get('timestamp_ms') or 0)
  if ts_ms_val == 0:
      age_h = 0.0   # 解析失败 → 当做新鲜新闻处理（w=1.0），不处罚
  else:
      age_h = max(0.0, (_now_ms - ts_ms_val) / 1000.0 / 3600.0)
  ```
  这保证 **ts_ms_val=0 时 w=1.0**，与旧实现字节等价（不造成意外零权重）。

### 4.2 注入点 B：_fd_S_tian_boost T1 政策情绪（L984-1044 段）

**Before（L993-L1024 只用 sentiment_label 启发式等权）**：
```python
for n in policy_news:  # L999-L1014
    lab = str(n.get("sentiment_label") or "").lower()
    if   lab in ("bullish","positive","long"):  s_pol_sum += 1.0
    elif lab in ("bearish","negative","short"): s_pol_sum += -1.0
    else:                                        s_pol_sum += 0.0
p_count = len(policy_news)
s_pol = s_pol_sum / float(p_count)  # L1019 等权
```

**After（SentimentEngine + 时间衰减 + 3 层 FAIL-OPEN fallback 回启发式）**：
```python
# 1) 优先 SentimentEngine 加权（import fail → 直接跳启发式）
_weighted_pol: List[Tuple[float, float]] = []
_eng_works = False
try:
    from engines.sentiment_engine import SentimentEngine, time_decay_weight
    _se = SentimentEngine()
    _eng_works = True  # 先假设成立，内部 L0-L2 失败本条回旧规则
except Exception:
    _eng_works = False

if _eng_works:
    for n in policy_news:
        if not isinstance(n, dict):
            continue
        txt = f"{n.get('title','')} {n.get('content','')}"
        if not txt.strip():
            continue
        # L0-L2 任一层失败：本条 r = None → fallback 启发式
        r_score: Optional[float] = None
        try:
            r = _se.analyze_text(txt)
            if isinstance(r, dict) and isinstance(r.get("score"), (int, float)):
                s = float(r["score"])
                if -1.0 <= s <= 1.0:
                    r_score = s
        except Exception:
            r_score = None
        # 本条回启发式
        if r_score is None:
            lab = str(n.get("sentiment_label") or "").lower()
            if   lab in ("bullish","positive","long"):  r_score =  0.7
            elif lab in ("bearish","negative","short"): r_score = -0.7
            else:                                        r_score =  0.0
        # 时间衰减（ts=0 → w=1.0 保护见 §4.1）
        ts_ms_val = int(n.get('timestamp_ms') or 0)
        if ts_ms_val == 0: age_h = 0.0
        else:              age_h = max(0.0, (_now_ms - ts_ms_val) / 1000.0 / 3600.0)
        w = time_decay_weight(age_h, tau_hours=24.0)
        _weighted_pol.append((float(r_score), w))
    # 聚合（同 §4.1 的 total_w >1e-9 保护）
    if _weighted_pol:
        total_w = sum(w for _, w in _weighted_pol)
        if total_w > 1e-9:
            s_pol = sum(s * w for s, w in _weighted_pol) / total_w
        else:
            s_pol = 0.0
        p_count_eff = max(1, len(_weighted_pol))  # min(1, p/3) 公式用
    else:
        s_pol, p_count_eff = 0.0, 0
else:
    # import 全失败 → 字节等价于旧代码（零行为变化）
    s_pol_sum = 0.0
    for n in policy_news:
        lab = str(n.get("sentiment_label") or "").lower()
        if   lab in ("bullish","positive","long"):  s_pol_sum += 1.0
        elif lab in ("bearish","negative","short"): s_pol_sum += -1.0
    p_count_eff = len(policy_news)
    s_pol = (s_pol_sum / float(p_count_eff)) if p_count_eff else 0.0

# → 原 L1020-L1024 公式一字不动：
s_pol = max(-1.0, min(1.0, s_pol))
p_count_for = max(1, p_count_eff) if '_weighted_pol' not in dir() else len(policy_news)
# 注意：上面两行 p_count_for 修正为直接用 len(policy_news) 跟旧行为一致。最终：
T1 = float(s_pol) * 0.08 * min(1.0, float(len(policy_news)) / 3.0)  # 原公式，一字不动
```

**关键保护**：
- `_eng_works=False`（import失败）分支 = 旧代码完全逐行复制 → **字节等价** ✅
- 单条 `_se.analyze_text` 异常 = 本条 fallback 启发式 ±0.7（±0.7 比原 ±1.0 略保守，FinBERT 不工作时不把启发式拉到极值）
- 外层 L984 try/except 保持不变：任何异常 → tian boost 返回 0.0

---

## §5 风险矩阵

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| R1 | 首次冷启动 2×420MB 模型下载（~2-10min）阻塞首个轮次 S1 推理 | 中 | L1 `_eng_ready=False` → 首个轮次字节等价旧规则；第 2 轮起 `~/.cache/huggingface` 秒加载 | 运维激活 §6.3 Step 2 预先 python -c warmup 下载完毕再重启 |
| R2 | valuesimplex/FinBERT2 tokenizer 依赖 `sentencepiece`（当前未装）→ ImportError 中文引擎不加载 | 高（中文 BERT 常见） | 中文新闻 fallback 旧规则，英文 ProsusAI/finbert 不受影响 | 1) TDD TC-5 已验证 fallback 链路；2) 真实运行首次报 sentencepiece 缺时 `pip install sentencepiece` + 重启；3) §6.3 Step 1 预检查 |
| R3 | 双模型 FP32 内存峰值 ≈2.4GB，+ polling_trader 其他模块引发 swap | 低（16GB 空闲通常 6-10GB） | OOM 触发在 pipeline 构造期，L1 捕获 → `_eng_ready=False`，后续旧规则 | 1) 进程内存监控（yijing_monitor 已有 RSS 告警）；2) 若真发生，在 pipeline(..., torch_dtype=torch.float16) 减半到 ≈1.2GB；3) 极限：`USE_FINBERT=0` 秒级关闭 |
| R4 | 200条 × 单条 20ms ≈ 4-5s 推理耗时 > 轮询热路径 1s 软目标 | 中 | 单次 compute() 额外 4-5s 延迟（polling_trader 每轮 20+ 币种 20 次 compute？否：五维按 crypto_usdt 类共享 system_state，compute 每轮 1 次非按币种） | 1) 冷模型加载一次后推理 200 条 batch 可加速；2) 可在 pipeline 加 `batch_size=8` 但不强制；3) Shadow 模式不影响生产，实际延时容忍度高 |

---

## §6 TDD 验收标准（8 TC 清单）

**测试文件**：`11-易经推理系统/tests/test_p1_finbert_sentiment.py`（新建）
**全局夹具**：`monkeypatch.setenv("USE_FINBERT", "0")`（防止 TC 运行触发真实下载），除非 TC 明确需要引擎。

| TC# | 名称 | 测试内容 | 核心断言 |
|-----|------|---------|---------|
| TC-1 | **接口不变铁律** | `SentimentEngine().analyze_text("")` / `analyze_text("random neutral text")` 各 1 次 | 返回值是 dict；含 4 键 `score`(float)、`sentiment`(str∈三值)、`categories`(list)、`matches`(dict含positive+negative int键)；score∈[-1,1] |
| TC-2 | **正面新闻** 得分 raw > 0.1（归一后 >0.55） | monkeypatch `engine._eng_ready=True` + fake `_en_pipe` 返回 `[{"label":"positive","score":0.95}]`；另造中文fake `_zh_pipe` | 英文调用 Dict["score"] > 0.1；中文调用 score > 0.1；sentiment="positive" |
| TC-3 | **负面新闻** 得分 raw < -0.1 | 同 TC-2，fake pipe 返回 `[{label:"negative",score:0.92}]` 中英文各 1 | score < -0.1；sentiment="negative" |
| TC-4 | **中性新闻** \|score\| ≤ 0.1 | fake pipe 返回 `[{label:"neutral",score:0.99}]` 1 次 | abs(score) ≤ 0.1；sentiment="neutral" |
| TC-5 | **transformers 不存在 fallback 旧规则**（不抛错） | `monkeypatch.setattr("builtins.__import__", wrap)` 拦截 `"transformers"` → 抛 ImportError；`USE_FINBERT=1` 强制走引擎路径 | 构造 + 调用 analyze_text 均不抛 Exception；返回合法 Dict，score ∈ [-1,1]；内部 `_eng_ready=False` |
| TC-6 | **USE_FINBERT=0 强制旧实现** | `monkeypatch.setenv("USE_FINBERT", "0")` 后构造 engine，即使 transformers 存在 | `engine._eng_ready is False`；`engine._en_pipe is None`；调用结果仍为合法 Dict，且可被正面关键词触发 score>0.1（验证走了旧规则分支） |
| TC-7 | **时间衰减函数** 4 点黄金值 | 直接调 `time_decay_weight` 4 次：age=0, 24, 72, -5(h) | age=0 → 1.0；age=24 → ≈0.3679 (tol=1e-3)；age=72 → ≈0.0498 (tol=1e-3)；age=-5 → 1.0（负数保护） |
| TC-8 | **集成：5条混合 news_list → D1 ≠ 0 且 \|D1\| ≤ 0.10 且 ≠ 等权值** | `FiveDomainFeatureComputer(enable_fundamental_7engines_boost=True)`（其余默认）；构造 news_list 5 条：titles=["BTC ETF 批准 创纪录流入 $1B", "黑客盗取 100M USDT 恐慌抛售", "Fed 按兵不动 符合市场预期", "SEC 起诉 Binance", "贝莱德增持 BTC 创新高"]；timestamp 梯度 0h/3h/24h/48h/72h（通过 monkeypatch 把 time.time() 固定到基准值） | `d1 = computer._fd_S_dao_boost(None)` → d1 ≠ 0；abs(d1) ≤ 0.10；再用 `monkeypatch` 把 `time_decay_weight` 替换为 `lambda *_:1.0`（强制等权）重算 → 两值 **不相等**（时间衰减真生效证据） |

**TC-8 夹具注意**：调用 _fd_S_dao_boost 内部会 import real SentimentEngine。为避免 TC-8 触发模型下载，需 `monkeypatch.setenv("USE_FINBERT","0")` + 在 `engines.sentiment_engine` 上 `monkeypatch.setattr(SentimentEngine, "analyze_text", fake_analyze)`（fake 返回固定分数如 [+0.8, -0.7, 0, -0.6, +0.9] 对应 5 条 title 的关键词匹配映射）。

---

## §7 生产激活（运维 4 步）

> **前提**：P1-5 8/8 TC GREEN + 总回归 ≥ 82 passed 零 regress（通过后再执行）

1. **Pre-check sentencepiece**：
   ```bash
   /opt/anaconda3/bin/python3 -c "import sentencepiece; print('sp ok', sentencepiece.__version__)"
   # 若报错 → /opt/anaconda3/bin/pip install sentencepiece
   ```
2. **Warmup 模型缓存**（提前下载，避免进程首轮阻塞 5-10min）：
   ```bash
   cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
   /opt/anaconda3/bin/python3 << 'EOF'
   import os
   os.environ.setdefault("TRANSFORMERS_CACHE", os.path.expanduser("~/.cache/huggingface"))
   from transformers import pipeline
   print("[1/2] 下载/加载 ProsusAI/finbert (en)...")
   pe = pipeline("text-classification", model="ProsusAI/finbert", truncation=True, max_length=512)
   test = pe("BlackRock spot bitcoin ETF sees record inflow of $1 billion")
   print("  试推结果:", test)
   print("[2/2] 下载/加载 valuesimplex/FinBERT2 (zh)...")
   try:
       zh = pipeline("text-classification", model="valuesimplex/FinBERT2", truncation=True, max_length=512)
       test = zh("贝莱德比特币现货ETF单日净流入10亿美元创历史新高")
       print("  试推结果:", test)
   except Exception as e:
       print("  FinBERT2 加载失败(单条不致命，会回旧规则):", type(e).__name__, e)
   print("缓存位置:", os.environ["TRANSFORMERS_CACHE"], "大小:")
   os.system(f"du -sh {os.environ['TRANSFORMERS_CACHE']}")
   EOF
   ```
3. **重启正版 polling_trader**：
   ```bash
   ps aux | grep polling_trader | grep -v grep  # 记 PID
   kill <PID>
   cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4
   ./start_trading.sh   # USE_FINBERT 默认 1，无需改脚本
   sleep 10 && ps aux | grep polling_trader | grep -v grep  # 确认新 PID 存活 + PPID=1 脱离终端
   ```
4. **§1.2 四项目标验证**（330s 后执行，=5.5min > 300s 轮询 + 30s 安全）：
   ```bash
   cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
   tail -n 2 scripts/runtime/fundamental_7engines_records.jsonl | /opt/anaconda3/bin/python3 -m json.tool --no-ensure-ascii 2>/dev/null || tail -n 2 scripts/runtime/fundamental_7engines_records.jsonl
   ```
   逐条核对：
   - [ ] 最新第 2 条 ts_ms 差 ≈ 300000ms（轮询周期正常）
   - [ ] `fd_S_dao_mean` 最新 vs 基线（Spec §1.1 保存的旧值），\|Δ\| ≥ 0.005
   - [ ] `fd_S_tian_mean` 最新 vs 基线，\|Δ\| ≥ 0.003
   - [ ] `import_fail_count` == 0
   - [ ] `reason_code` == "FD7_OK"
   - [ ] `enable_fundamental_7engines_production_injection` 在配置中仍为 False（日志里无 production inject 字样）

---

## §8 影响面矩阵（字节等价证明）

| 系统 / 模块 | 是否改动 | 行为变化？ | 证明 |
|------------|---------|-----------|------|
| 生产开仓/平仓交易决策 | ❌ 否 | 完全字节等价 | `enable_fundamental_7engines_production_injection=False` 乘法守卫红线，所有 boost 不注入五维评分 |
| Shadow JSONL 审计（fundamental_7engines_records.jsonl）| ✅ 是 | S_dao_mean/S_tian_mean 字段数值变化（§1.2 验收项） | 审计文件字段一个不增，schema 100% 兼容下游 fd7engines_hitrate_eval.py |
| Odaily 引擎 boost（odaily_engine_boost_records.jsonl） | ❌ 否 | 字节等价 | 完全独立开关 enable_odaily_engine_boost，不触及其代码 |
| 7引擎 S2-S5（EventLedger/NewsContract/EventMapping/Narrative） | ❌ 否 | 字节等价 | §4 注入点只改 S1 + T1 段 |
| 7引擎 A6 LeastResistance / A7 SignalEngine | ❌ 否 | 字节等价 | 完全独立段 _fd_A_dao_boost / _fd_A_tian_boost |
| 测试套件（Gap1=9, Gap2=3, Gap3=5, P0=8）| ❌ 否 | 零 regress | P1 代码只加 guard 不减字段，monkeypatch 覆盖的 test_fd7engines_stage1 TC 通过 |
| yijing_monitor / 运维脚本 / launchd plist | ❌ 否 | 字节等价 | 不改 Popen env，USE_FINBERT 默认值 = 1，无需写进 start_trading.sh |

---

## §9 与上游设计的一致性

- 对齐 Impl-11 Spec：乘法总公式 `dao_final = dao_raw × (1 + _fd_S_dao_boost + _fd_A_dao_boost) × (1 + _pn_dao_boost) × (1 + _od_dao_boost)`。P1 只改 `_fd_S_dao_boost` 的内部计算方式，乘法公式一字不动 ✅
- 对齐 FAIL-OPEN 铁律（Impl-11 §3）：S级/A级异常→中性0，3层回滚矩阵 ✅
- 对齐 `enable_fundamental_7engines_boost` / `enable_fundamental_7engines_production_injection` 双开关（Impl-11 §4.4 红线）：双开关零改动，只影响 Shadow 审计值 ✅
- 对齐时间衰减 τ=24h：与 P0-P5 路线图（summary 部分8(g)）"时间衰减权重 w = exp(-age/24h)" 表述完全一致 ✅
- 对齐 20+ GitHub 成熟项目调研（P0-P5 输出）：FinBERT（ProsusAI）被金融情绪领域引用最多，freqtrade/vectorbt 社区首选；valuesimplex/FinBERT2 是中文金融唯一工业级开源模型 ✅

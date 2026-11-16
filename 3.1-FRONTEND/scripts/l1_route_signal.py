# -*- coding: utf-8 -*-
"""L1 路由门控信号端到端产出脚本 (P3: SACG 编排 + 门控信号透传)。

由前端 /api/data/query 路由调用（execFile 模式）。
输入: JSON {message, intent?}（intent 可由前端 L1_INTENT_REGISTRY v3 预测透传）
输出: JSON 最后一行
  {
    success, intent, handled, answer, data, degraded,
    route_signal: RouteConfidenceResult.to_dict()
      # decision=L1_DIRECT → handled=true，answer 为零 token 直答结果
      # decision=L2_HANDOFF → handled=false，前端转 SSE 并透传 l1_intent_hint
  }

链路:
  意图识别（对齐 TS fallbackPattern 顺序）
  → L0 cognitive.recall（core/l0_foundation.py scope，FAIL-OPEN）
  → core.route_confidence.evaluate_route（C3 匹配度 + C4 预测误差，阈值单一事实源）
  → 确定性关键词注册表意图（whale_flow / calendar_event）：跳过 recall 门控直接单维直答
  → L1_DIRECT: 复用 data_query_executor 十意图执行器 + settle 沉淀
  → L2_HANDOFF: 不执行，仅回传信号

阈值禁止第二套：0.65 / 3 / 0.3 全部由 core.route_confidence 引用 C3/C4 常量。
"""

import json
import os
import re
import sys

# 接入 34 系统 core（与 data_query_executor 同构：脚本目录 → 34 系统根）
_TRAINING_SYS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "34-前端应用训练系统",
)
if _TRAINING_SYS_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_SYS_DIR)

# 脚本目录入 path，复用同目录 data_query_executor（execFile 运行时解释器已自动加入，显式兜底）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# 54 模块指标注册表（S1 唯一事实源）：判断「注册表可命中的查询类问法」
_L1AGG_ROOT = os.path.join(_SCRIPTS_DIR, "..", "..", "54-L1架构能力聚合层")
if _L1AGG_ROOT not in sys.path:
    sys.path.insert(0, _L1AGG_ROOT)

# 41 文件索引系统：L1 语义意图检索（SPEC-41-L1 §3.3）
# 注意：追加到 sys.path 末尾（非 insert(0)），避免 41 的 core（有 __init__.py）
# 遮蔽 34 的 core（l1_route_signal 需从 34 core 导入 cognitive_router 等）。
# 41 的 IntentMatcher 通过 importlib 以独立包名加载，不依赖 core 命名空间。
_INDEX_ROOT = os.path.join(_SCRIPTS_DIR, "..", "..", "41-文件索引系统")
if _INDEX_ROOT not in sys.path:
    sys.path.append(_INDEX_ROOT)

# 语义意图匹配器（懒加载：embedder 模型按需加载，不阻塞模块导入）
# 注意：34 的 core 是正规包（有 __init__.py），会遮蔽 41 的 core，
# 因此用 importlib 以独立包名 _l1_semantic_core 加载 41 模块。
# FAIL-OPEN：导入失败或环境变量关闭时，_semantic_matcher 为 None，退回纯正则
_L1_SEMANTIC_ENABLED = os.environ.get("L1_SEMANTIC_MATCH", "1") != "0"
_semantic_matcher = None


def _load_semantic_matcher():
    """通过 importlib 加载 41 的 IntentMatcher（避开与 34 core 的包名冲突）。"""
    import importlib.util
    import types

    pkg_name = "_l1_semantic_core"
    pkg_path = os.path.join(_INDEX_ROOT, "core")
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [pkg_path]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    # 按依赖顺序加载子模块
    for mod_name in ("embedder_bridge", "intent_vector_store", "intent_matcher"):
        full_name = f"{pkg_name}.{mod_name}"
        if full_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(
            full_name, os.path.join(pkg_path, f"{mod_name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{pkg_name}.intent_matcher"].IntentMatcher()


if _L1_SEMANTIC_ENABLED:
    try:
        _semantic_matcher = _load_semantic_matcher()
    except Exception:  # noqa: BLE001
        _semantic_matcher = None

from core.cognitive_router import evaluate_match  # noqa: E402
from core.l0_foundation import get_l0  # noqa: E402
from core.route_confidence import (  # noqa: E402
    L1_DIRECT,
    L2_HANDOFF,
    RouteConfidenceResult,
    evaluate_route,
)
from data_query_executor import (  # noqa: E402
    exec_asset_class_trend,
    exec_calendar_event,
    exec_contradiction_insight,
    exec_data_insight,
    exec_data_query,
    exec_event_analysis,
    exec_fundamental_valuation,
    exec_leader_compare,
    exec_metric_series,
    exec_news_search,
    exec_path_insight,
    exec_persistence_strength,
    exec_price_query,
    exec_risk_control,
    exec_stat_query,
    exec_technical_analysis,
    exec_technical_indicator,
    exec_top_correlation,
    exec_whale_flow,
    resolve_source,
    settle_to_cognitive,
)
from l1agg.series_catalog import count_series_hits, resolve_metric  # noqa: E402

# 十意图执行器（与 data_query_executor.main 分发一一对应；S1 新增 metric_series）
EXECUTORS = {
    "data_query": exec_data_query,
    "data_insight": exec_data_insight,
    "contradiction_insight": exec_contradiction_insight,
    "path_insight": exec_path_insight,
    "technical_analysis": exec_technical_analysis,
    "technical_indicator": exec_technical_indicator,
    "stat_query": exec_stat_query,
    "fundamental_valuation": exec_fundamental_valuation,
    "asset_class_trend": exec_asset_class_trend,
    "event_analysis": exec_event_analysis,
    "risk_control": exec_risk_control,
    "price_query": exec_price_query,
    "metric_series": exec_metric_series,
    "whale_flow": exec_whale_flow,
    "calendar_event": exec_calendar_event,
    "leader_compare": exec_leader_compare,
    "top_correlation": exec_top_correlation,
    "persistence_strength": exec_persistence_strength,
    # SPEC-41-L1-新闻意图检索 §7：新闻检索走 news_digest/hot_news，不再推 L2
    "event_listing": exec_news_search,
}

# 确定性关键词注册表意图（S1）：关键词命中即确定要走哪个单维数据，
# 执行器直连真实数据（mm_metrics / mm_events），不存在“语义猜错”风险，
# 因此不参与 recall 密度门控（route_confidence 0.65 门限只约束语义意图）。
# 这样「巨鲸动向」「下一次议息会议」不会因 recall 空/密度不足被推给 L2。
DETERMINISTIC_INTENTS = frozenset(
    {
        "whale_flow",
        "calendar_event",
        "leader_compare",
        "top_correlation",
        "persistence_strength",
        "technical_indicator",
        "stat_query",
    }
)
R_DETERMINISTIC_REGISTRY = "deterministic_keyword_registry"

# 产物检索型意图（SPEC-41-L1 §5.1 修订）：执行器直接读本地产物（news_digest/hot_news），
# 自带"产物缺失 → degraded FAIL-OPEN"，不存在语义猜错风险，因此不参与认知 recall 密度门控。
# 与 DETERMINISTIC_INTENTS 的区别：这类意图不是单维数值输出，而是"检索 + 选条"；
# 但检索的对象是新闻产物，不是认知记忆——拿认知召回当门槛会让检索永远空转
# （云端实测：认知库无新闻问法 → recall_empty → 全部交 L2，前端表现为无响应）。
EXECUTOR_AVAILABILITY_INTENTS = frozenset({"event_listing"})
R_EXECUTOR_AVAILABILITY = "executor_artifact_available"

# 查询类判定：命中其一即「要数值/序列」，交给 metric_series 做索引输出
_SERIES_QUERY_CUE = re.compile(
    r"多少|几|查询|查一下|查下|查查|帮我查|看看|看一下|是多少|现在|当前|最新|今天|本周"
    r"|近|过去|最近|走势|趋势|历史|数据|情况|怎么样|如何|显示|报一下"
    r"|总量|规模|总额|余额|供应量|数量|市值|成交量|持仓量|命中数"
)
# 解读类护栏：出现解读/建议词时不走单维直答（保留给 data_insight / L2 语义层）
_SERIES_INSIGHT_CUE = re.compile(
    r"意味着|意味|说明|代表什么|什么影响|影响|怎么解读|解读|为什么|为何|怎么看|怎么理解"
    r"|原因|建议|策略|怎么办|该不该|要不要|值不值|贵不贵|预测|后市|前景|分析"
)


def _is_deterministic_series(message: str) -> bool:
    """查询类单维数据：注册表可命中 + 查询词 + 无解读词 → 索引输出直答。

    与语义意图的 0.65 门控区分：这里命中的是「已注册的真实序列」，
    执行器必然给出确定数值或显式无数据，不存在语义猜错风险。
    """
    if not message or _SERIES_INSIGHT_CUE.search(message):
        return False
    if not _SERIES_QUERY_CUE.search(message):
        return False
    try:
        # 多维并列（如「链上数据与资金费率」）交回 data_query 组合口径，不做单维截断
        if count_series_hits(message) and re.search(r"[与和及、]|同时|以及|还有", message):
            return False
        return bool(resolve_metric(message))
    except Exception:
        return False


# ============================================================
# 意图识别 — 对齐 TS l1-intent-registry.ts v3
# 11 个 fallbackPattern（顺序与注册表一致）+ 2 个通用意图后端识别
# =========================================================

_FALLBACK_PATTERNS = [
    # 文档检索优先：出现文档类名词时，"风控/估值"只是检索主题而非意图本身
    (
        "doc_search",
        re.compile(
            r"(查|搜|检索|找|有没有|在哪|放哪|路径|怎么写的).*(文档|资料|SPEC|规范|手册|指南|知识库|wiki|白皮书)"
            r"|(文档|资料|SPEC|规范|手册|指南|知识库|wiki|白皮书).*(查|搜|找|有没有|在哪|放哪|路径|怎么写的|吗)"
            r"|全文检索"
        ),
    ),
    # 巨鲸数据先于事件演变：问到「巨鲸+动向/最近/流入流出」是确定性数据检索，
    # 不是事件流跟踪（否则被 event_line_query 吞掉且 L1 无执行器 → 推给 L2）
    (
        "whale_flow",
        re.compile(
            r"(?=.*(巨鲸|鲸鱼|whale|大户))"
            r"(?=.*(动向|动态|数据|流入|流出|净流|转账|动作|最近|当前|现在|多少|情况|怎么样|查询|查一下))",
            re.IGNORECASE,
        ),
    ),
    # 事件演变先于事件分析：问"后续/演变/进展"是跟踪，不是单次解读
    (
        "event_line_query",
        re.compile(
            r"(?=.*(事件|快讯(?!数)|监管|巨鲸|解锁|ETF|地缘|美联储|政策|局势|币种))"
            r"(?=.*(演变|后续|进展|动态|动向|变化|趋势|局势))"
        ),
    ),
    # 新闻罗列（listing）先于主题/数值类意图：问"新闻/消息/热点"是取条目，
    # 不是数值查询（否则「通胀主题的新闻」被 data_query 吃掉）。
    # 演化语义由更早的 event_line_query 优先承接（见 SPEC §4.4 划界规则）。
    (
        "event_listing",
        re.compile(
            # 「新闻数/走势/统计」是数值序列口径（metric_series），不归罗列
            r"^(?!.*(新闻数|新闻条数|消息数|新闻量|统计|走势|趋势))"
            r"(?:(?=.*(新闻|消息|资讯|热点|头条|要闻|动静|风吹草动|值得关注|该知道|值得留意))"
            r"(?=.*(有哪些|有什么|有没有|哪些|几条|列出|盘点|汇总|整理|看看|给我"
            r"|最近|今天|这两天|本周|上周|最新|近期|24小时|关于|相关|主题|方面))"
            r"|(?:新闻|消息|资讯|热点)\s*$)"
        ),
    ),
    (
        "contradiction_insight",
        re.compile(
            r"(?=.*(矛盾|一致|占主导|背离|打架|共振|冲突|统一|更重要|哪个更))"
            r"(?=.*(维度|资金面|技术面|情绪面|宏观|主要矛盾|主矛盾|占主导|共振|冲突))"
        ),
    ),
    (
        "path_insight",
        re.compile(
            r"最小阻力|往哪走|往哪边走|往哪个方向|该多还是空|交汇|综合看|综合判断|综合信号|最优路径|信号指向"
            r"|能不能上车|能上车吗|能追吗|还能追|该不该买|该不该卖|满仓还是空仓|加仓还是减仓"
            r"|要不要现在进场|该进场还是|布局多还是空|该买还是该卖|先测试.*还是"
            r"|怎么走|适合做多|适合做空|往哪个方向"
        ),
    ),
    # 技术指标（54 D-B00–B07，确定性计算）先于技术分析（BCRM2 卦象）：
    # 出现具体指标/价位词 + 标的或价位语境时，走真实 K 线计算而非卦象解读
    (
        "technical_indicator",
        re.compile(
            r"(?=.*(阻力位|阻力|支撑位|支撑|压力位|压力|均线|MACD|RSI|布林|ATR|金叉|死叉|超买|超卖|K线|技术指标))"
            r"(?=.*(BTC|ETH|SOL|比特币|以太坊|索拉纳|黄金|XAU|现价|价格|价位|多少|哪里|哪儿|在哪|位置|现在|当前|走势|分析|如何|怎么样|情况))",
            re.IGNORECASE,
        ),
    ),
    (
        "technical_analysis",
        re.compile(
            r"技术面|技术指标|技术形态|卦象|置信度|K线|均线|MACD|RSI|布林|背离|支撑位|压力位"
        ),
    ),
    (
        "fundamental_valuation",
        re.compile(r"估值|基本面|贵不贵|贵吗|便宜吗|值不值|值得买"),
    ),
    # 四类追问钩子对应的三项可执行能力（确定性，不参与 recall 门控）
    (
        "leader_compare",
        re.compile(
            # 仅让位给后续 asset_class_trend 已覆盖的跨资产组合，避免产生路由空洞
            r"^(?!(?=.*(美股|港股|A股|纳指|标普|黄金|原油|贵金属|加密))"
            r"(?=.*(怎么样|如何|表现|强弱|哪个强|谁强|谁更强|对比|走势|趋势|轮动)))"
            r"(?=.*(对比|对照|相比|比较|差距|谁更强|谁强|强弱))"
            r"(?=.*(涨跌|涨幅|跌幅|变化幅度|幅度|龙头|BTC|ETH|SOL|比特币|以太坊|索拉纳|黄金|原油|纳指|标普))"
        ),
    ),
    (
        "top_correlation",
        re.compile(r"相关性最高|最相关|相关性最强|相关度最高|相关.{0,6}指标|相关性分析|相关性"),
    ),
    (
        "persistence_strength",
        re.compile(r"延续性|趋势延续|记忆性|Hurst|均值回复|动量延续|持续性强度"),
    ),
    # 统计关系（54 D-E03/E05/E07/E08/E10，确定性计算）：
    # 统计词 + 标的口径/价格语境双条件，避免吞掉普通行情问法；
    # 置于 top_correlation 之后，保留「相关性最高/最相关」由该执行器处理
    (
        "stat_query",
        re.compile(
            r"(?=.*(波动率目标|目标波动|vol[ _-]?target|\bATH\b|历史新高|趋势斜率|斜率|slope"
            r"|12\s*[-_]\s*1|momentum(?!\s*factor)|动量(?!因子|延续)"
            r"|实际利率|real[ _-]?rate|滚动相关|rolling[ _-]?corr|领先滞后|lead[ _-]?lag"
            r"|极端事件|极端频率|超阈值|阈值频率|极端.{0,6}频率"
            r"|ETF.{0,12}(?:滚动和|滚动净流入)|净流入滚动和|(?:7|30)\s*日(?:ETF)?净流入"
            r"|稳定币.{0,10}(?:规模增速|规模增长|增速)|stablecoin.{0,20}growth"
            r"|同比|环比|CAGR|年化复合|复合增长率|历史分位|历史百分位|分位排名|当前分位"
            r"|变化率|区间变化|历史序列|序列降采样|年化波动|波动率|volatility"
            r"|回撤|drawdown|季节性|月份效应|日历效应|几月|星期几|周几|月内|月初|月末"
            r"|状态转移|转移矩阵|状态切换|停留|状态持续性"
            r"|信息系数|因子有效|单调性|(?:^|[^A-Za-z])IC(?:[^A-Za-z]|$)"
            r"|相关性|同向|领先|滞后"
            r"|拥挤度|拥挤|crowding|杠杆过热|多空比过热"
            r"|显著性|是否显著|显著吗|HAC|Newey|Newey-West|Deflated|DSR))"
            r"(?=.*(BTC|ETH|SOL|比特币|以太坊|索拉纳|黄金|XAU|CPI|PPI|MVRV|SOPR|NUPL|VIX"
            r"|DGS10|美债|利率|通胀|资金费率|ETF|稳定币|USDT|USDC|TVL|恐惧贪婪|美元指数"
            r"|标普|纳指|原油|标的|价格|价位|行情|走势|现在|当前|最新|历史))",
            re.IGNORECASE,
        ),
    ),
    (
        "asset_class_trend",
        re.compile(
            r"跨资产|资产对比|各类资产|各大类资产|大类资产|不同资产|资产轮动|趋势对比"
            r"|美股和加密|贵金属和加密"
            r"|(?=.*(美股|港股|A股|纳指|标普|黄金|原油|贵金属|加密))"
            r"(?=.*(怎么样|如何|表现|强弱|哪个强|谁强|谁更强|对比|走势|趋势|轮动))"
            r"|(?=.*(BTC|ETH|SOL))(?=.*(哪个强|谁强|谁更强))"
        ),
    ),
    # 经济日历先于事件分析：「议息/FOMC/非农 + 什么时候/下次/日程」问的是日程，
    # 不是事件解读；否则会被 event_analysis 的「议息」关键词吞掉
    (
        "calendar_event",
        re.compile(
            r"(?:经济日历|财经日历|宏观日历)"
            r"|(?=.*(议息|FOMC|美联储会议|利率决议|非农|NFP|CPI|PPI|经济数据|数据公布))"
            r"(?=.*(什么时候|何时|哪天|几号|下次|下一次|最近一次|日程|日历|时间表|公布时间|发布时间|安排))",
            re.IGNORECASE,
        ),
    ),
    (
        "event_analysis",
        re.compile(
            r"FOMC|事件驱动|这次事件|金融事件|事件分析|超预期事件|price in|priced|加息事件|降息事件"
            r"|鲍威尔|议息|发布会|讲话|会议纪要|公布后|落地|怎么反应|影响多大|表态"
            r"|(?:公布|发布).*事件|事件.*(?:解读|反应|影响)"
        ),
    ),
    (
        "risk_control",
        re.compile(
            r"风控|风险度|止盈|止损|调控状态|仓位状态|持仓风控|移动止盈|风险大不大|风险大吗|风险高不高"
            r"|风险敞口|要不要跑|要不要减仓|减仓控制|控制风险|平掉|平仓(?!量)"
        ),
    ),
    (
        # S1: 指标历史序列（指标别名 + 时间窗口/走势词双条件，避免吞掉行情对比与价格查询）
        "metric_series",
        re.compile(
            r"(?=.*(CPI|PPI|M2|VIX|MVRV|SOPR|NUPL|恐惧贪婪|fear ?greed|fng|资金费率|多空比|持仓量"
            r"|美元指数|美债|纳指|标普|BTC|ETH|SOL|黄金|活跃地址|哈希率|算力|DeFi ?TVL|TVL|ETF|降息概率"
            r"|新闻数|快讯数))"
            r"(?=.*(近[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)"
            r"|过去[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)"
            r"|最近[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)"
            r"|(近|过去|最近)?半年"
            r"|[0-9]+(天|日|周|个月|月|年)"
            r"|走势|趋势|历史序列|时间序列|历史数据))",
            re.IGNORECASE,
        ),
    ),
    (
        "price_query",
        # 多实体并列（如"价格和资金费率"）交给 data_query，避免只答一半；
        # 已注册的数据类实体（市值/市占率/余额/持币等）不是"现货价格"，让位 metric_series
        re.compile(
            r"^(?!.*(?:资金费率|费率|TVL|CPI|PCE|非农|未平仓|持仓量|成交量|算力|多空比|快讯|经济数据|宏观数据|合约|增发"
            r"|市值|市占率|主导|余额|储备|持币|总量|规模|供应量))"
            r"(?:(?=.*(?:BTC|ETH|SOL|比特币|以太坊|大饼|狗狗币|黄金|原油|纳指|标普))"
            r"(?=.*(?:多少|啥价|什么价|几个钱))"
            r"|.*(?:什么价|价格|现价|实时价|最新价|多少钱|涨到多少|跌到多少|报价))"
        ),
    ),
]

# 通用意图（TS 侧仅 requiredPattern 无 fallback，模型预测后做前置校验）
# data_insight：宏观/情绪实体 + 解读动词（双条件，先于 data_query）
_DATA_INSIGHT_PATTERN = re.compile(
    r"(?=.*(CPI|PCE|PMI|非农|失业率|恐惧贪婪|稳定币|USDT|多空比|资金费率|TVL|美联储|利率|加息|降息"
    r"|期权|通胀|就业|巨鲸|机构|交易所|ETF|增发|持仓量|成交量|未平仓|市值|占比|市占率|波动率"
    r"|活跃度|流动性|链上|美股|纳指|黄金|原油|算力))"
    r"(?=.*(意味着|意味什么|意味|说明什么|说明|代表什么|什么影响|怎么解读|什么含义|含义|超预期|不及预期"
    r"|会怎么样|会怎样|怎么看|为什么))"
)
# data_query："查询动词/时间限定" 与 "数据实体" 必须共现，避免"现在/多少"这类泛词吞掉其他意图
_DATA_ENTITY = (
    r"CPI|非农|PCE|GDP|PMI|恐惧贪婪|稳定币|USDT|多空比|资金费率|TVL|美联储|利率|期权|衍生品|链上|快讯|"
    r"行情|指数|价格|现价|K线|成交量|持仓量|未平仓|合约|市值|涨幅|跌幅|净流入|净流出|增发|算力"
    r"|经济数据|宏观数据|活跃度|BTC|ETH|SOL|数据"
)
_DATA_QUERY_PATTERN = re.compile(
    rf"(?=.*(?:查|查询|搜|检索|多少|几|最新|现在|当前|今天|本周|数据|情况))(?=.*(?:{_DATA_ENTITY}))",
    re.IGNORECASE,
)

R_INTENT_UNKNOWN = "intent_unknown"

_RECALL_TOP_K = 5


# 语义通道最小消息长度：短消息多为对话/寒暄/测试，跳过语义匹配避免误命中
SEMANTIC_MIN_LEN = 5


def required_pattern_ok(intent: str, message: str, *, strict_series: bool = True) -> bool:
    """通用意图的 requiredPattern 校验（与正则通道同等待遇）。

    strict_series=True 时 metric_series 还要求「注册表可命中的确定性序列」，
    供路由策略（E1）与 G2 特征闸使用；detect_intent 传 False 以保持线上行为不变
    （语义命中 metric_series 但非确定性序列时仍返回该意图，由 recall 门控裁决）。
    """
    if intent == "data_insight":
        return bool(_DATA_INSIGHT_PATTERN.search(message))
    if intent == "data_query":
        return bool(resolve_source(message) or _DATA_QUERY_PATTERN.search(message))
    if strict_series and intent == "metric_series":
        return _is_deterministic_series(message)
    return True


def detect_intent_regex(message: str) -> str:
    """通道 A：纯正则/注册表意图识别（不含语义兜底，供 E1 策略对比复用）。"""
    if not message:
        return ""
    for intent, pattern in _FALLBACK_PATTERNS:
        if pattern.search(message):
            return intent
    # data_insight 更具体（双条件），先于 data_query 判定
    if _DATA_INSIGHT_PATTERN.search(message):
        return "data_insight"
    # 查询类单维数据（注册表命中 + 查询词）→ 索引输出统一模板，先于 data_query
    # （data_query 走源级 latest 记录，多字段原始 JSON；单维指标应走序列索引输出）
    if _is_deterministic_series(message):
        return "metric_series"
    if resolve_source(message) or _DATA_QUERY_PATTERN.search(message):
        return "data_query"
    return ""


def regex_intent_hits(message: str) -> list:
    """通道 A 的**全量命中集合**（E2 复合问法检测用，不参与线上判决）。

    与 detect_intent_regex 的区别：不短路，返回全部命中的意图（按注册表顺序去重）。
    data_query 为兜底类（几乎任何金融词都会命中 resolve_source），
    复合判定时应由调用方排除或降权。
    """
    if not message:
        return []
    hits = []
    for intent, pattern in _FALLBACK_PATTERNS:
        if pattern.search(message) and intent not in hits:
            hits.append(intent)
    if _DATA_INSIGHT_PATTERN.search(message) and "data_insight" not in hits:
        hits.append("data_insight")
    if _is_deterministic_series(message) and "metric_series" not in hits:
        hits.append("metric_series")
    if (
        resolve_source(message) or _DATA_QUERY_PATTERN.search(message)
    ) and "data_query" not in hits:
        hits.append("data_query")
    return hits


# ============================================================
# 复合问法闸（E2-D5，SPEC v1.4 §9.3）：三信号合并，零模型、零 token
#   D4 子句切分+逐子句意图（零误杀基线）
#   ∪ D2 连接词+多实体（且无对比词）
#   ∪ 多指标并列（注册表命中 ≥2）
# ============================================================
_COMPOUND_SPLIT = re.compile(r"[，,；;、]|以及|还有|同时|顺便|另外|并且|然后|和|与|及")
_COMPOUND_CONNECTIVE = re.compile(r"[与和及、]|同时|还有|以及|一起|顺便|另外|再")
_COMPOUND_COMPARE = re.compile(r"对比|比较|谁更|谁强|哪个强|差距|vs|VS")
_COMPOUND_ANCHOR = re.compile(
    r"BTC|ETH|SOL|比特币|以太坊|索拉纳|二饼|大饼|姨太|黄金|原油|美股|港股|A股|纳指|标普"
    r"|CPI|PPI|GDP|非农|失业率|通胀|恐惧贪婪|恐慌贪婪|资金费率|多空比|稳定币|ETF|美元|国债|M2|M1"
)
R_COMPOUND_QUERY = "compound_query"
R_CONTRACT_DIRECT = "executor_contract_ok"


def is_compound_query(message: str) -> bool:
    """复合问法判定（D5）：命中即交 L2，不做隐式拆解。

    E2 实测（500 条）：compound 召回 78.8%、单意图误杀 2.0%。
    子句长度 <4 视为碎片（如单独 "BTC"），避免把「BTC和ETH涨跌幅对比」误判。
    """
    if not message:
        return False
    parts = [p.strip() for p in _COMPOUND_SPLIT.split(message) if len(p.strip()) >= 4]
    if len(parts) >= 2:
        intents = {detect_intent_regex(p) for p in parts}
        intents.discard("")
        if len(intents) >= 2:
            return True
    # D2：连接词 + 多实体，且不是「对比」类单意图
    if (
        _COMPOUND_CONNECTIVE.search(message)
        and not _COMPOUND_COMPARE.search(message)
        and len(set(_COMPOUND_ANCHOR.findall(message))) >= 2
    ):
        return True
    # 多指标并列（注册表命中 ≥2 个不同指标）
    try:
        return count_series_hits(message) >= 2
    except Exception:  # noqa: BLE001 — FAIL-OPEN：指标注册表异常不影响主链路
        return False


def _routing_strategy() -> str:
    """路由策略开关（默认 S0 = 现状，行为零变化）；S1 = 契约门控 + 复合闸。"""
    return (os.environ.get("L1_ROUTING_STRATEGY", "S0") or "S0").strip().upper()


def semantic_candidates(message: str, k: int = 3, *, validated: bool = True) -> list:
    """通道 B：语义候选 top-K（[(intent, score), ...]）。

    validated=True 时按 G2 特征闸过滤（requiredPattern / 确定性序列），
    与 route_query 的语义准入保持同一口径；FAIL-OPEN：异常返回空列表。
    """
    if _semantic_matcher is None or len(message or "") < SEMANTIC_MIN_LEN:
        return []
    try:
        top = _semantic_matcher.semantic_topk(message, lang="auto", k=k)
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return []
    out = []
    for intent, score in top:
        if validated and not required_pattern_ok(intent, message, strict_series=True):
            continue
        out.append((intent, score))
    return out


def detect_intent(message: str) -> str:
    """后端关键词识别（前端未透传 intent 时的兜底，规则与 TS 注册表对齐）。

    双通道：正则优先 → 语义兜底（SPEC-41-L1 §3.3）。
    语义命中的 data_query/data_insight 仍需 requiredPattern 校验。
    FAIL-OPEN：语义通道任何异常退回空串（交 L2）。
    """
    if not message:
        return ""
    regex_intent = detect_intent_regex(message)
    if regex_intent:
        return regex_intent

    # ===== 通道 B：语义兜底（正则未命中时启用） =====
    if _semantic_matcher is not None and len(message) >= SEMANTIC_MIN_LEN:
        try:
            semantic = _semantic_matcher.semantic_match(message, lang="auto")
            if semantic:
                intent = semantic[0]
                # 通用意图仍需 requiredPattern 校验（与正则通道同等待遇）；
                # strict_series=False：语义 metric_series 交由 recall 门控裁决（线上行为不变）
                if not required_pattern_ok(intent, message, strict_series=False):
                    return ""
                return intent
        except Exception:  # noqa: BLE001 — FAIL-OPEN：语义通道异常不影响主链路
            pass

    return ""


def extract_json(raw: str):
    """从混杂 stdout 中提取最后一个 JSON 对象（认知系统可能向 stdout 打警告行）。"""
    for line in reversed([ln.strip() for ln in (raw or "").splitlines()]):
        if not line or not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def _unknown_result(
    trace_id: str = "",
    intent: str = "unknown",
    reason: str = R_INTENT_UNKNOWN,
    degraded: bool = True,
):
    return {
        "success": True,
        "intent": intent,
        "handled": False,
        "answer": "",
        "data": None,
        "degraded": degraded,
        "trace_id": trace_id,
        "route_signal": RouteConfidenceResult(
            route_confidence=0.0,
            decision=L2_HANDOFF,
            match_score=0.0,
            case_density=0,
            prediction_error=None,
            fast_path=False,
            degraded=degraded,
            reasons=[reason],
        ).to_dict(),
    }


def _route_deterministic(
    intent: str, message: str, trace_id: str = "", reason: str = R_DETERMINISTIC_REGISTRY
) -> dict:
    """确定性关键词注册表命中：跳过 recall 门控，直接执行单维检索并直答。

    route_signal 显式标注 L1_DIRECT + reason，与语义意图的 0.65 门控区分
    （阈值本身不变，仍由 route_confidence 单一事实源维护）。
    reason 由调用方指定：确定性注册表 / 产物可用性（EXECUTOR_AVAILABILITY_INTENTS）。
    """
    try:
        result = EXECUTORS[intent](message)
    except Exception as e:
        result = {"success": True, "degraded": True, "answer": f"执行异常: {e}", "data": None}
    settle_attempted = False
    try:
        settle_to_cognitive(intent, message, result, trace_id=trace_id)
        settle_attempted = True
    except Exception:
        pass
    return {
        "success": True,
        "intent": intent,
        "handled": True,
        "answer": result.get("answer", ""),
        "data": result.get("data"),
        "degraded": bool(result.get("degraded")),
        "trace_id": trace_id,
        "route_signal": RouteConfidenceResult(
            route_confidence=1.0,
            decision=L1_DIRECT,
            match_score=1.0,
            case_density=0,
            prediction_error=None,
            fast_path=False,
            degraded=False,
            reasons=[reason],
        ).to_dict(),
        "settle_attempted": settle_attempted,
    }


def _route_query_impl(message: str, intent: str = "", trace_id: str = "") -> dict:
    """门控主流程：意图 → recall → evaluate_route → L1 直答 / L2 交接（全程 FAIL-OPEN）。

    trace_id 由前端入口生成并透传（执行链 SPEC §6.2），L1 直答的 settle 案例落同一 trace。
    """
    strategy = _routing_strategy()
    intent = (intent or "").strip()
    if intent not in EXECUTORS:
        # S1 只走正则通道（E1 实测口径：语义通道不参与准入）
        intent = detect_intent_regex(message) if strategy == "S1" else detect_intent(message)

    # ===== S1 契约门控（E1 选定；默认 S0 不进入此分支）=====
    if strategy == "S1":
        if is_compound_query(message):
            return _unknown_result(trace_id, intent or "unknown", R_COMPOUND_QUERY, degraded=False)
        if not intent:
            return _unknown_result(trace_id)
        if intent not in EXECUTORS:
            return _unknown_result(trace_id, intent, "l1_no_executor", degraded=False)
        return _route_deterministic(intent, message, trace_id, reason=R_CONTRACT_DIRECT)

    if not intent:
        return _unknown_result(trace_id)
    if intent not in EXECUTORS:
        # 注册表有该意图但 L1 没有确定性执行器（doc_search）→ 交 L2，保留 hint
        return _unknown_result(trace_id, intent, "l1_no_executor", degraded=False)

    # 确定性关键词注册表：不依赖认知召回，直接单维检索直答（无 LLM、无猜测）
    if intent in DETERMINISTIC_INTENTS:
        return _route_deterministic(intent, message, trace_id)
    # 产物检索型意图：执行器可自行判定产物是否可用（缺失 → degraded FAIL-OPEN），
    # 不依赖认知记忆召回（SPEC-41-L1 §5.1 修订）。
    if intent in EXECUTOR_AVAILABILITY_INTENTS:
        return _route_deterministic(intent, message, trace_id, reason=R_EXECUTOR_AVAILABILITY)
    # 查询类单维序列：注册表可命中的指标查询同样跳过 recall 门控
    if intent == "metric_series" and _is_deterministic_series(message):
        return _route_deterministic(intent, message, trace_id)

    # 认知召回（L0 scope；异常/降级 → cognitive_available=False → evaluate_route 静态兜底）
    cognitive_available = True
    memories = []
    try:
        ctx = get_l0().fetch_context(
            "cognitive.recall",
            {
                "context": f"{intent}::{message}",
                "top_k": _RECALL_TOP_K,
                # L1 只做确定性检索直答，PoE 证据门禁留给 L2 语义层判定
                "poe_enforcement": "off",
            },
        )
        if ctx.get("degraded"):
            cognitive_available = False
        else:
            memories = ctx.get("data") or []
    except Exception:
        cognitive_available = False

    # C4 预测误差信号（对齐 core/sufficiency.py 先例）：S 层无外部 actual，
    # rea_confidence=match_score 使 actual==expected（预测误差=0），C4 可用不降级；
    # 匹配评估异常时 FAIL-OPEN 退化为纯 C3（不扣预测误差分）。
    try:
        rea_conf = evaluate_match(memories)[0]
    except Exception:
        rea_conf = None
    signal = evaluate_route(
        memories, cognitive_available=cognitive_available, rea_confidence=rea_conf
    )

    out = {
        "success": True,
        "intent": intent,
        "handled": False,
        "answer": "",
        "data": None,
        "degraded": signal.degraded,
        "route_signal": signal.to_dict(),
        "trace_id": trace_id,
    }

    if signal.decision != L1_DIRECT:
        return out

    # L1 零 token 直答：复用十意图执行器（执行异常不外抛）
    try:
        result = EXECUTORS[intent](message)
    except Exception as e:
        result = {"success": True, "degraded": True, "answer": f"执行异常: {e}", "data": None}
    out["handled"] = True
    out["answer"] = result.get("answer", "")
    out["data"] = result.get("data")
    out["degraded"] = bool(signal.degraded or result.get("degraded"))

    # settle 沉淀（FAIL-OPEN，不阻塞返回）；trace_id 随案例落盘，供跨链关联
    settle_attempted = False
    try:
        settle_to_cognitive(intent, message, result, trace_id=trace_id)
        settle_attempted = True
    except Exception:
        pass
    # 执行链 trace 台账（G-BCL-3）：L1 直答无 task_id，由调用方按 trace 聚合
    out["settle_attempted"] = settle_attempted
    return out


def route_query(message: str, intent: str = "", trace_id: str = "") -> dict:
    """对外入口：在门控结果上挂建议器影子记录（默认关闭，返回字段零变化）。"""
    out = _route_query_impl(message, intent, trace_id)
    try:
        import l1_suggest_shadow as _shadow  # noqa: PLC0415 — 可选依赖，缺失不影响主链路

        _shadow.record(
            message,
            intent=out.get("intent", ""),
            decision=(out.get("route_signal") or {}).get("decision", ""),
            trace_id=trace_id,
            strategy=_routing_strategy(),
        )
    except Exception:  # noqa: BLE001 — 影子记录绝不影响主链路
        pass
    return out


def main():
    try:
        if len(sys.argv) > 1:
            req = json.loads(sys.argv[1])
        else:
            req = json.loads(sys.stdin.read() or "{}")
    except Exception:
        req = {}
    message = req.get("message", "") or ""
    intent = req.get("intent", "") or ""
    trace_id = req.get("trace_id", "") or ""
    try:
        result = route_query(message, intent, trace_id)
    except Exception as e:
        # 最终兜底：任何未预期异常都不阻塞前端（前端 FAIL-OPEN 转 L2）
        result = _unknown_result(trace_id)
        result["answer"] = f"路由异常: {e}"
    # 保证 JSON 在最后一行输出（供 extract_json 穿透 stdout 噪音）
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

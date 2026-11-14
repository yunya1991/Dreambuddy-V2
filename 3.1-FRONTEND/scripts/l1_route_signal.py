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
    exec_metric_series,
    exec_path_insight,
    exec_price_query,
    exec_risk_control,
    exec_technical_analysis,
    exec_whale_flow,
    resolve_source,
    settle_to_cognitive,
)

# 十意图执行器（与 data_query_executor.main 分发一一对应；S1 新增 metric_series）
EXECUTORS = {
    "data_query": exec_data_query,
    "data_insight": exec_data_insight,
    "contradiction_insight": exec_contradiction_insight,
    "path_insight": exec_path_insight,
    "technical_analysis": exec_technical_analysis,
    "fundamental_valuation": exec_fundamental_valuation,
    "asset_class_trend": exec_asset_class_trend,
    "event_analysis": exec_event_analysis,
    "risk_control": exec_risk_control,
    "price_query": exec_price_query,
    "metric_series": exec_metric_series,
    "whale_flow": exec_whale_flow,
    "calendar_event": exec_calendar_event,
}

# 确定性关键词注册表意图（S1）：关键词命中即确定要走哪个单维数据，
# 执行器直连真实数据（mm_metrics / mm_events），不存在“语义猜错”风险，
# 因此不参与 recall 密度门控（route_confidence 0.65 门限只约束语义意图）。
# 这样「巨鲸动向」「下一次议息会议」不会因 recall 空/密度不足被推给 L2。
DETERMINISTIC_INTENTS = frozenset({"whale_flow", "calendar_event"})
R_DETERMINISTIC_REGISTRY = "deterministic_keyword_registry"

# ============================================================
# 意图识别 — 对齐 TS l1-intent-registry.ts v3
# 10 个 fallbackPattern（顺序与注册表一致）+ 2 个通用意图后端识别
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
        # 多实体并列（如"价格和资金费率"）交给 data_query，避免只答一半
        re.compile(
            r"^(?!.*(?:资金费率|费率|TVL|CPI|PCE|非农|未平仓|持仓量|成交量|算力|多空比|快讯|经济数据|宏观数据|合约|增发))"
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


def detect_intent(message: str) -> str:
    """后端关键词识别（前端未透传 intent 时的兜底，规则与 TS 注册表对齐）。"""
    if not message:
        return ""
    for intent, pattern in _FALLBACK_PATTERNS:
        if pattern.search(message):
            return intent
    # data_insight 更具体（双条件），先于 data_query 判定
    if _DATA_INSIGHT_PATTERN.search(message):
        return "data_insight"
    if resolve_source(message) or _DATA_QUERY_PATTERN.search(message):
        return "data_query"
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


def _route_deterministic(intent: str, message: str, trace_id: str = "") -> dict:
    """确定性关键词注册表命中：跳过 recall 门控，直接执行单维检索并直答。

    route_signal 显式标注 L1_DIRECT + reason=deterministic_keyword_registry，
    与语义意图的 0.65 门控区分（阈值本身不变，仍由 route_confidence 单一事实源维护）。
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
            reasons=[R_DETERMINISTIC_REGISTRY],
        ).to_dict(),
        "settle_attempted": settle_attempted,
    }


def route_query(message: str, intent: str = "", trace_id: str = "") -> dict:
    """门控主流程：意图 → recall → evaluate_route → L1 直答 / L2 交接（全程 FAIL-OPEN）。

    trace_id 由前端入口生成并透传（执行链 SPEC §6.2），L1 直答的 settle 案例落同一 trace。
    """
    intent = (intent or "").strip()
    if intent not in EXECUTORS:
        intent = detect_intent(message)
    if not intent:
        return _unknown_result(trace_id)
    if intent not in EXECUTORS:
        # 注册表有该意图但 L1 没有确定性执行器（doc_search）→ 交 L2，保留 hint
        return _unknown_result(trace_id, intent, "l1_no_executor", degraded=False)

    # 确定性关键词注册表：不依赖认知召回，直接单维检索直答（无 LLM、无猜测）
    if intent in DETERMINISTIC_INTENTS:
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

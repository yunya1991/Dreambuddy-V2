# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · 阶段二第一圈：内部文档术语提取（零 token）

从仓库内部知识库文档提取三大术语域的术语与定义，产出术语表雏形：
  - indicator_terms.json: 技术指标术语
  - strategy_terms.json: 交易策略术语
  - theory_terms.json: 交易理论术语

提取源（第一圈·内部文档，五大术语域）：
  - 2-KNOWLEDGE/1-TRADING: 策略域（BCRM2/CBR/EV雷达等）
  - 2-KNOWLEDGE/2-TECHNICAL + 10-经典指标系统: 技术指标域
  - 2-KNOWLEDGE/3-THEORY + 23 系统: 理论域（矛盾分析法/第一性原理等）
  - 9-基本面分析 + 18-数据获取中心: 金融概念域（CPI/非农/恐惧贪婪等宏观数据概念）
  - 14/11/16/12 系统: 交易算法域（马丁策略/易经推理/调控算法/三屏趋势算法）

提取规则：
  - Markdown 标题/加粗术语行 → 术语条目
  - 术语定义取标题下首段文本（截断 200 字）
  - 每条带 source（源文件路径）与 quality=A（内部文档佐证）

用法: python3 extract_terms.py [--dry-run]
"""
import argparse
import json
import os
import re

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)
OUT_DIR = _SYS_DIR

# 术语域 → 源目录/文件（五大术语域）
SOURCES = {
    "indicator": [
        os.path.join(_REPO, "2-KNOWLEDGE", "2-TECHNICAL"),
        os.path.join(_REPO, "10-经典指标系统", "docs"),
    ],
    "strategy": [
        os.path.join(_REPO, "2-KNOWLEDGE", "1-TRADING"),
        os.path.join(_REPO, "6-TRADING", "knowledge"),
    ],
    "theory": [
        os.path.join(_REPO, "2-KNOWLEDGE", "3-THEORY"),
        os.path.join(_REPO, "23-四层闭环自进化交易架构"),
    ],
    "finance": [
        os.path.join(_REPO, "9-基本面分析"),
        os.path.join(_REPO, "18-数据获取中心"),
        os.path.join(_REPO, "2-KNOWLEDGE", "7-EXTERNAL-RESEARCH"),
        os.path.join(_REPO, "4-MEMORY"),
    ],
    "algorithm": [
        os.path.join(_REPO, "14-V15经典马丁策略"),
        os.path.join(_REPO, "11-易经推理系统"),
        os.path.join(_REPO, "16-调控系统"),
        os.path.join(_REPO, "12-三屏趋势系统"),
        os.path.join(_REPO, "4-MEMORY"),
    ],
}


def _spec_plan_files():
    """全仓库 SPEC/PLAN 调研文档（过往调研内容含大量金融概念与算法术语，重要采集源）。"""
    files = []
    for root, dirs, names in os.walk(_REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules" and d != "__pycache__"]
        for n in names:
            if n.startswith(("SPEC", "PLAN")) and n.endswith(".md"):
                files.append(os.path.join(root, n))
    return sorted(files)


# SPEC/PLAN 调研文档按关键词路由到对应术语域
_SPEC_DOMAIN_KEYWORDS = {
    "finance": ["CPI", "非农", "宏观", "美联储", "基本面", "估值", "恐惧贪婪", "资金费率",
                 "TVL", "稳定币", "事件驱动", "加息", "降息", "GDP", "PMI"],
    "algorithm": ["算法", "马丁", "网格", "趋势", "对冲", "动态止损", "移动止损", "仓位",
                  "凯利", "波动率", "网格策略", "轮动", "套利"],
}


def _route_spec_file(path):
    """按关键词将 SPEC/PLAN 文档路由到术语域（可多域）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(20000)
    except Exception:
        return []
    domains = []
    for domain, keywords in _SPEC_DOMAIN_KEYWORDS.items():
        if any(k in content for k in keywords):
            domains.append(domain)
    return domains

# 噪声标题模式（非术语的目录性/导航性标题）
NOISE_PATTERNS = re.compile(
    r"^(INDEX|README|目录|附录|参考|目录结构|使用说明|快速开始|安装|部署|FAQ|"
    r"\d+[\.\s、]|第[一二三四五六七八九十]+[章节部分]|\|)")

# 中文序号开头（一、二、三…）非术语
CN_NUM_PREFIX = re.compile(r"^[一二三四五六七八九十]+、")

# 编号/流程性标题（Step/Task/公理N/Phase N 等）非术语
NUMBERED_PREFIX = re.compile(r"^(Step|Task|Phase|公理\d|P\d|F\d|HC-)", re.IGNORECASE)

# 中文顿号/间隔号分隔标题（一 · 背景）非术语
CN_DOT_PREFIX = re.compile(r"^[一二三四五六七八九十]+\s*[·•]")

# 架构性泛词（非金融术语）
GENERIC_WORDS = {
    "核心架构", "建设原则", "常见陷阱", "核心机制", "状态机流转", "调度架构",
    "理论体系关系图", "总体架构", "设计原则", "实现方案", "技术选型",
    "使用方式", "注意事项", "总结", "概述", "背景", "目标", "流程",
    "验证清单", "测试", "架构总览", "现状基线", "修复", "问题", "方案",
}


def extract_from_file(path):
    """从单个 Markdown 文件提取术语条目（标题+定义）。"""
    terms = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return terms
    rel = os.path.relpath(path, _REPO)
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 匹配二三级标题: ## 术语 / ### 术语
        m = re.match(r"^#{2,3}\s+(.{2,30})$", line)
        if m:
            name = m.group(1).strip()
            # 过滤噪声标题
            if (not NOISE_PATTERNS.match(name)
                    and not CN_NUM_PREFIX.match(name)
                    and not CN_DOT_PREFIX.match(name)
                    and not NUMBERED_PREFIX.match(name)
                    and name not in GENERIC_WORDS
                    and not re.search(r"[\.。;；,，→：:]", name)
                    and not re.match(r"^[A-Za-z0-9\s\-_/()（）]+$", name)):
                # 取标题后首个非空非标题行作为定义（截断）
                definition = ""
                for j in range(i + 1, min(i + 6, len(lines))):
                    t = lines[j].strip()
                    if t and not t.startswith("#") and not t.startswith("|") and not t.startswith("-") and not t.startswith("```"):
                        definition = t[:200]
                        break
                if definition:
                    terms.append({
                        "term": name,
                        "definition": definition,
                        "source": rel,
                        "quality": "A",
                    })
        i += 1
    return terms


# 精选种子术语（文档正文高频但标题未覆盖的核心概念，人工审定 quality=A）
SEED_TERMS = {
    "finance": [
        {"term": "CPI", "definition": "消费者价格指数，衡量通胀水平的核心宏观指标，影响美联储利率决策与加密市场风险偏好"},
        {"term": "非农就业数据", "definition": "美国非农就业报告，反映就业市场强弱，是美联储政策的重要参考，公布时市场波动剧烈"},
        {"term": "美联储议息", "definition": "美联储联邦公开市场委员会（FOMC）利率决议，直接影响美元流动性加密资产估值"},
        {"term": "PPI", "definition": "生产者价格指数，衡量生产端通胀，是 CPI 的先行指标"},
        {"term": "GDP", "definition": "国内生产总值，衡量经济总量与增长速度的宏观核心指标"},
        {"term": "PMI", "definition": "采购经理指数，反映制造业/服务业景气度的先行指标，50 为荣枯线"},
        {"term": "恐惧贪婪指数", "definition": "市场情绪综合指标（0-100），衡量市场恐慌与贪婪程度，用于逆向参考"},
        {"term": "资金费率", "definition": "永续合约多空双方的费用交换机制，反映合约市场多空力量与杠杆情绪"},
        {"term": "TVL", "definition": "总锁仓价值，衡量 DeFi 协议资金规模的核心指标"},
        {"term": "估值百分位", "definition": "标的当前估值在历史分布中的位置，BDSM 基本面系统用于判断高估/低估"},
    ],
    "algorithm": [
        {"term": "马丁格尔策略", "definition": "亏损后加倍仓位的摊平策略，高胜率但存在爆仓尾部风险，V15 系统的核心策略"},
        {"term": "网格交易", "definition": "在价格区间内按网格间距低买高卖的震荡市策略"},
        {"term": "移动止损", "definition": "随价格顺方向移动的动态止损机制（Trailing Stop），锁定利润并控制回撤"},
        {"term": "ATR", "definition": "平均真实波幅，衡量标的波动率的指标，用于止损距离与仓位 sizing"},
        {"term": "MACD", "definition": "指数平滑异同移动平均线，通过快慢均线差判断趋势方向与动能"},
        {"term": "RSI", "definition": "相对强弱指数（0-100），判断超买超卖的动量指标"},
        {"term": "布林带", "definition": "基于标准差的价格通道指标，中轨为均线，上下轨反映波动范围"},
        {"term": "唐奇安通道", "definition": "N 日最高/最低价构成的通道，突破上轨做多/下轨做空的经典趋势策略"},
        {"term": "凯利公式", "definition": "按胜率与赔率计算最优仓位比例的资金管理公式"},
        {"term": "动态止损", "definition": "根据波动率/持仓时间等条件自适应调整的止损机制，16-调控系统的核心能力"},
    ],
}


def extract_domain(domain, sources):
    """提取一个术语域的全部条目，按术语去重（保留首个定义）。"""
    seen = {}
    # 精选种子术语优先入库
    for t in SEED_TERMS.get(domain, []):
        seen[t["term"]] = {**t, "source": "curated-seed", "quality": "A"}
    # SPEC/PLAN 调研文档按关键词路由补充
    for sp in _spec_plan_files():
        if domain in _route_spec_file(sp):
            sources = list(sources) + [sp]
    for src in sources:
        if not os.path.exists(src):
            continue
        if os.path.isfile(src):
            files = [src]
        else:
            files = []
            for root, _dirs, names in os.walk(src):
                for n in names:
                    if n.endswith(".md"):
                        files.append(os.path.join(root, n))
        for fp in sorted(files):
            for t in extract_from_file(fp):
                if t["term"] not in seen:
                    seen[t["term"]] = t
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    args = parser.parse_args()

    total = 0
    for domain, sources in SOURCES.items():
        terms = extract_domain(domain, sources)
        total += len(terms)
        out = os.path.join(OUT_DIR, f"{domain}_terms.json")
        if args.dry_run:
            print(f"[DRY] {domain}: {len(terms)} 条（示例: {[t['term'] for t in terms[:5]]}）")
            continue
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"domain": domain, "count": len(terms), "terms": terms},
                      f, ensure_ascii=False, indent=2)
        print(f"[OK] {domain}_terms.json: {len(terms)} 条 ← {out}")
    print(f"[DONE] 总计提取 {total} 条术语（第一圈·内部文档，零 token）")


if __name__ == "__main__":
    main()

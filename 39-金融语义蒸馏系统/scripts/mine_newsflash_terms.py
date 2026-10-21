# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-术语：从快讯数据挖掘四类新术语表种子（零 token）

从 18 中心星球日报快讯正文挖掘：
  - people_terms.json: 金融人物（分析师/创始人/巨鲸，规则：职位关键词+人名模式）
  - tokenomics_terms.json: 代币机制术语（挖矿/质押/解锁/销毁等词典+快讯高频机制词）
  - sector_terms.json: 金融板块概念（DeFi/L2/游戏/存储/AI 等板块词典+快讯板块词频）
  - macro_terms.json: 宏观术语（finance_terms 深化：利率决议/缩表/地缘政治等）

挖掘策略：精选种子词典（人工审定 quality=A）+ 快讯高频词统计补充（quality=B 待抽检）
用法: python3 mine_newsflash_terms.py
"""
import json
import os
import re
import sys
from collections import Counter

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

sys.path.insert(0, _THIS_DIR)
import dc_pg  # PostgreSQL 辅助模块（18 中心迁移后替代 SQLite）

# ── 精选种子词典（人工审定 quality=A）──────────────────────
SEEDS = {
    "people": [
        {"term": "巨鲸", "definition": "持有大量加密资产的钱包地址主体，其链上转移常引发市场关注"},
        {"term": "分析师", "definition": "对市场/项目发布研究观点的专业人士"},
        {"term": "创始人", "definition": "加密项目/公司的创立者，其言论对项目影响重大"},
        {"term": "CZ（赵长鹏）", "definition": "币安创始人，加密行业最具影响力人物之一"},
        {"term": "Vitalik（V神）", "definition": "以太坊创始人，以太坊技术路线的核心决策者"},
        {"term": "Satoshi Nakamoto（中本聪）", "definition": "比特币创始人，身份至今未知"},
        {"term": "Jerome Powell（鲍威尔）", "definition": "美联储主席，美国货币政策的核心决策者"},
        {"term": "Warren Buffett（巴菲特）", "definition": "伯克希尔董事长，价值投资代表人物"},
    ],
    "tokenomics": [
        {"term": "代币解锁", "definition": "锁仓代币到期释放流通，常对价格形成抛压"},
        {"term": "代币销毁", "definition": "永久移除部分代币流通量，制造通缩效应"},
        {"term": "质押", "definition": "锁定代币参与网络验证获取收益的机制"},
        {"term": "挖矿", "definition": "通过算力/质押参与区块生产获取代币奖励"},
        {"term": "空投", "definition": "项目向社区用户免费分发代币的营销/激励方式"},
        {"term": "回购", "definition": "项目方用收入买回自家代币，减少流通量"},
        {"term": "通胀率", "definition": "代币年增发比例，影响长期供给"},
        {"term": "流通量", "definition": "市场上可自由交易的代币数量"},
    ],
    "sector": [
        {"term": "DeFi", "definition": "去中心化金融，链上借贷/交易/衍生品等金融协议总称"},
        {"term": "Layer2", "definition": "以太坊二层扩容方案（Rollup 系），提升吞吐降低成本"},
        {"term": "RWA", "definition": "真实世界资产代币化，将国债/房产等上链流通"},
        {"term": "AI+Crypto", "definition": "人工智能与区块链结合的板块（算力/数据/AI Agent）"},
        {"term": "GameFi", "definition": "游戏与金融结合的板块（Play-to-Earn 模式）"},
        {"term": "Meme", "definition": "迷因币板块，社区驱动的文化型代币（DOGE/PEPE 等）"},
        {"term": "稳定币", "definition": "锚定法币价值的代币（USDT/USDC），加密市场的基础货币"},
        {"term": "NFT", "definition": "非同质化代币，数字资产确权与交易板块"},
    ],
    "macro": [
        {"term": "利率决议", "definition": "央行（美联储 FOMC）对基准利率的调整决定，市场最重磅事件"},
        {"term": "缩表", "definition": "央行缩减资产负债表，回收市场流动性"},
        {"term": "量化宽松", "definition": "央行购债向市场注入流动性"},
        {"term": "债务上限", "definition": "美国政府债务法定上限，触及将引发违约风险与政治博弈"},
        {"term": "地缘政治风险", "definition": "战争/制裁/冲突对风险资产的外溢冲击"},
        {"term": "风险偏好", "definition": "市场对风险资产的配置意愿，宏观环境驱动（Risk-on/Risk-off）"},
        {"term": "流动性", "definition": "市场资金充裕程度，决定资产估值水位"},
        {"term": "避险资产", "definition": "市场恐慌时资金流入的资产（黄金/美元/国债）"},
    ],
}

# ── 快讯高频词挖掘模式（quality=B 待抽检）──────────────────
# people 停用词：非人物的高频干扰词
_PEOPLE_STOPWORDS = {
    "平台", "发文", "此前", "知情人士", "消息", "分析", "报告", "数据", "研究",
    "统特朗普", "总统", "主席", "行长", "官员", "发言人", "媒体", "记者",
}
MINE_PATTERNS = {
    "people": re.compile(r"(?:创始人|分析师|CEO|首席|董事)([\u4e00-\u9fa5]{2,4})(?:表示|指出|称|认为)"),
    "tokenomics": re.compile(r"(解锁|销毁|质押|挖矿|空投|回购|增发|锁仓|减半|铸造)"),
    "sector": re.compile(r"(DeFi|Layer2|L2|RWA|GameFi|Meme|NFT|稳定币|现货ETF|公链|跨链)"),
    "macro": re.compile(r"(利率决议|缩表|加息|降息|通胀|债务上限|非农|地缘|制裁|流动性)"),
}


def load_newsflash_texts(limit=2000):
    texts = []
    # PostgreSQL 查询（dc_pg 统一接口，FAIL-OPEN：异常返回空）
    rows = dc_pg.fetch_records("newsflash_%", limit=limit, order_desc=True)
    for row in rows:
        m = row.get("metrics") or {}
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                continue
        if not isinstance(m, dict):
            continue
        try:
            desc = re.sub(r"<[^>]+>", "", m.get("description", ""))
            if desc:
                texts.append(desc)
        except Exception:
            continue
    return texts


def mine_domain(texts, pattern, min_count=3, top_n=30, stopwords=None):
    """按模式统计高频词，返回 quality=B 的挖掘条目。"""
    counter = Counter()
    for t in texts:
        for m in pattern.finditer(t):
            word = m.group(1)
            if stopwords and word in stopwords:
                continue
            counter[word] += 1
    out = []
    for word, n in counter.most_common(top_n):
        if n >= min_count:
            out.append({"term": word, "definition": f"快讯高频词（出现 {n} 次），定义待人工补充",
                        "source": "newsflash_mining", "quality": "B", "occurrences": n})
    return out


def main():
    texts = load_newsflash_texts()
    print(f"[INFO] 加载快讯正文 {len(texts)} 条")
    for domain in ("people", "tokenomics", "sector", "macro"):
        seeds = [{**s, "source": "curated-seed", "quality": "A"} for s in SEEDS[domain]]
        stopwords = _PEOPLE_STOPWORDS if domain == "people" else None
        mined = mine_domain(texts, MINE_PATTERNS[domain], stopwords=stopwords)
        # 去重：挖掘词与种子重复的跳过
        seed_terms = {s["term"] for s in seeds}
        mined = [m for m in mined if m["term"] not in seed_terms]
        terms = seeds + mined
        out = os.path.join(_SYS_DIR, f"{domain}_terms.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"domain": domain, "count": len(terms), "terms": terms},
                      f, ensure_ascii=False, indent=2)
        print(f"[OK] {domain}_terms.json: 种子 {len(seeds)} + 挖掘 {len(mined)} = {len(terms)} 条")
    print("[DONE] P-术语四类术语表产出完成（零 token）")


if __name__ == "__main__":
    main()

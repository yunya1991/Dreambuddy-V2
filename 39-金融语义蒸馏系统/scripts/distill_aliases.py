# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · 字典自动蒸馏脚本（阶段一）

职责（SPEC.md §3 阶段一）:
  1. 权威源校验: 从 OKX 公开接口拉取真实标的列表，校验别名表零幻觉代号
  2. 增量检测: 交易池新标的入池而别名表未覆盖时输出告警（禁止静默缺失）
  3. LLM 批量蒸馏（可选）: DEEPSEEK_API_KEY 可用时，对新标的批量生成中英文别名

成本设计:
  - OKX instruments 为公开免费接口，无 token 消耗
  - LLM 蒸馏仅在扩容事件触发时调用一次（非定时），无密钥时自动跳过

用法:
  python3 distill_aliases.py                # 校验 + 增量检测 + 告警
  python3 distill_aliases.py --with-llm     # 启用 LLM 蒸馏（需密钥）
  python3 distill_aliases.py --pool A,B,C   # 指定交易池（默认从别名表基准）

FAIL-OPEN: 任何环节失败不阻塞，输出告警后退出码 0；仅幻觉代号存在时退出码 1。
"""
import argparse
import json
import os
import sys
import urllib.request

ALIASES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "3.1-FRONTEND", "scripts", "entity_aliases.json",
)
OKX_SPOT_URL = "https://www.okx.com/api/v5/public/instruments?instType=SPOT"
OKX_SWAP_URL = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
# 非 OKX 品类（美股/贵金属，经其他渠道交易，跳过权威源校验）
NON_OKX_ASSETS = {"XAU", "XAG", "GOOGL", "NVDA", "AMZN", "MU", "SKHYNIX", "SNDK", "SPCX"}
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"


def load_aliases():
    with open(ALIASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_aliases(aliases):
    with open(ALIASES_PATH, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)


def fetch_okx_symbols():
    """拉取 OKX 现货+合约真实标的代号集合（公开接口，免费）。"""
    symbols = set()
    for url in (OKX_SPOT_URL, OKX_SWAP_URL):
        req = urllib.request.Request(url, headers={"User-Agent": "distill/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        symbols |= {row["instId"].split("-")[0] for row in data.get("data", [])}
    return symbols


def llm_distill_aliases(symbols):
    """LLM 批量蒸馏新标的中英文别名（需 DEEPSEEK_API_KEY，失败返回空）。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("[SKIP] DEEPSEEK_API_KEY 未配置，跳过 LLM 蒸馏（零成本模式）")
        return {}
    prompt = (
        "为以下交易标的生成中英文别名（含俗称与常见变体），"
        f"输出 JSON 对象 {{代号: [别名...]}}，别名不含代号本身: {','.join(symbols)}"
    )
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"[WARN] LLM 蒸馏失败（FAIL-OPEN 跳过）: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true", help="启用 LLM 蒸馏")
    parser.add_argument("--pool", default="", help="交易池标的（逗号分隔，默认以别名表为基准）")
    args = parser.parse_args()

    aliases = load_aliases()
    print(f"[INFO] 别名表当前覆盖 {len(aliases)} 个标的")

    # 1) 权威源校验（零幻觉代号；美股/贵金属白名单跳过）
    try:
        okx_symbols = fetch_okx_symbols()
        crypto_syms = [s for s in aliases if s not in NON_OKX_ASSETS]
        skipped = [s for s in aliases if s in NON_OKX_ASSETS]
        hallucinated = [s for s in crypto_syms if s not in okx_symbols]
        if skipped:
            print(f"[INFO] 非 OKX 品类（美股/贵金属）跳过校验: {skipped}")
        if hallucinated:
            print(f"[ALERT] 幻觉代号（OKX 不存在，需人工确认）: {hallucinated}")
            sys.exit(1)
        print(f"[OK] 权威源校验通过: {len(crypto_syms)} 个加密代号均真实存在")
    except Exception as e:
        print(f"[WARN] OKX 接口不可达，跳过校验（FAIL-OPEN）: {e}")

    # 2) 增量检测（新标的入池告警）
    pool = [s.strip().upper() for s in args.pool.split(",") if s.strip()] if args.pool else []
    if pool:
        missing = [s for s in pool if s not in aliases]
        if missing:
            print(f"[ALERT] 交易池新标的未覆盖别名（禁止静默缺失）: {missing}")
            if args.with_llm:
                distilled = llm_distill_aliases(missing)
                added = 0
                for sym, names in distilled.items():
                    sym = sym.upper()
                    if sym in missing and isinstance(names, list) and names:
                        aliases[sym] = [str(a) for a in names if a]
                        added += 1
                if added:
                    save_aliases(aliases)
                    print(f"[OK] LLM 蒸馏完成并入库: {added} 个标的")
                else:
                    print("[WARN] LLM 蒸馏未产出有效结果，保持告警状态")
        else:
            print("[OK] 交易池标的别名全覆盖")

    print("[DONE] 蒸馏流程结束")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intent_search_cli.py — 意图语义检索调试 CLI（P0）

用法:
    python scripts/intent_search_cli.py "BTC现在什么价格"
    python scripts/intent_search_cli.py "BTC现在什么价格" --lang en
    echo "BTC现在什么价格" | python scripts/intent_search_cli.py
"""

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEX_ROOT = _HERE.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core.intent_matcher import IntentMatcher, detect_lang  # noqa: E402
from core.intent_vector_store import IntentVectorStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="意图语义检索调试")
    parser.add_argument("message", nargs="?", type=str, help="用户问法")
    parser.add_argument("--lang", type=str, default="auto", choices=["auto", "zh", "en"])
    parser.add_argument("--topk", type=int, default=5, help="返回 top-K 候选")
    args = parser.parse_args()

    message = args.message
    if not message:
        message = sys.stdin.read().strip()
    if not message:
        print("请提供 message 参数或通过 stdin 输入", file=sys.stderr)
        sys.exit(1)

    store = IntentVectorStore()
    matcher = IntentMatcher(store=store)
    lang = detect_lang(message) if args.lang == "auto" else args.lang

    # 语义 top-K
    topk = matcher.semantic_topk(message, lang=lang, k=args.topk)

    result = {
        "message": message,
        "lang": lang,
        "semantic_topk": [
            {"intent": intent, "similarity": round(score, 4)} for intent, score in topk
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

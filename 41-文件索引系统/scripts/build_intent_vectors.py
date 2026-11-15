#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_intent_vectors.py — 构建所有意图的语义向量（P0）

用法:
    python scripts/build_intent_vectors.py            # 默认：使用前缀策略
    python scripts/build_intent_vectors.py --no-prefix  # 无前缀（A/B 验证）
    python scripts/build_intent_vectors.py --intent price_query  # 单个意图
"""

import argparse
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEX_ROOT = _HERE.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core.intent_embedder import build_all, build_intent_vector  # noqa: E402
from core.intent_vector_store import IntentVectorStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="构建意图语义向量")
    parser.add_argument("--intent", type=str, default=None, help="只构建指定意图")
    parser.add_argument(
        "--prefix", action="store_true", help="使用分块前缀策略（A/B 验证显示无前缀更优，默认关闭）"
    )
    parser.add_argument("--min-examples", type=int, default=5, help="最少正例句数")
    args = parser.parse_args()

    store = IntentVectorStore()
    use_prefix = args.prefix

    print(f"前缀策略: {'启用' if use_prefix else '禁用'}")
    print(f"最少正例句: {args.min_examples}")
    print()

    if args.intent:
        build_intent_vector(
            args.intent, store=store, use_prefix=use_prefix, min_examples=args.min_examples
        )
    else:
        results = build_all(store=store, use_prefix=use_prefix, min_examples=args.min_examples)
        zh_count = sum(1 for v in results.values() if v["zh"])
        en_count = sum(1 for v in results.values() if v["en"])
        print(f"\n完成: {zh_count} 个中文向量, {en_count} 个英文向量")


if __name__ == "__main__":
    main()

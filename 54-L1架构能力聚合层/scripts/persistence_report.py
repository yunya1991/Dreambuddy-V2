#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T0 延续性画像报告生成器（薄封装，逻辑在 l1agg/persistence/report.py）。

用法：
  python3 scripts/persistence_report.py
  python3 scripts/persistence_report.py --symbols BTC ETH --days 1200
  python3 scripts/persistence_report.py --out reports/persistence
"""

import os
import sys

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.persistence.report import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

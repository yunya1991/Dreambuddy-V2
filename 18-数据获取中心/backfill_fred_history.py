#!/usr/bin/env python3
"""一次性回填（2026-11-10）：FRED 序列全量历史 → data_center（跟随 DATA_CENTER_BACKEND）。
复用 FredCollector historical=True + 标准 sink 链路；dedupe_key 幂等，可安全重跑。
"""
import os
import sys
import time
from pathlib import Path
# 2026-11-10 修复：sink_postgres 密码发现不含 luke 私有凭证文件，先从 ~/.dreambuddy-pg.env 提取并注入环境变量
_cred = Path.home() / ".dreambuddy-pg.env"
if _cred.exists() and not os.environ.get("DATA_CENTER_PG_PASSWORD"):
    for _line in _cred.read_text().splitlines():
        _line = _line.strip()
        if _line.startswith("DATA_CENTER_PG_PASSWORD="):
            os.environ["DATA_CENTER_PG_PASSWORD"] = _line.split("=", 1)[1].strip()
            break
sys.path.insert(0, "/home/luke/dreambuddy/18-数据获取中心")
from data_center.collectors.macro.fred_collector import FredCollector
from data_center.storage import sink_postgres

SERIES = (
    # postgres 现有 13 序列
    "CPIAUCSL", "DCOILWTICO", "DGS10", "DTWEXBGS", "FEDFUNDS", "INDPRO",
    "IR14260", "M2NS", "NASDAQCOM", "PPIACO", "SP500", "VIXCLS", "WALCL",
    # 采集器标准序列补充
    "RRPONTSYD", "DFII10", "T10YIE", "M2SL", "PAYEMS",
    # 40 系统需要但 postgres 缺失
    "T10Y2Y", "BAMLH0A0HYM2",
)

def main():
    collector = FredCollector()
    sink = sink_postgres.get_sink()
    total_new = 0
    for s in SERIES:
        try:
            recs = collector.fetch({"series": s, "historical": True})
            if not recs:
                print(f"[warn] {s}: 0 条", flush=True)
                continue
            n = sink.write(recs)
            total_new += n
            print(f"{s}: 抓取 {len(recs)} 条, 新增 {n} 条", flush=True)
        except Exception as e:
            print(f"[error] {s}: {e}", flush=True)
        time.sleep(1)
    print(f"=== 回填完成，共新增 {total_new} 条 ===", flush=True)

if __name__ == "__main__":
    main()

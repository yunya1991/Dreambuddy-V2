# -*- coding: utf-8 -*-
"""BDSM（回购驱动力可持续性评估模型）原生数据采集器。

从项目原生网站爬取数据，不依赖第三方数据网站（DeFiLlama/CoinGecko）。
每个 collector 对应一个项目，输出 DataRecord 入库 data_center.db。

collectors:
  - pump_native_collector: pump.fun/pump-token HTML 爬取
  - circle_native_collector: circle.com/transparency HTML 爬取
  - uniswap_native_collector: GraphQL API (The Graph)
"""

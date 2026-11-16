# -*- coding: utf-8 -*-
"""E1-D1 测试集生成器（SPEC-v1.4 §7.1.2）。

产出：34-前端应用训练系统/eval/e1_cases.jsonl（500 条，版本 e1_d1@2026-11-16）
纪律：
  - 标注为 AI 初标（label_status=ai_draft），必须经 100% 人工复核后才可用于终态裁决；
  - semantic 段与 intent_units/*/examples_zh.jsonl、negatives_zh.jsonl 零重叠（脚本硬校验）；
  - semantic 段必须正则无法命中（否则测的不是语义通道）；
  - 生成结果确定性（无随机），重复执行得到同一文件。

用法：python3 34-前端应用训练系统/scripts/gen_e1_cases.py [--check]
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SCRIPTS_DIR = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l1_route_signal as lrs  # noqa: E402

UNITS_DIR = os.path.join(_ROOT, "41-文件索引系统", "intent_units")
OUT_PATH = os.path.join(_ROOT, "34-前端应用训练系统", "eval", "e1_cases.jsonl")
DATASET_VERSION = "e1_d1@2026-11-16"

# ============================================================
# data 段（80）：19 个有执行器意图各 4 条（部分 5 条）
# ============================================================
DATA = [
    # price_query
    ("BTC现在什么价格", "price_query"),
    ("ETH多少钱", "price_query"),
    ("SOL现价多少", "price_query"),
    ("比特币最新价", "price_query"),
    ("黄金实时价格是多少", "price_query"),
    ("以太坊现在什么价", "price_query"),
    # metric_series
    ("查一下最新CPI", "metric_series"),
    ("现在恐惧贪婪指数多少", "metric_series"),
    ("BTC资金费率是多少", "metric_series"),
    ("现在多空比是多少", "metric_series"),
    ("稳定币总市值现在多少", "metric_series"),
    # data_query
    ("查ETH链上TVL", "data_query"),
    ("最新快讯有哪些", "data_query"),
    ("查一下美股开盘数据", "data_query"),
    ("本周非农数据出了吗", "data_query"),
    # data_insight
    ("CPI超预期意味着什么", "data_insight"),
    ("稳定币流入增加说明什么", "data_insight"),
    ("资金费率转负什么影响", "data_insight"),
    ("非农数据不及预期意味着什么", "data_insight"),
    # contradiction_insight
    ("各维度和资金面有矛盾吗", "contradiction_insight"),
    ("技术面和情绪面哪个占主导", "contradiction_insight"),
    ("资金面和宏观数据打架了吗", "contradiction_insight"),
    ("技术面和资金面共振还是冲突", "contradiction_insight"),
    # path_insight
    ("综合看最小阻力路径往哪走", "path_insight"),
    ("现在能不能上车", "path_insight"),
    ("该多还是空", "path_insight"),
    ("综合判断现在该买还是该卖", "path_insight"),
    # technical_analysis
    ("BTC技术面和卦象", "technical_analysis"),
    ("以太坊技术形态怎么样", "technical_analysis"),
    ("以太坊的卦象置信度如何", "technical_analysis"),
    ("现在技术面偏多还是偏空", "technical_analysis"),
    # technical_indicator
    ("比特币目前阻力位在哪", "technical_indicator"),
    ("ETH 现在支撑位多少", "technical_indicator"),
    ("SOL的RSI超买了吗", "technical_indicator"),
    ("BTC均线金叉了吗", "technical_indicator"),
    ("黄金的压力位在哪里", "technical_indicator"),
    # stat_query
    ("BTC 年化波动率", "stat_query"),
    ("CPI 同比", "stat_query"),
    ("BTC 和 ETH 滚动相关", "stat_query"),
    ("MVRV 历史分位", "stat_query"),
    # fundamental_valuation
    ("ETH估值百分位高不高", "fundamental_valuation"),
    ("BTC现在贵不贵", "fundamental_valuation"),
    ("以太坊基本面怎么样", "fundamental_valuation"),
    ("现在估值便宜吗", "fundamental_valuation"),
    # asset_class_trend
    ("美股和加密的跨资产趋势对比", "asset_class_trend"),
    ("各大类资产最近表现如何", "asset_class_trend"),
    ("美股和黄金最近谁更强", "asset_class_trend"),
    ("资产轮动现在到什么阶段了", "asset_class_trend"),
    # event_analysis
    ("这次FOMC事件分析", "event_analysis"),
    ("鲍威尔讲话怎么反应", "event_analysis"),
    ("议息会议落地后影响多大", "event_analysis"),
    ("这次事件解读一下", "event_analysis"),
    # risk_control
    ("当前持仓风控和止损位", "risk_control"),
    ("我的仓位风险大不大", "risk_control"),
    ("现在要不要减仓", "risk_control"),
    ("移动止盈怎么设置", "risk_control"),
    # whale_flow
    ("查询巨鲸动向", "whale_flow"),
    ("巨鲸最近在流入还是流出", "whale_flow"),
    ("大户最近在转账吗", "whale_flow"),
    ("whale 最近有什么动作", "whale_flow"),
    # calendar_event
    ("下一次议息会议是什么时候", "calendar_event"),
    ("非农数据什么时候公布", "calendar_event"),
    ("经济日历里本周有什么", "calendar_event"),
    ("下次CPI数据哪天公布", "calendar_event"),
    # leader_compare
    ("BTC和ETH涨跌幅对比", "leader_compare"),
    ("以太坊和比特币谁更强", "leader_compare"),
    ("SOL和ETH最近涨幅对比", "leader_compare"),
    ("BTC和黄金比哪个涨得多", "leader_compare"),
    # top_correlation
    ("相关性最高的指标是哪个", "top_correlation"),
    ("BTC和哪个指标最相关", "top_correlation"),
    ("帮我看一下相关性分析", "top_correlation"),
    ("现在相关性最强的资产是什么", "top_correlation"),
    # persistence_strength
    ("这波趋势延续性怎么样", "persistence_strength"),
    ("现在动量延续强不强", "persistence_strength"),
    ("均值回复的概率有多大", "persistence_strength"),
    ("Hurst 指数多少", "persistence_strength"),
    # event_listing
    ("以太坊 最近新闻", "event_listing"),
    ("今天有什么值得关注的新闻", "event_listing"),
    ("给我盘点一下本周要闻", "event_listing"),
    ("最近币圈有什么热点", "event_listing"),
]

# ============================================================
# semantic 段（80）：口语改写，不含注册表关键词（脚本硬校验 regex 零命中）
# ============================================================
SEMANTIC = [
    # price_query
    ("大饼眼下报个什么数", "price_query"),
    ("姨太这会儿报几个点", "price_query"),
    ("二饼的盘面眼下咋样", "price_query"),
    ("银子现在值几个钱", "price_query"),
    # metric_series
    ("大饼的杠杆水位现在多高", "metric_series"),
    ("恐慌贪婪现在读数多少", "metric_series"),
    ("链上美元盘子眼下铺多大", "metric_series"),
    ("多空两边的人气现在哪边旺", "metric_series"),
    # data_query
    ("股那边开出来是好是坏", "data_query"),
    ("帮我把链上的近况拉出来", "data_query"),
    ("宏观这边最近出了啥数", "data_query"),
    ("帮我看看海外那边开盘啥样", "data_query"),
    # data_insight
    ("物价炸了这代表啥", "data_insight"),
    ("美元稳定资产突然涌进来能说明啥", "data_insight"),
    ("杠杆费用转负了这是要闹哪样", "data_insight"),
    ("就业数字拉了后边会往哪去", "data_insight"),
    # contradiction_insight
    ("几个面之间现在是对着干吗", "contradiction_insight"),
    ("技术这一面和情绪这一面谁说了算", "contradiction_insight"),
    ("资金这一面和宏观是不是拧着", "contradiction_insight"),
    ("几个面现在是一致还是互相拆台", "contradiction_insight"),
    # path_insight
    ("现在这盘适合偏多还是偏空", "path_insight"),
    ("这会儿进场合适不", "path_insight"),
    ("该加还是该撤", "path_insight"),
    ("整体看该压哪一头", "path_insight"),
    # technical_analysis
    ("用卦看一看大饼的走势", "technical_analysis"),
    ("从图形结构看现在偏强还是偏弱", "technical_analysis"),
    ("这波走势和指标不同步说明啥", "technical_analysis"),
    ("盘面技术这块偏强还是偏弱", "technical_analysis"),
    # technical_indicator
    ("大饼上面顶在哪儿", "technical_indicator"),
    ("姨太下面托在哪儿", "technical_indicator"),
    ("现在是不是卖过头了", "technical_indicator"),
    ("移动平均那块现在什么状态", "technical_indicator"),
    # stat_query
    ("大饼的波动现在算大吗", "stat_query"),
    ("物价这个月的年增怎么样", "stat_query"),
    ("大饼和二饼是不是同步动", "stat_query"),
    ("当前贵贱程度排在历史啥位置", "stat_query"),
    # fundamental_valuation
    ("大饼现在算高位吗", "fundamental_valuation"),
    ("姨太这个位置划不划算", "fundamental_valuation"),
    ("从底子看大饼值这个钱吗", "fundamental_valuation"),
    ("现在这价是偏贵还是偏便宜", "fundamental_valuation"),
    # asset_class_trend
    ("股和币最近谁走得顺", "asset_class_trend"),
    ("几个大类这些天谁在领跑", "asset_class_trend"),
    ("钱现在往哪类资产跑", "asset_class_trend"),
    ("金子和股这一阵谁更硬", "asset_class_trend"),
    # event_analysis
    ("这次利率会议出来后市场咋反应的", "event_analysis"),
    ("老大的发言这事影响大吗", "event_analysis"),
    ("这次会议开完后劲儿有多大", "event_analysis"),
    ("这个事件该怎么理解", "event_analysis"),
    # risk_control
    ("我这仓位现在稳不稳", "risk_control"),
    ("要不要先撤一部分", "risk_control"),
    ("保护线该放哪儿", "risk_control"),
    ("现在敞口是不是太大了", "risk_control"),
    # whale_flow
    ("大资金最近在偷偷买吗", "whale_flow"),
    ("巨无霸地址最近在挪钱吗", "whale_flow"),
    ("鲸鱼这一阵是进还是跑", "whale_flow"),
    ("大玩家最近什么动作", "whale_flow"),
    # calendar_event
    ("下次开会是哪天", "calendar_event"),
    ("就业数字哪天出", "calendar_event"),
    ("这周日程表上有啥", "calendar_event"),
    ("下次物价数字啥时候发", "calendar_event"),
    # leader_compare
    ("大饼和二饼谁跑得快", "leader_compare"),
    ("姨太比大饼强吗", "leader_compare"),
    ("这两个币最近谁赢", "leader_compare"),
    ("大饼和金子在的这波谁更猛", "leader_compare"),
    # top_correlation
    ("哪个东西和大饼最同步", "top_correlation"),
    ("和大饼联动最强的是谁", "top_correlation"),
    ("谁跟大饼走得最近", "top_correlation"),
    ("关联度最高的那个是啥", "top_correlation"),
    # persistence_strength
    ("这波势头还能撑多久", "persistence_strength"),
    ("这波势头是不是会自我延续", "persistence_strength"),
    ("现在这波是延续还是回头", "persistence_strength"),
    ("涨势的黏性大不大", "persistence_strength"),
    # event_listing
    ("这两天圈里有啥新鲜事", "event_listing"),
    ("给我念念今天都有啥大事", "event_listing"),
    ("最近有什么得早点晓得的事", "event_listing"),
    ("这两天风声有啥变化", "event_listing"),
    # fundamental_valuation / price 补充
    ("二饼这阵子热不热", "data_insight"),
    ("大饼这两天有没有异样", "event_listing"),
    ("姨太这会儿该不该下手", "path_insight"),
    ("大饼这会儿成交活不活", "data_query"),
]

# ============================================================
# out_of_scope 段（120）
# ============================================================
OUT_OF_SCOPE = [
    # 闲聊/寒暄 20
    "你好",
    "在吗",
    "早上好呀",
    "你是谁",
    "你能做什么",
    "谢谢",
    "再见",
    "晚安",
    "今天心情不错",
    "陪我聊会儿天",
    "讲个笑话",
    "你觉得我可爱吗",
    "无聊死了",
    "骂我一句",
    "夸夸我",
    "你多大了",
    "你住在哪",
    "你喜欢什么颜色",
    "我今天好累",
    "帮我写句情话",
    # 通用知识 20
    "地球到月球多远",
    "水的沸点是多少",
    "中国有多少个省份",
    "光速是多少",
    "恐龙为什么会灭绝",
    "珠穆朗玛峰有多高",
    "太阳系有几颗行星",
    "人类什么时候登上月球",
    "光合作用是什么",
    "DNA 是什么",
    "牛顿第一定律内容",
    "第一次世界大战哪年结束",
    "李白是哪个朝代的",
    "红楼梦作者是谁",
    "圆周率前一百位",
    "蚂蚁有几条腿",
    "大气层有哪几层",
    "世界上最大的沙漠",
    "企鹅生活在哪",
    "鲸鱼是哺乳动物吗",
    # 编程 20
    "Python 怎么写快速排序",
    "React 的 useEffect 依赖数组怎么用",
    "帮我写一个冒泡排序",
    "SQL 里 inner join 和 left join 区别",
    "Docker 容器怎么暴露端口",
    "Git 怎么撤销上一次 commit",
    "TypeScript 的 interface 和 type 区别",
    "怎么在 Linux 里查看端口占用",
    "Nginx 反向代理怎么配置",
    "Redis 缓存穿透怎么解决",
    "MySQL 索引失效的常见原因",
    "Kubernetes pod 一直重启怎么排查",
    "写一个正则匹配邮箱",
    "Java 的线程池参数怎么设置",
    "Go 的 goroutine 泄漏怎么查",
    "Vue 组件通信有几种方式",
    "怎么用 ffmpeg 压缩视频",
    "Shell 脚本怎么读取文件每一行",
    "Rust 的所有权是什么",
    "给这段代码加个单元测试",
    # 生活 20
    "西红柿炒鸡蛋怎么做",
    "明天会下雨吗",
    "怎么快速入睡",
    "北京到上海高铁多久",
    "附近有什么好吃的",
    "怎么减肥比较健康",
    "感冒了吃什么药",
    "洗衣服多久洗一次",
    "如何提高睡眠质量",
    "推荐几部好看的电影",
    "周末去哪玩比较好",
    "猫粮哪个牌子好",
    "怎么练出腹肌",
    "咖啡一天喝几杯合适",
    "电动车怎么保养",
    "护照怎么办",
    "房租太贵怎么办",
    "怎么和同事相处",
    "婚礼请帖怎么写",
    "孩子不爱写作业怎么办",
    # 非金融建议 20
    "帮我写一份求职简历",
    "给我规划一下职业发展",
    "这篇论文该怎么写",
    "帮我翻译一段英文",
    "给我起个公司名字",
    "写一首关于秋天的诗",
    "做一份生日策划方案",
    "帮我起个菜名",
    "写一段婚礼致辞",
    "帮我设计一个 logo",
    "写一篇产品发布会稿子",
    "给孩子起个名字",
    "帮我做一份旅行攻略",
    "写一段自我介绍",
    "帮我把这段话润色一下",
    "帮我拟一份合同模板",
    "教我怎么面试",
    "帮我编一个故事",
    "写一段广告文案",
    "帮我做一份周报模板",
    # 其他 20
    "今天星期几",
    "帮我订个会议室",
    "帮我定个闹钟",
    "提醒我明天开会",
    "帮我查一下快递",
    "附近加油站怎么走",
    "帮我买张电影票",
    "帮我写一封请假邮件",
    "我的车该保养了",
    "怎么修马桶漏水",
    "帮我算一下房贷",
    "推荐一款洗发水",
    "帮我找部纪录片",
    "这道数学题怎么解",
    "帮我写个祝福短信",
    "教我几句日语",
    "帮我整理一下桌面",
    "怎么给手机换电池",
    "帮我规划一下健身计划",
    "帮我写作业",
]

# ============================================================
# compound 段（80）：双意图并列 → L2（不隐式拆解）
# ============================================================
COMPOUND = [
    "BTC价格和CPI数据",
    "以太坊新闻和BTC现价",
    "巨鲸动向和资金费率",
    "BTC估值和黄金价格",
    "CPI同比和BTC波动率",
    "BTC技术面和美联储议息",
    "ETH阻力位和巨鲸转账",
    "稳定币市值和美股开盘",
    "BTC和ETH相关性对比以及CPI",
    "黄金价格和BTC资金费率",
    "BTC支撑位和相关最高指标",
    "美股趋势和BTC估值百分位",
    "BTC价格和以太坊新闻",
    "下一次议息会议和CPI数据",
    "BTC涨跌幅对比和巨鲸动向",
    "SOL现价和BTC技术形态",
    "BTC年化波动率和黄金现价",
    "恐惧贪婪指数和美股表现",
    "BTC多空比和非农数据",
    "ETH估值和趋势延续性",
    "帮我查BTC价格，再看看CPI",
    "先说下以太坊新闻，然后讲BTC现价",
    "巨鲸在干什么，顺手看下资金费率",
    "BTC贵不贵，和黄金比呢",
    "CPI出了多少，非农呢",
    "BTC技术面如何，基本面呢",
    "ETH支撑位在哪，阻力位呢",
    "大饼现价和姨太现价都报一下",
    "稳定币规模多少，美股开盘怎么样",
    "BTC和ETH谁强，还有CPI多少",
    "BTC和SOL涨跌幅对比，另外看下黄金",
    "相关性最高的指标和BTC估值",
    "BTC年化波动率多少，巨鲸在干嘛",
    "下次议息会议什么时候，CPI又是哪天",
    "以太坊最近新闻和ETH价格一起给我",
    "BTC技术指标和资金费率一起",
    "美股和黄金谁强，BTC和ETH谁强",
    "恐慌指数多少，多空比多少",
    "BTC和ETH滚动相关，顺便看CPI同比",
    "帮我查RWA规模，还有BTC价格",
    "BTC价格、CPI、巨鲸动向全都要",
    "以太坊行情加新闻，一次说完",
    "现在估值贵不贵，技术面又怎么说",
    "BTC能做多吗，CPI影响大吗",
    "帮我看看BTC和黄金的估值对比",
    "巨鲸流入和BTC价格一起看",
    "BTC资金费率和多空比，一起给我",
    "ETH阻力位、支撑位都要",
    "美股表现、A股表现都报一下",
    "BTC价格与ETH价格，再对比一下黄金",
    "CPI走势和通胀预期一起讲",
    "BTC波动率和VIX一起看",
    "以太坊估值和ETH技术面",
    "SOL现价与SOL新闻",
    "帮我查CPI，再算一下BTC实际利率",
    "巨鲸动向以及美股趋势",
    "BTC价格和稳定币规模",
    "黄金阻力位和BTC支撑位",
    "非农数据和失业率数据",
    "BTC和黄金相关性，还有ETH价格",
    "以太坊技术指标和巨鲸动作",
    "BTC价格多少，还有估值贵不贵",
    "ETH现价和BTC现价对比，再给新闻",
    "恐惧贪婪和资金费率一起看",
    "BTC历史分位和年化波动率",
    "CPI同比、环比、月频序列都要",
    "BTC价格走势和巨鲸动向一起",
    "美股和加密谁强，顺便CPI多少",
    "帮我查BTC价格，并分析CPI影响",
    "ETH支撑位和BTC阻力位一起说",
    "BTC和ETH的涨跌幅与相关性",
    "稳定币增速和ETF净流入",
    "BTC估值百分位与多空比",
    "下次CPI时间和下次议息时间",
    "以太坊新闻、ETH价格、ETH估值",
    "BTC现价、SOL现价、黄金现价",
    "巨鲸在买什么，BTC价格多少",
    "BTC技术面、资金面、情绪面一起评",
    "美股开盘数据和BTC价格",
    "黄金现价和BTC阻力位",
]

# ============================================================
# trap 段（60）：关键词陷阱 / 错别字 / 中英混写 / 超短
# expected_route: L1 / L2；expected_intent=None 表示期望交 L2
# ============================================================
TRAP = [
    ("现在几点了", "L2", None, "normal"),
    ("现在有多少人在线", "L2", None, "normal"),
    ("今天天气多少度", "L2", None, "normal"),
    ("股票是什么", "L2", None, "normal"),
    ("BTC是什么", "L2", None, "normal"),
    ("以太坊是哪个公司做的", "L2", None, "normal"),
    ("区块链和比特币有关系吗", "L2", None, "normal"),
    ("帮我写一篇关于以太坊的新闻稿", "L2", None, "critical"),
    ("以太坊最近新闻帮我写个总结报告", "L2", None, "normal"),
    ("模拟一下巨鲸讲话", "L2", None, "normal"),
    ("如果我有100万该怎么理财", "L2", None, "critical"),
    ("帮我预测下明天BTC涨还是跌", "L2", None, "critical"),
    ("告诉我买哪个币能赚钱", "L2", None, "critical"),
    ("BTC价格什么时候能到100万", "L2", None, "normal"),
    ("你会不会炒币", "L2", None, "normal"),
    ("讲个关于韭菜的段子", "L2", None, "normal"),
    ("最近有什么好听的歌", "L2", None, "normal"),
    ("CPI是什么的缩写", "L2", None, "normal"),
    ("非农数据是什么", "L2", None, "normal"),
    ("量化的意思是什么", "L2", None, "normal"),
    ("btc price now", "L1", "price_query", "normal"),
    ("eth price please", "L1", "price_query", "normal"),
    ("whale movement recent", "L1", "whale_flow", "normal"),
    ("cpi yoy latest", "L1", "metric_series", "normal"),
    ("btc support level", "L1", "technical_indicator", "normal"),
    ("比特市现在什么价", "L1", "price_query", "normal"),
    ("以太房最近新闻", "L1", "event_listing", "normal"),
    ("巨京最近在流入吗", "L1", "whale_flow", "normal"),
    ("CPI 超预其意味着什么", "L1", "data_insight", "normal"),
    ("稳顶币市值多少", "L1", "metric_series", "normal"),
    ("ETH?", "L2", None, "normal"),
    ("CPI呢", "L2", None, "normal"),
    ("BTC", "L2", None, "normal"),
    ("新闻", "L2", None, "normal"),
    ("价格", "L2", None, "normal"),
    ("巨鲸", "L2", None, "normal"),
    ("估值", "L2", None, "normal"),
    ("支撑位", "L2", None, "normal"),
    ("BTC价格和BTC价格", "L2", None, "normal"),
    ("帮我查一下文档里怎么写的风控", "L2", None, "normal"),
    ("SPEC文档在哪个目录", "L2", None, "normal"),
    ("最近监管有什么变化", "L2", None, "normal"),
    ("ETF资金流向最近有什么变化", "L2", None, "normal"),
    ("地缘事件最近进展如何", "L2", None, "normal"),
    ("BTC行情怎么看", "L2", None, "normal"),
    ("ETH还能拿吗", "L2", None, "normal"),
    ("我昨天买的BTC怎么办", "L2", None, "critical"),
    ("帮我梭哈BTC", "L2", None, "critical"),
    ("把房子卖了买币行不行", "L2", None, "critical"),
    ("CPI会不会把市场砸崩", "L2", None, "normal"),
    ("美联储是不是要完蛋了", "L2", None, "normal"),
    ("帮我生成一份BTC投资计划书", "L2", None, "normal"),
    ("写一段BTC看涨文案", "L2", None, "normal"),
    ("把我持仓全部清掉", "L2", None, "critical"),
    ("直接帮我下单买ETH", "L2", None, "critical"),
    ("BTC和美元哪个更保值", "L2", None, "normal"),
    ("能不能教我做量化策略", "L2", None, "normal"),
    ("稳定币会崩盘吗", "L2", None, "normal"),
    ("这波牛市还能持续多久", "L2", None, "normal"),
    ("美联储降息对房价影响", "L2", None, "normal"),
]

# ============================================================
# clarify 段（40）：缺关键槽位（无标的 / 无指标名）→ L1 追问
# ============================================================
CLARIFY = [
    # price_query 缺币种（22）——exec_price_query 返回 need_clarification
    ("现在什么价", "price_query"),
    ("这个币多少钱", "price_query"),
    ("帮我看看现价", "price_query"),
    ("最新报价是多少", "price_query"),
    ("现在卖什么价格", "price_query"),
    ("这货现在啥价格", "price_query"),
    ("实时价格多少", "price_query"),
    ("现价报一下", "price_query"),
    ("现在价格怎么样了", "price_query"),
    ("这个多少钱一个", "price_query"),
    ("帮我查价格", "price_query"),
    ("价格多少", "price_query"),
    ("现在涨到多少了", "price_query"),
    ("跌到多少了", "price_query"),
    ("这个标的现在什么价格", "price_query"),
    ("实时报价给我", "price_query"),
    ("现在什么价位", "price_query"),
    ("现价多少", "price_query"),
    ("最新价多少", "price_query"),
    ("给我个最新价", "price_query"),
    ("报价一下", "price_query"),
    ("价格报一下", "price_query"),
    # leader_compare 缺对比标的（10）——exec_leader_compare 返回 need_clarification
    ("对比一下涨幅", "leader_compare"),
    ("涨跌幅对比", "leader_compare"),
    ("比较一下涨幅差距", "leader_compare"),
    ("龙头涨跌幅对比", "leader_compare"),
    ("对比一下变化幅度", "leader_compare"),
    ("涨幅对比一下", "leader_compare"),
    ("比较两个的涨跌幅", "leader_compare"),
    ("对比涨幅差距", "leader_compare"),
    ("涨跌幅度对比", "leader_compare"),
    ("龙头之间涨跌幅对比", "leader_compare"),
    # technical_analysis 缺币种（8）——exec_technical_analysis 返回 need_clarification
    ("技术面现在怎么样", "technical_analysis"),
    ("技术面偏强还是偏弱", "technical_analysis"),
    ("卦象怎么看", "technical_analysis"),
    ("技术形态如何", "technical_analysis"),
    ("背离该怎么理解", "technical_analysis"),
    ("支撑位怎么理解", "technical_analysis"),
    ("技术指标怎么看", "technical_analysis"),
    ("置信度怎么看", "technical_analysis"),
]

# ============================================================
# regression 段（40）：golden 中曾被 recall_empty 门控拦下的意图样本
# ============================================================
_REGRESSION_INTENTS = (
    "price_query",
    "data_insight",
    "event_analysis",
    "path_insight",
    "contradiction_insight",
    "technical_analysis",
    "fundamental_valuation",
    "asset_class_trend",
    "risk_control",
)


def _load_lines(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _unit_messages():
    """intent_units 全部正例/负例消息（用于零重叠校验）。"""
    msgs = set()
    for name in os.listdir(UNITS_DIR):
        d = os.path.join(UNITS_DIR, name)
        if not os.path.isdir(d):
            continue
        for fn in ("examples_zh.jsonl", "negatives_zh.jsonl"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                msgs.update(r["message"] for r in _load_lines(p))
    return msgs


def _regression_cases(exclude=None):
    golden_path = os.path.join(_ROOT, "34-前端应用训练系统", "l1_intent_golden.jsonl")
    rows = _load_lines(golden_path)
    skip = set(exclude or ())
    picked = []
    for r in rows:
        msg = r["message"]
        if msg in skip:
            continue
        if r.get("intent") in _REGRESSION_INTENTS and r.get("variant") != "oos":
            picked.append(r)
        if len(picked) == 40:
            break
    return [(r["message"], r["intent"]) for r in picked]


def build_cases():
    cases = []

    def add(
        segment, message, expected_route, expected_intent, severity="normal", state=None, note=""
    ):
        cases.append(
            {
                "id": "",
                "message": message,
                "segment": segment,
                "expected_route": expected_route,
                "expected_intent": expected_intent,
                "expected_state": state,
                "severity": severity,
                "data_available": True,
                "label_status": "ai_draft",
                "note": note,
            }
        )

    for msg, intent in DATA:
        add("data", msg, "L1", intent)
    for msg, intent in SEMANTIC:
        add("semantic", msg, "L1", intent)
    for msg in OUT_OF_SCOPE:
        add("out_of_scope", msg, "L2", None, note="域外/闲聊/通用")
    for msg in COMPOUND:
        add("compound", msg, "L2", None, note="复合问法，禁止隐式拆解（部分作答非安全Critical）")
    for msg, route, intent, sev in TRAP:
        add("trap", msg, route, intent, severity=sev, note="边界陷阱")
    for msg, intent in CLARIFY:
        add("clarify", msg, "L1", intent, state="need_clarification", note="缺槽位，应追问")
    used = {c["message"] for c in cases}
    for msg, intent in _regression_cases(exclude=used):
        add("regression", msg, "L1", intent, note="golden 样本；云端 recall_empty 期间恒交 L2")

    for i, c in enumerate(cases, 1):
        c["id"] = f"E1-{i:04d}"
    return cases


def validate(cases):
    errors = []
    counts = Counter(c["segment"] for c in cases)
    expected = {
        "data": 80,
        "semantic": 80,
        "out_of_scope": 120,
        "compound": 80,
        "trap": 60,
        "clarify": 40,
        "regression": 40,
    }
    if counts != expected:
        errors.append(f"分段数量不符: {dict(counts)} != {expected}")
    if len(cases) != 500:
        errors.append(f"总数 {len(cases)} != 500")

    seen = {}
    for c in cases:
        if c["message"] in seen:
            errors.append(f"重复消息: {c['message']} ({seen[c['message']]} vs {c['id']})")
        seen[c["message"]] = c["id"]

    unit_msgs = _unit_messages()
    # SPEC §7.1.2 纪律 2：仅 semantic 段要求与 intent_units 零重叠（data 段用注册表规范问法）
    overlap = [
        c["message"] for c in cases if c["segment"] == "semantic" and c["message"] in unit_msgs
    ]
    if overlap:
        errors.append(f"semantic 段与 intent_units 正/负例重叠 {len(overlap)} 条: {overlap[:5]}")
    other_overlap = sum(
        1 for c in cases if c["segment"] != "semantic" and c["message"] in unit_msgs
    )

    sem_regex = [
        (c["message"], lrs.detect_intent_regex(c["message"]))
        for c in cases
        if c["segment"] == "semantic" and lrs.detect_intent_regex(c["message"])
    ]
    if sem_regex:
        errors.append(f"semantic 段被正则命中 {len(sem_regex)} 条: {sem_regex[:10]}")
    return errors, counts, other_overlap


def main():
    cases = build_cases()
    errors, counts, other_overlap = validate(cases)
    print("分段统计:", dict(counts), "合计:", len(cases))
    print(f"非 semantic 段与 intent_units 规范问法重叠（信息项）: {other_overlap} 条")
    if errors:
        print("校验失败:")
        for e in errors:
            print(" -", e)
        if "--check" not in sys.argv:
            print("（未写文件）")
        return 1
    if "--check" in sys.argv:
        print("校验通过（未写文件）")
        return 0
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("已写入", OUT_PATH, "版本", DATASET_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

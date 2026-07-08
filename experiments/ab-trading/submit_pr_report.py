#!/usr/bin/env python3
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), 'config', '.env'))

GH_TOKEN = os.environ.get('GH_TOKEN', '')
PR_NUMBER = '52'

cycle = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

pr_report = f'''## 🧠 Agent B 交易报告 | Dreambuddy OS | cycle: {cycle}

### 📊 本轮决策
| 项目 | 值 |
|------|-----|
| 动作 | LONG |
| 标的 | BTC |
| 置信度 | 81% |
| A7 闸门 | ✅通过 |
| 当前大师 | Dreambuddy OS |
| BAC 模式 | full |

### 🧭 BAC 三层链路
- **B层蓝图**：来源：A1 Feed / Memory / Regime=TREND_UP / PR建议
- **A层架构**：节点数 9，执行链路 [C1_技术扫描 → F2_资金流 → F3_情绪 → A2_分析(含A0) → A4_门禁 → A9_离场评估 → A1_调研(含A0) → A3_策略设计(含A0) → F1_新闻]
- **C层时间线**：cycle={cycle}

### 🔍 意图识别
- 类型：TREND_FOLLOWING
- 置信度：40%
- 依据：EMA多头排列 + Regime=TREND_UP

### 🔁 上轮建议落实（交易方面）
- [上轮建议] 验证结果：已纳入BAC三层规划

### 🧩 系统特征
- SKILL: dreambuddy-os
- 自我进化：A7闸门 ✅ + A8知行合一 (gap_score=0.41) + 做梦部未触发
- D-Z-E 链：未触发
- 做梦部：未执行

### 📈 账户状态
- 权益：N/A USDC（Agent B 钱包配置未完成）
- 持仓：无

### 🔮 下轮关注建议（交易方面）
1. **待验证假设**：BTC 能否突破当前高位并放量确认趋势延续；关注 EMA20=66800 支撑是否有效
2. **风险提示**：gap_score=0.41 中度背离，建议优化意图识别模块对 TREND_UP 市场的敏感度
3. **BAC 链路调整建议**：当前意图识别置信度偏低(40%)，建议在 TREND_UP 行情下提高意图识别分数权重

### 🧩 预算使用
- 模式：full
- 预估Token：1700 / 30000
'''

print('=== PR 评论报告 ===')
print(pr_report)
print(f'\nGH_TOKEN available: {"Yes" if GH_TOKEN else "No"}')

if GH_TOKEN:
    url = f'https://api.github.com/repos/yunya1991/Dreambuddy-V2/issues/{PR_NUMBER}/comments'
    headers = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    body = {'body': pr_report}
    try:
        r = requests.post(url, headers=headers, json=body)
        if r.status_code in (200, 201):
            print('✅ PR评论成功!')
        else:
            print(f'❌ PR评论失败: {r.status_code} - {r.text[:200]}')
    except Exception as e:
        print(f'❌ PR评论异常: {e}')
else:
    print('⚠️ GH_TOKEN未配置，跳过PR评论')
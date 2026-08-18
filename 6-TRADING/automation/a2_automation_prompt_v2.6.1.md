# A2第一性原理分析自动化提示词 v2.6.1

> **用途**: 加入自动化流程，自动执行A2分析并同步小白版到展示页面
> **目标URL**: `http://8.209.238.108/market-research` (已硬编码在A2 SKILL)
> **避免重复**: 内容哈希检查 + 投递验证

---

## 完整自动化提示词（可直接复制）

```
# A2第一性原理分析 - 自动执行流程

## 执行步骤

### 1. 读取A2 SKILL并加载上下文
- 读取 `~/.workbuddy/skills/dream-first-principles/SKILL.md`
- 读取 `artifact-alignment-manager` SKILL (§十一 URL投递验证)
- 确认目标URL: `http://8.209.238.108/market-research` (已硬编码，无需手动指定)

### 2. Phase 0: A0矛盾论强制调用 (P0门禁)
```python
# 必须首先执行
use_skill("dream-contradiction-theory")

# 门禁检查
assert a0_framework is not None, "❌ A0未调用，禁止继续"
```

### 3. Phase 1-7: A2分析执行 (50min)
按A2 SKILL §执行流程完成：
- Phase 1: 基本面分析 (5min)
- Phase 2: 技术面分析 (5min)
- Phase 3: 左右脑辩证 + A0抓住矛盾 (5min)
- Phase 4: 阻力分析 (5min)
- Phase 5: 趋势追踪 - MA轨迹法 (5min)
- Phase 6: 综合推演 (3min)
- Phase 7: Regime分类 (2min)

**输出**: 
- 专业版: `reports/trading/a2_first_principles_{YYYYMMDD}_{HHMM}.md`
- 小白版: `reports/trading/a2_first_principles_{YYYYMMDD}_{HHMM}_小白版.md`

### 4. Phase 8: 顾问评审 (10min)
```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / ".workbuddy" / "advisor-team" / "shared"))
from advisor_direct_call import advisors_review

result = advisors_review(
    consultation_id=f"A2-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    scene="MACRO_ANALYSIS",
    required_advisors=["advisor-mr", "advisor-tr"],
    context={
        "least_resistance_path": "<从分析中提取>",
        "trend_analysis": {"direction": "<UP/DOWN/NEUTRAL>"},
        "market_regime": "<TREND/RANGE/BREAKOUT>",
        "key_findings": [<核心发现列表>]
    },
    source="dream-first-principles"
)

verdict = result["summary"]["final_verdict"]
assert verdict in ["AGREE", "PARTIAL"], f"❌ 顾问评审未通过: {verdict}"
```

### 5. 双通道投递 (P0强制)
```bash
# 通道1: 秘书邮箱
cp reports/trading/a2_first_principles_*.md ~/.workbuddy/skills/boss-secretary/reports/trading/
cp reports/trading/a2_first_principles_*_小白版.md ~/.workbuddy/skills/boss-secretary/reports/trading/

# 通道2: 前端产物中心
mkdir -p ~/.workbuddy/artifacts/trading/
cp reports/trading/a2_first_principles_*.md ~/.workbuddy/artifacts/trading/
cp reports/trading/a2_first_principles_*_小白版.md ~/.workbuddy/artifacts/trading/

# 通道3: 更新index.json
python3 ~/.workbuddy/scripts/sync_artifact.py --source reports/trading/a2_first_principles_*.md
python3 ~/.workbuddy/scripts/sync_artifact.py --source reports/trading/a2_first_principles_*_小白版.md
```

### 6. 同步到展示页面 (🔴 新增 - 必须执行)
```python
import requests
import hashlib
from pathlib import Path

# 配置 (已硬编码在A2 SKILL，此处仅示例)
API_BASE = "http://8.209.238.108"
API_KEY = "8F_yf4C57w13-HaF3Wlw40uRYcica4Tfn-c93EocnLo"
TARGET_URL = "http://8.209.238.108/market-research"

# 1. 读取小白版内容
xiaobai_file = sorted(Path("reports/trading").glob("a2_first_principles_*_小白版.md"))[-1]
with open(xiaobai_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 2. 去重检查 (避免重复投递)
content_hash = hashlib.md5(content.encode()).hexdigest()
headers = {"X-API-Key": API_KEY}
r = requests.get(f"{API_BASE}/api/v1/admin/reports", headers=headers)
if r.status_code == 200:
    existing_reports = r.json()
    for report in existing_reports:
        if report.get('content_hash') == content_hash:
            print(f"⚠️ 内容已存在，跳过投递 (ID: {report['id']})")
            exit(0)

# 3. 推送小白版到展示页面
payload = {
    "title": f"A2第一性原理分析 {datetime.now().strftime('%Y-%m-%d')}",
    "content": content,
    "category": "market-analysis",
    "tags": ["BTC", "A2", "第一性原理", datetime.now().strftime('%Y-%m-%d')],
    "content_hash": content_hash
}

r = requests.post(f"{API_BASE}/api/v1/admin/reports", 
                  json=payload, 
                  headers={**headers, "Content-Type": "application/json"})

# 4. 验证投递结果
if r.status_code == 201:
    report_id = r.json().get('id')
    print(f"✅ 投递成功 (ID: {report_id})")
    
    # 验证前端页面
    r2 = requests.get(TARGET_URL)
    if "A2第一性原理" in r2.text:
        print(f"✅ 前端页面已更新: {TARGET_URL}")
    else:
        print(f"⚠️ 前端页面未更新，但API已成功")
else:
    print(f"❌ 投递失败: HTTP {r.status_code}")
    print(f"响应: {r.text}")
    
    # 写入待修复目录
    alert = f"""
❌ A2小白版投递失败

报告标题: {payload['title']}
目标URL: {TARGET_URL}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
HTTP状态码: {r.status_code}

建议操作:
1. 检查API服务是否可用: curl http://8.209.238.108/api/v1/health
2. 检查API Key是否有效
3. 手动推送: python3 scripts/push_reports_to_api.py --days 1
4. 查看AAM SKILL §十一 排查问题
"""
    with open(Path.home() / ".workbuddy" / "skills" / "boss-secretary" / "pending_tasks" / "inbox" / "a2_delivery_failed.md", 'w') as f:
        f.write(alert)
    print(f"❌ 告警: 已写入待修复目录")
    exit(1)
```

### 7. 投递后验证 (P0强制)
```bash
# 验证双通道
ls ~/.workbuddy/skills/boss-secretary/reports/trading/a2_first_principles_*.md || echo "❌ 秘书邮箱缺失"
ls ~/.workbuddy/artifacts/trading/a2_first_principles_*.md || echo "❌ 前端产物缺失"

# 验证前端页面
curl -s http://localhost:3456/feed/trading/a2_first_principles_*.md | grep -q "title" && echo "✅ 前端可见" || echo "❌ 前端不可见"

# 验证展示页面
curl -s http://8.209.238.108/market-research | grep -q "A2第一性原理" && echo "✅ 展示页面已更新" || echo "❌ 展示页面未更新"
```

### 8. 输出执行摘要
```markdown
## A2分析执行完成

**分析结论**: 
- 阻力最小路径: <UP/DOWN/NEUTRAL> (<置信度>%)
- 趋势方向: <UP/DOWN/NEUTRAL> (<置信度>%)
- Regime分类: <TREND/RANGE/BREAKOUT>

**顾问评审**: <AGREE/PARTIAL/DISAGREE> (置信度: <X>%)

**投递状态**:
- ✅ 秘书邮箱: 成功
- ✅ 前端产物中心: 成功
- ✅ 展示页面: 成功 (http://8.209.238.108/market-research)
- ✅ index.json: 已更新

**下次执行**: <YYYY-MM-DD HH:MM CST>
```

---

## 自动化调度配置

### 方式1: WorkBuddy自动化
```json
{
  "name": "A2第一性原理分析 - 每日01:30",
  "schedule": "cron:30 1 * * *",
  "timezone": "Asia/Shanghai",
  "prompt": "<上方完整提示词>",
  "enabled": true
}
```

### 方式2: 手动触发
在WorkBuddy中输入:
```
执行A2第一性原理分析，自动同步小白版到展示页面
```

---

## 避免重复投递的机制

| 机制 | 实现方式 | 作用 |
|:-----|:---------|:-----|
| **内容哈希** | `hashlib.md5(content.encode()).hexdigest()` | 检测完全相同的内容 |
| **标题+日期检查** | 检查 `{标题}_{日期}` 是否已存在 | 防止同一天重复投递 |
| **API响应检查** | 检查HTTP 409 Conflict | API层面防止重复 |
| **投递前验证** | 先检查URL是否已包含该内容 | 最后一道防线 |

---

## 故障排查

| 问题 | 排查步骤 | 解决方案 |
|:-----|:---------|:-----|
| 展示页面未更新 | 1. `curl http://8.209.238.108/api/v1/health`<br>2. 检查API Key<br>3. 查看AAM SKILL §十一 | 重启API服务 / 更新API Key |
| 重复投递 | 1. 检查内容哈希<br>2. 查看 `content_hash` 字段<br>3. 手动删除重复内容 | 清理重复内容 / 修复哈希检查逻辑 |
| 小白版格式错误 | 1. 检查小白版模板<br>2. 验证Markdown格式<br>3. 查看A2 SKILL §小白版模板 | 重新生成小白版 / 修复模板 |

---

## 关键配置 (已硬编码，无需修改)

| 配置项 | 值 | 位置 |
|:-----|:---|:-----|
| **目标URL** | `http://8.209.238.108/market-research` | A2 SKILL §研报API推送规范 |
| **API地址** | `http://8.209.238.108/api/v1/admin/reports` | A2 SKILL §API配置 |
| **API Key** | `8F_yf4C57w13-HaF3Wlw40uRYcica4Tfn-c93EocnLo` | A2 SKILL §API配置 |
| **检查逻辑** | §十一 URL投递验证 | AAM SKILL §十一 |

---

**使用说明**: 
1. 复制上方"完整自动化提示词"到WorkBuddy自动化配置
2. 调度时间建议: 每日 01:30 (A1完成后1.5小时)
3. 首次执行建议手动触发，验证流程正确性
4. 后续自动执行，异常会自动写入待修复目录

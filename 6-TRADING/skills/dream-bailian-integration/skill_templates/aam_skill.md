# Artifact Alignment Manager (AAM) SKILL

**版本**: v2.0
**日期**: 2026-05-07
**触发词**: 产物投递验证、双通道投递、frontmatter检查、index.json更新

---

## 定位

**AAM** 是 Dream-MultiSkill 系统的产物对齐管理器，负责：
1. 标准化产物 frontmatter 格式
2. 双通道投递 (秘书邮箱 + 前端产物中心)
3. index.json 索引管理
4. 投递验证与审计

---

## 核心功能

### §一、双通道投递

#### 1.1 标准投递流程
```
[1] 产物生成 → [2] frontmatter添加 → [3] 双通道写入 → [4] index.json更新 → [5] curl验证 → [6] 日志记录
```

#### 1.2 通道定义
| 通道 | 路径 | 说明 |
|:---|:---|:---|
| 秘书邮箱 | `~/.workbuddy/skills/boss-secretary/reports/{dept}/` | 邮件投递 |
| 前端产物中心 | `~/.workbuddy/artifacts/{dept}/` | Web展示 |

#### 1.3 frontmatter 规范 (7+1 字段)

| 字段 | 必填 | 格式 | 说明 |
|:---|:---:|:---|:---|
| `title` | ✅ | 字符串 | 产物标题，格式: "内容 YYYY-MM-DD" |
| `department` | ✅ | enum | trading/governance/hr/knowledge/support/cfo |
| `chain_phase` | ✅ | A1-A9 | A系列决策链阶段 |
| `date` | ✅ | ISO8601 | "YYYY-MM-DDTHH:MM:SS+08:00" |
| `type` | ✅ | enum | report/analysis/decision/skill/artifact |
| `status` | ✅ | enum | draft/review/completed/archived |
| `tags` | ✅ | 字符串 | 空格分隔的标签 |
| `by_a_phase` | ✅ | A1-A9 | 生成来源 |

#### 1.4 frontmatter 模板
```yaml
---
title: "产物标题 YYYY-MM-DD"
department: trading
chain_phase: A4
date: "2026-05-07T10:00:00+08:00"
type: report
status: completed
tags: "a4 tactical-validation trading"
by_a_phase: A4
---
```

---

### §二、投递执行

#### 2.1 投递代码模板
```python
import os
import json
import shutil
from datetime import datetime

ARTIFACT_TEMPLATE = """---
title: "{title}"
department: {department}
chain_phase: {chain_phase}
date: "{date}"
type: {type}
status: {status}
tags: "{tags}"
by_a_phase: {by_a_phase}
---

{content}
"""

class AAMDeliverer:
    def __init__(self):
        self.secretary_base = os.path.expanduser(
            "~/.workbuddy/skills/boss-secretary/reports"
        )
        self.hub_base = os.path.expanduser(
            "~/.workbuddy/artifacts"
        )

    def deliver(self, artifact_name, content, config):
        """
        双通道产物投递

        Args:
            artifact_name: 产物文件名 (不含时间戳)
            content: 产物内容 (Markdown)
            config: 配置字典
                - title: 产物标题
                - department: 部门
                - chain_phase: A系列阶段
                - type: 产物类型
                - tags: 标签 (空格分隔)
                - by_a_phase: 生成来源

        Returns:
            dict: 投递结果
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{artifact_name}_{timestamp}"

        # 1. 生成 frontmatter
        md_content = ARTIFACT_TEMPLATE.format(
            title=config['title'],
            department=config['department'],
            chain_phase=config['chain_phase'],
            date=datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            type=config['type'],
            status=config.get('status', 'completed'),
            tags=config['tags'],
            by_a_phase=config['by_a_phase'],
            content=content
        )

        # 2. 双通道写入
        secretary_path = os.path.join(
            self.secretary_base,
            config['department'],
            f"{filename}.md"
        )
        hub_path = os.path.join(
            self.hub_base,
            config['department'],
            f"{filename}.md"
        )

        os.makedirs(os.path.dirname(secretary_path), exist_ok=True)
        os.makedirs(os.path.dirname(hub_path), exist_ok=True)

        with open(secretary_path, 'w') as f:
            f.write(md_content)

        with open(hub_path, 'w') as f:
            f.write(md_content)

        # 3. 生成 JSON 摘要
        json_content = {
            "id": filename,
            "title": config['title'],
            "department": config['department'],
            "chain_phase": config['chain_phase'],
            "date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "type": config['type'],
            "status": config.get('status', 'completed'),
            "tags": config['tags'].split(),
            "by_a_phase": config['by_a_phase'],
            "filename": f"{filename}.md",
            "paths": {
                "secretary": secretary_path,
                "hub": hub_path
            }
        }

        json_path = os.path.join(
            self.hub_base,
            config['department'],
            f"{filename}.json"
        )
        with open(json_path, 'w') as f:
            json.dump(json_content, f, indent=2, ensure_ascii=False)

        # 4. 更新 index.json
        self._update_index(config['department'], json_content)

        # 5. 验证
        verified = self._verify(config['department'], filename)

        return {
            "status": "success" if verified else "warning",
            "filename": filename,
            "paths": {
                "secretary": secretary_path,
                "hub": hub_path,
                "json": json_path
            },
            "verified": verified
        }

    def _update_index(self, department, artifact_meta):
        """更新 index.json"""
        index_path = os.path.join(
            self.hub_base,
            department,
            "index.json"
        )

        if os.path.exists(index_path):
            with open(index_path, 'r') as f:
                index = json.load(f)
        else:
            index = {"department": department, "artifacts": []}

        index["artifacts"].append(artifact_meta)
        index["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _verify(self, department, filename):
        """验证投递"""
        hub_path = os.path.join(
            self.hub_base,
            department,
            f"{filename}.md"
        )

        if not os.path.exists(hub_path):
            return False

        # 验证 frontmatter
        with open(hub_path, 'r') as f:
            content = f.read()

        required_fields = [
            "title:", "department:", "chain_phase:",
            "date:", "type:", "status:", "tags:", "by_a_phase:"
        ]

        for field in required_fields:
            if field not in content:
                print(f"⚠️ Missing field: {field}")
                return False

        return True
```

#### 2.2 使用示例
```python
# 初始化 AAM
aam = AAMDeliverer()

# 配置
config = {
    "title": "A4 战术验证报告",
    "department": "trading",
    "chain_phase": "A4",
    "type": "report",
    "tags": "a4 tactical-validation trading",
    "by_a_phase": "A4"
}

# 投递
result = aam.deliver(
    artifact_name="a4_verification_report",
    content="# 战术验证报告\n\n...",
    config=config
)

print(f"投递状态: {result['status']}")
print(f"文件路径: {result['paths']['hub']}")
```

---

### §三、验证规范

#### 3.1 验证检查清单
- [ ] `.md` 文件写入秘书邮箱
- [ ] `.md` 文件写入前端产物中心
- [ ] `.json` 摘要文件写入
- [ ] `index.json` 已更新
- [ ] frontmatter 完整 (8字段)
- [ ] frontmatter 格式正确
- [ ] curl 验证返回 200

#### 3.2 curl 验证命令
```bash
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:3456/feed/{department}/{filename}
# 期望返回: 200
```

#### 3.3 验证失败处理
| 失败项 | 处理方式 |
|:---|:---|
| 通道1写入失败 | 检查目录权限 |
| 通道2写入失败 | 检查磁盘空间 |
| index.json更新失败 | 手动执行修复脚本 |
| curl验证失败 | 检查前端服务状态 |
| frontmatter不完整 | 重新生成并覆盖 |

---

### §四、修复流程

#### 4.1 修复脚本
```python
def fix_delivery(department, filename):
    """修复投递问题"""
    hub_path = f"~/.workbuddy/artifacts/{department}/{filename}.md"

    if not os.path.exists(hub_path):
        print(f"❌ 文件不存在: {hub_path}")
        return False

    # 读取内容
    with open(os.path.expanduser(hub_path), 'r') as f:
        content = f.read()

    # 检查 frontmatter
    lines = content.split('\n')
    frontmatter_end = 0
    for i, line in enumerate(lines):
        if line.strip() == '---' and i > 0:
            frontmatter_end = i
            break

    if frontmatter_end == 0:
        print("❌ 未找到 frontmatter")
        return False

    # 验证字段
    frontmatter = '\n'.join(lines[:frontmatter_end+1])
    required = ["title:", "department:", "chain_phase:",
                "date:", "type:", "status:", "tags:", "by_a_phase:"]

    missing = [f for f in required if f not in frontmatter]

    if missing:
        print(f"❌ 缺少字段: {missing}")
        # 自动补充缺失字段
        # ...

    # 重新验证
    return verify_delivery(department, filename)
```

---

### §五、日志规范

#### 5.1 投递日志格式
```json
{
  "timestamp": "2026-05-07T10:00:00+08:00",
  "level": "INFO",
  "action": "aam_deliver",
  "department": "trading",
  "filename": "a4_verification_20260507_100000",
  "status": "success",
  "verified": true,
  "paths": {
    "secretary": "...",
    "hub": "..."
  }
}
```

#### 5.2 日志存储
- 路径: `~/.workbuddy/skills/dream-bailian-integration/logs/aam_*.jsonl`
- 保留: 30天

---

## 版本历史

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v2.0 | 2026-05-07 | 增加完整投递代码模板和验证规范 |
| v1.0 | 2026-04-15 | 初始版本 |

---

*本文档是 AAM SKILL 的标准化规范，所有产物投递必须遵循此规范。*

# FAQ 常见问题

> **版本**: v2.0
> **更新日期**: 2026-05-14

---

## 📋 目录

1. [系统使用](#系统使用)
2. [交易相关](#交易相关)
3. [SKILL管理](#skill管理)
4. [部署运维](#部署运维)
5. [故障排查](#故障排查)

---

## 系统使用

### Q1: 如何登录Dream Universal Gateway？

**A**: 
1. 访问 `http://localhost:3456`
2. 点击"登录"按钮
3. 输入邮箱和密码
4. 完成邮箱验证
5. 获取JWT Token

**首次登录配置**:
```bash
# 1. 配置OKX API
# 设置 → API配置 → 添加API Key

# 2. 设置交易参数
# 设置 → 交易参数 → 选择账户(dreamdemo/A5)

# 3. 开启积分
# 设置 → 积分系统 → 购买积分档位
```

---

### Q2: 积分如何计算？

**A**: 积分按任务执行时间消耗：

| 任务类型 | 积分消耗 | 示例 |
|----------|----------|------|
| 1小时任务 | 200积分 | A1深度调研(1h) |
| 4小时任务 | 80积分 | A4战术验证(4h) |
| 1天任务 | 120积分 | A6情报监控(1d) |
| 深度调研 | 150积分 | A1联网调研 |
| 情报监控 | 50积分 | A6实时监控 |

**积分档位**:
- L1: ¥9.9 = 1000积分
- L2: ¥29.9 = 5000积分
- L3: ¥99 = 20000积分
- L4: ¥268 = 60000积分

---

### Q3: 如何创建定时任务？

**A**: 使用 `dream-task-creator` SKILL：

```
触发词: "创建定时任务"、"创建自动化"
```

**示例命令**:
```
"每天上午9点执行A1深度调研"
"每4小时检查一次持仓状态"
"每周一生成交易周报"
```

---

## 交易相关

### Q4: 模拟盘和实盘如何切换？

**A**: 

**切换方式**:
1. 前端: 设置 → 交易参数 → 账户选择
2. CLI: `okx account positions --profile dreamdemo` (模拟)
3. CLI: `okx account positions --profile real` (实盘)

**风险提示**:
> ⚠️ **警告**: 实盘交易涉及真实资金，请确保充分理解风险后再切换！

---

### Q5: 支持哪些交易所？

**A**: 

| 交易所 | 状态 | 支持产品 |
|--------|------|----------|
| OKX | ✅ 已实现 | 现货/合约/期权 |
| Binance | 🔄 开发中 | 合约 |
| Huobi | 🔄 开发中 | 合约 |

---

### Q6: 如何设置止损止盈？

**A**: 

**方式1: 前端设置**
```
设置 → 交易参数 → 止损/止盈
→ 止损: 2.0% (示例)
→ 止盈: 5.0% (示例)
```

**方式2: CLI设置**
```bash
# BTC-USDT-SWAP 止损止盈
okx trade tpsl BTC-USDT-SWAP \
  --slTriggerPx 79500 \    # 止损触发价
  --slOrdPx -1 \            # 市价止损
  --tpTriggerPx 82000 \     # 止盈触发价
  --tpOrdPx -1              # 市价止盈
```

---

### Q7: A0-A9流程是什么？

**A**: 完整的交易决策流水线：

```
用户输入 → A0矛盾识别 → A1深度调研 → A2第一性原理
    → A3沙盘推演 → A4战术验证 → A5决策执行
    → A6情报监控 → A7实践门禁 → A8知行验证 → A9离场
```

**各阶段说明**:

| 阶段 | 名称 | SKILL | 输出 |
|------|------|-------|------|
| A0 | 矛盾分析 | dream-contradiction-theory | 市场矛盾清单 |
| A1 | 深度调研 | dream-strategy-research | 市场调研报告 |
| A2 | 第一性原理 | dream-first-principles | 阻力分析报告 |
| A3 | 沙盘推演 | master-seminar | 大师评审意见 |
| A4 | 战术验证 | dream-tactical-validator | 验证报告 |
| A5 | 决策执行 | dream-tactical-executor | 执行结果 |
| A6 | 情报监控 | dream-intelligence-monitor | 实时告警 |
| A7 | 实践论门禁 | A7-practice-theory | PASS/SKIP |
| A8 | 理论实践验证 | A8-theory-practice-verification | 改进提案 |
| A9 | 离场决策 | dream-exit-skill-v2 | 离场执行 |

---

## SKILL管理

### Q8: 什么是SKILL？

**A**: SKILL是Dream-MultiSkill系统的能力模块，包含：

```yaml
SKILL结构:
├── SKILL.md          # SKILL定义(必需)
├── references/       # 参考资料(可选)
├── scripts/          # 执行脚本(可选)
├── assets/           # 静态资源(可选)
└── tests/           # 测试用例(可选)
```

---

### Q9: 如何安装新SKILL？

**A**: 

**方式1: 自动安装**
```
触发词: "安装XX技能的"
→ 自动搜索 → 审核 → 安装
```

**方式2: 手动安装**
```bash
# 1. 查找SKILL
→ 使用 skill-creator 或 find-skills

# 2. 安全审核
→ 加载 skills-security-check
→ 审核 SKILL.md 和所有文件

# 3. 安装
→ 复制到 ~/.workbuddy/skills/
```

---

### Q10: 如何创建自定义SKILL？

**A**: 使用 `skill-creator` SKILL：

**触发词**:
```
"创建一个新的SKILL"
"我想添加XX功能"
```

**创建步骤**:
1. 定义SKILL.md (核心配置)
2. 编写references/ (参考资料)
3. 编写scripts/ (执行脚本)
4. 编写tests/ (测试用例)
5. 提交审核

---

## 部署运维

### Q11: 如何部署Dream Universal Gateway？

**A**: 

**开发环境**:
```bash
cd 3-FRONTEND/dream-universal-gateway
pnpm install
pnpm dev
# 访问 http://localhost:3456
```

**生产环境 (Docker)**:
```bash
# 构建镜像
docker build -t dream-gateway:latest .

# 运行容器
docker run -d -p 3456:3000 \
  -e DATABASE_URL="postgresql://..." \
  -e NEXTAUTH_SECRET="..." \
  dream-gateway:latest
```

---

### Q12: 如何配置数据库？

**A**: 

**Prisma配置**:
```bash
# 1. 编辑 .env
DATABASE_URL="postgresql://user:pass@localhost:5432/dream_gateway"

# 2. 运行迁移
npx prisma migrate deploy

# 3. 生成客户端
npx prisma generate
```

**支持的数据库**:
- PostgreSQL ✅ (推荐)
- MySQL 🔄 开发中
- SQLite 🔄 开发中

---

### Q13: 如何更新系统？

**A**: 

**自动更新**:
```
→ 使用 auto-updater SKILL
→ 每天自动检查更新
→ 自动下载并应用
```

**手动更新**:
```bash
# 1. 拉取最新代码
git pull

# 2. 更新依赖
pnpm update

# 3. 重启服务
pm2 restart dream-gateway
```

---

## 故障排查

### Q14: 产物不显示怎么办？

**A**: 

**排查步骤**:
```
1. 检查产物是否创建
   → ls ~/.workbuddy/artifacts/{category}/

2. 检查index.json是否更新
   → cat ~/.workbuddy/artifacts/{category}/index.json

3. 手动同步
   → python scripts/sync_artifact.py

4. 清除缓存
   → 重启服务
```

---

### Q15: API调用失败怎么办？

**A**: 

**常见错误**:

| 错误码 | 描述 | 解决方案 |
|--------|------|----------|
| 401 | 未授权 | 检查API Key |
| 403 | 权限不足 | 检查账户权限 |
| 429 | 请求过多 | 降低频率 |
| 500 | 服务器错误 | 重试/联系支持 |

**排查命令**:
```bash
# 测试OKX连接
okx market ticker BTC-USDT-SWAP

# 测试Bailian连接
curl -X POST http://localhost:8080/api/health
```

---

### Q16: 记忆丢失怎么办？

**A**: 

**原因**:
- 记忆文件被删除
- 内存清理触发
- 系统重启

**恢复方案**:
```
1. 检查记忆文件
   → ls ~/.workbuddy/memory/

2. 使用记忆蒸馏
   → 调用 memory-distiller
   → 从日志重建记忆

3. 从产物恢复
   → 查看 A系列报告
   → 重建决策上下文
```

---

## 📞 技术支持

如遇问题，请联系：

- **文档**: [工作索引](../工作索引/README.md)
- **Slack**: #dream-support
- **邮件**: support@dream-multiskill.ai

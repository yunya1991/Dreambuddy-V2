# 沙箱测试环境（SkillHub 付费 Skill）

> 版本：v0.1　日期：2026-11-20
> 方案：[PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md](../PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md)
> 基线：[BASELINE-20261120.md](./BASELINE-20261120.md)

## 1. 目的

在本地复刻 `services/skillhub-audit-api` 的付费协议与返回结构，对三个已上线 Skill 做**可重复、可断言**的回归：

- 402 挑战 → 凭证重试 → 200 交付 → 幂等重放
- 断网 / 超时 / 502 / 非 JSON / 参数错误
- 认知管家指标契约与「缺测不参与评分」口径

**本轮只建环境，不改任何 Skill 代码。**

## 2. 目录

```
sandbox/
├── mock/paid_api.py          # 复刻 app.js：402/Payment-Needed/验付/200/400/413/502/断连/延迟
├── fixtures/                 # 返回结构样本（可替换为云端脱敏真实样本）
├── cases/cases.json          # 16 条场景与期望
├── run_cases.py              # 起 mock → 跑脚本 → 断言 → 汇总
├── workspace_fixture/        # 认知管家采集样本（断链/越界/重名/无文档代码）
└── BASELINE-20261120.md      # 优化前基线
```

## 3. 运行

```bash
cd 59-通用组件管理

# 全量
python3 sandbox/run_cases.py

# 单组 + 打印输出与请求体
python3 sandbox/run_cases.py --only mdp- --verbose

# 更新基线报告
python3 sandbox/run_cases.py --report sandbox/BASELINE-$(date +%Y%m%d).md
```

退出码：全部通过为 0，存在失败为 1。

## 4. 场景一览

| 组 | 场景 | 关注点 |
|---|---|---|
| mdp | `mdp-first-402` / `mdp-proof-ok` / `mdp-replay` | 付费闭环与幂等 |
| mdp | `mdp-proof-invalid` / `mdp-502` | 凭证失效、履约确认失败的重试指引 |
| mdp | `mdp-offline` / `mdp-timeout` / `mdp-html` | 断网、超时、非 JSON 的异常映射 |
| mdp | `mdp-missing-param` / `mdp-typo-param` | 本地参数校验，零请求 |
| ecp | `ecp-latest` / `ecp-events-ok` | 布尔开关真实进入请求体 |
| cs | `cs-valid-report` / `cs-unknown-key` / `cs-missing-metrics` / `cs-workspace-fixture` | 指标校验与 unavailable 口径 |

## 5. 基线结论（2026-11-20）

6 / 16 通过，10 条失败，与评测报告一致：

- 断网、非 JSON → Python traceback；
- 同一凭证重放无「幂等」提示；
- `--timeout` 被静默忽略；缺参/拼错参数仍会发出请求；
- `--latest` 未进入请求体（`params.latest=None`）；
- 认知管家未知指标静默忽略、缺测指标没有 `unavailable` 标记。

## 6. 用真实样本替换 fixtures

1. 在云端 `49.233.123.96` 只读查询订单表 `service_result`（按 `resource_id` 分组取一条）；
2. 脱敏（去掉真实 `out_trade_no`、凭证、用户标识），保留字段结构；
3. 覆盖 `fixtures/` 同名文件，重跑 `run_cases.py` 确认断言仍成立。

## 7. 约束

- 不连接生产端点：所有场景通过 `MDP_ENDPOINT` / `ECP_ENDPOINT` / `COGSTEWARD_ENDPOINT` 指向本地；
- 不改 Skill 包，不引入第三方依赖（仅标准库）；
- mock 的 402 报文与 `Payment-Needed` 结构以 `services/skillhub-audit-api` 为准，服务端变更时同步更新。

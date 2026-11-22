# 工程索引 — 手机预约助手（mobile-reservation-assist）

## 目录

```
mobile-reservation-assist/
├── component.yaml
├── docs/                      ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG
├── skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── mra.py             CLI 入口（含 reconcile 对账）
│   │   ├── ingest.py          上游命中归一 + 入队
│   │   ├── store.py           SQLite（jobs/results/events）+ 状态迁移守卫 + 对账
│   │   ├── gateway.py         本地 HTTP 指令网关
│   │   ├── executor.py        作业→指令 + 门禁 + 结构化回执落库
│   │   ├── knowledge.py       千问知识工具 knowledge.ask（引用/置信度/缓存）
│   │   ├── explore.py         探索录制 → 页面签名/断言 → 适配器草案
│   │   ├── locator.py         定位兜底：规则排序 + 本地小模型复核
│   │   ├── vision.py          视觉兜底：OCR 块排序（置信度加权）
│   │   ├── regression.py      回归任务集：基线 + 录制批量比对
│   │   ├── twitter.py         X 网页端发布：Playwright 持久化登录 + 定时队列
│   │   ├── notify.py          通知通道
│   │   ├── security.py        redact / Token / 容器判定
│   │   ├── phone_tools/       L3 语义工具层（平台无关，含风险策略）
│   │   └── phone_adapters/    L4 平台业务编排（6 平台 + 千问）
│   └── references/            adapters.md / compliance.md / agent-flow-runbook.md
├── agent/
│   └── reservation_agent.js   Auto.js 手机端常驻 Agent（复用现有工程）
└── tests/                     contract/store/ingest/gateway/executor/architecture
                               + state_machine/receipt/phone_tools/reconcile/knowledge/explore/replay_gate/locator/vision/multidevice/regression/twitter
                               + golden/fixtures
```

## 关键契约

- 输出：`reservation.v1`（见 59域 contracts/output.schema.json）。
- 回执：`mra.receipt.v1`（`trace_id/stage/screenshot/page_text/order_id`）。
- 知识：`knowledge.v1`（`answer/citations/confidence/side_effect`，只读）。
- 探索：`explore.draft.v1`（`steps/assertions/warnings/ready`）、`explore.check.v1`（兼容门禁）。
- 定位：`locator.v1`（`best/candidates/source`，`guard` 表示支付红线拦截）。
- 视觉：`vision.v1`（OCR 块 → `best.block_index`，置信度加权）。
- 回归：`regression.v1`（用例逐一 pass/fail/error，含 `run_id` 落库）。
- 上游：只读消费 `reservation-assist` 的公开 CLI（`report --json` / `watch list --json`），不 import、不写死路径。
- 分层：L3 `phone_tools` 不含平台词；L4 `phone_adapters` 只能调用已登记工具。
- 治理：通过 59域 `make check`（G1–G7）。

## 常用命令

```bash
python3 skill/scripts/mra.py ingest --source file:tests/fixtures/feed_basic.json
python3 skill/scripts/mra.py gateway --port 8765
python3 skill/scripts/mra.py jobs --json
python3 skill/scripts/mra.py report --json
python3 skill/scripts/mra.py reconcile --json
python3 skill/scripts/mra.py reconcile --job 12 --state done --order-id B123
python3 skill/scripts/mra.py knowledge ask "会员购实名能改吗" --app bilibili --json
python3 skill/scripts/mra.py explore start --app bilibili --goal "买票" --device-id dev-1
python3 skill/scripts/mra.py explore draft --id 1 --json
python3 skill/scripts/mra.py explore baseline --id 1 --name bilibili
python3 skill/scripts/mra.py explore check --name bilibili --id 2 --json
python3 skill/scripts/mra.py devices --json
python3 skill/scripts/mra.py regression run --tag smoke --json
python3 skill/scripts/mra.py ingest --ra-cli /path/ra.py --device-id dev-1
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

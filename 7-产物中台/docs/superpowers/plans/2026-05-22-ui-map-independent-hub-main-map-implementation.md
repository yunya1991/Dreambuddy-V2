# UI-Map Independent Hub Main Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first shippable `ui-map` independent hub homepage in `7-产物中台/系统研究索引体系` by constructing the frontend shell first, then filling modules one by one with mandatory pressure testing, multi-scenario simulation, and architecture-drift review after each important chunk.

**Architecture:** Deliver `ui-map` in two phases. `Phase A` builds the independent frontend shell and stabilizes the layered page skeleton, scenario fixtures, and navigation without touching real backend integration. `Phase B` fills the shell module by module in the same order as the approved architecture diagram: source layer, unified mainline, dual index foundations, then perspective layer. Each module lands only after passing tests, scripted pressure checks, multi-scenario simulation, and design-drift review against the approved diagram.

**Phase B data contract:** Before wiring real backend data, read `7-产物中台/docs/superpowers/specs/2026-06-07-ui-map-real-data-integration-contract.md`. It defines the source-of-truth mapping, server adapter boundary, fixture fallback rule, and the rollout order for real data mode.

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, Tailwind utility classes, `node:test` via `tsx --test`, Playwright CLI for multi-scenario screenshots, Node scripts for repeated route checks

---

## Hard Validation Gate

Every important feature chunk in this plan MUST pass four gates before moving to the next task:

1. **Unit / route validation**
   - The targeted test or build check for the current chunk must pass.
2. **Pressure test**
   - Repeated route/model execution must stay stable under scripted repetition.
3. **Multi-scenario simulation**
   - At minimum validate `balanced`, `custom-heavy`, `system-heavy`, and `execution-heavy`.
4. **Architecture-drift review**
   - Compare delivered UI and semantics against the approved architecture diagram:
     - Preview URL: `http://127.0.0.1:62932/ui-map-independent-hub-architecture.html`
     - Source file: `/.superpowers/brainstorm/72144-1779428592/content/ui-map-independent-hub-architecture.html`

The architecture-drift review is mandatory. Every completed chunk must explicitly preserve:

- `ui-map` is an independent hub homepage, not the user frontend
- first layer is `自定义策略 / 系统策略`
- `自定义策略` internally carries `意图闭环 + AI 推理与推荐`
- both sources converge into `策略主线`
- `用户上下文索引系统` supports both strategy generation and each execution
- `系统研究索引体系` remains the platform capability foundation
- `系统研究链路 / 系统运营链路` stay as perspective layers

## Phase Strategy

### Phase A: Shell First

Only build the frontend shell first:

- dedicated `/ui-map` route
- scenario fixtures and shell view model
- layered shell layout matching the approved architecture diagram
- navigation entry and scenario switching

Do **not** connect real backend capability chains in this phase.

### Phase B: Module By Module

After the shell is stable, fill modules in this fixed order:

1. `自定义策略 / 系统策略` 来源层
2. `策略主线`
3. `用户上下文索引系统 / 系统研究索引体系`
4. `系统研究链路 / 系统运营链路`

Each module is treated as its own unit of delivery and validation.

## File Structure

### New Files

- `7-产物中台/系统研究索引体系/app/ui-map/page.tsx`
  - Route entry for the independent hub homepage.
- `7-产物中台/系统研究索引体系/app/ui-map/UIMapClient.tsx`
  - Client shell that renders the layered homepage and scenario switcher.
- `7-产物中台/系统研究索引体系/app/ui-map/UIMapShell.tsx`
  - Pure shell layout that places source, mainline, index foundation, and perspective sections into the approved visual structure.
- `7-产物中台/系统研究索引体系/app/ui-map/UIMapModuleCard.tsx`
  - Reusable block renderer for each module card.
- `7-产物中台/系统研究索引体系/app/ui-map/ui-map-scenarios.ts`
  - Typed scenario fixtures for shell and module rendering.
- `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`
  - Pure transformation from scenario data to shell-ready `UIMapShellViewModel`.
- `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.test.ts`
  - TDD coverage for shell semantics and scenario fallback behavior.
- `7-产物中台/系统研究索引体系/app/ui-map/page.test.ts`
  - Smoke test for the `/ui-map` route entry.
- `7-产物中台/系统研究索引体系/app/ui-map/navigation.test.ts`
  - Smoke test for `/` redirect and `Header` promotion.
- `7-产物中台/系统研究索引体系/scripts/ui-map-pressure-check.mjs`
  - Repeated fetch checker for `/ui-map` across all scenarios.

### Modified Files

- `7-产物中台/系统研究索引体系/app/page.tsx`
  - Promote `/ui-map` as the independent hub entry.
- `7-产物中台/系统研究索引体系/components/Header.tsx`
  - Add the `UI-Map` navigation item while preserving `feed / chain / org / meeting`.
- `7-产物中台/系统研究索引体系/app/globals.css`
  - Minimal shared helpers only if needed for shell-level layout.
- `7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`
  - Backfill delivered route and shell notes after implementation.

## Task 1: Build The Shell Scenario Model

**Files:**
- Create: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-scenarios.ts`
- Create: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`
- Test: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import test from "node:test";
import assert from "node:assert/strict";

import { getUIMapScenario } from "./ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "./ui-map-shell-view-model.ts";

test("shell view model keeps source layer first and mainline second", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"));

  assert.equal(viewModel.sourceLayer[0]?.title, "自定义策略");
  assert.equal(viewModel.sourceLayer[1]?.title, "系统策略");
  assert.equal(viewModel.mainlineLayer.title, "策略主线");
  assert.equal(viewModel.mainlineLayer.convergenceLabel, "通过交易设置实现策略收口");
});

test("shell view model keeps user context index as build-time and runtime foundation", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("execution-heavy"));

  assert.equal(viewModel.indexFoundation.userContext.title, "用户上下文索引系统");
  assert.equal(viewModel.indexFoundation.userContext.buildLabel, "支撑自定义策略生成");
  assert.equal(viewModel.indexFoundation.userContext.runtimeLabel, "支撑每次策略执行");
  assert.deepEqual(viewModel.indexFoundation.userContext.executionFrequencies, ["1h", "4h", "1d"]);
});

test("unknown scenario falls back to balanced shell data", () => {
  assert.equal(getUIMapScenario("missing").id, "balanced");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: FAIL with missing module errors.

- [ ] **Step 3: Write minimal scenario and shell view-model implementation**

```ts
// app/ui-map/ui-map-scenarios.ts
export type UIMapScenarioId = "balanced" | "custom-heavy" | "system-heavy" | "execution-heavy";

export interface UIMapScenario {
  id: UIMapScenarioId;
  label: string;
  customStrategyBullets: string[];
  systemStrategyBullets: string[];
  executionFrequencies: string[];
  systemCapabilityBullets: string[];
}

const SCENARIOS: Record<UIMapScenarioId, UIMapScenario> = {
  balanced: {
    id: "balanced",
    label: "平衡场景",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验", "传统联网金融经验"],
    systemStrategyBullets: ["feed 系统策略入口", "系统研究产物", "固定研究链路结果"],
    executionFrequencies: ["1h", "4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "系统策略支撑", "平台公共能力", "AI 推理优先参考路径"],
  },
  "custom-heavy": {
    id: "custom-heavy",
    label: "自定义策略主导",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验加强", "联网金融经验增强"],
    systemStrategyBullets: ["系统策略补充入口", "系统研究辅助"],
    executionFrequencies: ["1h", "4h"],
    systemCapabilityBullets: ["研究能力调用", "最优路径参考"],
  },
  "system-heavy": {
    id: "system-heavy",
    label: "系统策略主导",
    customStrategyBullets: ["意图闭环辅助", "AI 推荐辅助", "个人经验补充"],
    systemStrategyBullets: ["feed 主入口", "固定研究链路", "系统研究主导"],
    executionFrequencies: ["4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "系统策略支撑", "平台公共能力"],
  },
  "execution-heavy": {
    id: "execution-heavy",
    label: "执行频次主导",
    customStrategyBullets: ["意图闭环", "AI 推理与推荐", "个人经验", "联网金融经验"],
    systemStrategyBullets: ["系统策略入口", "系统研究产物"],
    executionFrequencies: ["1h", "4h", "1d"],
    systemCapabilityBullets: ["系统研究结果沉淀", "AI 推理路径", "系统策略支撑"],
  },
};

export function getUIMapScenario(id: string | undefined): UIMapScenario {
  if (!id || !(id in SCENARIOS)) return SCENARIOS.balanced;
  return SCENARIOS[id as UIMapScenarioId];
}
```

```ts
// app/ui-map/ui-map-shell-view-model.ts
import type { UIMapScenario } from "./ui-map-scenarios.ts";

export interface UIMapShellViewModel {
  hero: { title: string; subtitle: string };
  sourceLayer: Array<{ title: string; description: string; bullets: string[] }>;
  mainlineLayer: { title: string; convergenceLabel: string; chain: string };
  indexFoundation: {
    userContext: {
      title: string;
      description: string;
      buildLabel: string;
      runtimeLabel: string;
      executionFrequencies: string[];
    };
    systemResearch: {
      title: string;
      description: string;
      bullets: string[];
    };
  };
  perspectiveLayer: Array<{ title: string; description: string }>;
}

export function buildUIMapShellViewModel(scenario: UIMapScenario): UIMapShellViewModel {
  return {
    hero: {
      title: "UI-Map 独立中台首页",
      subtitle: `当前场景：${scenario.label}。先稳定前端壳，再按模块逐块落地。`,
    },
    sourceLayer: [
      {
        title: "自定义策略",
        description: "自定义策略是业务来源，不是单一机制。",
        bullets: scenario.customStrategyBullets,
      },
      {
        title: "系统策略",
        description: "系统策略承接系统研究产物、固定研究链路与 feed 入口。",
        bullets: scenario.systemStrategyBullets,
      },
    ],
    mainlineLayer: {
      title: "策略主线",
      convergenceLabel: "通过交易设置实现策略收口",
      chain: "策略设置成功 → 策略任务单 → 交易链条 → 交易执行 → 结果产物 → 索引",
    },
    indexFoundation: {
      userContext: {
        title: "用户上下文索引系统",
        description: "用户底座，既服务策略构建，也服务每次执行。",
        buildLabel: "支撑自定义策略生成",
        runtimeLabel: "支撑每次策略执行",
        executionFrequencies: scenario.executionFrequencies,
      },
      systemResearch: {
        title: "系统研究索引体系",
        description: "平台基础能力底座，持续为系统策略和 AI 推理供能。",
        bullets: scenario.systemCapabilityBullets,
      },
    },
    perspectiveLayer: [
      { title: "系统研究链路", description: "展示固定研究流程、系统策略形成过程和研究产物关系。" },
      { title: "系统运营链路", description: "展示前端进入、策略收口、上下文调用、执行和索引更新。" },
    ],
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: PASS with 3 passing tests.

- [ ] **Step 5: Run pressure test and multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --eval "import { getUIMapScenario } from './app/ui-map/ui-map-scenarios.ts'; import { buildUIMapShellViewModel } from './app/ui-map/ui-map-shell-view-model.ts'; const ids=['balanced','custom-heavy','system-heavy','execution-heavy']; for (let i=0;i<200;i++) { for (const id of ids) { const vm=buildUIMapShellViewModel(getUIMapScenario(id)); if (vm.mainlineLayer.title !== '策略主线') throw new Error('broken shell model'); } } console.log('ui-map shell scenario pressure ok');"
```

Expected:

```text
ui-map shell scenario pressure ok
```

- [ ] **Step 6: Run architecture-drift review against the approved diagram**

Check:

```text
1. 第一层仍是“自定义策略 / 系统策略”
2. 自定义策略内部仍保留“意图闭环 + AI 推理与推荐”的表达
3. 策略主线仍是统一收口层
4. 用户上下文索引仍同时覆盖构建期和执行期
5. 当前任务只搭模型，没有把任何内部机制误抬成首页一级模块
```

- [ ] **Step 7: Commit**

```bash
git add app/ui-map/ui-map-scenarios.ts app/ui-map/ui-map-shell-view-model.ts app/ui-map/ui-map-shell-view-model.test.ts
git commit -m "feat: add ui-map shell model"
```

## Task 2: Build The UI-Map Frontend Shell

**Files:**
- Create: `7-产物中台/系统研究索引体系/app/ui-map/UIMapModuleCard.tsx`
- Create: `7-产物中台/系统研究索引体系/app/ui-map/UIMapShell.tsx`
- Create: `7-产物中台/系统研究索引体系/app/ui-map/UIMapClient.tsx`
- Create: `7-产物中台/系统研究索引体系/app/ui-map/page.tsx`
- Test: `7-产物中台/系统研究索引体系/app/ui-map/page.test.ts`

- [ ] **Step 1: Write the failing route smoke test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("ui-map route entry renders the shell and uses the shell view model", () => {
  const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(source, /export default function UIMapPage/);
  assert.match(source, /buildUIMapShellViewModel/);
  assert.match(source, /UIMapClient/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/page.test.ts
```

Expected: FAIL because the route files do not yet exist.

- [ ] **Step 3: Write the minimal shell components and route**

```tsx
// app/ui-map/UIMapModuleCard.tsx
export default function UIMapModuleCard(props: {
  title: string;
  description: string;
  bullets?: string[];
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${props.className ?? ""}`}>
      <h3 className="text-lg font-semibold text-slate-900">{props.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{props.description}</p>
      {props.bullets?.length ? (
        <ul className="mt-3 space-y-2 text-sm text-slate-700">
          {props.bullets.map((bullet) => (
            <li key={bullet}>• {bullet}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
```

```tsx
// app/ui-map/UIMapShell.tsx
import type { UIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import UIMapModuleCard from "./UIMapModuleCard";

export default function UIMapShell(props: { viewModel: UIMapShellViewModel }) {
  const { hero, sourceLayer, mainlineLayer, indexFoundation, perspectiveLayer } = props.viewModel;

  return (
    <div className="space-y-8">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <span className="inline-flex rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-600">独立中台首页</span>
        <h1 className="mt-4 text-3xl font-bold text-slate-900">{hero.title}</h1>
        <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-600">{hero.subtitle}</p>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        {sourceLayer.map((item) => (
          <UIMapModuleCard key={item.title} title={item.title} description={item.description} bullets={item.bullets} />
        ))}
      </section>

      <section className="rounded-3xl border border-emerald-200 bg-emerald-50 p-8 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">统一主线层</p>
        <h2 className="mt-2 text-2xl font-bold text-slate-900">{mainlineLayer.title}</h2>
        <p className="mt-3 text-sm font-medium text-emerald-700">{mainlineLayer.convergenceLabel}</p>
        <p className="mt-4 text-sm leading-7 text-slate-700">{mainlineLayer.chain}</p>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <UIMapModuleCard
          title={indexFoundation.userContext.title}
          description={`${indexFoundation.userContext.description} 执行频率：${indexFoundation.userContext.executionFrequencies.join(" / ")}`}
          bullets={[indexFoundation.userContext.buildLabel, indexFoundation.userContext.runtimeLabel]}
        />
        <UIMapModuleCard
          title={indexFoundation.systemResearch.title}
          description={indexFoundation.systemResearch.description}
          bullets={indexFoundation.systemResearch.bullets}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        {perspectiveLayer.map((item) => (
          <UIMapModuleCard key={item.title} title={item.title} description={item.description} />
        ))}
      </section>
    </div>
  );
}
```

```tsx
// app/ui-map/UIMapClient.tsx
'use client';

import Link from "next/link";
import type { UIMapScenarioId } from "./ui-map-scenarios.ts";
import type { UIMapShellViewModel } from "./ui-map-shell-view-model.ts";
import UIMapShell from "./UIMapShell";

const SCENARIOS: Array<{ id: UIMapScenarioId; label: string }> = [
  { id: "balanced", label: "平衡场景" },
  { id: "custom-heavy", label: "自定义策略主导" },
  { id: "system-heavy", label: "系统策略主导" },
  { id: "execution-heavy", label: "执行频次主导" },
];

export default function UIMapClient(props: {
  scenarioId: UIMapScenarioId;
  viewModel: UIMapShellViewModel;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2" data-testid="ui-map-scenario-switcher">
        {SCENARIOS.map((scenario) => (
          <Link
            key={scenario.id}
            href={`/ui-map?scenario=${scenario.id}`}
            className={scenario.id === props.scenarioId ? "rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white" : "rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700"}
          >
            {scenario.label}
          </Link>
        ))}
      </div>
      <UIMapShell viewModel={props.viewModel} />
    </div>
  );
}
```

```tsx
// app/ui-map/page.tsx
import UIMapClient from "./UIMapClient";
import { getUIMapScenario, type UIMapScenarioId } from "./ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "./ui-map-shell-view-model.ts";

export const dynamic = "force-dynamic";

export default function UIMapPage({
  searchParams,
}: {
  searchParams?: { scenario?: string };
}) {
  const scenario = getUIMapScenario(searchParams?.scenario);
  const viewModel = buildUIMapShellViewModel(scenario);
  return <UIMapClient scenarioId={scenario.id as UIMapScenarioId} viewModel={viewModel} />;
}
```

- [ ] **Step 4: Run build to verify the shell route compiles**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm build
```

Expected: `/ui-map` route builds successfully.

- [ ] **Step 5: Run pressure test and multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm dev >/tmp/ui-map-shell.log 2>&1 &
DEV_PID=$!
sleep 6
for scenario in balanced custom-heavy system-heavy execution-heavy; do
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "策略主线" || exit 1
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "用户上下文索引系统" || exit 1
done
kill $DEV_PID
wait $DEV_PID 2>/dev/null || true
echo "ui-map shell scenario smoke ok"
```

Expected:

```text
ui-map shell scenario smoke ok
```

- [ ] **Step 6: Run architecture-drift review against the approved diagram**

Check:

```text
1. 首页已经具备来源层 → 统一主线层 → 索引底座层 → 透视层的壳结构
2. 第一层仍然是“自定义策略 / 系统策略”
3. 用户上下文索引系统没有被画成后置结果框
4. 系统研究索引体系仍然表达平台能力底座
5. 当前只是壳，不提前塞入真实后端逻辑
```

- [ ] **Step 7: Commit**

```bash
git add app/ui-map/UIMapModuleCard.tsx app/ui-map/UIMapShell.tsx app/ui-map/UIMapClient.tsx app/ui-map/page.tsx app/ui-map/page.test.ts
git commit -m "feat: add ui-map frontend shell"
```

## Task 3: Fill The Source Layer Module

**Files:**
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/UIMapShell.tsx`
- Test: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.test.ts`

- [ ] **Step 1: Write the failing test for richer source-layer semantics**

```ts
test("source layer keeps custom strategy as a composite source instead of a flat mechanism list", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"));
  const custom = viewModel.sourceLayer[0];

  assert.equal(custom.title, "自定义策略");
  assert.match(custom.description, /业务来源/);
  assert.ok(custom.bullets.includes("意图闭环"));
  assert.ok(custom.bullets.includes("AI 推理与推荐"));
});
```

- [ ] **Step 2: Run test to verify it fails for missing source-layer refinement**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: FAIL because the richer source-layer wording is not yet present.

- [ ] **Step 3: Write the minimal source-layer refinement**

```ts
// ui-map-shell-view-model.ts excerpt
sourceLayer: [
  {
    title: "自定义策略",
    description: "业务来源层：自定义策略由意图闭环、AI 推理与推荐、个人经验和传统联网金融经验共同形成。",
    bullets: scenario.customStrategyBullets,
  },
  {
    title: "系统策略",
    description: "业务来源层：系统策略承接系统研究产物、固定研究链路和 feed 入口。",
    bullets: scenario.systemStrategyBullets,
  },
],
```

```tsx
// UIMapShell.tsx excerpt
<section aria-label="source-layer" className="grid gap-6 lg:grid-cols-2">
  {sourceLayer.map((item) => (
    <UIMapModuleCard key={item.title} title={item.title} description={item.description} bullets={item.bullets} />
  ))}
</section>
```

- [ ] **Step 4: Run tests again**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run pressure test and multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm dev >/tmp/ui-map-source.log 2>&1 &
DEV_PID=$!
sleep 6
for scenario in balanced custom-heavy system-heavy execution-heavy; do
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "自定义策略" || exit 1
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "系统策略" || exit 1
done
kill $DEV_PID
wait $DEV_PID 2>/dev/null || true
echo "ui-map source layer pressure ok"
```

- [ ] **Step 6: Run architecture-drift review against the approved diagram**

Check:

```text
1. 第一层仍然是两类策略来源，不是内部机制入口
2. 自定义策略内部仍明确包含“意图闭环 + AI 推理与推荐”
3. 系统策略仍是独立来源，不是主线子项
```

- [ ] **Step 7: Commit**

```bash
git add app/ui-map/ui-map-shell-view-model.ts app/ui-map/UIMapShell.tsx app/ui-map/ui-map-shell-view-model.test.ts
git commit -m "feat: refine ui-map source layer"
```

## Task 4: Fill The Mainline And Dual Index Modules

**Files:**
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/UIMapShell.tsx`
- Test: `7-产物中台/系统研究索引体系/app/ui-map/ui-map-shell-view-model.test.ts`

- [ ] **Step 1: Write the failing test for mainline and dual-index semantics**

```ts
test("mainline and dual-index layers keep convergence and foundation semantics", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("execution-heavy"));

  assert.equal(viewModel.mainlineLayer.convergenceLabel, "通过交易设置实现策略收口");
  assert.match(viewModel.indexFoundation.systemResearch.description, /平台基础能力底座/);
  assert.match(viewModel.indexFoundation.userContext.description, /用户底座/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: FAIL because the wording and relationships are not yet explicit enough.

- [ ] **Step 3: Write the minimal mainline and index-layer refinement**

```ts
// ui-map-shell-view-model.ts excerpt
mainlineLayer: {
  title: "策略主线",
  convergenceLabel: "通过交易设置实现策略收口",
  chain: "策略设置成功 → 策略任务单 → 交易链条 → 交易执行 → 结果产物 → 索引",
},
indexFoundation: {
  userContext: {
    title: "用户上下文索引系统",
    description: "用户底座：既服务策略构建，也服务每次执行。",
    buildLabel: "支撑自定义策略生成",
    runtimeLabel: "支撑每次策略执行",
    executionFrequencies: scenario.executionFrequencies,
  },
  systemResearch: {
    title: "系统研究索引体系",
    description: "平台基础能力底座：持续为系统策略和 AI 推理供能。",
    bullets: scenario.systemCapabilityBullets,
  },
},
```

```tsx
// UIMapShell.tsx excerpt
<section aria-label="mainline-layer" className="rounded-3xl border border-emerald-200 bg-emerald-50 p-8 shadow-sm">
  ...
</section>

<section aria-label="index-foundation-layer" className="grid gap-6 lg:grid-cols-2">
  ...
</section>
```

- [ ] **Step 4: Run tests again**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/ui-map-shell-view-model.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run pressure test and multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm dev >/tmp/ui-map-mainline.log 2>&1 &
DEV_PID=$!
sleep 6
for scenario in balanced custom-heavy system-heavy execution-heavy; do
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "通过交易设置实现策略收口" || exit 1
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "用户上下文索引系统" || exit 1
  curl -s "http://127.0.0.1:3456/ui-map?scenario=${scenario}" | grep -q "系统研究索引体系" || exit 1
done
kill $DEV_PID
wait $DEV_PID 2>/dev/null || true
echo "ui-map mainline foundation pressure ok"
```

- [ ] **Step 6: Run architecture-drift review against the approved diagram**

Check:

```text
1. 策略主线仍位于来源层之后，保持统一收口层身份
2. 用户上下文索引仍同时指向构建期和执行期
3. 系统研究索引仍保持平台能力底座语义
4. 双索引没有被误做成单一“产物索引”
```

- [ ] **Step 7: Commit**

```bash
git add app/ui-map/ui-map-shell-view-model.ts app/ui-map/UIMapShell.tsx app/ui-map/ui-map-shell-view-model.test.ts
git commit -m "feat: refine ui-map mainline and foundations"
```

## Task 5: Fill The Perspective Layer And Promote UI-Map Entry

**Files:**
- Modify: `7-产物中台/系统研究索引体系/app/page.tsx`
- Modify: `7-产物中台/系统研究索引体系/components/Header.tsx`
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/UIMapShell.tsx`
- Modify: `7-产物中台/系统研究索引体系/app/globals.css`
- Test: `7-产物中台/系统研究索引体系/app/ui-map/navigation.test.ts`

- [ ] **Step 1: Write the failing navigation and perspective test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("ui-map is promoted as hub entry and keeps dual perspective layer", () => {
  const homeSource = readFileSync(new URL("../page.tsx", import.meta.url), "utf8");
  const headerSource = readFileSync(new URL("../../components/Header.tsx", import.meta.url), "utf8");
  const shellSource = readFileSync(new URL("./UIMapShell.tsx", import.meta.url), "utf8");

  assert.match(homeSource, /redirect\("\/ui-map"\)/);
  assert.match(headerSource, /href="\/ui-map"/);
  assert.match(shellSource, /系统研究链路/);
  assert.match(shellSource, /系统运营链路/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm exec tsx --test app/ui-map/navigation.test.ts
```

Expected: FAIL because `/` and `Header` are not yet updated.

- [ ] **Step 3: Write the minimal promotion changes**

```tsx
// app/page.tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/ui-map");
}
```

```tsx
// components/Header.tsx excerpt
<Link
  href="/ui-map"
  className={cn(
    "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
    pathname === "/ui-map"
      ? "bg-gray-100 text-gray-900"
      : "text-gray-500 hover:bg-gray-50 hover:text-gray-700",
  )}
>
  UI-Map
</Link>
```

```tsx
// UIMapShell.tsx excerpt
<section aria-label="perspective-layer" className="grid gap-6 lg:grid-cols-2">
  {perspectiveLayer.map((item) => (
    <UIMapModuleCard key={item.title} title={item.title} description={item.description} />
  ))}
</section>
```

- [ ] **Step 4: Run build**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm build
```

Expected: `/` redirects to `/ui-map`, and `/feed` `/chain` remain available.

- [ ] **Step 5: Run pressure test and multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm dev >/tmp/ui-map-nav.log 2>&1 &
DEV_PID=$!
sleep 6
for path in / /ui-map /ui-map?scenario=custom-heavy /ui-map?scenario=system-heavy /feed /chain; do
  curl -s -o /tmp/ui-map-check.html -w "%{http_code}" "http://127.0.0.1:3456${path}" | grep -qE "200|307|308" || exit 1
done
kill $DEV_PID
wait $DEV_PID 2>/dev/null || true
echo "ui-map navigation pressure ok"
```

- [ ] **Step 6: Run architecture-drift review against the approved diagram**

Check:

```text
1. ui-map 被提升为独立中台入口，但 feed / chain 仍保留独立入口
2. 透视层仍然是“系统研究链路 / 系统运营链路”
3. 提升入口后没有把用户前端和中台重新混合
4. 入口推广没有改变首页分层结构
```

- [ ] **Step 7: Commit**

```bash
git add app/page.tsx components/Header.tsx app/ui-map/UIMapShell.tsx app/globals.css app/ui-map/navigation.test.ts
git commit -m "feat: promote ui-map shell as hub entry"
```

## Task 6: Add Automated Pressure Checks, Browser Scenarios, And Docs Handoff

**Files:**
- Create: `7-产物中台/系统研究索引体系/scripts/ui-map-pressure-check.mjs`
- Modify: `7-产物中台/系统研究索引体系/app/ui-map/UIMapClient.tsx`
- Modify: `7-产物中台/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`
- Modify: `7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md`

- [ ] **Step 1: Write the failing pressure script invocation**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
node scripts/ui-map-pressure-check.mjs
```

Expected: FAIL because the script does not yet exist.

- [ ] **Step 2: Write the pressure script and scenario markers**

```js
// scripts/ui-map-pressure-check.mjs
const scenarios = ["balanced", "custom-heavy", "system-heavy", "execution-heavy"];
const baseUrl = process.env.UI_MAP_BASE_URL || "http://127.0.0.1:3456";

async function main() {
  for (let round = 0; round < 10; round++) {
    for (const scenario of scenarios) {
      const response = await fetch(`${baseUrl}/ui-map?scenario=${scenario}`);
      const html = await response.text();
      if (!response.ok) throw new Error(`${scenario} failed: ${response.status}`);
      if (!html.includes("自定义策略")) throw new Error(`${scenario} missing 自定义策略`);
      if (!html.includes("系统策略")) throw new Error(`${scenario} missing 系统策略`);
      if (!html.includes("策略主线")) throw new Error(`${scenario} missing 策略主线`);
      if (!html.includes("用户上下文索引系统")) throw new Error(`${scenario} missing 用户上下文索引系统`);
      if (!html.includes("系统研究索引体系")) throw new Error(`${scenario} missing 系统研究索引体系`);
    }
  }
  console.log("ui-map pressure check ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
```

```tsx
// UIMapClient.tsx excerpt
<div className="flex flex-wrap gap-2" data-testid="ui-map-scenario-switcher">
  ...
</div>
```

- [ ] **Step 3: Run pressure script**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
pnpm dev >/tmp/ui-map-pressure.log 2>&1 &
DEV_PID=$!
sleep 6
node scripts/ui-map-pressure-check.mjs
kill $DEV_PID
wait $DEV_PID 2>/dev/null || true
```

Expected:

```text
ui-map pressure check ok
```

- [ ] **Step 4: Run browser multi-scenario simulation**

Run:

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/系统研究索引体系
mkdir -p .tmp/ui-map-scenarios
pnpm dlx playwright screenshot --viewport-size="1440,1400" "http://127.0.0.1:3456/ui-map?scenario=balanced" .tmp/ui-map-scenarios/balanced.png
pnpm dlx playwright screenshot --viewport-size="1440,1400" "http://127.0.0.1:3456/ui-map?scenario=custom-heavy" .tmp/ui-map-scenarios/custom-heavy.png
pnpm dlx playwright screenshot --viewport-size="1440,1400" "http://127.0.0.1:3456/ui-map?scenario=system-heavy" .tmp/ui-map-scenarios/system-heavy.png
pnpm dlx playwright screenshot --viewport-size="1440,1400" "http://127.0.0.1:3456/ui-map?scenario=execution-heavy" .tmp/ui-map-scenarios/execution-heavy.png
```

Expected: 4 screenshots created.

- [ ] **Step 5: Run final architecture-drift review against the approved diagram**

Check:

```text
1. 最终壳结构与设计图层级一致
2. 模块化填充没有破坏“来源层 → 主线层 → 底座层 → 透视层”
3. 双索引和双链路透视仍然成立
4. 没有把 backend 能力提前硬接进前端壳
```

- [ ] **Step 6: Backfill docs**

```md
## Implementation Notes

- First shipped route: `/ui-map`
- Delivery strategy: shell first, then module-by-module
- Validation includes pressure tests, four-scenario simulation, and architecture-drift review against `http://127.0.0.1:62932/ui-map-independent-hub-architecture.html`
```

- [ ] **Step 7: Commit**

```bash
git add scripts/ui-map-pressure-check.mjs app/ui-map/UIMapClient.tsx docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md
git commit -m "docs: finalize ui-map shell-first handoff"
```

## Self-Review

- Spec coverage:
  - `ui-map` 独立中台首页: Tasks 2 and 5
  - 先前端壳再逐模块落地: Tasks 1-6
  - 首页第一层按 `自定义策略 / 系统策略`: Tasks 1-3
  - `策略主线` 作为统一收口层: Task 4
  - `用户上下文索引系统` 与 `系统研究索引体系`: Task 4
  - `系统研究链路 / 系统运营链路`: Task 5
  - 每个重要功能后执行压力测试、多场景模拟、设计漂移检查: Tasks 1-6
- Placeholder scan:
  - No `TODO`/`TBD` placeholders remain.
  - Each task includes exact files, commands, and concrete snippets.
- Type consistency:
  - `UIMapScenarioId`, `UIMapScenario`, and `UIMapShellViewModel` are introduced in Task 1 and used consistently in later tasks.

Plan complete and saved to `7-产物中台/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

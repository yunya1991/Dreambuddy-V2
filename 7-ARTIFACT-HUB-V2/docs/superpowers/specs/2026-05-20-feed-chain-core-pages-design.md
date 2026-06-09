# Feed And Chain Core Pages Design

> Date: 2026-05-20
> Scope: `7-ARTIFACT-HUB-V2`
> Status: Ready for review

## 1. Goal

Within `7-ARTIFACT-HUB-V2`, restore the two core pages currently represented by:

- `http://49.233.123.96/feed`
- `http://49.233.123.96/chain`

The goal is not to rebuild a separate frontend, but to inherit their core capabilities into the middle-layer governance product already evolving inside `7-ARTIFACT-HUB-V2`.

The final positioning is:

- `/feed` is the content portal plus governance context entry.
- `/chain` is the internal research-chain monitoring page and the core governance surface for content and trading capabilities.
- Both pages belong to the same middle-layer governance system and must be strongly linked.

## 2. Product Positioning

### 2.1 `/feed`

`/feed` is the visible portal for artifacts and content governance. It answers:

- what the artifact is
- which department/category it belongs to
- what state it is in
- which governance context produced it

It must support browsing, filtering, searching, detail reading, and jumping into chain context.

### 2.2 `/chain`

`/chain` is the execution and monitoring view for internal research and trading-linked workflows. It answers:

- how an artifact was produced
- which workflow/phase it belongs to
- whether execution is healthy
- which task/result/trace links exist or are broken

It is not a generic page. It is the core monitoring and governance surface for the middle layer.

### 2.3 Relationship

`/feed` and `/chain` are two views over the same system:

- `/feed` is content-first
- `/chain` is process-first

They must share the same source of truth and provide two-way navigation.

## 3. Architecture Decision

Both `/feed` and `/chain` are hosted in `7-ARTIFACT-HUB-V2`.

They are exposed as real routes on the Hub server, while `ops-ui` remains an entry and governance control console.

### 3.1 Real routes

Required first-stage routes:

- `GET /feed`
- `GET /feed/:category`
- `GET /feed/:category/:artifactId`
- `GET /chain`
- `GET /chain/:workflowType`

Optional second-level chain detail route for later if needed:

- `GET /chain/:workflowType/:artifactId`

### 3.2 `ops-ui` role

`ops-ui` and `/ui-map` do not replace the real pages.

They should:

- explain the architecture
- point to the real `/feed`
- point to the real `/chain`
- provide governance and monitoring helper entry points

## 4. Code Structure

The implementation should stay inside the current package and reuse existing foundations.

### 4.1 Existing files to continue reusing

- `src/server.ts`
- `src/index.ts`
- `src/artifact-store.ts`
- `src/meta-store.ts`
- `src/router-engine.ts`
- `src/work-order.ts`
- `src/ops-ui/*`

### 4.2 Feed area

Continue evolving:

- `src/feed/content.ts`
- `src/feed/render.ts`
- `src/feed/types.ts`
- `src/feed/utils.ts`

### 4.3 Chain area

Add a dedicated area:

- `src/chain/content.ts`
- `src/chain/render.ts`
- `src/chain/types.ts`
- `src/chain/utils.ts`

The names can be adjusted to match existing patterns, but `/chain` must have its own query and rendering modules rather than being embedded directly into `server.ts`.

## 5. Responsibility Boundaries

### 5.1 `/feed` responsibilities

First-stage `/feed` must provide:

- top navigation and page shell
- search
- multi-dimensional filters
- artifact card stream
- pagination or equivalent large-list browsing
- detail page with content and governance context
- link from artifact to chain context

### 5.2 `/chain` responsibilities

First-stage `/chain` must provide:

- top navigation and page shell
- workflow overview
- workflow-type grouping
- chain-phase monitoring
- task/result/trace visibility
- anomaly visibility
- links back to artifact content

### 5.3 Shared governance fields

The two pages must align on these identifiers:

- `artifact_id`
- `category`
- `workflow_id`
- `workflow_type`
- `trace_id`
- `task_id`
- `status`
- `chain_phase`
- `department`

## 6. First-Stage Scope

This phase aims for a complete usable core, not a superficial mockup.

### 6.1 `/feed` must restore

- page structure close to the current remote `/feed`
- search across title, tags, excerpt, and category-related text
- filters for:
  - department
  - time
  - A segment / chain phase
  - category / type / status
- artifact cards with:
  - title
  - department
  - type
  - status
  - date
  - excerpt
  - tags
- pagination or equivalent list segmentation
- detail page with:
  - main reading area
  - metadata
  - trace/task/result/chain info
  - jump to related chain view

### 6.2 `/chain` must restore

- page structure close to the current remote `/chain`
- workflow overview
- grouping by `workflow_type`
- chain stage visibility
- monitoring of:
  - tasks
  - results
  - traces
  - health and failures
- links from chain entries back to matching artifacts
- explicit visibility of missing or broken states

### 6.3 Explicitly out of scope for this phase

- full parity for all non-core pages
- board/market/approval deep integrations
- pixel-perfect 1:1 cloning of every remote detail
- large new frontend frameworks or a separate SPA rewrite

## 7. Data Flow Design

The source of truth remains repo-local:

- `dreambuddy/artifacts`
- `dreambuddy/meta`
- `dreambuddy/config`

### 7.1 Layer model

Use three layers:

#### Layer 1: storage access

This layer reads raw facts from:

- `ArtifactStore`
- `MetaStore`
- `WorkOrderManager`

#### Layer 2: query/view-model layer

This layer composes page-oriented models for `/feed` and `/chain`.

It should combine artifact, trace, task, result, and metadata into objects suitable for rendering.

#### Layer 3: HTML rendering layer

This layer renders SSR HTML for:

- `/feed`
- `/chain`

### 7.2 Feed view models

Required:

- `FeedListViewModel`
- `FeedDetailViewModel`

These should expose content plus governance context, not just raw markdown/index data.

### 7.3 Chain view models

Required:

- `ChainOverviewViewModel`
- `ChainWorkflowViewModel`
- `ChainArtifactLinkViewModel`

### 7.4 Cross-link model

Add a shared cross-page model:

- `CrossLinkContext`

It should hold the minimum identifiers needed to link `/feed` and `/chain` in both directions.

## 8. Runtime Fix Strategy

Before adding more visible features, fix local runtime consistency.

### 8.1 Canonical local URLs

Target local URLs:

- Hub: `http://127.0.0.1:3456`
- Ops UI: `http://127.0.0.1:3457`

### 8.2 Required startup contract

`ops-ui` must be started with an explicit Hub target:

- `HUB_URL=http://127.0.0.1:3456`

If needed, `OPS_UI_FEED_BASE_URL` and an equivalent chain base URL may be introduced later, but the first-stage rule is simple:

- `ui-map` must point to the real local Hub routes

### 8.3 UI map behavior

The `feed` node in `ui-map` must jump to the real `/feed`.

The `chain` node in `ui-map` must jump to the real `/chain`.

Users should no longer be trapped on planned placeholders for these two core pages.

## 9. Error Handling

The system must prefer explicit degraded states over silent failure.

### 9.1 Feed

- If a full content file exists, render it.
- If only `index.json` metadata exists, render a fallback detail view.
- If artifact exists but detail context is incomplete, render the page with a clear incomplete-state panel.
- Only return `404` when the artifact truly cannot be resolved.

### 9.2 Chain

The page must remain renderable even if some operational links are missing.

Explicit anomaly types should be surfaced:

- missing task
- missing result
- orphan artifact
- broken trace link
- unknown phase/state

### 9.3 Cross-page navigation

- From `/feed` to `/chain`, missing chain context must show a clear empty state.
- From `/chain` to `/feed`, missing artifact context must show a clear missing-artifact state.

## 10. Validation Strategy

Validation must include both runtime and browser-level checks.

### 10.1 Runtime checks

- `GET /health` on Hub
- `GET /ui-map` on ops-ui
- `ui-map -> /feed`
- `ui-map -> /chain`

### 10.2 Page checks

- `/feed`
- `/feed/:category`
- `/feed/:category/:artifactId`
- `/chain`
- `/chain/:workflowType`

### 10.3 Cross-link checks

- `/feed` entry can jump to related `/chain`
- `/chain` entry can jump back to related `/feed`

### 10.4 Data realism checks

Validation must use real repo-local data:

- real artifacts
- real tasks/results
- real trace/meta data

## 11. Testing Strategy

This phase should add focused tests only where they materially reduce regression risk.

### 11.1 Required automated tests

- route tests for `/feed` and `/chain`
- view-model/query tests for feed and chain data composition
- fallback tests for missing detail files and missing chain links
- ops-ui tests to ensure `ui-map` points to real `/feed` and `/chain`

### 11.2 Recommended but optional browser checks

- browser verification of `ui-map -> /feed`
- browser verification of `ui-map -> /chain`
- browser verification of `/feed <-> /chain` bidirectional navigation

## 12. Delivery Order

Recommended implementation order:

1. Fix local runtime so Hub and ops-ui point to the correct current processes.
2. Make `ui-map` point `feed` and `chain` to real routes.
3. Upgrade `/feed` homepage and detail page toward the remote core behavior.
4. Introduce `/chain` real routes and monitoring views.
5. Add bidirectional linking and governance-context panels.
6. Run full runtime and browser-level verification.

## 13. Success Criteria

This phase is successful when all of the following are true:

- `7-ARTIFACT-HUB-V2` is the real host of both `/feed` and `/chain`
- `ui-map` enters the real local pages rather than placeholders
- local `/feed` is no longer just a minimal recovery page
- local `/chain` is no longer missing as a real page
- `/feed` and `/chain` share identifiers and can navigate to each other
- the pages expose governance context rather than only surface content
- local verification works with real repo-local data

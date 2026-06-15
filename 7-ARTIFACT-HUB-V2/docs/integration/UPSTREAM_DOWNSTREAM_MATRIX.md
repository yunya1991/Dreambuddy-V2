# Upstream Downstream Matrix

本文件冻结 `6-TRADING`、`7-ARTIFACT-HUB-V2`、`3-FRONTEND` 的承接关系，只用于明确“谁产出、谁承接、谁消费、谁审计”。

## 1. Systems

| Layer | Path | Owns |
|---|---|---|
| Upstream | `6-TRADING` | research/trading production |
| Middle | `7-ARTIFACT-HUB-V2` | route/trace/task/result/feed/ops governance |
| Downstream | `3-FRONTEND` | user entry and lightweight consumption |

## 2. Handoffs

| Producer | Artifact | Middle Layer Role | Consumer |
|---|---|---|---|
| `6-TRADING` | research/trading outputs | ingest, classify, route, audit | `3-FRONTEND` or governance views |
| `3-FRONTEND` | user intent/task requests | route and persistence | Hub / Trading |
| `7-ARTIFACT-HUB-V2` | trace/task/result/feed projections | expose governance evidence | both governance and user views |

## 3. Route Ownership

- `/feed`: middle-layer product surface in `7-ARTIFACT-HUB-V2`
- `/ops`: governance console in `7-ARTIFACT-HUB-V2`
- `/dashboard`: downstream user surface in `3-FRONTEND`
- `/chain`: shared consumption route, with governance evidence produced by `7-ARTIFACT-HUB-V2` and downstream user presentation owned by `3-FRONTEND`
- `/board`: downstream governance consumption surface in `3-FRONTEND`, backed by Hub governance data
- `/market`: downstream business consumption surface in `3-FRONTEND`, backed by upstream outputs and Hub projections
- `/api/ops/*`: middle-layer governance APIs exposed by `7-ARTIFACT-HUB-V2`
- `/route/decide`, `/route/execute`, `/traces/:traceId`, `/events/stream`: middle-layer Hub governance contracts exposed by `7-ARTIFACT-HUB-V2`

## 4. Ownership Notes

- `6-TRADING` produces upstream execution outputs and should not expand into governance UI ownership.
- `7-ARTIFACT-HUB-V2` owns governance evidence, handoff persistence, feed projections, and ops-facing control surfaces.
- `3-FRONTEND` owns end-user entry, authenticated downstream views, and lightweight consumption of Hub outputs.
- Shared runtime evidence should converge to repo-local truth sources rather than feature-local storage conventions.

## 5. Related Documents

- [SYSTEM_BOUNDARIES.md](../architecture/SYSTEM_BOUNDARIES.md)
- [SOURCE_OF_TRUTH.md](../architecture/SOURCE_OF_TRUTH.md)
- [FRONTEND_INTEGRATION_DESIGN.md](./FRONTEND_INTEGRATION_DESIGN.md)
- [frontend-hub-trading三端联通.md](./frontend-hub-trading三端联通.md)
- [OPS_UI_README.md](../governance/OPS_UI_README.md)

## 6. Non-Goals

- This document does not move code or rename routes.
- This document does not redefine runtime source-of-truth paths.
- This document only freezes current ownership language for later implementation work.

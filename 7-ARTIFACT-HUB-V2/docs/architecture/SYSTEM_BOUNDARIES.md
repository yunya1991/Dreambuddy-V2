# System Boundaries

## 1. Scope

This document freezes the role boundaries among:

- `3-FRONTEND`
- `7-ARTIFACT-HUB-V2`
- `6-TRADING`
- `dreambuddy/config`
- `dreambuddy/artifacts`

## 2. Boundary Table

| System | Role | Produces | Consumes | Must Not Own |
|---|---|---|---|---|
| `3-FRONTEND` | Consumer entry | user actions, downstream views | hub query results, task status, feed projections | governance source of truth, runtime evidence ownership |
| `7-ARTIFACT-HUB-V2` | Middle governance layer | route, trace, task, result, feed, ops projections | trading outputs, shared config, repo-local artifacts | end-user heavy UI ownership, upstream execution logic |
| `6-TRADING` | Upstream production layer | research outputs, trading execution artifacts, workflow results | market signals, skills, upstream task intents | governance UX, downstream presentation |
| `dreambuddy/config` | Shared config base | shared runtime configuration | reviewed policy inputs | feature-specific product logic, duplicated local overrides |
| `dreambuddy/artifacts` | Repo-local runtime evidence root | task files, result files, archived evidence | upstream and middle-layer writes | UI-specific view logic, ad hoc alternate storage roots |

## 3. Boundary Notes

- `3-FRONTEND` owns downstream user interaction and lightweight consumption surfaces.
- `7-ARTIFACT-HUB-V2` owns middle-layer governance surfaces such as routing, tracing, task persistence, feed projections, and ops views.
- `6-TRADING` owns upstream production workflows and should publish outputs into shared repo-local roots rather than downstream-specific locations.
- `dreambuddy/config` and `dreambuddy/artifacts` are shared bases and should not be redefined by feature-local conventions.

## 4. Freeze Rule

- This document defines current governance boundaries only.
- It does not authorize code moves, path migrations, or ownership expansion by itself.
- Later implementation work should link back to this document before changing cross-system responsibilities.

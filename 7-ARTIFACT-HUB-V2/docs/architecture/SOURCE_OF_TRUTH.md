# Source Of Truth

## 1. Repo-Local Truth Sources

- Artifacts root: `../dreambuddy/artifacts`
- Meta root: `../dreambuddy/meta`
- Config root: `../dreambuddy/config`

## 2. Rules

- New runtime artifacts must converge into repo-local roots.
- New docs must not redefine source-of-truth paths ad hoc.
- `~/.workbuddy` is compatibility context, not the long-term primary source.

## 3. Practical Constraints

- Feature docs may reference truth sources, but they must not create competing path standards.
- Runtime evidence should stay traceable to repo-local artifacts and meta paths.
- Shared config changes should be treated as cross-system changes and reviewed explicitly.

## 4. Non-Goals

- This document does not migrate existing files.
- This document does not replace implementation-specific schemas.
- This document only freezes the primary roots that later work must converge on.

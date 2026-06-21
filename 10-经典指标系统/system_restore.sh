#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash system_restore.sh (--latest | ARCHIVE.tar.gz) [--to DIR] [--verify-only]
  bash system_restore.sh (--latest | ARCHIVE.tar.gz) [--to DIR] --dry-run
  bash system_restore.sh --rollback

Notes:
  - Default restore (no --to) performs in-place restore with an automatic rollback archive.
  - Backups directory is preserved across restore.

Options:
  --latest       Restore newest backup from backups/system
  --to DIR       Restore into a new directory (no overwrite)
  --verify-only  Only verify checksum (if present) and archive readability
  --dry-run      Print restore plan after verification (no changes)
  --rollback     Restore newest pre_restore directory created by this script
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
PARENT_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

ARCHIVE=""
USE_LATEST=false
VERIFY_ONLY=false
TARGET_DIR=""
DO_ROLLBACK=false
NO_ROLLBACK_ARCHIVE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)
      USE_LATEST=true
      shift
      ;;
    --verify-only)
      VERIFY_ONLY=true
      shift
      ;;
    --to)
      TARGET_DIR="${2:-}"
      shift 2
      ;;
    --rollback)
      DO_ROLLBACK=true
      shift
      ;;
    --no-rollback-archive)
      NO_ROLLBACK_ARCHIVE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$ARCHIVE" ]]; then
        ARCHIVE="$1"
        shift
      else
        echo "unknown_arg:$1" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

cd "$PARENT_DIR"

if [[ "$DO_ROLLBACK" == "true" ]]; then
  latest_rb="$(ls -1t "$PROJECT_NAME"/backups/system/"${PROJECT_NAME}.pre_restore_"*.tar.gz 2>/dev/null | head -n 1 || true)"
  if [[ -z "$latest_rb" ]]; then
    latest_dir="$(ls -1dt "${PROJECT_NAME}.pre_restore_"* 2>/dev/null | head -n 1 || true)"
    if [[ -z "$latest_dir" ]]; then
      echo "rollback_not_found" >&2
      exit 1
    fi

    ts="$(date +"%Y%m%d_%H%M%S")"
    current_backup="${PROJECT_NAME}.rolled_back_from_${ts}"
    if [[ -d "$PROJECT_NAME" ]]; then
      mv "$PROJECT_NAME" "$current_backup"
    fi
    mv "$latest_dir" "$PROJECT_NAME"
    echo "ok:true"
    echo "rollback_from:$latest_dir"
    echo "previous_current:$current_backup"
    exit 0
  fi

  sha_file="${latest_rb}.sha256"
  if [[ -f "$sha_file" ]]; then
    (
      cd "$(dirname "$latest_rb")"
      shasum -a 256 -c "$(basename "$sha_file")" >/dev/null
    )
  fi

  tar -tzf "$latest_rb" >/dev/null

  ts="$(date +"%Y%m%d_%H%M%S")"
  current_backup="${PROJECT_NAME}.rolled_back_from_${ts}"
  hold_backups="${PROJECT_NAME}.backups_hold_${ts}"
  if [[ -d "$PROJECT_NAME/backups" ]]; then
    mv "$PROJECT_NAME/backups" "$hold_backups"
  fi
  if [[ -d "$PROJECT_NAME" ]]; then
    mv "$PROJECT_NAME" "$current_backup"
  fi
  COPYFILE_DISABLE=1 tar -xzf "$latest_rb" -C "$PARENT_DIR"
  if [[ -d "$hold_backups" ]]; then
    mkdir -p "$PROJECT_NAME"
    rm -rf "$PROJECT_NAME/backups" 2>/dev/null || true
    mv "$hold_backups" "$PROJECT_NAME/backups"
  fi
  echo "ok:true"
  echo "rolled_back:true"
  echo "archive:$latest_rb"
  echo "previous_current:$current_backup"
  exit 0
fi

if [[ "$USE_LATEST" == "true" ]]; then
  latest_file="$(ls -1t "$PROJECT_NAME"/backups/system/*backup_*.tar.gz 2>/dev/null | head -n 1 || true)"
  if [[ -z "$latest_file" ]]; then
    echo "no_backup_found" >&2
    exit 1
  fi
  ARCHIVE="$latest_file"
fi

if [[ -z "$ARCHIVE" ]]; then
  echo "missing_archive" >&2
  usage >&2
  exit 2
fi

if [[ ! -f "$ARCHIVE" ]]; then
  echo "archive_not_found:$ARCHIVE" >&2
  exit 1
fi

sha_file="${ARCHIVE}.sha256"
if [[ -f "$sha_file" ]]; then
  (
    cd "$(dirname "$ARCHIVE")"
    shasum -a 256 -c "$(basename "$sha_file")" >/dev/null
  )
fi

tar -tzf "$ARCHIVE" >/dev/null

archive_top="$(tar -tzf "$ARCHIVE" | head -n 1 | cut -d/ -f1 || true)"
if [[ -z "$archive_top" || "$archive_top" != "$PROJECT_NAME" ]]; then
  echo "invalid_archive_layout" >&2
  exit 1
fi

if [[ "$VERIFY_ONLY" == "true" ]]; then
  echo "ok:true"
  echo "verified:true"
  echo "archive:$ARCHIVE"
  exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "ok:true"
  echo "dry_run:true"
  echo "archive:$ARCHIVE"
  if [[ -n "$TARGET_DIR" ]]; then
    echo "action:restore_to"
    echo "target:$TARGET_DIR"
  else
    echo "action:restore_in_place"
    if [[ "$NO_ROLLBACK_ARCHIVE" == "true" ]]; then
      echo "rollback_archive:false"
    else
      echo "rollback_archive:true"
    fi
    if [[ -d "$PROJECT_NAME/backups" ]]; then
      echo "preserve_backups:true"
    else
      echo "preserve_backups:false"
    fi
  fi
  exit 0
fi

if [[ -n "$TARGET_DIR" ]]; then
  tmp_dir="$(mktemp -d -t "${PROJECT_NAME}_restore")"
  COPYFILE_DISABLE=1 tar -xzf "$ARCHIVE" -C "$tmp_dir"
  restored_dir="$tmp_dir/$PROJECT_NAME"

  if [[ -e "$TARGET_DIR" ]]; then
    rm -rf "$tmp_dir"
    echo "target_exists:$TARGET_DIR" >&2
    exit 1
  fi
  mv "$restored_dir" "$TARGET_DIR"
  rm -rf "$tmp_dir"
  echo "ok:true"
  echo "restored_to:$TARGET_DIR"
  echo "archive:$ARCHIVE"
  exit 0
fi

ts="$(date +"%Y%m%d_%H%M%S")"
hold_backups="${PROJECT_NAME}.backups_hold_${ts}"
rb_dir="$hold_backups/system"
rb_archive=""

if [[ -d "$PROJECT_NAME" ]]; then
  if [[ -d "$PROJECT_NAME/backups" ]]; then
    mv "$PROJECT_NAME/backups" "$hold_backups"
  else
    mkdir -p "$hold_backups"
  fi
  mkdir -p "$rb_dir"
  if [[ "$NO_ROLLBACK_ARCHIVE" != "true" ]]; then
    rb_archive="$rb_dir/${PROJECT_NAME}.pre_restore_${ts}.tar.gz"
  COPYFILE_DISABLE=1 tar -czf "$rb_archive" -C "$PARENT_DIR" "$PROJECT_NAME"
    (
      cd "$rb_dir"
      shasum -a 256 "$(basename "$rb_archive")" > "$(basename "$rb_archive").sha256"
    )
  fi
  rm -rf "$PROJECT_NAME"
fi

restore_ok=false
(
  cd "$PARENT_DIR"
  COPYFILE_DISABLE=1 tar -xzf "$ARCHIVE" -C "$PARENT_DIR"
) && restore_ok=true

if [[ "$restore_ok" != "true" ]]; then
  rm -rf "$PROJECT_NAME" 2>/dev/null || true
  if [[ -n "$rb_archive" && -f "$rb_archive" ]]; then
    COPYFILE_DISABLE=1 tar -xzf "$rb_archive" -C "$PARENT_DIR"
  fi
  if [[ -d "$hold_backups" ]]; then
    mkdir -p "$PROJECT_NAME"
    rm -rf "$PROJECT_NAME/backups" 2>/dev/null || true
    mv "$hold_backups" "$PROJECT_NAME/backups"
  fi
  echo "restore_failed" >&2
  exit 1
fi

if [[ -d "$hold_backups" ]]; then
  mkdir -p "$PROJECT_NAME"
  rm -rf "$PROJECT_NAME/backups" 2>/dev/null || true
  mv "$hold_backups" "$PROJECT_NAME/backups"
fi

echo "ok:true"
echo "restored:true"
echo "archive:$ARCHIVE"
if [[ -n "$rb_archive" ]]; then
  echo "rollback_archive:$rb_archive"
fi

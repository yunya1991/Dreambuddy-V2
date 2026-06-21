#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash system_backup.sh [--runtime|--full] [--out DIR] [--label LABEL] [--keep N] [--keep-pre-restore N] [--no-prune]

Notes:
  --full:    Includes user_data/data and backtest results (default)
  --runtime: Excludes large historical data
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
PARENT_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

MODE="full"
OUT_DIR="$PROJECT_DIR/backups/system"
LABEL=""
KEEP=3
KEEP_PRE_RESTORE=3
PRUNE=true
MODE_EXPLICIT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)
      MODE="runtime"
      MODE_EXPLICIT=true
      shift
      ;;
    --full)
      MODE="full"
      MODE_EXPLICIT=true
      shift
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --label)
      LABEL="${2:-}"
      shift 2
      ;;
    --keep)
      KEEP="${2:-}"
      shift 2
      ;;
    --keep-pre-restore)
      KEEP_PRE_RESTORE="${2:-}"
      shift 2
      ;;
    --no-prune)
      PRUNE=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown_arg:$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

REQUESTED_MODE="$MODE"

if [[ -z "${OUT_DIR}" ]]; then
  echo "missing_out_dir" >&2
  exit 2
fi

if [[ ! "$KEEP" =~ ^[0-9]+$ ]] || (( KEEP < 1 )); then
  echo "invalid_keep:$KEEP" >&2
  exit 2
fi

if [[ ! "$KEEP_PRE_RESTORE" =~ ^[0-9]+$ ]] || (( KEEP_PRE_RESTORE < 1 )); then
  echo "invalid_keep_pre_restore:$KEEP_PRE_RESTORE" >&2
  exit 2
fi

timestamp="$(date +"%Y%m%d_%H%M%S")"
safe_label="${LABEL//[^a-zA-Z0-9._-]/_}"
base_name="${PROJECT_NAME}_backup_${timestamp}"
if [[ -n "$safe_label" ]]; then
  base_name="${PROJECT_NAME}_${safe_label}_backup_${timestamp}"
fi

mkdir -p "$OUT_DIR"
archive="$OUT_DIR/${base_name}.tar.gz"

if [[ "$MODE" == "full" ]]; then
  avail_kb="$(df -k "$OUT_DIR" | tail -n 1 | awk '{print $4}' || true)"
  if [[ -z "$avail_kb" ]]; then
    avail_kb=0
  fi
  if [[ "$avail_kb" =~ ^[0-9]+$ ]]; then
    if (( avail_kb < 4194304 )); then
      if [[ "$MODE_EXPLICIT" == "true" ]]; then
        echo "insufficient_space_for_full_backup_kb:$avail_kb" >&2
        exit 1
      fi
      MODE="runtime"
    fi
  else
    if [[ "$MODE_EXPLICIT" == "true" ]]; then
      echo "df_parse_failed" >&2
      exit 1
    fi
    MODE="runtime"
  fi
fi

excludes=(
  "${PROJECT_NAME}/.mypy_cache"
  "${PROJECT_NAME}/.pytest_cache"
  "${PROJECT_NAME}/__pycache__"
  "${PROJECT_NAME}/cache"
  "${PROJECT_NAME}/frontend/node_modules"
  "${PROJECT_NAME}/backups"
)

if [[ "$MODE" == "runtime" ]]; then
  excludes+=(
    "${PROJECT_NAME}/user_data/data"
    "${PROJECT_NAME}/user_data/backtest_results"
    "${PROJECT_NAME}/user_data/plot"
    "${PROJECT_NAME}/user_data/hyperopt_results"
  )
fi

tar_args=( -czf "$archive" )
for e in "${excludes[@]}"; do
  tar_args+=( --exclude="$e" )
done

COPYFILE_DISABLE=1 tar "${tar_args[@]}" -C "$PARENT_DIR" "$PROJECT_NAME"

(
  cd "$OUT_DIR"
  shasum -a 256 "$(basename "$archive")" > "$(basename "$archive").sha256"
)

if [[ "$PRUNE" == "true" ]]; then
  shopt -s nullglob

  prune_files() {
    local keep_count="$1"
    shift
    local candidates=("$@")
    local sorted=()

    if (( ${#candidates[@]} == 0 )); then
      return 0
    fi

    while IFS= read -r f; do
      sorted+=("$f")
    done < <(ls -1t "${candidates[@]}")

    if (( ${#sorted[@]} <= keep_count )); then
      return 0
    fi

    for ((i=keep_count; i<${#sorted[@]}; i++)); do
      rm -f "${sorted[$i]}" "${sorted[$i]}.sha256" 2>/dev/null || true
    done
  }

  prune_files "$KEEP" "$OUT_DIR"/*backup_*.tar.gz
  prune_files "$KEEP_PRE_RESTORE" "$OUT_DIR"/"${PROJECT_NAME}.pre_restore_"*.tar.gz

  for sha in "$OUT_DIR"/*.tar.gz.sha256; do
    tar_file="${sha%.sha256}"
    if [[ ! -f "$tar_file" ]]; then
      rm -f "$sha" 2>/dev/null || true
    fi
  done
fi

echo "ok:true"
echo "archive:$archive"
echo "sha256:${archive}.sha256"
echo "requested_mode:$REQUESTED_MODE"
echo "mode:$MODE"

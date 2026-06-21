#!/usr/bin/env bash
set -euo pipefail

HOST="${LLAMA_HOST:-127.0.0.1}"
PORT="${LLAMA_PORT:-8080}"
MODEL_PATH="${LLAMA_GGUF_PATH:-}"

if [[ -z "${MODEL_PATH}" ]]; then
  echo "LLAMA_GGUF_PATH is required"
  exit 2
fi

exec llama-server --host "${HOST}" --port "${PORT}" --model "${MODEL_PATH}"


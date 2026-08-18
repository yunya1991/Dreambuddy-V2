#!/bin/bash
# Wrapper: load .env then start hermes gateway
set -a
source /Users/zhangjiangtao/.hermes/.env
set +a
exec /Users/zhangjiangtao/.hermes/.venv/bin/hermes gateway run --replace

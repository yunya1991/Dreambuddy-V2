#!/bin/bash
set -a
source /Users/zhangjiangtao/.hermes/.env
set +a
exec /Users/zhangjiangtao/.hermes/.venv/bin/hermes dashboard

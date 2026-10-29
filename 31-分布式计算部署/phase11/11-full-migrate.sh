#!/usr/bin/env bash
# ============================================================================
# Phase 11: 面板(8765)数据 本地 → 云端 全量同步（首次）
#
# 决策背景（用户 2026-10-14 确认）：
#   "我说的全量数据先仅包含 http://localhost:8765/ 页面中相关模块的全量数据"
#
# 同步集 = git 未覆盖的数据（ignored+modified）∩ 面板数据白名单
#   + git 漏列补全的 *.db*（data_center.db 等 git ls-files 异常漏列）
#
# 白名单 → 面板端点映射（data_server_fixed.py 数据源）：
#   experiments/ab-trading/{logs,data,config}   → /api/state /api/dreamos/history /api/capital/*
#   23-四层.../dreambuddy_evolution/            → /api/agi/* /api/nonlinear-path-metrics
#   14-V15经典马丁策略/{data,config}            → /api/v15-ct/*
#   11-易经推理系统/.workbuddy/memory_l4/{stats,open_positions,risk,guardian,cases}
#                                               → /api/l4-status /api/yijing/* /api/global-trade-stats
#   11-易经推理系统/.workbuddy/bdsm             → /api/bdsm/snapshot
#   11-易经推理系统/scripts/{artifacts,runtime} → shadow/force-vector/evolution/fuses
#   11-易经推理系统/data/（除 polling_trader|a7_gate_logs 生产日志）→ /api/event-driven /api/alpha|fma|inject
#   11-易经推理系统/.env                        → OKX 凭据（yijing 端点）
#   1-ARCHITECTURE/dreamos/{data,core/memory/*.json,cli/scheduler_data,.env}
#                                               → /api/dreamos*
#   10-经典指标系统/{user_data,.env}            → /api/classic-executor*
#   18-数据获取中心/data_center.db* + config/.env → /api/data-center/*
#   12-三屏趋势系统/{data,signal_pool,.env}     → /api/screen-* /api/trend-screen /api/v4-wave
#   6-TRADING/scripts/.env                      → 凭据
#
# 用法：
#   ./11-sync-panel-data.sh --dry-run   # 只生成清单并统计
#   ./11-sync-panel-data.sh             # tar+zstd 流式传输到云端
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_HOST="dreambuddy-remote"
REMOTE_DIR="/home/luke/dreambuddy"
SSH_OPTS=(-o ConnectTimeout=40 -o ServerAliveInterval=30 -o ServerAliveCountMax=6)
LIST="$(mktemp /tmp/sync_panel.XXXXXX)"
trap 'rm -f "$LIST"' EXIT
MODE="${1:-run}"

# ── 1. 生成同步清单 ──────────────────────────────────────────────────────────
# 1a. git ignored + modified（= git 未覆盖的数据）
{ git -C "$REPO_ROOT" ls-files --others --ignored --exclude-standard -z
  git -C "$REPO_ROOT" ls-files -m -z; } | tr '\0' '\n' | sort -u > "$LIST.raw"

# 1b. 面板数据白名单前缀过滤 + 排除生产者日志海（面板不读）
cat > "$LIST.prefix" <<'EOF'
experiments/ab-trading/
23-四层闭环自进化交易架构/dreambuddy_evolution/
14-V15经典马丁策略/data/
14-V15经典马丁策略/config/
11-易经推理系统/.workbuddy/memory_l4/stats/
11-易经推理系统/.workbuddy/memory_l4/open_positions/
11-易经推理系统/.workbuddy/memory_l4/risk/
11-易经推理系统/.workbuddy/memory_l4/guardian/
11-易经推理系统/.workbuddy/memory_l4/cases/
11-易经推理系统/.workbuddy/bdsm/
11-易经推理系统/scripts/artifacts/
11-易经推理系统/scripts/runtime/
11-易经推理系统/data/
11-易经推理系统/.env
1-ARCHITECTURE/dreamos/data/
1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.json
1-ARCHITECTURE/dreamos/cli/scheduler_data/
1-ARCHITECTURE/dreamos/.env
10-经典指标系统/user_data/
10-经典指标系统/.env
10-经典指标系统/user_data/.env
18-数据获取中心/config/
12-三屏趋势系统/data/
12-三屏趋势系统/signal_pool/
12-三屏趋势系统/.env
6-TRADING/scripts/.env
EOF
awk 'NR==FNR{p[$1]=1;next}{keep=0; for(pre in p){if(index($0,pre)==1){keep=1;break}}
     if(keep && $0 !~ /^11-易经推理系统\/data\/(polling_trader|a7_gate_logs)\//) print}' \
  "$LIST.prefix" "$LIST.raw" > "$LIST.p1"

# 1c. git 漏列补全：面板路径下全部 *.db/*.db-journal/*.db-wal/*.db-shm/*.sqlite*
for d in "experiments/ab-trading/data" \
         "23-四层闭环自进化交易架构/dreambuddy_evolution" \
         "14-V15经典马丁策略/data" \
         "11-易经推理系统/scripts/artifacts" \
         "11-易经推理系统/scripts/runtime" \
         "11-易经推理系统/data" \
         "1-ARCHITECTURE/dreamos/data" \
         "10-经典指标系统/user_data" \
         "12-三屏趋势系统/data" \
         "12-三屏趋势系统/signal_pool" \
         "18-数据获取中心"; do
  find "$REPO_ROOT/$d" \( -name node_modules -o -name __pycache__ -o -name .venv \) -prune -o \
       -type f \( -name '*.db' -o -name '*.db-journal' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.sqlite*' \) \
       -print 2>/dev/null
done | sed "s|^$REPO_ROOT/||" | sort -u >> "$LIST.p1"

sort -u "$LIST.p1" -o "$LIST"
N=$(wc -l < "$LIST" | tr -d ' ')
SZ=$(tr '\n' '\0' < "$LIST" | xargs -0 stat -f %z 2>/dev/null | awk '{s+=$1} END {printf "%.2f", s/1073741824}')
echo "[sync-panel] 清单: $N 个文件 / ${SZ} GB"

case "$MODE" in
  --dry-run)
    awk -F/ '{print $1"/"$2}' "$LIST" | sort | uniq -c | sort -rn | head -12
    ;;
  run)
    echo "[sync-panel] tar+zstd 流式传输 → $REMOTE_HOST:$REMOTE_DIR"
    # 云端写服务须已停止（见 11-cloud-safety-overrides.sh / 执行记录）
    # 清单为换行分隔（勿用 --null）。set +e：传输期间生产者可能删除/轮转个别文件，
    # tar 对缺失文件告警但继续，退出码非0属预期；ssh 端失败才是真失败。
    set +e
    tar -C "$REPO_ROOT" -T "$LIST" -cf - 2>"$LIST.tarerr" \
      | zstd -3 -T2 \
      | ssh "${SSH_OPTS[@]}" "$REMOTE_HOST" \
        "sudo -n -u luke tar --zstd -xf - -C $REMOTE_DIR"
    PIPE_RC=$?
    set -e
    TAR_WARN=$(wc -l < "$LIST.tarerr" | tr -d ' ')
    NONMISS=$(grep -vc "Cannot open: No such file or directory\|Does not exist\|Error exit delayed" "$LIST.tarerr" || true)
    echo "[sync-panel] 管道退出码=$PIPE_RC，tar 警告 $TAR_WARN 行（非缺失类 $NONMISS 行）"
    if [ "$NONMISS" != "0" ]; then
      echo "[sync-panel] 发现非缺失类错误（前3行）:"; head -3 "$LIST.tarerr"
      exit 1
    fi
    echo "[sync-panel] 传输完成"
    ;;
  *)
    echo "用法: $0 [--dry-run]" >&2; exit 1 ;;
esac

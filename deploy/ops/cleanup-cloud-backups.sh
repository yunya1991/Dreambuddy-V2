#!/bin/bash
# 云端备份轮转：只保留有价值的近期备份，防止根分区被历史产物堆满。
# 幂等，可重复执行；由 dreambuddy-backup-retention.timer 每天调用。
set -u

KEEP_DAILY=1
KEEP_CORE_DUMPS=2
KEEP_COGNITIVE_DUMPS=1
KEEP_NEXT_BUILDS=2
JOURNAL_MAX=200M

echo "[$(date '+%F %T')] backup retention start"

# 1) 每日运行时数据快照：保留最新 N 份
DAILY_DIR=/home/luke/runtime-data-backup/daily
if [ -d "$DAILY_DIR" ]; then
    cd "$DAILY_DIR" || exit 1
    ls -1dt */ 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | while read -r d; do
        echo "  rm daily/$d"
        rm -rf -- "$d"
    done
fi

# 2) DAL 每日 core dump：保留最新 N 份（含 sha256）
CORE_DIR=/home/luke/dreambuddy/19-数据访问层/data/backups
if [ -d "$CORE_DIR" ]; then
    cd "$CORE_DIR" || exit 1
    ls -1t dreambuddy_core_*.db 2>/dev/null | tail -n +$((KEEP_CORE_DUMPS + 1)) | while read -r f; do
        echo "  rm core/$f"
        rm -f -- "$f" "$f.sha256"
    done
    # 备份失败残留的 .tmp / .tmp-journal（>1 天且无进程占用），否则会永久滞留
    find . -maxdepth 1 -name 'dreambuddy_core_*.db.tmp*' -mtime +1 2>/dev/null | while read -r f; do
        if ! fuser -s "$f" 2>/dev/null; then
            echo "  rm core-tmp/$f"
            rm -f -- "$f"
        fi
    done
    # 认知库一次性 pre-* 备份：只保留最新 N 份
    ls -1t cognitive_memory*.db 2>/dev/null | tail -n +$((KEEP_COGNITIVE_DUMPS + 1)) | while read -r f; do
        echo "  rm cognitive/$f"
        rm -f -- "$f"
    done
fi

# 3) 前端构建备份：只保留最新 N 个 next-* 可回滚构建
BUILD_DIR=/home/luke/deploy-backups
if [ -d "$BUILD_DIR" ]; then
    cd "$BUILD_DIR" || exit 1
    ls -1dt next-* 2>/dev/null | tail -n +$((KEEP_NEXT_BUILDS + 1)) | while read -r d; do
        echo "  rm build/$d"
        rm -rf -- "$d"
    done
fi

# 4) 清理被中断的临时快照副本（>1 天且无进程占用）
SNAP_DIR=/home/luke/sync-snapshots
if [ -d "$SNAP_DIR" ]; then
    find "$SNAP_DIR" -maxdepth 1 -name '*.tmp*' -mtime +1 2>/dev/null | while read -r f; do
        if ! fuser -s "$f" 2>/dev/null; then
            echo "  rm snapshot/$f"
            rm -f -- "$f"
        fi
    done
fi

# 5) 压缩 systemd 日志
journalctl --vacuum-size="$JOURNAL_MAX" >/dev/null 2>&1 || true

echo "[$(date '+%F %T')] done: $(df -h / | awk 'NR==2 {print $3" used, "$4" avail, "$5}')"

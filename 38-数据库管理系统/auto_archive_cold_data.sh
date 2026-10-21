#!/bin/bash
# 自动降层归档 v4：
#   Part 1 - PostgreSQL data_center 库中超过 30 天的 records 归档并清理
#   Part 2 - L4 案例库中超过 60 天的案例文件打包归档并清理
#   Part 3 - 认知库中超过 90 天的冷记忆导出归档并清理
# 属于 38-数据库管理系统 SPEC，由 systemd timer 每日 04:30 触发
set -euo pipefail

PG="sudo docker exec dreambuddy-pg psql -U dreambuddy -d data_center -t -A"
ARCHIVE_DIR="/home/luke/dreambuddy/38-数据库管理系统/archive"
CASES_DIR="/home/luke/dreambuddy/11-易经推理系统/.workbuddy/memory_l4/cases"
COG_DB="/home/luke/dreambuddy/4-MEMORY/data/cognitive_memory.db"
LOG="$ARCHIVE_DIR/auto_archive.log"
DATE=$(date +%Y%m%d)

log() { echo "$(date '+%F %T') $1" >> "$LOG"; }

COLD_WHERE="substring(timestamp from 1 for 10) < to_char(now() - interval '30 days', 'YYYY-MM-DD')"

# ============ Part 1: PostgreSQL 冷数据归档（30 天阈值） ============
COUNT=$($PG -c "SELECT COUNT(*) FROM records WHERE $COLD_WHERE;")
if [ "$COUNT" -eq 0 ]; then
    log "[PG] 无冷数据需要归档"
else
    log "[PG] 开始归档：冷数据 $COUNT 条"
    FILE="$ARCHIVE_DIR/records_cold_$DATE.jsonl"
    ZST="$FILE.zst"
    $PG -c "SELECT json_build_object('id',id,'dedupe_key',dedupe_key,'source',source,'category',category,'sub_category',sub_category,'timestamp',timestamp,'metrics',metrics,'events',events,'timeseries',timeseries,'raw',raw,'schema_version',schema_version) FROM records WHERE $COLD_WHERE ORDER BY id;" > "$FILE"
    LINES=$(wc -l < "$FILE")
    if [ "$LINES" -ne "$COUNT" ]; then
        log "[PG] 校验失败：导出 $LINES 行 != 库内 $COUNT 条，中止并保留导出文件"
        exit 1
    fi
    zstd -f -q "$FILE"
    zstd -t "$ZST"
    $PG -c "DELETE FROM records WHERE $COLD_WHERE;" > /dev/null
    rm -f "$FILE"
    REMAIN=$($PG -c "SELECT COUNT(*) FROM records;")
    log "[PG] 归档完成：归档 $COUNT 条，主库剩余 $REMAIN 条"
fi

# ============ Part 2: L4 案例库归档（60 天阈值） ============
CASE_COUNT=$(find "$CASES_DIR" -type f -mtime +60 2>/dev/null | wc -l)
if [ "$CASE_COUNT" -eq 0 ]; then
    log "[CASES] 无 60 天前冷案例需要归档"
else
    log "[CASES] 开始归档：冷案例 $CASE_COUNT 个文件"
    CASE_TAR="$ARCHIVE_DIR/cases_cold_$DATE.tar.zst"
    find "$CASES_DIR" -type f -mtime +60 -print0 | tar --null -T - -cf - | zstd -f -q -o "$CASE_TAR"
    zstd -t "$CASE_TAR"
    TAR_COUNT=$(tar --zstd -tf "$CASE_TAR" | wc -l)
    if [ "$TAR_COUNT" -ne "$CASE_COUNT" ]; then
        log "[CASES] 校验失败：tar 内 $TAR_COUNT != 实际 $CASE_COUNT，中止且不删除任何文件"
        exit 1
    fi
    find "$CASES_DIR" -type f -mtime +60 -delete
    log "[CASES] 归档完成：$CASE_COUNT 个文件 → $(du -h "$CASE_TAR" | cut -f1) 的 $CASE_TAR"
fi

# ============ Part 3: 认知库冷记忆归档（90 天阈值） ============
COG_COUNT=$(sqlite3 "$COG_DB" "SELECT COUNT(*) FROM memories WHERE created_at < datetime('now','-90 days');" 2>/dev/null || echo 0)
if [ "$COG_COUNT" -eq 0 ]; then
    log "[COG] 无 90 天前冷记忆需要归档"
else
    log "[COG] 开始归档：冷记忆 $COG_COUNT 条"
    COG_FILE="$ARCHIVE_DIR/cognitive_cold_$DATE.jsonl"
    COG_ZST="$COG_FILE.zst"
    sqlite3 "$COG_DB" "SELECT json_object('id',id,'content',content,'quality_level',quality_level,'confidence',confidence,'tags',tags,'memory_type',memory_type,'created_at',created_at) FROM memories WHERE created_at < datetime('now','-90 days');" > "$COG_FILE"
    COG_LINES=$(wc -l < "$COG_FILE")
    if [ "$COG_LINES" -ne "$COG_COUNT" ]; then
        log "[COG] 校验失败：导出 $COG_LINES 行 != 库内 $COG_COUNT 条，中止并保留导出文件"
        exit 1
    fi
    zstd -f -q "$COG_FILE"
    zstd -t "$COG_ZST"
    sqlite3 "$COG_DB" "DELETE FROM memories WHERE created_at < datetime('now','-90 days');"
    sqlite3 "$COG_DB" "VACUUM;"
    rm -f "$COG_FILE"
    log "[COG] 归档完成：归档 $COG_COUNT 条冷记忆 → $COG_ZST"
fi

log "本次归档任务结束"

#!/bin/bash
# ============================================================
# 6-TRADING 腾讯云部署 — 04 Hermes 配置部署
# 用法: bash 04-hermes-config.sh
# 前置: 02 已完成, .env 已放到 /home/luke/.hermes/.env
# ============================================================
set -e

echo "=== Hermes 配置部署 ==="
HERMES_DEPLOY="/home/luke/tmp/deploy/hermes"
HERMES_HOME="/home/luke/.hermes"

# ── Skills ──
echo "Installing trading skills..."
cp -r "$HERMES_DEPLOY/skills/trading/"* "$HERMES_HOME/skills/trading/" 2>/dev/null || {
    mkdir -p "$HERMES_HOME/skills/trading"
    cp -r "$HERMES_DEPLOY/skills/trading/"* "$HERMES_HOME/skills/trading/"
}
echo "✓ Skills installed"

# ── Config ──
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$HERMES_DEPLOY/config.yaml" "$HERMES_HOME/config.yaml"
    echo "✓ config.yaml installed"
else
    echo "⚠ config.yaml already exists, skipping (preserve existing)"
fi

# ── Cron jobs ──
mkdir -p "$HERMES_HOME/cron"
cp "$HERMES_DEPLOY/cron/jobs.json" "$HERMES_HOME/cron/jobs.json"
echo "✓ Cron jobs installed (Linux paths)"

# ── Memories (optional) ──
if [ ! -f "$HERMES_HOME/memories/MEMORY.md" ]; then
    mkdir -p "$HERMES_HOME/memories"
    cp "$HERMES_DEPLOY/memories/"* "$HERMES_HOME/memories/" 2>/dev/null || true
    echo "✓ Memories installed"
else
    echo "⚠ Memories exist, skipping"
fi

# ── Permissions ──
chown -R luke:luke "$HERMES_HOME"

echo ""
echo "=== Hermes 配置完成 ==="
echo "Skills:    $(find $HERMES_HOME/skills/trading -name 'SKILL.md' | wc -l) trading skills"
echo "Cron:      $(python3 -c "import json; print(len(json.load(open('$HERMES_HOME/cron/jobs.json'))['jobs']))" 2>/dev/null || echo '?') jobs"
echo "Config:    $([ -f $HERMES_HOME/config.yaml ] && echo '✓' || echo '✗')"
echo ".env:      $([ -f $HERMES_HOME/.env ] && echo '✓' || echo '✗ MISSING — scp it!')"

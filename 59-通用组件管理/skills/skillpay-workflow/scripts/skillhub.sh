#!/usr/bin/env bash
# SkillHub CLI 封装：预检 + 发布（仅免费 Skill）
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
die() { echo "ERR: $*" >&2; exit 1; }
need_cli() { command -v skillhub >/dev/null || die "skillhub 未安装：curl -fsSL https://skillhub.cn/install/install.sh | bash -s -- --cli-only"; }

cmd="${1:-help}"; shift || true

case "$cmd" in
  check)
    need_cli
    skillhub --version 2>/dev/null | head -1
    skillhub auth whoami --json 2>/dev/null || echo "未登录（skillhub auth login）"
    ;;

  preflight)  # preflight <skill-dir>
    dir="${1:?用法: skillhub.sh preflight <skill-dir>}"; need_cli
    [[ -f "$dir/SKILL.md" ]] || die "缺少 $dir/SKILL.md"
    n=$(find "$dir" -type f | wc -l | tr -d ' ')
    sz=$(du -sh "$dir" | awk '{print $1}')
    sec=$(find "$dir" \( -name '.env*' -o -name '*.pem' -o -name '*.key' -o -name 'credentials*' \) -type f | head -5)
    echo "files=$n size=$sz"
    [[ "$n" -le 200 ]] || die "文件数 $n > 200"
    [[ -z "$sec" ]] || die "发现敏感文件：$sec"
    grep -qE '^slug:' "$dir/SKILL.md" || die "frontmatter 缺 slug"
    grep -qE '^version:' "$dir/SKILL.md" || die "frontmatter 缺 version"
    skillhub publish "$dir" --dry-run 2>&1 | tail -3
    ;;

  publish)  # publish <skill-dir> [--changelog "x"]
    dir="${1:?用法: skillhub.sh publish <skill-dir> [--changelog x]}"; shift
    need_cli
    chg="自动发布 $(date +%F)"
    [[ "${1:-}" == "--changelog" ]] && chg="${2:?changelog 不能为空}"
    skillhub publish "$dir" --changelog "$chg" --json
    ;;

  *)
    cat <<EOF
用法: bash scripts/skillhub.sh <命令>
  check                 CLI 版本 + 登录身份
  preflight <dir>       包卫生检查 + dry-run
  publish <dir> [--changelog "说明"]   发布（免费 Skill）
EOF
    ;;
esac

#!/bin/bash
# ============================================================
# review-extended.sh — 扩展维度评审脚本化（SPEC §一之五 D1/D4/D5/D7/D8）
#
# 原则：只读（SSH 只读查询），FAIL-OPEN（单条失败标注"未采集"并继续）
# 用法:
#   ./review-extended.sh d1|d4|d5|d7|d8|all [--no-save]
# 产出: .trae/documents/review-reports/YYYY-MM-DD-<dim>.md
# 周期建议: d1 每次部署后+每周；d4 每周；d5 每次训练后；d7 每月；d8 每周(水位)/每月(账单)
# ============================================================
set -uo pipefail

REMOTE="dreambuddy-remote"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$REPO_DIR/.trae/documents/review-reports"
TODAY="$(date +%F)"

DIM="${1:-all}"
SAVE=true
[ "${2:-}" = "--no-save" ] && SAVE=false
mkdir -p "$REPORT_DIR" 2>/dev/null || true

remote() { ssh -q -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE" "$@" 2>/dev/null || echo "(未采集：$REMOTE 不可达)"; }

# ── D1 代码一致性 ──
do_d1() {
    echo "## D1 代码一致性（$(date '+%F %T')）"
    echo '```'
    echo "-- 本地 --"
    echo "HEAD=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo 未采集)"
    echo "DIRTY=$(git -C "$REPO_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    echo "AHEAD_BEHIND=$(git -C "$REPO_DIR" rev-list --left-right --count origin/main...HEAD 2>/dev/null | awk '{print "behind="$1" ahead="$2}')"
    echo ""
    echo "-- 云端 --"
    remote 'cd /home/luke/dreambuddy 2>/dev/null && sudo -n git rev-parse --short HEAD 2>/dev/null; sudo -n git status --porcelain 2>/dev/null | wc -l'
    echo ""
    echo "-- 结论规则 --"
    echo "云端 HEAD == origin/main 且 云端 DIRTY 中无源码 M → 一致；否则登记 P1"
    echo '```'
}

# ── D4 数据链路 ──
do_d4() {
    echo "## D4 数据链路（$(date '+%F %T')）"
    echo '```'
    remote 'bash -s' <<'EOF'
echo "-- 快照/回填最新落盘 --"
for d in /home/luke/dreambuddy/18-数据获取中心/data /home/luke/dreambuddy/19-数据访问层/data; do
  [ -d "$d" ] && find "$d" -type f -newermt "-24 hours" -printf "%TY-%Tm-%Td %TH:%TM %p\n" 2>/dev/null | sort | tail -3
done
echo ""
echo "-- 最近一小时内更新的 json/jsonl/db（限 6 条）--"
sudo -n find /home/luke/dreambuddy/18-数据获取中心 /home/luke/dreambuddy/19-数据访问层 -type f \( -name "*.json" -o -name "*.db" \) -newermt "-2 hours" -printf "%TH:%TM %p\n" 2>/dev/null | sort | tail -6
echo ""
echo "-- API 字段可用性（取样）--"
for ep in http://127.0.0.1:8771/health http://127.0.0.1:8765; do
  code=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$ep" 2>/dev/null); echo "$ep -> ${code:-000}"
done
EOF
    echo ""
    echo "判定：超过 2h 无新落盘或 API 非 2xx/3xx → 登记 P1（数据延迟）"
    echo '```'
}

# ── D5 模型质量 ──
do_d5() {
    echo "## D5 模型质量（$(date '+%F %T')）"
    echo '```'
    python3 - "$REPO_DIR/12-三屏趋势系统/ml/models/registry.json" <<'EOF'
import json, sys
path = sys.argv[1]
try:
    reg = json.load(open(path))
except Exception as e:
    print(f"(未采集) registry 读取失败: {e}"); raise SystemExit(0)
cur = reg.get("current_version"); base = reg.get("baseline_version")
print(f"current={cur} baseline={base} next={reg.get('next_version')}")
for v in reg.get("versions", []):
    p = v.get("performance", {}) or {}
    wf = p.get("walk_forward_roc_auc"); gap = p.get("overfit_gap_accuracy")
    print(f"  {v.get('version'):>4} state={v.get('state','?'):<10} wf_auc={wf} overfit_gap={gap}")
ver = {v.get("version"): v for v in reg.get("versions", [])}
cp = (ver.get(cur) or {}).get("performance", {}) or {}
wf = cp.get("walk_forward_roc_auc"); gap = cp.get("overfit_gap_accuracy")
flags = []
if isinstance(gap, (int, float)) and gap > 0.35: flags.append(f"overfit_gap={gap:.3f}>0.35")
if isinstance(wf, (int, float)) and wf < 0.60: flags.append(f"walk_forward_auc={wf:.3f}<0.60")
print("结论: " + ("；".join(flags) if flags else "生产版指标在阈值内"))
EOF
    echo '```'
}

# ── D7 安全面 ──
do_d7() {
    echo "## D7 安全面（$(date '+%F %T')）"
    echo '```'
    remote 'bash -s' <<'EOF'
echo "-- ufw --"
sudo -n ufw status 2>/dev/null | head -6 || echo "(未采集: ufw)"
echo ""
echo "-- SSH 口令登录配置 --"
sudo -n sshd -T 2>/dev/null | grep -Ei "^(passwordauthentication|permitrootlogin)" || echo "(未采集: sshd -T)"
echo ""
echo "-- 凭据文件权限（仅路径与权限位，不输出内容）--"
sudo -n find /home/luke -maxdepth 3 -name ".env*" -printf "%m %p\n" 2>/dev/null | head -8
echo ""
echo "-- 监听端口（对外网卡）--"
ss -tln 2>/dev/null | awk 'NR>1 && $4 !~ /127.0.0.1/ {print $4}' | head -10
EOF
    echo "判定：口令登录应 disabled、root 登录应 no、.env 权限应为 600"
    echo '```'
}

# ── D8 成本/资源 ──
do_d8() {
    echo "## D8 成本/资源（$(date '+%F %T')）"
    echo '```'
    remote 'bash -s' <<'EOF'
free -h 2>/dev/null | head -2
echo ""
df -h / 2>/dev/null | tail -1
echo ""
echo "-- 内存 TOP5 --"
ps -eo pmem,comm --sort=-pmem 2>/dev/null | head -6
echo ""
echo "-- 仓库占用 --"
du -sh /home/luke/dreambuddy 2>/dev/null
echo ""
echo "-- timer 数量 --"
systemctl list-timers --all --no-legend --no-pager 2>/dev/null | wc -l
EOF
    if command -v gh >/dev/null 2>&1; then
        echo ""
        echo "-- GitHub Actions 用量（FAIL-OPEN）--"
        gh api /repos/yunya1991/Dreambuddy-V2/actions/runs --jq '.total_count' 2>/dev/null || echo "(未采集: gh 未授权)"
    fi
    echo "红线：内存 >85% 或磁盘 >80% → P1；月度总成本超预算 20% → 架构优化评审"
    echo '```'
}

save_one() {  # $1=dim, $2=report path, $3=content
    if ${SAVE}; then
        printf '# 三端评审报告 — %s (%s)\n\n%s\n' "$(echo "$1" | tr '[:lower:]' '[:upper:]')" "$TODAY" "$3" > "$2"
        echo "已归档 $2"
    else
        echo "$3"
    fi
}

case "$DIM" in
    d1|D1) RPT="$REPORT_DIR/$TODAY-d1.md"; FN=do_d1 ;;
    d4|D4) RPT="$REPORT_DIR/$TODAY-d4.md"; FN=do_d4 ;;
    d5|D5) RPT="$REPORT_DIR/$TODAY-d5.md"; FN=do_d5 ;;
    d7|D7) RPT="$REPORT_DIR/$TODAY-d7.md"; FN=do_d7 ;;
    d8|D8) RPT="$REPORT_DIR/$TODAY-d8.md"; FN=do_d8 ;;
    all)
        for d in d1 d4 d5 d7 d8; do
            save_one "$d" "$REPORT_DIR/$TODAY-$d.md" "$("do_$d")"
        done
        exit 0
        ;;
    *) echo "用法: $0 d1|d4|d5|d7|d8|all [--no-save]"; exit 2 ;;
esac

save_one "$DIM" "$RPT" "$("$FN")"

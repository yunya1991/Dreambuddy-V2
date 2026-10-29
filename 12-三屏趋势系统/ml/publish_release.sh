#!/usr/bin/env bash
# P1-3 本地辅训 → GitHub Release 模型分发通道：发布段
# 把 versions/<vX>/model.pkl + meta.json 打包为 GitHub Release（tag: ml-<vX>）
#
# 用法:
#   bash publish_release.sh --version v7 [--dry-run] [--models-dir DIR]
#
# 退出码: 0 成功 / 1 参数或文件校验失败 / 2 缺少 gh CLI
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/models"
VERSION=""
DRY_RUN=0

usage() {
    echo "用法: bash publish_release.sh --version vX [--dry-run] [--models-dir DIR]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="${2:-}"
            shift 2 || true
            ;;
        --models-dir)
            MODELS_DIR="${2:-}"
            shift 2 || true
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[错误] 未知参数: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    echo "[错误] 必须指定 --version vX" >&2
    usage >&2
    exit 1
fi

# gh 缺失 → 明确提示并退出 2（不崩溃）
if ! command -v gh >/dev/null 2>&1; then
    echo "[提示] 未检测到 gh CLI，无法发布产物。安装: brew install gh && gh auth login" >&2
    exit 2
fi

VERSION_DIR="$MODELS_DIR/versions/$VERSION"
MODEL_PATH="$VERSION_DIR/model.pkl"
META_PATH="$VERSION_DIR/meta.json"
TAG="ml-$VERSION"

# 产物存在性校验（硬失败）
if [[ ! -f "$MODEL_PATH" ]]; then
    echo "[错误] 缺少模型产物: $MODEL_PATH" >&2
    exit 1
fi
if [[ ! -f "$META_PATH" ]]; then
    echo "[错误] 缺少元数据: $META_PATH" >&2
    exit 1
fi

# 校验 meta.performance.walk_forward_roc_auc：缺失仅告警（FAIL-OPEN，不阻塞发布）
if ! python3 - "$META_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r") as f:
    meta = json.load(f)
perf = meta.get("performance") or {}
value = perf.get("walk_forward_roc_auc")
if value is None:
    sys.exit(2)
PY
then
    echo "[告警] meta.json 缺少 performance.walk_forward_roc_auc，仍继续发布（FAIL-OPEN）" >&2
fi

# 计算 sha256（供 manifest/校验使用）
CHECKSUM="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$MODEL_PATH")"
if [[ -z "$CHECKSUM" ]]; then
    echo "[错误] sha256 计算失败: $MODEL_PATH" >&2
    exit 1
fi

# manifest.json 由脚本生成到临时目录（version/checksum/metrics/created_at）
MANIFEST_TMPDIR="$(mktemp -d)"
MANIFEST_PATH="$MANIFEST_TMPDIR/manifest.json"
python3 - "$META_PATH" "$VERSION" "$CHECKSUM" "$MANIFEST_PATH" <<'PY'
import json
import sys
import time

meta_path, version, checksum, out_path = sys.argv[1:5]
with open(meta_path, "r") as f:
    meta = json.load(f)
perf = meta.get("performance") or {}
metrics = {k: v for k, v in perf.items() if isinstance(v, (int, float))}
payload = {
    "version": version,
    "checksum": checksum,
    "metrics": metrics,
    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "source": "local_aux_train",
}
with open(out_path, "w") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)
PY

if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "[错误] manifest.json 生成失败" >&2
    exit 1
fi

NOTES="本地辅训模型 ${VERSION}；walk_forward_roc_auc=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print((m.get("metrics") or {}).get("walk_forward_roc_auc", "N/A"))' "$MANIFEST_PATH")；sha256=${CHECKSUM}"

if [[ $DRY_RUN -eq 1 ]]; then
    # 只打印命令，不实际调用 gh
    echo "[dry-run] 将执行:"
    echo "gh release create \"$TAG\" \\"
    echo "  --title \"$TAG\" \\"
    echo "  --notes \"$NOTES\" \\"
    echo "  \"$MODEL_PATH\" \\"
    echo "  \"$META_PATH\" \\"
    echo "  \"$MANIFEST_PATH\""
    echo "[dry-run] checksum=$CHECKSUM"
    rm -rf "$MANIFEST_TMPDIR"
    exit 0
fi

gh release create "$TAG" \
    --title "$TAG" \
    --notes "$NOTES" \
    "$MODEL_PATH" \
    "$META_PATH" \
    "$MANIFEST_PATH"
RC=$?
rm -rf "$MANIFEST_TMPDIR"

if [[ $RC -ne 0 ]]; then
    echo "[错误] gh release create 失败（RC=$RC），tag=$TAG" >&2
    exit 1
fi
echo "[完成] 已发布 release ${TAG}（assets: model.pkl / meta.json / manifest.json）"

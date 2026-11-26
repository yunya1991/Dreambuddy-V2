#!/usr/bin/env python3
"""site-blog.publish：把一份 Markdown 研究稿发布到 59 研究博客。

安全边界：
- 必须显式 --allow-write；
- 只接受 front matter 完整的 md；slug 只允许 a-z0-9-；
- 配图只允许本地文件，复制到 platform/site/assets/charts/<run_id>/；
- build_site.py --write 后再 --check；失败不部署；
- 默认部署；--no-deploy 只做本地构建与校验；
- 远端目录不写死：取 --remote-dir 或 DREAMBUDDY_SITE_REMOTE_DIR，缺失则拒绝部署。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SITE_DIR = ROOT / "platform" / "site"
SITE_SCRIPTS = SITE_DIR / "scripts"
sys.path.insert(0, str(SITE_SCRIPTS))

import build_site  # noqa: E402

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9-]+", "-", str(value or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)[:80]


def _component(value: str) -> str:
    """目录名：保留大小写（run_id 含 T），只清掉路径分隔符。"""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-")
    return text[:80]


def _fail(message: str, code: int = 1) -> int:
    print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False))
    return code


def _validate(meta: dict, name: str) -> None:
    for key in ("title", "date", "summary"):
        if not meta.get(key):
            raise ValueError(f"{name} 缺少 front matter 字段 {key}")
    if not DATE_RE.match(str(meta["date"])):
        raise ValueError(f"{name} 的 date 必须是 YYYY-MM-DD")


def _series_order(posts_dir: Path, series: str, slug: str) -> int:
    """同一系列内递增 order；已存在的 slug 幂等复用原 order。"""
    existing = posts_dir / f"{slug}.md"
    if existing.is_file():
        try:
            meta, _ = build_site.split_front_matter(
                existing.read_text(encoding="utf-8"), existing.name
            )
            return int(meta.get("series_order") or 1)
        except (ValueError, build_site.SiteError, TypeError):
            pass
    orders = []
    for path in posts_dir.glob("*.md"):
        try:
            meta, _ = build_site.split_front_matter(path.read_text(encoding="utf-8"), path.name)
        except (ValueError, build_site.SiteError):
            continue
        if str(meta.get("series") or "") == series:
            try:
                orders.append(int(meta.get("series_order") or 0))
            except (TypeError, ValueError):
                continue
    return max(orders, default=0) + 1


def _http_status(url: str, retries: int = 3) -> int:
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=8) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404, 502, 503) or attempt == retries - 1:
                return int(exc.code)
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return 0


def main() -> int:
    # 统一 CLI（dreambuddy run site-blog publish ...）不会重复传子命令，
    # 直接调脚本时仍保留 publish 子命令；两种入口都兼容。
    if len(sys.argv) > 1 and sys.argv[1] != "publish":
        sys.argv.insert(1, "publish")
    parser = argparse.ArgumentParser(description="发布一篇研究博客到 59 站点")
    sub = parser.add_subparsers(dest="action", required=True)
    pub = sub.add_parser("publish", help="写 md + 拷图 + build + check + rsync + HTTP 校验")
    pub.add_argument("--file", required=True, help="Markdown 路径")
    pub.add_argument("--slug", default="", help="文章 slug（a-z0-9-）；省略时由标题派生")
    pub.add_argument("--run-id", default="", help="内容 run id，用于图片目录")
    pub.add_argument("--image", action="append", default=[], help="配图路径，可重复")
    pub.add_argument("--no-deploy", action="store_true", help="只构建与校验，不 rsync")
    pub.add_argument("--ssh", default="ubuntu@49.233.123.96")
    pub.add_argument(
        "--remote-dir",
        default=os.environ.get("DREAMBUDDY_SITE_REMOTE_DIR", ""),
        help="远端部署目录（留空取 DREAMBUDDY_SITE_REMOTE_DIR；仍为空则拒绝部署）",
    )
    pub.add_argument("--origin", default="http://49.233.123.96:8081")
    pub.add_argument("--allow-write", action="store_true", help="必须显式授权写入")
    pub.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not (args.allow_write or os.environ.get("DREAMBUDDY_ALLOW_WRITE") == "1"):
        return _fail("E_GATE: 缺少 --allow-write", 2)
    source = Path(args.file)
    if not source.is_file():
        return _fail(f"Markdown 不存在: {source}", 2)
    text = source.read_text(encoding="utf-8")
    try:
        meta, _ = build_site.split_front_matter(text, source.name)
        _validate(meta, source.name)
    except (ValueError, build_site.SiteError) as exc:
        return _fail(str(exc), 2)

    run_id = _component(args.run_id or source.parent.name) or "manual"
    slug = _slug(args.slug) or _slug(str(meta["title"]))
    if not slug:
        digest = hashlib.sha256(str(meta["title"]).encode("utf-8")).hexdigest()[:8]
        slug = "research-{}-{}".format(str(meta["date"]).replace("-", ""), digest)
    if not build_site.SLUG_RE.match(slug):
        return _fail(f"slug 非法: {slug}", 2)

    posts_dir = SITE_DIR / "blog" / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    series = str(meta.get("series") or "").strip()
    if series:
        order = _series_order(posts_dir, series, slug)
        text = re.sub(r"(?m)^series_order:\s*\d+\s*$", f"series_order: {order}", text)
    post_path = posts_dir / f"{slug}.md"
    post_path.write_text(text, encoding="utf-8")

    image_dir = SITE_DIR / "assets" / "charts" / run_id
    copied = []
    image_dir.mkdir(parents=True, exist_ok=True)
    for item in args.image or []:
        image = Path(item)
        if not image.is_file():
            return _fail(f"配图不存在: {image}", 2)
        target = image_dir / image.name
        if image.resolve() != target.resolve():
            shutil.copy2(image, target)
        copied.append(str(target))
    expected = f"../assets/charts/{run_id}/"
    for ref in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if not ref.startswith(expected):
            return _fail(f"配图引用与 run_id 不一致: {ref}（期望 {expected}）", 2)

    build = subprocess.run(
        [sys.executable, str(SITE_SCRIPTS / "build_site.py"), "--write"],
        cwd=str(SITE_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build.returncode != 0:
        return _fail("build_failed: " + (build.stderr or build.stdout)[-500:], 1)
    check = subprocess.run(
        [sys.executable, str(SITE_SCRIPTS / "build_site.py"), "--check"],
        cwd=str(SITE_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check.returncode != 0:
        return _fail("check_failed: " + (check.stderr or check.stdout)[-500:], 1)

    deployed = False
    if not args.no_deploy:
        if not args.remote_dir:
            return _fail("E_GATE: 未设置 --remote-dir 或 DREAMBUDDY_SITE_REMOTE_DIR", 2)
        sync = subprocess.run(
            [
                "rsync",
                "-av",
                "--delete",
                str(SITE_DIR) + "/",
                "{}:{}/".format(args.ssh, args.remote_dir),
            ],
            cwd=str(SITE_DIR),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if sync.returncode != 0:
            return _fail("rsync_failed: " + (sync.stderr or sync.stdout)[-500:], 1)
        deployed = True

    url = "{}/blog/{}.html".format(args.origin.rstrip("/"), slug)
    http_status = _http_status(url) if deployed else 0
    ok = (http_status == 200) if deployed else True
    payload = {
        "schema_version": "1.0",
        "command": "site-blog.publish",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "done" if ok else "failed",
        "slug": slug,
        "url": url,
        "build_ok": True,
        "deployed": deployed,
        "http_status": http_status,
        "images": copied,
        "post": str(post_path),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

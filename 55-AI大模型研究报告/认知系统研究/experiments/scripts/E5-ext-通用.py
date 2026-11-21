"""E5 通用版：在任意 Python 仓库上估计两类事实的失效风险率 λ。

用法：
    python3 e5_ext.py <repo_path> <work_dir> <out_json> [windows] [n_per]

类别：
    F1   fact = "符号 X 定义在文件 F"
    F2a  fact = "环境变量 X 的默认值是 V"（源码 getenv 第二参数）

口径（与 05 文档 §4 一致，不得就地修改）：
    - 行号漂移不算失效
    - 符号不再定义于 F = 失效
    - 配置键不再出现，或默认值改变 = 失效
    - 到 HEAD 仍成立 = 删失
"""

import ast
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys

REPO = sys.argv[1]
WORK = sys.argv[2]
OUT = sys.argv[3]
WINDOWS = [int(x) for x in (sys.argv[4].split(",") if len(sys.argv) > 4 else ["30", "90", "150"])]
N_PER = int(sys.argv[5]) if len(sys.argv) > 5 else 80
HOT = len(sys.argv) > 6 and sys.argv[6] == "hot"  # 按被引用次数加权，抽公共 API
SEED = 20261118
SKIP_DIR = (
    "node_modules/",
    "venv/",
    ".venv/",
    "site-packages/",
    "dist/",
    "build/",
    "migrations/",
    "__pycache__/",
    "vendor/",
    "third_party/",
)
GENERIC = {"setUp", "tearDown", "main", "run", "handler", "execute", "update", "render"}
SENSITIVE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|MNEMONIC|SIGNER|CREDENTIAL)", re.I)
DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)


def git(*a):
    return subprocess.run(
        ["git"] + list(a), cwd=REPO, capture_output=True, text=True, errors="replace"
    ).stdout


def d(s):
    return dt.datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S")


def commit_date(h):
    return d(git("log", "-1", "--format=%ad", "--date=iso", h))


def defs_in(src):
    try:
        tree = ast.parse(src)
        return [
            (n.name, n.lineno)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
    except SyntaxError:
        return [(m.group(1), src[: m.start()].count("\n") + 1) for m in DEF_RE.finditer(src)]


def env_defaults(src):
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or len(n.args) < 2:
            continue
        f, ok = n.func, False
        if isinstance(f, ast.Name) and f.id == "getenv":
            ok = True
        elif isinstance(f, ast.Attribute) and f.attr == "getenv":
            ok = True
        elif (
            isinstance(f, ast.Attribute)
            and f.attr == "get"
            and isinstance(f.value, ast.Attribute)
            and f.value.attr == "environ"
        ):
            ok = True
        if not ok:
            continue
        a0, a1 = n.args[0], n.args[1]
        if (
            isinstance(a0, ast.Constant)
            and isinstance(a0.value, str)
            and isinstance(a1, ast.Constant)
            and isinstance(a1.value, str)
        ):
            out.append((a0.value.strip(), a1.value.strip()))
    return out


def ref_counts(root):
    """符号名 -> 全仓出现次数（粗粒度，用于按使用度加权）。"""
    cnt = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if x not in {".git", "__pycache__"}]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if any(s in rel for s in SKIP_DIR):
                continue
            try:
                src = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for m in re.finditer(r"\b([A-Za-z_]\w{5,})\b", src):
                cnt[m.group(1)] = cnt.get(m.group(1), 0) + 1
    return cnt


def build_index(root):
    defs, envs = {}, {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if x not in {".git", "__pycache__"}]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if any(s in rel for s in SKIP_DIR):
                continue
            try:
                src = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for name, line in defs_in(src):
                defs.setdefault(name, []).append((rel, line))
            for k, v in env_defaults(src):
                if not SENSITIVE.search(k):
                    envs.setdefault(k, set()).add(v)
    return (defs, {k: next(iter(v)) for k, v in envs.items() if len(v) == 1})


def snapshot(h, dest):
    if os.path.isdir(dest) and os.listdir(dest):
        return
    os.makedirs(dest, exist_ok=True)
    p1 = subprocess.Popen(["git", "archive", "--format=tar", h], cwd=REPO, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["tar", "-x", "-C", dest], stdin=p1.stdout)
    p1.stdout.close()
    p2.communicate()


def show(h, p):
    r = subprocess.run(
        ["git", "show", f"{h}:{p}"], cwd=REPO, capture_output=True, text=True, errors="replace"
    )
    return r.stdout if r.returncode == 0 else None


def file_log(p):
    out = []
    for ln in git("log", "--format=%H|%ad", "--date=iso", "--", p).splitlines():
        if "|" in ln:
            h, iso = ln.split("|", 1)
            out.append((d(iso), h))
    return sorted(out)


def first_change(c0date, p, sym=None, cls="F1", v0=None):
    for when, h in file_log(p):
        if when <= c0date:
            continue
        src = show(h, p)
        if src is None:
            return when
        if cls == "F1":
            if not any(n == sym for n, _ in defs_in(src)):
                return when
        else:
            vals = {v for k, v in env_defaults(src) if k == sym}
            if not vals or v0 not in vals:
                return when
    return None


def mle(s):
    T = sum(t for t, _ in s)
    return (sum(1 for _, e in s if e) / T) if T else float("nan")


def boot(s, reps=1000):
    r = random.Random(SEED)
    n = len(s)
    v = sorted(mle([s[r.randrange(n)] for _ in range(n)]) for _ in range(reps))
    v = [x for x in v if x == x]
    return v[int(0.025 * len(v))], v[int(0.975 * len(v))]


def main():
    os.makedirs(WORK, exist_ok=True)
    head = git("rev-parse", "HEAD").strip()
    head_date = commit_date(head)
    rnd = random.Random(SEED)
    recs = []
    for w in WINDOWS:
        iso = (head_date - dt.timedelta(days=w)).strftime("%Y-%m-%d 00:00:00")
        h = git("rev-list", "-1", "--before=" + iso, "HEAD").strip()
        if not h:
            print(f"[skip] {w}d")
            continue
        cdate = commit_date(h)
        dest = os.path.join(WORK, f"snap_{w}")
        snapshot(h, dest)
        defs, envs = build_index(dest)
        uniq = sorted(
            (n, v[0][0], v[0][1])
            for n, v in defs.items()
            if len(v) == 1 and len(n) >= 6 and not n.startswith("__") and n not in GENERIC
        )
        if HOT:
            cnt = ref_counts(dest)
            scored = [(cnt.get(n, 0), n, p, lvl) for n, p, lvl in uniq]
            scored.sort(reverse=True)
            top = scored[: max(N_PER * 4, int(len(scored) * 0.2))]
            uniq = [(n, p, lvl) for _, n, p, lvl in top]
        rnd.shuffle(uniq)
        print(
            f"[win {w}] commit={h[:8]} date={cdate.date()} uniq_defs={len(uniq)} env_keys={len(envs)}"
        )
        for name, path, line in uniq[:N_PER]:
            br = first_change(cdate, path, name, "F1")
            recs.append(
                {
                    "cls": "F1",
                    "window": w,
                    "key": name,
                    "file": path,
                    "line": line,
                    "dur": (br - cdate).days if br else (head_date - cdate).days,
                    "event": bool(br),
                }
            )
        print(f"        env_keys_in_snapshot={len(envs)} (F2a 另跑)")

    summary = {
        "repo": REPO,
        "head": head[:12],
        "head_date": head_date.strftime("%Y-%m-%d"),
        "windows": WINDOWS,
        "n_per": N_PER,
        "seed": SEED,
        "classes": {},
    }
    for cls in ("F1", "F2a"):
        s = [(r["dur"], r["event"]) for r in recs if r["cls"] == cls]
        if not s:
            continue
        lo, hi = boot(s)
        summary["classes"][cls] = {
            "n": len(s),
            "events": sum(1 for _, e in s if e),
            "exposure": sum(t for t, _ in s),
            "lambda": round(mle(s), 6),
            "ci95": [round(lo, 6), round(hi, 6)],
            "half_life_days": round(0.693147 / mle(s), 1) if mle(s) else None,
        }
    summary["records"] = recs
    json.dump(summary, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary["classes"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

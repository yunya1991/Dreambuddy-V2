"""E5 / F1：代码位置事实的失效风险率 λ 估计。

口径（必须先固定，否则不可复现）：
  fact = "符号 X 定义在文件 F 中"
  - 行号漂移不算失效（grep 能给出当前行号，指针仍然可用）
  - 符号不再定义于 F（被移走或删除）才算失效事件
输出：E5-f1.json
"""

import ast
import datetime as dt
import json
import os
import random
import re
import subprocess

REPO = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
WORK = "/tmp/e5"
OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/E5-f1.json"
WINDOWS = [0, 30, 90, 150]
N_PER = 60
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
)


def git(*args, check=False):
    r = subprocess.run(
        ["git"] + list(args), cwd=REPO, capture_output=True, text=True, errors="replace"
    )
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout


def d(s):
    return dt.datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S")


def commit_before(iso):
    h = git("rev-list", "-1", "--before=" + iso, "HEAD").strip()
    return h


def commit_date(h):
    return d(git("log", "-1", "--format=%ad", "--date=iso", h))


DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.M)


def defs_in(src):
    """返回 (name, lineno) 列表；语法错误时退回正则。"""
    try:
        tree = ast.parse(src)
        out = []
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((n.name, n.lineno))
        return out
    except SyntaxError:
        return [(m.group(1), src[: m.start()].count("\n") + 1) for m in DEF_RE.finditer(src)]


def build_index(root):
    """符号名 -> [(relpath, lineno)]"""
    idx = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if x not in {".git", "__pycache__"}]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            if any(s in rel.replace(os.sep, "/") for s in SKIP_DIR):
                continue
            try:
                src = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for name, line in defs_in(src):
                idx.setdefault(name, []).append((rel, line))
    return idx


def snapshot(h, dest):
    if os.path.isdir(dest) and os.listdir(dest):
        return
    os.makedirs(dest, exist_ok=True)
    p1 = subprocess.Popen(["git", "archive", "--format=tar", h], cwd=REPO, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["tar", "-x", "-C", dest], stdin=p1.stdout)
    p1.stdout.close()
    p2.communicate()


def still_defined(commit, path, sym):
    """该 commit 上，path 是否仍定义 sym。"""
    r = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if r.returncode != 0:
        return False
    return any(n == sym for n, _ in defs_in(r.stdout))


def first_break(commit0, path, sym):
    """返回 (失效 commit 日期, 失效 commit) 或 None（删失）。"""
    log = git("log", "--format=%H|%ad", "--date=iso", "--", path).strip().splitlines()
    chain = []
    for line in log:
        if "|" not in line:
            continue
        h, iso = line.split("|", 1)
        try:
            chain.append((d(iso), h))
        except ValueError:
            continue
    chain.sort()  # oldest first
    c0 = commit_date(commit0)
    for when, h in chain:
        if when <= c0:
            continue
        if not still_defined(h, path, sym):
            return when, h
    return None


def km(samples):
    """Kaplan-Meier：返回 [(t, S(t))]。samples: [(duration, event:bool)]"""
    pts = sorted(samples)
    n = len(pts)
    at_risk = n
    s = 1.0
    curve = []
    i = 0
    while i < n:
        t = pts[i][0]
        deaths = 0
        while i < n and pts[i][0] == t:
            if pts[i][1]:
                deaths += 1
            i += 1
        if deaths and at_risk:
            s *= 1 - deaths / at_risk
            curve.append((t, round(s, 4)))
        at_risk -= i - (i - 0)  # placeholder, fixed below
        break
    # 重写：逐事件处理
    curve = []
    s = 1.0
    times = sorted({t for t, e in samples if e})
    for t in times:
        d_t = sum(1 for tt, e in samples if tt == t and e)
        n_t = sum(1 for tt, _ in samples if tt >= t)
        if n_t:
            s *= 1 - d_t / n_t
            curve.append((t, round(s, 4)))
    return curve


def mle_exp(samples):
    d_ = sum(1 for _, e in samples if e)
    T = sum(t for t, _ in samples)
    return (d_ / T) if T else float("nan")


def bootstrap(samples, reps=1000):
    rnd = random.Random(SEED)
    out = []
    n = len(samples)
    for _ in range(reps):
        bs = [samples[rnd.randrange(n)] for _ in range(n)]
        out.append(mle_exp(bs))
    out = [x for x in out if x == x]
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def main():
    os.makedirs(WORK, exist_ok=True)
    head = git("rev-parse", "HEAD").strip()
    head_date = commit_date(head)
    rnd = random.Random(SEED)
    records = []
    for w in WINDOWS:
        iso = (head_date - dt.timedelta(days=w)).strftime("%Y-%m-%d 00:00:00")
        h = commit_before(iso)
        if not h:
            print(f"[skip] window {w}: no commit before {iso}")
            continue
        cdate = commit_date(h)
        dest = os.path.join(WORK, f"snap_{w}")
        snapshot(h, dest)
        idx = build_index(dest)
        uniq = [
            (name, v[0][0], v[0][1])
            for name, v in idx.items()
            if len(v) == 1
            and len(name) >= 6
            and not name.startswith("__")
            and name
            not in {"setUp", "tearDown", "main", "run", "handler", "execute", "update", "render"}
        ]
        rnd.shuffle(uniq)
        picked = uniq[:N_PER]
        print(f"[win {w}] commit={h[:8]} date={cdate.date()} files={len(idx)} picked={len(picked)}")
        for name, path, line in picked:
            br = first_break(h, path, name)
            if br:
                dur = (br[0] - cdate).days
                rec = {
                    "window": w,
                    "sym": name,
                    "file": path,
                    "line": line,
                    "born": cdate.strftime("%Y-%m-%d"),
                    "event": True,
                    "dur_days": dur,
                    "break_commit": br[1][:8],
                }
            else:
                dur = (head_date - cdate).days
                rec = {
                    "window": w,
                    "sym": name,
                    "file": path,
                    "line": line,
                    "born": cdate.strftime("%Y-%m-%d"),
                    "event": False,
                    "dur_days": dur,
                    "break_commit": None,
                }
            records.append(rec)

    samples = [(r["dur_days"], r["event"]) for r in records]
    d_count = sum(1 for _, e in samples if e)
    lo, hi = bootstrap(samples)
    summary = {
        "instrument": {
            "repo": REPO,
            "head": head[:12],
            "head_date": head_date.strftime("%Y-%m-%d"),
            "windows": WINDOWS,
            "n_per_window": N_PER,
            "seed": SEED,
        },
        "n": len(samples),
        "events": d_count,
        "censored": len(samples) - d_count,
        "exposure_days": sum(t for t, _ in samples),
        "lambda_per_day": round(mle_exp(samples), 6),
        "lambda_ci95": [round(lo, 6), round(hi, 6)],
        "half_life_days": round(0.693147 / mle_exp(samples), 1) if mle_exp(samples) else None,
        "by_window": {},
        "km": km(samples),
        "records": records,
    }
    for w in WINDOWS:
        sub = [(r["dur_days"], r["event"]) for r in records if r["window"] == w]
        if sub:
            summary["by_window"][str(w)] = {
                "n": len(sub),
                "events": sum(1 for _, e in sub if e),
                "lambda": round(mle_exp(sub), 6),
            }
    with open(OUT, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("records", "km")},
            ensure_ascii=False,
            indent=1,
        )
    )
    print("km:", summary["km"][:12])


if __name__ == "__main__":
    main()

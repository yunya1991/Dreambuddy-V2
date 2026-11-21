"""E5 / F2 v2：配置值事实的失效风险率 λ。

修正：
  1. F2a 只认 os.getenv / os.environ.get / environ.get，不再把 dict.get 当配置；
  2. 敏感键（SECRET/KEY/TOKEN/PASSWORD/PRIVATE/SIGNER...）整体排除——协议要求敏感域 REJECT；
  3. 值只存 sha256 前 8 位，原始值不入盘、不打印；
  4. 「值改变」不再记 dur=None，改为回溯首个变更 commit 得到真实失效时刻。
"""

import ast
import datetime as dt
import hashlib
import json
import os
import random
import re
import subprocess

REPO = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
WORK = "/tmp/e5"
OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/E5-f2.json"
WINDOWS = [30, 90, 150]
N_PER = 60
SEED = 20261118
SKIP_DIR = ("node_modules/", "venv/", ".venv/", "site-packages/", "dist/", "build/", "__pycache__/")
SENSITIVE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|MNEMONIC|SIGNER|CREDENTIAL|API_?KEY|^KEY$|_KEY$)", re.I
)
ENVNAME = re.compile(r"^\.env(\..+)?$|^.+\.env$")


def h8(v):
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def git(*a):
    return subprocess.run(
        ["git"] + list(a), cwd=REPO, capture_output=True, text=True, errors="replace"
    ).stdout


def d(s):
    return dt.datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S")


def commit_date(h):
    return d(git("log", "-1", "--format=%ad", "--date=iso", h))


def norm(v):
    v = v.strip().strip('"').strip("'")
    return v.lower() if v.lower() in ("true", "false") else v


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
        elif (
            isinstance(f, ast.Attribute)
            and f.attr == "get"
            and isinstance(f.value, ast.Name)
            and f.value.id == "environ"
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
            out.append((a0.value.strip(), norm(a1.value)))
    return out


def dotenv_pairs(src):
    out = []
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            out.append((k, norm(v.split(" #")[0])))
    return out


def index_at(h, root):
    a, b = {}, {}
    if not (root and os.path.isdir(root)):
        return {"F2a": {}, "F2b": {}}
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if x not in {".git", "__pycache__"}]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if any(s in rel for s in SKIP_DIR):
                continue
            try:
                src = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            if fn.endswith(".py"):
                for k, v in env_defaults(src):
                    if not SENSITIVE.search(k):
                        a.setdefault(k, set()).add(v)
            elif ENVNAME.match(fn):
                for k, v in dotenv_pairs(src):
                    if not SENSITIVE.search(k):
                        b.setdefault(k, set()).add(v)
    return {
        "F2a": {k: next(iter(v)) for k, v in a.items() if len(v) == 1},
        "F2b": {k: next(iter(v)) for k, v in b.items() if len(v) == 1},
    }


def files_with_key(h, key, cls):
    """快照内出现该键的 .py 文件（F2b 则给 .env 文件名）。用 grep 粗筛即可。"""
    out = []
    for line in git("grep", "-l", "-E", re.escape(key), h, "--", "*.py", "*.env*").splitlines():
        out.append(line.split(":", 1)[1] if ":" in line else line)
    return out


def value_at(h, path, key, cls):
    src = subprocess.run(
        ["git", "show", f"{h}:{path}"], cwd=REPO, capture_output=True, text=True, errors="replace"
    ).stdout
    if not src:
        return None
    pairs = env_defaults(src) if cls == "F2a" else dotenv_pairs(src)
    vals = {v for k, v in pairs if k == key}
    return next(iter(vals)) if len(vals) == 1 else None


def first_change(c0, c0date, paths, key, cls, v0):
    cache = {}
    for p in paths:
        chain = cache.setdefault(
            p,
            sorted(
                [
                    (d(iso), hh)
                    for hh, iso in (
                        ln.split("|", 1)
                        for ln in git("log", "--format=%H|%ad", "--date=iso", "--", p).splitlines()
                        if "|" in ln
                    )
                ]
            ),
        )
        for when, hh in chain:
            if when <= c0date:
                continue
            cur = value_at(hh, p, key, cls)
            if cur is not None and cur != v0:
                return when
    return None


def main():
    head = git("rev-parse", "HEAD").strip()
    head_date = commit_date(head)
    today = index_at(head, os.path.join(WORK, "snap_0"))
    rnd = random.Random(SEED)
    records = []

    for w in WINDOWS:
        iso = (head_date - dt.timedelta(days=w)).strftime("%Y-%m-%d 00:00:00")
        h = git("rev-list", "-1", "--before=" + iso, "HEAD").strip()
        dest = os.path.join(WORK, f"snap_{w}")
        if not h or not (os.path.isdir(dest) and os.listdir(dest)):
            continue
        cdate = commit_date(h)
        idx = index_at(h, dest)
        for cls in ("F2a", "F2b"):
            alive = [(k, v) for k, v in idx[cls].items() if k in today[cls]]
            gone = [(k, v) for k, v in idx[cls].items() if k not in today[cls]]
            rnd.shuffle(alive)
            rnd.shuffle(gone)
            for k, v in alive[:N_PER] + gone[: N_PER // 4]:
                if today[cls].get(k) == v:
                    records.append(
                        {
                            "window": w,
                            "cls": cls,
                            "key": k,
                            "v_hash": h8(v),
                            "event": False,
                            "dur_days": (head_date - cdate).days,
                            "why": "仍成立",
                        }
                    )
                elif k not in today[cls]:
                    records.append(
                        {
                            "window": w,
                            "cls": cls,
                            "key": k,
                            "v_hash": h8(v),
                            "event": True,
                            "dur_days": (head_date - cdate).days,
                            "why": "键消失(上界)",
                        }
                    )
                else:
                    fc = first_change(h, cdate, files_with_key(h, k, cls), k, cls, v)
                    if fc:
                        records.append(
                            {
                                "window": w,
                                "cls": cls,
                                "key": k,
                                "v_hash": h8(v),
                                "event": True,
                                "dur_days": (fc - cdate).days,
                                "why": "值改变",
                            }
                        )
                    else:
                        records.append(
                            {
                                "window": w,
                                "cls": cls,
                                "key": k,
                                "v_hash": h8(v),
                                "event": True,
                                "dur_days": (head_date - cdate).days,
                                "why": "值改变(上界)",
                            }
                        )

    json.dump(
        {
            "head": head[:12],
            "head_date": head_date.strftime("%Y-%m-%d"),
            "note": "只存值哈希，原始值不入盘",
            "records": records,
        },
        open(OUT, "w"),
        ensure_ascii=False,
        indent=1,
    )
    for cls in ("F2a", "F2b"):
        sub = [r for r in records if r["cls"] == cls]
        ev = [r for r in sub if r["event"]]
        T = sum(r["dur_days"] for r in sub)
        lam = len(ev) / T if T else float("nan")
        print(
            f"{cls}: n={len(sub)} events={len(ev)} ({len(ev)/max(1,len(sub)):.1%}) exposure={T}d lambda={lam:.5f}/d half={0.693/lam if lam else 0:.0f}d"
        )
        reasons = {}
        for r in ev:
            reasons[r["why"]] = reasons.get(r["why"], 0) + 1
        print("   reasons:", reasons)
        for r in ev[:6]:
            print("   ", r["window"], r["key"], r["dur_days"], r["why"])


if __name__ == "__main__":
    main()

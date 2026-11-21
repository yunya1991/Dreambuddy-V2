"""E5 / F3 v2：偏好/决策类事实的候选提取（含 blame 定日期）。

修正 v1：
  1. 文档候选的时间改用 git blame 取该行的提交日期，不再用文件最后修改时间；
  2. 决策标记收紧为显式否决类，去掉「统一/改为/必须」这类中性词；
  3. 取消不可靠的自动推翻判定，改为「严格实体重叠」的疑似标记，且默认判为未推翻。

输出：E5-f3-candidates.json
"""

import datetime as dt
import json
import os
import re
import subprocess

REPO = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/E5-f3-candidates.json"
DOC_ROOT = os.path.join(REPO, "55-AI大模型研究报告")

DECISION_COMMIT = (
    "回退",
    "禁用",
    "停用",
    "放弃",
    "不允许",
    "禁止",
    "否决",
    "不再使用",
    "恢复至",
    "撤下",
)
DECISION_DOC = (
    "否决",
    "放弃",
    "不采用",
    "不纳入",
    "不再",
    "禁止",
    "不允许",
    "已回退",
    "作废",
    "停用",
)
REVERSAL = ("推翻了", "已回退", "改用", "重新启用", "撤销", "作废", "不再成立", "修正为")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


def git(*a):
    return subprocess.run(
        ["git"] + list(a), cwd=REPO, capture_output=True, text=True, errors="replace"
    ).stdout


def parse(s):
    try:
        return dt.datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def blame_date(rel, line):
    out = git("blame", "-L", f"{line},{line}", "--porcelain", "--", rel)
    sha = out.split(" ", 1)[0].strip() if out else ""
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return None
    d = git("show", "-s", "--format=%ad", "--date=short", sha).strip()
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else None


def main():
    raw = git("log", "--format=@@@%H|%ad|%s", "--date=iso")
    commits = []
    for line in raw.splitlines():
        if line.startswith("@@@"):
            h, when, subj = line[3:].split("|", 2)
            t = parse(when)
            if t:
                commits.append((t, h, subj))
    commits.sort()

    cands = []
    for t, h, subj in commits:
        if any(k in subj for k in DECISION_COMMIT):
            cands.append(
                {
                    "src": "commit",
                    "t": t.strftime("%Y-%m-%d"),
                    "ref": h[:8],
                    "text": subj.strip()[:200],
                }
            )

    for dp, dns, fns in os.walk(DOC_ROOT):
        dns[:] = [x for x in dns if x not in {".git", "__pycache__", "experiments"}]
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, REPO).replace(os.sep, "/")
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, ln in enumerate(lines, 1):
                s = ln.strip().lstrip("-*| ").strip()
                if len(s) < 12 or s.startswith("#") or s.startswith("```"):
                    continue
                if not any(k in s for k in DECISION_DOC):
                    continue
                d = blame_date(rel, i)
                if not d:
                    continue
                cands.append({"src": "doc", "t": d, "ref": f"{rel}:{i}", "text": s[:200]})

    # 严格实体重叠的疑似推翻（仅标记，不作真值）
    for i, c in enumerate(cands):
        ids = set(IDENT.findall(c["text"]))
        c["suspect_reversed"] = False
        c["suspect_evidence"] = ""
        if not ids:
            continue
        for j, o in enumerate(cands):
            if j <= i or o["t"] <= c["t"]:
                continue
            if (ids & set(IDENT.findall(o["text"]))) and any(k in o["text"] for k in REVERSAL):
                c["suspect_reversed"] = True
                c["suspect_evidence"] = f'{o["t"]} {o["ref"]}'
                break

    cands.sort(key=lambda x: (x["t"], x["src"]))
    sus = [c for c in cands if c["suspect_reversed"]]
    json.dump(
        {
            "n": len(cands),
            "suspect": len(sus),
            "note": "suspect_reversed 仅为疑似标记；真值须人工盲评",
            "records": cands,
        },
        open(OUT, "w"),
        ensure_ascii=False,
        indent=1,
    )

    from collections import Counter

    print(f"candidates={len(cands)} suspect={len(sus)}")
    print("by src:", Counter(c["src"] for c in cands))
    print("by month:", sorted(Counter(c["t"][:7] for c in cands).items()))
    print("\n--- 前 15 条 ---")
    for c in cands[:15]:
        print(f'  {c["t"]} [{c["src"]}] {c["text"][:70]}')


if __name__ == "__main__":
    main()

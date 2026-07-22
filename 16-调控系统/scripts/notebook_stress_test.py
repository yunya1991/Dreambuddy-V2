#!/usr/bin/env python3
"""笔记本系统压力测试器 v1.0 — 模拟6个压力场景"""

import json
import os
import random
import shutil
import string
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import Counter

BASE = Path.home() / "archives" / "Dreambuddy-V2-main"
NOTEBOOK = BASE / "0-NOTEBOOK"
HOOK = BASE / "scripts" / "notebook_hook.py"

os.chdir(str(BASE))

def run_hook(*args):
    import subprocess
    result = subprocess.run(
        [sys.executable, str(HOOK)] + list(args),
        capture_output=True, text=True, timeout=30
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def count_files(dir_name):
    d = NOTEBOOK / dir_name
    return len([f for f in d.iterdir() if f.suffix == '.md' and f.name != 'README.md'])

def file_size(dir_name, name):
    f = NOTEBOOK / dir_name / name
    return f.stat().st_size if f.exists() else 0

def gen_title(n=20):
    """生成随机标题"""
    return ''.join(random.choices(string.ascii_letters, k=n))

def now_ms():
    return time.time() * 1000

results = {}

# ════════════════════════════════════════════
# 场景1: 高频写入测试 (50个完成项)
# ════════════════════════════════════════════
print("=" * 60)
print("🏋️  场景1: 高频写入 (50个完成项)")
print("=" * 60)

t0 = now_ms()
errors = []
for i in range(50):
    rc, out, err = run_hook("done", f"批量测试{i:03d}", f"第{i}个压力测试项", f"/dev/null/test{i}")
    if rc != 0:
        errors.append((i, err))
t1 = now_ms()

done_count_after = count_files("2-DONE")
results["场景1_高频写入"] = {
    "耗时_ms": round(t1 - t0, 1),
    "平均每项_ms": round((t1 - t0) / 50, 1),
    "成功": 50 - len(errors),
    "失败": len(errors),
    "目录文件数": done_count_after,
    "错误": errors[:5] if errors else "无"
}
print(f"  ✅ 50项写入耗时: {results['场景1_高频写入']['耗时_ms']}ms (平均{results['场景1_高频写入']['平均每项_ms']}ms/项)")
print(f"  📂 2-DONE目录: {done_count_after} 个文件")
if errors:
    print(f"  ⚠️ 错误: {len(errors)}个")
    for e in errors[:3]:
        print(f"    {e}")

# ════════════════════════════════════════════
# 场景2: 三链全流程 (D→Z→E 11步)
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("🔗 场景2: 三链全流程 (D1→E3, 11步)")
print("=" * 60)

phases = [
    ("D1", "深度调研"),
    ("D2", "分析诊断"),
    ("D3", "推演验证"),
    ("D4", "Spec合成"),
    ("Z1", "代码扫描"),
    ("Z2", "范围划分"),
    ("Z3", "路径设计"),
    ("Z4", "验收方案"),
    ("E1", "任务执行"),
    ("E2", "测试验证"),
    ("E3", "部署交付"),
]

t0 = now_ms()
chain_errors = []
for i, (phase, name) in enumerate(phases):
    # 设置活跃链
    rc1, _, _ = run_hook("active", phase, name)
    if rc1 != 0:
        chain_errors.append(f"active_{phase}: exit={rc1}")
    # 如果是最后一个，完成它
    if i == len(phases) - 1:
        rc2, _, _ = run_hook("finish", phase, name)
        if rc2 != 0:
            chain_errors.append(f"finish_{phase}: exit={rc2}")

t1 = now_ms()
active_count = count_files("1-ACTIVE") - 1  # 减1排除README
results["场景2_三链全流程"] = {
    "耗时_ms": round(t1 - t0, 1),
    "步骤数": len(phases),
    "活跃链残存": max(0, active_count),
    "错误": chain_errors if chain_errors else "无",
    "结论": "✅ 完整" if not chain_errors and active_count == 0 else "⚠️ 有残留"
}
print(f"  ✅ 11步切换耗时: {results['场景2_三链全流程']['耗时_ms']}ms")
print(f"  📂 1-ACTIVE残存: {max(0, active_count)} 文件 (应为0)")
if chain_errors:
    print(f"  ⚠️ 错误: {chain_errors}")

# ════════════════════════════════════════════
# 场景3: 混合操作 (交错done/todo/active/sync 30次)
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("🔄 场景3: 混合操作 (30次交错done/todo/active/sync)")
print("=" * 60)

ops = [
    ("done", f"混合测试{i:03d}", f"混合操作第{i}项", f"output/{i}")
    if i % 4 == 0
    else ("todo", f"待办混合{i:03d}", f"待办第{i}项", "-p", "P1" if i % 2 == 0 else "P2")
    if i % 4 == 1
    else ("active", f"T{i}", f"测试链{i}")
    if i % 4 == 2
    else ("sync",)
    for i in range(30)
]

t0 = now_ms()
mix_errors = []
for op in ops:
    try:
        rc, out, err = run_hook(*op)
        if rc != 0:
            mix_errors.append((op, err))
    except Exception as e:
        mix_errors.append((op, str(e)))
t1 = now_ms()

results["场景3_混合操作"] = {
    "耗时_ms": round(t1 - t0, 1),
    "操作数": len(ops),
    "失败": len(mix_errors),
    "错误": mix_errors[:5] if mix_errors else "无"
}
print(f"  ✅ {len(ops)}次操作耗时: {results['场景3_混合操作']['耗时_ms']}ms")
if mix_errors:
    print(f"  ⚠️ 错误: {len(mix_errors)}个")

# ════════════════════════════════════════════
# 场景4: 边界值测试
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("🔮 场景4: 边界值测试")
print("=" * 60)

boundary_tests = [
    ("超长标题500字", "done", "A" * 500, "超长标题摘要"),
    ("特殊字符", "done", "!@#$%^&*()_+={}[]|\\:;\"'<>,.?/~\n\r\t", "特殊字符摘要"),
    ("Unicode全角", "done", "中文测试·「」『』【】《》★☆♦♣♠♥♪♫€¥₿🔥⚡", "Unicode摘要"),
    ("空标题/空摘要", "done", "", ""),
    ("路径注入", "done", "../../etc/passwd", "../恶意路径"),
    ("超长路径", "done", "正常标题", "/" + "a" * 4000),
    ("连续10次sync", "sync", None),
]

t0 = now_ms()
boundary_errors = []
for test_name, cmd, *args in boundary_tests:
    try:
        filtered_args = [a for a in args if a is not None]
        rc, out, err = run_hook(cmd, *filtered_args) if filtered_args else run_hook(cmd)
        if rc != 0:
            boundary_errors.append(f"{test_name}: exit={rc} {err[:50]}")
    except Exception as e:
        boundary_errors.append(f"{test_name}: {str(e)[:50]}")

t1 = now_ms()
results["场景4_边界值"] = {
    "耗时_ms": round(t1 - t0, 1),
    "测试数": len(boundary_tests),
    "失败": len(boundary_errors),
    "失败详情": boundary_errors[:5] if boundary_errors else "无"
}
print(f"  ✅ 边界值测试完成: {len(boundary_tests)}项")
if boundary_errors:
    for err in boundary_errors:
        print(f"  ⚠️  {err}")
else:
    print(f"  ✅ 全部通过")

# ════════════════════════════════════════════
# 场景5: NOTEBOOK.md 一致性测试
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("📋 场景5: NOTEBOOK.md 同步一致性 (连续sync 10次)")
print("=" * 60)

contents = []
for i in range(10):
    rc, _, _ = run_hook("sync")
    content = NOTEBOOK.joinpath("NOTEBOOK.md").read_text()
    contents.append(content)

is_consistent = all(c == contents[0] for c in contents)
results["场景5_一致性"] = {
    "sync次数": 10,
    "内容一致": is_consistent,
    "内容长度": len(contents[0])
}
print(f"  ✅ 10次sync后内容{'一致' if is_consistent else '不一致⚠️'}")

# ════════════════════════════════════════════
# 场景6: 恢复后状态读取测试
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("🔄 场景6: Session恢复上下文读取")
print("=" * 60)

# 模拟session重启: 读取NOTEBOOK.md能获得什么信息
notebook = NOTEBOOK.joinpath("NOTEBOOK.md").read_text()
done_files = sorted(
    (NOTEBOOK / "2-DONE").glob("*.md"),
    key=lambda p: p.stat().st_mtime, reverse=True
)
todo_files = list((NOTEBOOK / "0-TODO").glob("*.md"))
active_files = list((NOTEBOOK / "1-ACTIVE").glob("*.md"))
active_files = [f for f in active_files if f.name != "README.md"]

# 统计所有dir的文件数量
dir_stats = {}
for d in ["0-TODO", "1-ACTIVE", "2-DONE", "3-ARCHIVE"]:
    dir_path = NOTEBOOK / d
    files = [f for f in dir_path.iterdir() if f.suffix == '.md' and f.name != 'README.md']
    dir_stats[d] = len(files)

results["场景6_上下文恢复"] = {
    "NOTEBOOK.md长度": len(notebook),
    "各目录文件数": dir_stats,
    "最早完成项": done_files[-1].name if done_files else "无",
    "最新完成项": done_files[0].name if done_files else "无",
    "待办项": len(todo_files),
    "活跃链": len(active_files),
}

print(f"  📂 各目录文件数: {dir_stats}")
print(f"  📄 NOTEBOOK.md: {len(notebook)} 字节")
print(f"  ⏳ 待办: {len(todo_files)} / 活跃: {len(active_files)} / 完成: {dir_stats['2-DONE']}")

# ════════════════════════════════════════════
# 综合报告
# ════════════════════════════════════════════
print("\n" + "=" * 60)
print("📊 综合压力测试报告")
print("=" * 60)
print()

all_pass = True
for name, data in results.items():
    errs = data.get("错误", data.get("失败详情", "无"))
    has_err = errs != "无" and errs
    if has_err:
        all_pass = False
    status = "✅" if not has_err else "⚠️"
    print(f"  {status} {name}")
    for k, v in data.items():
        if k not in ("错误", "失败详情") or has_err:
            print(f"      {k}: {v}")

print()
print(f"\n{'🎉 全部通过!' if all_pass else '⚠️ 有失败项，需检查'}")
print(f"总写入项: {dir_stats.get('2-DONE', '?')} 个完成文件")

# 清理测试数据（保留初始1个+测试产生的）
# 注意: 不清理边界测试中的可能的破环性文件
print("\n📋 测试后目录状态:")
for d in ["0-TODO", "1-ACTIVE", "2-DONE", "3-ARCHIVE"]:
    dir_path = NOTEBOOK / d
    files = [f for f in dir_path.iterdir() if f.suffix == '.md' and f.name != 'README.md']
    print(f"  {d}: {len(files)} 个文件 ({sum(f.stat().st_size for f in files)} 字节)")

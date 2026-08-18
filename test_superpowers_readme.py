#!/usr/bin/env python3
"""Test superpowers README.md existence and content."""
import os
import sys

README_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/superpowers/README.md"
EXPECTED_COMMIT = "44c9b2d6e889982ac18c27d05a19fefe335194e1"

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


def main():
    check(os.path.exists(README_PATH), "README.md 文件不存在")

    lines = []
    if os.path.exists(README_PATH):
        content = open(README_PATH, "r", encoding="utf-8").read()
        lines = content.split("\n")

        check("1 目录结构" in content or "1. 目录结构" in content or "## 1 目录结构" in content, "缺少章节：1 目录结构")
        check("2 更新规则" in content or "2. 更新规则" in content or "## 2 更新规则" in content, "缺少章节：2 更新规则")
        check("2.1 只增不改原则" in content or "2.1 只增不改" in content, "缺少子章节：2.1 只增不改原则")
        check("2.2 同步上游操作" in content or "2.2 同步上游" in content, "缺少子章节：2.2 同步上游操作")
        check("2.3 supplement完善规则" in content or "2.3 supplement" in content, "缺少子章节：2.3 supplement完善规则")
        check("3 SKILL.md格式红线" in content or "3. SKILL.md格式红线" in content or "## 3 SKILL.md" in content, "缺少章节：3 SKILL.md格式红线")
        check("3.1 Frontmatter分隔符FAIL FAST" in content or "3.1 Frontmatter" in content, "缺少子章节：3.1 Frontmatter分隔符FAIL FAST")
        check("3.2 必填字段" in content, "缺少子章节：3.2 必填字段")
        check("3.3 推荐字段" in content, "缺少子章节：3.3 推荐字段")
        check("3.4 报错格式" in content, "缺少子章节：3.4 报错格式")
        check("4 skills-index.json说明" in content or "4. skills-index.json" in content or "## 4 skills-index.json" in content, "缺少章节：4 skills-index.json说明")
        check("5 常见问题" in content or "5. 常见问题" in content or "## 5 常见问题" in content, "缺少章节：5 常见问题")
        check("Q1" in content, "缺少 Q1")
        check("Q2" in content, "缺少 Q2")
        check("Q3" in content, "缺少 Q3")
        check("Q4" in content, "缺少 Q4")

        check(EXPECTED_COMMIT in content, "缺少上游版本 commit hash: " + EXPECTED_COMMIT)

        check("FAIL FAST" in content or "Fail Fast" in content or "fail fast" in content, "缺少格式红线关键词：FAIL FAST")
        check("Frontmatter" in content or "frontmatter" in content, "缺少格式红线关键词：Frontmatter")
        check("必填字段" in content, "缺少格式红线关键词：必填字段")
        check("推荐字段" in content, "缺少格式红线关键词：推荐字段")
        check("报错格式" in content, "缺少格式红线关键词：报错格式")
        check("supplement" in content.lower(), "缺少关键词：supplement")
        check("只增不改" in content, "缺少关键词：只增不改")
        check("同步上游" in content, "缺少关键词：同步上游")

    print("总行数: " + str(len(lines)))
    commit_ok = False
    if os.path.exists(README_PATH):
        content = open(README_PATH, "r", encoding="utf-8").read()
        commit_ok = EXPECTED_COMMIT in content
    print("Commit hash checked: " + str(commit_ok))

    if errors:
        print("\n❌ " + str(len(errors)) + " 个测试失败:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)
    else:
        print("\n✅ 所有测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()

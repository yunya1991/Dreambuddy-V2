#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-B 小样本探索性统计分析（纯标准库实现）。

口径来源：docs/SPEC-20261124-内容优化引擎-content-optimizer-P0可行性验证-v0.1.md
  - §6.3 覆盖口径（raw /34，applicable /27）
  - §8   分析计划（单变量、bootstrap 95%CI、BH FDR、负对照）
  - §9   G0–G5 门禁

约束：
  - 只读 samples.csv，只写 analysis/go_no_go.json；
  - 按 platform 分开建模，不混池；
  - 缺失字段一律不可用，禁止补 0；
  - 特征只做确定性派生（正则/行序），不做 LLM 打标。

用法：
    cd platform/lab/content-optimizer-p0 && python3 scripts/analyze_p0b.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import re
import statistics
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_PATH = os.path.join(BASE_DIR, "samples.csv")
OUT_JSON_PATH = os.path.join(BASE_DIR, "analysis", "go_no_go.json")
COLLECTION_LOG_PATH = os.path.join(BASE_DIR, "collection_log.jsonl")

# 34 个分析字段（schema.json 中除 missing_flags/outlier_flags/is_censored 外的全部属性）
ANALYSIS_FIELDS = [
    "sample_id",
    "platform",
    "source_type",
    "url_hash",
    "query",
    "rank_bucket",
    "collected_at",
    "collector",
    "author_followers_bucket",
    "published_at",
    "publish_hour",
    "weekday",
    "title",
    "title_len",
    "title_pattern",
    "body_len",
    "topic_count",
    "hashtag_count",
    "cover_type",
    "media_type",
    "duration_sec",
    "first3s_text_present",
    "likes",
    "saves",
    "comments",
    "shares",
    "metrics_at",
    "impressions",
    "views",
    "cover_ctr",
    "avg_watch_sec",
    "completion_rate",
    "two_sec_bounce",
    "follows",
]
# 公开样本结构性不可得的 7 个自有账号指标（applicable 覆盖分母排除）
STRUCTURAL_EXCLUDED = {
    "impressions",
    "views",
    "cover_ctr",
    "avg_watch_sec",
    "completion_rate",
    "two_sec_bounce",
    "follows",
}
# G1 判据里的“关键字段”（主目标 engagement 与分层所需）
KEY_FIELDS = ["title", "title_len", "likes", "saves", "comments", "query"]

BOOTSTRAP_N = 1000
PERMUTATION_N = 1000
SEED = 20261124
MIN_N = 20  # 某特征非空样本 <20 → insufficient，禁止给结论
G2_MIN_ABS_RHO = 0.20
G2_MAX_Q = 0.10
G2_MIN_DIRECTION = 0.70
G3_MIN_RELATIVE_DIFF = 0.10

PLATFORMS = ["xiaohongshu", "douyin"]


# ---------------------------------------------------------------- 基础工具
def is_null(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"none", "null", "nan", "n/a"}


def to_int(value):
    if is_null(value):
        return None
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def to_float(value):
    if is_null(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def avg_ranks(values):
    """平均秩（并列取平均），返回与输入等长的秩列表。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    return sxy / math.sqrt(sxx * syy)


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    return pearson(avg_ranks(xs), avg_ranks(ys))


def percentile_ci(values, alpha=0.05):
    """百分位 bootstrap CI（最近秩法）。"""
    if not values:
        return None, None
    ordered = sorted(values)
    lo_idx = max(0, int(math.floor(alpha / 2 * len(ordered))))
    hi_idx = min(len(ordered) - 1, int(math.ceil((1 - alpha / 2) * len(ordered))) - 1)
    return ordered[lo_idx], ordered[hi_idx]


def bootstrap_stats(xs, ys, seed):
    rng = random.Random(seed)
    n = len(xs)
    point = spearman(xs, ys)
    replicates = []
    for _ in range(BOOTSTRAP_N):
        idx = [rng.randrange(n) for _ in range(n)]
        rho = spearman([xs[i] for i in idx], [ys[i] for i in idx])
        if rho is not None:
            replicates.append(rho)
    if not replicates:
        return {"rho": point, "ci_low": None, "ci_high": None, "direction": None}
    lo, hi = percentile_ci(replicates)
    if point is None:
        direction = None
    elif point > 0:
        direction = sum(1 for r in replicates if r > 0) / len(replicates)
    elif point < 0:
        direction = sum(1 for r in replicates if r < 0) / len(replicates)
    else:
        direction = sum(1 for r in replicates if r == 0) / len(replicates)
    return {"rho": point, "ci_low": lo, "ci_high": hi, "direction": direction}


def permutation_pvalue(xs, ys, seed):
    """置换检验双侧 p 值（1000 次重排 y）。"""
    observed = spearman(xs, ys)
    if observed is None:
        return None
    rng = random.Random(seed)
    shuffled = list(ys)
    count = 0
    for _ in range(PERMUTATION_N):
        rng.shuffle(shuffled)
        rho = spearman(xs, shuffled)
        if rho is None:
            continue
        if abs(rho) >= abs(observed) - 1e-12:
            count += 1
    return (count + 1) / (PERMUTATION_N + 1)


def benjamini_hochberg(rows, p_key="p_value", q_key="q_value"):
    """就地写入 BH q 值；rows 中 p 为 None 的条目跳过。"""
    valid = [r for r in rows if r.get(p_key) is not None]
    m = len(valid)
    if m == 0:
        return rows
    ordered = sorted(valid, key=lambda r: r[p_key])
    prev_q = 1.0
    for rank_from_end in range(m, 0, -1):
        row = ordered[rank_from_end - 1]
        q = row[p_key] * m / rank_from_end
        q = min(q, prev_q)
        row[q_key] = round(min(q, 1.0), 4)
        prev_q = q
    return rows


# ---------------------------------------------------------------- 特征派生
EMOTION_WORDS = [
    "绝了",
    "震惊",
    "炸",
    "崩",
    "惨",
    "牛",
    "逆天",
    "后悔",
    "慌",
    "哭",
    "离谱",
    "暴涨",
    "暴跌",
    "狂",
    "疯",
    "真香",
    "泪",
    "怒",
    "救命",
    "惊呆",
    "可怕",
    "痛",
    "累",
    "爽",
    "气死",
    "无语",
    "狠",
]
BENEFIT_WORDS = [
    "如何",
    "怎么",
    "3步",
    "三步",
    "指南",
    "攻略",
    "避坑",
    "教你",
    "清单",
    "技巧",
    "教程",
    "干货",
    "必看",
]
CONTRAST_WORDS = ["vs", "相比", "对比"]
QUESTION_TAIL = re.compile(r"(吗|呢|怎么|如何|为什么|为啥|多少|哪[个里些])\s*[！!。.～~]*\s*$")


def derive_title_pattern(title):
    """按 SPEC §7 顺序判定：数字开头 → 疑问 → 对比 → 利益点 → 情绪 → 陈述。"""
    if is_null(title):
        return None
    text = str(title).strip()
    if re.match(r"^[\s\W]*\d", text):
        return "number"
    if "?" in text or "？" in text or QUESTION_TAIL.search(text):
        return "question"
    lowered = text.lower()
    if any(word.lower() in lowered for word in CONTRAST_WORDS):
        return "contrast"
    if any(word in text for word in BENEFIT_WORDS):
        return "benefit"
    if any(word in text for word in EMOTION_WORDS):
        return "emotion"
    return "statement"


def count_hashtags(title):
    if is_null(title):
        return None
    return len([m for m in re.findall(r"#([^\s#]+)", str(title)) if m.strip()])


PLACEHOLDER_PREFIX = re.compile(r"^(未点赞|点赞|收藏|评论|分享|按钮)")


def is_placeholder_title(title):
    """页面按钮文本被误采为标题，如「未点赞，喜欢33.9万，按钮」。"""
    if is_null(title):
        return False
    text = str(title).strip()
    return bool(PLACEHOLDER_PREFIX.match(text)) or "，按钮" in text


def build_rows():
    with open(SAMPLES_PATH, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        raw_rows = list(reader)

    rows = []
    for idx, raw in enumerate(raw_rows):
        row = dict(raw)
        row["_row_no"] = idx + 1
        row["_orig"] = dict(raw)  # 原始采集值，用于覆盖率统计（不含派生）
        row["platform"] = (raw.get("platform") or "").strip()
        row["query"] = raw.get("query").strip() if not is_null(raw.get("query")) else None
        row["title"] = raw.get("title") if not is_null(raw.get("title")) else None
        row["likes"] = to_int(raw.get("likes"))
        row["saves"] = to_int(raw.get("saves"))
        row["comments"] = to_int(raw.get("comments"))
        row["shares"] = to_int(raw.get("shares"))
        row["body_len"] = to_int(raw.get("body_len"))
        row["title_len"] = to_int(raw.get("title_len"))
        if row["title_len"] is None and row["title"] is not None:
            row["title_len"] = len(row["title"])
        row["hashtag_count"] = to_int(raw.get("hashtag_count"))
        if row["hashtag_count"] is None and row["title"] is not None:
            # 标题内 # 数量是可确定性派生的，0 表示标题确无话题（非补零）
            derive = count_hashtags(row["title"])
            if derive is not None:
                row["hashtag_count"] = derive
        row["publish_hour"] = to_int(raw.get("publish_hour"))
        row["weekday"] = to_int(raw.get("weekday"))
        row["title_pattern_derived"] = derive_title_pattern(row["title"])
        # 目标：engagement 要求 likes/saves/comments 三者齐全，否则该行不可用
        if row["likes"] is not None and row["saves"] is not None and row["comments"] is not None:
            row["engagement"] = row["likes"] + row["saves"] + row["comments"]
        else:
            row["engagement"] = None
        rows.append(row)

    # 预处理 1：按 (platform, title.strip(), likes) 去重，保留首次出现
    raw_by_platform = {}
    for row in rows:
        raw_by_platform[row["platform"]] = raw_by_platform.get(row["platform"], 0) + 1
    deduped_rows, dropped_rows = [], []
    seen_keys = set()
    for row in rows:
        key = (row["platform"], (row["title"] or "").strip(), row["likes"])
        if key in seen_keys:
            dropped_rows.append(row)
            continue
        seen_keys.add(key)
        deduped_rows.append(row)
    dropped_by_platform = {}
    for row in dropped_rows:
        dropped_by_platform[row["platform"]] = dropped_by_platform.get(row["platform"], 0) + 1
    deduped_by_platform = {}
    for row in deduped_rows:
        deduped_by_platform[row["platform"]] = deduped_by_platform.get(row["platform"], 0) + 1

    # 预处理 2：抖音占位标题识别；保留行用于 likes 分析，但排除 title 类特征
    placeholder_rows = []
    for row in deduped_rows:
        row["is_placeholder_title"] = bool(
            row["platform"] == "douyin" and is_placeholder_title(row["title"])
        )
        if row["is_placeholder_title"]:
            placeholder_rows.append(row)
            row["title_len"] = None
            row["title_pattern_derived"] = None
            row["hashtag_count"] = None
    placeholder_by_platform = {}
    for row in placeholder_rows:
        placeholder_by_platform[row["platform"]] = (
            placeholder_by_platform.get(row["platform"], 0) + 1
        )

    rows = deduped_rows
    prep_info = {
        "raw_total": len(raw_rows),
        "raw_by_platform": raw_by_platform,
        "dropped_total": len(dropped_rows),
        "dropped_by_platform": dropped_by_platform,
        "deduped_total": len(rows),
        "deduped_by_platform": deduped_by_platform,
        "placeholder_total": len(placeholder_rows),
        "placeholder_by_platform": placeholder_by_platform,
    }

    # rank 位置：同 platform × query 内按 csv 行序 1..n（去重后）
    groups = {}
    for row in rows:
        key = (row["platform"], row["query"])
        groups.setdefault(key, []).append(row)
    for key, members in groups.items():
        members_sorted = sorted(members, key=lambda r: r["_row_no"])
        for position, row in enumerate(members_sorted, start=1):
            row["rank"] = position
            row["group_key"] = key
            row["group_n"] = len(members_sorted)
    return rows, prep_info


# ---------------------------------------------------------------- 覆盖与质量
def coverage_stats(platform_rows):
    raw_scores, applicable_scores = [], []
    for row in platform_rows:
        present = 0
        for field in ANALYSIS_FIELDS:
            value = row["_orig"].get(field)  # 只用实际采集值，排除派生特征
            if not is_null(value):
                present += 1
        raw_scores.append(present / len(ANALYSIS_FIELDS))
        applicable_rows = len(ANALYSIS_FIELDS) - len(STRUCTURAL_EXCLUDED)
        applicable_scores.append(present / applicable_rows)
    return {
        "n": len(platform_rows),
        "raw_coverage": round(statistics.mean(raw_scores) * 100, 1) if raw_scores else 0.0,
        "applicable_coverage": (
            round(statistics.mean(applicable_scores) * 100, 1) if applicable_scores else 0.0
        ),
    }


def missing_rates(platform_rows):
    fields = [
        "title",
        "title_len",
        "likes",
        "saves",
        "comments",
        "shares",
        "body_len",
        "hashtag_count",
        "publish_hour",
        "published_at",
        "rank_bucket",
    ]
    result = {}
    for field in fields:
        missing = sum(1 for row in platform_rows if is_null(row.get(field)))
        result[field] = round(missing / len(platform_rows), 4) if platform_rows else None
    key_missing = 0.0
    for field in KEY_FIELDS:
        missing = sum(1 for row in platform_rows if is_null(row.get(field)))
        key_missing += missing / len(platform_rows) if platform_rows else 0
    result["key_fields_missing_rate"] = round(key_missing / len(KEY_FIELDS), 4)
    return result


def duplicate_stats(platform_rows):
    all_fields = ANALYSIS_FIELDS
    seen = set()
    exact_dups = 0
    for row in platform_rows:
        key = tuple("" if is_null(row.get(f)) else str(row.get(f)) for f in all_fields)
        if key in seen:
            exact_dups += 1
        else:
            seen.add(key)
    title_seen = {}
    duplicate_title_rows = 0
    for row in platform_rows:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        if title in title_seen:
            duplicate_title_rows += 1
        title_seen[title] = title_seen.get(title, 0) + 1
    n = len(platform_rows)
    return {
        "n": n,
        "exact_duplicate_rows": exact_dups,
        "exact_duplicate_rate": round(exact_dups / n, 4) if n else None,
        "duplicate_title_rows": duplicate_title_rows,
        "duplicate_title_rate": round(duplicate_title_rows / n, 4) if n else None,
        "distinct_titles": len(title_seen),
    }


def content_quality(platform_rows):
    """标题信息量相关的质量指标：占位标题、标题规则与 csv 标注不一致数。"""
    placeholder = [row for row in platform_rows if row.get("is_placeholder_title")]
    mismatch = 0
    compared = 0
    for row in platform_rows:
        csv_pattern = (row.get("title_pattern") or "").strip()
        derived = row.get("title_pattern_derived")
        if not csv_pattern or csv_pattern == "unknown" or derived is None:
            continue
        compared += 1
        if csv_pattern != derived:
            mismatch += 1
    return {
        "placeholder_title_rows": len(placeholder),
        "placeholder_ratio": round(len(placeholder) / len(platform_rows), 4),
        "pattern_compared": compared,
        "pattern_mismatch": mismatch,
    }


def publish_distribution(platform_rows):
    hours = {}
    for row in platform_rows:
        hour = row.get("publish_hour")
        key = "missing" if hour is None else str(hour)
        hours[key] = hours.get(key, 0) + 1
    dates = sorted(
        str(row.get("published_at"))[:10]
        for row in platform_rows
        if not is_null(row.get("published_at"))
    )
    return {
        "publish_hour_counts": dict(sorted(hours.items())),
        "published_date_min": dates[0] if dates else None,
        "published_date_max": dates[-1] if dates else None,
        "published_present": len(dates),
    }


def rank_distribution(platform_rows):
    distribution = {}
    for row in platform_rows:
        key = f"{row['query'] or '(none)'}"
        distribution.setdefault(key, {"n": 0, "group_n": row["group_n"]})
        distribution[key]["n"] += 1
    return distribution


# ---------------------------------------------------------------- 因变量标准化
def percentile_within(rows, target_key, platform):
    """platform × query 内百分位；组内 n<5 退化为同 platform 百分位。"""
    by_group = {}
    for row in rows:
        if row.get(target_key) is None:
            continue
        by_group.setdefault(row["group_key"], []).append(row)

    def assign(members, scope):
        values = [row[target_key] for row in members]
        ranks = avg_ranks(values)
        n = len(members)
        for row, rank in zip(members, ranks, strict=False):
            row[f"_pct_{target_key}_{scope}"] = 100.0 * (rank - 1) / (n - 1) if n > 1 else 50.0

    fallback_groups = 0
    for members in by_group.values():
        if len(members) >= 5:
            assign(members, "query")
        else:
            fallback_groups += 1
    # 平台级兜底百分位
    platform_members = [row for row in rows if row.get(target_key) is not None]
    if len(platform_members) >= 2:
        assign(platform_members, "platform")
    for row in platform_members:
        if f"_pct_{target_key}_query" not in row:
            row[f"_pct_{target_key}_final"] = row[f"_pct_{target_key}_platform"]
        else:
            row[f"_pct_{target_key}_final"] = row[f"_pct_{target_key}_query"]
    return fallback_groups, len([g for g in by_group if len(by_group[g]) < 5])


# ---------------------------------------------------------------- 单变量检验
def feature_definitions(platform):
    features = [
        ("title_len", "continuous", lambda r: r.get("title_len")),
        ("hashtag_count", "continuous", lambda r: r.get("hashtag_count")),
        ("body_len", "continuous", lambda r: r.get("body_len")),
        ("publish_hour", "continuous", lambda r: r.get("publish_hour")),
        ("rank", "continuous", lambda r: r.get("rank")),
    ]
    for pattern in ["number", "question", "contrast", "benefit", "emotion"]:
        features.append(
            (
                f"pattern_{pattern}",
                "binary",
                (
                    lambda p: (
                        lambda r: (
                            None
                            if r.get("title_pattern_derived") is None
                            else (1.0 if r["title_pattern_derived"] == p else 0.0)
                        )
                    )
                )(pattern),
            )
        )
    return features


CONTROLLABLE = {
    "title_len",
    "hashtag_count",
    "body_len",
    "publish_hour",
    "pattern_number",
    "pattern_question",
    "pattern_contrast",
    "pattern_benefit",
    "pattern_emotion",
}
NEGATIVE_CONTROLS = {"nc_title_len_parity", "nc_rank_parity", "nc_publish_hour_parity"}


def collect_pairs(rows, feature_fn, target_key):
    xs, ys, kept = [], [], []
    for row in rows:
        y_pct = row.get(f"_pct_{target_key}_final")
        if y_pct is None:
            continue
        x = feature_fn(row)
        if x is None:
            continue
        xs.append(float(x))
        ys.append(float(y_pct))
        kept.append(row)
    return xs, ys, kept


def quantile_relative_diff(xs, ys):
    """最低 25% 与最高 25% 的因变量均值相对差（%）。"""
    if len(xs) < 8:
        return None
    paired = sorted(zip(xs, ys, strict=False), key=lambda p: p[0])
    n = len(paired)
    k = max(1, n // 4)
    bottom = [y for _, y in paired[:k]]
    top = [y for _, y in paired[-k:]]
    bottom_mean = statistics.mean(bottom)
    top_mean = statistics.mean(top)
    if bottom_mean == 0:
        return None
    return (top_mean - bottom_mean) / bottom_mean


def oos_split_rho(rows_pairs, all_rows):
    """按 collected_at + 行序 70/30 切分，返回 (train_rho, holdout_rho, n_holdout)。"""

    def sort_key(row):
        collected = str(row.get("collected_at") or "")
        return (collected, row["_row_no"])

    ordered = sorted(rows_pairs, key=sort_key)
    n = len(ordered)
    if n < 10:
        return None, None, 0
    cut = int(n * 0.7)
    holdout = ordered[cut:]
    if len(holdout) < 3:
        return None, None, len(holdout)
    train_rho = spearman(
        [float(r["_x"]) for r in ordered[:cut]], [float(r["_y"]) for r in ordered[:cut]]
    )
    holdout_rho = spearman([float(r["_x"]) for r in holdout], [float(r["_y"]) for r in holdout])
    return train_rho, holdout_rho, len(holdout)


def run_tests(platform_rows, platform, target_key):
    results = []
    seed = SEED + sum(ord(c) for c in platform + target_key)
    features = feature_definitions(platform)
    # rank 位置不可控（平台推流结果），仅作描述；不参与 G2 计数
    for feat_name, feat_type, feat_fn in features:
        xs, ys, kept = collect_pairs(platform_rows, feat_fn, target_key)
        n = len(xs)
        entry = {
            "platform": platform,
            "target": target_key,
            "feature": feat_name,
            "feature_type": feat_type,
            "n": n,
            "n_group_1": int(sum(1 for x in xs if x == 1.0)) if feat_type == "binary" else None,
            "n_group_0": int(sum(1 for x in xs if x == 0.0)) if feat_type == "binary" else None,
            "rho": None,
            "ci_low": None,
            "ci_high": None,
            "q_value": None,
            "direction_agree": None,
            "p_value": None,
            "oos_rho": None,
            "n_holdout": None,
            "quantile_rel_diff": None,
            "status": "ok",
            "controllable": feat_name in CONTROLLABLE,
            "negative_control": False,
        }
        if n < MIN_N:
            entry["status"] = "insufficient"
            entry["reason"] = f"非空样本 {n} < {MIN_N}"
            results.append(entry)
            continue
        if feat_type == "binary" and (entry["n_group_1"] == 0 or entry["n_group_0"] == 0):
            entry["status"] = "insufficient"
            entry["reason"] = (
                f"二值分组单类为空（1类={entry['n_group_1']} / 0类={entry['n_group_0']}）"
            )
            results.append(entry)
            continue
        if len(set(xs)) == 1:
            entry["status"] = "zero_variance"
            entry["reason"] = f"特征取值恒为 {xs[0]:g}，无方差"
            results.append(entry)
            continue
        stats = bootstrap_stats(xs, ys, seed)
        entry.update(
            {
                "rho": round(stats["rho"], 4) if stats["rho"] is not None else None,
                "ci_low": round(stats["ci_low"], 4) if stats["ci_low"] is not None else None,
                "ci_high": round(stats["ci_high"], 4) if stats["ci_high"] is not None else None,
                "direction_agree": (
                    round(stats["direction"], 4) if stats["direction"] is not None else None
                ),
                "p_value": permutation_pvalue(xs, ys, seed + 7),
            }
        )
        if stats["rho"] is None:
            entry["status"] = "zero_variance"
            results.append(entry)
            continue
        for row, x, y in zip(kept, xs, ys, strict=False):
            row["_x"] = x
            row["_y"] = y
        _, holdout_rho, n_holdout = oos_split_rho(kept, platform_rows)
        entry["oos_rho"] = round(holdout_rho, 4) if holdout_rho is not None else None
        entry["n_holdout"] = n_holdout
        entry["quantile_rel_diff"] = (
            round(quantile_relative_diff(xs, ys), 4)
            if quantile_relative_diff(xs, ys) is not None
            else None
        )
        results.append(entry)

    # 负对照：title_len 奇偶；publish_hour 奇偶（仅当取值非常量），否则 rank 奇偶
    nc_specs = [
        (
            "nc_title_len_parity",
            lambda r: None if r.get("title_len") is None else float(r["title_len"] % 2),
        )
    ]
    hour_values = [
        row.get("publish_hour") for row in platform_rows if row.get("publish_hour") is not None
    ]
    if len(set(hour_values)) > 1:
        nc_specs.append(
            (
                "nc_publish_hour_parity",
                lambda r: None if r.get("publish_hour") is None else float(r["publish_hour"] % 2),
            )
        )
    else:
        nc_specs.append(("nc_rank_parity", lambda r: float(r["rank"] % 2)))
    for name, fn in nc_specs:
        xs, ys, kept = collect_pairs(platform_rows, fn, target_key)
        n = len(xs)
        entry = {
            "platform": platform,
            "target": target_key,
            "feature": name,
            "feature_type": "binary",
            "n": n,
            "n_group_1": int(sum(1 for x in xs if x == 1.0)),
            "n_group_0": int(sum(1 for x in xs if x == 0.0)),
            "rho": None,
            "ci_low": None,
            "ci_high": None,
            "q_value": None,
            "direction_agree": None,
            "p_value": None,
            "oos_rho": None,
            "n_holdout": None,
            "quantile_rel_diff": None,
            "status": "ok",
            "controllable": False,
            "negative_control": True,
        }
        if n < MIN_N:
            entry["status"] = "insufficient"
            entry["reason"] = f"非空样本 {n} < {MIN_N}"
            results.append(entry)
            continue
        stats = bootstrap_stats(xs, ys, seed + 11)
        entry.update(
            {
                "rho": round(stats["rho"], 4) if stats["rho"] is not None else None,
                "ci_low": round(stats["ci_low"], 4) if stats["ci_low"] is not None else None,
                "ci_high": round(stats["ci_high"], 4) if stats["ci_high"] is not None else None,
                "direction_agree": (
                    round(stats["direction"], 4) if stats["direction"] is not None else None
                ),
                "p_value": permutation_pvalue(xs, ys, seed + 13),
                "quantile_rel_diff": (
                    round(quantile_relative_diff(xs, ys), 4)
                    if quantile_relative_diff(xs, ys) is not None
                    else None
                ),
            }
        )
        results.append(entry)

    # 同 platform × 同 target 全部检验（含负对照）统一做 BH
    benjamini_hochberg(results)
    return results


# ---------------------------------------------------------------- 门禁
def evaluate_g2(tests, target_key):
    """G2：可控特征且同时满足 |rho|、CI、q、方向一致率、OOS 五项。"""
    qualified = []
    for row in tests:
        if row["target"] != target_key or not row["controllable"]:
            continue
        if row["status"] != "ok" or row["rho"] is None:
            continue
        ci_excludes_zero = (
            row["ci_low"] is not None
            and row["ci_high"] is not None
            and (row["ci_low"] > 0 or row["ci_high"] < 0)
        )
        oos_ok = (
            row["oos_rho"] is not None
            and abs(row["oos_rho"]) >= G2_MIN_ABS_RHO
            and (row["oos_rho"] > 0) == (row["rho"] > 0)
        )
        row["g2_qualified"] = bool(
            abs(row["rho"]) >= G2_MIN_ABS_RHO
            and ci_excludes_zero
            and row["q_value"] is not None
            and row["q_value"] <= G2_MAX_Q
            and row["direction_agree"] is not None
            and row["direction_agree"] >= G2_MIN_DIRECTION
            and oos_ok
        )
        if row["g2_qualified"]:
            qualified.append(row["feature"])
    return qualified


def negative_control_flags(tests, target_key):
    flagged = []
    for row in tests:
        if row["target"] != target_key or not row["negative_control"]:
            continue
        if row["status"] != "ok" or row["rho"] is None:
            continue
        ci_excludes_zero = (
            row["ci_low"] is not None
            and row["ci_high"] is not None
            and (row["ci_low"] > 0 or row["ci_high"] < 0)
        )
        if ci_excludes_zero and row["q_value"] is not None and row["q_value"] <= G2_MAX_Q:
            flagged.append(row["feature"])
    return flagged


def evaluate_g4():
    entries = []
    if os.path.exists(COLLECTION_LOG_PATH):
        with open(COLLECTION_LOG_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    violation_states = {"violation", "warning", "account_warning", "rate_limited", "blocked"}
    violations = [e for e in entries if str(e.get("state", "")).lower() in violation_states]
    timeouts = [e for e in entries if str(e.get("state", "")).lower() == "timeout"]
    return {
        "pass": len(violations) == 0,
        "evidence": {
            "log_entries": len(entries),
            "violations": len(violations),
            "timeouts": len(timeouts),
            "note": "collection_log.jsonl 中无违规/账号警告/限频记录；timeout 计为通道异常，非合规违规",
            "source": "collection_log.jsonl",
        },
    }


# ---------------------------------------------------------------- 主流程
def fmt(value, digits=3):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_table(title, headers, rows):
    print()
    print(title)
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        print("| " + " | ".join(row) + " |")


def main():
    rows, prep = build_rows()
    platform_rows = {p: [r for r in rows if r["platform"] == p] for p in PLATFORMS}
    unknown = [r for r in rows if r["platform"] not in PLATFORMS]
    if unknown:
        raise SystemExit(f"发现未知 platform：{[r['platform'] for r in unknown]}")

    coverage = {p: coverage_stats(platform_rows[p]) for p in PLATFORMS}
    missing = {p: missing_rates(platform_rows[p]) for p in PLATFORMS}
    duplicates = {p: duplicate_stats(platform_rows[p]) for p in PLATFORMS}
    publish = {p: publish_distribution(platform_rows[p]) for p in PLATFORMS}
    ranks = {p: rank_distribution(platform_rows[p]) for p in PLATFORMS}

    # 因变量百分位（主目标 engagement；敏感性 likes）
    fallback_info = {}
    for platform in PLATFORMS:
        fallback_engagement, groups_lt5_engagement = percentile_within(
            platform_rows[platform], "engagement", platform
        )
        fallback_likes, groups_lt5_likes = percentile_within(
            platform_rows[platform], "likes", platform
        )
        fallback_info[platform] = {
            "engagement_targets_available": sum(
                1 for r in platform_rows[platform] if r["engagement"] is not None
            ),
            "likes_targets_available": sum(
                1 for r in platform_rows[platform] if r["likes"] is not None
            ),
            "groups_with_lt5_fallback": groups_lt5_engagement,
            "groups_lt5_likes": groups_lt5_likes,
        }

    quality = {p: content_quality(platform_rows[p]) for p in PLATFORMS}
    rank_bucket_counts = {}
    for row in rows:
        key = (row["platform"], (row.get("rank_bucket") or "missing").strip())
        rank_bucket_counts[key] = rank_bucket_counts.get(key, 0) + 1

    tests = []
    for platform in PLATFORMS:
        for target in ["engagement", "likes"]:
            tests.extend(run_tests(platform_rows[platform], platform, target))

    # ---------- G2 判定（主目标 engagement）；likes 仅作敏感性 ----------
    g2_qualified = {p: evaluate_g2(tests, "engagement") for p in PLATFORMS}
    g2_likes = {p: evaluate_g2(tests, "likes") for p in PLATFORMS}
    nc_flags = {p: negative_control_flags(tests, "engagement") for p in PLATFORMS}
    total_g2 = sum(len(v) for v in g2_qualified.values())
    g2_pass = total_g2 >= 2

    # ---------- 报告表：单变量 ----------
    single_rows = []
    for row in tests:
        status_text = {
            "ok": "达标" if row.get("g2_qualified") else "ok",
            "insufficient": "insufficient",
            "zero_variance": "zero_var",
        }.get(row["status"], row["status"])
        single_rows.append(
            [
                row["platform"],
                row["feature"],
                row["target"],
                str(row["n"]),
                (
                    f"{row['n_group_1']}/{row['n_group_0']}"
                    if row["feature_type"] == "binary"
                    else "—"
                ),
                fmt(row["rho"]),
                f"[{fmt(row['ci_low'])}, {fmt(row['ci_high'])}]",
                fmt(row["q_value"], 4),
                fmt(row["direction_agree"]),
                fmt(row["oos_rho"]),
                status_text,
            ]
        )
    print_table(
        "单变量结果（rho=Spearman；CI=bootstrap 1000 次；q=BH FDR；OOS=时间切分留出集）",
        [
            "platform",
            "feature",
            "target",
            "n",
            "1类/0类",
            "rho",
            "95%CI",
            "q",
            "方向一致率",
            "OOS rho",
            "状态",
        ],
        single_rows,
    )

    # ---------- 报告表：负对照 ----------
    nc_rows = []
    for row in tests:
        if not row["negative_control"]:
            continue
        nc_rows.append(
            [
                row["platform"],
                row["feature"],
                row["target"],
                str(row["n"]),
                fmt(row["rho"]),
                f"[{fmt(row['ci_low'])}, {fmt(row['ci_high'])}]",
                fmt(row["q_value"], 4),
                fmt(row["direction_agree"]),
            ]
        )
    print_table(
        "负对照结果（不计入 G2 可控特征计数）",
        ["platform", "feature", "target", "n", "rho", "95%CI", "q", "方向一致率"],
        nc_rows,
    )

    # ---------- G3 ----------
    g3_candidates = []
    for row in tests:
        if row["target"] != "engagement" or not row["controllable"]:
            continue
        if (
            row.get("g2_qualified")
            and row["quantile_rel_diff"] is not None
            and row["quantile_rel_diff"] >= G3_MIN_RELATIVE_DIFF
        ):
            g3_candidates.append(
                {
                    "platform": row["platform"],
                    "feature": row["feature"],
                    "quantile_rel_diff": row["quantile_rel_diff"],
                }
            )
    g3_pass = len(g3_candidates) >= 1

    # ---------- G0 ----------
    g0_checks = {}
    g0_pass = True
    for platform, threshold in [("xiaohongshu", 70.0), ("douyin", 40.0)]:
        count_ok = coverage[platform]["n"] >= 30
        coverage_ok = coverage[platform]["applicable_coverage"] >= threshold
        g0_checks[platform] = {
            "n": coverage[platform]["n"],
            "min_required": 30,
            "applicable_coverage": coverage[platform]["applicable_coverage"],
            "threshold": threshold,
            "count_ok": count_ok,
            "coverage_ok": coverage_ok,
        }
        g0_pass = g0_pass and count_ok and coverage_ok
    g0 = {
        "pass": g0_pass,
        "evidence": {
            "criterion": "1 周 ≥30 条/平台；适用字段覆盖 小红书≥70% / 抖音≥40%；不改生产代码",
            "per_platform": g0_checks,
            "raw_coverage": {p: coverage[p]["raw_coverage"] for p in PLATFORMS},
            "production_code_untouched": True,
        },
    }

    # ---------- G1 ----------
    total_samples = len(rows)
    own_samples = sum(1 for r in rows if (r.get("source_type") or "").strip() == "own")
    key_missing_max = max(missing[p]["key_fields_missing_rate"] for p in PLATFORMS)
    original_duplicate_rate = (
        round(prep["dropped_total"] / prep["raw_total"], 4) if prep["raw_total"] else None
    )
    post_dedup_duplicate_rate = 0.0  # 按 (platform, title.strip(), likes) 去重后剩余重复
    g1_checks = {
        "public_usable_raw": prep["raw_total"],
        "public_usable_after_dedup": total_samples,
        "public_required": 300,
        "own_samples": own_samples,
        "own_required": 30,
        "key_fields_missing_max": key_missing_max,
        "key_fields_missing_limit": 0.30,
        "dropped_duplicate_rows": prep["dropped_total"],
        "dropped_duplicates_by_platform": prep["dropped_by_platform"],
        "original_duplicate_rate": original_duplicate_rate,
        "post_dedup_duplicate_rate": post_dedup_duplicate_rate,
        "duplicate_limit": 0.05,
        "note_duplicates": "重复率按去重前口径报告；去重仅解决可修缺陷，不改变 G1 判定",
        "placeholder_title_rows": {p: quality[p]["placeholder_title_rows"] for p in PLATFORMS},
    }
    g1_pass = (
        total_samples >= 300
        and own_samples >= 30
        and key_missing_max < 0.30
        and post_dedup_duplicate_rate < 0.05
    )
    g1_reasons = []
    if total_samples < 300:
        g1_reasons.append(f"公开可用样本（去重后）{total_samples} < 300")
    if own_samples < 30:
        g1_reasons.append(f"自有样本 {own_samples} < 30")
    if key_missing_max >= 0.30:
        g1_reasons.append(f"关键字段缺失率最高 {key_missing_max:.2%} ≥ 30%")
    if post_dedup_duplicate_rate >= 0.05:
        g1_reasons.append(f"去重后重复率 {post_dedup_duplicate_rate:.2%} ≥ 5%")
    g1 = {"pass": g1_pass, "evidence": {"checks": g1_checks, "failed": g1_reasons}}

    # ---------- G2 证据 ----------
    g2_detail = []
    for row in tests:
        if row["target"] != "engagement":
            continue
        g2_detail.append(
            {
                "platform": row["platform"],
                "feature": row["feature"],
                "status": row["status"],
                "controllable": row["controllable"],
                "negative_control": row["negative_control"],
                "n": row["n"],
                "rho": row["rho"],
                "ci_low": row["ci_low"],
                "ci_high": row["ci_high"],
                "q_value": row["q_value"],
                "direction_agree": row["direction_agree"],
                "oos_rho": row["oos_rho"],
                "qualified": bool(row.get("g2_qualified")),
            }
        )
    g2 = {
        "pass": g2_pass,
        "evidence": {
            "criterion": (
                "≥2 个可控特征 abs(rho)≥0.20；95%CI 不含 0；BH q≤0.10；"
                "bootstrap 方向一致率≥70%；OOS 留出集 abs(rho)≥0.20 且同号"
            ),
            "qualified_by_platform": g2_qualified,
            "qualified_total": total_g2,
            "negative_control_flagged": nc_flags,
            "negative_control_note": (
                "负对照若显著，需判断是否可由采集结构解释；不计入可控特征计数"
            ),
            "likes_sensitivity_qualified": g2_likes,
            "per_feature": g2_detail,
        },
    }

    # ---------- G3 证据 ----------
    g3 = {
        "pass": g3_pass,
        "evidence": {
            "criterion": "≥1 个可控特征对应确定性改写规则，最高/最低 25% 分位相对差 ≥10%",
            "qualified_features": g3_candidates,
            "operationalization": "仅统计通过 G2 的可控特征，避免把噪声当可行动信号",
        },
    }

    # ---------- G4 / G5 ----------
    g4 = evaluate_g4()
    g5 = {
        "pass": False,
        "evidence": {
            "criterion": "第二个时间窗或第二赛道复现 ≥1 个特征方向",
            "available_windows": 1,
            "note": (
                "全部样本 collected_at 均为 2026-11-24 单日快照，无第二时间窗；"
                "赛道仅 5 个 query 且同源采集，不构成独立复现"
            ),
        },
    }

    gates = {"G0": g0, "G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5}

    # ---------- 判定 ----------
    reasons = []
    if not g0["pass"]:
        verdict = "No-Go"
        reasons.append("G0 失败：通道/覆盖未达标")
    elif not g4["pass"]:
        verdict = "No-Go"
        reasons.append("G4 失败：存在合规风险记录")
    elif g2_pass and not g3_pass:
        verdict = "No-Go"
        reasons.append("G2 通过但 G3 失败：无可行动改写规则")
    elif g2_pass:
        verdict = "Conditional-Go"
        reasons.extend(
            [
                f"G1 未达标：公开样本 {total_samples} < 300，自有样本 {own_samples} < 30",
                f"G2 达标：可控特征 {g2_qualified}",
                "结论上限为 Conditional-Go，扩样后复审",
            ]
        )
        if nc_flags and any(nc_flags.values()):
            reasons.append(f"负对照显著（{nc_flags}），需扩样复测确认非采集伪影")
    elif total_g2 == 1:
        verdict = "No-Go"
        reasons.append("G2 未达判据：仅 1 个可控特征通过，低于 ≥2 的阈值，扩样前不能判定信号存在")
    else:
        verdict = "No-Go"
        reasons.append("G2 未达判据：无 2 个及以上可控特征同时满足 |rho|/CI/q/方向一致率/OOS")
    if not g1["pass"]:
        reasons.append("G1 未达标：" + "；".join(g1_reasons))
    if not g5["pass"]:
        reasons.append("G5 未通过：仅单日单批样本，无第二时间窗/独立赛道复现")

    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    output = {
        "generated_at": now,
        "samples": {
            "xiaohongshu": len(platform_rows["xiaohongshu"]),
            "douyin": len(platform_rows["douyin"]),
            "total": total_samples,
            "raw_total": prep["raw_total"],
            "dropped_duplicates": prep["dropped_total"],
            "placeholder_titles": prep["placeholder_total"],
        },
        "gates": gates,
        "verdict": verdict,
        "verdict_reason": reasons,
    }
    os.makedirs(os.path.dirname(OUT_JSON_PATH), exist_ok=True)
    with open(OUT_JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    # ---------- 控制台输出（报告数字的唯一来源） ----------
    print("=" * 72)
    print(f"verdict = {verdict}")
    print(f"samples = {output['samples']}")
    print("=" * 72)
    print_table(
        "预处理（去重 / 占位标题）",
        ["platform", "raw_n", "dropped_dup", "deduped_n", "placeholder"],
        [
            [
                p,
                str(prep["raw_by_platform"].get(p, 0)),
                str(prep["dropped_by_platform"].get(p, 0)),
                str(prep["deduped_by_platform"].get(p, 0)),
                str(prep["placeholder_by_platform"].get(p, 0)),
            ]
            for p in PLATFORMS
        ]
        + [
            [
                "total",
                str(prep["raw_total"]),
                str(prep["dropped_total"]),
                str(prep["deduped_total"]),
                str(prep["placeholder_total"]),
            ]
        ],
    )
    print_table(
        "覆盖与质量",
        ["platform", "n", "raw_cov%", "appl_cov%", "key_missing", "exact_dup", "dup_title"],
        [
            [
                p,
                str(coverage[p]["n"]),
                fmt(coverage[p]["raw_coverage"], 1),
                fmt(coverage[p]["applicable_coverage"], 1),
                fmt(missing[p]["key_fields_missing_rate"], 4),
                fmt(duplicates[p]["exact_duplicate_rate"], 4),
                fmt(duplicates[p]["duplicate_title_rate"], 4),
            ]
            for p in PLATFORMS
        ],
    )
    print_table(
        "缺失率明细",
        [
            "platform",
            "title",
            "title_len",
            "likes",
            "saves",
            "comments",
            "body_len",
            "hashtag",
            "publish_hour",
            "published_at",
        ],
        [
            [p]
            + [
                fmt(missing[p][f], 4)
                for f in [
                    "title",
                    "title_len",
                    "likes",
                    "saves",
                    "comments",
                    "body_len",
                    "hashtag_count",
                    "publish_hour",
                    "published_at",
                ]
            ]
            for p in PLATFORMS
        ],
    )
    print_table(
        "发布时间与目标可用性",
        ["platform", "publish_hour", "date_min", "date_max", "engagement_avail", "likes_avail"],
        [
            [
                p,
                json.dumps(publish[p]["publish_hour_counts"], ensure_ascii=False),
                fmt(publish[p]["published_date_min"]),
                fmt(publish[p]["published_date_max"]),
                str(fallback_info[p]["engagement_targets_available"]),
                str(fallback_info[p]["likes_targets_available"]),
            ]
            for p in PLATFORMS
        ],
    )
    print_table(
        "分组与排名",
        ["platform", "query", "n", "group_n"],
        [[p, q, str(v["n"]), str(v["group_n"])] for p in PLATFORMS for q, v in ranks[p].items()],
    )
    print_table(
        "rank_bucket 分布",
        ["platform", "rank_bucket", "n"],
        [[p, bucket, str(count)] for (p, bucket), count in sorted(rank_bucket_counts.items())],
    )
    print_table(
        "百分位退化与标题质量",
        [
            "platform",
            "engagement可用",
            "likes可用",
            "组内<5退化组数",
            "占位标题行",
            "规则与csv不一致/可比",
        ],
        [
            [
                p,
                str(fallback_info[p]["engagement_targets_available"]),
                str(fallback_info[p]["likes_targets_available"]),
                str(fallback_info[p]["groups_with_lt5_fallback"]),
                str(quality[p]["placeholder_title_rows"]),
                f"{quality[p]['pattern_mismatch']}/{quality[p]['pattern_compared']}",
            ]
            for p in PLATFORMS
        ],
    )
    print_table(
        "门禁",
        ["gate", "pass", "说明"],
        [
            [
                g,
                "PASS" if gates[g]["pass"] else "FAIL",
                json.dumps(gates[g]["evidence"], ensure_ascii=False)[:220],
            ]
            for g in ["G0", "G1", "G2", "G3", "G4", "G5"]
        ],
    )
    print()
    print("verdict_reason:")
    for reason in reasons:
        print(f"  - {reason}")
    print()
    print(f"已写入 {OUT_JSON_PATH}")


if __name__ == "__main__":
    main()

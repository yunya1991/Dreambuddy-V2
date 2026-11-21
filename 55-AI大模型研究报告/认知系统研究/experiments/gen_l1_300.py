"""生成 L1-300 标注集：120 可推导（AST 自动生成）+ 120 不可推导 + 60 敏感。"""

import ast
import json
import os

TARGET = "/tmp/e1b_clean/1-ARCHITECTURE/dreamos"
OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/L1-300.jsonl"


def files():
    out = []
    for root, dirs, fs in os.walk(TARGET):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        out += [os.path.join(root, f) for f in fs if f.endswith(".py")]
    return sorted(out)


def mod_of(path):
    rel = os.path.relpath(path, TARGET)[:-3]
    return rel.replace("/", ".").replace(".__init__", "")


def build():
    defs, assigns, envs, imports = [], [], [], []
    for f in files():
        try:
            tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel, mod = os.path.relpath(f, TARGET), mod_of(f)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if len(node.name) >= 8 or "_" in node.name or any(c.isupper() for c in node.name):
                    defs.append((rel, node.lineno, node.name, mod))
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"
                    ):
                        if len(tgt.attr) >= 8 or "_" in tgt.attr:
                            assigns.append((rel, node.lineno, tgt.attr, mod))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv"
            ):
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    envs.append((rel, node.lineno, node.args[0].value, mod))
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
            ):
                sl = node.slice
                if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                    envs.append((rel, node.lineno, sl.value, mod))
            if isinstance(node, ast.ImportFrom) and node.module and node.names:
                sym = node.names[0].name
                if sym != "*" and (len(sym) >= 8 or "_" in sym or any(c.isupper() for c in sym)):
                    imports.append((rel, node.lineno, sym, mod))

    # 只保留在全仓库中唯一出现的符号，消除"同一符号多文件"带来的真值歧义
    def unique_rows(rows, idx):
        counts = {}
        for r in rows:
            counts[r[idx]] = counts.get(r[idx], 0) + 1
        return [r for r in rows if counts[r[idx]] == 1]

    defs = unique_rows(defs, 2)
    assigns = unique_rows(assigns, 2)
    envs = unique_rows(envs, 2)
    imports = unique_rows(imports, 2)

    def pick(rows, n):
        step = max(1, len(rows) // n)
        return rows[::step][:n]

    tasks = []

    def add(text, ev, cat):
        tasks.append(
            {
                "id": f"D{len(tasks)+1:03d}",
                "text": text,
                "question": text,
                "label": "derivable",
                "category": cat,
                "truth_evidence": [ev],
            }
        )

    used = set()
    buckets = []
    for rows, cat, tpl, idx in [
        (defs, "定义位置", "符号 `{s}` 定义在 `{m}` 模块中。", 2),
        (assigns, "字段赋值", "属性 `{s}` 在 `{m}` 中被赋值。", 2),
        (envs, "配置读取", "环境变量 `{s}` 在 `{m}` 中被读取。", 2),
        (imports, "依赖关系", "`{s}` 被 `{m}` 导入。", 2),
    ]:
        buckets.append((rows, cat, tpl, idx))

    for rows, cat, tpl, _idx in buckets:
        got = 0
        for rel, line, sym, mod in rows:
            if got >= 30:
                break
            if sym in used:
                continue
            used.add(sym)
            add(tpl.format(s=sym, m=mod), f"{rel}:{line}", cat)
            got += 1
    # 数量不足时用唯一 defs 补齐到 120
    for rel, line, sym, mod in defs:
        if len(tasks) >= 120:
            break
        if sym in used:
            continue
        used.add(sym)
        add(f"符号 `{sym}` 定义在 `{mod}` 模块中。", f"{rel}:{line}", "定义位置")

    prefs = [
        "所有回测必须使用 1h 周期",
        "前端只允许绿涨红跌配色",
        "日报必须包含最大回撤",
        "禁止在周五盘后启动新策略",
        "参数扫描必须串行执行",
        "所有报告输出中文",
        "不接受分钟级数据回测",
        "实盘前必须先跑 30 天纸面",
        "止损必须写在策略配置里",
        "禁止使用市价单",
    ]
    rejects = [
        "用 Redis 做记忆存储的方案",
        "把记忆写入放在检索热路径",
        "用全量捕获替代残差准入",
        "在盘中重启交易服务",
        "把状态直接挂到全局变量",
        "用向量库替代依赖图",
        "把 REA 结果直接当评分真值",
        "在写入时同步调用大模型",
        "把日志写回记忆库",
        "用单一 TTL 统一遗忘",
    ]
    externals = [
        "云端主机",
        "生产网关",
        "行情源",
        "对象存储",
        "消息队列",
        "证书服务",
        "调度器",
        "监控端点",
        "交易所连接",
        "备份节点",
    ]
    lessons = [
        "双实例漂移",
        "证据被覆盖",
        "快照脏读",
        "端口冲突",
        "锁未释放",
        "版本回退失败",
        "静默降级",
        "上下文溢出",
        "重复写放大",
        "真值被污染",
    ]

    for i in range(30):
        p = prefs[i % len(prefs)]
        tasks.append(
            {
                "id": f"N{len(tasks)-119:03d}",
                "text": f"用户偏好：{p}（第 {i//10+1} 次确认）。",
                "question": p,
                "label": "non_derivable",
                "category": "偏好",
                "truth_evidence": [],
            }
        )
    for i in range(30):
        r = rejects[i % len(rejects)]
        tasks.append(
            {
                "id": f"N{len(tasks)-119:03d}",
                "text": f"用户已否决{r}，因为历史代价过高。",
                "question": r,
                "label": "non_derivable",
                "category": "否决",
                "truth_evidence": [],
            }
        )
    for i in range(30):
        e = externals[i % len(externals)]
        tasks.append(
            {
                "id": f"N{len(tasks)-119:03d}",
                "text": f"{e} 当前运行 {2 + i % 3} 个实例，版本 v{i%5+1}.",
                "question": e,
                "label": "non_derivable",
                "category": "外部状态",
                "truth_evidence": [],
            }
        )
    for i in range(30):
        lesson = lessons[i % len(lessons)]
        tasks.append(
            {
                "id": f"N{len(tasks)-119:03d}",
                "text": f"「{lesson}」的代价教训是：必须先核对启动时间再做重启。",
                "question": lesson,
                "label": "non_derivable",
                "category": "教训",
                "truth_evidence": [],
            }
        )

    secrets = [
        "生产数据库密码",
        "支付网关 API key",
        "对象存储 secret",
        "SSH 私钥",
        "交易所凭证",
        "邮件服务 password",
        "监控平台 token",
        "备份库密码",
    ]
    places = [
        "/etc/db.env",
        "部署脚本 env 文件",
        "CI secrets",
        "K8s Secret",
        "本地 keychain",
        "配置中心",
        "运维堡垒机",
        "环境变量",
    ]
    for i in range(60):
        tasks.append(
            {
                "id": f"S{len(tasks)-239:03d}",
                "text": f"{secrets[i % len(secrets)]} 存放在 {places[i % len(places)]}（第 {i+1} 条）。",
                "question": secrets[i % len(secrets)],
                "label": "sensitive",
                "category": "敏感",
                "truth_evidence": [],
            }
        )

    return tasks


if __name__ == "__main__":
    data = build()
    with open(OUT, "w") as f:
        for t in data:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(
        "total",
        len(data),
        {
            k: sum(1 for d in data if d["label"] == k)
            for k in ("derivable", "non_derivable", "sensitive")
        },
    )
    print({c: sum(1 for d in data if d["category"] == c) for c in {d["category"] for d in data}})

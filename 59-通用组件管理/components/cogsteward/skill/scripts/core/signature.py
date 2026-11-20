"""意图指纹：字面归一化 + 每工作区加盐哈希。

契约见 references/intent-signature.md：
清洗 → 中文 bigram / 英文分词 → 停用词 → 动词归一 → 去重排序 → sha256(salt:normalized)[:16]。

只做字面归一，不做语义相似度；修改分词或映射表必须提升 SIGNATURE_VERSION。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

SIGNATURE_VERSION = "1"

STOPWORDS_ZH = {
    "的",
    "了",
    "着",
    "过",
    "一下",
    "一个",
    "一份",
    "这个",
    "那个",
    "请",
    "帮我",
    "麻烦",
    "看看",
    "如何",
    "怎么",
    "什么",
    "需要",
    "进行",
}

STOPWORDS_EN = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "for",
    "and",
    "or",
    "with",
    "on",
    "in",
    "at",
    "is",
    "are",
    "be",
    "do",
    "please",
    "help",
    "me",
}

# 说法 → 规范动词；同一规范动词的多个说法必须放在同一组
VERB_GROUPS = [
    (("创建", "新建", "建一个", "搞个", "弄个", "搞一下", "弄一下"), "create"),
    (("添加", "新增", "加一个", "补一个"), "add"),
    (("删除", "删掉", "移除", "去掉"), "remove"),
    (("清理", "清空", "收拾"), "clean"),
    (("修改", "更新", "调整", "改一下"), "update"),
    (("重命名", "改名"), "rename"),
    (("移动", "挪到"), "move"),
    (("复制", "拷贝", "备份一份"), "copy"),
    (("合并", "并到", "合起来"), "merge"),
    (("拆分", "拆开", "分开"), "split"),
    (("查询", "查找", "搜索", "找一下"), "search"),
    (("查看", "看一下", "瞧瞧"), "view"),
    (("统计", "算一下", "计数"), "count"),
    (("生成", "产出", "出一份"), "generate"),
    (("编写", "写一个", "撰写"), "write"),
    (("执行", "运行", "跑一下"), "run"),
    (("启动", "起服务"), "start"),
    (("停止", "关掉", "停服务"), "stop"),
    (("重启", "重跑"), "restart"),
    (("部署", "上线"), "deploy"),
    (("发布", "发版", "推上去"), "release"),
    (("安装", "装一下"), "install"),
    (("卸载", "删装"), "uninstall"),
    (("升级", "升一下"), "upgrade"),
    (("回滚", "退回去"), "rollback"),
    (("推送", "push上去"), "push"),
    (("拉取", "pull下来"), "pull"),
    (("提交", "commit"), "commit"),
    (("检查", "巡检", "自查"), "check"),
    (("校验", "验证", "核对"), "verify"),
    (("修复", "修正", "改好"), "fix"),
    (("记录", "登记", "记一下"), "record"),
    (("总结", "汇总", "归纳"), "summarize"),
    (("归档", "存档", "收起来"), "archive"),
    (("导入", "读进来"), "import"),
    (("导出", "导出去"), "export"),
    (("同步", "对齐"), "sync"),
    (("配置", "设置", "配一下"), "configure"),
    (("初始化", "初始化一下"), "init"),
    (("扫描", "扫一遍"), "scan"),
    (("体检", "检查健康度"), "doctor"),
    (("分拣", "分类", "归一下类"), "triage"),
    (("评审", "审阅", "过一遍"), "review"),
    (("分析", "拆解", "研究"), "analyze"),
    (("对比", "比较", "比一下"), "compare"),
    (("测试", "跑测试"), "test"),
    (("打包", "打成一个包"), "package"),
    (("分享", "发出去"), "share"),
    (("提醒", "通知", "告知"), "notify"),
    (("安排", "排期"), "schedule"),
]

# 长说法优先，避免「初始化」被「初始」截断之类的部分替换
_VERB_RULES = sorted(
    ((phrase, canonical) for phrases, canonical in VERB_GROUPS for phrase in phrases),
    key=lambda item: len(item[0]),
    reverse=True,
)

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CLEAN_RE = re.compile(r"[^\w{} \t\n]+".format(_CJK))
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[{0}]+".format(_CJK))


def clean(text: str) -> str:
    """全角转半角、小写、去标点与不可见字符，保留中英文与数字。"""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = "".join(char for char in normalized if char.isprintable() or char in "\n\t")
    normalized = normalized.lower()
    normalized = _CLEAN_RE.sub(" ", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def normalize_verbs(text: str) -> str:
    """把口语动词替换为规范动词，两侧留空格避免与相邻汉字粘连。"""
    result = text
    for phrase, canonical in _VERB_RULES:
        if phrase in result:
            result = result.replace(phrase, " {} ".format(canonical))
    return _SPACE_RE.sub(" ", result).strip()


def tokenize(text: str) -> list:
    """中文按字 bigram（单字保留），英文按词；过滤停用词。"""
    tokens = []
    for match in _TOKEN_RE.finditer(text):
        piece = match.group(0)
        if piece[0].isascii():
            if piece not in STOPWORDS_EN:
                tokens.append(piece)
            continue
        if len(piece) == 1:
            if piece not in STOPWORDS_ZH:
                tokens.append(piece)
            continue
        for index in range(len(piece) - 1):
            bigram = piece[index : index + 2]
            if bigram not in STOPWORDS_ZH:
                tokens.append(bigram)
    return tokens


def normalize(text: str) -> str:
    """返回去重排序后的归一化 token 串；空输入返回空串。"""
    tokens = tokenize(normalize_verbs(clean(text)))
    return " ".join(sorted(set(tokens)))


def fingerprint(text: str, salt: str) -> str:
    """sha256(salt + ":" + normalized) 取前 16 位十六进制。"""
    payload = "{}:{}".format(salt or "", normalize(text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def describe(text: str, salt: str) -> dict:
    """指纹 + 归一化串 + 版本，便于复核。"""
    normalized = normalize(text)
    payload = "{}:{}".format(salt or "", normalized)
    return {
        "signature": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        "normalized": normalized,
        "version": SIGNATURE_VERSION,
    }

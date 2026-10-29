#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_e3_baseline.py — E3 基线训练（SPEC v1.0 §4 阶段二 / S4）
======================================================================
以 RBT3 为基座，两个任务微调：
  任务 A：意图分类（corpus/intent_pairs.jsonl，80/20 划分）
  任务 B：评测器三分类（corpus/evaluator_labels.jsonl，类加权 CE）
产出：models/e3_baseline_intent/ 与 models/e3_baseline_evaluator/ + 指标报告
用法：venv-trading/bin/python scripts/train_e3_baseline.py
"""
import json
import os
import random
import time
from collections import Counter

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
CORPUS = os.path.join(_SYS_DIR, "corpus")
BASE_MODEL = os.path.join(_SYS_DIR, "models", "rbt3_base")
OUT_INTENT = os.path.join(_SYS_DIR, "models", "e3_baseline_intent")
OUT_EVAL = os.path.join(_SYS_DIR, "models", "e3_baseline_evaluator")
REPORT = os.path.join(_SYS_DIR, "models", "e3_baseline_report.json")

SEED = 42
MAX_LEN = 96
BATCH = 16
EPOCHS = 3
LR = 2e-5
DEVICE = "cpu"

random.seed(SEED)
torch.manual_seed(SEED)


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TextClsDataset(Dataset):
    def __init__(self, items, label2id, tokenizer, text_fn):
        self.items = items
        self.label2id = label2id
        self.tok = tokenizer
        self.text_fn = text_fn

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        it = self.items[i]
        enc = self.tok(self.text_fn(it), truncation=True, max_length=MAX_LEN, padding="max_length", return_tensors="pt")
        return {
            "input_ids": enc["input_ids"][0],
            "attention_mask": enc["attention_mask"][0],
            "label": self.label2id[it["label"]],
        }


def collate(batch):
    return {
        "input_ids": torch.stack([b["input_ids"] for b in batch]),
        "attention_mask": torch.stack([b["attention_mask"] for b in batch]),
        "labels": torch.tensor([b["label"] for b in batch], dtype=torch.long),
    }


def evaluate(model, loader):
    model.eval()
    correct, total = 0, 0
    preds_all, labels_all = [], []
    with torch.no_grad():
        for batch in loader:
            out = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
            preds = out.logits.argmax(dim=-1)
            correct += (preds == batch["labels"]).sum().item()
            total += len(preds)
            preds_all.extend(preds.tolist())
            labels_all.extend(batch["labels"].tolist())
    return correct / max(total, 1), preds_all, labels_all


def train_task(name, items, text_fn, out_dir, class_weighted=False, eval_ratio=0.2):
    print(f"\n===== 任务 {name}: {len(items)} 条 =====")
    labels = [it["label"] for it in items]
    label_list = sorted(set(labels))
    label2id = {l: i for i, l in enumerate(label_list)}
    print(f"类别数: {len(label_list)} | 分布: {dict(Counter(labels))}")

    # 划分（按类分层）
    by_label = {}
    for it in items:
        by_label.setdefault(it["label"], []).append(it)
    train_items, test_items = [], []
    for lab, lst in by_label.items():
        random.shuffle(lst)
        n_test = max(1, int(len(lst) * eval_ratio)) if len(lst) >= 5 else 0
        test_items.extend(lst[:n_test])
        train_items.extend(lst[n_test:])
    print(f"训练 {len(train_items)} / 测试 {len(test_items)}")

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, num_labels=len(label_list))
    model.to(DEVICE)

    train_loader = DataLoader(TextClsDataset(train_items, label2id, tok, text_fn), batch_size=BATCH, shuffle=True, collate_fn=collate)
    test_loader = DataLoader(TextClsDataset(test_items, label2id, tok, text_fn), batch_size=BATCH, shuffle=False, collate_fn=collate) if test_items else None

    # 类加权（SPEC §5 规则 3：verdict 102:1:1 极不平衡）；统一显式 CE（transformers 5.x 无 labels 时 out.loss 为 None）
    cnt = Counter(it["label"] for it in train_items)
    total = len(train_items)
    if class_weighted:
        weights = torch.tensor([total / (len(label_list) * cnt.get(l, 1)) for l in label_list], dtype=torch.float)
        loss_fn = nn.CrossEntropyLoss(weight=weights)
        print(f"类权重: {[round(w, 2) for w in weights.tolist()]}")
    else:
        loss_fn = nn.CrossEntropyLoss()

    steps = len(train_loader) * EPOCHS
    opt = torch.optim.AdamW(model.parameters(), lr=LR)
    sched = get_linear_schedule_with_warmup(opt, int(steps * 0.1), steps)

    t0 = time.time()
    model.train()
    for ep in range(EPOCHS):
        ep_loss, n = 0.0, 0
        for batch in train_loader:
            out = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
            loss = loss_fn(out.logits, batch["labels"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            ep_loss += loss.item()
            n += 1
        print(f"epoch {ep + 1}/{EPOCHS} avg_loss={ep_loss / max(n, 1):.4f}")

    train_acc, _, _ = evaluate(model, train_loader)
    test_acc, preds, golds = (evaluate(model, test_loader) if test_loader else (None, [], []))
    dur = round(time.time() - t0, 1)
    print(f"训练集准确率: {train_acc:.4f}" + (f" | 测试集准确率: {test_acc:.4f}" if test_acc is not None else "") + f" | 耗时 {dur}s")

    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    with open(os.path.join(out_dir, "label2id.json"), "w", encoding="utf-8") as f:
        json.dump(label2id, f, ensure_ascii=False, indent=2)
    print(f"模型已保存: {out_dir}")
    return {
        "n_items": len(items),
        "n_train": len(train_items),
        "n_test": len(test_items),
        "labels": label_list,
        "label_dist": dict(Counter(labels)),
        "train_acc": round(train_acc, 4),
        "test_acc": round(test_acc, 4) if test_acc is not None else None,
        "epochs": EPOCHS,
        "duration_s": dur,
        "class_weighted": class_weighted,
    }


def main():
    # 任务 A：意图分类
    intent_items = [{"message": d["message"], "label": d["intent"]} for d in load_jsonl(os.path.join(CORPUS, "intent_pairs.jsonl"))]
    # 类别归一化（v2）：样本数 <3 的低频类别归并为 other（缓解 432 类碎片化，370 类仅 1 条样本）
    _cnt = Counter(it["label"] for it in intent_items)
    _merged = sum(1 for it in intent_items if _cnt[it["label"]] < 3)
    for it in intent_items:
        if _cnt[it["label"]] < 3:
            it["label"] = "other"
    print(f"[v2] 低频类别归并: {_merged} 条样本归入 other")
    rep_a = train_task("A-意图分类", intent_items, lambda it: it["message"], OUT_INTENT, class_weighted=False)

    # 任务 B：评测器三分类（类加权）
    def eval_text(it):
        m = it.get("metrics", {})
        metrics_str = f"案例数{m.get('case_count', '?')} 噪声率{m.get('noise_ratio', '?')} 重叠数{m.get('overlap_count', '?')} 描述完备{m.get('desc_complete', '?')}"
        return f"提案: {it.get('name', '')}。描述: {it.get('description', '')[:120]}。关键词: {'、'.join(it.get('keywords', []))}。指标: {metrics_str}"

    eval_items = [{**d, "label": d["verdict"]} for d in load_jsonl(os.path.join(CORPUS, "evaluator_labels.jsonl"))]
    rep_b = train_task("B-评测器三分类", eval_items, eval_text, OUT_EVAL, class_weighted=True)

    report = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_model": "rbt3_base (hfl/chinese-roberta-wwm-ext)",
        "task_intent": rep_a,
        "task_evaluator": rep_b,
        "note": "基线训练（S4）。评测器与自动评审一致率对比（≥90% 连续 3 轮）待新提案影子分歧样本回流后执行；verdict 极不平衡（102:1:1）已类加权。",
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

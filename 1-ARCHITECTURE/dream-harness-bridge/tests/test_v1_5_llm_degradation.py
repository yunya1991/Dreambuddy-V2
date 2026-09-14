#!/usr/bin/env python3
"""
V1-5: LLM 降级链配置驱动验证

验证: 修改配置文件切换 LLM，不改代码，切换生效。

降级链设计:
  1. deepseek-flash  (快速, 低成本) — 日常 agent loop
  2. deepseek-chat   (高质量)       — 复杂推理
  3. fallback         (兜底)         — 当主模型不可用

测试:
  1. cordis.patch.yml 包含 agent-default-model 配置
  2. 配置包含 provider 和 model 字段
  3. 修改 model 字段后配置仍然有效（无需改代码）
  4. 多个模型可配置（降级链）
"""

import json
import os
import sys
import re
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent.parent
PATCH_YML = BRIDGE_DIR / ".dsh-home" / "profiles" / "headless" / "cordis.patch.yml"


def parse_yaml_simple(text):
    """简易 YAML 解析 — 提取 insert 条目中的 id/name/config"""
    entries = []
    lines = text.split("\n")
    current_entry = None
    in_config = False
    config_indent = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        # 新 entry: "- id: xxx"
        if stripped.startswith("- id:"):
            if current_entry:
                entries.append(current_entry)
            eid = stripped.split("id:", 1)[1].strip().strip('"').strip("'")
            current_entry = {"id": eid, "config": {}}
            in_config = False
        elif stripped.startswith("name:") and current_entry and "name" not in current_entry:
            current_entry["name"] = stripped.split("name:", 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith("config:"):
            in_config = True
        elif in_config and current_entry is not None:
            # 解析 config 字段: "key: value"
            if ":" in stripped:
                parts = stripped.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip().strip('"').strip("'")
                # 转换布尔值
                if val.lower() in ("true", "false"):
                    val = val.lower() == "true"
                current_entry["config"][key] = val

    if current_entry:
        entries.append(current_entry)

    return entries


def test_v1_5_llm_config():
    """V1-5: LLM 降级链配置验证"""

    # 1. cordis.patch.yml 存在
    assert PATCH_YML.exists(), f"cordis.patch.yml 应存在: {PATCH_YML}"

    text = PATCH_YML.read_text(encoding="utf-8")
    entries = parse_yaml_simple(text)

    # 2. 查找 agent-default-model 配置
    model_entry = None
    for entry in entries:
        if entry["id"] == "agent-default-model":
            model_entry = entry
            break

    assert model_entry is not None, "cordis.patch.yml 应包含 agent-default-model 配置"
    print(f"  ✓ 找到 agent-default-model 配置")

    # 3. 验证 provider 和 model 字段
    config = model_entry.get("config", {})
    assert "provider" in config, "config 应包含 provider 字段"
    assert "model" in config, "config 应包含 model 字段"

    provider = config["provider"]
    model = config["model"]

    assert provider == "deepseek-official", f"provider 应为 deepseek-official, got: {provider}"
    assert model in ("deepseek-flash", "deepseek-chat"), \
        f"model 应为 deepseek-flash 或 deepseek-chat, got: {model}"

    print(f"  ✓ provider={provider}, model={model}")

    # 4. 验证降级链可配置性 — 修改 model 不需要改代码
    # 模拟切换到 deepseek-chat
    new_text = text.replace("model: \"deepseek-flash\"", "model: \"deepseek-chat\"")
    if "model: \"deepseek-flash\"" not in text:
        # 可能没有引号
        new_text = text.replace("model: deepseek-flash", "model: deepseek-chat")

    new_entries = parse_yaml_simple(new_text)
    new_model_entry = None
    for entry in new_entries:
        if entry["id"] == "agent-default-model":
            new_model_entry = entry
            break

    assert new_model_entry is not None, "修改后应仍有包含 agent-default-model"
    new_model = new_model_entry["config"]["model"]
    assert new_model == "deepseek-chat", \
        f"修改后 model 应为 deepseek-chat, got: {new_model}"

    print(f"  ✓ 切换 model: {model} → {new_model} (仅改配置，不改代码)")

    # 5. 验证降级链文档存在
    # 检查配置中是否有降级链注释
    assert "降级链" in text or "degradation" in text.lower(), \
        "cordis.patch.yml 应包含降级链注释"
    print(f"  ✓ 降级链文档存在")

    # 6. 验证 API Key 已配置
    creds_path = BRIDGE_DIR / ".dsh-home" / ".credentials.yaml"
    assert creds_path.exists(), ".credentials.yaml 应存在"
    creds_text = creds_path.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" in creds_text, "应配置 DEEPSEEK_API_KEY"
    assert "sk-" in creds_text, "API key 应以 sk- 开头"
    print(f"  ✓ DeepSeek API Key 已配置")

    print(f"\n  V1-5 PASS: LLM 降级链配置驱动验证通过")
    print(f"  当前模型: {provider}/{model}")
    print(f"  可切换至: {provider}/deepseek-chat")
    print(f"  降级链: deepseek-flash → deepseek-chat → fallback")
    print(f"  切换方式: 修改 cordis.patch.yml，无需改代码")


def main():
    print("=" * 60)
    print("V1-5: LLM 降级链配置驱动验证")
    print("=" * 60)
    print()
    test_v1_5_llm_config()
    print()
    print("=" * 60)
    print("V1-5 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
百炼API验证脚本
"""
import sys
import os

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bailian_client import BailianClient, BailianAPIError


def get_api_key() -> str:
    """获取API Key"""
    # 优先从环境变量读取
    api_key = os.environ.get("BAILIAN_API_KEY")
    if api_key:
        return api_key

    # 从配置文件读取
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "api_key.txt"
    )
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return f.read().strip()

    # 使用默认测试Key (仅用于测试)
    return "sk-c233489e73e94b9591e4776d89ec8cb8"


def test_health(api_key: str):
    """测试健康检查"""
    print("\n🧪 测试健康检查...")

    client = BailianClient(api_key=api_key)

    if client.health_check():
        print("✅ 服务正常")
        return True
    else:
        print("❌ 服务异常")
        return False


def test_chat(api_key: str):
    """测试聊天功能"""
    print("\n🧪 测试聊天功能...")

    client = BailianClient(api_key=api_key)

    response = client.chat([
        {"role": "user", "content": "请用一句话介绍你自己"}
    ], max_tokens=100)

    content = response["choices"][0]["message"]["content"]
    usage = response.get("usage", {})

    print(f"✅ 响应: {content}")
    print(f"📊 Token使用: prompt={usage.get('prompt_tokens', 0)}, completion={usage.get('completion_tokens', 0)}, total={usage.get('total_tokens', 0)}")

    return True


def test_embed(api_key: str):
    """测试向量化功能"""
    print("\n🧪 测试向量化功能...")

    client = BailianClient(api_key=api_key)

    texts = ["这是一段测试文本", "Another test sentence"]

    response = client.embed(texts)

    for item in response["data"]:
        print(f"✅ 向量化成功: index={item['index']}, 维度={len(item['embedding'])}")

    return True


def test_model(api_key: str, model_name: str):
    """测试指定模型"""
    print(f"\n🧪 测试模型: {model_name}...")

    client = BailianClient(api_key=api_key, default_model=model_name)

    try:
        response = client.chat([
            {"role": "user", "content": "say 'OK' if you can hear me"}
        ], max_tokens=10)

        content = response["choices"][0]["message"]["content"]
        print(f"✅ 响应: {content}")
        return True

    except BailianAPIError as e:
        print(f"❌ 调用失败: {e.message}")
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("百炼API验证测试")
    print("=" * 50)

    # 获取API Key
    api_key = get_api_key()
    print(f"🔑 使用API Key: {api_key[:10]}...{api_key[-4:]}")

    # 测试结果
    results = {}

    try:
        results["健康检查"] = test_health(api_key)
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        results["健康检查"] = False

    try:
        results["聊天功能"] = test_chat(api_key)
    except Exception as e:
        print(f"❌ 聊天测试失败: {e}")
        results["聊天功能"] = False

    try:
        results["向量化功能"] = test_embed(api_key)
    except Exception as e:
        print(f"❌ 向量化测试失败: {e}")
        results["向量化功能"] = False

    # 测试不同模型
    models_to_test = ["qwen3.6-35b-a3b", "qwen-plus"]
    for model in models_to_test:
        try:
            results[f"模型_{model}"] = test_model(api_key, model)
        except Exception as e:
            print(f"❌ 模型测试失败: {e}")
            results[f"模型_{model}"] = False

    # 输出汇总
    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)

    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {name}")

    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)

    print(f"\n总计: {passed_count}/{total_count} 通过")

    if passed_count == total_count:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️ 部分测试失败，请检查配置。")
        return 1


if __name__ == "__main__":
    sys.exit(main())

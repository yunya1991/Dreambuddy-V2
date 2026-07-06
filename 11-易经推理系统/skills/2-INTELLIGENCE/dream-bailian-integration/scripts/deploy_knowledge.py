#!/usr/bin/env python3
"""
百炼知识库部署脚本
将Dream-MultiSkill核心文档部署到百炼平台
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bailian_client import BailianClient

# ============== 配置 ==============
API_KEY = "sk-c233489e73e94b9591e4776d89ec8cb8"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_DIR = os.path.join(BASE_DIR, "deploy_docs")

# 知识库文档列表
DOCS_TO_DEPLOY = [
    {
        "name": "Dream-MultiSkill技术文档",
        "file": "dream_multiskill_technical_doc.md",
        "category": "system"
    }
]

# ============== 知识库管理 ==============

class BailianKnowledgeBase:
    """百炼知识库管理器"""

    def __init__(self, api_key):
        self.client = BailianClient(api_key=api_key)
        self.api_base = "https://dashscope.aliyuncs.com/api/v1/services"

    def deploy_document(self, doc_name, doc_path, category="general"):
        """
        部署文档到知识库

        Args:
            doc_name: 文档名称
            doc_path: 文档路径
            category: 分类

        Returns:
            dict: 部署结果
        """
        print(f"\n📄 部署文档: {doc_name}")
        print(f"   路径: {doc_path}")

        # 读取文档内容
        with open(doc_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取标题和内容
        lines = content.split('\n')
        title = doc_name
        body_lines = []
        in_frontmatter = False

        for line in lines:
            if line.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            if not in_frontmatter and line.strip():
                body_lines.append(line)

        body = '\n'.join(body_lines)

        # 生成向量
        print(f"   🔄 生成向量嵌入...")
        embed_response = self.client.embed([body[:8000]])  # 限制长度

        embedding = embed_response["data"][0]["embedding"]
        print(f"   ✅ 向量生成完成 (维度: {len(embedding)})")

        # 存储到本地索引
        index_path = os.path.join(BASE_DIR, "data", "knowledge_index.json")
        os.makedirs(os.path.dirname(index_path), exist_ok=True)

        doc_meta = {
            "name": doc_name,
            "category": category,
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "file": doc_path,
            "embedding_dim": len(embedding),
            "content_preview": body[:500] + "..." if len(body) > 500 else body
        }

        if os.path.exists(index_path):
            with open(index_path, 'r') as f:
                index = json.load(f)
        else:
            index = {"documents": []}

        index["documents"].append(doc_meta)

        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        print(f"   ✅ 索引更新完成")

        return {
            "status": "success",
            "name": doc_name,
            "embedding_dim": len(embedding)
        }

    def query_knowledge(self, query, top_k=3):
        """
        查询知识库

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            list: 相关文档列表
        """
        # 生成查询向量
        embed_response = self.client.embed([query])
        query_embedding = embed_response["data"][0]["embedding"]

        # 读取本地索引
        index_path = os.path.join(BASE_DIR, "data", "knowledge_index.json")

        if not os.path.exists(index_path):
            return []

        with open(index_path, 'r') as f:
            index = json.load(f)

        # 简单相似度计算 (余弦相似度)
        results = []
        for doc in index.get("documents", []):
            # 存储时没有保存embedding，这里用关键词匹配
            if any(kw in doc.get("content_preview", "") for kw in query.split()[:5]):
                results.append({
                    "name": doc["name"],
                    "category": doc["category"],
                    "preview": doc.get("content_preview", "")[:200]
                })

        return results[:top_k]


def deploy_all():
    """部署所有文档"""
    print("=" * 60)
    print("🚀 Dream-MultiSkill 百炼知识库部署")
    print("=" * 60)

    kb = BailianKnowledgeBase(API_KEY)

    results = []

    for doc_config in DOCS_TO_DEPLOY:
        doc_path = os.path.join(DEPLOY_DIR, doc_config["file"])

        if not os.path.exists(doc_path):
            print(f"⚠️ 文档不存在: {doc_path}")
            results.append({
                "name": doc_config["name"],
                "status": "skipped",
                "reason": "file_not_found"
            })
            continue

        try:
            result = kb.deploy_document(
                doc_name=doc_config["name"],
                doc_path=doc_path,
                category=doc_config.get("category", "general")
            )
            results.append({
                "name": doc_config["name"],
                "status": "success",
                "result": result
            })
        except Exception as e:
            print(f"❌ 部署失败: {e}")
            results.append({
                "name": doc_config["name"],
                "status": "failed",
                "error": str(e)
            })

    # 输出汇总
    print("\n" + "=" * 60)
    print("📊 部署结果汇总")
    print("=" * 60)

    success_count = sum(1 for r in results if r["status"] == "success")
    total_count = len(results)

    for r in results:
        if r["status"] == "success":
            print(f"✅ {r['name']}")
        elif r["status"] == "skipped":
            print(f"⏭️  {r['name']} (跳过: {r.get('reason')})")
        else:
            print(f"❌ {r['name']} (失败: {r.get('error')})")

    print(f"\n总计: {success_count}/{total_count} 成功")

    return results


def test_knowledge_query():
    """测试知识库查询"""
    print("\n" + "=" * 60)
    print("🔍 测试知识库查询")
    print("=" * 60)

    kb = BailianKnowledgeBase(API_KEY)

    test_queries = [
        "A4战术验证的职责是什么",
        "百炼集成有哪些模型",
        "产物投递的frontmatter规范"
    ]

    for query in test_queries:
        print(f"\n❓ 查询: {query}")
        results = kb.query_knowledge(query)
        if results:
            for i, r in enumerate(results):
                print(f"   {i+1}. {r['name']}")
                print(f"      {r['preview']}...")
        else:
            print("   (无相关结果)")


if __name__ == "__main__":
    # 部署文档
    deploy_all()

    # 测试查询
    test_knowledge_query()

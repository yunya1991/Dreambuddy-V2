# Dreambuddy-v2 → Classic System 集成指南

## 📦 已创建的文件

### 1. `classic-system-hooks.ts` (248行)
位置: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/`

**功能:**
- `onStrategyExecuteComplete()` - S5 Execute 完成后自动推送策略
- `queryStrategyKnowledge()` - S1/S2 阶段查询策略库作为知识参考
- `fetchSystemMonitorData()` - 获取监控数据（审批/回滚状态）

---

## 🔧 集成步骤

### 步骤1: 修改 `execute.ts` 添加 S5 钩子

在 `src/lib/strategy/steps/execute.ts` 文件末尾添加:

```typescript
import { onStrategyExecuteComplete, type CompleteStrategyChain } from "@/lib/classic-system-hooks";

export async function onExecuteCompleteWithPush(
  chain: CompleteStrategyChain
): Promise<{ success: boolean; pipelineResult?: any; error?: string }> {
  try {
    console.log(`[S5 Hook] 开始推送策略到 Classic System...`);
    const result = await onStrategyExecuteComplete(chain, {
      onProgress: (state) => {
        console.log(`[Pipeline/${state.phase}] ${state.success ? "✅" : "❌"} ${state.message}`);
      },
    });
    return result.success 
      ? { success: true, pipelineResult: result }
      : { success: false, error: result.error };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}
```

然后在 `executeS5Execute()` 函数返回前调用:

```typescript
// 在 executeS5Execute 函数末尾添加
export async function executeS5Execute(input: S5ExecuteInput): Promise<S5ExecuteOutput> {
  // ... 原有逻辑 ...
  
  const result = {
    checklist,
    alerts,
    warnings,
    trackingPlan,
  };

  // 自动推送（如果需要）
  if (input.autoPush ?? true) {
    const chain = input as any; // 传递完整策略链
    onExecuteCompleteWithPush(chain).catch(console.error);
  }

  return result;
}
```

---

### 步骤2: 修改 `research.ts` 添加知识库查询

在 `src/lib/strategy/steps/research.ts` 的 `executeS1Research()` 函数中添加:

```typescript
import { queryStrategyKnowledge } from "@/lib/classic-system-hooks";

export async function executeS1Research(input: S1ResearchInput): Promise<S1ResearchOutput> {
  const { symbol, displayName } = input;

  // 查询策略库作为知识参考
  const knowledgeResult = await queryStrategyKnowledge(symbol);
  if (knowledgeResult.strategies.length > 0) {
    console.log(`[S1] 找到 ${knowledgeResult.strategies.length} 个参考策略`);
  }

  // 并行获取所有数据
  const [marketData, indicators, supportResistance, sentiment] = await Promise.all([
    fetchMarketData(symbol),
    fetchTechnicalIndicators(symbol),
    fetchSupportResistance(symbol),
    fetchSentimentData(symbol),
  ]);

  // ... 原有逻辑 ...
}
```

---

### 步骤3: 修改 `analysis.ts` 添加知识库查询

在 `src/lib/strategy/steps/analysis.ts` 的 `executeS2Analysis()` 函数中添加:

```typescript
import { queryStrategyKnowledge } from "@/lib/classic-system-hooks";

export async function executeS2Analysis(input: S2AnalysisInput): Promise<S2AnalysisOutput> {
  const { symbol } = input;

  // 查询策略库作为分析参考
  const knowledgeResult = await queryStrategyKnowledge(symbol);
  if (knowledgeResult.strategies.length > 0) {
    console.log(`[S2] 找到 ${knowledgeResult.strategies.length} 个相关策略作为参考`);
  }

  // ... 原有逻辑 ...
}
```

---

### 步骤4: 创建监控页面

在 `src/app/monitor/classic/` 目录创建 `page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { fetchSystemMonitorData } from "@/lib/classic-system-hooks";

export default function ClassicMonitorPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSystemMonitorData().then(result => {
      setData(result);
      setLoading(false);
    });
  }, []);

  if (loading) return <div>加载中...</div>;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Classic System 监控</h1>
      
      {/* 健康状态 */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold">系统健康</h2>
        <div className={`px-4 py-2 rounded ${data?.health?.ok ? "bg-green-100" : "bg-red-100"}`}>
          {data?.health?.ok ? "✅ 运行正常" : "❌ 异常"}
        </div>
      </div>

      {/* 待审批 */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold">待审批 ({data?.approvals?.length || 0})</h2>
        <div className="space-y-2">
          {data?.approvals?.map((approval: any) => (
            <div key={approval.id} className="border p-4 rounded">
              <div className="font-medium">{approval.strategy_name}</div>
              <div className="text-sm text-gray-600">{approval.reason}</div>
            </div>
          ))}
          {data?.approvals?.length === 0 && <p className="text-gray-500">暂无待审批</p>}
        </div>
      </div>

      {/* 回滚点 */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold">可回滚点 ({data?.rollbackPoints?.length || 0})</h2>
        <div className="space-y-2">
          {data?.rollbackPoints?.map((point: any) => (
            <div key={point.id} className="border p-4 rounded">
              <div className="font-medium">{point.strategy_name}</div>
              <div className="text-sm text-gray-600">{point.reason}</div>
            </div>
          ))}
          {data?.rollbackPoints?.length === 0 && <p className="text-gray-500">暂无回滚点</p>}
        </div>
      </div>
    </div>
  );
}
```

---

## 📋 API 端点映射

| 功能 | 函数 | Classic System 端点 |
|------|------|---------------------|
| 创建草案 | `onStrategyExecuteComplete()` | `POST /agent/changeset/draft` |
| Gate评估 | (自动) | `POST /evaluation/gate/check` |
| 审批请求 | (自动) | `POST /agent/approvals/request` |
| 应用变更 | (自动) | `POST /governance/changeset/apply` |
| 审计记录 | (自动) | `POST /agent/audit/record` |
| 策略库查询 | `queryStrategyKnowledge()` | `GET /strategy/inject/list` |
| 监控数据 | `fetchSystemMonitorData()` | 多端点聚合 |

---

## 🎯 使用示例

### 在自定义组件中使用

```tsx
import { 
  onStrategyExecuteComplete, 
  queryStrategyKnowledge,
  fetchSystemMonitorData 
} from "@/lib/classic-system-hooks";

// 策略完成后自动推送
const result = await onStrategyExecuteComplete(chainResult);

// 查询知识库
const knowledge = await queryStrategyKnowledge("BTC_USDT");

// 获取监控数据
const monitor = await fetchSystemMonitorData();
```

---

## ⚙️ 配置

环境变量:
```bash
NEXT_PUBLIC_CLASSIC_SYSTEM_URL=http://127.0.0.1:8092
```

确保 classic-indicators-ml-system 后端运行在 `http://127.0.0.1:8092`

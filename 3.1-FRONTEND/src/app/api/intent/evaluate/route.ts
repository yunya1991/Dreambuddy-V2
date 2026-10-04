/**
 * 意图评估 API (JEV 二次评估)
 * POST /api/intent/evaluate - 调用 JEV 对意图识别结果进行二次评估
 *
 * 评估流程:
 * 1. choice 原语: 在 7 型意图中重新分类
 * 2. noul 原语: 校验原识别是否正确
 * 3. 根据结果调整意图和置信度
 *
 * FAIL-OPEN: 任何异常返回原识别结果，不阻塞主流程
 */
import { NextRequest, NextResponse } from "next/server";

const TYPESAFE_API_KEY = process.env.TYPESAFE_API_KEY || "";
const TYPESAFE_BASE_URL = (process.env.TYPESAFE_BASE_URL || "https://api.typesafe.ai").replace(/\/$/, "");
const TYPESAFE_TIMEOUT_MS = Number(process.env.TYPESAFE_TIMEOUT_MS || "10000");

// DreamOS 7 型策略意图
const DREAMOS_INTENTS = [
  "TREND_FOLLOWING",
  "MEAN_REVERSION",
  "FUNDAMENTAL_PLAY",
  "BREAKOUT",
  "KNOWLEDGE_MATCH",
  "DEEP_ANALYSIS",
  "UNCERTAIN",
];

interface EvalRequest {
  message: string;
  intent: string;
  confidence: number;
  entities?: Record<string, string>;
  context?: Record<string, unknown>;
}

interface EvalResponse {
  ok: boolean;
  intent_classify?: string;
  intent_correct?: number;
  jev_confidence?: number;
  adjusted_confidence?: number;
  adjusted_intent?: string;
  degraded?: boolean;
  error?: string;
}

export async function POST(request: NextRequest) {
  let body: EvalRequest;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "无效的 JSON 请求体" },
      { status: 400 }
    );
  }

  const { message, intent, confidence, entities, context } = body;

  // 参数校验
  if (!message || !intent) {
    return NextResponse.json(
      { ok: false, error: "缺少 message 或 intent" },
      { status: 400 }
    );
  }

  // JEV 未启用时直接 FAIL-OPEN
  if (!TYPESAFE_API_KEY) {
    return NextResponse.json({
      ok: true,
      degraded: true,
      adjusted_intent: intent,
      adjusted_confidence: confidence,
      error: "TYPESAFE_API_KEY 未配置，跳过 JEV 评估",
    });
  }

  try {
    // 构造 JEV state
    const state = JSON.stringify({
      user_message: message,
      original_intent: intent,
      original_confidence: confidence,
      entities: entities || {},
      context: context || {},
    });

    // 构造 JEV questions: choice (重分类) + noul (校验)
    const questions = {
      intent_classify: {
        type: "choice",
        instructions: `根据用户消息，选择最匹配的交易意图类型。\n用户消息: "${message}"`,
        options: DREAMOS_INTENTS,
      },
      intent_correct: {
        type: "noul",
        instructions: `原识别意图为 "${intent}"，置信度 ${confidence.toFixed(2)}。这个识别是否正确？\n用户消息: "${message}"`,
      },
    };

    // 调用 TypeSafe JEV API
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TYPESAFE_TIMEOUT_MS);

    const response = await fetch(`${TYPESAFE_BASE_URL}/v1/systemone`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TYPESAFE_API_KEY}`,
      },
      body: JSON.stringify({
        state,
        model: "jev-latest",
        questions,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      throw new Error(`JEV API 返回 ${response.status}`);
    }

    const data = await response.json();
    const answers = data.answers || {};

    // 解析 choice 结果
    const classifyAnswer = answers.intent_classify;
    const intentClassify = classifyAnswer?.choice || intent;
    const classifyConfidence = classifyAnswer?.confidence ?? 0.5;

    // 解析 noul 结果
    const correctAnswer = answers.intent_correct;
    const intentCorrect = correctAnswer?.noul ?? 0.5;

    // 调整置信度和意图
    let adjustedIntent = intent;
    let adjustedConfidence = confidence;

    if (intentClassify !== intent && classifyConfidence >= 0.7) {
      // JEV 重分类结果不同且置信度高 → 采用重分类结果
      adjustedIntent = intentClassify;
      adjustedConfidence = Math.max(0.4, confidence - 0.15);
    } else if (intentClassify !== intent) {
      // 重分类结果不同但置信度低 → 小幅降权
      adjustedConfidence = Math.max(0.2, confidence - 0.05);
    }

    if (intentCorrect < 0.5) {
      // noul 判断原识别不正确 → 降权
      adjustedConfidence = Math.max(0.2, adjustedConfidence - 0.1);
    }

    return NextResponse.json({
      ok: true,
      intent_classify: intentClassify,
      intent_correct: intentCorrect,
      jev_confidence: classifyConfidence,
      adjusted_intent: adjustedIntent,
      adjusted_confidence: adjustedConfidence,
      degraded: false,
    });
  } catch (error) {
    // FAIL-OPEN: 异常时返回原识别结果
    const isTimeout = error instanceof Error && error.name === "AbortError";
    return NextResponse.json({
      ok: true,
      degraded: true,
      adjusted_intent: intent,
      adjusted_confidence: confidence,
      error: isTimeout ? "JEV 评估超时" : `JEV 评估失败: ${error instanceof Error ? error.message : String(error)}`,
    });
  }
}

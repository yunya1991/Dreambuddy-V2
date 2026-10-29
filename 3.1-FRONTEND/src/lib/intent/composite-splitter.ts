/**
 * composite-splitter.ts — L1 组合意图拆分器（spec v0.5 §4 L1 层，P3）
 *
 * 职责：复合输入检测 → 子意图拆分 → 拆分结果聚合。
 * 拆分置信度不足时降级 L2 澄清（FAIL-OPEN，不阻断主链路）。
 *
 * 设计对齐 spec §4：
 * - L1 组合查询层：复合输入 → 意图拆分器 → 子意图编排执行 → 结果聚合
 * - 拆分粒度：初期规则+关键词拆分（已裁决决策点 4），后续模型化
 * - 子意图分派参考 Rasa retrieval intents 后缀分派机制（spec §11）
 */

/** 拆分结果 */
export interface SplitResult {
  /** 是否为复合输入 */
  isComposite: boolean;
  /** 拆分出的子意图消息列表（非复合时为单元素原消息） */
  subMessages: string[];
  /** 拆分置信度 [0,1]（分隔符命中数与子句完整度综合） */
  confidence: number;
  /** 拆分依据（证据，供归因与沉淀） */
  evidence: string[];
  /** 是否建议降级澄清（置信度不足） */
  needsClarification: boolean;
}

/** 复合输入分隔符（显式分隔：分号/问号/换行） */
const EXPLICIT_SEPARATORS = /[;；\n]+/;

/** 连接词（隐式分隔：『再』『然后』『顺便』『同时』） */
const CONNECTIVES = ['然后', '顺便', '同时', '再帮我', '再看下', '再查下', '接着'];

/** 最小子句长度（过短片段视为噪声，不构成子意图） */
const MIN_SUB_LENGTH = 4;

/** 拆分置信度阈值：低于此值降级 L2 澄清 */
const SPLIT_CONFIDENCE_THRESHOLD = 0.6;

/**
 * 检测并拆分复合输入。
 * 规则：显式分隔符优先；连接词次之；子句过滤噪声后评估置信度。
 */
export function splitCompositeInput(message: string): SplitResult {
  const trimmed = (message || '').trim();
  const failOpen: SplitResult = {
    isComposite: false,
    subMessages: [trimmed],
    confidence: 1.0,
    evidence: [],
    needsClarification: false,
  };

  if (!trimmed) return failOpen;

  // 1. 显式分隔符拆分
  let parts = trimmed
    .split(EXPLICIT_SEPARATORS)
    .map((p) => p.trim())
    .filter((p) => p.length >= MIN_SUB_LENGTH);

  let evidence: string[] = [];
  if (parts.length > 1) {
    evidence.push(`显式分隔符拆分为 ${parts.length} 个子句`);
  }

  // 2. 连接词拆分（无显式分隔符时）
  if (parts.length <= 1) {
    for (const conn of CONNECTIVES) {
      const idx = trimmed.indexOf(conn);
      if (idx > 0 && idx + conn.length < trimmed.length) {
        const left = trimmed.slice(0, idx).trim();
        const right = trimmed.slice(idx + conn.length).trim();
        if (left.length >= MIN_SUB_LENGTH && right.length >= MIN_SUB_LENGTH) {
          parts = [left, right];
          evidence.push(`连接词『${conn}』拆分为 2 个子句`);
          break;
        }
      }
    }
  }

  // 3. 非复合：单子句直接返回
  if (parts.length <= 1) {
    return failOpen;
  }

  // 4. 置信度评估：子句数适中（2-4）且各子句完整（含动词性词）加分
  let confidence = 0.5;
  if (parts.length >= 2 && parts.length <= 4) confidence += 0.2;
  if (parts.every((p) => /查|看|分析|买|卖|设置|回测|写|帮我/.test(p))) confidence += 0.2;
  if (evidence.length > 0) confidence += 0.1;
  confidence = Math.min(confidence, 1.0);

  return {
    isComposite: true,
    subMessages: parts,
    confidence,
    evidence,
    needsClarification: confidence < SPLIT_CONFIDENCE_THRESHOLD,
  };
}

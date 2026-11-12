/**
 * A7 探针：确定性 stub LLM provider。
 *
 * 目的：在 LLM 额度不可用时，仍然真实跑通「单 DSH 进程 → 多 child session 并发」链路。
 * 真实执行的是 DSH 的 agent loop / subagent seam / workflow 引擎 / 会话持久化；
 * 被替换的只有最外层模型调用（不产生网络请求、不消耗额度）。
 *
 * 行为约定（仅探针用）：
 *   - 根 agent 的 user 文本含 `A7-SPAWN` 且尚无 tool-result → 发出一次 `workflow` 工具调用；
 *   - 收到 tool-result 后 → 回复 `ROOT_DONE`；
 *   - 其余（child agent）→ 延迟 1500ms 后回复 `CHILD_DONE pid=<pid>`，用延迟制造并发窗口。
 *
 * 观测：每个 stream 记录 pid / inflight / 标记；并发峰值打到 stderr（前缀 A7_STUB）。
 */

const PID = process.pid;
const CHILD_DELAY_MS = 1500;

let inflight = 0;
let maxInflight = 0;
let callSeq = 0;

function log(line) {
  process.stderr.write(`A7_STUB ${line}\n`);
}

function userText(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (!msg || msg.role !== 'user' || !Array.isArray(msg.content)) continue;
    return msg.content
      .filter((b) => b && b.type === 'text')
      .map((b) => b.text)
      .join('');
  }
  return '';
}

/** 整段对话里的文本（根任务可能在 system-reminder 之前，不能只看最后一条 user）。 */
function transcriptText(messages) {
  const parts = [];
  for (const msg of messages) {
    if (!msg || !Array.isArray(msg.content)) continue;
    for (const block of msg.content) {
      if (block && block.type === 'text' && typeof block.text === 'string') parts.push(block.text);
    }
  }
  return parts.join('\n');
}

function hasToolResult(messages) {
  return messages.some(
    (m) => m && Array.isArray(m.content) && m.content.some((b) => b && b.type === 'tool-result'),
  );
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const WORKFLOW_SCRIPT = `
phase('A7');
const results = await parallel([
  () => agent('A7-CHILD-1 请回报你的进程标识'),
  () => agent('A7-CHILD-2 请回报你的进程标识'),
]);
return { children: results };
`;

const WORKFLOW_ARGS = JSON.stringify({
  script: WORKFLOW_SCRIPT,
  meta: { name: 'a7-multi-session', description: 'A7 单进程双会话并发探针' },
});

function textChunks(text) {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'usage', usage: { inputTokens: 1, outputTokens: 1 } },
    { type: 'finish', reason: { kind: 'stop' } },
  ];
}

function toolCallChunks() {
  const id = `stub-call-${PID}-${callSeq}`;
  return [
    { type: 'block-start', index: 0, blockType: 'tool-call' },
    { type: 'tool-call-delta', index: 0, id, name: 'workflow', argumentsDelta: WORKFLOW_ARGS },
    {
      type: 'block-end',
      index: 0,
      block: { type: 'tool-call', id, name: 'workflow', arguments: WORKFLOW_ARGS },
    },
    { type: 'usage', usage: { inputTokens: 1, outputTokens: 1 } },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  ];
}

class StubAdapter {
  providerInfo(provider) {
    return { id: provider, name: 'A7 Stub LLM' };
  }

  // 可选路由能力：显式声明为「无」，避免被当成基类方法缺失。
  providerRetryPolicy() {
    return undefined;
  }

  imageRequestPricing() {
    return undefined;
  }

  async listModels(provider) {
    return [{ provider, id: 'stub-1', name: 'A7 Stub 1', inputModalities: ['text'] }];
  }

  async resolveModel(provider, model) {
    return {
      provider,
      id: model,
      name: 'A7 Stub 1',
      inputModalities: ['text'],
      context: { contextWindow: 128000 },
      defaultMaxTokens: 1024,
    };
  }

  async prepareCall(provider, model) {
    return { model: await this.resolveModel(provider, model), stream: (options) => this.stream(options) };
  }

  async *stream(options) {
    const seq = (callSeq += 1);
    const messages = options.messages || [];
    const text = userText(messages);
    const transcript = transcriptText(messages);
    const isChild = transcript.includes('A7-CHILD');
    const hasWorkflowTool = Array.isArray(options.tools)
      ? options.tools.some((tool) => tool && tool.name === 'workflow')
      : false;
    const shouldDelegate =
      !isChild && transcript.includes('A7-SPAWN') && hasWorkflowTool && !hasToolResult(messages);
    const marker = shouldDelegate ? 'ROOT' : isChild ? 'CHILD' : 'OTHER';
    inflight += 1;
    if (inflight > maxInflight) maxInflight = inflight;
    log(
      `stream#${seq} pid=${PID} marker=${marker} inflight=${inflight} max=${maxInflight} ` +
        `model=${options.model} text=${JSON.stringify(text.slice(0, 60))}`,
    );
    try {
      if (hasToolResult(messages)) {
        for (const msg of messages) {
          if (!msg || !Array.isArray(msg.content)) continue;
          for (const block of msg.content) {
            if (!block || block.type !== 'tool-result') continue;
            const body = (block.content || [])
              .filter((b) => b && b.type === 'text')
              .map((b) => b.text)
              .join(' ')
              .slice(0, 300);
            log(`tool-result isError=${Boolean(block.isError)} body=${JSON.stringify(body)}`);
          }
        }
      }
      if (marker === 'ROOT') {
        for (const chunk of toolCallChunks()) yield chunk;
        return;
      }
      if (marker === 'CHILD') await sleep(CHILD_DELAY_MS);
      const reply =
        marker === 'CHILD' ? `CHILD_DONE pid=${PID} marker=${text.slice(0, 20)}` : 'ROOT_DONE';
      for (const chunk of textChunks(reply)) yield chunk;
    } finally {
      inflight -= 1;
      log(`stream#${seq} done pid=${PID} inflight=${inflight} max=${maxInflight}`);
    }
  }
}

export const name = 'a7-stub-llm';
export const inject = ['llm'];

export function apply(ctx) {
  ctx.llm.registerAdapter(['stub'], new StubAdapter());
  log(`registered provider=stub pid=${PID}`);
}

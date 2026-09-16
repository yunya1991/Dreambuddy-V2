/**
 * command-fastpath.ts — 命令快路径（零 LLM）
 * PROP-20260828B · Phase 2（Z3 §2 管线第①级）
 *
 * 背景：P0 黄金集基线显示 /命令 类识别准确率 0%（被规则引擎判成 simple_qa）。
 * 本模块在任何 LLM 调用之前拦截命令，零 token、零延迟。
 *
 * P5 修复：补充中文系统命令词典（精确匹配）。P0 基线中中文命令同样被
 * 规则引擎判成 simple_qa；为保精度只做 trim 后整句精确匹配，不做子串匹配，
 * 避免"帮我查看一下状态好吗"这类正常对话被误拦。
 */

const CMD_RE = /^\s*\/([a-zA-Z\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff-]*)(?:\s+([\s\S]*))?$/;

/** 中文系统命令词典：整句精确匹配（trim 后）→ 命令名 */
const CN_COMMANDS: Record<string, string> = {
  '查看状态': 'status',
  '帮助': 'help',
  '暂停交易': 'pause',
  '恢复交易': 'resume',
  '停止交易': 'stop',
  '开始交易': 'start',
  '查看持仓': 'positions',
  '查看积分': 'credits',
  '查看余额': 'balance',
  '清空会话': 'clear',
};

export interface CommandFastpathResult {
  intent: 'command';
  confidence: 1;
  entities: Record<string, string>;
  complexity: 'simple';
  reasoning: string;
  method: 'rule';
  context_aware: false;
}

/**
 * 匹配命令快路径（/斜杠命令 或 中文命令词典精确匹配）。
 * 命中返回结构化结果；非命令返回 null（调用方继续后续管线）。
 */
export function matchCommandFastpath(message: string): CommandFastpathResult | null {
  const m = CMD_RE.exec(message);
  if (m) {
    const name = m[1];
    const args = (m[2] || '').trim();
    return {
      intent: 'command',
      confidence: 1,
      entities: {
        command_name: name,
        ...(args ? { command_args: args } : {}),
      },
      complexity: 'simple',
      reasoning: `Command fastpath: /${name}`,
      method: 'rule',
      context_aware: false,
    };
  }

  const cnName = CN_COMMANDS[message.trim()];
  if (cnName) {
    return {
      intent: 'command',
      confidence: 1,
      entities: { command_name: cnName },
      complexity: 'simple',
      reasoning: `Command fastpath: CN exact "${message.trim()}"`,
      method: 'rule',
      context_aware: false,
    };
  }

  return null;
}

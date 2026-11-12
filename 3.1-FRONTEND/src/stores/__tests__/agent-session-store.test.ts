import {
  AGENT_SESSION_STORAGE_KEY,
  MAX_MESSAGES_PER_SESSION,
  MAX_SESSIONS,
  PERSIST_THROTTLE_MS,
  parsePersistedSessions,
  resetPersistForTest,
  resolveDeepLinkSessionId,
  trimSessions,
  useAgentSessionStore,
  type AgentSession,
} from '@/stores/agent-session-store';
import type { AgentMessage } from '@/types/agent-message';

function makeMessage(id: string): AgentMessage {
  return { id, role: 'user', parts: [{ type: 'text', text: id }], createdAt: 1 };
}

function makeSession(id: string, updatedAt: number, messageCount = 1): AgentSession {
  return {
    id,
    title: id,
    createdAt: updatedAt,
    updatedAt,
    messages: Array.from({ length: messageCount }, (_, i) => makeMessage(`${id}-${i}`)),
  };
}

describe('agent-session-store (T-B7)', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    window.localStorage.clear();
    resetPersistForTest();
    useAgentSessionStore.setState({ sessions: [], activeSessionId: null, hydrated: false });
  });

  afterEach(() => {
    resetPersistForTest();
    jest.useRealTimers();
  });

  it('创建会话并设为活跃', () => {
    const id = useAgentSessionStore.getState().createSession('首个会话');
    const state = useAgentSessionStore.getState();
    expect(state.sessions).toHaveLength(1);
    expect(state.activeSessionId).toBe(id);
    expect(state.sessions[0].title).toBe('首个会话');
  });

  it('选择 / 重命名 / 删除会话', () => {
    const a = useAgentSessionStore.getState().createSession('A');
    const b = useAgentSessionStore.getState().createSession('B');
    useAgentSessionStore.getState().selectSession(a);
    expect(useAgentSessionStore.getState().activeSessionId).toBe(a);
    useAgentSessionStore.getState().renameSession(a, 'A2');
    expect(useAgentSessionStore.getState().sessions.find((s) => s.id === a)?.title).toBe('A2');
    useAgentSessionStore.getState().deleteSession(b);
    expect(useAgentSessionStore.getState().sessions).toHaveLength(1);
  });

  it('无效 id 不改变活跃会话', () => {
    const a = useAgentSessionStore.getState().createSession('A');
    useAgentSessionStore.getState().selectSession('not-exist');
    expect(useAgentSessionStore.getState().activeSessionId).toBe(a);
  });

  it('删除活跃会话后回退到剩余首个', () => {
    const a = useAgentSessionStore.getState().createSession('A');
    const b = useAgentSessionStore.getState().createSession('B');
    useAgentSessionStore.getState().deleteSession(b);
    expect(useAgentSessionStore.getState().activeSessionId).toBe(a);
  });

  it('写入节流 500ms 后落盘并可反序列化', () => {
    const id = useAgentSessionStore.getState().createSession('持久化');
    useAgentSessionStore.getState().appendMessage(id, makeMessage('m1'));

    expect(window.localStorage.getItem(AGENT_SESSION_STORAGE_KEY)).toBeNull();
    jest.advanceTimersByTime(PERSIST_THROTTLE_MS);

    const persisted = parsePersistedSessions(window.localStorage.getItem(AGENT_SESSION_STORAGE_KEY));
    expect(persisted?.sessions).toHaveLength(1);
    expect(persisted?.sessions[0].messages).toHaveLength(1);
    expect(persisted?.activeSessionId).toBe(id);
  });

  it('hydrate 恢复持久化会话', () => {
    const id = useAgentSessionStore.getState().createSession('恢复');
    jest.advanceTimersByTime(PERSIST_THROTTLE_MS);
    useAgentSessionStore.setState({ sessions: [], activeSessionId: null, hydrated: false });

    useAgentSessionStore.getState().hydrate();
    expect(useAgentSessionStore.getState().sessions[0].id).toBe(id);
    expect(useAgentSessionStore.getState().hydrated).toBe(true);
  });

  it('最多保留 50 个会话（按 updatedAt 倒序）', () => {
    const sessions = Array.from({ length: MAX_SESSIONS + 15 }, (_, i) => makeSession(`s${i}`, i));
    const trimmed = trimSessions(sessions);
    expect(trimmed).toHaveLength(MAX_SESSIONS);
    expect(trimmed[0].updatedAt).toBe(MAX_SESSIONS + 14);
  });

  it('单会话最多保留 500 条消息（保留最新）', () => {
    const [trimmed] = trimSessions([makeSession('big', 1, MAX_MESSAGES_PER_SESSION + 50)]);
    expect(trimmed.messages).toHaveLength(MAX_MESSAGES_PER_SESSION);
    expect(trimmed.messages[trimmed.messages.length - 1].id).toBe('big-549');
  });

  it('损坏的持久化数据返回 null', () => {
    expect(parsePersistedSessions('not-json')).toBeNull();
    expect(parsePersistedSessions(JSON.stringify({ sessions: 'oops' }))).toBeNull();
    expect(parsePersistedSessions(null)).toBeNull();
  });

  it('深链：命中返回 id，无效/缺失返回 null', () => {
    const sessions = [makeSession('abc', 1)];
    expect(resolveDeepLinkSessionId('?session=abc', sessions)).toBe('abc');
    expect(resolveDeepLinkSessionId('session=abc', sessions)).toBe('abc');
    expect(resolveDeepLinkSessionId('?session=nope', sessions)).toBeNull();
    expect(resolveDeepLinkSessionId('', sessions)).toBeNull();
    expect(resolveDeepLinkSessionId(null, sessions)).toBeNull();
  });

  it('localStorage 写失败静默降级不抛错', () => {
    const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(() => {
      useAgentSessionStore.getState().createSession('quota');
      jest.advanceTimersByTime(PERSIST_THROTTLE_MS);
    }).not.toThrow();
    spy.mockRestore();
  });
});

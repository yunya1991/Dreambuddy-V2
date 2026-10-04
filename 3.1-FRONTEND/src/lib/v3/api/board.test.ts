// ============================================
// board.ts 单元 + 契约测试
// 验证: listProposals 调用 /api/board/proposals、解构 {success,data} 信封、deriveStageFromStatus 派生正确
//       P1: vote 调用 POST /votes、getProposalVotes 调用 GET /votes
// ============================================

import { jest } from '@jest/globals';
import { boardApi, deriveStageFromStatus, type Proposal } from './board';

// 全局 fetch mock — api-client.request 内部调用 fetch
const fetchMock = jest.fn() as unknown as jest.MockedFunction<typeof fetch>;
global.fetch = fetchMock as unknown as typeof fetch;

beforeEach(() => {
  fetchMock.mockReset();
});

describe('boardApi.listProposals', () => {
  it('calls fetch with /api/board/proposals and GET method', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: [] }),
    } as unknown as Response);

    await boardApi.listProposals();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/board/proposals');
    expect(init.method).toBe('GET');
  });

  it('unwraps {success,data} envelope and returns typed Proposal[]', async () => {
    const fakeProposal = {
      id: '1',
      title: 't1',
      status: 'DRAFT',
      type: 'TREND',
      direction: 'BUY',
      symbol: 'BTC/USDT',
      confidence: 0.5,
      edgeScore: 1.0,
      createdAt: new Date().toISOString(),
    };
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: [fakeProposal] }),
    } as unknown as Response);

    const result = await boardApi.listProposals();
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(1);
    expect((result as Proposal[])[0].id).toBe('1');
    expect((result as Proposal[])[0].status).toBe('DRAFT');
  });
});

describe('deriveStageFromStatus', () => {
  it('maps DRAFT → draft', () => {
    expect(deriveStageFromStatus('DRAFT')).toBe('draft');
  });
  it('maps APPROVED → approval', () => {
    expect(deriveStageFromStatus('APPROVED')).toBe('approval');
  });
  it('maps APPLIED → apply', () => {
    expect(deriveStageFromStatus('APPLIED')).toBe('apply');
  });
  it('maps PAUSED → audit', () => {
    expect(deriveStageFromStatus('PAUSED')).toBe('audit');
  });
  it('maps EXPIRED → audit', () => {
    expect(deriveStageFromStatus('EXPIRED')).toBe('audit');
  });
  it('maps unknown status (e.g. EXECUTING) → audit (defensive fallback)', () => {
    expect(deriveStageFromStatus('EXECUTING')).toBe('audit');
    expect(deriveStageFromStatus('UNKNOWN')).toBe('audit');
  });
});

// P1: 投票契约测试 (RED — 当前 boardApi.vote/getProposalVotes 是 stub throws)
describe('boardApi.vote (P1)', () => {
  it('calls POST /api/board/proposals/:id/votes with {vote}', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
    } as unknown as Response);

    await boardApi.vote('p1', 'FOR');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/board/proposals/p1/votes');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ vote: 'FOR' });
  });
});

describe('boardApi.getProposalVotes (P1)', () => {
  it('calls GET /api/board/proposals/:id/votes and returns ProposalVote[]', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: [{ id: 'v1', vote: 'FOR' }] }),
    } as unknown as Response);

    const result = await boardApi.getProposalVotes('p1');
    expect(Array.isArray(result)).toBe(true);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('v1');
    expect(result[0].vote).toBe('FOR');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/board/proposals/p1/votes');
    expect(init.method).toBe('GET');
  });
});

/**
 * SPEC-20261009 §10 P4-3: 认知闭环接入 (case verify → cognitive verify) 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - CaseVerifyBridge 类存在性
 *   - verifyCase: case verify → cognitive verify 调用
 *   - FAIL-OPEN: cognitive 不可用时不影响主链路
 *   - verifyCase 返回 { verified, confidence, message_id }
 */

jest.mock('../cognitive-client', () => ({
  callCognitive: jest.fn(),
}));

import { CaseVerifyBridge } from '../case-verify-bridge';
import { callCognitive } from '../cognitive-client';

describe('SPEC §10 P4-3: CaseVerifyBridge 认知闭环接入', () => {
  let bridge: CaseVerifyBridge;

  beforeEach(() => {
    bridge = new CaseVerifyBridge();
    jest.clearAllMocks();
  });

  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('CaseVerifyBridge 类应可导入且可实例化', () => {
      expect(bridge).toBeInstanceOf(CaseVerifyBridge);
    });

    it('verifyCase 方法应存在', () => {
      expect(typeof bridge.verifyCase).toBe('function');
    });
  });

  // ----------------------------------------------------------
  // 2. verifyCase 调用
  // ----------------------------------------------------------
  describe('verifyCase 调用', () => {
    it('成功 verify 应返回 verified=true', async () => {
      (callCognitive as jest.Mock).mockResolvedValueOnce({ ok: true, data: {} });

      const result = await bridge.verifyCase({
        memory_id: 'VM-test-123',
        success: true,
      });

      expect(callCognitive).toHaveBeenCalledWith('verify', {
        memory_id: 'VM-test-123',
        success: true,
      });
      expect(result.verified).toBe(true);
      expect(result.memory_id).toBe('VM-test-123');
    });

    it('verify 失败应返回 verified=false（FAIL-OPEN）', async () => {
      (callCognitive as jest.Mock).mockResolvedValueOnce({ ok: false, error: 'network error' });

      const result = await bridge.verifyCase({
        memory_id: 'VM-test-456',
        success: false,
      });

      expect(result.verified).toBe(false);
      expect(result.memory_id).toBe('VM-test-456');
    });

    it('cognitive 抛异常应返回 verified=false（FAIL-OPEN）', async () => {
      (callCognitive as jest.Mock).mockRejectedValueOnce(new Error('cognitive down'));

      const result = await bridge.verifyCase({
        memory_id: 'VM-test-789',
        success: true,
      });

      expect(result.verified).toBe(false);
      expect(result.error).toBeDefined();
    });
  });

  // ----------------------------------------------------------
  // 3. recordCase 留痕
  // ----------------------------------------------------------
  describe('recordCase 留痕', () => {
    it('recordCase 应调用 cognitive record', async () => {
      (callCognitive as jest.Mock).mockResolvedValueOnce({ ok: true, data: { id: 'VM-new-1' } });

      const result = await bridge.recordCase({
        content: 'SPL 测试经验',
        quality_level: 'B',
        tags: 'SPL,test',
      });

      expect(callCognitive).toHaveBeenCalledWith('record', {
        content: 'SPL 测试经验',
        quality_level: 'B',
        tags: 'SPL,test',
      });
      expect(result.recorded).toBe(true);
    });

    it('recordCase 失败应返回 recorded=false（FAIL-OPEN）', async () => {
      (callCognitive as jest.Mock).mockResolvedValueOnce({ ok: false });

      const result = await bridge.recordCase({
        content: 'test',
        quality_level: 'C',
        tags: 'test',
      });

      expect(result.recorded).toBe(false);
    });
  });

  // ----------------------------------------------------------
  // 4. 批量 verify
  // ----------------------------------------------------------
  describe('批量 verify', () => {
    it('verifyCases 应批量验证多个 case', async () => {
      (callCognitive as jest.Mock)
        .mockResolvedValueOnce({ ok: true, data: {} })
        .mockResolvedValueOnce({ ok: true, data: {} });

      const results = await bridge.verifyCases([
        { memory_id: 'VM-1', success: true },
        { memory_id: 'VM-2', success: true },
      ]);

      expect(results).toHaveLength(2);
      expect(results[0].verified).toBe(true);
      expect(results[1].verified).toBe(true);
    });
  });
});

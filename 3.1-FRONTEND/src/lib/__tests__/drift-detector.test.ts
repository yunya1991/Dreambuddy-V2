/**
 * SPEC-20261009 §3.5 P3: DriftDetector (分布漂移检测) 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - DriftDetector 类存在性 + 可实例化
 *   - window_size 默认 50，KL 阈值默认 0.15
 *   - addSample: 添加 codebook 索引到滑动窗口
 *   - computeKL: 计算当前窗口与基线的 KL 散度
 *   - detectDrift: KL > 阈值 → drift_detected=true
 *   - 漂移触发时返回增量训练动作
 *   - 非每轮训练：分布稳定时不触发
 */

import { DriftDetector, type DriftState, type DriftAction } from '../drift-detector';

describe('SPEC §3.5 P3: DriftDetector 分布漂移检测', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('DriftDetector 类应可导入且可实例化', () => {
      const detector = new DriftDetector();
      expect(detector).toBeInstanceOf(DriftDetector);
    });

    it('window_size 默认为 50', () => {
      const detector = new DriftDetector();
      expect(detector.windowSize).toBe(50);
    });

    it('KL 阈值默认为 0.15', () => {
      const detector = new DriftDetector();
      expect(detector.klThreshold).toBe(0.15);
    });
  });

  // ----------------------------------------------------------
  // 2. addSample 滑动窗口
  // ----------------------------------------------------------
  describe('addSample 滑动窗口', () => {
    it('addSample 应添加 codebook 索引到窗口', () => {
      const detector = new DriftDetector({ windowSize: 5 });
      detector.addSample([0, 1, 2, 3]);
      expect(detector.windowCount).toBe(1);
    });

    it('窗口满后应淘汰最旧数据（滑动窗口）', () => {
      const detector = new DriftDetector({ windowSize: 3 });
      detector.addSample([0, 0, 0, 0]);
      detector.addSample([1, 1, 1, 1]);
      detector.addSample([2, 2, 2, 2]);
      expect(detector.windowCount).toBe(3);
      // 第4条数据应淘汰第1条
      detector.addSample([3, 3, 3, 3]);
      expect(detector.windowCount).toBe(3);
    });
  });

  // ----------------------------------------------------------
  // 3. KL 散度计算
  // ----------------------------------------------------------
  describe('KL 散度计算', () => {
    it('相同分布的 KL 散度应为 0', () => {
      const detector = new DriftDetector({ windowSize: 10 });
      // 基线和当前窗口都是 [0,1,2,3]
      detector.setBaseline([[0, 1, 2, 3], [0, 1, 2, 3]]);
      detector.addSample([0, 1, 2, 3]);
      detector.addSample([0, 1, 2, 3]);
      const kl = detector.computeKL();
      expect(kl).toBeCloseTo(0, 5);
    });

    it('不同分布的 KL 散度应 > 0', () => {
      const detector = new DriftDetector({ windowSize: 10 });
      detector.setBaseline([[0, 1, 2, 3]]);
      detector.addSample([99, 98, 97, 96]);
      const kl = detector.computeKL();
      expect(kl).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 4. detectDrift 漂移检测
  // ----------------------------------------------------------
  describe('detectDrift 漂移检测', () => {
    it('KL > 阈值 → drift_detected=true', () => {
      const detector = new DriftDetector({ windowSize: 5, klThreshold: 0.01 });
      detector.setBaseline([[0, 1, 2, 3]]);
      detector.addSample([99, 98, 97, 96]);
      const state = detector.detectDrift();
      expect(state.drift_detected).toBe(true);
      expect(state.drift_score).toBeGreaterThan(0.01);
    });

    it('KL ≤ 阈值 → drift_detected=false', () => {
      const detector = new DriftDetector({ windowSize: 5, klThreshold: 0.15 });
      detector.setBaseline([[0, 1, 2, 3]]);
      detector.addSample([0, 1, 2, 3]);
      const state = detector.detectDrift();
      expect(state.drift_detected).toBe(false);
    });

    it('无数据时不应检测漂移', () => {
      const detector = new DriftDetector({ windowSize: 50 });
      detector.setBaseline([[0, 1, 2, 3]]);
      // 不添加任何样本
      const state = detector.detectDrift();
      expect(state.drift_detected).toBe(false);
    });

    it('无基线时不应检测漂移', () => {
      const detector = new DriftDetector({ windowSize: 50 });
      detector.addSample([99, 98, 97, 96]);
      // 未设置基线
      const state = detector.detectDrift();
      expect(state.drift_detected).toBe(false);
    });
  });

  // ----------------------------------------------------------
  // 5. 漂移触发的增量训练动作
  // ----------------------------------------------------------
  describe('漂移触发的增量训练动作', () => {
    it('漂移触发时应返回增量训练动作', () => {
      const detector = new DriftDetector({ windowSize: 5, klThreshold: 0.01 });
      detector.setBaseline([[0, 1, 2, 3]]);
      detector.addSample([99, 98, 97, 96]);
      const actions = detector.getDriftActions();

      expect(actions).toBeDefined();
      expect(actions.length).toBeGreaterThan(0);
      // 应包含重置 codebook 动作
      expect(actions.some(a => a.type === 'reset_codebook')).toBe(true);
      // 应包含更新检索参数动作
      expect(actions.some(a => a.type === 'update_retrieval_params')).toBe(true);
      // 应包含记录漂移事件动作
      expect(actions.some(a => a.type === 'record_drift_event')).toBe(true);
    });

    it('无漂移时应返回空动作列表', () => {
      const detector = new DriftDetector({ windowSize: 5, klThreshold: 0.15 });
      detector.setBaseline([[0, 1, 2, 3]]);
      detector.addSample([0, 1, 2, 3]);
      const actions = detector.getDriftActions();
      expect(actions).toHaveLength(0);
    });
  });

  // ----------------------------------------------------------
  // 6. DriftState 结构
  // ----------------------------------------------------------
  describe('DriftState 结构', () => {
    it('应包含 window_size, drift_score, drift_detected 字段', () => {
      const detector = new DriftDetector();
      const state = detector.getState();
      expect(state).toHaveProperty('window_size');
      expect(state).toHaveProperty('drift_score');
      expect(state).toHaveProperty('drift_detected');
      expect(state.window_size).toBe(50);
    });
  });

  // ----------------------------------------------------------
  // 7. 自定义参数
  // ----------------------------------------------------------
  describe('自定义参数', () => {
    it('应支持自定义 window_size 和 kl_threshold', () => {
      const detector = new DriftDetector({ windowSize: 100, klThreshold: 0.2 });
      expect(detector.windowSize).toBe(100);
      expect(detector.klThreshold).toBe(0.2);
    });
  });
});

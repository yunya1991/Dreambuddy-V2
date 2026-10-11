/**
 * SPEC v0.5 §5.3 P2: Registry 扩展测试
 * ==========================================
 * 测试 trainIncrementalLayer / checkpointLayer / restoreLayer / getModelSnapshot
 *
 * P2.1: API action=incremental/checkpoint/restore 依赖这些 registry 函数
 * P2.2: GET /model 依赖 getModelSnapshot
 */

import {
  trainIncrementalLayer,
  checkpointLayer,
  restoreLayer,
  getModelSnapshot,
  addTrainingData,
  type LayerName,
} from '../training-loop-registry';

describe('SPEC v0.5 §5.3 P2: TrainingLoopRegistry 扩展', () => {
  // ----------------------------------------------------------
  // P2.1: trainIncrementalLayer — 增量训练
  // ----------------------------------------------------------
  describe('trainIncrementalLayer()', () => {
    it('S层: 有数据时触发增量训练，返回 trained=true + 非空 weights', () => {
      const layer: LayerName = 'S';
      // 先添加足够数据（使用 B 质量避免自动触发 S 级优先级训练）
      for (let i = 0; i < 6; i++) {
        addTrainingData(layer, {
          message: `测试消息${i}`,
          intent_type: 'code_inspection',
          entities: [],
        });
      }

      const result = trainIncrementalLayer(layer);
      expect(result).not.toBeNull();
      expect(result!.trained).toBe(true);
      expect(result!.incrementalStep).toBeGreaterThan(0);
      expect(result!.weights).toBeDefined();
      expect(Object.keys(result!.weights!).length).toBeGreaterThan(0);
      expect(result!.bufferStats).toBeDefined();
      expect((result!.bufferStats as unknown as { size: number }).size).toBeGreaterThan(0);
    });

    it('DSH层: 有数据时触发增量训练', () => {
      const layer: LayerName = 'DSH';
      for (let i = 0; i < 11; i++) {
        addTrainingData(layer, {
          task: `task-${i}`,
          node_sequence: ['A', 'B', 'C'],
          outcome: 'success',
        });
      }

      const result = trainIncrementalLayer(layer);
      expect(result).not.toBeNull();
      expect(result!.trained).toBe(true);
    });

    it('空buffer时返回 trained=false', () => {
      // G层没有添加过数据
      const result = trainIncrementalLayer('G');
      expect(result).not.toBeNull();
      expect(result!.trained).toBe(false);
    });
  });

  // ----------------------------------------------------------
  // P2.1: checkpointLayer — 保存模型状态
  // ----------------------------------------------------------
  describe('checkpointLayer()', () => {
    it('S层: 保存模型状态，返回 checkpointed=true + state', () => {
      // 先添加数据并训练
      const layer: LayerName = 'S';
      for (let i = 0; i < 6; i++) {
        addTrainingData(layer, {
          message: `checkpoint测试${i}`,
          intent_type: 'test',
          entities: [],
        });
      }
      trainIncrementalLayer(layer);

      const result = checkpointLayer(layer);
      expect(result).not.toBeNull();
      expect(result!.checkpointed).toBe(true);
      expect(result!.state).toBeDefined();
      expect(result!.state!.step).toBeGreaterThan(0);
      expect(result!.state!.weights).toBeDefined();
      expect(result!.meta).toBeDefined();
      expect(result!.meta!.layer).toBe('S');
      expect(result!.meta!.id).toMatch(/^ckpt-/);
    });
  });

  // ----------------------------------------------------------
  // P2.1: restoreLayer — 恢复模型状态
  // ----------------------------------------------------------
  describe('restoreLayer()', () => {
    it('S层: 恢复模型状态，返回 restored=true', () => {
      const layer: LayerName = 'S';
      // 先 checkpoint
      for (let i = 0; i < 6; i++) {
        addTrainingData(layer, {
          message: `restore测试${i}`,
          intent_type: 'restore_test',
          entities: [],
        });
      }
      trainIncrementalLayer(layer);
      const ckpt = checkpointLayer(layer);
      const state = ckpt!.state!;

      // 恢复
      const result = restoreLayer(layer, state);
      expect(result).not.toBeNull();
      expect(result!.restored).toBe(true);
    });

    it('空state时 FAIL-OPEN 返回 restored=false', () => {
      const result = restoreLayer('C', {});
      expect(result).not.toBeNull();
      expect(result!.restored).toBe(false);
    });
  });

  // ----------------------------------------------------------
  // P2.2: getModelSnapshot — 获取模型状态 JSON
  // ----------------------------------------------------------
  describe('getModelSnapshot()', () => {
    it('S层: 返回模型状态 JSON（weights + step + drift_flag）', () => {
      const layer: LayerName = 'S';
      // 确保有数据
      addTrainingData(layer, {
        message: 'snapshot测试',
        intent_type: 'snapshot',
        entities: [],
      });

      const snapshot = getModelSnapshot(layer);
      expect(snapshot).not.toBeNull();
      expect(snapshot!.step).toBeDefined();
      expect(snapshot!.weights).toBeDefined();
      expect(snapshot!.drift_flag).toBeDefined();
      expect(snapshot!.timestamp).toBeDefined();
      expect(snapshot!.version).toBeDefined();
    });

    it('G层: 返回模型状态 JSON', () => {
      const snapshot = getModelSnapshot('G');
      expect(snapshot).not.toBeNull();
      expect(snapshot!.step).toBeDefined();
    });
  });
});

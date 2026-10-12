/**
 * SPEC-20261012 v0.6: 语义嵌入混合架构测试
 *
 * TDD RED → GREEN
 *
 * 覆盖：
 *   - 语义原型初始化（S/A 样本 → 原型向量）
 *   - 混合打分（α=0.7 时 TF-IDF + 语义融合）
 *   - FAIL-OPEN Level 1→2（API 失败 → n-gram 降级）
 *   - FAIL-OPEN Level 2→3（无原型 → 纯 TF-IDF）
 *   - 冷启动（无 S/A 样本时纯 TF-IDF）
 *   - checkpoint 持久化（semanticPrototypes 存取）
 *   - 语义层开关 + 参数可配
 */

// Mock knowledge-rag 的 embedding 函数（避免调真实 DeepSeek API）
const mockEmbedTexts = jest.fn();
const mockCosineSimilarity = jest.fn();
const mockNgramSimilarity = jest.fn();

jest.mock('../knowledge-rag', () => ({
  embedTexts: (...args: unknown[]) => mockEmbedTexts(...args),
  cosineSimilarity: (...args: unknown[]) => mockCosineSimilarity(...args),
  ngramSimilarity: (...args: unknown[]) => mockNgramSimilarity(...args),
}));

import {
  IntentTrainingLoop,
  type TrainingData,
  SEMANTIC_FUSION_ALPHA,
  SEMANTIC_EWMA_LAMBDA,
} from '../s-intent-training-loop';

describe('SPEC v0.6: 语义嵌入混合架构', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockEmbedTexts.mockReset();
    mockCosineSimilarity.mockReset();
    mockNgramSimilarity.mockReset();
  });

  // ----------------------------------------------------------
  // 1. 常量 + 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性 + 常量', () => {
    it('SEMANTIC_FUSION_ALPHA 应导出且默认 0.7', () => {
      expect(SEMANTIC_FUSION_ALPHA).toBeDefined();
      expect(SEMANTIC_FUSION_ALPHA).toBe(0.7);
    });

    it('SEMANTIC_EWMA_LAMBDA 应导出且默认 0.3', () => {
      expect(SEMANTIC_EWMA_LAMBDA).toBeDefined();
      expect(SEMANTIC_EWMA_LAMBDA).toBe(0.3);
    });

    it('IntentTrainingLoop 应可实例化', () => {
      const loop = new IntentTrainingLoop();
      expect(loop).toBeInstanceOf(IntentTrainingLoop);
    });
  });

  // ----------------------------------------------------------
  // 2. SModelState 扩展字段
  // ----------------------------------------------------------
  describe('SModelState 语义字段', () => {
    it('getModelSnapshot 应包含 semanticPrototypes 字段', () => {
      const loop = new IntentTrainingLoop();
      const snapshot = loop.getModelSnapshot();
      expect(snapshot).toHaveProperty('semanticPrototypes');
      expect(typeof snapshot.semanticPrototypes).toBe('object');
    });

    it('getModelSnapshot 应包含 semanticEnabled 字段', () => {
      const loop = new IntentTrainingLoop();
      const snapshot = loop.getModelSnapshot();
      expect(snapshot).toHaveProperty('semanticEnabled');
      expect(typeof snapshot.semanticEnabled).toBe('boolean');
    });

    it('getModelSnapshot 应包含 semanticStep 字段', () => {
      const loop = new IntentTrainingLoop();
      const snapshot = loop.getModelSnapshot();
      expect(snapshot).toHaveProperty('semanticStep');
      expect(typeof snapshot.semanticStep).toBe('number');
    });

    it('初始状态 semanticPrototypes 为空对象', () => {
      const loop = new IntentTrainingLoop();
      const snapshot = loop.getModelSnapshot();
      expect(Object.keys(snapshot.semanticPrototypes!)).toHaveLength(0);
      expect(snapshot.semanticStep).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 3. 语义原型初始化 + 更新
  // ----------------------------------------------------------
  describe('语义原型更新', () => {
    it('updateSemanticPrototypes 对 S 级样本应创建原型向量', async () => {
      const loop = new IntentTrainingLoop();
      const fakeVec = [0.1, 0.2, 0.3];
      mockEmbedTexts.mockResolvedValue([fakeVec]);

      const batch: TrainingData[] = [
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
      ];
      await loop.updateSemanticPrototypes(batch);

      const snapshot = loop.getModelSnapshot();
      expect(snapshot.semanticPrototypes!.restart).toBeDefined();
      expect(snapshot.semanticPrototypes!.restart).toEqual(fakeVec);
      expect(snapshot.semanticStep).toBe(1);
      expect(mockEmbedTexts).toHaveBeenCalledTimes(1);
    });

    it('updateSemanticPrototypes 对 A 级样本也应创建原型', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.5, 0.5, 0.5]]);

      const batch: TrainingData[] = [
        { message: 'reload', intent_type: 'restart', quality: 'A' },
      ];
      await loop.updateSemanticPrototypes(batch);

      const snapshot = loop.getModelSnapshot();
      expect(snapshot.semanticPrototypes!.restart).toBeDefined();
    });

    it('updateSemanticPrototypes 应跳过 C/D 级样本（S/A/B 做锚点）', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.1, 0.1]]);

      const batch: TrainingData[] = [
        { message: 'B级样本', intent_type: 'typeB', quality: 'B' },
        { message: 'C级样本', intent_type: 'typeC', quality: 'C' },
      ];
      await loop.updateSemanticPrototypes(batch);

      const snapshot = loop.getModelSnapshot();
      // B 级现在也创建原型（P2 放宽）
      expect(snapshot.semanticPrototypes!.typeB).toBeDefined();
      // C 级仍跳过
      expect(snapshot.semanticPrototypes!.typeC).toBeUndefined();
    });

    it('EWMA 更新：第二条 S 级样本应做移动平均，不是覆盖', async () => {
      const loop = new IntentTrainingLoop();
      // 第一条：原型 = [1, 0, 0]
      mockEmbedTexts.mockResolvedValueOnce([[1, 0, 0]]);
      await loop.updateSemanticPrototypes([
        { message: '重启', intent_type: 'restart', quality: 'S' },
      ]);

      // 第二条：原型 = β×[0,1,0] + (1-β)×[1,0,0], β=0.3
      // = 0.3×[0,1,0] + 0.7×[1,0,0] = [0.7, 0.3, 0]
      mockEmbedTexts.mockResolvedValueOnce([[0, 1, 0]]);
      await loop.updateSemanticPrototypes([
        { message: 'reload', intent_type: 'restart', quality: 'S' },
      ]);

      const snapshot = loop.getModelSnapshot();
      const proto = snapshot.semanticPrototypes!.restart;
      expect(proto[0]).toBeCloseTo(0.7, 5);
      expect(proto[1]).toBeCloseTo(0.3, 5);
      expect(proto[2]).toBeCloseTo(0, 5);
    });

    it('冷启动：首条样本直接初始化原型（不做 EWMA）', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.5, 0.5]]);

      await loop.updateSemanticPrototypes([
        { message: 'first', intent_type: 'init', quality: 'S' },
      ]);

      const proto = loop.getModelSnapshot().semanticPrototypes!.init;
      expect(proto).toEqual([0.5, 0.5]);
    });
  });

  // ----------------------------------------------------------
  // 4. 混合打分 predictIntent
  // ----------------------------------------------------------
  describe('predictIntent 混合打分', () => {
    it('有原型 + API 可用 → 混合打分（α×tfidf + (1-α)×semantic）', async () => {
      const loop = new IntentTrainingLoop();

      // 先训练 TF-IDF + 语义原型
      const batch: TrainingData[] = [
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
        { message: '分析代码', intent_type: 'analyze', quality: 'S' },
      ];
      loop.trainIncremental(batch); // TF-IDF 训练

      // updateSemanticPrototypes 对 3 条 S 级样本调 embedTexts → 返回 3 个向量
      mockEmbedTexts.mockResolvedValue([
        [0.1, 0.2, 0.3],
        [0.15, 0.25, 0.35],
        [0.9, 0.8, 0.7],
      ]);
      await loop.updateSemanticPrototypes(batch);

      // 预测时：query embedding + cosine
      mockEmbedTexts.mockResolvedValue([[0.15, 0.25, 0.35]]); // query 向量
      mockCosineSimilarity.mockReturnValueOnce(0.9); // restart 语义相似度
      mockCosineSimilarity.mockReturnValueOnce(0.1); // analyze 语义相似度

      const result = await loop.predictIntent('reload the service');

      // 应选择 restart（语义相似度高）
      expect(result).toBe('restart');
      expect(mockEmbedTexts).toHaveBeenCalled();
      expect(mockCosineSimilarity).toHaveBeenCalled();
    });

    it('α=1.0 时退化为纯 TF-IDF（语义不影响结果）', async () => {
      const loop = new IntentTrainingLoop({ semanticFusionAlpha: 1.0 });

      const batch: TrainingData[] = [
        { message: '检查架构', intent_type: 'inspect', quality: 'S' },
        { message: '检查架构', intent_type: 'inspect', quality: 'S' },
      ];
      loop.trainIncremental(batch);

      mockEmbedTexts.mockResolvedValue([[0.1, 0.2]]);
      await loop.updateSemanticPrototypes(batch);

      // 即使语义相似度返回 0（完全不相关），α=1.0 应忽略语义
      mockEmbedTexts.mockResolvedValue([[0.9, 0.8]]);
      mockCosineSimilarity.mockReturnValue(0.0);

      const result = await loop.predictIntent('检查架构');
      expect(result).toBe('inspect'); // TF-IDF 主导
    });

    it('语义捕获同义表达（TF-IDF 无法识别的场景）', async () => {
      const loop = new IntentTrainingLoop();

      // 训练: "重启服务" → restart
      const batch: TrainingData[] = [
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
      ];
      loop.trainIncremental(batch);

      mockEmbedTexts.mockResolvedValue([[1.0, 0.0]]); // 原型
      await loop.updateSemanticPrototypes(batch);

      // query "reload service" — TF-IDF 2-gram 几乎无匹配
      // 但语义上 "reload service" 与 "重启服务" 高度相似
      mockEmbedTexts.mockResolvedValue([[0.95, 0.1]]); // query 向量
      mockCosineSimilarity.mockReturnValueOnce(0.95); // 语义高度相似

      const result = await loop.predictIntent('reload service');
      // 语义辅助识别为 restart
      expect(result).toBe('restart');
    });
  });

  // ----------------------------------------------------------
  // 5. FAIL-OPEN 三级降级
  // ----------------------------------------------------------
  describe('FAIL-OPEN 降级链', () => {
    it('Level 1→2: API 失败 → n-gram fallback', async () => {
      const loop = new IntentTrainingLoop();

      const batch: TrainingData[] = [
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
      ];
      loop.trainIncremental(batch);

      mockEmbedTexts.mockResolvedValue([[0.1, 0.2]]);
      await loop.updateSemanticPrototypes(batch);

      // 预测时 API 失败
      mockEmbedTexts.mockRejectedValue(new Error('API 429 Too Many Requests'));
      mockNgramSimilarity.mockReturnValueOnce(0.5); // n-gram 降级相似度

      const result = await loop.predictIntent('重启服务');
      // 应走 n-gram fallback，仍返回 restart
      expect(result).toBe('restart');
      expect(mockNgramSimilarity).toHaveBeenCalled();
    });

    it('Level 2→3: 无原型 → 纯 TF-IDF', async () => {
      const loop = new IntentTrainingLoop();

      // 只用 B/C 级训练（不创建原型）
      const batch: TrainingData[] = [
        { message: '检查架构', intent_type: 'inspect', quality: 'B' },
        { message: '检查架构', intent_type: 'inspect', quality: 'C' },
      ];
      loop.trainIncremental(batch);

      // 无原型 → 不调 API，纯 TF-IDF
      const result = await loop.predictIntent('检查架构');
      expect(result).toBe('inspect');
      expect(mockEmbedTexts).not.toHaveBeenCalled();
    });

    it('Level 3: 冷启动期（无任何训练）返回空字符串', async () => {
      const loop = new IntentTrainingLoop();
      const result = await loop.predictIntent('未知意图');
      expect(result).toBe('');
    });

    it('API 失败 + n-gram fallback 关闭 → 纯 TF-IDF', async () => {
      const loop = new IntentTrainingLoop({ ngramFallback: false });

      const batch: TrainingData[] = [
        { message: '重启服务', intent_type: 'restart', quality: 'S' },
      ];
      loop.trainIncremental(batch);

      mockEmbedTexts.mockResolvedValue([[0.1, 0.2]]);
      await loop.updateSemanticPrototypes(batch);

      mockEmbedTexts.mockRejectedValue(new Error('network error'));

      const result = await loop.predictIntent('重启服务');
      // n-gram 关闭 → 纯 TF-IDF
      expect(result).toBe('restart');
      expect(mockNgramSimilarity).not.toHaveBeenCalled();
    });
  });

  // ----------------------------------------------------------
  // 6. checkpoint 持久化
  // ----------------------------------------------------------
  describe('checkpoint 语义原型持久化', () => {
    it('getModelSnapshot 应包含 semanticPrototypes', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.1, 0.2, 0.3]]);

      await loop.updateSemanticPrototypes([
        { message: 'test', intent_type: 't1', quality: 'S' },
      ]);

      const snapshot = loop.getModelSnapshot();
      expect(snapshot.semanticPrototypes!.t1).toEqual([0.1, 0.2, 0.3]);
      expect(snapshot.semanticStep).toBe(1);
    });

    it('restoreModel 应恢复 semanticPrototypes', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.5, 0.5]]);

      await loop.updateSemanticPrototypes([
        { message: 'restore', intent_type: 'rt', quality: 'S' },
      ]);

      const snapshot = loop.getModelSnapshot();
      const loop2 = new IntentTrainingLoop();
      loop2.restoreModel(snapshot);

      const restored = loop2.getModelSnapshot();
      expect(restored.semanticPrototypes!.rt).toEqual([0.5, 0.5]);
      expect(restored.semanticStep).toBe(1);
    });

    it('restoreModel 兼容旧 snapshot（无 semanticPrototypes 字段）', () => {
      const loop = new IntentTrainingLoop();
      // 模拟 v0.5 的旧 snapshot（无语义字段）
      const oldSnapshot = {
        weights: { a: 0.5 },
        typeKeywords: {},
        intentFreq: { a: 1 },
        docCount: 1,
        step: 1,
        drift_flag: false,
        timestamp: Date.now(),
        version: 'v0.5-20261011',
        intentArchive: [],
      };
      loop.restoreModel(oldSnapshot as any);
      // 不应崩溃，语义字段为默认值
      const restored = loop.getModelSnapshot();
      expect(restored.semanticPrototypes).toEqual({});
      expect(restored.semanticEnabled).toBe(true);
      expect(restored.semanticStep).toBe(0);
    });

    it('clear 应清空 semanticPrototypes', async () => {
      const loop = new IntentTrainingLoop();
      mockEmbedTexts.mockResolvedValue([[0.1, 0.2]]);

      await loop.updateSemanticPrototypes([
        { message: 'clear', intent_type: 'cl', quality: 'S' },
      ]);
      expect(Object.keys(loop.getModelSnapshot().semanticPrototypes!)).toHaveLength(1);

      loop.clear();
      expect(loop.getModelSnapshot().semanticPrototypes).toEqual({});
      expect(loop.getModelSnapshot().semanticStep).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 7. 语义开关 + 参数可配
  // ----------------------------------------------------------
  describe('语义层配置', () => {
    it('semanticEnabled=false 时 predictIntent 不调 API', async () => {
      const loop = new IntentTrainingLoop({ semanticEnabled: false });

      const batch: TrainingData[] = [
        { message: '测试意图', intent_type: 'test', quality: 'S' },
      ];
      loop.trainIncremental(batch);

      mockEmbedTexts.mockResolvedValue([[0.1]]);
      await loop.updateSemanticPrototypes(batch);

      // 即使有原型，semanticEnabled=false → 纯 TF-IDF
      const result = await loop.predictIntent('测试意图');
      expect(result).toBe('test');
      // predictIntent 不应调 embedTexts（语义关闭）
      // 注：updateSemanticPrototypes 调了一次，predictIntent 不应再调
      expect(mockEmbedTexts).toHaveBeenCalledTimes(1); // 仅 updateSemanticPrototypes
    });

    it('自定义 semanticFusionAlpha', () => {
      const loop = new IntentTrainingLoop({ semanticFusionAlpha: 0.5 });
      expect(loop.semanticFusionAlpha).toBe(0.5);
    });

    it('自定义 semanticEwmaLambda', () => {
      const loop = new IntentTrainingLoop({ semanticEwmaLambda: 0.5 });
      expect(loop.semanticEwmaLambda).toBe(0.5);
    });

    it('setSemanticConfig 运行时切换开关', async () => {
      const loop = new IntentTrainingLoop();

      const batch: TrainingData[] = [
        { message: '切换测试', intent_type: 'toggle', quality: 'S' },
      ];
      loop.trainIncremental(batch);
      mockEmbedTexts.mockResolvedValue([[0.1]]);
      await loop.updateSemanticPrototypes(batch);

      // 关闭语义
      loop.setSemanticConfig({ enabled: false });
      expect(loop.getModelSnapshot().semanticEnabled).toBe(false);

      mockEmbedTexts.mockClear();
      await loop.predictIntent('切换测试');
      expect(mockEmbedTexts).not.toHaveBeenCalled();

      // 重新开启
      loop.setSemanticConfig({ enabled: true });
      expect(loop.getModelSnapshot().semanticEnabled).toBe(true);
    });
  });

  // ----------------------------------------------------------
  // 8. trainIncremental 零回归（语义层不影响 TF-IDF 训练）
  // ----------------------------------------------------------
  describe('零回归: trainIncremental 不受语义层影响', () => {
    it('trainIncremental 权重计算与 v0.5 一致（语义层不参与）', () => {
      const loop = new IntentTrainingLoop();
      const batch: TrainingData[] = [];
      for (let i = 0; i < 10; i++) {
        batch.push({ message: `检查代码${i}`, intent_type: 'code_inspection', quality: 'S' });
      }
      const result = loop.trainIncremental(batch);
      // TF-IDF 权重正常计算
      expect(result.trained).toBe(true);
      expect(result.weights['code_inspection']).toBeGreaterThan(0);
      // 语义层不参与 trainIncremental（原型更新是单独方法）
      expect(loop.getModelSnapshot().semanticStep).toBe(0);
    });

    it('intentArchive 归档逻辑不受语义层影响', () => {
      const loop = new IntentTrainingLoop();
      const batch: TrainingData[] = [];
      for (let i = 0; i < 100; i++) {
        batch.push({ message: `m-${i}`, intent_type: 'dom' });
      }
      batch.push({ message: 'r', intent_type: 'rare' });
      loop.trainIncremental(batch);
      const model = loop.getModelSnapshot();
      // 归档逻辑照常工作
      expect(model.intentArchive).toContain('rare');
      expect(model.weights).not.toHaveProperty('rare');
    });
  });
});

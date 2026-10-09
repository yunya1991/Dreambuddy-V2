/**
 * SPEC-20261009 §1.2 + §10 P0-3: Trae Memory Bridge 测试
 *
 * TDD RED 阶段 — 验证 TraeMemoryBridge 接口 + 四元组提取
 *
 * 覆盖：
 *   - TraeMemoryBridge 类存在性
 *   - extractQuadruple: 从 session_memory JSONL 行提取四元组
 *   - ingestFile: 解析 JSONL 文件 → 四元组 → TDR 入库
 *   - 质量闸门：有 learned 才入库
 *   - Trae 记忆只读（不修改源文件）
 *   - startWatching / stopWatching 文件监听
 */

import { TraeMemoryBridge, type SessionMemoryEntry, type ExtractedQuadruple } from '../trae-memory-bridge';

describe('SPEC §10 P0-3: TraeMemoryBridge', () => {
  // ============================================================
  // §10: 类存在性
  // ============================================================
  describe('TraeMemoryBridge 类', () => {
    it('应导出 TraeMemoryBridge 类', () => {
      expect(TraeMemoryBridge).toBeDefined();
      expect(typeof TraeMemoryBridge).toBe('function');
    });

    it('应提供 getTraeMemoryBridge 单例', () => {
      const { getTraeMemoryBridge } = require('../trae-memory-bridge');
      expect(typeof getTraeMemoryBridge).toBe('function');
      const bridge = getTraeMemoryBridge();
      expect(bridge).toBeInstanceOf(TraeMemoryBridge);
    });
  });

  // ============================================================
  // §1.2: extractQuadruple — 从 session_memory JSONL 提取四元组
  // ============================================================
  describe('extractQuadruple', () => {
    const sampleEntry: SessionMemoryEntry = {
      intent: '整体上检查下项目架构逻辑',
      actions: ['检查项目架构逻辑', '修复架构中的严重问题', '修复架构中的中等问题'],
      outcome: '项目架构检查与修复完成，核心架构已修复并通过验证',
      learned: ['架构层次自洽', 'BCRMEngine.infer()包含七个步骤', '修复了8项问题'],
      message_summary_time: '2026-07-06 00:25:08',
      message_id: '6a4a82041788dd06ff269942',
    };

    it('应提取 intent', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple(sampleEntry);
      expect(q).not.toBeNull();
      expect(q!.intent).toBe('整体上检查下项目架构逻辑');
    });

    it('应提取 actions 数组', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple(sampleEntry);
      expect(q).not.toBeNull();
      expect(q!.actions).toHaveLength(3);
      expect(q!.actions[0]).toBe('检查项目架构逻辑');
    });

    it('应提取 outcome_text', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple(sampleEntry);
      expect(q).not.toBeNull();
      expect(q!.outcome_text).toContain('架构检查与修复完成');
    });

    it('应提取 learned 数组', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple(sampleEntry);
      expect(q).not.toBeNull();
      expect(q!.learned).toHaveLength(3);
      expect(q!.learned[0]).toBe('架构层次自洽');
    });

    it('应提取 message_id 和 message_summary_time', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple(sampleEntry);
      expect(q).not.toBeNull();
      expect(q!.message_id).toBe('6a4a82041788dd06ff269942');
      expect(q!.message_summary_time).toBe('2026-07-06 00:25:08');
    });

    it('learned 为空时应返回 null（质量闸门）', () => {
      const bridge = new TraeMemoryBridge();
      const q = bridge.extractQuadruple({
        ...sampleEntry,
        learned: [],
      });
      expect(q).toBeNull();
    });
  });

  // ============================================================
  // §10: parseJsonlLine — 解析单行 JSONL
  // ============================================================
  describe('parseJsonlLine', () => {
    it('应正确解析 JSONL 行', () => {
      const bridge = new TraeMemoryBridge();
      const line = '{"intent":"test","actions":["a"],"outcome":"ok","learned":["l"],"message_summary_time":"2026-01-01","message_id":"m1"}';
      const entry = bridge.parseJsonlLine(line);
      expect(entry).not.toBeNull();
      expect(entry?.intent).toBe('test');
      expect(entry?.actions).toEqual(['a']);
    });

    it('空行应返回 null', () => {
      const bridge = new TraeMemoryBridge();
      expect(bridge.parseJsonlLine('')).toBeNull();
      expect(bridge.parseJsonlLine('  \n')).toBeNull();
    });

    it('非法 JSON 应返回 null（不抛异常）', () => {
      const bridge = new TraeMemoryBridge();
      expect(bridge.parseJsonlLine('{invalid json')).toBeNull();
    });
  });

  // ============================================================
  // §10: startWatching / stopWatching
  // ============================================================
  describe('文件监听', () => {
    it('应提供 startWatching 方法', () => {
      const bridge = new TraeMemoryBridge();
      expect(typeof bridge.startWatching).toBe('function');
    });

    it('应提供 stopWatching 方法', () => {
      const bridge = new TraeMemoryBridge();
      expect(typeof bridge.stopWatching).toBe('function');
    });

    it('startWatching 在路径不存在时应 FAIL-OPEN 不抛异常', () => {
      const bridge = new TraeMemoryBridge();
      expect(() => bridge.startWatching('/nonexistent/path')).not.toThrow();
    });

    it('stopWatching 在未启动时应安全调用', () => {
      const bridge = new TraeMemoryBridge();
      expect(() => bridge.stopWatching()).not.toThrow();
    });
  });

  // ============================================================
  // §10: ingestFile — 解析文件 → 入库
  // ============================================================
  describe('ingestFile', () => {
    it('应提供 ingestFile 方法', () => {
      const bridge = new TraeMemoryBridge();
      expect(typeof bridge.ingestFile).toBe('function');
    });

    it('文件不存在时应返回 0 入库数（FAIL-OPEN）', async () => {
      const bridge = new TraeMemoryBridge();
      const result = await bridge.ingestFile('/nonexistent/file.jsonl');
      expect(result.ingested).toBe(0);
      expect(result.skipped).toBe(0);
    });
  });

  // ============================================================
  // §3.1: Trae 记忆只读
  // ============================================================
  describe('Trae 记忆只读', () => {
    it('应暴露 readonly 标记', () => {
      const bridge = new TraeMemoryBridge();
      expect(bridge.readonly).toBe(true);
    });
  });
});

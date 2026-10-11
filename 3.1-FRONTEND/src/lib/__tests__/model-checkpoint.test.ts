/**
 * SPEC v0.5 P1: ModelCheckpoint 模型状态持久化测试
 *
 * TDD RED→GREEN
 *
 * 覆盖:
 *   - ModelCheckpoint 类存在性 + 可实例化
 *   - checkpoint(): 保存模型状态
 *   - restore(): 恢复模型状态
 *   - listCheckpoints(): 列出检查点
 *   - 多层支持（S/DSH/C/G/LLM）
 *   - 最大保留数限制（maxCheckpoints=5）
 *   - 元数据（step, drift_flag, timestamp）
 */

import fs from 'fs';
import os from 'os';
import path from 'path';
import { ModelCheckpoint, type CheckpointMeta } from '../model-checkpoint';

describe('SPEC v0.5 P1: ModelCheckpoint 模型状态持久化', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('ModelCheckpoint 应可导入且可实例化', () => {
      const ckpt = new ModelCheckpoint();
      expect(ckpt).toBeInstanceOf(ModelCheckpoint);
    });
  });

  // ----------------------------------------------------------
  // 2. checkpoint / restore
  // ----------------------------------------------------------
  describe('checkpoint / restore', () => {
    it('checkpoint 后应可通过 restore 恢复', () => {
      const ckpt = new ModelCheckpoint();
      const state = { weights: { a: 1.0 }, step: 10, drift_flag: false };
      ckpt.checkpoint('S', state);

      const restored = ckpt.restore('S');
      expect(restored).not.toBeNull();
      expect(restored!.state).toEqual(state);
      expect(restored!.layer).toBe('S');
    });

    it('checkpoint 应记录元数据（step, timestamp, drift_flag）', () => {
      const ckpt = new ModelCheckpoint();
      const state = { weights: { a: 1.0 }, step: 42, drift_flag: true };
      ckpt.checkpoint('S', state);

      const meta = ckpt.listCheckpoints('S');
      expect(meta.length).toBe(1);
      expect(meta[0].step).toBe(42);
      expect(meta[0].drift_flag).toBe(true);
      expect(meta[0].timestamp).toBeGreaterThan(0);
      expect(meta[0].id).toBeDefined();
    });

    it('多次 checkpoint 应保留多个检查点', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 1 });
      ckpt.checkpoint('S', { step: 2 });
      ckpt.checkpoint('S', { step: 3 });

      const meta = ckpt.listCheckpoints('S');
      expect(meta.length).toBe(3);
    });

    it('restore 无检查点时应返回 null', () => {
      const ckpt = new ModelCheckpoint();
      const restored = ckpt.restore('S');
      expect(restored).toBeNull();
    });

    it('restore 指定 checkpointId 应恢复对应版本', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 1 });
      const meta2 = ckpt.checkpoint('S', { step: 2 });

      const restored = ckpt.restore('S', meta2.id);
      expect(restored).not.toBeNull();
      expect(restored!.state.step).toBe(2);
    });

    it('restore 未知 checkpointId 应返回 null', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 1 });

      const restored = ckpt.restore('S', 'nonexistent-id');
      expect(restored).toBeNull();
    });
  });

  // ----------------------------------------------------------
  // 3. 多层支持
  // ----------------------------------------------------------
  describe('多层支持', () => {
    it('不同层检查点应独立存储', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 10 });
      ckpt.checkpoint('C', { step: 20 });
      ckpt.checkpoint('G', { step: 30 });

      expect(ckpt.listCheckpoints('S').length).toBe(1);
      expect(ckpt.listCheckpoints('C').length).toBe(1);
      expect(ckpt.listCheckpoints('G').length).toBe(1);

      const restoredS = ckpt.restore('S');
      expect(restoredS!.state.step).toBe(10);

      const restoredC = ckpt.restore('C');
      expect(restoredC!.state.step).toBe(20);
    });

    it('5 层均可 checkpoint', () => {
      const ckpt = new ModelCheckpoint();
      for (const layer of ['S', 'DSH', 'C', 'G', 'LLM']) {
        ckpt.checkpoint(layer, { step: 1 });
        expect(ckpt.listCheckpoints(layer).length).toBe(1);
      }
    });
  });

  // ----------------------------------------------------------
  // 4. 最大保留数限制
  // ----------------------------------------------------------
  describe('最大保留数限制', () => {
    it('超过 maxCheckpoints=5 应淘汰最旧检查点', () => {
      const ckpt = new ModelCheckpoint({ maxCheckpoints: 5 });
      for (let i = 0; i < 7; i++) {
        ckpt.checkpoint('S', { step: i });
      }
      const meta = ckpt.listCheckpoints('S');
      expect(meta.length).toBe(5);
      // 最旧的 step=0,1 应被淘汰；降序排列：最新在前
      expect(meta[0].step).toBe(6);
      expect(meta[4].step).toBe(2);
    });

    it('默认 maxCheckpoints=5', () => {
      const ckpt = new ModelCheckpoint();
      expect(ckpt.maxCheckpoints).toBe(5);
    });
  });

  // ----------------------------------------------------------
  // 5. listCheckpoints
  // ----------------------------------------------------------
  describe('listCheckpoints', () => {
    it('listCheckpoints 应按时间降序返回（最新在前）', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 1 });
      ckpt.checkpoint('S', { step: 2 });
      ckpt.checkpoint('S', { step: 3 });

      const meta = ckpt.listCheckpoints('S');
      expect(meta[0].step).toBe(3);
      expect(meta[1].step).toBe(2);
      expect(meta[2].step).toBe(1);
    });

    it('listCheckpoints 无数据层应返回空数组', () => {
      const ckpt = new ModelCheckpoint();
      const meta = ckpt.listCheckpoints('S');
      expect(meta).toEqual([]);
    });
  });

  // ----------------------------------------------------------
  // 6. clear
  // ----------------------------------------------------------
  describe('clear', () => {
    it('clear 应清空指定层的所有检查点', () => {
      const ckpt = new ModelCheckpoint();
      ckpt.checkpoint('S', { step: 1 });
      ckpt.checkpoint('S', { step: 2 });
      ckpt.checkpoint('C', { step: 10 });

      ckpt.clear('S');
      expect(ckpt.listCheckpoints('S')).toEqual([]);
      // C 层不受影响
      expect(ckpt.listCheckpoints('C').length).toBe(1);
    });
  });

  // ----------------------------------------------------------
  // 7. 文件持久化（热重载恢复）
  // ----------------------------------------------------------
  describe('文件持久化（热重载恢复）', () => {
    let tmpDir: string;

    beforeEach(() => {
      tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ckpt-test-'));
    });

    afterEach(() => {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    });

    it('启用 persistDir 时，checkpoint 后应写入磁盘文件', () => {
      const ckpt = new ModelCheckpoint({ persistDir: tmpDir });
      ckpt.checkpoint('S', { weights: { a: 1.0 }, step: 10, drift_flag: false });

      const file = path.join(tmpDir, 'checkpoints.json');
      expect(fs.existsSync(file)).toBe(true);

      const raw = fs.readFileSync(file, 'utf-8');
      const parsed = JSON.parse(raw);
      expect(parsed.version).toBe('1.0');
      expect(parsed.store.S).toBeDefined();
      expect(parsed.store.S[0].state.step).toBe(10);
    });

    it('新实例应从磁盘加载检查点（模拟热重载恢复）', () => {
      // 实例 A：保存检查点
      const ckptA = new ModelCheckpoint({ persistDir: tmpDir });
      ckptA.checkpoint('S', { weights: { a: 1.0 }, step: 10, drift_flag: false });
      ckptA.checkpoint('C', { rules: { x: 0.5 }, step: 20, drift_flag: false });

      // 实例 B：模拟服务重启后新建实例，应从磁盘恢复
      const ckptB = new ModelCheckpoint({ persistDir: tmpDir });
      const restoredS = ckptB.restore('S');
      expect(restoredS).not.toBeNull();
      expect(restoredS!.state.step).toBe(10);
      expect(restoredS!.state.weights).toEqual({ a: 1.0 });

      const restoredC = ckptB.restore('C');
      expect(restoredC).not.toBeNull();
      expect(restoredC!.state.step).toBe(20);
    });

    it('clear 后磁盘文件应同步清除该层', () => {
      const ckpt = new ModelCheckpoint({ persistDir: tmpDir });
      ckpt.checkpoint('S', { step: 10 });
      ckpt.checkpoint('C', { step: 20 });

      ckpt.clear('S');

      const file = path.join(tmpDir, 'checkpoints.json');
      const parsed = JSON.parse(fs.readFileSync(file, 'utf-8'));
      expect(parsed.store.S).toBeUndefined();
      expect(parsed.store.C).toBeDefined();
    });

    it('多个实例（不同层）共享同一持久化文件，互不覆盖', () => {
      const ckptS = new ModelCheckpoint({ persistDir: tmpDir });
      const ckptC = new ModelCheckpoint({ persistDir: tmpDir });

      ckptS.checkpoint('S', { step: 10 });
      ckptC.checkpoint('C', { step: 20 });

      // S 层再次 checkpoint 不应覆盖 C 层
      ckptS.checkpoint('S', { step: 11 });

      const restoredS = ckptC.restore('S'); // 通过 C 实例也能读到 S 层
      expect(restoredS!.state.step).toBe(11);
      const restoredC = ckptS.restore('C'); // 通过 S 实例也能读到 C 层
      expect(restoredC!.state.step).toBe(20);
    });

    it('磁盘不可用时应降级为内存模式（FAIL-OPEN）', () => {
      // 传入一个文件路径而非目录，mkdirSync 会失败
      const fakeDir = path.join(tmpDir, 'not-a-dir.txt');
      fs.writeFileSync(fakeDir, 'blocker');

      const ckpt = new ModelCheckpoint({ persistDir: fakeDir });
      // 不应抛出，降级为内存模式
      ckpt.checkpoint('S', { step: 10 });
      expect(ckpt.restore('S')!.state.step).toBe(10);
    });
  });
});

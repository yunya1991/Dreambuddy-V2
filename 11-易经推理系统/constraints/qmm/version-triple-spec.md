# QMM 版本三元组规范

**日期**: 2026-05-13
**版本**: v1.0

---

## 一、概述

QMM 每次产物必须可追溯到完整的版本链：

```
data_version / feature_def_version / qmm_version
```

这确保任何信号输出都可以回答三个问题：
1. 基于哪个数据快照？（data_version）
2. 用了哪个特征定义？（feature_def_version）
3. 用了哪个 QMM 规则版本？（qmm_version）

---

## 二、版本格式

### 2.1 data_version

事实事件流切片/快照版本。

```
格式: dv-{YYYYMMDD}-{N}

示例:
  dv-20260513-001    2026-05-13 第 1 次数据快照
  dv-20260513-002    2026-05-13 第 2 次数据快照（有新增 case）
```

生成规则：
- 每次 QMM 运行时，扫描 `.workbuddy/memory_l4/cases/` 目录
- 计算 case 文件数量和最近修改时间的 hash
- 如果与上次不同，生成新 data_version

### 2.2 feature_def_version

特征口径与派生规则版本。

```
格式: fd-{major}.{minor}

示例:
  fd-1.0    Phase 1/2 特征定义（quadrant x/y, pnl, regime, stage_coverage）
  fd-2.0    Phase 3 特征定义（+ embedding, + market features）
  fd-3.0    Phase 4 特征定义（+ 跨市场特征, + 知识图谱特征）
```

变更规则：
- **major 变更**：特征增减或口径改变（如新增 velocity 特征）
- **minor 变更**：特征计算实现优化但口径不变（如异常值处理改进）

### 2.3 qmm_version

QMM 规则/参数版本。

```
格式: qmm-v{major}.{minor}

示例:
  qmm-v1.0    Phase 1 确定性基线
  qmm-v1.1    Phase 1 参数微调（如三屏窗口大小调整）
  qmm-v2.0    Phase 3 ML 训练器引入
  qmm-v3.0    Phase 4 表征学习 + 动态权重
```

变更规则：
- **major 变更**：核心算法改变（如引入 ML、改变 MRD 公式）
- **minor 变更**：参数调整但算法不变（如阈值从 20 调到 25）

---

## 三、版本在产物中的位置

每个 QMM 输出 JSON 必须包含：

```json
{
  "version": "qmm-v1.0",
  "snapshot_ts": "2026-05-13T15:30:00+08:00",
  "version_chain": {
    "data_version": "dv-20260513-001",
    "feature_def_version": "fd-1.0",
    "qmm_version": "qmm-v1.0"
  },
  "trend_state": "UP",
  "mrd_vector": { ... },
  "uncertainty": 0.23,
  "reason_codes": ["BULLISH_ALIGNMENT"],
  "evidence_refs": ["TC_001", "TC_002", "TC_003"]
}
```

---

## 四、版本追溯查询

给定一个 QMM 信号，可通过版本三元组追溯：

```
qmm-v1.0 / fd-1.0 / dv-20260513-001
    ↓
data: .workbuddy/memory_l4/cases/ (N files, latest at 2026-05-13T14:00:00)
feature: Phase 1 特征定义 (quadrant x/y, pnl, regime, stage_coverage)
qmm: 确定性基线算法 (三屏对齐 + MRD + 趋势速度)
```

---

## 五、版本变更流程

```
1. 开发者识别需要变更（新特征/新算法/数据更新）
2. 按上述规则确定新版本号
3. 在 constraints/qmm/architecture.md 中记录变更原因
4. 更新对应 phase 文档
5. 提交 PR
6. 新版本产物自动携带新版本三元组
```

---

## 六、版本兼容性

| qmm_version | 兼容的 fd_version | 兼容的 data_version |
|-------------|-------------------|---------------------|
| qmm-v1.x | fd-1.0 | 任意 dv |
| qmm-v2.x | fd-1.0, fd-2.0 | 任意 dv |
| qmm-v3.x | fd-1.0, fd-2.0, fd-3.0 | 任意 dv |

向后兼容原则：新 QMM 版本应能处理旧数据版本。

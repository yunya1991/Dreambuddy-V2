# technical — 技术方案调研

> 架构模式、算法实现、测试方法的技术方案对比调研归档。

## 子类

| 子目录 | 说明 | 典型主题 |
|--------|------|---------|
| [architecture/](./architecture/) | 架构模式 | Shadow模式、FAIL-OPEN、模块化开关 |
| [algorithms/](./algorithms/) | 算法实现 | Bayesian更新、CBR/KNN、弹性系数β |
| [testing/](./testing/) | 测试方法 | TDD红绿循环、字节等价、WalkForward |

## 已归档调研

### architecture（架构模式）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [FAIL-OPEN架构模式统一范式调研](./architecture/2026-09-01-FAIL-OPEN架构模式统一范式调研.md) | 2026-09-01 | L0-L4四级降级模型（正常/模块内替换/混合单路缺失/全链降级）；DreamBuddy 25处真实FAIL-OPEN全景扫描；15处契约清单（3处规范格式+1处P0根因反模式黑名单写盘吞异常）；5行标准模板代码；3处P1立即修复项（weight_feedback/memory_bridge/build_graph） |

### algorithms（算法实现）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [TDA持久同调Ising相变Kalman-PCA衍生算法调研](./algorithms/2026-09-01-TDA持久同调Ising相变Kalman-PCA衍生算法调研.md) | 2026-09-01 | TDA Betti数持久条形码(持久性>0.6留信号) / Ising Tc=1/(2σ)临界温度 / Kalman-PCA λ1/Σλ>0.75共振三算法9维对照；9文件13处真实代码坐标；5张决策表(算法对比/依赖兼容/场景适用/集成场景/置信度注入)；TDA×Ising×PCA三重叠加BCRM2 conf -0.03-0.04-0.05；4条P1建议(持久条形码方法/临界温度方法/PCA共振分数方法/依赖安装门禁) |

### testing（测试方法）
_（暂无，随开发过程自动积累）_

---

_最后更新：2026-09-01（W3 批量填充后）_

/**
 * 用户上下文标准对象契约
 * 
 * 定义用户上下文索引系统的标准接口，用于从 summary-only 模式升级到完整集成。
 * 
 * 重要约束：
 * - 用户配置数据属于敏感信息，不能直接透出到 ui-map
 * - 只能展示经过脱敏和聚合的上下文摘要信息
 * - 基于 artifacts 索引的产物统计来构建上下文可见范围
 */

export interface UserContextConfiguration {
  /** 上下文类型：build-time(策略构建) / runtime(策略执行) */
  contextType: 'build-time' | 'runtime';
  /** 可见的产物类型范围 */
  visibleArtifactTypes: string[];
  /** 可见的部门范围 */
  visibleDepartments: string[];
}

export interface UserContextArtifact {
  /** 产物 ID */
  artifactId: string;
  /** 产物标题 */
  title: string;
  /** 产物类型 */
  type: string;
  /** 所属部门 */
  department: string;
  /** 关联的策略数量 */
  linkedStrategyCount: number;
  /** 最后更新时间 */
  lastUpdated: string;
}

export interface UserContextSummary {
  /** 上下文 ID */
  contextId: string;
  /** 用户 ID（脱敏） */
  userIdHash: string;
  /** 上下文类型 */
  type: 'build-time' | 'runtime';
  /** 上下文配置（已脱敏） */
  configuration: UserContextConfiguration;
  /** 可索引的产物数量 */
  indexableArtifactCount: number;
  /** 上下文覆盖率 */
  coverageRate: number;
  /** 创建时间 */
  createdAt: string;
  /** 更新时间 */
  updatedAt: string;
}

export interface UserContextFullView {
  /** 上下文摘要 */
  summary: UserContextSummary;
  /** 关联的产物列表（已脱敏） */
  linkedArtifacts: UserContextArtifact[];
  /** 可用于策略构建的产物数量 */
  buildTimeArtifactCount: number;
  /** 可用于策略执行的产物数量 */
  runtimeArtifactCount: number;
}

/**
 * 从 artifacts 数据构建用户上下文摘要
 * 
 * 注意：此函数只基于 artifacts 索引构建摘要，不涉及敏感用户配置数据
 */
export function buildUserContextSummary(
  artifactsData: {
    total: number;
    statistics: {
      by_department: Record<string, number>;
      by_type: Record<string, number>;
      by_status: Record<string, number>;
    };
    artifacts: Array<{
      artifact_id: string;
      title: string;
      type: string;
      department: string;
      status: string;
      date: string;
    }>;
  },
  contextType: 'build-time' | 'runtime' = 'build-time'
): UserContextFullView {
  const totalArtifacts = artifactsData.total;
  const departments = Object.keys(artifactsData.statistics.by_department ?? {});
  const artifactTypes = Object.keys(artifactsData.statistics.by_type ?? {});
  
  // 统计已完成和活跃的产物
  const byStatus = artifactsData.statistics.by_status ?? {};
  const completedCount = Number(byStatus['completed'] ?? 0);
  const activeCount = totalArtifacts - completedCount;
  
  // 构建上下文配置（基于公开的 artifacts 统计）
  const configuration: UserContextConfiguration = {
    contextType,
    visibleArtifactTypes: artifactTypes,
    visibleDepartments: departments,
  };
  
  // 构建关联产物列表（已脱敏）
  const linkedArtifacts: UserContextArtifact[] = artifactsData.artifacts.slice(0, 10).map((artifact) => ({
    artifactId: artifact.artifact_id,
    title: artifact.title,
    type: artifact.type,
    department: artifact.department,
    linkedStrategyCount: 0, // artifacts 索引不包含策略关联信息
    lastUpdated: artifact.date,
  }));
  
  // 计算上下文覆盖率（基于可见的产物类型和部门）
  const coverageRate = Math.min(
    (departments.length / 10) * 0.5 + (artifactTypes.length / 5) * 0.5,
    1.0
  );
  
  const summary: UserContextSummary = {
    contextId: `uc-${contextType}-${Date.now()}`,
    userIdHash: 'HASHED', // 不透出真实用户 ID
    type: contextType,
    configuration,
    indexableArtifactCount: contextType === 'build-time' ? completedCount : activeCount,
    coverageRate,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  
  return {
    summary,
    linkedArtifacts,
    buildTimeArtifactCount: completedCount,
    runtimeArtifactCount: activeCount,
  };
}

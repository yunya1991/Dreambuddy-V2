'use strict';

/** 进程内计数器：付费报告按规则版本聚合（重启清零，仅供灰度决策参考）。 */
function createMetrics() {
  const paidByVersion = {};

  return {
    recordPaidReport(version) {
      const key = String(version ?? '');
      if (!key) return;
      paidByVersion[key] = (paidByVersion[key] || 0) + 1;
    },
    paidReportVersions() {
      return { ...paidByVersion };
    }
  };
}

module.exports = { createMetrics };

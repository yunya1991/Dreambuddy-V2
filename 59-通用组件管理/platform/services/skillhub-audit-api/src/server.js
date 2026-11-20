'use strict';

const { loadConfig } = require('./config');
const { createApp } = require('./app');
const { createAlipayClient } = require('./alipay');
const { SqliteOrderRepository } = require('./store');
const { createMetrics } = require('./metrics');
const { createStatsService } = require('./stats');
const { createAdminApp } = require('./admin');
const { startCleanupJobs } = require('./cleanup');

function main() {
  const config = loadConfig();
  const repository = new SqliteOrderRepository(config.dbPath);
  const alipay = createAlipayClient(config);
  const metrics = createMetrics();
  const app = createApp({ config, repository, alipay, metrics });

  const server = app.listen(config.port, config.host, () => {
    console.log(
      `[skillhub-audit-api] listening on ${config.host}:${config.port} price=${config.price}${config.currency} ` +
        `serviceId=${config.serviceId} gateway=${config.gateway} sandbox=${config.sandboxExact}`
    );
  });

  let adminServer = null;
  if (config.admin) {
    const stats = createStatsService({
      repository,
      eventsFile: config.beacon.logPath,
      trialGlobalDaily: config.trial ? config.trial.globalDaily : 0,
      publicJsonPath: config.publicJsonPath,
      paidVersions: () => metrics.paidReportVersions()
    });
    const adminApp = createAdminApp({ config, getStats: (force) => stats.getStats(force) });
    adminServer = adminApp.listen(config.admin.port, config.admin.host, () => {
      console.log(`[skillhub-audit-api] admin listening on ${config.admin.host}:${config.admin.port} (X-Admin-Token)`);
    });
  } else {
    console.log('[skillhub-audit-api] ADMIN_TOKEN 未设置，管理接口（8789）未启动');
  }

  const cleanup = startCleanupJobs({
    repository,
    eventsFile: config.beacon.logPath
  });

  const shutdown = (signal) => {
    console.log(`[skillhub-audit-api] ${signal} received, shutting down`);
    cleanup.stop();
    const closeAdmin = () => new Promise((resolve) => (adminServer ? adminServer.close(resolve) : resolve()));
    server.close(() => {
      closeAdmin().then(() => {
        repository.close();
        process.exit(0);
      });
    });
    setTimeout(() => process.exit(1), 10000).unref();
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main();

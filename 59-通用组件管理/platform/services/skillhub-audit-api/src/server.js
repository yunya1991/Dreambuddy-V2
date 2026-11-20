'use strict';

const { loadConfig } = require('./config');
const { createApp } = require('./app');
const { createAlipayClient } = require('./alipay');
const { SqliteOrderRepository } = require('./store');

function main() {
  const config = loadConfig();
  const repository = new SqliteOrderRepository(config.dbPath);
  const alipay = createAlipayClient(config);
  const app = createApp({ config, repository, alipay });

  const server = app.listen(config.port, config.host, () => {
    console.log(
      `[skillhub-audit-api] listening on ${config.host}:${config.port} price=${config.price}${config.currency} ` +
        `serviceId=${config.serviceId} gateway=${config.gateway} sandbox=${config.sandboxExact}`
    );
  });

  const shutdown = (signal) => {
    console.log(`[skillhub-audit-api] ${signal} received, shutting down`);
    server.close(() => {
      repository.close();
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10000).unref();
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main();

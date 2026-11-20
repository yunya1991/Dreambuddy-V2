'use strict';

const express = require('express');
const spec = require('./rules.generated');

/**
 * 管理接口：仅 127.0.0.1:ADMIN_PORT，所有路由要求 X-Admin-Token。
 * 公网入口由 nginx 8082 叠加 Basic Auth 后反代。
 */
function createAdminApp({ config, getStats }) {
  const app = express();
  app.disable('x-powered-by');

  app.use((req, res, next) => {
    const token = req.get('X-Admin-Token');
    if (!token || token !== config.admin.token) {
      return res.status(401).json({ code: 'UNAUTHORIZED', message: '需要有效的 X-Admin-Token' });
    }
    return next();
  });

  app.get('/health', (req, res) => {
    res.json({
      status: 'ok',
      service: 'skillhub-audit-api',
      price: config.price,
      currency: config.currency,
      rules_version: spec.version,
      score_formula_version: spec.score.formula,
      rate_limit_mode: 'memory'
    });
  });

  app.get('/api/stats', (req, res) => {
    res.set('Cache-Control', 'no-store');
    res.json(getStats());
  });

  app.use((req, res) => res.status(404).json({ code: 'NOT_FOUND' }));
  return app;
}

module.exports = { createAdminApp };

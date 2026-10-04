const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push('CONSOLE: ' + msg.text());
  });
  page.on('pageerror', err => errors.push('PAGEERROR: ' + err.message + '\n' + (err.stack||'').split('\n').slice(0,8).join('\n')));
  await page.goto('http://localhost:3001/dashboard/settings', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  console.log('=== ERRORS ===');
  console.log(errors.join('\n\n') || 'no errors');
  await browser.close();
})();

const { chromium } = require('playwright');
(async () => {
  const [, , pwd] = process.argv;
  const b = await chromium.launch(); const p = await b.newPage();
  let fired = false, cspViolations = 0;
  p.on('dialog', async d => { fired = true; await d.dismiss(); });
  p.on('console', m => { if (/Content Security Policy/i.test(m.text())) cspViolations++; });
  await p.goto('http://127.0.0.1:8099/');
  await p.waitForSelector('#login-view:not(.hidden)');
  await p.fill('#login-form input[name=email]', 'admin@pentest.com.br');
  await p.fill('#login-form input[name=password]', pwd);
  await p.click('#login-form button[type=submit]');
  await p.waitForSelector('#app-view:not(.hidden)');
  for (const v of ['clientes', 'qualidade', 'painel']) { await p.click(`#nav button[data-view=${v}]`); await p.waitForTimeout(700); }
  await p.click('#nav button[data-view=clientes]'); await p.waitForTimeout(700);
  const shown = await p.locator('#main td', { hasText: '<img src=x' }).count();
  const injected = await p.locator('#main img[src="x"]').count();
  console.log(JSON.stringify({ alertFired: fired, payloadShownAsText: shown > 0, imgInjected: injected, cspViolations }));
  await b.close();
})();

// Renders stage/wide.html to out/wide_bg.png and a rounded-corner alpha mask for the 16:9 composite.
const path = require('path');
const { pathToFileURL } = require('url');
const puppeteer = require('puppeteer-core');
const DATA = process.env.REGKNOT_VIDEO_DATA || path.resolve(__dirname, '..', '..', 'data', 'video');
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
    args: ['--force-device-scale-factor=1', '--allow-file-access-from-files'], defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 } });
  const p = await b.newPage();
  await p.goto(pathToFileURL(path.join(__dirname, 'stage', 'wide.html')).href, { waitUntil: 'networkidle0' });
  await p.evaluate(() => document.fonts.ready);
  await p.screenshot({ path: path.join(DATA, 'out', 'wide_bg.png') });
  await p.setViewport({ width: 562, height: 1000, deviceScaleFactor: 1 });
  await p.setContent('<html><body style="margin:0;background:#000"><div style="width:562px;height:1000px;border-radius:34px;background:#fff"></div></body></html>');
  await p.screenshot({ path: path.join(DATA, 'out', 'wide_mask.png') });
  await b.close();
  console.log('ok');
})();

// Deterministic frame renderer: seek(t) → screenshot → ffmpeg.
//   node render.js <cut> stills 0.5,3.4,...   → out/stills/<cut>_<t>.png
//   node render.js <cut> events               → out/<cut>_events.json (for audio.py)
//   node render.js <cut> video [fps]          → out/<cut>_9x16_silent.mp4 + out/<cut>_events.json
// out/ and the assets live in data/video/ (gitignored); REGKNOT_VIDEO_DATA overrides.
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { pathToFileURL } = require('url');
const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const FFMPEG = process.env.FFMPEG;
const HERE = __dirname;
const DATA = process.env.REGKNOT_VIDEO_DATA || path.resolve(HERE, '..', '..', 'data', 'video');
const OUT = path.join(DATA, 'out');
fs.mkdirSync(path.join(OUT, 'stills'), { recursive: true });

(async () => {
  // --vo <voice>: the voice-over variant; captions come from data/video/vo/<cut>_<voice>.js
  // and every output is named <cut>_<voice>_…
  const argv = process.argv.slice(2);
  const voAt = argv.indexOf('--vo');
  const voice = voAt >= 0 ? argv.splice(voAt, 2)[1] : null;
  const [cut = 'main', mode = 'stills', arg] = argv;
  const name = voice ? `${cut}_${voice}` : cut;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--force-device-scale-factor=1', '--hide-scrollbars', '--allow-file-access-from-files', '--disable-web-security', '--font-render-hinting=none', '--force-color-profile=srgb'],
    defaultViewport: { width: 1080, height: 1920, deviceScaleFactor: 1 },
  });
  const page = await browser.newPage();
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) console.log('[page]', m.type(), m.text()); });
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  const assets = pathToFileURL(path.join(DATA, 'assets')).href + '/';
  let url = pathToFileURL(path.join(HERE, 'stage', 'stage.html')).href + `?cut=${cut}&assets=${encodeURIComponent(assets)}`;
  if (voice) url += `&vo=${encodeURIComponent(pathToFileURL(path.join(DATA, 'vo', `${name}.js`)).href)}`;
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 });
  const info = await page.evaluate(() => window.ready);
  console.log('ready', JSON.stringify(info));
  const cdp = await page.target().createCDPSession();
  const shot = async (fmt, quality) => {
    const { data } = await cdp.send('Page.captureScreenshot', fmt === 'png' ? { format: 'png' } : { format: 'jpeg', quality });
    return Buffer.from(data, 'base64');
  };

  if (mode === 'events') {
    const events = await page.evaluate(() => window.EVENTS);
    fs.writeFileSync(path.join(OUT, `${name}_events.json`), JSON.stringify({ duration: info.duration, events }, null, 1));
    console.log('events', events.length);
  } else if (mode === 'stills') {
    const times = (arg || '0').split(',').map(Number);
    for (const t of times) {
      await page.evaluate(tt => window.seek(tt), t);
      const buf = await shot('png');
      const f = path.join(OUT, 'stills', `${name}_${t.toFixed(2)}.png`);
      fs.writeFileSync(f, buf);
      console.log(f);
    }
  } else {
    const fps = Number(arg || 30);
    const events = await page.evaluate(() => window.EVENTS);
    fs.writeFileSync(path.join(OUT, `${name}_events.json`), JSON.stringify({ duration: info.duration, events }, null, 1));
    const n = Math.round(info.duration * fps);
    const outFile = path.join(OUT, `${name}_9x16_silent.mp4`);
    const ff = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
      '-vf', 'scale=in_range=full:out_range=limited:out_color_matrix=bt709,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '15', '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
      '-movflags', '+faststart', outFile], { stdio: ['pipe', 'inherit', 'inherit'] });
    const t0 = Date.now();
    for (let f = 0; f < n; f++) {
      await page.evaluate(tt => window.seek(tt), f / fps);
      const buf = await shot('jpeg', 95);
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (f % 150 === 0) console.log(`frame ${f}/${n}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
    console.log('wrote', outFile, `${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });

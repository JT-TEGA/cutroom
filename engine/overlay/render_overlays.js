#!/usr/bin/env node
// Render the overlay layer (captions, text, flashes, end card) to a transparent PNG sequence.
//   node engine/overlay/render_overlays.js work/<name>/overlay/spec.json work/<name>/overlay/frames
// Only frames whose content changes are screenshotted; the rest are hard links,
// so ffmpeg can read a plain f_00000.png ... sequence at the project fps.
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const puppeteer = require('puppeteer');

(async () => {
  const [specPath, outDir] = process.argv.slice(2);
  if (!specPath || !outDir) {
    console.error('usage: render_overlays.js spec.json outDir');
    process.exit(2);
  }
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await puppeteer.launch({
    headless: 'shell',   // chrome-headless-shell: faster for screenshots, and new headless can hang on captureScreenshot
    args: ['--allow-file-access-from-files', '--font-render-hinting=none', '--hide-scrollbars'],
  });
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error') console.error('[page]', m.text()); });
    page.on('pageerror', e => console.error('[page error]', e.message));
    await page.setViewport({ width: spec.width, height: spec.height, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.join(__dirname, 'overlay.html')).href);
    await page.evaluate(s => window.setup(s), spec);

    const keys = await page.evaluate(n => window.allKeys(n), spec.frames);
    const t0 = Date.now();
    let prev = null, uniq = -1;
    const map = new Array(spec.frames);
    for (let i = 0; i < spec.frames; i++) {
      if (keys[i] !== prev) {
        uniq++;
        await page.evaluate(i => window.draw(i), i);
        await page.screenshot({
          path: path.join(outDir, `u_${String(uniq).padStart(5, '0')}.png`),
          omitBackground: true, optimizeForSpeed: true, captureBeyondViewport: false,
        });
        prev = keys[i];
      }
      map[i] = uniq;
      if (i % 150 === 0) process.stdout.write(`  overlay frame ${i}/${spec.frames}\r`);
    }
    for (let u = 0; u <= uniq; u++) {   // PNG colour type 6 = RGBA; anything else breaks the ffmpeg sequence
      const head = fs.readFileSync(path.join(outDir, `u_${String(u).padStart(5, '0')}.png`)).subarray(0, 26);
      if (head[25] !== 6) console.error(`  ! overlay frame u_${u} has no alpha channel (colour type ${head[25]})`);
    }
    for (let i = 0; i < spec.frames; i++) {
      fs.linkSync(path.join(outDir, `u_${String(map[i]).padStart(5, '0')}.png`),
                  path.join(outDir, `f_${String(i).padStart(5, '0')}.png`));
    }
    console.log(`  overlay: ${spec.frames} frames, ${uniq + 1} unique, ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });

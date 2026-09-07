import { chromium } from 'playwright';
import { readFileSync, mkdirSync, writeFileSync } from 'fs';

const svg = readFileSync('/home/user/ai-news-digest/desktop/icon.svg', 'utf8');
const sizes = [16, 32, 64, 128, 256, 512, 1024];
mkdirSync('icons', { recursive: true });

const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
for (const s of sizes) {
  const p = await b.newPage({ viewport: { width: s, height: s }, deviceScaleFactor: 1 });
  await p.setContent(
    `<style>html,body{margin:0;padding:0;background:transparent}
     svg{display:block;width:${s}px;height:${s}px}</style>${svg}`,
    { waitUntil: 'load' });
  const buf = await p.locator('svg').screenshot({ omitBackground: true });
  writeFileSync(`icons/icon_${s}.png`, buf);
  await p.close();
  console.log(`icon_${s}.png  ${buf.length} bytes`);
}
await b.close();

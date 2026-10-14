// Deploy step (Pages workflow, Vercel): the new site becomes the main address (docs/49).
//   node scripts/assemble.mjs <site dir> <astro build dir>
// 1. The previous single-page site (site/index.html) moves to classic/ (its links to site files are pointed one level up;
//    in-page anchors keep working).
// 2. The Astro build is copied over the site (figures, downloads and archived releases of site/ stay where they are).
// 3. Every page published under next/ (releases 2026-10-14.3 to .7) forwards to its new address.
import fs from 'node:fs';
import path from 'node:path';

const [siteArg, distArg] = process.argv.slice(2);
if (!siteArg || !distArg) throw new Error('usage: node scripts/assemble.mjs <site dir> <astro build dir>');
const site = path.resolve(siteArg), dist = path.resolve(distArg);
if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error(`no Astro build in ${dist}`);

// 1. the classic page
const old = fs.readFileSync(path.join(site, 'index.html'), 'utf-8');
const already = old.includes('data-pagefind-body');                  // assembled before: the root is the new site already
const banner = '<div style="background:#e6f1ed;color:#0b0b0b;padding:8px 16px;font:14px/1.5 system-ui,sans-serif;border-bottom:1px solid #b9d7cc">' +
  'This is the previous single-page version of the site, kept unchanged. <a href="./">Open the current site</a>.</div>';
const classic = old.replace(/(["'(])(assets|downloads|data|releases)\//g, '$1../$2/').replace('<body>', '<body>' + banner.replace('href="./"', 'href="../"'));
if (!already) {
  fs.mkdirSync(path.join(site, 'classic'), { recursive: true });
  fs.writeFileSync(path.join(site, 'classic', 'index.html'), classic);
}

// 2. the new site over the old root
const pages = [];
const copy = (src, dst) => {
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) { fs.mkdirSync(d, { recursive: true }); copy(s, d); }
    else { fs.copyFileSync(s, d); if (e.name === 'index.html') pages.push(path.relative(dist, src).split(path.sep).join('/')); }
  }
};
copy(dist, site);

// 3. next/ addresses forward to the new ones (the base is read from the built home page)
const base = (fs.readFileSync(path.join(dist, 'index.html'), 'utf-8').match(/<link rel="stylesheet" href="([^"]*?)assets\/style\.css"/) || [, '/'])[1];
fs.rmSync(path.join(site, 'next'), { recursive: true, force: true });
for (const p of pages) {
  if (p.startsWith('pagefind')) continue;
  const to = base + (p ? p + '/' : '');
  const dir = path.join(site, 'next', p);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=${to}">` +
    `<link rel="canonical" href="${to}"><title>Moved</title></head><body><p>This page has moved: <a href="${to}">${to}</a></p></body></html>\n`);
}
console.log(`Assembled: ${pages.length} pages at the root, the previous page at classic/, ${pages.length} forwards under next/`);

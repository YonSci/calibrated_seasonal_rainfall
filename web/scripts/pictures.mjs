// After `astro build`: every figure of the site (<img src=".../assets/....png">) is served through <picture> with the WebP
// display copies of scripts/site_webp.py (640 and 1280 pixels wide) when they exist in ../site/assets; the PNG stays the
// fallback and the full-size image. Images also get decoding="async", loading="lazy" (unless set) and their pixel size,
// so the page does not jump while they load.
import fs from 'node:fs';
import path from 'node:path';

const base = process.env.ASTRO_BASE ?? '/calibrated_seasonal_rainfall/';
const ROOT = base.replace(/next\/$/, '');
const SITE = path.resolve(process.env.SITE_DIR ?? '../site');
export const SIZES = '(max-width: 860px) 100vw, 60vw';

const pngSize = (file) => {
  try {
    const b = Buffer.alloc(24); const fd = fs.openSync(file, 'r'); fs.readSync(fd, b, 0, 24, 0); fs.closeSync(fd);
    return b.toString('latin1', 12, 16) === 'IHDR' ? [b.readUInt32BE(16), b.readUInt32BE(20)] : null;
  } catch { return null; }
};
const local = (src) => (src.startsWith(ROOT + 'assets/') ? path.join(SITE, decodeURI(src.slice(ROOT.length))) : null);

export function srcsetOf(src) {
  const f = local(src);
  if (!f || !f.endsWith('.png')) return null;
  const W = (pngSize(f) ?? [Infinity])[0], seen = new Set();
  const v = [640, 1280].filter((w) => fs.existsSync(f.replace(/\.png$/, `.w${w}.webp`)))
    .map((w) => [w, Math.min(w, W)]).filter(([, a]) => !seen.has(a) && seen.add(a));      // true widths: copies are never enlarged
  return v.length ? v.map(([w, a]) => `${src.replace(/\.png$/, `.w${w}.webp`)} ${a}w`).join(', ') : null;
}

function rewrite(html) {
  let n = 0;
  const out = html.replace(/(<picture\b[\s\S]*?<\/picture>)|<img\b([^>]*?)\bsrc="([^"]+\.png)"([^>]*)>/g, (m, pic, pre, src, post) => {
    if (pic) return pic;                                     // already a picture
    const attrs = pre + post;
    const f = local(src);
    let img = '<img' + pre + 'src="' + src + '"' + post;
    if (!/\bdecoding=/.test(attrs)) img += ' decoding="async"';
    if (!/\bloading=/.test(attrs)) img += ' loading="lazy"';
    const dims = f && !/\bwidth=/.test(attrs) ? pngSize(f) : null;
    if (dims) img += ` width="${dims[0]}" height="${dims[1]}"`;
    img += '>';
    const set = srcsetOf(src);
    if (!set) return img;
    n++;
    return `<picture><source type="image/webp" srcset="${set}" sizes="${SIZES}">${img}</picture>`;
  });
  return [out, n];
}

export function pictures(dir) {
  let pages = 0, figs = 0;
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (e.name !== 'pagefind') walk(p); }
      else if (e.name.endsWith('.html')) {
        const html = fs.readFileSync(p, 'utf-8');
        const [out, n] = rewrite(html);
        if (out !== html) { fs.writeFileSync(p, out); pages++; figs += n; }
      }
    }
  };
  walk(dir);
  return { pages, figs };
}

// The DRN at a glance (scripts/neural_calibration.py, docs/54): inputs -> standardization -> shared network -> censored
// shifted gamma -> mixture of three seeds -> products, with the training below. One SVG for the research page (colours as
// CSS variables, so it follows the site theme) and the scientists' deck (fixed colours, rasterized there).
const CSS = {
  ink: 'var(--ink)', ink2: 'var(--ink2)', muted: 'var(--muted)', line: 'var(--line)', surface: 'var(--surface)', bg: 'var(--bg)',
  accent: 'var(--accent)', soft: 'var(--accent-soft)', below: 'var(--below)', near: 'var(--near)', above: 'var(--above)', fc: 'var(--fc)',
};
export const HEX = {
  ink: '#222221', ink2: '#52514e', muted: '#6b6a66', line: '#d9d6d2', surface: '#ffffff', bg: '#f7f7f5',
  accent: '#762123', soft: '#f3e9e9', below: '#a6611a', near: '#8f8d86', above: '#1b7c94', fc: '#2a78d6',
};

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function drnDiagram(colours = CSS, { font = 'Inter, Calibri, Arial, sans-serif', title = true, background = null } = {}) {
  const C = { ...CSS, ...colours };
  const W = 1000, H = 548;
  let g = '';
  const text = (x, y, s, o = {}) => {
    g += `<text x="${x}" y="${y}" font-size="${o.size ?? 12}" fill="${o.fill ?? C.ink}"${o.weight ? ` font-weight="${o.weight}"` : ''}` +
      `${o.anchor ? ` text-anchor="${o.anchor}"` : ''}${o.italic ? ' font-style="italic"' : ''}>${esc(s)}</text>`;
  };
  const box = (x, y, w, h, o = {}) => {
    g += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${o.r ?? 8}" fill="${o.fill ?? C.surface}" stroke="${o.stroke ?? C.line}"` +
      ` stroke-width="${o.sw ?? 1.2}"${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}/>`;
  };
  const line = (x1, y1, x2, y2, o = {}) => {
    g += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${o.stroke ?? C.ink2}" stroke-width="${o.sw ?? 1}"` +
      `${o.op != null ? ` stroke-opacity="${o.op}"` : ''}${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}${o.arrow ? ' marker-end="url(#drn-arrow)"' : ''}/>`;
  };
  const node = (x, y, r, o = {}) => {
    g += `<circle cx="${x}" cy="${y}" r="${r}" fill="${o.fill ?? C.surface}" stroke="${o.stroke ?? C.accent}" stroke-width="${o.sw ?? 1.6}"` +
      `${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}/>`;
  };

  // column headings
  [[125, 'Inputs (per cell and year)'], [276, 'Scale'], [400, 'Shared network'], [712, 'Distribution (3 seeds)'], [928, 'Products']]
    .forEach(([x, s]) => text(x, 22, s, { anchor: 'middle', weight: 700, size: 13, fill: C.accent }));

  // 1 inputs
  const groups = [
    { y: 36, h: 178, head: 'SEAS5 ensemble, 25 members', sub: 'relative to the cell’s SEAS5 training mean',
      items: ['ensemble mean', 'ensemble median', 'standard deviation', 'mean absolute difference', '10% and 90% quantiles'] },
    { y: 226, h: 92, head: 'Local climate (CHIRPS v3.0)', sub: 'training years of the fold', items: ['log of the mean rainfall', 'coefficient of variation'] },
    { y: 330, h: 74, head: 'Location', sub: '0.25° grid cell', items: ['latitude, longitude'] },
  ];
  groups.forEach((gr) => {
    box(10, gr.y, 232, gr.h, { fill: C.soft, stroke: C.line });
    text(22, gr.y + 20, gr.head, { weight: 700, size: 12.5 });
    text(22, gr.y + 36, gr.sub, { size: 10.5, fill: C.muted });
    gr.items.forEach((s, i) => text(30, gr.y + 56 + i * 20, '• ' + s, { size: 12 }));
  });
  text(126, 424, '10 inputs (6 + 2 + 2); the observation', { anchor: 'middle', size: 10.5, fill: C.muted });
  text(126, 437, 'is relative to the CHIRPS training mean', { anchor: 'middle', size: 10.5, fill: C.muted });

  // 2 standardization
  box(258, 36, 36, 368, { fill: C.bg, stroke: C.ink2, r: 6 });
  g += `<text x="0" y="0" transform="translate(281 220) rotate(-90)" font-size="11.5" text-anchor="middle" fill="${C.ink}">standardized with the fold’s training samples</text>`;

  // 3 hidden layers and outputs
  const h1 = Array.from({ length: 9 }, (_, i) => 62 + i * 39), h2 = Array.from({ length: 6 }, (_, i) => 120 + i * 40);
  const out = [150, 220, 290];
  const mids = groups.map((gr) => gr.y + gr.h / 2);
  mids.forEach((y) => h1.forEach((yy, j) => { if (j !== 4) line(294, y, 351, yy, { op: 0.22 }); }));
  h1.forEach((y, j) => { if (j !== 4) h2.forEach((yy) => line(369, y, 441, yy, { op: 0.14 })); });
  h2.forEach((y) => out.forEach((yy) => line(459, y, 531, yy, { op: 0.25 })));
  h1.forEach((y, j) => (j === 4 ? text(360, y + 5, '⋮', { anchor: 'middle', size: 16, fill: C.muted }) : node(360, y, 9)));
  h2.forEach((y) => node(450, y, 9, { dash: '3 2' }));
  out.forEach((y, i) => { node(540, y, 11, { fill: C.soft }); text(540, y + 4, `o${i + 1}`, { anchor: 'middle', size: 10.5, weight: 700 }); });
  text(360, 418, '32 units, ELU', { anchor: 'middle', size: 11.5, weight: 700 });
  text(450, 418, '16 units, ELU', { anchor: 'middle', size: 11.5, weight: 700 });
  text(450, 432, '(only if chosen)', { anchor: 'middle', size: 10.5, fill: C.muted });
  text(540, 330, '3 outputs', { anchor: 'middle', size: 11.5, weight: 700 });

  // 4 the parameters and the censored shifted gamma
  const pars = [['μ = softplus(o1)', 'mean'], ['σ = softplus(o2)', 'spread'], ['δ = −softplus(o3)', 'shift: chance of no rain']];
  pars.forEach(([f, s], i) => {
    const y = out[i];
    line(552, y, 572, y, { arrow: true, stroke: C.ink2 });
    box(576, y - 20, 126, 40, { r: 6 });
    text(586, y - 3, f, { size: 12, weight: 700 });
    text(586, y + 12, s, { size: 10.5, fill: C.muted });
  });
  // distribution sketch: a point mass at zero and a gamma density above it
  const px = 716, py = 128, pw = 128, ph = 178, x0 = px + 18, base = py + ph - 26;
  box(px + 10, py - 10, pw, ph, { r: 8, fill: C.bg });                    // the three seeds' distributions, mixed
  box(px + 5, py - 5, pw, ph, { r: 8, fill: C.bg });
  box(px, py, pw, ph, { r: 8 });
  line(x0, base, px + pw - 10, base, { stroke: C.ink2 });
  line(x0, base, x0, py + 14, { stroke: C.ink2 });
  g += `<rect x="${x0 - 3}" y="${base - 46}" width="6" height="46" fill="${C.accent}"/>`;
  const k = 2.6, th = 0.38, sh = 0.18, xs = Array.from({ length: 60 }, (_, i) => (i + 1) * 0.05);
  const pdf = (x) => { const z = x + sh; return Math.pow(z, k - 1) * Math.exp(-z / th); };
  const top = Math.max(...xs.map(pdf));
  const pts = xs.map((x) => `${(x0 + x * 34).toFixed(1)},${(base - (pdf(x) / top) * 108).toFixed(1)}`).join(' ');
  g += `<polyline points="${x0},${base} ${pts}" fill="none" stroke="${C.accent}" stroke-width="2"/>`;
  text(x0 + 6, base + 14, '0', { size: 10, fill: C.muted });
  text(px + pw - 12, base + 14, 'rain', { size: 10, fill: C.muted, anchor: 'end' });
  text(px + pw / 2, py + ph + 16, 'censored shifted gamma', { anchor: 'middle', size: 11.5, weight: 700 });
  text(px + pw / 2, py + ph + 30, 'Y = max(0, X + δ) × CHIRPS mean', { anchor: 'middle', size: 10.5, fill: C.muted });
  text(px + pw / 2, py + ph + 43, 'X ~ Gamma(k = μ²/σ², θ = σ²/μ)', { anchor: 'middle', size: 10.5, fill: C.muted });
  text(px + pw / 2, py + ph + 61, 'equal mixture of 3 seeds,', { anchor: 'middle', size: 10.5, fill: C.ink2 });
  text(px + pw / 2, py + ph + 74, 'each with its own held-out years', { anchor: 'middle', size: 10.5, fill: C.ink2 });
  pars.forEach((_, i) => line(702, out[i], 714, out[i] < 220 ? 190 : out[i] > 220 ? 250 : 220, { stroke: C.ink2, op: 0.6 }));

  line(856, 214, 864, 214, { arrow: true });

  // 6 products
  const prods = [
    ['Tercile probabilities', 'at the training terciles'], ['Rainfall amount', 'median of the mixture'],
    ['10–90% range', '10% and 90% quantiles'], ['Full distribution', 'CDF, chance of no rain'],
  ];
  prods.forEach(([a, b], i) => {
    const y = 40 + i * 92;
    box(868, y, 124, 78, { r: 8, stroke: C.accent, sw: 1.4 });
    text(877, y + 20, a, { size: 12, weight: 700 });
    text(877, y + 35, b, { size: 10, fill: C.muted });
    if (i === 0) [[C.below, 0.24], [C.near, 0.31], [C.above, 0.45]].forEach(([c, v], j) =>
      { g += `<rect x="${878 + j * 34}" y="${y + 68 - v * 50}" width="28" height="${v * 50}" fill="${c}" rx="2"/>`; });
    if (i === 2) { line(880, y + 58, 982, y + 58, { stroke: C.ink2, sw: 2 }); g += `<rect x="900" y="${y + 50}" width="50" height="16" fill="${C.soft}" stroke="${C.accent}"/>`; line(922, y + 48, 922, y + 68, { stroke: C.accent, sw: 2 }); }
    if (i === 1) { line(880, y + 58, 982, y + 58, { stroke: C.line, sw: 2 }); node(922, y + 58, 5, { fill: C.accent, stroke: C.accent }); text(932, y + 72, 'median', { size: 10, fill: C.muted }); }
    if (i === 3) { const cx = 878; g += `<polyline points="${cx},${y + 68} ${cx + 4},${y + 58} ${cx + 30},${y + 50} ${cx + 60},${y + 46} ${cx + 110},${y + 45}" fill="none" stroke="${C.accent}" stroke-width="1.8"/>`; }
  });

  // 7 training
  box(10, 456, 982, 86, { fill: C.bg, stroke: C.line });
  text(24, 477, 'Training, inside every outer fold (nothing from the scored year):', { size: 12.5, weight: 700, fill: C.accent });
  text(24, 497, 'Loss: closed-form CRPS of the censored shifted gamma (Scheuerer & Hamill 2015), area-weighted, equal weight per year, + weight decay.', { size: 11.5 });
  text(24, 514, 'Adam (learning rate 0.003, up to 2,000 full-batch steps); stop when the held-out years’ CRPS stops improving (20% of the years, per seed).', { size: 11.5 });
  text(24, 530, 'Architecture (32 or 32–16 units) × weight decay (10⁻⁴ or 10⁻³) chosen by held-out CRPS; trained on every second cell, forecasts for every cell.', { size: 11.5 });

  // arrows between columns
  line(242, 220, 256, 220, { arrow: true });
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="${font}" role="img" aria-labelledby="drn-svg-title">` +
    (title ? '<title id="drn-svg-title">Architecture of the distributional regression network: ten inputs per cell and year, standardized, a shared network of 32 (and optionally 16) ELU units, three outputs turned into the mean, spread and shift of a censored shifted gamma, a mixture of three seeds, and the products: tercile probabilities, amount, 10–90% range and the full distribution.</title>' : '') +
    `<defs><marker id="drn-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.ink2}"/></marker></defs>` +
    (background ? `<rect width="${W}" height="${H}" fill="${background}"/>` : '') + g + '</svg>';
}

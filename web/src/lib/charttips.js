// Interactive SVG charts (svg.chart, drawn at build time in lib/outlook.js and the research pages): the <title> of each bar
// or point becomes a styled tooltip on hover, the hovered element is highlighted, and each chart is one tab stop whose points
// the arrow keys step through (Home / End for the first and last, Escape to hide). Charts drawn later are picked up too.
let tip = null;
const points = (svg) => [...svg.querySelectorAll('[data-tip]')];

function prepare(svg) {
  if (svg.dataset.tips) return;
  svg.dataset.tips = '1';
  svg.querySelectorAll('title').forEach((t) => {
    const el = t.parentElement;
    if (!el || el === svg) return;
    el.dataset.tip = t.textContent.trim();
    el.classList.add('ch-pt');
    t.remove();                                           // the styled tooltip replaces the browser's own
  });
  if (!points(svg).length) return;
  svg.setAttribute('tabindex', '0');
  const label = svg.getAttribute('aria-label') ?? '';
  if (!label.includes('arrow keys')) svg.setAttribute('aria-label', label + (label ? '. ' : '') + 'Use the arrow keys to read each value.');
}

function show(el, x, y) {
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'ch-tip';
    tip.setAttribute('role', 'status');
    document.body.append(tip);
  }
  document.querySelectorAll('.ch-pt.ch-on').forEach((e) => e.classList.remove('ch-on'));
  el.classList.add('ch-on');
  tip.textContent = el.dataset.tip;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.max(6, Math.min(x + 14, innerWidth - r.width - 6)) + 'px';
  tip.style.top = (y + 14 + r.height > innerHeight ? y - r.height - 10 : y + 14) + 'px';
}
function hide() {
  if (tip) tip.hidden = true;
  document.querySelectorAll('.ch-pt.ch-on').forEach((e) => e.classList.remove('ch-on'));
}

export function enableChartTips(root = document) {
  root.querySelectorAll('svg.chart').forEach(prepare);
  document.addEventListener('pointermove', (ev) => {
    const el = ev.target instanceof Element ? ev.target.closest('svg.chart [data-tip]') : null;
    if (el) show(el, ev.clientX, ev.clientY);
    else if (tip && !tip.hidden && !(document.activeElement instanceof SVGElement && document.activeElement.matches('svg.chart'))) hide();
  });
  document.addEventListener('focusin', (ev) => {
    const svg = ev.target instanceof Element ? ev.target.closest('svg.chart') : null;
    if (svg) { prepare(svg); svg.dataset.at = svg.dataset.at ?? '-1'; }
  });
  document.addEventListener('focusout', (ev) => { if (ev.target instanceof Element && ev.target.matches('svg.chart')) hide(); });
  document.addEventListener('keydown', (ev) => {
    const svg = document.activeElement instanceof Element && document.activeElement.matches('svg.chart') ? document.activeElement : null;
    if (!svg) return;
    const pts = points(svg);
    if (!pts.length) return;
    let i = Number(svg.dataset.at ?? -1);
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') i = Math.min(pts.length - 1, i + 1);
    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') i = Math.max(0, i < 0 ? 0 : i - 1);
    else if (ev.key === 'Home') i = 0;
    else if (ev.key === 'End') i = pts.length - 1;
    else if (ev.key === 'Escape') { hide(); return; }
    else return;
    ev.preventDefault();
    svg.dataset.at = String(i);
    const b = pts[i].getBoundingClientRect();
    show(pts[i], b.left + b.width / 2, b.top);
  });
  // charts drawn later (e.g. a period switch) are prepared when they appear
  new MutationObserver(() => root.querySelectorAll('svg.chart:not([data-tips])').forEach(prepare)).observe(document.body, { childList: true, subtree: true });
}

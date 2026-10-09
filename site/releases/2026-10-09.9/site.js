(() => {
  const D = JSON.parse(document.getElementById('site-data').textContent);
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const CAT = ['below normal', 'near normal', 'above normal'];
  const CATV = ['--below', '--near', '--above'];
  const ok = x => x !== null && x !== undefined && !Number.isNaN(x);
  const fx = (x, d = 0) => ok(x) ? Number(x).toFixed(d).replace('-', '−') : '—';
  const sg = (x, d = 0) => !ok(x) ? '—' : Number(Math.abs(x).toFixed(d)) === 0 ? (0).toFixed(d) : (x > 0 ? '+' : '−') + Math.abs(x).toFixed(d);
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const dt = s => { const [y, m, d] = s.split('-').map(Number); return d + ' ' + MON[m - 1] + ' ' + y; };
  const pc = (x, d = 0) => ok(x) ? (100 * x).toFixed(d) + '%' : '—';
  // Shares near the ends are not rounded to 'all' or 'none'; agreement shares keep one decimal.
  const share = x => !ok(x) ? '—' : (x >= 0.995 && x < 1) ? '>99%' : (x > 0 && x < 0.005) ? '<1%' : (100 * x).toFixed(0) + '%';
  const share1 = x => !ok(x) ? '—' : x >= 0.99995 ? '100%' : (100 * x).toFixed(1) + '%';
  const PRODUCTS = D.products;
  const HELP = {
    tercile_outlook: '<p>Colour shows the <strong>most likely tercile</strong> at each place, shaded by its probability: yellow–red for below normal, cyan for near normal, green for above normal. Terciles split the reference-period rainfall into three equally likely parts, so climatology is about 33% each. Places where no category reaches 40% are left white.</p>',
    rainfall_total_mm: '<p>The <strong>corrected ensemble-mean rainfall</strong> for the target period in mm. It is the average of the bias-corrected members, not a probability.</p>',
    rainfall_anomaly_mm: '<p>The <strong>difference in mm</strong> between the corrected ensemble mean and the reference-period CHIRPS average. Red–orange: drier than average; green: wetter.</p>',
    rainfall_anomaly_percent: '<p>The same anomaly as a <strong>percentage of the reference average</strong>. Hidden where the reference rainfall is below 10 mm, where percentages exaggerate small amounts.</p>',
    verification_maps: '<p>All six panels in one figure (also available separately): observed anomaly, forecast anomaly, forecast minus observed, the observed tercile at each cell, the probability score difference against climatology and the rainfall amount score.</p>',
    verification_comparison: '<p><strong>Forecast anomaly (left) and observed anomaly (right)</strong> for the same target and area, cut from one figure: same map extent, units (mm), reference period and colour scale. Brown: drier than average; green: wetter.</p>',
    verification_comparison_error: '<p><strong>Forecast anomaly, observed anomaly and forecast minus observed</strong>. The first two share one colour scale; in the error map red means the forecast was too wet and blue too dry.</p>',
    verification_observed_anomaly: '<p><strong>Observed rainfall anomaly</strong> (CHIRPS minus the reference average, mm). Brown: drier than average; green: wetter. Same colour scale as the forecast anomaly panel.</p>',
    verification_forecast_anomaly: '<p><strong>Forecast anomaly</strong> of the frozen corrected ensemble mean (mm), on the same colour scale as the observed anomaly so the two can be compared directly.</p>',
    verification_error: '<p><strong>Forecast minus observed</strong> rainfall (mm). Red: the forecast was too wet; blue: too dry.</p>',
    verification_observed_tercile: '<p>The <strong>observed tercile</strong> at each grid cell (below, near or above normal) relative to the reference period. Cells are not smoothed or filled from neighbours.</p>',
    verification_rps_difference: '<p><strong>Probability score difference</strong>: RPS of the forecast minus RPS of climatology at each cell. Blue (negative) favours the forecast; red favours climatology.</p>',
    verification_crps: '<p><strong>Rainfall amount score</strong> (CRPS of the corrected ensemble, mm). Lower is better; it grows with the size of the error and with rainfall amounts.</p>'
  };
  let S = {};
  const cyc = () => D.cycles.find(c => c.id === S.cycle);
  const tgt = () => cyc().targets.find(t => t.id === S.target);
  const viewLabel = v => (cyc().views.find(x => x[0] === v) || [v, v])[1];

  function init() {
    const q = new URLSearchParams(location.search);
    const c = D.cycles.find(x => x.id === q.get('cycle')) || D.cycles.find(x => x.id === D.default);
    S.cycle = c.id;
    S.target = c.targets.some(t => t.id === q.get('target')) ? q.get('target') : c.targets[0].id;
    S.view = c.views.some(v => v[0] === q.get('view')) ? q.get('view') : c.domain_view;
    S.kind = q.get('kind') === 'verification' ? 'verification' : 'forecast';
    S.product = q.get('product') || 'tercile_outlook';
    S.period = q.get('period') === 'operational' ? 'operational' : 'training';
  }
  function sync() {
    const q = new URLSearchParams({cycle: S.cycle, target: S.target, view: S.view, kind: S.kind, product: S.product, period: S.period});
    history.replaceState(null, '', location.pathname + '?' + q + location.hash);
  }

  function status(st) { return '<span class="status ' + st.code + '">' + esc(st.text) + '</span>'; }
  function signal(p) {
    if (!p || p.some(x => !ok(x))) return {text: 'Not available', cat: -1, shift: 0};
    const k = p.indexOf(Math.max(...p)), shift = p[k] - 1 / 3;
    const word = shift < 0.04 ? null : shift < 0.10 ? 'Weak' : shift < 0.20 ? 'Moderate' : 'Strong';
    return {cat: word ? k : -1, shift, text: word ? word + ' tilt toward ' + CAT[k] : 'No clear tilt (close to climatology)'};
  }
  // Verbal skill labels carry the uncertainty: an interval that includes zero is not an established gain.
  function skillWord(h) {
    if (!h) return '—';
    if (h.ci[0] > 0) return (h.rpss < 0.03 ? 'Small' : h.rpss < 0.10 ? 'Modest' : 'Moderate') + ' improvement over climatology (interval above zero)';
    if (h.rpss > 0) return 'Small estimated improvement; skill uncertain';
    return 'No demonstrated improvement over climatology';
  }
  function holmText(h, n) {
    if (!h || !ok(h.holm_p)) return '';
    return 'One-target p = ' + h.p.toFixed(3) + '; adjusted for testing ' + n + ' targets (Holm), p = ' + h.holm_p.toFixed(3) + (h.holm_p < 0.05 ? ' (still significant).' : ' (not significant after adjustment).');
  }
  // Historical skill for the selected area; falls back to all Ethiopia with an explicit label.
  function areaHistory(t) {
    const own = t.history[S.view];
    if (own && own.training) return {h: own, area: viewLabel(S.view), fallback: false};
    return {h: t.history.all_ethiopia, area: 'All Ethiopia', fallback: S.view !== 'all_ethiopia'};
  }
  function rpssText(r) { return sg(r, 3) + ' (' + Math.abs(100 * r).toFixed(1) + '% ' + (r >= 0 ? 'lower' : 'higher') + ' score than climatology)'; }
  function img(e, name, cap, alt) {
    const src = e.folder + '/' + name + '.png';
    return '<a href="' + src + '" target="_blank" rel="noopener"><img src="' + src + '" alt="' + esc(alt) +
      '" onerror="this.parentNode.outerHTML=\'<p class=img-error>Map image could not be loaded. Try Open full-size or the Downloads section.</p>\'"></a>' +
      '<figcaption>' + esc(cap) + '</figcaption>';
  }

  // ---------- outlook
  function renderOutlook() {
    const c = cyc(), t = tgt(), f = t.forecast[S.view];
    $('ol-eyebrow').textContent = c.init + ' initialization · ECMWF SEAS5 calibrated with CHIRPS · ' + viewLabel(S.view);
    $('ol-title').textContent = t.label + ' rainfall outlook';
    $('ol-targets').innerHTML = c.targets.map(x => '<button type="button" class="chip" aria-pressed="' + (x.id === S.target) +
      '" data-t="' + x.id + '">' + esc(x.label) + '</button>').join('');
    if (!f) { $('ol-lead').textContent = 'No forecast is available for this view.'; return; }
    const s = f.summary, p = s.mean_local_probabilities, sig = signal(p);
    const ref = s.mean_reference_mm, anomPct = ref ? 100 * s.mean_anomaly_mm / ref : null;
    const where = S.view === 'all_ethiopia' ? 'across Ethiopia' : 'in the ' + viewLabel(S.view);
    let lead = sig.cat >= 0
      ? 'The forecast leans toward <strong>' + CAT[sig.cat] + '</strong> rainfall ' + esc(where) + ': averaged over the area, the local probability of ' + CAT[sig.cat] + ' is <strong>' + pc(p[sig.cat]) + '</strong>, against about 33% for climatology.'
      : 'The forecast is <strong>close to climatology</strong> ' + esc(where) + ': no tercile stands out on average.';
    lead += ' Mean forecast rainfall is ' + fx(s.mean_rainfall_mm) + ' mm against a ' + c.reference + ' average of ' + fx(ref) + ' mm (' + sg(s.mean_anomaly_mm) + ' mm' + (ok(anomPct) ? ', ' + sg(anomPct) + '%' : '') + ').';
    $('ol-lead').innerHTML = lead;
    $('ol-live').textContent = t.label + ', ' + viewLabel(S.view) + ': ' + sig.text + '.';
    $('ol-prob').innerHTML = (p.every(ok)
      ? '<div class="probbar" role="img" aria-label="Below normal ' + pc(p[0]) + ', near normal ' + pc(p[1]) + ', above normal ' + pc(p[2]) + '">' +
        p.map((x, i) => '<span style="width:' + (100 * x).toFixed(1) + '%;background:var(' + CATV[i] + ')"></span>').join('') + '</div>' : '') +
      '<div class="problegend">' + p.map((x, i) => '<span><i class="sw" style="background:var(' + CATV[i] + ')"></i>' + CAT[i][0].toUpperCase() + CAT[i].slice(1) + ' <b>' + pc(x) + '</b></span>').join('') + '</div>';
    $('ol-prob-note').textContent = 'Each grid cell has its own tercile probabilities; these are their averages over the ' +
      fx(s.probability_domain_area_percent) + '% of the area that has probabilities. They are not the probability that the area-total rainfall falls in a category.';
    $('ol-amount').innerHTML = '<div class="amount"><div><span>Forecast mean</span><b>' + fx(s.mean_rainfall_mm) + ' mm</b></div>' +
      '<div><span>' + c.reference + ' average</span><b>' + fx(ref) + ' mm</b></div><div><span>Anomaly</span><b>' + sg(s.mean_anomaly_mm) + ' mm' +
      (ok(anomPct) ? ' (' + sg(anomPct) + '%)' : '') + '</b></div></div><p class="caveat">Amounts cover ' + fx(s.amount_domain_area_percent) +
      '% of the area. They come from the amount-corrected ensemble, calibrated separately from the probabilities, so the two can differ slightly.</p>';
    $('ol-signal').innerHTML = '<p class="big">' + sig.text + '</p><p class="caveat">Largest area-average probability ' + (p.every(ok) ? pc(Math.max(...p)) : '—') +
      ', compared with a one-third reference. The local climatological probabilities (observed tercile frequencies in the training years) are close to, but not exactly, one-third. Based on probabilities only.</p>';
    const A = areaHistory(t), h = A.h.training;
    $('ol-skill-title').textContent = 'Historical skill — ' + A.area;
    $('ol-skill').innerHTML = h ? '<p class="big">' + skillWord(h) + '</p><p class="caveat">Probability skill (RPSS) ' + sg(h.rpss, 3) +
      ' for ' + esc(t.id) + ', cross-validated ' + h.first + '–' + h.last + ' (95% interval ' + sg(h.ci[0], 3) + ' to ' + sg(h.ci[1], 3) + '); better than climatology in ' + h.better + ' of ' + h.years + ' years. ' +
      holmText(h, c.targets.length) + ' <a href="#history">Details</a></p>' +
      (A.fallback ? '<p class="caveat">Historical skill for the selected rainfall domain has not yet been evaluated.</p>' : '')
      : '<p>Not computed for this target.</p>';
    const e = t.forecast[S.view];
    $('ol-map').innerHTML = img(e, 'tercile_outlook', 'Tercile probabilities, ' + t.label + ', ' + viewLabel(S.view) + '. Open the map viewer below for other products.',
      'Map of ' + t.label + ' tercile probabilities for ' + viewLabel(S.view));
    // targets table
    $('ol-table').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' targets, ' + esc(viewLabel(S.view)) +
      '. Probabilities are average local probabilities.</caption><thead><tr><th scope="col">Target</th><th scope="col">Period</th><th scope="col">Below / near / above</th><th scope="col">Probability coverage</th><th scope="col">Anomaly</th><th scope="col">Verification status</th></tr></thead><tbody>' +
      c.targets.map(x => { const v = (x.forecast[S.view] || {}).summary; return '<tr' + (x.id === S.target ? ' class="current"' : '') + '><td><button type="button" class="linkbtn" data-t="' + x.id + '">' + esc(x.label) + '</button></td><td>' + dt(x.start) + ' – ' + dt(x.end) + '</td><td>' +
        (v ? v.mean_local_probabilities.map(z => pc(z)).join(' / ') : '—') + '</td><td>' + (v ? fx(v.probability_domain_area_percent) + '% of area' : '—') + '</td><td>' + (v ? sg(v.mean_anomaly_mm) + ' mm' : '—') + '</td><td>' + status(x.status) + '</td></tr>'; }).join('') +
      '</tbody></table></div><p class="caveat">Probability coverage is the share of the area with tercile probabilities; averages are over that share only. Cells with very little reference-period rainfall have no terciles.</p>';
    $('ol-meta').innerHTML = '<dl class="meta">' + c.meta.map(r => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') +
      '<dt>Rainfall domain</dt><dd>' + esc(c.definition) + (c.note ? ' ' + esc(c.note) : '') + '</dd></dl>';
  }

  // ---------- maps
  function renderMaps() {
    const c = cyc(), t = tgt();
    $('mp-target').innerHTML = c.targets.map(x => '<option value="' + x.id + '"' + (x.id === S.target ? ' selected' : '') + '>' + esc(x.label) + '</option>').join('');
    const hasV = !!t.verification[S.view];
    $('mp-kind').innerHTML = '<button type="button" data-k="forecast" aria-pressed="' + (S.kind === 'forecast') + '">Forecast</button>' +
      '<button type="button" data-k="verification" aria-pressed="' + (S.kind === 'verification') + '">Verification' + (hasV ? '' : ' (not available)') + '</button>';
    const e = S.kind === 'forecast' ? t.forecast[S.view] : t.verification[S.view];
    const prods = S.kind === 'forecast' ? PRODUCTS : (e ? e.images : []);
    if (prods.length && !prods.some(p => p[0] === S.product)) S.product = prods[0][0];
    const cmp = S.product === 'verification_comparison' || S.product === 'verification_comparison_error';
    $('mp-tabs').innerHTML = prods.filter(p => p[0] !== 'verification_comparison_error').map(p => '<button type="button" class="tab" data-p="' + p[0] + '" aria-pressed="' +
      (p[0] === S.product || (cmp && p[0] === 'verification_comparison')) + '">' + esc(p[1]) + '</button>').join('');
    $('mp-toggle').innerHTML = cmp && prods.some(p => p[0] === 'verification_comparison_error')
      ? '<label class="check"><input type="checkbox" id="mp-error"' + (S.product === 'verification_comparison_error' ? ' checked' : '') + '> Show error map (forecast minus observed)</label>' : '';
    const fig = $('mp-figure');
    fig.classList.toggle('wide', S.kind === 'verification' && (S.product === 'verification_maps' || cmp));
    $('mp-actions').hidden = !e;
    if (!e) {
      fig.innerHTML = '<div class="unavailable" role="status"><p><strong>' + esc(t.label) + ' ' + (S.kind === 'verification' ? 'verification' : 'forecast') + ' is unavailable.</strong> ' + esc(t.status.text) + '.</p>' +
        (S.kind === 'verification' ? '<button type="button" data-k="forecast">View the ' + esc(t.label) + ' forecast</button>' : '') + '</div>';
      $('mp-help').innerHTML = '<p>Verification maps appear once the target period is complete and its CHIRPS observations have been processed.</p>';
      return;
    }
    const pname = prods.find(p => p[0] === S.product)[1];
    const cap = t.label + ' · ' + viewLabel(S.view) + ' · ' + pname + ' · ' + c.init + ' initialization';
    fig.innerHTML = img(e, S.product, cap, (S.kind === 'forecast' ? 'Forecast map: ' : 'Verification map: ') + cap);
    const src = e.folder + '/' + S.product + '.png';
    const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    $('mp-open').href = src;
    $('mp-download').href = src;
    $('mp-open').textContent = cmp ? 'Open full-size comparison' : 'Open full-size';
    $('mp-download').textContent = cmp ? 'Download comparison figure' : 'Download PNG';
    $('mp-download').setAttribute('download', ['ethiopia-rainfall', slug(t.label), slug(c.init) + '-init', slug(viewLabel(S.view)), slug(pname)].join('_') + '.png');
    $('mp-help').innerHTML = (HELP[S.product] || '') + '<p class="caveat">Reference period: CHIRPS ' + c.reference + '.</p>';
  }

  // ---------- verification
  function chart(rows) {
    const W = 640, H = 250, L = 46, R = 10, T = 18, B = 34;
    const vals = rows.flatMap(r => [r.f, r.o]), mx = Math.max(5, ...vals.map(Math.abs));
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200].find(s => mx / s <= 4) || 500, top = Math.ceil(Math.max(0, ...vals) / step) * step, bot = Math.floor(Math.min(0, ...vals) / step) * step;
    const y = v => T + (top - v) / (top - bot || 1) * (H - T - B);
    const gw = (W - L - R) / rows.length, bw = Math.min(46, gw / 3.2);
    let g = '';
    for (let v = bot; v <= top + 1e-9; v += step) g += '<line class="axis" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + sg(v).replace('+0', '0') + '</text>';
    g += '<line class="zero" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
    rows.forEach((r, i) => {
      const cx = L + gw * (i + .5);
      [[r.f, 'var(--fc)', 'Forecast', -1], [r.o, 'var(--obs)', 'Observed', 1]].forEach(([v, col, name, side]) => {
        const x = cx + (side < 0 ? -bw - 1 : 1), y0 = y(Math.max(v, 0)), h = Math.max(1, Math.abs(y(v) - y(0)));
        const rad = Math.min(4, h / 2), up = v >= 0;
        const d = up ? 'M' + x + ',' + (y0 + h) + 'V' + (y0 + rad) + 'q0,-' + rad + ' ' + rad + ',-' + rad + 'H' + (x + bw - rad) + 'q' + rad + ',0 ' + rad + ',' + rad + 'V' + (y0 + h) + 'Z'
          : 'M' + x + ',' + y0 + 'V' + (y0 + h - rad) + 'q0,' + rad + ' ' + rad + ',' + rad + 'H' + (x + bw - rad) + 'q' + rad + ',0 ' + rad + ',-' + rad + 'V' + y0 + 'Z';
        g += '<path d="' + d + '" fill="' + col + '"><title>' + esc(r.label) + ' ' + name.toLowerCase() + ' anomaly: ' + sg(v, 1) + ' mm</title></path>';
        g += '<text class="val" x="' + (x + bw / 2) + '" y="' + (up ? y(v) - 5 : y(v) + 14) + '" text-anchor="middle">' + sg(v) + '</text>';
      });
      g += '<text x="' + cx + '" y="' + (H - 10) + '" text-anchor="middle">' + esc(r.label) + '</text>';
    });
    return '<div class="legend"><span><i class="sw" style="background:var(--fc)"></i>Forecast anomaly</span><span><i class="sw" style="background:var(--obs)"></i>Observed anomaly</span></div>' +
      '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Forecast versus observed rainfall anomaly (mm): ' +
      esc(rows.map(r => r.label + ' forecast ' + sg(r.f) + ', observed ' + sg(r.o)).join('; ')) + '">' + g + '</svg>';
  }
  function narrative(t, s) {
    const ref = s.observed_mean_mm - s.observed_mean_anomaly_mm, o = s.observed_mean_anomaly_mm, f = s.forecast_mean_anomaly_mm;
    const obsCat = s.observed_category_area_fractions, k = obsCat.indexOf(Math.max(...obsCat));
    const fp = s.shared_mean_probabilities, fk = fp.indexOf(Math.max(...fp));
    const pb = s.probability.shared_blend, ac = s.amount.corrected;
    const happened = ['Rainfall was <strong>' + (o >= 0 ? 'wetter' : 'drier') + '</strong> than the reference average by ' + fx(Math.abs(o)) + ' mm' + (ref > 0 ? ' (' + sg(100 * o / ref) + '%)' : '') + ', averaged over the assessed area.',
      pc(obsCat[k]) + ' of the assessed area fell in the <strong>' + CAT[k] + '</strong> tercile.'];
    const got = [], miss = [];
    const small = Math.max(2, 0.03 * Math.abs(ref));            // anomalies below this are "near average"
    const word = o >= 0 ? 'surplus' : 'deficit', cond = o >= 0 ? 'wet' : 'dry';
    const bias = ac.bias_mm, big = x => '<strong>' + x + '</strong>';
    // The signed rainfall error is always reported; larger discrepancies are emphasised.
    const err = 'Forecast rainfall was ' + fx(Math.abs(bias), 1) + ' mm ' + (bias >= 0 ? 'higher' : 'lower') + ' than observed, averaged over the assessed area.';
    const errBig = Math.abs(bias) >= Math.max(5, 0.1 * Math.abs(ref));
    if (Math.abs(o) < small) {
      got.push('Observed rainfall was close to average (' + sg(o) + ' mm); the forecast anomaly was ' + sg(f) + ' mm.');
      miss.push(errBig ? big(err) : err);
    } else if (Math.abs(f) < small) {
      miss.push('The forecast mean was close to average (' + sg(f) + ' mm), so it gave little indication of the observed ' + cond + ' anomaly (' + sg(o) + ' mm).');
      miss.push(errBig ? big(err) : err);
    } else if (Math.sign(f) === Math.sign(o)) {
      got.push('The forecast captured the ' + cond + ' conditions (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).');
      const r = Math.abs(f) / Math.abs(o), off = Math.round(100 * Math.abs(1 - r));
      const size = r < 1 ? 'It underestimated the rainfall ' + word + ' by about ' + off + '%.' : 'It overestimated the rainfall ' + word + ' by about ' + off + '%.';
      const line = err + ' ' + (off >= 10 ? size : 'The size of the anomaly was close to the observed one.');
      miss.push(off >= 30 || errBig ? big(line) : line);
    } else {
      miss.push(big('The forecast anomaly had the wrong sign (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).'));
      miss.push(err);
    }
    if (fk === k && fp[fk] - 1 / 3 >= 0.02) got.push('The highest average probability (' + pc(fp[fk]) + ') was on the observed ' + CAT[k] + ' category.');
    else if (fp[fk] - 1 / 3 >= 0.02) miss.push('Probabilities favoured ' + CAT[fk] + ' (' + pc(fp[fk]) + ') while most of the area was ' + CAT[k] + '.');
    else miss.push('Probabilities stayed close to climatology (largest ' + pc(fp[fk]) + ').');
    (pb.rpss > 0 ? got : miss).push('Probabilities scored ' + (pb.rpss > 0 ? 'better' : 'worse') + ' than climatology (RPSS ' + sg(pb.rpss, 3) + ').');
    (ac.crpss > 0 ? got : miss).push('Rainfall amounts scored ' + (ac.crpss > 0 ? 'better' : 'worse') + ' than climatology (CRPSS ' + sg(ac.crpss, 3) + ').');
    const li = a => a.length ? '<ul>' + a.map(x => '<li>' + x + '</li>').join('') + '</ul>' : '<p class="caveat">None of the checked aspects (sign of the anomaly, leading category, scores against climatology).</p>';
    const raw = (s.probability.raw_observed_thresholds || {}).rpss;
    return '<div class="box vcard"><h3>' + esc(t.label) + '</h3><div class="qa"><div><h4>What happened?</h4>' + li(happened) + '</div><div><h4>What did the forecast capture?</h4>' + li(got) +
      '</div><div><h4>What did it miss?</h4>' + li(miss) + '</div></div><div class="metrics">' +
      '<div class="metric"><span>Probability skill (RPSS)</span><b>' + rpssText(pb.rpss) + '</b></div>' +
      '<div class="metric"><span>Rainfall amount skill (CRPSS)</span><b>' + rpssText(ac.crpss) + '</b></div>' +
      '<div class="metric"><span>Average rainfall error (bias, positive = too wet)</span><b>' + sg(ac.bias_mm, 1) + ' mm</b></div>' +
      '<div class="metric"><span>Observed category distribution (of the assessed area)</span><b>' + obsCat.map(x => pc(x)).join(' / ') + '</b> <span>below / near / above</span></div>' +
      '<div class="metric"><span>Assessed area (share of the selected area)</span><b>' + fx(s.probability_domain_area_percent) + '% probabilities · ' + fx(s.amount_domain_area_percent) + '% amounts</b></div>' +
      (ok(raw) ? '<div class="metric"><span>Raw benchmark (uncorrected model) RPSS</span><b>' + sg(raw, 3) + '</b></div>' : '') +
      '</div></div>';
  }
  function renderVerification() {
    const c = cyc(), done = c.targets.filter(t => t.verification[S.view]);
    let h = '';
    if (!done.length) h += '<p class="notice">No target of ' + esc(c.label) + ' has been verified yet.</p>';
    else {
      const ordered = [...done.filter(t => t.kind === 'month'), ...done.filter(t => t.kind === 'season')];
      const rows = ordered.map(t => ({label: t.label, f: t.verification[S.view].summary.forecast_mean_anomaly_mm, o: t.verification[S.view].summary.observed_mean_anomaly_mm}));
      h += '<div class="box"><h3>Forecast vs observed rainfall anomaly, ' + esc(viewLabel(S.view)) + ' (mm)</h3>' + chart(rows) +
        '<p class="caveat">Area-mean anomalies against the ' + c.reference + ' CHIRPS average. Probability skill (RPSS) refers to the blended probabilities; rainfall amount skill (CRPSS) and bias to the amount-corrected ensemble. Skill scores are decimals: +0.193 means a 19.3% lower score than climatology.</p></div>';
      h += ordered.map(t => narrative(t, t.verification[S.view].summary)).join('');
    }
    const pending = c.targets.filter(t => !t.verification[S.view]);
    if (pending.length) h += '<div class="box"><h3>Not yet verified</h3><ul class="dl">' + pending.map(t => '<li><strong>' + esc(t.label) + '</strong> ' + status(t.status) + '</li>').join('') + '</ul></div>';
    $('vf-body').innerHTML = h;
  }

  // ---------- history
  function renderHistory() {
    const c = cyc();
    const cell = (r, main = true) => r ? '<' + (main ? 'strong' : 'span') + ' class="' + (r.rpss > 0 ? 'pos' : 'neg') + '">' + sg(r.rpss, 3) + '</' + (main ? 'strong' : 'span') + '> <span class="ci">(' + sg(r.ci[0], 3) + ' to ' + sg(r.ci[1], 3) + ')</span>' : '—';
    const yrs = r => r ? r.better + ' of ' + r.years : '—';
    const H = t => areaHistory(t), area = H(c.targets[0]).area;
    const tr = H(c.targets[0]).h.training, op = H(c.targets[0]).h.operational;
    const sig = c.targets.filter(t => (H(t).h.training || {}).holm_p < 0.05).map(t => t.id);
    $('hs-body').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' (' + esc(c.init) + ' initialization), ' + esc(area) + ': probability skill (RPSS) of the final method against climatology, with whole-year 95% intervals' +
      (H(c.targets[0]).fallback ? '. Historical skill for the selected rainfall domain has not yet been evaluated.' : '') + '</caption><thead><tr>' +
      '<th scope="col">Target</th><th scope="col">Cross-validated ' + tr.first + '–' + tr.last + ' (main)</th><th scope="col">Years better</th><th scope="col">p (one target / Holm)</th><th scope="col">In words</th>' +
      '<th scope="col">Exploratory ' + (op ? op.first + '–' + op.last : '') + '</th><th scope="col">Years better</th><th scope="col">Blend weight λ</th></tr></thead><tbody>' +
      c.targets.map(t => { const h = H(t).h; return '<tr' + (t.id === S.target ? ' class="current"' : '') + '><td>' + esc(t.id) + '</td><td>' + cell(h.training) + '</td><td>' + yrs(h.training) + '</td><td>' +
        (h.training ? h.training.p.toFixed(3) + ' / ' + (ok(h.training.holm_p) ? h.training.holm_p.toFixed(3) : '—') : '—') + '</td><td>' + skillWord(h.training) + '</td><td>' + cell(h.operational, false) + '</td><td>' + yrs(h.operational) + '</td><td>' + (ok(t.lambda) ? t.lambda.toFixed(2) : '—') + '</td></tr>'; }).join('') +
      '</tbody></table></div><p class="caveat">RPSS +0.05 means a 5% lower ranked probability score than climatology. Each interval and one-target p-value describes that target alone. Because ' + c.targets.length +
      ' targets are examined, the Holm-adjusted p is the stricter test: ' + (sig.length ? sig.join(', ') + ' remain' + (sig.length === 1 ? 's' : '') + ' significant after adjustment.' : 'no target remains significant after adjustment.') +
      ' Gains are modest and the intervals are wide; an interval that includes zero means the gain is not established. λ is the weight given to climatology in the blend (higher = closer to climatology).</p>';
    const R = c.regions;
    $('hs-regions').innerHTML = !R || !R.rows ? '<p class="caveat">Regional skill has not been computed for this cycle.</p>' :
      '<div class="table-wrap"><table class="compact"><caption>' + esc(c.label) + ': probability skill (RPSS) by rainfall region, cross-validated ' + tr.first + '–' + tr.last + ', with whole-year 95% intervals and years better than climatology</caption><thead><tr><th scope="col">Region</th>' +
      c.targets.map(t => '<th scope="col">' + esc(t.id) + '</th>').join('') + '</tr></thead><tbody>' +
      R.rows.map(([name, v]) => '<tr><td>' + esc(name) + '</td>' + c.targets.map(t => { const r = v[t.id]; return '<td>' + (r ? cell(r, false) + ' <span class="ci">' + r.better + '/' + r.years + ' yrs</span>' : '<span class="ci">too little coverage</span>') + '</td>'; }).join('') + '</tr>').join('') +
      '</tbody></table></div><p class="caveat">Positive values mean lower RPS than climatology. Intervals resample whole years; regions are the fixed 1993–2025 rainfall regimes, and the last row is this cycle\'s rainfall domain. Regional results are noisier than national ones.</p>';
  }

  // ---------- historical verification explorer (data/<cycle>_diagnostics.json, loaded on demand)
  const siteURL = path => new URL(path, window.SITE_BASE || document.baseURI).href;
  const DIAG = {};
  function loadDiag(c) {
    if (!c.diagnostics) return Promise.resolve(null);
    if (!DIAG[c.id]) DIAG[c.id] = fetch(siteURL(c.diagnostics)).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    return DIAG[c.id];
  }
  function yearChart(rows) {
    const W = 640, H = 220, L = 46, R = 8, T = 16, B = 30, ys = rows.filter(r => ok(r.rpss));
    const vals = ys.map(r => r.rpss), mx = Math.max(0.05, ...vals.map(Math.abs));
    const step = [0.02, 0.05, 0.1, 0.2, 0.5].find(s => mx / s <= 3) || 1, top = Math.ceil(Math.max(0, ...vals) / step) * step, bot = Math.floor(Math.min(0, ...vals) / step) * step;
    const y = v => T + (top - v) / (top - bot || 1) * (H - T - B), gw = (W - L - R) / rows.length, bw = Math.max(3, gw - 3);
    const hi = vals.indexOf(Math.max(...vals)), lo = vals.indexOf(Math.min(...vals));
    let g = '';
    for (let v = bot; v <= top + 1e-9; v += step) g += '<line class="axis" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + sg(v, 2) + '</text>';
    g += '<line class="zero" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
    ys.forEach((r, i) => {
      const x = L + gw * rows.indexOf(r) + 1.5, v = r.rpss, up = v >= 0, top0 = y(Math.max(v, 0)), h = Math.max(1, Math.abs(y(v) - y(0)));
      g += '<rect x="' + x + '" y="' + top0 + '" width="' + bw + '" height="' + h + '" rx="2" fill="var(' + (up ? '--fc' : '--neg') + ')"><title>' + r.year + ': RPSS ' + sg(v, 3) +
        ' (forecast RPS ' + r.rps_blend.toFixed(3) + ', climatology ' + r.rps_climatology.toFixed(3) + '; ' + r.cells + ' cells)</title></rect>';
      if (i === hi || i === lo) g += '<text class="val" x="' + (x + bw / 2) + '" y="' + (up ? y(v) - 4 : y(v) + 13) + '" text-anchor="middle">' + r.year + '</text>';
      if (r.year % 4 === 1) g += '<text x="' + (x + bw / 2) + '" y="' + (H - 10) + '" text-anchor="middle">' + r.year + '</text>';
    });
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Probability skill by year: ' + esc(ys.map(r => r.year + ' ' + sg(r.rpss, 3)).join(', ')) + '">' + g + '</svg>';
  }
  function reliabilityChart(rel, minCount) {
    const S0 = 300, M = 40, P = S0 - M - 10, x = v => M + v * P, y = v => 10 + (1 - v) * P;
    let g = '<rect x="' + M + '" y="10" width="' + P + '" height="' + P + '" fill="none" class="axis" stroke="var(--line)"/>';
    for (let v = 0; v <= 1.0001; v += 0.2) g += '<text x="' + x(v) + '" y="' + (S0 - 14) + '" text-anchor="middle">' + v.toFixed(1) + '</text><text x="' + (M - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + v.toFixed(1) + '</text>';
    g += '<line x1="' + x(0) + '" y1="' + y(0) + '" x2="' + x(1) + '" y2="' + y(1) + '" stroke="var(--ink2)" stroke-dasharray="4 4"/>';
    // Bins with few cell-years are shown as open points and not joined: their observed frequency is unstable.
    rel.forEach((rows, k) => {
      const pts = rows.filter(r => r.count >= minCount).map(r => x(r.forecast).toFixed(1) + ',' + y(r.observed).toFixed(1)).join(' ');
      g += '<polyline points="' + pts + '" fill="none" stroke="var(' + CATV[k] + ')" stroke-width="2"/>';
      rows.forEach(r => { const full = r.count >= minCount;
        g += '<circle cx="' + x(r.forecast) + '" cy="' + y(r.observed) + '" r="' + (full ? 4.5 : 3.5) + '" fill="' + (full ? 'var(' + CATV[k] + ')' : 'var(--surface)') +
          '" stroke="' + (full ? 'var(--surface)' : 'var(' + CATV[k] + ')') + '" stroke-width="' + (full ? 2 : 1.5) + '"><title>' + CAT[k] + ': forecast ' + pc(r.forecast) + ', observed ' + pc(r.observed) + ' (' + r.count + ' cell-years' + (full ? '' : ', too few to judge') + ')</title></circle>'; });
    });
    g += '<text x="' + (M + P / 2) + '" y="' + (S0) + '" text-anchor="middle">Forecast probability</text>';
    return '<svg class="chart rel" viewBox="0 0 ' + S0 + ' ' + (S0 + 6) + '" role="img" aria-label="Reliability diagram: observed frequency against forecast probability for each tercile">' + g + '</svg>';
  }
  function renderDiag() {
    const c = cyc(), t = tgt();
    $('dg-target').innerHTML = c.targets.map(x => '<option value="' + x.id + '"' + (x.id === S.target ? ' selected' : '') + '>' + esc(x.label) + '</option>').join('');
    $('dg-period').innerHTML = [['training', 'Cross-validated'], ['operational', 'Exploratory']].map(([k, l]) => '<button type="button" data-period="' + k + '" aria-pressed="' + (S.period === k) + '">' + l + '</button>').join('');
    const body = $('dg-body');
    if (!c.diagnostics) { body.innerHTML = '<p class="notice">Historical diagnostics have not been generated for this cycle (run scripts/historical_diagnostics.py).</p>'; return; }
    body.innerHTML = '<p class="caveat">Loading diagnostics…</p>';
    const want = [c.id, S.target, S.view, S.period].join('|');
    loadDiag(c).then(D2 => {
      if ([cyc().id, S.target, S.view, S.period].join('|') !== want) return;     // selection changed meanwhile
      const area = D2.areas.includes(S.view) ? S.view : 'all_ethiopia';
      const d = ((D2.targets[t.id] || {})[S.period] || {})[area];
      if (!d) { body.innerHTML = '<p class="notice">No ' + (S.period === 'training' ? 'cross-validated' : 'exploratory') + ' diagnostics for ' + esc(t.label) + ' in this area.</p>'; return; }
      const better = d.per_year.filter(r => r.rpss > 0).length;
      const worst = d.per_year.filter(r => ok(r.rpss)).sort((a, b) => a.rpss - b.rpss).slice(0, 3);
      const head = '<dl class="meta"><dt>Evaluation</dt><dd>' + (S.period === 'training' ? 'Cross-validated (nested leave-one-year-out), ' : 'Exploratory: parameters fitted on 1993–2016 applied to later years, which were seen during method selection, ') + d.first + '–' + d.last + '</dd>' +
        '<dt>Benchmark</dt><dd>Climatology: observed tercile frequencies of the training years (about one-third each)</dd>' +
        '<dt>Area</dt><dd>' + esc(area === S.view ? viewLabel(S.view) : 'All Ethiopia (the selected domain has no diagnostics)') + '; probabilities on ' + pc(d.coverage) + ' of it on average</dd>' +
        '<dt>Sample</dt><dd>' + d.years + ' years, ' + d.cell_years.toLocaleString('en') + ' cell-years. Cells within a year are spatially correlated, so the independent sample is closer to one value per year.</dd></dl>';
      const bs = d.brier, cats = [0, 1, 2];
      const brier = '<div class="table-wrap"><table class="compact"><caption>Category Brier scores (lower is better) and Brier skill against climatology</caption><thead><tr><th scope="col">Category</th><th scope="col">Forecast</th><th scope="col">Climatology</th><th scope="col">Brier skill</th></tr></thead><tbody>' +
        cats.map(k => '<tr><td><i class="sw" style="background:var(' + CATV[k] + ')"></i>' + CAT[k] + '</td><td>' + bs.blend[k].toFixed(4) + '</td><td>' + bs.climatology[k].toFixed(4) + '</td><td class="' + (bs.bss[k] > 0 ? 'pos' : 'neg') + '">' + sg(bs.bss[k], 3) + '</td></tr>').join('') + '</tbody></table></div>';
      const hist = '<div class="hbars">' + d.histogram.map(h => '<div class="hbar"><span>' + esc(h.label) + '</span><div><i style="width:' + (100 * h.share).toFixed(1) + '%"></i></div><b>' + pc(h.share) + '</b></div>').join('') + '</div>';
      const relTable = '<details><summary>Reliability table (forecast bins, observed frequency, counts)</summary><div class="table-wrap"><table class="compact"><thead><tr><th scope="col">Category</th><th scope="col">Bin</th><th scope="col">Mean forecast</th><th scope="col">Observed frequency</th><th scope="col">Cell-years</th></tr></thead><tbody>' +
        d.reliability.flatMap((rows, k) => rows.map(r => '<tr><td>' + CAT[k] + '</td><td>' + pc(r.bin[0]) + '–' + pc(r.bin[1]) + '</td><td>' + pc(r.forecast) + '</td><td>' + pc(r.observed) + '</td><td>' + r.count.toLocaleString('en') + '</td></tr>')).join('') + '</tbody></table></div></details>';
      const am = ((D2.amount || {})[t.id] || {})[area];
      const amount = am ? '<div class="table-wrap"><table class="compact"><caption>Rainfall amounts, ' + esc(am.period) + '</caption><tbody>' +
          '<tr><td>Rainfall amount skill (CRPSS)</td><td>' + sg(am.crpss, 3) + '</td></tr><tr><td>CRPS, corrected / climatology</td><td>' + am.corrected_crps_mm.toFixed(1) + ' / ' + am.climatology_crps_mm.toFixed(1) + ' mm</td></tr>' +
          '<tr><td>Average rainfall error, corrected (raw model)</td><td>' + sg(am.corrected_bias_mm, 1) + ' mm (' + sg(am.raw_bias_mm, 1) + ' mm)</td></tr><tr><td>RMSE, corrected / climatology</td><td>' + am.corrected_rmse_mm.toFixed(1) + ' / ' + am.climatology_rmse_mm.toFixed(1) + ' mm</td></tr></tbody></table></div>'
        : '<p class="caveat">Historical rainfall-amount diagnostics (CRPS, CRPSS and amount errors) have not been generated for ' + esc(t.label) + ' in this area and period; this needs a separate cross-validated amount evaluation. Single-season amount scores are in the Verification section.</p>';
      body.innerHTML = head +
        '<div class="box"><h4>Performance by year</h4><p class="caveat">Probability skill (RPSS) of each year; better than climatology in ' + better + ' of ' + d.years + ' years. Weakest years: ' + worst.map(r => r.year + ' (' + sg(r.rpss, 3) + ')').join(', ') + '.</p>' +
        '<div class="legend"><span><i class="sw" style="background:var(--fc)"></i>Better than climatology</span><span><i class="sw" style="background:var(--neg)"></i>Worse</span></div>' + yearChart(d.per_year) + '</div>' +
        '<div class="grid2"><div class="box"><h4>Reliability</h4><div class="legend">' + cats.map(k => '<span><i class="sw" style="background:var(' + CATV[k] + ')"></i>' + CAT[k] + '</span>').join('') + '</div>' + reliabilityChart(d.reliability, Math.max(50, Math.round(0.005 * d.cell_years))) +
        '<p class="caveat">Points on the dashed diagonal are reliable: events forecast with probability p happen p of the time. Points flatter than the diagonal mean over-confident probabilities. Open points have fewer than ' + Math.max(50, Math.round(0.005 * d.cell_years)) + ' cell-years (0.5% of the sample, at least 50) and are not joined. Hover a point for its count.</p>' + relTable + '</div>' +
        '<div class="box"><h4>How strong are the signals?</h4><p class="caveat">Share of cell-years by the leading tercile probability.</p>' + hist + brier + '</div></div>' +
        '<div class="box"><h4>Rainfall amounts</h4>' + amount + '</div>';
    }).catch(() => { body.innerHTML = '<p class="notice">The diagnostics file could not be loaded. Try reloading the page.</p>'; });
  }

  // ---------- comparison with official outlooks (data/<cycle>_comparison.json; validated content only)
  const CMP = {};
  const METRIC = {display_official_probabilities: 'Official probabilities shown', favoured_category_relationship: 'Favoured-category relationship',
    zone_mean_probability: 'Platform mean over the official zone', same_event_probability_difference: 'Probability difference for the same event',
    mapped_category_agreement: 'Mapped category agreement', rainfall_anomaly_difference: 'Rainfall anomaly difference', forecast_accuracy: 'Which forecast is more accurate'};
  const REASON = {transcription_awaiting_review: 'transcribed values await review against the published figure',
    transcription_and_anchor_awaiting_review: 'transcribed values and locations await review', digitization_awaiting_review: 'digitized map awaits review',
    zone_geometry_requires_alignment: 'the zone boundary is not published with the figure', official_reference_period_unknown: 'the official reference period is not stated',
    target_window_mismatch: 'the target periods differ', official_publishes_only_favoured_category_interval: 'only the favoured category and its interval are published',
    official_amount_anomaly_not_found_in_checked_products: 'no official rainfall-amount anomaly product was found in the checked products'};
  const plainReason = r => !r ? '' : r.split(';').map(x => x.trim()).map(x => x.startsWith('out_of_scope') ? 'needs observations and a separate verification design (see Verification)' : (REASON[x] || x.replace(/_/g, ' '))).join('; ');
  function renderComparison() {
    const c = cyc(), body = $('cmp-body'), head = $('official');
    const season = c.targets.find(t => t.kind === 'season') || c.targets[0];
    head.textContent = 'Official outlook comparison — ' + season.label;
    if (!c.comparison) { body.innerHTML = '<p class="caveat">No comparison with official outlooks is configured for this cycle.</p>'; return; }
    body.innerHTML = '<p class="caveat">Loading…</p>';
    if (!CMP[c.id]) CMP[c.id] = fetch(siteURL(c.comparison)).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const want = [c.id, S.target, S.view].join('|');
    CMP[c.id].then(X => {
      if ([cyc().id, S.target, S.view].join('|') !== want) return;
      const ev = X.evidence || {};
      const areaKey = S.view === 'all_ethiopia' ? 'all_ethiopia' : 'season_domain';
      const areaName = viewLabel(S.view), otherName = areaKey === 'all_ethiopia' ? 'Rainfall-domain context' : 'National context';
      const href = p => esc(siteURL(p));
      // Evidence maps follow the finding's own scope (a national-context finding links the national map).
      const scopeView = key => key === 'season_domain' ? c.domain_view : key === 'all_ethiopia' ? 'all_ethiopia' : S.view;
      const links = (ids, sid, view = S.view) => {
        const seen = new Set(), out = [];
        [...ids, ...(sid ? [sid + '_record'] : [])].forEach(i => ((ev[i] || {}).links || []).forEach(l => {
          const map = l.href.includes('{view}'), url = l.href.replace('{view}', view);
          const label = map ? l.label + ' (' + (view === 'all_ethiopia' ? 'All Ethiopia' : 'domain') + ')' : l.label;
          if (!seen.has(url)) { seen.add(url); out.push('<a href="' + href(url) + '" target="_blank" rel="noopener">' + esc(label) + '</a>'); }
        }));
        return out.length ? '<span class="evlinks">Evidence: ' + out.join(' · ') + '</span>' : '';
      };
      const overlap = x => !ok(x) ? '' : x <= 0 ? 'Outside the domain (national context)' : x >= 1 ? 'Entire sample in the domain' :
        'Partly overlaps the domain — ' + (100 * x).toFixed(0) + '% of sample cells';
      const item = i => '<li><strong>' + esc(i.title) + '.</strong> ' + esc(i.text) + links(i.evidence_ids, i.source_id, scopeView(i.area_key)) + '</li>';
      let h = '<p class="scope"><strong>Season:</strong> ' + esc(season.label) + ' (' + dt(season.start) + ' – ' + dt(season.end) + ') · <strong>Area:</strong> ' + esc(areaName) + '</p>';
      if (S.target !== season.id) h += '<p class="notice">This comparison covers the full ' + esc(season.id) + ' season. A separate ' + esc(tgt().label) + ' comparison is not available.</p>';
      if (X.stale.length) h += '<p class="notice"><strong>Comparison withheld.</strong> The saved comparison no longer matches the current ' + esc(X.stale.join(', ')) +
        '. Its findings are not shown until it is regenerated: <code>' + esc(X.rerun) + '</code></p>';
      h += '<p class="caveat">Official outlooks from ICPAC and the Ethiopian Meteorology Institute (EMI), compared with this platform\'s forecast. The comparison describes agreement between outlooks, not which is more accurate, and uses only values a person has checked against the published figures.</p>';
      // 1. key findings for the selected area; the rest as context
      const mine = X.summary.filter(i => i.area_key === areaKey || i.area_key === 'any');
      const ctx = X.summary.filter(i => i.area_key !== areaKey && i.area_key !== 'any');
      if (mine.length) h += '<div class="box"><h3>Key findings — ' + esc(areaName) + '</h3><ul class="findings">' + mine.map(item).join('') + '</ul></div>';
      // 2. maps
      const cap = {icpac: 'Platform ' + season.label + ' vs ICPAC (left to right: platform favoured category, ICPAC favoured category, agreement). Periods differ; see the findings.',
                   emi: 'Platform ' + season.label + ' favoured category with EMI zone values at their arrow tips; boxes show the sampled ±0.5° neighbourhoods.'};
      // The EMI comparison map is shown next to EMI's own official figure (the zones as EMI published them).
      const emiFig = X.sources.filter(s => s.provider === 'EMI').flatMap(s => s.figures)[0];
      const fig = (file, alt, caption) => '<figure><a href="' + href(file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(file) +
        '" alt="' + esc(alt) + '"></a><figcaption>' + esc(caption) + '</figcaption></figure>';
      // Right-hand panel: the EMI zones as regions (reviewed digitization) or, until then, EMI's own figure.
      const regionMap = X.maps.find(m => m.name.includes('regions'));
      const layer = (X.reference_layers || [])[0];
      const right = regionMap
        ? fig(regionMap.file, 'EMI homogeneous rainfall regions with the Bega 2026/27 values', 'EMI zones as homogeneous rainfall regions, with the values EMI printed for Bega 2026/27. Regions redrawn after ' +
              (layer ? layer.citation.split(' (figure')[0] : 'Korecha and Sorteberg (2013)') + '; region layout as published in 2013. EMI\'s own figure is under Sources.')
        : (emiFig ? fig(emiFig.file, 'EMI official figure', 'EMI official figure (as published): ' + emiFig.caption + '. EMI publishes zone values with arrows; no zone boundaries are given.') : '');
      if (X.maps.length) h += X.maps.filter(m => !m.name.includes('regions')).map(m => m.name.includes('anchors')
        ? '<div class="cmp-pair">' + fig(m.file, 'Platform map with EMI zone values', cap.emi) + right + '</div>'
        : '<figure class="map-figure wide"><a href="' + href(m.file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(m.file) +
          '" alt="Comparison map"></a><figcaption>' + esc(cap.icpac) + '</figcaption></figure>').join('');
      // 3. compact tables
      const agree = X.metrics.filter(m => m.metric === 'mapped_category_agreement' && m.value);
      if (agree.length) h += '<div class="table-wrap"><table class="compact"><caption>ICPAC category agreement (only where both outlooks show a favoured category)</caption><thead><tr><th scope="col">Area</th><th scope="col">Compared area (share of the analysed area)</th><th scope="col">Category agreement within it</th><th scope="col">Opposite categories within it</th></tr></thead><tbody>' +
        agree.map(m => { const v = m.value, here = (areaKey === 'all_ethiopia') === (m.where === 'All Ethiopia');
          return '<tr' + (here ? ' class="current"' : '') + '><td>' + esc(m.where) + (here ? '' : ' <span class="caveat">(' + otherName.toLowerCase() + ')</span>') + '</td><td>' + share(v.area_share_both_favoured) + '</td><td>' +
            share1(v.agreement_share_where_both_favoured) + '</td><td>' + share1(v.opposing_share_where_both_favoured) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (X.emi_table.length) {
        const rows = areaKey === 'all_ethiopia' ? X.emi_table : [...X.emi_table].sort((a, b) => b.domain_share - a.domain_share);
        const hasZone = rows.some(r => r.zone_mean);
        h += '<div class="table-wrap"><table class="compact"><caption>EMI zones: printed values and the platform (below / near / above)</caption><thead><tr><th scope="col">Location</th><th scope="col">Official</th>' +
          (hasZone ? '<th scope="col">Platform over the whole zone</th>' : '') + '<th scope="col">Platform near the arrow (±0.5°)</th><th scope="col">Relationship near the arrow</th><th scope="col">Evidence</th></tr></thead><tbody>' +
          rows.map(r => { const mapView = areaKey === 'season_domain' && r.domain_share >= 1 ? c.domain_view : 'all_ethiopia';
            const zoneCell = hasZone ? '<td>' + (r.zone_mean ? '<span class="nowrap">' + esc(r.zone_mean) + '</span><br><span class="caveat">' + esc(r.zone_relationship) +
              (r.zone_name ? ' · ' + esc(r.zone_name) + ' region' : '') + (areaKey === 'season_domain' && ok(r.zone_domain_share) && r.zone_domain_share < 1 ? ' · ' + (100 * r.zone_domain_share).toFixed(0) + '% of the zone in the domain' : '') + '</span>' : '—') + '</td>' : '';
            return '<tr' + (r.relationship_code === 'opposing_favoured_categories' ? ' class="current"' : '') + '><td>Zone ' + esc(r.zone) +
              (areaKey === 'all_ethiopia' ? '' : '<br><span class="caveat">' + overlap(r.domain_share) + ' (arrow sample)</span>') + '</td><td class="nowrap">' + esc(r.official) + '</td>' + zoneCell + '<td class="nowrap">' + esc(r.platform) +
              '</td><td>' + esc(r.relationship) + (r.stable === false ? ' <span class="caveat">(sensitive to location)</span>' : '') + '</td><td>' + links(r.evidence_ids, null, mapView).replace('Evidence: ', '') + '</td></tr>'; }).join('') +
          '</tbody></table></div><p class="caveat">Platform values are area means of local probabilities. ' + (hasZone ? '"Whole zone" uses EMI\'s homogeneous rainfall regions as published in 2013 (assumed unchanged for 2026/27); ' : '') + '"near the arrow" uses the ±0.5° sample around each arrow tip, also where it only partly overlaps the domain. Percentages are rounded to add up to 100%.</p>';
      }
      if ((X.icpac_table || []).length) {
        const samples = X.icpac_table.filter(r => r.kind === 'sample'), arows = X.icpac_table.filter(r => r.kind === 'area');
        const ordered = [...(areaKey === 'all_ethiopia' ? samples : [...samples].sort((a, b) => b.domain_share - a.domain_share)),
                         ...arows.filter(r => r.area_key === areaKey), ...arows.filter(r => r.area_key !== areaKey)];
        h += '<div class="table-wrap"><table class="compact"><caption>ICPAC: printed favoured category and interval vs the platform (below / near / above)</caption><thead><tr><th scope="col">Location</th><th scope="col">ICPAC (favoured category, printed interval)</th><th scope="col">Platform</th><th scope="col">Relationship</th><th scope="col">Evidence</th></tr></thead><tbody>' +
          ordered.map(r => { const mapView = r.kind === 'area' ? (r.area_key === 'season_domain' ? c.domain_view : 'all_ethiopia')
                                             : (areaKey === 'season_domain' && r.domain_share >= 1 ? c.domain_view : 'all_ethiopia');
            const where = r.kind === 'sample' ? (areaKey === 'all_ethiopia' ? '' : '<br><span class="caveat">' + overlap(r.domain_share) + '</span>')
                                              : (r.area_key === areaKey ? '<br><span class="caveat">selected area</span>' : '<br><span class="caveat">' + otherName.toLowerCase() + '</span>');
            return '<tr' + (r.relationship_code === 'opposing_favoured_categories' ? ' class="current"' : '') + '><td>' + esc(r.location) + where + '</td><td>' + esc(r.official) +
              (r.official_note ? '<br><span class="caveat">' + esc(r.official_note) + '</span>' : '') + '</td><td class="nowrap">' + esc(r.platform) + '</td><td>' + esc(r.relationship) +
              '</td><td>' + links(r.evidence_ids, null, mapView).replace('Evidence: ', '') + '</td></tr>'; }).join('') +
          '</tbody></table></div><p class="caveat">ICPAC publishes only the favoured category and its probability interval (the other two categories are not published), for October–December; the platform covers October–January, so the two are compared as tendencies, not as the same event. Sample locations are the EMI arrow-tip boxes; platform values are area means of local probabilities over each sample or area.</p>';
      }
      if (ctx.length) h += '<details><summary>' + otherName + '</summary><ul class="findings">' + ctx.map(item).join('') + '</ul></details>';
      // 4. detailed interpretation
      if (X.paragraphs.length) {
        const order = p => (p.area_key === areaKey ? 0 : p.area_key === 'zone' ? 1 : p.area_key === 'any' ? 3 : 2);
        h += '<details><summary>Detailed interpretation</summary>' + [...X.paragraphs].sort((a, b) => order(a) - order(b)).map(p =>
          '<p>' + (p.area_key !== 'zone' && p.area_key !== 'any' && p.area_key !== areaKey ? '<span class="caveat">' + otherName + ':</span> ' : '') + esc(p.text) + links(p.evidence_ids, null, scopeView(p.area_key === 'zone' ? 'all_ethiopia' : p.area_key)) + '</p>').join('') + '</details>';
      }
      // 5. sources, extraction review and methods
      const st = s => s === 'validated' ? '<span class="status published">Extraction reviewed</span>' : '<span class="status awaiting">Extraction awaiting review</span>';
      const chk = r => '<span class="status ' + ({checked: 'published', new_awaiting_review: 'awaiting', refresh_failed: 'awaiting'}[r.state] || 'not_started') + '">' + esc(r.text) + '</span>';
      h += '<details><summary>Sources, extraction review and methods</summary><div class="grid2">' + X.sources.map(s => {
        const same = s.target_start === X.platform.target_start && s.target_end === X.platform.target_end;
        const rv = s.extraction.review;
        return '<div class="box"><h3>' + esc(s.provider) + ': ' + esc(s.season_label || s.label) + '</h3><p>' + st(s.extraction.status) + ' ' + chk(s.refresh) + '</p>' +
          '<dl class="meta"><dt>Product</dt><dd>' + esc(s.label) + '</dd><dt>Target period</dt><dd>' + dt(s.target_start) + ' – ' + dt(s.target_end) +
          (same ? '' : ' <strong>(differs from this forecast: ' + dt(X.platform.target_start) + ' – ' + dt(X.platform.target_end) + ')</strong>') + '</dd>' +
          '<dt>Issue date</dt><dd>' + esc(s.issue_date || 'not stated by the provider') + '</dd><dt>Reference period</dt><dd>' + esc(s.reference_period || 'not stated') + '</dd>' +
          '<dt>Retrieved</dt><dd>' + esc((s.retrieved_utc || '').slice(0, 10)) + ' · content hash ' + esc((s.sha256 || '').slice(0, 12)) + '</dd>' +
          (rv ? '<dt>Review</dt><dd>' + esc(rv.decision) + ' by ' + esc(rv.reviewer) + ', ' + esc((rv.reviewed_utc || '').slice(0, 10)) + '</dd>' : '') +
          (s.extraction.note ? '<dt>Note</dt><dd>' + esc(s.extraction.note) + '</dd>' : '') +
          '<dt>Source</dt><dd><a href="' + esc(s.page) + '" rel="noopener">product page</a> · <a href="' + esc(s.download) + '" rel="noopener">original file</a></dd></dl>' +
          (s.narrative.length ? '<blockquote class="quote">' + s.narrative.map(n => esc(n.text)).join('<br>') + '<br><span class="caveat">— ' + esc(s.provider) + ', ' + esc(s.narrative[0].locator) + '</span></blockquote>' : '') +
          s.figures.map(f => '<figure><a href="' + href(f.file) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + href(f.file) + '" alt="' + esc(f.caption) + '"></a><figcaption>' + esc(f.caption) + ' (original figure)</figcaption></figure>').join('') + '</div>';
      }).join('') + '</div><div class="table-wrap"><table class="compact"><caption>What is compared, and what is not</caption><thead><tr><th scope="col">Comparison</th><th scope="col">Where</th><th scope="col">Status</th><th scope="col">Why</th></tr></thead><tbody>' +
        X.metrics.map(m => '<tr><td>' + esc(METRIC[m.metric] || m.metric) + '</td><td>' + esc(m.where ? (String(m.where).length < 5 ? 'EMI zone ' + m.where : m.where) : '—') + '</td><td>' +
          esc(m.status.replace(/_/g, ' ')) + '</td><td>' + esc(plainReason(m.reason) || (m.basis || '').replace(/_/g, ' ')) + '</td></tr>').join('') + '</tbody></table></div>' +
        '<ul class="caveat">' + X.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
      body.innerHTML = h;
    }).catch(() => { body.innerHTML = '<p class="notice">The comparison file could not be loaded.</p>'; });
  }

  // ---------- one-click package (files are zipped in the browser)
  function loadZip() {
    if (window.JSZip) return Promise.resolve(window.JSZip);
    const urls = ['https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js', 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js'];
    const tryLoad = i => new Promise((res, rej) => { const sc = document.createElement('script'); sc.src = urls[i];
      sc.onload = () => res(window.JSZip); sc.onerror = () => (i + 1 < urls.length ? tryLoad(i + 1).then(res, rej) : rej(new Error('ZIP library could not be loaded')));
      document.head.appendChild(sc); });
    return tryLoad(0);
  }
  async function downloadPackage() {
    const c = cyc(), btn = $('dl-package'), prog = $('dl-progress');
    btn.disabled = true;
    try {
      const Z = await loadZip(), zip = new Z(), root = 'ethiopia-rainfall_' + c.id + '_package/';
      let n = 0;
      for (const [src, dest] of c.package) {
        prog.textContent = 'Adding file ' + (++n) + ' of ' + c.package.length + '…';
        const r = await fetch(siteURL(src));
        if (!r.ok) throw new Error(src + ' (' + r.status + ')');
        zip.file(root + dest, await r.arrayBuffer());
      }
      prog.textContent = 'Compressing…';
      const blob = await zip.generateAsync({type: 'blob'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'ethiopia-rainfall_' + c.id + '_package.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      prog.textContent = 'Package ready (' + (blob.size / 1e6).toFixed(1) + ' MB, ' + c.package.length + ' files).';
    } catch (err) {
      prog.textContent = 'The package could not be built: ' + err.message + '. The individual files below are still available.';
    } finally { btn.disabled = false; }
  }

  function renderDownloads() {
    const c = cyc();
    $('dl-package').textContent = 'Download package (ZIP): ' + c.label + ', ' + c.package.length + ' files';
    $('dl-body').innerHTML = '<div class="box"><h3>' + esc(c.option) + ' — individual files</h3><ul class="dl">' + c.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(d.note) + '</span></li>').join('') + '</ul></div>' +
      '<details><summary>Other cycles</summary><ul class="dl">' + D.cycles.filter(x => x.id !== c.id).flatMap(x => x.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(x.option) + '</span></li>')).join('') + '</ul></details>';
  }

  // Re-rendering replaces controls; keep keyboard focus on the equivalent control.
  function focusKey() {
    const a = document.activeElement;
    if (!a || a === document.body) return null;
    if (a.id) return '#' + a.id;
    for (const k of ['t', 'k', 'p', 'period']) if (a.dataset && a.dataset[k]) { const box = a.closest('[id]'); return (box ? '#' + box.id + ' ' : '') + '[data-' + k + '="' + a.dataset[k] + '"]'; }
    return null;
  }
  function renderAll() {
    const key = focusKey();
    renderParts();
    if (key) {
      // A control that disappears (e.g. the forecast button in an unavailable-verification message) hands focus to
      // the persistent control with the same action (#mp-kind).
      const el = document.querySelector(key) || document.querySelector('#mp-kind ' + key.replace(/^#[^ ]+ /, ''));
      if (el && el !== document.activeElement) el.focus({preventScroll: true});
    }
  }
  function renderParts() {
    const c = cyc();
    $('cycle').value = c.id;
    $('view').innerHTML = c.views.map(v => '<option value="' + v[0] + '"' + (v[0] === S.view ? ' selected' : '') + '>' + esc(v[1]) + '</option>').join('');
    renderOutlook(); renderMaps(); renderVerification(); renderHistory(); renderDiag(); renderComparison(); renderDownloads(); sync();
  }

  // Anchor offset follows the real height of the sticky header (wrapped controls included).
  const header = document.querySelector('.top');
  const offset = () => { const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.scrollPaddingTop = (sticky ? header.offsetHeight + 12 : 8) + 'px'; };
  if (window.ResizeObserver) new ResizeObserver(offset).observe(header);
  window.addEventListener('resize', offset);
  offset();

  init();
  $('cycle').addEventListener('change', e => { const c = D.cycles.find(x => x.id === e.target.value); S.cycle = c.id; S.target = c.targets[0].id; S.view = c.domain_view; renderAll(); });
  $('view').addEventListener('change', e => { S.view = e.target.value; renderAll(); });
  $('mp-target').addEventListener('change', e => { S.target = e.target.value; renderAll(); });
  $('dg-target').addEventListener('change', e => { S.target = e.target.value; renderAll(); });
  document.addEventListener('change', e => { if (e.target.id === 'mp-error') { S.product = e.target.checked ? 'verification_comparison_error' : 'verification_comparison'; renderAll(); } });
  $('dl-package').addEventListener('click', downloadPackage);
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-t],[data-k],[data-p],[data-period]');
    if (!b) return;
    if (b.dataset.period) S.period = b.dataset.period;
    if (b.dataset.t) S.target = b.dataset.t;
    if (b.dataset.k) S.kind = b.dataset.k;
    if (b.dataset.p) S.product = b.dataset.p;
    renderAll();
  });
  $('mp-copy').addEventListener('click', () => {
    const url = location.href.split('#')[0] + '#maps';
    const done = () => { $('mp-copied').textContent = 'Link copied.'; setTimeout(() => { $('mp-copied').textContent = ''; }, 2500); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => { $('mp-copied').textContent = url; });
    else $('mp-copied').textContent = url;
  });
  renderAll();
})();

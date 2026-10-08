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
  const PRODUCTS = D.products;
  const HELP = {
    tercile_outlook: '<p>Colour shows the <strong>most likely tercile</strong> at each place, shaded by its probability: yellow–red for below normal, cyan for near normal, green for above normal. Terciles split the reference-period rainfall into three equally likely parts, so climatology is about 33% each. Places where no category reaches 40% are left white.</p>',
    rainfall_total_mm: '<p>The <strong>corrected ensemble-mean rainfall</strong> for the target period in mm. It is the average of the bias-corrected members, not a probability.</p>',
    rainfall_anomaly_mm: '<p>The <strong>difference in mm</strong> between the corrected ensemble mean and the reference-period CHIRPS average. Red–orange: drier than average; green: wetter.</p>',
    rainfall_anomaly_percent: '<p>The same anomaly as a <strong>percentage of the reference average</strong>. Hidden where the reference rainfall is below 10 mm, where percentages exaggerate small amounts.</p>',
    verification_maps: '<p>All six panels in one figure (also available separately): observed anomaly, forecast anomaly, forecast minus observed, the observed tercile at each cell, the probability score difference against climatology and the rainfall amount score.</p>',
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
  }
  function sync() {
    const q = new URLSearchParams({cycle: S.cycle, target: S.target, view: S.view, kind: S.kind, product: S.product});
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
    $('mp-tabs').innerHTML = prods.map(p => '<button type="button" class="tab" data-p="' + p[0] + '" aria-pressed="' + (p[0] === S.product) + '">' + esc(p[1]) + '</button>').join('');
    const fig = $('mp-figure');
    fig.classList.toggle('wide', S.kind === 'verification' && S.product === 'verification_maps');
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

  function renderDownloads() {
    const c = cyc();
    $('dl-body').innerHTML = '<div class="box"><h3>' + esc(c.option) + '</h3><ul class="dl">' + c.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(d.note) + '</span></li>').join('') + '</ul></div>' +
      '<details><summary>Other cycles</summary><ul class="dl">' + D.cycles.filter(x => x.id !== c.id).flatMap(x => x.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(x.option) + '</span></li>')).join('') + '</ul></details>';
  }

  // Re-rendering replaces controls; keep keyboard focus on the equivalent control.
  function focusKey() {
    const a = document.activeElement;
    if (!a || a === document.body) return null;
    if (a.id) return '#' + a.id;
    for (const k of ['t', 'k', 'p']) if (a.dataset && a.dataset[k]) { const box = a.closest('[id]'); return (box ? '#' + box.id + ' ' : '') + '[data-' + k + '="' + a.dataset[k] + '"]'; }
    return null;
  }
  function renderAll() {
    const key = focusKey();
    renderParts();
    if (key) { const el = document.querySelector(key); if (el && el !== document.activeElement) el.focus({preventScroll: true}); }
  }
  function renderParts() {
    const c = cyc();
    $('cycle').value = c.id;
    $('view').innerHTML = c.views.map(v => '<option value="' + v[0] + '"' + (v[0] === S.view ? ' selected' : '') + '>' + esc(v[1]) + '</option>').join('');
    renderOutlook(); renderMaps(); renderVerification(); renderHistory(); renderDownloads(); sync();
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
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-t],[data-k],[data-p]');
    if (!b) return;
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

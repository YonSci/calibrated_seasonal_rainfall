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
    tercile_outlook: '<p>Colour shows the <strong>most likely tercile</strong> at each place, shaded by its probability: yellow–red for below normal, cyan for near normal, green for above normal. Terciles split the reference-period rainfall into three equally likely parts, so climatology is 33% each. Places where no category reaches 40% are left white.</p>',
    rainfall_total_mm: '<p>The <strong>corrected ensemble-mean rainfall</strong> for the target period in mm. It is the average of the bias-corrected members, not a probability.</p>',
    rainfall_anomaly_mm: '<p>The <strong>difference in mm</strong> between the corrected ensemble mean and the reference-period CHIRPS average. Red–orange: drier than average; green: wetter.</p>',
    rainfall_anomaly_percent: '<p>The same anomaly as a <strong>percentage of the reference average</strong>. Hidden where the reference rainfall is below 10 mm, where percentages exaggerate small amounts.</p>',
    verification_maps: '<p>Six panels: observed anomaly, forecast anomaly, forecast minus observed, the observed tercile at each cell, the probability score difference against climatology (blue favours the forecast) and the rainfall amount score (lower is better).</p>'
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
  function skillWord(r) { return r <= 0 ? 'No skill over climatology' : r < 0.03 ? 'Slight' : r < 0.10 ? 'Modest' : 'Moderate'; }
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
      ? 'The forecast leans toward <strong>' + CAT[sig.cat] + '</strong> rainfall ' + esc(where) + ': averaged over the area, the local probability of ' + CAT[sig.cat] + ' is <strong>' + pc(p[sig.cat]) + '</strong>, against 33% for climatology.'
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
    $('ol-signal').innerHTML = '<p class="big">' + sig.text + '</p><p class="caveat">Largest area-average probability ' + (p.every(ok) ? pc(Math.max(...p)) : '—') + ' vs 33% climatology. Based on probabilities only.</p>';
    const h = t.history.training, o = t.history.operational;
    $('ol-skill').innerHTML = h ? '<p class="big">' + skillWord(h.rpss) + '</p><p class="caveat">Probability skill (RPSS) ' + sg(h.rpss, 3) +
      ' for ' + esc(t.id) + ', cross-validated ' + h.first + '–' + h.last + ' (95% interval ' + sg(h.ci[0], 3) + ' to ' + sg(h.ci[1], 3) + '); better than climatology in ' + h.better + ' of ' + h.years + ' years. <a href="#history">Details</a></p>'
      : '<p>Not computed for this target.</p>';
    const e = t.forecast[S.view];
    $('ol-map').innerHTML = img(e, 'tercile_outlook', 'Tercile probabilities, ' + t.label + ', ' + viewLabel(S.view) + '. Open the map viewer below for other products.',
      'Map of ' + t.label + ' tercile probabilities for ' + viewLabel(S.view));
    // targets table
    $('ol-table').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' targets, ' + esc(viewLabel(S.view)) +
      '. Probabilities are average local probabilities.</caption><thead><tr><th scope="col">Target</th><th scope="col">Period</th><th scope="col">Below / near / above</th><th scope="col">Anomaly</th><th scope="col">Verification status</th></tr></thead><tbody>' +
      c.targets.map(x => { const v = (x.forecast[S.view] || {}).summary; return '<tr' + (x.id === S.target ? ' class="current"' : '') + '><td><button type="button" class="linkbtn" data-t="' + x.id + '">' + esc(x.label) + '</button></td><td>' + dt(x.start) + ' – ' + dt(x.end) + '</td><td>' +
        (v ? v.mean_local_probabilities.map(z => pc(z)).join(' / ') : '—') + '</td><td>' + (v ? sg(v.mean_anomaly_mm) + ' mm' : '—') + '</td><td>' + status(x.status) + '</td></tr>'; }).join('') + '</tbody></table></div>';
    $('ol-meta').innerHTML = '<dl class="meta">' + c.meta.map(r => '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>').join('') +
      '<dt>Rainfall domain</dt><dd>' + esc(c.definition) + (c.note ? ' ' + esc(c.note) : '') + '</dd></dl>';
  }

  // ---------- maps
  function renderMaps() {
    const c = cyc(), t = tgt();
    $('mp-target').innerHTML = c.targets.map(x => '<option value="' + x.id + '"' + (x.id === S.target ? ' selected' : '') + '>' + esc(x.label) + '</option>').join('');
    const hasV = !!t.verification[S.view];
    if (S.kind === 'verification' && !hasV) S.kind = 'forecast';
    $('mp-kind').innerHTML = '<button type="button" data-k="forecast" aria-pressed="' + (S.kind === 'forecast') + '">Forecast</button>' +
      '<button type="button" data-k="verification" aria-pressed="' + (S.kind === 'verification') + '"' + (hasV ? '' : ' disabled title="' + esc(t.status.text) + '"') + '>Verification</button>';
    const e = S.kind === 'forecast' ? t.forecast[S.view] : t.verification[S.view];
    const prods = S.kind === 'forecast' ? PRODUCTS : [['verification_maps', 'Verification (6 panels)']];
    if (!prods.some(p => p[0] === S.product)) S.product = prods[0][0];
    $('mp-tabs').innerHTML = prods.map(p => '<button type="button" role="tab" class="tab" data-p="' + p[0] + '" aria-selected="' + (p[0] === S.product) + '">' + p[1] + '</button>').join('');
    const fig = $('mp-figure');
    fig.classList.toggle('wide', S.kind === 'verification');
    if (!e) { fig.innerHTML = '<p class="img-error">' + esc(t.status.text) + '</p>'; return; }
    const pname = prods.find(p => p[0] === S.product)[1];
    const cap = t.label + ' · ' + viewLabel(S.view) + ' · ' + pname + ' · ' + c.init + ' initialization';
    fig.innerHTML = img(e, S.product, cap, (S.kind === 'forecast' ? 'Forecast map: ' : 'Verification maps: ') + cap);
    const src = e.folder + '/' + S.product + '.png';
    const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    $('mp-open').href = src;
    $('mp-download').href = src;
    $('mp-download').setAttribute('download', ['ethiopia-rainfall', slug(t.label), slug(c.init) + '-init', slug(viewLabel(S.view)), slug(pname)].join('_') + '.png');
    $('mp-help').innerHTML = HELP[S.product] + (S.kind === 'forecast' ? '<p class="caveat">Reference period: CHIRPS ' + c.reference + '.</p>' : '');
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
    const small = Math.max(2, 0.03 * Math.abs(ref));
    if (Math.abs(f) < small) miss.push('The forecast mean was close to average (' + sg(f) + ' mm), so it gave little indication of the observed ' + (o >= 0 ? 'wet' : 'dry') + ' anomaly.');
    else if (Math.sign(f) === Math.sign(o)) {
      got.push('The forecast anomaly had the right sign (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).');
      if (Math.abs(f) < 0.5 * Math.abs(o)) miss.push('It underestimated the size of the anomaly: ' + sg(f) + ' mm forecast against ' + sg(o) + ' mm observed.');
      else if (Math.abs(f) > 2 * Math.abs(o)) miss.push('It overestimated the size of the anomaly: ' + sg(f) + ' mm forecast against ' + sg(o) + ' mm observed.');
    } else miss.push('The forecast anomaly had the wrong sign (' + sg(f) + ' mm forecast, ' + sg(o) + ' mm observed).');
    if (fk === k && fp[fk] - 1 / 3 >= 0.02) got.push('The highest average probability (' + pc(fp[fk]) + ') was on the observed ' + CAT[k] + ' category.');
    else if (fp[fk] - 1 / 3 >= 0.02) miss.push('Probabilities favoured ' + CAT[fk] + ' (' + pc(fp[fk]) + ') while most of the area was ' + CAT[k] + '.');
    else miss.push('Probabilities stayed close to climatology (largest ' + pc(fp[fk]) + ').');
    (pb.rpss > 0 ? got : miss).push('Probabilities scored ' + (pb.rpss > 0 ? 'better' : 'worse') + ' than climatology (RPSS ' + sg(pb.rpss, 3) + ').');
    if (Math.abs(ac.bias_mm) >= Math.max(5, 0.1 * Math.abs(ref))) miss.push('Forecast amounts were too ' + (ac.bias_mm > 0 ? 'wet' : 'dry') + ' on average (bias ' + sg(ac.bias_mm, 1) + ' mm).');
    (ac.crpss > 0 ? got : miss).push('Rainfall amounts scored ' + (ac.crpss > 0 ? 'better' : 'worse') + ' than climatology (CRPSS ' + sg(ac.crpss, 3) + ').');
    const li = a => a.length ? '<ul>' + a.map(x => '<li>' + x + '</li>').join('') + '</ul>' : '<p class="caveat">Nothing notable.</p>';
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
    const tr = c.targets.find(t => t.history.training).history.training, op = (c.targets.find(t => t.history.operational) || {history: {}}).history.operational;
    $('hs-body').innerHTML = '<div class="table-wrap"><table><caption>' + esc(c.label) + ' (' + esc(c.init) + ' initialization): probability skill (RPSS) of the final method against climatology, all Ethiopia, with whole-year 95% intervals</caption><thead><tr>' +
      '<th scope="col">Target</th><th scope="col">Cross-validated ' + tr.first + '–' + tr.last + ' (main)</th><th scope="col">Years better</th><th scope="col">In words</th>' +
      '<th scope="col">Exploratory ' + (op ? op.first + '–' + op.last : '') + '</th><th scope="col">Years better</th><th scope="col">Blend weight λ</th></tr></thead><tbody>' +
      c.targets.map(t => '<tr' + (t.id === S.target ? ' class="current"' : '') + '><td>' + esc(t.id) + '</td><td>' + cell(t.history.training) + '</td><td>' + yrs(t.history.training) + '</td><td>' +
        (t.history.training ? skillWord(t.history.training.rpss) : '—') + '</td><td>' + cell(t.history.operational, false) + '</td><td>' + yrs(t.history.operational) + '</td><td>' + (ok(t.lambda) ? t.lambda.toFixed(2) : '—') + '</td></tr>').join('') +
      '</tbody></table></div><p class="caveat">RPSS +0.05 means a 5% lower ranked probability score than climatology. Gains are <strong>modest</strong> and the intervals are wide; an interval that includes zero means the gain is not established. λ is the weight given to climatology in the blend (higher = closer to 33/33/33).</p>';
  }

  function renderDownloads() {
    const c = cyc();
    $('dl-body').innerHTML = '<div class="box"><h3>' + esc(c.option) + '</h3><ul class="dl">' + c.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(d.note) + '</span></li>').join('') + '</ul></div>' +
      '<details><summary>Other cycles</summary><ul class="dl">' + D.cycles.filter(x => x.id !== c.id).flatMap(x => x.downloads.map(d => '<li><a href="' + d.href + '" download>' + esc(d.label) + '</a><span>' + esc(x.option) + '</span></li>')).join('') + '</ul></details>';
  }

  function renderAll() {
    const c = cyc();
    $('cycle').value = c.id;
    $('view').innerHTML = c.views.map(v => '<option value="' + v[0] + '"' + (v[0] === S.view ? ' selected' : '') + '>' + esc(v[1]) + '</option>').join('');
    renderOutlook(); renderMaps(); renderVerification(); renderHistory(); renderDownloads(); sync();
  }

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

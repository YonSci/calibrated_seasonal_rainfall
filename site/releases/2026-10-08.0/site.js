(() => {
  const entries = JSON.parse(document.getElementById('entries').textContent);
  const fmt = (x, d = 1) => (x === null || x === undefined || Number.isNaN(x)) ? '—' : Number(x).toFixed(d);
  const pct = x => fmt(x === null || x === undefined ? null : 100 * x);
  const $ = id => document.getElementById(id);
  const tSel = $('ex-target'), pSel = $('ex-product'), vSel = $('ex-view'), body = $('ex-body');
  if (!tSel) return;
  const pick = () => { const [group, target] = tSel.value.split('|'); return {group, target}; };
  function fillViews() {
    const {group, target} = pick();
    const seen = new Map();
    entries.filter(e => e.group === group && (e.target === target || !entries.some(x => x.group === group && x.target === target)))
      .forEach(e => seen.set(e.view, e.label));
    if (!seen.size) entries.filter(e => e.group === group).forEach(e => seen.set(e.view, e.label));
    const keep = vSel.value;
    vSel.innerHTML = [...seen].map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join('');
    if ([...seen.keys()].includes(keep)) vSel.value = keep;
  }
  function render() {
    const {group, target} = pick(), kind = pSel.value, view = vSel.value;
    const e = entries.find(x => x.group === group && x.kind === kind && x.target === target && x.view === view);
    if (!e) {
      body.innerHTML = '<p class="pending">' + target + ' ' + kind + ' is not available yet' +
        (kind === 'verification' ? ': it needs complete CHIRPS observations for the target period.' : '.') + '</p>';
      return;
    }
    const s = e.summary;
    const rows = [['Domain cells', s.domain_cells], ['Domain share of country area (%)', fmt(s.domain_country_area_percent)],
      ['Amount coverage within domain (%)', fmt(s.amount_domain_area_percent)],
      ['Probability coverage within domain (%)', fmt(s.probability_domain_area_percent)]];
    if (kind === 'forecast') {
      rows.push(['Mean rainfall / reference (mm)', fmt(s.mean_rainfall_mm) + ' / ' + fmt(s.mean_reference_mm)],
        ['Mean anomaly (mm)', fmt(s.mean_anomaly_mm)],
        ['Area-mean local Below / Near / Above probabilities (%)', s.mean_local_probabilities.map(pct).join(' / ')]);
    } else {
      const p = s.probability.shared_blend || {}, a = s.amount.corrected || {};
      rows.push(['Shared RPS', fmt(p.rps, 4)], ['Shared RPSS (%)', pct(p.rpss)], ['Corrected CRPS (mm)', fmt(a.crps_mm)],
        ['Corrected CRPSS (%)', pct(a.crpss)], ['Corrected rainfall bias (mm)', fmt(a.bias_mm)],
        ['Observed Below / Near / Above area (%)', s.observed_category_area_fractions.map(pct).join(' / ')]);
    }
    const note = kind === 'forecast'
      ? 'Area means of local probabilities are not probabilities for domain-total rainfall.'
      : 'Positive skill means improvement over climatology on this support. Single-year results do not establish long-term reliability.';
    body.innerHTML = '<h3>' + target + ' · ' + e.label + ' · ' + (kind === 'forecast' ? 'Forecast' : 'Verification') + '</h3>' +
      '<p class="caveat">' + group + '</p><div class="table-wrap"><table class="stats">' +
      rows.map(r => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('') + '</table></div><p class="caveat">' + note + '</p>' +
      '<div class="maps' + (kind === 'verification' ? ' wide' : '') + '">' + e.images.map(([name, cap]) =>
        '<figure><a href="' + e.folder + '/' + name + '.png"><img loading="lazy" src="' + e.folder + '/' + name + '.png" alt="' +
        target + ' ' + e.label + ' ' + cap + '"></a><figcaption>' + cap + '</figcaption></figure>').join('') + '</div>';
  }
  tSel.addEventListener('change', () => { fillViews(); render(); });
  pSel.addEventListener('change', render);
  vSel.addEventListener('change', render);
  fillViews(); render();
})();

(() => {
  const entries = JSON.parse(document.getElementById('entries').textContent);
  const fmt = (x, d = 1) => (x === null || x === undefined || Number.isNaN(x)) ? '—' : Number(x).toFixed(d);
  const pct = x => fmt(x === null || x === undefined ? null : 100 * x);
  function render(box) {
    const {kind, target, view} = box.dataset;
    const body = box.querySelector('.view-body');
    const e = entries.find(x => x.kind === kind && x.target === target && x.view === view);
    if (!e) {
      body.innerHTML = '<p class="pending">' + target + ' ' + kind + ' is pending: complete CHIRPS observations are required (September 2026 not yet published).</p>';
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
    body.innerHTML = '<h3>' + target + ' 2026 · ' + e.label + '</h3><div class="table-wrap"><table class="stats">' +
      rows.map(r => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('') + '</table></div><p class="caveat">' + note + '</p>' +
      '<div class="maps' + (kind === 'verification' ? ' wide' : '') + '">' + e.images.map(([name, cap]) =>
        '<figure><a href="' + e.folder + '/' + name + '.png"><img loading="lazy" src="' + e.folder + '/' + name + '.png" alt="' +
        target + ' 2026 ' + e.label + ' ' + cap + '"></a><figcaption>' + cap + '</figcaption></figure>').join('') + '</div>';
  }
  document.querySelectorAll('.viewer').forEach(box => {
    box.querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => {
      const key = chip.dataset.target ? 'target' : 'view';
      box.dataset[key] = chip.dataset[key];
      chip.parentElement.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c === chip));
      render(box);
    }));
    render(box);
  });
})();

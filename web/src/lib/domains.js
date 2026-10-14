// Rainfall climatology and domains (docs/44): the current page's domain review (scripts/build_site.py, renderDomains)
// ported to build time. One review per season; every tab and every candidate is rendered, and the page shows one at a time.
import { asset } from './data.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pc = (x) => (x == null ? '—' : Math.round(100 * x) + '%');
const km = (x) => (x == null ? '—' : Math.round(x).toLocaleString('en-US') + ' km²');
const tbl = (cap, head, rows) => '<div class="table-wrap"><table><caption>' + esc(cap) + '</caption><thead><tr>' + head.map((x) => '<th scope="col">' + esc(x) + '</th>').join('') +
  '</tr></thead><tbody>' + rows.map((r) => '<tr>' + r.map((x) => '<td>' + x + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';

export function review(R, cycleViews) {
  const fig = (f, alt) => '<figure class="map-figure"><img src="' + asset(R.base + f) + '" alt="' + esc(alt) + '" loading="lazy" style="max-width:100%;height:auto"><figcaption class="caveat">' + esc(alt) + '</figcaption></figure>';
  let head = (R.selected ? '' : '<p class="notice">Evidence only: no candidate has been selected for ' + esc(R.season) + ', so the forecast products keep their current domain (' +
      esc(cycleViews.filter((v) => v[0] !== 'all_ethiopia').map((v) => v[1]).join('; ')) + ').</p>') +
    '<p class="caveat">' + esc(R.season) + ' climatology from ' + esc(R.dataset || 'CHIRPS') + ' ' + esc(R.period) + ' · built ' + esc(R.built.slice(0, 10)) +
    ' · <a href="' + asset(R.report) + '">Full review report</a></p>';
  if (R.stale.length) head += '<p class="notice">This review was built before a change to ' + esc(R.stale.join(', ')) + '; its numbers describe the earlier inputs.</p>';
  head += '<p>' + (R.selected ? 'Selected domain: <strong>' + esc(R.selected) + '</strong>' + (R.rationale ? ' — ' + esc(R.rationale) : '')
    : 'No candidate has been selected yet. The review shows the evidence; a domain is exported to the forecast products only after an explicit selection.') + '</p>';

  const climatology = '<p>Ratio of climatological means from actual-calendar monthly totals (February 29 included). Every year of the period is required in each cell; nothing is filled in.</p>' +
    R.figures.climatology.map((f) => fig(f, { [R.season.toLowerCase() + '_total_mm.png']: R.season + ' mean rainfall', 'annual_total_mm.png': 'Mean annual rainfall (the share denominator)',
      [R.season.toLowerCase() + '_share_percent.png']: R.season + ' share of annual rainfall', 'monthly_cycle_review.png': 'Monthly cycle by EMI rainfall region' }[f] || f)).join('') +
    tbl('Reference periods', ['Period', 'Status', 'Note'], R.periods.map((p) => [esc(p.period), esc(p.status), esc(p.note || '')])) +
    '<p class="caveat">Calendar check ' + (R.qc.calendar ? 'passed' : 'FAILED') + '; ' + R.qc.years.count + ' years (' + R.qc.years.first + '–' + R.qc.years.last + '); ' +
    R.qc.incomplete_cells + ' cells without a complete baseline; Ethiopia ' + km(R.country_km2) + ', of which ' + km(R.qc.outside_grid_km2) + ' lies beyond the grid. CHIRPS source ' + esc(R.qc.source) + '….</p>';

  const references = (!R.references.length ? '<p class="notice">No EMI long-term maps are registered for ' + esc(R.season) + '. ' + esc(R.note || '') + '</p>' :
    '<p>' + (R.reference_note ? esc(R.reference_note) + ' ' : 'The registered EMI long-term maps for ' + esc(R.season) + ' are climatologies whose averaging period is not documented. ') +
    'Until their georeferencing and legend digitization are reviewed they are compared <strong>visually only</strong>.</p>') +
    tbl('Registered climatology references', ['Reference', 'Comparison mode', 'Why not higher', 'Digitization', 'Outline match (IoU)', 'Control / check error'],
      R.references.map((r) => [esc(r.id), esc(r.mode.replace(/_/g, ' ')), esc(r.reasons.join('; ') || '—'), esc(r.status), r.iou, (r.control_km || 0).toFixed(1) + ' / ' + (r.check_km || 0).toFixed(1) + ' km'])) +
    R.figures.references.map((f) => fig(f, f.startsWith('reference_comparison') ? 'CHIRPS, EMI as published, and CHIRPS in the EMI classes' : 'Registration and digitized classes (' + f.replace('georeference_qc_', '').replace('.png', '') + ')')).join('');

  // Candidates: one block per threshold candidate and named comparison; the cutoff buttons and the comparison list pick one.
  const block = (cur, isCand) => {
    const rows = [['Included area', km(cur.km2) + ' (' + cur.pct.toFixed(1) + '% of Ethiopia)']];
    const ref = cur.ref || {};
    rows.push(['Agreement with EMI-implied membership', ref.agreement == null ? '<span class="caveat">' + esc(ref.note || 'not computed') + '</span>'
      : pc(ref.agreement) + ' <span class="caveat">(' + esc(ref.mode) + '; undecided ' + km(ref.undecided_area_km2) + ')</span>']);
    rows.push(['Domain files', '<a href="' + asset(R.base + 'domains/' + cur.id + '.nc') + '" download>NetCDF</a> · <a href="' + asset(R.base + 'domains/' + cur.id + '.geojson') + '" download>GeoJSON outline</a>']);
    if (isCand) {
      rows.push(['Unknown area', km(cur.unknown)]);
      Object.entries(cur.baseline).forEach(([k, v]) => rows.push(['Baseline ' + k, v.status === 'unavailable' ? 'unavailable: ' + esc(v.note) : '+' + km(v.gained_area_km2) + ' / −' + km(v.lost_area_km2)]));
    }
    return '<div class="dr-cand" data-cand="' + esc(cur.id) + '"' + (cur.id === (R.selected || R.focus || R.candidates[0].id) ? '' : ' hidden') + '>' +
      '<div class="grid2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;align-items:start">' + fig('candidates/' + cur.id + '.png', (isCand ? 'Candidate ' : '') + cur.id + ' (blue: included; dark grey: insufficient data)') +
      '<div>' + tbl(cur.id, ['Measure', 'Value'], rows.map((r) => [esc(r[0]), r[1]])) +
      tbl('Share of each EMI rainfall region included', ['Region', 'Included'], Object.entries(cur.regions).map(([k, v]) => [esc(k), v == null ? '—' : v + '%'])) + '</div></div></div>';
  };
  const first = R.candidates.find((c) => c.id === (R.selected || R.focus)) || R.candidates[0];
  const candidates = '<div class="map-controls"><span>' + esc(R.season) + ' rainfall</span><div class="seg" role="group" aria-label="Rainfall cutoff">' +
      R.mm.map((v) => '<button type="button" data-dmm="' + v + '" aria-pressed="' + (first.mm === v) + '">≥ ' + v + ' mm</button>').join('') + '</div>' +
      '<span>Share of annual</span><div class="seg" role="group" aria-label="Share cutoff">' +
      R.shares.map((v) => '<button type="button" data-dsh="' + v + '" aria-pressed="' + (first.share === v) + '">≥ ' + v + '%</button>').join('') + '</div>' +
      '<label>Comparison <select class="dr-comp"><option value="">— threshold candidates —</option>' + R.comparators.map((c) => '<option value="' + esc(c.id) + '">' + esc(c.label) + '</option>').join('') + '</select></label></div>' +
    R.candidates.map((c) => block(c, true)).join('') + R.comparators.map((c) => block(c, false)).join('') +
    tbl('Named comparisons', ['Rule', 'Share of Ethiopia', 'Agreement with EMI-implied membership', 'Files'], R.comparators.map((c) => [esc(c.label), c.pct.toFixed(1) + '%',
      (c.ref || {}).agreement == null ? '<span class="caveat">' + esc((c.ref || {}).note || '—') + '</span>' : pc(c.ref.agreement),
      '<a href="' + asset(R.base + 'domains/' + c.id + '.nc') + '" download>NetCDF</a> · <a href="' + asset(R.base + 'domains/' + c.id + '.geojson') + '" download>GeoJSON</a>'])) +
    R.figures.candidates.map((f) => fig(f, { 'domains_named_comparisons.png': 'Named comparisons side by side', 'domains_all_candidates.png': 'All threshold candidates (rows: rainfall cutoff; columns: share cutoff)', 'candidate_area_heatmap.png': 'Included share of Ethiopia for each candidate', 'candidate_inclusion_map.png': 'How many candidates include each cell',
      'regional_inclusion.png': 'Regional inclusion by candidate' }[f] || f)).join('');

  const assessment = tbl('Agreement of CHIRPS with the EMI classes', ['Reference', 'Mode', 'Exact class', 'Within one class', 'CHIRPS wetter / drier', 'Outside the class interval (median / 90th pct)', 'Comparable / uncertain area'],
      R.comparisons.map((c) => [esc(c.id), esc(c.mode.replace(/_/g, ' ')) + (c.draft ? ' <span class="caveat">(unreviewed preview)</span>' : ''), pc(c.exact), pc(c.within1), pc(c.wetter) + ' / ' + pc(c.drier),
        (c.dev_median || 0).toFixed(1) + ' / ' + (c.dev_p90 || 0).toFixed(1) + ' ' + (c.units === 'percent' ? 'pp' : esc(c.units)), km(c.comparable) + ' / ' + km(c.uncertain)])) +
    tbl('Largest changes between neighbouring cutoffs', ['From', 'To', 'Changed', 'Area switching'], R.neighbours.map((n) => [esc(n.from_candidate), esc(n.to_candidate), esc(n.changed.replace(/_/g, ' ')), km(n.switched_area_km2)])) +
    R.figures.assessment.map((f) => fig(f, 'Baseline sensitivity of ' + R.focus)).join('') +
    '<p class="caveat">Candidates nested (raising a cutoff never adds a cell): ' + (R.monotonic ? 'yes' : 'NO') + '. Dataset sensitivity: not assessed (CHIRPS only).</p>';

  return { head, tabs: [['climatology', 'Climatology', climatology], ['references', 'References', references], ['candidates', 'Candidate domains', candidates], ['assessment', 'Assessment', assessment]],
    candidates: R.candidates.map((c) => ({ id: c.id, mm: c.mm, share: c.share })) };
}

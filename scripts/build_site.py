"""Build the static GitHub Pages site (site/) from the project's result files.

Every number on the page is read from outputs/ JSON files; maps are copied from the
delivery and verification packages. Rerun after results change:

    python scripts\\build_site.py
"""
import html
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'site'
REPO = 'https://github.com/YonSci/calibrated_seasonal_rainfall'
TARGETS = ['JJAS', 'Jun', 'Jul', 'Aug', 'Sep']
MONTHS = ['Jun', 'Jul', 'Aug']
CAT = ['Below normal', 'Near normal', 'Above normal']
esc = html.escape


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8-sig'))


def pct(x, d=0):
    return f'{100 * x:.{d}f}%'


def signed(x, d=3):
    return f'{x:+.{d}f}'


def table(head, rows, cls=''):
    h = ''.join(f'<th>{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def skill_cell(v, p=None):
    cls = 'pos' if v > 0 else 'neg'
    sig = '' if p is None else (' <span class="sig">p=' + f'{p:.2f}' + '</span>')
    strong = p is not None and p < .05
    return f'<span class="{cls}{" strong" if strong else ""}">{signed(v)}</span>{sig}'


def copy_assets():
    assets = OUT / 'assets'
    if assets.exists():
        shutil.rmtree(assets)
    (assets / 'forecast').mkdir(parents=True)
    (assets / 'verification').mkdir(parents=True)
    for t in TARGETS:
        src = ROOT / f'outputs/forecast_delivery/init05_2026/maps/init05_{t}/2026/all_ethiopia'
        for name in ('dominant_tercile_2026.png', 'rainfall_anomaly_mm_2026.png'):
            shutil.copy2(src / name, assets / 'forecast' / f'{t}_{name}')
    for m in MONTHS:
        shutil.copy2(ROOT / f'outputs/verification_report_2026/Jun_Jul_Aug/maps/{m}_verification.png',
                     assets / 'verification' / f'{m}_verification.png')


def gather():
    fc = {s['target']: s for s in load('outputs/forecast_delivery/init05_2026/forecast_summary.json')['summaries']}
    ver = {r['target']: r for r in load('outputs/verification_report_2026/Jun_Jul_Aug/evidence/country_summary.json')['results']}
    reg = load('outputs/regional_skill/regional_skill.json')['targets']
    gates = load('outputs/decision_gates/decision_gates.json')['gates']
    ens = load('outputs/ensemble_checks/ensemble_checks.json')['targets']
    mono = load('outputs/monthly_consistency/monthly_consistency.json')
    clip = load('outputs/clipping_analysis/amount_correction_alternatives.json')['targets']
    raw = load('outputs/verification/init05_JJAS/Ethiopia/verification_summary.json')['summary']
    status = load('outputs/verification_followup/season_status.json')
    return fc, ver, reg, gates, ens, mono, clip, raw, status


def page(fc, ver, reg, gates, ens, mono, clip, raw, status):
    j = fc['JJAS']
    vs = {m: ver[m]['probability']['shared_blend']['rpss'] for m in MONTHS}
    eth = {t: reg[t] for t in TARGETS}
    raw_rpss = 1 - raw['raw_rps'] / raw['climatology_rps'] if 'raw_rps' in raw and 'climatology_rps' in raw else None
    sep_status = next((f['status'] for f in status['files'] if f['month'] == 'Sep'), 'unknown')

    # ---------- key numbers
    cards = [
        ('2026 JJAS outlook', f'{pct(j["area_mean_local_probabilities"][0])} below normal',
         f'Area-mean probability; anomaly {j["area_mean_anomaly_mm"]:+.0f} mm'),
        ('Skill 2017–2025 (JJAS)', f'RPSS {signed(eth["JJAS"]["operational"]["ethiopia"]["rpss_blend"], 3)}',
         'Ranked probability skill vs climatology'),
        ('2026 verified so far', ' / '.join(f'{m} {signed(vs[m], 2)}' for m in MONTHS),
         f'RPSS against CHIRPS; Sep & JJAS pending (Sep CHIRPS: {sep_status})'),
    ]
    card_html = ''.join(f'<div class="card"><div class="card-label">{a}</div><div class="card-value">{b}</div>'
                        f'<div class="card-note">{c}</div></div>' for a, b, c in cards)

    # ---------- workflow
    steps = [
        ('Download', 'ECMWF SEAS5 (system 51) daily accumulated precipitation, May initialization, 183 days, 25 hindcast / 51 forecast members, via the Copernicus CDS.', 'download_seasonal_forecasts_daily_c3s.py'),
        ('Inspect', 'Inventory every year: initialization, lead times, member counts, accumulation increments (GRIB packing tolerance 0.2 mm).', 'inspect_inputs.py'),
        ('Prepare', 'De-accumulate to daily totals, label days by interval start, sum JJAS (122 days) and each month; CHIRPS on the same dates.', 'prepare_seasonal.py · run_monthly.py'),
        ('Regrid', 'Each 1° model cell copied into its 4×4 block of 0.25° CHIRPS cells; edges and area conservation verified.', 'regrid_seasonal.py'),
        ('Calibrate', 'Per-cell mean–variance amount correction, smoothed tercile counts, one climatology-blend weight per target (leave-one-year-out).', 'final_shared_blend.py'),
        ('Evaluate', 'Nested cross-validation 1993–2016, fixed-fit evaluation 2017–2025, whole-year significance gates.', 'local_blend.py · decision_gates.py'),
        ('Deliver', 'Maps, bulletin and offline gallery; forecasts frozen with SHA-256 hashes before observations are used.', 'finalize_forecast_delivery.py · run_operational.py'),
        ('Verify', 'Official CHIRPS v2.0 p25 monthly files, overlap-checked against the archive, scored per month and season.', 'prepare_verification_2026.py · verify_frozen_2026.py'),
    ]
    flow = ''.join(f'<li class="step"><div class="step-n">{i}</div><div><h3>{a}</h3><p>{b}</p><code>{c}</code></div></li>'
                   for i, (a, b, c) in enumerate(steps, 1))

    # ---------- historical skill
    hist_rows = []
    for t in TARGETS:
        tr, op = eth[t]['training']['ethiopia'], eth[t]['operational']['ethiopia']
        hist_rows.append([t, skill_cell(tr['rpss_blend'], tr['p_blend_better_than_climatology']),
                          f'{tr["years_blend_better"]}/{tr["years"]}',
                          skill_cell(op['rpss_blend'], op['p_blend_better_than_climatology']),
                          f'{op["years_blend_better"]}/{op["years"]}', pct(op['probability_coverage'])])
    hist = table(['Target', 'RPSS 1993–2016 (nested CV)', 'Years better', 'RPSS 2017–2025', 'Years better', 'Probability coverage'], hist_rows)

    regions = [('R0_arid_marginal', 'R0 arid / marginal'), ('R1_western_unimodal', 'R1 western unimodal'),
               ('R2_belg_kiremt', 'R2 Belg–Kiremt'), ('R3_gu_deyr', 'R3 Gu–Deyr'), ('R1_R2_jjas_domain', 'R1+R2 JJAS domain')]
    reg_rows = []
    for key, label in regions:
        row = [label]
        for t in TARGETS:
            r = reg[t]['training'].get(key, {})
            row.append(skill_cell(r['rpss_blend'], r['p_blend_better_than_climatology']) if 'rpss_blend' in r else '—')
        reg_rows.append(row)
    regional = table(['Region (nested 1993–2016)'] + TARGETS, reg_rows, 'compact')

    gate_names = [('ethiopia_lambda_vs_current', 'Fit blend weight on Ethiopia only'),
                  ('sqrt_vs_current', 'Square-root amount correction (probabilities)'),
                  ('no_blend_vs_current', 'Remove the climatology blend'),
                  ('climatology_vs_current', 'Plain climatology')]
    gate_rows = []
    for fam, label in gate_names:
        g = gates[fam]
        tr = [g[t]['training']['mean_difference'] for t in TARGETS]
        op = [g[t]['operational']['mean_difference'] for t in TARGETS]
        adopted = [t for t in TARGETS if g[t]['decision']['adopt']]
        gate_rows.append([label, f'{min(tr):+.4f} to {max(tr):+.4f}', f'{min(op):+.4f} to {max(op):+.4f}',
                          'Adopted: ' + ', '.join(adopted) if adopted else '<span class="neg">Not adopted</span>'])
    sq = [clip[t]['training_loyo_1993_2016'] for t in TARGETS]
    gate_rows.append(['Square-root amount correction (rainfall amounts, CRPS)',
                      f'{min(s["sqrt_affine"]["crps"] - s["affine"]["crps"] for s in sq):+.2f} to {max(s["sqrt_affine"]["crps"] - s["affine"]["crps"] for s in sq):+.2f} mm',
                      'better in all targets', '<span class="pos">Passes for all targets (next cycle)</span>'])
    gate = table(['Candidate change', 'Δ score 1993–2016', 'Δ score 2017–2025', 'Decision'], gate_rows)

    ens_rows = [[t, f'{ens[t]["ensemble_size"]["rps_51"]:.4f}', f'{ens[t]["ensemble_size"]["rps_25_mean"]:.4f}',
                 f'{ens[t]["system_consistency"]["spread_error_ratio_hindcast"]:.2f} → {ens[t]["system_consistency"]["spread_error_ratio_operational"]:.2f}']
                for t in TARGETS]
    ens_t = table(['Target', 'RPS, 51 members', 'RPS, 25-member subsets', 'Spread / error (hindcast → operational)'], ens_rows, 'compact')

    # ---------- forecast
    fc_rows = []
    for t in TARGETS:
        s = fc[t]
        p = s['area_mean_local_probabilities']
        lead = s['area_fraction_leading_display_category']
        fc_rows.append([t, *(pct(x) for x in p), f'{s["area_mean_anomaly_mm"]:+.1f} mm',
                        f'{s["climatology_weight"]:.2f}', pct(lead['below'])])
    fc_t = table(['Target', CAT[0], CAT[1], CAT[2], 'Mean anomaly', 'Climatology weight', 'Area led by below normal'], fc_rows)
    tabs = ''.join(f'<button class="tab{" active" if t == "JJAS" else ""}" data-t="{t}">{t}</button>' for t in TARGETS)
    panels = ''.join(
        f'<div class="panel{" active" if t == "JJAS" else ""}" data-t="{t}"><figure><img loading="lazy" src="assets/forecast/{t}_dominant_tercile_2026.png" '
        f'alt="{t} 2026 leading tercile probability map for Ethiopia"><figcaption>Leading tercile and its probability</figcaption></figure>'
        f'<figure><img loading="lazy" src="assets/forecast/{t}_rainfall_anomaly_mm_2026.png" alt="{t} 2026 rainfall anomaly map for Ethiopia">'
        f'<figcaption>Corrected ensemble-mean anomaly vs 1993–2025</figcaption></figure></div>' for t in TARGETS)

    # ---------- verification
    v_rows = []
    for m in MONTHS:
        r = ver[m]
        pr, am = r['probability'], r['amount']
        obs = r['observed_category_area_fractions']
        v_rows.append([m, skill_cell(pr['shared_blend']['rpss']), signed(pr['raw_observed_thresholds']['rpss'], 2),
                       skill_cell(am['corrected']['crpss']), f'{am["corrected"]["bias_mm"]:+.1f} mm',
                       ' / '.join(pct(x) for x in obs)])
    v_rows += [[t, '<span class="pending">pending</span>', '—', '—', '—', '—'] for t in ('Sep', 'JJAS')]
    v_t = table(['Target', 'Final RPSS', 'Raw RPSS', 'Corrected CRPSS', 'Corrected bias', 'Observed below / near / above (area)'], v_rows)
    v_maps = ''.join(f'<figure><img loading="lazy" src="assets/verification/{m}_verification.png" alt="{m} 2026 forecast verification maps">'
                     f'<figcaption>{m} 2026: forecast, observation and score maps</figcaption></figure>' for m in MONTHS)

    mc = mono['frozen_2026']
    built = date.today().isoformat()
    raw_line = f' Uncalibrated ECMWF probabilities score RPSS {raw_rpss:+.2f} for JJAS over 2017–2025.' if raw_rpss is not None else ''

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ethiopia Seasonal Rainfall</title>
<meta name="description" content="Calibrated ECMWF SEAS5 seasonal rainfall outlooks for Ethiopia, verified against CHIRPS: workflow, methods, skill, 2026 forecast and verification.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="top">
  <div class="wrap nav">
    <a class="brand" href="#top">Ethiopia Seasonal Rainfall</a>
    <nav><a href="#workflow">Workflow</a><a href="#methods">Methods</a><a href="#skill">Skill</a><a href="#forecast">2026 forecast</a><a href="#verification">Verification</a><a href="{REPO}">GitHub</a></nav>
  </div>
</header>
<main id="top">
<section class="hero wrap">
  <p class="eyebrow">ECMWF SEAS5 · May initialization · CHIRPS v2.0 · 0.25°</p>
  <h1>Calibrated seasonal rainfall outlooks for Ethiopia</h1>
  <p class="lead">Bias-corrected, probability-calibrated June–September rainfall outlooks for Ethiopia, built from the ECMWF SEAS5 ensemble and evaluated against CHIRPS observations over 1993–2025, with a frozen 2026 forecast verified as observations arrive.</p>
  <p class="notice"><strong>Research reconstruction.</strong> These are retrospective research products, not official forecasts of the Ethiopian Meteorology Institute (EMI) or ICPAC.</p>
  <div class="cards">{card_html}</div>
</section>

<section id="workflow" class="wrap">
  <h2>Workflow</h2>
  <p>Every stage is a script in <a href="{REPO}/tree/main/scripts"><code>scripts/</code></a> with its own checks; documents 01–37 in <a href="{REPO}/tree/main/docs"><code>docs/</code></a> record each step and decision.</p>
  <ol class="flow">{flow}</ol>
</section>

<section id="methods" class="wrap">
  <h2>Data and methods</h2>
  <div class="grid2">
    <div>
      <h3>Data</h3>
      {table(['Source', 'Details'], [
          ['ECMWF SEAS5', 'CDS <code>seasonal-original-single-levels</code>, system 51, total precipitation, 1 May initialization, 1993–2026; 25 members (1993–2016), 51 (2017–2026); 1° grid, 3–15°N, 33–48°E'],
          ['CHIRPS v2.0', '0.25° daily; archive 1993–2025; 2026 from official p25 monthly files, overlap-checked against the archive'],
          ['Targets', 'JJAS (122 days) and the months Jun, Jul, Aug, Sep'],
          ['Masks', 'Ethiopia (1,484 cells, cell-centre rule); descriptive rainfall regimes R0–R3 fixed on 1993–2025'],
      ], 'compact')}
      <h3>Quality control</h3>
      <ul>
        <li>All 34 forecast files inventoried; re-downloaded years were bit-identical, confirming SEAS5 system 51.</li>
        <li>Small negative daily increments (≤0.15 mm) are GRIB packing rounding (2<sup>−13</sup> m); tolerated up to 0.2 mm, clipped, and the seasonal sum is checked to telescope.</li>
        <li>CHIRPS sea cells (223) are permanently missing; no partial seasons enter any fit.</li>
      </ul>
    </div>
    <div>
      <h3>Calibration (final method)</h3>
      <ol>
        <li><strong>Amount correction</strong> per cell, equal weight per year:<br><code>x̂ = max(0, μ<sub>obs</sub> + r·(x − μ<sub>model</sub>)), r = clip(σ<sub>obs</sub>/σ<sub>model</sub>, 0.5, 2)</code></li>
        <li><strong>Tercile probabilities</strong> from corrected members against CHIRPS terciles, smoothed: <code>(n + 0.5)/(M + 1.5)</code></li>
        <li><strong>Climatology blend</strong>: <code>p = (1 − λ)·p<sub>model</sub> + λ·p<sub>clim</sub></code>, one λ per target fitted on leave-one-year-out RPS (λ = {', '.join(f'{t} {fc[t]["climatology_weight"]:.2f}' for t in TARGETS)})</li>
      </ol>
      <p>Evaluated and not adopted: regularized Dirichlet recalibration, per-cell and regime-specific blend weights, an Ethiopia-only blend domain and removing the blend.{raw_line}</p>
    </div>
  </div>
</section>

<section id="skill" class="wrap">
  <h2>Historical skill</h2>
  <p>Ranked probability skill score (RPSS) of the final method against climatology, Ethiopia cells, one score per year. 1993–2016 uses nested leave-one-year-out fits; 2017–2025 uses fits on 1993–2016 (exploratory, years seen during method selection). <span class="strong pos">Bold</span>: one-sided whole-year permutation p &lt; 0.05.</p>
  {hist}
  <p class="caveat">After adjusting for five targets, no gain over climatology is statistically significant; JJAS is significant on its own (p = {eth["JJAS"]["training"]["ethiopia"]["p_blend_better_than_climatology"]:.2f}). Monthly skill is small.</p>
  <h3>Where the forecast is skilful</h3>
  {regional}
  <p class="caveat">R3 (Gu–Deyr, south and south-east) shows no clean-period skill for any target; June and September show none in any region.</p>
  <h3>Decisions tested with significance gates</h3>
  <p>A change is adopted only if it improves nested 1993–2016 scores (Holm-adjusted p &lt; 0.05) and does not worsen 2017–2025.</p>
  {gate}
  <h3>Ensemble diagnostics</h3>
  {ens_t}
  <p class="caveat">51-member forecasts score at least as well as 25-member hindcast-sized ensembles, so the transfer is safe. The corrected ensemble is under-dispersive (spread/error below 1), which the climatology blend partly compensates.</p>
</section>

<section id="forecast" class="wrap">
  <h2>2026 forecast</h2>
  <p>May-initialized, 51 members, fitted on 1993–2025 and frozen before any 2026 observation was used. Probabilities are area means of grid-cell probabilities.</p>
  {fc_t}
  <p class="caveat">Monthly and seasonal outlooks are calibrated separately: the corrected monthly means sum to {mc["sum_of_monthly_corrected_means_mm"]:.0f} mm against {mc["jjas_corrected_mean_mm"]:.0f} mm for JJAS ({mc["difference_mm"]:+.1f} mm).</p>
  <div class="tabs" role="tablist">{tabs}</div>
  <div class="panels">{panels}</div>
</section>

<section id="verification" class="wrap">
  <h2>2026 verification</h2>
  <p>Frozen forecasts scored against official CHIRPS v2.0 observations. Single-season results, not evidence of multi-year reliability.</p>
  {v_t}
  <div class="gallery">{v_maps}</div>
</section>

<section class="wrap">
  <h2>Limitations</h2>
  <ul>
    <li>Nine fixed-fit evaluation years and one verification season give wide uncertainty; regional and monthly results are noisy.</li>
    <li>The 2017–2025 period was inspected during method development; clean evidence comes from nested 1993–2016 scores.</li>
    <li>The 0.25° maps repeat 1° model information; they do not add dynamical detail.</li>
    <li>Not an official EMI or ICPAC product.</li>
  </ul>
  <h2>Reproduce</h2>
  <pre><code>git clone {REPO}.git
python -m venv .venv &amp;&amp; .venv\\Scripts\\activate &amp;&amp; pip install -r requirements.txt
python scripts\\prepare_seasonal.py --config config\\project.json --all-years
python scripts\\final_shared_blend.py --config config\\project.json --region-mask data\\masks\\ethiopia_common.nc
python scripts\\run_operational.py --workflow all</code></pre>
  <p>Raw ECMWF and CHIRPS data are not stored in the repository; download instructions are in <a href="{REPO}/blob/main/docs/37_NEW_FORECAST_CYCLE.md">docs/37</a>. Status and decisions: <a href="{REPO}/blob/main/docs/36_PROJECT_STATUS_REVIEW.md">docs/36</a>.</p>
</section>
</main>
<footer class="wrap foot">Built {built} by <code>scripts/build_site.py</code> from the project's result files.</footer>
<script>
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.tab,.panel').forEach(e=>e.classList.toggle('active',e.dataset.t===b.dataset.t));
}}));
</script>
</body>
</html>
'''


CSS = '''
:root{--bg:#f7f8f6;--surface:#ffffff;--ink:#1c2a2a;--muted:#5b6b6a;--line:#dfe5e3;--accent:#1f6f5c;--accent-soft:#e3f1ec;
--pos:#1f6f5c;--neg:#a5402d;--warn-bg:#fff6e5;--warn-line:#e2b25c;--code:#eef2f0}
@media (prefers-color-scheme:dark){:root{--bg:#111716;--surface:#18201f;--ink:#e3ebe9;--muted:#9fb0ad;--line:#2b3735;--accent:#6fc7ad;
--accent-soft:#1d2f2a;--pos:#7fd3b8;--neg:#f0907c;--warn-bg:#2a2416;--warn-line:#8a6d2f;--code:#1f2928}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,system-ui,sans-serif}
a{color:var(--accent)}code,pre{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.85em}
code{background:var(--code);padding:.1em .35em;border-radius:4px}
pre{background:var(--code);padding:16px;border-radius:8px;overflow-x:auto}pre code{background:none;padding:0}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
.top{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.nav{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:56px;flex-wrap:wrap}
.brand{font-weight:700;text-decoration:none;color:var(--ink)}
nav{display:flex;gap:16px;flex-wrap:wrap}nav a{text-decoration:none;color:var(--muted);font-size:.92rem}nav a:hover{color:var(--accent)}
section{padding:40px 0 8px}h1{font-size:clamp(1.9rem,4vw,2.8rem);line-height:1.15;margin:.2em 0 .4em}
h2{font-size:1.6rem;margin:0 0 .5em}h3{font-size:1.1rem;margin:1.4em 0 .5em}
.eyebrow{color:var(--accent);font-weight:600;letter-spacing:.02em;margin:0}.lead{font-size:1.1rem;color:var(--muted);max-width:760px}
.notice{background:var(--warn-bg);border-left:4px solid var(--warn-line);padding:12px 16px;border-radius:6px;max-width:760px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:24px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px}
.card-label{color:var(--muted);font-size:.85rem}.card-value{font-size:1.35rem;font-weight:700;margin:.2em 0}.card-note{color:var(--muted);font-size:.85rem}
.flow{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}
.step{display:flex;gap:12px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px}
.step>div{min-width:0}.step code{overflow-wrap:anywhere;display:inline-block}
.step h3{margin:0 0 .2em}.step p{margin:0 0 .5em;color:var(--muted);font-size:.92rem}
.step-n{flex:none;width:28px;height:28px;border-radius:50%;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-weight:700}
.grid2>*,.panel>*,.gallery>*,.cards>*{min-width:0}code{overflow-wrap:anywhere}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:32px}@media (max-width:860px){.grid2{grid-template-columns:1fr}}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface);margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--accent-soft);font-weight:600}tbody tr:last-child td{border-bottom:none}table.compact td,table.compact th{padding:7px 10px}
td:not(:first-child){font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}.strong{font-weight:700}.sig{color:var(--muted);font-size:.8em}.pending{color:var(--muted);font-style:italic}
.caveat{color:var(--muted);font-size:.92rem}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 12px}
.tab{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:6px 14px;border-radius:999px;cursor:pointer}
.tab.active{background:var(--accent);border-color:var(--accent);color:var(--surface)}
.panel{display:none;grid-template-columns:1fr 1fr;gap:16px}.panel.active{display:grid}@media (max-width:860px){.panel.active{grid-template-columns:1fr}}
figure{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px}
figure img{width:100%;height:auto;display:block;border-radius:6px;background:#fff}figcaption{color:var(--muted);font-size:.85rem;padding-top:6px}
.gallery{display:grid;gap:16px;margin-top:16px}
.foot{color:var(--muted);font-size:.85rem;padding:32px 16px 48px;border-top:1px solid var(--line);margin-top:40px}
'''


def main():
    OUT.mkdir(exist_ok=True)
    copy_assets()
    (OUT / 'assets/style.css').write_text(CSS.strip() + '\n', encoding='utf-8')
    (OUT / 'index.html').write_text(page(*gather()), encoding='utf-8')
    (OUT / '.nojekyll').write_text('', encoding='utf-8')
    size = sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    print(f'Site written to {OUT} ({size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()

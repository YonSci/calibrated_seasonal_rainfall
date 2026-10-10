r"""Score the platform and the official outlooks (EMI, ICPAC) against CHIRPS observations.

Runs after the season's verification (verify_frozen_2026.py) and the official-outlook comparison.
Each outlook is scored against observations for its own target window, with the observed tercile
taken from the same CHIRPS 1993-2025 per-cell terciles the platform verification uses:

* favoured-category outcome (all three): where an outlook favours a category (leading tercile >= 40%,
  the display rule), the area share where that category was observed ("hit"), where the opposite
  outer category was observed, and the climatological chance of the favoured category there;
* RPSS against climatology (platform and EMI, which publish all three probabilities), on identical
  cells. ICPAC publishes only the favoured category and its interval, so no RPS is computed for it
  (the other two probabilities are not inferred).

One season, one year: these are descriptive single-season scores, not evidence of general skill.
The official reference periods are not stated; observed categories use CHIRPS 1993-2025.

    python scripts\verify_external_forecasts.py --comparison outputs\operational_2026_fmam_feb\comparisons ^
        --verification-root outputs\verification_2026_fmam_feb --processed-root data\processed --tag init02 --season FMAM ^
        --year 2026 --domain-mask data\masks\fmam_coverage_chirps_v2_1993_2025_v1.nc

The operational runner calls this as the external_verify stage (run_operational.py --compare-external)
once the season has been verified.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from compare_external_forecasts import CATS, COLOURS, NAMES, favoured, months, read_json, repo_path, write_json, _boundary, _draft, interior_contour
from verify2026_math import probability_losses

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = {'hit': '#2a78d6', 'near_other': '#e2b25c', 'opposite': '#b03a24'}
OUTCOME_NAMES = {'hit': 'favoured category observed', 'near_other': 'near normal vs an outer category',
                 'opposite': 'opposite outer category observed'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def category(x, q1, q2):
    return np.where(x < q1, 0, np.where(x > q2, 2, 1))


def outcome(fav, obs):
    """Favoured category (name) vs observed category (index) for one cell."""
    o = CATS[obs]
    if fav == o:
        return 'hit'
    if {fav, o} == {'above', 'below'}:
        return 'opposite'
    return 'near_other'


def season_observations(vr, tag, season, processed_root, year, ref_years, window, platform_window, native):
    """Observed tercile category (-1 where not scored), climatology probabilities and the files used.

    The platform's own season reads the verification fields directly. Another window (ICPAC MAM inside
    FMAM) is built from the verified monthly totals and the historical monthly CHIRPS totals of the
    same months, with terciles computed the way verify_frozen_2026.py computes them.
    """
    import xarray as xr
    fields = vr / f'results/{season}/verification_fields.nc'
    with xr.open_dataset(fields) as f:
        f = f.load()
    pv = f.probability_support.values == 1
    if window == platform_window:
        with xr.open_dataset(native) as d:
            clim = d.climatology_probability.transpose('lat', 'lon', 'category').values
        y = np.where(pv, f.observed_category.values.astype(int), -1)
        return dict(y=y, clim=clim, support=pv, files={repo_path(fields): sha(fields)}, basis=f'verified {season} observations')
    names = [m.split()[0] for m in window]
    obs_files = [vr / f'observations/{m}/chirps_{year}_common.nc' for m in names]
    hist = {m: [Path(processed_root) / f'{tag}_{m}/chirps_{y}_common.nc' for y in ref_years] for m in names}
    missing = [str(p) for p in obs_files + [p for v in hist.values() for p in v] if not p.is_file()]
    if missing:
        return dict(unavailable='observations_for_official_window_missing', detail=missing[:3])
    obs = 0.0
    for p in obs_files:
        with xr.open_dataset(p) as d:
            if not (np.allclose(d.lat, f.lat) and np.allclose(d.lon, f.lon)):
                raise ValueError(f'{p}: grid differs from the verification grid')
            obs = obs + d.precip_season.values.astype(float)
    h = np.zeros((len(ref_years), f.sizes['lat'], f.sizes['lon']))
    for m in names:
        for i, p in enumerate(hist[m]):
            with xr.open_dataset(p) as d:
                h[i] += d.precip_season.transpose('year', 'lat', 'lon').values[0].astype(float)
    ok = pv & np.isfinite(obs) & np.isfinite(h).all(0)
    q1, q2 = np.quantile(h, [1 / 3, 2 / 3], axis=0)
    yh = category(h, q1, q2)
    clim = np.stack([(yh == k).mean(0) for k in range(3)], -1)
    y = np.where(ok, category(np.nan_to_num(obs), q1, q2), -1)
    files = {repo_path(p): sha(p) for p in [*obs_files, *[p for v in hist.values() for p in v], fields]}
    return dict(y=y, clim=clim, support=ok, files=files,
                basis=f'sum of verified monthly totals ({", ".join(names)}); terciles from the same months {ref_years[0]}-{ref_years[-1]}')


def score(fav, obs, clim, w, mask, probs=None, rps_clim=None, area=None, issued=None):
    """Coverage, favoured-category outcome shares and (with probabilities) RPSS.

    area: the evaluation area; mask: its cells with usable observations (and any extra restriction);
    issued: cells where the provider issued an outlook. Coverage fields, all area-weighted:
      observation_coverage  share of the area with usable CHIRPS observations,
      outlook_coverage      share of those cells where the provider issued an outlook,
      favoured_coverage     share of those cells where its favoured-category rule selects a category.
    Outcome shares (hit / near_other / opposite) are within the favoured cells; observed_fractions and RPSS
    are over the cells with an outlook.
    """
    base = mask & (obs >= 0)
    issued = np.ones(base.shape, bool) if issued is None else issued
    cells = base & issued
    if not cells.any():
        return None
    wa = lambda m: float(w[m].sum())
    shown = cells & np.isin(fav, CATS)
    row = dict(cells=int(cells.sum()), observation_coverage=wa(base) / wa(area) if area is not None and area.any() else None,
               outlook_coverage=wa(cells) / wa(base), favoured_coverage=wa(shown) / wa(base),
               observed_fractions={c: wa(cells & (obs == k)) / wa(cells) for k, c in enumerate(CATS)})
    if shown.any():
        oc = np.full(fav.shape, '', dtype=object)
        for i, j in zip(*np.nonzero(shown)):
            oc[i, j] = outcome(fav[i, j], obs[i, j])
        row.update({f'{k}_share': wa(shown & (oc == k)) / wa(shown) for k in OUTCOMES})
        chance = np.zeros(fav.shape)
        for k, c in enumerate(CATS):
            chance = np.where(fav == c, clim[..., k], chance)
        row['chance_of_favoured'] = float(np.average(chance[shown], weights=w[shown]))
        row['favoured_categories'] = {c: wa(shown & (fav == c)) / wa(shown) for c in CATS if (shown & (fav == c)).any()}
    if probs is not None:
        _, rps, _ = probability_losses(np.where(cells[..., None], probs, np.nan), np.where(cells, obs, -1))
        ok = cells & np.isfinite(rps) & np.isfinite(rps_clim)
        r, rc = float(np.average(rps[ok], weights=w[ok])), float(np.average(rps_clim[ok], weights=w[ok]))
        row.update(rps=r, climatology_rps=rc, rpss=1 - r / rc if rc > 0 else None)
    return row


RULES = {'Platform': 'untied leading tercile probability of at least 40%', 'EMI': 'untied leading tercile probability of at least 40%',
         'ICPAC': 'the dominant category ICPAC printed, including its 33–40% intervals'}


def verify_external(comparison_root, verification_root, processed_root, tag, year, ref_years, season, domain_mask, out=None, extra_domains=None):
    import xarray as xr
    import external_forecasts as ef
    base = Path(comparison_root)
    out = Path(out) if out else base / 'observed'
    vr = Path(verification_root)
    comp_file, rec_file = base / 'comparison/comparison.json', base / 'sources/official_records.json'
    comp, recs = read_json(comp_file), read_json(rec_file)['records']
    manifest = read_json(base / 'sources/source_manifest.json')
    plat = comp['platform']
    native = Path(plat['native_forecast']) if Path(plat['native_forecast']).is_absolute() else ROOT / plat['native_forecast']
    fields_file = vr / f'results/{season}/verification_fields.nc'
    with xr.open_dataset(fields_file) as f:
        f = f.load()
    with xr.open_dataset(native) as d:
        region = d.region_mask.values == 1
        if not (np.allclose(d.lat, f.lat) and np.allclose(d.lon, f.lon)):
            raise ValueError('Verification grid differs from the compared forecast grid')
    lat, lon = f.lat.values.astype(float), f.lon.values.astype(float)
    w = np.repeat(np.cos(np.deg2rad(lat))[:, None], len(lon), 1)
    with xr.open_dataset(domain_mask) as m:
        domain = m.season_domain.values == 1
    if sha(domain_mask) != comp['inputs']['domain_mask_sha256']:
        raise ValueError('The domain mask differs from the one the comparison used; rerun the comparison first')
    pv = f.probability_support.values == 1
    areas = {'all_ethiopia': ('All Ethiopia', region), 'season_domain': (plat['areas']['season_domain'], region & domain)}
    for view, path in (extra_domains or {}).items():                  # further presentation domains, by view id
        with xr.open_dataset(path) as m:
            areas[view] = (plat['areas'].get(view, m.attrs.get('view_label', view)), region & (m.season_domain.values == 1))
        if sha(path) != (comp['inputs'].get('extra_domain_masks_sha256') or {}).get(view):
            raise ValueError(f'The {view} mask differs from the one the comparison used; rerun the comparison first')
    pwin = months(plat['target_start'], plat['target_end'])
    cache, rows, maps = {}, [], {}

    def obs_for(start, end):
        win = months(start, end)
        key = tuple(win)
        if key not in cache:
            cache[key] = season_observations(vr, tag, season, processed_root, year, ref_years, win, pwin, native)
        return win, cache[key]

    def add(source_id, provider, label, win, o, fav, issued, probs=None, rps_clim=None, extra=None):
        for key, (name, amask) in areas.items():
            m = amask & o['support']
            r = score(fav, o['y'], o['clim'], w, m, probs, rps_clim, area=amask, issued=issued)
            if r:
                rows.append(dict(source_id=source_id, provider=provider, label=label, window=[win[0], win[-1]], area_key=key, area=name,
                                 favoured_rule=RULES[provider], **r, **(extra(amask & o['support']) if extra else {})))

    # Platform: the frozen season forecast against the verified season observations.
    pwin_, po = obs_for(plat['target_start'], plat['target_end'])
    pp = f.shared_blend_probability.transpose('lat', 'lon', 'category').values
    pfav = np.full(pv.shape, 'unknown', dtype=object)
    for i, j in zip(*np.nonzero(pv)):
        pfav[i, j] = favoured(list(pp[i, j]), plat['minimum_leading_probability'])
    add('platform', 'Platform', plat['label'], pwin_, po, pfav, pv, pp, f.climatology_rps.values)
    maps['platform'] = (pfav, po)

    # EMI: zone probabilities, constant over each digitized zone (or reviewed rainfall region).
    zone_recs = [r for r in recs if r['representation'] == 'zone_tercile_probabilities' and r['extraction_status'] == 'validated']
    layer = next((l for l in manifest.get('reference_layers', []) if l.get('kind') == 'region_map' and l.get('status') == 'validated'), None)
    for r in zone_recs:
        zone = r['source_locator']['zone_label']
        if r.get('geometry_file') and (base / 'sources' / r['geometry_file']).is_file():
            zg = np.array(read_json(base / 'sources' / r['geometry_file'])['zone'], dtype=object)
            zm = zg == zone
        elif layer and zone in layer['region_names']:
            with xr.open_dataset(ROOT / layer['mask']) as rg:
                zm = rg.region.values.astype(int) == list(layer['region_names']).index(zone) + 1
        else:
            continue                                       # arrow-only zone: no area to score
        r['_mask'] = zm
    zone_recs = [r for r in zone_recs if '_mask' in r]
    if zone_recs:
        win, eo = obs_for(zone_recs[0]['target_start'], zone_recs[0]['target_end'])
        if 'unavailable' not in eo:
            efav = np.full(pv.shape, 'noforecast', dtype=object)   # outside EMI's zones (e.g. its excluded dry areas): no outlook
            ep = np.full(pp.shape, np.nan)
            union = np.zeros(pv.shape, bool)
            for r in zone_recs:
                p = [r['probabilities'][c] for c in CATS]
                efav[r['_mask']] = favoured(p, plat['minimum_leading_probability'])
                ep[r['_mask']] = p
                union |= r['_mask']
            # EMI's zones: the platform is also scored on exactly these cells for a like-for-like RPSS.
            add('emi', 'EMI', next(s['season_label'] for s in manifest['sources'] if s['source_id'] == zone_recs[0]['source_id']),
                win, eo, efav, union, ep, f.climatology_rps.values if win == pwin else None)
            if win == pwin:      # the platform on exactly EMI's cells, for a like-for-like RPSS
                add('platform_on_emi_zones', 'Platform', plat['label'] + ' (on the EMI zones)', pwin_, po, pfav, pv & union, pp, f.climatology_rps.values)
            for r in zone_recs:
                zone = r['source_locator']['zone_label']
                zarea = r['_mask'] & region
                for sid, prov, fav, prb, o, iss in [('emi', 'EMI', efav, ep, eo, union), ('platform', 'Platform', pfav, pp, po, pv)]:
                    s = score(fav, o['y'], o['clim'], w, zarea & o['support'], prb, f.climatology_rps.values if o is po or win == pwin else None,
                              area=zarea, issued=iss)
                    if s:
                        rows.append(dict(source_id=sid, provider=prov, label=f'EMI zone {zone}', window=[win[0], win[-1]] if sid == 'emi' else [pwin_[0], pwin_[-1]],
                                         area_key='zone', area=f'EMI zone {zone}', zone=zone, official=r['probabilities'] if sid == 'emi' else None,
                                         favoured_rule=RULES[prov], **s))
            maps['emi'] = (efav, eo, union)

    # ICPAC: favoured category only (dominant-category map), scored against its own window.
    for r in [r for r in recs if r['representation'] == 'dominant_category_map' and r['extraction_status'] == 'validated']:
        g = read_json(base / 'sources' / r['grid_file'])
        cat, st = np.array(g['category'], dtype=object), np.array(g['state'], dtype=object)
        ifav = np.where(st == 'forecast', cat, np.where(st == 'no_forecast_shown', 'noforecast', 'unknown'))
        low = np.array([[np.nan if v is None else v for v in row] for row in g['low']])
        shown_icpac = st == 'forecast'

        def interval_note(cells):
            # How much of ICPAC's favoured area rests on its lowest (33–40%) printed interval: below the 40% rule.
            fc = cells & shown_icpac & (io['y'] >= 0)
            return dict(favoured_below_40_share=float(w[fc & (low < 40)].sum() / w[fc].sum()) if fc.any() else None)
        win, io = obs_for(r['target_start'], r['target_end'])
        label = next(s['season_label'] for s in manifest['sources'] if s['source_id'] == r['source_id'])
        if 'unavailable' in io:
            rows.append(dict(source_id=r['source_id'], provider='ICPAC', label=label, window=[win[0], win[-1]], unavailable=io['unavailable']))
            continue
        add(r['source_id'], 'ICPAC', label, win, io, ifav, shown_icpac, extra=interval_note)
        for z in zone_recs:
            zarea = z['_mask'] & region
            s = score(ifav, io['y'], io['clim'], w, zarea & io['support'], area=zarea, issued=shown_icpac)
            if s:
                rows.append(dict(source_id=r['source_id'], provider='ICPAC', label=f'EMI zone {z["source_locator"]["zone_label"]}', window=[win[0], win[-1]],
                                 area_key='zone', area=f'EMI zone {z["source_locator"]["zone_label"]}', zone=z['source_locator']['zone_label'],
                                 favoured_rule=RULES['ICPAC'], **s, **interval_note(zarea & io['support'])))
        maps['icpac'] = (ifav, io, label, win)

    tmp = ef.staging(out)
    figure = 'observed_comparison.png'
    observed_map(tmp / figure, lon, lat, region, domain, maps, plat, zone_recs, rows)
    side = 'forecasts_and_observed.png'
    side_by_side_map(tmp / side, lon, lat, region, domain, maps, plat, zone_recs)
    inputs = dict(comparison_sha256=sha(comp_file), official_records_sha256=sha(rec_file), native_sha256=sha(native), domain_mask_sha256=sha(domain_mask),
                  extra_domain_masks_sha256={v: sha(p) for v, p in sorted((extra_domains or {}).items())},
                  observations={k: v for o in cache.values() if 'files' in o for k, v in o['files'].items()})
    write_json(tmp / 'observed_verification.json', dict(
        created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), season=season, year=year,
        reference_years=[ref_years[0], ref_years[-1]], inputs=inputs, rows=rows, map=figure, side_by_side_map=side,
        areas={k: v[0] for k, v in areas.items()}, favoured_rules=RULES,
        windows={', '.join(k): v.get('basis', v.get('unavailable')) for k, v in cache.items()},
        notes=['Single season: descriptive scores for one year, not evidence of general skill.',
               'Each outlook is scored against observations for its own target window; the observed tercile uses CHIRPS '
               f'{ref_years[0]}-{ref_years[-1]} terciles per 0.25° cell (official reference periods are not stated).',
               'Favoured category: for the platform and EMI, the untied leading tercile where it reaches 40% (the map display rule); for ICPAC, '
               'the dominant category ICPAC printed, including its 33–40% intervals (the share resting on 33–40% is reported). "Chance" is the '
               'climatological probability of the favoured category over the same cells (about one in three).',
               'Coverage: observation coverage is the share of the area with usable CHIRPS observations; outlook coverage the share of those '
               'cells where the provider issued an outlook (ICPAC grey areas and EMI\'s excluded dry areas have none); favoured-category '
               'coverage the share where its rule selects a category. Match percentages are within the favoured cells.',
               'RPSS: ranked probability skill score against the CHIRPS climatology, on identical cells; ICPAC publishes only the '
               'favoured category and its interval, so no RPSS is computed for ICPAC.',
               'EMI zone probabilities are applied uniformly over each digitized zone.']))
    ef.publish(tmp, out)
    return out / 'observed_verification.json'


def observed_map(path, lon, lat, region, domain, maps, plat, zone_recs, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    ext = [lon[0] - .125, lon[-1] + .125, lat[0] - .125, lat[-1] + .125]
    ocmap = ListedColormap([COLOURS[c] for c in CATS])
    keys = list(OUTCOMES) + ['weak', 'noforecast']
    kcmap = ListedColormap([OUTCOMES[k] for k in OUTCOMES] + [COLOURS['weak'], COLOURS['noforecast']])

    def outcome_grid(fav, o):
        z = np.full(fav.shape, np.nan)
        for i, j in zip(*np.nonzero(o['y'] >= 0)):
            v = fav[i, j]
            z[i, j] = keys.index(outcome(v, o['y'][i, j])) if v in CATS else keys.index('noforecast') if v == 'noforecast' else keys.index('weak')
        return z

    def frame(ax, title, zones=False):
        ax.set_facecolor(COLOURS['unknown'])
        _boundary(ax)
        interior_contour(ax, lon, lat, domain & region, region, colors='#446761', linewidths=.8)
        if zones:
            for r in zone_recs:
                interior_contour(ax, lon, lat, r['_mask'], region, colors='black', linewidths=1.1)
        ax.set_xlim(ext[:2]); ax.set_ylim(ext[2:]); ax.set_aspect('equal'); ax.tick_params(labelsize=7)
        ax.set_title(title, fontsize=9.5)

    panels = []
    pfav, po = maps['platform']
    plabel = plat['label']
    panels.append(('obs', po, f'Observed {plabel} tercile (CHIRPS)'))
    panels.append(('out', (pfav, po), f'Platform {plat["label"]} vs observed'))
    if 'emi' in maps:
        efav, eo, _ = maps['emi']
        panels.append(('out_z', (efav, eo), 'EMI zones vs observed ' + plabel))
    if 'icpac' in maps:
        ifav, io, ilabel, win = maps['icpac']
        wl = win[0] if len(win) == 1 else f'{win[0].split()[0]}–{win[-1]}'
        if win != months(plat['target_start'], plat['target_end']):
            panels.append(('obs', io, f'Observed {wl} tercile (CHIRPS)'))
        panels.append(('out', (ifav, io), f'{ilabel} (ICPAC) vs observed {wl}'))
    n = len(panels)
    cols = 3 if n > 4 else n
    nrows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(4.7 * cols, 4.1 * nrows + .9), squeeze=False)
    for ax, (kind, data, title) in zip(axes.flat, panels):
        if kind == 'obs':
            ax.imshow(np.where(data['y'] >= 0, data['y'], np.nan).astype(float), origin='lower', extent=ext, cmap=ocmap, vmin=-.5, vmax=2.5, interpolation='nearest')
        else:
            ax.imshow(outcome_grid(*data), origin='lower', extent=ext, cmap=kcmap, vmin=-.5, vmax=len(keys) - .5, interpolation='nearest')
        frame(ax, title, zones=kind == 'out_z')
    for ax in list(axes.flat)[n:]:
        ax.axis('off')
    if n < nrows * cols:                                  # spare panel: the headline numbers per area
        ax = list(axes.flat)[n]
        lines = []
        for key in ('all_ethiopia', 'season_domain'):
            rs = [r for r in rows if r.get('area_key') == key and r['source_id'] != 'platform_on_emi_zones' and 'hit_share' in r]
            if not rs:
                continue
            lines.append(rs[0]['area'])
            for r in rs:
                lines.append(f'  {r["provider"]:<8} hit {r["hit_share"]:.0%}  opposite {r["opposite_share"]:.0%}'
                             + (f'  RPSS {r["rpss"]:+.2f}' if r.get('rpss') is not None else '') + f'  ({r["window"][0][:3]}–{r["window"][1]}'
                             + (f'; outlook on {r["outlook_coverage"]:.0%}' if r['outlook_coverage'] < .995 else '') + ')')
            lines.append('')
        lines.append('hit: favoured category observed, as a share of the')
        lines.append('area where the outlook favours one (chance about 33%)')
        ax.text(0, .95, '\n'.join(lines), va='top', ha='left', fontsize=8, family='monospace', transform=ax.transAxes)
    fig.legend(handles=[Patch(color=COLOURS[c], label='observed ' + NAMES[c]) for c in CATS] +
               [Patch(color=OUTCOMES[k], label=OUTCOME_NAMES[k]) for k in OUTCOMES] +
               [Patch(facecolor='white', edgecolor='grey', label='no favoured category (<40%)'),
                Patch(color=COLOURS['noforecast'], label='no outlook (ICPAC grey; outside the EMI zones)')],
               loc='lower center', ncol=4, fontsize=8, frameon=False)
    fig.suptitle(f'Outlooks against CHIRPS observations — {plat["label"]} (single season; black lines in the EMI panel: EMI zones)', fontsize=11)
    fig.subplots_adjust(left=.03, right=.99, bottom=.1 if nrows > 1 else .2, top=.92, wspace=.06, hspace=.14)
    _draft(fig, True)
    fig.savefig(path, dpi=130, facecolor='white')
    plt.close(fig)


def side_by_side_map(path, lon, lat, region, domain, maps, plat, zone_recs):
    """The outlooks' favoured categories next to the observed CHIRPS terciles, in the same colours.

    Top row: platform, EMI and ICPAC as published (favoured category at >= 40%). Bottom row: the observed
    tercile for the season and, when ICPAC's window differs, for ICPAC's window, under the ICPAC panel.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    ext = [lon[0] - .125, lon[-1] + .125, lat[0] - .125, lat[-1] + .125]
    keys = [*CATS, 'weak', 'noforecast']
    cmap = ListedColormap([COLOURS[k] for k in keys[:-1]] + ['white'])   # no outlook: white, hatched (grey is near normal)
    pwin = months(plat['target_start'], plat['target_end'])
    span = lambda win: win[0] if len(win) == 1 else f'{win[0].split()[0]}–{win[-1]}'

    def code(fav, support):
        z = np.full(fav.shape, np.nan)
        for i, j in zip(*np.nonzero(support)):
            v = fav[i, j]
            z[i, j] = keys.index(v) if v in keys else keys.index('weak')
        return z

    def frame(ax, title, zones=False):
        ax.set_facecolor(COLOURS['unknown'])
        _boundary(ax)
        interior_contour(ax, lon, lat, domain & region, region, colors='#446761', linewidths=.8)
        if zones:
            for r in zone_recs:
                interior_contour(ax, lon, lat, r['_mask'], region, colors='black', linewidths=1.1)
        ax.set_xlim(ext[:2]); ax.set_ylim(ext[2:]); ax.set_aspect('equal'); ax.tick_params(labelsize=7)
        ax.set_title(title, fontsize=9.5)

    pfav, po = maps['platform']
    support = po['y'] >= 0
    top = [(code(pfav, support), f'Platform {plat["label"]}', False)]
    if 'emi' in maps:
        efav, _, _ = maps['emi']
        top.append((code(efav, support), f'EMI {span(pwin)} (zone values)', True))
    if 'icpac' in maps:
        ifav, io, ilabel, iwin = maps['icpac']
        top.append((code(ifav, support), f'ICPAC {span(iwin)}', False))
    obs = lambda o: np.where(o['y'] >= 0, o['y'], np.nan).astype(float)
    bottom = [(obs(po), f'Observed {span(pwin)} (CHIRPS)', False)]
    if 'icpac' in maps and iwin != pwin:
        bottom.append((obs(io), f'Observed {span(iwin)} (CHIRPS), ICPAC\'s period', False))
    cols = len(top)
    fig, axes = plt.subplots(2, cols, figsize=(4.7 * cols, 9.2), squeeze=False)
    for ax, (z, title, zones) in zip(axes[0], top):
        ax.imshow(z, origin='lower', extent=ext, cmap=cmap, vmin=-.5, vmax=len(keys) - .5, interpolation='nearest')
        none = z == keys.index('noforecast')
        if none.any():
            ax.contourf(lon, lat, none.astype(float), levels=[.5, 1.5], colors='none', hatches=['////'])
        frame(ax, title + ': favoured category', zones)
    slots = [0, cols - 1] if len(bottom) == 2 else [0]
    for k, (z, title, zones) in zip(slots, bottom):
        axes[1, k].imshow(z, origin='lower', extent=ext, cmap=cmap, vmin=-.5, vmax=len(keys) - .5, interpolation='nearest')
        frame(axes[1, k], title + ': tercile', zones)
    for k in range(cols):
        if k not in slots:
            axes[1, k].axis('off')
    if cols > 2 and len(bottom) == 2:
        axes[1, 1].text(.5, .5, 'Same colours above and below:\nthe favoured category of each\noutlook (top) and the tercile\nthat was observed (bottom).\n\nEach outlook is shown with\nthe observations for its own\nperiod: platform and EMI\n' + span(pwin) + ', ICPAC ' + span(iwin) + '.',
                        ha='center', va='center', fontsize=9, transform=axes[1, 1].transAxes)
    fig.legend(handles=[Patch(color=COLOURS[c], label=NAMES[c]) for c in CATS] +
               [Patch(facecolor='white', edgecolor='grey', label='no favoured category (<40%)'),
                Patch(facecolor='white', edgecolor='#555', hatch='////', label='no outlook (ICPAC grey; outside the EMI zones)')],
               loc='lower center', ncol=5, fontsize=8.5, frameon=False)
    fig.suptitle(f'Official outlooks, the platform forecast and the observed CHIRPS terciles — {plat["label"]}', fontsize=11)
    fig.subplots_adjust(left=.03, right=.99, bottom=.07, top=.92, wspace=.06, hspace=.12)
    fig.savefig(path, dpi=130, facecolor='white')
    plt.close(fig)


def main():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--comparison', required=True, help='The cycle comparison root (with sources/ and comparison/)')
    ap.add_argument('--verification-root', required=True)
    ap.add_argument('--processed-root', default='data/processed')
    ap.add_argument('--tag', required=True)
    ap.add_argument('--season', required=True)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--domain-mask', required=True)
    ap.add_argument('--extra-domain', nargs=2, action='append', default=[], metavar=('VIEW', 'MASK'),
                    help='A further domain view and its mask (repeatable)')
    ap.add_argument('--reference-years', type=int, nargs=2, default=[1993, 2025])
    a = ap.parse_args()
    r = lambda p: Path(p) if Path(p).is_absolute() else ROOT / p
    print(verify_external(r(a.comparison), r(a.verification_root), r(a.processed_root), a.tag, a.year,
                          list(range(a.reference_years[0], a.reference_years[1] + 1)), a.season, r(a.domain_mask),
                          extra_domains={v: r(m) for v, m in a.extra_domain}))


if __name__ == '__main__':
    main()

r"""Compare the platform's native forecast with standardized official outlook records.

Facts first: every metric carries its own eligibility (available / pending_review /
unavailable) with a reason, and every finding records the areas, favoured categories,
relationship, numbers, comparison basis, limitations and evidence identifiers. The
interpretation step turns these findings into sentences.

Platform side: the native forecast NetCDF the runner selected (info["sources"][season]),
probabilities read by their category labels. Area means are area-weighted means of local
grid-cell probabilities ("area mean of local probabilities"), not probabilities of the
area-mean rainfall.

    python scripts\compare_external_forecasts.py --sources outputs\operational_2026_ondj\comparisons\sources ^
        --native outputs\final_shared_blend\init09_ONDJ\2026\forecast_2026.nc ^
        --domain-mask data\masks\init09_ONDJ_regime_domain.nc --registry config\external_forecasts\ondj_2026_27.json ^
        --out outputs\operational_2026_ondj\comparisons\comparison
"""
import argparse
import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CATS = ('below', 'near', 'above')
NAMES = {'below': 'below normal', 'near': 'near normal', 'above': 'above normal', 'weak': 'no clear category'}


def repo_path(p):
    p = Path(p).resolve()
    return (p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).as_posix()


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding='utf-8', newline='')


def favoured(p, minimum):
    """Favoured category under the display rule: the leading category if it reaches `minimum`."""
    if p is None or any(v is None or not np.isfinite(v) for v in p):
        return 'unknown'
    order = np.argsort(p)[::-1]
    if abs(p[order[0]] - p[order[1]]) < 1e-9:     # tied leaders: no unique favoured category
        return 'weak'
    k = int(order[0])
    return CATS[k] if p[k] >= minimum else 'weak'


def file_sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def input_fingerprint(native_path, domain_mask, registry, sources, minimum):
    """Everything a published comparison depends on; build_site re-checks it before publishing.

    sources: {source_id: {sha256, extraction_status, content_sha256}}.
    """
    return dict(native_sha256=file_sha(native_path), domain_mask_sha256=file_sha(domain_mask),
                registry_sha256=hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest(),
                minimum_leading_probability=minimum, sources=sources)


def manifest_states(manifest):
    return {s['source_id']: dict(sha256=s.get('sha256'), extraction_status=s.get('extraction', {}).get('status'),
                                 content_sha256=s.get('extraction', {}).get('content_sha256'))
            for s in manifest['sources'] if s.get('sha256')}


HALF_WIDTHS = (0.25, 0.5, 0.75, 1.0)
CENTRE_SHIFTS = (-0.5, -0.25, 0.0, 0.25, 0.5)


def relationship(platform, official):
    if 'unknown' in (platform, official):
        return 'unknown'
    if 'weak' in (platform, official):
        return 'weak_signal'
    if platform == official:
        return 'same_favoured_category'
    if {platform, official} == {'above', 'below'}:
        return 'opposing_favoured_categories'
    return 'near_versus_other'


def months(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f'{date(y, m, 1):%b %Y}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def window_limitation(platform, rec):
    a, b = months(platform['target_start'], platform['target_end']), months(rec['target_start'], rec['target_end'])
    if a == b:
        return None
    return dict(code='target_window_mismatch', platform_months=a, official_months=b,
                only_platform=[m for m in a if m not in b], only_official=[m for m in b if m not in a])


def load_native(path):
    import xarray as xr
    with xr.open_dataset(path) as d:
        d = d.load()
    labels = [str(c) for c in d.category.values]
    if sorted(labels) != sorted(CATS):
        raise ValueError(f'{path}: unexpected category labels {labels}')
    p = d.blend_probability.transpose('lat', 'lon', 'category').values[..., [labels.index(c) for c in CATS]]
    eligible = (d.probability_eligible.values == 1) & (d.region_mask.values == 1) & np.isfinite(p).all(-1)
    return dict(lat=d.lat.values.astype(float), lon=d.lon.values.astype(float), p=p, eligible=eligible,
                anomaly=d.corrected_mean_anomaly.values, sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def area_mean(p, mask, w):
    if not mask.any():
        return None
    ww = w[mask]
    return [float(np.average(p[..., k][mask], weights=ww)) for k in range(3)]


def compare(sources_dir, native_path, domain_mask, registry, out, minimum=0.40, domain_label=None):
    import xarray as xr
    import external_forecasts as ef
    sources_dir, out = Path(sources_dir), Path(out)
    tmp = ef.staging(out)
    (tmp / 'maps').mkdir(parents=True)
    recs = read_json(sources_dir / 'official_records.json')['records']
    manifest = read_json(sources_dir / 'source_manifest.json')
    nat = load_native(native_path)
    with xr.open_dataset(domain_mask) as m:
        if not (np.allclose(m.lat.values, nat['lat']) and np.allclose(m.lon.values, nat['lon'])):
            raise ValueError('Domain mask grid differs from the native forecast grid')
        domain = (m.season_domain.values == 1) & nat['eligible']
        domain_label = domain_label or m.attrs.get('view_label', 'season rainfall domain')
    lat2 = np.repeat(nat['lat'][:, None], len(nat['lon']), 1)
    w = np.cos(np.deg2rad(lat2))
    areas = {'all_ethiopia': ('All Ethiopia', nat['eligible']), 'season_domain': (domain_label, domain)}
    platform = registry['platform']
    metrics, findings = [], []
    plat_ev = 'platform_forecast_' + platform['target'].lower()

    def metric(**kw):
        metrics.append(kw)

    # ------------------------------------------------------------------ EMI zone records
    for r in [r for r in recs if r['representation'] == 'zone_tercile_probabilities']:
        validated = r['extraction_status'] == 'validated'
        state = 'available' if validated else 'pending_review'
        zone = r['source_locator']['zone_label']
        lim = ['exact_zone_alignment_pending', 'official_reference_period_unknown'] if not r.get('reference_period') else ['exact_zone_alignment_pending']
        wl = window_limitation(platform, r)
        if wl:
            lim.append(wl)
        metric(metric='display_official_probabilities', source_id=r['source_id'], zone=zone, status=state,
               value=r['probabilities'] if validated else None,
               reason=None if validated else 'transcription_awaiting_review', draft_value=None if validated else r['probabilities'],
               evidence_ids=r['evidence_ids'])
        a = r.get('anchor')
        neighbourhood = None
        off_p = [r['probabilities'][c] for c in CATS]
        off_cat = favoured(off_p, minimum)
        lon2 = np.repeat(nat['lon'][None], len(nat['lat']), 0)
        box_at = lambda x, y, h: (np.abs(lat2 - y) <= h) & (np.abs(lon2 - x) <= h) & nat['eligible']
        sensitivity = None
        if a:
            half = a.get('uncertainty_deg', 0.5)
            box = box_at(a['lon'], a['lat'], half)
            mean = area_mean(nat['p'], box, w)
            neighbourhood = dict(center=[a['lon'], a['lat']], half_width_deg=half, cells=int(box.sum()), mean_local_probabilities=mean,
                                 domain_share=float((box & domain).sum() / box.sum()) if box.any() else 0.0)
            # Bounded sensitivity: other neighbourhood sizes and shifted arrow-tip positions.
            rels = {}
            for h in HALF_WIDTHS:
                for dx in CENTRE_SHIFTS:
                    for dy in CENTRE_SHIFTS:
                        b = box_at(a['lon'] + dx, a['lat'] + dy, h)
                        if b.any():
                            k = relationship(favoured(area_mean(nat['p'], b, w), minimum), off_cat)
                            rels[k] = rels.get(k, 0) + 1
        plat_cat = favoured(neighbourhood and neighbourhood['mean_local_probabilities'], minimum)
        rel = relationship(plat_cat, off_cat)
        if a:
            sensitivity = dict(tested=sum(rels.values()), relationships=rels, stable=set(rels) == {rel},
                               half_widths_deg=list(HALF_WIDTHS), centre_shifts_deg=list(CENTRE_SHIFTS))
        metric(metric='favoured_category_relationship', source_id=r['source_id'], zone=zone,
               status=state if neighbourhood and neighbourhood['cells'] else 'unavailable',
               reason=None if validated else 'transcription_and_anchor_awaiting_review', value=rel if validated else None,
               draft_value=None if validated else rel, basis='reviewed_visual (arrow-tip neighbourhood)' if validated else 'draft_visual',
               evidence_ids=[*r['evidence_ids'], plat_ev])
        metric(metric='zone_mean_probability', source_id=r['source_id'], zone=zone, status='unavailable', value=None,
               reason='zone_geometry_requires_alignment',
               detail='The figure locates the zone only by an arrow; zone polygons are needed for an area mean over the zone.')
        metric(metric='same_event_probability_difference', source_id=r['source_id'], zone=zone, status='unavailable', value=None,
               reason='zone_geometry_requires_alignment; official_reference_period_unknown')
        findings.append(dict(
            id=f'{r["record_id"]}_finding', kind='zone', source_id=r['source_id'], provider=r['provider'], area=f'EMI zone {zone}',
            status='validated' if validated else 'draft', official_category=off_cat, official_probabilities=r['probabilities'],
            platform_category=plat_cat, platform_neighbourhood=neighbourhood, relationship=rel, sensitivity=sensitivity,
            comparison_basis='reviewed_visual' if validated else 'draft_visual', probability_difference_pp=None,
            target_windows=dict(platform=[platform['target_start'], platform['target_end']], official=[r['target_start'], r['target_end']]),
            limitations=lim + ['platform_value_is_neighbourhood_of_arrow_tip_not_zone_mean'],
            evidence_ids=[plat_ev, *r['evidence_ids']]))

    # ------------------------------------------------------------------ ICPAC dominant-category map
    for r in [r for r in recs if r['representation'] == 'dominant_category_map']:
        validated = r['extraction_status'] == 'validated'
        if not (sources_dir / r['grid_file']).is_file():
            metric(metric='mapped_category_agreement', source_id=r['source_id'], status='pending_review', value=None,
                   reason='digitization_unavailable')
            continue
        g = read_json(sources_dir / r['grid_file'])
        shift_file = sources_dir / r['grid_file'].replace('_grid.json', '_grid_shifts.json')
        shifts = read_json(shift_file) if shift_file.is_file() else {}
        if not (np.allclose(g['lat'], nat['lat']) and np.allclose(g['lon'], nat['lon'])):
            raise ValueError('Digitized grid differs from the native grid')
        cat = np.array(g['category'], dtype=object)
        st = np.array(g['state'], dtype=object)
        low = np.array([[np.nan if v is None else v for v in row] for row in g['low']])
        wl = window_limitation(platform, r)
        lim = [wl] if wl else []
        lim += ['official_reference_period_unknown', 'digitized_from_published_image', 'official_other_category_probabilities_not_published']
        pc = np.empty(cat.shape, dtype=object)
        for i in range(cat.shape[0]):
            for j in range(cat.shape[1]):
                pc[i, j] = favoured(list(nat['p'][i, j]), minimum) if nat['eligible'][i, j] else 'unknown'
        for key, (label, amask) in areas.items():
            shown = amask & (st == 'forecast')
            grey = amask & (st == 'no_forecast_shown')
            both = shown & np.isin(pc, CATS)
            same = both & (cat == pc)
            opp = both & (((cat == 'above') & (pc == 'below')) | ((cat == 'below') & (pc == 'above')))
            wa = lambda m: float(w[m].sum())
            total = wa(amask)
            off_share = {c: wa(shown & (cat == c)) / wa(shown) if shown.any() else None for c in CATS}
            plat_share = {c: wa(amask & (pc == c)) / total for c in (*CATS, 'weak')}
            intervals = {}
            for c in CATS:
                for lo in sorted(set(low[shown & (cat == c)].tolist())):
                    intervals[f'{c} {int(lo)}-{int(lo) + 10}%'] = wa(shown & (cat == c) & (low == lo)) / wa(shown)
            value = dict(area_share_official_forecast_shown=wa(shown) / total, area_share_official_no_forecast=wa(grey) / total,
                         area_share_both_favoured=wa(both) / total,
                         agreement_share_where_both_favoured=wa(same) / wa(both) if both.any() else None,
                         opposing_share_where_both_favoured=wa(opp) / wa(both) if both.any() else None,
                         official_category_shares=off_share, official_interval_shares=intervals, platform_category_shares=plat_share,
                         platform_mean_local_probabilities=area_mean(nat['p'], amask, w), cells=int(amask.sum()))
            metric(metric='mapped_category_agreement', source_id=r['source_id'], area=label, status='available' if validated else 'pending_review',
                   value=value if validated else None, draft_value=None if validated else value,
                   reason=None if validated else 'digitization_awaiting_review', basis='reviewed_digitization' if validated else 'draft_digitization',
                   limitations=lim, evidence_ids=[*r['evidence_ids'], plat_ev, f'{r["source_id"]}_comparison_map'])
            # Registration sensitivity: the same statistics with the map shifted by one source pixel.
            if shifts:
                ag, cov = [], []
                for alt in shifts.values():
                    acat, ast = np.array(alt['category'], dtype=object), np.array(alt['state'], dtype=object)
                    b2 = amask & (ast == 'forecast') & np.isin(pc, CATS)
                    if b2.any():
                        ag.append(wa(b2 & (acat == pc)) / wa(b2))
                        cov.append(wa(b2) / total)
                value['registration_sensitivity'] = dict(shifts_px=len(shifts), agreement_range=[min(ag), max(ag)] if ag else None,
                                                          compared_area_range=[min(cov), max(cov)] if cov else None)
            # Relationship over the overlap only: where both show a favoured category.
            if both.any():
                om = max(CATS, key=lambda c: wa(both & (cat == c)))
                pm = max(CATS, key=lambda c: wa(both & (pc == c)))
                value['overlap_majority'] = dict(official=om, platform=pm,
                                                 official_share=wa(both & (cat == om)) / wa(both), platform_share=wa(both & (pc == pm)) / wa(both))
            else:
                om = pm = 'unknown'
            findings.append(dict(
                id=f'{r["record_id"]}_{key}_finding', kind='area', area_key=key, source_id=r['source_id'], provider=r['provider'], area=label,
                status='validated' if validated else 'draft', official_category=om, platform_category=pm,
                relationship=relationship(pm, om), comparison_basis='reviewed_digitization' if validated else 'draft_digitization',
                numbers=value, probability_difference_pp=None,
                target_windows=dict(platform=[platform['target_start'], platform['target_end']], official=[r['target_start'], r['target_end']]),
                limitations=lim, evidence_ids=[plat_ev, *r['evidence_ids'], f'{r["source_id"]}_comparison_map']))
        metric(metric='same_event_probability_difference', source_id=r['source_id'], status='unavailable', value=None,
               reason='target_window_mismatch; official_publishes_only_favoured_category_interval')
        icpac_map(tmp / 'maps' / f'{r["source_id"]}_comparison.png', nat, cat, st, pc, areas['season_domain'][1], validated, minimum)

    # ------------------------------------------------------------------ explicitly unavailable
    metric(metric='rainfall_anomaly_difference', status='unavailable', value=None,
           reason='official_amount_anomaly_not_found_in_checked_products', detail=manifest.get('anomaly_products_checked'))
    metric(metric='forecast_accuracy', status='unavailable', value=None,
           reason='out_of_scope: needs observations and a separate verification design (see the Verification section)')
    if any(r['representation'] == 'zone_tercile_probabilities' for r in recs):
        zone_recs = [r for r in recs if r['representation'] == 'zone_tercile_probabilities']
        emi_map(tmp / 'maps' / f'{zone_recs[0]["source_id"]}_anchors.png', nat, zone_recs, areas['season_domain'][1],
                all(r['extraction_status'] == 'validated' for r in zone_recs), minimum)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'), registry=registry['id'],
                  platform=dict(platform, native_forecast=repo_path(native_path),
                                native_sha256=nat['sha256'], minimum_leading_probability=minimum,
                                areas={k: v[0] for k, v in areas.items()}),
                  inputs=input_fingerprint(native_path, domain_mask, registry, manifest_states(manifest), minimum),
                  metrics=metrics, findings=findings,
                  maps=sorted(p.name for p in (tmp / 'maps').glob('*.png')),
                  notes=['Area means are area-weighted means of local grid-cell probabilities, not probabilities of area-mean rainfall.',
                         'Favoured category: the leading tercile where it reaches 40% (the map display rule); otherwise no clear category.',
                         'An OND probability cannot be built by averaging monthly probabilities; ONDJ and OND are compared only as spatial tendencies.'])
    write_json(tmp / 'comparison.json', result)
    ef.publish(tmp, out)
    return result


# ---------------------------------------------------------------------------------- figures
COLOURS = {'below': '#eb6834', 'near': '#a9a7a0', 'above': '#1baf7a', 'weak': '#ffffff', 'unknown': '#eeeeee', 'noforecast': '#bdbdbd'}


def _draft(fig, validated):
    if not validated:
        fig.text(.5, .5, 'DRAFT — extraction not yet reviewed', ha='center', va='center', fontsize=26, color='#b03a24',
                 alpha=.25, rotation=20, weight='bold')


def _boundary(ax):
    try:
        import delivery_map_base as base
        for x, y in base.boundary_lines(ROOT / 'data/boundaries/ethiopia/eth_admin0.shp'):
            ax.plot(x, y, color='#35414b', lw=.7)
    except Exception:
        pass


def icpac_map(path, nat, cat, st, pc, domain, validated, minimum):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    keys = ['below', 'near', 'above', 'weak', 'unknown', 'noforecast']
    cmap = ListedColormap([COLOURS[k] for k in keys])
    code = lambda arr: np.vectorize(lambda v: keys.index(v) if v in keys else 4)(arr).astype(float)
    off = np.where(st == 'forecast', cat, np.where(st == 'no_forecast_shown', 'noforecast', 'unknown'))
    off = np.where(nat['eligible'], off, 'unknown')
    agree = np.full(cat.shape, np.nan)
    both = (st == 'forecast') & np.isin(pc, CATS)
    agree[both] = np.where(cat[both] == pc[both], 1, np.where(np.isin(cat[both], ['above', 'below']) & np.isin(pc[both], ['above', 'below']), 0, .5))
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))
    ext = [nat['lon'][0] - .125, nat['lon'][-1] + .125, nat['lat'][0] - .125, nat['lat'][-1] + .125]
    for ax, data, title in [(axes[0], code(np.where(nat['eligible'], pc, 'unknown')), f'Platform ONDJ 2026/27: favoured tercile (≥{minimum:.0%})'),
                            (axes[1], code(off), 'ICPAC OND 2026 update: favoured tercile (digitized)')]:
        ax.imshow(data, origin='lower', extent=ext, cmap=cmap, vmin=-.5, vmax=5.5, interpolation='nearest')
        ax.set_title(title, fontsize=10)
    axes[2].imshow(np.where(nat['eligible'], agree, np.nan), origin='lower', extent=ext, interpolation='nearest',
                   cmap=ListedColormap(['#b03a24', '#e2b25c', '#2a78d6']), vmin=-.25, vmax=1.25)
    axes[2].set_title('Agreement where both favour a category', fontsize=10)
    for ax in axes:
        _boundary(ax)
        ax.contour(nat['lon'], nat['lat'], domain.astype(float), levels=[.5], colors='#446761', linewidths=.8)
        ax.set_xlim(ext[:2]); ax.set_ylim(ext[2:]); ax.set_aspect('equal'); ax.tick_params(labelsize=8)
    fig.legend(handles=[Patch(color=COLOURS[k], label=NAMES[k]) for k in CATS] +
               [Patch(facecolor='white', edgecolor='grey', label='platform: no clear category (<40%)'),
                Patch(color=COLOURS['noforecast'], label='ICPAC grey: no forecast category shown'),
                Patch(color='#2a78d6', label='same category'), Patch(color='#e2b25c', label='near vs other'),
                Patch(color='#b03a24', label='opposite (above vs below)')], loc='lower center', ncol=4, fontsize=8, frameon=False)
    fig.suptitle('Platform ONDJ 2026/27 vs ICPAC OND 2026 update — different target windows (January only in the platform)', fontsize=11)
    fig.subplots_adjust(bottom=.2, top=.9, wspace=.12)
    _draft(fig, validated)
    fig.savefig(path, dpi=130, facecolor='white')
    plt.close(fig)


def emi_map(path, nat, recs, domain, validated, minimum):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch, Rectangle
    keys = ['below', 'near', 'above', 'weak', 'unknown']
    pc = np.empty(nat['eligible'].shape, dtype=object)
    for i in range(pc.shape[0]):
        for j in range(pc.shape[1]):
            pc[i, j] = favoured(list(nat['p'][i, j]), minimum) if nat['eligible'][i, j] else 'unknown'
    data = np.vectorize(keys.index)(pc).astype(float)
    ext = [nat['lon'][0] - .125, nat['lon'][-1] + .125, nat['lat'][0] - .125, nat['lat'][-1] + .125]
    fig, ax = plt.subplots(figsize=(8.6, 7))
    ax.imshow(data, origin='lower', extent=ext, cmap=ListedColormap([COLOURS[k] for k in keys]), vmin=-.5, vmax=4.5, interpolation='nearest')
    _boundary(ax)
    ax.contour(nat['lon'], nat['lat'], domain.astype(float), levels=[.5], colors='#446761', linewidths=.8)
    for r in recs:
        a = r.get('anchor')
        if not a:
            continue
        h = a.get('uncertainty_deg', .5)
        ax.add_patch(Rectangle((a['lon'] - h, a['lat'] - h), 2 * h, 2 * h, fill=False, ec='black', lw=1.4))
        p = r['probabilities']
        ax.annotate(f'EMI zone {r["source_locator"]["zone_label"]}\nA {p["above"]:.0%} N {p["near"]:.0%} B {p["below"]:.0%}',
                    (a['lon'], a['lat'] + h), xytext=(0, 6), textcoords='offset points', ha='center', fontsize=8,
                    bbox=dict(boxstyle='round,pad=.25', fc='white', ec='#999', alpha=.9))
    ax.set_xlim(ext[:2]); ax.set_ylim(ext[2:]); ax.set_aspect('equal'); ax.tick_params(labelsize=8)
    ax.set_title('Platform ONDJ 2026/27 favoured tercile with EMI zone values at their arrow tips (±0.5° boxes)', fontsize=10)
    ax.legend(handles=[Patch(color=COLOURS[k], label=NAMES[k]) for k in CATS] +
              [Patch(facecolor='white', edgecolor='grey', label='no clear category (<40%)')], loc='lower left', fontsize=8)
    _draft(fig, validated)
    fig.savefig(path, dpi=130, facecolor='white', bbox_inches='tight')
    plt.close(fig)


def main():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sources', required=True)
    ap.add_argument('--native', required=True)
    ap.add_argument('--domain-mask', required=True)
    ap.add_argument('--registry', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--minimum-leading-probability', type=float, default=0.40)
    a = ap.parse_args()
    r = lambda p: Path(p) if Path(p).is_absolute() else ROOT / p
    compare(r(a.sources), r(a.native), r(a.domain_mask), read_json(r(a.registry)), r(a.out), a.minimum_leading_probability)


if __name__ == '__main__':
    main()

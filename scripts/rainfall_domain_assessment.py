"""Candidate rainfall domains: threshold sensitivity, comparators and reference agreement.

A candidate includes a cell when the climatological seasonal rainfall reaches T_mm AND the season's
share of the annual rainfall reaches T_% (ratio of climatological means). Codes on the grid:
  1 included, 0 excluded by the criteria, -1 insufficient data to classify, -2 outside Ethiopia.
No patch removal or smoothing: those change membership and are assessed separately.

Areas come from the cell / country-polygon intersections (rainfall_climatology_core.country_area_weights),
so percentages are shares of Ethiopia's area. The part of the country beyond the grid counts as unknown.
Thresholds are chosen for what the domain means climatologically; forecast skill is reported for a
selected domain but never used to move its boundary.
"""
import json
import numpy as np
import xarray as xr
from common import source_path
import rainfall_climatology_core as rc
import climatology_reference_core as cr

INCLUDED, EXCLUDED, UNKNOWN, OUTSIDE = 1, 0, -1, -2


def classify(clim, t_mm, t_share, fraction):
    """Codes for one candidate (see module docstring)."""
    mm, sh = clim.season_mean_mm.values, clim.season_share_percent.values
    known = np.isfinite(mm) & np.isfinite(sh)
    out = np.where(known, np.where((mm >= t_mm) & (sh >= t_share), INCLUDED, EXCLUDED), UNKNOWN)
    return np.where(np.asarray(fraction) > 0, out, OUTSIDE).astype('int8')


def comparator_codes(comp, clim, fraction):
    """Membership of a named comparator rule or an existing mask file, on the same codes."""
    frac = np.asarray(fraction)
    if comp['kind'] == 'mask_file':
        with xr.open_dataset(source_path(comp['path'])) as d:
            if not (np.allclose(d.lat.values, clim.lat.values) and np.allclose(d.lon.values, clim.lon.values)):
                raise ValueError(f'{comp["path"]}: grid differs from the climatology grid')
            member = d.season_domain.values == 1
        out = np.where(member, INCLUDED, EXCLUDED)
    elif comp['rule'] == 'share':
        return classify(clim, comp['seasonal_rainfall_mm'], comp['annual_share_percent'], fraction)
    elif comp['rule'] == 'wettest':
        wet, _ = rc.wettest_of_partition(clim.monthly_mean_mm)
        mm = clim.season_mean_mm.values
        out = np.where(wet < 0, UNKNOWN, np.where((wet == 0) & (mm >= comp['seasonal_rainfall_mm']), INCLUDED, EXCLUDED))
    else:
        raise ValueError(f'Unknown comparator {comp}')
    return np.where(frac > 0, out, OUTSIDE).astype('int8')


def region_layer(path, lat, lon):
    with xr.open_dataset(source_path(path)) as d:
        if not (np.allclose(d.lat.values, lat) and np.allclose(d.lon.values, lon)):
            raise ValueError(f'{path}: grid differs from the climatology grid')
        names = json.loads(d.attrs.get('region_names', '{}'))
        codes = d.region.values.astype(int)
    roman = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
    labels = {k: f'{roman[k - 1]} {names.get(roman[k - 1], "")}'.strip() for k in sorted(set(codes.ravel()) - {0})}
    return codes, labels


def summarize(codes, area, country_km2, outside_grid_km2, regions=None, region_labels=None):
    a = np.asarray(area, float)
    inc = a[codes == INCLUDED].sum()
    unknown = a[codes == UNKNOWN].sum() + outside_grid_km2
    row = dict(included_area_km2=round(float(inc), 1), included_country_percent=round(float(100 * inc / country_km2), 2),
               unknown_area_km2=round(float(unknown), 1), unknown_country_percent=round(float(100 * unknown / country_km2), 3))
    if regions is not None:
        reg = {}
        for k, label in region_labels.items():
            ra = a[(regions == k)].sum()
            reg[label] = round(float(100 * a[(regions == k) & (codes == INCLUDED)].sum() / ra), 1) if ra else None
        unassigned = a[(regions == 0) & (codes != OUTSIDE)].sum()
        row['regional_inclusion_percent'] = reg
        row['regional_note'] = (f'Share of each EMI rainfall region (Korecha and Sorteberg 2013) included; '
                                f'{unassigned:,.0f} km2 of Ethiopia lies outside the digitized regions.')
    return row


def neighbour_changes(cands, codes, area):
    """Area switching membership between neighbouring threshold choices (one cutoff changed by one step)."""
    a = np.asarray(area, float)
    mms = sorted({c['seasonal_rainfall_mm'] for c in cands})
    shs = sorted({c['annual_share_percent'] for c in cands})
    key = {(c['seasonal_rainfall_mm'], c['annual_share_percent']): c['id'] for c in cands}
    out = []
    for i, mm in enumerate(mms):
        for j, sh in enumerate(shs):
            for di, dj, axis in ((1, 0, 'seasonal_rainfall_mm'), (0, 1, 'annual_share_percent')):
                if i + di < len(mms) and j + dj < len(shs):
                    p, q = key[(mm, sh)], key[(mms[i + di], shs[j + dj])]
                    switched = (codes[p] == INCLUDED) != (codes[q] == INCLUDED)
                    out.append(dict(from_candidate=p, to_candidate=q, changed=axis,
                                    switched_area_km2=round(float(a[switched].sum()), 1)))
    return sorted(out, key=lambda r: -r['switched_area_km2'])


def baseline_sensitivity(monthly, cfg, cands, base_codes, area, fraction):
    """Membership changes when the climatology uses another (complete) reference period."""
    a = np.asarray(area, float)
    periods = []
    for period in cfg['additional_reference_periods']:
        st = rc.period_status(monthly.year.values, period)
        if st['status'] != 'available':
            if cfg.get('unavailable_optional_period', 'record_unavailable') == 'fail':
                raise rc.IncompleteBaseline(st['note'])
            periods.append(dict(st, candidates={}))
            continue
        clim = rc.climatology(monthly, period[0], period[1], cfg['season_months'], cfg['annual_months'])
        res = {}
        for c in cands:
            codes = classify(clim, c['seasonal_rainfall_mm'], c['annual_share_percent'], fraction)
            gained = (codes == INCLUDED) & (base_codes[c['id']] != INCLUDED)
            lost = (codes != INCLUDED) & (base_codes[c['id']] == INCLUDED)
            res[c['id']] = dict(included_area_km2=round(float(a[codes == INCLUDED].sum()), 1),
                                gained_area_km2=round(float(a[gained].sum()), 1), lost_area_km2=round(float(a[lost].sum()), 1))
        periods.append(dict(st, candidates=res, climatology=clim))
    return periods


def reference_agreement(codes, cand, refs, area):
    """Agreement of a candidate with the membership implied by classified references (amount and share).

    Each reference implies membership only where its class lies entirely on one side of the cutoff
    (within half a legend unit); straddling classes and unclassified cells are reported, not guessed.
    """
    a = np.asarray(area, float)
    implied = []
    for ref in refs:
        field = ref['record']['quantity']['comparable_field']
        t = cand['seasonal_rainfall_mm'] if field == 'season_mean_mm' else cand['annual_share_percent']
        implied.append(cr.implied_membership(ref['classes_grid'], ref['record']['representation']['classes'], t))
    implied = np.stack(implied)
    excluded_any = (implied == 0).any(axis=0)          # one reference excluding is decisive
    included_all = (implied == 1).all(axis=0)
    decided = (excluded_any | included_all) & (codes >= 0)
    implied = np.where(included_all & ~excluded_any, 1, 0)
    used = [ref['record']['id'] for ref in refs]
    agree = decided & ((codes == INCLUDED) == (implied == 1))
    country = codes != OUTSIDE
    da = a[decided].sum()
    return dict(references=used, agreement=round(float(a[agree].sum() / da), 4) if da else None,
                decided_area_km2=round(float(da), 1), undecided_area_km2=round(float(a[country & ~decided].sum()), 1),
                candidate_only_km2=round(float(a[decided & (codes == INCLUDED) & (implied == 0)].sum()), 1),
                reference_only_km2=round(float(a[decided & (codes != INCLUDED) & (implied == 1)].sum()), 1))


def monotonic(cands, codes):
    """True when raising either cutoff never adds a cell (the inclusion sets are nested)."""
    by = {(c['seasonal_rainfall_mm'], c['annual_share_percent']): codes[c['id']] == INCLUDED for c in cands}
    for (mm, sh), inc in by.items():
        for (mm2, sh2), inc2 in by.items():
            if mm2 >= mm and sh2 >= sh and (inc2 & ~inc).any():
                return False
    return True

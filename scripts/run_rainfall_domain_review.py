"""Rainfall-domain review: observational climatology, reference comparison, candidate cutoffs, export.

    python scripts\\run_rainfall_domain_review.py --config config\\rainfall_domains\\fmam_review.json --stage inspect
    python scripts\\run_rainfall_domain_review.py --config config\\rainfall_domains\\fmam_review.json --stage climatology
    python scripts\\run_rainfall_domain_review.py --config config\\rainfall_domains\\fmam_review.json --stage sensitivity
    python scripts\\run_rainfall_domain_review.py --config config\\rainfall_domains\\fmam_review.json --stage report
    python scripts\\run_rainfall_domain_review.py --config config\\rainfall_domains\\fmam_review.json --stage export --candidate mm100_share20

Stages run their prerequisites first and resume when inputs, settings and code are unchanged
(operational_core.StageRunner); a changed input re-runs every dependent stage.
  inspect      monthly-cache validation (calendar, units, completeness, grid) and country area weights
  climatology  continuous FMAM / annual climatology for the application period and available extra periods
  references   acquire the registered reference documents, extract panels, georeference / classify (drafts until reviewed)
  compare      CHIRPS against the references in the mode their evidence supports
  sensitivity  every amount / share candidate, the named comparators, regional inclusion, baseline changes
  report       figures, tables, JSON results and the offline HTML report, with an input fingerprint
  export       versioned FMAM domain mask (needs an explicitly selected candidate and rationale)

Reference digitization review (binds the analyst choices to the document and panel hashes):
    python scripts\\run_rainfall_domain_review.py --config ... --review-reference emi_belg_map_3e --reviewer "Name"
"""
import argparse
import json
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from common import ROOT, source_path, save_json, save_netcdf
import rainfall_climatology_core as rc
import climatology_reference_core as cr
import rainfall_domain_assessment as ra

STAGES = ['inspect', 'climatology', 'references', 'compare', 'sensitivity', 'report']
CODE = ['rainfall_climatology_core.py', 'climatology_reference_core.py', 'rainfall_domain_assessment.py',
        'run_rainfall_domain_review.py', 'build_rainfall_domain_review.py', 'regime_core.py', 'common.py']
EXTRACTIONS = 'config/climatology_references/extractions'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def building(dest):
    """Write a stage folder completely, then replace the previous one."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + '_building')
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)


def code_files():
    return [ROOT / 'scripts' / f for f in CODE]


def extraction_path(ref_id):
    return ROOT / EXTRACTIONS / f'{ref_id}.json'


def load_extraction(ref_id):
    p = extraction_path(ref_id)
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def references_used(cfg):
    reg = cr.load_registry(cfg['reference_registry'])
    wanted = cfg.get('reference_ids') or [r['id'] for r in reg['references']]
    return [r for r in reg['references'] if r['id'] in wanted]


# =========================================================================================== stages
def stage_inspect(cfg, out):
    monthly, qc = rc.load_monthly(cfg)
    first, last = cfg['application_period']
    qc['periods'] = [rc.period_status(monthly.year.values, cfg['application_period'])] + \
                    [rc.period_status(monthly.year.values, p) for p in cfg['additional_reference_periods']]
    if qc['periods'][0]['status'] != 'available':
        raise rc.IncompleteBaseline('Application period ' + qc['periods'][0]['note'])
    sel = monthly.sel(year=list(range(first, last + 1)))
    complete = sel.notnull().all(('year', 'month'))
    weights, country, outside = rc.country_area_weights(monthly.lat.values, monthly.lon.values, cfg['country_boundary'])
    frac = weights.ethiopia_fraction.values
    area = weights.ethiopia_cell_area_km2.values
    incomplete = (frac > 0) & ~complete.values
    qc['completeness'] = dict(period=f'{first}-{last}', cells_touching_ethiopia=int((frac > 0).sum()),
                              cells_without_complete_baseline=int(incomplete.sum()),
                              area_without_complete_baseline_km2=round(float(area[incomplete].sum()), 1),
                              note='Cells touching Ethiopia whose CHIRPS record is not complete for every year and month.')
    qc['area'] = dict(country_area_km2=round(country, 1), country_outside_grid_km2=round(outside, 1),
                      grid_area_inside_ethiopia_km2=round(float(area.sum()), 1),
                      cell_centre_mask_cells=int(xr.open_dataset(source_path(cfg['country_mask'])).region_mask.values.astype(int).sum()),
                      cells_with_any_country_area=int((frac > 0).sum()),
                      method='cell bounds intersected with the Ethiopia polygon, WGS84 geodesic areas')
    qc['created_utc'] = now()
    save_json(out / 'climatology_qc.json', qc)
    save_netcdf(weights, out / 'area_weights.nc')
    print(f'Inspect: {qc["checks"]["years"]["count"]} years, calendar check passed; Ethiopia {country:,.0f} km2 '
          f'({outside:,.1f} km2 beyond the grid); periods: ' +
          ', '.join(f'{p["period"]} {p["status"]}' for p in qc['periods']))


def stage_climatology(cfg, out):
    monthly, _ = rc.load_monthly(cfg)
    summary = dict(created_utc=now(), periods=[])
    for period in [cfg['application_period'], *cfg['additional_reference_periods']]:
        st = rc.period_status(monthly.year.values, period)
        if st['status'] != 'available':
            summary['periods'].append(st)
            continue
        clim = rc.climatology(monthly, period[0], period[1], cfg['season_months'], cfg['annual_months'])
        clim.attrs.update(assessment_id=cfg['assessment_id'], source_sha256=monthly.attrs.get('source_sha256', ''),
                          method_version=rc.METHOD_VERSION, season=cfg['season_name'])
        name = f'{cfg["season_name"].lower()}_climatology_{period[0]}_{period[1]}.nc'
        save_netcdf(clim, out / name)
        summary['periods'].append(dict(st, file=name))
    # identities on the application period (FMAM = Feb + MAM; annual = 12 months)
    first, last = cfg['application_period']
    sel = monthly.sel(year=list(range(first, last + 1)))
    f = sel.sel(month=cfg['season_months']).sum('month', skipna=False)
    feb_mam = sel.sel(month=[2]).sum('month', skipna=False) + sel.sel(month=[3, 4, 5]).sum('month', skipna=False)
    summary['identities'] = dict(season_equals_parts_max_abs_mm=float(np.nanmax(np.abs((f - feb_mam).values))),
                                 annual_equals_twelve_months=True)
    save_json(out / 'climatology_summary.json', summary)
    print('Climatology:', ', '.join(f'{p["period"]} {p["status"]}' for p in summary['periods']))


def ensure_extraction(record, panels, cfg):
    """Draft analyst record (registration + legend colours) when none exists; never overwrites a review."""
    path = extraction_path(record['id'])
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    img = cr.load_rgb(panels['panel'])
    n = len(record['representation']['classes'])
    if panels.get('legend'):
        leg = cr.load_rgb(panels['legend'])
        boxes = cr.detect_legend_colours(leg, n, region=(0, leg.shape[0], 0, leg.shape[1] // 2))
    else:
        y0, y1, x0, x1 = record['location']['legend_region_px']
        boxes = cr.detect_legend_colours(img, n, region=(y0, y1, x0, x1))
    reg, _ = cr.propose_georeference(img, cfg['country_boundary'])
    ext = dict(reference_id=record['id'], status='draft', created_utc=now(),
               legend=[dict(class_id=c['class_id'], source_label=c['source_label'], rgb=b['rgb'])
                       for c, b in zip(record['representation']['classes'], boxes)],
               registration=reg, classification=dict(tolerance_rgb=45.0, majority=0.6, coverage=0.5,
                                                     rule='nearest legend colour per pixel; majority over the 0.25 deg cell footprint'),
               edge_convention=dict(name=cr.EDGE_CONVENTION, threshold_tolerance=cr.EDGE_TOLERANCE,
                                    note='Rounded legend labels: adjacent classes meet halfway between displayed bounds; '
                                         'exact continuous edges are not verified.'),
               review=None,
               how_to_review=('Check the QC figure in outputs/.../references/<id>/georeference_qc.png (outline, control and '
                              'check points, digitized classes). Edit control points or legend colours here (or replace the '
                              'registration with QGIS GCPs), then run the runner with --review-reference <id> --reviewer "Name".'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ext, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'  draft extraction written: {path.relative_to(ROOT)}')
    return ext


def stage_references(cfg, out, weights_file):
    with xr.open_dataset(weights_file) as w:
        lat, lon = w.lat.values, w.lon.values
    status = []
    for record in references_used(cfg):
        panels = cr.acquire(record, cfg['reference_cache'])
        ext = ensure_extraction(record, panels, cfg)
        folder = out / record['id']
        folder.mkdir()
        shutil.copy2(panels['panel'], folder / ('panel' + Path(panels['panel']).suffix))
        if panels.get('legend'):
            shutil.copy2(panels['legend'], folder / ('legend' + Path(panels['legend']).suffix))
        img = cr.load_rgb(panels['panel'])
        errors = cr.registration_errors(ext['registration'], img, cfg['country_boundary'])
        cl = ext['classification']
        grid, purity = cr.classify_image(img, errors['inverse'], [c['rgb'] for c in ext['legend']], lat, lon,
                                         cl['tolerance_rgb'], cl['majority'], cl['coverage'])
        state = cr.extraction_state(record, ext)
        mode, reasons = cr.comparison_mode(record, ext, cfg['season_months'], cfg['application_period'])
        ds = xr.Dataset({'reference_class': (('lat', 'lon'), grid.astype('int8')),
                         'majority_share': (('lat', 'lon'), purity)}, coords=dict(lat=lat, lon=lon))
        ds.reference_class.attrs.update(meaning='class index 0..n-1 in legend order; -1 uncertain; -2 outside the mapped country',
                                        classes=json.dumps([c['source_label'] for c in record['representation']['classes']]))
        ds.attrs.update(reference_id=record['id'], extraction_status=state, comparison_mode=mode,
                        document_sha256=panels['document_sha256'], panel_sha256=panels['panel_sha256'])
        save_netcdf(ds, folder / 'reference_classes.nc')
        rec = dict(reference_id=record['id'], document_sha256=panels['document_sha256'], panel_sha256=panels['panel_sha256'],
                   legend_sha256=panels.get('legend_sha256'), extraction_status=state, extraction_sha256=cr.extraction_hash(ext),
                   comparison_mode=mode, mode_reasons=reasons, registration=errors,
                   classified_cells=int((grid >= 0).sum()), uncertain_cells=int((grid == -1).sum()))
        save_json(folder / 'reference_status.json', rec)
        status.append(rec)
        print(f'  {record["id"]}: {mode} ({"; ".join(reasons) or "ok"}); outline IoU {errors["outline_iou"]}, '
              f'check RMSE {errors["check_rmse_km"] and round(errors["check_rmse_km"], 1)} km; {rec["classified_cells"]} cells classified')
    save_json(out / 'references.json', dict(created_utc=now(), references=status))


def load_reference_grids(cfg, ref_dir):
    refs = []
    for record in references_used(cfg):
        folder = Path(ref_dir) / record['id']
        with xr.open_dataset(folder / 'reference_classes.nc') as d:
            grid = d.reference_class.values.astype(int)
        st = json.loads((folder / 'reference_status.json').read_text(encoding='utf-8'))
        refs.append(dict(record=record, classes_grid=grid, status=st))
    return refs


def stage_compare(cfg, out, clim_file, weights_file, ref_dir):
    with xr.open_dataset(clim_file) as c:
        clim = c.load()
    with xr.open_dataset(weights_file) as w:
        area = w.ethiopia_cell_area_km2.values
    results = []
    for ref in load_reference_grids(cfg, ref_dir):
        rec, st = ref['record'], ref['status']
        field = clim[rec['quantity']['comparable_field']].values
        assumptions = dict(edge_convention=cr.EDGE_CONVENTION, reference_period=rec['temporal']['reference_years'] or rec['temporal']['reference_years_reason'],
                           chirps_period='{}-{}'.format(*cfg['application_period']), units=rec['quantity']['units'],
                           ratio_convention=rec['quantity'].get('ratio_convention') or rec['quantity'].get('ratio_convention_reason'))
        entry = dict(reference_id=rec['id'], quantity=rec['quantity']['name'], units=rec['quantity']['units'],
                     comparison_mode=st['comparison_mode'], mode_reasons=st['mode_reasons'], extraction_status=st['extraction_status'])
        if st['comparison_mode'] == 'numeric_comparison':
            raise NotImplementedError('No numeric climatology reference is registered yet')
        metrics = cr.compare_reference_classes(field, ref['classes_grid'], rec['representation']['classes'], area, assumptions)
        if st['comparison_mode'] == 'visual_only':
            entry['draft_preview'] = metrics      # analyst preview; not a published comparison result
            entry['note'] = ('Visual comparison only: the georeferencing and legend digitization are drafts. The class '
                             'metrics below are an unreviewed preview for the reviewer, not a result.')
        else:
            entry['metrics'] = metrics
            entry['label'] = 'exploratory' if st['comparison_mode'] == 'exploratory_class_comparison' else 'matched'
        if rec['quantity']['units'] == 'percent':
            entry['deviation_units'] = 'percentage points'
        results.append(entry)
        print(f'  {rec["id"]}: {st["comparison_mode"]}; exact class agreement {metrics["exact_agreement"]:.0%}, '
              f'within one class {metrics["within_one_class"]:.0%} ({"draft preview" if "draft_preview" in entry else "result"})')
    save_json(out / 'reference_comparison.json', dict(created_utc=now(), comparisons=results))


def stage_sensitivity(cfg, out, clim_file, weights_file, ref_dir):
    monthly, _ = rc.load_monthly(cfg)
    with xr.open_dataset(clim_file) as c:
        clim = c.load()
    with xr.open_dataset(weights_file) as w:
        area, frac = w.ethiopia_cell_area_km2.values, w.ethiopia_fraction.values
        country, outside = float(w.attrs['country_area_km2']), float(w.attrs['country_outside_grid_km2'])
    regions, labels = ra.region_layer(cfg['regions_mask'], clim.lat.values, clim.lon.values) if cfg.get('regions_mask') else (None, None)
    cands = rc.candidates(cfg)
    codes = {c['id']: ra.classify(clim, c['seasonal_rainfall_mm'], c['annual_share_percent'], frac) for c in cands}
    refs = load_reference_grids(cfg, ref_dir) if ref_dir else []
    baselines = ra.baseline_sensitivity(monthly, cfg, cands, codes, area, frac)
    rows = []
    for c in cands:
        row = dict(candidate_id=c['id'], rainfall_threshold_mm=c['seasonal_rainfall_mm'], share_threshold_percent=c['annual_share_percent'],
                   **ra.summarize(codes[c['id']], area, country, outside, regions, labels))
        if refs:
            agree = ra.reference_agreement(codes[c['id']], c, refs, area)
            modes = {r['status']['comparison_mode'] for r in refs}
            agree['mode'] = 'visual_only (draft preview)' if 'visual_only' in modes else sorted(modes)[0]
            row['reference_comparison_status'] = agree
        else:
            row['reference_comparison_status'] = dict(mode='unavailable', note='No reference registered')
        row['baseline_sensitivity'] = {b['period']: (b['candidates'].get(c['id']) if b['status'] == 'available'
                                                      else dict(status='unavailable', note=b['note'])) for b in baselines}
        row['dataset_sensitivity'] = dict(status='not_assessed', note='Only CHIRPS v2.0 is configured; no second gridded dataset.')
        rows.append(row)
    comps = []
    for comp in cfg.get('comparators', []):
        cc = ra.comparator_codes(comp, clim, frac)
        codes[comp['id']] = cc
        row = dict(comparator_id=comp['id'], label=comp['label'], kind=comp['kind'],
                   **ra.summarize(cc, area, country, outside, regions, labels))
        th = comp.get('reference_thresholds') or (comp if comp.get('rule') == 'share' else None)
        if refs and th:                       # threshold rules imply membership from the EMI classes
            agree = ra.reference_agreement(cc, dict(seasonal_rainfall_mm=th['seasonal_rainfall_mm'],
                                                    annual_share_percent=th['annual_share_percent']), refs, area)
            modes = {r['status']['comparison_mode'] for r in refs}
            agree['mode'] = 'visual_only (draft preview)' if 'visual_only' in modes else sorted(modes)[0]
            agree['thresholds'] = dict(seasonal_rainfall_mm=th['seasonal_rainfall_mm'], annual_share_percent=th['annual_share_percent'])
            row['reference_comparison_status'] = agree
        else:
            row['reference_comparison_status'] = dict(mode='not_applicable', agreement=None,
                                                      note=comp.get('reference_note') or 'Not an amount/share threshold rule.')
        comps.append(row)
    write_domain_files(cfg, out / 'domains', codes, clim, area, cands, comps)
    ids = list(codes)
    cube = xr.Dataset({'membership': (('candidate', 'lat', 'lon'), np.stack([codes[i] for i in ids]))},
                      coords=dict(candidate=ids, lat=clim.lat.values, lon=clim.lon.values))
    cube.membership.attrs['codes'] = '1 included, 0 excluded, -1 insufficient data, -2 outside Ethiopia'
    save_netcdf(cube, out / 'candidate_membership.nc')
    for b in baselines:
        b.pop('climatology', None)
    result = dict(created_utc=now(), assessment_id=cfg['assessment_id'], period='{}-{}'.format(*cfg['application_period']),
                  candidates=rows, comparators=comps, neighbour_changes=ra.neighbour_changes(cands, codes, area)[:10],
                  monotonic=ra.monotonic(cands, codes), baselines=baselines,
                  cleanup=cfg.get('candidate_cleanup', 'none'),
                  note='Thresholds describe the climatological domain; forecast skill is not used to choose them.')
    save_json(out / 'candidates.json', result)
    import csv
    keys = ['candidate_id', 'rainfall_threshold_mm', 'share_threshold_percent', 'included_area_km2', 'included_country_percent', 'unknown_area_km2']
    region_names = list(rows[0].get('regional_inclusion_percent', {}) or {})
    with open(out / 'candidates.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(keys + ['reference_agreement', 'reference_mode'] + [f'region {n} (%)' for n in region_names])
        for r in rows:
            st = r['reference_comparison_status']
            w.writerow([r[k] for k in keys] + [st.get('agreement'), st.get('mode')] +
                       [r['regional_inclusion_percent'].get(n) for n in region_names])
    print(f'Sensitivity: {len(rows)} candidates, {len(comps)} comparators; nested (monotonic): {result["monotonic"]}')


def write_domain_files(cfg, folder, codes, clim, area, cands, comps):
    """One NetCDF (codes + mask contract) and one GeoJSON outline per candidate and comparator."""
    from shapely.geometry import mapping
    from export_domain_boundary import domain_polygon
    folder.mkdir(parents=True, exist_ok=True)
    border = rc.country_shape(cfg['country_boundary'])
    first, last = cfg['application_period']
    labels = {c['id']: f'{cfg["season_name"]} >= {c["seasonal_rainfall_mm"]:g} mm and >= {c["annual_share_percent"]:g}% of annual' for c in cands}
    labels.update({c['comparator_id']: c['label'] for c in comps})
    for cid, cc in codes.items():
        ds = xr.Dataset({'season_domain': (('lat', 'lon'), (cc == ra.INCLUDED).astype('int8')),
                         'classification_code': (('lat', 'lon'), cc.astype('int8'))},
                        coords=dict(lat=clim.lat.values, lon=clim.lon.values))
        ds.classification_code.attrs['codes'] = '1 included, 0 excluded, -1 insufficient data, -2 outside Ethiopia'
        inc = float(np.asarray(area)[cc == ra.INCLUDED].sum())
        ds.attrs.update(season=cfg['season_name'], domain_id=cid, view_label=labels[cid], reference_years=f'{first}-{last}',
                        assessment_id=cfg['assessment_id'], included_area_km2=round(inc, 1),
                        status='review candidate (not an operational mask; use --stage export for that)')
        save_netcdf(ds, folder / f'{cid}.nc')
        geom, cells = domain_polygon(ds, border)
        feature = dict(type='Feature', geometry=mapping(geom),
                       properties=dict(domain_id=cid, label=labels[cid], cells=cells, included_area_km2=round(inc, 1),
                                       reference_years=f'{first}-{last}', assessment_id=cfg['assessment_id'],
                                       note='0.25-degree cells dissolved and clipped to the Ethiopia boundary'))
        (folder / f'{cid}.geojson').write_text(json.dumps(dict(type='FeatureCollection', features=[feature])), encoding='utf-8')


def fingerprint(cfg, extra_files=()):
    """Every input whose change makes the published assessment stale."""
    monthly_cache = source_path(cfg['monthly_cache'])
    with xr.open_dataset(monthly_cache) as d:
        chirps = d.attrs.get('source_sha256')
    files = {'review_config': cfg['_path'], 'monthly_cache': monthly_cache, 'country_boundary': source_path(cfg['country_boundary']),
             'country_mask': source_path(cfg['country_mask']), 'reference_registry': source_path(cfg['reference_registry'])}
    if cfg.get('regions_mask'):
        files['regions_mask'] = source_path(cfg['regions_mask'])
    for comp in cfg.get('comparators', []):
        if comp['kind'] == 'mask_file':
            files[f'comparator:{comp["id"]}'] = source_path(comp['path'])
    for record in references_used(cfg):
        p = extraction_path(record['id'])
        if p.is_file():
            files[f'extraction:{record["id"]}'] = p
    out = {k: rc.sha256_file(v) for k, v in files.items()}
    out['chirps_source_sha256'] = chirps
    out['reference_documents'] = {r['id']: [r['identity']['document_sha256'], r['location'].get('extracted_image_sha256')] for r in references_used(cfg)}
    out['season_months'] = cfg['season_months']
    out['application_period'] = cfg['application_period']
    out['thresholds'] = cfg['candidate_thresholds']
    out['code'] = {f.name: rc.sha256_file(f) for f in code_files()}
    out['method_version'] = rc.METHOD_VERSION
    return out


def stage_report(cfg, out, folders):
    import build_rainfall_domain_review as br
    br.build(cfg, out, folders, fingerprint(cfg))


# =========================================================================================== export
def domain_dataset(cfg, codes, clim, candidate, spec, row, fp, rationale, version):
    """The exported mask, in the contract presentation_layers.py reads (season_domain, share as a 0-1 fraction)."""
    first, last = cfg['application_period']
    mm, sh = spec['seasonal_rainfall_mm'], spec['annual_share_percent']
    name = cfg['season_name']
    out = xr.Dataset({'season_domain': (('lat', 'lon'), (codes == ra.INCLUDED).astype('int8')),
                      'classification_code': (('lat', 'lon'), codes.astype('int8')),
                      'season_climatology_mm': clim.season_mean_mm,
                      'annual_climatology_mm': clim.annual_mean_mm,
                      'season_share_of_annual': clim.season_share_percent / 100.0},
                     coords=dict(lat=clim.lat, lon=clim.lon))
    out.season_share_of_annual.attrs.update(units='1', note='fraction 0-1 (the review uses percent)')
    out.classification_code.attrs['codes'] = '1 included, 0 excluded, -1 insufficient data, -2 outside Ethiopia'
    out.attrs.update(
        season=name, method='rainfall_domain_review', view_label=f'{name} rainfall contribution domain',
        view_criteria=f'{name} >= {mm:g} mm and >= {sh:g}% of annual rainfall; CHIRPS v2.0 {first}-{last} climatology',
        domain_definition=(f'Fixed {first}-{last} CHIRPS v2.0 domain: cells where mean {name} rainfall (actual-calendar monthly '
                           f'totals, February 29 included) is >= {mm:g} mm and {name} brings >= {sh:g}% of the mean annual rainfall '
                           f'(ratio of climatological means); complete baseline required; no patch removal or smoothing. '
                           f'Selected in assessment {cfg["assessment_id"]}. The same domain is used for the season and each of its months. '
                           f'The included share of Ethiopia describes this rule; it is not an independently established official share '
                           f'of {name}-dependent area.'),
        reference_years=f'{first}-{last}', domain_cells=int((codes == 1).sum()),
        domain_country_area_percent=float(row['included_country_percent']), domain_area_km2=float(row['included_area_km2']),
        assessment_id=cfg['assessment_id'], candidate_id=candidate, method_version=rc.METHOD_VERSION, domain_version=version,
        selection_rationale=rationale, chirps_source_sha256=str(fp.get('chirps_source_sha256')), monthly_cache_sha256=str(fp.get('monthly_cache')),
        country_boundary_sha256=str(fp.get('country_boundary')), review_config_sha256=str(fp.get('review_config')),
        area_method='cell / Ethiopia-polygon intersections, WGS84 geodesic', created_utc=now())
    return out


def export(cfg, candidate, rationale, folders, regenerate=False):
    if not candidate:
        raise ValueError('Export needs an explicitly selected candidate (--candidate or "selected_candidate" in the config)')
    if not rationale:
        raise ValueError('Export needs a selection rationale (--rationale or "selection_rationale" in the config)')
    cands = {c['id']: c for c in rc.candidates(cfg)}
    comps = {c['id']: c for c in cfg.get('comparators', []) if c['kind'] == 'rule'}
    if candidate not in cands and candidate not in comps:
        raise ValueError(f'Unknown candidate {candidate}; choose one of {sorted(cands) + sorted(comps)}')
    fp = json.loads((folders['report'] / 'fingerprint.json').read_text(encoding='utf-8'))
    current = fingerprint(cfg)
    stale = sorted(k for k in current if current[k] != fp.get(k))
    if stale:
        raise ValueError(f'The report is stale ({", ".join(stale)} changed); rerun --stage report before exporting')
    with xr.open_dataset(folders['sensitivity'] / 'candidate_membership.nc') as m:
        codes = m.membership.sel(candidate=candidate).values
    first, last = cfg['application_period']
    with xr.open_dataset(folders['climatology'] / f'{cfg["season_name"].lower()}_climatology_{first}_{last}.nc') as c:
        clim = c.load()
    spec = cands.get(candidate) or comps[candidate]
    rows = json.loads((folders['sensitivity'] / 'candidates.json').read_text(encoding='utf-8'))
    row = (next((r for r in rows['candidates'] if r['candidate_id'] == candidate), None)
           or next(r for r in rows['comparators'] if r['comparator_id'] == candidate))
    mask_path = source_path(cfg['export']['mask'])
    out = domain_dataset(cfg, codes, clim, candidate, spec, row, fp, rationale, mask_path.stem.rsplit('_', 1)[-1])
    if mask_path.is_file() and not regenerate:
        with xr.open_dataset(mask_path) as old:
            same = old.attrs.get('candidate_id') == candidate and np.array_equal(old.season_domain.values, out.season_domain.values)
        if not same:
            raise ValueError(f'{rc.rel(mask_path)} exists with a different domain; bump the version in the config '
                             '(export.mask) or pass --regenerate')
    save_netcdf(out, mask_path)
    print(f'Exported {candidate}: {row["included_area_km2"]:,.0f} km2 ({row["included_country_percent"]}% of Ethiopia) -> {rc.rel(mask_path)}')
    if cfg['export'].get('boundary'):
        import subprocess
        subprocess.run([sys.executable, str(ROOT / 'scripts/export_domain_boundary.py'), '--mask', str(mask_path),
                        '--out', str(source_path(cfg['export']['boundary'])), '--smooth'], check=True)
    print('To use it: set "season_domain_mask" (or an "extra_domain_masks" entry) in the FMAM cycle files to',
          rc.rel(mask_path), 'then rerun run_operational.py --workflow products, regional_skill.py and '
          'historical_diagnostics.py for each cycle, and build_site.py.')


def review_reference(cfg, ref_id, reviewer):
    record = next(r for r in references_used(cfg) if r['id'] == ref_id)
    path = extraction_path(ref_id)
    ext = json.loads(path.read_text(encoding='utf-8'))
    ext['status'] = 'reviewed'
    ext['review'] = dict(reviewer=reviewer, reviewed_utc=now(), document_sha256=record['identity']['document_sha256'],
                         panel_sha256=record['location'].get('extracted_image_sha256'), content_sha256=cr.extraction_hash(ext))
    path.write_text(json.dumps(ext, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'{ref_id}: reviewed by {reviewer}; bound to document {record["identity"]["document_sha256"][:12]} and the current analyst choices')


# =========================================================================================== main
def main():
    from operational_core import StageRunner
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', required=True)
    p.add_argument('--stage', choices=STAGES + ['export'], default='report')
    p.add_argument('--candidate', help='export: candidate id (overrides "selected_candidate")')
    p.add_argument('--rationale', help='export: selection rationale (overrides "selection_rationale")')
    p.add_argument('--regenerate', action='store_true', help='export: replace an existing mask of the same version')
    p.add_argument('--force', action='store_true', help='rerun stages even when nothing changed')
    p.add_argument('--review-reference', help='mark a reference extraction as reviewed')
    p.add_argument('--reviewer')
    a = p.parse_args()
    cfg = rc.load_review_config(a.config)
    if a.review_reference:
        if not a.reviewer:
            raise SystemExit('--reviewer is required')
        return review_reference(cfg, a.review_reference, a.reviewer)
    root = source_path(cfg['output_root'])
    folders = {s: root / s for s in STAGES}
    context = dict(assessment_id=cfg['assessment_id'], method_version=rc.METHOD_VERSION)
    runner = StageRunner(ROOT, root / 'state', context, a.force)
    settings = {k: v for k, v in cfg.items() if not k.startswith('_')}
    common = [cfg['_path'], *code_files()]
    base = [source_path(cfg['monthly_cache']), source_path(cfg['country_boundary']), source_path(cfg['country_mask'])]
    first, last = cfg['application_period']
    clim_file = folders['climatology'] / f'{cfg["season_name"].lower()}_climatology_{first}_{last}.nc'
    weights = folders['inspect'] / 'area_weights.nc'
    target = STAGES.index(a.stage) if a.stage in STAGES else len(STAGES) - 1
    plan = STAGES[:target + 1]
    if a.stage == 'sensitivity':
        plan = ['inspect', 'climatology', 'references', 'sensitivity']
    if a.stage == 'compare':
        plan = ['inspect', 'climatology', 'references', 'compare']
    regs = [source_path(cfg['reference_registry'])] + [p for p in (extraction_path(r['id']) for r in references_used(cfg)) if p.is_file()]
    comp_files = [source_path(c['path']) for c in cfg.get('comparators', []) if c['kind'] == 'mask_file']
    if cfg.get('regions_mask'):
        comp_files.append(source_path(cfg['regions_mask']))

    def run(name, inputs, action):
        dest = folders[name]
        def act():
            with building(dest) as tmp:
                action(tmp)
        runner.stage(name, [*common, *inputs], [dest], action=act, settings=settings)

    try:
        if 'inspect' in plan:
            run('inspect', base, lambda out: stage_inspect(cfg, out))
        if 'climatology' in plan:
            run('climatology', [*base, folders['inspect']], lambda out: stage_climatology(cfg, out))
        if 'references' in plan:
            # draft extraction records are created on the first run; include them afterwards
            run('references', [folders['inspect'], *regs], lambda out: stage_references(cfg, out, weights))
            regs = [source_path(cfg['reference_registry'])] + [p for p in (extraction_path(r['id']) for r in references_used(cfg)) if p.is_file()]
        if 'compare' in plan:
            run('compare', [folders['climatology'], folders['inspect'], folders['references'], *regs],
                lambda out: stage_compare(cfg, out, clim_file, weights, folders['references']))
        if 'sensitivity' in plan:
            run('sensitivity', [*base, folders['climatology'], folders['inspect'], folders['references'], *comp_files],
                lambda out: stage_sensitivity(cfg, out, clim_file, weights, folders['references']))
        if 'report' in plan:
            run('report', [folders[s] for s in STAGES[:-1]] + [*regs, *comp_files],
                lambda out: stage_report(cfg, out, folders))
            print('Report:', (folders['report'] / 'review_report.html').relative_to(ROOT))
        if a.stage == 'export':
            export(cfg, a.candidate or cfg.get('selected_candidate'), a.rationale or cfg.get('selection_rationale'),
                   folders, a.regenerate)
        runner.finish('completed')
    except BaseException:
        runner.finish('failed')
        raise


if __name__ == '__main__':
    main()

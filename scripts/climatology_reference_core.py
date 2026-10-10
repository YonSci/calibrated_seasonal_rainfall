"""Climatology references (e.g. EMI long-term Belg rainfall and Belg share maps) for the domain review.

These are climatological quantities, not forecast products, so they have their own registry
(config/climatology_references/registry.json). Source handling follows external_forecasts.py:
the document is downloaded once, stored under its SHA-256, and every extracted panel, digitization
and review is bound to those hashes.

Evidence decides the comparison mode:
  visual_only                  the published image is available (always shown side by side)
  exploratory_class_comparison reviewed georeferencing and classes; temporal metadata unresolved
  matched_class_comparison     as above, with a confirmed reference period and matching season
  numeric_comparison           a genuine numerical field with compatible support
Image-derived classes never enter numeric comparison, and a class carries no exact value
(reference_value stays null). Grey is a valid low class in these figures, not "no data".
"""
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from common import ROOT, source_path

MODES = ('visual_only', 'exploratory_class_comparison', 'matched_class_comparison', 'numeric_comparison')
CLASS_REPRESENTATIONS = {'published_image', 'digitized_classes'}
NOT_DOCUMENTED = 'not_documented'
EDGE_CONVENTION = 'midpoint_between_displayed_bounds'
EDGE_TOLERANCE = 0.5          # rounded legend labels: a class is decided for a threshold within half a unit


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_registry(path):
    reg = json.loads(source_path(path).read_text(encoding='utf-8-sig'))
    ids = [r['id'] for r in reg['references']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate reference ids')
    for r in reg['references']:
        check_record(r)
    return reg


REQUIRED = {'identity': ['publisher', 'document_url', 'document_sha256'],
            'location': ['page', 'panel', 'image_name'],
            'quantity': ['name', 'units', 'season_months', 'numerator', 'denominator'],
            'temporal': ['reference_years', 'aggregation', 'documentation_status'],
            'provenance': ['dataset', 'station_network', 'interpolation', 'version'],
            'spatial': ['original_crs', 'analysis_crs', 'resolution'],
            'representation': ['kind', 'classes'],
            'institutional_status': ['status']}


def check_record(r):
    """Every field group present; undocumented values are null with a reason, never guessed."""
    missing = [f'{g}.{k}' for g, keys in REQUIRED.items() for k in keys if k not in r.get(g, {})]
    if missing:
        raise ValueError(f'{r.get("id")}: missing fields {missing}')
    for g in ('temporal', 'provenance', 'spatial'):
        for k, v in r[g].items():
            if v is None and not r[g].get(f'{k}_reason'):
                raise ValueError(f'{r["id"]}: {g}.{k} is null without a {k}_reason (e.g. "{NOT_DOCUMENTED}")')
    kind = r['representation']['kind']
    if kind not in CLASS_REPRESENTATIONS | {'numeric_grid', 'stations', 'polygon'}:
        raise ValueError(f'{r["id"]}: unknown representation {kind}')
    for c in r['representation']['classes']:
        if c.get('reference_value') is not None:
            raise ValueError(f'{r["id"]}: class {c["class_id"]} must not carry an exact reference_value')


# ----------------------------------------------------------------------------------- acquisition
def acquire(record, cache_root):
    """Download (once) the document and extract the panel; verify both hashes. Returns paths and hashes."""
    import pypdf
    ident, loc = record['identity'], record['location']
    folder = source_path(cache_root) / record['document_id']
    expected = ident['document_sha256']
    doc = folder / f'{expected[:16]}.pdf' if expected else None
    if doc is None or not doc.is_file():
        import external_forecasts as ef
        _, body, headers = ef.fetch(ident['document_url'])
        got = sha256_bytes(body)
        if expected and got != expected:
            raise ValueError(f'{record["id"]}: downloaded document hash {got[:16]} differs from the registry '
                             f'({expected[:16]}); the source changed and needs a new review')
        folder.mkdir(parents=True, exist_ok=True)
        doc = folder / f'{got[:16]}.pdf'
        doc.write_bytes(body)
        (folder / f'{got[:16]}.json').write_text(json.dumps(dict(url=ident['document_url'], sha256=got, bytes=len(body),
                                                                  http_last_modified=headers.get('Last-Modified')), indent=2))
    data = doc.read_bytes()
    if expected and sha256_bytes(data) != expected:
        raise ValueError(f'{record["id"]}: cached document hash differs from the registry')
    page = pypdf.PdfReader(io.BytesIO(data)).pages[loc['page'] - 1]
    image = next((im for im in page.images if im.name == loc['image_name']), None)
    if image is None:
        raise ValueError(f'{record["id"]}: image {loc["image_name"]} not on page {loc["page"]}')
    panel = folder / f'{expected[:16] if expected else sha256_bytes(data)[:16]}_p{loc["page"]}_{loc["image_name"]}'
    panel.write_bytes(image.data)
    out = dict(document=doc, document_sha256=sha256_bytes(data), panel=panel, panel_sha256=sha256_bytes(image.data))
    if loc.get('extracted_image_sha256') and loc['extracted_image_sha256'] != out['panel_sha256']:
        raise ValueError(f'{record["id"]}: extracted panel hash differs from the registry')
    legend = loc.get('legend_image_name')
    if legend:
        im = next((im for im in page.images if im.name == legend), None)
        if im is None:
            raise ValueError(f'{record["id"]}: legend image {legend} not on page {loc["page"]}')
        out['legend'] = folder / f'{panel.name.rsplit("_", 1)[0]}_{legend}'
        out['legend'].write_bytes(im.data)
        out['legend_sha256'] = sha256_bytes(im.data)
    return out


def load_rgb(path):
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA') or 'transparency' in im.info:
        im = im.convert('RGBA')
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return np.asarray(im.convert('RGB')).astype(int)


def detect_legend_colours(img, n, region=None, min_rows=5):
    """Colours of n legend boxes, top to bottom: rows of box-coloured pixels (not white, not text-dark)."""
    y0, y1, x0, x1 = region or (0, img.shape[0], 0, img.shape[1])
    sub = img[y0:y1, x0:x1]
    s = sub.sum(axis=2)
    box = (s < 3 * 235) & (s > 150) & ~((np.ptp(sub, axis=2) < 12) & (s < 3 * 190))   # exclude black text and dark-grey borders
    runs, cur = [], None
    for r in range(sub.shape[0]):
        cols = np.nonzero(box[r])[0]
        if len(cols) < 6:
            cur = None
            continue
        colour = np.median(sub[r, cols], axis=0)
        if cur is not None and np.abs(colour - cur['colour']).sum() < 25:          # adjacent boxes may touch
            cur['rows'].append(r)
        else:
            cur = dict(colour=colour, rows=[r])
            runs.append(cur)
    boxes = [dict(rgb=[int(v) for v in np.median([sub[r, np.nonzero(box[r])[0]].mean(axis=0) for r in run['rows']], axis=0)],
                  rows=[run['rows'][0] + y0, run['rows'][-1] + y0]) for run in runs if len(run['rows']) >= min_rows]
    if len(boxes) != n:
        raise ValueError(f'Expected {n} legend boxes, found {len(boxes)}')
    return boxes


# ----------------------------------------------------------------------------------- georeferencing
def silhouette(img, frame=None):
    """Country silhouette inside the map frame: any non-white pixel that is not part of the frame."""
    import external_forecasts as ef
    H, W, _ = img.shape
    if frame is None:
        dark = img.sum(axis=2) < 3 * 120
        rows, cols = ef.frame_lines(dark)
        if len(rows) >= 2 and len(cols) >= 2:
            # the map frame: lines running the full frame height/width (legend box edges are shorter)
            cols = [c for c in cols if dark[rows[0]:rows[-1] + 1, c].sum() >= 0.9 * (rows[-1] - rows[0])]
            rows = [r for r in rows if dark[r, cols[0]:cols[-1] + 1].sum() >= 0.9 * (cols[-1] - cols[0])] if len(cols) >= 2 else rows
        m = 4                                     # skip the frame line and its anti-aliasing
        frame = (rows[0] + m, rows[-1] - m, cols[0] + m, cols[1] - m) if len(rows) >= 2 and len(cols) >= 2 else (0, H, 0, W)
    y0, y1, x0, x1 = frame
    inside = np.zeros((H, W), bool)
    inside[y0:y1, x0:x1] = True
    sil = inside & (img.sum(axis=2) < 3 * 248)
    from scipy.ndimage import binary_fill_holes, label
    sil = binary_fill_holes(sil)
    lab, n = label(sil)
    if n > 1:                                   # the country is the largest connected component
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        sil = lab == sizes.argmax()
    return sil, frame


def fit_affine(points):
    """lon/lat = A @ [x, y, 1] by least squares; returns 2x3 matrix."""
    P = np.array([[p['pixel'][0], p['pixel'][1], 1.0] for p in points])
    L = np.array([p['lonlat'] for p in points], float)
    A, *_ = np.linalg.lstsq(P, L, rcond=None)
    return A.T


def apply_affine(A, x, y):
    return A[0, 0] * x + A[0, 1] * y + A[0, 2], A[1, 0] * x + A[1, 1] * y + A[1, 2]


def invert_affine(A):
    M = np.vstack([A, [0, 0, 1]])
    return np.linalg.inv(M)[:2]


def km_error(lonlat_a, lonlat_b):
    from pyproj import Geod
    g = Geod(ellps='WGS84')
    return abs(g.inv(lonlat_a[0], lonlat_a[1], lonlat_b[0], lonlat_b[1])[2]) / 1000


def _extremes(xy):
    """Indices of the N, S, W, E extreme points and the four diagonal extremes of (lon, lat)-like arrays."""
    x, y = xy
    return {'north': np.argmax(y), 'south': np.argmin(y), 'west': np.argmin(x), 'east': np.argmax(x),
            'northeast': np.argmax(x + y), 'southwest': np.argmin(x + y), 'northwest': np.argmax(y - x), 'southeast': np.argmax(x - y)}


def propose_georeference(img, boundary, frame=None):
    """Draft registration: country extremes as control points, diagonal extremes as independent checks.

    The control points pair the silhouette's N/S/W/E extreme pixels with the boundary polygon's extreme
    vertices. Check points are not used in the fit; their errors and the outline IoU are recorded so the
    reviewer can accept, edit (e.g. in QGIS) or reject the registration.
    """
    from rainfall_climatology_core import country_shape
    poly = country_shape(boundary)
    coords = np.vstack([np.asarray(g.exterior.coords) for g in getattr(poly, 'geoms', [poly])])
    sil, frame = silhouette(img, frame)
    ys, xs = np.nonzero(sil)
    px = (xs.astype(float), -ys.astype(float))              # image y grows downward
    pe, ge = _extremes(px), _extremes((coords[:, 0], coords[:, 1]))
    control = [dict(name=k, role='control', pixel=[float(xs[pe[k]]), float(ys[pe[k]])],
                    lonlat=[float(coords[ge[k], 0]), float(coords[ge[k], 1])]) for k in ('north', 'south', 'west', 'east')]
    y0, y1, x0, x1 = frame
    clipped = lambda p: p['pixel'][1] <= y0 + 2 or p['pixel'][1] >= y1 - 3 or p['pixel'][0] <= x0 + 2 or p['pixel'][0] >= x1 - 3
    for p in control:
        p['clipped_by_frame'] = bool(clipped(p))
    usable = [p for p in control if not p['clipped_by_frame']]
    A = fit_affine(usable if len(usable) >= 3 else control)
    A = refine_by_outline(A, sil, poly, frame)
    lon, lat = apply_affine(A, xs.astype(float), ys.astype(float))
    se = _extremes((lon, lat))
    checks = []
    for k in ('northeast', 'southwest', 'northwest', 'southeast'):
        gp = [float(coords[ge[k], 0]), float(coords[ge[k], 1])]
        c = dict(name=k, role='check', pixel=[float(xs[se[k]]), float(ys[se[k]])], lonlat=gp)
        c['clipped_by_frame'] = bool(clipped(c))
        checks.append(c)
    return dict(method='outline_fit_affine', status='draft', frame_px=[int(v) for v in frame], affine=A.tolist(),
                control_points=control, check_points=checks,
                proposed_by='automatic draft: silhouette extreme points, refined by fitting the country outline '
                            '(scale and offset per axis); points touching the map frame are not used'), sil


def refine_by_outline(A, sil, poly, frame, step=3):
    """Scale/offset per axis that best overlays the boundary polygon on the silhouette inside the frame."""
    from matplotlib.path import Path as MPath
    from scipy.optimize import minimize
    y0, y1, x0, x1 = frame
    yy, xx = np.mgrid[y0:y1:step, x0:x1:step]
    xx, yy = xx.ravel().astype(float), yy.ravel().astype(float)
    target = sil[yy.astype(int), xx.astype(int)]
    simple = poly.simplify(0.01)                       # ~1 km; the image pixels are 3-4 km
    paths = [MPath(np.asarray(g.exterior.coords)) for g in getattr(simple, 'geoms', [simple])]
    def mismatch(q):
        sx, ox, sy, oy = q
        lon, lat = sx * xx + ox, sy * yy + oy
        inside = np.zeros(len(xx), bool)
        for pth in paths:
            inside |= pth.contains_points(np.c_[lon, lat])
        return float((inside != target).sum())
    q0 = [A[0, 0], A[0, 2], A[1, 1], A[1, 2]]
    res = minimize(mismatch, q0, method='Nelder-Mead',
                   options=dict(xatol=1e-5, fatol=0.5, maxiter=300))
    best = res.x if res.fun <= mismatch(q0) else q0
    return np.array([[best[0], 0.0, best[1]], [0.0, best[2], best[3]]])


def registration_errors(reg, img, boundary):
    """Control residuals, independent check-point errors (km) and outline IoU for a registration."""
    from rainfall_climatology_core import country_shape
    from matplotlib.path import Path as MPath
    A = np.asarray(reg['affine']) if reg.get('affine') else fit_affine(reg['control_points'])
    def errs(points):
        return [dict(name=p['name'], error_km=round(km_error(apply_affine(A, *p['pixel']), p['lonlat']), 2))
                for p in points if not p.get('clipped_by_frame')]
    sil, _ = silhouette(img, tuple(reg['frame_px']))
    H, W = sil.shape
    Ai = invert_affine(A)
    poly = country_shape(boundary)
    yy, xx = np.mgrid[0:H, 0:W]
    lon, lat = apply_affine(A, xx.ravel().astype(float), yy.ravel().astype(float))
    inside = np.zeros(H * W, bool)
    for g in getattr(poly, 'geoms', [poly]):
        inside |= MPath(np.asarray(g.exterior.coords)).contains_points(np.c_[lon, lat])
    inside = inside.reshape(H, W)
    iou = float((inside & sil).sum() / max((inside | sil).sum(), 1))
    px_km = km_error(apply_affine(A, W / 2, H / 2), apply_affine(A, W / 2 + 1, H / 2))
    control, check = errs(reg['control_points']), errs(reg.get('check_points', []))
    rms = lambda e: float(np.sqrt(np.mean([x['error_km'] ** 2 for x in e]))) if e else None
    return dict(affine=A.tolist(), inverse=Ai.tolist(), pixel_size_km=round(px_km, 2), control=control, check=check,
                control_rmse_km=rms(control), check_rmse_km=rms(check), outline_iou=round(iou, 3))


# ----------------------------------------------------------------------------------- classes
def class_edges(classes):
    """Continuous interval [lo, hi) of every class under the documented edge convention."""
    out = []
    for i, c in enumerate(classes):
        lo = c['lower_displayed'] if c['lower_displayed'] is not None else -np.inf
        hi = c['upper_displayed'] if c['upper_displayed'] is not None else np.inf
        if i > 0:
            prev = classes[i - 1]['upper_displayed']
            lo = (prev + c['lower_displayed']) / 2 if c['lower_displayed'] is not None and c.get('lower_inclusive', True) else prev
        if i < len(classes) - 1:
            nxt = classes[i + 1]
            hi = (c['upper_displayed'] + nxt['lower_displayed']) / 2 if nxt.get('lower_inclusive', True) else c['upper_displayed']
        out.append((float(lo), float(hi)))
    return out


def classify_values(values, classes):
    """Class index (0..n-1) of continuous values under the edge convention; values beyond the ends go to the end classes."""
    edges = class_edges(classes)
    inner = [hi for _, hi in edges[:-1]]
    v = np.asarray(values, float)
    out = np.searchsorted(inner, v, side='right')
    return np.where(np.isfinite(v), out, -1)


def interval_deviation(values, class_index, classes):
    """Distance of each value outside its reference class interval (0 inside; NaN where undefined)."""
    edges = class_edges(classes)
    v = np.asarray(values, float)
    k = np.asarray(class_index)
    lo = np.array([e[0] for e in edges])
    hi = np.array([e[1] for e in edges])
    ok = (k >= 0) & np.isfinite(v)
    kk = np.where(ok, k, 0)
    d = np.where(v < lo[kk], lo[kk] - v, np.where(v >= hi[kk], v - hi[kk], 0.0))
    return np.where(ok, d, np.nan)


def classify_image(img, reg_affine_inverse, colours, lat, lon, tolerance=45.0, majority=0.6, coverage=0.5):
    """Reference class per grid cell from the published image.

    Every pixel of the cell footprint is matched to the nearest legend colour within the tolerance;
    lines and labels match nothing and are ignored. A cell gets the majority class when it holds at
    least `majority` of the matched pixels and matched pixels cover at least `coverage` of the footprint;
    otherwise it is uncertain (-1). Cells outside the mapped country are -2.
    """
    Ai = np.asarray(reg_affine_inverse)
    H, W, _ = img.shape
    cols = np.asarray(colours, float)
    dist = np.sqrt(((img[:, :, None, :] - cols[None, None]) ** 2).sum(axis=3))
    nearest = dist.argmin(axis=2)
    matched = dist.min(axis=2) <= tolerance
    white = img.sum(axis=2) >= 3 * 248
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    hy, hx = abs(lat[1] - lat[0]) / 2, abs(lon[1] - lon[0]) / 2
    out = np.full((len(lat), len(lon)), -2, int)
    share = np.zeros((len(lat), len(lon)))
    for i, y in enumerate(lat):
        for j, x in enumerate(lon):
            corners = np.array([apply_affine(Ai, a, b) for a, b in [(x - hx, y - hy), (x + hx, y - hy), (x - hx, y + hy), (x + hx, y + hy)]])
            c0, c1 = int(np.floor(corners[:, 0].min())), int(np.ceil(corners[:, 0].max()))
            r0, r1 = int(np.floor(corners[:, 1].min())), int(np.ceil(corners[:, 1].max()))
            if c1 <= 0 or r1 <= 0 or c0 >= W or r0 >= H:
                continue
            c0, r0, c1, r1 = max(c0, 0), max(r0, 0), min(c1, W), min(r1, H)
            win_m, win_n, win_w = matched[r0:r1, c0:c1], nearest[r0:r1, c0:c1], white[r0:r1, c0:c1]
            if win_w.mean() > 0.5:
                continue                                       # mostly outside the mapped country
            if win_m.mean() < coverage:
                out[i, j] = -1
                continue
            counts = np.bincount(win_n[win_m], minlength=len(cols))
            k = counts.argmax()
            share[i, j] = counts[k] / counts.sum()
            out[i, j] = k if share[i, j] >= majority else -1
    return out, share


# ----------------------------------------------------------------------------------- comparisons
def comparison_mode(record, extraction, season_months, period_years=None):
    """Highest comparison mode the evidence supports, with the reasons for anything lower.

    `extraction` is the analyst record (registration, legend colours, classification settings) with
    its review state; a draft or stale extraction keeps the reference at visual_only.
    """
    reasons = []
    rep = record['representation']
    state = extraction_state(record, extraction)
    if rep['kind'] == 'numeric_grid' and state == 'reviewed':
        return 'numeric_comparison', reasons
    if extraction is None:
        reasons.append('not georeferenced or digitized')
    elif state != 'reviewed':
        reasons.append('georeferencing and legend classes not reviewed' if state == 'draft' else f'extraction review is {state}')
    if reasons:
        return 'visual_only', reasons
    temporal = record['temporal']
    season_match = list(record['quantity']['season_months'] or []) == list(season_months)
    if not season_match:
        reasons.append('season months differ')
    if temporal.get('reference_years') is None:
        reasons.append(f'reference period {temporal.get("reference_years_reason", NOT_DOCUMENTED)}')
    elif period_years is not None and list(temporal['reference_years']) != list(period_years):
        reasons.append(f'reference period {temporal["reference_years"]} differs from {period_years}')
    if reasons:
        return 'exploratory_class_comparison', reasons
    return 'matched_class_comparison', reasons


REVIEW_FIELDS = ('legend', 'registration', 'classification', 'edge_convention')


def extraction_hash(extraction):
    return hashlib.sha256(json.dumps({k: extraction.get(k) for k in REVIEW_FIELDS}, sort_keys=True).encode()).hexdigest()


def extraction_state(record, extraction):
    """draft | reviewed | stale (the document, panel or analyst choices changed after the review)."""
    if extraction is None:
        return 'missing'
    review = extraction.get('review')
    if extraction.get('status') != 'reviewed' or not review:
        return 'draft'
    if (review.get('document_sha256') != record['identity']['document_sha256']
            or review.get('panel_sha256') != record['location'].get('extracted_image_sha256')
            or review.get('content_sha256') != extraction_hash(extraction)):
        return 'stale'
    return 'reviewed'


def compare_numeric_fields(field, reference, weights, representation):
    """Bias, MAE, RMSE and spatial correlation (area-weighted). Refuses image-derived class data."""
    if representation in CLASS_REPRESENTATIONS:
        raise ValueError(f'Numeric comparison refuses a {representation} reference: classes are intervals, not values')
    f, r, w = (np.asarray(a, float) for a in (field, reference, weights))
    ok = np.isfinite(f) & np.isfinite(r) & (w > 0)
    if not ok.any():
        raise ValueError('No comparable cells')
    d, ww = (f - r)[ok], w[ok] / w[ok].sum()
    fm, rm = (f[ok] * ww).sum(), (r[ok] * ww).sum()
    cov = (ww * (f[ok] - fm) * (r[ok] - rm)).sum()
    corr = cov / np.sqrt((ww * (f[ok] - fm) ** 2).sum() * (ww * (r[ok] - rm) ** 2).sum())
    return dict(bias=float((ww * d).sum()), mae=float((ww * np.abs(d)).sum()), rmse=float(np.sqrt((ww * d ** 2).sum())),
                spatial_correlation=float(corr), comparable_area=float(w[ok].sum()))


def compare_reference_classes(field, reference_class, classes, weights, assumptions):
    """Class agreement of a continuous field with a classified reference (area-weighted).

    Returns exact and within-one-class agreement, the area-weighted confusion matrix (rows reference,
    columns field), the distance of field values outside the reference interval, and the comparable
    and uncertain areas. The reference class supplies an interval, never a value.
    """
    f = np.asarray(field, float)
    ref = np.asarray(reference_class)
    w = np.asarray(weights, float)
    country = w > 0
    comparable = country & (ref >= 0) & np.isfinite(f)
    uncertain = country & (ref == -1)
    fc = classify_values(f, classes)
    n = len(classes)
    conf = np.zeros((n, n))
    for a, b, ww in zip(ref[comparable], fc[comparable], w[comparable]):
        conf[a, b] += ww
    total = conf.sum()
    dev = interval_deviation(f, np.where(comparable, ref, -1), classes)
    dv, dw = dev[comparable], w[comparable]
    order = np.argsort(dv)
    cum = np.cumsum(dw[order]) / dw.sum() if len(dv) else []
    pct = lambda q: float(dv[order][np.searchsorted(cum, q)]) if len(dv) else None
    diff = fc[comparable] - ref[comparable]
    return dict(exact_agreement=float(w[comparable][diff == 0].sum() / total) if total else None,
                within_one_class=float(w[comparable][np.abs(diff) <= 1].sum() / total) if total else None,
                field_wetter_share=float(w[comparable][diff > 0].sum() / total) if total else None,
                field_drier_share=float(w[comparable][diff < 0].sum() / total) if total else None,
                confusion_area=conf.round(1).tolist(), class_labels=[c['source_label'] for c in classes],
                interval_deviation=dict(mean=float((dv * dw).sum() / dw.sum()) if len(dv) else None,
                                        median=pct(0.5), p90=pct(0.9), share_inside=float(dw[dv == 0].sum() / dw.sum()) if len(dv) else None),
                comparable_area=float(w[comparable].sum()), uncertain_area=float(w[uncertain].sum()),
                unmapped_area=float(w[country & (ref == -2)].sum()), assumptions=assumptions)


def implied_membership(reference_class, classes, threshold):
    """Membership a classified reference implies for 'value >= threshold': 1, 0, or -1 when a class straddles it."""
    edges = class_edges(classes)
    ref = np.asarray(reference_class)
    out = np.full(ref.shape, -1)
    for k, (lo, hi) in enumerate(edges):
        if lo >= threshold - EDGE_TOLERANCE:
            out[ref == k] = 1
        elif hi <= threshold + EDGE_TOLERANCE:
            out[ref == k] = 0
    out[ref < 0] = -1
    return out

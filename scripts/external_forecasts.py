r"""Official seasonal outlooks (ICPAC, EMI): discovery, versioned download and standardized records.

Three steps, kept separate so that an unchanged source never forces recalculation:

  refresh   (network) discover the configured products, download them and keep a versioned
            snapshot per content hash (SHA-256) under the cache root. Every check is appended
            to retrieval_log.jsonl; current.json points to the latest snapshot of each source.
  prepare   (offline) turn the current snapshots into standardized records using the
            extraction records in config/external_forecasts/extractions/. A record applies
            only to the exact source bytes it names (source_sha256): a replaced image or PDF
            becomes "needs_extraction_review" automatically.
  review    mark an extraction record validated (or rejected) after a person has checked it
            against the source figure; validation is stored against the source hash.

Representations (the provider's product type is preserved, nothing is forced into a grid):
  dominant_category_map       favoured tercile and the printed probability interval per place
  zone_tercile_probabilities  three printed probabilities attached to a named forecast zone
  narrative                   the provider's explanatory text with its location

Metadata the provider does not state stays null: a retrieval time, an HTTP Last-Modified
header or a PDF creation date is recorded under its own name, never as the issue date.

    python scripts\external_forecasts.py refresh --registry config\external_forecasts\ondj_2026_27.json
    python scripts\external_forecasts.py status  --registry config\external_forecasts\ondj_2026_27.json
    python scripts\external_forecasts.py review  --registry config\external_forecasts\ondj_2026_27.json ^
           --record emi_bega_2026_27_outlook --reviewer "Name"
"""
import argparse
import hashlib
import html
import io
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXTRACTION_VERSION = 1
USER_AGENT = 'Mozilla/5.0 (compatible; calibrated_seasonal_rainfall research; +https://github.com/YonSci/calibrated_seasonal_rainfall)'
# ICPAC resource types (from the site's product filter): different products, different identifiers.
ICPAC_RESOURCE_TYPES = {'27': 'rainfall_tercile_probability', '4': 'rainfall_total_mm', '23': 'rainfall_anomaly',
                        '25': 'rainfall_anomaly', '18': 'rainfall_threshold_exceedance_300mm',
                        '20': 'rainfall_threshold_exceedance_400mm', '5': 'temperature_tercile_probability'}
CATEGORIES = ('below', 'near', 'above')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def resolve(p):
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def rel(p):
    """Repository-relative path with forward slashes (absolute if outside the repository)."""
    p = Path(p).resolve()
    return (p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).as_posix()


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding='utf-8', newline='')
    tmp.replace(p)


def fetch(url, retries=3, timeout=120):
    """GET with a descriptive user agent; returns (final_url, bytes, headers)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.geturl(), r.read(), dict(r.headers)
        except Exception as exc:              # network errors are retried, then reported
            last = exc
            time.sleep(2 * (attempt + 1))
    raise OSError(f'Could not retrieve {url}: {last}')


def _cp1252_fallback(err):
    # Pages that are UTF-8 except for a stray Windows-1252 byte (e.g. an en dash in "50–70%").
    return err.object[err.start:err.end].decode('cp1252', 'replace'), err.end


import codecs                                          # noqa: E402
codecs.register_error('cp1252_fallback', _cp1252_fallback)


def decode(body):
    return body.decode('utf-8', 'cp1252_fallback')


def text_of(fragment):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragment))).replace('�', ' ').strip()


# ======================================================================================= adapters
class ICPACAdapter:
    """ICPAC seasonal forecast pages: /seasonal-forecast/<slug>/?region=<r>&resource_type=<t>."""

    def __init__(self, spec):
        self.spec = spec

    def discover(self):
        s = self.spec
        _, page, _ = fetch(s['index_url'])
        index = page.decode('utf-8', 'cp1252_fallback')
        links = sorted(set(html.unescape(x) for x in re.findall(r'href="(/seasonal-forecast/[^"/]+/\?[^"]*)"', index)))
        products = {}
        for link in links:
            parsed = urllib.parse.urlparse(link)
            slug = parsed.path.strip('/').split('/')[-1]
            q = dict(urllib.parse.parse_qsl(parsed.query))
            if slug == s['slug'] and q.get('region') == s['region']:
                products[q.get('resource_type')] = ICPAC_RESOURCE_TYPES.get(q.get('resource_type'), 'other')
        if s['resource_type'] not in products:
            raise ValueError(f'ICPAC: {s["slug"]} region {s["region"]} resource_type {s["resource_type"]} not listed at {s["index_url"]}')
        # Keep region and resource_type: different regional products share the same path.
        detail = urllib.parse.urljoin(s['index_url'], f'/seasonal-forecast/{s["slug"]}/?region={s["region"]}&resource_type={s["resource_type"]}')
        final, body, _ = fetch(detail)
        doc = body.decode('utf-8', 'cp1252_fallback')
        items = re.split(r'<div[^>]*class="forecast-item', doc)[1:]
        item = next((i for i in items if f'alt="{s["image_alt"]}"' in i), None)
        if item is None:
            raise ValueError(f'ICPAC: no forecast item with alt="{s["image_alt"]}" on {detail}')
        link = re.search(r'<a[^>]+href="([^"]+)"[^>]*\bdownload="([^"]+)"', item)
        if not link:
            raise ValueError('ICPAC: the forecast item has no download link')
        label = html.unescape(link.group(2))
        missing = [w for w in s['expected_label'] if w not in label]
        if missing:
            raise ValueError(f'ICPAC: product label {label!r} lacks {missing}; refusing a possibly different season or region')
        rich = re.search(r'<div class="rich-text">(.*?)</div>', item, re.S)
        title = re.search(r'<title>(.*?)</title>', doc, re.S)
        return dict(detail_url=final, download_url=urllib.parse.urljoin(final, html.unescape(link.group(1))), label=label,
                    page_title=text_of(title.group(1)) if title else None,
                    narrative=[dict(text=text_of(li), locator='detail page, rainfall forecast item')
                               for li in re.findall(r'<li[^>]*>(.*?)</li>', rich.group(1), re.S)] if rich else [],
                    products_listed_for_season={k: v for k, v in sorted(products.items())})


def _years(text):
    """Years written as 2026_27, 2026/27, 2026-27, 202627 or 2026 -> set of full years."""
    out = set()
    for a, b in re.findall(r'(20\d\d)\s*[_/\-]?\s*(\d{2})(?!\d)', text):
        out.update({int(a), int(a[:2] + b)})
    out.update(int(y) for y in re.findall(r'20\d\d', text))
    return out


class EMIAdapter:
    """EMI seasonal forecasts and seasonal hydromet bulletins (title -> detail page -> PDF)."""

    def __init__(self, spec):
        self.spec = spec

    def outlook_part(self, title):
        """For 'X assessment and Y outlook' titles only the outlook half may match."""
        t = title.lower()
        parts = re.split(r'assess?ment\s+and', t)
        return parts[-1] if len(parts) > 1 else t

    def matches(self, title):
        s = self.spec
        part = self.outlook_part(title)
        return s['outlook_season'] in part and set(s['outlook_years']) <= _years(part)

    def discover(self):
        s = self.spec
        candidates, errors = [], []
        for listing in s['listing_urls']:
            try:                                  # each listing on its own: one failure must not hide the others
                _, body, _ = fetch(listing)
            except OSError as exc:
                errors.append(str(exc))
                continue
            doc = body.decode('utf-8', 'cp1252_fallback')
            for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', doc, re.S):
                title = text_of(inner)
                if title and self.matches(title):
                    candidates.append((urllib.parse.urljoin(listing, html.unescape(href)), title, listing))
        if not candidates:
            raise ValueError(f'EMI: no product whose outlook part names {s["outlook_season"]} {s["outlook_years"]}'
                             + (f' (listing errors: {"; ".join(errors)})' if errors else ''))
        # Take the first matching product that actually carries a document; a page published before its
        # PDF is attached (a placeholder) is recorded and skipped.
        skipped = []
        for detail, title, listing in dict.fromkeys(candidates):
            try:
                final, body, _ = fetch(detail)
            except OSError as exc:
                skipped.append(dict(title=title, url=detail, reason=str(exc)))
                continue
            doc = body.decode('utf-8', 'cp1252_fallback')
            pdfs = [html.unescape(x) for x in re.findall(r'(?:href|src|data)="([^"]+\.pdf[^"]*)"', doc, re.I)]
            if not pdfs:
                skipped.append(dict(title=title, url=final, reason='no PDF on the page yet'))
                continue
            return dict(detail_url=final, download_url=urllib.parse.urljoin(final, pdfs[0]), label=title, listing_url=listing,
                        other_matches=[c[1] for c in candidates if c[1] != title], skipped=skipped, narrative=[])
        raise ValueError('EMI: no matching product has a PDF yet: ' + '; '.join(f'{s["title"]} ({s["reason"]})' for s in skipped))


ADAPTERS = {'icpac': ICPACAdapter, 'emi': EMIAdapter}


def staging(out):
    """Sibling staging folder in the form the project's safe publisher expects."""
    out = Path(out)
    tmp = out.with_name(out.name + '_building_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    tmp.mkdir(parents=True)
    return tmp


def publish(tmp, out):
    """Replace `out` with the complete staging folder; the previous output is kept as a backup
    and restored if the swap fails (Windows file locks)."""
    from verify2026_outputs import publish_stage
    publish_stage(tmp, out, regenerate=True)


# ======================================================================================= refresh
def cache_dir(registry, cache_root):
    return resolve(cache_root) / registry['id']


def refresh(registry, cache_root):
    """Check every source; keep a new snapshot only when the content hash changed."""
    base = cache_dir(registry, cache_root)
    base.mkdir(parents=True, exist_ok=True)
    current_path = base / 'current.json'
    current = read_json(current_path) if current_path.is_file() else {}
    log = base / 'retrieval_log.jsonl'
    # The latest check per source, kept apart from current.json (a stage input) so routine
    # checks never force recalculation.
    status_path = base / 'refresh_status.json'
    latest = read_json(status_path) if status_path.is_file() else {}
    changed = []
    for spec in registry['sources']:
        checked = now()
        try:
            found = ADAPTERS[spec['adapter']](spec).discover()
            final, data, headers = fetch(found['download_url'])
        except (OSError, ValueError) as exc:
            entry = dict(source_id=spec['id'], checked_utc=checked, status='failed', error=str(exc))
            with log.open('a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
            latest[spec['id']] = dict(entry, saved_snapshot=current.get(spec['id'], {}).get('sha256'))
            print(f'{spec["id"]}: retrieval failed ({exc}); the previous snapshot stays current')
            continue
        digest = sha256(data)
        ext = '.pdf' if data[:4] == b'%PDF' else '.png' if data[:8] == b'\x89PNG\r\n\x1a\n' else Path(urllib.parse.urlparse(final).path).suffix
        folder = base / spec['id']
        folder.mkdir(exist_ok=True)
        stored = folder / f'{digest[:16]}{ext}'
        new = not stored.is_file()
        if new:
            stored.write_bytes(data)
            meta = dict(
                source_id=spec['id'], provider=spec['provider'], product=spec['product'],
                representation=spec['representation'], label=found['label'],
                requested_url=found['detail_url'], download_url=final, file=str(stored.relative_to(ROOT)).replace('\\', '/'),
                sha256=digest, bytes=len(data), retrieved_utc=checked,
                target_start=spec['target_start'], target_end=spec['target_end'], season_label=spec['season_label'],
                # Not stated by the provider on the checked pages -> null (never a retrieval or file date).
                issue_date=spec.get('issue_date'), initialization=spec.get('initialization'),
                reference_period=spec.get('reference_period'),
                http_last_modified=headers.get('Last-Modified'), narrative=found.get('narrative', []),
                products_listed_for_season=found.get('products_listed_for_season'),
                other_title_matches=found.get('other_matches'), skipped_candidates=found.get('skipped'), extraction_version=EXTRACTION_VERSION)
            if ext == '.pdf':
                meta['pdf_metadata'] = pdf_metadata(stored)
            write_json(stored.with_suffix('.json'), meta)
        previous = current.get(spec['id'], {}).get('sha256')
        if previous != digest:
            changed.append(spec['id'])
        current[spec['id']] = dict(sha256=digest, file=str(stored.relative_to(ROOT)).replace('\\', '/'),
                                   meta=str(stored.with_suffix('.json').relative_to(ROOT)).replace('\\', '/'))
        entry = dict(source_id=spec['id'], checked_utc=checked, status='ok', sha256=digest, changed=previous != digest,
                     skipped_candidates=found.get('skipped') or None,
                     new_snapshot=new, download_url=final)
        with log.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
        latest[spec['id']] = entry
        print(f'{spec["id"]}: {"CHANGED" if previous and previous != digest else "new" if previous is None else "unchanged"} '
              f'{digest[:12]} ({len(data) / 1e3:.0f} kB) from {final}')
    if json.dumps(read_json(current_path) if current_path.is_file() else None, sort_keys=True) != json.dumps(current, sort_keys=True):
        write_json(current_path, current)
    write_json(status_path, latest)
    return changed


def pdf_metadata(path):
    import pypdf
    meta = pypdf.PdfReader(str(path)).metadata or {}
    return {k.lstrip('/'): str(v) for k, v in meta.items()}


# ======================================================================================= extraction
def extraction_record(registry, source_id):
    p = resolve(registry['extractions_dir']) / f'{source_id}.json'
    return (read_json(p), p) if p.is_file() else (None, p)


# Everything in an extraction record that determines published numbers. A review covers exactly
# these contents: editing a probability, an arrow position, the calibration or the legend template
# after review sends the record back to review even when the source file is unchanged.
CONTENT_FIELDS = ('method', 'extraction_version', 'template', 'zones', 'source_locator', 'figure_axes', 'figure_sha256')


def content_sha256(record):
    fields = {k: record.get(k) for k in CONTENT_FIELDS}
    if record.get('derived_sha256'):              # digitized reference layers: the derived file is part of the content
        fields['derived_sha256'] = record['derived_sha256']
    return sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode('utf-8'))


def extraction_check(record, digest):
    """(status, note): validated only if both the source file and the reviewed contents are unchanged."""
    if record is None:
        return 'needs_extraction', 'No extraction record for this source'
    if record.get('source_sha256') != digest:
        return 'needs_extraction_review', 'The source file changed after this record was made'
    state = record.get('status')
    if state == 'validated':
        reviewed = (record.get('review') or {}).get('content_sha256')
        if reviewed != content_sha256(record):
            return 'needs_extraction_review', 'The extracted values or settings changed after review'
        return 'validated', None
    if state == 'rejected':
        return 'rejected', (record.get('review') or {}).get('note')
    return 'needs_extraction_review', 'Draft extraction awaiting review'


def extraction_status(record, digest):
    return extraction_check(record, digest)[0]


def find_outlook_pages(pdf_path, keywords, require_image=True):
    """Pages whose text names the target season and an outlook, and that carry a figure."""
    import pypdf
    reader = pypdf.PdfReader(str(pdf_path))
    hits = []
    for i, page in enumerate(reader.pages, 1):
        # Layout mode keeps words whole where plain mode splits them ("southe rn").
        text = re.sub(r'\s+', ' ', page.extract_text(extraction_mode='layout') or '')
        score = sum(k.lower() in text.lower() for k in keywords)
        has_outlook = re.search(r'(?i)outlook|advisory|forecast', text) is not None
        if score and has_outlook and (not require_image or len(page.images)):
            hits.append(dict(page=i, keyword_hits=score, images=len(page.images), text=text))
    hits.sort(key=lambda h: (-h['keyword_hits'], h['page']))
    return hits


def pdf_figure(pdf_path, page, out_path):
    """Write the largest embedded image of a PDF page (the original figure, not a re-rendering)."""
    import pypdf
    page_obj = pypdf.PdfReader(str(pdf_path)).pages[page - 1]
    images = sorted(page_obj.images, key=lambda im: len(im.data), reverse=True)
    if not images:
        raise ValueError(f'No figure on PDF page {page}')
    im = images[0]
    out_path = Path(out_path).with_suffix(Path(im.name).suffix or '.png')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(im.data)
    return out_path, sha256(im.data), im.image.size


def digitize_dominant_map(png_path, template, lat, lon, shift_px=(0, 0)):
    """Dominant-category map (favoured tercile + printed interval) -> the platform's 0.25 deg grid.

    Georeference from the detected axis frame and tick marks (expected tick values from the
    template), classify pixels against the legend's own colour boxes, then take a majority
    vote of classified pixels inside each grid cell. Boundary lines and unlabelled colours do
    not vote. Returns arrays and quality-control numbers; nothing is interpolated.
    """
    from PIL import Image
    a = np.asarray(Image.open(png_path).convert('RGB')).astype(int)
    H, W, _ = a.shape
    dark = a.sum(-1) < 150
    # Axis frame: the longest dark horizontal and vertical lines.
    rows = [y for y in range(H) if dark[y].sum() > 0.5 * W]
    cols = [x for x in range(W) if dark[:, x].sum() > 0.5 * H]
    if len(rows) < 2 or len(cols) < 2:
        raise ValueError('Axis frame not found')
    top, bottom, left, right = min(rows), max(rows), min(cols), max(cols)

    def groups(idx):
        out, cur = [], []
        for i in idx:
            if cur and i != cur[-1] + 1:
                out.append(sum(cur) / len(cur))
                cur = []
            cur.append(i)
        if cur:
            out.append(sum(cur) / len(cur))
        return out
    xt = groups([x for x in range(left + 2, right - 1) if dark[bottom + 2:bottom + 11, x].sum() >= 5])
    yt = groups([y for y in range(top + 1, bottom) if dark[y, left - 9:left - 1].sum() >= 5])
    if len(xt) != len(template['x_ticks_deg']) or len(yt) != len(template['y_ticks_deg']):
        raise ValueError(f'Tick count differs from the template: {len(xt)} x, {len(yt)} y')
    fx = np.polyfit(template['x_ticks_deg'], xt, 1)
    fy = np.polyfit(template['y_ticks_deg'], yt, 1)
    res_x = float(np.max(np.abs(np.polyval(fx, template['x_ticks_deg']) - xt)))
    res_y = float(np.max(np.abs(np.polyval(fy, template['y_ticks_deg']) - yt)))
    # Legend: runs of one colour down the colour-bar column, grouped into bars by white gaps.
    lx = template['legend_x']
    col = a[:, lx]
    boxes, start = [], None
    for y in range(1, H):
        same = np.abs(col[y] - col[y - 1]).sum() < 12
        if start is None:
            start = y
        if not same:
            if y - start > 15 and not (col[start] > 245).all() and col[start].sum() > 60:
                boxes.append((start, y - 1, tuple(int(v) for v in col[(start + y) // 2])))
            start = y
    # Bars top to bottom, each with its own boxes (e.g. Above 40-100 %, Normal and Below 40-90 %).
    expected = sum(len(bar['intervals_top_down']) for bar in template['legend_bars'])
    if len(boxes) != expected:
        raise ValueError(f'Legend boxes found: {len(boxes)}, expected {expected}; the legend layout changed')
    classes, k = [], 0                              # (category, interval, rgb)
    for bar in template['legend_bars']:
        for interval in bar['intervals_top_down']:
            classes.append((bar['category'], interval, boxes[k][2]))
            k += 1
    palette = np.array([c[2] for c in classes])
    grey = np.array(template['no_forecast_rgb'])
    inner = a[top + 2:bottom - 1, left + 2:right - 1]
    flat = inner.reshape(-1, 3)
    dist = np.sqrt(((flat[:, None, :] - palette[None]) ** 2).sum(-1))
    best = dist.argmin(1)
    ok = dist.min(1) <= template['colour_tolerance']
    is_grey = np.sqrt(((flat - grey) ** 2).sum(-1)) <= template['colour_tolerance']
    label = np.where(ok, best, np.where(is_grey, -2, -1)).reshape(inner.shape[:2])   # -2 no forecast, -1 other
    # Pixel centres -> lon/lat.
    xs = np.arange(left + 2, right - 1)
    ys = np.arange(top + 2, bottom - 1)
    plon = (xs + shift_px[0] - fx[1]) / fx[0]            # shift_px: registration sensitivity only
    plat = (ys + shift_px[1] - fy[1]) / fy[0]
    step = float(abs(lat[1] - lat[0]))
    cat = np.full((len(lat), len(lon)), '', dtype=object)
    lo = np.full((len(lat), len(lon)), np.nan)
    hi = np.full((len(lat), len(lon)), np.nan)
    state = np.full((len(lat), len(lon)), 'outside', dtype=object)
    votes_used = np.zeros((len(lat), len(lon)), int)
    for i, la in enumerate(lat):
        rsel = np.where(np.abs(plat - la) <= step / 2)[0]
        if not len(rsel):
            continue
        for j, lo_ in enumerate(lon):
            csel = np.where(np.abs(plon - lo_) <= step / 2)[0]
            if not len(csel):
                continue
            v = label[np.ix_(rsel, csel)].ravel()
            counts = {k: int((v == k).sum()) for k in set(v.tolist())}
            classified = {k: n for k, n in counts.items() if k >= 0}
            n_grey = counts.get(-2, 0)
            if classified and sum(classified.values()) >= n_grey:
                k = max(classified, key=classified.get)
                cat[i, j], (lo[i, j], hi[i, j]) = classes[k][0], classes[k][1]
                state[i, j], votes_used[i, j] = 'forecast', classified[k]
            elif n_grey:
                state[i, j] = 'no_forecast_shown'
            else:
                state[i, j] = 'unclassified'
    qc = dict(frame_px=[int(left), int(top), int(right), int(bottom)], x_ticks_px=xt, y_ticks_px=yt,
              px_per_degree=[float(fx[0]), float(-fy[0])], tick_fit_max_residual_px=[res_x, res_y],
              legend_colours={f'{c}_{iv[0]}-{iv[1]}': rgb for c, iv, rgb in classes},
              pixels_classified_share=float(ok.mean()), pixels_no_forecast_share=float(is_grey.mean()))
    return dict(category=cat, low=lo, high=hi, state=state, votes=votes_used), qc


def prepare(registry, cache_root, grid_path, out_dir):
    """Standardized records + previews for the current snapshots (offline, deterministic)."""
    import xarray as xr
    out_dir = Path(out_dir)
    tmp = staging(out_dir)
    (tmp / 'previews').mkdir(parents=True)
    current_path = cache_dir(registry, cache_root) / 'current.json'
    if not current_path.is_file():
        raise FileNotFoundError(f'{current_path}: no snapshots yet; run with --refresh-external first')
    current = read_json(current_path)
    with xr.open_dataset(grid_path) as g:
        lat, lon = g.lat.values.astype(float), g.lon.values.astype(float)
    manifest, records = [], []
    for spec in registry['sources']:
        cur = current.get(spec['id'])
        if not cur:
            manifest.append(dict(source_id=spec['id'], provider=spec['provider'], status='not_retrieved'))
            continue
        meta = read_json(resolve(cur['meta']))
        src = resolve(cur['file'])
        if sha256(src.read_bytes()) != cur['sha256']:
            raise ValueError(f'{src}: stored bytes do not match the recorded SHA-256')
        rec, rec_path = extraction_record(registry, spec['id'])
        status, note = extraction_check(rec, cur['sha256'])
        entry = dict(meta, extraction=dict(status=status, note=note, record=rel(rec_path),
                                           content_sha256=rec and content_sha256(rec),
                                           method=rec and rec.get('method'), review=rec and rec.get('review'),
                                           checks_for_reviewer=rec and rec.get('checks_for_reviewer')))
        evidence = []
        if spec['representation'] == 'dominant_category_map':
            preview = tmp / 'previews' / f'{spec["id"]}{src.suffix}'
            shutil.copy2(src, preview)
            evidence.append(dict(id=f'{spec["id"]}_map', file=f'previews/{preview.name}', caption=meta['label']))
            fields = None
            if rec:
                try:
                    fields, qc = digitize_dominant_map(src, rec['template'], lat, lon)
                except ValueError as exc:      # e.g. a new image layout: report it instead of failing
                    status = 'needs_extraction_review'
                    entry['extraction'].update(status=status, note=f'The digitization template does not fit this image: {exc}')
            if fields is not None:
                # Registration sensitivity: the same digitization with the map shifted by one source pixel.
                shifts = {}
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            alt, _ = digitize_dominant_map(src, rec['template'], lat, lon, (dx, dy))
                            shifts[f'{dx},{dy}'] = dict(category=alt['category'].tolist(), state=alt['state'].tolist())
                write_json(tmp / f'{spec["id"]}_grid_shifts.json', shifts)
                grid = dict(lat=lat.tolist(), lon=lon.tolist(), category=fields['category'].tolist(),
                            low=np.where(np.isnan(fields['low']), None, fields['low']).tolist(),
                            high=np.where(np.isnan(fields['high']), None, fields['high']).tolist(),
                            state=fields['state'].tolist())
                write_json(tmp / f'{spec["id"]}_grid.json', grid)
                entry['digitization_qc'] = qc
                records.append(dict(record_id=spec['id'], source_id=spec['id'], provider=spec['provider'], product=spec['product'],
                                    representation='dominant_category_map', target_start=spec['target_start'],
                                    target_end=spec['target_end'], reference_period=meta.get('reference_period'),
                                    extraction_status=status, extraction_method=rec['method'], grid_file=f'{spec["id"]}_grid.json',
                                    interval_semantics='printed probability interval of the favoured category; the other two '
                                                       'category probabilities are not published and are not inferred',
                                    no_forecast_meaning=rec['template'].get('no_forecast_meaning'), evidence_ids=[e['id'] for e in evidence],
                                    qc=qc))
        elif spec['representation'] == 'zone_tercile_probabilities':
            pages = find_outlook_pages(src, spec['page_keywords'])
            entry['candidate_pages'] = [dict(page=p['page'], keyword_hits=p['keyword_hits'], images=p['images']) for p in pages]
            if not pages:
                entry['extraction']['status'] = 'needs_extraction_review'
                entry['extraction']['note'] = 'No candidate outlook page found'
            else:
                page = pages[0]['page']
                fig, fig_sha, size = pdf_figure(src, page, tmp / 'previews' / f'{spec["id"]}_page{page}_figure')
                evidence.append(dict(id=f'{spec["id"]}_page{page}', file=f'previews/{fig.name}',
                                     caption=f'{meta["label"]}, PDF page {page}', pdf_page=page))
                summary = pages[0]['text']
                entry['narrative'] = [dict(text=t.strip(), locator=f'PDF page {page}')
                                      for t in re.findall(r'((?:October|November|December|January)\s*:.*?)(?=(?:October|November|December|January)\s*:|$)', summary)]
                if rec:
                    if rec['source_locator']['pdf_page'] != page:
                        status = 'needs_extraction_review'
                        entry['extraction'].update(status=status, note=f'Outlook page discovered on page {page}, the record names page {rec["source_locator"]["pdf_page"]}')
                    if rec.get('figure_sha256') and rec['figure_sha256'] != fig_sha:
                        status = 'needs_extraction_review'
                        entry['extraction'].update(status=status, note='The embedded figure differs from the reviewed one')
                    for z in rec['zones']:
                        p = z['probabilities']
                        if abs(sum(p.values()) - 1) > 1e-6 or set(p) != set(CATEGORIES):
                            raise ValueError(f'{rec_path}: zone {z["zone_label"]} probabilities must name below/near/above and sum to 1')
                        records.append(dict(record_id=f'{spec["id"]}_zone_{z["zone_label"]}', source_id=spec['id'], provider=spec['provider'],
                                            product=spec['product'], representation='zone_tercile_probabilities',
                                            target_start=spec['target_start'], target_end=spec['target_end'],
                                            source_locator=dict(rec['source_locator'], zone_label=z['zone_label']),
                                            probabilities=p, printed_order=z.get('printed_order'),
                                            anchor=z.get('anchor'), reference_period=meta.get('reference_period'),
                                            geometry_id=None, geometry_status='requires_alignment',
                                            extraction_method=rec['method'], extraction_status=status,
                                            evidence_ids=[e['id'] for e in evidence]))
        entry['evidence'] = evidence
        if entry.get('narrative'):
            records.append(dict(record_id=f'{spec["id"]}_narrative', source_id=spec['id'], provider=spec['provider'],
                                representation='narrative', text=entry['narrative'], extraction_status='verbatim',
                                target_start=spec['target_start'], target_end=spec['target_end'],
                                evidence_ids=[e['id'] for e in evidence]))
        manifest.append(entry)
    layers = []
    for layer in registry.get('reference_layers', []):
        st, note, derived = reference_check(registry, layer)
        rec, rec_path = extraction_record(registry, layer['extraction'])
        layers.append(dict(layer, status=st, note=note, derived_sha256=derived, record=rel(rec_path),
                           content_sha256=rec and content_sha256(rec), citation=rec and rec.get('citation'),
                           doi=rec and rec.get('doi'), url=rec and rec.get('url'), license_note=rec and rec.get('license_note'),
                           review=rec and rec.get('review'), checks_for_reviewer=rec and rec.get('checks_for_reviewer'),
                           region_names={k: v['name'] for k, v in (rec or {}).get('template', {}).get('regions', {}).items()}))
    write_json(tmp / 'source_manifest.json', dict(created_utc=now(), registry=registry['id'], sources=manifest, reference_layers=layers,
                                                  anomaly_products_checked=registry.get('anomaly_products_checked')))
    write_json(tmp / 'official_records.json', dict(created_utc=now(), registry=registry['id'], records=records))
    publish(tmp, out_dir)
    return out_dir


# ======================================================================================= review
def reference_layer(registry, layer_id):
    return next((r for r in registry.get('reference_layers', []) if r['id'] == layer_id), None)


def reference_check(registry, layer):
    """(status, note, derived file hash) for a reference layer (e.g. digitized rainfall regions)."""
    rec, _ = extraction_record(registry, layer['extraction'])
    mask = resolve(layer['mask'])
    if rec is None or not mask.is_file():
        return 'needs_extraction', 'Reference layer or its record is missing', None
    import xarray as xr
    with xr.open_dataset(mask) as m:
        image_sha = m.attrs.get('source_image_sha256')
    derived = sha256(mask.read_bytes())
    if image_sha != rec['source_sha256']:
        return 'needs_extraction_review', 'The digitized layer was made from a different source image', derived
    if rec.get('derived_sha256') not in (None, derived):
        return 'needs_extraction_review', 'The digitized layer changed after review', derived
    status, note = extraction_check(rec, rec['source_sha256'])
    return status, note, derived


def review(registry, record_id, reviewer, reject=False, note=None, cache_root=None):
    rec, p = extraction_record(registry, record_id)
    if rec is None:
        raise FileNotFoundError(p)
    layer = next((r for r in registry.get('reference_layers', []) if r['extraction'] == record_id), None)
    if layer:                                     # a digitized reference layer: bind the review to the derived file too
        mask = resolve(layer['mask'])
        import xarray as xr
        with xr.open_dataset(mask) as m:
            if m.attrs.get('source_image_sha256') != rec['source_sha256']:
                raise ValueError('The digitized layer was made from a different source image; digitize again first')
        rec['derived_sha256'] = sha256(mask.read_bytes())
    else:
        cache_root = cache_root or registry.get('cache_root', 'data/external_forecasts')
        current = read_json(cache_dir(registry, cache_root) / 'current.json').get(record_id, {})
        if current.get('sha256') != rec['source_sha256']:
            raise ValueError('The current source differs from the one this record describes; create a new extraction record first')
    rec['status'] = 'rejected' if reject else 'validated'
    rec['review'] = dict(reviewer=reviewer, reviewed_utc=now(), decision=rec['status'], note=note,
                         confirmed_checks=[] if reject else rec.get('checks_for_reviewer', []),
                         source_sha256=rec['source_sha256'], content_sha256=content_sha256(rec))
    write_json(p, rec)
    print(f'{record_id}: {rec["status"]} by {reviewer} for source {rec["source_sha256"][:12]}')


def status(registry, cache_root):
    current_path = cache_dir(registry, cache_root) / 'current.json'
    current = read_json(current_path) if current_path.is_file() else {}
    for spec in registry['sources']:
        cur = current.get(spec['id'])
        rec, _ = extraction_record(registry, spec['id'])
        st, note = extraction_check(rec, cur['sha256']) if cur else ('not_retrieved', None)
        print(f'{spec["id"]}: source {cur["sha256"][:12] if cur else "-"} | extraction {st}' + (f' ({note})' if note else ''))


def load_registry(path):
    reg = read_json(resolve(path))
    if reg.get('schema_version') != 1:
        raise ValueError('Unsupported external forecast registry')
    return reg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['refresh', 'prepare', 'review', 'status'])
    ap.add_argument('--registry', required=True)
    ap.add_argument('--cache-root', default='data/external_forecasts')
    ap.add_argument('--grid', help='prepare: NetCDF on the platform grid (lat, lon)')
    ap.add_argument('--out', help='prepare: output folder')
    ap.add_argument('--record', help='review: extraction record id (= source id)')
    ap.add_argument('--reviewer', help='review: name of the person who checked the record')
    ap.add_argument('--reject', action='store_true')
    ap.add_argument('--note')
    a = ap.parse_args()
    reg = load_registry(a.registry)
    if a.command == 'refresh':
        refresh(reg, a.cache_root)
    elif a.command == 'prepare':
        prepare(reg, a.cache_root, resolve(a.grid), resolve(a.out))
    elif a.command == 'review':
        if not (a.record and a.reviewer):
            ap.error('review needs --record and --reviewer')
        review(reg, a.record, a.reviewer, a.reject, a.note, a.cache_root)
    else:
        status(reg, a.cache_root)


if __name__ == '__main__':
    sys.exit(main())

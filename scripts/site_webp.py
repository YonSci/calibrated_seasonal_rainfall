"""WebP display copies of the site's PNG figures, for faster pages (docs/49).

Every PNG under site/assets gets two lossy WebP copies next to it, <name>.w640.webp and <name>.w1280.webp (at most that many
pixels wide, never enlarged). The pages show them through <picture> / srcset (web/scripts/postbuild.mjs and the map viewer),
so a phone loads the small one and a wide or high-density screen the large one; the PNG stays the full-size image behind
"Open full-size" and the download links. A copy is about a seventh (640) or a third (1280) of the PNG.

The copies are cached by the PNG's content (outputs/cache/webp/<sha1>.w<width>.webp), so a rebuild of the site, which
recreates site/assets, only encodes figures that changed. Run by scripts/build_site.py; also on its own:

  python scripts/site_webp.py [site/assets] [--workers 3]
"""
import argparse
import hashlib
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'outputs/cache/webp'
WIDTHS = (640, 1280)
QUALITY = 78


def variants(png):
    return {w: png.with_name(f'{png.stem}.w{w}.webp') for w in WIDTHS}


def _encode(job):
    from PIL import Image
    png, key = job
    im = Image.open(png)
    im.load()
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA')
    made = 0
    for w, dest in variants(png).items():
        cached = CACHE / f'{key}.w{w}.webp'
        if not cached.is_file():
            x = im if im.width <= w else im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
            tmp = cached.with_suffix('.tmp')
            x.save(tmp, 'WEBP', quality=QUALITY, method=4)
            tmp.replace(cached)
            made += 1
        shutil.copyfile(cached, dest)
    return made


def make_all(assets, workers=3):
    """Write the WebP copies of every PNG under `assets`; returns (figures, newly encoded, bytes of the copies)."""
    assets = Path(assets)
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs = [(p, hashlib.sha1(p.read_bytes()).hexdigest()) for p in sorted(assets.rglob('*.png'))]
    todo = [j for j in jobs if not all((CACHE / f'{j[1]}.w{w}.webp').is_file() for w in WIDTHS)]
    done = [j for j in jobs if j not in todo]
    for j in done:                                         # cached: copy only
        _encode(j)
    made = 0
    if todo:
        with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
            made = sum(ex.map(_encode, todo, chunksize=8))
    size = sum(d.stat().st_size for p, _ in jobs for d in variants(p).values())
    return len(jobs), made, size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('assets', nargs='?', default=str(ROOT / 'site/assets'))
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    n, made, size = make_all(a.assets, a.workers)
    print(f'WebP copies: {n} figures, {made} images encoded now, {size / 1e6:.1f} MB')


if __name__ == '__main__':
    main()

"""Large site downloads served as GitHub release assets instead of files committed with the site.

The site's data downloads (NetCDF, JSON, PDF, CSV; not HTML pages) of at least MIN_BYTES are uploaded to one GitHub release,
tag `site-files`, and the page links point there instead of to site/downloads/. This keeps the repository from growing with
every build: the files no longer enter git history, and site/ holds only pages, small data and figures.

Assets are content-addressed: the name is <first 16 hex digits of the SHA-256>-<flattened path>. An asset never changes once
uploaded, so a link published in any release keeps working, unchanged files are never uploaded twice, and archived pages need
no rewriting. config/site_files.json is the manifest of uploaded assets (an entry is added only after a successful upload);
a file whose asset is not uploaded yet stays in site/downloads/ and is linked locally, so a build never breaks the site.

  python scripts/build_site.py --upload-files     # build, upload new download files, link them
  python scripts/build_site.py                     # build; link files already uploaded, keep the others local
  python scripts/build_site.py --keep-downloads    # build with every download local (as before)
"""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'config/site_files.json'
TAG = 'site-files'
REPO = 'YonSci/calibrated_seasonal_rainfall'
MIN_BYTES = 100_000
KEEP_SUFFIXES = {'.html', '.htm'}                     # pages are viewed in the browser: they stay on the site
URL = f'https://github.com/{REPO}/releases/download/{TAG}/'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def asset_name(rel, digest):
    flat = re.sub(r'[^A-Za-z0-9._-]', '_', rel.removeprefix('downloads/').replace('/', '.'))
    return f'{digest[:16]}-{flat}'


def load_manifest():
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    return dict(description='Download files of the site served as assets of the GitHub release "site-files" (scripts/site_files.py). '
                            'Content-addressed: an asset never changes once uploaded.', release=TAG, assets={})


def save_manifest(m):
    m['assets'] = dict(sorted(m['assets'].items()))
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def gh(*args, check=True):
    return subprocess.run(['gh', *args], cwd=ROOT, capture_output=True, text=True, check=check)


def release_view():
    """(state, asset names): state 'ok', 'missing' (GitHub says the release does not exist) or 'unreachable'."""
    for _ in range(3):
        r = gh('release', 'view', TAG, '--repo', REPO, '--json', 'assets', '--jq', '.assets[].name', check=False)
        if r.returncode == 0:
            return 'ok', set(r.stdout.split())
        if 'not found' in (r.stderr or '').lower():
            return 'missing', None
    return 'unreachable', None


def remote_assets():
    """Names of the assets of the release, or None when the release does not exist or GitHub cannot be reached."""
    return release_view()[1]


def ensure_release():
    state, _ = release_view()
    if state == 'unreachable':
        raise RuntimeError('GitHub could not be reached to check the release "site-files"; nothing was uploaded')
    if state == 'missing':
        gh('release', 'create', TAG, '--repo', REPO, '--title', 'Site download files',
           '--notes', 'Data downloads of the results site (NetCDF, JSON, PDF, CSV), content-addressed: an asset never changes once '
                      'uploaded. Linked from the site; see scripts/site_files.py and config/site_files.json.',
           '--latest=false')


def upload(files):
    """files: [(local path, asset name)]; uploads in batches through a temporary folder (the asset name is the file name)."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = []
        for src, name in files:
            dst = Path(tmp) / name
            shutil.copy2(src, dst)
            staged.append(str(dst))
        for i in range(0, len(staged), 10):
            gh('release', 'upload', TAG, '--repo', REPO, *staged[i:i + 10])


def candidates(out):
    for f in sorted((out / 'downloads').rglob('*')):
        if f.is_file() and f.suffix.lower() not in KEEP_SUFFIXES and f.stat().st_size >= MIN_BYTES:
            yield f.relative_to(out).as_posix(), f


def rewrite(out, urls):
    """Point every link to an offloaded file at its asset: the page and its data use 'downloads/...' after a quote or
    parenthesis; the downloads listing links relative to its own folder."""
    pattern = re.compile(r'''(["'(])(downloads/[^"'#?)\s]+)''')
    sub = lambda m: m.group(1) + urls.get(m.group(2), m.group(2))
    targets = [out / 'index.html', *sorted((out / 'data').glob('*.json'))] if (out / 'data').is_dir() else [out / 'index.html']
    for f in targets:
        text = f.read_text(encoding='utf-8')
        new = pattern.sub(sub, text)
        if new != text:
            f.write_text(new, encoding='utf-8', newline='')
    listing = out / 'downloads/index.html'
    if listing.is_file():
        text = listing.read_text(encoding='utf-8')
        new = re.sub(r'href="([^"#?:]+)"', lambda m: f'href="{urls.get("downloads/" + m.group(1), m.group(1))}"', text)
        if new != text:
            listing.write_text(new, encoding='utf-8', newline='')


def offload(out, upload_new=False, offline=False):
    """Serve large downloads from release assets; returns a summary. Files without an uploaded asset stay local."""
    manifest = load_manifest()
    known = manifest['assets']
    files = [(rel, f, sha256(f)) for rel, f in candidates(out)]
    names = {rel: asset_name(rel, d) for rel, f, d in files}
    remote = None if offline else remote_assets()
    if remote is not None:                               # an asset missing on GitHub is not linked (and is re-uploaded)
        for name in [n for n in known if n not in remote]:
            known.pop(name)
    new = [(f, names[rel], rel, d) for rel, f, d in files if names[rel] not in known]
    if upload_new and new and not offline:
        ensure_release()
        upload([(f, n) for f, n, _, _ in {n: (f, n, rel, d) for f, n, rel, d in new}.values()])
        for f, n, rel, d in new:
            known[n] = dict(sha256=d, bytes=f.stat().st_size, first_path=rel, url=URL + n)
        save_manifest(manifest)
    urls = {rel: known[names[rel]]['url'] for rel, f, d in files if names[rel] in known}
    rewrite(out, urls)
    moved = 0
    for rel, f, d in files:
        if rel in urls:
            moved += f.stat().st_size
            f.unlink()
    for d in sorted((out / 'downloads').rglob('*'), key=lambda p: -len(p.parts)):   # remove emptied folders
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    pending = [rel for rel, f, d in files if rel not in urls]
    return dict(linked=len(urls), bytes=moved, pending=pending, uploaded=len(new) if upload_new and not offline else 0)

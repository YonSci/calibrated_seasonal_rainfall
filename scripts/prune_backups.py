"""List or prune `<name>_backup_<timestamp>_<id>` folders left by --regenerate runs.

Safe by default: prints what would be removed. Add --apply to delete.
Rules:
  * Keeps the --keep newest backups (default 1) for every output folder.
  * Never removes a backup whose live output folder is missing (it may be the only copy).
  * Never touches `_building_` staging folders; they are reported only, because the
    operational runner can recover completed staging after a publication failure.
"""
import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path
from common import ROOT

PATTERN = re.compile(r'^(?P<base>.+)_(?P<kind>backup|building)_(?P<stamp>\d{8}T\d{6}Z)_(?P<id>[0-9a-f]{8})$')


def folder_size(path):
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def scan(root):
    """Return {live_destination: [backup paths, newest first]} and the staging folders."""
    backups, staging = defaultdict(list), []
    for path in root.rglob('*'):
        if not path.is_dir():
            continue
        m = PATTERN.match(path.name)
        if not m:
            continue
        if m['kind'] == 'building':
            staging.append(path)
        else:
            backups[path.with_name(m['base'])].append((m['stamp'], path))
    return {dest: [p for _, p in sorted(items, reverse=True)] for dest, items in backups.items()}, sorted(staging)


def plan(root, keep):
    backups, staging = scan(root)
    remove, retain = [], []
    for dest, paths in sorted(backups.items()):
        if not dest.is_dir():
            retain.extend((p, 'live output missing') for p in paths)
            continue
        retain.extend((p, 'newest') for p in paths[:keep])
        remove.extend(paths[keep:])
    return remove, retain, staging


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', default='outputs', help='Folder to scan (default: outputs)')
    p.add_argument('--keep', type=int, default=1, help='Newest backups to keep per output folder (default 1)')
    p.add_argument('--apply', action='store_true', help='Delete the listed backups (otherwise preview only)')
    args = p.parse_args()
    if args.keep < 0:
        raise SystemExit('--keep must be >= 0')
    root = Path(args.root)
    root = root if root.is_absolute() else ROOT / root
    remove, retain, staging = plan(root, args.keep)
    total = 0
    for path in remove:
        size = folder_size(path)
        total += size
        print(f"{'DELETE' if args.apply else 'would delete'}  {size / 1e6:8.1f} MB  {path.relative_to(ROOT)}")
        if args.apply:
            shutil.rmtree(path)
    for path, why in retain:
        print(f'keep ({why})  {path.relative_to(ROOT)}')
    for path in staging:
        print(f'staging (not touched; see docs/35)  {path.relative_to(ROOT)}')
    verb = 'Removed' if args.apply else 'Would remove'
    print(f'{verb} {len(remove)} backup folder(s), {total / 1e6:.1f} MB. Kept {len(retain)}. Staging folders: {len(staging)}.')
    if remove and not args.apply:
        print('Preview only. Rerun with --apply to delete.')


if __name__ == '__main__':
    main()

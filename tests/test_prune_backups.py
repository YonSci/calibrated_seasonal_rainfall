import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prune_backups import plan


class PruneTests(unittest.TestCase):
    def make(self, root, *names):
        for n in names:
            (root / n).mkdir(parents=True)
            (root / n / 'f.txt').write_text('x')

    def test_keeps_newest_and_orphans_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make(root, 'a/Sep', 'a/Sep_backup_20261001T000000Z_aaaaaaaa',
                      'a/Sep_backup_20261003T000000Z_bbbbbbbb', 'a/Sep_backup_20261002T000000Z_cccccccc',
                      'b/Jun_backup_20261001T000000Z_dddddddd',          # live output missing
                      'a/Aug_building_20261004T000000Z_eeeeeeee')
            remove, retain, staging = plan(root, keep=1)
            self.assertEqual(sorted(p.name for p in remove),
                             ['Sep_backup_20261001T000000Z_aaaaaaaa', 'Sep_backup_20261002T000000Z_cccccccc'])
            kept = {p.name: why for p, why in retain}
            self.assertEqual(kept['Sep_backup_20261003T000000Z_bbbbbbbb'], 'newest')
            self.assertEqual(kept['Jun_backup_20261001T000000Z_dddddddd'], 'live output missing')
            self.assertEqual([p.name for p in staging], ['Aug_building_20261004T000000Z_eeeeeeee'])

    def test_keep_zero_and_unrelated_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make(root, 'x', 'x_backup_20261001T000000Z_aaaaaaaa', 'x_backup_notes', 'frozen_forecasts')
            remove, retain, staging = plan(root, keep=0)
            self.assertEqual([p.name for p in remove], ['x_backup_20261001T000000Z_aaaaaaaa'])
            self.assertEqual(retain, [])
            self.assertEqual(staging, [])


if __name__ == '__main__':
    unittest.main()

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_readiness as cr          # noqa: E402


class Readiness(unittest.TestCase):
    def test_season_months_cross_the_year(self):
        ondj = dict(season=dict(name='ONDJ', start='10-01', end='01-31'))
        self.assertEqual(cr.season_year_months(ondj, 2027), [(2027, 10), (2027, 11), (2027, 12), (2028, 1)])

    @unittest.skipUnless((cr.ROOT / 'data/processed').is_dir() and (cr.ROOT / 'data/raw/ecmwf_sst').is_dir(),
                         'needs the local SEAS5 and CHIRPS archive (not in the repository)')
    def test_2027_cycles_have_no_defects(self):
        for c in ('config/cycles/jan_2027_fmam.json', 'config/cycles/feb_2027_fmam.json', 'config/cycles/may_2027.json',
                  'config/cycles/sep_2027_ondj.json'):
            rows, info = cr.check_cycle(c, date(2026, 10, 20))
            self.assertEqual([r['text'] for r in rows if r['status'] == 'fail'], [], c)
            self.assertEqual(info['forecast_year'], 2027)

    def test_feb_fmam_is_issued_in_season(self):
        rows, _ = cr.check_cycle('config/cycles/feb_2027_fmam.json', date(2026, 10, 20))
        issue = next(r for r in rows if r['area'] == 'issue')
        self.assertIn('issue before 2027-03-01', issue['text'])
        self.assertIn('in season', issue['text'])

    def test_a_missed_issue_is_a_defect(self):
        rows, _ = cr.check_cycle('config/cycles/jan_2027_fmam.json', date(2027, 6, 1))
        self.assertTrue(any(r['area'] == 'issue' and r['status'] == 'fail' for r in rows))


if __name__ == '__main__':
    unittest.main()

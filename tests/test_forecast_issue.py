import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cycle import load_cycle                    # noqa: E402
import forecast_issue as fi                     # noqa: E402
import issue_forecast                           # noqa: E402


def cycle_with_root(name, root):
    """The named cycle with its verification root moved to a temporary folder."""
    d = json.loads((ROOT / f'config/cycles/{name}.json').read_text(encoding='utf-8'))
    d['verification_root'] = str(root)
    p = Path(root) / 'cycle.json'
    p.write_text(json.dumps(d), encoding='utf-8')
    return load_cycle(p)


class IssueStatus(unittest.TestCase):
    def test_period_start(self):
        self.assertEqual(fi.period_start(load_cycle(ROOT / 'config/cycles/jan_2027_fmam.json')).isoformat(), '2027-02-01')
        self.assertEqual(fi.period_start(load_cycle(ROOT / 'config/cycles/may_2027.json')).isoformat(), '2027-06-01')
        self.assertEqual(fi.period_start(load_cycle(ROOT / 'config/cycles/sep_2027_ondj.json')).isoformat(), '2027-10-01')
        self.assertEqual(fi.period_start(load_cycle(ROOT / 'config/cycles/sep_2026_ondj.json')).isoformat(), '2026-10-01')

    def test_without_record_it_is_a_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = fi.issue_status(cycle_with_root('jan_2027_fmam', tmp))
            self.assertFalse(s['issued'])
            self.assertIn('Research reconstruction', s['short'])
            self.assertIn('not an official EMI or ICPAC forecast', s['long'])

    def test_issued_only_before_the_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cycle_with_root('jan_2027_fmam', tmp)
            fi.record_path(c).parent.mkdir(parents=True)
            fi.record_path(c).write_text(json.dumps(dict(issued_utc='2027-01-14T08:00:00+00:00', tag='forecast-fmam2027',
                                                         release_url='https://example.org/r')), encoding='utf-8')
            s = fi.issue_status(c)
            self.assertTrue(s['issued'])
            self.assertIn('14 January 2027', s['short'])
            self.assertIn('public release forecast-fmam2027', s['long'])
            fi.record_path(c).write_text(json.dumps(dict(issued_utc='2027-05-03T08:00:00+00:00', tag='forecast-fmam2027')), encoding='utf-8')
            self.assertFalse(fi.issue_status(c)['issued'])             # after every target period began: a reconstruction

    def test_february_initialization_is_partly_in_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cycle_with_root('feb_2027_fmam', tmp)
            fi.record_path(c).parent.mkdir(parents=True)
            fi.record_path(c).write_text(json.dumps(dict(issued_utc='2027-02-13T12:00:00+00:00', tag='forecast-fmam2027feb')), encoding='utf-8')
            s = fi.issue_status(c)
            self.assertTrue(s['issued'])
            self.assertEqual(s['before'], ['Mar', 'Apr', 'May'])
            self.assertEqual(s['in_season'], ['Feb', 'FMAM'])
            self.assertIn('in season for Feb, FMAM', s['short'])
            self.assertIn('FMAM (12 days in)', s['long'])


class IssueChecks(unittest.TestCase):
    def test_refuses_late_or_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cycle_with_root('jan_2027_fmam', tmp)
            early = issue_forecast.checks(c, datetime(2027, 1, 14, tzinfo=timezone.utc))
            self.assertTrue(any('forecast files missing' in p for p in early))
            self.assertFalse(any('too late' in p for p in early))
            in_season = issue_forecast.checks(c, datetime(2027, 2, 2, tzinfo=timezone.utc))      # Feb started, Mar-May ahead
            self.assertFalse(any('too late' in p for p in in_season))
            late = issue_forecast.checks(c, datetime(2027, 5, 2, tzinfo=timezone.utc))           # every target period started
            self.assertTrue(any('too late' in p for p in late))

    def test_refuses_when_observations_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = cycle_with_root('jan_2027_fmam', tmp)
            (Path(tmp) / 'observations/Feb').mkdir(parents=True)
            (Path(tmp) / 'observations/Feb/chirps_2027_common.nc').write_bytes(b'')
            self.assertTrue(any('observations already' in p for p in issue_forecast.checks(c, datetime(2027, 1, 14, tzinfo=timezone.utc))))


class MemberPolicy(unittest.TestCase):
    def test_first_25_members_from_2027(self):
        c = load_cycle(ROOT / 'config/cycles/may_2027.json')
        self.assertEqual((c.members(2027), c.archive_members(2027)), (25, 51))
        self.assertEqual(c.members(2020), 51)                         # earlier years keep every member
        self.assertEqual(c.members(2010), 25)
        self.assertEqual(load_cycle(ROOT / 'config/cycles/sep_2026_ondj.json').members(2026), 51)


if __name__ == '__main__':
    unittest.main()

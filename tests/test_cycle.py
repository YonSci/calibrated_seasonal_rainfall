import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cycle import load_cycle, expected_members, BUILTIN


class CycleTests(unittest.TestCase):
    def write(self, folder, **changes):
        cfg = dict(BUILTIN, schema_version=1)
        cfg.update(changes)
        p = Path(folder) / 'cycle.json'
        p.write_text(json.dumps(cfg))
        return p

    def test_default_is_frozen_2026_cycle(self):
        c = load_cycle(ROOT / 'config/operational.json')
        self.assertEqual((c.year, c.reference_label, c.members(c.year)), (2026, '1993-2025', 51))
        self.assertEqual(c.forecast_file(Path('x'), 'JJAS'), Path('x/init05_JJAS/2026/forecast_2026.nc'))

    def test_2027_template(self):
        c = load_cycle(ROOT / 'config/cycles/may_2027.json')
        self.assertEqual((c.year, c.reference_years[0], c.reference_years[-1]), (2027, 1993, 2026))
        self.assertEqual(c.regime_mask_label, '1993-2025')   # descriptive mask stays fixed
        self.assertEqual(c.evaluation_years[-1], 2026)
        self.assertEqual(c.root('verification_root').name, 'verification_2027')

    def test_ondj_cycle_and_season_window(self):
        from common import season_window, season_months
        c = load_cycle(ROOT / 'config/cycles/sep_2026_ondj.json')
        self.assertEqual((c.tag, c.season_name, c.reference_label), ('init09', 'ONDJ', '1993-2024'))
        self.assertEqual([c.target_label(t) for t in ('Dec', 'Jan', 'ONDJ')], ['Dec 2026', 'Jan 2027', 'ONDJ 2026/27'])
        ondj = {'initialization_month': 9, 'season': {'name': 'ONDJ', 'start': '10-01', 'end': '01-31'}}
        jjas = {'initialization_month': 5, 'season': {'name': 'JJAS', 'start': '06-01', 'end': '09-30'}}
        self.assertEqual([d.isoformat() for d in season_window(ondj, 2026)], ['2026-10-01', '2027-01-31'])
        self.assertEqual([d.isoformat() for d in season_window(jjas, 2026)], ['2026-06-01', '2026-09-30'])
        self.assertEqual(season_months(ondj), [10, 11, 12, 1])

    def test_fmam_cycle_and_february(self):
        from common import season_window, load_config
        from run_monthly import monthly_config
        c = load_cycle(ROOT / 'config/cycles/jan_2026_fmam.json')
        self.assertEqual((c.tag, c.season_name, c.reference_label), ('init01', 'FMAM', '1993-2025'))
        self.assertEqual(c.target_label('Feb'), 'Feb 2026')
        feb = monthly_config(load_config('config/fmam/project.json'), 2)
        self.assertEqual(season_window(feb, 2026)[1].isoformat(), '2026-02-28')   # non-leap year
        self.assertEqual(season_window(feb, 1996)[1].isoformat(), '1996-02-29')   # leap year

    def test_member_rule(self):
        self.assertEqual([expected_members(y) for y in (1993, 2016, 2017, 2030)], [25, 25, 51, 51])
        rule = [{'last_year': 2020, 'members': 25}, {'members': 101}]
        self.assertEqual((expected_members(2020, rule), expected_members(2021, rule)), (25, 101))

    def test_invalid_cycles_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for changes, message in [
                (dict(adapter='other'), 'adapter'),
                (dict(initialization_month=4), 'initialization_month'),
                (dict(reference_years=[1993, 2026]), 'end before'),
                (dict(targets=['MAM']), 'Targets'),
                (dict(development_years=[1993, 2025]), 'development'),
            ]:
                with self.assertRaisesRegex(ValueError, message):
                    load_cycle(self.write(tmp, **changes))


if __name__ == '__main__':
    unittest.main()

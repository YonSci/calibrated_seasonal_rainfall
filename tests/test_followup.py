"""Step 31 tests: real historical evidence plus explicitly synthetic 2026 fixtures."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import followup_common as common
import review_historical_blending as historical
import followup_reliability as reliability
import verify_2026_regimes as regimes
import complete_verification_2026 as completion
from verify_frozen_2026 import calculate
from verify2026_common import PERIODS


def fixture(target):
    base = np.array([[0., 10.], [20., 30.]])
    history = np.arange(30, 96, 2)[:, None, None] + base
    corrected = np.repeat((50 + base)[None], 51, axis=0)
    q1, q2 = np.quantile(history, [1/3, 2/3], axis=0)
    p = np.zeros((2, 2, 3)); p[..., 0] = 1
    smooth = (51 * p + .5) / 52.5
    clim = np.full_like(p, 1/3)
    f = xr.Dataset(coords={'lat': [7.125, 7.375], 'lon': [37.125, 37.375], 'member': np.arange(51), 'category': common.CATS},
                   attrs={'initialization_month': 5, 'target_year': 2026, 'target_period': json.dumps({'name': target, 'start': PERIODS[target][0], 'end': PERIODS[target][1]}),
                          'training_years': '1993-2025', 'method': 'shared climatology blend', 'climatology_weight': .5})
    f['precip_corrected'] = (('member', 'lat', 'lon'), corrected)
    for key, value in [('corrected_ensemble_mean', corrected.mean(0)), ('observed_training_mean', history.mean(0)), ('corrected_mean_anomaly', corrected.mean(0) - history.mean(0)), ('q1', q1), ('q2', q2)]:
        f[key] = (('lat', 'lon'), value)
    for key in ['precip_corrected', 'corrected_ensemble_mean', 'observed_training_mean', 'corrected_mean_anomaly', 'q1', 'q2']:
        f[key].attrs['units'] = 'mm'
    for key, value in [('base_probability', p), ('smoothed_probability', smooth), ('climatology_probability', clim), ('blend_probability', .5 * smooth + .5 * clim)]:
        f[key] = (('lat', 'lon', 'category'), value)
    for key in ['region_mask', 'amount_eligible', 'probability_eligible']:
        f[key] = (('lat', 'lon'), np.array([[1, 1], [1, 0]], 'int8'))
    obs = 50 + base
    obs[1, 0] = 60   # Deliberately nonzero corrected amount error in one region.
    return f, history, corrected - 5, obs


def fixture_root(root):
    manifest = {'evaluation_year': 2026, 'training_years': '1993-2025', 'targets': {}}
    for target in common.TARGETS:
        f, h, raw, obs = fixture(target)
        dest = root / f'frozen_forecasts/init05_{target}/forecast_2026.nc'
        dest.parent.mkdir(parents=True)
        f.to_netcdf(dest)
        manifest['targets'][target] = {'sha256': common.sha(dest)}
    common.write(root / 'frozen_forecasts/freeze_manifest.json', manifest)
    f, h, raw, obs = fixture('Jun')
    report, fields = calculate(f, raw, h, obs)
    fields.attrs['target'] = 'Jun'
    folder = root / 'results/Jun'; folder.mkdir(parents=True)
    fields.to_netcdf(folder / 'verification_fields.nc')
    op = root / 'observations/Jun/chirps_2026_common.nc'; op.parent.mkdir(parents=True)
    xr.Dataset({'precip_season': (('lat', 'lon'), obs)}, coords={'lat': f.lat, 'lon': f.lon}).to_netcdf(op)
    report.update(target='Jun', year=2026, forecast_sha256=manifest['targets']['Jun']['sha256'], observations_sha256=common.sha(op))
    common.write(folder / 'verification_report.json', report)
    mask = xr.Dataset(coords={'lat': f.lat, 'lon': f.lon}, attrs={'method': common.METHOD, 'training_years': json.dumps(list(range(1993, 2026)))})
    mask['region_mask'] = f.region_mask
    mask['github_regime_cleaned'] = (('lat', 'lon'), np.array([[1, 2], [3, -2]], 'int8'))
    mask['github_jjas_r12_rainfall_cleaned'] = (('lat', 'lon'), np.array([[1, 1], [0, 0]], 'int8'))
    return fields, report, mask


class FollowupTests(unittest.TestCase):
    def test_real_evidence_and_leakage_guard(self):
        e = common.read(ROOT / 'evidence/followup_all_regime_experiments.json')
        result = historical.review_evidence(e, ['Aug'], ['training', 'operational'])
        v = result['reviews'][1]['domains']['all_country']['groups']['all']
        self.assertAlmostEqual(v['blend_minus_smooth']['mean'], .013722225167379944)
        self.assertEqual(v['blend_minus_smooth']['years_blend_worse'], 6)
        report = copy.deepcopy(next(r['report'] for r in e['experiments'] if r['method'] == common.METHOD and r['target'] == 'Aug' and r['mode'] == 'training'))
        report['years'][0]['training_years'].append(1993)
        with self.assertRaisesRegex(ValueError, 'leakage'):
            historical.validate_report(report, 'Aug', 'training')
        self.assertIsNone(common.paired_summary([1, -1])['whole_year_bootstrap_95_interval'])

    def test_regime_partition_and_integrated_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); root = p / 'verification'
            fields, report, mask = fixture_root(root)
            snapshot = common.freeze_snapshot(root)
            d, info = regimes.inspect_source(root, 'Jun', snapshot)
            self.assertTrue(info['country_reproduction_passed'])
            domains = regimes.make_domains(mask, d)
            rows = {k: regimes.summarize_domain(d, v) for k, v in domains.items()}
            self.assertEqual(sum(rows['regime_' + str(k)]['probability_cells'] for k in [-1, 0, 1, 2, 3, 4]), rows['all_country']['probability_cells'])
            self.assertFalse(rows['regime_0']['probability'])
            self.assertEqual(rows['regime_1']['amount']['corrected']['crps_mm'], 0)
            self.assertEqual(rows['regime_3']['amount']['corrected']['bias_mm'], 10)
            regimes.reproduce_country(rows['all_country'], report)
            mp = p / 'mask.nc'; mask.to_netcdf(mp)
            command = [sys.executable, str(ROOT / 'scripts/verify_2026_regimes.py'), '--targets', 'Jun', '--verification-root', str(root), '--mask', str(mp), '--output-root', str(p / 'review')]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(command + ['--regenerate'], check=True, capture_output=True, text=True)
            self.assertTrue((p / 'review/Jun/regime_verification_summary.json').is_file())
            self.assertEqual(len(list((p / 'review').glob('Jun_backup_*'))), 1)
            self.assertEqual(snapshot, common.freeze_snapshot(root))
            with self.assertRaisesRegex(ValueError, 'Grid mismatch'):
                regimes.make_domains(mask.assign_coords(lon=mask.lon + .01), fields)
            mask.attrs['training_years'] = json.dumps(list(range(1993, 2027)))
            with self.assertRaisesRegex(ValueError, 'baseline'):
                regimes.make_domains(mask, fields)
            with (root / 'frozen_forecasts/init05_Jun/forecast_2026.nc').open('ab') as stream:
                stream.write(b'modified')
            with self.assertRaisesRegex(ValueError, 'changed'):
                common.freeze_snapshot(root)

    def test_reliability_reproduces_known_scores(self):
        f, h, raw, obs = fixture('Jun')
        report, fields = calculate(f, raw, h, obs)
        d = xr.Dataset(coords={'year': [2001, 2002], 'lat': f.lat, 'lon': f.lon, 'category': f.category})
        d['region_mask'] = f.region_mask
        d['probability_common_support'] = (('year', 'lat', 'lon'), np.repeat(fields.probability_support.values[None], 2, 0))
        d['observed_category'] = (('year', 'lat', 'lon'), np.repeat(fields.observed_category.values[None], 2, 0))
        expected = []
        for method, key in [('smooth', 'smoothed_probability'), ('shared_blend', 'blend_probability'), ('climatology', 'climatology_probability')]:
            d[method + '_probability'] = (('year', 'lat', 'lon', 'category'), np.repeat(f[key].values[None], 2, 0))
        for year in [2001, 2002]:
            expected.append({'year': year, 'probability_cells': report['probability_cells'], 'probability': {m: report['probability']['corrected_smoothed' if m == 'smooth' else m] for m in common.METHODS}})
        r = reliability.calculate(d, expected)
        for method in common.METHODS:
            for cat in common.CATS:
                self.assertAlmostEqual(sum(v['weight_fraction'] for v in r['methods'][method][cat]), 1)
        d['smooth_probability'].values[0, 0, 0] = [1, 0, 0]
        with self.assertRaisesRegex(ValueError, 'reproduce'):
            reliability.calculate(d, expected)

    def test_availability_gate_and_command_chain(self):
        def unavailable(req, **kwargs):
            raise urllib.error.HTTPError(req.full_url, 404, 'Not found', {}, None)
        def network_error(req, **kwargs):
            raise urllib.error.URLError('timeout')
        self.assertEqual(completion.probe('https://example.invalid/test.nc', unavailable)['status'], 'unavailable')
        self.assertEqual(completion.probe('https://example.invalid/test.nc', network_error)['status'], 'unknown')
        args = SimpleNamespace(run=True, regenerate=True, config='config/project.json', mask='evidence/mask.nc', verification_root='outputs/verification_2026')
        calls = []
        completion.execute_if_ready({'ready_to_attempt_preparation': False}, args, lambda *a, **k: calls.append(a))
        self.assertFalse(calls)
        completion.execute_if_ready({'ready_to_attempt_preparation': True}, args, lambda *a, **k: calls.append(a))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all('--regenerate' in c[0] for c in calls))
        self.assertTrue(all(m in calls[0][0] for m in ['Jun', 'Jul', 'Aug', 'Sep']))
        self.assertIn('JJAS', calls[1][0])
        def fail(*a, **k):
            raise subprocess.CalledProcessError(2, a[0])
        with self.assertRaises(subprocess.CalledProcessError):
            completion.execute_if_ready({'ready_to_attempt_preparation': True}, args, fail)

    def test_protected_outputs(self):
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            common.protect_output(common.ROOT / 'outputs/final_shared_blend', [])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            common.protect_output(common.ROOT, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

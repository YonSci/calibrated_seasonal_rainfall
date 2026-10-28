"""Ranking by season (method_summary.py, docs/50): every method scored for all the season's months, by its skill gain averaged
over the months, with the published approach in the list at 0."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import method_summary as ms             # noqa: E402

ORDER = [('jan_fmam', t) for t in ('Feb', 'Mar', 'Apr', 'May', 'FMAM')]


def method(name, product, gains, season=None, confirmed=()):
    by_target = {f'FMAM (Jan) {t}': dict(gain_all=g, confirmed=t in confirmed) for t, g in zip(('Feb', 'Mar', 'Apr', 'May'), gains)}
    if season is not None:
        by_target['FMAM (Jan) FMAM'] = dict(gain_all=season, confirmed='FMAM' in confirmed)
    return dict(method=name, label=name.upper(), category='Neural network', product=product, by_target=by_target)


class Ranking(unittest.TestCase):
    def test_ranked_by_mean_gain_over_the_months(self):
        rows = [method('a', 'amounts', [0.01, 0.01, 0.01, 0.01], season=0.5),        # the season total is not ranked
                method('b', 'amounts', [0.04, 0.02, 0.0, 0.02], confirmed=('Feb', 'Mar')),
                method('c', 'amounts', [-0.02, -0.02, -0.02, -0.02], season=-0.01, confirmed=('FMAM',)),
                method('d', 'amounts', [0.05, 0.05, 0.05]),                            # a month missing: not ranked
                method('e', 'probabilities', [0.1] * 4)]
        r = ms.ranking(rows, ORDER)['jan_fmam']
        amounts = r['amounts']
        self.assertEqual([e['method'] for e in amounts], ['b', 'a', 'published', 'c'])
        self.assertEqual([e['rank'] for e in amounts], [1, 2, 3, 4])
        self.assertAlmostEqual(amounts[0]['gain'], 0.02)
        self.assertEqual(amounts[0]['confirmed'], ['Feb', 'Mar'])
        self.assertIsNone(amounts[0]['season'])
        self.assertEqual(amounts[3]['confirmed'], ['FMAM'])
        self.assertEqual(amounts[2]['label'], ms.REFERENCE['amounts'])
        self.assertEqual([e['method'] for e in r['probabilities']], ['e', 'published'])
        self.assertEqual(set(ms.ranking(rows, ORDER)), set(ms.CYCLES))

    def test_published_first_on_a_tie(self):
        r = ms.ranking([method('z', 'amounts', [0.0] * 4)], ORDER)['jan_fmam']['amounts']
        self.assertEqual([e['method'] for e in r], ['published', 'z'])

    def test_tables(self):
        rank = ms.ranking([method('b', 'amounts', [0.04, 0.02, 0.0, 0.02], confirmed=('Feb',))], ORDER)
        md = ms.ranking_tables(rank)
        self.assertIn('| 1 | B | Neural network | +2.00 | — | Feb |', md)
        self.assertIn(f"| 2 | **{ms.REFERENCE['amounts']}** | Published | +0.00 | +0.00 | — |", md)


if __name__ == '__main__':
    unittest.main()

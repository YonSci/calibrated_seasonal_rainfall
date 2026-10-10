"""Forecast-cycle settings shared by the operational chain.

One JSON file describes a cycle (forecast year, initialization month, reference
period, member-count rule, output folders). The default is config/operational.json
(the frozen May 2026 cycle), so existing commands behave exactly as before.

Select another cycle for every script in a session with an environment variable:

    set CALIBRATION_CYCLE=config\\cycles\\may_2027.json

`run_operational.py --config <cycle.json>` sets it for its child stages.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = 'CALIBRATION_CYCLE'
DEFAULT = 'config/operational.json'
ADAPTERS = {'may_2026_shared_blend', 'may_shared_blend', 'sep_shared_blend', 'shared_blend'}
ORDER = ['Jun', 'Jul', 'Aug', 'Sep', 'JJAS']
# Members per year: first rule whose last_year is >= year (no last_year = open-ended).
DEFAULT_MEMBER_RULE = [{'last_year': 2016, 'members': 25}, {'members': 51}]
DEFAULT_DEVELOPMENT = [1993, 2016]
DEFAULT_REGIME_MASK_YEARS = [1993, 2025]


def resolve(p):
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def expected_members(year, rule=None):
    for r in rule or DEFAULT_MEMBER_RULE:
        if 'last_year' not in r or year <= int(r['last_year']):
            return int(r['members'])
    raise ValueError(f'No member-count rule covers {year}')


@dataclass(frozen=True)
class Cycle:
    path: Path
    year: int
    init_month: int
    ref_first: int
    ref_last: int
    targets: tuple
    raw: dict = field(repr=False)

    @property
    def reference_years(self):
        return list(range(self.ref_first, self.ref_last + 1))

    @property
    def reference_label(self):
        return f'{self.ref_first}-{self.ref_last}'

    @property
    def reference_dash(self):
        return f'{self.ref_first}–{self.ref_last}'

    @property
    def tag(self):
        return f'init{self.init_month:02d}'

    @property
    def development_years(self):
        a, b = self.raw.get('development_years', DEFAULT_DEVELOPMENT)
        return list(range(a, b + 1))

    @property
    def evaluation_years(self):
        """Fixed-fit evaluation years after development, up to the reference end."""
        return list(range(self.development_years[-1] + 1, self.ref_last + 1))

    @property
    def regime_mask_years(self):
        a, b = self.raw.get('regime_mask_years', DEFAULT_REGIME_MASK_YEARS)
        return list(range(a, b + 1))

    @property
    def regime_mask_label(self):
        y = self.regime_mask_years
        return f'{y[0]}-{y[-1]}'

    def members(self, year):
        return expected_members(year, self.raw.get('expected_members'))

    def root(self, key, default=None):
        value = self.raw.get(key, default)
        if value is None:
            raise KeyError(f'Cycle file {self.path} has no "{key}"')
        return resolve(value)

    def extra_domains(self):
        """Additional presentation views beyond the season domain: [(view, mask path)] from "extra_domain_masks"."""
        return [(e['view'], resolve(e['mask'])) for e in self.raw.get('extra_domain_masks', [])]

    @property
    def project(self):
        """The project configuration (season, archive) this cycle forecasts."""
        p = resolve(self.raw.get('project_config', 'config/project.json'))
        if not p.is_file():   # minimal test projects: the established JJAS season
            return {'initialization_month': 5, 'season': {'name': 'JJAS', 'start': '06-01', 'end': '09-30'}}
        return json.loads(p.read_text(encoding='utf-8-sig'))

    @property
    def season_name(self):
        return self.project['season']['name']

    def target_label(self, target):
        """Display label with the calendar year(s) of the target, e.g. 'JJAS 2026', 'ONDJ 2026/27', 'Jan 2027'."""
        from common import season_window
        from run_monthly import monthly_config
        import calendar
        cfg = self.project
        if target != self.season_name:
            cfg = monthly_config(cfg, list(calendar.month_abbr).index(target))
        start, end = season_window(cfg, self.year)
        years = str(start.year) if start.year == end.year else f'{start.year}/{str(end.year)[-2:]}'
        return f'{target} {years}'

    @property
    def init_month_name(self):
        import calendar
        return calendar.month_name[self.init_month]

    def forecast_dir(self, root, target):
        return Path(root) / f'{self.tag}_{target}/{self.year}'

    def forecast_file(self, root, target):
        return self.forecast_dir(root, target) / f'forecast_{self.year}.nc'


# Used only when no cycle is selected and config/operational.json is absent
# (for example a minimal test project): the frozen May 2026 cycle.
BUILTIN = {'adapter': 'may_2026_shared_blend', 'forecast_year': 2026, 'initialization_month': 5,
           'reference_years': [1993, 2025], 'targets': ORDER,
           'forecast_root': 'outputs/final_shared_blend', 'verification_root': 'outputs/verification_2026',
           'output_root': 'outputs/operational_2026'}


def season_targets(project):
    """Month abbreviations of the season followed by the season name, e.g. Jun..Sep, JJAS."""
    import calendar
    from common import season_months
    return [calendar.month_abbr[m] for m in season_months(project)] + [project['season']['name']]


def load_cycle(path=None):
    chosen = path or os.environ.get(ENV)
    p = resolve(chosen or DEFAULT)
    if chosen is None and not p.is_file():
        raw = dict(BUILTIN)
    else:
        raw = json.loads(p.read_text(encoding='utf-8-sig'))
    if raw.get('adapter') not in ADAPTERS:
        raise ValueError(f'Unsupported adapter {raw.get("adapter")!r} in {p}; expected one of {sorted(ADAPTERS)}')
    first, last = raw['reference_years']
    c = Cycle(p, int(raw['forecast_year']), int(raw['initialization_month']), int(first), int(last),
              tuple(raw.get('targets', ORDER)), raw)
    if c.init_month != int(c.project.get('initialization_month', c.init_month)):
        raise ValueError("initialization_month differs from the cycle's project configuration")
    if not first < last < c.year:
        raise ValueError('reference_years must end before forecast_year')
    if c.development_years[-1] >= last:
        raise ValueError('development_years must end before the reference period ends')
    allowed = season_targets(c.project)
    if not set(c.targets) <= set(allowed):
        raise ValueError(f'Targets must be among {allowed}')
    return c


CYCLE = load_cycle()

# Convenience constants for the operational scripts (all derived from CYCLE).
YEAR = CYCLE.year
REF = CYCLE.reference_label            # e.g. '1993-2025' (stored in file attributes)
REF_DASH = CYCLE.reference_dash        # e.g. '1993–2025' (display text)
REF_YEARS = CYCLE.reference_years
MEMBERS = CYCLE.members(CYCLE.year)
REGIME = CYCLE.regime_mask_label       # fixed descriptive regime-mask baseline
REGIME_YEARS = CYCLE.regime_mask_years
# Last year of the historical CHIRPS archive file; official downloads are checked against it.
OVERLAP_YEAR = int(CYCLE.raw.get('overlap_year', 2025))
# Historical method-evaluation study (docs 15-17); fixed evidence, not the cycle.
EVALUATION_STUDY = list(range(2017, 2026))


# Season profile of the selected cycle: target names, calendar windows and presentation domain.
def _season_profile(cycle):
    import calendar
    from common import season_months
    project = cycle.project
    return project['season']['name'], {calendar.month_abbr[m]: m for m in season_months(project)}


SEASON, SEASON_MONTHS = _season_profile(CYCLE)          # e.g. 'JJAS', {'Jun': 6, ...}
TARGET_ORDER = list(SEASON_MONTHS) + [SEASON]            # months in season order, then the season
DOMAIN_VIEW = 'jjas_r12_rainfall_domain' if SEASON == 'JJAS' else f'{SEASON.lower()}_rainfall_domain'


def target_window(target, cycle=None):
    """First and last calendar day of a target for the cycle's forecast year (January of ONDJ -> next year)."""
    import calendar
    from common import season_window
    from run_monthly import monthly_config
    c = cycle or CYCLE
    cfg = c.project if target == c.season_name else monthly_config(c.project, list(calendar.month_abbr).index(target))
    return season_window(cfg, c.year)

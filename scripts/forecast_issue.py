"""Issue status of a forecast cycle (docs/52): issued in real time, or a research reconstruction.

A cycle counts as issued only if `<verification_root>/frozen_forecasts/issue_record.json` exists (written by
scripts/issue_forecast.py) and its issue time is before the start of at least one target period. Each target is judged on
its own start: *before its period* or *in season* (issued after its period began, with no observation of the period in the
project). A February-initialized FMAM forecast, for example, is issued in season for February and FMAM (SEAS5 for the
initialization appears around the 5th-13th) and before the period for March, April and May. Every statement the site, maps,
bulletins and packages make about a cycle's status comes from `issue_status()`, so the wording follows the record.
"""
import calendar
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOT_OFFICIAL = 'not an official EMI or ICPAC forecast'
MONTHS = list(calendar.month_abbr)


def record_path(cycle):
    return ROOT / cycle.raw['verification_root'] / 'frozen_forecasts' / 'issue_record.json'


def target_start(cycle, target):
    """First day of a target's period: its month, or the first month of the season."""
    if target in MONTHS[1:]:
        m = MONTHS.index(target)
    else:                                                             # a season: its first month is the first month target
        m = MONTHS.index([t for t in cycle.targets if t in MONTHS[1:]][0])
    return date(cycle.year + (1 if m < cycle.init_month else 0), m, 1)


def period_start(cycle):
    """First day of the whole target period (the earliest target)."""
    return min(target_start(cycle, t) for t in cycle.targets)


def last_start(cycle):
    """Start of the last target period to begin: after it, nothing of the cycle can be issued before its period."""
    return max(target_start(cycle, t) for t in cycle.targets)


def read_record(cycle):
    p = record_path(cycle)
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def long_date(d):
    return f'{d.day} {calendar.month_name[d.month]} {d.year}'


def issue_status(cycle):
    """dict(issued, date, tag, release_url, before, in_season, kind, short, long, footer) for site, maps and documents."""
    rec = read_record(cycle)
    issued_at = datetime.fromisoformat(rec['issued_utc']).date() if rec else None
    before = [t for t in cycle.targets if issued_at and issued_at < target_start(cycle, t)]
    late = [t for t in cycle.targets if issued_at and t not in before]
    issued = bool(rec) and bool(before)
    base = dict(issued=issued, date=issued_at.isoformat() if issued else None, tag=rec.get('tag') if rec else None,
                release_url=rec.get('release_url') if rec else None, before=before, in_season=late if issued else [],
                period_start=period_start(cycle).isoformat())
    if not issued:
        init = calendar.month_name[cycle.init_month]
        return dict(base, kind='retrospective reconstruction', short=f'Research reconstruction · {NOT_OFFICIAL}',
                    long=f'Research reconstruction: produced after the initialization date with the published method; {NOT_OFFICIAL}',
                    footer=f'Research reconstruction of a {init}-initialized forecast; {NOT_OFFICIAL}.')
    when = long_date(issued_at)
    where = f'public release {rec["tag"]}' if rec.get('release_url') else f'tag {rec["tag"]} (not yet published)'
    if not late:
        return dict(base, kind='issued before the target period', short=f'Forecast issued {when}, before the season · {NOT_OFFICIAL}',
                    long=(f'Issued {when}, before the target period starts ({period_start(cycle).isoformat()}), with the published method; '
                          f'the frozen files are in the {where}. {NOT_OFFICIAL.capitalize()}.'),
                    footer=f'Forecast issued {when}, before the season ({rec["tag"]}); {NOT_OFFICIAL}.')
    days = {t: (issued_at - target_start(cycle, t)).days for t in late}
    late_text = ', '.join(f'{t} ({days[t]} days in)' for t in late)
    return dict(base, kind='issued in real time, partly in season',
                short=f'Forecast issued {when} (in season for {", ".join(late)}) · {NOT_OFFICIAL}',
                long=(f'Issued {when} with the published method: before the target period of {", ".join(before)}; in season for '
                      f'{late_text}, with no observation of those periods in the project. The frozen files are in the {where}. '
                      f'{NOT_OFFICIAL.capitalize()}.'),
                footer=f'Forecast issued {when} ({rec["tag"]}); in season for {", ".join(late)}; {NOT_OFFICIAL}.')

"""Render forecast presentation layers for a cycle and list them for the site.

Uses the same presentation code as the operational gallery: for each target, maps
and statistics for All Ethiopia and the season's rainfall domain. Forecast only;
verification follows once observations for the target periods exist.

    set CALIBRATION_CYCLE=config\\cycles\\sep_2026_ondj.json
    python scripts\\build_season_products.py
"""
import argparse
import json
from datetime import datetime, timezone
from cycle import CYCLE, resolve
import presentation_layers as layers

IMAGES = [['tercile_outlook', 'Leading tercile probability'], ['rainfall_total_mm', 'Corrected mean rainfall'],
          ['rainfall_anomaly_mm', 'Rainfall anomaly (mm)'], ['rainfall_anomaly_percent', 'Rainfall anomaly (%)']]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--targets', nargs='+', choices=list(CYCLE.targets), default=list(CYCLE.targets))
    a = p.parse_args()
    out = CYCLE.root('output_root')
    if not out.is_relative_to(resolve('outputs')) or out == resolve('outputs'):
        raise ValueError('output_root must be a subfolder of outputs/')
    mask = CYCLE.root('season_domain_mask') if layers.SEASON_VIEW else CYCLE.root('regime_mask')
    settings = CYCLE.raw['display']
    entries = []
    for target in a.targets:
        source = CYCLE.forecast_file(CYCLE.root('forecast_root'), target)
        dest = out / 'presentation/forecast' / target
        result = layers.build_forecast(source, mask, CYCLE.root('boundary'), target, dest, settings)
        for view, summary in result['summaries'].items():
            entries.append(dict(kind='forecast', target=target, label=layers.VIEWS[view], view=view,
                                target_label=CYCLE.target_label(target),
                                folder=f'presentation/forecast/{target}/{view}', images=IMAGES, summary=summary))
        print('Rendered', CYCLE.target_label(target), flush=True)
    (out / 'entries.json').write_text(json.dumps(dict(
        created_utc=datetime.now(timezone.utc).isoformat(), cycle=str(CYCLE.path), forecast_year=CYCLE.year,
        initialization_month=CYCLE.init_month, season=CYCLE.season_name, reference_years=CYCLE.reference_label,
        domain_definition=result['domain_definition'], domain_note=result['domain_note'], entries=entries), indent=2),
        encoding='utf-8')
    print('Entries:', out / 'entries.json')


if __name__ == '__main__':
    main()

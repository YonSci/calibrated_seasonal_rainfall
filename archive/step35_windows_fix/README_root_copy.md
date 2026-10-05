# Windows publication fix

Copy both files in `scripts` into the existing project `scripts` folder, replacing
`verify2026_outputs.py` and `operational_core.py`. Close viewers and File Explorer
previews using generated outputs, then rerun:

```cmd
python scripts\run_operational.py --workflow products
```

No `--force`, package installation or configuration change is needed.

See `docs/35_WINDOWS_PUBLICATION_FIX.md` for the cause, recovery behavior,
limitations and optional tests. The patch does not modify forecast/calibration data.

Validation: six simulated Windows-lock/recovery tests passed. The five existing
operational integration test groups also passed with the patched helpers.

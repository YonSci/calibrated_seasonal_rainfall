# 06 — Troubleshooting in CMD

| Symptom | Action |
| --- | --- |
| `py` not recognized | Install Python with its launcher, then open a new terminal. If an appropriate Python is on PATH, verify its version before using `python -m venv .venv`. |
| No Python 3.11 | Install 3.11 x64 or manually create the environment using installed 3.12. |
| Activation errors / `PS` prompt | Select Command Prompt as the VS Code terminal profile and open a new terminal. Use `call .venv\Scripts\activate.bat`. |
| `ModuleNotFoundError` | Check `python -c "import sys; print(sys.executable)"`; activate the correct environment and run `python -m pip install -r requirements.txt`. |
| Network/proxy failure in pip | Fix internet/proxy access or use an approved wheel cache. Do not bypass certificate validation or disable security checks. |
| `No matching distribution` | Check Python version (3.11/3.12 x64), actual network error above it, and current interpreter. |
| Input missing | Edit both source paths in config; do not guess the truncated screenshot path. |
| JSON decode error | Use forward-slash paths, double quotes, no comments/trailing commas. |
| `Unexpected dimension` | Share the variable's actual dimensions. Do not silently squeeze non-singleton axes. |
| Non-daily endpoints / resets | Stop; verify product convention before changing the reader. |
| Unexpected members | Review that year's file and provenance. Do not drop members simply to pass checks. |
| Missing CHIRPS season | Confirm time coverage and exact timestamps. The preparation preserves pixel NaNs. |
| Permission denied writing output | Close viewers holding the derived NetCDF open; use a writable project directory. |
| Existing bootstrap file conflict | Use a fresh project folder. The bootstrap deliberately does not overwrite edited configuration/code. |
| Full inventory fails with only one downloaded sample | Temporarily narrow archive_years for a sample review; restore 1993–2026 for the full archive. |

## Useful commands

```bat
where python
python --version
python -m pip check
python scripts\check_environment.py
python -m unittest discover -s tests -v
```

To inspect one file manually after activating:

```bat
python -c "import xarray as xr; ds=xr.open_dataset('D:/YOUR_PATH/ecmwf_199305_d01.nc'); print(ds); print(ds['tp'].attrs); ds.close()"
```

If an environment becomes inconsistent, close VS Code terminals using it, rename `.venv` to `.venv_old` in File Explorer, and recreate `.venv`. Keep original data and project configuration. An environment can be recreated from requirements; no raw-data deletion is needed.

# 01 — Windows CMD and Python environment

## 1. Install the prerequisites

Install **64-bit CPython 3.11** from https://www.python.org/downloads/windows/ if it is not already installed. Enable the Python launcher when offered. Python 3.12 is also supported by the pinned baseline, using the manual alternative below. Internet is needed for installing packages, but processing local NetCDF files does not require network access.

Install VS Code and the Microsoft **Python** extension. Pylance is recommended. A GPU, CUDA, R, Docker, WSL, Conda, CDS credentials, and Earthdata credentials are not needed for these local stages.

In VS Code choose **Terminal > Select Default Profile > Command Prompt**, then open a **new** terminal. These commands use CMD syntax, not PowerShell syntax.

```bat
py -0p
py -3.11 --version
```

## 2. Create the project from the standalone bootstrap

Save the supplied `bootstrap_seasonal_project.py` in your Downloads folder. Run:

```bat
py -3.11 "%USERPROFILE%\Downloads\bootstrap_seasonal_project.py" --root "D:\seasonal-calibration-et"
cd /d "D:\seasonal-calibration-et"
```

The bootstrap uses only the Python standard library and requires no network. It creates the source files, guides, configuration, and directories. It never modifies source climate data. It refuses to overwrite differing existing files; use a fresh directory for a new starter version. Rerunning it on an unchanged scaffold is safe.

Alternative: extract `seasonal_calibration_starter.zip` to a new folder and use that folder as the project root. Use **either bootstrap or ZIP extraction**, not both in the same working directory.

## 3. Create the environment and install packages

Automatic route:

```bat
call setup_project.cmd
call .venv\Scripts\activate.bat
```

The setup script stops if any command fails. It creates a local environment, installs the fixed dependency baseline, checks imports and package consistency, runs synthetic preparation tests, and creates output directories.

Equivalent manual route (choose this instead of automatic setup):

```bat
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python scripts\check_environment.py
python -m unittest discover -s tests -v
```

For installed Python 3.12, substitute `py -3.12 -m venv .venv`; subsequent commands are unchanged. Do not mix package installs between interpreters. If a manual command fails, resolve it before continuing.

## 4. Select the interpreter in VS Code

```bat
code .
```

If `code` is unavailable, open the folder through **File > Open Folder**. Press **Ctrl+Shift+P**, select **Python: Select Interpreter**, and choose:

`D:\seasonal-calibration-et\.venv\Scripts\python.exe`

If it is absent, use **Enter interpreter path**. Workspace settings provide a default path, but an already selected interpreter may take precedence.

Verify:

```bat
where python
python -c "import sys; print(sys.executable)"
```

The executable should be in this project's `.venv`. The generated `logs/environment.json` and `logs/requirements-resolved.txt` preserve exact versions, including transitive packages. Direct dependency versions are a fixed baseline, not the latest package releases.

## 5. Resume work later

```bat
cd /d "D:\seasonal-calibration-et"
call .venv\Scripts\activate.bat
```

You do not need to reinstall requirements on every session. Close the session with:

```bat
deactivate
```

## References

- Python venv: https://docs.python.org/3.11/library/venv.html
- VS Code environments: https://code.visualstudio.com/docs/python/environments

The CMD activation command is `activate.bat`; no PowerShell execution-policy change is necessary.

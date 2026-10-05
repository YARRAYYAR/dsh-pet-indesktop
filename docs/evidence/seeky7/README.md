# seeky.7 evidence

Baseline45cb1fd5365cbfa47a1b3c4cbc1a11b937caff5b; root=/Users/ray/Documents/New project/dsr-pet; Python=.venv/bin/python; PYTHONPYCACHEPREFIX=/tmp/seeky7-main-pycache.

- Native UI: `PYTHONPATH=. .venv/bin/python scripts/verify_seeky7_settings.py --output <freshdir> --idle-seconds 30`. Matrix: `scripts/verify_seeky_settings_ui.py --output <freshdir> --phase after --live`. Actual results ui/final-seven and ui/final-matrix.
- Native drag/cursor: scripts/verify_seeky7_interactions.py; originalRED, GREEN33andheld-frame diagnosis in runtime/. Every JSON contains command/setup/assertions/errors/reset/status.
- Additional public AppShell two-pet/restart lifecycle: copy runners/verify_lifecycle.py.txt to a temporary .py, run from root with `PYTHONPATH=. .venv/bin/python <copied.py>`. Does not edit user config. lifecycle/ preserves three failures then final green.
- Required checks: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`; `.venv/bin/python -m ruff check pet/ tests/ scripts/`. checks/ retains first report-only failure, checks-final/ has final results.
- Full CPU reruns: copy runners/run_load.py.txt to `.scratch/seeky7/run_load.py`, run with .venv Python; creates and cleans only owned workers. load/ records commands, actual systemCPU and179 tests per round.
- Frozen baseline, before/after3rounds,620s observation, pressure and costs: performance/. summary.json defines comparison windows; runtime-equivalence-2.json confirms identical environment. FPS gates have failures explicitly retained.
- package/ contains build/static/nativeIPC runs. `*-before-release-offset-fix` directories preserve preceding successful runs. install.json records exact retained old application and Config integrity.
- Runners are archived as plain text to preserve commands, including historical failures, without turning evidence into a new test or lint source tree. Source tests and native verification scripts remain in tests/ and scripts/.
- Native point tests temporarily move the OS cursor; each original cursor is restored. No user system reduce-motion preference or system load app was changed.

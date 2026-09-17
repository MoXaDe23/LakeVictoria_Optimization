# Lake Victoria Policy Observatory

A local Panel dashboard using this repository's historical observations and saved
model scenarios. The interface has scenario comparisons, a selectable 120-policy
explorer, archived flood maps, source inspection and an exploratory daily simulator.

## Open the app

Double-click `Open-Observatory.cmd` in the project root. It starts a hidden Python
server if needed and opens **http://localhost:5006/app** in your default browser.
Chrome can also use **http://127.0.0.1:5006/app**. Both use HTTP, not HTTPS.

The address is local to this computer. It is not a deployed public website and will
not open on a different device. Run the launcher again after restarting Windows.
The server continues in the background after the launcher closes.

Server logs and its PID are in `outputs/observatory/`. The launcher will not stop an
unrelated process if port 5006 is already in use.

## Install on another machine

Requires Python 3.12 or later and the existing project data/outputs.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\Start-Observatory.ps1
```

`dashboard/requirements-lock.txt` records the tested environment's exact package
versions. On Windows/Python 3.12, install it with `pip install -r
dashboard/requirements-lock.txt` before the editable install to reproduce that
environment. The lock contains the application's dependency closure, excluding
unrelated host tools. Regenerate it with `python scripts/freeze_app.py`.

For foreground development:

```powershell
.\.venv\Scripts\python.exe -m panel serve dashboard/app.py --address 127.0.0.1 --port 5006 --allow-websocket-origin=localhost:5006 --allow-websocket-origin=127.0.0.1:5006 --dev
```

## Evidence and calculations

- Observations: `data/processed/audit_daily_core_variables.csv`.
- Saved scenarios: `06_optimized_rulecurve_sim.csv` and `06_baseline_agreedcurve_sim.csv`.
- Level metrics use common valid level dates; outflow metrics use common valid flow
  dates. No missing observation is imputed. Ramping excludes nonconsecutive dates.
- The selected flood threshold and period apply to all comparison scores/charts.
  The series checkboxes affect only the lake-level chart. Exports contain every
  compared scenario, their filtered daily rows, scores and a source manifest.
- The full record contains 7,422 days, 7,420 observed levels and 7,360 observed
  outflows. 2021 ends on 27 April and is not a full annual comparison.
- Gauge levels convert to metres ASL by adding 1,122.85.
- The README's older optimized exceedance results do not match the current saved
  daily file. This dashboard recomputes from the daily file; at 12.8 m it yields
  452 observed exceedance days and zero optimized exceedance days.
- The two map editions each display their own original figure and matching table.
  Their area estimates differ and are never mixed. Maps are archived, not live
  raster calculations. Rasterio imports are blocked by this machine's Windows
  Application Control policy; no security policy is modified by this project.

## Exploratory engine

`src/engine.py` adapts the nonlinear stage-area-storage equations from notebook 06.
It uses the current calibration table, reconstructed tributary inflows, initial
observed lake level, and rainfall/evaporation forcings. Release is calculated from
the **beginning-of-day simulated state** with seasonal safeguards, hard release
bounds and a ramp constraint. It never uses future observed levels.

This differs deliberately from the legacy notebook's two full-series iterations.
The default knots are a rounded reference rule, not a new optimized policy.
Groundwater uses notebook 06's fixed 30-day month convention. Invalid forcings or
storage outside the hypsometry domain raise an error instead of silently filling
gaps or clipping storage. These runs are sensitivity scenarios, not forecasts.

Successful runs are saved under `outputs/observatory/runs/<run-id>/`:

- `daily.parquet`: daily states, releases and water-balance terms.
- `run.json`: input hashes, engine hash, calibration, settings and initial state.

The original notebooks and existing results are not rewritten. New NSGA-II searches,
independent calibration/validation, forecast ingestion, hydropower generation and
downstream hydraulic routing are future work.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests check unit conversions, storage conservation, causality, missing-data handling,
threshold boundaries, source-derived metrics, and filtered exports.

"""Run library, comparison snapshots, and persistent stress-test batches."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

import numpy as np
import pandas as pd

from .observatory import ROOT, fingerprint, load_scenarios, scorecard, slice_scenarios

PERIODS = {
    "Full record · 2001–2021": ("2001-01-01", "2021-04-27"),
    "Flood year · 2020": ("2020-01-01", "2020-12-31"),
    "Recent years · 2018–2021": ("2018-01-01", "2021-04-27"),
    "Dry period · 2004–2007": ("2004-01-01", "2007-12-31"),
}
INPUT_KEYS = ("observations", "calibration", "inflow", "hypsometry")
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[a-f0-9]{8}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    pending.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def run_folder(run_id, root=ROOT):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run identifier.")
    base = (root / "outputs/observatory/runs").resolve()
    folder = (base / run_id).resolve()
    if folder.parent != base:
        raise ValueError("Run path must remain inside the run library.")
    return folder


def read_run_metadata(run_id, root=ROOT):
    folder = run_folder(run_id, root)
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    if meta.get("run_id") != run_id:
        raise ValueError("Run identifier does not match its metadata.")
    for key in ("policy", "forcing_multipliers", "sources", "period", "engine_sha256"):
        if key not in meta:
            raise ValueError(f"Run metadata is missing {key}.")
    alias = folder / "label.json"
    meta["display_name"] = json.loads(alias.read_text(encoding="utf-8"))["name"] if alias.exists() else meta.get("name", "Earlier exploratory run")
    return meta


def list_runs(root=ROOT):
    """List completed metadata records; keep invalid records visible as issues."""
    base = root / "outputs/observatory/runs"
    rows, issues = [], []
    if not base.exists():
        return rows, issues
    for path in sorted(base.glob("*/run.json"), reverse=True):
        try:
            meta = read_run_metadata(path.parent.name, root)
            if not (path.parent / "daily.parquet").is_file():
                raise ValueError("Daily results are missing.")
            rows.append(meta)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            issues.append(f"{path.parent.name}: {exc}")
    return rows, issues


def load_run(run_id, root=ROOT):
    meta = read_run_metadata(run_id, root)
    path = run_folder(run_id, root) / "daily.parquet"
    if meta.get("daily_sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != meta["daily_sha256"]:
        raise ValueError("Saved daily results have changed since this run was written.")
    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Saved results have an invalid daily calendar.")
    if not {"level_m", "outflow_m3s"}.issubset(frame.columns) or not np.isfinite(frame[["level_m", "outflow_m3s"]]).all().all():
        raise ValueError("Saved results contain invalid levels or releases.")
    if not frame.index.equals(pd.date_range(*meta["period"])):
        raise ValueError("Saved results do not cover the run's declared daily period.")
    frame.index.name = "date"
    return frame, meta


def rename_run(run_id, name, root=ROOT):
    name = str(name).strip()
    if not name or len(name) > 100:
        raise ValueError("Use a name of 1–100 characters.")
    read_run_metadata(run_id, root)
    atomic_json(run_folder(run_id, root) / "label.json", {"name": name, "updated_at": utc_now()})


def compatibility_key(meta):
    sources = {source["id"]: source["sha256"] for source in meta["sources"]}
    return tuple(sources.get(key) for key in INPUT_KEYS)


def comparison_snapshot(run_ids, period, threshold, root=ROOT):
    ids = list(dict.fromkeys(run_ids))
    if not 1 <= len(ids) <= 4:
        raise ValueError("Select between one and four saved runs.")
    if period not in PERIODS or not np.isfinite(threshold):
        raise ValueError("Choose a valid comparison period and threshold.")
    current = fingerprint(root)
    frames = {k: v for k, v in load_scenarios(root).items() if k in ("Observed", "Optimized")}
    runs, settings, engine = [], [], None
    for i, run_id in enumerate(ids):
        frame, meta = load_run(run_id, root)
        if compatibility_key(meta) != compatibility_key(current):
            raise ValueError(f'{meta["display_name"]}: source inputs differ from the current project. Run it again before comparing.')
        if engine is not None and engine != meta["engine_sha256"]:
            raise ValueError("Selected runs use different engine versions. Select runs from one engine version.")
        engine = meta["engine_sha256"]
        label = f'{chr(65 + i)} · {meta["display_name"]}'
        frames[label] = frame[["level_m", "outflow_m3s"]]
        meta = {**meta, "comparison_label": label}
        runs.append(meta)
        p, f = meta["policy"], meta["forcing_multipliers"]
        settings.append({"Scenario": label, "Run ID": run_id, "Release ×": p["release_multiplier"],
            "Inflow ×": f["inflow"], "Rainfall ×": f["rainfall"], "Ramp limit · m³/s/day": p["ramp_limit"]})
    start, end = PERIODS[period]
    frames = slice_scenarios(frames, start, end)
    scores = scorecard(frames, threshold)
    if (scores.valid_level_days == 0).any() or (scores.valid_flow_days == 0).any():
        raise ValueError("No common valid observations exist for this comparison.")
    return {"frames": frames, "scores": scores, "settings": pd.DataFrame(settings),
            "manifest": {"title": "Lake Victoria experiment comparison", "created_at": utc_now(),
                "period": [start, end], "period_label": period, "threshold_m": float(threshold), "low_water_threshold_m": 11.15,
                "sources": current, "runs": runs,
                "interpretation": "Sensitivity scenarios, not forecasts. Historical references provide context; changed forcings mean differences do not isolate release-policy effects.",
                "legacy_integrity": "Earlier runs without daily_sha256 can be read but have no recorded output checksum."}}


def batch_plan(kind, settings, name):
    if kind == "Rainfall × inflow grid":
        return [{**settings, "rain_multiplier": rain, "inflow_multiplier": inflow,
                 "name": f"{name[:55]} · rain {rain:.1f}× / inflow {inflow:.1f}×"}
                for rain in (.8, 1., 1.2) for inflow in (.8, 1., 1.2)]
    if kind == "Release sweep":
        return [{**settings, "release_multiplier": release,
                 "name": f"{name[:65]} · release {release:.1f}×"} for release in (.9, 1., 1.1)]
    raise ValueError("Unknown stress-test suite.")


def save_batch(batch, root=ROOT):
    # Batch IDs use the same safe identifier grammar as run IDs.
    if not RUN_ID.fullmatch(batch["batch_id"]):
        raise ValueError("Invalid batch identifier.")
    folder = root / "outputs/observatory/batches"
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / f'{batch["batch_id"]}.json', batch)


def list_batches(root=ROOT):
    rows = []
    for path in sorted((root / "outputs/observatory/batches").glob("*.json"), reverse=True):
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
            rows.append(batch)
        except (ValueError, OSError):
            rows.append({"batch_id": path.stem, "name": "Unreadable batch record", "status": "unavailable", "results": []})
    return rows

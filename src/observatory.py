"""Canonical data loading, comparable metrics and immutable local run records."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import numpy as np
import pandas as pd
from .engine import ReleasePolicy, SimParams, simulate_with_policy

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = {
    "observations": "data/processed/audit_daily_core_variables.csv",
    "optimized": "data/processed/06_optimized_rulecurve_sim.csv",
    "baseline": "data/processed/06_baseline_agreedcurve_sim.csv",
    "pareto": "outputs/tables/06_optimization_pareto_solutions.csv",
    "candidates": "outputs/tables/06_candidate_behavior_metrics.csv",
    "calibration": "outputs/tables/05_lake_level_performance.csv",
    "inflow": "data/processed/Qin_total_daily_2001_2021.csv",
    "hypsometry": "data/processed/hypsometry/lv_stage_area_storage.csv",
    "map_summary_notebook09": "outputs/tables/09_flood_extent_summary.csv",
    "map_summary_project_aligned": "outputs/tables/project_aligned_peak_net_flood_summary.csv",
    "map_notebook09": "outputs/figures/09_peak_flood_maps_observed_vs_optimized_true_metrics.png",
    "map_project_aligned": "outputs/figures/Side_By_Side_Flood_Maps.png",
}
SCENARIOS = ("Observed", "Optimized", "Agreed Curve")


def read_daily(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans or not df.index.is_unique:
        raise ValueError(f"Invalid or duplicate dates in {Path(path).name}")
    df = df.sort_index()
    df.index.name = "date"
    return df


def load_scenarios(root=ROOT):
    obs = read_daily(root / SOURCE_FILES["observations"])
    out = {"Observed": obs.rename(columns={"lake_level_m": "level_m"})[["level_m", "outflow_m3s"]]}
    for name, key in [("Optimized", "optimized"), ("Agreed Curve", "baseline")]:
        df = read_daily(root / SOURCE_FILES[key])
        out[name] = df.rename(columns={"level_sim_m": "level_m", "qout_policy_m3s": "outflow_m3s"})[["level_m", "outflow_m3s"]]
    start = max(df.index.min() for df in out.values())
    end = min(df.index.max() for df in out.values())
    calendar = pd.date_range(start, end, name="date")
    return {name: df.reindex(calendar) for name, df in out.items()}


def slice_scenarios(scenarios, start, end):
    return {name: df.loc[pd.Timestamp(start):pd.Timestamp(end)].copy() for name, df in scenarios.items()}


def common_metric_frames(scenarios, column):
    aligned = pd.concat({name: df[column] for name, df in scenarios.items()}, axis=1)
    return aligned.where(np.isfinite(aligned)).dropna(how="any")


def scorecard(scenarios, threshold=12.8, low=11.15):
    """Each metric uses dates valid for that metric in every scenario."""
    levels = common_metric_frames(scenarios, "level_m")
    flows = common_metric_frames(scenarios, "outflow_m3s")
    rows = []
    consecutive = flows.index.to_series().diff().eq(pd.Timedelta(days=1))
    for name in scenarios:
        h, q = levels[name], flows[name]
        excess = (h - threshold).clip(lower=0)
        rows.append(dict(scenario=name, valid_level_days=len(h), valid_flow_days=len(q),
            peak_level_m=h.max(), mean_level_m=h.mean(), flood_days=int((h > threshold).sum()) if len(h) else np.nan,
            severity_m_days=excess.sum() if len(h) else np.nan,
            low_days=int((h < low).sum()) if len(h) else np.nan,
            mean_outflow_m3s=q.mean(), mean_ramp_m3s_day=q.diff().abs()[consecutive].mean()))
    return pd.DataFrame(rows).set_index("scenario")


def load_pareto(root=ROOT):
    df = pd.read_csv(root / SOURCE_FILES["pareto"])
    df.index.name = "candidate_index"
    return df.reset_index()


def fingerprint(root=ROOT):
    sources = []
    for key, rel in SOURCE_FILES.items():
        path = root / rel
        sources.append({"id": key, "path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "bytes": path.stat().st_size})
    identity = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()[:12]
    return {"snapshot_id": identity, "sources": sources,
            "classification": "Historical observations and supplied model scenarios",
            "level_units": "m relative to Jinja gauge datum; add 1122.85 for m ASL",
            "comparison": "Metric-specific common valid daily dates; no observation gap filling",
            "limitations": ["Legacy artifacts have no shared run identifier.",
                "Pareto scores describe the supplied candidate export, not the saved daily policy run.",
                "New runs use daily causal feedback; legacy optimization used two full-series iterations."]}


def run_experiment(*, release_multiplier=1.0, inflow_multiplier=1.0, rain_multiplier=1.0,
                   ramp_limit=200.0, name="Exploratory scenario", batch_id=None, root=ROOT):
    name = str(name).strip()
    if not name or len(name) > 100:
        raise ValueError("Give the scenario a name of 1–100 characters.")
    before = fingerprint(root)
    core = read_daily(root / SOURCE_FILES["observations"])
    core["qin_m3s"] = read_daily(root / SOURCE_FILES["inflow"]).iloc[:, 0]
    c = pd.read_csv(root / SOURCE_FILES["calibration"]).iloc[0]
    params = SimParams(c.level_offset_m, c.k_gw, c.alpha_storage_physical, c.beta_inflow)
    policy = ReleasePolicy(release_multiplier=release_multiplier, ramp_limit=ramp_limit)
    result = simulate_with_policy(policy, core, params=params,
        hypsometry=pd.read_csv(root / SOURCE_FILES["hypsometry"]),
        initial_level=float(core.lake_level_m.iloc[0]),
        inflow_multiplier=inflow_multiplier, rain_multiplier=rain_multiplier)
    meta = fingerprint(root)
    if before["snapshot_id"] != meta["snapshot_id"]:
        raise ValueError("Source files changed during this run. Please rerun with stable inputs.")
    meta.update({"run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
        "name": name, "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "engine": "causal-daily-v1",
        "policy": asdict(policy), "calibration": asdict(params),
        "forcing_multipliers": {"inflow": inflow_multiplier, "rainfall": rain_multiplier},
        "initial_level_m": float(core.lake_level_m.iloc[0]), "period": [str(result.index.min().date()), str(result.index.max().date())],
        "engine_sha256": hashlib.sha256((ROOT / "src/engine.py").read_bytes()).hexdigest()})
    folder = root / "outputs/observatory/runs" / meta["run_id"]
    folder.mkdir(parents=True)
    result.to_parquet(folder / "daily.parquet")
    meta["daily_sha256"] = hashlib.sha256((folder / "daily.parquet").read_bytes()).hexdigest()
    pending = folder / "run.pending.json"
    pending.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    pending.replace(folder / "run.json")
    return result, meta

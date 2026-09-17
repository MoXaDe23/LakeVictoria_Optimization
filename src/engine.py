"""Daily storage model adapted from notebook 06 with explicit validation.

New exploratory runs use causal daily feedback. Notebook 06 used two full-series
iterations; its historical outputs remain separate. Missing forcings and storage
overflow raise errors rather than silently creating or destroying water.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class SimParams:
    level_offset_m: float
    k_gw: float
    alpha_storage: float
    beta_inflow: float


@dataclass(frozen=True)
class ReleasePolicy:
    dry_knots: tuple = (980.0, 980.6, 980.6, 1131.0)
    wet_knots: tuple = (995.0, 995.6, 995.6, 1146.0)
    level_knots: tuple = (11.15, 11.50, 11.85, 12.15)
    wet_months: tuple = (3, 4, 5, 6, 11, 12)
    q_min: float = 343.0
    q_max: float = 1528.0
    ramp_limit: float = 200.0
    low_buffer: float = 0.20
    high_buffer: float = 0.20
    protective_min: float = 800.0
    release_multiplier: float = 1.0

    def __post_init__(self):
        values = [*self.dry_knots, *self.wet_knots, *self.level_knots, self.q_min,
                  self.q_max, self.ramp_limit, self.low_buffer, self.high_buffer,
                  self.protective_min, self.release_multiplier]
        if not np.isfinite(values).all():
            raise ValueError("Policy parameters must be finite.")
        if any(len(v) != 4 for v in (self.level_knots, self.dry_knots, self.wet_knots)):
            raise ValueError("Four level and release knots are required.")
        if np.any(np.diff(self.level_knots) <= 0):
            raise ValueError("Level knots must strictly increase.")
        if self.q_min < 0 or self.q_max < self.q_min or self.ramp_limit < 0:
            raise ValueError("Invalid release limits.")
        if min(self.low_buffer, self.high_buffer, self.release_multiplier) <= 0:
            raise ValueError("Buffers and multiplier must be positive.")

    def release(self, level, month, previous=None):
        wet = month in self.wet_months
        knots = self.wet_knots if wet else self.dry_knots
        q = float(np.interp(level, self.level_knots, np.maximum.accumulate(knots)))
        if wet:
            protection = np.clip((level - (12.15 - self.high_buffer)) / self.high_buffer, 0, 1)
            ceiling = 1200 + protection * (self.q_max - 1200)
            share = np.clip((q - 980) / 220, 0, 1)
            q = 980 + share * (ceiling - 980)
        else:
            protection = np.clip((11.15 + self.low_buffer - level) / self.low_buffer, 0, 1)
            q = min(q, self.protective_min + (1 - protection) * (980 - self.protective_min))
        q = float(np.clip(q * self.release_multiplier, self.q_min, self.q_max))
        if previous is not None:
            q = float(np.clip(q, previous - self.ramp_limit, previous + self.ramp_limit))
        return q


def lake_mass_balance(P, E, Qin, Qout, area, H0):
    """Constant-area check model; P/E mm/day, flows m³/s, area m²."""
    p, e, qi, qo = np.broadcast_arrays(P, E, Qin, Qout)
    if not np.isfinite([area, H0]).all() or area <= 0:
        raise ValueError("Area must be positive and initial level finite.")
    if not all(np.isfinite(v).all() for v in (p, e, qi, qo)):
        raise ValueError("Inputs must be finite.")
    return H0 + np.cumsum((p - e) / 1000 + (qi - qo) * SECONDS_PER_DAY / area)


def simulate_with_policy(policy_params, inputs, *, params, hypsometry,
                         initial_level, inflow_multiplier=1.0, rain_multiplier=1.0):
    """End-of-day states. Only the initial observed level is used.

    Groundwater follows notebook 06's fixed 30-day convention.
    """
    frame = inputs[["rainfall_mm", "evap_mm", "qin_m3s"]].copy()
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("A nonempty daily DatetimeIndex is required.")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Dates must be unique and ordered.")
    if len(frame) > 1 and not (frame.index.to_series().diff().iloc[1:] == pd.Timedelta(days=1)).all():
        raise ValueError("Inputs must have an uninterrupted daily calendar.")
    if not np.isfinite(frame.to_numpy()).all() or (frame < 0).any().any():
        raise ValueError("Forcings must be finite, nonnegative, and complete.")
    scalars = [params.level_offset_m, params.k_gw, params.alpha_storage, params.beta_inflow,
               initial_level, inflow_multiplier, rain_multiplier]
    if not np.isfinite(scalars).all() or params.alpha_storage <= 0 or min(params.k_gw, params.beta_inflow, inflow_multiplier, rain_multiplier) < 0:
        raise ValueError("Invalid model parameters.")
    hyp = hypsometry.sort_values("stage_rel_m")
    h, a, s = (hyp[c].to_numpy(float) for c in ("stage_rel_m", "area_m2", "storage_m3"))
    if len(h) < 2 or not all(np.isfinite(x).all() for x in (h, a, s)) or np.any(a <= 0) or np.any(np.diff(h) <= 0) or np.any(np.diff(s) <= 0):
        raise ValueError("Hypsometry must have positive areas and increasing stage/storage.")
    stage = initial_level - params.level_offset_m
    if not h[0] <= stage <= h[-1]:
        raise ValueError("Initial level lies outside the hypsometry domain.")
    storage = params.alpha_storage * np.interp(stage, h, s)
    gw = params.k_gw * 0.09e9 / 30
    rows, previous = [], None
    for date, (rain, evap, qin) in zip(frame.index, frame.to_numpy(float)):
        area = np.interp(stage, h, a)
        release = policy_params.release(stage + params.level_offset_m, date.month, previous)
        v_pe = (rain * rain_multiplier - evap) / 1000 * area
        v_in = qin * params.beta_inflow * inflow_multiplier * SECONDS_PER_DAY
        v_out = release * SECONDS_PER_DAY
        delta = v_pe + v_in - v_out - gw
        storage += delta
        if not s[0] <= storage / params.alpha_storage <= s[-1]:
            raise ValueError(f"Storage outside the hypsometry domain on {date.date()}.")
        stage = np.interp(storage / params.alpha_storage, s, h)
        rows.append((stage + params.level_offset_m, release, storage, delta, v_pe, v_in, v_out, gw))
        previous = release
    return pd.DataFrame(rows, index=frame.index, columns=[
        "level_m", "outflow_m3s", "storage_m3", "dS_m3d", "vol_p_minus_e_m3d",
        "vol_qin_m3d", "vol_qout_m3d", "vol_gw_m3d"])

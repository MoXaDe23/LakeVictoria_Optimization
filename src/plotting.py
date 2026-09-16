from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from config import (
    HIGH_FLOOD_THRESHOLD_ASL_M,
    LOW_WATER_THRESHOLD_ASL_M,
    LOW_WATER_THRESHOLD_REL_M,
    OFFICIAL_LAKE_SURFACE_AREA_KM2,
    REFERENCE_LEVEL_M_ASL,
    asl_column_name,
    rel_to_asl,
)

LOW_WATER_THRESHOLD_M = LOW_WATER_THRESHOLD_ASL_M
HIGH_FLOOD_THRESHOLD_M = HIGH_FLOOD_THRESHOLD_ASL_M
DEFAULT_LAKE_AREA_KM2 = OFFICIAL_LAKE_SURFACE_AREA_KM2
DEFAULT_QUICKLOOK_STEP = 20


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    data_raw: Path
    data_processed: Path
    figures: Path
    tables: Path


def infer_project_root(project_root: str | Path | None = None) -> Path:
    if project_root is not None:
        return Path(project_root).resolve()

    cwd = Path.cwd()
    if cwd.name == "notebooks":
        return cwd.parent.resolve()
    return cwd.resolve()


def build_project_paths(project_root: str | Path | None = None) -> ProjectPaths:
    root = infer_project_root(project_root)
    figures = root / "outputs" / "figures"
    tables = root / "outputs" / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    return ProjectPaths(
        project_root=root,
        data_raw=root / "data" / "raw",
        data_processed=root / "data" / "processed",
        figures=figures,
        tables=tables,
    )


def _load_csv_with_date_index(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    candidate_cols = [
        "date",
        "Date",
        "datetime",
        "Datetime",
        "Unnamed: 0",
        "index",
    ]
    date_col = next((col for col in candidate_cols if col in df.columns), None)
    if date_col is None:
        date_col = df.columns[0]

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    df.index.name = "date"
    return df


def _load_observed_outflow(
    raw_dir: Path,
    target_index: pd.DatetimeIndex,
) -> pd.Series:
    obs_out_path = raw_dir / "Victoria_Nile_Out_Flows.csv"
    obs_out = pd.read_csv(obs_out_path)

    date_col = next((col for col in obs_out.columns if "date" in col.lower()), None)
    if date_col is None:
        raise ValueError(
            f"No date column found in {obs_out_path.name}. "
            f"Columns={obs_out.columns.tolist()}"
        )

    numeric_cols = [
        col
        for col in obs_out.columns
        if col != date_col and np.issubdtype(obs_out[col].dtype, np.number)
    ]
    if not numeric_cols:
        raise ValueError(
            f"No numeric flow column found in {obs_out_path.name}. "
            f"Columns={obs_out.columns.tolist()}"
        )

    preferred_cols = [
        col
        for col in numeric_cols
        if any(token in col.lower() for token in ("out", "flow", "discharge", "q"))
    ]
    flow_col = preferred_cols[0] if preferred_cols else numeric_cols[0]

    obs_out[date_col] = pd.to_datetime(obs_out[date_col], errors="coerce")
    outflow = (
        obs_out.dropna(subset=[date_col])
        .set_index(date_col)
        .sort_index()[flow_col]
        .astype(float)
        .reindex(target_index)
        .interpolate(limit_direction="both")
        .ffill()
        .bfill()
    )
    outflow.index.name = "date"
    outflow.name = "qout_observed_m3s"
    return outflow


def load_project_comparison_frame(
    project_root: str | Path | None = None,
    reference_level_m_asl: float = REFERENCE_LEVEL_M_ASL,
) -> pd.DataFrame:
    paths = build_project_paths(project_root)

    baseline_path = paths.data_processed / "06_baseline_agreedcurve_sim.csv"
    optimized_path = paths.data_processed / "06_optimized_rulecurve_sim.csv"

    baseline = _load_csv_with_date_index(baseline_path)
    optimized = _load_csv_with_date_index(optimized_path)

    required_level_cols = {"level_obs_m", "level_sim_m"}
    missing_baseline = required_level_cols - set(baseline.columns)
    missing_optimized = {"level_sim_m", "qout_policy_m3s"} - set(optimized.columns)
    if missing_baseline:
        raise ValueError(
            f"Baseline simulation is missing columns: {sorted(missing_baseline)}"
        )
    if missing_optimized:
        raise ValueError(
            f"Optimized simulation is missing columns: {sorted(missing_optimized)}"
        )

    observed_outflow = _load_observed_outflow(paths.data_raw, baseline.index)

    obs_level_rel = baseline["level_obs_m"].astype(float)
    opt_level_rel = optimized["level_sim_m"].astype(float).reindex(baseline.index)
    obs_level_asl_col = asl_column_name("level_obs_m")
    opt_level_asl_col = asl_column_name("level_sim_m")

    if obs_level_asl_col in baseline.columns:
        obs_level_asl = baseline[obs_level_asl_col].astype(float)
    else:
        obs_level_asl = rel_to_asl(obs_level_rel, reference_level_m_asl)

    if opt_level_asl_col in optimized.columns:
        opt_level_asl = optimized[opt_level_asl_col].astype(float).reindex(baseline.index)
    else:
        opt_level_asl = rel_to_asl(opt_level_rel, reference_level_m_asl)

    frame = pd.DataFrame(
        {
            "level_obs_m": obs_level_rel,
            "level_obs_m_asl": obs_level_asl,
            "level_opt_m": opt_level_rel,
            "level_opt_m_asl": opt_level_asl,
            "qout_observed_m3s": observed_outflow,
            "qout_opt_policy_m3s": optimized["qout_policy_m3s"]
            .astype(float)
            .reindex(baseline.index),
        },
        index=baseline.index,
    ).sort_index()
    frame.index.name = "date"
    return frame


def _month_labels() -> list[str]:
    return [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]


def plot_monthly_average_comparison(
    comparison: pd.DataFrame,
    output_path: Path,
) -> Path:
    monthly = comparison.resample("MS").mean(numeric_only=True)
    climatology = (
        monthly.groupby(monthly.index.month)[
            ["qout_observed_m3s", "qout_opt_policy_m3s"]
        ]
        .mean()
        .rename(
            columns={
                "qout_observed_m3s": "Observed",
                "qout_opt_policy_m3s": "Optimized Rule",
            }
        )
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        climatology.index,
        climatology["Observed"],
        marker="o",
        linewidth=2.0,
        label="Observed",
        color="#d62728",
    )
    ax.plot(
        climatology.index,
        climatology["Optimized Rule"],
        marker="o",
        linewidth=2.0,
        label="Optimized Rule",
        color="#1f77b4",
    )
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(_month_labels())
    ax.set_xlabel("Month")
    ax.set_ylabel("Outflow (m3/s)")
    ax.set_title("Average Monthly Outflow: Observed vs Optimized Rule")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_scenario_comparison(
    comparison: pd.DataFrame,
    output_path: Path,
    low_water_threshold_m: float = LOW_WATER_THRESHOLD_M,
    high_flood_threshold_m: float = HIGH_FLOOD_THRESHOLD_M,
) -> Path:
    monthly = comparison.resample("MS").mean(numeric_only=True)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12), sharex=True)

    ax1.plot(
        monthly.index,
        monthly["level_obs_m_asl"],
        color="0.45",
        linewidth=1.8,
        alpha=0.85,
        label="Observed Level",
    )
    ax1.plot(
        monthly.index,
        monthly["level_opt_m_asl"],
        color="#1f77b4",
        linewidth=2.0,
        label="Optimized Rule Level",
    )
    ax1.axhspan(
        low_water_threshold_m,
        high_flood_threshold_m,
        color="#8BC34A",
        alpha=0.18,
        label="Preferred Operating Band",
    )
    ax1.axhline(
        high_flood_threshold_m,
        color="#b22222",
        linestyle="--",
        linewidth=1.1,
        label=f"High Flood Threshold ({high_flood_threshold_m:.2f} m asl)",
    )
    ax1.axhline(
        low_water_threshold_m,
        color="#b22222",
        linestyle="--",
        linewidth=1.1,
        label=f"Low-Water Threshold ({low_water_threshold_m:.2f} m asl)",
    )
    ax1.set_ylabel("Lake Level (m asl)")
    ax1.set_title("Lake Victoria Levels and Outflows: Observed vs Optimized Rule")
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="best")

    ax2.plot(
        monthly.index,
        monthly["qout_observed_m3s"],
        color="#d62728",
        linewidth=1.8,
        alpha=0.75,
        label="Observed Outflow",
    )
    ax2.plot(
        monthly.index,
        monthly["qout_opt_policy_m3s"],
        color="#1f77b4",
        linewidth=2.0,
        label="Optimized Rule Outflow",
    )
    ax2.set_xlabel("Date")
    ax2.set_ylabel("Outflow (m3/s)")
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="best")

    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _resolve_dem_path(paths: ProjectPaths) -> Path:
    preferred = paths.data_raw / "dem_kyoganile" / "LVBDEM2.tif"
    if preferred.exists():
        return preferred

    for dem_dir_name in ("dem_kyoganile", "dem_kyoganil"):
        dem_dir = paths.data_raw / dem_dir_name
        tif_candidates = sorted(dem_dir.glob("*.tif"))
        if tif_candidates:
            return tif_candidates[0]

    raise FileNotFoundError(
        "No DEM .tif was found under data/raw/dem_kyoganile or data/raw/dem_kyoganil."
    )


def _quicklook(array: np.ndarray, step: int = DEFAULT_QUICKLOOK_STEP) -> np.ndarray:
    return array[::step, ::step]


def _flood_mask(dem: np.ndarray, water_level_m_asl: float) -> np.ndarray:
    mask = np.empty(dem.shape, dtype=bool)
    np.isfinite(dem, out=mask)
    np.less_equal(dem, water_level_m_asl, out=mask, where=mask)
    return mask


def create_peak_net_flood_summary(
    project_root: str | Path | None = None,
    reference_level_m_asl: float = REFERENCE_LEVEL_M_ASL,
    reference_lake_level_rel_m: float = LOW_WATER_THRESHOLD_REL_M,
    lake_area_km2: float = DEFAULT_LAKE_AREA_KM2,
    quicklook_step: int = DEFAULT_QUICKLOOK_STEP,
) -> tuple[pd.DataFrame, dict[str, np.ndarray], np.ndarray]:
    try:
        import rasterio
    except ImportError as exc:
        raise ImportError(
            "rasterio is required for the flood-extent plots. "
            "Install it in the notebook kernel before running this step."
        ) from exc

    paths = build_project_paths(project_root)
    comparison = load_project_comparison_frame(paths.project_root)

    level_obs_asl = comparison["level_obs_m_asl"]
    level_opt_asl = comparison["level_opt_m_asl"]
    peak_year = int(level_obs_asl.resample("YS").max().idxmax().year)

    scenario_levels = {
        "Observed Historical Peak": float(level_obs_asl[level_obs_asl.index.year == peak_year].max()),
        "Optimized Rule": float(level_opt_asl[level_opt_asl.index.year == peak_year].max()),
    }

    dem_path = _resolve_dem_path(paths)
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        if src.nodata is not None:
            dem = np.where(dem == src.nodata, np.nan, dem)
        cell_area_km2 = abs(src.res[0] * src.res[1]) / 1e6

    reference_lake_level_asl = reference_level_m_asl + reference_lake_level_rel_m
    reference_mask = _flood_mask(dem, reference_lake_level_asl)
    reference_preview = _quicklook(reference_mask, quicklook_step)
    dem_preview = _quicklook(dem, quicklook_step)
    reference_area_from_dem_km2 = float(np.count_nonzero(reference_mask) * cell_area_km2)

    preview_layers: dict[str, np.ndarray] = {"reference_lake": reference_preview}
    rows: list[dict[str, Any]] = []

    for scenario, water_level_m_asl in scenario_levels.items():
        total_mask = _flood_mask(dem, water_level_m_asl)
        total_pixels = int(np.count_nonzero(total_mask))
        total_area_km2 = float(total_pixels * cell_area_km2)

        total_preview = _quicklook(total_mask, quicklook_step)
        net_preview = total_preview & ~reference_preview
        preview_layers[scenario] = net_preview

        rows.append(
            {
                "scenario": scenario,
                "peak_year": peak_year,
                "water_level_m_asl": water_level_m_asl,
                "total_flooded_area_km2": total_area_km2,
                "lake_area_reference_km2": float(lake_area_km2),
                "reference_mask_area_from_dem_km2": reference_area_from_dem_km2,
                "net_flooded_land_km2": max(total_area_km2 - lake_area_km2, 0.0),
            }
        )

    summary = pd.DataFrame(rows)
    summary.to_csv(
        paths.tables / "project_aligned_peak_net_flood_summary.csv",
        index=False,
    )
    return summary, preview_layers, dem_preview


def plot_side_by_side_flood_maps(
    summary: pd.DataFrame,
    preview_layers: dict[str, np.ndarray],
    dem_preview: np.ndarray,
    output_path: Path,
) -> Path:
    scenarios = ["Observed Historical Peak", "Optimized Rule"]
    fig, axes = plt.subplots(1, 2, figsize=(18, 8), constrained_layout=False)

    lake_cmap = ListedColormap(["#4c78a8"])
    flood_cmap = ListedColormap(["#d62728"])

    for ax, scenario in zip(axes, scenarios):
        ax.imshow(dem_preview, cmap="terrain", alpha=0.18)
        ax.imshow(
            np.ma.masked_where(~preview_layers["reference_lake"], preview_layers["reference_lake"]),
            cmap=lake_cmap,
            alpha=0.78,
        )
        ax.imshow(
            np.ma.masked_where(~preview_layers[scenario], preview_layers[scenario]),
            cmap=flood_cmap,
            alpha=0.82,
        )

        row = summary.loc[summary["scenario"] == scenario].iloc[0]
        ax.set_title(
            (
                f"{scenario}\n"
                f"Peak-year level: {row['water_level_m_asl']:.2f} m asl | "
                f"Net flooded land: {row['net_flooded_land_km2']:.1f} km2"
            ),
            fontsize=11,
        )
        ax.set_xticks([])
        ax.set_yticks([])

    legend_handles = [
        Patch(facecolor="#4c78a8", edgecolor="none", label="Reference lake footprint"),
        Patch(facecolor="#d62728", edgecolor="none", label="Net flooded land"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.02),
        ncol=2,
        frameon=False,
    )
    fig.suptitle("Peak Flood-Year Flood Maps: Observed vs Optimized Rule", fontsize=16)
    fig.subplots_adjust(bottom=0.14, top=0.88, wspace=0.08)
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_peak_net_flood_comparison(
    summary: pd.DataFrame,
    output_path: Path,
) -> Path:
    ordered = (
        summary.set_index("scenario")
        .loc[["Observed Historical Peak", "Optimized Rule"]]
        .reset_index()
    )
    colors = ["#d62728", "#1f77b4"]

    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.bar(
        ordered["scenario"],
        ordered["net_flooded_land_km2"],
        color=colors,
        alpha=0.85,
    )
    ax.set_title("Comparison of Peak Net Flooded Land Area")
    ax.set_ylabel("Net Flooded Land (km2)")
    ax.grid(axis="y", linestyle="--", alpha=0.45)

    for bar in bars:
        height = float(bar.get_height())
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height,
            f"{height:.1f}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output_path


def generate_project_aligned_comparison_figures(
    project_root: str | Path | None = None,
    reference_level_m_asl: float = REFERENCE_LEVEL_M_ASL,
    lake_area_km2: float = DEFAULT_LAKE_AREA_KM2,
    quicklook_step: int = DEFAULT_QUICKLOOK_STEP,
) -> dict[str, Any]:
    paths = build_project_paths(project_root)
    comparison = load_project_comparison_frame(paths.project_root)

    monthly_average_path = plot_monthly_average_comparison(
        comparison=comparison,
        output_path=paths.figures / "Monthly_Average_Comparison.png",
    )
    scenario_comparison_path = plot_scenario_comparison(
        comparison=comparison,
        output_path=paths.figures / "Scenario_Comparison_Seasonal.png",
    )

    flood_summary, preview_layers, dem_preview = create_peak_net_flood_summary(
        project_root=paths.project_root,
        reference_level_m_asl=reference_level_m_asl,
        lake_area_km2=lake_area_km2,
        quicklook_step=quicklook_step,
    )
    side_by_side_path = plot_side_by_side_flood_maps(
        summary=flood_summary,
        preview_layers=preview_layers,
        dem_preview=dem_preview,
        output_path=paths.figures / "Side_By_Side_Flood_Maps.png",
    )
    peak_net_path = plot_peak_net_flood_comparison(
        summary=flood_summary,
        output_path=paths.figures / "Peak_Net_Flood_Comparison.png",
    )

    return {
        "project_root": paths.project_root,
        "figures": {
            "Monthly_Average_Comparison": monthly_average_path,
            "Scenario_Comparison_Seasonal": scenario_comparison_path,
            "Side_By_Side_Flood_Maps": side_by_side_path,
            "Peak_Net_Flood_Comparison": peak_net_path,
        },
        "tables": {
            "project_aligned_peak_net_flood_summary": paths.tables
            / "project_aligned_peak_net_flood_summary.csv",
        },
        "peak_flood_summary": flood_summary,
    }

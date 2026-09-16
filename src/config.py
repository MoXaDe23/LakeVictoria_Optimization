from __future__ import annotations

REFERENCE_LEVEL_M_ASL = 1122.85

LOW_WATER_THRESHOLD_REL_M = 11.15
HIGH_FLOOD_THRESHOLD_REL_M = 12.15

LOW_WATER_THRESHOLD_ASL_M = REFERENCE_LEVEL_M_ASL + LOW_WATER_THRESHOLD_REL_M
HIGH_FLOOD_THRESHOLD_ASL_M = REFERENCE_LEVEL_M_ASL + HIGH_FLOOD_THRESHOLD_REL_M

OFFICIAL_LAKE_SURFACE_AREA_KM2 = 68800.0


def rel_to_asl(level_rel_m, reference_level_m_asl: float = REFERENCE_LEVEL_M_ASL):
    return level_rel_m + reference_level_m_asl


def asl_column_name(relative_level_column: str) -> str:
    if relative_level_column.endswith("_m"):
        return f"{relative_level_column}_asl"
    return f"{relative_level_column}_m_asl"

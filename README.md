# LakeVictoria_Optimization

## Optimized Dam Outflow Policy for Lake Victoria Flood Risk Reduction

This repository presents the methodology and results for developing and evaluating an optimized dam outflow policy for Lake Victoria. The primary objective is to reduce flood risk around the lake by improving upon historical dam operations.

The study period spans from January 1, 2001, to April 27, 2021, and compares three distinct scenarios:
1.  **Observed:** Actual historical lake levels and dam outflows.
2.  **Agreed Curve:** A pre-existing baseline policy for dam releases.
3.  **Optimized:** The new, improved outflow policy developed through this project.

## Methodology

The project followed a structured approach involving data preparation, hydrological modeling, and scenario evaluation:

### 1. Data Auditing and Preparation

A comprehensive data inventory and quality audit was performed on all hydro-meteorological inputs. These core daily datasets included:
*   Lake-average precipitation (CHIRPS)
*   Lake evaporation
*   Victoria Nile outflows at Jinja
*   Observed lake levels at Jinja pier

The common overlapping period of **2001-01-01 to 2021-04-27 (7,422 days)** was established as the primary calibration and evaluation window for the lake water balance model.

### 2. Tributary Inflow Reconstruction

Due to varying record lengths and gaps, continuous daily tributary inflow series (`Qin`) for 15 Lake Victoria tributaries were reconstructed for the 2001–2021 study period. This involved using rainfall-informed methods:
*   For 12 tributaries with sufficient overlap between observed flow records and the study window, ridge regression models were developed using monthly rainfall totals, lagged rainfall, and seasonal terms. These models showed generally good predictive skill.
*   For three tributaries (Nyando, Nzoia, Yala) lacking overlap with the study period, historical monthly climatology scaled by rainfall anomalies was used.
*   Reconstructed monthly inflows were then disaggregated to daily flows using rainfall-weighted allocation, preserving monthly mean discharge while reflecting intra-month variability.

### 3. Lake Water Balance Modeling

A daily water balance model for Lake Victoria was developed and calibrated for the 2001–2021 period. The model incorporates:
*   Lake hypsometry (stage–area–storage relationships) derived from a 100 m bathymetry raster, preserving the nonlinear storage response of the basin.
*   Direct lake rainfall, evaporation, reconstructed tributary inflows (`Qin`), observed outflows at Jinja (`Qout`), and groundwater loss (parameterized as `k_gw·0.09×10^9 m³/month` with `k_gw=1.50`).
*   Calibration against observed lake levels yielded strong performance metrics: **RMSE=0.162 m** and **NSE=0.923**, indicating the model's ability to accurately capture lake level dynamics and providing a physically consistent basis for subsequent outflow optimization experiments.

### 4. Outflow Optimization and Scenario Evaluation

Building upon the validated water balance model, an optimized dam outflow policy was developed. This policy was then rigorously evaluated against the observed historical operations and the 'Agreed Curve' baseline across various flood risk metrics.

## Key Findings

The optimized outflow policy demonstrates significant improvements in flood risk reduction compared to observed operations, while successfully avoiding the excessive long-term drawdown exhibited by the baseline 'Agreed Curve' policy.

### Time-Series Flood Metrics (at 12.8 m threshold)

Flood-risk diagnostics were evaluated using multi-threshold exceedance metrics (12.5 m, 12.8 m, and 13.0 m). At the **12.8 m (high-flood reference) threshold**, the analysis revealed:

*   **Exceedance Frequency (Number of days exceeding 12.8 m):**
    *   Observed: 452 days
    *   Agreed Curve: 0 days (indicating excessive drawdown)
    *   Optimized: 389 days (a reduction from observed conditions)

*   **Flood Severity (Sum of meters above threshold across exceedance days):**
    *   Observed: 162.74 m-days
    *   Optimized: 115.92 m-days (a substantial reduction of approximately 29%)

These results indicate that the optimized policy produced improved flood-risk shaping (reduced peak severity and altered exceedance structure) compared to observed operations.

### Spatial Flood Extent Analysis

Raster-based inundation analysis using a surrounding-land Digital Elevation Model (DEM) was applied to evaluate spatial flood extent under the different regulation scenarios.

*   For the **peak flood year (2020)**, the optimized rule curve significantly reduced the flooded area relative to observed conditions.
*   The optimized policy also avoided the excessive drawdown associated with the Agreed Curve counterfactual.

These spatial flood extent results reinforce the time-series flood metrics, demonstrating that the optimized release policy effectively reduces flood risk exposure while maintaining realistic lake level dynamics.

## Conclusion

Overall, the optimized policy successfully reduces flood frequency, severity, and spatial extent, offering a more resilient and sustainable dam management strategy for Lake Victoria.
```
<!--
[PROMPT_SUGGESTION]Based on the flood metrics, can you create a markdown table comparing the 'Observed', 'Agreed Curve', and 'Optimized' scenarios at the 12.8m threshold?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Can you explain the concept of "hypsometry" in the context of the Lake Water Balance Model?[/PROMPT_SUGGESTION]

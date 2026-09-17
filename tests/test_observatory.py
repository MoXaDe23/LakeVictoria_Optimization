from io import BytesIO
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.engine import ReleasePolicy, SimParams, lake_mass_balance, simulate_with_policy
from src.observatory import load_scenarios, scorecard, slice_scenarios


def test_constant_area_water_balance_units():
    assert lake_mass_balance([10, 0], [0, 10], [1, 0], [0, 1], 86400, 10).tolist() == pytest.approx([11.01, 10.0])


def test_daily_storage_conservation_and_causality():
    dates = pd.date_range('2020-01-01', periods=5)
    forcing = pd.DataFrame({'rainfall_mm': [1, 5, 2, 1, 0], 'evap_mm': 1., 'qin_m3s': 1000.}, index=dates)
    hyp = pd.DataFrame({'stage_rel_m': [-5., 5.], 'storage_m3': [1e12, 2e12], 'area_m2': [1e11, 1e11]})
    params = SimParams(10., 1.5, 1., 1.)
    policy = ReleasePolicy(ramp_limit=25.)
    run = simulate_with_policy(policy, forcing, params=params, hypsometry=hyp, initial_level=11.69)
    initial_storage = np.interp(1.69, hyp.stage_rel_m, hyp.storage_m3)
    np.testing.assert_allclose(np.diff(np.r_[initial_storage, run.storage_m3]), run.dS_m3d, atol=.001)
    np.testing.assert_allclose(run.dS_m3d, run.vol_p_minus_e_m3d + run.vol_qin_m3d - run.vol_qout_m3d - run.vol_gw_m3d)
    assert run.outflow_m3s.between(policy.q_min, policy.q_max).all()
    assert run.outflow_m3s.diff().abs().dropna().max() <= 25.
    future_changed = forcing.copy()
    future_changed.iloc[-1, 0] = 100.
    other = simulate_with_policy(policy, future_changed, params=params, hypsometry=hyp, initial_level=11.69)
    pd.testing.assert_frame_equal(run.iloc[:-1], other.iloc[:-1])
    assert run.outflow_m3s.iloc[-1] == other.outflow_m3s.iloc[-1]
    bad = forcing.copy()
    bad.iloc[2, 0] = np.nan
    with pytest.raises(ValueError, match='complete'):
        simulate_with_policy(policy, bad, params=params, hypsometry=hyp, initial_level=11.69)


def test_missing_observations_are_excluded_and_ramps_do_not_bridge():
    dates = pd.date_range('2020-01-01', periods=4)
    a = pd.DataFrame({'level_m': [13., np.nan, 12., 12.8], 'outflow_m3s': [100., np.nan, 400., 500.]}, index=dates)
    b = pd.DataFrame({'level_m': [12.9, 20., 11., 12.8], 'outflow_m3s': [200., 600., 700., 800.]}, index=dates)
    result = scorecard({'Observed': a, 'Optimized': b})
    assert (result.valid_level_days == 3).all()
    assert result.loc['Observed', 'flood_days'] == 1
    assert result.loc['Optimized', 'flood_days'] == 1
    assert result.loc['Observed', 'severity_m_days'] == pytest.approx(.2)
    assert result.loc['Observed', 'mean_ramp_m3s_day'] == 100.


def test_empty_comparison_is_unavailable_not_zero():
    empty = pd.DataFrame({'level_m': [], 'outflow_m3s': []}, index=pd.DatetimeIndex([]))
    result = scorecard({'Observed': empty, 'Optimized': empty})
    assert result.flood_days.isna().all()
    assert result.severity_m_days.isna().all()


def test_project_comparison_matches_daily_sources():
    scenarios = load_scenarios()
    result = scorecard(scenarios)
    assert result.loc['Observed', 'valid_level_days'] == 7420
    assert result.loc['Observed', 'valid_flow_days'] == 7360
    assert result.loc['Observed', 'flood_days'] == 452
    assert result.loc['Observed', 'severity_m_days'] == pytest.approx(162.74)
    assert result.loc['Optimized', 'flood_days'] == 0
    assert result.loc['Agreed Curve', 'low_days'] > result.loc['Optimized', 'low_days']
    year = slice_scenarios(scenarios, '2020-01-01', '2020-12-31')
    assert len(year['Observed']) == 366
    scores = scorecard(year, 12.15)
    assert scores.loc['Observed', 'flood_days'] == int((year['Observed'].level_m > 12.15).sum())


def test_export_tracks_filters_and_contains_all_scenarios():
    from dashboard.app import Observatory
    app = Observatory()
    app.period.value = '2020'
    app.threshold.value = 12.15
    app.visible.value = ['Observed']
    with zipfile.ZipFile(app.export_comparison()) as archive:
        daily = pd.read_csv(BytesIO(archive.read('daily.csv')))
        metadata = json.loads(archive.read('sources-and-settings.json'))
        scores = pd.read_csv(BytesIO(archive.read('scorecard.csv')))
    assert len(daily) == 366 * 3
    assert daily.date.min() == '2020-01-01'
    assert daily.date.max() == '2020-12-31'
    assert metadata['threshold_m'] == 12.15
    assert scores.shape[0] == 3
    app.reset_view()
    assert len(app.scoped()['Observed']) == 7422

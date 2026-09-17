"""Run with: python -m panel serve dashboard/app.py --address 127.0.0.1 --port 5006"""
from __future__ import annotations
import asyncio
from html import escape
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import panel as pn
from dashboard.charts import COLORS, annual_chart, flow_chart, level_chart, pareto_chart, rule_chart
from src.observatory import SCENARIOS, SOURCE_FILES, fingerprint, load_pareto, load_scenarios, run_experiment, scorecard, slice_scenarios

pn.extension(sizing_mode="stretch_width")
CSS = (ROOT / "dashboard/style.css").read_text(encoding="utf-8")
WIDGET_CSS = """
:host{font-family:'Segoe UI',Arial,sans-serif;color:#284e40;font-size:12px}
label,.bk-input-group label{font-size:11px!important;font-weight:500;color:#657b69;margin-bottom:8px}
select,input.bk-input{border:1px solid #dae2d2!important;background:#fafbf7!important;border-radius:7px!important;color:#315443!important;min-height:36px;font-size:12px!important;padding:6px 10px!important}
.bk-btn{border-radius:7px!important;font-size:12px!important;min-height:37px;border-color:#d8e1cf!important;background:#fff!important;color:#315b44!important;box-shadow:none!important}
.bk-btn.bk-btn-primary{background:#1a6452!important;color:#f4f8df!important;border-color:#1a6452!important}
.bk-btn:hover{background:#edf3e3!important;color:#163f38!important}
.bk-btn:focus-visible,select:focus-visible{outline:2px solid #8fac50!important;outline-offset:2px}
.noUi-connect{background:#698d59!important}.noUi-target{background:#e3e9d9!important;border:0!important;box-shadow:none!important}.noUi-handle{border:2px solid #698d59!important;box-shadow:none!important}
"""
NAV_CSS = """
:host{width:100%;font-family:'Segoe UI',Arial,sans-serif}
.bk-btn{background:transparent!important;color:#b3c8bb!important;text-align:left!important;justify-content:flex-start!important;border:0!important;border-radius:8px!important;padding:14px 16px!important;font-size:12px!important;font-weight:450!important;box-shadow:none!important;width:100%;height:45px}
.bk-btn.bk-btn-primary{background:#d6ee8a!important;color:#21482f!important;font-weight:600!important}
.bk-btn:hover{background:#2b5145!important;color:#e1edbb!important}
.bk-btn:focus-visible{outline:2px solid #d6ee8a!important;outline-offset:2px}
"""


def html(text, **kwargs):
    return pn.pane.HTML(text, stylesheets=[CSS], margin=0, **kwargs)


def heading(title, subtitle, eyebrow="POLICY OBSERVATORY", tag=""):
    return html(f'<div class="page-heading"><div><div class="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>' + (f'<span class="edition">{tag}</span>' if tag else '') + '</div>')


def section(title, note="", tag=""):
    return html(f'<div class="section-heading"><div><h2>{title}</h2><p>{note}</p></div><span class="small-label">{tag}</span></div>')


def card(*objects, **kwargs):
    styles = {"background": "white", "border": "1px solid #e4e9e0", "border-radius": "12px", "padding": "22px", "min-width": "0"}
    styles.update(kwargs.pop("styles", {}))
    return pn.Column(*objects, margin=0, styles=styles, **kwargs)


def grid(*objects):
    return pn.FlexBox(*objects, flex_wrap="wrap", gap="18px", margin=0, sizing_mode="stretch_width", align_items="stretch")


def widget(cls, **kwargs):
    if kwargs.get("sizing_mode") == "fixed" and "height" not in kwargs:
        kwargs["height"] = 65 if issubclass(cls, (pn.widgets.Select, pn.widgets.FloatSlider, pn.widgets.IntSlider)) else 40
    return cls(stylesheets=[WIDGET_CSS], margin=(0, 0, 8, 0), **kwargs)


def table(df):
    return html('<div class="table-wrap">' + df.to_html(index=False, classes="data-table", border=0, escape=True, na_rep="Unavailable") + '</div>')


def legend(names):
    return html('<div class="legend">' + ''.join(f'<span><i style="background:{COLORS[n]}"></i>{n}</span>' for n in names) + '</div>')


def number(value, fmt=",.0f"):
    return format(value, fmt) if pd.notna(value) and np.isfinite(value) else "—"


def kpis(items):
    return html('<div class="kpi-grid">' + ''.join(
        f'<div class="kpi"><div class="kpi-label">{label}<span class="kpi-icon">{icon}</span></div><div class="kpi-value">{value}<small>{unit}</small></div><div class="kpi-note">{note}</div></div>'
        for label, value, unit, note, icon in items) + '</div>')


class Observatory:
    def __init__(self):
        self.scenarios = load_scenarios()
        self.meta = fingerprint()
        self.pareto = load_pareto()
        self.run_meta = None
        self.page = "Scenario Comparison"
        self.main = pn.Column(margin=0, styles={"gap": "20px"})
        self.period = widget(pn.widgets.Select, name="Study window", options={
            "Full record · 2001–2021": "all", "Recent years · 2018–2021": "recent",
            "Flood year · 2020": "2020", "Dry period · 2004–2007": "dry"}, value="all", width=230, sizing_mode="fixed")
        self.threshold = widget(pn.widgets.Select, name="Flood reference · gauge m", options=[11.15, 12.15, 12.5, 12.8, 13.0], value=12.8, width=180, sizing_mode="fixed")
        self.visible = widget(pn.widgets.CheckBoxGroup, name="Visible lake-level series", options=list(SCENARIOS), value=list(SCENARIOS), inline=True)
        self.reset = widget(pn.widgets.Button, name="Reset view", width=110, sizing_mode="fixed")
        self.reset.on_click(self.reset_view)
        self.download = widget(pn.widgets.FileDownload, label="Export comparison ↓", callback=self.export_comparison,
                               filename="lake-victoria-comparison.zip", button_type="primary", width=185, sizing_mode="fixed")
        self.comparison_body = pn.Column(margin=0, styles={"gap": "18px"})
        self.period.param.watch(self.update_comparison, "value")
        self.threshold.param.watch(self.update_comparison, "value")
        self.visible.param.watch(self.update_comparison, "value")
        self.nav = []
        for title, icon in [("Scenario Comparison", "◫"), ("Policy Trade-offs", "⋈"), ("Flood Maps", "◈"), ("Sources & Methods", "≡")]:
            button = pn.widgets.Button(name=f"{icon}   {title}", button_type="primary" if title == self.page else "default",
                                       stylesheets=[NAV_CSS], height=45, margin=(0, 0, 5, 0))
            button.on_click(lambda e, title=title: self.navigate(title))
            self.nav.append((title, button))
        self.navigation = pn.Column(*(button for _, button in self.nav), margin=0)
        self.update_comparison()
        self.navigate(self.page)

    def scoped(self):
        bounds = {"all": ("2001-01-01", "2021-04-27"), "recent": ("2018-01-01", "2021-04-27"),
                  "2020": ("2020-01-01", "2020-12-31"), "dry": ("2004-01-01", "2007-12-31")}
        start, end = bounds[self.period.value]
        return slice_scenarios(self.scenarios, start, end)

    def reset_view(self, event=None):
        self.period.value = "all"
        self.threshold.value = 12.8
        self.visible.value = list(self.scenarios)

    def export_comparison(self):
        frames = self.scoped()
        scores = scorecard(frames, self.threshold.value)
        metadata = {**self.meta, "threshold_m": self.threshold.value, "period_preset": self.period.value,
                    "export_scope": "All compared scenarios, regardless of lake-level chart visibility", "exploratory_run": self.run_meta}
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("scorecard.csv", scores.to_csv())
            archive.writestr("daily.csv", pd.concat(frames, names=["scenario", "date"]).to_csv())
            archive.writestr("sources-and-settings.json", json.dumps(metadata, indent=2))
        output.seek(0)
        return output

    def update_comparison(self, event=None):
        frames = self.scoped()
        scores = scorecard(frames, self.threshold.value)
        obs, opt = scores.loc["Observed"], scores.loc["Optimized"]
        avoided = obs.flood_days - opt.flood_days
        pct = 100 * (obs.severity_m_days - opt.severity_m_days) / obs.severity_m_days if obs.severity_m_days > 0 else np.nan
        peak_delta = obs.peak_level_m - opt.peak_level_m
        count = len(frames["Observed"])
        interval = f'{frames["Observed"].index.min():%d %b %Y} – {frames["Observed"].index.max():%d %b %Y}'
        if pd.notna(pct):
            hero_value, hero_label = f'{abs(pct):.0f}%', 'less flood severity' if pct >= 0 else 'more flood severity'
        else:
            hero_value, hero_label = '—', 'No observed exceedance<br>at this threshold'
        hero = html(f'<div class="hero"><div class="hero-copy"><div class="eyebrow">OBSERVED ↔ OPTIMIZED · {self.threshold.value:.2f} M REFERENCE</div><h2>A different release.<br>A different lake.</h2><p>Explore how the saved policy changes lake levels,<br>flood exposure, and the rhythm of daily releases.</p></div><div class="hero-stat"><strong>{hero_value}</strong><span>{hero_label}<br>in the selected period</span><small>SUM OF DAILY EXCEEDANCE · M-DAYS</small></div></div>')
        metrics = kpis([
            ("Optimized peak level", number(opt.peak_level_m, ".2f"), "m", f'Observed {obs.peak_level_m:.2f} m · <em>{peak_delta:.2f} m lower</em>' if peak_delta >= 0 else f'Observed {obs.peak_level_m:.2f} m · {abs(peak_delta):.2f} m higher', '↗'),
            ("Optimized flood days", number(opt.flood_days), "days", f'Observed {number(obs.flood_days)} · <em>{number(avoided)} fewer</em>' if avoided >= 0 else f'Observed {number(obs.flood_days)} · {number(-avoided)} more', '≋'),
            ("Optimized mean release", number(opt.mean_outflow_m3s), "m³/s", f'Observed {number(obs.mean_outflow_m3s)} m³/s', '↗'),
            ("Optimized low-water days", number(opt.low_days), "days", f'Below 11.15 m · observed {number(obs.low_days)}', '↘'),
        ])
        level = card(section("The lake through time", "Daily levels · shaded area is the 11.15–12.15 m operating band", "01 / LEVELS"),
                     self.visible, pn.pane.Bokeh(level_chart(frames, self.threshold.value, self.visible.value), sizing_mode="stretch_width"),
                     html(f'<div class="note">Dashed horizontal line: {self.threshold.value:.2f} m flood reference. Series toggles affect this chart only.</div>'))
        releases = card(section("The rhythm of releases", "Monthly means on common valid outflow dates", "02 / OUTFLOW"),
                        legend(frames), pn.pane.Bokeh(flow_chart(frames)), styles={"flex": "1 1 440px", "background": "white", "border": "1px solid #e4e9e0", "border-radius": "12px", "padding": "22px", "min-width": "0"})
        flood = card(section("Flood days, year by year", "Daily exceedances on common valid level dates", "03 / EXPOSURE"),
                     legend(frames), pn.pane.Bokeh(annual_chart(frames, self.threshold.value)), styles={"flex": "1 1 440px", "background": "white", "border": "1px solid #e4e9e0", "border-radius": "12px", "padding": "22px", "min-width": "0"})
        display = scores.reset_index()[["scenario", "peak_level_m", "flood_days", "severity_m_days", "low_days", "mean_outflow_m3s", "mean_ramp_m3s_day"]]
        display.columns = ["Scenario", "Peak · m", "Flood days", "Severity · m-days", "Low-water days", "Mean release · m³/s", "Mean daily ramp · m³/s/day"]
        display = display.map(lambda v: number(v, ",.2f") if isinstance(v, (float, np.floating)) else v)
        coverage = f'{interval} · {count:,} calendar days. Comparisons use {int(obs.valid_level_days):,} shared level dates and {int(obs.valid_flow_days):,} shared outflow dates. Missing observations are excluded, never filled. 2021 ends on 27 April.'
        self.comparison_body.objects = [hero, metrics, level, grid(releases, flood),
            section("The full trade-off", "Flood severity is the sum of daily metres above the selected threshold. Low-water days are below 11.15 m."), table(display),
            html(f'<div class="note">{coverage}</div>'), self.experiment_panel()]

    def experiment_panel(self):
        release = widget(pn.widgets.FloatSlider, name="Release multiplier", start=.8, end=1.2, step=.01, value=1, width=215, sizing_mode="fixed")
        inflow = widget(pn.widgets.FloatSlider, name="Tributary inflow multiplier", start=.8, end=1.2, step=.01, value=1, width=215, sizing_mode="fixed")
        rainfall = widget(pn.widgets.FloatSlider, name="Rainfall multiplier", start=.8, end=1.2, step=.01, value=1, width=215, sizing_mode="fixed")
        ramp = widget(pn.widgets.IntSlider, name="Daily ramp limit · m³/s/day", start=25, end=200, step=25, value=200, width=215, sizing_mode="fixed")
        run = widget(pn.widgets.Button, name="Run exploratory scenario ↗", button_type="primary", width=240, sizing_mode="fixed")
        clear = widget(pn.widgets.Button, name="Remove exploratory overlay", width=220, sizing_mode="fixed", disabled="Exploratory" not in self.scenarios)
        status = html('<div class="note">A new run uses daily state feedback and the calibrated storage model. Results are exploratory and differ from the historical two-pass optimization.</div>')
        if self.run_meta:
            cfg = self.run_meta["forcing_multipliers"]
            status.object = f'<div class="notice">Displayed run: <span class="mono">{self.run_meta["run_id"]}</span><br>Release ×{self.run_meta["policy"]["release_multiplier"]:.2f} · inflow ×{cfg["inflow"]:.2f} · rainfall ×{cfg["rainfall"]:.2f}. Run settings and daily outputs saved locally.</div>'
        async def execute(event):
            run.disabled, run.loading = True, True
            status.object = '<div class="notice">Simulating the full daily record…</div>'
            try:
                result, metadata = await asyncio.to_thread(run_experiment, release_multiplier=release.value,
                    inflow_multiplier=inflow.value, rain_multiplier=rainfall.value, ramp_limit=ramp.value)
                self.scenarios["Exploratory"] = result[["level_m", "outflow_m3s"]]
                self.run_meta = metadata
                self.visible.options = list(self.scenarios)
                self.visible.value = list(self.scenarios)
                self.update_comparison()
            except Exception as exc:
                status.object = f'<div class="notice warning">The run could not finish: {escape(str(exc))}</div>'
            finally:
                run.disabled, run.loading = False, False
        def remove(event):
            self.scenarios.pop("Exploratory", None)
            self.run_meta = None
            self.visible.value = list(SCENARIOS)
            self.visible.options = list(SCENARIOS)
            self.update_comparison()
        run.on_click(execute)
        clear.on_click(remove)
        return card(section("Make room for a different scenario", "Adjust one assumption, then compare the resulting full-record simulation.", "SCENARIO LAB"),
                    grid(release, inflow, rainfall, ramp), grid(run, clear), status)

    def comparison_page(self):
        return [heading("A better balance for the lake.", "Compare historical operations, the Agreed Curve, and the saved optimized policy.", tag="<b>3</b> historical scenarios"),
                grid(self.period, self.threshold, self.reset, self.download), self.comparison_body]

    def policies_page(self):
        data = self.pareto
        selected = widget(pn.widgets.Select, name="Inspect a candidate", options={f'Policy {i + 1:03d}': int(i) for i in data.candidate_index}, value=68, width=220, sizing_mode="fixed")
        detail = pn.Column(margin=0, styles={"gap": "15px"})
        def show(event=None):
            row = data.loc[data.candidate_index == selected.value].iloc[0]
            feasible = row.g_high_level <= 0 and row.g_low_level <= 0
            detail.objects = [section(f'Policy {selected.value + 1:03d}', 'Base release knots before safeguards and ramp limits'),
                html(f'<span class="pill {"" if feasible else "amber"}">{"Within exported guardrails" if feasible else "Guardrail violation in export"}</span>'),
                pn.pane.Bokeh(rule_chart(row)),
                table(pd.DataFrame({"Objective": ["Level-band penalty", "Seasonality penalty", "Smoothness penalty"], "Score": [f'{row.F_level_band:.2f}', f'{row.F_seasonality:.2f}', f'{row.F_smooth:.2f}']})),
                html(f'<div class="note">High-water buffer: {row.high_water_buffer_m:.2f} m<br>Low-water buffer: {row.low_water_buffer_m:.2f} m<br>Dry protective minimum: {row.dry_protective_q_min_m3s:,.0f} m³/s</div>')]
        def tap(attr, old, new):
            if new:
                selected.value = int(data.iloc[new[0]].candidate_index)
        plot, source = pareto_chart(data, tap)
        def choose(event):
            source.selected.indices = [int(event.new)]
            show()
        selected.param.watch(choose, "value")
        show()
        source.selected.indices = [68]
        download = widget(pn.widgets.FileDownload, label="Export candidate pool ↓", callback=lambda: BytesIO(data.to_csv(index=False).encode()), filename="policy-candidates.csv", width=205, sizing_mode="fixed")
        left = card(section("Every point is a possible policy", "Select a point to inspect its release curve. Both axes favour the lower left.", "120 CANDIDATES"),
                    pn.pane.Bokeh(plot), html('<div class="note">These are weighted objective scores from notebook 06, not flood days or energy units. The third objective, smoothness, appears in the candidate detail.</div>'),
                    styles={"flex": "2 1 520px", "background": "white", "padding": "22px", "border": "1px solid #e4e9e0", "border-radius": "12px", "min-width": "0"})
        right = card(detail, styles={"flex": "1 1 290px", "background": "white", "padding": "22px", "border": "1px solid #e4e9e0", "border-radius": "12px", "min-width": "0"})
        return [heading("Good policy is a balancing act.", "Explore the saved optimization pool and the compromises behind each release rule.", eyebrow="POLICY TRADE-OFFS", tag="NSGA-II · <b>120</b> candidates"),
            grid(selected, download), grid(left, right),
            html('<div class="notice warning">The candidate export and the saved optimized daily series do not share a verified run ID. Selecting a candidate inspects its exported scores and parameters; it does not replace the scenario comparison.</div>'),
            section("Reading the objectives", "Three goals were evaluated together in the original optimization."),
            table(pd.DataFrame({"Objective": ["Level band", "Seasonality", "Smoothness"], "Meaning": ["Weighted frequency and magnitude outside the 11.15–12.15 m target band", "Deviation from monthly release targets, with operating-band penalties", "Squared daily changes in release, with excess-ramping penalties"], "Direction": ["Lower is better"] * 3}))]

    def maps_page(self):
        edition = widget(pn.widgets.Select, name="Published map set", options=["Notebook 09", "Project-aligned comparison"], width=260, sizing_mode="fixed")
        body = pn.Column(margin=0, styles={"gap": "18px"})
        def update(event=None):
            if edition.value == "Notebook 09":
                path = ROOT / "outputs/figures/09_peak_flood_maps_observed_vs_optimized_true_metrics.png"
                rel = "outputs/tables/09_flood_extent_summary.csv"
                df = pd.read_csv(ROOT / rel)
                df = df[df.case.eq("peak_year_level") & df.scenario.isin(["Observed", "Optimized"])]
                values = df.set_index("scenario")
                obs, opt = values.loc["Observed", "net_flooded_area_km2"], values.loc["Optimized", "net_flooded_area_km2"]
            else:
                path = ROOT / "outputs/figures/Side_By_Side_Flood_Maps.png"
                rel = "outputs/tables/project_aligned_peak_net_flood_summary.csv"
                df = pd.read_csv(ROOT / rel)
                values = df.set_index("scenario")
                obs, opt = values.loc["Observed Historical Peak", "net_flooded_land_km2"], values.loc["Optimized Rule", "net_flooded_land_km2"]
            change = (obs - opt) / obs * 100
            body.objects = [kpis([
                ("Observed area proxy", number(obs, ",.1f"), "km²", "2020 peak · supplied map summary", "◈"),
                ("Optimized area proxy", number(opt, ",.1f"), "km²", "2020 peak · supplied map summary", "◈"),
                ("Difference in area proxy", number(obs - opt, ",.1f"), "km²", f'{change:.1f}% lower in this map set', "↘"),
                ("Reference lake area", "68,800", "km²", "Subtracted from thresholded DEM area", "≋"),
            ]), card(section("Two policies. One shoreline.", f'Archived 2020 peak comparison · {edition.value}', "SPATIAL VIEW"),
                     pn.pane.PNG(str(path), sizing_mode="stretch_width", alt_text="Observed and optimized flood extent comparison for the peak flood year 2020"),
                     widget(pn.widgets.FileDownload, label="Download original map ↓", file=str(path), filename=path.name, width=220, sizing_mode="fixed")),
                html('<div class="notice">Area proxy = max(total DEM area below the water level − 68,800 km², 0). This is an elevation-screening estimate; it does not establish connected inundation, flood depth, or people affected. The archived map does not change with scenario controls.</div>'),
                section("Keep the map and its evidence together", "The two supplied map sets report different areas. Each view uses its own matching table; the estimates are not combined."),
                table(df.round(3)), html(f'<div class="note">Source: <span class="mono">{rel}</span><br>Raster regeneration is not available in this installation; these are original project exports.</div>')]
        edition.param.watch(update, "value")
        update()
        return [heading("See the shoreline differently.", "Compare the project’s archived flood-extent maps and inspect the assumptions behind the area estimates.", eyebrow="FLOOD MAPS", tag="<b>2020</b> · peak flood year"), edition, body]

    def sources_page(self):
        sources = pd.DataFrame(self.meta["sources"])
        sources["sha256"] = sources.sha256.str.slice(0, 16) + "…"
        sources.columns = ["Dataset", "Project file", "SHA-256 prefix", "Bytes"]
        download = widget(pn.widgets.FileDownload, label="Download source manifest ↓", callback=lambda: BytesIO(json.dumps(self.meta, indent=2).encode()), filename="lake-victoria-sources.json", width=235, sizing_mode="fixed")
        return [heading("Every result has a source.", "Inspect the data, calculation rules, and boundaries of this research workspace.", eyebrow="SOURCES & METHODS", tag=f'Snapshot · <b>{self.meta["snapshot_id"]}</b>'),
                download, table(sources),
                html('<div class="source-summary"><h3>Comparable daily measurements</h3><p>Historical observations come from the audited daily core file. Optimized and Agreed Curve series come from their saved daily simulation files. All series share the 1 January 2001–27 April 2021 calendar. Level comparisons exclude the two missing observed levels; outflow comparisons exclude the 62 missing observed outflows. Filters recalculate these counts within the selected window. Daily ramps never bridge a missing observation.</p><h3>Units and references</h3><p>Lake levels use the Jinja gauge datum. Add 1,122.85 m to convert to metres above sea level. The target operating band is 11.15–12.15 m. The flood reference is independently selectable. Exceedance uses strictly greater than the threshold; low-water days use strictly less than 11.15 m. Flood severity sums daily exceedance in m-days. Monthly outflows average available common daily observations; they are not energy estimates.</p><h3>Historical results versus exploratory runs</h3><p>Saved candidate objectives and historical daily exports are separate evidence sets. Legacy files lack a common run identifier. New simulations use beginning-of-day model state to determine release, preserve daily storage balance, apply release/ramping constraints, and use the notebook’s fixed 30-day groundwater convention. They do not reproduce or revalidate the legacy two-pass optimizer. Default release knots are a documented rounded reference rule, not a newly optimized policy.</p><h3>Reproducible experiments</h3><p>Each successful scenario creates an immutable run folder with daily Parquet output and JSON metadata containing the source hashes, engine hash, calibration, release settings, forcing multipliers, and initial level. Scenarios are sensitivity experiments, not forecasts or calibrated probability intervals.</p><h3>What is available now</h3><p>Daily scenario comparison, policy inspection, archived flood maps, and the causal scenario runner are available. Live forecasts, new Pareto optimization, downstream routing, hydropower energy production, and population exposure modelling remain future extensions.</p></div>')]

    def navigate(self, page):
        self.page = page
        for name, button in self.nav:
            button.button_type = "primary" if name == page else "default"
        pages = {"Scenario Comparison": self.comparison_page, "Policy Trade-offs": self.policies_page,
                 "Flood Maps": self.maps_page, "Sources & Methods": self.sources_page}
        self.main.objects = pages[page]()

    def template(self):
        template = pn.Template((ROOT / "dashboard/template.html").read_text(encoding="utf-8"))
        template.add_variable("app_css", CSS)
        template.add_panel("navigation", self.navigation)
        template.add_panel("main", self.main)
        return template


def create_app():
    return Observatory().template()


if __name__.startswith("bokeh") or __name__ == "__main__":
    create_app().servable(title="Lake Victoria · Policy Observatory")

"""Bokeh plots sharing the observatory's palette, units and evidence scope."""
import numpy as np
import pandas as pd
from bokeh.models import BoxAnnotation, ColumnDataSource, DatetimeTicker, HoverTool, NumeralTickFormatter, Span
from bokeh.plotting import figure
from bokeh.transform import dodge
from src.observatory import common_metric_frames

COLORS = {"Observed": "#789687", "Optimized": "#127364", "Agreed Curve": "#cbaa68", "Exploratory": "#8873b2"}
DASHES = {"Observed": "solid", "Optimized": "solid", "Agreed Curve": "dashed", "Exploratory": "dotdash"}


def style(plot):
    plot.background_fill_color = "#ffffff"
    plot.border_fill_color = "#ffffff"
    plot.outline_line_color = None
    plot.grid.grid_line_color = "#eaf0e7"
    plot.grid.grid_line_dash = [3, 5]
    plot.axis.axis_line_color = None
    plot.axis.major_tick_line_color = None
    plot.axis.minor_tick_line_color = None
    plot.axis.major_label_text_color = "#829083"
    plot.axis.major_label_text_font_size = "10px"
    plot.axis.axis_label_text_color = "#6d8173"
    plot.axis.axis_label_text_font_size = "10px"
    plot.axis.axis_label_text_font_style = "normal"
    plot.toolbar.logo = None
    plot.toolbar.autohide = True
    plot.min_border_left = 45
    plot.min_border_right = 18
    plot.min_border_top = 12
    plot.min_border_bottom = 28
    return plot


def level_chart(scenarios, threshold, shown=None):
    plot = style(figure(height=310, sizing_mode="stretch_width", x_axis_type="datetime",
                        tools="pan,xwheel_zoom,box_zoom,reset,save", active_scroll=None))
    plot.yaxis.axis_label = "Lake level · m, Jinja gauge"
    plot.xaxis.ticker = DatetimeTicker(desired_num_ticks=4)
    plot.add_layout(BoxAnnotation(bottom=11.15, top=12.15, fill_color="#b9d990", fill_alpha=.12, line_alpha=0, level="underlay"))
    plot.add_layout(Span(location=threshold, dimension="width", line_color="#c3a665", line_dash=[6, 5], line_width=1))
    for name, df in scenarios.items():
        if shown is not None and name not in shown:
            continue
        source = ColumnDataSource(dict(date=df.index, level=df.level_m))
        renderer = plot.line("date", "level", source=source, color=COLORS[name],
                             line_width=2.5 if name == "Optimized" else 1.6,
                             line_dash=DASHES[name], alpha=.95)
        plot.add_tools(HoverTool(renderers=[renderer], tooltips=[("Scenario", name), ("Date", "@date{%d %b %Y}"), ("Lake level", "@level{0.00} m")], formatters={"@date": "datetime"}, mode="vline"))
    return plot


def flow_chart(scenarios):
    flows = common_metric_frames(scenarios, "outflow_m3s")
    plot = style(figure(height=235, sizing_mode="stretch_width", x_axis_type="datetime", tools="pan,xwheel_zoom,reset,save"))
    plot.yaxis.axis_label = "Monthly mean release · m³/s"
    plot.xaxis.ticker = DatetimeTicker(desired_num_ticks=4)
    plot.yaxis.formatter = NumeralTickFormatter(format="0,0")
    monthly = flows.resample("MS").mean()
    for name in monthly:
        r = plot.line(monthly.index, monthly[name], color=COLORS[name], line_width=2, line_dash=DASHES[name])
        plot.add_tools(HoverTool(renderers=[r], tooltips=[("Scenario", name), ("Month", "$x{%b %Y}"), ("Release", "$y{0,0} m³/s")], formatters={"$x": "datetime"}, mode="vline"))
    return plot


def annual_chart(scenarios, threshold):
    levels = common_metric_frames(scenarios, "level_m")
    counts = levels.gt(threshold).resample("YS").sum()
    years = [str(x.year) for x in counts.index]
    plot = style(figure(height=235, sizing_mode="stretch_width", x_range=years, tools="hover,save", tooltips=[("Year", "@year"), ("Exceedance days", "$y{0}")]))
    plot.y_range.start = 0
    plot.yaxis.axis_label = f"Days above {threshold:.2f} m"
    names = list(counts.columns)
    source = ColumnDataSource(dict(year=years, **{name: counts[name].values for name in names}))
    width = .8 / max(len(names), 1)
    for i, name in enumerate(names):
        plot.vbar(x=dodge("year", -.4 + width * (i + .5), range=plot.x_range), top=name,
                  width=width * .85, source=source, color=COLORS[name], line_color=None)
    if len(years) > 10:
        plot.xaxis.major_label_orientation = .8
    return plot


def pareto_chart(data, on_select):
    source = ColumnDataSource(data)
    plot = style(figure(height=380, sizing_mode="stretch_width", tools="tap,pan,wheel_zoom,box_zoom,reset,save"))
    plot.xaxis.axis_label = "Level-band penalty · lower is better"
    plot.yaxis.axis_label = "Seasonality penalty · lower is better"
    r = plot.scatter("F_level_band", "F_seasonality", source=source, size=10,
                     color="#539480", alpha=.75, line_color="white", line_width=1,
                     selection_color="#173e35", selection_alpha=1,
                     nonselection_alpha=.22)
    plot.add_tools(HoverTool(renderers=[r], tooltips=[("Candidate", "@candidate_index"), ("Level-band penalty", "@F_level_band{0.00}"), ("Seasonality penalty", "@F_seasonality{0.00}"), ("Smoothness penalty", "@F_smooth{0.00}")]))
    source.selected.on_change("indices", on_select)
    return plot, source


def rule_chart(row):
    plot = style(figure(height=220, sizing_mode="stretch_width", tools="hover,save", tooltips=[("Level", "$x{0.00} m"), ("Base release", "$y{0,0} m³/s")]))
    levels = [11.15, 11.50, 11.85, 12.15]
    for season, color in [("dry", "#b8c56d"), ("wet", "#176f61")]:
        q = [row[f"Q_{season}_knot_{i}"] for i in range(1, 5)]
        plot.line(levels, q, line_width=2, color=color, legend_label=season.title() + " season")
        plot.scatter(levels, q, size=7, color=color)
    plot.xaxis.axis_label = "Lake level · m, Jinja gauge"
    plot.yaxis.axis_label = "Base release · m³/s"
    plot.legend.location = "top_left"
    plot.legend.label_text_font_size = "10px"
    plot.legend.border_line_color = None
    plot.legend.background_fill_alpha = .8
    return plot

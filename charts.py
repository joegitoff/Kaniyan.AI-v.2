"""
charts.py - Plotly figures used by the dashboard.

Honesty rules: missing values are shown as GAPS (never interpolated or zero-filled), units are in the
axis titles and hover text, bar charts start at zero, and every chart still renders (with a short
"no data" message) when its data are empty or incomplete. Dashed lines show configured thresholds so
users can see WHY an alert fires.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config

LEVEL_COLORS = {-1: "#cfd8dc", 0: "#e8f5e9", 1: "#90caf9", 2: "#ffb74d", 3: "#e53935"}
LEVEL_SYMBOL = {-1: "?", 0: "-", 1: "i", 2: "C", 3: "H"}
LEVEL_NAME = {-1: "No data", 0: "No alert", 1: "Information", 2: "Caution", 3: "High concern"}


def _style(fig: go.Figure, title: str, y_title: str, height: int = 320) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=15)), yaxis_title=y_title, height=height, autosize=True,
                      margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.2),
                      hovermode="x unified")
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def empty_figure(title: str, message: str = "No data available") -> go.Figure:
    """Placeholder that keeps the page layout stable when there is nothing to plot."""
    fig = go.Figure()
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=14))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(title=dict(text=title, font=dict(size=15)), height=200, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def _has(df, *columns) -> bool:
    return df is not None and not df.empty and any(c in df.columns and df[c].notna().any() for c in columns)


# ------------------------------------------------------------- daily (7-day) ---
def temperature_chart(daily: pd.DataFrame, caution_c: float) -> go.Figure:
    if not _has(daily, "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max"):
        return empty_figure("Daily temperature forecast", "Temperature forecast unavailable")
    fig = go.Figure()
    for column, name, mode, extra in (("temperature_2m_max", "Max temp", "lines+markers", {}),
                                      ("temperature_2m_min", "Min temp", "lines+markers", {}),
                                      ("apparent_temperature_max", "Max feels-like", "lines", {"line": dict(dash="dot")})):
        if column in daily:
            fig.add_trace(go.Scatter(x=daily["date"], y=daily[column], name=name, mode=mode,
                                     hovertemplate="%{y:.1f} °C", connectgaps=False, **extra))
    fig.add_hline(y=caution_c, line_dash="dash", line_color="orange",
                  annotation_text=f"Caution rule: {caution_c:g} °C", annotation_position="top left")
    return _style(fig, "Daily temperature forecast", "Temperature (°C)")


def rainfall_chart(daily: pd.DataFrame, caution_mm: float) -> go.Figure:
    if not _has(daily, "precipitation_sum"):
        return empty_figure("Daily rainfall forecast", "Rainfall forecast unavailable")
    fig = go.Figure(go.Bar(x=daily["date"], y=daily["precipitation_sum"], name="Rain (mm)",
                           hovertemplate="%{y:.1f} mm"))
    fig.add_hline(y=caution_mm, line_dash="dash", line_color="orange",
                  annotation_text=f"Caution rule: {caution_mm:g} mm/day", annotation_position="top left")
    fig = _style(fig, "Daily rainfall forecast (model estimate, not a flood prediction)", "Rain (mm per day)")
    fig.update_yaxes(rangemode="tozero")
    return fig


def wind_chart(daily: pd.DataFrame, caution_kmh: float) -> go.Figure:
    if not _has(daily, "wind_speed_10m_max", "wind_gusts_10m_max"):
        return empty_figure("Daily wind forecast", "Wind forecast unavailable")
    fig = go.Figure()
    if "wind_speed_10m_max" in daily:
        fig.add_trace(go.Bar(x=daily["date"], y=daily["wind_speed_10m_max"], name="Max wind", hovertemplate="%{y:.0f} km/h"))
    if "wind_gusts_10m_max" in daily:
        fig.add_trace(go.Scatter(x=daily["date"], y=daily["wind_gusts_10m_max"], name="Max gust", mode="lines+markers",
                                 hovertemplate="%{y:.0f} km/h"))
    fig.add_hline(y=caution_kmh, line_dash="dash", line_color="orange",
                  annotation_text=f"Caution rule (gust): {caution_kmh:g} km/h", annotation_position="top left")
    fig = _style(fig, "Daily wind forecast", "Wind speed (km/h)")
    fig.update_yaxes(rangemode="tozero")
    return fig


def aqi_chart(hourly: pd.DataFrame, info: float, caution: float, high: float, title_suffix: str = "") -> go.Figure:
    title = "Hourly air-quality index forecast (US AQI scale, CAMS model)" + title_suffix
    if not _has(hourly, "us_aqi"):
        return empty_figure(title, "Hourly US AQI forecast unavailable")
    fig = go.Figure(go.Scatter(x=hourly["time"], y=hourly["us_aqi"], name="US AQI (model)", mode="lines",
                               connectgaps=False, hovertemplate="%{y:.0f} US AQI"))
    for value, label, colour in ((info, "Info", "gold"), (caution, "Caution", "orange"), (high, "High concern", "red")):
        fig.add_hline(y=value, line_dash="dash", line_color=colour, annotation_text=f"{label}: {value:g}",
                      annotation_position="top left")
    fig = _style(fig, title, "US AQI (not CPCB)")
    fig.update_yaxes(rangemode="tozero")
    return fig


def pm_chart(hourly: pd.DataFrame) -> go.Figure:
    if not _has(hourly, "pm2_5", "pm10"):
        return empty_figure("Particulate matter concentrations", "PM2.5 / PM10 data unavailable")
    fig = go.Figure()
    for column, name in (("pm2_5", "PM2.5"), ("pm10", "PM10")):
        if column in hourly:
            fig.add_trace(go.Scatter(x=hourly["time"], y=hourly[column], name=name, mode="lines", connectgaps=False,
                                     hovertemplate="%{y:.1f} µg/m³"))
    fig = _style(fig, "Particulate matter concentrations (µg/m³, model)", "Concentration (µg/m³)")
    fig.update_yaxes(rangemode="tozero")
    return fig


# --------------------------------------------------------- next 24 hours ---
def hourly_temperature_chart(window, thresholds: dict) -> go.Figure:
    title = "Next 24 hours: temperature (forecast)"
    if window is None or not _has(window.frame, "temperature_2m", "apparent_temperature"):
        return empty_figure(title, "Hourly temperature forecast unavailable")
    f, fig = window.frame, go.Figure()
    fig.add_trace(go.Scatter(x=f["time"], y=f["temperature_2m"], name="Air temperature", mode="lines+markers",
                             connectgaps=False, hovertemplate="%{y:.1f} °C"))
    fig.add_trace(go.Scatter(x=f["time"], y=f["apparent_temperature"], name="Feels like", mode="lines",
                             line=dict(dash="dot"), connectgaps=False, hovertemplate="%{y:.1f} °C"))
    c = thresholds["temp_max_c"]["caution"]
    fig.add_hline(y=c, line_dash="dash", line_color="orange", annotation_text=f"Caution rule (air temp): {c:g} °C",
                  annotation_position="top left")
    fig = _style(fig, title, "Temperature (°C)")
    fig.update_xaxes(tickformat="%H:%M\n%a")
    return fig


def hourly_rain_chart(window) -> go.Figure:
    title = "Next 24 hours: rain probability and precipitation (forecast)"
    if window is None:
        return empty_figure(title, "Hourly rain forecast unavailable")
    f = window.frame
    has_p, has_mm = _has(f, "precipitation_probability"), _has(f, "precipitation")
    if not (has_p or has_mm):
        return empty_figure(title, "Hourly rain forecast unavailable")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.5, 0.5])
    if has_p:
        fig.add_trace(go.Scatter(x=f["time"], y=f["precipitation_probability"], name="Rain probability", mode="lines+markers",
                                 connectgaps=False, hovertemplate="%{y:.0f} %"), row=1, col=1)
        fig.add_hline(y=config.RAIN_PROB_NOTABLE_PERCENT, line_dash="dash", line_color="orange", row=1, col=1,
                      annotation_text=f"{config.RAIN_PROB_NOTABLE_PERCENT:g}% (app's 'high chance' level)", annotation_position="top left")
    else:
        fig.add_annotation(text="Rain probability unavailable", xref="x domain", yref="y domain", x=0.5, y=0.5, showarrow=False, row=1, col=1)
    if has_mm:
        fig.add_trace(go.Bar(x=f["time"], y=f["precipitation"], name="Precipitation", hovertemplate="%{y:.1f} mm"), row=2, col=1)
    else:
        fig.add_annotation(text="Precipitation amount unavailable", xref="x2 domain", yref="y2 domain", x=0.5, y=0.5, showarrow=False, row=2, col=1)
    fig.update_yaxes(title_text="Probability (%)", range=[0, 100], row=1, col=1)
    fig.update_yaxes(title_text="Precipitation (mm/h)", rangemode="tozero", row=2, col=1)
    fig.update_layout(title=dict(text=title, font=dict(size=15)), height=420, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.12), hovermode="x unified", autosize=True)
    fig.update_xaxes(tickformat="%H:%M\n%a")
    return fig


def hourly_wind_chart(window, thresholds: dict) -> go.Figure:
    title = "Next 24 hours: wind (forecast)"
    if window is None or not _has(window.frame, "wind_speed_10m", "wind_gusts_10m"):
        return empty_figure(title, "Hourly wind forecast unavailable")
    f, fig = window.frame, go.Figure()
    fig.add_trace(go.Scatter(x=f["time"], y=f["wind_speed_10m"], name="Wind speed", mode="lines", connectgaps=False,
                             hovertemplate="%{y:.0f} km/h"))
    fig.add_trace(go.Scatter(x=f["time"], y=f["wind_gusts_10m"], name="Gusts", mode="lines+markers", connectgaps=False,
                             hovertemplate="%{y:.0f} km/h"))
    c = thresholds["wind_gust_kmh"]["caution"]
    fig.add_hline(y=c, line_dash="dash", line_color="orange", annotation_text=f"Caution rule (gust): {c:g} km/h",
                  annotation_position="top left")
    fig = _style(fig, title, "Wind (km/h)")
    fig.update_yaxes(rangemode="tozero")
    fig.update_xaxes(tickformat="%H:%M\n%a")
    return fig


def risk_timeline_chart(window) -> go.Figure:
    """Rows = hazards, columns = hours. Colour AND a letter show the level (not colour alone)."""
    title = "Next 24 hours: when configured alert thresholds may be crossed (app-generated, forecast)"
    if window is None:
        return empty_figure(title, "No hourly data available")
    import timeline
    f = window.frame
    labels, z, text, hover = [], [], [], []
    for key, label, unit, column, _rule in timeline.HAZARDS:
        levels = f[f"level_{key}"].fillna(-1).astype(int)
        labels.append(label)
        z.append([int(v) + 1 for v in levels])                      # shift so -1..3 becomes 0..4
        text.append([LEVEL_SYMBOL[int(v)] for v in levels])
        hover.append([f"{label}<br>{t:%a %H:%M}<br>" + (f"{val:.1f} {unit}" if pd.notna(val) else "no value")
                      + f"<br>{LEVEL_NAME[int(v)]}" for t, val, v in zip(f["time"], f[column], levels)])
    colors = [LEVEL_COLORS[k] for k in (-1, 0, 1, 2, 3)]
    scale = []
    for i, colour in enumerate(colors):
        scale += [[i / 5, colour], [(i + 1) / 5, colour]]
    fig = go.Figure(go.Heatmap(x=f["time"], y=labels, z=z, zmin=-0.5, zmax=4.5, colorscale=scale, showscale=False,
                               text=text, texttemplate="%{text}", hovertext=hover, hoverinfo="text", xgap=2, ygap=2))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickformat="%H:%M\n%a")
    fig.update_layout(title=dict(text=title, font=dict(size=15)), height=320, autosize=True,
                      margin=dict(l=10, r=10, t=50, b=10))
    return fig

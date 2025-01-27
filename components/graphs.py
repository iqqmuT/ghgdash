from __future__ import annotations
from datetime import date
from dataclasses import dataclass
import pandas as pd
import plotly.graph_objs as go
from colour import Color

from utils import deepupdate
from utils.data import find_consecutive_start
from utils.colors import GHG_MAIN_SECTOR_COLORS


def make_layout(**kwargs):
    params = dict(
        margin=dict(
            t=30,
            r=15,
            l=60,
        ),
        yaxis=dict(
            rangemode='tozero',
            hoverformat='.3r',
            separatethousands=True,
            anchor='free',
            domain=[0.02, 1],
            tickfont=dict(
                family='HelsinkiGrotesk, Arial',
                size=14,
            ),
            gridwidth=1,
            gridcolor='#ccc',
            fixedrange=True,
        ),
        xaxis=dict(
            showgrid=False,
            showline=False,
            anchor='free',
            domain=[0.01, 1],
            tickfont=dict(
                family='HelsinkiGrotesk, Arial',
                size=14,
            ),
            gridwidth=1,
            gridcolor='#ccc',
            fixedrange=True
        ),
        font=dict(
            family='HelsinkiGrotesk, Open Sans, Arial'
        ),
        separators=', ',
        plot_bgcolor='#fff',
    )
    if 'legend' not in kwargs:
        params['showlegend'] = False

    deepupdate(params, kwargs)
    if 'title' in params:
        params['title'] = '<b>%s</b>' % params['title']

    # ret = go.Layout(**params)
    return params


@dataclass
class PredictionGraphSeries:
    graph: PredictionGraph
    df: pd.DataFrame
    trace_name: str = None
    column_name: str = None
    historical_color: str = None
    forecast_color: str = None
    luminance_change: float = None

    def __post_init__(self):
        df = self.df
        col_names = list(df.columns)
        assert 'Forecast' in df.columns
        col_names.remove('Forecast')
        if 'Year' in col_names:
            self.df = df = df.set_index('Year')
            col_names.remove('Year')

        if not self.column_name:
            # Make sure there is only one column for Y axis
            assert len(col_names) == 1
            self.column_name = col_names[0]
        else:
            assert isinstance(self.column_name, str)

    def get_color(self, forecast=False):
        if forecast:
            color = self.forecast_color
        else:
            color = self.historical_color

        if color:
            return color

        if forecast and self.historical_color:
            color = Color(self.historical_color)
        else:
            color = Color(GHG_MAIN_SECTOR_COLORS[self.graph.sector_name])

        if self.luminance_change:
            luminance = color.get_luminance()
            if self.luminance_change < 0:
                luminance = luminance * (1 + self.luminance_change)
            else:
                luminance = luminance + (1 - luminance) * self.luminance_change
            color.set_luminance(luminance)

        if forecast:
            # Lighten forecast series by 30 %
            luminance = color.get_luminance()
            luminance = luminance + (1 - color.get_luminance()) * .3
            color.set_luminance(luminance)
        return color.hex


@dataclass
class PredictionGraph:
    sector_name: str = None
    title: str = None
    unit_name: str = None
    y_max: float = None
    smoothing: bool = False
    fill: bool = False
    stacked: bool = False
    allow_nonconsecutive_years: bool = False

    def __post_init__(self):
        self.series_list = []
        self.min_year = None
        self.max_year = None
        self.forecast_start_year = None

    def get_traces_for_series(self, series: PredictionGraphSeries, index: int, has_multiple_series: bool):
        df = series.df

        trace_attrs = {}
        if self.stacked or self.fill:
            if self.stacked and index > 0:
                trace_attrs['fill'] = 'tonexty'
            else:
                trace_attrs['fill'] = 'tozeroy'

        if self.fill:
            trace_attrs['mode'] = 'none'
        else:
            trace_attrs['mode'] = 'lines'

        if self.allow_nonconsecutive_years:
            start_year = df.index.min()
        else:
            start_year = find_consecutive_start(df.index)

        y_column = series.column_name
        hist_series = df.loc[~df.Forecast & (df.index >= start_year), y_column].dropna()

        hovertemplate = '%{x}: %{y}'
        if self.unit_name:
            hovertemplate += ' %s' % self.unit_name

        traces = []
        line_attrs = dict(width=4)
        if self.smoothing:
            line_attrs.update(dict(smoothing=1, shape='spline'))

        if len(hist_series):
            color = series.get_color(forecast=False)

            if self.stacked:
                trace_attrs['stackgroup'] = 'history'
            if self.fill:
                trace_attrs['fillcolor'] = color

            hist_trace = dict(
                type='scatter',
                x=hist_series.index.astype(str),
                y=hist_series,
                name=series.trace_name,
                hovertemplate=hovertemplate,
                line=dict(
                    color=color,
                    **line_attrs,
                ),
                **trace_attrs
            )

            traces.append(hist_trace)
            last_hist_year = hist_series.index.max()
            forecast_series = df.loc[df.Forecast | (df.index == last_hist_year), y_column]
        else:
            forecast_series = df.loc[df.Forecast, y_column]

        forecast_series = forecast_series.dropna()
        if len(forecast_series):
            color = series.get_color(forecast=True)

            if self.stacked:
                trace_attrs['stackgroup'] = 'forecast'
            if self.fill:
                trace_attrs['fillcolor'] = color
            else:
                line_attrs['dash'] = 'dash'

            forecast_trace = dict(
                type='scatter',
                x=forecast_series.index.astype(str),
                y=forecast_series,
                name='%s (enn.)' % series.trace_name,
                hovertemplate=hovertemplate,
                line=dict(
                    color=color,
                    **line_attrs,
                ),
                **trace_attrs
            )
            traces.insert(0, forecast_trace)

        return traces

    def add_series(self, *args, **kwargs):
        series = PredictionGraphSeries(self, *args, **kwargs)
        self.series_list.append(series)
        df = series.df
        if self.min_year is None or df.index.min() < self.min_year:
            self.min_year = df.index.min()
        if self.max_year is None or df.index.max() > self.max_year:
            self.max_year = df.index.max()

        fstart = df.loc[~df.Forecast].index.max()
        if self.forecast_start_year is None or fstart < self.forecast_start_year:
            self.forecast_start_year = fstart

    def get_figure(self):
        yattrs = {}
        if self.y_max:
            yattrs['fixedrange'] = True
            yattrs['range'] = [0, self.y_max]

        tick_vals = []
        tick_labels = []
        today = date.today()
        print(self.forecast_start_year)
        for year in range(self.min_year, self.max_year + 1):
            if year != self.forecast_start_year and tick_vals and year != self.max_year:
                if year - tick_vals[-1] < 3:
                    continue
                if year % 5 != 0:
                    continue
            tick_vals.append(year)
            tick_labels.append(str(year))

        layout = make_layout(
            title=self.title,
            yaxis=dict(
                title=self.unit_name,
                **yattrs,
            ),
            xaxis=dict(
                # type='linear',
                fixedrange=True,
                tickvals=tick_vals,
                ticklabels=tick_labels,
            ),
            hovermode='closest',
            height=450,
        )

        traces = []
        has_multiple = len(self.series_list) > 1
        for idx, series in enumerate(self.series_list):
            traces += self.get_traces_for_series(series, idx, has_multiple)

        fig = dict(data=traces, layout=layout)

        return fig

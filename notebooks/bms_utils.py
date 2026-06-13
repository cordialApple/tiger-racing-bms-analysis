"""Shared utilities for the LSU Tiger Racing BMS analysis notebooks.

A single source of truth for loading and cleaning the cellvoltages_*.csv
exports, plus a few per-cell summary helpers (z-score, mean rank, load
residual, BMS-reported resistance summary) used across the per-session and
cross-session notebooks.

Resistance and Open Cell Voltage columns are KEPT — earlier notebooks
dropped them under an "Impedance Analysis TBA" comment, but cross-session
trends and load-residual diagnostics need them.
"""

from __future__ import annotations

import os
import re

import numpy as np
import pandas as pd

N_CELLS = 84
CV_COLS = [f'Cell Voltage {i}' for i in range(1, N_CELLS + 1)]
RES_COLS = [f'Cell Resistance {i}' for i in range(1, N_CELLS + 1)]
OCV_COLS = [f'Open Cell Voltage {i}' for i in range(1, N_CELLS + 1)]

_TZ_PATTERN = re.compile(r'\s+[A-Z]{2,4}\s+')

LSU_COLORS = ["#4E2A84", "#FDD023", "#7F857765", "#000000"]  # purple, gold, gray, black


def _session_id_from_path(path: str) -> str:
    """Extract the timestamp portion of cellvoltages_<id>.csv."""
    base = os.path.basename(path)
    return base.split('cellvoltages_')[1].replace('.csv', '')


def load_session(path: str) -> pd.DataFrame:
    """Load and clean one cellvoltages_*.csv export.

    Returns a DataFrame with:
      - whitespace-stripped column names
      - the BMS trailing-empty column removed
      - Pack Current sign-flipped so positive = charging
      - Time parsed to pandas datetime (timezone-agnostic; handles CST/CDT/etc.)
      - elapsed_s column (seconds since first sample)
      - session_id column derived from the filename
    """
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    df = df.dropna(axis=1, how='all')
    df['Pack Current'] = df['Pack Current'] * -1
    df['Time'] = pd.to_datetime(
        df['Time'].str.replace(_TZ_PATTERN, ' ', regex=True),
        format='%a %b %d %H:%M:%S %Y',
    )
    df['elapsed_s'] = (df['Time'] - df['Time'].iloc[0]).dt.total_seconds()
    df['session_id'] = _session_id_from_path(path)
    return df


def sampling_summary(df: pd.DataFrame, group_col: str = 'session_id') -> pd.DataFrame:
    """Per-session sampling diagnostics: rows, duration, median dt, max gap."""
    rows = []
    for sid, g in df.groupby(group_col):
        dt = g['Time'].diff().dt.total_seconds().dropna()
        rows.append({
            'session_id': sid,
            'rows': len(g),
            'duration_s': float(g['elapsed_s'].max()) if 'elapsed_s' in g else float(dt.sum()),
            'median_dt_s': float(dt.median()) if len(dt) else float('nan'),
            'p99_dt_s': float(dt.quantile(0.99)) if len(dt) else float('nan'),
            'max_gap_s': float(dt.max()) if len(dt) else float('nan'),
        })
    return pd.DataFrame(rows)


def cell_mean_voltage(df: pd.DataFrame) -> pd.Series:
    """Per-cell mean voltage across all samples."""
    return df[CV_COLS].mean()


def cell_mean_rank(df: pd.DataFrame) -> pd.Series:
    """Per-cell mean rank (1 = lowest cell in that row)."""
    return df[CV_COLS].rank(axis=1).mean()


def cell_voltage_z(df: pd.DataFrame) -> pd.Series:
    """Per-cell mean-voltage z-score across the 84-cell distribution."""
    means = cell_mean_voltage(df)
    return (means - means.mean()) / means.std()


def load_residual_mv(df: pd.DataFrame, min_abs_current_a: float = 1.0) -> pd.Series:
    """Per-cell median load-induced voltage delta V_loaded − OCV, in mV.

    Computed only over samples where |Pack Current| >= min_abs_current_a so
    the delta is dominated by I·R rather than measurement noise. A cell with
    an abnormally large |delta| at the same pack current as its peers is
    showing elevated internal resistance.
    """
    if 'Pack Current' not in df.columns or not set(OCV_COLS).issubset(df.columns):
        return pd.Series(np.nan, index=range(1, N_CELLS + 1), name='load_residual_mV')
    mask = df['Pack Current'].abs() >= min_abs_current_a
    if mask.sum() == 0:
        return pd.Series(np.nan, index=range(1, N_CELLS + 1), name='load_residual_mV')
    sub = df.loc[mask]
    delta_mv = (sub[CV_COLS].to_numpy() - sub[OCV_COLS].to_numpy()) * 1000
    med = np.median(delta_mv, axis=0)
    return pd.Series(med, index=range(1, N_CELLS + 1), name='load_residual_mV')


def bms_resistance_summary(df: pd.DataFrame) -> pd.Series:
    """Per-cell median of the BMS-reported Cell Resistance N column.

    Units are whatever the BMS exports (verify against your hardware sheet);
    useful for relative cross-cell comparison even without a unit calibration.
    """
    if not set(RES_COLS).issubset(df.columns):
        return pd.Series(np.nan, index=range(1, N_CELLS + 1), name='bms_resistance')
    med = df[RES_COLS].median().to_numpy()
    return pd.Series(med, index=range(1, N_CELLS + 1), name='bms_resistance')


def annotate_runs(ax, df: pd.DataFrame, x: str = 'elapsed_m', group_col: str = 'run_id') -> None:
    """Mark run boundaries on a time-series plot with a dotted vertical line."""
    if group_col not in df.columns:
        return
    for _, g in df.groupby(group_col):
        ax.axvline(g[x].iloc[0], color='gray', linewidth=0.8, linestyle=':', alpha=0.7)


def apply_lsu_style() -> None:
    """Set matplotlib + seaborn defaults to the LSU purple/gold palette."""
    import matplotlib.pyplot as plt
    import seaborn as sns
    sns.set_theme(style='darkgrid')
    sns.set_palette(sns.color_palette(LSU_COLORS))
    plt.rcParams['figure.figsize'] = (14, 4)

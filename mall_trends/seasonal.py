"""NZ retail calendar anchors for seasonal week alignment (Auckland)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

# Easter Sunday — school hols / Good Friday cluster around this anchor.
EASTER_SUNDAY = {
    2024: date(2024, 3, 31),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
}

# Fixed-ish public holidays (Monday observed where applicable).
FIXED_HOLIDAYS = {
    "Auckland Anniversary": {
        2024: date(2024, 1, 29),
        2025: date(2025, 1, 27),
        2026: date(2026, 1, 26),
    },
    "Waitangi Day": {
        2024: date(2024, 2, 6),
        2025: date(2025, 2, 6),
        2026: date(2026, 2, 6),
    },
    "ANZAC Day": {
        2024: date(2024, 4, 25),
        2025: date(2025, 4, 25),
        2026: date(2026, 4, 25),
    },
    "King's Birthday": {
        2024: date(2024, 6, 3),
        2025: date(2025, 6, 2),
        2026: date(2026, 6, 1),
    },
    "Matariki": {
        2024: date(2024, 6, 28),
        2025: date(2025, 6, 20),
        2026: date(2026, 7, 10),
    },
    "Labour Day": {
        2024: date(2024, 10, 28),
        2025: date(2025, 10, 27),
        2026: date(2026, 10, 26),
    },
    "Christmas": {
        2024: date(2024, 12, 25),
        2025: date(2025, 12, 25),
        2026: date(2026, 12, 25),
    },
}

# NZ school holiday midpoints (approx.) for shading.
SCHOOL_HOLIDAY_MID = {
    "Term 1 break": {
        2024: date(2024, 4, 20),
        2025: date(2025, 4, 20),
        2026: date(2026, 4, 10),
    },
    "Term 2 break": {
        2024: date(2024, 7, 12),
        2025: date(2025, 7, 12),
        2026: date(2026, 7, 12),
    },
    "Term 3 break": {
        2024: date(2024, 10, 5),
        2025: date(2025, 10, 5),
        2026: date(2026, 10, 5),
    },
    "Summer break": {
        2024: date(2024, 12, 20),
        2025: date(2025, 12, 20),
        2026: date(2026, 12, 20),
    },
}


@dataclass(frozen=True)
class HolidayMarker:
    name: str
    season_week: int
    color: str


def week_start_monday(d: date) -> date:
    return d - pd.Timedelta(days=d.weekday())


def season_week_from_easter(week_start: pd.Timestamp, year: int) -> int:
    """Weeks from Easter week (0 = week containing Easter Sunday)."""
    easter_monday = week_start_monday(EASTER_SUNDAY[year])
    ws = week_start.date() if hasattr(week_start, "date") else week_start
    if isinstance(ws, pd.Timestamp):
        ws = ws.date()
    return int((ws - easter_monday).days // 7)


def enrich_seasonal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["year"] = df["week_start"].dt.isocalendar().year.astype(int)
    df["iso_week"] = df["week_start"].dt.isocalendar().week.astype(int)
    df["year_trend_index"] = df.groupby("year")["panel_visits"].transform(
        lambda s: s / s.median()
    )
    df["season_week"] = [
        season_week_from_easter(row.week_start, int(row.year))
        for row in df.itertuples()
    ]
    return df


def drop_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """IQR filter on year_trend_index within each year."""
    parts = []
    for _, g in df.groupby("year", sort=True):
        q1, q3 = g["year_trend_index"].quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        parts.append(g[(g["year_trend_index"] >= lo) & (g["year_trend_index"] <= hi)])
    return pd.concat(parts, ignore_index=True)


def _pair_correlations(pair: pd.DataFrame, y1, y2) -> dict:
    a, b = pair[y1], pair[y2]
    return {
        "pearson": a.corr(b),
        "spearman": a.rank().corr(b.rank()),
    }


def correlation_by_iso_week(df: pd.DataFrame) -> pd.DataFrame:
    clean = drop_anomalies(df)
    pivot = clean.pivot_table(
        index="iso_week", columns="year", values="year_trend_index", aggfunc="first"
    )
    years = sorted(pivot.columns)
    rows = []
    for i, y1 in enumerate(years):
        for y2 in years[i + 1 :]:
            pair = pivot[[y1, y2]].dropna()
            if len(pair) < 8:
                continue
            rows.append(
                {
                    "year_a": y1,
                    "year_b": y2,
                    "weeks_overlap": len(pair),
                    **_pair_correlations(pair, y1, y2),
                }
            )
    return pd.DataFrame(rows)


def correlation_by_season_week(df: pd.DataFrame) -> pd.DataFrame:
    clean = drop_anomalies(df)
    pivot = clean.pivot_table(
        index="season_week", columns="year", values="year_trend_index", aggfunc="first"
    )
    years = sorted(pivot.columns)
    rows = []
    for i, y1 in enumerate(years):
        for y2 in years[i + 1 :]:
            pair = pivot[[y1, y2]].dropna()
            if len(pair) < 8:
                continue
            rows.append(
                {
                    "year_a": y1,
                    "year_b": y2,
                    "weeks_overlap": len(pair),
                    **_pair_correlations(pair, y1, y2),
                }
            )
    return pd.DataFrame(rows)


def holiday_markers() -> list[HolidayMarker]:
    palette = {
        "Easter": "#f97316",
        "Auckland Anniversary": "#a855f7",
        "Waitangi Day": "#14b8a6",
        "ANZAC Day": "#64748b",
        "King's Birthday": "#eab308",
        "Matariki": "#6366f1",
        "Labour Day": "#22c55e",
        "Christmas": "#dc2626",
        "Term 1 break": "#fdba74",
        "Term 2 break": "#93c5fd",
        "Term 3 break": "#86efac",
        "Summer break": "#fca5a5",
    }
    markers: list[HolidayMarker] = []
    markers.append(HolidayMarker("Easter", 0, palette["Easter"]))

    all_events = {**FIXED_HOLIDAYS, **SCHOOL_HOLIDAY_MID}
    for name, by_year in all_events.items():
        weeks = []
        for year, d in by_year.items():
            easter_monday = week_start_monday(EASTER_SUNDAY[year])
            ws = week_start_monday(d)
            weeks.append(int((ws - easter_monday).days // 7))
        median_sw = int(round(sum(weeks) / len(weeks)))
        markers.append(HolidayMarker(name, median_sw, palette.get(name, "#cbd5e1")))
    return markers

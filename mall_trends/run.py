"""Build weekly Newmarket visitor trends from materialized analytics tables."""

from __future__ import annotations

import argparse
from pathlib import Path

from mall_trends.bq_client import query
from mall_trends.newmarket_geofence import SCENTRE_ANNUAL_VISITS
from mall_trends.tables import AUCKLAND_PANEL, daily_visits_table

WEEKLY_SQL = """
WITH daily_visits AS (
  SELECT local_date, COUNT(*) AS visits, COUNT(DISTINCT maid) AS unique_devices
  FROM {daily_visits}
  WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'
  GROUP BY local_date
),
daily_panel AS (
  SELECT local_date, device_count AS auckland_devices
  FROM {auckland_panel}
  WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'
)
SELECT
  DATE_TRUNC(v.local_date, WEEK(MONDAY)) AS week_start,
  SUM(v.visits) AS panel_visits,
  SUM(v.unique_devices) AS sum_daily_unique_devices,
  AVG(p.auckland_devices) AS avg_auckland_panel_devices,
  SAFE_DIVIDE(SUM(v.visits), AVG(p.auckland_devices)) AS mall_share_of_auckland_panel
FROM daily_visits v
JOIN daily_panel p USING (local_date)
GROUP BY week_start
ORDER BY week_start
"""


def build_sql(start: str, end: str, *, no_dwell: bool = False) -> str:
    return WEEKLY_SQL.format(
        start=start,
        end=end,
        daily_visits=daily_visits_table(no_dwell),
        auckland_panel=AUCKLAND_PANEL,
    )


def calibrate(df, annual_visits: int = SCENTRE_ANNUAL_VISITS):
    df = df.copy()
    mean_panel = df["panel_visits"].mean()
    if mean_panel <= 0:
        return df
    scale = (annual_visits / 52) / mean_panel
    df["calibrated_visits"] = df["panel_visits"] * scale
    df["yoy_panel_visits"] = df["panel_visits"].pct_change(periods=52)
    median_panel = df["panel_visits"].median()
    if median_panel > 0:
        df["trend_index"] = df["panel_visits"] / median_panel
    return df


def write_outputs(df, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    index_out = out.with_name(out.stem + "_index" + out.suffix)
    index_df = df[["week_start", "panel_visits", "trend_index"]].copy()
    if "calibrated_visits" in df.columns:
        median_cal = df["calibrated_visits"].median()
        if median_cal > 0:
            index_df["calibrated_trend_index"] = df["calibrated_visits"] / median_cal
    index_df.to_csv(index_out, index=False)
    print(f"Wrote {len(df)} weeks to {out}")
    print(f"Wrote trend index to {index_out} (median week = 1.0)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Newmarket weekly mall visitor trends")
    parser.add_argument("--start", default="2024-02-01", help="local_date start (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-08-01", help="local_date end (YYYY-MM-DD)")
    parser.add_argument(
        "--out",
        default="results/newmarket_weekly_trends.csv",
        help="output CSV path",
    )
    parser.add_argument("--dry-run", action="store_true", help="estimate bytes scanned only")
    parser.add_argument(
        "--no-dwell",
        action="store_true",
        help="use newmarket_daily_visits_no_dwell table",
    )
    args = parser.parse_args(argv)

    suffix = "_no_dwell" if args.no_dwell else ""
    if args.out == "results/newmarket_weekly_trends.csv" and suffix:
        args.out = f"results/newmarket_weekly_trends{suffix}.csv"

    sql = build_sql(args.start, args.end, no_dwell=args.no_dwell)
    if args.dry_run:
        bytes_scanned = query(sql, dry_run=True)
        print(f"Dry run: {bytes_scanned / 1e9:.2f} GB scanned")
        return

    df = query(sql)
    df = calibrate(df)
    out = Path(args.out)
    write_outputs(df, out)
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

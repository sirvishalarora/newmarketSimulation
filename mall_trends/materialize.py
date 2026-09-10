"""Create and refresh analytics tables from fact_ping (incremental by date range)."""

from __future__ import annotations

import argparse

from mall_trends.bq_client import execute, query
from mall_trends.tables import (
    CREATE_AUCKLAND_PANEL,
    CREATE_DATASET,
    create_daily_visits,
    daily_visits_table,
    delete_daily_visits,
    insert_auckland_panel,
    insert_daily_visits,
)


def ensure_tables(*, no_dwell: bool, refresh_panel: bool) -> None:
    execute(CREATE_DATASET)
    execute(create_daily_visits(no_dwell))
    if refresh_panel:
        execute(CREATE_AUCKLAND_PANEL)


def refresh(
    start: str,
    end: str,
    *,
    no_dwell: bool = False,
    refresh_panel: bool = True,
    dry_run: bool = False,
) -> None:
    steps = [
        delete_daily_visits(start, end, no_dwell=no_dwell),
        insert_daily_visits(start, end, no_dwell=no_dwell),
    ]
    if refresh_panel:
        steps.extend(
            [
                f"DELETE FROM `geo-reach.analytics.auckland_panel_daily` "
                f"WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'",
                insert_auckland_panel(start, end),
            ]
        )
    if dry_run:
        total = sum(query(sql, dry_run=True) for sql in steps)
        print(f"Dry run: {total / 1e9:.2f} GB scanned ({start} to {end})")
        return

    for sql in steps:
        execute(sql)

    table = daily_visits_table(no_dwell).strip("`")
    summary = query(f"""
    SELECT
      (SELECT COUNT(*) FROM `{table}`
       WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}') AS visit_rows,
      (SELECT COUNT(DISTINCT local_date) FROM `{table}`
       WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}') AS visit_days
    """)
    print(summary.to_string(index=False))


def table_stats(*, no_dwell: bool = False) -> None:
    visits = daily_visits_table(no_dwell).strip("`")
    df = query(f"""
    SELECT
      '{visits.split('.')[-1]}' AS table_name,
      MIN(local_date) AS min_date,
      MAX(local_date) AS max_date,
      COUNT(1) AS row_count
    FROM `{visits}`
    """)
    print(df.to_string(index=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Materialize Newmarket analytics tables")
    parser.add_argument("--start", help="local_date start (YYYY-MM-DD)")
    parser.add_argument("--end", help="local_date end (YYYY-MM-DD)")
    parser.add_argument("--full", action="store_true", help="backfill 2024-02-01 to 2026-08-01")
    parser.add_argument(
        "--no-dwell",
        action="store_true",
        help="any ping in geofence counts (no min pings / dwell time)",
    )
    parser.add_argument(
        "--skip-panel",
        action="store_true",
        help="skip auckland panel refresh (already materialized)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true", help="show table row counts")
    args = parser.parse_args(argv)

    if args.stats:
        table_stats(no_dwell=args.no_dwell)
        return

    start = args.start or ("2024-02-01" if args.full else None)
    end = args.end or ("2026-08-01" if args.full else None)
    if not start or not end:
        parser.error("Provide --start and --end, or use --full")

    refresh_panel = not args.skip_panel
    ensure_tables(no_dwell=args.no_dwell, refresh_panel=refresh_panel)
    refresh(
        start,
        end,
        no_dwell=args.no_dwell,
        refresh_panel=refresh_panel,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

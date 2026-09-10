"""Ingest weekly_weights_combined CSV into geo-reach.mortalportal.site_weekly_trend."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from google.cloud import bigquery

from mall_trends.bq_client import get_client, query

DIM_SITE = "`geo-reach.panels.dim_site`"
TARGET = "geo-reach.mortalportal.site_weekly_trend"

# Map CSV weight columns -> dim_site.name match
WEIGHT_COLUMNS = {
    "albany_visit_weight": "Westfield Albany",
    "newmarket_transaction_weight": "Westfield Newmarket",
}


def load_sites() -> pd.DataFrame:
    names = list(WEIGHT_COLUMNS.values())
    in_list = ", ".join(f"'{n}'" for n in names)
    return query(f"""
    SELECT site_id, name AS site_name
    FROM {DIM_SITE}
    WHERE name IN ({in_list})
    """)


def unpivot_weights(csv_path: Path, sites: pd.DataFrame) -> pd.DataFrame:
    raw = pd.read_csv(csv_path)
    by_name = sites.set_index("site_name")["site_id"].to_dict()
    frames = []
    for col, site_name in WEIGHT_COLUMNS.items():
        if col not in raw.columns:
            raise KeyError(f"Missing column {col} in {csv_path}")
        if site_name not in by_name:
            raise KeyError(f"Site '{site_name}' not found in dim_site")
        part = pd.DataFrame(
            {
                "site_id": int(by_name[site_name]),
                "site_name": site_name,
                "week_index": raw["week_index"].astype(int),
                "trend_value": raw[col].astype(float),
            }
        )
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["site_id", "week_index"]).reset_index(drop=True)


def write_bq(df: pd.DataFrame, table_id: str = TARGET) -> None:
    client = get_client()
    client.query("CREATE SCHEMA IF NOT EXISTS `geo-reach.mortalportal`").result()
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    print(f"Loaded {len(df)} rows into {table_id}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="/Users/vishalarora/Projects/newmarket-spend-data/weekly_weights_combined_2026.csv",
    )
    parser.add_argument("--table", default=TARGET)
    parser.add_argument(
        "--out-csv",
        default="results/site_weekly_trend.csv",
        help="local copy of unpivoted table",
    )
    args = parser.parse_args(argv)

    sites = load_sites()
    print("dim_site matches:")
    print(sites.to_string(index=False))

    df = unpivot_weights(Path(args.csv), sites)
    out = Path(args.out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {out} ({len(df)} rows)")
    print(df.groupby("site_name").size().to_string())

    write_bq(df, args.table)

    check = query(f"""
    SELECT site_id, site_name, COUNT(*) AS weeks,
           MIN(week_index) AS min_w, MAX(week_index) AS max_w,
           ROUND(AVG(trend_value), 4) AS avg_trend
    FROM `{args.table}`
    GROUP BY 1, 2
    ORDER BY site_id
    """)
    print("\nBigQuery verification:")
    print(check.to_string(index=False))


if __name__ == "__main__":
    main()

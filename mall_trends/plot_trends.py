"""Bar plot of weekly trend_index."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def plot_trend_index(csv_path: Path, out_path: Path, *, title_suffix: str = "") -> None:
    df = pd.read_csv(csv_path, parse_dates=["week_start"])
    df = df.sort_values("week_start")

    fig, ax = plt.subplots(figsize=(18, 6))
    colors = ["#2563eb" if v >= 1 else "#94a3b8" for v in df["trend_index"]]
    ax.bar(df["week_start"], df["trend_index"], width=5, color=colors, edgecolor="none")

    ax.axhline(1.0, color="#dc2626", linewidth=1.2, linestyle="--", label="Median (1.0)")
    ax.set_ylabel("Trend index (median week = 1.0)")
    ax.set_xlabel("Week starting")
    ax.set_title(f"Westfield Newmarket — weekly visitor trend{title_suffix}")
    ax.set_ylim(0, max(df["trend_index"].max() * 1.08, 1.15))

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="results/newmarket_weekly_trends_index.csv",
    )
    parser.add_argument(
        "--out",
        default=None,
    )
    parser.add_argument(
        "--no-dwell",
        action="store_true",
        help="use no-dwell trend CSV paths",
    )
    args = parser.parse_args()
    if args.no_dwell:
        csv_path = args.csv if args.csv != "results/newmarket_weekly_trends_index.csv" else (
            "results/newmarket_weekly_trends_no_dwell_index.csv"
        )
        out_path = args.out or "results/newmarket_weekly_trends_no_dwell_index.png"
        title_suffix = " (tight geofence, no dwell filter)"
    else:
        csv_path = args.csv
        out_path = args.out or "results/newmarket_weekly_trends_index.png"
        title_suffix = " (tight geofence)"
    plot_trend_index(Path(csv_path), Path(out_path), title_suffix=title_suffix)


if __name__ == "__main__":
    main()

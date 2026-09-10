"""Seasonal overlay plot and year-on-year correlation."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from mall_trends.seasonal import (
    correlation_by_iso_week,
    correlation_by_season_week,
    drop_anomalies,
    enrich_seasonal,
    holiday_markers,
)


def _plot_overlay(ax, df: pd.DataFrame, x_col: str, title: str, show_holidays: bool) -> None:
    colors = {2024: "#64748b", 2025: "#2563eb", 2026: "#16a34a"}
    for year, g in df.groupby("year"):
        ax.plot(
            g[x_col],
            g["year_trend_index"],
            marker="o",
            markersize=4,
            linewidth=1.8,
            label=str(year),
            color=colors.get(year, "#111827"),
            alpha=0.9,
        )

    ax.axhline(1.0, color="#dc2626", linestyle="--", linewidth=1, label="Year median")

    if show_holidays and x_col == "season_week":
        for h in holiday_markers():
            ax.axvline(h.season_week, color=h.color, alpha=0.2, linewidth=10, zorder=0)
        for name in ("Easter", "ANZAC Day", "Matariki", "Christmas", "Summer break"):
            h = next((m for m in holiday_markers() if m.name == name), None)
            if not h:
                continue
            ax.text(
                h.season_week,
                ax.get_ylim()[1] * 0.97,
                h.name.replace(" break", ""),
                rotation=90,
                va="top",
                ha="center",
                fontsize=7,
                color="#475569",
            )

    ax.set_title(title)
    ax.set_ylabel("Year trend index (year median = 1.0)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)


def plot_seasonal(csv_path: Path, out_path: Path, corr_out: Path) -> None:
    raw = pd.read_csv(csv_path, parse_dates=["week_start"])
    df = enrich_seasonal(raw)
    clean = drop_anomalies(df)

    iso_corr = correlation_by_iso_week(df)
    season_corr = correlation_by_season_week(df)
    corr_out.parent.mkdir(parents=True, exist_ok=True)
    with corr_out.open("w") as f:
        f.write("# ISO week alignment (calendar week 1-52, holidays drift)\n")
        iso_corr.to_csv(f, index=False)
        f.write("\n# Season week alignment (0 = Easter week, moving holidays line up)\n")
        season_corr.to_csv(f, index=False)

    enriched_out = csv_path.with_name(
        csv_path.stem.replace("_index", "") + "_seasonal.csv"
    )
    df.to_csv(enriched_out, index=False)
    clean.to_csv(
        csv_path.with_name(csv_path.stem.replace("_index", "") + "_seasonal_clean.csv"),
        index=False,
    )

    fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharey=True)

    _plot_overlay(
        axes[0],
        clean,
        "iso_week",
        "Calendar ISO week — shape by year (anomalies removed)",
        show_holidays=False,
    )
    axes[0].set_xlabel("ISO week of year (1–52)")
    axes[0].set_xticks(range(1, 53, 4))

    _plot_overlay(
        axes[1],
        clean,
        "season_week",
        "Holiday-aligned season week (0 = Easter week; bands = major holidays)",
        show_holidays=True,
    )
    axes[1].set_xlabel("Season week (weeks from Easter week)")
    axes[1].set_xticks(range(-20, 36, 5))

    fig.suptitle(
        "Westfield Newmarket — year-on-year seasonal shape (year median = 1.0)",
        fontsize=13,
        y=0.98,
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved {out_path}")
    print(f"Saved {enriched_out}")
    print(f"Saved {corr_out}")
    print("\nISO week correlations:")
    print(iso_corr.to_string(index=False))
    print("\nSeason week (Easter-aligned) correlations:")
    print(season_corr.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="results/newmarket_weekly_trends_index.csv")
    parser.add_argument("--out", default=None)
    parser.add_argument("--corr-out", default=None)
    parser.add_argument("--no-dwell", action="store_true")
    args = parser.parse_args()
    if args.no_dwell:
        csv_path = (
            args.csv
            if args.csv != "results/newmarket_weekly_trends_index.csv"
            else "results/newmarket_weekly_trends_no_dwell_index.csv"
        )
        out_path = args.out or "results/newmarket_seasonal_overlay_no_dwell.png"
        corr_out = args.corr_out or "results/newmarket_seasonal_correlation_no_dwell.csv"
    else:
        csv_path = args.csv
        out_path = args.out or "results/newmarket_seasonal_overlay.png"
        corr_out = args.corr_out or "results/newmarket_seasonal_correlation.csv"
    plot_seasonal(Path(csv_path), Path(out_path), Path(corr_out))


if __name__ == "__main__":
    main()

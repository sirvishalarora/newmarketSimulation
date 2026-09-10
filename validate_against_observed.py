"""Compare simulated panel overlap against observed MAID-derived similarity.

The observed matrices produced by the earlier RetailSimulation work are
**Jaccard** (shared / combined audience), so that is what the simulation is
scored on. Reading the simulation's overlap coefficient (shared / smaller
audience) against them instead makes a well-calibrated run look roughly twice
too high.

Reports the level agreement (are overlaps the right size overall?) and the rank
agreement (are the right pairs the most overlapping?). They fail
independently: panel positions coarse enough that several panels share one
coordinate hurt rank correlation while leaving the level broadly right.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics

import malls


def read_observed(path):
    """Read a square similarity matrix into an upper-triangle dict."""
    out = {}
    with path.open(newline="") as f:
        reader = csv.reader(f)
        columns = next(reader)[1:]
        for row in reader:
            a = row[0]
            for b, value in zip(columns, row[1:]):
                if a < b:
                    out[(a, b)] = float(value)
    return out


def read_simulated(path):
    jaccard, overlap = {}, {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            key = (row["panel_a"], row["panel_b"])
            overlap[key] = float(row["overlap_coefficient"])
            if "jaccard" in row and row["jaccard"] not in (None, ""):
                jaccard[key] = float(row["jaccard"])
            else:
                # Older outputs predate the jaccard column; derive it.
                ra = int(row["unique_reach_a"])
                rb = int(row["unique_reach_b"])
                shared = int(row["shared_agents"])
                union = ra + rb - shared
                jaccard[key] = shared / union if union else 0.0
    return jaccard, overlap


def pearson(x, y):
    n = len(x)
    if n < 2:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else float("nan")


def spearman(x, y):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0] * len(values)
        for position, index in enumerate(order):
            out[index] = position
        return out

    return pearson(ranks(x), ranks(y))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    malls.add_mall_argument(parser)
    args = parser.parse_args()
    mall = malls.resolve(args.mall)

    if not mall.observed_similarity:
        raise SystemExit(f"{mall.name} has no observed similarity matrix configured")

    observed_path = mall.path("observed_similarity")
    simulated_path = mall.path("results_dir") / "panel_pair_overlap.csv"
    for label, path in (("observed", observed_path), ("simulated", simulated_path)):
        if not path.exists():
            raise SystemExit(f"missing {label} data: {path}")

    observed = read_observed(observed_path)
    jaccard, overlap = read_simulated(simulated_path)

    common = sorted(set(observed) & set(jaccard))
    if not common:
        raise SystemExit("no panel pairs in common between observed and simulated")
    missing = len(set(observed) ^ set(jaccard))

    x = [observed[k] for k in common]
    print(f"{mall.name}: {len(common)} panel pairs compared"
          + (f" ({missing} present in only one source)" if missing else ""))
    print(f"  observed (Jaccard)   mean={statistics.mean(x):.3f} "
          f"median={statistics.median(x):.3f}")

    for label, values in (("simulated Jaccard", jaccard), ("simulated overlap", overlap)):
        y = [values[k] for k in common]
        ratio = statistics.mean(y) / statistics.mean(x) if statistics.mean(x) else float("nan")
        print(f"  {label}    mean={statistics.mean(y):.3f} "
              f"median={statistics.median(y):.3f}  "
              f"r={pearson(x, y):.3f}  rho={spearman(x, y):.3f}  ratio={ratio:.2f}x")

    print("\n  Compare on the Jaccard row. The overlap row is shown only to make "
          "the metric mismatch visible, not as a second score.")


if __name__ == "__main__":
    main()

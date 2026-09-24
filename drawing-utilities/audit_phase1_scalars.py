#!/usr/bin/env python3
"""Audit a scalar-only CMA-ES result repository and render dependency-free SVGs.

The input is an unpacked results repository containing optimizer_history.json
and real_sims/<stage>/iter_N/cand_NN/config.json.  The output directory receives
three SVG plots and a machine-readable audit_summary.json.
"""

import argparse
import html
import json
import math
import statistics
from pathlib import Path


SCALARS = ("school", "class", "age_coupling_param")
COMPONENTS = ("daily_detections_cumulative", "daily_deaths_cumulative",
              "validation_mean_error")
COLORS = ("#2563eb", "#dc2626", "#059669")


def load_records(root: Path) -> list[dict]:
    records = []
    for entry in json.loads((root / "optimizer_history.json").read_text()):
        if entry.get("status") not in ("ok", "completed"):
            continue
        config_path = (root / "real_sims" / entry["stage"] /
                       f"iter_{int(entry['iteration'])}" /
                       f"cand_{int(entry['candidate']):02d}" / "config.json")
        config = json.loads(config_path.read_text())
        metrics = entry.get("metrics", {}).get("metrics", {})
        components = metrics.get("selection_score_components", {})
        records.append({
            "iteration": int(entry["iteration"]),
            "candidate": int(entry["candidate"]),
            "score": float(entry["score"]),
            "scalars": {key: float(config["transmission_probabilities"][key])
                        for key in SCALARS},
            "components": {key: float(components[key]["value"])
                           for key in COMPONENTS},
            "quality_levels": metrics.get("quality_gates", {}).get("achieved_levels", []),
        })
    if not records:
        raise ValueError("optimizer history has no completed candidates")
    return records


def pearson(left: list[float], right: list[float]) -> float:
    left_mean, right_mean = statistics.mean(left), statistics.mean(right)
    numerator = sum((x - left_mean) * (y - right_mean)
                    for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) *
                            sum((y - right_mean) ** 2 for y in right))
    return numerator / denominator if denominator else float("nan")


def summarize(records: list[dict], validation: dict | None = None) -> dict:
    iterations = sorted({row["iteration"] for row in records})
    per_iteration = []
    for iteration in iterations:
        rows = [row for row in records if row["iteration"] == iteration]
        winner = min(rows, key=lambda row: row["score"])
        per_iteration.append({
            "iteration": iteration,
            "candidate_count": len(rows),
            "best_candidate": winner["candidate"],
            "best_score": winner["score"],
            "median_score": statistics.median(row["score"] for row in rows),
            "best_scalars": winner["scalars"],
            "best_components": winner["components"],
        })
    best = min(records, key=lambda row: row["score"])
    result = {
        "candidate_count": len(records),
        "iteration_count": len(iterations),
        "best": best,
        "per_iteration": per_iteration,
        "scalar_score_correlations": {
            key: pearson([row["scalars"][key] for row in records],
                         [row["score"] for row in records]) for key in SCALARS
        },
        "scalar_ranges": {
            key: {
                "minimum": min(row["scalars"][key] for row in records),
                "maximum": max(row["scalars"][key] for row in records),
                "minimum_count": sum(row["scalars"][key] ==
                                     min(item["scalars"][key] for item in records)
                                     for row in records),
            } for key in SCALARS
        },
        "component_score_correlations": {
            key: pearson([row["components"][key] for row in records],
                         [row["score"] for row in records]) for key in COMPONENTS
        },
        "quality_gate_level_counts": {
            "0.5": sum(0.5 in row["quality_levels"] for row in records),
            "none": sum(not row["quality_levels"] for row in records),
        },
    }
    if validation:
        scores = [float(row["score"]) for row in validation.get("results", [])]
        result["validation"] = {
            "status": validation.get("status"),
            "seeds": validation.get("seeds", []),
            "scores": scores,
            "unique_score_count": len(set(scores)),
            "mean_score": validation.get("mean_score"),
            "std_score": validation.get("std_score"),
        }
    return result


def svg_plot(title: str, series: list[tuple[str, str, list[tuple[float, float]]]],
             x_label: str, y_label: str, y_min=None, y_max=None) -> str:
    width, height = 960, 480
    left, right, top, bottom = 75, 25, 55, 65
    points = [point for _, _, values in series for point in values]
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin = min(ys) if y_min is None else y_min
    ymax = max(ys) if y_max is None else y_max
    if ymin == ymax:
        ymax = ymin + 1
    xscale = lambda value: left + (value - xmin) * (width-left-right) / max(xmax-xmin, 1)
    yscale = lambda value: top + (ymax-value) * (height-top-bottom) / (ymax-ymin)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="20" font-weight="bold">{html.escape(title)}</text>']
    for tick in range(6):
        value = ymin + (ymax-ymin)*tick/5
        y = yscale(value)
        out += [f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb"/>',
                f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{value:.3f}</text>']
    out.append(f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#111827"/>')
    out.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#111827"/>')
    for label, color, values in series:
        ordered = sorted(values)
        path = " ".join(("M" if index == 0 else "L") +
                        f" {xscale(x):.1f} {yscale(y):.1f}"
                        for index, (x, y) in enumerate(ordered))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        out.extend(f'<circle cx="{xscale(x):.1f}" cy="{yscale(y):.1f}" r="3" fill="{color}"/>'
                   for x, y in ordered)
    for value in sorted(set(xs)):
        out.append(f'<text x="{xscale(value):.1f}" y="{height-bottom+22}" text-anchor="middle" font-family="sans-serif" font-size="12">{value:g}</text>')
    out += [f'<text x="{width/2}" y="{height-14}" text-anchor="middle" font-family="sans-serif" font-size="13">{html.escape(x_label)}</text>',
            f'<text x="18" y="{height/2}" text-anchor="middle" transform="rotate(-90 18 {height/2})" font-family="sans-serif" font-size="13">{html.escape(y_label)}</text>']
    legend_x = left
    for label, color, _ in series:
        out += [f'<rect x="{legend_x}" y="38" width="12" height="12" fill="{color}"/>',
                f'<text x="{legend_x+17}" y="49" font-family="sans-serif" font-size="12">{html.escape(label)}</text>']
        legend_x += 205
    out.append('</svg>')
    return "\n".join(out)


def write_outputs(summary: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    output.joinpath("audit_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    iterations = summary["per_iteration"]
    score_series = [
        ("iteration best", COLORS[0], [(row["iteration"], row["best_score"]) for row in iterations]),
        ("population median", "#6b7280", [(row["iteration"], row["median_score"]) for row in iterations]),
    ]
    output.joinpath("score_progress.svg").write_text(svg_plot(
        "Selection score progression", score_series, "Iteration", "Composite score"))
    scalar_series = [(key.replace("_", " "), color,
                      [(row["iteration"], row["best_scalars"][key]) for row in iterations])
                     for key, color in zip(SCALARS, COLORS)]
    output.joinpath("scalar_evolution.svg").write_text(svg_plot(
        "Iteration-winner scalar values", scalar_series, "Iteration", "Parameter value",
        y_min=0, y_max=0.65))
    component_series = [(key.replace("_", " "), color,
                         [(row["iteration"], row["best_components"][key]) for row in iterations])
                        for key, color in zip(COMPONENTS, COLORS)]
    output.joinpath("objective_components.svg").write_text(svg_plot(
        "Iteration-winner objective components", component_series, "Iteration", "Relative error",
        y_min=0, y_max=max(y for _, _, values in component_series for _, y in values) * 1.08))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    validation_path = args.results / "validation_replicates.json"
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else None
    write_outputs(summarize(load_records(args.results), validation), args.output)
    print(f"Wrote scalar audit to {args.output}")


if __name__ == "__main__":
    main()

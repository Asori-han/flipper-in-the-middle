#!/usr/bin/env python3
"""Generate the PoE startup phase chart used in the paper."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def spanish_decimal(value: float, _position: int) -> str:
    return f"{value:g}".replace(".", ",")


def draw_chart(output: Path) -> None:
    # Timings and measured levels come from the positive-polarity startup
    # capture; the shaded voltage bands are the IEEE 802.3 clause 33 ranges.
    boundaries = [0.6, 118.2, 259.7, 266.6, 350.0]
    levels = [3.2, 7.7, 18.1, 53.2, 53.2]

    fig, ax = plt.subplots(figsize=(10.5, 5.2), constrained_layout=True)
    standard_ranges = [
        (2.8, 10.0, "Detección: 2,8–10 V", "#4c78a8"),
        (15.5, 20.5, "Clasificación: 15,5–20,5 V", "#f2a541"),
        (44.0, 57.0, "Alimentación: 44–57 V", "#54a878"),
    ]
    for low, high, label, color in standard_ranges:
        ax.axhspan(low, high, color=color, alpha=0.15, label=label, zorder=0)

    phase_ranges = [
        (boundaries[0], boundaries[1], "#4c78a8"),
        (boundaries[1], boundaries[2], "#4c78a8"),
        (boundaries[2], boundaries[3], "#f2a541"),
        (boundaries[3], boundaries[4], "#54a878"),
    ]
    for start, end, color in phase_ranges:
        ax.axvspan(start, end, color=color, alpha=0.055, zorder=0)

    ax.step(boundaries, levels, where="post", color="#202b38", lw=2.6, zorder=3)
    measured_times = boundaries[:-1]
    measured_levels = levels[:-1]
    ax.scatter(measured_times, measured_levels, s=42, color="#202b38", zorder=4)
    for x, y, label, offset in [
        (0.6, 3.2, "3,2 V", (8, 9)),
        (118.2, 7.7, "7,7 V", (8, 9)),
        (259.7, 18.1, "18,1 V", (-42, 12)),
        (266.6, 53.2, "53,2 V", (8, -19)),
    ]:
        ax.annotate(
            label,
            (x, y),
            xytext=offset,
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
        )

    # Transition markers and elapsed-time labels make the unequal durations
    # (especially the brief classification event) explicit.
    for boundary in boundaries[1:-1]:
        ax.axvline(boundary, color="#667085", ls="--", lw=0.8, alpha=0.65)
    ax.text(59.4, 59.0, "Detección · 1.er punto\n117,6 ms", ha="center", va="top", fontsize=8.5)
    ax.text(188.95, 59.0, "Detección · 2.º punto\n141,5 ms", ha="center", va="top", fontsize=8.5)
    ax.annotate(
        "Clasificación · 6,9 ms",
        xy=(263.15, 18.1),
        xytext=(286, 31),
        arrowprops={"arrowstyle": "->", "color": "#7a4d00", "lw": 1},
        color="#7a4d00",
        fontsize=8.5,
        ha="left",
    )
    ax.text(309, 49.5, "Alimentación\ncontinua", fontsize=8.5, color="#286341")

    ax.set_xlim(0, 355)
    ax.set_ylim(0, 62)
    ax.set_xlabel("Tiempo desde el inicio de la secuencia (ms)")
    ax.set_ylabel("Tensión medida (V)")
    ax.set_title(
        "Arranque PoE: rangos de IEEE 802.3 y medidas del ensayo",
        loc="left",
        fontsize=12,
        fontweight="bold",
    )
    ax.xaxis.set_major_formatter(FuncFormatter(spanish_decimal))
    ax.yaxis.set_major_formatter(FuncFormatter(spanish_decimal))
    ax.grid(axis="both", color="#d0d5dd", lw=0.7, alpha=0.75)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(
        loc="center left",
        bbox_to_anchor=(0.02, 0.48),
        frameon=True,
        framealpha=0.94,
        fontsize=8,
    )
    fig.savefig(output, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    draw_chart(args.output)


if __name__ == "__main__":
    main()

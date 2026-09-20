#!/usr/bin/env python3
"""Generate the explanatory Manchester waveform used by the paper."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


BIT_LABELS = ("0x55 · preámbulo", "0xD5 · SFD", "0x02 · MAC destino")
BIT_VALUES = (0x55, 0xD5, 0x02)


def waveform(byte: int) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Return time in nanoseconds, Manchester levels and bit boundaries."""
    bits = [(byte >> index) & 1 for index in range(8)]
    levels: list[int] = []
    for bit in bits:
        levels.extend((-1, 1) if bit else (1, -1))
    return np.arange(len(levels) + 1) * 50, np.asarray(levels + [levels[-1]]), bits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    figure, axes = plt.subplots(3, 1, figsize=(10, 6.8), sharex=False)
    for axis, title, value in zip(axes, BIT_LABELS, BIT_VALUES):
        time_ns, levels, bits = waveform(value)
        axis.step(time_ns, levels, where="post", color="#145a86", linewidth=2.2)
        for bit_index in range(9):
            axis.axvline(bit_index * 100, color="#999999", linewidth=0.6, alpha=0.6)
        axis.set_ylim(-1.45, 1.45)
        axis.set_yticks([-1, 1], labels=["−V", "+V"])
        axis.set_ylabel(title, rotation=0, ha="right", va="center")
        axis.grid(axis="y", alpha=0.25)
        axis.text(
            0.01,
            0.08,
            "bits LSB→MSB: " + " ".join(map(str, bits)),
            transform=axis.transAxes,
            fontsize=9,
            color="#444444",
        )

    axes[-1].set_xlabel("tiempo (ns); Tbit = 100 ns, Tsemibit = 50 ns")
    figure.suptitle("Codificación Manchester en el comienzo de una trama 10BASE-T")
    figure.tight_layout(rect=(0, 0, 1, 0.96))
    figure.savefig(args.output / "manchester-waveform.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()

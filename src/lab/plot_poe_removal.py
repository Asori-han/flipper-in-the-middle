#!/usr/bin/env python3
"""Plot power removal after the PD disappears.

Unlike the connection edge, this analysis uses a millisecond scale to show both
the falling ramp and how long the PSE takes to decide that the PD is gone.

    plot_poe_removal.py data/captures/poe/poe_power_removal_20260911_214836.npz \
        --shunt 10 --invert-voltage --output build/figures/poe-retirada.svg
"""

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plot_labels import plot_label


def channel_scale(metadata, channel):
    for c in metadata["CHANNEL"]:
        if c["NAME"] == channel:
            return float(c["Current_Ratio"]) / float(c["Current_Rate"])
    raise RuntimeError(f"The capture does not describe channel {channel}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npz")
    p.add_argument("--shunt", type=float, required=True)
    p.add_argument("--branches", type=int, default=2)
    p.add_argument("--invert-voltage", action="store_true")
    p.add_argument("--cutoff-threshold", type=float, default=40.0,
                   help="voltage below which power is considered removed")
    p.add_argument("--output", default="build/figures/poe-retirada.svg")
    args = p.parse_args()

    data = np.load(args.npz, allow_pickle=True)
    metadata = json.loads(str(data["metadata_json"]))
    if data["ch2"].size == 0:
        raise SystemExit("The capture has no CH2 current measurement")

    fs = float(data["samplerate_hz"])
    t_ms = np.arange(data["ch1"].size) / fs * 1e3
    voltage_sign = -1.0 if args.invert_voltage else 1.0
    v = voltage_sign * data["ch1"].astype(float) * channel_scale(metadata, "CH1")
    i = (data["ch2"].astype(float) * channel_scale(metadata, "CH2")
         / args.shunt * args.branches * 1e3)

    below = np.where(v < args.cutoff_threshold)[0]
    if below.size == 0:
        raise SystemExit("The capture does not contain a power-removal event")
    k = int(below[0])

    powered_voltage = float(np.median(v[:max(1, k - 20)]))
    idle_voltage = float(np.median(v[-2000:]))
    u90 = idle_voltage + 0.9 * (powered_voltage - idle_voltage)
    u10 = idle_voltage + 0.1 * (powered_voltage - idle_voltage)
    a = k - 1 + int(np.argmax(v[k - 1:] <= u90))
    b = k - 1 + int(np.argmax(v[k - 1:] <= u10))
    fall_ms = float(t_ms[b] - t_ms[a])

    # The PD is absent throughout the preceding history, so this measurement is
    # a lower bound for the PSE delay rather than its exact value.
    before = i[:k]
    noise = float(before.std())
    lower_bound_ms = float(t_ms[k])

    # Current is noise around zero throughout the record. Smooth it so the plot
    # remains readable and state the averaging window in the legend.
    window = max(1, int(fs * 0.005))
    smoothed_current = np.convolve(i, np.ones(window) / window, mode="same")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
    for ax, zoom in ((ax1, False), (ax2, True)):
        current_axis = ax.twinx()
        ax.plot(t_ms, v, lw=0.9, color="#1f1f1f", label=plot_label("common.line_voltage"))
        current_axis.plot(t_ms, smoothed_current, lw=0.9, color="#1f4e79",
                   label=plot_label("poe_removal.smoothed_current", window_ms=window/fs*1e3))
        current_axis.set_ylim(-40, 40)
        ax.set_ylabel(plot_label("common.voltage_v"))
        current_axis.set_ylabel(plot_label("common.current_ma"), color="#1f4e79")
        current_axis.tick_params(axis="y", colors="#1f4e79")
        ax.grid(alpha=0.25, lw=0.5)
        ax.axvline(t_ms[k], color="#c0392b", lw=0.8, ls="--")
        if zoom:
            ax.set_xlim(t_ms[k] - 30, t_ms[k] + 90)
            ax.set_title(plot_label("poe_removal.detail_title", fall_ms=fall_ms))
            ax.set_xlabel(plot_label("common.time_ms"))
        else:
            ax.set_title(plot_label("poe_removal.overview_title",
                                    powered_v=powered_voltage, cutoff_ms=t_ms[k],
                                    idle_v=idle_voltage))
            lines = [l for l in ax.get_lines() + current_axis.get_lines()
                      if not l.get_label().startswith("_")]
            ax.legend(lines, [l.get_label() for l in lines],
                      loc="upper right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)

    summary = {
        "source": Path(args.npz).name,
        "sample_rate_hz": fs,
        "resolution_ms": 1e3 / fs,
        "powered_voltage_v": powered_voltage,
        "idle_voltage_v": idle_voltage,
        "cutoff_time_ms": float(t_ms[k]),
        "fall_90_10_ms": fall_ms,
        "previous_current_median_ma": float(np.median(before)),
        "previous_current_sigma_ma": noise,
        "pse_delay_lower_bound_ms": lower_bound_ms,
    }
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"Figure: {output}")
    print(f"  powered voltage         {powered_voltage:.1f} V")
    print(f"  cutoff                  t={t_ms[k]:.1f} ms")
    print(f"  90-10% fall             {fall_ms:.1f} ms")
    print(f"  idle voltage            {idle_voltage:.1f} V")
    print(f"  previous current        median {np.median(before):.1f} mA, sigma {noise:.1f} mA")
    print(f"  PSE delay               > {lower_bound_ms:.0f} ms (lower bound)")


if __name__ == "__main__":
    main()

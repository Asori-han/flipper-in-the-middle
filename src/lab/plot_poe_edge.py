#!/usr/bin/env python3
"""Plot the power-connection edge with simultaneous voltage and current.

CH1 measures line voltage and CH2 measures the drop across a resistor in one
of the two return conductors. Both channels share a ground at the same node, so
the two quantities use the same time base and can be compared sample by sample.

The CH1 probe reference is connected to the positive conductor, so line voltage
appears negative in the record. ``--invert-voltage`` restores its physical sign.

    plot_poe_edge.py data/captures/poe/poe_power_on_edge_20260911_210434.npz \
        --shunt 10 --invert-voltage --output build/figures/poe-flanco.svg
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
    p.add_argument("--invert-voltage", action="store_true",
                   help="CH1 references the positive conductor")
    p.add_argument("--invert-current", action="store_true")
    p.add_argument("--output", default="build/figures/poe-flanco.svg")
    args = p.parse_args()

    data = np.load(args.npz, allow_pickle=True)
    metadata = json.loads(str(data["metadata_json"]))
    if data["ch2"].size == 0:
        raise SystemExit("The capture has no CH2 current measurement")

    fs = float(data["samplerate_hz"])
    t_us = np.arange(data["ch1"].size) / fs * 1e6
    voltage_sign = -1.0 if args.invert_voltage else 1.0
    current_sign = -1.0 if args.invert_current else 1.0
    v = voltage_sign * data["ch1"].astype(float) * channel_scale(metadata, "CH1")
    i = (current_sign * data["ch2"].astype(float) * channel_scale(metadata, "CH2")
         / args.shunt * args.branches * 1e3)

    # Voltage falls before rising because the PSE removes classification power.
    # Use that minimum as the edge baseline; the classification plateau would
    # produce a wrongly referenced 10-90% measurement.
    classification_v = float(np.median(v[:200]))
    v1 = float(np.median(v[-200:]))
    high_index = int(np.argmax(v >= 0.9 * v1))
    base_index = int(np.argmin(v[:high_index])) if high_index > 0 else 0
    v0 = float(v[base_index])
    u10, u90 = v0 + 0.1 * (v1 - v0), v0 + 0.9 * (v1 - v0)
    k10 = base_index + int(np.argmax(v[base_index:] >= u10))
    k90 = base_index + int(np.argmax(v[base_index:] >= u90))
    rise_us = float(t_us[k90] - t_us[k10])

    previous_current = float(np.median(i[:200]))
    peak_index = int(np.argmax(i))
    # The PD is capacitive, so input current does not follow voltage immediately.
    # Measure the delay until current exceeds half of its peak excursion.
    threshold = previous_current + 0.5 * (i[peak_index] - previous_current)
    current_index = int(np.argmax(i >= threshold))
    delay_us = float(t_us[current_index] - t_us[k10])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
    for ax, zoom in ((ax1, False), (ax2, True)):
        current_axis = ax.twinx()
        ax.plot(t_us, v, lw=0.8, color="#1f1f1f", label=plot_label("common.line_voltage"))
        current_axis.plot(t_us, i, lw=0.8, color="#1f4e79", label=plot_label("common.total_current"))
        ax.set_ylabel(plot_label("common.voltage_v"))
        current_axis.set_ylabel(plot_label("common.current_ma"), color="#1f4e79")
        current_axis.tick_params(axis="y", colors="#1f4e79")
        ax.grid(alpha=0.25, lw=0.5)
        if zoom:
            margin = max(150.0, rise_us * 3)
            ax.set_xlim(t_us[k10] - margin, t_us[k10] + margin * 2)
            ax.axvline(t_us[k10], color="#c0392b", lw=0.8, ls="--")
            ax.axvline(t_us[k90], color="#c0392b", lw=0.8, ls="--")
            ax.set_title(plot_label("poe_edge.detail_title", rise_us=rise_us,
                                    delay_us=delay_us))
            ax.set_xlabel(plot_label("common.time_us"))
        else:
            ax.set_title(plot_label(
                "poe_edge.overview_title", classification_v=classification_v,
                previous_ma=previous_current, final_v=v1,
                duration_ms=t_us[-1] / 1e3, sample_rate_msps=fs / 1e6))

    fig.tight_layout()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)

    summary = {
        "source": Path(args.npz).name,
        "sample_rate_hz": fs,
        "resolution_us": 1e6 / fs,
        "shunt_ohm": args.shunt,
        "branches": args.branches,
        "classification_voltage_v": classification_v,
        "edge_baseline_voltage_v": v0,
        "final_voltage_v": v1,
        "previous_current_ma": previous_current,
        "rise_10_90_us": rise_us,
        "current_delay_us": delay_us,
        "peak_current_ma": float(i[peak_index]),
        "peak_current_us": float(t_us[peak_index]),
    }
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"Figure: {output}")
    print(f"  resolution             {1e6/fs:.3f} us")
    print(f"  before edge            {v0:.1f} V, {previous_current:.1f} mA")
    print(f"  after edge             {v1:.1f} V")
    print(f"  10-90% rise            {rise_us:.1f} us")
    print(f"  current delay          {delay_us:.1f} us")
    print(f"  peak current           {i[peak_index]:.1f} mA at t={t_us[peak_index]:.0f} us")


if __name__ == "__main__":
    main()

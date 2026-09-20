#!/usr/bin/env python3
"""Plot a PoE startup sequence from a DOS1102 NPZ capture.

The SVG contains the complete record and the phase before power connection.
Levels and durations are measured from samples so the figure is reproducible.

    plot_poe_startup.py data/captures/poe/poe_startup_reversed_20260911_192627.npz \
        --output build/figures/poe-arranque.svg
"""

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plot_labels import plot_label

def volts_per_count(metadata, channel="CH1"):
    """Return the scale factor stored by the instrument in the capture.

    ``Current_Ratio / Current_Rate`` yields volts per count and already includes
    probe attenuation. Read it from the downloaded capture because live status
    headers may retain values from the previous acquisition.
    """
    for c in metadata["CHANNEL"]:
        if c["NAME"] == channel:
            return float(c["Current_Ratio"]) / float(c["Current_Rate"])
    raise RuntimeError(f"The capture does not describe channel {channel}")

# IEEE 802.3af/at bands used only as visual references.
BANDS = [
    ("detection", 2.8, 10.0, "#4f8a8b"),
    ("classification", 15.5, 20.5, "#c06c3e"),
    ("power", 44.0, 57.0, "#7a5ba6"),
]


def segment(v, fs, window, threshold, merge_gap):
    """Split a signal into stable-level segments."""
    smooth = np.convolve(v, np.ones(window) / window, mode="same")
    edges = np.where(np.abs(np.diff(smooth)) > threshold)[0]
    groups = []
    for i in edges:
        if groups and i - groups[-1][-1] <= merge_gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    boundaries = [0] + [int(np.mean(g)) for g in groups] + [len(v)]
    segments = []
    for i0, i1 in zip(boundaries[:-1], boundaries[1:]):
        guard = min(60, max(1, (i1 - i0) // 4))
        seg = v[i0 + guard:max(i0 + guard + 1, i1 - guard)]
        if seg.size < 20:
            continue
        segments.append({
            "start_ms": i0 / fs * 1e3,
            "end_ms": (i1 - 1) / fs * 1e3,
            "duration_ms": (i1 - i0) / fs * 1e3,
            "level_v": float(seg.mean()),
            "sigma_v": float(seg.std()),
            # Guarded boundaries exclude edge transitions from segment averages.
            "_start": i0 + guard,
            "_end": max(i0 + guard + 1, i1 - guard),
        })
    return segments


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npz")
    p.add_argument("--output", default="build/figures/poe-arranque.svg")
    p.add_argument("--power-threshold", type=float, default=40.0,
                   help="voltage above which the line is considered powered")
    p.add_argument("--current", action="store_true",
                   help="CH2 contains the shunt drop used to measure current")
    p.add_argument("--shunt", type=float, default=10.0)
    p.add_argument("--branches", type=int, default=2)
    p.add_argument("--invert-current", action="store_true")
    p.add_argument("--invert-voltage", action="store_true",
                   help="the probe references the positive conductor")
    args = p.parse_args()

    data = np.load(args.npz, allow_pickle=True)
    metadata = json.loads(str(data["metadata_json"]))
    scale = volts_per_count(metadata)
    counts = data["ch1"].astype(float)
    fs = float(data["samplerate_hz"])
    t_ms = np.arange(counts.size) / fs * 1e3
    v = (-1.0 if args.invert_voltage else 1.0) * counts * scale
    magnitude = np.abs(v)

    # Voltage has clean plateaus. Segment on voltage and average current within
    # the same phase boundaries.
    current = None
    if args.current:
        if data["ch2"].size == 0:
            raise SystemExit("The capture has no CH2 current measurement")
        current_sign = -1.0 if args.invert_current else 1.0
        current = (current_sign * data["ch2"].astype(float)
                     * volts_per_count(metadata, "CH2") / args.shunt * args.branches * 1e3)

    powered = np.where(magnitude > args.power_threshold)[0]
    if powered.size == 0:
        raise SystemExit("The capture does not contain a power-connection event")
    power_index = int(powered[0])
    power_time = t_ms[power_index]

    previous = segment(v[:power_index], fs, window=51, threshold=0.08, merge_gap=100)
    segments = previous + [{
        "start_ms": power_time,
        "end_ms": t_ms[-1],
        "duration_ms": t_ms[-1] - power_time,
        "level_v": float(v[power_index + 20:].mean()),
        "sigma_v": float(v[power_index + 20:].std()),
        "_start": power_index + 20,
        "_end": len(v),
    }]

    # Draw standard bands on the side selected by probe polarity.
    polarity = 1.0 if v[power_index] > 0 else -1.0

    if current is not None:
        for tr in segments:
            seg = current[tr["_start"]:tr["_end"]]
            if seg.size:
                tr["current_ma"] = float(seg.mean())
                tr["current_sigma_ma"] = float(seg.std())
                tr["current_error_ma"] = float(seg.std() / np.sqrt(seg.size))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
    if current is not None:
        current_axis = ax1.twinx()
        current_axis.plot(t_ms, current, lw=0.6, color="#1f4e79", alpha=0.75)
        current_axis.set_ylabel(plot_label("poe_startup.current_axis"), color="#1f4e79")
        current_axis.tick_params(axis="y", colors="#1f4e79")
    for ax in (ax1, ax2):
        for name, lo, hi, color in BANDS:
            ax.axhspan(polarity * lo, polarity * hi, color=color, alpha=0.12, lw=0)
        ax.grid(alpha=0.25, lw=0.5)
        ax.set_ylabel(plot_label("poe_startup.voltage_axis"))

    ax1.plot(t_ms, v, lw=0.7, color="#1f1f1f")
    ax1.set_title(plot_label("poe_startup.overview_title", duration_s=t_ms[-1] / 1e3,
                             sample_rate_ksps=fs / 1e3))
    ax1.axvline(power_time, color="#c0392b", lw=0.8, ls="--")

    m = t_ms <= power_time * 1.15
    ax2.plot(t_ms[m], v[m], lw=0.9, color="#1f1f1f")
    ax2.set_title(plot_label("poe_startup.detail_title"))
    ax2.set_xlabel(plot_label("poe_startup.time_axis"))
    for tr in segments[:-1]:
        center = (tr["start_ms"] + tr["end_ms"]) / 2
        # Move annotations away from zero, where the axis edge lies.
        ax2.annotate(f"{tr['level_v']:.1f} V / {tr['duration_ms']:.0f} ms",
                     (center, tr["level_v"]), textcoords="offset points",
                     xytext=(0, int(14 * polarity)), ha="center",
                     va="bottom" if polarity > 0 else "top", fontsize=8)

    for name, lo, hi, color in BANDS:
        ax1.annotate(plot_label(f"poe_startup.bands.{name}"),
                     (t_ms[-1], polarity * (lo + hi) / 2), fontsize=7,
                     color=color, ha="right", va="center")

    fig.tight_layout()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)

    summary = {
        "source": str(Path(args.npz).name),
        "sample_rate_hz": fs,
        "samples": int(counts.size),
        "volts_per_count": scale,
        "polarity": "positive" if polarity > 0 else "negative",
        "power_connection_ms": float(power_time),
        "segments": [{k: val for k, val in tr.items() if not k.startswith("_")}
                   for tr in segments],
        "resolution_ms": 1e3 / fs,
    }
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Figure: {output}")
    print(f"Measurements: {output.with_suffix('.json')}")
    for tr in segments:
        extra = ""
        if "current_ma" in tr:
            extra = f"  {tr['current_ma']:7.2f} ± {tr['current_error_ma']:.2f} mA"
        print(f"  {tr['start_ms']:8.1f} -> {tr['end_ms']:8.1f} ms  "
              f"duration={tr['duration_ms']:7.1f} ms  level={tr['level_v']:7.2f} V{extra}")


if __name__ == "__main__":
    main()

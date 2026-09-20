#!/usr/bin/env python3
"""Plot and measure PoE current from a DOS1102 NPZ capture.

Current is derived from the voltage drop across a series resistor in one of
the two return conductors. The other conductor has an identical resistor, so
the known current split makes total current twice the measured branch current.
Resistor tolerance contributes directly to the result.

    plot_poe_current.py data/captures/poe/poe_current_20260911_201209.npz \
        --shunt 10 --output build/figures/poe-corriente.svg
"""

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plot_labels import plot_label

# IEEE 802.3at classification-current bands measured at the PSE, paired with
# the power reserved for the PD by each class.
CLASSES = [
    (0, 0.0, 4.0, 12.95),
    (1, 9.0, 12.0, 3.84),
    (2, 17.0, 20.0, 6.49),
    (3, 26.0, 30.0, 12.95),
    (4, 36.0, 44.0, 25.5),
]


def volts_per_count(metadata, channel="CH1"):
    """Return the scale factor recorded by the instrument."""
    for c in metadata["CHANNEL"]:
        if c["NAME"] == channel:
            return float(c["Current_Ratio"]) / float(c["Current_Rate"])
    raise RuntimeError(f"The capture does not describe channel {channel}")


def class_for_current(mA):
    for number, lo, hi, power in CLASSES:
        if lo <= mA <= hi:
            return {"class": number, "range_ma": [lo, hi], "pd_power_w": power}
    return None


def plateaus(current, fs, threshold, merge_gap, minimum_ms):
    """Return stable-current segments with their mean and duration."""
    smooth = np.convolve(current, np.ones(31) / 31, mode="same")
    edges = np.where(np.abs(np.diff(smooth)) > threshold)[0]
    groups = []
    for i in edges:
        if groups and i - groups[-1][-1] <= merge_gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    boundaries = [0] + [int(np.mean(g)) for g in groups] + [len(current)]
    output = []
    for i0, i1 in zip(boundaries[:-1], boundaries[1:]):
        duration = (i1 - i0) / fs * 1e3
        if duration < minimum_ms:
            continue
        guard = min(40, max(1, (i1 - i0) // 5))
        seg = current[i0 + guard:max(i0 + guard + 1, i1 - guard)]
        if seg.size < 10:
            continue
        output.append({
            "start_ms": i0 / fs * 1e3,
            "end_ms": (i1 - 1) / fs * 1e3,
            "duration_ms": duration,
            "current_ma": float(seg.mean()),
            "sigma_ma": float(seg.std()),
        })
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npz")
    p.add_argument("--shunt", type=float, required=True,
                   help="resistance in ohms of each of the two resistors")
    p.add_argument("--branches", type=int, default=2,
                   help="parallel return conductors, each with its own resistor")
    p.add_argument("--voltage", type=float, default=53.2,
                   help="measured line voltage used to estimate power")
    p.add_argument("--idle-ms", type=float, default=200.0,
                   help="end of the idle interval used for zero correction")
    p.add_argument("--current-channel", default="ch1", choices=["ch1", "ch2"],
                   help="ch1 for single-channel captures, ch2 for dual-channel captures")
    p.add_argument("--with-voltage", action="store_true",
                   help="plot voltage from the other channel on a secondary axis")
    p.add_argument("--invert-current", action="store_true")
    p.add_argument("--invert-voltage", action="store_true")
    p.add_argument("--output", default="build/figures/poe-corriente.svg")
    args = p.parse_args()

    data = np.load(args.npz, allow_pickle=True)
    metadata = json.loads(str(data["metadata_json"]))
    current_channel = args.current_channel
    voltage_channel = "ch2" if current_channel == "ch1" else "ch1"
    scale = volts_per_count(metadata, current_channel.upper())
    counts = data[current_channel].astype(float)
    fs = float(data["samplerate_hz"])
    t_ms = np.arange(counts.size) / fs * 1e3

    current_sign = -1.0 if args.invert_current else 1.0
    raw_current = current_sign * counts * scale / args.shunt * args.branches * 1e3

    voltage = None
    if args.with_voltage:
        if data[voltage_channel].size == 0:
            raise SystemExit(f"The capture has no voltage data in {voltage_channel}")
        voltage_sign = -1.0 if args.invert_voltage else 1.0
        voltage = (voltage_sign * data[voltage_channel].astype(float)
                   * volts_per_count(metadata, voltage_channel.upper()))
    idle = raw_current[t_ms <= args.idle_ms]
    zero = float(idle.mean()) if idle.size else 0.0
    current = raw_current - zero

    step = 16 * scale / args.shunt * args.branches * 1e3
    segments = plateaus(current, fs, threshold=scale / args.shunt * args.branches * 1e3 * 2,
                     merge_gap=60, minimum_ms=3.0)

    # Classification is the first appreciable current plateau before the line
    # begins sustained power delivery.
    candidates = [m for m in segments if m["current_ma"] > 3 * step]
    classification = candidates[0] if candidates else None
    power_class = class_for_current(classification["current_ma"]) if classification else None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5))
    if voltage is not None:
        voltage_axis = ax1.twinx()
        voltage_axis.plot(t_ms, voltage, lw=0.7, color="#1f1f1f", alpha=0.75)
        voltage_axis.set_ylabel(plot_label("common.voltage_v"))
    ax1.plot(t_ms, current, lw=0.7, color="#1f4e79")
    ax1.set_title(plot_label("poe_current.startup_title", duration_s=t_ms[-1] / 1e3,
                             sample_rate_ksps=fs / 1e3))
    ax1.set_ylabel(plot_label("common.current_ma"))
    ax1.grid(alpha=0.25, lw=0.5)

    if classification:
        center = (classification["start_ms"] + classification["end_ms"]) / 2
        window = (t_ms >= classification["start_ms"] - 15) & (t_ms <= classification["end_ms"] + 25)
        ax2.plot(t_ms[window], current[window], lw=1.0, marker=".", ms=2.5, color="#1f4e79")
        ax2.set_title(plot_label("poe_current.classification_title"))
        for number, lo, hi, _ in CLASSES:
            ax2.axhspan(lo, hi, color="#c06c3e", alpha=0.10, lw=0)
            ax2.annotate(plot_label("poe_current.class", number=number),
                         (t_ms[window][-1], (lo + hi) / 2),
                         fontsize=7, color="#8a4b2a", ha="right", va="center")
        # Limit the axis so the later power phase does not flatten the class bands.
        ax2.set_ylim(-5, max(48.0, classification["current_ma"] * 1.7))
        ax2.axhline(classification["current_ma"], color="#c0392b", lw=0.8, ls="--")
        ax2.annotate(f"{classification['current_ma']:.1f} mA / "
                     f"{classification['duration_ms']:.1f} ms",
                     (center, classification["current_ma"]), textcoords="offset points",
                     xytext=(0, 8), ha="center", fontsize=8)
    ax2.set_xlabel(plot_label("common.time_ms"))
    ax2.set_ylabel(plot_label("common.current_ma"))
    ax2.grid(alpha=0.25, lw=0.5)

    fig.tight_layout()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)

    summary = {
        "source": Path(args.npz).name,
        "shunt_ohm": args.shunt,
        "branches": args.branches,
        "zero_correction_ma": zero,
        "quantization_step_ma": step,
        "line_voltage_v": args.voltage,
        "classification": classification,
        "power_class": power_class,
        "segments": segments,
        "peak_ma": float(current.max()),
        "peak_ms": float(t_ms[int(np.argmax(current))]),
    }
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"Figure: {output}")
    print(f"Zero correction: {zero:.2f} mA | quantization step: {step:.2f} mA")
    for m in segments:
        extra = ""
        if voltage is not None:
            s_ = slice(int(m["start_ms"] * fs / 1e3), max(1, int(m["end_ms"] * fs / 1e3)))
            if voltage[s_].size:
                m["voltage_v"] = float(voltage[s_].mean())
                extra = f"  {m['voltage_v']:7.2f} V"
        print(f"  {m['start_ms']:8.1f} -> {m['end_ms']:8.1f} ms  dur={m['duration_ms']:7.1f} ms  "
              f"{m['current_ma']:8.2f} mA{extra}")
    if power_class:
        print(f"\nClassification: {classification['current_ma']:.2f} mA for "
              f"{classification['duration_ms']:.1f} ms -> class {power_class['class']} "
              f"({power_class['range_ma'][0]:.0f}-{power_class['range_ma'][1]:.0f} mA, "
              f"{power_class['pd_power_w']} W at the PD)")
    elif classification:
        print(f"\nClassification: {classification['current_ma']:.2f} mA, outside the standard bands")


if __name__ == "__main__":
    main()

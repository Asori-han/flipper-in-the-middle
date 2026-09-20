#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

import numpy as np


from manchester import DEFAULT_BITRATE, bytes_to_bits, manchester_halves, sample_levels


def read_hex(path):
    text = Path(path).read_text()

    # Allow comments introduced by # and arbitrary whitespace.
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    text = re.sub(r"0x", "", text, flags=re.I)
    text = re.sub(r"[^0-9a-fA-F]", "", text)

    if len(text) % 2:
        raise ValueError("The hexadecimal file contains a half byte")

    return bytes.fromhex(text)


def read_bits(path):
    text = Path(path).read_text()
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    bits = "".join(c for c in text if c in "01")

    if not bits:
        raise ValueError("The .bits file contains no bits")

    return [int(c) for c in bits]


def smooth_edges(x, alpha):
    if alpha >= 1:
        return x.copy()

    y = np.empty_like(x, dtype=float)
    y[0] = x[0]

    for i in range(1, len(x)):
        y[i] = y[i - 1] + alpha * (x[i] - y[i - 1])

    return y


def add_ringing(x, strength):
    if strength <= 0:
        return x.copy()

    y = x.copy()
    transitions = np.flatnonzero(np.diff(np.signbit(x)) != 0) + 1

    n = np.arange(18)
    kernel = strength * (0.82 ** n) * np.sin(2 * np.pi * n / 3.2)

    for pos in transitions:
        end = min(len(y), pos + len(kernel))
        y[pos:end] += kernel[:end - pos]

    return y


def main():
    p = argparse.ArgumentParser(
        description="Generate a synthetic Manchester capture from a file"
    )
    p.add_argument("input", help=".hex, .bin o .bits")
    p.add_argument("-o", "--output",
                   help="Output NPZ; defaults to the input name")
    p.add_argument("--samplerate", type=float, default=50e6)
    p.add_argument("--bitrate", type=float, default=DEFAULT_BITRATE)
    p.add_argument("--duration-us", type=float, default=200.0)
    p.add_argument("--start-us", type=float, default=100.0)
    p.add_argument("--amplitude", type=float, default=1850.0)
    p.add_argument("--noise", type=float, default=24.0)
    p.add_argument("--edge-alpha", type=float, default=0.70)
    p.add_argument("--ringing", type=float, default=90.0)
    p.add_argument("--seed", type=int, default=12345)

    order = p.add_mutually_exclusive_group()
    order.add_argument("--lsb-first", action="store_true",
                       help="Bytes LSB-first (por defecto)")
    order.add_argument("--msb-first", action="store_true")

    args = p.parse_args()

    src = Path(args.input)
    suffix = src.suffix.lower()

    if suffix == ".hex":
        raw = read_hex(src)
        bits = bytes_to_bits(raw, lsb_first=not args.msb_first)
        source_kind = "hex"
    elif suffix == ".bin":
        raw = src.read_bytes()
        bits = bytes_to_bits(raw, lsb_first=not args.msb_first)
        source_kind = "bin"
    elif suffix == ".bits":
        raw = None
        bits = read_bits(src)
        source_kind = "bits"
    else:
        raise SystemExit("Input must be .hex, .bin, or .bits")

    fs = float(args.samplerate)
    n_total = int(round(args.duration_us * 1e-6 * fs))
    start = int(round(args.start_us * 1e-6 * fs))

    if not (0 <= start < n_total):
        raise SystemExit("--start-us falls outside the capture")

    waveform = sample_levels(
        manchester_halves(bits),
        fs,
        args.bitrate
    )

    if start + len(waveform) > n_total:
        raise SystemExit(
            "The signal does not fit in the capture. "
            "Aumenta --duration-us o reduce --start-us."
        )

    analog = waveform * args.amplitude
    analog = smooth_edges(analog, args.edge_alpha)
    analog = add_ringing(analog, args.ringing)

    diff = np.zeros(n_total, dtype=float)
    diff[start:start + len(analog)] = analog

    rng = np.random.default_rng(args.seed)

    # Mimic the display offsets observed on the DOS1102.
    ch1 = (
        1008.0
        + diff / 2
        + rng.normal(0, args.noise, n_total)
    )
    ch2 = (
        -1008.0
        - diff / 2
        + rng.normal(0, args.noise, n_total)
    )

    ch1 = np.rint(ch1).astype(np.int16)
    ch2 = np.rint(ch2).astype(np.int16)

    duration_s = n_total / fs

    metadata = {
        "SYNTHETIC": True,
        "GENERATOR": "generate_manchester.py",
        "TIMEBASE": {
            "SCALE": "synthetic",
            "HOFFSET": 0
        },
        "SAMPLE": {
            "DATALEN": n_total,
            "SAMPLERATE": f"({fs / 1e6:g}MS/s)",
            "TYPE": "SAMPle",
            "DEPMEM": f"{n_total / 1000:g}K",
            "SCREENOFFSET": start
        },
        "DATATYPE": "SYNTHETIC",
        "RUNSTATUS": "STOP",
        "synthetic": {
            "input_file": src.name,
            "input_type": source_kind,
            "bit_order": (
                "raw-bits"
                if source_kind == "bits"
                else ("msb-first" if args.msb_first else "lsb-first")
            ),
            "bitrate": args.bitrate,
            "start_us": args.start_us,
            "amplitude": args.amplitude,
            "noise_sigma": args.noise,
            "edge_alpha": args.edge_alpha,
            "ringing": args.ringing,
            "seed": args.seed
        }
    }

    info = {
        "samplerate_hz": fs,
        "datalen": n_total,
        "duration_s": duration_s,
        "duration_us": duration_s * 1e6,
        "sample_period_ns": 1e9 / fs,
        "samples_per_bit": fs / args.bitrate
    }

    out = (
        Path(args.output)
        if args.output
        else src.with_suffix(".npz")
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        out,
        ch1=ch1[np.newaxis, :],
        ch2=ch2[np.newaxis, :],
        timestamps=np.asarray([0.0]),
        metadata_json=np.asarray([json.dumps(metadata)]),
        capture_info_json=np.asarray([json.dumps(info)]),
        samplerate_hz=np.asarray([fs]),
        duration_us=np.asarray([duration_s * 1e6]),
        samples_per_10base_bit=np.asarray([fs / args.bitrate])
    )

    print("Input           :", src)
    print("Bits            :", len(bits))
    if raw is not None:
        print("Bytes           :", len(raw))
    print("Samplerate      :", fs / 1e6, "MS/s")
    print("Samples/bit     :", fs / args.bitrate)
    print("Start           :", args.start_us, "us")
    print("Output          :", out)


if __name__ == "__main__":
    main()

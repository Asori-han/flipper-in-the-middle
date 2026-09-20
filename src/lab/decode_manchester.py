#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np


from ethernet import ethernet_summary
from manchester import (DEFAULT_BITRATE, samplerate_hz, recover_logic,
    recover_bit_grid, decode_bits, trim_trailing_invalid, bits_to_bytes_lsb,
    capture_channels)


def write_hex(path, data):
    lines = []
    for i in range(0, len(data), 16):
        lines.append(" ".join(f"{b:02x}" for b in data[i:i + 16]))
    Path(path).write_text("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(
        description="Decode Manchester from a DOS1102 NPZ capture"
    )
    p.add_argument("npz")
    p.add_argument("-o", "--output", required=True,
                   help="Output .hex, .bin, or .bits")
    p.add_argument("--capture", type=int, default=1,
                   help="1-based acquisition number within the NPZ")
    p.add_argument("--threshold", type=float, default=300)
    p.add_argument("--bitrate", type=float, default=DEFAULT_BITRATE)
    p.add_argument("--baseline-samples", type=int, default=4000)
    p.add_argument("--allow-invalid", action="store_true",
                   help="Allow '?' in .bits output; .hex/.bin still require valid bits")
    args = p.parse_args()

    z = np.load(args.npz, allow_pickle=True)
    index = args.capture - 1

    ch1, ch2 = capture_channels(z, index)
    fs = samplerate_hz(z, index)

    diff = ch1 - ch2
    quiet_len = min(args.baseline_samples, len(diff) // 2)
    baseline = np.median(diff[:quiet_len])
    d = diff - baseline

    active = np.flatnonzero(np.abs(d) > args.threshold)
    if not len(active):
        raise SystemExit("No burst was detected")

    start = int(active[0])
    end = int(active[-1])

    logic = recover_logic(d, args.threshold)
    if args.bitrate == DEFAULT_BITRATE:
        boundary, first_center, bit_samples = recover_bit_grid(d, start, fs)
    else:
        bit_samples = fs / args.bitrate
        first_center = first_zero_crossing(d, start, end)
        boundary = first_center - bit_samples / 2

    count = int(round((end + 1 - boundary) / bit_samples))
    bits = decode_bits(logic, boundary, bit_samples, count)
    bits = trim_trailing_invalid(bits)

    invalid = sum(b is None for b in bits)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()

    if suffix == ".bits":
        if invalid and not args.allow_invalid:
            raise SystemExit(
                f"There are {invalid} invalid Manchester bits; "
                "use --allow-invalid to write them as '?'"
            )
        text = "".join("?" if b is None else str(b) for b in bits)
        out.write_text(text + "\n")
        data = None

    elif suffix in (".hex", ".bin"):
        data = bits_to_bytes_lsb(bits)

        if suffix == ".hex":
            write_hex(out, data)
        else:
            out.write_bytes(data)

    else:
        raise SystemExit("Output must end in .hex, .bin, or .bits")

    print("Capture          :", args.capture)
    print("Samplerate       :", fs / 1e6, "MS/s")
    print("Samples/bit      :", bit_samples)
    print("Burst samples     :", start, "->", end)
    print("Primer centro    :", first_center)
    print("Bits recuperados :", len(bits))
    print("Invalid bits      :", invalid)

    if data is not None:
        print("Bytes recuperados:", len(data))

        summary = ethernet_summary(data)
        if summary:
            print()
            print("Ethernet:")
            for key, value in summary.items():
                print(f"  {key}: {value}")

    print()
    print("Saved:", out)


if __name__ == "__main__":
    main()

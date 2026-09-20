#!/usr/bin/env python3
"""Import a Logic 2 digital burst into the laboratory NPZ format.

Logic 2 exports state changes rather than one sample per clock period. This
program selects a burst and reconstructs the uniform grid used by
``decode_manchester.py``. Values are scaled from 0/1 to 0/1000 to preserve the
pipeline's historical threshold of 300.
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def read_events(path, channel_a, channel_b):
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not fields:
            raise ValueError("The CSV has no header")
        time_field = next((name for name in fields if name.lower().startswith("time")), None)
        if time_field is None:
            raise ValueError("No time column was found")
        for channel in (channel_a, channel_b):
            if channel not in fields:
                raise ValueError(f"Column {channel!r} was not found")

        rows = list(reader)

    if len(rows) < 2:
        raise ValueError("The CSV requires at least two events")

    times = np.asarray([float(row[time_field]) for row in rows], dtype=float)
    states = np.asarray(
        [[int(row[channel_a]), int(row[channel_b])] for row in rows],
        dtype=np.int8,
    )
    if np.any(np.diff(times) < 0):
        raise ValueError("Events are not ordered by time")
    if np.any((states != 0) & (states != 1)):
        raise ValueError("Digital channels may contain only 0 or 1")
    return times, states


def find_bursts(times, gap_seconds=10e-6, min_events=100):
    """Return inclusive intervals separated by gaps longer than the threshold."""
    starts = np.r_[0, np.flatnonzero(np.diff(times) > gap_seconds) + 1]
    ends = np.r_[starts[1:] - 1, len(times) - 1]
    return [
        (int(start), int(end))
        for start, end in zip(starts, ends)
        if end - start + 1 >= min_events
    ]


def resample_burst(times, states, burst, samplerate, padding_seconds):
    first, last = burst
    start = max(float(times[0]), float(times[first]) - padding_seconds)
    end = min(float(times[-1]), float(times[last]) + padding_seconds)
    count = max(2, int(np.ceil((end - start) * samplerate)) + 1)
    grid = start + np.arange(count, dtype=float) / samplerate
    indices = np.searchsorted(times, grid, side="right") - 1
    sampled = states[np.maximum(indices, 0)].astype(np.int16) * 1000
    return start, end, sampled


def print_bursts(times, bursts):
    print("N  start [s]         duration [us] events")
    for number, (first, last) in enumerate(bursts, 1):
        duration_us = (times[last] - times[first]) * 1e6
        print(f"{number:<2} {times[first]:<16.9f} {duration_us:>13.3f}  {last-first+1}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Logic 2 digital export to the laboratory NPZ format"
    )
    parser.add_argument("csv")
    parser.add_argument("-o", "--output")
    parser.add_argument("--burst", type=int, help="1-based burst to import")
    parser.add_argument("--list-bursts", action="store_true")
    parser.add_argument("--channel-a", default="Channel 0")
    parser.add_argument("--channel-b", default="Channel 1")
    parser.add_argument("--samplerate", type=float, default=24_000_000)
    parser.add_argument("--gap-us", type=float, default=10)
    parser.add_argument("--min-events", type=int, default=100)
    parser.add_argument("--padding-us", type=float, default=10)
    args = parser.parse_args()

    if args.samplerate <= 0 or args.gap_us <= 0 or args.padding_us < 0:
        parser.error("sample rate and gap must be positive; padding cannot be negative")

    try:
        times, states = read_events(args.csv, args.channel_a, args.channel_b)
        bursts = find_bursts(times, args.gap_us * 1e-6, args.min_events)
    except ValueError as error:
        parser.error(str(error))

    if args.list_bursts or args.burst is None:
        print_bursts(times, bursts)
    if args.burst is None:
        if not args.list_bursts:
            parser.error("specify --burst N to create the NPZ")
        return
    if not args.output:
        parser.error("--output is required when selecting a burst")
    if not 1 <= args.burst <= len(bursts):
        parser.error(f"burst must be between 1 and {len(bursts)}")

    burst = bursts[args.burst - 1]
    start, end, sampled = resample_burst(
        times, states, burst, args.samplerate, args.padding_us * 1e-6
    )
    first, last = burst
    metadata = {
        "instrument": "Saleae Logic",
        "source_format": "Logic 2 raw digital CSV",
        "source_file": Path(args.csv).name,
        "channels": [args.channel_a, args.channel_b],
        "burst": args.burst,
        "burst_start_s": float(times[first]),
        "burst_end_s": float(times[last]),
        "event_count": last - first + 1,
        "sampling_note": "States reconstructed from quantized digital events",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        ch1=sampled[:, 0],
        ch2=sampled[:, 1],
        samplerate_hz=args.samplerate,
        duration_us=(end - start) * 1e6,
        sample_period_ns=1e9 / args.samplerate,
        samples_per_10base_bit=args.samplerate / 10_000_000,
        metadata_json=json.dumps(metadata),
    )
    print(
        f"Saved: {output} ({len(sampled)} samples, "
        f"{args.samplerate/1e6:g} MS/s, burst {args.burst})"
    )


if __name__ == "__main__":
    main()

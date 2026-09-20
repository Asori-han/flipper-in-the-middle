#!/usr/bin/env python3
"""Sanitize MAC addresses in a Logic 2 W5500 SPI CSV export."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from packet import load_mac_map


CHANNELS = ("mosi", "miso")


def _transactions(path: Path):
    """Yield one transaction at a time, bounding memory by the largest transfer."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        transaction = None
        for row in csv.DictReader(stream):
            kind = row["type"].strip().lower()
            if kind == "enable":
                transaction = [row]
            elif transaction is not None:
                transaction.append(row)
                if kind == "disable":
                    yield transaction
                    transaction = None


def _find_replacements(path: Path, mapping: dict[bytes, bytes]):
    """Find MACs over each channel's concatenated data stream, excluding headers."""
    positions = {channel: {} for channel in CHANNELS}
    carry = {channel: b"" for channel in CHANNELS}
    totals = {channel: 0 for channel in CHANNELS}
    for rows in _transactions(path):
        results = [row for row in rows if row["type"].strip().lower() == "result"]
        for channel in CHANNELS:
            values = bytes(int(row.get(channel, "").strip().removeprefix("0x") or "0", 16)
                           for row in results)
            payload = values[3:]
            prefix = carry[channel]
            combined = prefix + payload
            base = totals[channel] - len(prefix)
            for source, target in mapping.items():
                offset = 0
                while True:
                    offset = combined.find(source, offset)
                    if offset < 0:
                        break
                    absolute = base + offset
                    for index, value in enumerate(target):
                        positions[channel][absolute + index] = value
                    offset += len(source)
            totals[channel] += len(payload)
            carry[channel] = combined[-5:]
    return positions


def sanitize_csv(source: Path, output: Path, mapping: dict[bytes, bytes]) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    replacements = _find_replacements(source, mapping)
    count = sum(len(values) for values in replacements.values()) // 6
    with source.open(newline="", encoding="utf-8-sig") as src, output.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        active = False
        result_index = {channel: 0 for channel in CHANNELS}
        payload_index = {channel: 0 for channel in CHANNELS}
        for row in reader:
            kind = row["type"].strip().lower()
            if kind == "enable":
                active = True
                result_index = {channel: 0 for channel in CHANNELS}
            elif kind == "result" and active:
                for channel in CHANNELS:
                    index = result_index[channel]
                    if index >= 3:
                        value = int(row.get(channel, "").strip().removeprefix("0x") or "0", 16)
                        value = replacements[channel].get(payload_index[channel], value)
                        row[channel] = f"0x{value:02x}"
                        payload_index[channel] += 1
                    result_index[channel] += 1
            elif kind == "disable":
                active = False
            writer.writerow(row)
    return count


def assert_sanitized(path: Path, mapping: dict[bytes, bytes]) -> None:
    """Fail closed if any mapped address remains in a transaction's data bytes."""
    if any(_find_replacements(path, mapping).values()):
        raise ValueError("An original MAC remains in the sanitized SPI data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mac-map", type=Path, required=True)
    args = parser.parse_args()
    mapping = {source: target for source, target in load_mac_map(args.mac_map).items()
               if source != target}
    count = sanitize_csv(args.source, args.output, mapping)
    assert_sanitized(args.output, mapping)
    print(f"Sanitized SPI CSV written; mapped occurrences: {count}")


if __name__ == "__main__":
    main()

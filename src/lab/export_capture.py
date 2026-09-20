#!/usr/bin/env python3
"""Generate HEX, layered JSON and PCAPNG artifacts from a sanitized NPZ."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

import numpy as np

from manchester import capture_channels, capture_value, samplerate_hz
from packet import PacketError, analyze_ethernet_frame
from sanitize_capture import decode_waveform


def _option(code: int, value: bytes) -> bytes:
    padding = b"\x00" * ((-len(value)) % 4)
    return struct.pack("<HH", code, len(value)) + value + padding


def _block(kind: int, body: bytes) -> bytes:
    body += b"\x00" * ((-len(body)) % 4)
    length = 12 + len(body)
    return struct.pack("<II", kind, length) + body + struct.pack("<I", length)


def write_pcapng(path: Path, packets: list[tuple[int, bytes]]):
    section = _block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    options = _option(9, b"\x06") + _option(13, b"\x04") + _option(0, b"")
    interface = _block(1, struct.pack("<HHI", 1, 0, 65535) + options)
    enhanced = []
    for timestamp_us, packet in packets:
        padding = b"\x00" * ((-len(packet)) % 4)
        header = struct.pack("<IIIII", 0, timestamp_us >> 32, timestamp_us & 0xFFFFFFFF,
                             len(packet), len(packet))
        enhanced.append(_block(6, header + packet + padding + _option(0, b"")))
    path.write_bytes(section + interface + b"".join(enhanced))


def write_hex(path: Path, wires: list[bytes]):
    lines = []
    for capture, wire in enumerate(wires, 1):
        if len(wires) > 1:
            lines.append(f"# Acquisition {capture}")
        for offset in range(0, len(wire), 16):
            lines.append(" ".join(f"{byte:02x}" for byte in wire[offset:offset + 16]))
        if capture != len(wires):
            lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("npz", help="Sanitized capture")
    parser.add_argument("-o", "--output-prefix", required=True)
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="override the stored sanitization threshold (default: stored value or 300)")
    args = parser.parse_args()
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)

    try:
        wires, packets, reports = [], [], []
        with np.load(args.npz, allow_pickle=True) as source:
            count = 1 if source["ch1"].ndim == 1 else len(source["ch1"])
            for index in range(count):
                raw_metadata = capture_value(source, "metadata_json", index)
                if isinstance(raw_metadata, bytes):
                    raw_metadata = raw_metadata.decode()
                metadata = json.loads(str(raw_metadata))
                if metadata.get("sanitized") is not True:
                    raise PacketError("Input is not marked as sanitized")
                ch1, ch2 = capture_channels(source, index)
                fs = samplerate_hz(source, index)
                threshold = args.threshold
                if threshold is None:
                    threshold = metadata.get("sanitization", {}).get(
                        "decode_threshold", 300)
                _, _, _, _, wire = decode_waveform(ch1, ch2, fs, float(threshold))
                frame = wire[8:]
                report = analyze_ethernet_frame(frame)
                if not report["ethernet"]["fcs_valid"]:
                    raise PacketError("The FCS is invalid")
                try:
                    timestamp = float(capture_value(source, "timestamps", index))
                except (KeyError, TypeError, ValueError):
                    timestamp = float(index)
                timestamp_us = max(0, round(timestamp * 1_000_000))
                wires.append(wire)
                packets.append((timestamp_us, frame))
                reports.append({
                    "acquisition": index + 1,
                    "physical": {
                        "encoding": "Manchester 10BASE-T",
                        "bitrate": 10_000_000,
                        "samplerate_hz": fs,
                        "preamble": "55 55 55 55 55 55 55",
                        "sfd": "d5",
                    },
                    **report,
                })
        write_hex(prefix.with_suffix(".hex"), wires)
        write_pcapng(prefix.with_suffix(".pcapng"), packets)
        prefix.with_suffix(".json").write_text(json.dumps(
            {"source": Path(args.npz).name, "captures": reports}, indent=2) + "\n")
    except (PacketError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Export cancelled: {exc}") from None

    print(f"Acquisitions: {len(wires)}")
    print("HEX          :", prefix.with_suffix(".hex"))
    print("Layers JSON  :", prefix.with_suffix(".json"))
    print("PCAPNG       :", prefix.with_suffix(".pcapng"))


if __name__ == "__main__":
    main()

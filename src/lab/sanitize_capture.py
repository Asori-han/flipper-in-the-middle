#!/usr/bin/env python3
"""Sanitize every configured MAC occurrence in a captured 10BASE-T frame."""
from __future__ import annotations

import argparse
import binascii
import json
from pathlib import Path

import numpy as np

from manchester import (DEFAULT_BITRATE as BITRATE, samplerate_hz, recover_logic,
    first_zero_crossing, recover_bit_grid, decode_bits, trim_trailing_invalid,
    bits_to_bytes_lsb, capture_channels, capture_value)
from packet import (PacketError, load_mac_map, metadata_contains_original,
                    sanitize_ethernet_frame, sanitize_metadata)


def desired_half_sign(bit, half):
    if bit == 0:
        return 1 if half == 0 else -1
    return -1 if half == 0 else 1


def replace_byte_waveform(d, boundary, bit_samples, wire_byte_index, value):
    """Replace Manchester polarity while retaining the real sample envelope."""
    for bit_in_byte in range(8):
        bit = (value >> bit_in_byte) & 1
        global_bit = wire_byte_index * 8 + bit_in_byte
        bit_start = boundary + global_bit * bit_samples
        bit_end = bit_start + bit_samples
        midpoint = bit_start + bit_samples / 2
        first_sample = max(0, int(np.floor(bit_start)))
        last_sample = min(len(d), int(np.ceil(bit_end)) + 1)
        for index in range(first_sample, last_sample):
            sample_center = index + 0.5
            if bit_start <= sample_center < bit_end:
                half = 0 if sample_center < midpoint else 1
                d[index] = desired_half_sign(bit, half) * abs(float(d[index]))


def decode_waveform(ch1, ch2, fs, threshold):
    difference = ch1.astype(float) - ch2.astype(float)
    baseline = np.median(difference[:min(4000, len(difference) // 2)])
    centered = difference - baseline
    active = np.flatnonzero(np.abs(centered) > threshold)
    if not len(active):
        raise PacketError("No frame was detected")
    # Prefer a clock fitted from the regular preamble crossings. Real DOS1102
    # captures are close to, but not exactly, five samples per bit; using only
    # the nominal value can accumulate enough phase error to reject the end of a
    # valid frame. Keep the nominal grid as a fallback because a noisy preamble
    # can occasionally make that fit worse. The FCS decides between them.
    fitted_boundary, _first_center, fitted_bit_samples = recover_bit_grid(
        centered, int(active[0]), fs)
    nominal_bit_samples = fs / BITRATE
    nominal_boundary = (
        first_zero_crossing(centered, int(active[0]), int(active[-1]))
        - nominal_bit_samples / 2
    )
    grids = (
        (fitted_boundary, fitted_bit_samples),
        (nominal_boundary, nominal_bit_samples),
    )
    logic = recover_logic(centered, threshold)
    for boundary, bit_samples in grids:
        count = int(round((int(active[-1]) + 1 - boundary) / bit_samples))
        try:
            bits = trim_trailing_invalid(
                decode_bits(logic, boundary, bit_samples, count))
            wire = bits_to_bytes_lsb(bits)
        except RuntimeError:
            continue
        if len(wire) < 26 or wire[:8] != b"\x55" * 7 + b"\xd5":
            continue
        frame = wire[8:]
        if len(frame) >= 4 and (
            binascii.crc32(frame[:-4]) & 0xFFFFFFFF
        ) == int.from_bytes(frame[-4:], "little"):
            return centered, baseline, boundary, bit_samples, wire
    raise PacketError(
        "No complete Ethernet frame with preamble, SFD and valid FCS was recognized")


def sample_ranges(changed_samples):
    groups = np.split(changed_samples, np.flatnonzero(np.diff(changed_samples) > 1) + 1)
    return [[int(group[0]), int(group[-1]) + 1] for group in groups if len(group)]


def main():
    parser = argparse.ArgumentParser(
        description="Sanitize every configured MAC in a 10BASE-T capture")
    parser.add_argument("npz")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--mac-map", required=True,
                        help="Private JSON map from original to replacement MAC addresses")
    parser.add_argument("--capture", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=300)
    args = parser.parse_args()

    try:
        mapping = load_mac_map(args.mac_map)
        with np.load(args.npz, allow_pickle=True) as source:
            index = args.capture - 1
            ch1, ch2 = capture_channels(source, index)
            fs = samplerate_hz(source, index)
            centered, baseline, boundary, bit_samples, wire = decode_waveform(
                ch1, ch2, fs, args.threshold)
            clean_frame, report = sanitize_ethernet_frame(wire[8:], mapping)
            clean_wire = wire[:8] + clean_frame

            centered_new = centered.copy()
            changed_wire_indices = [8 + offset for offset in report["changed_frame_offsets"]]
            for wire_index in changed_wire_indices:
                replace_byte_waveform(centered_new, boundary, bit_samples,
                                      wire_index, clean_wire[wire_index])

            common = (ch1 + ch2) / 2.0
            ch1_new = np.rint(common + (centered_new + baseline) / 2.0).astype(np.int16)
            ch2_new = np.rint(common - (centered_new + baseline) / 2.0).astype(np.int16)

            _, _, _, _, verified_wire = decode_waveform(ch1_new, ch2_new, fs, args.threshold)
            if verified_wire != clean_wire:
                raise PacketError("The sanitized signal does not reproduce the expected bytes exactly")

            meta_raw = capture_value(source, "metadata_json", index)
            if isinstance(meta_raw, bytes):
                meta_raw = meta_raw.decode()
            metadata = sanitize_metadata(json.loads(str(meta_raw)), mapping)

        changed = np.flatnonzero((ch1_new != ch1) | (ch2_new != ch2))
        metadata["sanitized"] = True
        metadata["sanitization"] = {
            "tool": "sanitize_capture.py",
            "source_capture": args.capture,
            "modified_sample_ranges": sample_ranges(changed),
            "sample_range_convention": "zero-based, end-exclusive",
            "semantic_fields": report["semantic_fields"],
            "mapped_occurrences": report["mapped_occurrences"],
            "checksums_repaired": report["checksums_repaired"],
            "decode_threshold": args.threshold,
            "method": ("Manchester polarity replaced only in affected waveform regions; "
                       "per-sample magnitude and common-mode retained"),
            "original_values_retained": False,
        }
        if metadata_contains_original(metadata, mapping):
            raise PacketError("An original MAC remains in metadata; output was not written")

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            output,
            ch1=ch1_new[np.newaxis, :],
            ch2=ch2_new[np.newaxis, :],
            timestamps=np.asarray([0.0]),
            metadata_json=np.asarray([json.dumps(metadata)]),
            samplerate_hz=np.asarray([fs]),
            duration_us=np.asarray([len(ch1_new) / fs * 1e6]),
            samples_per_10base_bit=np.asarray([fs / BITRATE]),
        )
    except (PacketError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Sanitization cancelled: {exc}") from None

    print(f"Campos MAC saneados : {len(report['semantic_fields'])}")
    print(f"Coincidencias totales: {report['mapped_occurrences']}")
    print("Integridad reparada  : " + ", ".join(report["checksums_repaired"]))
    print("Verification         : Manchester, bytes, and checksums are correct")
    print("Output               :", output)


if __name__ == "__main__":
    main()

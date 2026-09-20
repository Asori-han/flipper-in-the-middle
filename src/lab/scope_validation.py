"""Closed validation of Ethernet frames recovered from the DOS1102."""

import binascii

import numpy as np

try:
    from .manchester import decode_bits, recover_bit_grid, recover_logic, trim_trailing_invalid
except ImportError:  # direct execution from src/lab/
    from manchester import decode_bits, recover_bit_grid, recover_logic, trim_trailing_invalid


PREAMBLE_SFD = b"\x55" * 7 + b"\xd5"


def _bits_to_bytes(bits):
    usable = len(bits) - len(bits) % 8
    if any(bit is None for bit in bits[:usable]):
        return b""
    return bytes(sum(bits[pos + bit] << bit for bit in range(8)) for pos in range(0, usable, 8))


def _valid_frame(data):
    start = data.find(PREAMBLE_SFD)
    if start < 0:
        return None
    frame_start = start + len(PREAMBLE_SFD)
    for end in range(frame_start + 64, len(data) + 1):
        frame = data[frame_start:end]
        stored = int.from_bytes(frame[-4:], "little")
        if stored == (binascii.crc32(frame[:-4]) & 0xFFFFFFFF):
            return frame
    return None


def _payload_pattern(frame):
    if len(frame) >= 14 + 28 + 4 and frame[12:14] == b"\x08\x06":
        opcode = int.from_bytes(frame[20:22], "big")
        return "arp" if opcode in (1, 2) else "other"
    if len(frame) < 14 + 20 + 4 or frame[12:14] != b"\x08\x00":
        return None
    ip = 14
    ihl = (frame[ip] & 0x0F) * 4
    total = int.from_bytes(frame[ip + 2:ip + 4], "big")
    if ihl < 20 or total < ihl:
        return None
    protocol = frame[ip + 9]
    if protocol == 1 and total >= ihl + 8:
        payload = frame[ip + ihl + 8:ip + total]
        if not payload:
            return None
        for value, name in ((0x00, "00"), (0xFF, "ff"), (0x55, "55"), (0xAA, "aa")):
            if all(byte == value for byte in payload):
                return name
        if all(payload[index] == index & 0xFF for index in range(len(payload))):
            return "increment"
    if protocol == 6 and total >= ihl + 20:
        tcp = ip + ihl
        source_port = int.from_bytes(frame[tcp:tcp + 2], "big")
        destination_port = int.from_bytes(frame[tcp + 2:tcp + 4], "big")
        tcp_header = (frame[tcp + 12] >> 4) * 4
        if tcp_header >= 20 and total >= ihl + tcp_header:
            payload = frame[tcp + tcp_header:ip + total]
            if payload.startswith((b"GET ", b"HEAD ")):
                return "http"
            if source_port == 80 or destination_port == 80:
                return "tcp80"
    return "other"


def _segments(signal, threshold, gap_samples):
    active = np.flatnonzero(np.abs(signal) > threshold)
    if not len(active):
        return []
    cuts = np.flatnonzero(np.diff(active) > gap_samples)
    starts = np.r_[0, cuts + 1]
    ends = np.r_[cuts, len(active) - 1]
    return [(int(active[a]), int(active[b])) for a, b in zip(starts, ends)]


def recover_scope_frames(
    captures,
    threshold=300,
    decode_threshold=None,
):
    """Recover frames supported by a valid preamble, SFD, and FCS."""
    # The activity threshold must reject noise between frames. To decide
    # semibits, use a lower threshold: DOS1102 amplitude varies with frame
    # contents, and some valid levels fall below the threshold used to
    # detect activity.
    if decode_threshold is None:
        decode_thresholds = (
            threshold / 15,
            threshold / 6,
            threshold / 3,
            threshold * 2 / 3,
            threshold,
            threshold * 1.5,
            threshold * 2,
            threshold * 3,
        )
    else:
        decode_thresholds = (decode_threshold,)
    frames = []
    for capture_index, (meta, ch1, ch2, timestamp) in enumerate(captures, 1):
        rate_text = meta["SAMPLE"]["SAMPLERATE"].strip("()")
        factor = 1e6 if rate_text.endswith("MS/s") else 1e3 if rate_text.endswith("KS/s") else 1
        fs = float(rate_text.split("S/s")[0][:-1]) * factor if factor != 1 else float(rate_text[:-3])
        signal = np.asarray(ch1, dtype=float) - np.asarray(ch2, dtype=float)
        signal -= np.median(signal)
        gap_samples = max(2, int(round(fs * 2e-6)))
        for start, end in _segments(signal, threshold, gap_samples):
            if end - start < int(fs * 40e-6):
                continue
            try:
                boundary, _center, samples_per_bit = recover_bit_grid(signal, start, fs)
            except RuntimeError:
                continue
            count = int(round((end + 1 - boundary) / samples_per_bit))
            found = False
            for slicing_threshold in decode_thresholds:
                logic = recover_logic(signal, slicing_threshold)
                bits = trim_trailing_invalid(
                    decode_bits(logic, boundary, samples_per_bit, count)
                )
                if any(bit is None for bit in bits):
                    continue
                decoded = _bits_to_bytes(bits)
                for candidate, inverted in (
                    (decoded, False),
                    (bytes(byte ^ 0xFF for byte in decoded), True),
                ):
                    frame = _valid_frame(candidate)
                    if frame is not None:
                        frames.append({
                            "capture": capture_index,
                            "timestamp_seconds": round(float(timestamp), 6),
                            "frame_bytes_with_fcs": len(frame),
                            "pattern": _payload_pattern(frame),
                            "polarity_inverted": inverted,
                            "frame": frame,
                        })
                        found = True
                        break
                if found:
                    break
    return frames


def validate_scope_captures(
    captures,
    threshold=300,
    decode_threshold=None,
    required_patterns=None,
):
    """Return patterns supported by a valid preamble, SFD, and FCS."""
    recovered = recover_scope_frames(captures, threshold, decode_threshold)
    frames = [
        {key: value for key, value in item.items() if key != "frame"}
        for item in recovered
    ]
    patterns = sorted({item["pattern"] for item in frames if item["pattern"]})
    required = set(required_patterns or {"increment", "00", "ff", "55", "aa"})
    return {
        "passed": required.issubset(patterns),
        "required_patterns": sorted(required),
        "captured_patterns": patterns,
        "missing_patterns": sorted(required - set(patterns)),
        "valid_frames": frames,
    }

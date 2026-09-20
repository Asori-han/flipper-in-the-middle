"""Manchester signal primitives, independent of Ethernet and USB."""
import json
import numpy as np

DEFAULT_BITRATE = 10_000_000
BITRATE_10BASET = DEFAULT_BITRATE

def capture_value(z, key, index):
    value = np.asarray(z[key])
    return value.item() if value.ndim == 0 else value[index]


def capture_channels(z, index):
    """Accept both single-capture (samples,) and batch (captures, samples) NPZ."""
    a, b = np.asarray(z["ch1"]), np.asarray(z["ch2"])
    if a.shape != b.shape or a.ndim not in (1, 2):
        raise ValueError("Channels must have the same 1D or 2D shape")
    count = 1 if a.ndim == 1 else len(a)
    if not 0 <= index < count:
        raise SystemExit("Acquisition number is out of range")
    a, b = (a, b) if a.ndim == 1 else (a[index], b[index])
    if len(a) < 2:
        raise ValueError("The capture requires at least two samples")
    return a.astype(float), b.astype(float)


def samplerate_hz(z, index):
    if "samplerate_hz" in z.files:
        sr = np.asarray(z["samplerate_hz"])
        return float(sr if sr.ndim == 0 else sr[index])

    meta_raw = capture_value(z, "metadata_json", index)
    if isinstance(meta_raw, bytes):
        meta_raw = meta_raw.decode()

    meta = json.loads(str(meta_raw))
    s = (
        meta["SAMPLE"]["SAMPLERATE"]
        .replace("(", "")
        .replace(")", "")
        .replace("S/s", "")
        .strip()
    )

    if s.endswith("G"):
        return float(s[:-1]) * 1e9
    if s.endswith("M"):
        return float(s[:-1]) * 1e6
    if s.endswith("K"):
        return float(s[:-1]) * 1e3
    return float(s)


def recover_logic(d, threshold):
    logic = np.zeros(len(d), dtype=np.int8)

    if not len(d):
        return logic

    if d[0] > threshold:
        state = 1
    elif d[0] < -threshold:
        state = -1
    else:
        state = 0

    for i, x in enumerate(d):
        if x > threshold:
            state = 1
        elif x < -threshold:
            state = -1
        logic[i] = state

    valid = np.flatnonzero(logic != 0)
    if len(valid):
        logic[:valid[0]] = logic[valid[0]]

    return logic


def first_zero_crossing(d, start, end):
    for i in range(start, min(end, len(d) - 1)):
        if d[i] * d[i + 1] < 0:
            a = abs(d[i])
            b = abs(d[i + 1])
            frac = 0.0 if a + b == 0 else a / (a + b)
            return i + frac
    raise RuntimeError("No zero crossing was found in the burst")


def decode_bits(logic, boundary, bit_samples, count):
    bits = []
    # Sample within each half-bit, away from its center crossing. With five
    # samples per bit, rounding 0.20 bits first left only one sample of
    # separation and still landed on some real DOS1102 edges.
    delta = max(1.0, bit_samples * 0.25)

    for n in range(count):
        center = boundary + (n + 0.5) * bit_samples
        pre = int(round(center - delta))
        post = int(round(center + delta))

        if pre < 0 or post >= len(logic):
            bits.append(None)
            continue

        a = int(logic[pre])
        b = int(logic[post])

        if a == 1 and b == -1:
            bits.append(0)
        elif a == -1 and b == 1:
            bits.append(1)
        else:
            bits.append(None)

    return bits


def trim_trailing_invalid(bits):
    bits = list(bits)
    while bits and bits[-1] is None:
        bits.pop()
    return bits


def bits_to_bytes_lsb(bits):
    if any(b is None for b in bits):
        first = bits.index(None)
        raise RuntimeError(
            f"Invalid Manchester encoding at bit {first}; "
            "use --allow-invalid to export .bits only"
        )

    usable = len(bits) - (len(bits) % 8)
    bits = bits[:usable]

    out = bytearray()
    for pos in range(0, usable, 8):
        value = sum(bits[pos + k] << k for k in range(8))
        out.append(value)

    return bytes(out)


def crossing_position(d, i):
    """Return the fractional position of a zero crossing between i and i+1."""
    a = abs(d[i])
    b = abs(d[i + 1])
    if a + b == 0:
        return float(i)
    return i + a / (a + b)


def recover_bit_grid(d, burst_start, fs):
    """
    Recover the initial phase from the first zero crossing in the burst.
    Each 10BASE-T bit lasts 100 ns.
    """
    search_end = min(len(d) - 1, burst_start + int(fs * 10e-6))

    crossings = []
    for i in range(burst_start, search_end):
        if d[i] * d[i + 1] < 0:
            crossings.append(crossing_position(d, i))

    if not crossings:
        raise RuntimeError("No crossings were found to recover Manchester phase")

    nominal_bit_samples = fs / BITRATE_10BASET
    # The first seven Ethernet bytes are 0x55. Their 56 center crossings form a
    # regular reference used to measure the PHY clock without accumulating drift.
    reference = crossings[:56]
    regular = len(reference) >= 16 and all(
        nominal_bit_samples * 0.75 <= step <= nominal_bit_samples * 1.25
        for step in np.diff(reference)
    )
    if regular:
        positions = np.arange(len(reference), dtype=float)
        bit_samples, first_center_sample = np.polyfit(positions, reference, 1)
    else:
        bit_samples = nominal_bit_samples
        first_center_sample = crossings[0]
    first_boundary_sample = first_center_sample - bit_samples / 2

    return first_boundary_sample, first_center_sample, bit_samples


def byte_labels_lsb(bits):
    out = []
    for pos in range(0, len(bits), 8):
        chunk = bits[pos:pos + 8]
        if len(chunk) < 8 or any(b is None for b in chunk):
            out.append(None)
            continue

        value = sum(bit << k for k, bit in enumerate(chunk))
        out.append(value)

    return out


def bytes_to_bits(data, lsb_first):
    bits = []
    for b in data:
        order = range(8) if lsb_first else range(7, -1, -1)
        bits.extend((b >> i) & 1 for i in order)
    return bits


def manchester_halves(bits):
    halves = []
    for bit in bits:
        # Convention used by the 10BASE-T decoder:
        # 0 => + to -
        # 1 => - to +
        halves.extend((1.0, -1.0) if bit == 0 else (-1.0, 1.0))
    return np.asarray(halves, dtype=float)


def sample_levels(halves, fs, bitrate):
    halfbit = 1.0 / (2.0 * bitrate)
    duration = len(halves) * halfbit
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    indices = np.floor(t / halfbit).astype(int)
    indices = np.clip(indices, 0, len(halves) - 1)
    return halves[indices]

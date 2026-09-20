import binascii
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'lab'))

from manchester import bytes_to_bits, manchester_halves, sample_levels
from scope_validation import validate_scope_captures


def wire_frame(pattern):
    payload = bytes(range(18)) if pattern == "increment" else bytes([int(pattern, 16)]) * 18
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (20 + 8 + len(payload)).to_bytes(2, "big")
    ip[9] = 1
    icmp = bytes([8, 0, 0, 0, 0, 1, 0, 1]) + payload
    body = bytes.fromhex("0200000000020200000000010800") + bytes(ip) + icmp
    body += bytes(60 - len(body))
    frame = body + binascii.crc32(body).to_bytes(4, "little")
    return b"\x55" * 7 + b"\xd5" + frame


def wire_arp():
    arp = bytes.fromhex(
        "0001080006040001" "020000000001" "c0a807a3"
        "000000000000" "c0a80701"
    )
    body = bytes.fromhex("ffffffffffff0200000000010806") + arp
    body += bytes(60 - len(body))
    return b"\x55" * 7 + b"\xd5" + body + binascii.crc32(body).to_bytes(4, "little")


def wire_http(payload=b"GET / HTTP/1.0\r\n\r\n"):
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (20 + 20 + len(payload)).to_bytes(2, "big")
    ip[9] = 6
    tcp = bytearray(20)
    tcp[0:2] = (49152).to_bytes(2, "big")
    tcp[2:4] = (80).to_bytes(2, "big")
    tcp[12] = 0x50
    tcp[13] = 0x18
    body = bytes.fromhex("0200000000020200000000010800") + bytes(ip) + bytes(tcp) + payload
    body += bytes(max(0, 60 - len(body)))
    return b"\x55" * 7 + b"\xd5" + body + binascii.crc32(body).to_bytes(4, "little")


def capture_wire(wire, corrupt=False, weak_semibits=False):
    wire = bytearray(wire)
    if corrupt:
        wire[-1] ^= 1
    fs = 50_000_000.0
    encoded = sample_levels(manchester_halves(bytes_to_bits(wire, True)), fs, 10_000_000)
    if weak_semibits:
        # Keep the burst easy to detect while attenuating isolated semibits,
        # as observed in the real FF-pattern capture.
        for half in range(140, len(wire) * 16, 37):
            start = int(round(half * fs / 20_000_000))
            end = int(round((half + 1) * fs / 20_000_000))
            encoded[start:end] *= 0.12
    signal = np.zeros(10_000)
    signal[1000:1000 + len(encoded)] = encoded * 1000
    meta = {"SAMPLE": {"SAMPLERATE": "(50MS/s)"}}
    return meta, signal / 2, -signal / 2, 0.0


def capture_for(pattern, corrupt=False, weak_semibits=False):
    return capture_wire(wire_frame(pattern), corrupt, weak_semibits)


class ScopeValidationTests(unittest.TestCase):
    def test_requires_all_patterns_with_valid_fcs(self):
        captures = [capture_for(pattern) for pattern in ("increment", "00", "ff", "55", "aa")]
        result = validate_scope_captures(captures)
        self.assertTrue(result["passed"])
        self.assertEqual(result["missing_patterns"], [])
        self.assertEqual(len(result["valid_frames"]), 5)

    def test_rejects_bad_fcs(self):
        result = validate_scope_captures([capture_for("aa", corrupt=True)])
        self.assertFalse(result["passed"])
        self.assertEqual(result["valid_frames"], [])

    def test_decodes_attenuated_semibits_below_activity_threshold(self):
        result = validate_scope_captures([capture_for("ff", weak_semibits=True)])
        self.assertEqual(result["captured_patterns"], ["ff"])

    def test_can_validate_one_pattern_in_isolation(self):
        result = validate_scope_captures(
            [capture_for("55")], required_patterns={"55"}
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["required_patterns"], ["55"])

    def test_classifies_arp_and_http_frames(self):
        arp = validate_scope_captures(
            [capture_wire(wire_arp())], required_patterns={"arp"}
        )
        http = validate_scope_captures(
            [capture_wire(wire_http())], required_patterns={"http"}
        )
        self.assertTrue(arp["passed"])
        self.assertTrue(http["passed"])

        tcp80 = validate_scope_captures(
            [capture_wire(wire_http(b""))], required_patterns={"tcp80"}
        )
        self.assertTrue(tcp80["passed"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "lab"))

from plot_spi_capture import bytes_to_msb_bits, visible_waveform_bytes


class PlotSpiCaptureTests(unittest.TestCase):
    def test_converts_bytes_to_spi_msb_first_order(self):
        np.testing.assert_array_equal(
            bytes_to_msb_bits(bytes([0x81, 0x55])),
            [1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        )

    def test_collapses_long_constant_suffix_but_keeps_two_bytes(self):
        self.assertEqual(visible_waveform_bytes(b"\x08\x01" + b"\x00" * 32), (4, 30))

    def test_keeps_short_or_varying_suffix(self):
        self.assertEqual(visible_waveform_bytes(bytes(range(16))), (16, 0))
        self.assertEqual(visible_waveform_bytes(b"\x01" + b"\xff" * 7), (8, 0))


if __name__ == "__main__":
    unittest.main()

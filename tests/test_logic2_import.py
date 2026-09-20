import csv
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'lab'))
from import_logic2_csv import find_bursts, read_events, resample_burst


class Logic2ImportTests(unittest.TestCase):
    def test_event_read_burst_detection_and_resampling(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "digital.csv"
            with source.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Time [s]", "Channel 0", "Channel 1"])
                writer.writerows([
                    (0.0, 0, 0),
                    (1e-6, 1, 0),
                    (2e-6, 0, 1),
                    (20e-6, 0, 0),
                    (21e-6, 1, 0),
                    (22e-6, 0, 1),
                ])

            times, states = read_events(source, "Channel 0", "Channel 1")
            bursts = find_bursts(times, gap_seconds=10e-6, min_events=2)
            self.assertEqual(bursts, [(0, 2), (3, 5)])
            start, end, samples = resample_burst(
                times, states, bursts[0], samplerate=1e6, padding_seconds=0
            )
            self.assertEqual((start, end), (0.0, 2e-6))
            np.testing.assert_array_equal(
                samples, np.array([[0, 0], [1000, 0], [0, 1000]], dtype=np.int16)
            )


if __name__ == "__main__":
    unittest.main()

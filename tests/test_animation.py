import os
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/manchester-animation-mpl')
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'src' / 'lab'
sys.path.insert(0, str(LAB))
from animate_capture import Segment, segments_for, segment_frames, frame_positions


class AnimationTests(unittest.TestCase):
    def test_complete_coverage_and_multiple_bursts(self):
        d = np.zeros(400)
        wave = np.repeat([-1000, 1000, 1000, -1000] * 4, 5)
        d[100:180] = wave
        d[250:330] = wave
        parts = segments_for(d, 100e6)
        self.assertEqual(parts[0].start, 0)
        self.assertEqual(parts[-1].end, len(d))
        for a, b in zip(parts, parts[1:]):
            self.assertEqual(a.end, b.start)
        bursts = [p for p in parts if p.bits is not None]
        self.assertEqual(len(bursts), 2)
        self.assertEqual(bursts[0].bits, [1, 0] * 4)
        self.assertEqual(bursts[1].bits, [1, 0] * 4)
        self.assertEqual(segment_frames(bursts[0], 100e6, 8, 50, 10, 10e6), 10)

    def test_page_end_reveals_last_bit(self):
        seg = Segment(0, 160, 0, [1] * 32)
        positions = frame_positions(seg, 50e6, 8, 50, 10, 10e6, 16)
        # Last bit post-transition sample is 79; next page starts at 80.
        self.assertTrue(any(79 <= pos < 80 for pos in positions))
        self.assertTrue(any(159 <= pos < 160 for pos in positions))

    def test_silence_and_pulse_not_fabricated_bits(self):
        d = np.zeros(200)
        self.assertIsNone(segments_for(d, 50e6)[0].bits)
        d[100] = 1000
        parts = segments_for(d, 50e6)
        self.assertTrue(all(p.bits is None for p in parts))
        self.assertEqual(parts[1].start, 100)
        self.assertEqual(parts[1].end, 101)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
    def test_gif_and_mp4_export_all_acquisitions(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source = temp / 'input.npz'
            np.savez(source, ch1=np.zeros((2, 200)), ch2=np.zeros((2, 200)),
                     samplerate_hz=np.array([50e6, 50e6]))
            for extension in ['gif', 'mp4']:
                out = temp / f'output.{extension}'
                result = subprocess.run([sys.executable, str(LAB / 'animate_capture.py'),
                    str(source), '-o', str(out), '--width', '640'],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('2 acquisitions', result.stdout)
                self.assertGreater(out.stat().st_size, 100)
                if extension == 'gif':
                    with Image.open(out) as image:
                        self.assertEqual(image.size, (640, 360))
                        self.assertEqual(image.info['loop'], 0)
                        self.assertGreaterEqual(image.n_frames, 2)


if __name__ == '__main__':
    unittest.main()

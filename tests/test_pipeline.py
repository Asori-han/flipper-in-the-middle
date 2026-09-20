import binascii
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'src' / 'lab'
sys.path.insert(0, str(LAB))
from manchester import (bytes_to_bits, bits_to_bytes_lsb, decode_bits,
                        recover_logic, byte_labels_lsb, capture_channels)
from generate_manchester import read_hex
from packet import format_mac, sanitize_ethernet_frame


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def cli(self, script, *args):
        result = subprocess.run([sys.executable, str(LAB / script), *map(str, args)],
                                capture_output=True, text=True,
                                env={**os.environ, 'MPLBACKEND': 'Agg',
                                     'MPLCONFIGDIR': str(self.work / 'mpl')})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def decode(self, path, capture=1):
        out = self.work / 'decoded.bin'
        self.cli('decode_manchester.py', path, '--capture', capture, '-o', out)
        return out.read_bytes()

    def test_known_vectors(self):
        bits = [0, 0, 1, 0, 1, 0, 0, 1]
        self.assertEqual(bytes_to_bits(b'\x94', True), bits)
        self.assertEqual(bits_to_bytes_lsb(bits), b'\x94')
        # Independent explicit signal for bits 0,1,1,0, at ten samples/bit.
        signal = np.repeat([1, -1, -1, 1, -1, 1, 1, -1], 5)
        self.assertEqual(decode_bits(signal, 0, 10, 4), [0, 1, 1, 0])
        self.assertEqual(recover_logic(np.array([0, 4, 1, -1, -4, 0]), 2).tolist(),
                         [1, 1, 1, 1, -1, -1])
        self.assertEqual(byte_labels_lsb([None] * 8 + [1]), [None, None])
        with self.assertRaises(RuntimeError):
            bits_to_bytes_lsb([None] * 8)

    def test_noise_roundtrips_and_single_capture(self):
        data = bytes(range(100))
        src = self.work / 'input.hex'
        src.write_text(data.hex())
        for noise, ringing in [(0, 0), (24, 90), (40, 120)]:
            with self.subTest(noise=noise, ringing=ringing):
                npz = self.work / 'synthetic.npz'
                self.cli('generate_manchester.py', src, '-o', npz,
                         '--noise', noise, '--ringing', ringing)
                self.assertEqual(self.decode(npz), data)
        with np.load(npz) as z:
            single = {key: z[key][0] for key in z.files}
        single.pop('samplerate_hz')  # Exercise scalar metadata fallback too.
        one = self.work / 'single.npz'
        np.savez(one, **single)
        self.assertEqual(self.decode(one), data)
        with np.load(one) as z:
            with self.assertRaises(SystemExit):
                capture_channels(z, 1)
        prefix = self.work / 'view'
        self.cli('npz_to_svg.py', one, '--capture', 1, '--mode', 'all',
                 '--output-prefix', prefix)
        for mode in ['full', 'zoom', 'overlay']:
            self.assertIn('<svg', Path(f'{prefix}_{mode}.svg').read_text())

    def test_bits_and_binary_cli(self):
        for extension, content in [('bits', b'00101001'), ('bin', b'\x94')]:
            with self.subTest(extension=extension):
                src = self.work / f'input.{extension}'
                src.write_bytes(content)
                npz = self.work / 'bits.npz'
                self.cli('generate_manchester.py', src, '-o', npz)
                out = self.work / 'output.bits'
                self.cli('decode_manchester.py', npz, '-o', out)
                self.assertEqual(out.read_text().strip(), '00101001')
                self.assertEqual(self.decode(npz), b'\x94')

    def check_sanitize(self, source, capture=1):
        original = self.decode(source, capture)
        destination, source_mac = original[8:14], original[14:20]
        mapping = {destination: bytes.fromhex('020000000001'),
                   source_mac: bytes.fromhex('020000000002')}
        expected_frame, _ = sanitize_ethernet_frame(original[8:], mapping)
        expected = original[:8] + expected_frame
        map_path = self.work / 'private-mac-map.json'
        map_path.write_text(json.dumps({'macs': {
            format_mac(key): format_mac(value) for key, value in mapping.items()
        }}))
        out = self.work / 'sanitized.npz'
        stdout = self.cli('sanitize_capture.py', source, '--capture', capture,
                          '--mac-map', map_path, '-o', out)
        for original_mac in mapping:
            self.assertNotIn(format_mac(original_mac), stdout.lower())
            self.assertNotIn(original_mac.hex(), stdout.lower())
        self.assertEqual(self.decode(out), expected)
        with np.load(source) as z, np.load(out) as clean:
            a, b = capture_channels(z, capture - 1)
            self.assertEqual(clean['ch1'].shape, (1, len(a)))
            meta = json.loads(str(clean['metadata_json'][0]))
            mask = np.zeros(len(a), dtype=bool)
            for start, end in meta['sanitization']['modified_sample_ranges']:
                mask[start:end] = True
            actual = (a != clean['ch1'][0]) | (b != clean['ch2'][0])
            np.testing.assert_array_equal(mask, actual)
            np.testing.assert_array_equal(clean['ch1'][0][~mask], a[~mask])
            np.testing.assert_array_equal(clean['ch2'][0][~mask], b[~mask])
            serialized = str(clean['metadata_json'][0]).lower().replace(':', '').replace('-', '')
            for original_mac in mapping:
                self.assertNotIn(original_mac.hex(), serialized)
        return original, out

    def test_synthetic_sanitization(self):
        frame = bytes.fromhex('020000123456020000abcdef88b5') + bytes(range(46))
        wire = b'\x55' * 7 + b'\xd5' + frame + binascii.crc32(frame).to_bytes(4, 'little')
        src = self.work / 'frame.bin'
        src.write_bytes(wire)
        npz = self.work / 'frame.npz'
        self.cli('generate_manchester.py', src, '-o', npz)
        self.check_sanitize(npz)

    def test_public_real_fixture_roundtrip_and_export(self):
        source = ROOT / 'data/captures/ethernet/20260913_031915_00.npz'
        data = self.decode(source)
        self.assertEqual(data[:8], b'\x55' * 7 + b'\xd5')
        self.assertEqual(binascii.crc32(data[8:-4]), int.from_bytes(data[-4:], 'little'))
        with np.load(source) as capture:
            metadata = json.loads(str(capture['metadata_json'][0]))
            self.assertTrue(metadata['sanitized'])
        src = self.work / 'real.hex'
        src.write_text(data.hex())
        npz = self.work / 'regenerated.npz'
        self.cli('generate_manchester.py', src, '-o', npz)
        result = self.work / 'roundtrip.hex'
        self.cli('decode_manchester.py', npz, '-o', result)
        self.assertEqual(read_hex(result), data)
        artifacts = self.work / 'ping'
        self.cli('export_capture.py', source, '-o', artifacts)
        self.assertEqual(artifacts.with_suffix('.pcapng').read_bytes()[:4],
                         bytes.fromhex('0a0d0d0a'))
        report = json.loads(artifacts.with_suffix('.json').read_text())
        self.assertEqual(report['captures'][0]['ipv4']['protocol'], 'ICMP')
        self.assertTrue(report['captures'][0]['icmp']['checksum_valid'])


if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'lab'))

from w5500_spi import block_name, find_write, parse_logic2_spi


class W5500SpiTests(unittest.TestCase):
    def test_parses_header_and_finds_tx_payload(self):
        csv_text = """name,type,start_time,duration,miso,mosi
W5500,enable,1.0,0.0,,
W5500,result,1.1,0.0,0x00,0x12
W5500,result,1.2,0.0,0x00,0x34
W5500,result,1.3,0.0,0x00,0x34
W5500,result,1.4,0.0,0x00,0x08
W5500,result,1.5,0.0,0x00,0x00
W5500,disable,1.6,0.0,,
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spi.csv"
            path.write_text(csv_text)
            transactions = parse_logic2_spi(path)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].address, 0x1234)
        self.assertEqual(transactions[0].block, 6)
        self.assertTrue(transactions[0].write)
        self.assertEqual(transactions[0].data, b"\x08\x00")
        self.assertEqual(block_name(6), "socket-1-tx-buffer")
        self.assertEqual(find_write(transactions, 6, b"\x08\x00")["offset"], 0)


if __name__ == "__main__":
    unittest.main()

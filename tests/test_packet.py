import binascii
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'lab'))
from packet import (PacketError, analyze_ethernet_frame, checksum16, load_mac_map,
                    sanitize_ethernet_frame)


OLD_DST = bytes.fromhex('001122334455')
OLD_SRC = bytes.fromhex('aabbccddeeff')
NEW_DST = bytes.fromhex('020000000001')
NEW_SRC = bytes.fromhex('020000000002')
MAPPING = {OLD_DST: NEW_DST, OLD_SRC: NEW_SRC}


def ethernet(ethertype, payload, destination=OLD_DST, source=OLD_SRC):
    body = destination + source + ethertype.to_bytes(2, 'big') + payload
    if len(body) < 60:
        body += bytes(60 - len(body))
    return body + binascii.crc32(body).to_bytes(4, 'little')


def ipv4(protocol, segment, fragment=0):
    source, destination = bytes([192, 0, 2, 1]), bytes([198, 51, 100, 2])
    if protocol in (6, 17):
        checksum_at = 16 if protocol == 6 else 6
        mutable = bytearray(segment)
        mutable[checksum_at:checksum_at + 2] = b'\0\0'
        pseudo = source + destination + b'\0' + bytes([protocol]) + len(mutable).to_bytes(2, 'big')
        value = checksum16(pseudo + mutable)
        mutable[checksum_at:checksum_at + 2] = (value or 0xffff).to_bytes(2, 'big')
        segment = bytes(mutable)
    header = bytearray.fromhex('450000000001000040000000') + bytearray(source + destination)
    header[2:4] = (20 + len(segment)).to_bytes(2, 'big')
    header[6:8] = fragment.to_bytes(2, 'big')
    header[9] = protocol
    header[10:12] = checksum16(header).to_bytes(2, 'big')
    return bytes(header) + segment


class PacketTests(unittest.TestCase):
    def test_icmp_payload_mac_repairs_all_integrity(self):
        icmp = bytearray(b'\x08\x00\x00\x00\x12\x34\x00\x01' + OLD_SRC + b'payload')
        icmp[2:4] = checksum16(icmp).to_bytes(2, 'big')
        clean, report = sanitize_ethernet_frame(ethernet(0x0800, ipv4(1, icmp)), MAPPING)
        self.assertNotIn(OLD_DST, clean)
        self.assertNotIn(OLD_SRC, clean)
        self.assertIn(NEW_SRC, clean)
        self.assertEqual(report['mapped_occurrences'], 3)
        self.assertEqual(report['checksums_repaired'],
                         ['ipv4.header_checksum', 'icmp.checksum', 'ethernet.fcs'])
        analysis = analyze_ethernet_frame(clean)
        self.assertTrue(analysis['ethernet']['fcs_valid'])
        self.assertTrue(analysis['ipv4']['header_checksum_valid'])
        self.assertTrue(analysis['icmp']['checksum_valid'])

    def test_tcp_and_udp_checksums(self):
        tcp = bytearray(20) + OLD_DST + b'data'
        tcp[0:4] = bytes.fromhex('04d20050')
        tcp[12] = 0x50
        udp = bytearray(8) + OLD_SRC + b'data'
        udp[0:6] = bytes.fromhex('04d200350012')
        for protocol, segment, name in [(6, tcp, 'tcp'), (17, udp, 'udp')]:
            with self.subTest(protocol=protocol):
                clean, report = sanitize_ethernet_frame(
                    ethernet(0x0800, ipv4(protocol, segment)), MAPPING)
                analysis = analyze_ethernet_frame(clean)
                self.assertTrue(analysis[name]['checksum_valid'])
                self.assertIn(f'{name}.checksum', report['checksums_repaired'])

    def test_udp_zero_checksum_is_preserved(self):
        udp = bytearray(8) + OLD_SRC
        udp[0:6] = bytes.fromhex('04d20035000e')
        packet = bytearray(ipv4(17, udp))
        packet[20 + 6:20 + 8] = b'\0\0'
        clean, report = sanitize_ethernet_frame(ethernet(0x0800, packet), MAPPING)
        analysis = analyze_ethernet_frame(clean)
        self.assertFalse(analysis['udp']['checksum_present'])
        self.assertIsNone(analysis['udp']['checksum_valid'])
        self.assertIn('udp.checksum-preserved-zero', report['checksums_repaired'])

    def test_arp_semantic_addresses_and_special_values(self):
        arp = (bytes.fromhex('0001080006040001') + OLD_SRC + bytes([192, 0, 2, 1])
               + b'\0' * 6 + bytes([192, 0, 2, 2]))
        clean, report = sanitize_ethernet_frame(
            ethernet(0x0806, arp, destination=b'\xff' * 6), {OLD_SRC: NEW_SRC})
        analysis = analyze_ethernet_frame(clean)
        self.assertEqual(analysis['arp']['sender_mac'], '02:00:00:00:00:02')
        self.assertEqual(analysis['arp']['target_mac'], '00:00:00:00:00:00')
        self.assertEqual(report['mapped_occurrences'], 2)

    def test_missing_map_bad_fcs_and_fragment_fail_closed(self):
        frame = ethernet(0x88B5, b'data')
        with self.assertRaisesRegex(PacketError, 'missing MAC addresses'):
            sanitize_ethernet_frame(frame, {OLD_SRC: NEW_SRC})
        damaged = frame[:-1] + bytes([frame[-1] ^ 1])
        with self.assertRaisesRegex(PacketError, 'original FCS'):
            sanitize_ethernet_frame(damaged, MAPPING)
        payload = OLD_SRC + b'data'
        with self.assertRaisesRegex(PacketError, 'fragmented IPv4'):
            sanitize_ethernet_frame(ethernet(0x0800, ipv4(1, payload, fragment=0x2000)), MAPPING)

    def test_private_map_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'map.json'
            path.write_text(json.dumps({'macs': {
                '00:11:22:33:44:55': '02:00:00:00:00:01',
                'aa:bb:cc:dd:ee:ff': '02:00:00:00:00:02',
            }}))
            self.assertEqual(load_mac_map(path), MAPPING)
            path.write_text(json.dumps({'00:11:22:33:44:55': '01:00:00:00:00:01'}))
            with self.assertRaisesRegex(PacketError, 'locally administered unicast'):
                load_mac_map(path)


if __name__ == '__main__':
    unittest.main()

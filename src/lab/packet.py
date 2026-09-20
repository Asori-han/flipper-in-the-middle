"""Ethernet frame parsing, MAC sanitization and checksum repair."""
from __future__ import annotations

import binascii
import json
import re
from pathlib import Path


ETHERTYPE_VLAN = {0x8100, 0x88A8, 0x9100}


class PacketError(ValueError):
    pass


def parse_mac(value: str) -> bytes:
    clean = value.replace(":", "").replace("-", "")
    if len(clean) != 12:
        raise PacketError("Each MAC address must contain exactly six bytes")
    try:
        return bytes.fromhex(clean)
    except ValueError as exc:
        raise PacketError("Una MAC del mapa no es hexadecimal") from exc


def format_mac(value: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in value)


def is_special_mac(value: bytes) -> bool:
    return value in (b"\x00" * 6, b"\xff" * 6) or bool(value[0] & 1)


def load_mac_map(path: str | Path) -> dict[bytes, bytes]:
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PacketError("Could not read the private MAC map as JSON") from exc
    values = document.get("macs") if isinstance(document, dict) and "macs" in document else document
    if not isinstance(values, dict) or not values:
        raise PacketError("The map must be a non-empty JSON object, optionally under 'macs'")
    mapping = {parse_mac(source): parse_mac(target) for source, target in values.items()}
    if any(is_special_mac(source) for source in mapping):
        raise PacketError("The map must not include special, multicast, zero, or broadcast MAC addresses")
    targets = list(mapping.values())
    if len(set(targets)) != len(targets):
        raise PacketError("Cada dispositivo necesita una MAC sustituta distinta")
    if any((target[0] & 0x03) != 0x02 for target in targets):
        raise PacketError("Replacements must be locally administered unicast MAC addresses")
    for source, target in mapping.items():
        if target in mapping and target != source:
            raise PacketError("A replacement cannot also be another original MAC address")
    return mapping


def checksum16(data: bytes) -> int:
    if len(data) & 1:
        data += b"\x00"
    total = sum(int.from_bytes(data[pos:pos + 2], "big") for pos in range(0, len(data), 2))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def ethernet_payload(body: bytes) -> tuple[int, int]:
    if len(body) < 14:
        raise PacketError("Ethernet frame is too short")
    offset = 14
    ethertype = int.from_bytes(body[12:14], "big")
    while ethertype in ETHERTYPE_VLAN:
        if len(body) < offset + 4:
            raise PacketError("Cabecera VLAN incompleta")
        ethertype = int.from_bytes(body[offset + 2:offset + 4], "big")
        offset += 4
    return ethertype, offset


def semantic_mac_fields(body: bytes) -> list[tuple[int, str, bytes]]:
    fields = [(0, "ethernet.dst_mac", body[0:6]), (6, "ethernet.src_mac", body[6:12])]
    ethertype, offset = ethernet_payload(body)
    if ethertype != 0x0806:
        return fields
    if len(body) < offset + 8:
        raise PacketError("Cabecera ARP incompleta")
    hlen, plen = body[offset + 4], body[offset + 5]
    arp_len = 8 + 2 * hlen + 2 * plen
    if len(body) < offset + arp_len:
        raise PacketError("Paquete ARP incompleto")
    if hlen == 6:
        sender = offset + 8
        target = sender + hlen + plen
        fields.extend([
            (sender, "arp.sender_mac", body[sender:sender + 6]),
            (target, "arp.target_mac", body[target:target + 6]),
        ])
    return fields


def _overlaps(start: int, end: int, changes: set[int]) -> bool:
    return any(start <= position < end for position in changes)


def _repair_ipv4(body: bytearray, offset: int, changes: set[int]) -> list[str]:
    if len(body) < offset + 20 or body[offset] >> 4 != 4:
        raise PacketError("Incomplete or invalid IPv4 header")
    ihl = (body[offset] & 0x0F) * 4
    total_length = int.from_bytes(body[offset + 2:offset + 4], "big")
    if ihl < 20 or total_length < ihl or len(body) < offset + total_length:
        raise PacketError("Truncated IPv4 datagram; its checksums cannot be guaranteed")
    end = offset + total_length
    if not _overlaps(offset, end, changes):
        return []

    repaired = ["ipv4.header_checksum"]
    body[offset + 10:offset + 12] = b"\x00\x00"
    body[offset + 10:offset + 12] = checksum16(bytes(body[offset:offset + ihl])).to_bytes(2, "big")

    flags_fragment = int.from_bytes(body[offset + 6:offset + 8], "big")
    protocol = body[offset + 9]
    transport = offset + ihl
    segment_length = total_length - ihl
    transport_changed = _overlaps(transport, end, changes)
    addresses_changed = _overlaps(offset + 12, offset + 20, changes)
    if not (transport_changed or addresses_changed):
        return repaired
    if flags_fragment & 0x3FFF:
        raise PacketError("Replacement affects fragmented IPv4; partial output will not be written")

    segment = bytearray(body[transport:end])
    if protocol == 1:
        if len(segment) < 4:
            raise PacketError("Mensaje ICMP incompleto")
        segment[2:4] = b"\x00\x00"
        segment[2:4] = checksum16(bytes(segment)).to_bytes(2, "big")
        repaired.append("icmp.checksum")
    elif protocol in (6, 17):
        checksum_offset = 16 if protocol == 6 else 6
        minimum = 20 if protocol == 6 else 8
        if len(segment) < minimum:
            raise PacketError("Segmento TCP/UDP incompleto")
        original = int.from_bytes(segment[checksum_offset:checksum_offset + 2], "big")
        if protocol == 17 and original == 0:
            repaired.append("udp.checksum-preserved-zero")
        else:
            segment[checksum_offset:checksum_offset + 2] = b"\x00\x00"
            pseudo = (bytes(body[offset + 12:offset + 20]) + b"\x00" + bytes([protocol])
                      + len(segment).to_bytes(2, "big"))
            value = checksum16(pseudo + bytes(segment))
            if protocol == 17 and value == 0:
                value = 0xFFFF
            segment[checksum_offset:checksum_offset + 2] = value.to_bytes(2, "big")
            repaired.append("tcp.checksum" if protocol == 6 else "udp.checksum")
    else:
        raise PacketError("Replacement affects an IPv4 protocol with an unsupported checksum")
    body[transport:end] = segment
    return repaired


def sanitize_ethernet_frame(frame: bytes, mapping: dict[bytes, bytes]):
    if len(frame) < 18:
        raise PacketError("Ethernet frame is too short to contain an FCS")
    stored = int.from_bytes(frame[-4:], "little")
    calculated = binascii.crc32(frame[:-4]) & 0xFFFFFFFF
    if stored != calculated:
        raise PacketError("The original FCS is invalid; sanitization stopped")

    original = bytes(frame[:-4])
    fields = semantic_mac_fields(original)
    missing = sorted({label for _, label, mac in fields if not is_special_mac(mac) and mac not in mapping})
    if missing:
        raise PacketError("The private map is missing MAC addresses: " + ", ".join(missing))

    replacements: list[tuple[int, bytes, bytes]] = []
    for source, target in mapping.items():
        position = original.find(source)
        while position >= 0:
            replacements.append((position, source, target))
            position = original.find(source, position + 1)
    replacements.sort(key=lambda item: item[0])
    for previous, current in zip(replacements, replacements[1:]):
        if previous[0] + 6 > current[0]:
            raise PacketError("Two MAC matches overlap; sanitization stopped")

    body = bytearray(original)
    changes: set[int] = set()
    for position, source, target in replacements:
        body[position:position + 6] = target
        changes.update(range(position, position + 6))

    ethertype, payload_offset = ethernet_payload(body)
    repaired = []
    if ethertype == 0x0800:
        repaired.extend(_repair_ipv4(body, payload_offset, changes))
    elif ethertype not in (0x0806,) and _overlaps(payload_offset, len(body), changes):
        raise PacketError("Replacement affects the payload of an unsupported protocol")

    new_fcs = binascii.crc32(body) & 0xFFFFFFFF
    result = bytes(body) + new_fcs.to_bytes(4, "little")
    changed_offsets = [index for index, (before, after) in enumerate(zip(frame, result)) if before != after]
    return result, {
        "semantic_fields": sorted({label for _, label, mac in fields if mac in mapping}),
        "mapped_occurrences": len(replacements),
        "checksums_repaired": repaired + ["ethernet.fcs"],
        "changed_frame_offsets": changed_offsets,
    }


def sanitize_metadata(value, mapping: dict[bytes, bytes]):
    if isinstance(value, dict):
        return {sanitize_metadata(key, mapping): sanitize_metadata(item, mapping)
                for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(item, mapping) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for source, target in mapping.items():
        compact_source, compact_target = source.hex(), target.hex()
        colon_source, colon_target = format_mac(source), format_mac(target)
        hyphen_source, hyphen_target = colon_source.replace(":", "-"), colon_target.replace(":", "-")
        for old, new in ((compact_source, compact_target), (colon_source, colon_target),
                         (hyphen_source, hyphen_target)):
            result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
    return result


def metadata_contains_original(value, mapping: dict[bytes, bytes]) -> bool:
    text = json.dumps(value, sort_keys=True)
    normalized = re.sub(r"[:-]", "", text).lower()
    return any(source.hex() in normalized for source in mapping)


def analyze_ethernet_frame(frame: bytes) -> dict:
    """Return a JSON-safe layered interpretation of a frame including its FCS."""
    if len(frame) < 18:
        raise PacketError("Ethernet frame is too short")
    body = frame[:-4]
    stored = int.from_bytes(frame[-4:], "little")
    calculated = binascii.crc32(body) & 0xFFFFFFFF
    ethertype, offset = ethernet_payload(body)
    result = {
        "length_with_fcs": len(frame),
        "ethernet": {
            "destination": format_mac(body[0:6]),
            "source": format_mac(body[6:12]),
            "ethertype": f"0x{ethertype:04x}",
            "fcs": f"0x{stored:08x}",
            "fcs_valid": stored == calculated,
        },
    }
    if ethertype == 0x0806:
        if len(body) < offset + 8:
            raise PacketError("Cabecera ARP incompleta")
        hardware, protocol = int.from_bytes(body[offset:offset + 2], "big"), int.from_bytes(body[offset + 2:offset + 4], "big")
        hlen, plen = body[offset + 4], body[offset + 5]
        operation = int.from_bytes(body[offset + 6:offset + 8], "big")
        arp_end = offset + 8 + 2 * hlen + 2 * plen
        if len(body) < arp_end:
            raise PacketError("Paquete ARP incompleto")
        arp = {"hardware_type": hardware, "protocol_type": f"0x{protocol:04x}",
               "operation": operation, "hardware_length": hlen, "protocol_length": plen}
        if hlen == 6:
            sender = offset + 8
            target = sender + hlen + plen
            arp["sender_mac"] = format_mac(body[sender:sender + 6])
            arp["target_mac"] = format_mac(body[target:target + 6])
            if protocol == 0x0800 and plen == 4:
                arp["sender_ip"] = ".".join(str(value) for value in body[sender + 6:sender + 10])
                arp["target_ip"] = ".".join(str(value) for value in body[target + 6:target + 10])
        result["arp"] = arp
        return result
    if ethertype != 0x0800:
        result["payload"] = {"length": len(body) - offset}
        return result

    if len(body) < offset + 20 or body[offset] >> 4 != 4:
        raise PacketError("Incomplete or invalid IPv4 header")
    ihl = (body[offset] & 0x0F) * 4
    total_length = int.from_bytes(body[offset + 2:offset + 4], "big")
    end = offset + total_length
    if ihl < 20 or total_length < ihl or end > len(body):
        raise PacketError("Datagrama IPv4 truncado")
    protocol = body[offset + 9]
    protocol_name = {1: "ICMP", 6: "TCP", 17: "UDP"}.get(protocol, str(protocol))
    result["ipv4"] = {
        "header_length": ihl,
        "total_length": total_length,
        "source": ".".join(str(value) for value in body[offset + 12:offset + 16]),
        "destination": ".".join(str(value) for value in body[offset + 16:offset + 20]),
        "ttl": body[offset + 8],
        "protocol": protocol_name,
        "header_checksum_valid": checksum16(body[offset:offset + ihl]) == 0,
        "fragmented": bool(int.from_bytes(body[offset + 6:offset + 8], "big") & 0x3FFF),
    }
    segment = body[offset + ihl:end]
    if protocol == 1 and len(segment) >= 4:
        result["icmp"] = {
            "type": segment[0], "code": segment[1],
            "checksum_valid": checksum16(segment) == 0,
            "payload_length": max(0, len(segment) - 8),
        }
    elif protocol in (6, 17):
        minimum, checksum_offset = (20, 16) if protocol == 6 else (8, 6)
        if len(segment) < minimum:
            raise PacketError("Segmento TCP/UDP incompleto")
        source_port = int.from_bytes(segment[0:2], "big")
        destination_port = int.from_bytes(segment[2:4], "big")
        stored_checksum = int.from_bytes(segment[checksum_offset:checksum_offset + 2], "big")
        pseudo = body[offset + 12:offset + 20] + b"\x00" + bytes([protocol]) + len(segment).to_bytes(2, "big")
        valid = None if protocol == 17 and stored_checksum == 0 else checksum16(pseudo + segment) == 0
        name = "tcp" if protocol == 6 else "udp"
        header_length = ((segment[12] >> 4) * 4) if protocol == 6 else 8
        result[name] = {
            "source_port": source_port, "destination_port": destination_port,
            "checksum_valid": valid, "checksum_present": not (protocol == 17 and stored_checksum == 0),
            "payload_length": max(0, len(segment) - header_length),
        }
    return result

"""Ethernet interpretation, separate from Manchester recovery."""
import binascii

def ethernet_summary(data):
    result = {}

    if len(data) < 8 or data[:7] != b"\x55" * 7 or data[7] != 0xD5:
        return result

    result["preamble_sfd"] = True
    frame = data[8:]

    if len(frame) < 18:
        return result

    result["dst_mac"] = ":".join(f"{b:02x}" for b in frame[0:6])
    result["src_mac"] = ":".join(f"{b:02x}" for b in frame[6:12])
    result["ethertype"] = f"0x{int.from_bytes(frame[12:14], 'big'):04x}"

    stored_fcs = int.from_bytes(frame[-4:], "little")
    calc_fcs = binascii.crc32(frame[:-4]) & 0xFFFFFFFF
    result["fcs_stored"] = f"0x{stored_fcs:08x}"
    result["fcs_calculated"] = f"0x{calc_fcs:08x}"
    result["fcs_valid"] = stored_fcs == calc_fcs

    return result



#!/usr/bin/env python3
"""Correlate Flipper/W5500 SPI bytes with a DOS1102 frame."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from scope_validation import recover_scope_frames
from w5500_spi import block_name, find_write, parse_logic2_spi


def load_scope_captures(path: Path):
    with np.load(path, allow_pickle=False) as source:
        return [
            (
                json.loads(str(source["metadata_json"][index])),
                source["ch1"][index],
                source["ch2"][index],
                float(source["timestamps"][index]),
            )
            for index in range(len(source["ch1"]))
        ]


def comparison_target(frame: bytes, kind: str):
    if kind == "arp":
        return 2, frame[:-4], "Ethernet frame without FCS (MACRAW, socket 0)"
    if frame[12:14] != b"\x08\x00":
        raise ValueError("The physical frame is not IPv4")
    ip = 14
    ihl = (frame[ip] & 0x0F) * 4
    total = int.from_bytes(frame[ip + 2:ip + 4], "big")
    if kind in {"increment", "00", "ff", "55", "aa"}:
        return 6, frame[ip + ihl:ip + total], "paquete ICMP (IPRAW, socket 1)"
    if kind == "http":
        tcp = ip + ihl
        tcp_header = (frame[tcp + 12] >> 4) * 4
        return 10, frame[tcp + tcp_header:ip + total], "carga TCP HTTP (socket 2)"
    raise ValueError(f"Tipo de ensayo no soportado: {kind}")


def analyze(spi_csv: Path, scope_npz: Path, kind: str):
    transactions = parse_logic2_spi(spi_csv)
    accepted_scope_kinds = {kind, "tcp80"} if kind == "http" else {kind}
    recovered = [x for x in recover_scope_frames(load_scope_captures(scope_npz))
                 if x["pattern"] in accepted_scope_kinds]
    if not recovered:
        raise RuntimeError(f"The NPZ contains no valid {kind} frame")
    frame = recovered[0]["frame"]
    if kind == "http" and recovered[0]["pattern"] == "tcp80":
        requests = [tx.data for tx in transactions
                    if tx.write and tx.block == 10 and tx.data.startswith(b"GET ")]
        if not requests:
            raise RuntimeError("The SPI capture contains no GET request")
        block, needle = 10, requests[0]
        compared = "physical TCP/80 frame and GET request in the socket 2 TX block"
    else:
        block, needle, compared = comparison_target(frame, kind)
    match = find_write(transactions, block, needle)
    blocks = Counter((tx.block, tx.write) for tx in transactions)
    if match["offset"] < 0:
        interpretation = "The expected bytes were not found in the SPI block."
    elif kind == "http" and recovered[0]["pattern"] == "tcp80":
        interpretation = (
            "The DOS1102 confirms a TCP/80 frame with a valid FCS, while SPI confirms "
            "the GET request delivered to socket 2; the W5500 generates TCP/IP, Ethernet, and FCS."
        )
    else:
        interpretation = (
            "The compared bytes appear in the SPI write to the W5500. "
            "The FCS appears only on the wire because the controller/PHY generates it."
        )
    return {
        "passed": match["offset"] >= 0,
        "kind": kind,
        "scope_frame_kind": recovered[0]["pattern"],
        "scope_capture": recovered[0]["capture"],
        "wire_frame_bytes_with_fcs": len(frame),
        "fcs_on_wire_bytes": 4,
        "compared": compared,
        "comparison_bytes": len(needle),
        "spi_match": match,
        "transactions": {
            "total": len(transactions),
            "reads": sum(not tx.write for tx in transactions),
            "writes": sum(tx.write for tx in transactions),
            "by_block": [
                {"block": block_id, "name": block_name(block_id),
                 "operation": "write" if write else "read", "count": count}
                for (block_id, write), count in sorted(blocks.items())
            ],
        },
        "interpretation": interpretation,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spi_csv", type=Path)
    parser.add_argument("scope_npz", type=Path)
    parser.add_argument("--kind", required=True,
                        choices=("increment", "00", "ff", "55", "aa", "arp", "http"))
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.spi_csv, args.scope_npz, args.kind)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

"""Read W5500 transactions exported by the Logic 2 SPI analyzer."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class W5500Transaction:
    start_time: float
    address: int
    block: int
    write: bool
    mode: int
    mosi: bytes
    miso: bytes

    @property
    def data(self) -> bytes:
        return self.mosi[3:] if self.write else self.miso[3:]


def _byte(value: str) -> int:
    return int(value, 16) if value else 0


def parse_logic2_spi(path: Path | str) -> list[W5500Transaction]:
    """Group bytes between CS enable and disable events."""
    transactions = []
    current = None
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            kind = row["type"].strip().lower()
            if kind == "enable":
                current = {"start": float(row["start_time"]), "mosi": [], "miso": []}
            elif kind == "result" and current is not None:
                current["mosi"].append(_byte(row.get("mosi", "")))
                current["miso"].append(_byte(row.get("miso", "")))
            elif kind == "disable" and current is not None:
                mosi = bytes(current["mosi"])
                miso = bytes(current["miso"])
                if len(mosi) >= 3:
                    control = mosi[2]
                    transactions.append(W5500Transaction(
                        start_time=current["start"],
                        address=int.from_bytes(mosi[:2], "big"),
                        block=(control >> 3) & 0x1F,
                        write=bool(control & 0x04),
                        mode=control & 0x03,
                        mosi=mosi,
                        miso=miso,
                    ))
                current = None
    return transactions


def block_name(block: int) -> str:
    if block == 0:
        return "common-registers"
    socket = (block - 1) // 4
    kind = (block - 1) % 4
    if 0 <= socket <= 7 and kind < 3:
        suffix = ("registers", "tx-buffer", "rx-buffer")[kind]
        return f"socket-{socket}-{suffix}"
    return f"reserved-{block}"


def joined_writes(transactions: list[W5500Transaction], block: int) -> bytes:
    return b"".join(tx.data for tx in transactions if tx.write and tx.block == block)


def find_write(transactions: list[W5500Transaction], block: int, needle: bytes):
    """Find bytes in block writes, including across transaction boundaries."""
    haystack = joined_writes(transactions, block)
    offset = haystack.find(needle)
    return {"block": block, "block_name": block_name(block), "offset": offset,
            "matched_bytes": len(needle) if offset >= 0 else 0,
            "written_bytes": len(haystack)}

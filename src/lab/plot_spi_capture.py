#!/usr/bin/env python3
"""Plot decoded W5500 SPI bytes beside the frame recovered on the wire."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle


COLORS = {
    "Ethernet": "#88c0d0",
    "IPv4": "#81a1c1",
    "Cabecera ICMP": "#5e81ac",
    "ARP": "#a3be8c",
    "Relleno": "#d8dee9",
    "GET / HTTP/1.0": "#ebcb8b",
    "Cabeceras HTTP": "#d08770",
    "TCP ACK": "#b48ead",
    "FCS": "#bf616a",
}


def bytes_to_msb_bits(data: bytes) -> np.ndarray:
    """Return the bit order displayed by the captured SPI analyzer."""
    return np.array([(value >> bit) & 1 for value in data for bit in range(7, -1, -1)])


def visible_waveform_bytes(data: bytes, minimum_run: int = 8) -> tuple[int, int]:
    """Collapse a long constant suffix, retaining two representative bytes."""
    if not data:
        return 0, 0
    repeated = 1
    for value in reversed(data[:-1]):
        if value != data[-1]:
            break
        repeated += 1
    if repeated < minimum_run:
        return len(data), 0
    omitted = repeated - 2
    return len(data) - omitted, omitted


def draw_fields(ax, fields, label: str, total_width: int) -> None:
    position = 0
    for name, length in fields:
        color = COLORS.get(name, "#8fbcbb")
        hatch = "////" if name == "FCS" else None
        ax.add_patch(Rectangle(
            (position, 0), length, 1, facecolor=color, edgecolor="white",
            linewidth=1.2, hatch=hatch,
        ))
        if length >= 4:
            ax.text(position + length / 2, 0.5, f"{name}\n{length} B",
                    ha="center", va="center", fontsize=8)
        position += length
    ax.set_xlim(0, total_width)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_ylabel(label, rotation=0, ha="right", va="center", labelpad=12,
                  fontsize=9, fontweight="bold")
    ax.spines[:].set_visible(False)


def extract_write_data(path: Path, block: int) -> bytes:
    """Stream the selected W5500 TX block from a Logic 2 CSV export."""
    data = bytearray()
    active = False
    transaction = bytearray()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            kind = row["type"].strip().lower()
            if kind == "enable":
                active, transaction = True, bytearray()
            elif kind == "result" and active:
                value = row.get("mosi", "").strip()
                transaction.append(int(value, 16) if value else 0)
            elif kind == "disable" and active:
                if len(transaction) >= 3:
                    control = transaction[2]
                    if control & 0x04 and ((control >> 3) & 0x1F) == block:
                        data.extend(transaction[3:])
                active = False
    return bytes(data)


def plot_capture(descriptor: dict, slug: str, spi_csv: Path, output: Path) -> None:
    capture = descriptor["captures"][slug]
    expected = bytes.fromhex(capture["mosi_hex"])
    block = {"arp": 2, "http": 10}.get(slug, 6)
    if slug == "arp":
        # MACRAW writes include the Ethernet header and padding.
        expected = expected[:14 + 28 + 18]
    # The descriptor contains payload bytes, not the 3-byte W5500 command header.
    writes = extract_write_data(spi_csv, block)
    offset = writes.find(expected)
    if offset < 0:
        raise ValueError(f"{slug}: expected payload was not found in {spi_csv}")
    data = writes[offset:offset + len(expected)]
    bits = bytes_to_msb_bits(data)
    visible_bytes, omitted_bytes = visible_waveform_bytes(data)
    visible_bits = bits[:visible_bytes * 8]
    spi_fields = capture["spi_fields"]
    wire_fields = capture["wire_fields"]

    if sum(length for _, length in spi_fields) != len(data):
        raise ValueError(f"{slug}: SPI field lengths do not match MOSI data")

    wire_bytes = sum(length for _, length in wire_fields)
    clock_hz = descriptor["spi_clock_hz"]
    duration_us = len(bits) / clock_hz * 1e6

    fig = plt.figure(figsize=(15, 6.6), constrained_layout=True)
    grid = fig.add_gridspec(4, 1, height_ratios=(3.2, 0.9, 0.9, 0.45))
    waveform = fig.add_subplot(grid[0])
    spi_map = fig.add_subplot(grid[1])
    wire_map = fig.add_subplot(grid[2])
    note = fig.add_subplot(grid[3])

    x = np.arange(len(visible_bits) + 1) / 8
    y = np.r_[visible_bits, visible_bits[-1]]
    waveform.step(x, y, where="post", color="#2e3440", linewidth=0.75)
    for byte in range(visible_bytes + 1):
        waveform.axvline(byte, color="#4c566a", linewidth=0.25, alpha=0.25)
    for byte in range(0, visible_bytes, 4):
        chunk = data[byte:min(byte + 4, visible_bytes)].hex(" ")
        waveform.text(byte + min(2, (visible_bytes - byte) / 2), 1.12, chunk,
                      ha="center", va="bottom", fontsize=7, family="monospace")
    if omitted_bytes:
        waveform.axvline(visible_bytes - 2, color="#bf616a", linestyle="--",
                         linewidth=1)
        waveform.text(
            visible_bytes - 1, 0.55,
            f"… {omitted_bytes} bytes {data[-1]:02x}\nconstantes omitidos",
            ha="center", va="center", fontsize=8, color="#8f2633",
            bbox={"facecolor": "white", "edgecolor": "#bf616a", "alpha": 0.9},
        )
    waveform.set_xlim(0, visible_bytes)
    waveform.set_ylim(-0.18, 1.34)
    waveform.set_yticks([0, 1])
    waveform.set_ylabel("MOSI")
    crop_note = f"; {omitted_bytes} bytes constantes omitidos en la vista" if omitted_bytes else ""
    waveform.set_xlabel(
        f"Posición en la transferencia SPI (byte); captura completa: "
        f"{duration_us:.1f} µs a {clock_hz / 1e6:.1f} MHz{crop_note}"
    )
    waveform.grid(axis="y", alpha=0.2)
    waveform.spines[["top", "right"]].set_visible(False)
    waveform.set_title(
        f"Logic 2: datos digitales hacia el W5500 — {capture['mode']}\n"
        "Reconstrucción de la señal a partir de los bytes SPI decodificados"
    )

    width = max(len(data), wire_bytes)
    draw_fields(spi_map, spi_fields, "SPI", width)
    draw_fields(wire_map, wire_fields, "Cable", width)
    wire_map.set_xlabel("Posición en bytes dentro de cada representación")

    note.axis("off")
    if capture["same_packet"]:
        message = (
            "Comparación del mismo paquete. El área rayada FCS sólo existe en el cable: "
            "el W5500 la calcula después de recibir los datos por SPI."
        )
    else:
        message = (
            "No hay alineación byte a byte: SPI contiene el GET, mientras que el DOS1102 "
            "capturó otro paquete de la sesión, un ACK sin payload. El FCS del ACK sólo existe en el cable."
        )
    note.text(0, 0.55, message, ha="left", va="center", fontsize=9.5,
              transform=note.transAxes)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, metadata={"Software": "flipper-in-the-middle"})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("slug")
    parser.add_argument("spi_csv", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    descriptor = json.loads(args.descriptor.read_text(encoding="utf-8"))
    if args.slug not in descriptor["captures"]:
        raise SystemExit(f"Unknown capture: {args.slug}")
    plot_capture(descriptor, args.slug, args.spi_csv, args.output)


if __name__ == "__main__":
    main()

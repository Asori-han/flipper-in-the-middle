#!/usr/bin/env python3
"""Render a byte layout from TShark's PDML dissection of one packet."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


COLORS = {
    "eth": "#88c0d0", "ip": "#81a1c1", "arp": "#a3be8c",
    "icmp": "#5e81ac", "tcp": "#b48ead", "udp": "#d08770",
    "padding": "#d8dee9", "fcs": "#bf616a",
}


def resolve_tshark() -> str:
    configured = os.environ.get("TSHARK_BIN")
    if configured:
        return configured
    discovered = shutil.which("tshark")
    if discovered:
        return discovered
    raise FileNotFoundError("tshark was not found (set TSHARK_BIN to its executable)")


def dissect(pcapng: Path, tshark: str) -> ET.Element:
    command = [
        tshark, "-r", str(pcapng), "-n", "-o", "eth.check_fcs:true",
        "-o", "ip.check_checksum:true", "-o", "tcp.check_checksum:true",
        "-T", "pdml",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    root = ET.fromstring(result.stdout)
    packet = root.find("packet")
    if packet is None:
        raise ValueError(f"TShark returned no packets for {pcapng}")
    return packet


def extract_layout(packet: ET.Element):
    frame_proto = packet.find("proto[@name='frame']")
    if frame_proto is None:
        raise ValueError("PDML has no frame protocol")
    total_length = int(frame_proto.attrib["size"])
    protos = []
    fcs_value = "not reported"
    fcs_start = total_length
    validations = []
    for proto in packet.findall("proto"):
        name = proto.attrib.get("name", "")
        if name == "eth":
            for field in proto.findall("field"):
                field_name = field.attrib.get("name", "")
                if field_name == "eth.fcs":
                    fcs_value = field.attrib.get("show", "not reported")
                    fcs_start = int(field.attrib.get("pos", total_length))
        if name in {"eth", "ip", "arp", "icmp", "tcp", "udp"}:
            start = int(proto.attrib.get("pos", "0"))
            length = int(proto.attrib.get("size", "0"))
            if length > 0:
                protos.append((start, start + length, name, proto.attrib.get("showname", name)))

    validation_names = {
        "eth.fcs.status": "FCS",
        "ip.checksum.status": "IPv4 checksum",
        "tcp.checksum.status": "TCP checksum",
        "icmp.checksum.status": "ICMP checksum",
    }
    for field in packet.iter("field"):
        field_name = field.attrib.get("name", "")
        if field_name in validation_names:
            result = field.attrib.get("showname", "").rsplit(":", 1)[-1].strip()
            validations.append(f"{validation_names[field_name]}: {result}")

    protos.sort()
    segments = list(protos)
    parsed_end = max((end for _, end, _, _ in segments), default=0)
    if parsed_end < fcs_start:
        segments.append((parsed_end, fcs_start, "padding", "Ethernet padding"))
    if fcs_start < total_length:
        segments.append((fcs_start, total_length, "fcs", f"FCS {fcs_value}"))
    return total_length, segments, validations, fcs_value


def render(packet: ET.Element, pcapng: Path, output: Path, tshark_version: str) -> None:
    total, segments, validations, fcs_value = extract_layout(packet)
    descriptions = [
        {"eth": "Ethernet II", "ip": "IPv4", "arp": "ARP", "icmp": "ICMP",
         "tcp": "TCP", "udp": "UDP"}.get(name, name.upper())
        for _, _, name, _ in segments if name not in {"padding", "fcs"}
    ]
    fig, (ax, details) = plt.subplots(
        2, 1, figsize=(14, 4.6), gridspec_kw={"height_ratios": [1.6, 1]},
        constrained_layout=True,
    )
    for start, end, name, label in segments:
        width = end - start
        if width <= 0:
            continue
        ax.add_patch(Rectangle(
            (start, 0), width, 1, facecolor=COLORS.get(name, "#8fbcbb"),
            edgecolor="white", linewidth=1.5, hatch="////" if name == "fcs" else None,
        ))
        display = {"eth": "ETH", "ip": "IPv4", "arp": "ARP", "icmp": "ICMP",
                   "tcp": "TCP", "udp": "UDP", "fcs": "FCS"}.get(name, label)
        if width >= 4:
            ax.text(start + width / 2, 0.63, display, ha="center", va="center",
                    fontsize=9, fontweight="bold")
            ax.text(start + width / 2, 0.30, f"{start}–{end - 1} · {width} B",
                    ha="center", va="center", fontsize=8)
    ax.set_xlim(0, total)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xticks(range(0, total + 1, 4))
    ax.set_xlabel("Offset en el paquete (bytes)")
    ax.set_title("Disección de TShark: " + " → ".join(descriptions), fontsize=11)
    ax.spines[["left", "right", "top"]].set_visible(False)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)

    details.axis("off")
    checks = " · ".join(validations)
    if not checks:
        checks = "Sin campos de integridad reportados por los disectores"
    details.text(0.01, 0.76,
                 f"Integridad según TShark: {checks} · FCS {fcs_value}",
                 transform=details.transAxes, fontsize=9.5, va="center")
    details.text(
        0.01, 0.35,
        f"CLI: tshark -r {pcapng.name} -n -o eth.check_fcs:true -T pdml    |    "
        f"{tshark_version.split(' (')[0]}", transform=details.transAxes, fontsize=8.5,
        family="monospace", va="center",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, metadata={"Software": "Wireshark TShark PDML"})
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcapng", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    tshark = resolve_tshark()
    version_result = subprocess.run([tshark, "--version"], check=True,
                                    capture_output=True, text=True)
    version = version_result.stdout.splitlines()[0]
    render(dissect(args.pcapng, tshark), args.pcapng, args.output, version)


if __name__ == "__main__":
    main()

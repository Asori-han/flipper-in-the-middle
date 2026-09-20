#!/usr/bin/env python3
"""Generate the Kirchhoff teaching schematics used by the paper."""

from __future__ import annotations

import argparse
from pathlib import Path

import schemdraw
import schemdraw.elements as elm


def draw_current_node(path: Path) -> None:
    """Draw a node with two incoming and two outgoing currents."""
    with schemdraw.Drawing(file=str(path), show=False) as drawing:
        drawing.config(fontsize=14, lw=1.8, color="black")
        drawing += elm.Arrow().right().at((-2, 0)).length(2.0).label("I1", loc="top")
        drawing += elm.Arrow().down().at((0, 2)).length(2.0).label("I2", loc="right")
        drawing += elm.Arrow().right().at((0, 0)).length(2.0).label("I3", loc="top")
        drawing += elm.Arrow().down().at((0, 0)).length(2.0).label("I4", loc="left")
        drawing += elm.Dot().at((0, 0))


def draw_voltage_loop(path: Path) -> None:
    """Draw a voltage source and two series resistors in a closed loop."""
    with schemdraw.Drawing(file=str(path), show=False) as drawing:
        drawing.config(fontsize=14, lw=1.8, color="black")
        drawing += elm.SourceV().up().label("V", loc="left")
        drawing += elm.Resistor().right().label("R1", loc="top")
        drawing += elm.Resistor().down().label("R2", loc="right")
        drawing += elm.Line().left()
        drawing += elm.Line().up()
        drawing += elm.Arrow().right().at((1.0, 2.0)).length(0.7).label("I", loc="top")


def draw_differential_measurement(path: Path) -> None:
    """Draw the two-resistor differential probe reference circuit."""
    with schemdraw.Drawing(file=str(path), show=False) as drawing:
        drawing.config(fontsize=13, lw=1.8, color="black")
        drawing += elm.Line().right().at((-2.5, 2.2)).length(2.5).label(
            "Hilo A / CH1", loc="left"
        )
        drawing += elm.Resistor().down().at((0, 2.2)).length(2.2)
        drawing += elm.Label().at((1.8, 1.3)).label("R1 = 10 kΩ")
        drawing += elm.Resistor().down().at((0, 0)).length(2.0)
        drawing += elm.Label().at((1.8, -1.0)).label("R2 = 10 kΩ")
        drawing += elm.Line().left().at((0, -2.0)).length(2.5).label(
            "Hilo B / CH2", loc="left"
        )
        drawing += elm.Line().left().at((0, 0)).length(1.1)
        drawing += elm.Ground().at((-1.1, 0))
        drawing += elm.Dot().at((0, 0))


def draw_poe_dual_channel_measurement(path: Path) -> None:
    """Draw the confirmed PoE voltage/current measurement wiring."""
    with schemdraw.Drawing(file=str(path), show=False) as drawing:
        drawing.config(fontsize=12, lw=1.8, color="black")

        # Alternative A: pins 1/2 carry the positive rail; 3/6 the return.
        drawing += elm.Label().at((1.2, 4.7)).label("PSE", loc="center")
        drawing += elm.Label().at((8.0, 4.7)).label("PD", loc="center")
        drawing += elm.Label().at((1.1, 4.0)).label("pin 1 (+)", loc="left")
        drawing += elm.Line().right().at((1.8, 4.0)).length(5.8)
        drawing += elm.Label().at((1.1, 3.1)).label("pin 2 (+)", loc="left")
        drawing += elm.Line().right().at((1.8, 3.1)).length(5.8)

        # Pin 3 contains the measured 10-ohm shunt. CH2 senses its load-side
        # voltage while both probe grounds remain at the source-side node.
        drawing += elm.Label().at((1.1, 2.0)).label("pin 3 (−)", loc="left")
        drawing += elm.Line().right().at((1.8, 2.0)).length(1.0)
        drawing += elm.Dot().at((2.8, 2.0))
        drawing += elm.Resistor().right().at((2.8, 2.0)).length(1.8)
        drawing += elm.Label().at((3.7, 2.65)).label("R1 = 10 Ω · shunt CH2", loc="center")
        drawing += elm.Dot().at((4.6, 2.0))
        drawing += elm.Line().right().at((4.6, 2.0)).length(3.0).label(
            "hacia PD", loc="right"
        )

        # The matching resistor on pin 6 preserves an equal current split;
        # it is not a second measurement shunt.
        drawing += elm.Label().at((1.1, -0.6)).label("pin 6 (−)", loc="left")
        drawing += elm.Line().right().at((1.8, -0.6)).length(1.0)
        drawing += elm.Resistor().right().at((2.8, -0.6)).length(1.8)
        drawing += elm.Label().at((3.7, -1.25)).label("R2 = 10 Ω", loc="center")
        drawing += elm.Line().right().at((4.6, -0.6)).length(3.0).label(
            "hacia PD", loc="right"
        )

        # Common probe reference at the PSE end of R1.
        drawing += elm.Line().down().at((2.8, 2.0)).length(0.55)
        drawing += elm.Line().left().at((2.8, 1.45)).length(1.5)
        drawing += elm.Ground().at((1.3, 1.45))
        drawing += elm.Label().at((1.3, 0.55)).label("masas comunes", loc="center")

        # Probe tips: CH1 measures the rail voltage; CH2 measures the shunt.
        drawing += elm.Dot().at((5.3, 4.0))
        drawing += elm.Arrow().up().at((5.3, 4.0)).length(0.55).label(
            "punta CH1 ×10", loc="right"
        )
        drawing += elm.Dot().at((5.0, 2.0))
        drawing += elm.Line().down().at((5.0, 2.0)).length(0.45)
        drawing += elm.Arrow().down().at((5.0, 1.55)).length(0.35)
        drawing += elm.Label().at((5.35, 1.25)).label("punta CH2 ×1", loc="left")

        drawing += elm.Label().at((4.5, -1.75)).label(
            "Alternativa A · los demás pares pasan sin modificar", loc="center"
        )


def draw_flipper_spi_wiring(path: Path) -> None:
    """Draw the parallel Flipper–W5500–Logic 2 SPI wiring."""
    with schemdraw.Drawing(file=str(path), show=False) as drawing:
        drawing.config(fontsize=11, lw=1.6, color="black")
        drawing += elm.Label().at((0.0, 6.0)).label("Flipper Zero", loc="center")
        drawing += elm.Label().at((4.5, 6.0)).label("W5500 Mini", loc="center")
        drawing += elm.Label().at((7.8, 6.0)).label("Analizador lógico", loc="center")

        rows = [
            (5.2, "pin 2 · PA7", "MO / MOSI", "D0 · MOSI"),
            (4.2, "pin 3 · PA6", "MI / MISO", "D1 · MISO"),
            (3.2, "pin 4 · PA4", "CS · activo bajo", "D2 · Enable"),
            (2.2, "pin 5 · PB3", "SCK", "D3 · Clock"),
            (1.2, "pin 7 · PC3", "RST · activo bajo", "D4 · referencia"),
            (0.2, "pin 8 · GND", "G", "GND · masa común"),
        ]
        for y, flipper, w5500, logic in rows:
            drawing += elm.Label().at((0.0, y + 0.28)).label(flipper, loc="center")
            drawing += elm.Line().right().at((0.0, y)).length(8.8)
            drawing += elm.Dot().at((4.5, y))
            drawing += elm.Dot().at((8.2, y))
            drawing += elm.Label().at((4.5, y + 0.28)).label(w5500, loc="center")
            drawing += elm.Label().at((8.8, y + 0.28)).label(logic, loc="center")

        drawing += elm.Label().at((0.0, -0.8)).label("pin 9 · 3,3 V", loc="center")
        drawing += elm.Line().right().at((0.0, -1.1)).length(4.5)
        drawing += elm.Dot().at((4.5, -1.1))
        drawing += elm.Label().at((4.5, -0.8)).label("V", loc="center")
        drawing += elm.Label().at((7.6, -1.1)).label(
            "VCC (sin usar)", loc="center"
        )

        drawing += elm.Label().at((4.5, -1.8)).label(
            "Logic 2 · SPI: modo 0 · 8 bits · MSB primero · ≥12 MS/s para 2 MHz",
            loc="center",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    draw_current_node(args.output / "kirchhoff-current-node.png")
    draw_voltage_loop(args.output / "kirchhoff-voltage-loop.png")
    draw_differential_measurement(args.output / "differential-resistor-measurement.png")
    draw_poe_dual_channel_measurement(args.output / "poe-dual-channel-measurement.png")
    draw_flipper_spi_wiring(args.output / "flipper-w5500-logic2.png")


if __name__ == "__main__":
    main()

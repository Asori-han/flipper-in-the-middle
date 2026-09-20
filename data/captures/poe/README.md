# PoE captures

These publishable oscilloscope captures contain no private identifiers. Each
NPZ acquisition is accompanied by its JSON metadata file.

| Capture | Contents |
| --- | --- |
| `poe_startup_positive_20260911_193902.npz` | Positive-polarity PoE startup. Primary appendix record. |
| `poe_startup_reversed_20260911_192627.npz` | Same sequence with probe tip and ground clip reversed. Independent repetition. |
| `poe_current_20260911_201209.npz` | Startup current measured on one return conductor with a 10 Ω resistor and 1× probe. |
| `poe_power_on_edge_20260911_210434.npz` | Power-connection edge with simultaneous voltage and current, 2 ms at 5 MS/s. |
| `poe_power_removal_20260911_214836.npz` | Power removal after disconnecting the splitter, followed by the return to detection idle. |
| `poe_full_sequence_20260911_230051.npz` | Reference capture containing all four phases with voltage and current in the same event. |

The startup captures use a TL-SG108PE, PS15G splitter, and Raspberry Pi 4 as
the PD. They record 1 s at 10 kS/s with CH1 at 20 V/div and a 10× probe.

Regenerate the PoE appendix figure:

    python3 src/lab/plot_poe_startup.py data/captures/poe/poe_startup_positive_20260911_193902.npz \
        --output build/figures/poe-arranque.svg

Regenerate the current figure:

    python3 src/lab/plot_poe_current.py data/captures/poe/poe_current_20260911_201209.npz \
        --shunt 10 --output build/figures/poe-corriente.svg

Regenerate the edge figure:

    python3 src/lab/plot_poe_edge.py data/captures/poe/poe_power_on_edge_20260911_210434.npz \
        --shunt 10 --invert-voltage --output build/figures/poe-flanco.svg

Regenerate the reference figure with current for each phase:

    python3 src/lab/plot_poe_startup.py data/captures/poe/poe_full_sequence_20260911_230051.npz \
        --current --shunt 10 --invert-current --invert-voltage \
        --output build/figures/poe-secuencia.svg

Regenerate the removal figure:

    python3 src/lab/plot_poe_removal.py data/captures/poe/poe_power_removal_20260911_214836.npz \
        --shunt 10 --invert-voltage --output build/figures/poe-retirada.svg

Every script reads the scale factor recorded by the instrument in
`Current_Ratio / Current_Rate` and measures levels and durations directly from
the samples. Figure captions and labels come from `docs/plot-labels.es.json`.

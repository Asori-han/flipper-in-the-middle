# Publishable Ethernet captures

These NPZ files come from real DOS1102 captures and have been sanitized. Each
file contains one acquisition, uses locally administered MAC addresses, and
was decoded again after repairing checksums and the FCS. The source run name
identifies its test; acquisition numbers and decode thresholds are listed below.

| File | Acquisition | Threshold | Decoded contents |
| --- | ---: | ---: | --- |
| `20260913_031230_increment.npz` | 3 | 450 | ICMP Echo Request with incremental payload |
| `20260913_031416_55.npz` | 3 | 300 | ICMP Echo Request with `55` payload |
| `20260913_031449_aa.npz` | 5 | 450 | ICMP Echo Request with `aa` payload |
| `20260913_031915_00.npz` | 3 | 300 | ICMP Echo Request with `00` payload |
| `20260913_031956_ff.npz` | 5 | 450 | ICMP Echo Request with `ff` payload |
| `20260913_121908_arp.npz` | 5 | 300 | Broadcast ARP request |
| `20260913_122619_http.npz` | 5 | 300 | TCP/80 segment without payload |
| `20260917_221140_arp.npz` | 3 | 450 | Independent valid ARP request repetition |

The adjacent `*_spi.csv` files are the complete Logic 2 SPI analyzer exports
for these same eight runs. They retain the analyzer rows and timestamps; the
MOSI/MISO data bytes have only had mapped device MAC addresses replaced. The
three-byte W5500 command header, transaction boundaries, timing, and all other
bytes are preserved. These are the source data for the SPI comparison images;
the plotting script deterministically locates the relevant TX payload in the
appropriate W5500 block. It does not curate or rewrite the CSV for display.

To reproduce the sanitized CSV copies from the private local exports:

```sh
for run in 20260913_031230_increment 20260913_031416_55 20260913_031449_aa \
  20260913_031915_00 20260913_031956_ff 20260913_121908_arp \
  20260913_122619_http 20260917_221140_arp; do
  python3 src/lab/sanitize_spi_csv.py \
    "data/local/evidence/demo-runs/$run/spi.csv" \
    "data/captures/ethernet/${run}_spi.csv" \
    --mac-map data/local/evidence/paper.mac-map.json
done
```

The rejected-run audit is documented in `docs/paper/includes/monitoring.adoc`.
Those attempts do not have a complete valid frame and therefore have no
published NPZ. The original private captures and MAC replacement map remain
under `data/local/` and are not published.

HEX, layered JSON, PCAPNG, and SVG derivatives are regenerated with:

```sh
./scripts/generate-public-assets
```

The physical HTTP frame is a TCP/80 segment without a payload. The GET request
is demonstrated by the SPI capture from the same run, rather than by this NPZ.

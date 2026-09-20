# Ethernet Lab for Flipper Zero

Ethernet Lab turns a Flipper Zero plus a W5500 module into a repeatable source
of small Ethernet experiments. A text file defines the frames and requests used
in a live demonstration, so the same sequence can be captured with an
oscilloscope, a logic analyser and Wireshark.

The application validates the complete script before it enables the W5500.
Invalid commands therefore cannot leave a demo half configured. It accepts
only locally administered unicast MAC addresses, such as
`02:00:00:00:00:01`, to avoid presenting a real vendor OUI as the Flipper's
identity.

## Hardware

| Order | W5500 | Flipper Zero GPIO | Physical pin | Logic 2 |
|---:|---|---|---:|---|
| 1 | MO / MOSI | PA7 | 2 | D0 / Channel 0 |
| 2 | MI / MISO | PA6 | 3 | D1 / Channel 1 |
| 3 | CS | PA4 | 4 | D2 / Channel 2 |
| 4 | SCK | PB3 | 5 | D3 / Channel 3 |
| 5 | RST | PC3 | 7 | D4 / Channel 4 |
| 6 | GND | GND | 8 or 11 | GND |
| 7 | V | 3V3 | 9 | Not connected |

In Logic 2, configure the SPI analyser with clock D3, MOSI D0, MISO D1 and
active-low enable D2. D4 records reset as a timing reference but is not part of
the SPI decoder. Use 24 MS/s or faster, SPI mode 0, 8-bit words and MSB first.

Use a W5500 board that accepts 3.3 V power and logic. If the board cannot be
powered within the Flipper GPIO rail's current budget, use a regulated external
3.3 V supply and join both grounds. The application releases the SPI bus and
returns its GPIO pins to their default state on exit.

## Build

From the project root, build against the pinned firmware submodule:

```sh
git submodule update --init third_party/flipperzero-firmware
scripts/build-flipper-app
```

The resulting `.fap` can be copied to `apps/GPIO` on the microSD card. On its
first run the app creates `/ext/apps_data/ethernet_lab/demo.eth`. Additional
`.eth` files placed in that directory appear in the file chooser.

Every execution overwrites `/ext/apps_data/ethernet_lab/last_run.log` with the
script path and the complete sequence of results. Each line is flushed as it is
produced, so the completed portion remains available if a demonstration is
cancelled.

The wrapper exposes this source tree temporarily under the firmware checkout's
`applications_user/` directory because FBT only discovers manifests from its
configured application directories. It removes the link after the build and
copies the result to `build/flipper/ethernet_lab.fap`.

The current build has been verified with official firmware `1.4.3` (API
`87.1`). Generated FAP files are ignored by Git.

## Script format

Every file starts with `ETHERNET-LAB/1`. Empty lines and text following `#`
are ignored. Keywords and symbolic values are uppercase.

| Command | Arguments | Effect |
|---|---|---|
| `MAC` | local-unicast MAC | Set the W5500 source MAC. |
| `IP`, `MASK`, `GATEWAY`, `DNS` | IPv4 address | Set static IPv4 configuration. |
| `DHCP` | optional timeout, 1000–30000 ms | Obtain IP, mask, gateway and DNS through a complete DHCP exchange. |
| `PHY` | `AUTO`, `10_HALF`, `10_FULL`, `100_HALF`, `100_FULL` | Select PHY negotiation or a forced mode. |
| `LINK` | optional timeout, 100–10000 ms | Wait for link and report speed/duplex. |
| `ARP` | IPv4, optional timeout and count | Request and report the target MAC; count is 1–30. |
| `PING` | IPv4, optional count, timeout and pattern | Send ICMP echoes. Patterns: `INCREMENT`, `00`, `FF`, `55`, `AA`. |
| `HTTP_GET` | IPv4, port, path and optional count | Make 1–30 HTTP/1.0 requests to a numeric address. |
| `WAIT` | 1–30000 ms | Pause while remaining cancellable. |
| `NOTE` | up to 96 characters | Put a cue in the on-device log. |

Files are limited to 16 KiB, 192 characters per line and 64 commands. A ping
count is capped at 30. Press Back during execution to cancel and release the
hardware.

The `DHCP` command performs Discover, Offer, Request and ACK using the WIZnet
ioLibrary client. The application calculates the ICMP checksum over each
selected payload. The W5500 constructs IPv4/TCP headers for its IPRAW and TCP
sockets and generates the Ethernet FCS on transmission. ARP is emitted through
MACRAW as a padded 60-byte frame; the controller appends its FCS. These
boundaries are useful in the presentation because they separate bytes produced
by the toolkit from fields produced by the Ethernet controller.

Version 0.2.0 was also exercised on hardware against the demonstration router:
the W5500 negotiated 10BASE-T full duplex, acquired a DHCP lease, resolved the
gateway by ARP, received all five patterned ICMP replies and completed the HTTP
request with status 200.

The bundled demonstration waits two seconds before the first measurement and
between successive network operations. This leaves enough time to rearm a
short, Manchester-resolving oscilloscope acquisition while the Flipper runs the
whole sequence only once.

See [`examples/demo.eth`](examples/demo.eth) for the sequence intended for the
project demonstration. Change the lab addresses before copying it to the SD
card. `HTTP_GET` deliberately supports clear-text HTTP only, because its
request is intended to remain inspectable in Wireshark.

[`examples/oscilloscope.eth`](examples/oscilloscope.eth) runs the same sequence
but forces 10BASE-T half duplex. A switch left in autonegotiation can identify
the forced 10 Mb/s speed through parallel detection and falls back to half
duplex, which avoids a duplex mismatch while exposing Manchester on the wire.

[`examples/oscilloscope-burst.eth`](examples/oscilloscope-burst.eth) repeats the
five ICMP payload patterns in five consecutive blocks of 300 echoes. Each block
lasts longer than a DOS1102 acquisition/download cycle, making it possible to
associate complete 10BASE-T frames with a known pattern. It is a capture aid
rather than an additional protocol test.

For repeatable demo captures, the five `examples/scope-*.eth` files isolate one
payload pattern per run and send 1200 echoes. A failed acquisition then requires
repeating only that pattern.

`examples/scope-arp.eth` sends 600 ARP requests. `examples/scope-http.eth`
opens 30 independent TCP connections and sends a plain HTTP GET request on each.
They are intended for isolated physical/SPI captures using the `arp` and `http`
arguments of `scripts/run-demo-capture`.

## Reused work

The project uses a small, attributed part of the MIT-licensed
`fz-W5500-lan-analyse` project and the official WIZnet ioLibrary. Details and
exact revisions are in [`THIRD_PARTY.md`](THIRD_PARTY.md).

## Development checks

The parser is platform-independent and can be tested without a Flipper SDK:

```sh
./src/flipper/ethernet_lab/tests/run.sh
```

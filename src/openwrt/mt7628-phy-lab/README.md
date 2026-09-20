# MT7628 PHY laboratory module

This package rebuilds the laboratory kernel module for the GL.iNet Mango
(GL-MT300N-V2) with OpenWrt 22.03.4.

The source in `src/` is the C file recovered from the project history. It
performs three MDIO writes:

1. select PHY page `0x8000`;
2. advertise `0x0041`, selector plus 10BASE-T full duplex;
3. write `0x1200` to restart autonegotiation.

The module defaults to safety mode. PHY registers are modified only when it is
loaded with `apply=1`.

Build it in the dedicated OpenWrt container:

```sh
docker compose run --rm openwrt
```

Outputs are written under `build/openwrt/`, including the `.ko`, an `.ipk`
package and the generated SHA-256 checksum.

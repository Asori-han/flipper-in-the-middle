# Changelog

## 0.2.2 - 2026-09-13

- Allow up to 30 echoes per `PING` command for deterministic oscilloscope bursts.

## 0.2.1 - 2026-09-13

- Add two-second observation gaps between the oscilloscope demonstration steps.

## 0.2.0 - 2026-09-13

- Add a complete DHCP client command backed by the WIZnet ioLibrary.
- Configure the demonstration for the `192.168.7.1` lab target after DHCP.

## 0.1.1 - 2026-09-13

- Persist the complete result of the latest execution in `last_run.log`.
- Flush every result line so an interrupted demonstration remains diagnosable.

## 0.1.0 - 2026-09-12

- Initial W5500 application for Flipper Zero.
- Versioned `.eth` scripts with full preflight validation.
- Link, ARP, patterned ICMP echo and HTTP/1.0 GET commands.
- Local-unicast MAC enforcement and cancellable execution log.

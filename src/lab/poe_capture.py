#!/usr/bin/env python3
"""Capture a PoE startup sequence with the DOS1102.

Intended workflow, with USB connected only at the endpoints:

    poe_capture.py probe                 # current status and settings
    poe_capture.py arm [options]         # configure and arm the trigger
    ... disconnect USB, apply PoE, wait, then disconnect PoE ...
    poe_capture.py collect               # confirm STOP and download DEPMem

``arm`` leaves the instrument in RUN waiting for a single trigger. It does not
query memory during acquisition because USB traffic can alter instrument state.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from scope import DOS1102, capture_info, samplerate_to_hz, save_capture

CAPTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "local" / "captures"

# Some diagnostic queries may be absent from this firmware. Report failures
# without aborting the complete probe.
PROBE_QUERIES = [
    ":TRIGger:SINGle:SWEep?",
    ":TRIGger:SINGle:MODE?",
    ":TRIGger:SINGle:EDGe:SOURce?",
    ":TRIGger:SINGle:EDGe:SLOPe?",
    ":TRIGger:SINGle:EDGe:LEVel?",
    ":TRIGger:SINGle:EDGe:COUPling?",
    ":ACQuire:DEPMEM?",
    ":ACQuire:MODE?",
    ":CH1:SCALe?",
    ":CH1:OFFSet?",
    ":CH1:COUPling?",
    ":CH1:PROBe?",
    ":CH1:DISPlay?",
    ":CH2:SCALe?",
    ":CH2:DISPlay?",
    ":HORIzontal:SCALe?",
    ":HORIzontal:OFFSet?",
]


def probe(scope):
    print(json.dumps(scope.status(), indent=2, ensure_ascii=False))
    print("\n=== direct queries ===")
    for q in PROBE_QUERIES:
        try:
            print(f"{q:38s} -> {scope.query_text(q)!r}")
        except Exception as exc:  # noqa: BLE001 - diagnostic query; do not abort
            print(f"{q:38s} -> ERROR {exc}")


def apply_and_verify(scope, command, query, settle=0.20):
    """Apply a setting and return the corresponding query response."""
    scope.send(command)
    time.sleep(settle)
    try:
        got = scope.query_text(query)
    except Exception as exc:  # noqa: BLE001
        got = f"ERROR {exc}"
    print(f"  {command:44s} {query:34s} -> {got!r}")
    return got


def arm(scope, args):
    print("Forcing initial STOP...")
    scope.ensure_stop(timeout=3.0)

    # Simultaneous voltage and current need different channel settings: line
    # voltage uses a 10x probe while the shunt drop uses a 1x probe.
    print("\nChannels:")
    for ch in ("CH1", "CH2"):
        on = "ON" if (ch == "CH1" or args.dual) else "OFF"
        apply_and_verify(scope, f":{ch}:DISPlay {on}", f":{ch}:DISPlay?")
        if on == "OFF":
            continue
        scale = args.scale if ch == "CH1" else (args.ch2_scale or args.scale)
        probe_setting = args.probe if ch == "CH1" else (args.ch2_probe or args.probe)
        apply_and_verify(scope, f":{ch}:PROBe {probe_setting}", f":{ch}:PROBe?")
        apply_and_verify(scope, f":{ch}:COUPling {args.coupling}", f":{ch}:COUPling?")
        apply_and_verify(scope, f":{ch}:SCALe {scale}", f":{ch}:SCALe?")
        apply_and_verify(scope, f":{ch}:OFFSet {args.offset}", f":{ch}:OFFSet?")

    print("\nTime base and memory:")
    if args.depmem:
        apply_and_verify(scope, f":ACQuire:DEPMEM {args.depmem}", ":ACQuire:DEPMEM?")
    apply_and_verify(scope, f":HORIzontal:SCALe {args.timebase}", ":HORIzontal:SCALe?")

    print("\nTrigger:")
    apply_and_verify(scope, ":TRIGger:SINGle:MODE EDGE", ":TRIGger:SINGle:MODE?")
    apply_and_verify(scope, f":TRIGger:SINGle:EDGe:SOURce {args.source}", ":TRIGger:SINGle:EDGe:SOURce?")
    apply_and_verify(scope, f":TRIGger:SINGle:EDGe:SLOPe {args.slope}", ":TRIGger:SINGle:EDGe:SLOPe?")
    apply_and_verify(scope, f":TRIGger:SINGle:EDGe:COUPling {args.trig_coupling}", ":TRIGger:SINGle:EDGe:COUPling?")
    apply_and_verify(scope, f":TRIGger:SINGle:EDGe:LEVel {args.level}", ":TRIGger:SINGle:EDGe:LEVel?")

    print("\nHeader before arming:")
    head = scope.head()
    print(json.dumps({"TIMEBASE": head.get("TIMEBASE"), "SAMPLE": head.get("SAMPLE"),
                      "Trig": head.get("Trig"), "RUNSTATUS": head.get("RUNSTATUS")},
                     indent=2, ensure_ascii=False))

    # Ordering matters. A sweep set before RUN reverts to AUTO. SINGLE after RUN
    # leaves the instrument in STOP. Only NORMal after RUN reaches READY.
    print("\nArming (RUN followed by sweep)...")
    scope.run()
    time.sleep(0.5)
    apply_and_verify(scope, f":TRIGger:SINGle:SWEep {args.sweep}", ":TRIGger:SINGle:SWEep?")

    seen = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.watch:
        st = scope.trigger_status()
        if not seen or seen[-1][1] != st:
            seen.append((round(time.monotonic() - t0, 2), st))
        time.sleep(0.15)
    print("Observed states:", seen)
    final = seen[-1][1] if seen else None
    if final == "READY":
        print("\nARMED and waiting for a trigger. Do not send commands until after the event.")
    elif final == "SCAN":
        print("\nWARNING: rolling mode. Triggering is inactive at this time base and\n"
              "the startup will not freeze. Use a faster time base.")
    elif final == "STOP":
        print("\nWARNING: the instrument is in STOP and is not acquiring.")
    else:
        print(f"\nWARNING: status {final}; READY was not confirmed.")
    return final


def collect(scope, args):
    st = scope.trigger_status()
    print("Status on connection:", st)
    if st != "STOP":
        if args.force_stop:
            print("Sending STOP...")
            scope.ensure_stop(timeout=3.0)
        else:
            raise SystemExit("The instrument is not in STOP. Use --force-stop if appropriate.")

    meta, ch1, ch2, raw = scope.deepmem()
    info = capture_info(meta)
    prefix = CAPTURE_DIR / f"{args.name}_{time.strftime('%Y%m%d_%H%M%S')}"
    files = save_capture(meta, ch1, ch2, raw, str(prefix))

    print("\n=== CAPTURE ===")
    print(json.dumps(info, indent=2))
    for ch, data in (("ch1", ch1), ("ch2", ch2)):
        arr = np.asarray(data, dtype=float)
        if arr.size == 0:
            print(f"{ch}: channel disabled, no samples")
            continue
        print(f"{ch}: n={arr.size} min={arr.min():.0f} max={arr.max():.0f} "
              f"mean={arr.mean():.1f} first={arr[:4].astype(int).tolist()} "
              f"last={arr[-4:].astype(int).tolist()}")
    duration = info["duration_s"]
    print(f"\nCaptured window: {duration*1e3:.3f} ms "
          f"({'too short' if duration < 0.05 else 'compatible'} with a PoE startup lasting tens or hundreds of ms)")
    for f in files:
        print(f)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("probe")

    a = sub.add_parser("arm")
    a.add_argument("--scale", default="2V", help="native scale per division")
    a.add_argument("--offset", default="0")
    a.add_argument("--probe", default="10X")
    a.add_argument("--coupling", default="DC")
    a.add_argument("--timebase", default="50ms")
    a.add_argument("--depmem", default="", help="memory depth, such as 10K or 10M")
    a.add_argument("--source", default="CH1")
    a.add_argument("--slope", default="RISE", choices=["RISE", "FALL"])
    a.add_argument("--level", default="10V")
    a.add_argument("--sweep", default="NORMal", choices=["AUTO", "NORMal", "SINGLE"])
    a.add_argument("--trig-coupling", default="DC")
    a.add_argument("--dual", action="store_true", help="keep CH2 enabled")
    a.add_argument("--ch2-scale", default="", help="CH2 scale when different from CH1")
    a.add_argument("--ch2-probe", default="", help="CH2 probe setting when different from CH1")
    a.add_argument("--watch", type=float, default=1.5, help="seconds to observe after RUN")

    c = sub.add_parser("collect")
    c.add_argument("--name", default="poe")
    c.add_argument("--force-stop", action="store_true")

    args = p.parse_args()
    scope = DOS1102()

    if args.command == "probe":
        probe(scope)
    elif args.command == "arm":
        arm(scope, args)
    elif args.command == "collect":
        collect(scope, args)


if __name__ == "__main__":
    main()

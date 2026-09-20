#!/usr/bin/env python3
"""Prepare the DOS1102 for a live PoE demonstration.

CH1 continuously displays line voltage and CH2 displays current, making cable
connection and removal visible on the oscilloscope itself. This mode does not
arm a single trigger.

Both probe ground clips must connect to the same node because they are common
inside the instrument. The assumed circuit is documented in the paper's PoE
annex.
"""

import argparse
import time

from scope import DOS1102

# With a 10x probe, a native 2 V scale means 20 V/div and leaves headroom for
# the 53 V line and its input transient.
VOLTAGE_SCALE = "2V"
# With a 1x probe, 200 mV/div and two 10-ohm branches represent 40 mA/div.
CURRENT_SCALE = "200mV"


def apply(scope, command, query, settle=0.25):
    scope.send(command)
    time.sleep(settle)
    try:
        return scope.query_text(query)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {exc}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timebase", default="50ms")
    p.add_argument("--rolling", action="store_true",
                   help="100 ms/div rolling trace without a trigger")
    p.add_argument("--voltage-scale", default=VOLTAGE_SCALE)
    p.add_argument("--current-scale", default=CURRENT_SCALE)
    p.add_argument("--shunt", type=float, default=10.0,
                   help="used only in the printed summary")
    p.add_argument("--branches", type=int, default=2)
    p.add_argument("--screenshot", default="", help="save the screen to this BMP file")
    args = p.parse_args()

    base = "100ms" if args.rolling else args.timebase

    scope = DOS1102()
    scope.resync()
    print("Instrument:", scope.idn())
    scope.ensure_stop(timeout=3.0)

    settings = [
        (":CH1:DISPlay ON", ":CH1:DISPlay?"),
        (":CH1:PROBe 10X", ":CH1:PROBe?"),
        (":CH1:COUPling DC", ":CH1:COUPling?"),
        (f":CH1:SCALe {args.voltage_scale}", ":CH1:SCALe?"),
        (":CH1:OFFSet 0", ":CH1:OFFSet?"),
        (":CH2:DISPlay ON", ":CH2:DISPlay?"),
        (":CH2:PROBe 1X", ":CH2:PROBe?"),
        (":CH2:COUPling DC", ":CH2:COUPling?"),
        (f":CH2:SCALe {args.current_scale}", ":CH2:SCALe?"),
        (":CH2:OFFSet 0", ":CH2:OFFSet?"),
        (":ACQuire:DEPMEM 10K", ":ACQuire:DEPMEM?"),
        (f":HORIzontal:SCALe {base}", ":HORIzontal:SCALe?"),
    ]
    print("\nSettings:")
    for command, query in settings:
        print(f"  {command:28s} -> {apply(scope, command, query)!r}")

    # The instrument reverts a sweep set before RUN, so apply it afterward.
    print("\nStarting continuous acquisition...")
    scope.run()
    time.sleep(0.5)
    print(f"  sweep -> {apply(scope, ':TRIGger:SINGle:SWEep AUTO', ':TRIGger:SINGle:SWEep?')!r}")

    time.sleep(1.0)
    status = scope.trigger_status()
    print(f"  status -> {status}")

    if args.screenshot:
        n = scope.screenshot(args.screenshot)
        print(f"  screen saved to {args.screenshot} ({n} bytes)")

    current_per_division = None
    try:
        volts = float(args.current_scale.replace("mV", "e-3").replace("V", ""))
        current_per_division = volts / args.shunt * args.branches * 1e3
    except ValueError:
        pass

    print("\n--- ready for the demonstration ---")
    print(f"  time base: {base}" + (" (rolling mode)" if args.rolling else ""))
    print("  CH1, lower trace: line voltage, 20 V per division")
    if current_per_division:
        print(f"  CH2, upper trace: total current, {current_per_division:.0f} mA per division")
    print("  CH1 appears negative because its reference is the positive conductor.")
    if status == "SCAN":
        print("  Rolling mode advances continuously and does not trigger.")
    elif status != "AUTO":
        print(f"  WARNING: status is {status}; expected AUTO.")


if __name__ == "__main__":
    main()

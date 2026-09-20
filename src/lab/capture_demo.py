#!/usr/bin/env python3
"""Synchronize a DOS1102, Logic 2, and Flipper Zero capture.

Logic 2 is controlled through the official logic2-automation library. The
Flipper must display the selected script with its start action highlighted;
the program sends a short OK press after arming both instruments.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scope import DOS1102, capture_info, save_many
from scope_validation import validate_scope_captures


DEFAULT_LOGIC_APP = "/Applications/Saleae Logic.app/Contents/MacOS/Logic"
DEFAULT_FLIPPER_LOG = "/ext/apps_data/ethernet_lab/last_run.log"


class RunLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def detect_flipper_port(requested: str | None) -> str:
    if requested:
        return requested
    matches = sorted(glob.glob("/dev/cu.usbmodemflip_*"))
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one Flipper at /dev/cu.usbmodemflip_*; "
            f"found: {matches or 'none'}. Use --flipper-port."
        )
    return matches[0]


def import_flipper_proto(extra_source: str | None):
    if extra_source:
        sys.path.insert(0, str(Path(extra_source).expanduser().resolve()))
    else:
        checkout = (Path(__file__).resolve().parents[2] / "build" / "cache" /
                    "deps" / "flipperzero_protobuf_py")
        if checkout.is_dir():
            sys.path.insert(0, str(checkout))
    try:
        from flipperzero_protobuf.flipper_proto import FlipperProto
    except ImportError as exc:
        raise RuntimeError(
            "flipperzero_protobuf is missing. Run scripts/setup-demo-capture or "
            "provide its checkout with --flipper-protobuf-source."
        ) from exc
    return FlipperProto


@contextmanager
def flipper_connection(port: str, extra_source: str | None):
    FlipperProto = import_flipper_proto(extra_source)
    proto = FlipperProto(port)
    try:
        yield proto
    finally:
        serial_connection = getattr(proto, "_serial", None)
        if serial_connection is not None:
            serial_connection.close()


def press_flipper_ok(port: str, extra_source: str | None) -> None:
    with flipper_connection(port, extra_source) as proto:
        proto.rpc_gui_send_input("SHORT OK")


def read_flipper_log(port: str, remote_path: str, extra_source: str | None) -> bytes:
    with flipper_connection(port, extra_source) as proto:
        return proto.rpc_read(remote_path)


def import_saleae_automation():
    try:
        from saleae import automation
    except ImportError as exc:
        raise RuntimeError(
            "logic2-automation is missing. Run scripts/setup-demo-capture."
        ) from exc
    return automation


def open_logic_manager(args: argparse.Namespace, automation):
    if args.logic_mode == "connect":
        return automation.Manager.connect(
            address=args.logic_address,
            port=args.logic_port,
            connect_timeout_seconds=10.0,
        )
    app = Path(args.logic_app).expanduser().resolve()
    if not app.is_file():
        raise RuntimeError(f"Logic 2 executable not found: {app}")
    return automation.Manager.launch(
        application_path=app,
        port=args.logic_port,
        connect_timeout_seconds=30.0,
    )


def logic_device_configuration(args: argparse.Namespace, automation):
    values: dict[str, Any] = {
        "enabled_digital_channels": [0, 1, 2, 3, 4],
        "digital_sample_rate": args.logic_sample_rate,
    }
    if args.digital_threshold is not None:
        values["digital_threshold_volts"] = args.digital_threshold
    return automation.LogicDeviceConfiguration(**values)


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def arm_scope(scope: DOS1102) -> float:
    """Arm the DOS1102 in the order required by its firmware."""
    scope.run()
    # Allow firmware to settle after RUN. At 50 ms it accepted the sweep
    # command intermittently and left some windows in AUTO.
    time.sleep(0.5)
    # The DOS1102 reverts this setting to AUTO if applied before RUN. NORMal
    # aligns acquisitions to an Ethernet edge instead of arbitrary windows.
    for _attempt in range(3):
        scope.send(":TRIGger:SINGle:SWEep NORMal")
        time.sleep(0.1)
        effective = scope.query_text(":TRIGger:SINGle:SWEep?")
        if effective and effective.upper().startswith("NORM"):
            break
    else:
        raise RuntimeError(
            f"The DOS1102 did not confirm NORMal sweep; received: {effective!r}"
        )
    return time.monotonic()


def collect_scope_windows(
    scope: DOS1102,
    deadline: float,
    time_origin: float,
    first_started_at: float,
    window_seconds: float,
    pause_seconds: float,
    runlog: RunLog,
    required_pattern: str,
):
    captures = []
    armed_at = first_started_at
    index = 1
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        dwell = min(window_seconds, remaining)
        runlog.write(f"DOS1102 window {index}: RUN for {dwell:.3f} s")
        time.sleep(dwell)
        scope.ensure_stop(timeout=2.0)
        meta, ch1, ch2, _raw = scope.deepmem()
        captures.append((meta, ch1, ch2, armed_at - time_origin))
        info = capture_info(meta)
        runlog.write(
            "DOS1102 window "
            f"{index}: {info['datalen']} samples, {info['samplerate_text']}, "
            f"{info['duration_us']:.1f} us"
        )
        if validate_scope_captures(
            captures, required_patterns={required_pattern}
        )["passed"]:
            runlog.write(f"DOS1102: recovered {required_pattern}; stopping search")
            break
        if time.monotonic() + pause_seconds >= deadline:
            break
        time.sleep(pause_seconds)
        armed_at = arm_scope(scope)
        index += 1
    return captures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture DOS1102, Logic 2, and the Flipper log together"
    )
    parser.add_argument(
        "pattern",
        choices=("increment", "00", "ff", "55", "aa", "arp", "http"),
        help="single test represented by the script selected on the Flipper",
    )
    parser.add_argument("--duration", type=float, default=18.0, help="Logic 2 duration in seconds")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "local" / "evidence" / "demo-runs",
    )
    parser.add_argument("--name", help="directory name; defaults to date and time")
    parser.add_argument("--logic-mode", choices=("launch", "connect"), default="launch")
    parser.add_argument("--logic-app", default=DEFAULT_LOGIC_APP)
    parser.add_argument("--logic-address", default="127.0.0.1")
    parser.add_argument("--logic-port", type=int, default=10430)
    parser.add_argument("--logic-device", help="device ID; defaults to the first physical device")
    parser.add_argument("--logic-sample-rate", type=int, default=12_000_000)
    parser.add_argument("--digital-threshold", type=float)
    parser.add_argument("--scope-timebase", default="10us")
    parser.add_argument("--scope-trigger-level", default="0.30V")
    parser.add_argument("--scope-window", type=float, default=0.1)
    parser.add_argument("--scope-pause", type=float, default=0.15)
    parser.add_argument("--flipper-port")
    parser.add_argument("--flipper-log", default=DEFAULT_FLIPPER_LOG)
    parser.add_argument(
        "--flipper-protobuf-source",
        help="alternative flipperzero_protobuf_py checkout",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the plan without accessing hardware")
    return parser


def run(args: argparse.Namespace) -> Path:
    if args.duration <= 0 or args.scope_window <= 0 or args.scope_pause < 0:
        raise ValueError("Duration and window must be positive; pause cannot be negative")

    scope_required = "tcp80" if args.pattern == "http" else args.pattern
    if args.pattern == "http":
        if args.scope_trigger_level == "0.30V":
            args.scope_trigger_level = "0.70V"
        if args.scope_window == 0.1:
            args.scope_window = 0.5

    run_name = args.name or (
        datetime.now().astimezone().strftime("%Y%m%d_%H%M%S") + f"_{args.pattern}"
    )
    output_dir = args.output_root.expanduser().resolve() / run_name
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")

    if args.dry_run:
        print(json.dumps({
            "output_dir": str(output_dir),
            "duration_seconds": args.duration,
            "logic_mode": args.logic_mode,
            "logic_endpoint": f"{args.logic_address}:{args.logic_port}",
            "logic_channels": [0, 1, 2, 3, 4],
            "logic_sample_rate": args.logic_sample_rate,
            "scope_timebase": args.scope_timebase,
            "scope_trigger_level": args.scope_trigger_level,
            "scope_window_seconds": args.scope_window,
            "pattern": args.pattern,
            "flipper_action": "SHORT OK",
            "flipper_log": args.flipper_log,
        }, indent=2, ensure_ascii=False))
        return output_dir

    output_dir.mkdir(parents=True)
    runlog = RunLog(output_dir / "capture.log")
    manifest: dict[str, Any] = {
        "status": "running",
        "started_utc": utc_now(),
        "duration_seconds": args.duration,
        "pattern": args.pattern,
        "wiring": {"D0": "MOSI", "D1": "MISO", "D2": "CS", "D3": "SCK", "D4": "RST"},
        "logic2": {
            "mode": args.logic_mode,
            "address": args.logic_address,
            "port": args.logic_port,
            "device_id": args.logic_device,
            "sample_rate": args.logic_sample_rate,
        },
        "oscilloscope": {
            "timebase": args.scope_timebase,
            "trigger": {
                "mode": "EDGE",
                "source": "CH1",
                "slope": "RISE",
                "coupling": "DC",
                "level": args.scope_trigger_level,
            },
        },
        "outputs": {},
        "errors": [],
    }
    save_manifest(output_dir / "manifest.json", manifest)

    logic_capture = None
    logic_finished = False
    manager = None
    scope = None
    flipper_port = detect_flipper_port(args.flipper_port)
    try:
        automation = import_saleae_automation()
        runlog.write("Preparing DOS1102")
        scope = DOS1102()
        scope.ensure_stop(timeout=2.0)
        effective_timebase = scope.set_timebase(args.scope_timebase)
        manifest["oscilloscope"]["effective_timebase"] = effective_timebase
        for command in (
            ":TRIGger:SINGle:MODE EDGE",
            ":TRIGger:SINGle:EDGe:SOURce CH1",
            ":TRIGger:SINGle:EDGe:SLOPe RISE",
            ":TRIGger:SINGle:EDGe:COUPling DC",
            f":TRIGger:SINGle:EDGe:LEVel {args.scope_trigger_level}",
        ):
            scope.send(command)
            time.sleep(0.05)
        effective_level = scope.query_text(":TRIGger:SINGle:EDGe:LEVel?")
        manifest["oscilloscope"]["trigger"]["effective_level"] = effective_level
        runlog.write(f"Trigger DOS1102: CH1 RISE, effective level {effective_level}")

        runlog.write(f"Connecting to Logic 2 over gRPC at {args.logic_address}:{args.logic_port}")
        manager = open_logic_manager(args, automation)
        devices = manager.get_devices()
        manifest["logic2"]["detected_devices"] = [
            {"id": d.device_id, "type": str(d.device_type), "simulation": d.is_simulation}
            for d in devices
        ]
        config = logic_device_configuration(args, automation)
        capture_config = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=args.duration)
        )
        runlog.write("Arming Logic 2")
        logic_capture = manager.start_capture(
            device_id=args.logic_device,
            device_configuration=config,
            capture_configuration=capture_config,
        )
        logic_started = time.monotonic()
        deadline = logic_started + args.duration

        runlog.write("Arming DOS1102")
        first_scope_started = arm_scope(scope)

        runlog.write(f"Both instruments armed; sending SHORT OK to the Flipper at {flipper_port}")
        press_flipper_ok(flipper_port, args.flipper_protobuf_source)
        manifest["flipper_ok_utc"] = utc_now()

        scope_captures = collect_scope_windows(
            scope,
            deadline,
            logic_started,
            first_scope_started,
            args.scope_window,
            args.scope_pause,
            runlog,
            scope_required,
        )
        if scope_captures:
            scope_path = output_dir / "oscilloscope-many.npz"
            save_many(scope_captures, str(scope_path))
            manifest["outputs"]["oscilloscope"] = scope_path.name
            manifest["oscilloscope"]["windows"] = len(scope_captures)
            validation = validate_scope_captures(
                scope_captures, required_patterns={scope_required}
            )
            validation_path = output_dir / "scope-validation.json"
            save_manifest(validation_path, validation)
            manifest["outputs"]["scope_validation"] = validation_path.name
            manifest["oscilloscope"]["validation_passed"] = validation["passed"]
            if validation["passed"]:
                runlog.write(
                    f"DOS1102 validated: {scope_required} with valid preamble, SFD, and FCS"
                )
            else:
                missing = ", ".join(validation["missing_patterns"])
                runlog.write(f"DOS1102 WARNING: complete frames are missing for: {missing}")

        runlog.write("Waiting for the timed Logic 2 capture to finish")
        logic_capture.wait()
        logic_finished = True

        runlog.write("Adding the SPI analyzer and exporting Logic 2")
        spi = logic_capture.add_analyzer(
            "SPI",
            label="Flipper-W5500",
            settings={
                "MOSI": 0,
                "MISO": 1,
                "Enable": 2,
                "Clock": 3,
                "Bits per Transfer": "8 Bits per Transfer (Standard)",
            },
        )
        sal_path = output_dir / "logic2.sal"
        digital_path = output_dir / "digital.csv"
        spi_path = output_dir / "spi.csv"
        logic_capture.export_raw_data_csv(directory=str(output_dir), digital_channels=[0, 1, 2, 3, 4])
        logic_capture.export_data_table(
            filepath=str(spi_path),
            analyzers=[automation.DataTableExportConfiguration(spi, automation.RadixType.HEXADECIMAL)],
        )
        logic_capture.save_capture(filepath=str(sal_path))
        manifest["outputs"].update({"logic2": sal_path.name, "digital_csv": digital_path.name, "spi_csv": spi_path.name})

        runlog.write("Reading Flipper last_run.log")
        flipper_log = read_flipper_log(flipper_port, args.flipper_log, args.flipper_protobuf_source)
        flipper_log_path = output_dir / "flipper-last_run.log"
        flipper_log_path.write_bytes(flipper_log)
        manifest["outputs"]["flipper_log"] = flipper_log_path.name
        manifest["status"] = "complete"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["errors"].append(f"{type(exc).__name__}: {exc}")
        runlog.write(f"ERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise
    finally:
        if scope is not None:
            try:
                scope.stop()
            except Exception as exc:
                manifest["errors"].append(f"Error stopping DOS1102: {exc}")
        if logic_capture is not None:
            try:
                if not logic_finished:
                    logic_capture.stop()
                logic_capture.close()
            except Exception as exc:
                manifest["errors"].append(f"Error closing Logic 2: {exc}")
        if manager is not None:
            try:
                manager.close()
            except Exception as exc:
                manifest["errors"].append(f"Error closing Logic 2 manager: {exc}")
        manifest["finished_utc"] = utc_now()
        save_manifest(output_dir / "manifest.json", manifest)
        runlog.write(f"Test directory: {output_dir}")
    return output_dir


def main() -> int:
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

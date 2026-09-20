#!/usr/bin/env python3

import argparse
import json
import time
from pathlib import Path

import numpy as np
import usb.core
import usb.util

VID = 0x5345
PID = 0x1234
EP_OUT = 0x01
EP_IN = 0x81
DEFAULT_TIMEBASE = "10us"
DEFAULT_ACQUIRE_TIME = 0.5


def json_end(buf, start):
    """Return the end offset of the JSON object beginning at `start`."""
    depth = 0
    for i in range(start, len(buf)):
        b = buf[i]
        if b == 0x7B:
            depth += 1
        elif b == 0x7D:
            depth -= 1
            if depth == 0:
                return i + 1
    raise RuntimeError("The end of the JSON object was not found in the response")


class DOS1102:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("Hanmatek DOS1102 not found")
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass

    def drain(self):
        while True:
            try:
                self.dev.read(EP_IN, 64, timeout=20)
            except (usb.core.USBTimeoutError, usb.core.USBError):
                break

    def flush(self, timeout=200):
        """Discard pending responses with a longer wait.

        ``drain`` uses 20 ms and misses late replies. An interrupted transfer
        can leave bytes in the channel and shift every subsequent response.
        """
        discarded = 0
        while True:
            try:
                discarded += len(self.dev.read(EP_IN, 8192, timeout=timeout))
            except (usb.core.USBTimeoutError, usb.core.USBError):
                return discarded

    def reconnect(self):
        """Reset the USB device when draining alone cannot recover the channel."""
        try:
            self.dev.reset()
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)
        time.sleep(1.0)
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("Hanmatek DOS1102 not found after the USB reset")
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass

    def resync(self, retries=4):
        """Leave the channel synchronized so each query receives its own response."""
        self.flush()
        for attempt in range(retries):
            idn = self.query_text("*IDN?")
            status = self.query_text(":TRIG:STAT?")
            if "HANMATEK" in idn and status and "HANMATEK" not in status:
                return True
            if attempt == 1:
                self.reconnect()
            else:
                self.flush()
            time.sleep(0.3)
        raise RuntimeError("The USB channel could not be synchronized")

    def send(self, cmd):
        self.drain()
        self.dev.write(EP_OUT, cmd.encode("ascii"), timeout=500)

    def query_short(self, cmd, timeout=500):
        self.drain()
        self.dev.write(EP_OUT, cmd.encode("ascii"), timeout=500)
        chunks = []
        while True:
            try:
                data = bytes(self.dev.read(EP_IN, 4096, timeout=timeout))
            except usb.core.USBTimeoutError:
                break
            chunks.append(data)
            if len(data) < 64:
                break
        return b"".join(chunks)

    def query_text(self, cmd, timeout=500):
        raw = self.query_short(cmd, timeout=timeout)
        return raw.decode("ascii", errors="replace").replace("->", "").strip()

    def query_length_prefixed(self, cmd, timeout=2500):
        # A RUN/STOP cycle leaves status responses in the channel. Drain them
        # with a long timeout so they cannot shift the transfer header.
        self.flush()
        self.dev.write(EP_OUT, cmd.encode("ascii"), timeout=1000)
        raw = bytearray()
        expected = None
        while True:
            try:
                data = bytes(self.dev.read(EP_IN, 4096, timeout=timeout))
            except usb.core.USBTimeoutError:
                raise RuntimeError(f"Timed out reading {cmd}: received {len(raw)} bytes")
            raw.extend(data)
            if expected is None and len(raw) >= 4:
                payload_len = int.from_bytes(raw[:4], "little")
                expected = payload_len + 4
            if expected is not None and len(raw) >= expected:
                break
        return bytes(raw[:expected])

    def idn(self):
        return self.query_text("*IDN?")

    def trigger_status(self):
        text = self.query_text(":TRIG:STAT?")
        return text.upper() if text else None

    def head(self):
        raw = self.query_length_prefixed(":DATA:WAVE:SCREen:HEAD?")
        return json.loads(raw[4:].decode("utf-8"))

    def horizontal_scale(self):
        return self.query_text(":HORIzontal:SCALe?")

    def status(self):
        h = self.head()
        return {
            "idn": self.idn(),
            "trigger_status": self.trigger_status(),
            "horizontal_scale_query": self.horizontal_scale(),
            "runstatus": h.get("RUNSTATUS"),
            "timebase": h.get("TIMEBASE"),
            "sample": h.get("SAMPLE"),
            "channels": h.get("CHANNEL"),
            "trigger": h.get("Trig"),
        }

    def run(self):
        self.send(":RUNning RUN")

    def stop(self):
        self.send(":RUNning STOP")

    def wait_for_status(self, wanted, timeout=2.0, interval=0.10):
        wanted = wanted.upper()
        start = time.monotonic()
        last = None
        while time.monotonic() - start < timeout:
            status = self.trigger_status()
            if status != last:
                print(f"  status: {status}")
                last = status
            if status == wanted:
                return status
            time.sleep(interval)
        raise RuntimeError(f"Timed out waiting for {wanted}; last status={last}")

    def ensure_stop(self, timeout=2.0):
        self.stop()
        return self.wait_for_status("STOP", timeout=timeout)

    def set_timebase(self, scale, settle=0.20):
        self.send(f":HORIzontal:SCALe {scale}")
        time.sleep(settle)
        return self.horizontal_scale()

    def screenshot(self, filename):
        raw = self.query_length_prefixed(":DATA:WAVE:SCREen:BMP?", timeout=3000)
        bmp = raw[4:]
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bmp)
        return len(bmp)

    def deepmem(self):
        raw = self.query_length_prefixed(":DATA:WAVE:DEPMem:All?", timeout=3000)
        pos = 4
        json_len = int.from_bytes(raw[pos:pos+4], "little")
        pos += 4
        # The declared length is unreliable on this firmware. Find the actual
        # JSON boundary by balancing braces.
        end = json_end(raw, pos)
        if end != pos + json_len:
            print(f"warning: declared json_len {json_len}, actual length {end - pos}")
        meta = json.loads(raw[pos:end].decode("utf-8"))
        pos = end

        def read_block():
            nonlocal pos
            block_len = int.from_bytes(raw[pos:pos+4], "little")
            pos += 4
            payload = raw[pos:pos+block_len]
            pos += block_len
            if len(payload) != block_len:
                raise RuntimeError("Incomplete DEPMem block")
            if block_len % 2:
                raise RuntimeError("Odd-length DEPMem block")
            return np.frombuffer(payload, dtype="<i2").copy()

        ch1 = read_block()
        # With one channel disabled, the instrument returns a single sample block.
        if len(raw) - pos >= 4:
            ch2 = read_block()
        else:
            ch2 = np.zeros(0, dtype="<i2")
        if pos != len(raw):
            raise RuntimeError(f"Parser stopped at {pos}, response has {len(raw)} bytes")
        return meta, ch1, ch2, raw

    def acquire_once(self, timebase=DEFAULT_TIMEBASE, acquire_time=DEFAULT_ACQUIRE_TIME):
        print("Forcing initial STOP...")
        self.ensure_stop(timeout=2.0)

        print(f"Setting time base to {timebase}...")
        actual_scale = self.set_timebase(timebase)
        print("Effective time base:", actual_scale)

        print("Arming acquisition...")
        self.run()
        print(f"RUN for {acquire_time:.3f} s without USB polling...")
        time.sleep(acquire_time)

        print("Stopping acquisition...")
        self.ensure_stop(timeout=2.0)

        print("STOP confirmed; downloading DEPMem...")
        meta, ch1, ch2, raw = self.deepmem()
        sample = meta["SAMPLE"]
        print("DEPMem:", meta["TIMEBASE"]["SCALE"], sample["SAMPLERATE"], sample["DATALEN"], "samples")
        return meta, ch1, ch2, raw


def samplerate_to_hz(text):
    s = text.replace("(", "").replace(")", "").replace("S/s", "").strip()
    if s.endswith("G"):
        return float(s[:-1]) * 1e9
    if s.endswith("M"):
        return float(s[:-1]) * 1e6
    if s.endswith("K"):
        return float(s[:-1]) * 1e3
    return float(s)


def capture_info(meta):
    sample = meta["SAMPLE"]
    fs = samplerate_to_hz(sample["SAMPLERATE"])
    n = int(sample["DATALEN"])
    duration_s = n / fs
    return {
        "timebase": meta["TIMEBASE"]["SCALE"],
        "samplerate_text": sample["SAMPLERATE"],
        "samplerate_hz": fs,
        "datalen": n,
        "duration_s": duration_s,
        "duration_us": duration_s * 1e6,
        "sample_period_ns": 1e9 / fs,
        "samples_per_10base_bit": fs / 10e6,
    }


def save_capture(meta, ch1, ch2, raw, prefix):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    info = capture_info(meta)
    np.savez_compressed(
        str(prefix) + ".npz",
        ch1=ch1,
        ch2=ch2,
        metadata_json=json.dumps(meta),
        capture_info_json=json.dumps(info),
        samplerate_hz=info["samplerate_hz"],
        duration_us=info["duration_us"],
        sample_period_ns=info["sample_period_ns"],
        samples_per_10base_bit=info["samples_per_10base_bit"],
    )
    Path(str(prefix) + ".json").write_text(json.dumps({"metadata": meta, "capture_info": info}, indent=2))
    Path(str(prefix) + ".raw").write_bytes(raw)
    return str(prefix) + ".npz", str(prefix) + ".json", str(prefix) + ".raw"


def save_many(captures, filename):
    if not captures:
        raise RuntimeError("There are no captures to save")
    ch1_all = np.stack([x[1] for x in captures])
    ch2_all = np.stack([x[2] for x in captures])
    timestamps = np.asarray([x[3] for x in captures], dtype=float)
    metadata_json = np.asarray([json.dumps(x[0]) for x in captures])
    info_json = np.asarray([json.dumps(capture_info(x[0])) for x in captures])
    samplerates = np.asarray([capture_info(x[0])["samplerate_hz"] for x in captures], dtype=float)
    durations_us = np.asarray([capture_info(x[0])["duration_us"] for x in captures], dtype=float)
    samples_per_bit = np.asarray([capture_info(x[0])["samples_per_10base_bit"] for x in captures], dtype=float)
    np.savez_compressed(
        filename,
        ch1=ch1_all,
        ch2=ch2_all,
        timestamps=timestamps,
        metadata_json=metadata_json,
        capture_info_json=info_json,
        samplerate_hz=samplerates,
        duration_us=durations_us,
        samples_per_10base_bit=samples_per_bit,
    )


def main():
    parser = argparse.ArgumentParser(description="Control the Hanmatek DOS1102 over USB")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("run")
    sub.add_parser("stop")

    p = sub.add_parser("set-timebase")
    p.add_argument("scale")

    p = sub.add_parser("screenshot")
    p.add_argument("filename", nargs="?", default="data/local/captures/screen.bmp")

    p = sub.add_parser("capture")
    p.add_argument("--prefix", default="data/local/captures/capture")

    p = sub.add_parser("acquire-once")
    p.add_argument("--prefix", default="data/local/captures/ethernet")
    p.add_argument("--timebase", default=DEFAULT_TIMEBASE)
    p.add_argument("--time", type=float, default=DEFAULT_ACQUIRE_TIME)

    p = sub.add_parser("acquire-many")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--pause", type=float, default=0.25)
    p.add_argument("--time", type=float, default=DEFAULT_ACQUIRE_TIME)
    p.add_argument("--timebase", default=DEFAULT_TIMEBASE)
    p.add_argument("--prefix", default="data/local/captures/ethernet")

    args = parser.parse_args()
    scope = DOS1102()

    if args.command == "status":
        print(json.dumps(scope.status(), indent=2))
    elif args.command == "run":
        scope.run(); time.sleep(0.15); print("Status:", scope.trigger_status())
    elif args.command == "stop":
        scope.ensure_stop(timeout=2.0); print("Status:", scope.trigger_status())
    elif args.command == "set-timebase":
        scope.ensure_stop(timeout=2.0); print("Effective time base:", scope.set_timebase(args.scale))
    elif args.command == "screenshot":
        n = scope.screenshot(args.filename); print(f"Saved {args.filename} ({n} bytes)")
    elif args.command == "capture":
        if scope.trigger_status() != "STOP":
            raise SystemExit("The oscilloscope must be in STOP.")
        meta, ch1, ch2, raw = scope.deepmem()
        info = capture_info(meta)
        files = save_capture(meta, ch1, ch2, raw, args.prefix)
        print(json.dumps(info, indent=2))
        for f in files: print(f)
    elif args.command == "acquire-once":
        meta, ch1, ch2, raw = scope.acquire_once(timebase=args.timebase, acquire_time=args.time)
        info = capture_info(meta)
        files = save_capture(meta, ch1, ch2, raw, args.prefix)
        print("\n=== CAPTURE ===")
        print(json.dumps(info, indent=2))
        for f in files: print(f)
    elif args.command == "acquire-many":
        captures = []
        start = time.monotonic()
        print(f"Capturing {args.count} acquisitions")
        print("Timebase:", args.timebase)
        print("RUN per cycle:", args.time, "s")
        print("Pause:", args.pause, "s\n")
        for i in range(1, args.count + 1):
            print(f"=== {i}/{args.count} ===")
            try:
                meta, ch1, ch2, raw = scope.acquire_once(timebase=args.timebase, acquire_time=args.time)
            except Exception as e:
                print("ERROR:", e)
                print("Aborting to avoid repeatedly querying the firmware.")
                break
            timestamp = time.monotonic() - start
            captures.append((meta, ch1, ch2, timestamp))
            info = capture_info(meta)
            print(f"OK: {info['datalen']} samples, {info['samplerate_text']}, {info['duration_us']:.1f} us, {info['samples_per_10base_bit']:.1f} samples/bit")
            if i < args.count:
                print(f"Pause {args.pause}s")
                time.sleep(args.pause)
            print()
        if not captures:
            raise SystemExit("No capture was obtained.")
        outfile = args.prefix + "_many.npz"
        Path(outfile).parent.mkdir(parents=True, exist_ok=True)
        save_many(captures, outfile)
        print("\n=== END ===")
        print("Captures:", len(captures))
        print("Shape:", (len(captures), len(captures[0][1])))
        print("Saved:", outfile)


if __name__ == "__main__":
    main()

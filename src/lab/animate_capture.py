#!/usr/bin/env python3
"""Animate every acquisition in an NPZ, with Manchester decoding and quiet intervals."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter
import numpy as np

from manchester import (capture_channels, samplerate_hz, recover_logic,
                        first_zero_crossing, decode_bits, byte_labels_lsb)
from plot_labels import plot_label


@dataclass
class Segment:
    start: float
    end: float
    boundary: float | None = None
    bits: list | None = None


def segments_for(d, fs, threshold=300, bitrate=10e6):
    """Partition the complete sample interval; reacquire phase after each quiet gap."""
    spb = fs / bitrate
    active = np.flatnonzero(np.abs(d) > threshold)
    groups = np.split(active, np.flatnonzero(np.diff(active) > 2 * spb) + 1)
    logic = recover_logic(d, threshold)
    result, previous = [], 0.0
    for group in groups:
        if not len(group):
            continue
        start, end = float(group[0]), float(group[-1] + 1)
        if start > previous:
            result.append(Segment(previous, start))
        boundary, bits = None, None
        try:
            center = first_zero_crossing(d, int(start), int(end))
            boundary = center - spb / 2
            count = max(1, int(round((end - boundary) / spb)))
            bits = decode_bits(logic, boundary, spb, count)
        except RuntimeError:
            pass  # Isolated pulses remain visible, without invented bit values.
        result.append(Segment(start, end, boundary, bits))
        previous = end
    if previous < len(d):
        result.append(Segment(previous, float(len(d))))
    return result


def segment_frames(segment, fs, bits_per_second, idle_us_per_second, fps, bitrate):
    duration = ((segment.end - segment.start) / (fs / bitrate) / bits_per_second
                if segment.bits is not None else
                (segment.end - segment.start) / fs * 1e6 / idle_us_per_second)
    return max(2, math.ceil(duration * fps))


def frame_positions(segment, fs, bits_per_second, idle_us_per_second, fps, bitrate, window_bits):
    """Include each page's end so its final bit is visible before advancing."""
    cuts = [segment.start]
    if segment.bits is not None:
        step = fs / bitrate * window_bits
        edge = segment.boundary + step
        while edge < segment.end:
            if edge > segment.start:
                cuts.append(edge)
            edge += step
    cuts.append(segment.end)
    positions = []
    for left, right in zip(cuts, cuts[1:]):
        part = Segment(left, right, segment.boundary, segment.bits)
        count = segment_frames(part, fs, bits_per_second, idle_us_per_second, fps, bitrate)
        positions.extend(np.linspace(left, right - 1e-6, count))
    return positions


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz')
    p.add_argument('-o', '--output', required=True, help='Looping GIF or MP4')
    p.add_argument('--capture', type=int, help='One acquisition (1-based); default: all')
    p.add_argument('--bits-per-second', type=float, default=8,
                   help='Bits revealed per second of playback (default: 8)')
    p.add_argument('--idle-us-per-second', type=float, default=50,
                   help='Microseconds of undecoded signal per second of playback')
    p.add_argument('--window-bits', type=int, default=16, choices=[8, 16, 32])
    p.add_argument('--bitrate', type=float, default=10e6)
    p.add_argument('--threshold', type=float, default=300)
    p.add_argument('--fps', type=int, default=10)
    p.add_argument('--width', type=int, default=1280)
    p.add_argument('--poster', help='PNG of one decoded signal window')
    p.add_argument('--estimate', action='store_true', help='Show duration without rendering')
    return p


def main():
    p = parser()
    args = p.parse_args()
    if any(not math.isfinite(x) or x <= 0 for x in
           [args.bits_per_second, args.idle_us_per_second, args.bitrate, args.threshold, args.fps]):
        p.error('Rates, threshold, and fps must be positive and finite')
    if args.bits_per_second > args.fps:
        p.error('Use fps >= bits-per-second to show every bit')
    if args.width < 640 or args.width % 32:
        p.error('Width must be >= 640 and a multiple of 32')
    out = Path(args.output)
    if out.suffix.lower() not in ['.gif', '.mp4']:
        p.error('Output must be .gif or .mp4')
    captures = []
    with np.load(args.npz, allow_pickle=False) as z:
        count = 1 if z['ch1'].ndim == 1 else len(z['ch1'])
        indices = [args.capture - 1] if args.capture is not None else range(count)
        for index in indices:
            a, b = capture_channels(z, index)
            fs = samplerate_hz(z, index)
            if not math.isfinite(fs) or fs / args.bitrate < 4:
                p.error('At least four samples per bit are required')
            d = a - b
            d -= np.median(d[:min(4000, len(d) // 2)])
            captures.append((index, fs, d, segments_for(d, fs, args.threshold, args.bitrate)))
    if not captures:
        p.error('The NPZ contains no acquisitions')
    def positions(seg, fs):
        return frame_positions(seg, fs, args.bits_per_second, args.idle_us_per_second,
                               args.fps, args.bitrate, args.window_bits)
    def nframes(seg, fs):
        return len(positions(seg, fs))
    total = sum(nframes(s, fs) for _, fs, _, segs in captures for s in segs)
    print(f'{len(captures)} acquisitions, {total / args.fps:.1f} s, {total} frames', flush=True)
    if args.estimate:
        return
    bg, ink, muted, cyan, gold = '#0b1220', '#edf4ff', '#93a6bd', '#55d6ee', '#ffc66d'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'text.color': ink,
                         'axes.labelcolor': muted, 'xtick.color': muted,
                         'ytick.color': muted, 'font.size': 12})
    fig = plt.figure(figsize=(16, 9), facecolor=bg)
    title = fig.text(.08, .94, '', size=23, weight='bold')
    fig.text(.08, .89, plot_label('capture_animation.subtitle', bits_per_second=args.bits_per_second),
             size=15, color=muted)
    overview = fig.add_axes([.105, .72, .85, .12], facecolor=bg)
    detail = fig.add_axes([.105, .34, .85, .29], facecolor=bg)
    for ax in [overview, detail]:
        for spine in ax.spines.values():
            spine.set_color('#30405a')
    overview.set_ylabel(plot_label('capture_animation.overview_axis'))
    overview.set_xlabel(plot_label('capture_animation.time_axis'))
    detail.set_ylabel(plot_label('capture_animation.detail_axis'))
    detail.set_xlabel(plot_label('capture_animation.time_axis'))
    full, = overview.plot([], [], color=cyan, lw=.8)
    marker = overview.axvline(0, color=gold, lw=2)
    faint, = detail.plot([], [], color=cyan, alpha=.22, lw=1.2)
    line, = detail.plot([], [], color=cyan, lw=2, marker='o', markersize=3)
    logical, = detail.step([], [], where='post', color=gold, lw=1.3)
    cursor = detail.axvline(0, color=ink, lw=1)
    labels = [detail.text(0, 1.08, '', transform=detail.get_xaxis_transform(),
                          ha='center', size=15, color=gold) for _ in range(args.window_bits)]
    grid = [detail.axvline(0, color=muted, alpha=.2, lw=.7) for _ in range(args.window_bits + 1)]
    byte_text = fig.text(.105, .235, '', size=19, family='monospace', color=gold)
    history = fig.text(.105, .17, '', size=14, family='monospace')
    status = fig.text(.105, .085, '', size=14, color=muted)
    fig.text(.955, .025, plot_label('capture_animation.legend'), ha='right', color=muted, size=11)
    if out.suffix.lower() == '.gif':
        # Stream frames to FFmpeg: PillowWriter retains the whole movie in RAM.
        writer = FFMpegWriter(fps=args.fps, codec='gif', extra_args=[
            '-filter_complex', '[0:v]split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=new=1',
            '-loop', '0'])
    else:
        writer = FFMpegWriter(fps=args.fps, codec='libx264', extra_args=[
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-crf', '20'])
    out.parent.mkdir(parents=True, exist_ok=True)
    poster_saved = False
    with writer.saving(fig, str(out), dpi=args.width / 16):
        for index, fs, d, segments in captures:
            print(f'Rendering acquisition {index + 1}/{count}...', flush=True)
            spb = fs / args.bitrate
            t = np.arange(len(d)) / fs * 1e6
            logic = recover_logic(d, args.threshold)
            peak = max(float(np.max(np.abs(d))) * 1.2, args.threshold * 2)
            full.set_data(t, d)
            overview.set_xlim(0, len(d) / fs * 1e6)
            overview.set_ylim(-peak, peak)
            detail.set_ylim(-peak, peak)
            title.set_text(plot_label('capture_animation.title', capture=index + 1, count=count))
            burst = 0
            for seg in segments:
                decoded = seg.bits is not None
                if decoded:
                    burst += 1
                for pos in positions(seg, fs):
                    now = pos / fs * 1e6
                    marker.set_xdata([now, now])
                    cursor.set_xdata([now, now])
                    for label in labels:
                        label.set_text('')
                    for bar in grid:
                        bar.set_visible(decoded)
                    if decoded:
                        n = min(len(seg.bits) - 1, max(0, int((pos - seg.boundary) / spb)))
                        first = n // args.window_bits * args.window_bits
                        left = seg.boundary + first * spb
                        right = left + args.window_bits * spb
                        # Match decode_bits' post-transition sampling point.
                        delta = max(1, int(round(spb * .20)))
                        known = [bit if pos >= round(seg.boundary + (k + .5) * spb + delta)
                                 else None for k, bit in enumerate(seg.bits)]
                        for j, label in enumerate(labels):
                            k = first + j
                            label.set_x((left + (j + .5) * spb) / fs * 1e6)
                            if k < len(seg.bits):
                                revealed = pos >= round(seg.boundary + (k + .5) * spb + delta)
                                label.set_text(('?' if seg.bits[k] is None else str(seg.bits[k])) if revealed else '·')
                        for j, bar in enumerate(grid):
                            x = (left + j * spb) / fs * 1e6
                            bar.set_xdata([x, x])
                        values = byte_labels_lsb(known)
                        first_byte = first // 8
                        fmt = lambda value: '??' if value is None else f'{value:02X}'
                        byte_text.set_text(plot_label(
                            'capture_animation.bytes', first=first_byte,
                            last=first_byte + args.window_bits // 8 - 1,
                            values='   '.join(fmt(v) for v in values[first_byte:first_byte + args.window_bits // 8])))
                        history.set_text(plot_label(
                            'capture_animation.previous',
                            values=' '.join(fmt(v) for v in values[max(0, first_byte - 16):first_byte])))
                        status.set_text(plot_label(
                            'capture_animation.status', burst=burst, bit=n + 1,
                            count=len(seg.bits), sample_rate_msps=fs / 1e6))
                    else:
                        left, right = seg.start, seg.end
                        byte_text.set_text(plot_label('capture_animation.no_bits'))
                        history.set_text('')
                        status.set_text(plot_label(
                            'capture_animation.fast_forward', idle_rate=args.idle_us_per_second))
                    detail.set_xlim(left / fs * 1e6, right / fs * 1e6)
                    mask = (np.arange(len(d)) >= left) & (np.arange(len(d)) <= right)
                    visible = mask & (np.arange(len(d)) <= pos)
                    faint.set_data(t[mask], d[mask])
                    line.set_data(t[visible], d[visible])
                    logical.set_data(t[visible] if decoded else [],
                                     logic[visible] * peak * .65 if decoded else [])
                    writer.grab_frame(facecolor=bg)
                    if args.poster and decoded and not poster_saved and n >= args.window_bits - 1 and pos >= round(seg.boundary + (args.window_bits - .5) * spb + delta):
                        path = Path(args.poster)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        fig.savefig(path, dpi=args.width / 16, facecolor=bg)
                        poster_saved = True
    plt.close(fig)
    print(f'Saved: {out}', flush=True)


if __name__ == '__main__':
    main()

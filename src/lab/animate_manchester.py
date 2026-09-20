#!/usr/bin/env python3
"""Render a captured Manchester byte as a presentation-ready animation."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter, PillowWriter
import numpy as np

from manchester import (capture_channels, samplerate_hz, recover_logic,
                        recover_bit_grid, decode_bits, bits_to_bytes_lsb)
from plot_labels import plot_label


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz')
    p.add_argument('-o', '--output', required=True, help='MP4 or GIF')
    p.add_argument('--capture', type=int, default=1)
    p.add_argument('--wire-byte-offset', type=int, default=7,
                   help='Byte from the start of the burst; 7 = Ethernet SFD')
    p.add_argument('--threshold', type=float, default=300)
    p.add_argument('--seconds', type=float, default=12)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--poster', help='PNG of the final state')
    args = p.parse_args()
    out = Path(args.output)
    if out.suffix.lower() not in ('.mp4', '.gif'):
        p.error('Output must be .mp4 or .gif')
    if args.seconds < 3 or args.fps < 1 or args.width < 640 or args.width % 32:
        p.error('Duration >= 3, fps >= 1, and width >= 640 as a multiple of 32')
    if args.wire_byte_offset < 0 or args.threshold <= 0:
        p.error('Offset must be >= 0 and threshold must be > 0')
    with np.load(args.npz, allow_pickle=False) as z:
        ch1, ch2 = capture_channels(z, args.capture - 1)
        fs = samplerate_hz(z, args.capture - 1)
    d = ch1 - ch2
    d -= np.median(d[:min(4000, len(d) // 2)])
    active = np.flatnonzero(np.abs(d) > args.threshold)
    if not len(active):
        p.error('No burst was detected')
    boundary, _, samples = recover_bit_grid(d, int(active[0]), fs)
    boundary += args.wire_byte_offset * 8 * samples
    if boundary < 0 or boundary + 8 * samples > len(d):
        p.error('The requested byte falls outside the capture')
    logic = recover_logic(d, args.threshold)
    bits = decode_bits(logic, boundary, samples, 8)
    value = bits_to_bytes_lsb(bits)[0]
    t = (np.arange(len(d)) - boundary) / fs * 1e9
    mask = (t >= -30) & (t <= 830)
    x, y = t[mask], d[mask]
    peak = max(np.max(np.abs(y)) * 1.3, args.threshold * 2)
    bg, ink, muted, cyan, gold = '#0b1220', '#edf4ff', '#93a6bd', '#55d6ee', '#ffc66d'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'text.color': ink,
                         'axes.labelcolor': muted, 'xtick.color': muted,
                         'ytick.color': muted, 'font.size': 14})
    fig = plt.figure(figsize=(16, 9), facecolor=bg)
    fig.text(.07, .925, plot_label('byte_animation.title'), size=29, weight='bold')
    fig.text(.07, .88, plot_label('byte_animation.subtitle', capture=args.capture,
                                  byte_offset=args.wire_byte_offset),
             color=muted, size=16)
    ax = fig.add_axes([.115, .40, .825, .38], facecolor=bg)
    ax.set_xlim(-30, 830)
    ax.set_ylim(-peak, peak)
    ax.set_xlabel(plot_label('byte_animation.time_axis'), labelpad=12)
    ax.set_ylabel(plot_label('byte_animation.detail_axis'), labelpad=12)
    ax.set_xticks(np.arange(0, 801, 100))
    for spine in ax.spines.values():
        spine.set_color('#30405a')
    ax.axhline(0, color=muted, alpha=.3, lw=1)
    for n in range(9):
        ax.axvline(n * 100, color=muted, alpha=.22, lw=1)
    ax.plot(x, y, color=cyan, alpha=.16, lw=2)
    line, = ax.plot([], [], color=cyan, lw=2.3, marker='o', markersize=4)
    logical, = ax.step([], [], where='post', color=gold, lw=1.5, alpha=.85)
    cursor = ax.axvline(0, color=ink, lw=1.2)
    fig.text(.08, .82, plot_label('byte_animation.captured_signal'), color=cyan, size=14)
    fig.text(.32, .82, plot_label('byte_animation.recovered_logic'), color=gold, size=14)
    fig.text(.08, .285, plot_label('byte_animation.bit_order'), color=muted, size=15)
    labels = []
    for n in range(8):
        pos = .12 + n * .077
        labels.append(fig.text(pos, .205, '·', ha='center', size=30, weight='bold', color=muted))
        fig.text(pos, .163, f'b{n}', ha='center', size=12, color=muted)
    result = fig.text(.79, .205, '0x··', ha='center', size=34, color=gold, weight='bold')
    status = fig.text(.08, .08, '', size=17)
    fig.text(.94, .08, plot_label('byte_animation.sampling_note',
                                  sample_rate_msps=fs / 1e6, samples_per_bit=samples),
             ha='right', color=muted, size=13)

    def draw(progress):
        time_ns = progress * 800
        visible = x <= time_ns
        line.set_data(x[visible], y[visible])
        logical.set_data(x[visible], logic[mask][visible] * peak * .65)
        cursor.set_xdata([time_ns, time_ns])
        for n, label in enumerate(labels):
            seen = time_ns >= n * 100 + 70
            label.set_text(str(bits[n]) if seen else '·')
            label.set_color(ink if seen else muted)
        result.set_text(f'0x{value:02X}' if progress >= 1 else '0x··')
        if progress >= 1:
            status.set_text(plot_label('byte_animation.recovered_byte',
                                       binary=f'{value:08b}', value=value))
        else:
            n = min(7, int(time_ns // 100))
            direction = '+ → −' if bits[n] == 0 else '− → +'
            status.set_text(
                plot_label('byte_animation.transition', bit=n, direction=direction, value=bits[n])
                if time_ns >= n * 100 + 70
                else plot_label('byte_animation.waiting', bit=n))

    out.parent.mkdir(parents=True, exist_ok=True)
    writer = (FFMpegWriter(fps=args.fps, codec='libx264',
                          extra_args=['-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-crf', '18'])
              if out.suffix.lower() == '.mp4' else PillowWriter(fps=args.fps))
    frames = round(args.seconds * args.fps)
    with writer.saving(fig, str(out), dpi=args.width / 16):
        for frame in range(frames):
            progress = np.clip((frame / max(1, frames - 1) * args.seconds - .75)
                               / (args.seconds - 2.25), 0, 1)
            draw(progress)
            writer.grab_frame(facecolor=bg)
    if args.poster:
        poster = Path(args.poster)
        poster.parent.mkdir(parents=True, exist_ok=True)
        draw(1)
        fig.savefig(poster, dpi=args.width / 16, facecolor=bg)
    plt.close(fig)
    print(f'Saved: {out} ({frames} frames, byte 0x{value:02X})')


if __name__ == '__main__':
    main()

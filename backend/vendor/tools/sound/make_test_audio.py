"""Make the two synthetic test sounds used by the in-game checks (stdlib only, deterministic).

  test_menu_music.wav  44.1 kHz stereo, 24 s loop: a C-major-pentatonic arpeggio, notes alternating left/right,
                       one bar of low "bass" per 2 s. Unmistakably not TOD music; the hard L/R panning proves stereo.
  test_footstep.wav    22.05 kHz mono, 0.12 s: a 1.4 kHz beep with a fast decay, the same length class as
                       stepgrass1.wav (0.118 s), so the left foot "beeps" on concrete/asphalt.
"""
import math
import os
import struct
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))


def tone(f, n, rate, amp, decay):
    return [amp * math.sin(2 * math.pi * f * i / rate) * math.exp(-decay * i / rate) for i in range(n)]


def write(path, rate, chans, frames):
    with wave.open(path, 'wb') as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(struct.pack('<' + 'h' * chans, *[max(-32767, min(32767, int(v))) for v in fr])
                               for fr in frames))


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rate = 44100
    notes = [261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 440.0, 392.0, 329.63, 293.66]
    step = int(0.25 * rate)
    total = 24 * rate
    L = [0.0] * total
    R = [0.0] * total
    for k in range(total // step):
        f = notes[k % len(notes)]
        t = tone(f, step, rate, 9000, 6.0)
        dst = L if k % 2 == 0 else R
        for i, v in enumerate(t):
            dst[k * step + i] += v
    bar = 2 * rate
    for k in range(total // bar):
        b = tone(65.41 if (k // 2) % 2 == 0 else 98.0, bar, rate, 7000, 1.2)
        for i, v in enumerate(b):
            L[k * bar + i] += v
            R[k * bar + i] += v
    write(os.path.join(out_dir, 'test_menu_music.wav'), rate, 2, list(zip(L, R)))
    r2 = 22050
    n = int(0.12 * r2)
    beep = tone(1400.0, n, r2, 14000, 30.0)
    for i in range(int(0.004 * r2)):              # 4 ms attack, no click
        beep[i] *= i / (0.004 * r2)
    write(os.path.join(out_dir, 'test_footstep.wav'), r2, 1, [(v,) for v in beep])
    print('wrote test_menu_music.wav (24 s stereo 44.1 kHz) and test_footstep.wav (0.12 s mono 22.05 kHz) ->', out_dir)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'test_audio'))

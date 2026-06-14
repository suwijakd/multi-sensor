#!/usr/bin/env python3
"""Generate a deterministic synthetic session for verifying analyze.py.

Phases (sampled at 100 Hz), with ground-truth values baked in:
  30 s rest    @  72 bpm PPG, no motion
  30 s active  @ 120 bpm PPG + 0.5 Hz squat oscillation  (=> 15 squats)
  60 s rest    @  90 bpm PPG (recovery), no motion

So a correct analyze.py should recover ~72 / ~120 bpm, 15 reps, and
HRR60 ~30 bpm (120 -> 90). Same 17-column layout the firmware emits, so the
file drops straight into `analyze.py`.

    python tests/make_synthetic_session.py            # -> tests/data/session_synth.csv
    python tests/make_synthetic_session.py some.csv   # custom path
"""
import csv
import math
import os
import random

EXPECTED = dict(baseline_hr=72.0, active_hr=120.0, recovery_hr=90.0, reps=15, hrr60=30.0)

HEADER = ["host_unix_time", "t_us", "seq", "ppg_raw", "gsr_raw", "ax", "ay", "az",
          "gx", "gy", "gz", "mx", "my", "mz", "temp_obj_c", "temp_amb_c", "label"]

# (label, duration_s, heart-rate Hz, squat Hz)
PLAN = [("rest", 30, 72 / 60, 0.0),
        ("active", 30, 120 / 60, 0.5),
        ("rest", 60, 90 / 60, 0.0)]


def generate(path, seed=0, fs=100):
    """Write a synthetic session CSV to `path`. Deterministic for a given seed."""
    rng = random.Random(seed)
    rows, seq, t = [], 0, 0.0
    for label, dur, hr_hz, squat_hz in PLAN:
        for _ in range(int(dur * fs)):
            ppg = 2048 + 300 * math.sin(2 * math.pi * hr_hz * t) + rng.gauss(0, 8)
            az = 9.8 + (3.0 * math.sin(2 * math.pi * squat_hz * t) if squat_hz else 0.0) \
                + rng.gauss(0, 0.05)
            rows.append([f"{1.7e9 + t:.6f}", int(t * 1e6), seq, round(ppg), 1500,
                         0.0, 0.0, round(az, 4), 0.0, 0.0, 0.0, "nan", "nan", "nan",
                         "nan", "nan", label])
            seq += 1
            t += 1.0 / fs
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return EXPECTED


if __name__ == "__main__":
    import sys
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "session_synth.csv")
    out = sys.argv[1] if len(sys.argv) > 1 else default
    generate(out)
    print(f"wrote {out}")
    print(f"expected from analyze.py: {EXPECTED}")

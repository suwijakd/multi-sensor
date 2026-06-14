#!/usr/bin/env python3
"""Self-check for analyze.py.

Generates a synthetic session with known values, runs the analysis, and asserts
the recovered measures match the ground truth. Also writes the QA figure so you
can eyeball beat/squat detection.

    cd pc
    python tests/test_analyze.py        # prints PASS / FAIL, exit code 0 / 1
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PCDIR = os.path.dirname(HERE)
sys.path.insert(0, PCDIR)   # for `import analyze`
sys.path.insert(0, HERE)    # for `import make_synthetic_session`

import analyze
from make_synthetic_session import generate, EXPECTED


class Args:
    squat_prominence = 1.5
    squat_min_interval = 1.0


def main():
    data_dir = os.path.join(HERE, "data")
    csv_path = os.path.join(data_dir, "session_synth.csv")
    generate(csv_path, seed=0)

    df = analyze.load_session(csv_path)
    fig_path = os.path.join(data_dir, "session_synth_qa.png")
    rows, summ = analyze.analyze_session(df, "session_synth", Args(), fig_path)

    # (summary key, expected value, tolerance)
    checks = [
        ("baseline_hr",    EXPECTED["baseline_hr"], 3.0),
        ("active_hr_mean", EXPECTED["active_hr"],   4.0),
        ("active_hr_peak", EXPECTED["active_hr"],   8.0),
        ("total_reps",     EXPECTED["reps"],        1),
        ("hrr60_bpm",      EXPECTED["hrr60"],       5.0),
    ]
    print(f"Analyzed {len(rows)} phases. Checking summary against ground truth:")
    ok = True
    for key, exp, tol in checks:
        got = summ.get(key)
        passed = got is not None and got == got and abs(got - exp) <= tol  # got==got rejects NaN
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {key:15} got={str(got):>7}  expected {exp}±{tol}")
    print(f"\nQA figure: {fig_path}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

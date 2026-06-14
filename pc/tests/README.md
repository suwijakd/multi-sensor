# Verification fixtures for `analyze.py`

Verify the analysis pipeline without real hardware, using a synthetic session
with known ground-truth values (30 s rest @72 bpm, 30 s active @120 bpm + 15
squats, 60 s recovery @90 bpm).

## Quick self-check (PASS / FAIL)

```bash
cd pc
python tests/test_analyze.py
```

Generates the synthetic session, runs the analysis, and asserts the recovered
HR / reps / HRR match the injected values (exit code 0 = PASS). Use this after
changing `analyze.py` to confirm nothing regressed.

## Manual / visual check

```bash
cd pc
python tests/make_synthetic_session.py     # writes tests/data/session_synth.csv
python analyze.py --indir tests/data        # -> tests/data/analysis/*.png + *.csv
```

Open `tests/data/analysis/session_synth_qa.png` and confirm the red beat marks
sit on the PPG peaks and the squat triangles sit on the accel peaks.

Generated files under `tests/data/` are reproducible from these scripts and are
git-ignored.

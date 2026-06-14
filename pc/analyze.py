#!/usr/bin/env python3
"""Batch post-processing for wearable squat-experiment sessions.

Reads every ``session_*.csv`` in a folder, segments it by the ``label`` column
(rest / active / ...), computes the mandatory squat-experiment measures, and
writes two combined tables plus one quick-look QA figure per session so you can
verify the detections before trusting the numbers.

Measures
--------
  HR     : heart rate from PPG (mean + robust peak), per phase
  HRV    : RMSSD (+ SDNN) from inter-beat intervals. Only trust these on
           low-motion phases (rest / recovery) -- PPG is motion-corrupted while
           squatting. The ``motion`` column flags how stationary each phase is.
  Reps   : squat repetitions + cadence from accelerometer magnitude, per phase
  HRR60  : heart-rate recovery ~60 s after each active->rest transition

Outputs (in --outdir, default <indir>/analysis):
  analysis_phases.csv    one row per phase per session (tidy)
  analysis_summary.csv   one row per session (baseline / active / HRR / reps)
  <session>_qa.png       PPG+beats, accel+squats, and HR timeline

Usage
-----
    python analyze.py                          # process ./recordings
    python analyze.py --indir recordings --outdir results
    python analyze.py --squat-prominence 2.0   # tune squat detection
    python analyze.py --no-plots
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks

# ---- detection tunables (a few are overridable on the CLI) ----------------- #
PPG_BAND = (0.5, 4.0)        # Hz, ~30-240 bpm
SQUAT_BAND = (0.1, 2.0)      # Hz
HR_MIN_BPM, HR_MAX_BPM = 30, 220
MIN_BEATS_FOR_HRV = 8        # RMSSD/SDNN need a few beats to mean anything


def r(x, n=2):
    """Round for tidy CSVs; pass NaN/None through."""
    try:
        return round(float(x), n) if x is not None and np.isfinite(x) else np.nan
    except (TypeError, ValueError):
        return np.nan


# --------------------------------------------------------------------------- #
# Loading + signal helpers
# --------------------------------------------------------------------------- #
def load_session(path):
    df = pd.read_csv(path)
    for c in df.columns:
        if c != "label":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["label"] = df["label"].fillna("").astype(str) if "label" in df else ""
    df = df.dropna(subset=["t_us"]).reset_index(drop=True)
    if len(df):
        df["t_s"] = (df["t_us"] - df["t_us"].iloc[0]) / 1e6
    return df


def estimate_fs(t_s):
    d = np.diff(np.asarray(t_s, float))
    d = d[(d > 0) & (d < 1)]
    return float(1.0 / np.median(d)) if len(d) else 100.0


def uniform_grid(t_s, x, fs):
    """Interpolate x(t_s) onto a uniform grid at fs; returns (t_grid, x) or
    (None, None) if there isn't enough finite data (e.g. sensor missing)."""
    t = np.asarray(t_s, float)
    x = np.asarray(x, float)
    good = np.isfinite(t) & np.isfinite(x)
    if good.sum() < 4:
        return None, None
    t, x = t[good], x[good]
    if x.std() < 1e-9:                 # flat line (e.g. ppg=0, sensor missing)
        return None, None
    tg = np.arange(t[0], t[-1], 1.0 / fs)
    return tg, np.interp(tg, t, x)


def bandpass(x, fs, lo, hi, order=2):
    nyq = 0.5 * fs
    lo_n, hi_n = max(lo / nyq, 1e-4), min(hi / nyq, 0.99)
    if hi_n <= lo_n or len(x) <= 3 * (2 * order + 1):
        return x - np.mean(x)
    b, a = butter(order, [lo_n, hi_n], btype="band")
    return filtfilt(b, a, x)


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def beats_from(bp_ppg, t_grid, fs):
    """Beat times (s) from a band-passed PPG. Normalised so it works for both
    the analog (0-4095) and MAX30102 IR (counts) signals."""
    sd = np.std(bp_ppg)
    if sd < 1e-9:
        return np.array([])
    z = bp_ppg / sd
    min_dist = max(1, int(fs * 60.0 / HR_MAX_BPM))
    peaks, _ = find_peaks(z, distance=min_dist, prominence=0.5)
    return t_grid[peaks]


def squats_from(bp_acc, t_grid, fs, prominence, min_interval):
    min_dist = max(1, int(fs * min_interval))
    peaks, _ = find_peaks(bp_acc, distance=min_dist, prominence=prominence)
    return t_grid[peaks]


def clean_ibi(beat_t):
    """Inter-beat intervals (s) with non-physiological + ectopic rejection."""
    if len(beat_t) < 3:
        return np.array([])
    ibi = np.diff(beat_t)
    lo, hi = 60.0 / HR_MAX_BPM, 60.0 / HR_MIN_BPM
    ibi = ibi[(ibi >= lo) & (ibi <= hi)]
    if len(ibi) < 3:
        return ibi
    med = np.median(ibi)
    return ibi[np.abs(ibi - med) <= 0.30 * med]


def hr_metrics(beat_t):
    out = dict(n_beats=int(len(beat_t)), hr_mean=np.nan, hr_peak=np.nan,
               rmssd_ms=np.nan, sdnn_ms=np.nan)
    ibi = clean_ibi(beat_t)
    if len(ibi) >= 2:
        hr = 60.0 / ibi
        out["hr_mean"] = float(np.mean(hr))
        out["hr_peak"] = float(np.percentile(hr, 95))   # robust "peak"
    if len(ibi) >= MIN_BEATS_FOR_HRV:
        diff_ms = np.diff(ibi) * 1000.0
        out["rmssd_ms"] = float(np.sqrt(np.mean(diff_ms ** 2)))
        out["sdnn_ms"] = float(np.std(ibi * 1000.0, ddof=1))
    return out


def mean_hr_window(beat_t, a, b):
    bt = beat_t[(beat_t >= a) & (beat_t <= b)]
    if len(bt) < 2:
        return np.nan
    ibi = np.diff(bt)
    lo, hi = 60.0 / HR_MAX_BPM, 60.0 / HR_MIN_BPM
    ibi = ibi[(ibi >= lo) & (ibi <= hi)]
    return float(np.mean(60.0 / ibi)) if len(ibi) else np.nan


def segment_phases(df):
    """Contiguous runs of the same `label` -> list of {label, i0, i1, t0, t1}."""
    labels = df["label"].values
    n = len(labels)
    if n == 0:
        return []
    change = np.where(labels[1:] != labels[:-1])[0] + 1
    bounds = np.concatenate([[0], change, [n]])
    phases = []
    for i in range(len(bounds) - 1):
        a, b = int(bounds[i]), int(bounds[i + 1])
        phases.append(dict(label=labels[a], i0=a, i1=b,
                           t0=float(df["t_s"].iloc[a]), t1=float(df["t_s"].iloc[b - 1])))
    return phases


# --------------------------------------------------------------------------- #
# Per-session analysis
# --------------------------------------------------------------------------- #
def analyze_session(df, name, args, fig_path=None):
    fs = estimate_fs(df["t_s"])
    tg_ppg, ppg = uniform_grid(df["t_s"], df["ppg_raw"], fs)
    acc_cols = [c for c in ("ax", "ay", "az") if c in df]
    mag = np.sqrt(sum(df[c] ** 2 for c in acc_cols)) if acc_cols else None
    tg_acc, accmag = uniform_grid(df["t_s"], mag, fs) if mag is not None else (None, None)

    bp_ppg = bandpass(ppg, fs, *PPG_BAND) if ppg is not None else None
    beat_t = beats_from(bp_ppg, tg_ppg, fs) if bp_ppg is not None else np.array([])
    bp_acc = bandpass(accmag, fs, *SQUAT_BAND) if accmag is not None else None
    squat_t = (squats_from(bp_acc, tg_acc, fs, args.squat_prominence, args.squat_min_interval)
               if bp_acc is not None else np.array([]))

    phases = segment_phases(df)
    rows = []
    for k, ph in enumerate(phases):
        dur = max(ph["t1"] - ph["t0"], 1e-6)
        bt = beat_t[(beat_t >= ph["t0"]) & (beat_t <= ph["t1"])]
        reps = int(np.sum((squat_t >= ph["t0"]) & (squat_t <= ph["t1"])))
        # motion = std of accel magnitude in the phase (m/s^2): high => HR/HRV suspect
        seg = df.iloc[ph["i0"]:ph["i1"]]
        motion = float(np.sqrt(sum(seg[c] ** 2 for c in acc_cols)).std()) if acc_cols else np.nan
        hm = hr_metrics(bt)
        rows.append(dict(
            session=name, phase=k, label=ph["label"],
            t_start_s=r(ph["t0"], 1), duration_s=r(dur, 1),
            hr_mean=r(hm["hr_mean"], 1), hr_peak=r(hm["hr_peak"], 1), n_beats=hm["n_beats"],
            rmssd_ms=r(hm["rmssd_ms"], 1), sdnn_ms=r(hm["sdnn_ms"], 1),
            reps=reps, cadence_spm=r(reps / dur * 60.0, 1),
            motion_ms2=r(motion, 2)))

    # HRR60: mean HR in the last 15 s of an active phase minus HR ~60 s into the
    # rest phase that follows it.
    hrr_vals = []
    for k in range(len(phases) - 1):
        if "activ" in phases[k]["label"].lower() and "rest" in phases[k + 1]["label"].lower():
            t_tr = phases[k]["t1"]
            end_hr = mean_hr_window(beat_t, t_tr - 15, t_tr)
            t_rec = min(t_tr + 60.0, phases[k + 1]["t1"])
            rec_hr = mean_hr_window(beat_t, t_rec - 10, t_rec + 10)
            if np.isfinite(end_hr) and np.isfinite(rec_hr):
                hrr_vals.append(end_hr - rec_hr)

    rest_rows = [x for x in rows if "rest" in x["label"].lower()]
    act_rows = [x for x in rows if "activ" in x["label"].lower()]
    summary = dict(
        session=name, fs_hz=r(fs, 1), duration_s=r(df["t_s"].iloc[-1], 1),
        n_phases=len(phases),
        baseline_hr=rest_rows[0]["hr_mean"] if rest_rows else np.nan,
        baseline_rmssd_ms=rest_rows[0]["rmssd_ms"] if rest_rows else np.nan,
        active_hr_mean=r(np.nanmean([x["hr_mean"] for x in act_rows]), 1) if act_rows else np.nan,
        active_hr_peak=r(np.nanmax([x["hr_peak"] for x in act_rows]), 1) if act_rows else np.nan,
        total_reps=int(np.nansum([x["reps"] for x in act_rows])) if act_rows else 0,
        hrr60_bpm=r(np.mean(hrr_vals), 1) if hrr_vals else np.nan)

    if fig_path is not None:
        qa_figure(name, fs, phases, tg_ppg, bp_ppg, beat_t,
                  tg_acc, bp_acc, squat_t, beat_t, fig_path)
    return rows, summary


# --------------------------------------------------------------------------- #
def qa_figure(name, fs, phases, tg_ppg, bp_ppg, beat_t,
              tg_acc, bp_acc, squat_t, hr_beats, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 8))
    fig.suptitle(f"{name} — QA (verify detections)")

    # 1) PPG + beats over a rest window (cleanest place to check beat detection)
    rest = next((p for p in phases if "rest" in p["label"].lower()),
                phases[0] if phases else None)
    if bp_ppg is not None and rest is not None:
        w0, w1 = rest["t0"], min(rest["t0"] + 15.0, rest["t1"])
        m = (tg_ppg >= w0) & (tg_ppg <= w1)
        a1.plot(tg_ppg[m], bp_ppg[m], lw=0.8)
        bm = beat_t[(beat_t >= w0) & (beat_t <= w1)]
        a1.plot(bm, np.interp(bm, tg_ppg, bp_ppg), "rx", ms=6)
        a1.set_title(f"PPG (band-passed) + {len(bm)} beats — rest window")
    else:
        a1.set_title("PPG — no usable signal (sensor missing?)")
    a1.set_ylabel("PPG")

    # 2) accel magnitude + detected squats over an active window
    act = next((p for p in phases if "activ" in p["label"].lower()), None)
    if bp_acc is not None:
        if act is not None:
            w0, w1 = act["t0"], act["t1"]
        else:
            w0, w1 = tg_acc[0], tg_acc[-1]
        m = (tg_acc >= w0) & (tg_acc <= w1)
        a2.plot(tg_acc[m], bp_acc[m], lw=0.8, color="tab:green")
        sm = squat_t[(squat_t >= w0) & (squat_t <= w1)]
        a2.plot(sm, np.interp(sm, tg_acc, bp_acc), "k^", ms=6)
        a2.set_title(f"Accel magnitude (band-passed) + {len(sm)} squats — active window")
    else:
        a2.set_title("Accel — no usable signal (IMU missing?)")
    a2.set_ylabel("accel (m/s$^2$)")

    # 3) instantaneous HR timeline with phase shading
    if len(hr_beats) >= 2:
        ibi = np.diff(hr_beats)
        hr = 60.0 / ibi
        ok = (hr >= HR_MIN_BPM) & (hr <= HR_MAX_BPM)
        a3.plot(hr_beats[1:][ok], hr[ok], ".-", ms=3, lw=0.6)
    for p in phases:
        c = "tab:blue" if "rest" in p["label"].lower() else (
            "tab:red" if "activ" in p["label"].lower() else "0.85")
        a3.axvspan(p["t0"], p["t1"], color=c, alpha=0.12)
    a3.set_title("Instantaneous HR (blue=rest, red=active shading)")
    a3.set_ylabel("HR (bpm)")
    a3.set_xlabel("time (s)")

    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Batch analysis of squat-experiment sessions.")
    ap.add_argument("--indir", default="recordings", help="folder of session_*.csv files")
    ap.add_argument("--outdir", default=None, help="output folder (default <indir>/analysis)")
    ap.add_argument("--squat-prominence", type=float, default=1.5,
                    help="min accel swing (m/s^2) to count a squat")
    ap.add_argument("--squat-min-interval", type=float, default=1.0,
                    help="min seconds between squats (caps cadence)")
    ap.add_argument("--no-plots", action="store_true", help="skip the QA figures")
    args = ap.parse_args()

    sessions = sorted(p for p in glob.glob(os.path.join(args.indir, "session_*.csv"))
                      if not p.endswith("_events.csv"))
    if not sessions:
        print(f"No session_*.csv files in {args.indir!r}.")
        return 1

    outdir = args.outdir or os.path.join(args.indir, "analysis")
    os.makedirs(outdir, exist_ok=True)

    all_rows, all_summ = [], []
    for path in sessions:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            df = load_session(path)
        except Exception as exc:
            print(f"  {name}: SKIPPED ({exc})")
            continue
        if len(df) < 10:
            print(f"  {name}: SKIPPED (too few rows)")
            continue
        fig_path = None if args.no_plots else os.path.join(outdir, f"{name}_qa.png")
        rows, summ = analyze_session(df, name, args, fig_path)
        all_rows.extend(rows)
        all_summ.append(summ)
        print(f"  {name}: {summ['n_phases']} phases  "
              f"baseline_hr={summ['baseline_hr']}  active_hr={summ['active_hr_mean']}  "
              f"reps={summ['total_reps']}  hrr60={summ['hrr60_bpm']}")

    if not all_summ:
        print("Nothing analysable.")
        return 1

    phases_csv = os.path.join(outdir, "analysis_phases.csv")
    summary_csv = os.path.join(outdir, "analysis_summary.csv")
    pd.DataFrame(all_rows).to_csv(phases_csv, index=False)
    pd.DataFrame(all_summ).to_csv(summary_csv, index=False)
    print(f"\n{len(all_summ)} session(s) analysed.")
    print(f"Per-phase table: {phases_csv}")
    print(f"Per-session table: {summary_csv}")
    if not args.no_plots:
        print(f"QA figures: {outdir}\\<session>_qa.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())

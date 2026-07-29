"""
====================================================================
 SafeBeat — ECG signal preprocessing bridge
====================================================================
This file converts a raw, continuous ECG signal (like what your AD8232
sensor streams to Firebase) into individual heartbeat windows in the
exact format the trained model expects: 187 samples per beat, resampled
to 125Hz, amplitude normalized 0-1.

WHY THIS FILE IS NEEDED:
  The trained model (safebeat_ecg_model.h5) was trained on the MIT-BIH
  dataset, where each heartbeat is already a pre-cut 187-sample window
  at 125Hz. Your sensor produces one continuous stream of numbers, not
  pre-cut beats. This file finds each heartbeat in that stream and cuts
  it into the same shape the model was trained on.

WHAT IT DOES, STEP BY STEP:
  1. Finds the R-peaks (the sharp spike of each heartbeat) in the signal.
  2. For each R-peak, cuts out a window of signal around it.
  3. Resamples that window so it has exactly 187 points (matching the
     125Hz rate the model was trained on), regardless of what rate your
     sensor actually samples at.
  4. Normalizes it to 0-1, matching how the training data was prepared.

HOW TO TEST THIS FILE ON ITS OWN:
  python3 ecg_preprocessing.py
  This runs a self-test with a synthetic ECG signal and saves a picture
  (preprocessing_selftest.png) so you can see the peak detection and
  resampling actually worked, with no other dependencies needed.
====================================================================
"""

import numpy as np
from scipy.signal import find_peaks, resample as scipy_resample


def normalize_beat(beat):
    """Scales one heartbeat window to the 0-1 range, matching how the
    training dataset was prepared."""
    beat = beat.astype("float32")
    lo, hi = beat.min(), beat.max()
    if hi - lo < 1e-6:
        return np.zeros_like(beat)
    return (beat - lo) / (hi - lo)


def detect_r_peaks(signal, source_rate_hz, max_bpm=220):
    """
    Finds the R-peaks (the tall spikes) in a raw ECG signal.
    signal: a 1D list/array of raw sensor readings.
    source_rate_hz: how many samples per second your sensor collects.
    Returns: the index positions of each detected peak.
    """
    signal = np.asarray(signal, dtype="float32")
    if len(signal) < source_rate_hz:  # need at least ~1 second of data
        return np.array([], dtype=int)

    # light smoothing first, so small noise wiggles don't get mistaken for peaks
    kernel_size = max(1, int(source_rate_hz * 0.02))
    if kernel_size > 1:
        kernel = np.ones(kernel_size) / kernel_size
        smoothed = np.convolve(signal, kernel, mode="same")
    else:
        smoothed = signal

    threshold = smoothed.mean() + 0.5 * (smoothed.max() - smoothed.mean())
    min_distance = int(source_rate_hz * 60.0 / max_bpm)

    peaks, _ = find_peaks(smoothed, height=threshold, distance=max(1, min_distance))
    return peaks


def extract_beat_windows(signal, source_rate_hz, target_len=187, target_rate_hz=125,
                          pre_r_seconds=0.20, max_active_seconds=0.9,
                          return_to_baseline_frac=0.12):
    """
    Cuts a continuous signal into individual heartbeat windows, ready to
    feed directly into the trained model.

    IMPORTANT — matching the real MIT-BIH training data format is what
    makes this work correctly. Two things matter a lot here:
      1. Each real training beat is active for a VARIABLE length (a
         narrow ~49-sample Ventricular beat vs. a much longer ~124-sample
         Normal beat) — that width difference is literally part of what
         identifies the beat type. An earlier version of this function
         forced every beat into the same fixed active length, which
         destroyed that width information and caused wide/abnormal
         beats to be misclassified as Normal.
      2. After the beat's real duration, the rest of the 187-sample
         window is hard ZERO-padding, not stretched signal.

    This version detects where the beat actually returns close to its
    own resting baseline (instead of assuming a fixed width), keeps that
    real proportional width when resampling to the model's 125Hz
    timescale, and zero-pads the remainder — matching the training data.

    Returns: (beats_array, peak_positions)
      beats_array has shape (number_of_beats_found, 187, 1) — exactly
      what model.predict() expects.
    """
    signal = np.asarray(signal, dtype="float32")
    peaks = detect_r_peaks(signal, source_rate_hz)

    if len(peaks) == 0:
        return np.zeros((0, target_len, 1), dtype="float32"), peaks

    pre_samples_src = int(round(pre_r_seconds * source_rate_hz))
    max_active_samples_src = int(round(max_active_seconds * source_rate_hz))

    beats = []
    valid_peaks = []
    for p in peaks:
        start = p - pre_samples_src
        end = p - pre_samples_src + pre_samples_src + max_active_samples_src
        if start < 0 or end > len(signal):
            continue  # skip beats too close to the start/end of the signal

        raw_window = signal[start:end]
        baseline = np.median(raw_window)
        amplitude = raw_window.max() - baseline
        if amplitude < 1e-6:
            continue  # flat/dead signal, not a real beat

        # smooth before measuring where the beat returns to baseline, so
        # sensor noise doesn't cause the detected width to jitter beat
        # to beat on an otherwise identical waveform
        smooth_kernel = max(1, int(0.02 * source_rate_hz))
        if smooth_kernel > 1:
            kernel = np.ones(smooth_kernel) / smooth_kernel
            smoothed_window = np.convolve(raw_window, kernel, mode="same")
        else:
            smoothed_window = raw_window

        threshold = baseline + return_to_baseline_frac * amplitude
        peak_idx_local = int(np.argmax(smoothed_window))

        # walk forward from the peak until the signal settles back near
        # its own baseline — that is the beat's real active length
        active_end = len(raw_window)
        for i in range(peak_idx_local + 1, len(smoothed_window)):
            if abs(smoothed_window[i] - baseline) <= threshold - baseline:
                active_end = i
                break

        active_raw = raw_window[:active_end]


        # resample the ACTIVE portion only, scaled proportionally so the
        # real relative width (narrow PVC vs. wide Normal) survives the
        # change from source_rate_hz to target_rate_hz
        active_len_target = int(round(len(active_raw) * target_rate_hz / source_rate_hz))
        active_len_target = max(2, min(active_len_target, target_len))
        resampled_active = scipy_resample(active_raw, active_len_target)
        normalized_active = normalize_beat(resampled_active)

        full_beat = np.zeros(target_len, dtype="float32")
        full_beat[:active_len_target] = normalized_active

        beats.append(full_beat)
        valid_peaks.append(p)

    if not beats:
        return np.zeros((0, target_len, 1), dtype="float32"), np.array([], dtype=int)

    beats_array = np.stack(beats)[..., np.newaxis]
    return beats_array, np.array(valid_peaks)




# =====================================================================
# SELF-TEST — run this file directly to confirm it works with no other
# setup needed
# =====================================================================
if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fs = 50       # matches the 20ms sample interval in the ESP32 Firebase sketch
    duration_s = 10
    bpm = 72
    t = np.arange(0, duration_s, 1 / fs)

    signal = np.zeros_like(t)
    beat_period = 60.0 / bpm
    for beat_time in np.arange(0, duration_s, beat_period):
        spike = np.exp(-0.5 * ((t - beat_time) / 0.02) ** 2) * 3.0
        p_wave = np.exp(-0.5 * ((t - (beat_time - 0.15)) / 0.04) ** 2) * 0.4
        t_wave = np.exp(-0.5 * ((t - (beat_time + 0.25)) / 0.08) ** 2) * 0.6
        signal += spike + p_wave + t_wave
    signal += np.random.normal(0, 0.03, size=signal.shape)

    beats, peaks = extract_beat_windows(signal, source_rate_hz=fs)
    print(f"Synthetic {duration_s}s signal at {fs}Hz, target bpm={bpm}")
    print(f"Detected {len(peaks)} R-peaks -> extracted {beats.shape[0]} beat windows of shape {beats.shape[1:]}")

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), dpi=150)
    axes[0].plot(t, signal, color="#8c464b")
    axes[0].scatter(t[peaks], signal[peaks], color="#662b2f", zorder=5, label="Detected R-peaks")
    axes[0].set_title(f"Synthetic raw signal ({fs}Hz) with detected peaks")
    axes[0].legend()

    for i in range(min(3, beats.shape[0])):
        axes[1].plot(beats[i, :, 0], alpha=0.8, label=f"Beat {i+1}")
    axes[1].set_title("Extracted + resampled beat windows (125Hz, 187 samples)")
    axes[1].legend()

    fig.tight_layout()
    fig.savefig("preprocessing_selftest.png", bbox_inches="tight")
    print("Saved: preprocessing_selftest.png")

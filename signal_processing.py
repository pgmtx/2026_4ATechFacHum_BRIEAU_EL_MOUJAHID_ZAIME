"""
==============================================================
ChunkyMemo — signal_processing.py
==============================================================
Real-time processing of physiological signals.

Processed signals :
  PPG  -> Heart rate (FC) + Pulse wave amplitude (PWA)
  PZT  -> Respiratory rate (RR) + Detection of cognitive apnea
  Keyboard -> Response time (RT) + Error rate

Composite index I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4

Scientific references :
  [1] Elgendi (2012) "On the Analysis of Fingertip PPG Signals"
      Current Cardiology Reviews
      Standard PPG -> FC pipeline, filter [0.5-4 Hz], peak detection.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC3394104/

  [2] Pavlov et al. (2023) "Task-evoked pulse wave amplitude tracks cognitive load"
      Scientific Reports - DOI 10.1038/s41598-023-48917-5
      PWA decreases significantly with digit span.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC10730617/

  [3] Charlton et al. (2018) "Breathing Rate Estimation from ECG and PPG"
      IEEE Reviews in Biomedical Engineering
      Standard filter [0.1-0.8 Hz] for measuring respiratory rate.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC7612521/

  [4] Grassmann et al. (2016) "Respiratory Changes in Response to Cognitive Load"
      Neural Plasticity - DOI 10.1155/2016/8146809
      Cognitively demanding tasks -> faster breathing.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC4923594/

How to test this file on its own :
  python signal_processing.py
  -> generates synthetic signals, calculates all metrics, displays validation graphs
==============================================================
"""

import logging
import time
from collections import deque

import numpy as np
from scipy import signal as sp_signal

import config

# ==============================================================
# PPGProcessor -- HR and PWA from the PPG signal
# ==============================================================


class PPGProcessor:
    """
    Extract two metrics from the raw PPG signal:
      - FC:  heart rate in bpm
      - PWA: pulse wave amplitude (normalized to baseline)

    Pipeline [ref 1]:
      1. PPG_WINDOW_SEC-second sliding buffer
      2. Butterworth bandpass filter [0.7-4.0 Hz]
         -> 0.7 Hz = 42 bpm minimum (idle)
         -> 4.0 Hz = 240 bpm maximum (intense effort)
      3. Detection of peaks in the filtered signal
      4. FC  = 60 / IBI_moyen  (IBI = inter-beat interval, in seconds)
      5. PWA = highest_value - previous_lowest_value

    PWAs and cognitive load [ref 2] :
      PWA decreases under cognitive load because the sympathetic nervous system causes peripheral vasoconstriction.
      Blood flow to the fingertips is reduced -> smaller PPG peak.
    """

    def __init__(self):
        # RingBuffer: stores PPG_WINDOW_SEC last seconds
        maxlen = int(config.PPG_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)

        # Calculated results -- None = not enough data yet
        self.fc_bpm = None  # heart rate (bpm)
        self.pwa_raw = None  # peak-to-trough amplitude
        self.pwa_norm = None  # normalized amplitude (relative to baseline)
        self.last_peaks = []  # Indices of the most recent peaks detected

        # Individual baseline (calculated during calibration)
        self._pwa_baseline = None

        self.fc_history = []
        self.pwa_history = []

        # Butterworth bandpass filter [ref 1]
        nyq = config.SAMPLING_RATE / 2
        low = config.PPG_LOW_HZ / nyq
        high = config.PPG_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PPG_FILTER_ORDER, [low, high], btype="band"
        )

        self._sample_count = 0

    def update(self, ppg_value: int, timestamp: float):
        """
        Adds a raw PPG sample and recalculates FC + PWA..
        Calls BITalino every frame (100 Hz).
        """
        self._buf.append(ppg_value)
        self._ts_buf.append(timestamp)
        self._sample_count += 1

        # Recalculate every 50 frames = every 0.5 seconds
        if self._sample_count % 50 == 0:
            self._compute()

    def _compute(self):
        """Internal calculation of FC + PWA based on the current buffer."""
        if len(self._buf) < int(3 * config.SAMPLING_RATE):
            return

        arr = np.array(self._buf, dtype=float)

        # Zero-phase filter [ref 1] -- no time delay
        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return

        # Peaks detection
        # min distance = 0.4 s = 150 bpm max (physiological limit)
        min_dist = int(0.4 * config.SAMPLING_RATE)
        height_thr = 0.3 * (filtered.max() - filtered.min())
        if height_thr < 1:
            return

        peaks, _ = sp_signal.find_peaks(
            filtered, distance=min_dist, height=filtered.min() + height_thr
        )
        self.last_peaks = list(peaks)

        if len(peaks) < 2:
            return

        # HR = 60 / average IBI over the last 5 beats
        recent_peaks = peaks[-6:]
        ibis_samples = np.diff(recent_peaks)
        ibis_sec = ibis_samples / config.SAMPLING_RATE

        # Filter out HRs outside the physiological range (40–180 bpm)
        valid_ibis = ibis_sec[(ibis_sec > 0.33) & (ibis_sec < 1.5)]
        if len(valid_ibis) == 0:
            return

        mean_ibi = np.mean(valid_ibis)
        self.fc_bpm = 60.0 / mean_ibi

        if not (35 <= self.fc_bpm <= 200):
            self.fc_bpm = None
            return

        # PWA = peak_value - previous_trough_value [ref 2]
        last_peak_idx = peaks[-1]
        search_start = max(0, last_peak_idx - int(config.SAMPLING_RATE))
        trough_idx = np.argmin(filtered[search_start:last_peak_idx]) + search_start
        self.pwa_raw = float(filtered[last_peak_idx] - filtered[trough_idx])

        # Normalization using individual baselines
        if self._pwa_baseline is not None and self._pwa_baseline > 0:
            self.pwa_norm = self.pwa_raw / self._pwa_baseline

        if self._ts_buf:
            ts = self._ts_buf[-1]
            if self.fc_bpm:
                self.fc_history.append((ts, self.fc_bpm))
            if self.pwa_raw:
                self.pwa_history.append((ts, self.pwa_raw))

    def set_baseline(self, pwa_baseline: float):
        """
        Defines the individual PWA baseline measured at rest.
        Call this after the calibration phase
        """
        self._pwa_baseline = pwa_baseline
        logging.info(f"[PPG] Baseline PWA : {pwa_baseline:.1f}")

    def get_filtered_signal(self) -> np.ndarray:
        """Returns the filtered PPG signal for real-time display."""
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr


# ==============================================================
# PZTProcessor -- RR and cognitive apnea from the PZT signal
# ==============================================================


class PZTProcessor:
    """
    Extract two metrics from the raw PZT signal:
      - RR:    respiratory rate in cycles per minute
      - Apnea: True if there is no inhalation for > 4 seconds

    Pipeline [ref 3] :
      1. PZT_WINDOW_SEC-second (15-second) sliding buffer
      2. Butterworth bandpass filter [0.1-0.8 Hz]
      3. Peaks detection (one spike = one breath)
      4. RR = 60 / average IBI over the last 3 cycles

    Link to cognitive load [ref 4] :
      Cognitively demanding tasks -> faster breathing.
      Under heavy mental strain (more than 7 elements), involuntary breathing pauses
      occur due to extreme concentration.
    """

    def __init__(self):
        maxlen = int(config.PZT_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)

        self.rr_rpm = None
        self.apnea_detected = False
        self.last_peaks = []
        self._last_peak_ts = None

        # Apnea threshold: 4 seconds without breathing
        self.APNEA_THRESHOLD_SEC = 4.0

        self.rr_history = []
        self.apnea_history = []

        # Butterworth bandpass filter [ref 3]
        nyq = config.SAMPLING_RATE / 2
        low = config.PZT_LOW_HZ / nyq
        high = config.PZT_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PZT_FILTER_ORDER, [low, high], btype="band"
        )

        self._sample_count = 0

    def update(self, pzt_value: int, timestamp: float):
        """
        Add a raw PZT sample and recalculate RR and apnea.
        Called at every BITalino frame (100 Hz).
        """
        self._buf.append(pzt_value)
        self._ts_buf.append(timestamp)
        self._sample_count += 1

        # Apnea detection: continuously monitor (reactive)
        self._check_apnea(timestamp)

        # Recalculate RR every 100 frames = every second
        if self._sample_count % 100 == 0:
            self._compute_rr()

    def _check_apnea(self, timestamp: float):
        """Check to see if a breathing pause is in progress."""
        if self._last_peak_ts is None:
            self.apnea_detected = False
            return

        elapsed = timestamp - self._last_peak_ts
        was_apnea = self.apnea_detected
        self.apnea_detected = elapsed > self.APNEA_THRESHOLD_SEC

        if self.apnea_detected and not was_apnea:
            self.apnea_history.append((timestamp, True))
            logging.info(f"[PZT] Apnée cognitive detectée (pause {elapsed:.1f}s)")

    def _compute_rr(self):
        """Internal calculation of respiratory rate."""
        if len(self._buf) < int(5 * config.SAMPLING_RATE):
            return

        arr = np.array(self._buf, dtype=float)

        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return

        # min. distance = 1.25 s = 48 cycles/min max [ref 3]
        min_dist = int(1.25 * config.SAMPLING_RATE)
        height_thr = 0.3 * (filtered.max() - filtered.min())
        if height_thr < 1:
            return

        peaks, _ = sp_signal.find_peaks(
            filtered, distance=min_dist, height=filtered.min() + height_thr
        )
        self.last_peaks = list(peaks)

        if len(peaks) < 2:
            return

        # Update the timestamp of the last peak (for apnea)
        if self._ts_buf:
            ts_arr = list(self._ts_buf)
            last_p = peaks[-1]
            if last_p < len(ts_arr):
                self._last_peak_ts = ts_arr[last_p]

        # RR = 60 / average IBI over the last 3 cycles
        recent_peaks = peaks[-4:]
        ibis_samples = np.diff(recent_peaks)
        ibis_sec = ibis_samples / config.SAMPLING_RATE

        # Valid range: 6–48 cycles per minute = intervals of 1.25–10 seconds
        valid_ibis = ibis_sec[(ibis_sec > 1.25) & (ibis_sec < 10.0)]
        if len(valid_ibis) == 0:
            return

        mean_ibi = np.mean(valid_ibis)
        self.rr_rpm = 60.0 / mean_ibi

        if not (4 <= self.rr_rpm <= 50):
            self.rr_rpm = None
            return

        if self._ts_buf:
            self.rr_history.append((self._ts_buf[-1], self.rr_rpm))

    def get_filtered_signal(self) -> np.ndarray:
        """Returns the filtered PZT signal for display."""
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr


# ==============================================================
# KeyboardProcessor -- Response time and error rate from the keyboard
# ==============================================================


class KeyboardProcessor:
    """
    Calculates behavioral metrics based on keyboard responses.

      - RT:         reaction time in ms (t_press - t_display)
      - RT_moyen:   moving average of the last 3 RTs
      - error_rate: number_of_errors / total_count per level

    Link to cognitive load:
      RT is a robust behavioral indicator of cognitive load.
      PAs the load increases, RT increases.
      [Welford 1980, Reaction Times, Academic Press]

    Usage:
        kp = KeyboardProcessor()
        kp.arrow_shown("UP", time.perf_counter())      # when the arrow is displayed
        kp.arrow_answered("UP", time.perf_counter())   # when the player presses
    """

    def __init__(self):
        self.rt_ms = None  # last response time (ms)
        self.rt_mean_ms = None  # average of the last 3 RTs
        self.error_rate = 0.0  # 0.0-1.0

        self._rt_buf = deque(maxlen=3)  # 3 last RT
        self._pending_ts = None  # timestamp of the last arrow displayed
        self._pending_dir = None  # expected direction

        self._total = 0
        self._errors = 0

        self.rt_history = []  # (timestamp, rt_ms)
        self.error_history = []  # (timestamp, error_rate)

    def arrow_shown(self, direction: str, timestamp: float):
        """
        Records the display of an arrow.
        Called by the game at the exact moment the arrow appears.
        """
        self._pending_ts = timestamp
        self._pending_dir = direction

    def arrow_answered(self, direction_given: str, timestamp: float) -> bool:
        """
        Records the player's response and calculates the response time.
        Called by the game at the exact moment the key is pressed.

        Returns True if the response is correct.
        """
        if self._pending_ts is None:
            return False

        # RT calculation in milliseconds
        rt = (timestamp - self._pending_ts) * 1000
        if 50 < rt < 10000:  # sanity check : 50ms min, 10s max
            self.rt_ms = rt
            self._rt_buf.append(rt)
            self.rt_mean_ms = float(np.mean(self._rt_buf))
            self.rt_history.append((timestamp, rt))

        # Correct / Error checking
        correct = direction_given == self._pending_dir
        self._total += 1
        if not correct:
            self._errors += 1
        self.error_rate = self._errors / self._total if self._total > 0 else 0.0
        self.error_history.append((timestamp, self.error_rate))

        self._pending_ts = None
        self._pending_dir = None
        return correct

    def reset_level(self):
        """Resets the counters for a new level."""
        self._total = 0
        self._errors = 0
        self.error_rate = 0.0


# ==============================================================
# CognitiveLoadIndex -- Composite indexe I_cog
# ==============================================================


class CognitiveLoadIndex:
    """
    Calculate the composite cognitive load index I_cog.

    I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4

    Each metric normalized by individual z-score:
      z = (valeur - mu_baseline) / sigma_baseline

    z_PWA is inversely proportional because PWA decreases as the load increases [ref 2].

    Overload threshold: I_cog > 1.5
    = 1.5 standard deviations above the individual resting value

    Z-score justification :
       A standard method in psychophysiology for normalizing inter-individual differences.
       Threshold 1.5 = conservative, avoids false positives while remaining sensitive.
    """

    OVERLOAD_THRESHOLD = 1.5

    def __init__(self):
        self._baseline = {
            "fc": {"mu": None, "sigma": None},
            "pwa": {"mu": None, "sigma": None},
            "rr": {"mu": None, "sigma": None},
            "rt": {"mu": None, "sigma": None},
        }
        self.i_cog = None
        self.overload = False
        self.i_cog_history = []

    def set_baseline(self, metric: str, values: list):
        """
        Defines the baseline for a metric based on resting values.
        metric: “fc” / “pwa” / ‘rr’ / “rt”
        values: list of values measured during the resting phase
        """
        if len(values) < 3:
            logging.warning(
                f"[I_cog] Baseline {metric} : pas assez de valeurs ({len(values)})"
            )
            return
        arr = np.array(values, dtype=float)
        mu = float(np.mean(arr))
        sigma = float(np.std(arr))
        if sigma < 0.01:
            sigma = 0.01  # avoids division by zero
        self._baseline[metric]["mu"] = mu
        self._baseline[metric]["sigma"] = sigma
        logging.info(f"[I_cog] Baseline {metric} : mu={mu:.2f}  sigma={sigma:.2f}")

    @property
    def is_calibrated(self) -> bool:
        """True if all baselines are defined."""
        return all(
            self._baseline[m]["mu"] is not None for m in ["fc", "pwa", "rr", "rt"]
        )

    def _zscore(self, metric: str, value: float, invert: bool = False):
        """Calculates the z-score of a metric. Returns None if not calibrated."""
        b = self._baseline[metric]
        if b["mu"] is None:
            return None
        z = (value - b["mu"]) / b["sigma"]
        return -z if invert else z

    def update(self, fc, pwa, rr, rt, timestamp: float):
        """
        Recalculates I_cog using the current values.
        Metrics marked as None are ignored (they do not affect the index).

        Returns I_cog (float) or None if calibration is incomplete.
        """
        if not self.is_calibrated:
            return None

        z_scores = []

        if fc is not None:
            z = self._zscore("fc", fc, invert=False)
            if z is not None:
                z_scores.append(z)

        if pwa is not None:
            # PWA inverte : PWA baisse = charge monte [ref 2]
            z = self._zscore("pwa", pwa, invert=True)
            if z is not None:
                z_scores.append(z)

        if rr is not None:
            z = self._zscore("rr", rr, invert=False)
            if z is not None:
                z_scores.append(z)

        if rt is not None:
            z = self._zscore("rt", rt, invert=False)
            if z is not None:
                z_scores.append(z)

        if not z_scores:
            return None

        self.i_cog = float(np.mean(z_scores))
        self.overload = self.i_cog > self.OVERLOAD_THRESHOLD
        self.i_cog_history.append((timestamp, self.i_cog))
        return self.i_cog


# ==============================================================
# CalibrationPhase -- collects baselines at launch
# ==============================================================


class CalibrationPhase:
    """
    Handles the 30-second calibration phase at startup.
    The player is at rest -> baseline physiological values are measured.

    Usage:
        calib = CalibrationPhase(ppg_proc, pzt_proc, cog_idx)
        calib.start()
        while not calib.is_done():
            calib.update(sample)
        calib.finalize()
    """

    DURATION_SEC = 30

    def __init__(
        self,
        ppg_proc: PPGProcessor,
        pzt_proc: PZTProcessor,
        cog_idx: CognitiveLoadIndex,
    ):
        self._ppg = ppg_proc
        self._pzt = pzt_proc
        self._cog = cog_idx

        self._start_time = None
        self._done = False

        self._fc_vals = []
        self._pwa_vals = []
        self._rr_vals = []

    def start(self):
        """Start the calibration phase."""
        self._start_time = time.perf_counter()
        logging.info(f"[Calibration] Debut -- {self.DURATION_SEC}s de repos")
        logging.info("[Calibration] Restez immobile et respirez normalement")

    def update(self, sample: dict):
        """
        Processes a sample during calibration.
        sample must contain: {"ts": float, "ppg": int, "pzt": int}
        """
        if self._start_time is None or self._done:
            return

        ts = sample["ts"]
        self._ppg.update(sample["ppg"], ts)
        self._pzt.update(sample["pzt"], ts)

        if self._ppg.fc_bpm is not None:
            self._fc_vals.append(self._ppg.fc_bpm)
        if self._ppg.pwa_raw is not None:
            self._pwa_vals.append(self._ppg.pwa_raw)
        if self._pzt.rr_rpm is not None:
            self._rr_vals.append(self._pzt.rr_rpm)

    def is_done(self) -> bool:
        """True if the calibration period has expired."""
        if self._start_time is None:
            return False
        return (time.perf_counter() - self._start_time) >= self.DURATION_SEC

    def finalize(self):
        """Calculates and applies the baselines. Call after is_done()."""
        if self._done:
            return
        self._done = True
        logging.info("[Calibration] Calcul des baselines individuelles...")

        if self._pwa_vals:
            pwa_mean = float(np.mean(self._pwa_vals))
            self._ppg.set_baseline(pwa_mean)
            self._cog.set_baseline("pwa", self._pwa_vals)

        if self._fc_vals:
            self._cog.set_baseline("fc", self._fc_vals)
            logging.info(f"[Calibration] FC repos : {np.mean(self._fc_vals):.1f} bpm")

        if self._rr_vals:
            self._cog.set_baseline("rr", self._rr_vals)
            logging.info(f"[Calibration] RR repos : {np.mean(self._rr_vals):.1f} rpm")

        logging.info(
            "[Calibration] Terminee -- baseline RT calculee sur les 5 premieres reponses du jeu"
        )


# ==============================================================
# STANDALONE TEST -- python signal_processing.py
# ==============================================================

if __name__ == "__main__":
    import matplotlib.gridspec as gridspec
    import matplotlib.pyplot as plt

    logging.info("=" * 55)
    logging.info("TEST TRAITEMENT SIGNAL -- ChunkyMemo")
    logging.info("=" * 55 + "\n")

    config.validate()

    DURATION = 60
    N = DURATION * config.SAMPLING_RATE
    t_arr = np.linspace(0, DURATION, N)
    logging.info(f"\nGénération de {DURATION}s de signaux synthétiques...")

    # PPG : pulse wave at 72 bpm (1.2 Hz)
    ppg_signal = (
        np.sin(2 * np.pi * 1.2 * t_arr)
        * 6000
        * np.maximum(0, np.sin(2 * np.pi * 1.2 * t_arr))
        + np.random.normal(0, 200, N)
    ) + 32768

    # PZT : respiratory rate of 15 breaths per minute (0.25 Hz)
    pzt_signal = (
        np.sin(2 * np.pi * 0.25 * t_arr) * 10000 + np.random.normal(0, 100, N)
    ) + 32768

    ppg_proc = PPGProcessor()
    pzt_proc = PZTProcessor()
    cog_idx = CognitiveLoadIndex()
    kb_proc = KeyboardProcessor()

    # Baseline calculated from the first 10 seconds of the synthetic signal
    # (equivalent to the CalibrationPhase in a real-world scenario)
    # First, we feed in 10 seconds of data, retrieve the values, and then calibrate
    logging.info("Phase de calibration synthétique (10s)...")
    ts_now = time.perf_counter()
    calib_samples = int(10 * config.SAMPLING_RATE)
    for i in range(calib_samples):
        ts_c = ts_now + t_arr[i]
        ppg_proc.update(int(ppg_signal[i]), ts_c)
        pzt_proc.update(int(pzt_signal[i]), ts_c)

    # Collect the values calculated during this calibration
    fc_calib = [v for _, v in ppg_proc.fc_history]
    pwa_calib = [v for _, v in ppg_proc.pwa_history]
    rr_calib = [v for _, v in pzt_proc.rr_history]
    rt_calib = [400.0, 420.0, 380.0, 410.0, 390.0]  # RT Level 1 Simulation

    # Apply the actual baselines
    if pwa_calib:
        ppg_proc.set_baseline(float(np.mean(pwa_calib)))
        cog_idx.set_baseline("pwa", pwa_calib)
    if fc_calib:
        cog_idx.set_baseline("fc", fc_calib)
    if rr_calib:
        cog_idx.set_baseline("rr", rr_calib)
    cog_idx.set_baseline("rt", rt_calib)

    logging.info(
        f"  FC baseline  : {np.mean(fc_calib):.1f} bpm"
        if fc_calib
        else "  FC baseline : pas encore calculée"
    )
    logging.info(
        f"  PWA baseline : {np.mean(pwa_calib):.1f}"
        if pwa_calib
        else "  PWA baseline : pas encore calculée"
    )
    logging.info(
        f"  RR baseline  : {np.mean(rr_calib):.1f} rpm"
        if rr_calib
        else "  RR baseline : pas encore calculée"
    )

    logging.info("\nTraitement en cours...")
    ts_now = time.perf_counter()
    fc_ts, fc_vals = [], []
    pwa_ts, pwa_vals = [], []
    rr_ts, rr_vals = [], []
    icog_ts, icog_v = [], []

    # Start after calibration (the first 10 seconds have already been processed)
    calib_start = int(10 * config.SAMPLING_RATE)
    for i in range(calib_start, N):
        ts = ts_now + t_arr[i]
        ppg_proc.update(int(ppg_signal[i]), ts)
        pzt_proc.update(int(pzt_signal[i]), ts)

        if i % (5 * config.SAMPLING_RATE) == 0:
            kb_proc.arrow_shown("UP", ts)
        if i % (5 * config.SAMPLING_RATE) == int(0.4 * config.SAMPLING_RATE):
            kb_proc.arrow_answered("UP", ts)

        if i % config.SAMPLING_RATE == 0:
            ic = cog_idx.update(
                ppg_proc.fc_bpm, ppg_proc.pwa_raw, pzt_proc.rr_rpm, kb_proc.rt_ms, ts
            )
            if ppg_proc.fc_bpm:
                fc_ts.append(t_arr[i])
                fc_vals.append(ppg_proc.fc_bpm)
            if ppg_proc.pwa_raw:
                pwa_ts.append(t_arr[i])
                pwa_vals.append(ppg_proc.pwa_raw)
            if pzt_proc.rr_rpm:
                rr_ts.append(t_arr[i])
                rr_vals.append(pzt_proc.rr_rpm)
            if ic is not None:
                icog_ts.append(t_arr[i])
                icog_v.append(ic)

    logging.info(
        f"FC finale  : {ppg_proc.fc_bpm:.1f} bpm"
        if ppg_proc.fc_bpm
        else "FC : non calculee"
    )
    logging.info(
        f"PWA finale : {ppg_proc.pwa_raw:.1f}"
        if ppg_proc.pwa_raw
        else "PWA : non calculee"
    )
    logging.info(
        f"RR final   : {pzt_proc.rr_rpm:.1f} rpm"
        if pzt_proc.rr_rpm
        else "RR : non calcule"
    )
    logging.info(
        f"RT moyen   : {kb_proc.rt_mean_ms:.1f} ms"
        if kb_proc.rt_mean_ms
        else "RT : non calcule"
    )
    logging.info(
        f"I_cog      : {cog_idx.i_cog:.3f}"
        if cog_idx.i_cog is not None
        else "I_cog : non calcule"
    )
    logging.info(f"Surcharge  : {cog_idx.overload}\n")

    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)
    fig.suptitle("Validation signal_processing.py -- signaux synthetiques", fontsize=13)

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(t_arr, ppg_signal, color="lightcoral", linewidth=0.4, alpha=0.7)
    ax1.set_title("PPG brut")
    ax1.set_ylabel("Amplitude")

    ax2 = fig.add_subplot(gs[0, 1])
    filt_ppg = ppg_proc.get_filtered_signal()
    if len(filt_ppg) > 0:
        t_filt = t_arr[-len(filt_ppg) :]
        ax2.plot(t_filt, filt_ppg, color="tab:red", linewidth=1)
        if ppg_proc.last_peaks:
            vp = [p for p in ppg_proc.last_peaks if p < len(t_filt)]
            ax2.plot(t_filt[vp], filt_ppg[vp], "x", color="darkred", markersize=8)
    ax2.set_title(
        f"PPG filtre + pics (FC={ppg_proc.fc_bpm:.0f} bpm)"
        if ppg_proc.fc_bpm
        else "PPG filtre"
    )
    ax2.set_ylabel("Amplitude")

    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(t_arr, pzt_signal, color="moccasin", linewidth=0.4, alpha=0.7)
    ax3.set_title("PZT brut")
    ax3.set_ylabel("Amplitude")

    ax4 = fig.add_subplot(gs[1, 1])
    filt_pzt = pzt_proc.get_filtered_signal()
    if len(filt_pzt) > 0:
        t_filt_p = t_arr[-len(filt_pzt) :]
        ax4.plot(t_filt_p, filt_pzt, color="tab:orange", linewidth=1)
        if pzt_proc.last_peaks:
            vp2 = [p for p in pzt_proc.last_peaks if p < len(t_filt_p)]
            ax4.plot(
                t_filt_p[vp2], filt_pzt[vp2], "x", color="darkorange", markersize=8
            )
    ax4.set_title(
        f"PZT filtre + pics (RR={pzt_proc.rr_rpm:.0f} rpm)"
        if pzt_proc.rr_rpm
        else "PZT filtre"
    )
    ax4.set_ylabel("Amplitude")

    ax5 = fig.add_subplot(gs[2, 0])
    if fc_vals:
        ax5.plot(fc_ts, fc_vals, "o-", color="tab:red", markersize=4, label="FC (bpm)")
    if rr_vals:
        ax5r = ax5.twinx()
        ax5r.plot(
            rr_ts, rr_vals, "s-", color="tab:orange", markersize=4, label="RR (rpm)"
        )
        ax5r.set_ylabel("RR (rpm)", color="tab:orange")
    ax5.set_title("FC et RR au cours du temps")
    ax5.set_ylabel("FC (bpm)", color="tab:red")
    ax5.set_xlabel("Temps (s)")

    ax6 = fig.add_subplot(gs[2, 1])
    if icog_v:
        ax6.plot(icog_ts, icog_v, color="tab:purple", linewidth=1.5)
        ax6.axhline(
            y=CognitiveLoadIndex.OVERLOAD_THRESHOLD,
            color="red",
            linestyle="--",
            alpha=0.7,
            label=f"Seuil surcharge ({CognitiveLoadIndex.OVERLOAD_THRESHOLD})",
        )
        ax6.fill_between(
            icog_ts,
            icog_v,
            CognitiveLoadIndex.OVERLOAD_THRESHOLD,
            where=[v > CognitiveLoadIndex.OVERLOAD_THRESHOLD for v in icog_v],
            color="red",
            alpha=0.2,
        )
    ax6.set_title("Indice composite I_cog")
    ax6.set_ylabel("I_cog (z-score moyen)")
    ax6.set_xlabel("Temps (s)")
    ax6.legend(fontsize=8)
    ax6.grid(True, alpha=0.3)

    output_filename = "validation_signal_processing.png"
    plt.savefig(output_filename, dpi=120, bbox_inches="tight")
    logging.info(f"Graphique sauvegardé : {output_filename}")
    plt.show()
    logging.info("Test terminé.")

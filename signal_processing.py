"""
==============================================================
ChunkyMemo — signal_processing.py
==============================================================
Traitement des signaux physiologiques en temps reel.
Entierement base sur le document de conception ChunkyMemo.

Signaux traites :
  PPG  -> Frequence cardiaque (FC) + Amplitude onde de pouls (PWA)
  PZT  -> Rythme respiratoire (RR) + Detection d apnee cognitive
  Clavier -> Temps de reaction (RT) + Taux d erreur

Indice composite I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4

References scientifiques :
  [1] Elgendi (2012) "On the Analysis of Fingertip PPG Signals"
      Current Cardiology Reviews
      Pipeline standard PPG -> FC, filtre [0.5-4 Hz], detection de pics.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC3394104/

  [2] Pavlov et al. (2023) "Task-evoked pulse wave amplitude tracks cognitive load"
      Scientific Reports - DOI 10.1038/s41598-023-48917-5
      PWA diminue significativement avec la charge memorielle (digit span).
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC10730617/

  [3] Charlton et al. (2018) "Breathing Rate Estimation from ECG and PPG"
      IEEE Reviews in Biomedical Engineering
      Filtre [0.1-0.8 Hz] standard pour extraction du rythme respiratoire.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC7612521/

  [4] Grassmann et al. (2016) "Respiratory Changes in Response to Cognitive Load"
      Neural Plasticity - DOI 10.1155/2016/8146809
      Episodes cognitifs exigeants -> respiration plus rapide.
      PMC : https://pmc.ncbi.nlm.nih.gov/articles/PMC4923594/

Comment tester ce fichier seul :
  python signal_processing.py
  -> genere des signaux synthetiques, calcule toutes les metriques,
     affiche les graphiques de validation
==============================================================
"""

import time
import numpy as np
from collections import deque
from scipy import signal as sp_signal

import config


# ==============================================================
# PPGProcessor -- FC et PWA depuis le signal PPG
# ==============================================================

class PPGProcessor:
    """
    Extrait deux metriques depuis le signal PPG brut :
      - FC  : frequence cardiaque en bpm
      - PWA : amplitude de l onde de pouls (normalisee par baseline)

    Pipeline [ref 1] :
      1. Buffer glissant de PPG_WINDOW_SEC secondes
      2. Filtre Butterworth passe-bande [0.7-4.0 Hz]
         -> 0.7 Hz = 42 bpm minimum (repos)
         -> 4.0 Hz = 240 bpm maximum (effort intense)
      3. Detection de pics sur le signal filtre
      4. FC  = 60 / IBI_moyen  (IBI = inter-beat interval, en secondes)
      5. PWA = valeur_pic - valeur_creux_precedent

    PWA et charge cognitive [ref 2] :
      La PWA diminue sous charge cognitive car le systeme nerveux
      sympathique provoque une vasoconstriction peripherique.
      Le sang arrive moins fort au bout du doigt -> pic PPG plus petit.
    """

    def __init__(self):
        # Buffer circulaire : conserve les PPG_WINDOW_SEC dernieres secondes
        maxlen = int(config.PPG_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf    = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)

        # Resultats calcules -- None = pas encore assez de donnees
        self.fc_bpm        = None   # frequence cardiaque (bpm)
        self.pwa_raw       = None   # amplitude brute pic-creux
        self.pwa_norm      = None   # amplitude normalisee (/ baseline)
        self.last_peaks    = []     # indices des derniers pics detectes

        # Baseline individuelle (calculee pendant la calibration)
        self._pwa_baseline = None

        # Historique (timestamp, valeur)
        self.fc_history    = []
        self.pwa_history   = []

        # Filtre Butterworth passe-bande [ref 1]
        nyq  = config.SAMPLING_RATE / 2
        low  = config.PPG_LOW_HZ  / nyq
        high = config.PPG_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PPG_FILTER_ORDER, [low, high], btype='band'
        )

        self._sample_count = 0

    def update(self, ppg_value: int, timestamp: float):
        """
        Ajoute un echantillon PPG brut et recalcule FC + PWA.
        Appele a chaque frame BITalino (100 Hz).
        """
        self._buf.append(ppg_value)
        self._ts_buf.append(timestamp)
        self._sample_count += 1

        # Recalcul toutes les 50 frames = toutes les 0.5 secondes
        if self._sample_count % 50 == 0:
            self._compute()

    def _compute(self):
        """Calcul interne FC + PWA sur le buffer courant."""
        if len(self._buf) < int(3 * config.SAMPLING_RATE):
            return

        arr = np.array(self._buf, dtype=float)

        # Filtre zero-phase [ref 1] -- pas de decalage temporel
        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return

        # Detection de pics
        # distance min = 0.4s = 150 bpm max (limite physiologique)
        min_dist   = int(0.4 * config.SAMPLING_RATE)
        height_thr = 0.3 * (filtered.max() - filtered.min())
        if height_thr < 1:
            return

        peaks, _ = sp_signal.find_peaks(
            filtered,
            distance=min_dist,
            height=filtered.min() + height_thr
        )
        self.last_peaks = list(peaks)

        if len(peaks) < 2:
            return

        # FC = 60 / IBI_moyen sur les 5 derniers battements [doc conception]
        recent_peaks = peaks[-6:]
        ibis_samples = np.diff(recent_peaks)
        ibis_sec     = ibis_samples / config.SAMPLING_RATE

        # Filtrer les IBI hors plage physiologique (40-180 bpm)
        valid_ibis = ibis_sec[(ibis_sec > 0.33) & (ibis_sec < 1.5)]
        if len(valid_ibis) == 0:
            return

        mean_ibi    = np.mean(valid_ibis)
        self.fc_bpm = 60.0 / mean_ibi

        if not (35 <= self.fc_bpm <= 200):
            self.fc_bpm = None
            return

        # PWA = valeur_pic - valeur_creux_precedent [ref 2]
        last_peak_idx = peaks[-1]
        search_start  = max(0, last_peak_idx - int(config.SAMPLING_RATE))
        trough_idx    = np.argmin(filtered[search_start:last_peak_idx]) + search_start
        self.pwa_raw  = float(filtered[last_peak_idx] - filtered[trough_idx])

        # Normalisation par baseline individuelle
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
        Definit la baseline PWA individuelle mesuree au repos.
        A appeler apres la phase de calibration.
        """
        self._pwa_baseline = pwa_baseline
        print(f"[PPG] Baseline PWA : {pwa_baseline:.1f}")

    def get_filtered_signal(self) -> np.ndarray:
        """Retourne le signal PPG filtre pour affichage temps reel."""
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr


# ==============================================================
# PZTProcessor -- RR et apnee cognitive depuis le signal PZT
# ==============================================================

class PZTProcessor:
    """
    Extrait deux metriques depuis le signal PZT brut :
      - RR    : rythme respiratoire en cycles/minute
      - Apnee : True si aucune inspiration pendant > 4 secondes

    Pipeline [ref 3] :
      1. Buffer glissant de PZT_WINDOW_SEC secondes (15s)
      2. Filtre Butterworth passe-bande [0.1-0.8 Hz]
      3. Detection de pics (chaque pic = une inspiration)
      4. RR = 60 / IBI_moyen sur les 3 derniers cycles

    Lien avec charge cognitive [ref 4] :
      Episodes cognitifs exigeants -> respiration plus rapide.
      Sous surcharge > 7 elements, on observe des pauses respiratoires
      involontaires liees a la concentration extreme.
    """

    def __init__(self):
        maxlen = int(config.PZT_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf    = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)

        self.rr_rpm         = None
        self.apnea_detected = False
        self.last_peaks     = []
        self._last_peak_ts  = None

        # Seuil apnee : 4 secondes sans inspiration [doc conception]
        self.APNEA_THRESHOLD_SEC = 4.0

        self.rr_history    = []
        self.apnea_history = []

        # Filtre Butterworth passe-bande [ref 3]
        nyq  = config.SAMPLING_RATE / 2
        low  = config.PZT_LOW_HZ  / nyq
        high = config.PZT_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PZT_FILTER_ORDER, [low, high], btype='band'
        )

        self._sample_count = 0

    def update(self, pzt_value: int, timestamp: float):
        """
        Ajoute un echantillon PZT brut et recalcule RR + apnee.
        Appele a chaque frame BITalino (100 Hz).
        """
        self._buf.append(pzt_value)
        self._ts_buf.append(timestamp)
        self._sample_count += 1

        # Detection d apnee : verifier en permanence (reactif)
        self._check_apnea(timestamp)

        # Recalcul RR toutes les 100 frames = toutes les secondes
        if self._sample_count % 100 == 0:
            self._compute_rr()

    def _check_apnea(self, timestamp: float):
        """Verifie si une pause respiratoire est en cours."""
        if self._last_peak_ts is None:
            self.apnea_detected = False
            return

        elapsed = timestamp - self._last_peak_ts
        was_apnea = self.apnea_detected
        self.apnea_detected = elapsed > self.APNEA_THRESHOLD_SEC

        if self.apnea_detected and not was_apnea:
            self.apnea_history.append((timestamp, True))
            print(f"[PZT] Apnee cognitive detectee (pause {elapsed:.1f}s)")

    def _compute_rr(self):
        """Calcul interne du rythme respiratoire."""
        if len(self._buf) < int(5 * config.SAMPLING_RATE):
            return

        arr = np.array(self._buf, dtype=float)

        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return

        # distance min = 1.25s = 48 cycles/min max [ref 3]
        min_dist   = int(1.25 * config.SAMPLING_RATE)
        height_thr = 0.3 * (filtered.max() - filtered.min())
        if height_thr < 1:
            return

        peaks, _ = sp_signal.find_peaks(
            filtered,
            distance=min_dist,
            height=filtered.min() + height_thr
        )
        self.last_peaks = list(peaks)

        if len(peaks) < 2:
            return

        # Mettre a jour le timestamp du dernier pic (pour l apnee)
        if self._ts_buf:
            ts_arr = list(self._ts_buf)
            last_p = peaks[-1]
            if last_p < len(ts_arr):
                self._last_peak_ts = ts_arr[last_p]

        # RR = 60 / IBI_moyen sur les 3 derniers cycles [doc conception]
        recent_peaks = peaks[-4:]
        ibis_samples = np.diff(recent_peaks)
        ibis_sec     = ibis_samples / config.SAMPLING_RATE

        # Plage valide : 6-48 cycles/min = intervalles 1.25-10 secondes
        valid_ibis = ibis_sec[(ibis_sec > 1.25) & (ibis_sec < 10.0)]
        if len(valid_ibis) == 0:
            return

        mean_ibi    = np.mean(valid_ibis)
        self.rr_rpm = 60.0 / mean_ibi

        if not (4 <= self.rr_rpm <= 50):
            self.rr_rpm = None
            return

        if self._ts_buf:
            self.rr_history.append((self._ts_buf[-1], self.rr_rpm))

    def get_filtered_signal(self) -> np.ndarray:
        """Retourne le signal PZT filtre pour affichage."""
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr


# ==============================================================
# KeyboardProcessor -- RT et taux d erreur depuis le clavier
# ==============================================================

class KeyboardProcessor:
    """
    Calcule les metriques comportementales depuis les reponses clavier.

      - RT         : temps de reaction en ms (t_appui - t_affichage)
      - RT_moyen   : moyenne glissante des 3 derniers RT
      - taux_erreur: nb_mauvaises / nb_total par niveau

    Lien avec charge cognitive :
      Le RT est un indicateur comportemental robuste de la charge cognitive.
      Plus la charge augmente, plus le RT s allonge.
      [Welford 1980, Reaction Times, Academic Press]

    Utilisation :
        kp = KeyboardProcessor()
        kp.arrow_shown("UP", time.time())      # quand la fleche s affiche
        kp.arrow_answered("UP", time.time())   # quand le joueur appuie
    """

    def __init__(self):
        self.rt_ms       = None    # dernier temps de reaction (ms)
        self.rt_mean_ms  = None    # moyenne des 3 derniers RT
        self.error_rate  = 0.0     # taux d erreur (0.0 a 1.0)

        self._rt_buf      = deque(maxlen=3)   # 3 derniers RT
        self._pending_ts  = None              # timestamp derniere fleche affichee
        self._pending_dir = None              # direction attendue

        self._total  = 0
        self._errors = 0

        self.rt_history    = []   # (timestamp, rt_ms)
        self.error_history = []   # (timestamp, taux_erreur)

    def arrow_shown(self, direction: str, timestamp: float):
        """
        Enregistre l affichage d une fleche.
        Appele par le jeu au moment exact ou la fleche apparait.
        """
        self._pending_ts  = timestamp
        self._pending_dir = direction

    def arrow_answered(self, direction_given: str, timestamp: float) -> bool:
        """
        Enregistre la reponse du joueur et calcule le RT.
        Appele par le jeu au moment exact de l appui clavier.

        Retourne True si la reponse est correcte.
        """
        if self._pending_ts is None:
            return False

        # Calcul RT en millisecondes
        rt = (timestamp - self._pending_ts) * 1000
        if 50 < rt < 10000:   # sanity check : 50ms min, 10s max
            self.rt_ms = rt
            self._rt_buf.append(rt)
            self.rt_mean_ms = float(np.mean(self._rt_buf))
            self.rt_history.append((timestamp, rt))

        # Verification correcte / erreur
        correct = (direction_given == self._pending_dir)
        self._total += 1
        if not correct:
            self._errors += 1
        self.error_rate = self._errors / self._total if self._total > 0 else 0.0
        self.error_history.append((timestamp, self.error_rate))

        self._pending_ts  = None
        self._pending_dir = None
        return correct

    def reset_level(self):
        """Remet a zero les compteurs pour un nouveau niveau."""
        self._total  = 0
        self._errors = 0
        self.error_rate = 0.0


# ==============================================================
# CognitiveLoadIndex -- Indice composite I_cog
# ==============================================================

class CognitiveLoadIndex:
    """
    Calcule l indice composite de charge cognitive I_cog.

    I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4

    Chaque metrique normalisee par z-score individuel :
        z = (valeur - mu_baseline) / sigma_baseline

    z_PWA est inverte car PWA diminue quand la charge augmente [ref 2].

    Seuil de surcharge : I_cog > 1.5
    = 1.5 ecart-type au-dessus du repos individuel

    Justification z-score :
      Methode standard en psychophysiologie pour normaliser
      les differences inter-individuelles. Seuil 1.5 = conservateur,
      evite les faux positifs tout en restant sensible.
    """

    OVERLOAD_THRESHOLD = 1.5

    def __init__(self):
        self._baseline = {
            "fc":  {"mu": None, "sigma": None},
            "pwa": {"mu": None, "sigma": None},
            "rr":  {"mu": None, "sigma": None},
            "rt":  {"mu": None, "sigma": None},
        }
        self.i_cog         = None
        self.overload      = False
        self.i_cog_history = []

    def set_baseline(self, metric: str, values: list):
        """
        Definit la baseline pour une metrique a partir des valeurs de repos.
        metric : "fc" / "pwa" / "rr" / "rt"
        values : liste des valeurs mesurees pendant la phase de repos
        """
        if len(values) < 3:
            print(f"[I_cog] Baseline {metric} : pas assez de valeurs ({len(values)})")
            return
        arr   = np.array(values, dtype=float)
        mu    = float(np.mean(arr))
        sigma = float(np.std(arr))
        if sigma < 0.01:
            sigma = 0.01   # evite la division par zero
        self._baseline[metric]["mu"]    = mu
        self._baseline[metric]["sigma"] = sigma
        print(f"[I_cog] Baseline {metric} : mu={mu:.2f}  sigma={sigma:.2f}")

    @property
    def is_calibrated(self) -> bool:
        """True si toutes les baselines sont definies."""
        return all(
            self._baseline[m]["mu"] is not None
            for m in ["fc", "pwa", "rr", "rt"]
        )

    def _zscore(self, metric: str, value: float, invert: bool = False):
        """Calcule le z-score d une metrique. Retourne None si pas calibre."""
        b = self._baseline[metric]
        if b["mu"] is None:
            return None
        z = (value - b["mu"]) / b["sigma"]
        return -z if invert else z

    def update(self, fc, pwa, rr, rt, timestamp: float):
        """
        Recalcule I_cog avec les valeurs courantes.
        Les metriques None sont ignorees (n influencent pas l indice).

        Retourne I_cog (float) ou None si calibration incomplete.
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

        self.i_cog    = float(np.mean(z_scores))
        self.overload = self.i_cog > self.OVERLOAD_THRESHOLD
        self.i_cog_history.append((timestamp, self.i_cog))
        return self.i_cog


# ==============================================================
# CalibrationPhase -- collecte les baselines au lancement
# ==============================================================

class CalibrationPhase:
    """
    Gere la phase de calibration de 30 secondes au lancement.
    Le joueur est au repos -> on mesure les valeurs physiologiques de base.

    Utilisation :
        calib = CalibrationPhase(ppg_proc, pzt_proc, cog_idx)
        calib.start()
        while not calib.is_done():
            calib.update(sample)
        calib.finalize()
    """

    DURATION_SEC = 30

    def __init__(self, ppg_proc: PPGProcessor,
                 pzt_proc: PZTProcessor,
                 cog_idx: CognitiveLoadIndex):
        self._ppg  = ppg_proc
        self._pzt  = pzt_proc
        self._cog  = cog_idx

        self._start_time = None
        self._done       = False

        self._fc_vals  = []
        self._pwa_vals = []
        self._rr_vals  = []

    def start(self):
        """Demarre la phase de calibration."""
        self._start_time = time.time()
        print(f"[Calibration] Debut -- {self.DURATION_SEC}s de repos")
        print("[Calibration] Restez immobile et respirez normalement")

    def update(self, sample: dict):
        """
        Traite un echantillon pendant la calibration.
        sample doit contenir : {"ts": float, "ppg": int, "pzt": int}
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
        """True si la duree de calibration est ecoulee."""
        if self._start_time is None:
            return False
        return (time.time() - self._start_time) >= self.DURATION_SEC

    def finalize(self):
        """Calcule et applique les baselines. Appeler apres is_done()."""
        if self._done:
            return
        self._done = True
        print("[Calibration] Calcul des baselines individuelles...")

        if self._pwa_vals:
            pwa_mean = float(np.mean(self._pwa_vals))
            self._ppg.set_baseline(pwa_mean)
            self._cog.set_baseline("pwa", self._pwa_vals)

        if self._fc_vals:
            self._cog.set_baseline("fc", self._fc_vals)
            print(f"[Calibration] FC repos : {np.mean(self._fc_vals):.1f} bpm")

        if self._rr_vals:
            self._cog.set_baseline("rr", self._rr_vals)
            print(f"[Calibration] RR repos : {np.mean(self._rr_vals):.1f} rpm")

        print("[Calibration] Terminee -- baseline RT calculee sur les 5 premieres reponses du jeu")

# ==============================================================
# TEST STANDALONE -- python signal_processing.py
# ==============================================================

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec

    print("=" * 55)
    print("TEST TRAITEMENT SIGNAL -- ChunkyMemo")
    print("=" * 55)
    print()

    config.validate()
    print()

    DURATION = 60
    N        = DURATION * config.SAMPLING_RATE
    t_arr    = np.linspace(0, DURATION, N)
    print(f"Generation de {DURATION}s de signaux synthetiques...")

    # PPG : onde de pouls a 72 bpm (1.2 Hz)
    ppg_signal = (
        np.sin(2 * np.pi * 1.2 * t_arr) * 6000 *
        np.maximum(0, np.sin(2 * np.pi * 1.2 * t_arr)) +
        np.random.normal(0, 200, N)
    ) + 32768

    # PZT : respiration a 15 cycles/min (0.25 Hz)
    pzt_signal = (
        np.sin(2 * np.pi * 0.25 * t_arr) * 10000 +
        np.random.normal(0, 100, N)
    ) + 32768

    ppg_proc = PPGProcessor()
    pzt_proc = PZTProcessor()
    cog_idx  = CognitiveLoadIndex()
    kb_proc  = KeyboardProcessor()

    # Baseline calculee depuis les 10 premieres secondes du signal synthetique
    # (equivalent a la CalibrationPhase en situation reelle)
    # On alimente d abord 10s de donnees, on recupere les valeurs, puis on calibre
    print("Phase de calibration synthetique (10s)...")
    ts_now = time.time()
    calib_samples = int(10 * config.SAMPLING_RATE)
    for i in range(calib_samples):
        ts_c = ts_now + t_arr[i]
        ppg_proc.update(int(ppg_signal[i]), ts_c)
        pzt_proc.update(int(pzt_signal[i]), ts_c)

    # Collecter les valeurs calculees pendant cette calibration
    fc_calib  = [v for _, v in ppg_proc.fc_history]
    pwa_calib = [v for _, v in ppg_proc.pwa_history]
    rr_calib  = [v for _, v in pzt_proc.rr_history]
    rt_calib  = [400.0, 420.0, 380.0, 410.0, 390.0]   # RT simule niveau 1

    # Appliquer les baselines reelles
    if pwa_calib:
        ppg_proc.set_baseline(float(np.mean(pwa_calib)))
        cog_idx.set_baseline("pwa", pwa_calib)
    if fc_calib:
        cog_idx.set_baseline("fc", fc_calib)
    if rr_calib:
        cog_idx.set_baseline("rr", rr_calib)
    cog_idx.set_baseline("rt", rt_calib)

    print(f"  FC baseline  : {np.mean(fc_calib):.1f} bpm" if fc_calib else "  FC baseline : pas encore calculee")
    print(f"  PWA baseline : {np.mean(pwa_calib):.1f}" if pwa_calib else "  PWA baseline : pas encore calculee")
    print(f"  RR baseline  : {np.mean(rr_calib):.1f} rpm" if rr_calib else "  RR baseline : pas encore calculee")
    print()

    print("Traitement en cours...")
    ts_now = time.time()
    fc_ts, fc_vals   = [], []
    pwa_ts, pwa_vals = [], []
    rr_ts, rr_vals   = [], []
    icog_ts, icog_v  = [], []

    # Commencer apres la calibration (les 10 premieres secondes deja traitees)
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
                ppg_proc.fc_bpm, ppg_proc.pwa_raw,
                pzt_proc.rr_rpm, kb_proc.rt_ms, ts
            )
            if ppg_proc.fc_bpm:
                fc_ts.append(t_arr[i]); fc_vals.append(ppg_proc.fc_bpm)
            if ppg_proc.pwa_raw:
                pwa_ts.append(t_arr[i]); pwa_vals.append(ppg_proc.pwa_raw)
            if pzt_proc.rr_rpm:
                rr_ts.append(t_arr[i]); rr_vals.append(pzt_proc.rr_rpm)
            if ic is not None:
                icog_ts.append(t_arr[i]); icog_v.append(ic)

    print(f"FC finale  : {ppg_proc.fc_bpm:.1f} bpm" if ppg_proc.fc_bpm else "FC : non calculee")
    print(f"PWA finale : {ppg_proc.pwa_raw:.1f}" if ppg_proc.pwa_raw else "PWA : non calculee")
    print(f"RR final   : {pzt_proc.rr_rpm:.1f} rpm" if pzt_proc.rr_rpm else "RR : non calcule")
    print(f"RT moyen   : {kb_proc.rt_mean_ms:.1f} ms" if kb_proc.rt_mean_ms else "RT : non calcule")
    print(f"I_cog      : {cog_idx.i_cog:.3f}" if cog_idx.i_cog is not None else "I_cog : non calcule")
    print(f"Surcharge  : {cog_idx.overload}")
    print()

    fig = plt.figure(figsize=(14, 10))
    gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)
    fig.suptitle("Validation signal_processing.py -- signaux synthetiques", fontsize=13)

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(t_arr, ppg_signal, color="lightcoral", linewidth=0.4, alpha=0.7)
    ax1.set_title("PPG brut"); ax1.set_ylabel("Amplitude")

    ax2 = fig.add_subplot(gs[0, 1])
    filt_ppg = ppg_proc.get_filtered_signal()
    if len(filt_ppg) > 0:
        t_filt = t_arr[-len(filt_ppg):]
        ax2.plot(t_filt, filt_ppg, color="tab:red", linewidth=1)
        if ppg_proc.last_peaks:
            vp = [p for p in ppg_proc.last_peaks if p < len(t_filt)]
            ax2.plot(t_filt[vp], filt_ppg[vp], "x", color="darkred", markersize=8)
    ax2.set_title(f"PPG filtre + pics (FC={ppg_proc.fc_bpm:.0f} bpm)" if ppg_proc.fc_bpm else "PPG filtre")
    ax2.set_ylabel("Amplitude")

    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(t_arr, pzt_signal, color="moccasin", linewidth=0.4, alpha=0.7)
    ax3.set_title("PZT brut"); ax3.set_ylabel("Amplitude")

    ax4 = fig.add_subplot(gs[1, 1])
    filt_pzt = pzt_proc.get_filtered_signal()
    if len(filt_pzt) > 0:
        t_filt_p = t_arr[-len(filt_pzt):]
        ax4.plot(t_filt_p, filt_pzt, color="tab:orange", linewidth=1)
        if pzt_proc.last_peaks:
            vp2 = [p for p in pzt_proc.last_peaks if p < len(t_filt_p)]
            ax4.plot(t_filt_p[vp2], filt_pzt[vp2], "x", color="darkorange", markersize=8)
    ax4.set_title(f"PZT filtre + pics (RR={pzt_proc.rr_rpm:.0f} rpm)" if pzt_proc.rr_rpm else "PZT filtre")
    ax4.set_ylabel("Amplitude")

    ax5 = fig.add_subplot(gs[2, 0])
    if fc_vals:
        ax5.plot(fc_ts, fc_vals, "o-", color="tab:red", markersize=4, label="FC (bpm)")
    if rr_vals:
        ax5r = ax5.twinx()
        ax5r.plot(rr_ts, rr_vals, "s-", color="tab:orange", markersize=4, label="RR (rpm)")
        ax5r.set_ylabel("RR (rpm)", color="tab:orange")
    ax5.set_title("FC et RR au cours du temps")
    ax5.set_ylabel("FC (bpm)", color="tab:red"); ax5.set_xlabel("Temps (s)")

    ax6 = fig.add_subplot(gs[2, 1])
    if icog_v:
        ax6.plot(icog_ts, icog_v, color="tab:purple", linewidth=1.5)
        ax6.axhline(y=CognitiveLoadIndex.OVERLOAD_THRESHOLD,
                    color="red", linestyle="--", alpha=0.7,
                    label=f"Seuil surcharge ({CognitiveLoadIndex.OVERLOAD_THRESHOLD})")
        ax6.fill_between(icog_ts, icog_v, CognitiveLoadIndex.OVERLOAD_THRESHOLD,
                         where=[v > CognitiveLoadIndex.OVERLOAD_THRESHOLD for v in icog_v],
                         color="red", alpha=0.2)
    ax6.set_title("Indice composite I_cog")
    ax6.set_ylabel("I_cog (z-score moyen)"); ax6.set_xlabel("Temps (s)")
    ax6.legend(fontsize=8); ax6.grid(True, alpha=0.3)

    plt.savefig("validation_signal_processing.png", dpi=120, bbox_inches="tight")
    print("Graphique sauvegarde : validation_signal_processing.png")
    plt.show()
    print("Test termine.")
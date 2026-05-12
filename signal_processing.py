#signal_processing.py: le code est pour le traitement des signaux ACC, PPG et PZT.


import time
import math
import random
import numpy as np
from collections import deque
from scipy import signal as sp_signal

import config


#DÉTECTEUR DE GESTES ACC

class GestureDetector:

    def __init__(self):
        # Calibration
        self._calib_buf    = deque(maxlen=config.ACC_CALIB_SAMPLES)
        self._calibrated   = False
        self._baseline_x   = 32768   # valeur initiale = milieu plage 16 bits
        self._baseline_y   = 32768

        # Debounce
        self._last_gesture_time = 0.0

        # Stats pour debug
        self.gestures_detected = 0
        self.last_gesture      = None
        self.last_dx           = 0
        self.last_dy           = 0

    @property
    def is_calibrated(self):
        return self._calibrated

    def update(self, acc_x: int, acc_y: int) -> str | None:
        

        #etape 1 : Calibration
        #on accumule les N premières valeurs au repos
        if not self._calibrated:
            self._calib_buf.append((acc_x, acc_y))

            if len(self._calib_buf) == config.ACC_CALIB_SAMPLES:
                # Moyenne = position de repos pour CE joueur et CE placement
                xs = [s[0] for s in self._calib_buf]
                ys = [s[1] for s in self._calib_buf]
                self._baseline_x = sum(xs) / len(xs)
                self._baseline_y = sum(ys) / len(ys)
                self._calibrated  = True
                print(f"[ACC] Calibré — repos X={self._baseline_x:.0f} "
                      f"Y={self._baseline_y:.0f}")

            return None   # pas de geste pendant la calibration

        #etape 2 : ecart par rapport au repos
        dx = acc_x - self._baseline_x   # positif = droite, négatif = gauche
        dy = acc_y - self._baseline_y   # positif = bas, négatif = haut
        self.last_dx = dx
        self.last_dy = dy

        #etape 3 : seuillage
        # Si les deux axes sont sous le seuil → bras au repos → pas de geste
        if abs(dx) < config.ACC_THRESHOLD and abs(dy) < config.ACC_THRESHOLD:
            return None

        #etape 4 : debounce
        now = time.time()
        if now - self._last_gesture_time < config.ACC_DEBOUNCE_SEC:
            return None   # trop tôt depuis le dernier geste

        #etape 5 : Direction dominante
        #l'axe avec le plus grand écart détermine la direction
        if abs(dx) >= abs(dy):
            direction = "RIGHT" if dx > 0 else "LEFT"
        else:
            direction = "DOWN" if dy > 0 else "UP"

        #enregistrement
        self._last_gesture_time = now
        self.last_gesture       = direction
        self.gestures_detected += 1

        print(f"[ACC] Geste : {direction:5s} | dx={dx:+6.0f}  dy={dy:+6.0f}")
        return direction

    def reset_calibration(self):
        #Remet à zero la calibration (utile entre deux sessions)
        self._calib_buf.clear()
        self._calibrated = False
        print("[ACC] Calibration réinitialisée")


#processeur ppg pour la frequence cardiaque

class PPGProcessor:

    def __init__(self):
        #buffer circulaire : conserve les N dernières secondes
        maxlen = int(config.PPG_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf       = deque(maxlen=maxlen)
        self._ts_buf    = deque(maxlen=maxlen)

        #resultats calcules
        self.heart_rate_bpm = None   # None = pas encore calculé
        self.last_peaks     = []     # indices des pics détectés

        #historique pour les graphiques
        self.hr_history     = []     

        #filtre Butterworth passe-bande
        nyq = config.SAMPLING_RATE / 2   # fréquence de Nyquist
        low  = config.PPG_LOW_HZ  / nyq
        high = config.PPG_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PPG_FILTER_ORDER, [low, high], btype="band"
        )

        #compteur d'updates
        self._update_count = 0

    def update(self, ppg_value: int, timestamp: float) -> float | None:
        
        self._buf.append(ppg_value)
        self._ts_buf.append(timestamp)
        self._update_count += 1

        #recalcul toutes les 0.5 secondes = tous les 50 samples à 100 Hz
        if self._update_count % 50 != 0:
            return self.heart_rate_bpm

        #besoin d'au moins 3 secondes pour une estimation stable
        min_samples = int(3 * config.SAMPLING_RATE)
        if len(self._buf) < min_samples:
            return None

        return self._compute_hr()

    def _compute_hr(self) -> float | None:
        arr = np.array(self._buf, dtype=float)

        #filtre passe-bande
        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception as e:
            print(f"[PPG] Erreur filtre : {e}")
            return None

        #détection de pics
        # distance min entre pics = 0.4s = 150 bpm max
        # distance max entre pics = 1.5s = 40 bpm min
        min_dist = int(0.4  * config.SAMPLING_RATE)   # 40 samples
        max_dist = int(1.5  * config.SAMPLING_RATE)   # 150 samples

        #hauteur minimum = 30% de l'amplitude → filtre les petits artefacts
        height_threshold = 0.3 * (filtered.max() - filtered.min())
        if height_threshold < 1:
            return None   # signal trop plat → pas de pouls détectable

        peaks, properties = sp_signal.find_peaks(
            filtered,
            distance=min_dist,
            height=filtered.min() + height_threshold
        )
        self.last_peaks = peaks

        #calcul de la FC 
        if len(peaks) < 2:
            return None   # besoin d'au moins 2 pics pour calculer un intervalle

        #Intervalles entre pics successifs (en secondes)
        intervals_samples = np.diff(peaks)
        intervals_sec     = intervals_samples / config.SAMPLING_RATE

        #Filtrage des intervalles aberrants
        valid = intervals_sec[(intervals_sec > 0.33) & (intervals_sec < 1.5)]
        if len(valid) == 0:
            return None

        #FC = 60 / intervalle moyen
        mean_interval     = np.mean(valid)
        self.heart_rate_bpm = 60.0 / mean_interval

        #sanity check: plage physiologique raisonnable
        if not (35 <= self.heart_rate_bpm <= 200):
            self.heart_rate_bpm = None
            return None

        #enregistrement dans l historique
        if self._ts_buf:
            self.hr_history.append((self._ts_buf[-1], self.heart_rate_bpm))

        return self.heart_rate_bpm

    def get_filtered_signal(self) -> np.ndarray:
        #retourne le signal PPG filtré (pour affichage temps réel)
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr   #retourne le signal brut si le filtre echoue

    def get_amplitude(self) -> float | None:
        if len(self._buf) < int(3 * config.SAMPLING_RATE):
            return None
        filtered = self.get_filtered_signal()
        if len(filtered) == 0:
            return None

        #amplitude = difference entre les percentiles 10 et 90
        #(robuste aux pics aberrants)
        return float(np.percentile(filtered, 90) - np.percentile(filtered, 10))


#PROCESSEUR PZT pour le rythme respiratoire

class PZTProcessor:
    

    def __init__(self):
        maxlen = int(config.PZT_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf    = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)

        self.resp_rate_rpm  = None   # cycles par minute
        self.last_peaks     = []
        self.rr_history     = []     # list de (timestamp, rpm)

        #filtre Butterworth passe  bande respiration
        nyq  = config.SAMPLING_RATE / 2
        low  = config.PZT_LOW_HZ  / nyq
        high = config.PZT_HIGH_HZ / nyq
        self._b, self._a = sp_signal.butter(
            config.PZT_FILTER_ORDER, [low, high], btype="band"
        )

        self._update_count = 0

    def update(self, pzt_value: int, timestamp: float) -> float | None:
        
        self._buf.append(pzt_value)
        self._ts_buf.append(timestamp)
        self._update_count += 1

        #recalcul toutes les secondes (respiration plus lente)
        if self._update_count % 100 != 0:
            return self.resp_rate_rpm

        #besoin d'au moins 5 secondes (respiration lente)
        min_samples = int(5 * config.SAMPLING_RATE)
        if len(self._buf) < min_samples:
            return None

        return self._compute_rr()

    def _compute_rr(self) -> float | None:
        """Calcul interne du rythme respiratoire."""
        arr = np.array(self._buf, dtype=float)

        try:
            filtered = sp_signal.filtfilt(self._b, self._a, arr)
        except Exception as e:
            print(f"[PZT] Erreur filtre : {e}")
            return None

        #distance min entre inspirations = 1.25s = 48 resp/min max
        #distance max = 10s = 6 resp/min min
        min_dist = int(1.25 * config.SAMPLING_RATE)

        height_threshold = 0.3 * (filtered.max() - filtered.min())
        if height_threshold < 1:
            return None

        peaks, _ = sp_signal.find_peaks(
            filtered,
            distance=min_dist,
            height=filtered.min() + height_threshold
        )
        self.last_peaks = peaks

        if len(peaks) < 2:
            return None

        intervals_samples = np.diff(peaks)
        intervals_sec     = intervals_samples / config.SAMPLING_RATE

        #Plage valide : 6–48 resp/min = intervalles 1.25–10 secondes
        valid = intervals_sec[(intervals_sec > 1.25) & (intervals_sec < 10.0)]
        if len(valid) == 0:
            return None

        mean_interval      = np.mean(valid)
        self.resp_rate_rpm = 60.0 / mean_interval

        if not (4 <= self.resp_rate_rpm <= 50):
            self.resp_rate_rpm = None
            return None

        if self._ts_buf:
            self.rr_history.append((self._ts_buf[-1], self.resp_rate_rpm))

        return self.resp_rate_rpm

    def get_filtered_signal(self) -> np.ndarray:
        #Retourne le signal PZT filtré
        if len(self._buf) < 10:
            return np.array([])
        arr = np.array(self._buf, dtype=float)
        try:
            return sp_signal.filtfilt(self._b, self._a, arr)
        except Exception:
            return arr

    def detect_pause(self, pause_threshold_sec: float = 3.0) -> bool:
        
        if len(self.last_peaks) == 0:
            return False

        # Dernière inspiration détectée
        last_peak_sample = self.last_peaks[-1]
        samples_since    = len(self._buf) - last_peak_sample
        seconds_since    = samples_since / config.SAMPLING_RATE

        return seconds_since > pause_threshold_sec


#conteneur de session(stocke tous les signaux d'une partie)

class SessionData:

    def __init__(self, mode: str):
        self.mode           = mode         # "NORMAL" ou "CHUNKING"
        self.start_time     = time.time()

        #signaux bruts (un echantillon toutes les 10ms)
        self.raw_ppg        = []
        self.raw_pzt        = []
        self.raw_acc_x      = []
        self.raw_acc_y      = []
        self.timestamps     = []

        
        self.levels         = []

        #evenements de niveau (pour annoter les graphiques)
        self.level_events   = []   # (timestamp, level_number)

        #niveau courant (rempli au fur et a mesure)
        self._current_level = None

    def add_sample(self, sample: dict):
        #ajoute un échantillon brut a la session
        t = sample["ts"] - self.start_time   # temps relatif au début de session
        self.timestamps.append(t)
        self.raw_ppg.append(sample["ppg"])
        self.raw_pzt.append(sample["pzt"])
        self.raw_acc_x.append(sample["acc_x"])
        self.raw_acc_y.append(sample["acc_y"])

    def start_level(self, level: int):
        #marque le debut d'un nouveau niveau
        ts = time.time() - self.start_time
        self._current_level = {
            "level":    level,
            "ts_start": ts,
            "ts_end":   None,
            "success":  None,
            "seq_len":  level + 2,   #niveau 1 = 3 fleches, etc
        }
        self.level_events.append((ts, level))
        print(f"[session] Niveau {level} démarré (t={ts:.1f}s)")

    def end_level(self, success: bool, hr_bpm: float | None,
                  rr_rpm: float | None, ppg_amplitude: float | None,
                  resp_pauses: int):
        #enregistre les métriques à la fin d'un niveau
        if self._current_level is None:
            return

        ts = time.time() - self.start_time
        self._current_level.update({
            "ts_end":       ts,
            "success":      success,
            "hr_bpm":       hr_bpm,
            "rr_rpm":       rr_rpm,
            "ppg_amplitude":ppg_amplitude,
            "resp_pauses":  resp_pauses,
            "duration_sec": ts - self._current_level["ts_start"],
        })
        self.levels.append(dict(self._current_level))
        self._current_level = None

    def to_dict(self) -> dict:
        #serialise la session pour export JSON/CSV
        return {
            "mode":         self.mode,
            "start_time":   self.start_time,
            "n_levels":     len(self.levels),
            "max_level":    max((l["level"] for l in self.levels), default=0),
            "levels":       self.levels,
        }


#test standalone 

if __name__ == "__main__":
    import matplotlib.pyplot as plt

    print("=" * 50)
    print("TEST TRAITEMENT SIGNAL")
    print("=" * 50)

    config.validate()
    print()

    #generer des signaux synthetiques de test
    print("Génération de 30 secondes de signal synthétique...")
    duration  = 30
    n_samples = duration * config.SAMPLING_RATE
    t_arr     = np.linspace(0, duration, n_samples)

    #PPG : onde de pouls à 72 bpm + harmoniques + bruit
    ppg_clean = (
        np.sin(2 * np.pi * 1.2 * t_arr) * 6000 +
        np.sin(2 * np.pi * 2.4 * t_arr) * 1000 +
        np.random.normal(0, 200, n_samples)
    ) + 32768

    #PZT : respiration a 15 cycles/min
    pzt_clean = (
        np.sin(2 * np.pi * 0.25 * t_arr) * 10000 +
        np.random.normal(0, 100, n_samples)
    ) + 32768

    #test PPG
    print("\nTest PPGProcessor...")
    ppg_proc = PPGProcessor()
    ts_now   = time.time()

    for i, (v, t) in enumerate(zip(ppg_clean.astype(int), t_arr)):
        hr = ppg_proc.update(v, ts_now + t)

    print(f"  Fréquence cardiaque calculée : "
          f"{ppg_proc.heart_rate_bpm:.1f} bpm"
          if ppg_proc.heart_rate_bpm else "  FC non calculable")
    print(f"  Amplitude PPG : "
          f"{ppg_proc.get_amplitude():.1f}"
          if ppg_proc.get_amplitude() else "  Amplitude non calculable")

    #test PZT
    print("\nTest PZTProcessor...")
    pzt_proc = PZTProcessor()

    for i, (v, t) in enumerate(zip(pzt_clean.astype(int), t_arr)):
        rr = pzt_proc.update(v, ts_now + t)

    print(f"  Rythme respiratoire calculé : "
          f"{pzt_proc.resp_rate_rpm:.1f} resp/min"
          if pzt_proc.resp_rate_rpm else "  RR non calculable")

    #test GestureDetector
    print("\nTest GestureDetector...")
    gd = GestureDetector()

    #simuler 100 échantillons au repos (calibration)
    for _ in range(100):
        gd.update(32768 + random.randint(-50, 50),
                  32768 + random.randint(-50, 50))

    print(f"  Calibré : {gd.is_calibrated}")

    #simuler un geste vers le haut (acc_y diminue beaucoup)
    time.sleep(0.6)   # dépasser le debounce
    g = gd.update(32768, 32768 - 5000)   # grand écart sur Y → geste UP
    print(f"  Geste simulé UP → détecté : {g}")

    #graph de validation
    print("\nAffichage des graphiques de validation...")
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle("Validation traitement signal", fontsize=14)

    # PPG brut
    axes[0, 0].plot(t_arr, ppg_clean, color="lightcoral", linewidth=0.5, alpha=0.7)
    axes[0, 0].set_title("PPG brut")
    axes[0, 0].set_ylabel("Amplitude")

    # PPG filtré + pics
    filtered_ppg = ppg_proc.get_filtered_signal()
    if len(filtered_ppg) > 0:
        t_filt = t_arr[-len(filtered_ppg):]
        axes[0, 1].plot(t_filt, filtered_ppg, color="tab:red", linewidth=1)
        if len(ppg_proc.last_peaks) > 0:
            peak_t = t_filt[ppg_proc.last_peaks[ppg_proc.last_peaks < len(t_filt)]]
            peak_v = filtered_ppg[ppg_proc.last_peaks[ppg_proc.last_peaks < len(filtered_ppg)]]
            axes[0, 1].plot(peak_t, peak_v, "x", color="darkred", markersize=8)
        axes[0, 1].set_title(f"PPG filtré + pics "
                              f"(FC={ppg_proc.heart_rate_bpm:.0f} bpm)"
                              if ppg_proc.heart_rate_bpm else "PPG filtré + pics")
        axes[0, 1].set_ylabel("Amplitude")

    # PZT brut
    axes[1, 0].plot(t_arr, pzt_clean, color="lightblue", linewidth=0.5, alpha=0.7)
    axes[1, 0].set_title("PZT brut")
    axes[1, 0].set_ylabel("Amplitude")
    axes[1, 0].set_xlabel("Temps (s)")

    # PZT filtré + pics
    filtered_pzt = pzt_proc.get_filtered_signal()
    if len(filtered_pzt) > 0:
        t_filt_pzt = t_arr[-len(filtered_pzt):]
        axes[1, 1].plot(t_filt_pzt, filtered_pzt, color="tab:orange", linewidth=1)
        if len(pzt_proc.last_peaks) > 0:
            valid_peaks = pzt_proc.last_peaks[pzt_proc.last_peaks < len(t_filt_pzt)]
            axes[1, 1].plot(t_filt_pzt[valid_peaks], filtered_pzt[valid_peaks],
                            "x", color="darkorange", markersize=8)
        axes[1, 1].set_title(f"PZT filtré + pics "
                              f"(RR={pzt_proc.resp_rate_rpm:.0f} resp/min)"
                              if pzt_proc.resp_rate_rpm else "PZT filtré + pics")
        axes[1, 1].set_ylabel("Amplitude")
        axes[1, 1].set_xlabel("Temps (s)")

    plt.tight_layout()
    plt.show()
    print("Test terminé avec succès")
    
"""
==============================================================
ChunkyMemo — acquisition_final.py
==============================================================
Fichier unique qui fait tout dans l ordre :

  1. Connexion BITalino (PPG port 3, PZT port 4)
  2. Calibration 30s au repos → baseline FC, PWA, RR individuelle
  3. Acquisition + traitement temps reel :
       PPG → FC (bpm) + PWA (amplitude onde de pouls)
       PZT → RR (rpm) + detection apnee cognitive
       I_cog = z-score composite (FC + PWA + RR)
  4. Affichage temps reel : 5 graphiques mis a jour en direct
  5. Graphique final complet apres la session

References :
  [1] Elgendi (2012) PPG pipeline — PMC pmc.ncbi.nlm.nih.gov/articles/PMC3394104/
  [2] Pavlov et al. (2023) PWA cognitive load — PMC pmc.ncbi.nlm.nih.gov/articles/PMC10730617/
  [3] Charlton et al. (2018) RR estimation — PMC pmc.ncbi.nlm.nih.gov/articles/PMC7612521/
  [4] Grassmann et al. (2016) Respiration cognitive load — PMC pmc.ncbi.nlm.nih.gov/articles/PMC4923594/

Lancer :
  python acquisition_final.py
==============================================================
"""

import platform, sys, os, time, queue, threading
import numpy as np
from collections import deque
from scipy import signal as sp_signal

import config

# ── plux.pyd dans le meme dossier ─────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import plux
    _ = plux.SignalsDev
    print("[plux] charge avec succes")
except (ImportError, AttributeError):
    pv = platform.python_version().split(".")
    suf = platform.architecture()[0][:2] + "_" + pv[0] + pv[1]
    print(f"[ERREUR] plux.pyd introuvable dans {SCRIPT_DIR}")
    print(f"  Telechargez : https://github.com/pluxbiosignals/python-samples/tree/master/PLUX-API-Python3/Win{suf}")
    sys.exit(1)

# ==============================================================
# BITALINO — identique au main.py du prof
# ==============================================================

class ChunkyDevice(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.data_queue  = None
        self.stop_event  = None
        self.duration    = config.DURATION_MAX
        self.frequency   = config.SAMPLING_RATE
        self._last_print = 0

    def onRawFrame(self, nSeq, data):
        sample = {
            "ts":  time.time(),
            "nSeq": nSeq,
            "ppg": int(data[config.IDX_PPG]),
            "pzt": int(data[config.IDX_PZT]),
        }
        try:
            self.data_queue.put_nowait(sample)
        except queue.Full:
            pass
        now = time.time()
        if now - self._last_print >= 1.0:
            print(f"  [BITalino] nSeq={nSeq:6d} | ppg={sample['ppg']:5d} | pzt={sample['pzt']:5d}")
            self._last_print = now
        return self.stop_event.is_set() or (nSeq > self.duration * self.frequency)


class AcquisitionThread(threading.Thread):
    def __init__(self, data_queue):
        super().__init__(daemon=True)
        self.data_queue = data_queue
        self.stop_event = threading.Event()
        self.device     = None

    def run(self):
        try:
            print(f"[BITalino] Connexion a {config.MAC_ADDRESS} ...")
            self.device = ChunkyDevice(config.MAC_ADDRESS)
            self.device.data_queue = self.data_queue
            self.device.stop_event = self.stop_event
            self.device.duration   = config.DURATION_MAX
            self.device.frequency  = config.SAMPLING_RATE
            self.device.start(config.SAMPLING_RATE, config.ACTIVE_PORTS, config.RESOLUTION)
            print(f"[BITalino] Demarre — ports={config.ACTIVE_PORTS} @ {config.SAMPLING_RATE}Hz")
            self.device.loop()
        except Exception as e:
            print(f"[BITalino] ERREUR : {e}")
        finally:
            if self.device:
                try: self.device.stop(); self.device.close()
                except: pass

    def stop(self):
        self.stop_event.set()


# ==============================================================
# TRAITEMENT SIGNAL — PPGProcessor
# ==============================================================

class PPGProcessor:
    """
    PPG brut → FC (bpm) + PWA (amplitude onde de pouls)
    Filtre Butterworth passe-bande [0.7-4.0 Hz] [ref 1]
    FC = 60 / IBI_moyen sur les 5 derniers battements
    PWA = valeur_pic - valeur_creux_precedent [ref 2]
    """
    def __init__(self):
        maxlen = int(config.PPG_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf    = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)
        self.fc_bpm      = None
        self.pwa_raw     = None
        self.pwa_norm    = None
        self.last_peaks  = []
        self._pwa_base   = None
        self.fc_history  = []
        self.pwa_history = []
        self._n          = 0
        nyq = config.SAMPLING_RATE / 2
        self._b, self._a = sp_signal.butter(
            config.PPG_FILTER_ORDER,
            [config.PPG_LOW_HZ / nyq, config.PPG_HIGH_HZ / nyq],
            btype='band'
        )

    def update(self, val, ts):
        self._buf.append(val)
        self._ts_buf.append(ts)
        self._n += 1
        if self._n % 50 == 0:
            self._compute()

    def _compute(self):
        if len(self._buf) < int(3 * config.SAMPLING_RATE):
            return
        arr = np.array(self._buf, dtype=float)
        try:
            f = sp_signal.filtfilt(self._b, self._a, arr)
        except:
            return
        min_d = int(0.4 * config.SAMPLING_RATE)
        hthr  = 0.3 * (f.max() - f.min())
        if hthr < 1: return
        peaks, _ = sp_signal.find_peaks(f, distance=min_d, height=f.min() + hthr)
        self.last_peaks = list(peaks)
        if len(peaks) < 2: return
        ibis = np.diff(peaks[-6:]) / config.SAMPLING_RATE
        valid = ibis[(ibis > 0.33) & (ibis < 1.5)]
        if len(valid) == 0: return
        self.fc_bpm = 60.0 / np.mean(valid)
        if not (35 <= self.fc_bpm <= 200):
            self.fc_bpm = None; return
        lp = peaks[-1]
        ss = max(0, lp - int(config.SAMPLING_RATE))
        ti = np.argmin(f[ss:lp]) + ss
        self.pwa_raw = float(f[lp] - f[ti])
        if self._pwa_base and self._pwa_base > 0:
            self.pwa_norm = self.pwa_raw / self._pwa_base
        if self._ts_buf:
            t = self._ts_buf[-1]
            if self.fc_bpm:  self.fc_history.append((t, self.fc_bpm))
            if self.pwa_raw: self.pwa_history.append((t, self.pwa_raw))

    def set_baseline(self, v):
        self._pwa_base = v
        print(f"[PPG] Baseline PWA : {v:.1f}")

    def get_filtered(self):
        if len(self._buf) < 10: return np.array([])
        try: return sp_signal.filtfilt(self._b, self._a, np.array(self._buf, dtype=float))
        except: return np.array(self._buf, dtype=float)


# ==============================================================
# TRAITEMENT SIGNAL — PZTProcessor
# ==============================================================

class PZTProcessor:
    """
    PZT brut → RR (cycles/min) + detection apnee cognitive
    Filtre Butterworth passe-bande [0.1-0.8 Hz] [ref 3]
    RR = 60 / IBI_moyen sur les 3 derniers cycles
    Apnee = True si pas de pic respiratoire depuis > 4s [ref 4]
    """
    def __init__(self):
        maxlen = int(config.PZT_WINDOW_SEC * config.SAMPLING_RATE)
        self._buf    = deque(maxlen=maxlen)
        self._ts_buf = deque(maxlen=maxlen)
        self.rr_rpm         = None
        self.apnea_detected = False
        self.last_peaks     = []
        self._last_peak_ts  = None
        self.APNEA_SEC      = 4.0
        self.rr_history     = []
        self.apnea_history  = []
        self._n             = 0
        nyq = config.SAMPLING_RATE / 2
        self._b, self._a = sp_signal.butter(
            config.PZT_FILTER_ORDER,
            [config.PZT_LOW_HZ / nyq, config.PZT_HIGH_HZ / nyq],
            btype='band'
        )

    def update(self, val, ts):
        self._buf.append(val)
        self._ts_buf.append(ts)
        self._n += 1
        self._check_apnea(ts)
        if self._n % 100 == 0:
            self._compute()

    def _check_apnea(self, ts):
        if self._last_peak_ts is None:
            self.apnea_detected = False; return
        was = self.apnea_detected
        self.apnea_detected = (ts - self._last_peak_ts) > self.APNEA_SEC
        if self.apnea_detected and not was:
            self.apnea_history.append((ts, True))
            print(f"[PZT] Apnee detectee ({ts - self._last_peak_ts:.1f}s)")

    def _compute(self):
        if len(self._buf) < int(5 * config.SAMPLING_RATE): return
        arr = np.array(self._buf, dtype=float)
        try: f = sp_signal.filtfilt(self._b, self._a, arr)
        except: return
        min_d = int(1.25 * config.SAMPLING_RATE)
        hthr  = 0.3 * (f.max() - f.min())
        if hthr < 1: return
        peaks, _ = sp_signal.find_peaks(f, distance=min_d, height=f.min() + hthr)
        self.last_peaks = list(peaks)
        if len(peaks) < 2: return
        if self._ts_buf:
            ts_list = list(self._ts_buf)
            lp = peaks[-1]
            if lp < len(ts_list):
                self._last_peak_ts = ts_list[lp]
        ibis = np.diff(peaks[-4:]) / config.SAMPLING_RATE
        valid = ibis[(ibis > 1.25) & (ibis < 10.0)]
        if len(valid) == 0: return
        self.rr_rpm = 60.0 / np.mean(valid)
        if not (4 <= self.rr_rpm <= 50):
            self.rr_rpm = None; return
        if self._ts_buf:
            self.rr_history.append((self._ts_buf[-1], self.rr_rpm))

    def get_filtered(self):
        if len(self._buf) < 10: return np.array([])
        try: return sp_signal.filtfilt(self._b, self._a, np.array(self._buf, dtype=float))
        except: return np.array(self._buf, dtype=float)


# ==============================================================
# INDICE COMPOSITE I_cog
# ==============================================================

class CognitiveLoadIndex:
    """
    I_cog = (z_FC + z_PWA_inv + z_RR) / 3  (RT absent hors jeu)
    z-score individuel par rapport a la baseline de repos.
    z_PWA inverse : PWA baisse quand charge monte [ref 2].
    Seuil surcharge : I_cog > 1.5
    """
    THRESHOLD = 1.5

    def __init__(self):
        self._bl = {m: {"mu": None, "s": None} for m in ["fc","pwa","rr"]}
        self.i_cog    = None
        self.overload = False
        self.history  = []

    def set_baseline(self, metric, values):
        if len(values) < 3:
            print(f"[I_cog] {metric} : pas assez de valeurs ({len(values)})"); return
        a = np.array(values, dtype=float)
        mu, s = float(np.mean(a)), float(np.std(a))
        if s < 0.01: s = 0.01
        self._bl[metric]["mu"] = mu
        self._bl[metric]["s"]  = s
        print(f"[I_cog] Baseline {metric:3s} : mu={mu:.2f}  sigma={s:.2f}")

    @property
    def is_calibrated(self):
        return all(self._bl[m]["mu"] is not None for m in ["fc","pwa","rr"])

    def _z(self, metric, val, inv=False):
        b = self._bl[metric]
        if b["mu"] is None: return None
        z = (val - b["mu"]) / b["s"]
        return -z if inv else z

    def update(self, fc, pwa, rr, ts):
        if not self.is_calibrated: return None
        zs = []
        if fc  is not None:
            z = self._z("fc",  fc,  inv=False); zs.append(z) if z is not None else None
        if pwa is not None:
            z = self._z("pwa", pwa, inv=True);  zs.append(z) if z is not None else None
        if rr  is not None:
            z = self._z("rr",  rr,  inv=False); zs.append(z) if z is not None else None
        if not zs: return None
        self.i_cog    = float(np.mean(zs))
        self.overload = self.i_cog > self.THRESHOLD
        self.history.append((ts, self.i_cog))
        return self.i_cog


# ==============================================================
# PROGRAMME PRINCIPAL
# ==============================================================

def main():
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.animation import FuncAnimation

    # Desactiver raccourcis conflictuels
    for key in ['s','q','z','Z','d','g','p','f','h','l']:
        for km in ['keymap.save','keymap.quit','keymap.zoom','keymap.xscale',
                   'keymap.yscale','keymap.grid','keymap.pan','keymap.fullscreen',
                   'keymap.home','keymap.back']:
            try:
                if key in matplotlib.rcParams.get(km, []):
                    matplotlib.rcParams[km].remove(key)
            except: pass

    print("=" * 55)
    print("ChunkyMemo — Acquisition + Traitement temps reel")
    print("=" * 55)
    config.validate()
    print(f"\nPPG → port {config.ACTIVE_PORTS[config.IDX_PPG]}")
    print(f"PZT → port {config.ACTIVE_PORTS[config.IDX_PZT]}")
    input("\nAppuyez sur Entree pour demarrer...")

    # ── Demarrage acquisition ──────────────────────────────────
    data_q = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
    acq    = AcquisitionThread(data_q)
    acq.start()
    start  = time.time()

    print("\nAttente connexion BITalino (5s max)...")
    deadline = time.time() + 5
    while data_q.empty() and time.time() < deadline:
        time.sleep(0.1)
    if data_q.empty():
        print("ERREUR : aucune donnee. Verifiez BITalino + Bluetooth.")
        acq.stop(); sys.exit(1)
    print("BITalino connecte !\n")

    # ── Instanciation processeurs ─────────────────────────────
    ppg = PPGProcessor()
    pzt = PZTProcessor()
    cog = CognitiveLoadIndex()

    # ── Buffers d'affichage ───────────────────────────────────
    # Signaux bruts
    all_ts, all_ppg, all_pzt = [], [], []
    # Signaux filtres (mis a jour periodiquement)
    filt_ppg_ts, filt_ppg_v = [], []
    filt_pzt_ts, filt_pzt_v = [], []
    # Metriques calculees
    fc_ts, fc_v   = [], []
    rr_ts, rr_v   = [], []
    ic_ts, ic_v   = [], []

    WINDOW = 15.0        # secondes affichees
    CALIB_SEC = 40.0     # duree calibration au repos
    calibrated = [False]
    calib_vals = {"fc": [], "pwa": [], "rr": []}

    # ── Construction figure ───────────────────────────────────
    fig = plt.figure(figsize=(15, 12))
    gs  = gridspec.GridSpec(5, 2, figure=fig,
                            height_ratios=[2,2,1.5,1.5,1.5],
                            hspace=0.65, wspace=0.35)

    # PPG brut (colonne gauche)  + PPG filtre + pics (colonne droite)
    ax_ppg_raw  = fig.add_subplot(gs[0, 0])
    ax_ppg_filt = fig.add_subplot(gs[0, 1])
    # PZT brut + PZT filtre + pics
    ax_pzt_raw  = fig.add_subplot(gs[1, 0])
    ax_pzt_filt = fig.add_subplot(gs[1, 1])
    # FC calculee
    ax_fc       = fig.add_subplot(gs[2, :])
    # RR calculee
    ax_rr       = fig.add_subplot(gs[3, :])
    # I_cog composite
    ax_icog     = fig.add_subplot(gs[4, :])

    line_ppg_r,  = ax_ppg_raw.plot([], [],  color="lightcoral",  lw=0.7, alpha=0.8)
    line_ppg_f,  = ax_ppg_filt.plot([], [], color="tab:red",     lw=1.0)
    peaks_ppg,   = ax_ppg_filt.plot([], [], "x", color="darkred", ms=8, mew=2)

    line_pzt_r,  = ax_pzt_raw.plot([], [],  color="moccasin",    lw=0.7, alpha=0.8)
    line_pzt_f,  = ax_pzt_filt.plot([], [], color="tab:orange",  lw=1.0)
    peaks_pzt,   = ax_pzt_filt.plot([], [], "x", color="darkorange", ms=8, mew=2)

    line_fc,     = ax_fc.plot([],   [],   color="crimson",   lw=1.8, marker="o", ms=4)
    line_rr,     = ax_rr.plot([],   [],   color="darkorange",lw=1.8, marker="s", ms=4)
    line_icog,   = ax_icog.plot([], [],   color="tab:purple",lw=2.0)

    # Titres et labels fixes
    ax_ppg_raw.set_title("PPG brut");          ax_ppg_raw.set_ylabel("Amplitude"); ax_ppg_raw.grid(True, alpha=0.3)
    ax_ppg_filt.set_title("PPG filtre + pics detectes [ref 1]"); ax_ppg_filt.set_ylabel("Amplitude"); ax_ppg_filt.grid(True, alpha=0.3)
    ax_pzt_raw.set_title("PZT brut");          ax_pzt_raw.set_ylabel("Amplitude"); ax_pzt_raw.grid(True, alpha=0.3)
    ax_pzt_filt.set_title("PZT filtre + pics detectes [ref 3]"); ax_pzt_filt.set_ylabel("Amplitude"); ax_pzt_filt.grid(True, alpha=0.3)
    ax_fc.set_title("Frequence cardiaque calculee (bpm) [ref 1]"); ax_fc.set_ylabel("FC (bpm)"); ax_fc.grid(True, alpha=0.3)
    ax_rr.set_title("Rythme respiratoire calcule (cycles/min) [ref 3]"); ax_rr.set_ylabel("RR (rpm)"); ax_rr.grid(True, alpha=0.3)
    ax_icog.axhline(y=CognitiveLoadIndex.THRESHOLD, color="red", ls="--", alpha=0.7, lw=1,
                    label=f"Seuil surcharge I_cog > {CognitiveLoadIndex.THRESHOLD}")
    ax_icog.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
    ax_icog.set_title("Indice composite I_cog = (z_FC + z_PWA_inv + z_RR) / 3")
    ax_icog.set_ylabel("I_cog"); ax_icog.set_xlabel("Temps (s)")
    ax_icog.legend(fontsize=9, loc="upper left"); ax_icog.grid(True, alpha=0.3)

    fig.suptitle("ChunkyMemo — Acquisition + Traitement temps reel", fontsize=12)
    plt.tight_layout()

    # ── Fonction de mise a jour (FuncAnimation) ───────────────
    def update(frame):
        # 1. Vider la queue
        while not data_q.empty():
            try:
                s = data_q.get_nowait()
            except queue.Empty:
                break

            ts_rel = s["ts"] - start
            all_ts.append(ts_rel)
            all_ppg.append(s["ppg"])
            all_pzt.append(s["pzt"])

            # 2. Calibration pendant les 30 premieres secondes
            if ts_rel < CALIB_SEC:
                ppg.update(s["ppg"], s["ts"])
                pzt.update(s["pzt"], s["ts"])
                if ppg.fc_bpm  is not None:
                    calib_vals["fc"].append(ppg.fc_bpm)
                    fc_ts.append(ts_rel); fc_v.append(ppg.fc_bpm)
                if ppg.pwa_raw is not None:
                    calib_vals["pwa"].append(ppg.pwa_raw)
                if pzt.rr_rpm  is not None:
                    calib_vals["rr"].append(pzt.rr_rpm)
                    rr_ts.append(ts_rel); rr_v.append(pzt.rr_rpm)

            else:
                # 3. Appliquer baseline une seule fois
                if not calibrated[0]:
                    calibrated[0] = True
                    print("\n[Calibration] Calcul des baselines...")
                    if calib_vals["pwa"]:
                        ppg.set_baseline(float(np.mean(calib_vals["pwa"])))
                        cog.set_baseline("pwa", calib_vals["pwa"])
                    if calib_vals["fc"]:
                        cog.set_baseline("fc", calib_vals["fc"])
                    if calib_vals["rr"]:
                        cog.set_baseline("rr", calib_vals["rr"])
                    print("[Calibration] Terminee — acquisition en cours\n")

                # 4. Traitement normal
                ppg.update(s["ppg"], s["ts"])
                pzt.update(s["pzt"], s["ts"])
                ic = cog.update(ppg.fc_bpm, ppg.pwa_raw, pzt.rr_rpm, s["ts"])

                if ppg.fc_bpm is not None:
                    fc_ts.append(ts_rel); fc_v.append(ppg.fc_bpm)
                if pzt.rr_rpm is not None:
                    rr_ts.append(ts_rel); rr_v.append(pzt.rr_rpm)
                if ic is not None:
                    ic_ts.append(ts_rel); ic_v.append(ic)

        if not all_ts:
            return

        t_now = all_ts[-1]
        t_min = max(0, t_now - WINDOW)

        # ── Signaux bruts ─────────────────────────────────────
        mask = [i for i,t in enumerate(all_ts) if t >= t_min]
        if mask:
            tw = [all_ts[i] for i in mask]
            pw = [all_ppg[i] for i in mask]
            zw = [all_pzt[i] for i in mask]
            line_ppg_r.set_data(tw, pw)
            ax_ppg_raw.set_xlim(t_min, t_now+0.3)
            ax_ppg_raw.set_ylim(min(pw)-5, max(pw)+5)
            line_pzt_r.set_data(tw, zw)
            ax_pzt_raw.set_xlim(t_min, t_now+0.3)
            ax_pzt_raw.set_ylim(min(zw)-5, max(zw)+5)

        # ── PPG filtre + pics ─────────────────────────────────
        fp = ppg.get_filtered()
        if len(fp) > 0:
            n  = len(fp)
            t0 = all_ts[-n] if n <= len(all_ts) else 0
            tf = np.linspace(t0, t_now, n)
            line_ppg_f.set_data(tf, fp)
            ax_ppg_filt.set_xlim(max(0, t_now-WINDOW), t_now+0.3)
            ax_ppg_filt.set_ylim(fp.min()-10, fp.max()+10)
            # Pics
            if ppg.last_peaks:
                pi = [p for p in ppg.last_peaks if p < n]
                if pi:
                    peaks_ppg.set_data(tf[pi], fp[pi])

        # ── PZT filtre + pics ─────────────────────────────────
        fz = pzt.get_filtered()
        if len(fz) > 0:
            n  = len(fz)
            t0 = all_ts[-n] if n <= len(all_ts) else 0
            tf = np.linspace(t0, t_now, n)
            line_pzt_f.set_data(tf, fz)
            ax_pzt_filt.set_xlim(max(0, t_now-WINDOW), t_now+0.3)
            ax_pzt_filt.set_ylim(fz.min()-10, fz.max()+10)
            if pzt.last_peaks:
                pi = [p for p in pzt.last_peaks if p < n]
                if pi:
                    peaks_pzt.set_data(tf[pi], fz[pi])

        # ── FC ────────────────────────────────────────────────
        if len(fc_ts) > 1:
            fm = [(t,v) for t,v in zip(fc_ts,fc_v) if t >= t_min]
            if fm:
                ft,fv = zip(*fm)
                line_fc.set_data(ft, fv)
                ax_fc.set_xlim(t_min, t_now+0.3)
                mg = max(3, (max(fv)-min(fv))*0.2+2)
                ax_fc.set_ylim(min(fv)-mg, max(fv)+mg)

        # ── RR ────────────────────────────────────────────────
        if len(rr_ts) > 1:
            rm = [(t,v) for t,v in zip(rr_ts,rr_v) if t >= t_min]
            if rm:
                rt,rv = zip(*rm)
                line_rr.set_data(rt, rv)
                ax_rr.set_xlim(t_min, t_now+0.3)
                mg = max(1, (max(rv)-min(rv))*0.2+1)
                ax_rr.set_ylim(min(rv)-mg, max(rv)+mg)

        # ── I_cog ─────────────────────────────────────────────
        if len(ic_ts) > 1:
            im2 = [(t,v) for t,v in zip(ic_ts,ic_v) if t >= t_min]
            if im2:
                it,iv = zip(*im2)
                line_icog.set_data(it, iv)
                ax_icog.set_xlim(t_min, t_now+0.3)
                all_v = list(iv) + [CognitiveLoadIndex.THRESHOLD, 0]
                mg = max(0.3, (max(all_v)-min(all_v))*0.15)
                ax_icog.set_ylim(min(all_v)-mg, max(all_v)+mg)
                # Zone rouge surcharge
                ax_icog.collections.clear()
                ax_icog.fill_between(it, iv, CognitiveLoadIndex.THRESHOLD,
                    where=[v > CognitiveLoadIndex.THRESHOLD for v in iv],
                    color="red", alpha=0.25, label="_nolegend_")

        # ── Titre dynamique ───────────────────────────────────
        fc_s  = f"FC={ppg.fc_bpm:.0f}bpm"  if ppg.fc_bpm  else "FC=---"
        rr_s  = f"RR={pzt.rr_rpm:.0f}rpm"  if pzt.rr_rpm  else "RR=---"
        ap_s  = " | APNEE" if pzt.apnea_detected else ""
        if not calibrated[0]:
            rem = max(0, CALIB_SEC - t_now)
            st  = f" [CALIBRATION {rem:.0f}s — restez immobile]"
        elif cog.i_cog is not None:
            ov  = " *** SURCHARGE ***" if cog.overload else ""
            st  = f" | I_cog={cog.i_cog:.2f}{ov}"
        else:
            st = " [calcul en cours...]"
        fig.suptitle(f"ChunkyMemo — {fc_s}  {rr_s}{ap_s}{st}", fontsize=11)

    ani = FuncAnimation(fig, update, interval=100, blit=False, cache_frame_data=False)
    plt.show(block=True)

    # ── Nettoyage ─────────────────────────────────────────────
    acq.stop()
    time.sleep(0.3)
    plt.ioff()

    if not all_ppg:
        print("Aucune donnee collectee."); return

    print(f"\nSession terminee : {len(all_ppg)} echantillons")
    print(f"FC finale  : {ppg.fc_bpm:.1f} bpm"  if ppg.fc_bpm  else "FC : non calculee")
    print(f"RR final   : {pzt.rr_rpm:.1f} rpm"  if pzt.rr_rpm  else "RR : non calcule")
    print(f"I_cog      : {cog.i_cog:.3f}"        if cog.i_cog is not None else "I_cog : non calcule")

    # ── Graphique final complet ───────────────────────────────
    fig2 = plt.figure(figsize=(15, 12))
    gs2  = gridspec.GridSpec(5, 2, figure=fig2,
                             height_ratios=[2,2,1.5,1.5,1.5],
                             hspace=0.65, wspace=0.35)

    ax1 = fig2.add_subplot(gs2[0, 0])
    ax1.plot(all_ts, all_ppg, color="lightcoral", lw=0.5, alpha=0.8)
    ax1.set_title("PPG brut — session complete"); ax1.set_ylabel("Amplitude"); ax1.grid(True, alpha=0.3)

    ax2 = fig2.add_subplot(gs2[0, 1])
    fp = ppg.get_filtered()
    if len(fp) > 0:
        tf = np.linspace(all_ts[-len(fp)], all_ts[-1], len(fp)) if len(fp) <= len(all_ts) else np.array(all_ts[-len(fp):])
        ax2.plot(tf, fp, color="tab:red", lw=0.8)
        if ppg.last_peaks:
            pi = [p for p in ppg.last_peaks if p < len(fp)]
            if pi: ax2.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)
    ax2.set_title(f"PPG filtre + pics (FC={ppg.fc_bpm:.0f}bpm)" if ppg.fc_bpm else "PPG filtre")
    ax2.set_ylabel("Amplitude"); ax2.grid(True, alpha=0.3)

    ax3 = fig2.add_subplot(gs2[1, 0])
    ax3.plot(all_ts, all_pzt, color="moccasin", lw=0.5, alpha=0.8)
    ax3.set_title("PZT brut — session complete"); ax3.set_ylabel("Amplitude"); ax3.grid(True, alpha=0.3)

    ax4 = fig2.add_subplot(gs2[1, 1])
    fz = pzt.get_filtered()
    if len(fz) > 0:
        tf = np.linspace(all_ts[-len(fz)], all_ts[-1], len(fz)) if len(fz) <= len(all_ts) else np.array(all_ts[-len(fz):])
        ax4.plot(tf, fz, color="tab:orange", lw=0.8)
        if pzt.last_peaks:
            pi = [p for p in pzt.last_peaks if p < len(fz)]
            if pi: ax4.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)
    ax4.set_title(f"PZT filtre + pics (RR={pzt.rr_rpm:.0f}rpm)" if pzt.rr_rpm else "PZT filtre")
    ax4.set_ylabel("Amplitude"); ax4.grid(True, alpha=0.3)

    ax5 = fig2.add_subplot(gs2[2, :])
    if fc_ts: ax5.plot(fc_ts, fc_v, "o-", color="crimson",    lw=1.5, ms=5, label="FC (bpm)")
    ax5.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.5, label="Fin calibration")
    ax5.set_title("Frequence cardiaque calculee"); ax5.set_ylabel("FC (bpm)")
    ax5.legend(fontsize=9); ax5.grid(True, alpha=0.3)

    ax6 = fig2.add_subplot(gs2[3, :])
    if rr_ts: ax6.plot(rr_ts, rr_v, "s-", color="darkorange", lw=1.5, ms=5, label="RR (rpm)")
    ax6.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.5, label="Fin calibration")
    for ts_ap, _ in pzt.apnea_history:
        ax6.axvline(x=ts_ap - start, color="red", alpha=0.4, lw=1)
    ax6.set_title("Rythme respiratoire calcule + apnees (|)"); ax6.set_ylabel("RR (rpm)")
    ax6.legend(fontsize=9); ax6.grid(True, alpha=0.3)

    ax7 = fig2.add_subplot(gs2[4, :])
    if ic_ts:
        ax7.plot(ic_ts, ic_v, color="tab:purple", lw=2.0, label="I_cog")
        ax7.fill_between(ic_ts, ic_v, CognitiveLoadIndex.THRESHOLD,
            where=[v > CognitiveLoadIndex.THRESHOLD for v in ic_v],
            color="red", alpha=0.25, label="Surcharge")
    ax7.axhline(y=CognitiveLoadIndex.THRESHOLD, color="red",  ls="--", alpha=0.7, lw=1)
    ax7.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
    ax7.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.5, label="Fin calibration")
    ax7.set_title("Indice composite I_cog = (z_FC + z_PWA_inv + z_RR) / 3")
    ax7.set_ylabel("I_cog"); ax7.set_xlabel("Temps (s)")
    ax7.legend(fontsize=9); ax7.grid(True, alpha=0.3)

    fig2.suptitle(
        f"ChunkyMemo — Session complete  |  "
        f"FC={ppg.fc_bpm:.0f}bpm  RR={pzt.rr_rpm:.0f}rpm  I_cog={cog.i_cog:.2f}"
        if (ppg.fc_bpm and pzt.rr_rpm and cog.i_cog) else "ChunkyMemo — Session complete",
        fontsize=12
    )
    plt.tight_layout()

    # Sauvegarde
    import os as _os
    _os.makedirs("sessions", exist_ok=True)
    fname = f"sessions/session_{time.strftime('%Y%m%d_%H%M%S')}.png"
    fig2.savefig(fname, dpi=130, bbox_inches="tight")
    print(f"\nGraphique final sauvegarde : {fname}")
    plt.show()


if __name__ == "__main__":
    main()
    
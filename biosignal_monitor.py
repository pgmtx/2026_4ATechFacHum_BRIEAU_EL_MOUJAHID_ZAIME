"""
physio_live.py — Acquisition BITalino + graphes matplotlib temps réel.

Basé sur acquisation_processing_.py (qui marchait).
- Attend que le jeu démarre (calib_start dans live_events.json)
- FuncAnimation : PPG | PZT | Touches | I_cog
- Quand game_end détecté → affiche le rapport final dans la même fenêtre
- Sauvegarde les données complètes de la session dans live_events.json pour analysis.py
"""

import json
import os
import platform
import queue
import sys
import threading
import time
from collections import deque

import numpy as np
from scipy import signal as sp_signal

import config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import plux

    _ = plux.SignalsDev
    print("[plux] chargé")
except (ImportError, AttributeError):
    pv = platform.python_version().split(".")
    suf = platform.architecture()[0][:2] + "_" + pv[0] + pv[1]
    print(f"[ERREUR] plux introuvable — téléchargez Win{suf}")
    sys.exit(1)

EVENTS_FILE = "sessions/live_events.json"


# ── BITalino ──────────────────────────────────────────────────
class ChunkyDevice(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.data_queue = None
        self.stop_event = None
        self.duration = config.DURATION_MAX
        self.frequency = config.SAMPLING_RATE
        self._last = 0

    def onRawFrame(self, nSeq, data):
        s = {
            "ts": time.time(),
            "ppg": int(data[config.IDX_PPG]),
            "pzt": int(data[config.IDX_PZT]),
        }
        try:
            self.data_queue.put_nowait(s)
        except queue.Full:
            pass
        now = time.time()
        if now - self._last >= 2.0:
            print(f"  [BITalino] {nSeq} ppg={s['ppg']} pzt={s['pzt']}")
            self._last = now
        return self.stop_event.is_set() or (nSeq > self.duration * self.frequency)


class AcqThread(threading.Thread):
    def __init__(self, q):
        super().__init__(daemon=True)
        self.q = q
        self.stop_event = threading.Event()
        self.device = None

    def run(self):
        try:
            print(f"[acq] Connexion {config.MAC_ADDRESS}...")
            self.device = ChunkyDevice(config.MAC_ADDRESS)
            self.device.data_queue = self.q
            self.device.stop_event = self.stop_event
            self.device.duration = config.DURATION_MAX
            self.device.frequency = config.SAMPLING_RATE
            self.device.start(
                config.SAMPLING_RATE, config.ACTIVE_PORTS, config.RESOLUTION
            )
            print("[acq] Démarré")
            self.device.loop()
        except Exception as e:
            print(f"[acq] ERREUR : {e}")
        finally:
            if self.device:
                try:
                    self.device.stop()
                    self.device.close()
                except:
                    pass

    def stop(self):
        self.stop_event.set()


from signal_processing import CognitiveLoadIndex, PPGProcessor, PZTProcessor


def main():
    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.gridspec as gridspec
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    for key in ["s", "q", "z", "Z", "d", "g", "p", "f", "h", "l"]:
        for km in [
            "keymap.save",
            "keymap.quit",
            "keymap.zoom",
            "keymap.xscale",
            "keymap.yscale",
            "keymap.grid",
            "keymap.pan",
        ]:
            try:
                if key in matplotlib.rcParams.get(km, []):
                    matplotlib.rcParams[km].remove(key)
            except:
                pass

    config.validate()

    # ── Connexion BITalino ────────────────────────────────────
    data_q = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
    acq = AcqThread(data_q)
    acq.start()

    print("Attente BITalino (5s)...")
    deadline = time.time() + 5
    while data_q.empty() and time.time() < deadline:
        time.sleep(0.1)
    if data_q.empty():
        print("ERREUR : aucune donnée BITalino")
        sys.exit(1)
    print("BITalino connecté !")

    # ── Attendre que le joueur clique Jouer ───────────────────
    print("En attente du démarrage du jeu (cliquez Jouer)...")
    while True:
        try:
            with open(EVENTS_FILE) as f:
                ev = json.load(f)
            if ev.get("calib_start") is not None:
                break
        except Exception:
            pass
        # Vider la queue pendant l'attente
        while not data_q.empty():
            try:
                data_q.get_nowait()
            except:
                break
        time.sleep(0.2)

    # Réinitialiser le timestamp de référence
    start = time.time()
    while not data_q.empty():
        try:
            data_q.get_nowait()
        except:
            break
    print("Calibration démarrée !")

    # ── Processeurs signal ────────────────────────────────────
    ppg = PPGProcessor()
    pzt = PZTProcessor()
    cog = CognitiveLoadIndex()

    all_ts, all_ppg, all_pzt = [], [], []
    fc_ts, fc_v = [], []
    rr_ts, rr_v = [], []
    ic_ts, ic_v = [], []
    CALIB_SEC = 20.0
    calibrated = [False]
    calib_vals = {"fc": [], "pwa": [], "rr": []}
    WINDOW = 15.0
    DIR_Y = {"left": 0, "down": 1, "up": 2, "right": 3}

    # ── Figure temps réel (4 lignes) ─────────────────────────
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(
        4, 2, figure=fig, height_ratios=[2, 2, 1.5, 2], hspace=0.60, wspace=0.35
    )

    ax_ppg_raw = fig.add_subplot(gs[0, 0])
    ax_ppg_filt = fig.add_subplot(gs[0, 1])
    ax_pzt_raw = fig.add_subplot(gs[1, 0])
    ax_pzt_filt = fig.add_subplot(gs[1, 1])
    ax_keys = fig.add_subplot(gs[2, :])
    ax_icog = fig.add_subplot(gs[3, :])

    for ax in [ax_ppg_raw, ax_ppg_filt, ax_pzt_raw, ax_pzt_filt, ax_keys, ax_icog]:
        ax.grid(True, alpha=0.3)

    ax_ppg_raw.set(title="PPG brut", ylabel="Amplitude")
    ax_ppg_filt.set(title="PPG filtré + pics [ref 1]", ylabel="Amplitude")
    ax_pzt_raw.set(title="PZT brut", ylabel="Amplitude")
    ax_pzt_filt.set(title="PZT filtré + pics [ref 3]", ylabel="Amplitude")
    ax_keys.set(
        title="Touches jeu — ▲▼◄► (vert=correct  rouge=erreur)",
        ylabel="Direction",
        xlabel="Temps (s)",
    )
    ax_keys.set_yticks([0, 1, 2, 3])
    ax_keys.set_yticklabels(["◄ gauche", "▼ bas", "▲ haut", "► droite"], fontsize=9)
    ax_keys.set_ylim(-0.5, 3.5)
    ax_icog.axhline(y=1.5, color="red", ls="--", lw=1.5, label="Seuil > 1.5")
    ax_icog.set(
        title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
        ylabel="I_cog",
        xlabel="Temps (s)",
    )
    ax_icog.legend(fontsize=9, loc="upper left")

    fig.suptitle("ChunkyMemo — Calibration en cours...", fontsize=12)
    plt.tight_layout()

    # Positionner la fenêtre
    try:
        mgr = fig.canvas.manager
        sh = mgr.window.winfo_screenheight()
        mgr.window.wm_geometry(f"1000x720+0+{sh - 760}")
        mgr.window.attributes("-topmost", False)
    except Exception:
        pass

    _game_ended = [False]
    _closing = [False]
    _close_at = [None]

    # ── FuncAnimation ─────────────────────────────────────────
    def update(frame):
        # Détecter fin de jeu
        if not _game_ended[0]:
            try:
                with open(EVENTS_FILE) as _f:
                    _ev = json.load(_f)
                if _ev.get("game_end") and not _ev.get("_report_done"):
                    _game_ended[0] = True
                    _close_at[0] = time.time() + 1.0
            except Exception:
                pass

        if _game_ended[0] and _close_at[0] and time.time() >= _close_at[0]:
            if not _closing[0]:
                _closing[0] = True
                # Enrichir les niveaux MAINTENANT (avant que analysis.py tourne)
                _enrich_levels(all_ts, fc_ts, fc_v, rr_ts, rr_v, ppg)
                try:
                    with open(EVENTS_FILE) as _f:
                        _ev = json.load(_f)
                    _ev["_report_done"] = True
                    with open(EVENTS_FILE, "w") as _f:
                        json.dump(_ev, _f)
                except Exception:
                    pass
                ani.event_source.stop()
                _show_final_in_fig(
                    fig,
                    gs,
                    all_ts,
                    all_ppg,
                    all_pzt,
                    fc_ts,
                    fc_v,
                    rr_ts,
                    rr_v,
                    ic_ts,
                    ic_v,
                    ppg,
                    pzt,
                    cog,
                    CALIB_SEC,
                )
            return

        # Vider la queue
        while not data_q.empty():
            try:
                s = data_q.get_nowait()
            except:
                break

            ts_rel = s["ts"] - start
            all_ts.append(ts_rel)
            all_ppg.append(s["ppg"])
            all_pzt.append(s["pzt"])

            if ts_rel < CALIB_SEC:
                ppg.update(s["ppg"], s["ts"])
                pzt.update(s["pzt"], s["ts"])
                if ppg.fc_bpm:
                    calib_vals["fc"].append(ppg.fc_bpm)
                    fc_ts.append(ts_rel)
                    fc_v.append(ppg.fc_bpm)
                if ppg.pwa_raw:
                    calib_vals["pwa"].append(ppg.pwa_raw)
                if pzt.rr_rpm:
                    calib_vals["rr"].append(pzt.rr_rpm)
                    rr_ts.append(ts_rel)
                    rr_v.append(pzt.rr_rpm)
            else:
                if not calibrated[0]:
                    calibrated[0] = True
                    if calib_vals["pwa"]:
                        ppg.set_baseline(float(np.mean(calib_vals["pwa"])))
                        cog.set_baseline("pwa", calib_vals["pwa"])
                    if calib_vals["fc"]:
                        cog.set_baseline("fc", calib_vals["fc"])
                    if calib_vals["rr"]:
                        cog.set_baseline("rr", calib_vals["rr"])
                    cog.set_baseline("rt", [400, 450, 500, 550, 600])
                    print("[Calibration] Terminée !")

                ppg.update(s["ppg"], s["ts"])
                pzt.update(s["pzt"], s["ts"])
                ic = cog.update(ppg.fc_bpm, ppg.pwa_raw, pzt.rr_rpm, None, s["ts"])
                if ppg.fc_bpm:
                    fc_ts.append(ts_rel)
                    fc_v.append(ppg.fc_bpm)
                if pzt.rr_rpm:
                    rr_ts.append(ts_rel)
                    rr_v.append(pzt.rr_rpm)
                if ic is not None:
                    ic_ts.append(ts_rel)
                    ic_v.append(ic)

        if not all_ts:
            return

        t_now = all_ts[-1]
        # Fenêtre glissante : si < WINDOW montrer depuis 0
        x_min = max(0, t_now - WINDOW) if t_now >= WINDOW else 0

        # PPG brut
        ax_ppg_raw.cla()
        ax_ppg_raw.grid(True, alpha=0.3)
        ax_ppg_raw.set(title="PPG brut", ylabel="Amplitude")
        mask = [(t, v) for t, v in zip(all_ts, all_ppg) if t >= x_min]
        if mask:
            tt, vv = zip(*mask)
            ax_ppg_raw.plot(tt, vv, color="lightcoral", lw=0.7)
            ax_ppg_raw.set_xlim(x_min, t_now + 0.3)
            ax_ppg_raw.set_ylim(min(vv) - 5, max(vv) + 5)

        # PPG filtré
        ax_ppg_filt.cla()
        ax_ppg_filt.grid(True, alpha=0.3)
        fp = ppg.get_filtered_signal()
        if len(fp) > 0:
            n = len(fp)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, t_now, n)
            ax_ppg_filt.plot(tf, fp, color="tab:red", lw=1.0)
            ax_ppg_filt.set_xlim(max(0, t_now - WINDOW), t_now + 0.3)
            if fp.max() != fp.min():
                ax_ppg_filt.set_ylim(fp.min() - 10, fp.max() + 10)
            pi = [p for p in ppg.last_peaks if p < n]
            if pi:
                ax_ppg_filt.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)
        fc_s = f"FC={ppg.fc_bpm:.0f}bpm" if ppg.fc_bpm else "FC=---"
        ax_ppg_filt.set(title=f"PPG filtré + pics — {fc_s} [ref 1]", ylabel="Amplitude")

        # PZT brut
        ax_pzt_raw.cla()
        ax_pzt_raw.grid(True, alpha=0.3)
        ax_pzt_raw.set(title="PZT brut", ylabel="Amplitude")
        mask = [(t, v) for t, v in zip(all_ts, all_pzt) if t >= x_min]
        if mask:
            tt, vv = zip(*mask)
            ax_pzt_raw.plot(tt, vv, color="moccasin", lw=0.7)
            ax_pzt_raw.set_xlim(x_min, t_now + 0.3)
            ax_pzt_raw.set_ylim(min(vv) - 5, max(vv) + 5)

        # PZT filtré
        ax_pzt_filt.cla()
        ax_pzt_filt.grid(True, alpha=0.3)
        fz = pzt.get_filtered_signal()
        if len(fz) > 0:
            n = len(fz)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, t_now, n)
            ax_pzt_filt.plot(tf, fz, color="tab:orange", lw=1.0)
            ax_pzt_filt.set_xlim(max(0, t_now - WINDOW), t_now + 0.3)
            if fz.max() != fz.min():
                ax_pzt_filt.set_ylim(fz.min() - 10, fz.max() + 10)
            pi = [p for p in pzt.last_peaks if p < n]
            if pi:
                ax_pzt_filt.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)
        rr_s = f"RR={pzt.rr_rpm:.0f}rpm" if pzt.rr_rpm else "RR=---"
        ax_pzt_filt.set(title=f"PZT filtré + pics — {rr_s} [ref 3]", ylabel="Amplitude")

        # Touches jeu
        ax_keys.cla()
        ax_keys.grid(True, alpha=0.2)
        ax_keys.set(
            title="Touches jeu — ▲▼◄► (vert=correct  rouge=erreur)",
            ylabel="Direction",
            xlabel="Temps (s)",
        )
        ax_keys.set_yticks([0, 1, 2, 3])
        ax_keys.set_yticklabels(["◄ gauche", "▼ bas", "▲ haut", "► droite"], fontsize=9)
        ax_keys.set_ylim(-0.5, 3.5)
        ax_keys.set_xlim(x_min, t_now + 0.3)
        try:
            with open(EVENTS_FILE) as _f:
                _ev = json.load(_f)
            for k in _ev.get("keys", []):
                ts_k = k["ts"]
                if ts_k >= x_min:
                    y = DIR_Y.get(k["direction"], 2)
                    c = "#1D9E75" if k["correct"] else "#E24B4A"
                    ax_keys.scatter(
                        ts_k,
                        y,
                        color=c,
                        s=150,
                        marker="^" if k["correct"] else "x",
                        zorder=5,
                        linewidths=2,
                    )
            for lv in _ev.get("levels", []):
                lts = lv["ts"]
                if lts >= x_min:
                    ax_keys.axvline(x=lts, color="#014F84", alpha=0.4, lw=1)
                    ax_keys.text(
                        lts,
                        3.2,
                        f"N{lv['level']}",
                        fontsize=7,
                        color="#014F84",
                        ha="center",
                    )
        except Exception:
            pass

        # I_cog
        ax_icog.cla()
        ax_icog.grid(True, alpha=0.3)
        ax_icog.axhline(y=1.5, color="red", ls="--", lw=1.5, label="Seuil > 1.5")
        ax_icog.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
        ax_icog.set(
            title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
            ylabel="I_cog",
            xlabel="Temps (s)",
        )
        if ic_ts and ic_v:
            t_ni = ic_ts[-1]
            t_mi = max(0, t_ni - WINDOW)
            pairs = [(t, v) for t, v in zip(ic_ts, ic_v) if t >= t_mi]
            if pairs:
                tt, vv = zip(*pairs)
                ax_icog.plot(tt, vv, color="tab:purple", lw=2.0, label="I_cog")
                ax_icog.fill_between(
                    tt, vv, 1.5, where=[v > 1.5 for v in vv], color="red", alpha=0.25
                )
                ax_icog.set_xlim(t_mi, t_ni + 0.3)
                allv = list(vv) + [1.5, 0]
                mg = max(0.3, (max(allv) - min(allv)) * 0.15)
                ax_icog.set_ylim(min(allv) - mg, max(allv) + mg)
            else:
                ax_icog.set_xlim(x_min, t_now + 0.3)
                ax_icog.set_ylim(-0.5, 2.5)
        else:
            ax_icog.set_xlim(x_min, t_now + 0.3)
            ax_icog.set_ylim(-0.5, 2.5)
            if not calibrated[0]:
                rem = max(0, CALIB_SEC - t_now)
                ax_icog.text(
                    0.5,
                    0.5,
                    f"Calibration {rem:.0f}s restantes — I_cog disponible après",
                    transform=ax_icog.transAxes,
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="#014F84",
                    style="italic",
                )
        ax_icog.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.5)
        ax_icog.legend(fontsize=9, loc="upper left")

        # Titre
        ic_s = f"I_cog={cog.i_cog:.2f}" if cog.i_cog is not None else "---"
        ov = "  ⚠SURCHARGE" if cog.overload else ""
        st = (
            "[CALIBRATION — restez immobile]"
            if not calibrated[0]
            else f"I_cog={ic_s}{ov}"
        )
        fig.suptitle(f"ChunkyMemo — {fc_s}  {rr_s}  {st}", fontsize=11)

    ani = FuncAnimation(fig, update, interval=100, blit=False, cache_frame_data=False)
    plt.show(block=True)

    acq.stop()
    print(f"\nSession : {len(all_ppg)} échantillons  FC={ppg.fc_bpm}  RR={pzt.rr_rpm}")

    # Sauvegarder les données complètes de la session pour analysis.py
    try:
        with open(EVENTS_FILE) as f:
            ev = json.load(f)
        mode = ev.get("mode", "normal").lower()
        # Construire le dict de session compatible avec analysis.py
        session_data = {
            "mode": mode,
            "levels": ev.get("levels", []),
            "raw_pzt": all_pzt,
            "timestamps": all_ts,
            "level_events": [(lv["ts"], lv["level"]) for lv in ev.get("levels", [])],
        }
        # Ajouter les métriques physiologiques par niveau
        snap_fc = ppg.fc_bpm
        snap_rr = pzt.rr_rpm
        snap_pwa = ppg.pwa_raw
        for lv in session_data["levels"]:
            if "hr_bpm" not in lv:
                lv["hr_bpm"] = snap_fc
                lv["rr_rpm"] = snap_rr
                lv["ppg_amplitude"] = snap_pwa
                lv["success"] = True  # on ne sait pas ici, game_only le sait

        fname_session = f"sessions/session_{mode}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("sessions", exist_ok=True)
        with open(fname_session, "w") as f:
            json.dump(session_data, f)
        print(f"[session] Sauvegardée : {fname_session}")
        print(
            "[session] Lancez 'python analysis.py' pour la comparaison Normal vs Chunking"
        )
    except Exception as e:
        print(f"[session] Erreur sauvegarde : {e}")


def _enrich_levels(all_ts, fc_ts, fc_v, rr_ts, rr_v, ppg):
    """
    Calcule FC/RR/PWA moyenne pour chaque niveau à partir des séries temporelles.
    Enrichit le JSON live_events avec ces valeurs.
    """
    try:
        with open(EVENTS_FILE) as f:
            ev = json.load(f)

        def mean_in_window(ts_series, v_series, t_start, t_end):
            if t_end is None:
                t_end = max(ts_series) if ts_series else t_start + 30
            vals = [
                v
                for t, v in zip(ts_series, v_series)
                if v is not None and t_start <= t <= t_end
            ]
            return float(sum(vals) / len(vals)) if vals else None

        for phase in ("levels_normal", "levels_chunking"):
            lvs = ev.get(phase, [])
            for i, lv in enumerate(lvs):
                t0 = lv.get("ts", 0)
                t1 = lv.get("ts_end") or (
                    lvs[i + 1]["ts"] if i + 1 < len(lvs) else None
                )
                lv["hr_bpm"] = mean_in_window(fc_ts, fc_v, t0, t1)
                lv["rr_rpm"] = mean_in_window(rr_ts, rr_v, t0, t1)
                # PWA depuis ppg brut
                if all_ts:
                    pwa_vals = [ppg.pwa_raw] if ppg.pwa_raw else []
                    # approximation : dernier pwa_raw connu
                    lv["ppg_amplitude"] = ppg.pwa_raw

        with open(EVENTS_FILE, "w") as f:
            json.dump(ev, f)
        print("[physio] Niveaux enrichis avec FC/RR")
    except Exception as e:
        print(f"[physio] Erreur enrichissement : {e}")


def _show_final_in_fig(
    fig,
    gs,
    all_ts,
    all_ppg,
    all_pzt,
    fc_ts,
    fc_v,
    rr_ts,
    rr_v,
    ic_ts,
    ic_v,
    ppg,
    pzt,
    cog,
    CALIB_SEC,
):
    """Remplace les axes temps réel par le rapport final dans la même fenêtre."""
    import matplotlib.gridspec as gridspec
    import matplotlib.pyplot as plt

    # (enrichissement déjà fait dans update() avant l'appel)

    # Effacer tous les axes existants
    for ax in fig.get_axes():
        fig.delaxes(ax)

    DIR_Y = {"left": 0, "down": 1, "up": 2, "right": 3}
    THRESHOLD = 1.5

    gs2 = gridspec.GridSpec(
        5, 2, figure=fig, height_ratios=[2, 2, 1.5, 1.5, 1.5], hspace=0.65, wspace=0.35
    )

    fc_fin = ppg.fc_bpm
    rr_fin = pzt.rr_rpm
    ic_fin = cog.i_cog
    fc_s = f"FC={fc_fin:.0f}bpm" if fc_fin else "FC=---"
    rr_s = f"RR={rr_fin:.0f}rpm" if rr_fin else "RR=---"
    ic_s = f"I_cog={ic_fin:.2f}" if ic_fin is not None else "I_cog=---"

    try:
        with open(EVENTS_FILE) as f:
            ev = json.load(f)
    except Exception:
        ev = {"levels": [], "keys": []}

    max_lv = max((lv["level"] for lv in ev.get("levels", [])), default=0)
    n_lvs = len(ev.get("levels", []))

    fig.suptitle(
        f"ChunkyMemo — Session complète  |  Mode : NORMAL  |  "
        f"Niveaux joués : {n_lvs}  |  Niveau max : {max_lv}  |  "
        f"{fc_s}  {rr_s}  {ic_s}",
        fontsize=11,
        fontweight="bold",
    )

    # PPG brut
    ax1 = fig.add_subplot(gs2[0, 0])
    ax1.set(title="PPG brut — session complète", ylabel="Amplitude")
    ax1.grid(True, alpha=0.3)
    if all_ts and all_ppg:
        ax1.plot(all_ts, all_ppg, color="lightcoral", lw=0.4, alpha=0.8)

    # PPG filtré
    ax2 = fig.add_subplot(gs2[0, 1])
    ax2.set(title=f"PPG filtré + pics ({fc_s})", ylabel="Amplitude")
    ax2.grid(True, alpha=0.3)
    fp = ppg.get_filtered_signal()
    if len(fp) > 0 and all_ts:
        n = len(fp)
        tf = (
            np.array(all_ts[-n:])
            if n <= len(all_ts)
            else np.linspace(all_ts[0], all_ts[-1], n)
        )
        ax2.plot(tf, fp, color="tab:red", lw=0.8)
        pi = [p for p in ppg.last_peaks if p < len(tf)]
        if pi:
            ax2.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)

    # PZT brut
    ax3 = fig.add_subplot(gs2[1, 0])
    ax3.set(title="PZT brut — session complète", ylabel="Amplitude")
    ax3.grid(True, alpha=0.3)
    if all_ts and all_pzt:
        ax3.plot(all_ts, all_pzt, color="moccasin", lw=0.4, alpha=0.8)

    # PZT filtré
    ax4 = fig.add_subplot(gs2[1, 1])
    ax4.set(title=f"PZT filtré + pics ({rr_s})", ylabel="Amplitude")
    ax4.grid(True, alpha=0.3)
    fz = pzt.get_filtered_signal()
    if len(fz) > 0 and all_ts:
        n = len(fz)
        tf = (
            np.array(all_ts[-n:])
            if n <= len(all_ts)
            else np.linspace(all_ts[0], all_ts[-1], n)
        )
        ax4.plot(tf, fz, color="tab:orange", lw=0.8)
        pi = [p for p in pzt.last_peaks if p < len(tf)]
        if pi:
            ax4.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)

    # FC
    ax5 = fig.add_subplot(gs2[2, :])
    ax5.set(
        title="Fréquence cardiaque calculée [ref 1]",
        ylabel="FC (bpm)",
        xlabel="Temps (s)",
    )
    ax5.grid(True, alpha=0.3)
    if fc_ts and fc_v:
        ax5.plot(fc_ts, fc_v, "o-", color="crimson", lw=1.5, ms=4, label="FC (bpm)")
    ax5.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calibration")
    bl_fc = cog._baseline["fc"]["mu"]
    if bl_fc:
        ax5.axhline(
            y=bl_fc, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_fc:.0f}"
        )
    if fc_v:
        fc_max = max(fc_v)
        for lv in ev.get("levels", []):
            lts = lv["ts"]
            ax5.axvline(x=lts, color="#014F84", alpha=0.3, lw=1)
            ax5.text(
                lts,
                fc_max * 0.97,
                f"N{lv['level']}",
                fontsize=7,
                color="#014F84",
                ha="center",
            )
    ax5.legend(fontsize=8, loc="upper left")

    # RR + touches
    ax6 = fig.add_subplot(gs2[3, :])
    ax6.set(
        title="Rythme respiratoire calculé + apnées + touches [ref 3]",
        ylabel="RR (rpm)",
        xlabel="Temps (s)",
    )
    ax6.grid(True, alpha=0.3)
    if rr_ts and rr_v:
        ax6.plot(rr_ts, rr_v, "s-", color="darkorange", lw=1.5, ms=4, label="RR (rpm)")
    ax6.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6)
    bl_rr = cog._baseline["rr"]["mu"]
    if bl_rr:
        ax6.axhline(
            y=bl_rr, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_rr:.0f}"
        )
    keys = ev.get("keys", [])
    if keys:
        ax6b = ax6.twinx()
        ok = [(k["ts"], DIR_Y.get(k["direction"], 2)) for k in keys if k["correct"]]
        err = [
            (k["ts"], DIR_Y.get(k["direction"], 2)) for k in keys if not k["correct"]
        ]
        if ok:
            xs, ys = zip(*ok)
            ax6b.scatter(
                xs,
                ys,
                color="#1D9E75",
                s=80,
                marker="^",
                alpha=0.8,
                zorder=5,
                label="Correct",
            )
        if err:
            xs, ys = zip(*err)
            ax6b.scatter(
                xs,
                ys,
                color="#E24B4A",
                s=80,
                marker="x",
                alpha=0.8,
                zorder=5,
                linewidths=2,
                label="Erreur",
            )
        ax6b.set_yticks([0, 1, 2, 3])
        ax6b.set_yticklabels(["◄", "▼", "▲", "►"], fontsize=9)
        ax6b.set_ylim(-0.5, 3.5)
        ax6b.legend(fontsize=8, loc="upper right")
    if rr_v:
        rr_max = max(rr_v)
        for lv in ev.get("levels", []):
            lts = lv["ts"]
            ax6.axvline(x=lts, color="#014F84", alpha=0.3, lw=1)
            ax6.text(
                lts,
                rr_max * 0.97,
                f"N{lv['level']}",
                fontsize=7,
                color="#014F84",
                ha="center",
            )
    ax6.legend(fontsize=8, loc="upper left")

    # I_cog
    ax7 = fig.add_subplot(gs2[4, :])
    ax7.set(
        title="Indice composite I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
        ylabel="I_cog",
        xlabel="Temps (s)",
    )
    ax7.grid(True, alpha=0.3)
    if ic_ts and ic_v:
        ax7.plot(ic_ts, ic_v, color="tab:purple", lw=2.0, label="I_cog")
        ax7.fill_between(
            ic_ts,
            ic_v,
            THRESHOLD,
            where=[v > THRESHOLD for v in ic_v],
            color="red",
            alpha=0.25,
            label="Surcharge",
        )
    ax7.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.5)
    ax7.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
    ax7.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calibration")
    ax7.legend(fontsize=8, loc="upper left")

    fig.canvas.draw_idle()
    print("[rapport] Rapport final affiché dans la fenêtre matplotlib")


if __name__ == "__main__":
    main()

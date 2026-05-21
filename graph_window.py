"""
graph_window.py — Fenêtres matplotlib dans un THREAD (pas multiprocessing).

Tk doit être initialisé AVANT pygame. main.py doit donc importer
ce module et appeler GraphWindow() AVANT pygame.init().

Les figures tournent dans leur propre thread Tk via matplotlib.
Pas de conflit GIL car on utilise la boucle Tk propre à matplotlib.
"""

import threading
import time
import queue
import numpy as np


DIR_Y     = {"left": 0, "down": 1, "up": 2, "right": 3}
THRESHOLD = 1.5


class GraphWindow:
    """
    Gère toutes les fenêtres matplotlib dans un thread dédié.
    Communique via une queue de commandes (thread-safe).
    """

    def __init__(self):
        self._cmd_q = queue.Queue(maxsize=100)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Attendre que matplotlib soit prêt
        time.sleep(0.5)

    def send(self, msg: dict):
        try:
            self._cmd_q.put_nowait(msg)
        except queue.Full:
            pass

    def open_calib(self):    self.send({"type": "open_calib"})
    def close_calib(self):   self.send({"type": "close_calib"})
    def open_game(self):     self.send({"type": "open_game"})
    def close_game(self):    self.send({"type": "close_game"})
    def update_calib(self, d):  self.send({**d, "type": "calib_update"})
    def update_game(self, d):   self.send({**d, "type": "game_update"})
    def show_final(self, d):    self.send({**d, "type": "final_report"})

    # ── Thread Tk/matplotlib ──────────────────────────────────

    def _run(self):
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from matplotlib.animation import FuncAnimation

        # Désactiver raccourcis conflictuels
        for key in ['s','q','z','Z','d','g','p','f','h','l']:
            for km in ['keymap.save','keymap.quit','keymap.zoom','keymap.xscale',
                       'keymap.yscale','keymap.grid','keymap.pan','keymap.fullscreen',
                       'keymap.home','keymap.back']:
                try:
                    if key in matplotlib.rcParams.get(km, []):
                        matplotlib.rcParams[km].remove(key)
                except Exception:
                    pass

        self._plt = plt
        self._gs  = gridspec
        self._fig_calib  = None
        self._axes_calib = {}
        self._fig_game   = None
        self._axes_game  = {}

        plt.ion()

        def _safe_draw(fig):
            try:
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
            except Exception:
                pass

        def _pos(fig, x, y):
            try:
                fig.canvas.manager.window.wm_geometry(f"+{x}+{y}")
                fig.canvas.manager.window.attributes("-topmost", False)
            except Exception:
                pass

        # ── Calibration ───────────────────────────────────────
        def open_calib():
            fig, axs = plt.subplots(2, 2, figsize=(12, 7))
            fig.suptitle("ChunkyMemo — Calibration", fontsize=11)
            self._fig_calib  = fig
            self._axes_calib = {
                "ppg_raw":  axs[0][0], "ppg_filt": axs[0][1],
                "pzt_raw":  axs[1][0], "pzt_filt": axs[1][1],
            }
            for ax in axs.flat:
                ax.grid(True, alpha=0.3)
            axs[0][0].set(title="PPG brut",                   ylabel="Amplitude")
            axs[0][1].set(title="PPG filtré + pics [ref 1]",  ylabel="Amplitude")
            axs[1][0].set(title="PZT brut",                   ylabel="Amplitude")
            axs[1][1].set(title="PZT filtré + pics [ref 3]",  ylabel="Amplitude")
            plt.tight_layout()
            _pos(fig, 760, 30)
            plt.pause(0.001)

        def update_calib(d):
            fig = self._fig_calib
            if fig is None:
                return
            axes = self._axes_calib
            rem  = d.get("remaining", 0)
            fc_str = d.get("fc_str", "---")
            rr_str = d.get("rr_str", "---")

            ax = axes["ppg_raw"]
            ax.cla(); ax.grid(True, alpha=0.3); ax.set(title="PPG brut", ylabel="Amplitude")
            if d.get("ppg_raw"): ax.plot(d["ppg_raw"], color="lightcoral", lw=0.7)

            ax = axes["ppg_filt"]
            ax.cla(); ax.grid(True, alpha=0.3)
            ax.set(title=f"PPG filtré — FC={fc_str}", ylabel="Amplitude")
            if d.get("ppg_filt"):
                fp = np.array(d["ppg_filt"])
                ax.plot(fp, color="tab:red", lw=1.0)
                pi = [p for p in d.get("ppg_peaks",[]) if p < len(fp)]
                if pi: ax.plot(pi, fp[pi], "x", color="darkred", ms=8, mew=2)

            ax = axes["pzt_raw"]
            ax.cla(); ax.grid(True, alpha=0.3); ax.set(title="PZT brut", ylabel="Amplitude")
            if d.get("pzt_raw"): ax.plot(d["pzt_raw"], color="moccasin", lw=0.7)

            ax = axes["pzt_filt"]
            ax.cla(); ax.grid(True, alpha=0.3)
            ax.set(title=f"PZT filtré — RR={rr_str}", ylabel="Amplitude")
            if d.get("pzt_filt"):
                fz = np.array(d["pzt_filt"])
                ax.plot(fz, color="tab:orange", lw=1.0)
                pi = [p for p in d.get("pzt_peaks",[]) if p < len(fz)]
                if pi: ax.plot(pi, fz[pi], "x", color="darkorange", ms=8, mew=2)

            fig.suptitle(
                f"ChunkyMemo — Calibration {rem:.0f}s restantes — "
                f"FC={fc_str}  RR={rr_str}  [RESTEZ IMMOBILE]",
                fontsize=10
            )
            _safe_draw(fig)

        # ── Jeu (4 lignes) ────────────────────────────────────
        def open_game():
            fig = plt.figure(figsize=(13, 11))
            gs  = gridspec.GridSpec(4, 2, figure=fig,
                                    height_ratios=[2,2,1.5,2],
                                    hspace=0.65, wspace=0.35)
            self._fig_game  = fig
            self._axes_game = {
                "ppg_raw":  fig.add_subplot(gs[0,0]),
                "ppg_filt": fig.add_subplot(gs[0,1]),
                "pzt_raw":  fig.add_subplot(gs[1,0]),
                "pzt_filt": fig.add_subplot(gs[1,1]),
                "keys":     fig.add_subplot(gs[2,:]),
                "icog":     fig.add_subplot(gs[3,:]),
            }
            ax = self._axes_game
            ax["ppg_raw"].set( title="PPG brut",                   ylabel="Amplitude"); ax["ppg_raw"].grid(True, alpha=0.3)
            ax["ppg_filt"].set(title="PPG filtré + pics [ref 1]",  ylabel="Amplitude"); ax["ppg_filt"].grid(True, alpha=0.3)
            ax["pzt_raw"].set( title="PZT brut",                   ylabel="Amplitude"); ax["pzt_raw"].grid(True, alpha=0.3)
            ax["pzt_filt"].set(title="PZT filtré + pics [ref 3]",  ylabel="Amplitude"); ax["pzt_filt"].grid(True, alpha=0.3)
            ax["keys"].set(title="Touches — vert=correct  rouge=erreur",
                           ylabel="Touche", xlabel="Temps (s)")
            ax["keys"].set_yticks([0,1,2,3])
            ax["keys"].set_yticklabels(["◄ gauche","▼ bas","▲ haut","► droite"], fontsize=9)
            ax["keys"].set_ylim(-0.5, 3.5); ax["keys"].grid(True, alpha=0.2)
            ax["icog"].axhline(y=THRESHOLD, color="red", ls="--", lw=1.5,
                               label=f"Seuil > {THRESHOLD}")
            ax["icog"].axhline(y=0, color="gray", ls=":", alpha=0.4)
            ax["icog"].set(title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
                           ylabel="I_cog", xlabel="Temps (s)")
            ax["icog"].legend(fontsize=9); ax["icog"].grid(True, alpha=0.3)
            fig.suptitle("ChunkyMemo — Jeu en cours", fontsize=11)
            plt.tight_layout()
            _pos(fig, 760, 30)
            plt.pause(0.001)

        def update_game(d):
            fig = self._fig_game
            if fig is None:
                return
            ax      = self._axes_game
            all_ts  = d.get("all_ts", [])
            fc_v    = d.get("fc_v",   [])
            rr_v    = d.get("rr_v",   [])
            ic_ts   = d.get("ic_ts",  [])
            ic_v    = d.get("ic_v",   [])
            key_ev  = d.get("key_events", [])
            fc_str  = d.get("fc_str", "---")
            rr_str  = d.get("rr_str", "---")
            ic_str  = d.get("ic_str", "---")
            overload= d.get("overload", False)
            apnea   = d.get("apnea",   False)
            WIN     = 25.0

            # t_now = dernier timestamp dispo (physio ou I_cog)
            t_now_p = all_ts[-1] if all_ts else 0
            t_now_i = ic_ts[-1]  if ic_ts  else 0
            t_now   = max(t_now_p, t_now_i)
            t_min   = max(0, t_now - WIN)

            # PPG brut
            a = ax["ppg_raw"]; a.cla(); a.grid(True, alpha=0.3)
            a.set(title="PPG brut", ylabel="Amplitude")
            if d.get("ppg_raw") and all_ts:
                n = min(len(d["ppg_raw"]), len(all_ts))
                pairs = [(t,v) for t,v in zip(all_ts[-n:], d["ppg_raw"][-n:]) if t >= t_min]
                if pairs:
                    tt,vv = zip(*pairs); a.plot(tt, vv, color="lightcoral", lw=0.7)
                    a.set_xlim(t_min, t_now+0.3); a.set_ylim(min(vv)-5, max(vv)+5)

            # PPG filtré
            a = ax["ppg_filt"]; a.cla(); a.grid(True, alpha=0.3)
            a.set(title=f"PPG filtré + pics (FC={fc_str}) [ref 1]", ylabel="Amplitude")
            if d.get("ppg_filt") and all_ts:
                fp = np.array(d["ppg_filt"]); n = len(fp)
                t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
                tf = np.linspace(t0, t_now_p, n)
                a.plot(tf, fp, color="tab:red", lw=1.0)
                a.set_xlim(max(0, t_now_p-WIN), t_now_p+0.3)
                if fp.max() != fp.min(): a.set_ylim(fp.min()-10, fp.max()+10)
                pi = [p for p in d.get("ppg_peaks",[]) if p < n]
                if pi: a.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)

            # PZT brut
            a = ax["pzt_raw"]; a.cla(); a.grid(True, alpha=0.3)
            a.set(title="PZT brut", ylabel="Amplitude")
            if d.get("pzt_raw") and all_ts:
                n = min(len(d["pzt_raw"]), len(all_ts))
                pairs = [(t,v) for t,v in zip(all_ts[-n:], d["pzt_raw"][-n:]) if t >= t_min]
                if pairs:
                    tt,vv = zip(*pairs); a.plot(tt, vv, color="moccasin", lw=0.7)
                    a.set_xlim(t_min, t_now+0.3); a.set_ylim(min(vv)-5, max(vv)+5)

            # PZT filtré
            a = ax["pzt_filt"]; a.cla(); a.grid(True, alpha=0.3)
            a.set(title=f"PZT filtré + pics (RR={rr_str}) [ref 3]", ylabel="Amplitude")
            if d.get("pzt_filt") and all_ts:
                fz = np.array(d["pzt_filt"]); n = len(fz)
                t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
                tf = np.linspace(t0, t_now_p, n)
                a.plot(tf, fz, color="tab:orange", lw=1.0)
                a.set_xlim(max(0, t_now_p-WIN), t_now_p+0.3)
                if fz.max() != fz.min(): a.set_ylim(fz.min()-10, fz.max()+10)
                pi = [p for p in d.get("pzt_peaks",[]) if p < n]
                if pi: a.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)

            # Touches
            a = ax["keys"]; a.cla(); a.grid(True, alpha=0.2)
            a.set(title="Touches — ▲▼◄► (vert=correct  rouge=erreur)",
                  ylabel="Touche", xlabel="Temps (s)")
            a.set_yticks([0,1,2,3])
            a.set_yticklabels(["◄ gauche","▼ bas","▲ haut","► droite"], fontsize=9)
            a.set_ylim(-0.5, 3.5); a.set_xlim(t_min, t_now+0.3)
            for (ts_k, d_, c) in key_ev:
                if ts_k >= t_min:
                    a.scatter(ts_k, DIR_Y.get(d_,2),
                              color="#1D9E75" if c else "#E24B4A",
                              s=150, marker="^" if c else "x",
                              zorder=5, linewidths=2)

            # I_cog — utilise IC_TS propres
            a = ax["icog"]; a.cla(); a.grid(True, alpha=0.3)
            a.axhline(y=THRESHOLD, color="red", ls="--", lw=1.5, label=f"Seuil > {THRESHOLD}")
            a.axhline(y=0, color="gray", ls=":", alpha=0.4)
            a.set(title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
                  ylabel="I_cog", xlabel="Temps (s)")
            if ic_ts and ic_v:
                t_ni = ic_ts[-1]; t_mi = max(0, t_ni - WIN)
                pairs = [(t,v) for t,v in zip(ic_ts, ic_v) if t >= t_mi]
                if pairs:
                    tt, vv = zip(*pairs)
                    a.plot(tt, vv, color="tab:purple", lw=2.0, label="I_cog")
                    a.fill_between(tt, vv, THRESHOLD,
                        where=[v > THRESHOLD for v in vv], color="red", alpha=0.25)
                    a.set_xlim(t_mi, t_ni+0.3)
                    allv = list(vv)+[THRESHOLD,0]
                    mg   = max(0.3,(max(allv)-min(allv))*0.15)
                    a.set_ylim(min(allv)-mg, max(allv)+mg)
                else:
                    a.set_xlim(t_min, t_now+0.3); a.set_ylim(-0.5, 2.5)
            else:
                a.set_xlim(t_min, t_now+0.3); a.set_ylim(-0.5, 2.5)
                a.text(0.5, 0.5, "I_cog en calcul\n(calibration pas encore terminée)",
                       transform=a.transAxes, ha="center", va="center",
                       fontsize=10, color="gray", style="italic")
            a.legend(fontsize=9, loc="upper left")

            ov = "  ⚠ SURCHARGE" if overload else ""
            ap = " | APNÉE" if apnea else ""
            fig.suptitle(f"ChunkyMemo — FC={fc_str}  RR={rr_str}  I_cog={ic_str}{ov}{ap}",
                         fontsize=11)
            _safe_draw(fig)

        # ── Rapport final ─────────────────────────────────────
        def show_final(d):
            plt.ioff()
            levels   = d.get("levels", [])
            lvs      = [lv for lv in levels if lv.get("level") is not None]
            all_ts   = d.get("all_ts",  []); all_ppg = d.get("all_ppg", [])
            all_pzt  = d.get("all_pzt", [])
            fc_ts_a  = d.get("fc_ts",   []); fc_v_a  = d.get("fc_v",   [])
            rr_ts_a  = d.get("rr_ts",   []); rr_v_a  = d.get("rr_v",   [])
            ic_ts_a  = d.get("ic_ts",   []); ic_v_a  = d.get("ic_v",   [])
            ppg_filt = d.get("ppg_filt",[]); ppg_pk  = d.get("ppg_peaks",[])
            pzt_filt = d.get("pzt_filt",[]); pzt_pk  = d.get("pzt_peaks",[])
            bl_fc    = d.get("bl_fc"); bl_rr = d.get("bl_rr")
            fc_fin   = d.get("fc_final"); rr_fin = d.get("rr_final"); ic_fin = d.get("ic_final")
            mode     = d.get("mode","NORMAL"); key_ev = d.get("key_events",[])
            CALIB    = d.get("calib_sec", 20.0)
            max_lv   = max((lv["level"] for lv in lvs), default=0)

            fig2 = plt.figure(figsize=(15,14))
            gs2  = gridspec.GridSpec(5, 2, figure=fig2,
                                     height_ratios=[2,2,1.5,1.5,1.5],
                                     hspace=0.65, wspace=0.35)
            fc_s = f"FC={'%.0f'%fc_fin if fc_fin else '---'}bpm"
            rr_s = f"RR={'%.0f'%rr_fin if rr_fin else '---'}rpm"
            ic_s = f"I_cog={'%.2f'%ic_fin if ic_fin is not None else '---'}"
            fig2.suptitle(
                f"ChunkyMemo — Rapport final  |  Mode:{mode}  Niveaux:{len(lvs)}  Max:N{max_lv}\n"
                f"{fc_s}  {rr_s}  {ic_s}",
                fontsize=12, fontweight="bold"
            )

            # PPG brut
            ax = fig2.add_subplot(gs2[0,0])
            ax.set(title="PPG brut — session complète", ylabel="Amplitude"); ax.grid(True,alpha=0.3)
            if all_ts and all_ppg: ax.plot(all_ts, all_ppg, color="lightcoral", lw=0.4, alpha=0.8)

            # PPG filtré
            ax = fig2.add_subplot(gs2[0,1])
            ax.set(title=f"PPG filtré + pics ({fc_s})", ylabel="Amplitude"); ax.grid(True,alpha=0.3)
            if ppg_filt and all_ts:
                fp = np.array(ppg_filt); n = len(fp)
                tf = np.array(all_ts[-n:]) if n<=len(all_ts) else np.linspace(all_ts[0],all_ts[-1],n)
                ax.plot(tf, fp, color="tab:red", lw=0.8)
                pi = [p for p in ppg_pk if p<len(tf)]
                if pi: ax.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)

            # PZT brut
            ax = fig2.add_subplot(gs2[1,0])
            ax.set(title="PZT brut — session complète", ylabel="Amplitude"); ax.grid(True,alpha=0.3)
            if all_ts and all_pzt: ax.plot(all_ts, all_pzt, color="moccasin", lw=0.4, alpha=0.8)

            # PZT filtré
            ax = fig2.add_subplot(gs2[1,1])
            ax.set(title=f"PZT filtré + pics ({rr_s})", ylabel="Amplitude"); ax.grid(True,alpha=0.3)
            if pzt_filt and all_ts:
                fz = np.array(pzt_filt); n = len(fz)
                tf = np.array(all_ts[-n:]) if n<=len(all_ts) else np.linspace(all_ts[0],all_ts[-1],n)
                ax.plot(tf, fz, color="tab:orange", lw=0.8)
                pi = [p for p in pzt_pk if p<len(tf)]
                if pi: ax.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)

            # FC
            ax = fig2.add_subplot(gs2[2,:])
            ax.set(title="Fréquence cardiaque calculée [ref 1]",
                   ylabel="FC (bpm)", xlabel="Temps (s)"); ax.grid(True,alpha=0.3)
            if fc_ts_a and fc_v_a:
                ax.plot(fc_ts_a, fc_v_a, "o-", color="crimson", lw=1.5, ms=4, label="FC (bpm)")
            ax.axvline(x=CALIB, color="gray", ls="--", alpha=0.6, label="Fin calibration")
            if bl_fc: ax.axhline(y=bl_fc, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_fc:.0f}")
            if fc_v_a:
                fc_max = max(v for v in fc_v_a if v)
                for lv in lvs:
                    lts = lv.get("ts_start"); lnum = lv.get("level")
                    if lts:
                        ax.axvline(x=lts, color="#014F84", alpha=0.3, lw=1)
                        ax.text(lts, fc_max*0.97, f"N{lnum}", fontsize=7, color="#014F84", ha="center")
            ax.legend(fontsize=8, loc="upper left")

            # RR + touches
            ax = fig2.add_subplot(gs2[3,:])
            ax.set(title="Rythme respiratoire calculé + apnées + touches [ref 3]",
                   ylabel="RR (rpm)", xlabel="Temps (s)"); ax.grid(True,alpha=0.3)
            if rr_ts_a and rr_v_a:
                ax.plot(rr_ts_a, rr_v_a, "s-", color="darkorange", lw=1.5, ms=4, label="RR (rpm)")
            ax.axvline(x=CALIB, color="gray", ls="--", alpha=0.6)
            if bl_rr: ax.axhline(y=bl_rr, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_rr:.0f}")
            if key_ev:
                ax2 = ax.twinx()
                ok  = [(t,DIR_Y.get(d_,2)) for t,d_,c in key_ev if c]
                err = [(t,DIR_Y.get(d_,2)) for t,d_,c in key_ev if not c]
                if ok:  xs,ys=zip(*ok);  ax2.scatter(xs,ys,color="#1D9E75",s=80,marker="^",alpha=0.8,zorder=5)
                if err: xs,ys=zip(*err); ax2.scatter(xs,ys,color="#E24B4A",s=80,marker="x",alpha=0.8,zorder=5,linewidths=2)
                ax2.set_yticks([0,1,2,3]); ax2.set_yticklabels(["◄","▼","▲","►"],fontsize=9)
                ax2.set_ylim(-0.5,3.5); ax2.legend(["Correct","Erreur"],fontsize=8,loc="upper right")
            if rr_v_a:
                rr_max = max(v for v in rr_v_a if v)
                for lv in lvs:
                    lts = lv.get("ts_start"); lnum = lv.get("level")
                    if lts:
                        ax.axvline(x=lts, color="#014F84", alpha=0.3, lw=1)
                        ax.text(lts, rr_max*0.97, f"N{lnum}", fontsize=7, color="#014F84", ha="center")
            ax.legend(fontsize=8, loc="upper left")

            # I_cog
            ax = fig2.add_subplot(gs2[4,:])
            ax.set(title="Indice composite I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
                   ylabel="I_cog", xlabel="Temps (s)"); ax.grid(True,alpha=0.3)
            if ic_ts_a and ic_v_a:
                ax.plot(ic_ts_a, ic_v_a, color="tab:purple", lw=2.0, label="I_cog")
                ax.fill_between(ic_ts_a, ic_v_a, THRESHOLD,
                    where=[v>THRESHOLD for v in ic_v_a], color="red", alpha=0.25, label="Surcharge")
            ax.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.5)
            ax.axvline(x=CALIB, color="gray", ls="--", alpha=0.6, label="Fin calibration")
            ax.legend(fontsize=8, loc="upper left")

            plt.tight_layout()
            import os as _os
            _os.makedirs("sessions", exist_ok=True)
            fname = f"sessions/rapport_{time.strftime('%Y%m%d_%H%M%S')}.png"
            try:
                fig2.savefig(fname, dpi=130, bbox_inches="tight")
                print(f"[rapport] Sauvegardé : {fname}")
            except Exception as e:
                print(f"[rapport] Erreur : {e}")
            _pos(fig2, 700, 30)
            plt.show(block=False)
            plt.pause(0.1)
            plt.ion()

        # ── Boucle principale du thread ───────────────────────
        while True:
            try:
                cmd = self._cmd_q.get(timeout=0.05)
            except queue.Empty:
                try:
                    plt.pause(0.001)
                except Exception:
                    pass
                continue

            t = cmd.get("type")
            try:
                if   t == "open_calib":    open_calib()
                elif t == "calib_update":  update_calib(cmd)
                elif t == "close_calib":
                    if self._fig_calib:
                        try: plt.close(self._fig_calib)
                        except: pass
                        self._fig_calib = None; self._axes_calib = {}
                elif t == "open_game":     open_game()
                elif t == "game_update":   update_game(cmd)
                elif t == "close_game":
                    if self._fig_game:
                        try: plt.close(self._fig_game)
                        except: pass
                        self._fig_game = None; self._axes_game = {}
                elif t == "final_report":  show_final(cmd)
                elif t == "quit":          break
            except Exception as e:
                print(f"[graph_window] Erreur cmd={t} : {e}")

        try: plt.close("all")
        except: pass
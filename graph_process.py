"""
graph_process.py v4 — Fenêtres matplotlib dans un processus séparé.

Corrections :
  - I_cog : t_now calculé depuis ic_ts (pas all_ts) pour la fenêtre glissante
  - Rapport final : timestamps PPG/PZT bruts corrects (indices simples)
  - Fenêtre positionnée sans bloquer pygame (always on top désactivé)
  - Figure jeu 4 lignes : PPG | PZT | Touches | I_cog
"""

import multiprocessing as mp
import time
import numpy as np


def graph_worker(cmd_queue: mp.Queue, screen_width: int = 1920):
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec

    for key in ['s','q','z','Z','d','g','p','f','h','l']:
        for km in ['keymap.save','keymap.quit','keymap.zoom','keymap.xscale',
                   'keymap.yscale','keymap.grid','keymap.pan','keymap.fullscreen',
                   'keymap.home','keymap.back']:
            try:
                if key in matplotlib.rcParams.get(km, []):
                    matplotlib.rcParams[km].remove(key)
            except Exception:
                pass

    plt.ion()

    fig_calib  = None
    axes_calib = {}
    fig_game   = None
    axes_game  = {}

    DIR_Y = {"left": 0, "down": 1, "up": 2, "right": 3}

    def _pos_right(fig):
        """
        Positionne la figure dans le coin BAS-GAUCHE de l'écran.
        Taille réduite pour ne pas cacher les flèches (centre de l'écran).
        """
        try:
            mgr = fig.canvas.manager
            win = mgr.window
            sh  = win.winfo_screenheight()

            # Taille fixe : 700px de large, 550px de haut
            # → occupe le coin bas-gauche sans toucher le centre
            fw = 700
            fh = 550
            x  = 0          # collé au bord gauche
            y  = sh - fh - 40  # collé en bas (au-dessus de la barre des tâches)

            try:
                fig.set_size_inches(fw / fig.dpi, fh / fig.dpi)
            except Exception:
                pass

            win.wm_geometry(f"{fw}x{fh}+{x}+{y}")
            win.attributes("-topmost", False)
        except Exception:
            pass

    def _safe_draw(fig):
        try:
            fig.canvas.draw_idle()
            plt.pause(0.001)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────
    # CALIBRATION
    # ─────────────────────────────────────────────────────────
    def _open_calib():
        nonlocal fig_calib, axes_calib
        fig_calib = plt.figure(figsize=(13, 9))
        gs = gridspec.GridSpec(3, 2, figure=fig_calib,
                               height_ratios=[2, 2, 1.5], hspace=0.55, wspace=0.35)
        axes_calib = {
            "ppg_raw":  fig_calib.add_subplot(gs[0, 0]),
            "ppg_filt": fig_calib.add_subplot(gs[0, 1]),
            "pzt_raw":  fig_calib.add_subplot(gs[1, 0]),
            "pzt_filt": fig_calib.add_subplot(gs[1, 1]),
            "fc":       fig_calib.add_subplot(gs[2, 0]),
            "rr":       fig_calib.add_subplot(gs[2, 1]),
        }
        for k in axes_calib:
            axes_calib[k].grid(True, alpha=0.3)
        axes_calib["ppg_raw"].set(title="PPG brut",                   ylabel="Amplitude")
        axes_calib["ppg_filt"].set(title="PPG filtré + pics [ref 1]", ylabel="Amplitude")
        axes_calib["pzt_raw"].set(title="PZT brut",                   ylabel="Amplitude")
        axes_calib["pzt_filt"].set(title="PZT filtré + pics [ref 3]", ylabel="Amplitude")
        axes_calib["fc"].set(title="FC (bpm)",  ylabel="FC (bpm)",  xlabel="Temps (s)")
        axes_calib["rr"].set(title="RR (rpm)",  ylabel="RR (rpm)",  xlabel="Temps (s)")
        fig_calib.suptitle("ChunkyMemo — Calibration en cours", fontsize=12)
        plt.tight_layout()
        _pos_right(fig_calib)
        plt.pause(0.001)

    def _update_calib(d):
        if fig_calib is None:
            return
        ppg_raw = d.get("ppg_raw", [])
        ppg_filt = d.get("ppg_filt", [])
        ppg_peaks = d.get("ppg_peaks", [])
        pzt_raw = d.get("pzt_raw", [])
        pzt_filt = d.get("pzt_filt", [])
        pzt_peaks = d.get("pzt_peaks", [])
        fc_hist = d.get("fc_hist", [])
        rr_hist = d.get("rr_hist", [])
        fc_str = d.get("fc_str", "---")
        rr_str = d.get("rr_str", "---")
        rem = d.get("remaining", 0)
        WIN = 15.0

        ax = axes_calib["ppg_raw"]
        ax.cla(); ax.grid(True, alpha=0.3); ax.set(title="PPG brut", ylabel="Amplitude")
        if ppg_raw:
            ax.plot(ppg_raw, color="lightcoral", lw=0.7, alpha=0.8)

        ax = axes_calib["ppg_filt"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"PPG filtré + pics — FC={fc_str}", ylabel="Amplitude")
        if ppg_filt:
            fp = np.array(ppg_filt)
            ax.plot(fp, color="tab:red", lw=1.0)
            pi = [p for p in ppg_peaks if p < len(fp)]
            if pi: ax.plot(pi, fp[pi], "x", color="darkred", ms=8, mew=2)

        ax = axes_calib["pzt_raw"]
        ax.cla(); ax.grid(True, alpha=0.3); ax.set(title="PZT brut", ylabel="Amplitude")
        if pzt_raw:
            ax.plot(pzt_raw, color="moccasin", lw=0.7, alpha=0.8)

        ax = axes_calib["pzt_filt"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"PZT filtré + pics — RR={rr_str}", ylabel="Amplitude")
        if pzt_filt:
            fz = np.array(pzt_filt)
            ax.plot(fz, color="tab:orange", lw=1.0)
            pi = [p for p in pzt_peaks if p < len(fz)]
            if pi: ax.plot(pi, fz[pi], "x", color="darkorange", ms=8, mew=2)

        ax = axes_calib["fc"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"FC (bpm) — {fc_str}", ylabel="FC (bpm)", xlabel="Temps (s)")
        if fc_hist:
            t_now = fc_hist[-1][0]; t_min = max(0, t_now - WIN)
            pairs = [(t, v) for t, v in fc_hist if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, "o-", color="crimson", lw=1.5, ms=4)
                ax.set_xlim(t_min, t_now + 0.3)

        ax = axes_calib["rr"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"RR (rpm) — {rr_str}", ylabel="RR (rpm)", xlabel="Temps (s)")
        if rr_hist:
            t_now = rr_hist[-1][0]; t_min = max(0, t_now - WIN)
            pairs = [(t, v) for t, v in rr_hist if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, "s-", color="darkorange", lw=1.5, ms=4)
                ax.set_xlim(t_min, t_now + 0.3)

        fig_calib.suptitle(
            f"ChunkyMemo — Calibration {rem:.0f}s restantes — FC={fc_str}  RR={rr_str}  [RESTEZ IMMOBILE]",
            fontsize=11)
        _safe_draw(fig_calib)

    # ─────────────────────────────────────────────────────────
    # JEU — 4 lignes
    # ─────────────────────────────────────────────────────────
    def _open_game():
        nonlocal fig_game, axes_game
        fig_game = plt.figure(figsize=(13, 11))
        gs = gridspec.GridSpec(4, 2, figure=fig_game,
                               height_ratios=[2, 2, 1.5, 2], hspace=0.65, wspace=0.35)
        axes_game = {
            "ppg_raw":  fig_game.add_subplot(gs[0, 0]),
            "ppg_filt": fig_game.add_subplot(gs[0, 1]),
            "pzt_raw":  fig_game.add_subplot(gs[1, 0]),
            "pzt_filt": fig_game.add_subplot(gs[1, 1]),
            "keys":     fig_game.add_subplot(gs[2, :]),
            "icog":     fig_game.add_subplot(gs[3, :]),
        }
        for k in axes_game:
            axes_game[k].grid(True, alpha=0.3)
        axes_game["ppg_raw"].set(title="PPG brut",                    ylabel="Amplitude")
        axes_game["ppg_filt"].set(title="PPG filtré + pics [ref 1]",  ylabel="Amplitude")
        axes_game["pzt_raw"].set(title="PZT brut",                    ylabel="Amplitude")
        axes_game["pzt_filt"].set(title="PZT filtré + pics [ref 3]",  ylabel="Amplitude")

        ax_k = axes_game["keys"]
        ax_k.set(title="Touches saisies — ▲▼◄► (vert=correct  rouge=erreur)",
                 ylabel="Touche", xlabel="Temps (s)")
        ax_k.set_yticks([0, 1, 2, 3])
        ax_k.set_yticklabels(["◄ gauche", "▼ bas", "▲ haut", "► droite"], fontsize=9)
        ax_k.set_ylim(-0.5, 3.5)

        ax_ic = axes_game["icog"]
        ax_ic.axhline(y=1.5, color="red", ls="--", alpha=0.7, lw=1.5,
                      label="Seuil surcharge I_cog > 1.5")
        ax_ic.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
        ax_ic.set(title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
                  ylabel="I_cog", xlabel="Temps (s)")
        ax_ic.legend(fontsize=9, loc="upper left")

        fig_game.suptitle("ChunkyMemo — Jeu en cours", fontsize=12)
        plt.tight_layout()
        _pos_right(fig_game)
        plt.pause(0.001)

    def _update_game(d):
        if fig_game is None:
            return

        ppg_raw   = d.get("ppg_raw", [])
        ppg_filt  = d.get("ppg_filt", [])
        ppg_peaks = d.get("ppg_peaks", [])
        pzt_raw   = d.get("pzt_raw", [])
        pzt_filt  = d.get("pzt_filt", [])
        pzt_peaks = d.get("pzt_peaks", [])
        all_ts    = d.get("all_ts", [])
        fc_v      = d.get("fc_v", [])
        rr_v      = d.get("rr_v", [])
        ic_ts     = d.get("ic_ts", [])    # timestamps propres I_cog
        ic_v      = d.get("ic_v", [])
        key_events= d.get("key_events", [])
        fc_str    = d.get("fc_str", "---")
        rr_str    = d.get("rr_str", "---")
        ic_str    = d.get("ic_str", "---")
        overload  = d.get("overload", False)
        apnea     = d.get("apnea", False)
        THRESHOLD = 1.5
        WIN       = 60.0   # 60s visibles pour voir I_cog évoluer

        # t_now = dernier timestamp disponible (physio ou I_cog)
        t_now_phys = all_ts[-1] if all_ts else 0
        t_now_ic   = ic_ts[-1]  if ic_ts  else 0
        t_now      = max(t_now_phys, t_now_ic)
        t_min      = max(0, t_now - WIN)

        # ── PPG brut ──────────────────────────────────────────
        ax = axes_game["ppg_raw"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title="PPG brut", ylabel="Amplitude")
        if ppg_raw and all_ts:
            n = min(len(ppg_raw), len(all_ts))
            pairs = [(t, v) for t, v in zip(all_ts[-n:], ppg_raw[-n:]) if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, color="lightcoral", lw=0.7, alpha=0.8)
                ax.set_xlim(t_min, t_now + 0.3)
                ax.set_ylim(min(vv)-5, max(vv)+5)

        # ── PPG filtré + pics ─────────────────────────────────
        ax = axes_game["ppg_filt"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"PPG filtré + pics (FC={fc_str}) [ref 1]", ylabel="Amplitude")
        if ppg_filt and all_ts:
            fp = np.array(ppg_filt); n = len(fp)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, t_now_phys, n)
            ax.plot(tf, fp, color="tab:red", lw=1.0)
            ax.set_xlim(max(0, t_now_phys - WIN), t_now_phys + 0.3)
            if not (fp.max() == fp.min()):
                ax.set_ylim(fp.min()-10, fp.max()+10)
            pi = [p for p in ppg_peaks if p < n]
            if pi: ax.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)

        # ── PZT brut ──────────────────────────────────────────
        ax = axes_game["pzt_raw"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title="PZT brut", ylabel="Amplitude")
        if pzt_raw and all_ts:
            n = min(len(pzt_raw), len(all_ts))
            pairs = [(t, v) for t, v in zip(all_ts[-n:], pzt_raw[-n:]) if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, color="moccasin", lw=0.7, alpha=0.8)
                ax.set_xlim(t_min, t_now + 0.3)
                ax.set_ylim(min(vv)-5, max(vv)+5)

        # ── PZT filtré + pics ─────────────────────────────────
        ax = axes_game["pzt_filt"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.set(title=f"PZT filtré + pics (RR={rr_str}) [ref 3]", ylabel="Amplitude")
        if pzt_filt and all_ts:
            fz = np.array(pzt_filt); n = len(fz)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, t_now_phys, n)
            ax.plot(tf, fz, color="tab:orange", lw=1.0)
            ax.set_xlim(max(0, t_now_phys - WIN), t_now_phys + 0.3)
            if not (fz.max() == fz.min()):
                ax.set_ylim(fz.min()-10, fz.max()+10)
            pi = [p for p in pzt_peaks if p < n]
            if pi: ax.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)

        # ── Touches clavier ───────────────────────────────────
        ax = axes_game["keys"]
        ax.cla(); ax.grid(True, alpha=0.2)
        ax.set(title="Touches saisies — ▲▼◄► (vert=correct  rouge=erreur)",
               ylabel="Touche", xlabel="Temps (s)")
        ax.set_yticks([0, 1, 2, 3])
        ax.set_yticklabels(["◄ gauche", "▼ bas", "▲ haut", "► droite"], fontsize=9)
        ax.set_ylim(-0.5, 3.5)
        ax.set_xlim(t_min, t_now + 0.3)
        if key_events:
            shown = [(ts_k, d_, c) for ts_k, d_, c in key_events if ts_k >= t_min]
            if shown:
                xs = [e[0] for e in shown]
                ys = [DIR_Y.get(e[1], 2) for e in shown]
                cs = ["#1D9E75" if e[2] else "#E24B4A" for e in shown]
                ms = ["^" if e[2] else "x" for e in shown]
                for x, y, c, m in zip(xs, ys, cs, ms):
                    ax.scatter(x, y, color=c, s=150, zorder=5, marker=m, linewidths=2)

        # ── I_cog ─────────────────────────────────────────────
        ax = axes_game["icog"]
        ax.cla(); ax.grid(True, alpha=0.3)
        ax.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.5,
                   label=f"Seuil surcharge > {THRESHOLD}")
        ax.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
        ax.set(title="I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
               ylabel="I_cog", xlabel="Temps (s)")

        if ic_ts and ic_v:
            # Utilise ic_ts comme axe X (pas all_ts)
            t_now_ic = ic_ts[-1]
            t_min_ic = max(0, t_now_ic - WIN)
            pairs_ic = [(t, v) for t, v in zip(ic_ts, ic_v) if t >= t_min_ic]
            if pairs_ic:
                tt, vv = zip(*pairs_ic)
                ax.plot(tt, vv, color="tab:purple", lw=2.0, label="I_cog")
                ax.fill_between(tt, vv, THRESHOLD,
                    where=[v > THRESHOLD for v in vv],
                    color="red", alpha=0.25)
                ax.set_xlim(t_min_ic, t_now_ic + 0.3)
                all_v = list(vv) + [THRESHOLD, 0]
                mg = max(0.3, (max(all_v) - min(all_v)) * 0.15)
                ax.set_ylim(min(all_v) - mg, max(all_v) + mg)
            else:
                # Pas encore de données mais on sait que ça existe — afficher fenêtre vide correcte
                ax.set_xlim(max(0, t_now - WIN), t_now + 0.3)
        else:
            ax.set_xlim(max(0, t_now - WIN), t_now + 0.3)
            ax.set_ylim(-0.5, 2.5)

        ax.legend(fontsize=9, loc="upper left")

        ov_s = "  *** SURCHARGE ***" if overload else ""
        ap_s = " | APNÉE" if apnea else ""
        ic_disp = f"I_cog={ic_str}" if ic_str != "---" else "I_cog (en calcul...)"
        fig_game.suptitle(
            f"ChunkyMemo — FC={fc_str}  RR={rr_str}  {ic_disp}{ov_s}{ap_s}",
            fontsize=11)
        _safe_draw(fig_game)

    # ─────────────────────────────────────────────────────────
    # RAPPORT FINAL
    # ─────────────────────────────────────────────────────────
    def _show_final(d):
        plt.ioff()
        levels    = d.get("levels", [])
        lvs       = [lv for lv in levels if lv.get("level") is not None]
        all_ts    = d.get("all_ts", [])
        all_ppg   = d.get("all_ppg", [])
        all_pzt   = d.get("all_pzt", [])
        fc_ts_a   = d.get("fc_ts", [])
        fc_v_a    = d.get("fc_v", [])
        rr_ts_a   = d.get("rr_ts", [])
        rr_v_a    = d.get("rr_v", [])
        ic_ts_a   = d.get("ic_ts", [])
        ic_v_a    = d.get("ic_v", [])
        ppg_filt  = d.get("ppg_filt", [])
        ppg_peaks = d.get("ppg_peaks", [])
        pzt_filt  = d.get("pzt_filt", [])
        pzt_peaks = d.get("pzt_peaks", [])
        bl_fc     = d.get("bl_fc")
        bl_rr     = d.get("bl_rr")
        fc_final  = d.get("fc_final")
        rr_final  = d.get("rr_final")
        ic_final  = d.get("ic_final")
        mode      = d.get("mode", "NORMAL")
        key_ev    = d.get("key_events", [])
        CALIB_SEC = d.get("calib_sec", 20.0)
        THRESHOLD = 1.5

        max_lv = max((lv["level"] for lv in lvs), default=0)
        n_lvs  = len(lvs)

        fig2 = plt.figure(figsize=(15, 14))
        gs2  = gridspec.GridSpec(5, 2, figure=fig2,
                                 height_ratios=[2, 2, 1.5, 1.5, 1.5],
                                 hspace=0.65, wspace=0.35)

        fc_s = f"FC={fc_final:.0f}bpm" if fc_final else "FC=---"
        rr_s = f"RR={rr_final:.0f}rpm" if rr_final else "RR=---"
        ic_s = f"I_cog={ic_final:.2f}" if ic_final is not None else "I_cog=---"

        # ── PPG brut (axe = secondes depuis début) ────────────
        ax1 = fig2.add_subplot(gs2[0, 0])
        ax1.set(title="PPG brut — session complète", ylabel="Amplitude"); ax1.grid(True, alpha=0.3)
        if all_ts and all_ppg:
            ax1.plot(all_ts, all_ppg, color="lightcoral", lw=0.5, alpha=0.8)
            ax1.set_xlabel("Temps (s)")

        # ── PPG filtré (axe = secondes aligné sur la fin) ─────
        ax2 = fig2.add_subplot(gs2[0, 1])
        ax2.set(title=f"PPG filtré + pics ({fc_s})", ylabel="Amplitude"); ax2.grid(True, alpha=0.3)
        if ppg_filt and all_ts:
            fp = np.array(ppg_filt)
            n  = len(fp)
            # Aligner sur les dernières n secondes de all_ts
            if n <= len(all_ts):
                tf = np.array(all_ts[-n:])
            else:
                # Buffer plus long que all_ts → linspace depuis début
                tf = np.linspace(all_ts[0] if all_ts else 0, all_ts[-1] if all_ts else n, n)
            ax2.plot(tf, fp, color="tab:red", lw=0.8)
            ax2.set_xlabel("Temps (s)")
            if len(ppg_peaks):
                pi = [p for p in ppg_peaks if p < len(tf)]
                if pi: ax2.plot(tf[pi], fp[pi], "x", color="darkred", ms=8, mew=2)

        # ── PZT brut ──────────────────────────────────────────
        ax3 = fig2.add_subplot(gs2[1, 0])
        ax3.set(title="PZT brut — session complète", ylabel="Amplitude"); ax3.grid(True, alpha=0.3)
        if all_ts and all_pzt:
            ax3.plot(all_ts, all_pzt, color="moccasin", lw=0.5, alpha=0.8)
            ax3.set_xlabel("Temps (s)")

        # ── PZT filtré ────────────────────────────────────────
        ax4 = fig2.add_subplot(gs2[1, 1])
        ax4.set(title=f"PZT filtré + pics ({rr_s})", ylabel="Amplitude"); ax4.grid(True, alpha=0.3)
        if pzt_filt and all_ts:
            fz = np.array(pzt_filt)
            n  = len(fz)
            if n <= len(all_ts):
                tf = np.array(all_ts[-n:])
            else:
                tf = np.linspace(all_ts[0] if all_ts else 0, all_ts[-1] if all_ts else n, n)
            ax4.plot(tf, fz, color="tab:orange", lw=0.8)
            ax4.set_xlabel("Temps (s)")
            if len(pzt_peaks):
                pi = [p for p in pzt_peaks if p < len(tf)]
                if pi: ax4.plot(tf[pi], fz[pi], "x", color="darkorange", ms=8, mew=2)

        # ── FC calculée + niveaux ─────────────────────────────
        ax5 = fig2.add_subplot(gs2[2, :])
        ax5.set(title="Fréquence cardiaque calculée [ref 1]",
                ylabel="FC (bpm)", xlabel="Temps (s)"); ax5.grid(True, alpha=0.3)
        if fc_ts_a and fc_v_a:
            ax5.plot(fc_ts_a, fc_v_a, "o-", color="crimson", lw=1.5, ms=4, label="FC (bpm)")
        ax5.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calibration")
        if bl_fc:
            ax5.axhline(y=bl_fc, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_fc:.0f}")
        # Annotations niveaux
        if fc_v_a:
            fc_max = max(v for v in fc_v_a if v) if fc_v_a else 100
            for lv in lvs:
                lv_ts = lv.get("ts_start")
                lv_num = lv.get("level")
                if lv_ts is not None:
                    ax5.axvline(x=lv_ts, color="#014F84", alpha=0.3, lw=1)
                    ax5.text(lv_ts, fc_max * 0.98, f"N{lv_num}",
                             fontsize=7, color="#014F84", ha="center")
        ax5.legend(fontsize=8, loc="upper left")

        # ── RR calculé + touches ──────────────────────────────
        ax6 = fig2.add_subplot(gs2[3, :])
        ax6.set(title="Rythme respiratoire calculé + apnées + touches [ref 3]",
                ylabel="RR (rpm)", xlabel="Temps (s)"); ax6.grid(True, alpha=0.3)
        if rr_ts_a and rr_v_a:
            ax6.plot(rr_ts_a, rr_v_a, "s-", color="darkorange", lw=1.5, ms=4, label="RR (rpm)")
        ax6.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calibration")
        if bl_rr:
            ax6.axhline(y=bl_rr, color="gray", ls=":", lw=1.5, label=f"Baseline {bl_rr:.0f}")
        # Touches en axe secondaire
        if key_ev:
            ax6b = ax6.twinx()
            ok_ev  = [(ts_k, DIR_Y.get(dir_, 2)) for ts_k, dir_, c in key_ev if c]
            err_ev = [(ts_k, DIR_Y.get(dir_, 2)) for ts_k, dir_, c in key_ev if not c]
            if ok_ev:
                xs, ys = zip(*ok_ev)
                ax6b.scatter(xs, ys, color="#1D9E75", s=80, marker="^", alpha=0.8, zorder=5, label="Correct")
            if err_ev:
                xs, ys = zip(*err_ev)
                ax6b.scatter(xs, ys, color="#E24B4A", s=80, marker="x", alpha=0.8, zorder=5, linewidths=2, label="Erreur")
            ax6b.set_yticks([0,1,2,3])
            ax6b.set_yticklabels(["◄","▼","▲","►"], fontsize=10)
            ax6b.set_ylim(-0.5, 3.5)
            ax6b.legend(fontsize=8, loc="upper right")
        # Annotations niveaux
        if rr_v_a:
            rr_max = max(v for v in rr_v_a if v) if rr_v_a else 30
            for lv in lvs:
                lv_ts = lv.get("ts_start")
                lv_num = lv.get("level")
                if lv_ts is not None:
                    ax6.axvline(x=lv_ts, color="#014F84", alpha=0.3, lw=1)
                    ax6.text(lv_ts, rr_max * 0.98, f"N{lv_num}",
                             fontsize=7, color="#014F84", ha="center")
        ax6.legend(fontsize=8, loc="upper left")

        # ── I_cog composite ───────────────────────────────────
        ax7 = fig2.add_subplot(gs2[4, :])
        ax7.set(title="Indice composite I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4",
                ylabel="I_cog", xlabel="Temps (s)"); ax7.grid(True, alpha=0.3)
        if ic_ts_a and ic_v_a:
            ax7.plot(ic_ts_a, ic_v_a, color="tab:purple", lw=2.0, label="I_cog")
            ax7.fill_between(ic_ts_a, ic_v_a, THRESHOLD,
                where=[v > THRESHOLD for v in ic_v_a],
                color="red", alpha=0.25, label="Surcharge")
        ax7.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.5,
                    label=f"Seuil {THRESHOLD}")
        ax7.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=1)
        ax7.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calibration")
        ax7.legend(fontsize=8, loc="upper left")

        fig2.suptitle(
            f"ChunkyMemo — Session complète  |  Mode : {mode}  |  "
            f"Niveaux joués : {n_lvs}  |  Niveau max : {max_lv}  |  "
            f"{fc_s}  {rr_s}  {ic_s}",
            fontsize=12, fontweight="bold")
        plt.tight_layout()

        import os as _os
        _os.makedirs("sessions", exist_ok=True)
        fname = f"sessions/rapport_{time.strftime('%Y%m%d_%H%M%S')}.png"
        try:
            fig2.savefig(fname, dpi=130, bbox_inches="tight")
            print(f"[rapport] Sauvegardé : {fname}")
        except Exception as e:
            print(f"[rapport] Erreur sauvegarde : {e}")

        _pos_right(fig2)
        # Non-bloquant → pygame reste accessible
        plt.show(block=False)
        plt.pause(0.1)
        plt.ion()

    # ─────────────────────────────────────────────────────────
    # BOUCLE PRINCIPALE
    # ─────────────────────────────────────────────────────────
    while True:
        try:
            cmd = cmd_queue.get(timeout=0.05)
        except Exception:
            try: plt.pause(0.001)
            except Exception: pass
            continue

        t = cmd.get("type")
        if   t == "open_calib":   _open_calib()
        elif t == "calib_update": _update_calib(cmd)
        elif t == "close_calib":
            if fig_calib:
                try: plt.close(fig_calib)
                except: pass
                fig_calib = None; axes_calib = {}
        elif t == "open_game":    _open_game()
        elif t == "game_update":  _update_game(cmd)
        elif t == "close_game":
            if fig_game:
                try: plt.close(fig_game)
                except: pass
                fig_game = None; axes_game = {}
        elif t == "final_report": _show_final(cmd)
        elif t == "quit":         break

    try: plt.close("all")
    except Exception: pass
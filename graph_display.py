"""
graph_display.py — Graphes matplotlib rendus dans pygame via surface en mémoire.

Principe : matplotlib.use("Agg") → pas de fenêtre Tk, pas de GIL conflict.
Les figures sont rendues en PNG bytes puis converties en pygame.Surface.
Affichage dans une petite fenêtre pygame séparée (SDL sub-window) ou
directement dans le coin de l'écran principal.

Usage :
    gd = GraphDisplay(screen, sig_thread)
    # Dans la boucle pygame :
    gd.tick()          # re-render si données nouvelles
    gd.draw_overlay()  # dessine dans le coin droit de l'écran
"""

import io
import threading
import time
import numpy as np

# Matplotlib en mode non-interactif (pas de Tk, pas de SDL)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

import pygame


DIR_Y     = {"left": 0, "down": 1, "up": 2, "right": 3}
THRESHOLD = 1.5


class GraphDisplay:
    """
    Rendu matplotlib → pygame.Surface dans un thread background.
    Le thread principal pygame appelle juste draw_overlay().
    """

    # Taille de la surface overlay dans l'écran pygame
    OVERLAY_W = 700
    OVERLAY_H = 560

    def __init__(self, screen: pygame.Surface, sig_thread):
        self.screen      = screen
        self.sig         = sig_thread
        self._surface    = None          # pygame.Surface courante
        self._lock       = threading.Lock()
        self._dirty      = False         # True = nouveau rendu disponible
        self._phase      = "none"        # "calibration" | "game" | "final"
        self._final_data = None
        self._last_render= 0
        self.RENDER_SEC  = 0.8           # re-render toutes les 0.8s

        # Démarrer le thread de rendu
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

        # Police pygame pour le titre overlay
        self._font = pygame.font.SysFont("Arial", 11)

    def set_phase(self, phase: str):
        self._phase = phase

    def set_final_data(self, data: dict):
        self._final_data = data
        self._phase = "final"

    def tick(self):
        """Appelé chaque frame pygame — ne fait rien de lourd."""
        pass   # Le thread fait le travail

    def draw_overlay(self):
        """Dessine la surface matplotlib dans le coin droit de l'écran pygame."""
        with self._lock:
            surf = self._surface
        if surf is None:
            return
        sw, sh = self.screen.get_size()
        x = sw - self.OVERLAY_W - 10
        y = 10
        # Fond semi-transparent
        bg = pygame.Surface((self.OVERLAY_W, self.OVERLAY_H), pygame.SRCALPHA)
        bg.fill((255, 255, 255, 230))
        self.screen.blit(bg, (x, y))
        self.screen.blit(surf, (x, y))
        # Bordure
        pygame.draw.rect(self.screen, (150, 150, 150), (x, y, self.OVERLAY_W, self.OVERLAY_H), 1)

    def stop(self):
        self._stop.set()

    # ── Thread de rendu ───────────────────────────────────────

    def _render_loop(self):
        while not self._stop.is_set():
            now = time.time()
            if now - self._last_render >= self.RENDER_SEC and self._phase != "none":
                self._last_render = now
                try:
                    if self._phase == "calibration":
                        surf = self._render_calibration()
                    elif self._phase == "game":
                        surf = self._render_game()
                    elif self._phase == "final" and self._final_data:
                        surf = self._render_final(self._final_data)
                    else:
                        surf = None
                    if surf:
                        with self._lock:
                            self._surface = surf
                except Exception as e:
                    print(f"[graph] Erreur rendu : {e}")
            time.sleep(0.05)

    def _fig_to_surface(self, fig) -> pygame.Surface:
        """Convertit une figure matplotlib en pygame.Surface."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=85, bbox_inches="tight",
                    facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return pygame.image.load(buf, "fig.png").convert()

    # ── Rendu calibration ─────────────────────────────────────

    def _render_calibration(self) -> pygame.Surface:
        ppg = self.sig.ppg
        pzt = self.sig.pzt
        ts_rel = time.time() - self.sig._t0
        rem    = max(0, self.sig.CALIB_SEC - ts_rel)

        fig, axes = plt.subplots(2, 2, figsize=(8, 5.5))
        fig.suptitle(
            f"CALIBRATION {rem:.0f}s restantes — "
            f"FC={'%.0f' % ppg.fc_bpm if ppg.fc_bpm else '---'}bpm  "
            f"RR={'%.0f' % pzt.rr_rpm if pzt.rr_rpm else '---'}rpm  "
            f"[RESTEZ IMMOBILE]",
            fontsize=9, color="#014F84", fontweight="bold"
        )

        _plot_raw(axes[0][0], list(ppg._buf), "PPG brut", "lightcoral")
        _plot_filt_peaks(axes[0][1], ppg.get_filtered_signal(), ppg.last_peaks,
                         f"PPG filtré FC={'%.0f'%ppg.fc_bpm if ppg.fc_bpm else '---'}bpm",
                         "tab:red", "darkred")
        _plot_raw(axes[1][0], list(pzt._buf), "PZT brut", "moccasin")
        _plot_filt_peaks(axes[1][1], pzt.get_filtered_signal(), pzt.last_peaks,
                         f"PZT filtré RR={'%.0f'%pzt.rr_rpm if pzt.rr_rpm else '---'}rpm",
                         "tab:orange", "darkorange")

        plt.tight_layout()
        return self._fig_to_surface(fig)

    # ── Rendu jeu ─────────────────────────────────────────────

    def _render_game(self) -> pygame.Surface:
        ppg = self.sig.ppg
        pzt = self.sig.pzt
        snap = self.sig.phys.snapshot()
        WIN  = 25.0

        with self.sig._hlock:
            all_ts  = list(self.sig._all_ts)
            fc_ts   = list(self.sig._fc_ts); fc_v  = list(self.sig._fc_v)
            rr_ts   = list(self.sig._rr_ts); rr_v  = list(self.sig._rr_v)
            ic_ts   = list(self.sig._ic_ts); ic_v  = list(self.sig._ic_v)
            key_ev  = list(self.sig._key_ev)

        bl  = self.sig.cog._baseline
        t_now = max(all_ts[-1] if all_ts else 0,
                    ic_ts[-1]  if ic_ts  else 0)
        t_min = max(0, t_now - WIN)

        fig = plt.figure(figsize=(8, 7.5))
        gs  = gridspec.GridSpec(4, 2, figure=fig,
                                height_ratios=[2, 2, 1.5, 2],
                                hspace=0.70, wspace=0.35)

        fc_s = f"FC={'%.0f'%snap['fc_bpm'] if snap['fc_bpm'] else '---'}bpm"
        rr_s = f"RR={'%.0f'%snap['rr_rpm'] if snap['rr_rpm'] else '---'}rpm"
        ic_s = f"I_cog={'%.2f'%snap['i_cog'] if snap['i_cog'] is not None else 'calcul...'}"
        ov_s = "  ⚠SURCHARGE" if snap["overload"] else ""
        fig.suptitle(f"JEU — {fc_s}  {rr_s}  {ic_s}{ov_s}",
                     fontsize=9, color="#014F84", fontweight="bold")

        # PPG brut
        ax = fig.add_subplot(gs[0, 0])
        if ppg._buf and all_ts:
            n = min(len(ppg._buf), len(all_ts))
            pairs = [(t,v) for t,v in zip(all_ts[-n:], list(ppg._buf)[-n:]) if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, color="lightcoral", lw=0.7)
                ax.set_xlim(t_min, t_now+0.3); ax.set_ylim(min(vv)-5, max(vv)+5)
        ax.set_title("PPG brut", fontsize=8); ax.set_ylabel("Amplitude", fontsize=7); ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

        # PPG filtré + pics
        ax = fig.add_subplot(gs[0, 1])
        fp = ppg.get_filtered_signal()
        if len(fp) > 0 and all_ts:
            n = len(fp)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, all_ts[-1] if all_ts else t0, n)
            ax.plot(tf, fp, color="tab:red", lw=0.9)
            ax.set_xlim(max(0, all_ts[-1]-WIN if all_ts else 0), (all_ts[-1] if all_ts else 0)+0.3)
            if not (fp.max() == fp.min()):
                ax.set_ylim(fp.min()-10, fp.max()+10)
            pi = [p for p in ppg.last_peaks if p < n]
            if pi: ax.plot(tf[pi], fp[pi], "x", color="darkred", ms=6, mew=1.5)
        ax.set_title(f"PPG filtré ({fc_s})", fontsize=8); ax.set_ylabel("Amplitude", fontsize=7); ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

        # PZT brut
        ax = fig.add_subplot(gs[1, 0])
        if pzt._buf and all_ts:
            n = min(len(pzt._buf), len(all_ts))
            pairs = [(t,v) for t,v in zip(all_ts[-n:], list(pzt._buf)[-n:]) if t >= t_min]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, color="moccasin", lw=0.7)
                ax.set_xlim(t_min, t_now+0.3); ax.set_ylim(min(vv)-5, max(vv)+5)
        ax.set_title("PZT brut", fontsize=8); ax.set_ylabel("Amplitude", fontsize=7); ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

        # PZT filtré + pics
        ax = fig.add_subplot(gs[1, 1])
        fz = pzt.get_filtered_signal()
        if len(fz) > 0 and all_ts:
            n = len(fz)
            t0 = all_ts[-n] if n <= len(all_ts) else all_ts[0]
            tf = np.linspace(t0, all_ts[-1] if all_ts else t0, n)
            ax.plot(tf, fz, color="tab:orange", lw=0.9)
            ax.set_xlim(max(0, all_ts[-1]-WIN if all_ts else 0), (all_ts[-1] if all_ts else 0)+0.3)
            if not (fz.max() == fz.min()):
                ax.set_ylim(fz.min()-10, fz.max()+10)
            pi = [p for p in pzt.last_peaks if p < n]
            if pi: ax.plot(tf[pi], fz[pi], "x", color="darkorange", ms=6, mew=1.5)
        ax.set_title(f"PZT filtré ({rr_s})", fontsize=8); ax.set_ylabel("Amplitude", fontsize=7); ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=7)

        # Touches clavier
        ax = fig.add_subplot(gs[2, :])
        ax.set_title("Touches — ▲▼◄► (vert=correct, rouge=erreur)", fontsize=8)
        ax.set_yticks([0,1,2,3]); ax.set_yticklabels(["◄","▼","▲","►"], fontsize=8)
        ax.set_ylim(-0.5, 3.5); ax.set_xlim(t_min, t_now+0.3); ax.grid(True, alpha=0.2)
        ax.tick_params(labelsize=7)
        if key_ev:
            for (ts_k, d_, c) in key_ev:
                if ts_k >= t_min:
                    ax.scatter(ts_k, DIR_Y.get(d_, 2),
                               color="#1D9E75" if c else "#E24B4A",
                               s=120, marker="^" if c else "x",
                               zorder=5, linewidths=2)

        # I_cog
        ax = fig.add_subplot(gs[3, :])
        ax.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.2,
                   label=f"Seuil > {THRESHOLD}")
        ax.axhline(y=0, color="gray", ls=":", alpha=0.4, lw=0.8)
        ax.set_title("I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4", fontsize=8)
        ax.set_ylabel("I_cog", fontsize=7); ax.set_xlabel("Temps (s)", fontsize=7)
        ax.tick_params(labelsize=7); ax.grid(True, alpha=0.3)
        if ic_ts and ic_v:
            t_now_ic = ic_ts[-1]; t_min_ic = max(0, t_now_ic - WIN)
            pairs = [(t,v) for t,v in zip(ic_ts, ic_v) if t >= t_min_ic]
            if pairs:
                tt, vv = zip(*pairs)
                ax.plot(tt, vv, color="tab:purple", lw=1.8, label="I_cog")
                ax.fill_between(tt, vv, THRESHOLD,
                    where=[v > THRESHOLD for v in vv],
                    color="red", alpha=0.25)
                ax.set_xlim(t_min_ic, t_now_ic+0.3)
                all_v = list(vv) + [THRESHOLD, 0]
                mg = max(0.3, (max(all_v)-min(all_v))*0.15)
                ax.set_ylim(min(all_v)-mg, max(all_v)+mg)
            else:
                ax.set_xlim(t_min, t_now+0.3); ax.set_ylim(-0.5, 2.5)
        else:
            ax.set_xlim(t_min, t_now+0.3); ax.set_ylim(-0.5, 2.5)
            ax.text(0.5, 0.5, "I_cog en calcul\n(baselines pas encore prêtes)",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color="gray")
        ax.legend(fontsize=8, loc="upper left")

        plt.tight_layout()
        return self._fig_to_surface(fig)

    # ── Rendu rapport final ───────────────────────────────────

    def _render_final(self, d: dict) -> pygame.Surface:
        levels    = d.get("levels", [])
        lvs       = [lv for lv in levels if lv.get("level") is not None]
        all_ts    = d.get("all_ts", [])
        all_ppg   = d.get("all_ppg", [])
        all_pzt   = d.get("all_pzt", [])
        fc_ts_a   = d.get("fc_ts", []); fc_v_a = d.get("fc_v", [])
        rr_ts_a   = d.get("rr_ts", []); rr_v_a = d.get("rr_v", [])
        ic_ts_a   = d.get("ic_ts", []); ic_v_a = d.get("ic_v", [])
        ppg_filt  = d.get("ppg_filt", []); ppg_peaks = d.get("ppg_peaks", [])
        pzt_filt  = d.get("pzt_filt", []); pzt_peaks = d.get("pzt_peaks", [])
        bl_fc     = d.get("bl_fc"); bl_rr = d.get("bl_rr")
        fc_final  = d.get("fc_final"); rr_final = d.get("rr_final"); ic_final = d.get("ic_final")
        mode      = d.get("mode", "NORMAL"); key_ev = d.get("key_events", [])
        CALIB_SEC = d.get("calib_sec", 20.0)
        max_lv    = max((lv["level"] for lv in lvs), default=0)

        fig = plt.figure(figsize=(10, 12))
        gs  = gridspec.GridSpec(5, 2, figure=fig,
                                height_ratios=[2,2,1.5,1.5,1.5], hspace=0.70, wspace=0.35)

        fc_s = f"FC={'%.0f'%fc_final if fc_final else '---'}bpm"
        rr_s = f"RR={'%.0f'%rr_final if rr_final else '---'}rpm"
        ic_s = f"I_cog={'%.2f'%ic_final if ic_final is not None else '---'}"
        fig.suptitle(
            f"RAPPORT FINAL — Mode:{mode}  Niveaux:{len(lvs)}  Max:N{max_lv}\n"
            f"{fc_s}  {rr_s}  {ic_s}",
            fontsize=10, fontweight="bold", color="#014F84"
        )

        # PPG brut
        ax = fig.add_subplot(gs[0,0])
        ax.set_title("PPG brut — session complète", fontsize=8); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if all_ts and all_ppg:
            ax.plot(all_ts, all_ppg, color="lightcoral", lw=0.4, alpha=0.8)

        # PPG filtré
        ax = fig.add_subplot(gs[0,1])
        ax.set_title(f"PPG filtré + pics ({fc_s})", fontsize=8); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if ppg_filt and all_ts:
            fp = np.array(ppg_filt); n = len(fp)
            tf = np.array(all_ts[-n:]) if n <= len(all_ts) else np.linspace(all_ts[0], all_ts[-1], n)
            ax.plot(tf, fp, color="tab:red", lw=0.7)
            pi = [p for p in ppg_peaks if p < len(tf)]
            if pi: ax.plot(tf[pi], fp[pi], "x", color="darkred", ms=6, mew=1.5)

        # PZT brut
        ax = fig.add_subplot(gs[1,0])
        ax.set_title("PZT brut — session complète", fontsize=8); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if all_ts and all_pzt:
            ax.plot(all_ts, all_pzt, color="moccasin", lw=0.4, alpha=0.8)

        # PZT filtré
        ax = fig.add_subplot(gs[1,1])
        ax.set_title(f"PZT filtré + pics ({rr_s})", fontsize=8); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if pzt_filt and all_ts:
            fz = np.array(pzt_filt); n = len(fz)
            tf = np.array(all_ts[-n:]) if n <= len(all_ts) else np.linspace(all_ts[0], all_ts[-1], n)
            ax.plot(tf, fz, color="tab:orange", lw=0.7)
            pi = [p for p in pzt_peaks if p < len(tf)]
            if pi: ax.plot(tf[pi], fz[pi], "x", color="darkorange", ms=6, mew=1.5)

        # FC
        ax = fig.add_subplot(gs[2,:])
        ax.set_title("Fréquence cardiaque", fontsize=8); ax.set_ylabel("FC (bpm)", fontsize=7); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if fc_ts_a and fc_v_a:
            ax.plot(fc_ts_a, fc_v_a, "o-", color="crimson", lw=1.2, ms=3, label="FC")
        ax.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calib.")
        if bl_fc: ax.axhline(y=bl_fc, color="gray", ls=":", lw=1.2, label=f"Base {bl_fc:.0f}")
        for lv in lvs:
            lv_ts = lv.get("ts_start"); lv_num = lv.get("level")
            if lv_ts and fc_v_a:
                ax.axvline(x=lv_ts, color="#014F84", alpha=0.3, lw=1)
                ax.text(lv_ts, max(v for v in fc_v_a if v)*0.97, f"N{lv_num}",
                        fontsize=6, color="#014F84", ha="center")
        ax.legend(fontsize=7, loc="upper left")

        # RR + touches
        ax = fig.add_subplot(gs[3,:])
        ax.set_title("Rythme respiratoire + touches", fontsize=8); ax.set_ylabel("RR (rpm)", fontsize=7); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if rr_ts_a and rr_v_a:
            ax.plot(rr_ts_a, rr_v_a, "s-", color="darkorange", lw=1.2, ms=3, label="RR")
        ax.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6)
        if bl_rr: ax.axhline(y=bl_rr, color="gray", ls=":", lw=1.2, label=f"Base {bl_rr:.0f}")
        if key_ev:
            ax2 = ax.twinx()
            ok  = [(t, DIR_Y.get(d_,2)) for t,d_,c in key_ev if c]
            err = [(t, DIR_Y.get(d_,2)) for t,d_,c in key_ev if not c]
            if ok:  xs,ys=zip(*ok);  ax2.scatter(xs,ys,color="#1D9E75",s=60,marker="^",alpha=0.8)
            if err: xs,ys=zip(*err); ax2.scatter(xs,ys,color="#E24B4A",s=60,marker="x",alpha=0.8,linewidths=2)
            ax2.set_yticks([0,1,2,3]); ax2.set_yticklabels(["◄","▼","▲","►"],fontsize=8); ax2.set_ylim(-0.5,3.5)
        ax.legend(fontsize=7, loc="upper left")

        # I_cog
        ax = fig.add_subplot(gs[4,:])
        ax.set_title("I_cog = (z_FC + z_PWA_inv + z_RR + z_RT) / 4", fontsize=8); ax.set_ylabel("I_cog", fontsize=7); ax.set_xlabel("Temps (s)", fontsize=7); ax.grid(True, alpha=0.3); ax.tick_params(labelsize=7)
        if ic_ts_a and ic_v_a:
            ax.plot(ic_ts_a, ic_v_a, color="tab:purple", lw=1.5, label="I_cog")
            ax.fill_between(ic_ts_a, ic_v_a, THRESHOLD,
                where=[v > THRESHOLD for v in ic_v_a], color="red", alpha=0.25)
        ax.axhline(y=THRESHOLD, color="red", ls="--", alpha=0.7, lw=1.2)
        ax.axvline(x=CALIB_SEC, color="gray", ls="--", alpha=0.6, label="Fin calib.")
        ax.legend(fontsize=7, loc="upper left")

        plt.tight_layout()

        # Sauvegarder aussi en fichier
        import os as _os
        _os.makedirs("sessions", exist_ok=True)
        fname = f"sessions/rapport_{time.strftime('%Y%m%d_%H%M%S')}.png"
        try:
            fig.savefig(fname, dpi=130, bbox_inches="tight", facecolor="white")
            print(f"[rapport] Sauvegardé : {fname}")
        except Exception as e:
            print(f"[rapport] Erreur sauvegarde : {e}")

        return self._fig_to_surface(fig)


def _plot_raw(ax, buf, title, color):
    ax.cla(); ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=8); ax.set_ylabel("Amplitude", fontsize=7)
    ax.tick_params(labelsize=7)
    if buf:
        ax.plot(buf, color=color, lw=0.7, alpha=0.85)


def _plot_filt_peaks(ax, filt, peaks, title, color, peak_color):
    ax.cla(); ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=8); ax.set_ylabel("Amplitude", fontsize=7)
    ax.tick_params(labelsize=7)
    if len(filt) > 0:
        ax.plot(filt, color=color, lw=0.9)
        pi = [p for p in peaks if p < len(filt)]
        if pi:
            ax.plot(pi, filt[pi], "x", color=peak_color, ms=7, mew=1.5)
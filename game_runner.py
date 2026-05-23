"""
game_only.py — Jeu pygame pur avec suivi des evenements.
Patch via _start_next_round (plus fiable que __init__).
"""

import json
import os
import sys
import time

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from game import Game

EVENTS_FILE = "sessions/live_events.json"


def load_ev():
    try:
        with open(EVENTS_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "levels_normal": [],
            "levels_chunking": [],
            "keys_normal": [],
            "keys_chunking": [],
            "phase": "normal",
        }


def save_ev(d):
    try:
        os.makedirs("sessions", exist_ok=True)
        with open(EVENTS_FILE, "w") as f:
            json.dump(d, f)
    except Exception:
        pass


def patch_game(game):
    save_ev(
        {
            "levels_normal": [],
            "levels_chunking": [],
            "keys_normal": [],
            "keys_chunking": [],
            "phase": "normal",
            "session_start": time.time(),
        }
    )

    from game import (
        CalibrationState,
        PairArrowState,
        PrePairState,
        SingleArrowState,
        SummaryState,
    )

    t0 = [time.time()]

    def ts():
        return time.time() - t0[0]

    # ── Calibration ───────────────────────────────────────────
    orig_calib = CalibrationState.update
    _calib_started = [False]

    def new_calib(self_c):
        if not self_c.inited and not _calib_started[0]:
            _calib_started[0] = True
            d = load_ev()
            d["calib_start"] = ts()
            save_ev(d)
            t0[0] = time.time()
        orig_calib(self_c)
        if game.current_state is not self_c and _calib_started[0]:
            d = load_ev()
            d["calib_end"] = ts()
            save_ev(d)

    CalibrationState.update = new_calib

    # ── NORMAL : patcher _start_next_round ───────────────────
    # C'est appelé à chaque nouveau niveau (arrows_count += 1)
    orig_sa_next = SingleArrowState._start_next_round
    orig_sa_handle = SingleArrowState.handle_player_inputs

    def new_sa_next(self_s):
        # Fermer le niveau précédent
        d = load_ev()
        if d["levels_normal"]:
            d["levels_normal"][-1]["ts_end"] = ts()
            d["levels_normal"][-1]["success"] = True
        orig_sa_next(self_s)  # arrows_count += 1 ici
        # Ouvrir le nouveau niveau
        d["levels_normal"].append(
            {"level": self_s.arrows_count, "ts": ts(), "ts_end": None, "success": True}
        )
        save_ev(d)

    def new_sa_handle(self_s):
        was = game.current_state
        # Enregistrer touche
        if not self_s.show_arrows and self_s.chosen_direction is not None:
            expected = self_s.arrow_directions[self_s.pressed_directions]
            correct = self_s.chosen_direction == expected
            d = load_ev()
            d["keys_normal"].append(
                {"ts": ts(), "direction": self_s.chosen_direction, "correct": correct}
            )
            save_ev(d)
        orig_sa_handle(self_s)
        # Perdu
        if game.current_state is not self_s and was is self_s:
            if not isinstance(game.current_state, PrePairState):
                d = load_ev()
                if d["levels_normal"]:
                    d["levels_normal"][-1]["ts_end"] = ts()
                    d["levels_normal"][-1]["success"] = False
                save_ev(d)

    SingleArrowState._start_next_round = new_sa_next
    SingleArrowState.handle_player_inputs = new_sa_handle

    # Détecter quand SingleArrowState devient actif (premier niveau = 1)
    # en patchant update pour enregistrer le niveau 1
    orig_sa_update = SingleArrowState.update
    _sa_registered = [False]

    def new_sa_update(self_s):
        if not _sa_registered[0]:
            _sa_registered[0] = True
            d = load_ev()
            d["phase"] = "normal"
            # Niveau 1 (arrows_count commence à 1)
            if not any(lv["level"] == 1 for lv in d["levels_normal"]):
                d["levels_normal"].append(
                    {"level": 1, "ts": ts(), "ts_end": None, "success": True}
                )
            save_ev(d)
        orig_sa_update(self_s)

    SingleArrowState.update = new_sa_update

    # ── Transition Normal → Chunking ──────────────────────────
    orig_prepair = PrePairState.__init__

    def new_prepair(self_p, gr):
        orig_prepair(self_p, gr)
        d = load_ev()
        d["phase"] = "chunking"
        d["transition_ts"] = ts()
        save_ev(d)

    PrePairState.__init__ = new_prepair

    # ── CHUNKING : patcher _start_next_round ─────────────────
    orig_pa_next = PairArrowState._start_next_round
    orig_pa_update = PairArrowState.update
    _pa_registered = [False]

    def new_pa_update(self_p):
        if not _pa_registered[0]:
            _pa_registered[0] = True
            d = load_ev()
            n = len(self_p.pair_directions)
            if not any(lv["level"] == n for lv in d["levels_chunking"]):
                d["levels_chunking"].append(
                    {"level": n, "ts": ts(), "ts_end": None, "success": True}
                )
            save_ev(d)
        orig_pa_update(self_p)
        # Perdu (state a changé)
        if game.current_state is not self_p:
            d = load_ev()
            if d["levels_chunking"] and d["levels_chunking"][-1]["ts_end"] is None:
                d["levels_chunking"][-1]["ts_end"] = ts()
                d["levels_chunking"][-1]["success"] = False
            save_ev(d)

    def new_pa_next(self_p):
        d = load_ev()
        if d["levels_chunking"]:
            d["levels_chunking"][-1]["ts_end"] = ts()
            d["levels_chunking"][-1]["success"] = True
        orig_pa_next(self_p)
        n = len(self_p.pair_directions)
        d["levels_chunking"].append(
            {"level": n, "ts": ts(), "ts_end": None, "success": True}
        )
        save_ev(d)

    PairArrowState.update = new_pa_update
    PairArrowState._start_next_round = new_pa_next

    # ── Summary ───────────────────────────────────────────────
    orig_sum_init = SummaryState.__init__
    orig_sum_draw = SummaryState.draw
    orig_sum_handle = SummaryState.handle_events
    _surf = [None]  # liste de pygame.Surface
    _fig_idx = [0]  # index courant galerie

    def new_sum_init(self_s, gr):
        orig_sum_init(self_s, gr)
        d = load_ev()
        d["game_end"] = ts()
        max_n = max((lv["level"] for lv in d["levels_normal"]), default=0)
        max_c = max((lv["level"] for lv in d["levels_chunking"]), default=0)
        d["max_level_normal"] = max_n
        d["max_level_chunking"] = max_c
        save_ev(d)
        print(
            f"[game] Fin — Normal niveaux:{len(d['levels_normal'])}  Chunking niveaux:{len(d['levels_chunking'])}"
        )

        # Attendre que physio_live enrichisse les niveaux (max 4s)
        import time as _t

        deadline = _t.time() + 4
        while _t.time() < deadline:
            try:
                with open(EVENTS_FILE) as f:
                    ev = json.load(f)
                # Vérifier si les physio sont disponibles
                n_lvs = ev.get("levels_normal", [])
                if n_lvs and n_lvs[0].get("hr_bpm") is not None:
                    break
            except Exception:
                pass
            _t.sleep(0.3)

        # Générer PNG comparatif
        import glob as _gl
        import subprocess as _sp

        _env = dict(os.environ, MPLBACKEND="Agg")
        proc = _sp.Popen(
            [sys.executable, "analysis.py"], stdout=None, stderr=None, env=_env
        )
        proc.wait(timeout=10)  # attendre la fin

        # Charger toutes les figures depuis l'index
        import glob as _gl

        try:
            with open("sessions/figures_index.json") as _f:
                idx = json.load(_f)
            fig_paths = idx.get("figures", [])
        except Exception:
            fig_paths = sorted(_gl.glob("sessions/fig_*.png"), reverse=True)[:5]

        surfs = []
        sw = gr.screen.get_width()
        sh = gr.screen.get_height()
        title_h = 120
        avail_h = sh - title_h - 80
        for fp in fig_paths:
            try:
                s = pygame.image.load(fp)
                ratio = min((sw - 60) / s.get_width(), avail_h / s.get_height())
                nw = int(s.get_width() * ratio)
                nh = int(s.get_height() * ratio)
                surfs.append(pygame.transform.smoothscale(s, (nw, nh)))
            except Exception as e:
                print(f"[game] Erreur chargement {fp}: {e}")

        if surfs:
            _surf[0] = surfs  # liste de surfaces
            _fig_idx[0] = 0
            print(f"[game] {len(surfs)} figures chargees")
        else:
            _surf[0] = None

    def new_sum_draw(self_s):
        if _surf[0] and isinstance(_surf[0], list) and len(_surf[0]) > 0:
            scr = self_s.game.screen
            sw = scr.get_width()
            sh = scr.get_height()
            scr.fill("#014F84")
            # Titre
            scr.blit(self_s.title, self_s.title_rect)
            # Figure courante
            idx = _fig_idx[0] % len(_surf[0])
            surf = _surf[0][idx]
            x = (sw - surf.get_width()) // 2
            y = self_s.title_rect.bottom + 5
            scr.blit(surf, (x, y))
            # Navigation
            font = pygame.font.SysFont("Arial", 20)
            nav = font.render(
                f"< >  Figure {idx + 1}/{len(_surf[0])}  |  ESC = menu",
                True,
                (200, 200, 200),
            )
            scr.blit(nav, (sw // 2 - nav.get_width() // 2, sh - 35))
            # Noms des figures
            names = ["FC", "RR", "PWA", "Succes", "Erreurs"]
            if idx < len(names):
                lbl = font.render(names[idx], True, (255, 255, 200))
                scr.blit(lbl, (sw // 2 - lbl.get_width() // 2, sh - 60))
        else:
            orig_sum_draw(self_s)

    def new_sum_handle(self_s, events):
        orig_sum_handle(self_s, events)
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self_s.game.current_state = self_s.game.states["menu"]
                    _surf[0] = None
                elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                    if _surf[0] and isinstance(_surf[0], list):
                        _fig_idx[0] = (_fig_idx[0] + 1) % len(_surf[0])
                elif ev.key in (pygame.K_LEFT, pygame.K_q):
                    if _surf[0] and isinstance(_surf[0], list):
                        _fig_idx[0] = (_fig_idx[0] - 1) % len(_surf[0])

    SummaryState.__init__ = new_sum_init
    SummaryState.draw = new_sum_draw
    SummaryState.handle_events = new_sum_handle


if __name__ == "__main__":
    pygame.init()
    game = Game()
    patch_game(game)
    game.run()
    pygame.quit()

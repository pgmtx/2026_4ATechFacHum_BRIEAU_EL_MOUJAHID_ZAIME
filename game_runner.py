"""
game_runner.py — A pure PyGame game with event handling
Patch via _start_next_round (more reliable than __init__).
"""

import json
import logging
import os
import sys
import time
from typing import Any, cast

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
            "session_start": time.perf_counter(),
        }
    )

    from game import (
        CalibrationState,
        PairArrowState,
        PrePairState,
        SingleArrowState,
        SummaryState,
    )

    t0 = [time.perf_counter()]

    def ts():
        return time.perf_counter() - t0[0]

    # ── Calibration ───────────────────────────────────────────
    orig_calib = CalibrationState.update
    _calib_started = [False]

    # The parameter must be named self to match the _start_next_round signature.
    def new_calib(self: CalibrationState):
        if not self.inited and not _calib_started[0]:
            _calib_started[0] = True
            d = load_ev()
            d["calib_start"] = ts()
            save_ev(d)
            t0[0] = time.perf_counter()
        orig_calib(self)
        if game.current_state is not self and _calib_started[0]:
            d = load_ev()
            d["calib_end"] = ts()
            save_ev(d)

    CalibrationState.update = cast(Any, new_calib)

    # ── NORMAL : patch _start_next_round ───────────────────
    # Called at the start of each new level (arrows_count += 1)
    orig_sa_next = SingleArrowState._start_next_round
    orig_sa_handle = SingleArrowState.handle_player_inputs

    def new_sa_next(self: SingleArrowState):
        # Close the previous level
        d = load_ev()
        if d["levels_normal"]:
            last_level = d["levels_normal"][-1]
            last_level["ts_end"] = ts()
            last_level["success"] = True
        orig_sa_next(self)  # arrows_count increses here
        # Open a new level
        d["levels_normal"].append(
            {"level": self.arrows_count, "ts": ts(), "ts_end": None, "success": True}
        )
        save_ev(d)

    def new_sa_handle(self: SingleArrowState):
        was = game.current_state
        # Save key
        if not self.show_arrows and self.chosen_direction is not None:
            expected = self.arrow_directions[self.pressed_directions]
            correct = self.chosen_direction == expected
            d = load_ev()
            d["keys_normal"].append(
                {"ts": ts(), "direction": self.chosen_direction, "correct": correct}
            )
            save_ev(d)
        orig_sa_handle(self)

        has_lost = game.current_state is not self and was is self
        if has_lost and not isinstance(game.current_state, PrePairState):
            d = load_ev()
            if d["levels_normal"]:
                last_level = d["levels_normal"][-1]
                last_level["ts_end"] = ts()
                last_level["success"] = False
            save_ev(d)

    SingleArrowState._start_next_round = cast(Any, new_sa_next)
    SingleArrowState.handle_player_inputs = cast(Any, new_sa_handle)

    # Detects when SingleArrowState becomes active (level 1) by patching the update function to record level 1
    orig_sa_update = SingleArrowState.update
    _sa_registered = [False]

    def new_sa_update(self: SingleArrowState):
        if not _sa_registered[0]:
            _sa_registered[0] = True
            d = load_ev()
            d["phase"] = "normal"
            # Level 1 (arrows_count = 1)
            if not any(lv["level"] == 1 for lv in d["levels_normal"]):
                d["levels_normal"].append(
                    {"level": 1, "ts": ts(), "ts_end": None, "success": True}
                )
            save_ev(d)
        orig_sa_update(self)

    SingleArrowState.update = cast(Any, new_sa_update)

    # ── Transition from Normal to Chunking ──────────────────────────
    orig_prepair = PrePairState.__init__

    # The second parameter is not named game to avoid confusion with the outer parameter
    def new_prepair(self: PrePairState, gr: Game):
        orig_prepair(self, gr)
        d = load_ev()
        d["phase"] = "chunking"
        d["transition_ts"] = ts()
        save_ev(d)

    PrePairState.__init__ = cast(Any, new_prepair)

    # ── CHUNKING : patch _start_next_round ─────────────────
    orig_pa_next = PairArrowState._start_next_round
    orig_pa_update = PairArrowState.update
    _pa_registered = [False]

    def new_pa_update(self: PairArrowState):
        if not _pa_registered[0]:
            _pa_registered[0] = True
            d = load_ev()
            n = len(self.pair_directions)
            if not any(lv["level"] == n for lv in d["levels_chunking"]):
                d["levels_chunking"].append(
                    {"level": n, "ts": ts(), "ts_end": None, "success": True}
                )
            save_ev(d)
        orig_pa_update(self)
        # Perdu (state a changé)
        if game.current_state is not self:
            d = load_ev()
            if d["levels_chunking"] and d["levels_chunking"][-1]["ts_end"] is None:
                last_level = d["levels_chunking"][-1]
                last_level["ts_end"] = ts()
                last_level["success"] = False
            save_ev(d)

    def new_pa_next(self: PairArrowState):
        d = load_ev()
        if d["levels_chunking"]:
            last_level = d["levels_chunking"][-1]
            last_level["ts_end"] = ts()
            last_level["success"] = True
        orig_pa_next(self)
        n = len(self.pair_directions)
        d["levels_chunking"].append(
            {"level": n, "ts": ts(), "ts_end": None, "success": True}
        )
        save_ev(d)

    PairArrowState.update = cast(Any, new_pa_update)
    PairArrowState._start_next_round = cast(Any, new_pa_next)

    # ── Summary ───────────────────────────────────────────────
    orig_sum_init = SummaryState.__init__
    orig_sum_draw = SummaryState.draw
    orig_sum_handle = SummaryState.handle_events
    _surf: list[pygame.Surface] | None = None
    _fig_idx = 0  # current gallery index

    def new_sum_init(self: SummaryState, gr: Game):
        orig_sum_init(self, gr)
        d = load_ev()
        d["game_end"] = ts()
        max_n = max((lv["level"] for lv in d["levels_normal"]), default=0)
        max_c = max((lv["level"] for lv in d["levels_chunking"]), default=0)
        d["max_level_normal"] = max_n
        d["max_level_chunking"] = max_c
        save_ev(d)
        logging.info(
            f"[game] Fin — Normal niveaux:{len(d['levels_normal'])}  Chunking niveaux:{len(d['levels_chunking'])}"
        )

        # Wait for biosignal_monitor to load the levels (max 4s)
        import time as _t

        deadline = _t.perf_counter() + 4
        while _t.perf_counter() < deadline:
            try:
                with open(EVENTS_FILE) as f:
                    ev = json.load(f)
                # Check if the physios are available
                n_lvs = ev.get("levels_normal", [])
                if n_lvs and n_lvs[0].get("hr_bpm") is not None:
                    break
            except Exception:
                pass
            _t.sleep(0.3)

        # Generate a comparison PNG
        import glob as _gl
        import subprocess as _sp

        _env = dict(os.environ, MPLBACKEND="Agg")
        proc = _sp.Popen(
            [sys.executable, "analysis.py"], stdout=None, stderr=None, env=_env
        )
        proc.wait(timeout=10)

        # Load all figures from the index
        try:
            with open("sessions/figures_index.json") as _f:
                idx = json.load(_f)
            fig_paths = idx.get("figures", [])
        except Exception:
            fig_paths = sorted(_gl.glob("sessions/fig_*.png"), reverse=True)[:5]

        surfs: list[pygame.Surface] = []
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
                logging.exception(f"[game] Erreur chargement {fp}: {e}")

        # Allows new_sum_init to assign to patch_game()'s _surf and _fig_idx (shares state across closures)
        nonlocal _surf, _fig_idx

        if surfs:
            _surf = surfs
            _fig_idx = 0
            logging.info(f"[game] {len(surfs)} figures chargees")
        else:
            _surf = None

    def new_sum_draw(self: SummaryState):
        has_surface = isinstance(_surf, list) and _surf
        if not has_surface:
            orig_sum_draw(self)
            return

        # Prevents static analysis warning about None being non-subscriptable
        assert isinstance(_surf, list)

        scr = self.game.screen
        sw = scr.get_width()
        sh = scr.get_height()
        scr.fill("#014F84")

        # Titre
        scr.blit(self.title, self.title_rect)

        # Figure courante
        idx = _fig_idx % len(_surf)
        surf = _surf[idx]
        x = (sw - surf.get_width()) // 2
        y = self.title_rect.bottom + 5
        scr.blit(surf, (x, y))

        # Navigation
        font = pygame.font.SysFont("Arial", 20)
        nav = font.render(
            f"< >  Figure {idx + 1}/{len(_surf)}  |  ESC = menu",
            True,
            (200, 200, 200),
        )
        scr.blit(nav, (sw // 2 - nav.get_width() // 2, sh - 35))

        # Figure names
        names = ("FC", "RR", "PWA", "Succes", "Erreurs")
        if idx < len(names):
            lbl = font.render(names[idx], True, (255, 255, 200))
            scr.blit(lbl, (sw // 2 - lbl.get_width() // 2, sh - 60))

    def new_sum_handle(self: SummaryState, events: list[pygame.event.Event]):
        orig_sum_handle(self, events)

        nonlocal _surf, _fig_idx
        for ev in events:
            if ev.type != pygame.KEYDOWN:
                continue
            if ev.key == pygame.K_ESCAPE:
                self.game.current_state = self.game.states["menu"]
                _surf = None
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                if _surf and isinstance(_surf, list):
                    _fig_idx = (_fig_idx + 1) % len(_surf)
            elif ev.key in (pygame.K_LEFT, pygame.K_q):
                if _surf and isinstance(_surf, list):
                    _fig_idx = (_fig_idx - 1) % len(_surf)

    SummaryState.__init__ = cast(Any, new_sum_init)
    SummaryState.draw = cast(Any, new_sum_draw)
    SummaryState.handle_events = cast(Any, new_sum_handle)


if __name__ == "__main__":
    pygame.init()
    game = Game()
    patch_game(game)
    game.run()
    pygame.quit()

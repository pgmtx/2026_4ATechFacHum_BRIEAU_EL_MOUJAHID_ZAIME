"""
game_only.py — Jeu pygame pur.
Écrit les événements dans sessions/live_events.json pour physio_live.py.
"""

import os, sys, time, json
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame
from game import Game

EVENTS_FILE = "sessions/live_events.json"

def load_events():
    try:
        with open(EVENTS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"levels": [], "keys": [], "session_start": time.time()}

def save_events(data):
    try:
        os.makedirs("sessions", exist_ok=True)
        with open(EVENTS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def patch_game(game):
    # Initialiser le JSON (sans calib_start → physio_live attend)
    save_events({"levels": [], "keys": [], "session_start": time.time()})

    from game import (CalibrationState, SingleArrowState,
                      PairArrowState, SummaryState)

    t0 = [time.time()]

    def ts():
        return time.time() - t0[0]

    # Calibration → signaler à physio_live
    orig_calib = CalibrationState.update
    def new_calib(self_c):
        if not self_c.inited:
            d = load_events()
            d["calib_start"] = ts()
            save_events(d)
            t0[0] = time.time()
        orig_calib(self_c)
        if game.current_state is not self_c:
            d = load_events()
            d["calib_end"] = ts()
            save_events(d)
    CalibrationState.update = new_calib

    # SingleArrow → enregistrer niveaux et touches
    orig_sa_init   = SingleArrowState.__init__
    orig_sa_handle = SingleArrowState.handle_player_inputs

    def new_sa_init(self_s, gr):
        orig_sa_init(self_s, gr)
        d = load_events()
        d["levels"].append({"level": self_s.arrows_count, "ts": ts()})
        save_events(d)

    def new_sa_handle(self_s):
        if not self_s.show_arrows and self_s.chosen_direction is not None:
            expected = self_s.arrow_directions[self_s.pressed_directions]
            correct  = (self_s.chosen_direction == expected)
            d = load_events()
            d["keys"].append({
                "ts": ts(),
                "direction": self_s.chosen_direction,
                "correct": correct
            })
            save_events(d)
        orig_sa_handle(self_s)

    SingleArrowState.__init__ = new_sa_init
    SingleArrowState.handle_player_inputs = new_sa_handle

    # Summary → signaler fin de jeu à physio_live
    orig_sum_init = SummaryState.__init__

    def new_sum_init(self_s, gr):
        orig_sum_init(self_s, gr)
        d = load_events()
        d["game_end"] = ts()
        d["max_level"] = max((lv["level"] for lv in d["levels"]), default=0)
        save_events(d)
        print("[game] Fin de partie — rapport affiché dans physio_live")

    SummaryState.__init__ = new_sum_init


if __name__ == "__main__":
    pygame.init()
    game = Game()
    patch_game(game)
    game.run()
    pygame.quit()
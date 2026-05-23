"""
ChunkyMemo — main.py (architecture finale simple)

Lance 2 sous-processus indépendants en parallèle :
  1. game_runner.py   — jeu pygame pur
  2. biosignal_monitor.py — acquisition BITalino + graphes matplotlib

Les deux communiquent via sessions/live_events.json :
  - game_runner .py écrit les événements jeu (niveaux, touches, score)
  - biosignal_monitor.py les lit pour annoter ses graphes
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

LIVE_EVENT_DEFAULTS = {
    "levels_normal": [],
    "levels_chunking": [],
    "keys_normal": [],
    "keys_chunking": [],
}


def main():
    logging.basicConfig(
        level=logging.DEBUG, format="[%(funcName)s] %(levelname)s - %(message)s"
    )

    Path("sessions").mkdir(exist_ok=True)
    with open("sessions/live_events.json", "w") as f:
        json.dump(LIVE_EVENT_DEFAULTS, f)

    logging.debug("Démarrage de ChunkyMemo")
    logging.debug("Ouverture du jeu")

    game_proc = subprocess.Popen([sys.executable, "game_runner.py", *sys.argv[1:]])
    logging.debug(f"PID du jeu : {game_proc.pid}")

    physio_proc = subprocess.Popen([sys.executable, "biosignal_monitor.py"])
    logging.debug(f"PID de physio : {physio_proc.pid}")

    # Makes the physio window close when we close the game
    try:
        game_proc.wait()
    finally:
        physio_proc.terminate()
        physio_proc.wait()


if __name__ == "__main__":
    main()

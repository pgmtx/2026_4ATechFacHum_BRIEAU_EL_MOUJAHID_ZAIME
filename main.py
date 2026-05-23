"""
ChunkyMemo — main.py (architecture finale simple)

Lance 2 sous-processus indépendants en parallèle :
  1. game_only.py   — jeu pygame pur (game.py original sans modification)
  2. physio_live.py — acquisition BITalino + graphes matplotlib (FuncAnimation)

Les deux communiquent via sessions/live_events.json :
  - game_only.py écrit les événements jeu (niveaux, touches, score)
  - physio_live.py les lit pour annoter ses graphes
"""

import os
import subprocess
import sys


def main():
    os.makedirs("sessions", exist_ok=True)
    try:
        with open("sessions/live_events.json", "w") as f:
            import json

            json.dump(
                {
                    "levels_normal": [],
                    "levels_chunking": [],
                    "keys_normal": [],
                    "keys_chunking": [],
                },
                f,
            )
    except Exception:
        pass

    print("[main] Démarrage ChunkyMemo")
    print("[main] Phase 1 : Normal  →  Phase 2 : Chunking")
    print("[main] Fenêtre JEU  → gauche  |  Fenêtre GRAPHES → bas-gauche\n")

    game_proc = subprocess.Popen([sys.executable, "game_only.py", *sys.argv[1:]])
    physio_proc = subprocess.Popen([sys.executable, "physio_live.py"])

    print(f"[main] Jeu PID={game_proc.pid}  Physio PID={physio_proc.pid}")
    print("[main] Fermez la fenêtre JEU pour terminer les deux")

    # Attendre que le jeu se termine (le joueur ferme pygame)
    game_proc.wait()
    print(
        "[main] Jeu terminé — physio_live reste ouvert (fermez la fenêtre matplotlib)"
    )
    # Attendre que physio_live se ferme tout seul (l'utilisateur ferme la fenêtre)
    physio_proc.wait()
    print("[main] Terminé")


if __name__ == "__main__":
    main()

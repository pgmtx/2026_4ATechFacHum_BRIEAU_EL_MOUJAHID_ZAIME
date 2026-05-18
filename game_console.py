"""
==============================================================
ChunkyMemo — game_console.py
==============================================================
Jeu complet dans le terminal + acquisition réelle BITalino.

Ce fichier fait TOUT en un seul lancement :
  1. Connecte le BITalino via plux (ou simule si non branché)
  2. Lance le jeu de mémoire dans le terminal
  3. Enregistre tous les signaux (PPG + PZT + ACC) en continu
  4. Sauvegarde les données en CSV à la fin
  5. Génère les graphiques comparatifs automatiquement

Comment jouer :
  - Une séquence de flèches s'affiche (ex: ↑ ↓ → ←)
  - Vous avez 2 secondes pour la mémoriser
  - Elle disparaît → vous tapez les directions au clavier
  - Touches : Z=haut  S=bas  Q=gauche  D=droite  (ou flèches)
  - Entrée après chaque direction (ou tout d'un coup séparé par espaces)

Comment lancer :
  pip install plux scipy numpy matplotlib
  python game_console.py

  Pour forcer la simulation (sans BITalino) :
  python game_console.py --sim

Omar / Salma :
  Si le BITalino ne se connecte pas → le jeu tourne quand même
  en mode simulation. Les données sont sauvegardées pareil.
  Testez d'abord sans le BITalino pour valider le jeu.
==============================================================
"""

import sys
import time
import queue
import threading
import random
import os
import csv
import platform
import math
import signal as os_signal
from datetime import datetime
from collections import deque

import config
from signal_processing import PPGProcessor, PZTProcessor, SessionData

# ==============================================================
# IMPORT PLUX — copie exacte de la structure du prof
# ==============================================================

FORCE_SIM = "--sim" in sys.argv   # python game_console.py --sim

try:
    import plux
    _ = plux.SignalsDev
    PLUX_AVAILABLE = True and not FORCE_SIM
except (ImportError, AttributeError):
    PLUX_AVAILABLE = False

if FORCE_SIM:
    print("[INFO] Mode simulation forcé (--sim)")
elif not PLUX_AVAILABLE:
    print("[INFO] plux non disponible → simulation automatique")

# ==============================================================
# DEVICE PLUX — identique au main.py du prof
# ==============================================================

if PLUX_AVAILABLE:
    class ChunkyDevice(plux.SignalsDev):
        """
        Exactement comme NewDevice du prof.
        onRawFrame → queue au lieu de matplotlib.
        """
        def __init__(self, address, data_queue, stop_event):
            plux.SignalsDev.__init__(address)
            self.data_queue  = data_queue
            self.stop_event  = stop_event
            self.duration    = config.DURATION_MAX
            self.frequency   = config.SAMPLING_RATE
            self._last_print = 0

        def onRawFrame(self, nSeq, data):
            # Construction du sample — PPG + PZT uniquement (pas d'ACC)
            sample = {
                "ts":    time.time(),
                "nSeq":  nSeq,
                "ppg":   int(data[config.IDX_PPG]),
                "pzt":   int(data[config.IDX_PZT]),
                "acc_x": 0,   # pas d'ACC — champ conserve pour compatibilite CSV
                "acc_y": 0,
            }
            try:
                self.data_queue.put_nowait(sample)
            except queue.Full:
                pass  # queue pleine → on ignore, le jeu est prioritaire

            # Affichage debug discret (1x/sec) — ne pollue pas le terminal du jeu
            now = time.time()
            if now - self._last_print >= 2.0:
                # On affiche en bas sans interrompre le jeu
                self._last_print = now

            # Arrêt si demandé
            return self.stop_event.is_set() or (nSeq > self.duration * self.frequency)


# ==============================================================
# THREAD D'ACQUISITION — tourne en parallèle du jeu
# ==============================================================

class AcquisitionThread(threading.Thread):
    """
    Thread daemon : acquisition BITalino en arrière-plan.
    Le jeu tourne dans le thread principal, ce thread lit les capteurs.
    Communication via data_queue (thread-safe).
    """

    def __init__(self, data_queue):
        super().__init__(daemon=True)
        self.data_queue = data_queue
        self.stop_event = threading.Event()
        self.device     = None
        self.simulating = not PLUX_AVAILABLE

    def run(self):
        if not PLUX_AVAILABLE:
            print("[acquisition] ERREUR : plux non disponible et simulation desactivee.")
            print("  Verifiez l'installation de plux et la connexion BITalino.")
            return
        self._run_real()

    def _run_real(self):
        """Acquisition réelle — structure identique à exampleAcquisition() du prof."""
        try:
            print(f"[BITalino] Connexion à {config.MAC_ADDRESS} ...")
            self.device = ChunkyDevice(config.MAC_ADDRESS,
                                       self.data_queue, self.stop_event)
            self.device.start(config.SAMPLING_RATE,
                              config.ACTIVE_PORTS,
                              config.RESOLUTION)
            print(f"[BITalino] ✓ Connecté — ports {config.ACTIVE_PORTS} @ {config.SAMPLING_RATE}Hz")
            self.device.loop()   # bloque jusqu'à stop_event

        except Exception as e:
            print(f"[BITalino] Erreur connexion : {e}")
            print("[BITalino] Verifiez :")
            print(f"  1. BITalino allume et bluetooth actif")
            print(f"  2. Adresse MAC dans config.py : {config.MAC_ADDRESS}")
            print(f"  3. Ports branches : {config.ACTIVE_PORTS}")
        finally:
            if self.device:
                try:
                    self.device.stop()
                    self.device.close()
                except Exception:
                    pass

    def stop(self):
        self.stop_event.set()


# ==============================================================
# AFFICHAGE CONSOLE — fonctions d'affichage du jeu
# ==============================================================

# Symboles flèches
ARROW = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→"}

# Couleurs ANSI (fonctionnent sur Linux/Mac/Windows Terminal)
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    WHITE  = "\033[97m"
    PURPLE = "\033[95m"

def clear():
    """Efface le terminal."""
    os.system("cls" if os.name == "nt" else "clear")

def print_header(mode, level, score, hr=None, rr=None, simulating=False):
    """Barre de statut en haut du terminal."""
    sim_tag = f" {C.YELLOW}[SIM]{C.RESET}" if simulating else f" {C.GREEN}[LIVE]{C.RESET}"
    hr_str  = f"{hr:.0f}bpm" if hr else "---"
    rr_str  = f"{rr:.0f}rpm" if rr else "---"

    print(f"{C.BOLD}{'='*60}{C.RESET}")
    print(f"  {C.BOLD}ChunkyMemo{C.RESET}{sim_tag}  "
          f"| Mode: {C.CYAN}{mode}{C.RESET} "
          f"| Niveau: {C.YELLOW}{level}{C.RESET} "
          f"| Score: {C.GREEN}{score}{C.RESET}")
    print(f"  {C.GRAY}Capteurs → PPG: {hr_str}  PZT: {rr_str}{C.RESET}")
    print(f"{C.BOLD}{'='*60}{C.RESET}")

def print_sequence(seq, mode, title="Mémorisez !"):
    """Affiche la séquence de flèches."""
    arrows = [ARROW[d] for d in seq]

    print(f"\n  {C.YELLOW}{C.BOLD}{title}{C.RESET}\n")

    if mode == "NORMAL":
        # Mode normal : flèches alignées
        print("  " + "  ".join(
            f"{C.WHITE}{C.BOLD}{a}{C.RESET}" for a in arrows
        ))
        print("  " + "  ".join(
            f"{C.GRAY}{d[:1]}{C.RESET}" for d in seq   # lettre initiale en gris
        ))
    else:
        # Mode chunking : regroupées par paires avec séparateur visuel
        chunks = [seq[i:i+2] for i in range(0, len(seq), 2)]
        arrow_chunks = [arrows[i:i+2] for i in range(0, len(arrows), 2)]

        chunk_strs = []
        for i, (chunk_a, chunk_d) in enumerate(zip(arrow_chunks, chunks)):
            # Alternance de couleurs pour chaque chunk
            col = C.CYAN if i % 2 == 0 else C.PURPLE
            chunk_str = col + " ".join(chunk_a) + C.RESET
            chunk_strs.append(f"[{chunk_str}]")

        print("  " + "  ".join(chunk_strs))
        print(f"\n  {C.GRAY}(séquence groupée par paires — chunking){C.RESET}")

def print_reproduce_prompt(seq, player_input, last_ok=None):
    """
    Affiche la progression de la reproduction.
    Montre les flèches déjà tapées (vertes/rouges) et le curseur.
    """
    arrows = [ARROW[d] for d in seq]
    n = len(player_input)

    result = []
    for i, a in enumerate(arrows):
        if i < n:
            # Déjà tapé
            if player_input[i] == seq[i]:
                result.append(f"{C.GREEN}{C.BOLD}{a}{C.RESET}")   # correct
            else:
                result.append(f"{C.RED}{C.BOLD}✗{C.RESET}")        # erreur
        elif i == n:
            result.append(f"{C.YELLOW}{C.BOLD}_{C.RESET}")          # curseur
        else:
            result.append(f"{C.GRAY}·{C.RESET}")                    # pas encore tapé

    print(f"\n  Reproduisez : " + "  ".join(result))
    print(f"  {C.GRAY}({n}/{len(seq)} tapés){C.RESET}")
    print()

def print_feedback(success, seq, player_input):
    """Affiche le résultat après chaque niveau."""
    if success:
        print(f"\n  {C.GREEN}{C.BOLD}✓ Correct !{C.RESET}\n")
    else:
        print(f"\n  {C.RED}{C.BOLD}✗ Erreur !{C.RESET}")
        expected = "  ".join(ARROW[d] for d in seq)
        given    = "  ".join(ARROW.get(d, "?") for d in player_input)
        print(f"  Attendu  : {C.GREEN}{expected}{C.RESET}")
        print(f"  Tapé     : {C.RED}{given}{C.RESET}\n")

def print_sensor_bar(ppg_buf, pzt_buf, width=40):
    """
    Mini-visualisation ASCII des signaux capteurs.
    Affiche une ligne par capteur avec un graphique de caractères.
    """
    if len(ppg_buf) < 5:
        print(f"  {C.GRAY}[capteurs: calibration...]{C.RESET}")
        return

    def mini_graph(buf, color, label, n=40):
        """Génère un mini graphique ASCII d'un signal."""
        vals = list(buf)[-n:]
        if not vals:
            return ""
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1
        chars = " ▁▂▃▄▅▆▇█"
        bars  = ""
        for v in vals:
            idx = int((v - mn) / rng * (len(chars) - 1))
            bars += chars[idx]
        return f"  {color}{label}: {C.RESET}{color}{bars}{C.RESET}"

    print(mini_graph(ppg_buf, C.RED,    "PPG"))
    print(mini_graph(pzt_buf, C.YELLOW, "PZT"))


# ==============================================================
# LECTURE CLAVIER — saisie des directions
# ==============================================================

def read_direction(prompt="  > ") -> str | None:
    """
    Lit une direction au clavier.
    Accepte : Z/z=UP  S/s=DOWN  Q/q=LEFT  D/d=RIGHT
              ou les lettres U/D/L/R
              ou les mots complets "up", "down", "left", "right"
    Retourne None si l'entrée est invalide.
    """
    KEYMAP = {
        # ZQSD
        "z": "UP",   "Z": "UP",
        "s": "DOWN", "S": "DOWN",
        "q": "LEFT", "Q": "LEFT",
        "d": "RIGHT","D": "RIGHT",
        # Mots complets
        "up":    "UP",   "UP":    "UP",
        "down":  "DOWN", "DOWN":  "DOWN",
        "left":  "LEFT", "LEFT":  "LEFT",
        "right": "RIGHT","RIGHT": "RIGHT",
        # Raccourcis
        "u": "UP",   "U": "UP",
        "l": "LEFT", "L": "LEFT",
        "r": "RIGHT","R": "RIGHT",
        # Flèches Unicode (si le terminal les envoie)
        "↑": "UP", "↓": "DOWN", "←": "LEFT", "→": "RIGHT",
    }

    try:
        raw = input(prompt).strip()
        if raw in KEYMAP:
            return KEYMAP[raw]
        # Essaie de traiter une séquence séparée par espaces
        # ex: "z s d q" → ["UP", "DOWN", "RIGHT", "LEFT"]
        parts = raw.split()
        if all(p in KEYMAP for p in parts):
            return parts   # retourne une liste
        print(f"  {C.GRAY}(Z=↑  S=↓  Q=←  D=→ — ou mot complet : up/down/left/right){C.RESET}")
        return None
    except (EOFError, KeyboardInterrupt):
        return None


def read_full_sequence(seq_len: int) -> list:
    """
    Lit toute la séquence d'un coup ou direction par direction.
    Supporte :
      - Saisie direction par direction (touche + Entrée)
      - Saisie de toute la séquence d'un coup : "z s d q z"
    Retourne une liste de directions de longueur seq_len.
    """
    print(f"\n  {C.CYAN}Tapez {seq_len} directions (Z=↑  S=↓  Q=←  D=→){C.RESET}")
    print(f"  {C.GRAY}(une par une avec Entrée, ou tout en une ligne séparé par espaces){C.RESET}\n")

    result = []

    while len(result) < seq_len:
        remaining = seq_len - len(result)
        prompt    = f"  [{len(result)+1}/{seq_len}] > "
        inp       = read_direction(prompt)

        if inp is None:
            continue

        if isinstance(inp, list):
            # Saisie multiple d'un coup
            # On prend le bon nombre de directions
            for d in inp[:remaining]:
                result.append(d)
                print_reproduce_prompt(["?"] * seq_len, result)
        else:
            result.append(inp)
            print_reproduce_prompt(["?"] * seq_len, result)

    return result


# ==============================================================
# PROCESSEUR DE DONNÉES CAPTEURS — lit la queue en continu
# ==============================================================

class SensorProcessor:
    """
    Lit la queue de données capteurs et met à jour les métriques
    en temps réel (FC, RR, gestes ACC).
    Tourne dans un thread séparé pour ne pas bloquer l'interface.
    """

    def __init__(self, data_queue):
        self.data_queue  = data_queue
        self.ppg_proc    = PPGProcessor()
        self.pzt_proc    = PZTProcessor()

        # Dernières métriques calculées (thread-safe grâce au GIL Python)
        self.heart_rate  = None   # bpm
        self.resp_rate   = None   # rpm
        self.simulating  = False  # toujours False (simulation supprimée)

        # Buffers pour affichage ASCII
        self.ppg_display = deque(maxlen=40)
        self.pzt_display = deque(maxlen=40)

        # Toutes les données brutes de la session (pour CSV et graphs)
        self.all_samples = []

        # Thread
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        """Boucle de traitement — tourne tant que le jeu est actif."""
        while not self._stop.is_set():
            try:
                # Vider la queue rapidement (plusieurs samples en attente)
                batch = []
                while not self.data_queue.empty() and len(batch) < 50:
                    batch.append(self.data_queue.get_nowait())

                for sample in batch:
                    ts = sample["ts"]

                    # Stocker pour export CSV
                    self.all_samples.append(sample)

                    # Mettre à jour les buffers d'affichage
                    self.ppg_display.append(sample["ppg"])
                    self.pzt_display.append(sample["pzt"])

                    # Traitement PPG → FC
                    hr = self.ppg_proc.update(sample["ppg"], ts)
                    if hr:
                        self.heart_rate = hr

                    # Traitement PZT → RR
                    rr = self.pzt_proc.update(sample["pzt"], ts)
                    if rr:
                        self.resp_rate = rr

                    # ACC non utilisé (clavier utilisé à la place)

            except queue.Empty:
                pass
            except Exception as e:
                print(f"[sensor] Erreur traitement : {e}")

            time.sleep(0.02)   # 50 Hz de traitement suffit


# ==============================================================
# MOTEUR DU JEU PRINCIPAL
# ==============================================================

class ChunkyMemoGame:
    """
    Moteur du jeu ChunkyMemo en mode console.

    Structure :
      - 2 modes : NORMAL et CHUNKING
      - Séquences de flèches croissantes (niveau 1 = 3 flèches)
      - Acquisition BITalino en parallèle
      - Export CSV + graphiques à la fin
    """

    MEMORIZE_SEC  = 3.0   # secondes d'affichage de la séquence
    FEEDBACK_SEC  = 1.5   # secondes d'affichage du feedback

    def __init__(self):
        # Queue partagée : acquisition → traitement
        self.data_queue   = queue.Queue(maxsize=config.QUEUE_MAXSIZE)

        # Thread acquisition BITalino
        self.acq_thread   = AcquisitionThread(self.data_queue)

        # Processeur signaux (tourne en parallèle)
        self.sensor_proc  = SensorProcessor(self.data_queue)

        # État du jeu
        self.level        = 1
        self.score        = 0
        self.mode         = "NORMAL"
        self.running      = True

        # Sessions de données pour les graphiques comparatifs
        self.session_normal   = None
        self.session_chunking = None

    def start(self):
        """Point d'entrée principal."""
        # Démarrer l'acquisition immédiatement
        self.acq_thread.start()
        self.sensor_proc.start()

        # Attendre 1 seconde que le BITalino se connecte
        print("\n[INFO] Démarrage de l'acquisition capteurs...")
        time.sleep(1.5)

        # Menu principal
        self._show_menu()

    def _show_menu(self):
        """Menu de sélection du mode."""
        while self.running:
            clear()
            sim_status = "SIMULATION" if self.acq_thread.simulating else "BITalino LIVE"
            print(f"""
{C.BOLD}{'='*60}{C.RESET}
{C.BOLD}  ChunkyMemo — Jeu de mémoire de travail{C.RESET}
  Capteurs : {C.GREEN}{sim_status}{C.RESET}
{C.BOLD}{'='*60}{C.RESET}

  Basé sur : Miller (1956) — La mémoire de travail
  est limitée à {C.YELLOW}7 ± 2{C.RESET} éléments.

  Le chunking permet de dépasser cette limite en
  regroupant les éléments en blocs mémorisables.

{C.BOLD}  Choisissez un mode :{C.RESET}

    {C.CYAN}[1]{C.RESET} Mode Normal    — flèches une par une
    {C.CYAN}[2]{C.RESET} Mode Chunking  — flèches groupées par paires
    {C.CYAN}[3]{C.RESET} Les deux modes (Normal puis Chunking)
    {C.CYAN}[Q]{C.RESET} Quitter

{C.BOLD}{'='*60}{C.RESET}
""")
            choice = input("  Votre choix : ").strip().upper()

            if choice == "1":
                self._run_session("NORMAL")
            elif choice == "2":
                self._run_session("CHUNKING")
            elif choice == "3":
                self._run_session("NORMAL")
                print(f"\n  {C.CYAN}Session NORMAL terminée. Démarrage CHUNKING dans 3s...{C.RESET}")
                time.sleep(3)
                self._run_session("CHUNKING")
                self._show_final_comparison()
            elif choice == "Q":
                self._quit()
                return
            else:
                print(f"  {C.GRAY}(tapez 1, 2, 3 ou Q){C.RESET}")
                time.sleep(1)

    def _run_session(self, mode: str):
        """Lance une session complète dans un mode donné."""
        self.mode  = mode
        self.level = 1
        self.score = 0

        session = SessionData(mode)

        # Partager le niveau avec la simulation (pour moduler le signal)
        self.acq_thread.current_level = self.level

        clear()
        print(f"""
{C.BOLD}{'='*60}{C.RESET}
{C.BOLD}  Mode : {C.CYAN}{mode}{C.RESET}
{C.BOLD}{'='*60}{C.RESET}

  {C.YELLOW}Règles :{C.RESET}
  1. Une séquence de flèches s'affiche {self.MEMORIZE_SEC:.0f} secondes
  2. Elle disparaît
  3. Vous reproduisez au clavier :
     Z = haut   S = bas
     Q = gauche   D = droite
  4. Chaque niveau ajoute une flèche

{C.BOLD}{'='*60}{C.RESET}
""")
        input("  Appuyez sur Entrée pour commencer...")

        game_over = False
        while not game_over:
            seq_len = self.level + 2   # niveau 1 = 3 flèches, niveau 5 = 7 flèches

            # Informer la simulation du niveau courant
            self.acq_thread.current_level = self.level

            # Marquer le début du niveau dans la session
            session.start_level(self.level)

            # ── Phase MÉMORISATION ─────────────────────────────────
            self._show_memorize(seq_len)

            # Générer la séquence
            sequence = [random.choice(["UP","DOWN","LEFT","RIGHT"])
                        for _ in range(seq_len)]

            # Afficher la séquence
            clear()
            print_header(self.mode, self.level, self.score,
                         self.sensor_proc.heart_rate,
                         self.sensor_proc.resp_rate,
                         self.acq_thread.simulating)
            print_sequence(sequence, self.mode, "Mémorisez !")
            print_sensor_bar(self.sensor_proc.ppg_display,
                             self.sensor_proc.pzt_display)

            # Afficher un compte à rebours
            for remaining in range(int(self.MEMORIZE_SEC), 0, -1):
                print(f"\r  {C.YELLOW}Disparaît dans {remaining}s...{C.RESET}  ", end="", flush=True)
                time.sleep(1)
            print()

            # ── Phase REPRODUCTION — via clavier ──────────────────
            # Le joueur tape Z/S/Q/D pour reproduire la séquence.
            player_input = self._collect_keyboard(seq_len)

            # ── Vérification ───────────────────────────────────────
            success = (player_input == sequence)

            clear()
            print_header(self.mode, self.level, self.score,
                         self.sensor_proc.heart_rate,
                         self.sensor_proc.resp_rate,
                         self.acq_thread.simulating)
            print_feedback(success, sequence, player_input)

            # Enregistrer les métriques du niveau
            session.end_level(
                success       = success,
                hr_bpm        = self.sensor_proc.heart_rate,
                rr_rpm        = self.sensor_proc.resp_rate,
                ppg_amplitude = self.sensor_proc.ppg_proc.get_amplitude(),
                resp_pauses   = 0,
            )

            if success:
                self.score += seq_len * 10
                print(f"  {C.GREEN}+{seq_len*10} points → Score total : {self.score}{C.RESET}")
                self.level += 1
                time.sleep(self.FEEDBACK_SEC)
            else:
                game_over = True
                print(f"\n  {C.RED}{C.BOLD}GAME OVER{C.RESET}")
                print(f"  Niveau atteint : {C.YELLOW}{self.level}{C.RESET}  "
                      f"Score : {C.GREEN}{self.score}{C.RESET}")

                # Commentaire sur la limite de Miller
                seq_at_fail = seq_len
                if seq_at_fail >= 7:
                    print(f"\n  {C.CYAN}→ {seq_at_fail} éléments : vous avez atteint ou dépassé")
                    print(f"    la limite de Miller (7±2). Normal de se tromper !{C.RESET}")
                elif seq_at_fail >= 5:
                    print(f"\n  {C.CYAN}→ Vous approchez de la limite de mémoire de travail.{C.RESET}")

                time.sleep(2)

        # Sauvegarder la session
        if mode == "NORMAL":
            self.session_normal   = session
        else:
            self.session_chunking = session

        # Export CSV de la session
        self._export_session_csv(session)

        # Graphique de la session
        self._show_session_graphs(session)

        return session

    def _show_memorize(self, seq_len: int):
        """Affiche une animation de préparation avant la séquence."""
        clear()
        print_header(self.mode, self.level, self.score,
                     self.sensor_proc.heart_rate,
                     self.sensor_proc.resp_rate,
                     self.acq_thread.simulating)
        print(f"\n  {C.YELLOW}Niveau {self.level} — {seq_len} flèches à mémoriser{C.RESET}")
        print(f"\n  {C.GRAY}Préparez-vous...{C.RESET}\n")
        print_sensor_bar(self.sensor_proc.ppg_display,
                         self.sensor_proc.pzt_display)
        time.sleep(1.0)

    def _collect_keyboard(self, seq_len: int) -> list:
        """
        Lit seq_len directions au clavier et les retourne.
        Remplace _collect_gestures (ACC supprime).

        Touches : Z=↑  S=↓  Q=←  D=→  (ou mots complets up/down/left/right)
        L'écran affiche la progression en temps réel + les mini-graphiques capteurs.
        """
        PLACEHOLDER = ["?"] * seq_len

        # Affichage de la phase
        clear()
        print_header(
            self.mode, self.level, self.score,
            self.sensor_proc.heart_rate,
            self.sensor_proc.resp_rate,
            self.acq_thread.simulating
        )
        print(f"\n  {C.BOLD}Reproduisez la séquence au clavier !{C.RESET}")
        print(f"  {C.GRAY}Z=↑  S=↓  Q=←  D=→  (une par une + Entrée, ou tout d'un coup){C.RESET}\n")
        print_sensor_bar(self.sensor_proc.ppg_display, self.sensor_proc.pzt_display)
        print()

        player_input = read_full_sequence(seq_len)

        # Affichage final récapitulatif
        clear()
        print_header(
            self.mode, self.level, self.score,
            self.sensor_proc.heart_rate,
            self.sensor_proc.resp_rate,
            self.acq_thread.simulating
        )
        print(f"\n  {C.BOLD}Séquence complète :{C.RESET}")
        print_reproduce_prompt(PLACEHOLDER, player_input)
        time.sleep(0.5)

        return player_input

    def _export_session_csv(self, session: SessionData):
        """
        Sauvegarde les données brutes de la session en CSV.
        Deux fichiers :
          - session_MODE_DATETIME_levels.csv  → métriques par niveau
          - session_MODE_DATETIME_raw.csv     → tous les échantillons
        """
        os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        base   = f"{config.CSV_OUTPUT_DIR}/session_{session.mode}_{ts_str}"

        # Fichier 1 : métriques par niveau
        levels_file = f"{base}_levels.csv"
        if session.levels:
            with open(levels_file, "w", newline="", encoding="utf-8") as f:
                fieldnames = ["level", "mode", "success", "seq_len",
                              "hr_bpm", "rr_rpm", "ppg_amplitude",
                              "duration_sec", "ts_start", "ts_end"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for lv in session.levels:
                    row = {k: lv.get(k, "") for k in fieldnames}
                    writer.writerow(row)
            print(f"  {C.GREEN}✓ Niveaux sauvegardés : {levels_file}{C.RESET}")

        # Fichier 2 : signaux bruts
        raw_file = f"{base}_raw.csv"
        samples  = self.sensor_proc.all_samples
        if samples:
            with open(raw_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ts","nSeq","acc_x","acc_y","ppg","pzt"])
                writer.writeheader()
                writer.writerows(
                    {k: s.get(k, "") for k in ["ts","nSeq","acc_x","acc_y","ppg","pzt"]}
                    for s in samples
                )
            print(f"  {C.GREEN}✓ Signaux bruts sauvegardés : {raw_file}{C.RESET}")

        input(f"\n  Appuyez sur Entrée pour continuer...")

    def _show_session_graphs(self, session: SessionData):
        """Génère les graphiques matplotlib de la session."""
        try:
            import matplotlib
            matplotlib.use("TkAgg" if os.name != "nt" else "Qt5Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print(f"  {C.GRAY}(matplotlib non disponible — graphiques ignorés){C.RESET}")
            return

        if not session.levels:
            return

        # Données par niveau
        levels  = [lv["level"] for lv in session.levels]
        hr_vals = [lv.get("hr_bpm") for lv in session.levels]
        rr_vals = [lv.get("rr_rpm") for lv in session.levels]

        # Signaux bruts collectés
        samples = self.sensor_proc.all_samples
        if not samples:
            return

        ts_arr  = [s["ts"] - samples[0]["ts"] for s in samples]
        ppg_arr = [s["ppg"] for s in samples]
        pzt_arr = [s["pzt"] for s in samples]

        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        fig.suptitle(
            f"ChunkyMemo — Session {session.mode}\n"
            f"Niveau max: {max(levels)}  |  "
            f"{'SIMULATION' if self.acq_thread.simulating else 'DONNÉES RÉELLES'}",
            fontsize=13
        )

        # Signal PPG brut
        axes[0, 0].plot(ts_arr, ppg_arr, color="tab:red", linewidth=0.6, alpha=0.8)
        # Annotations des niveaux
        for (t_ev, lv) in session.level_events:
            axes[0, 0].axvline(x=t_ev, color="gray", alpha=0.4, linewidth=1)
            axes[0, 0].text(t_ev, max(ppg_arr)*0.98, f"N{lv}",
                            fontsize=7, color="gray", ha="center")
        axes[0, 0].set_title("Signal PPG brut (pouls)")
        axes[0, 0].set_xlabel("Temps (s)")
        axes[0, 0].set_ylabel("Amplitude")

        # Signal PZT brut
        axes[0, 1].plot(ts_arr, pzt_arr, color="tab:orange", linewidth=0.6, alpha=0.8)
        for (t_ev, lv) in session.level_events:
            axes[0, 1].axvline(x=t_ev, color="gray", alpha=0.4, linewidth=1)
            axes[0, 1].text(t_ev, max(pzt_arr)*0.98, f"N{lv}",
                            fontsize=7, color="gray", ha="center")
        axes[0, 1].set_title("Signal PZT brut (respiration)")
        axes[0, 1].set_xlabel("Temps (s)")
        axes[0, 1].set_ylabel("Amplitude")

        # FC par niveau
        hr_clean = [(l, v) for l, v in zip(levels, hr_vals) if v is not None]
        if hr_clean:
            lv_hr, val_hr = zip(*hr_clean)
            axes[1, 0].plot(lv_hr, val_hr, "o-", color="tab:red",
                            linewidth=2, markersize=7)
            axes[1, 0].axvline(x=5, color="purple", linestyle="--",
                               alpha=0.5, label="Limite 7±2 (Miller)")
            axes[1, 0].set_title("Fréquence cardiaque par niveau")
            axes[1, 0].set_xlabel("Niveau")
            axes[1, 0].set_ylabel("FC (bpm)")
            axes[1, 0].legend(fontsize=8)
            axes[1, 0].grid(True, alpha=0.3)

        # RR par niveau
        rr_clean = [(l, v) for l, v in zip(levels, rr_vals) if v is not None]
        if rr_clean:
            lv_rr, val_rr = zip(*rr_clean)
            axes[1, 1].plot(lv_rr, val_rr, "o-", color="tab:orange",
                            linewidth=2, markersize=7)
            axes[1, 1].axvline(x=5, color="purple", linestyle="--",
                               alpha=0.5, label="Limite 7±2 (Miller)")
            axes[1, 1].set_title("Rythme respiratoire par niveau")
            axes[1, 1].set_xlabel("Niveau")
            axes[1, 1].set_ylabel("Resp. (cycles/min)")
            axes[1, 1].legend(fontsize=8)
            axes[1, 1].grid(True, alpha=0.3)

        plt.tight_layout()

        # Sauvegarder
        os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
        ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
        fig_path = f"{config.CSV_OUTPUT_DIR}/graph_{session.mode}_{ts_str}.png"
        plt.savefig(fig_path, dpi=120, bbox_inches="tight")
        print(f"\n  {C.GREEN}✓ Graphique sauvegardé : {fig_path}{C.RESET}")

        plt.show(block=False)
        plt.pause(3)
        plt.close()

    def _show_final_comparison(self):
        """Graphique comparatif final si les deux modes ont été joués."""
        if not (self.session_normal and self.session_chunking):
            return

        print(f"\n  {C.CYAN}Génération du rapport comparatif Normal vs Chunking...{C.RESET}")
        try:
            from analysis import generate_comparison_report
            os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
            ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
            fig_path = f"{config.CSV_OUTPUT_DIR}/rapport_comparatif_{ts_str}.png"
            generate_comparison_report(
                self.session_normal,
                self.session_chunking,
                save_path=fig_path
            )
            print(f"  {C.GREEN}✓ Rapport sauvegardé : {fig_path}{C.RESET}")
        except Exception as e:
            print(f"  {C.GRAY}(Rapport comparatif non disponible : {e}){C.RESET}")

        input("\n  Appuyez sur Entrée pour revenir au menu...")

    def _quit(self):
        """Arrêt propre."""
        print(f"\n  {C.YELLOW}Arrêt en cours...{C.RESET}")
        self.acq_thread.stop()
        self.sensor_proc.stop()
        time.sleep(0.5)
        print(f"  {C.GREEN}Au revoir !{C.RESET}\n")


# ==============================================================
# POINT D'ENTRÉE
# ==============================================================

if __name__ == "__main__":
    # Gestion Ctrl+C propre
    def _handle_sigint(sig, frame):
        print(f"\n\n  {C.YELLOW}Interruption — fermeture propre...{C.RESET}")
        sys.exit(0)
    os_signal.signal(os_signal.SIGINT, _handle_sigint)

    # Validation config
    print()
    if not config.validate():
        print("Corrigez config.py avant de continuer.")
        sys.exit(1)
    print()

    # Lancement
    game = ChunkyMemoGame()
    game.start()
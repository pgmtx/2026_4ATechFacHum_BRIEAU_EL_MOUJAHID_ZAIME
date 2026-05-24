"""
==============================================================
ChunkyMemo — acquisition.py
==============================================================
Acquisition REELLE uniquement via BITalino + plux.
Pas de simulation — si plux n'est pas disponible ou si le
BITalino n'est pas connecté, le programme s'arrête avec un
message d'erreur clair.

Capteurs actifs : PPG (port 3) + PZT (port 4)

Comment tester :
  python acquisition.py
  → connecte le BITalino, 10 secondes d'acquisition,
    affiche les graphiques PPG + PZT + flèches clavier
==============================================================
"""

import logging
import os
import platform
import queue
import sys
import threading
import time

import config

# ==============================================================
# CHEMIN VERS plux.pyd
# ==============================================================
# plux.pyd (Windows) ou plux.so (Linux/Mac) doit etre dans le
# meme dossier que ce fichier.
# On ajoute le dossier du script dans sys.path pour que Python
# le trouve automatiquement.

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ==============================================================
# IMPORT PLUX — obligatoire, pas de fallback
# ==============================================================

try:
    import plux

    _ = plux.SignalsDev
    logging.info("[acquisition] plux charge avec succès")
except (ImportError, AttributeError):
    logging.exception("[acquisition] ERREUR : plux.pyd introuvable")
    logging.error(f"  Verifiez que plux.pyd est dans : {SCRIPT_DIR}")
    pv = platform.python_version().split(".")
    suffix = platform.architecture()[0][:2] + "_" + pv[0] + pv[1]
    os_name = platform.system()
    if os_name == "Windows":
        path = f"Win{suffix}"
    elif os_name == "Darwin":
        path = f"MacOS/Intel{pv[0]}{pv[1]}"
    else:
        path = "Linux64"
    logging.error(
        f"  https://github.com/pluxbiosignals/python-samples/tree/master/PLUX-API-Python3/{path}"
    )
    sys.exit(1)


# ==============================================================
# CLASSE DEVICE — sous-classe de plux.SignalsDev
# Identique au NewDevice de l'exemple de départ, données vers queue
# ==============================================================


class ChunkyDevice(plux.SignalsDev):
    """
    Sous-classe de plux.SignalsDev.
    Identique au NewDevice de l'exemple de départ — __init__ prend SEULEMENT address.
    data_queue et stop_event sont assignes depuis run() apres creation.

    ACTIVE_PORTS = [3, 4]
      data[0] = port 3 = PPG   (config.IDX_PPG = 0)
      data[1] = port 4 = PZT   (config.IDX_PZT = 1)
    """

    def __init__(self, address: str):
        # PAS de self, PAS d'autres arguments — c'est la convention plux
        plux.SignalsDev.__init__(address)
        # Ces attributs seront assignes depuis run() apres creation :
        # self.data_queue, self.stop_event
        self.data_queue = None
        self.stop_event = None
        self.duration = config.DURATION_MAX
        self.frequency = config.SAMPLING_RATE
        self._last_print = 0

    def onRawFrame(self, nSeq, data):
        """
        Appelé automatiquement par plux a chaque frame (100x/seconde).

        data[config.IDX_PPG] = data[0] = valeur PPG brute
        data[config.IDX_PZT] = data[1] = valeur PZT brute

        Retourne True  → arrête device.loop()
        Retourne False → continue
        """
        sample = {
            "ts": time.perf_counter(),
            "nSeq": nSeq,  # numero de frame depuis le debut
            "ppg": int(data[config.IDX_PPG]),  # pouls — valeur brute 0-65535
            "pzt": int(data[config.IDX_PZT]),  # respiration — valeur brute 0-65535
            "raw": list(data),  # toutes les valeurs brutes du frame
        }

        try:
            self.data_queue.put_nowait(sample)  # non bloquant
        except queue.Full:
            pass  # queue pleine → on perd l echantillon plutot que de bloquer

        # Debug : 1 ligne par seconde dans la console
        now = time.perf_counter()
        if now - self._last_print >= 1.0:
            logging.debug(
                f"[BITalino] nSeq={nSeq:6d} | "
                f"ppg={sample['ppg']:5d} | "
                f"pzt={sample['pzt']:5d}"
            )
            self._last_print = now

        return self.stop_event.is_set() or (nSeq > self.duration * self.frequency)


# ==============================================================
# THREAD D'ACQUISITION
# ==============================================================


class AcquisitionThread(threading.Thread):
    """
    Thread daemon — acquisition BITalino en arriere-plan.
    Le jeu tourne dans le thread principal, celui-ci lit les capteurs.

    Utilisation :
        q = queue.Queue(maxsize=2000)
        t = AcquisitionThread(q)
        t.start()
        # ... jeu en cours ...
        t.stop()
    """

    def __init__(self, data_queue: queue.Queue):
        super().__init__(daemon=True)  # s arrete avec le programme principal
        self.data_queue = data_queue
        self.stop_event = threading.Event()
        self.device = None

    def run(self):
        """Acquisition reelle uniquement — pas de simulation."""
        try:
            logging.info(f"[acquisition] Connexion à {config.MAC_ADDRESS} ...")
            # On assigne data_queue et stop_event comme attributs
            self.device = ChunkyDevice(config.MAC_ADDRESS)
            self.device.data_queue = self.data_queue
            self.device.stop_event = self.stop_event
            self.device.duration = config.DURATION_MAX
            self.device.frequency = config.SAMPLING_RATE

            self.device.start(
                config.SAMPLING_RATE, config.ACTIVE_PORTS, config.RESOLUTION
            )
            logging.info(
                f"[acquisition] Démarrage — "
                f"ports={config.ACTIVE_PORTS} @ {config.SAMPLING_RATE}Hz"
            )

            # device.loop() bloque jusqu a ce que onRawFrame retourne True
            self.device.loop()

        except Exception:
            logging.exception("[acquisition] ERREUR connexion BITalino")
            logging.error("[acquisition] Vérifiez les éléments suivants :")
            logging.error(
                "  1. Le capteur BITalino est-il allumé ? Le bluetooth est-il actif ?"
            )
            logging.error(
                f"  2. L'adresse MAC dans config.py est-elle correcte ? ({config.MAC_ADDRESS})"
            )
            logging.error(
                f"  3. Les ports sont-ils correctement branchés ? ({config.ACTIVE_PORTS})"
            )
        finally:
            if self.device:
                try:
                    self.device.stop()
                    self.device.close()
                    logging.info("[acquisition] Connexion fermée proprement")
                except Exception:
                    pass

    def stop(self):
        """Arret propre — signal a onRawFrame de retourner True."""
        logging.info("[acquisition] Arrêt demandé...")
        self.stop_event.set()


# ==============================================================
# TEST STANDALONE — python acquisition.py
# ==============================================================

if __name__ == "__main__":
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    logging.info("=" * 50)
    logging.info("TEST ACQUISITION RÉELLE — ChunkyMemo")
    logging.info("=" * 50 + "\n\n")

    if not config.validate():
        sys.exit(1)

    logging.info(f"  - PPG branche sur port {config.ACTIVE_PORTS[config.IDX_PPG]}")
    logging.info(f"  - PZT branche sur port {config.ACTIVE_PORTS[config.IDX_PZT]}\n")
    logging.info(
        "Pendant le test : tapez Z/S/Q/D + [entrée] pour marquer des flèches\n"
    )
    input("Appuyez sur [entrée] pour commencer...")
    logging.info("")

    TEST_DURATION = 30
    WINDOW_SHOW = 10.0
    REFRESH_SEC = 0.1

    KEYMAP = {
        "z": "UP",
        "Z": "UP",
        "s": "DOWN",
        "S": "DOWN",
        "q": "LEFT",
        "Q": "LEFT",
        "d": "RIGHT",
        "D": "RIGHT",
    }
    ARROW_LABEL = {
        "UP": "fleche haut",
        "DOWN": "fleche bas",
        "LEFT": "fleche gauche",
        "RIGHT": "fleche droite",
    }
    ARROW_COLOR = {"UP": "green", "DOWN": "red", "LEFT": "blue", "RIGHT": "purple"}
    DIR_Y = {"LEFT": 0, "DOWN": 1, "UP": 2, "RIGHT": 3}

    all_ppg, all_pzt, all_ts = [], [], []
    key_events = []
    key_events_lock = threading.Lock()
    stop_flag = [False]  # utilise pour arreter la boucle principale

    # Desactiver les raccourcis clavier par defaut de matplotlib
    # qui entrent en conflit avec nos touches de jeu :
    #   s → save figure    q → quit    z/Z → zoom
    #   d → xscale         g → grid    p → pan
    import matplotlib

    for key in ["s", "q", "z", "Z", "d", "g", "p", "f", "h", "l"]:
        if key in matplotlib.rcParams.get("keymap.save", []):
            matplotlib.rcParams["keymap.save"].remove(key)
        if key in matplotlib.rcParams.get("keymap.quit", []):
            matplotlib.rcParams["keymap.quit"].remove(key)
        if key in matplotlib.rcParams.get("keymap.zoom", []):
            matplotlib.rcParams["keymap.zoom"].remove(key)
        if key in matplotlib.rcParams.get("keymap.xscale", []):
            matplotlib.rcParams["keymap.xscale"].remove(key)
        if key in matplotlib.rcParams.get("keymap.yscale", []):
            matplotlib.rcParams["keymap.yscale"].remove(key)
        if key in matplotlib.rcParams.get("keymap.grid", []):
            matplotlib.rcParams["keymap.grid"].remove(key)
        if key in matplotlib.rcParams.get("keymap.pan", []):
            matplotlib.rcParams["keymap.pan"].remove(key)
        if key in matplotlib.rcParams.get("keymap.fullscreen", []):
            matplotlib.rcParams["keymap.fullscreen"].remove(key)
        if key in matplotlib.rcParams.get("keymap.home", []):
            matplotlib.rcParams["keymap.home"].remove(key)
        if key in matplotlib.rcParams.get("keymap.back", []):
            matplotlib.rcParams["keymap.back"].remove(key)

    # Detection des touches directement dans la fenetre matplotlib
    # input() dans un thread ne marche pas sous Windows quand matplotlib est actif
    # mpl_connect capte les touches peu importe ou est le focus
    def on_key_press(event):
        ts = time.perf_counter() - start
        d = KEYMAP.get(event.key)
        if d:
            with key_events_lock:
                key_events.append((ts, d))
            logging.info(f"  -> {ARROW_LABEL[d]} a t={ts:.2f}s")

    # Demarrer acquisition
    data_q = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
    acq = AcquisitionThread(data_q)
    acq.start()
    start = time.perf_counter()

    # Graphique temps reel — 3 subplots
    plt.ion()
    fig, (ax_ppg, ax_pzt, ax_keys) = plt.subplots(3, 1, figsize=(14, 9), sharex=False)
    fig.suptitle("Acquisition temps reel ChunkyMemo", fontsize=12)

    (line_ppg,) = ax_ppg.plot([], [], color="tab:red", linewidth=0.9)
    (line_pzt,) = ax_pzt.plot([], [], color="tab:orange", linewidth=0.9)

    ax_ppg.set_ylabel("PPG (pouls)")
    ax_ppg.set_title("Photoplethysmographie")
    ax_ppg.grid(True, alpha=0.3)

    ax_pzt.set_ylabel("PZT (respiration)")
    ax_pzt.set_title("Respiration piezzoelectrique")
    ax_pzt.grid(True, alpha=0.3)

    ax_keys.set_ylabel("Fleches")
    ax_keys.set_xlabel("Temps (secondes)")
    ax_keys.set_title("Fleches tapees au clavier")
    ax_keys.set_ylim(-0.5, 3.5)
    ax_keys.set_yticks([0, 1, 2, 3])
    ax_keys.set_yticklabels(["gauche", "bas", "haut", "droite"], fontsize=9)
    ax_keys.grid(True, alpha=0.2)

    plt.tight_layout()
    # mpl_connect capte les touches dans la fenetre matplotlib sans bloquer
    fig.canvas.mpl_connect("key_press_event", on_key_press)

    logging.info(f"Acquisition en cours ({TEST_DURATION}s)...")
    logging.info("Cliquez sur la fenêtre et tapez Z/S/Q/D pour marquer des fleches")

    # FuncAnimation — rafraichit le graphique a interval regulier
    # sans jamais bloquer la fenetre ni la boucle d'evenements
    from matplotlib.animation import FuncAnimation

    def update_graph(frame):
        # Vider la queue — prendre tous les echantillons disponibles
        while not data_q.empty():
            try:
                s = data_q.get_nowait()
                all_ppg.append(s["ppg"])
                all_pzt.append(s["pzt"])
                all_ts.append(s["ts"] - start)
            except queue.Empty:
                break

        if len(all_ts) < 2:
            return line_ppg, line_pzt

        t_now = all_ts[-1]
        t_min = max(0, t_now - WINDOW_SHOW)

        # Mettre a jour PPG et PZT
        mask = [i for i, t in enumerate(all_ts) if t >= t_min]
        if mask:
            ts_w = [all_ts[i] for i in mask]
            ppg_w = [all_ppg[i] for i in mask]
            pzt_w = [all_pzt[i] for i in mask]

            line_ppg.set_data(ts_w, ppg_w)
            line_pzt.set_data(ts_w, pzt_w)

            ax_ppg.set_xlim(t_min, t_now + 0.5)
            ax_ppg.set_ylim(min(ppg_w) - 5, max(ppg_w) + 5)
            ax_pzt.set_xlim(t_min, t_now + 0.5)
            ax_pzt.set_ylim(min(pzt_w) - 5, max(pzt_w) + 5)

        # Mettre a jour le subplot fleches
        ax_keys.cla()
        ax_keys.set_ylabel("Fleches")
        ax_keys.set_xlabel("Temps (secondes)")
        ax_keys.set_title("Fleches tapees au clavier")
        ax_keys.set_ylim(-0.5, 3.5)
        ax_keys.set_yticks([0, 1, 2, 3])
        ax_keys.set_yticklabels(["gauche", "bas", "haut", "droite"], fontsize=9)
        ax_keys.set_xlim(t_min, t_now + 0.5)
        ax_keys.grid(True, alpha=0.2)

        with key_events_lock:
            keys_snap = list(key_events)

        for ts_k, d in keys_snap:
            if ts_k >= t_min:
                ax_keys.scatter(
                    ts_k, DIR_Y[d], color=ARROW_COLOR[d], s=120, zorder=5, marker="D"
                )
                ax_keys.annotate(
                    {"UP": "haut", "DOWN": "bas", "LEFT": "gauche", "RIGHT": "droite"}[
                        d
                    ],
                    xy=(ts_k, DIR_Y[d]),
                    fontsize=11,
                    ha="center",
                    va="bottom",
                    color=ARROW_COLOR[d],
                    fontweight="bold",
                )

        remaining = max(0, TEST_DURATION - t_now)
        fig.suptitle(
            f"Acquisition temps reel — {remaining:.0f}s restantes", fontsize=12
        )

        # Arreter l'animation quand la duree est ecoulee
        if t_now >= TEST_DURATION:
            ani.event_source.stop()

        return line_ppg, line_pzt

    # interval=100ms = 10 fps — assez rapide pour voir les signaux, assez lent pour ne pas bloquer
    ani = FuncAnimation(
        fig, update_graph, interval=100, blit=False, cache_frame_data=False
    )
    plt.show(block=True)  # block=True = attend la fin de l'animation avant de continuer

    stop_flag[0] = True  # signal d'arret de la boucle
    acq.stop()
    time.sleep(0.3)
    plt.ioff()

    with key_events_lock:
        captured_keys = list(key_events)

    if not all_ppg:
        logging.error(
            "AUCUNE donnée recue — vérifiez la connexion avec le capteur BITalino"
        )
        sys.exit(1)

    logging.info(f"\nCollecte      : {len(all_ppg)} echantillons")
    logging.info(f"Freq. effect. : {len(all_ppg) / TEST_DURATION:.1f} Hz")
    logging.info(f"Fleches tapees: {len(captured_keys)}")
    logging.info(f"PPG amplitude : {max(all_ppg) - min(all_ppg)}")
    logging.info(f"PZT amplitude : {max(all_pzt) - min(all_pzt)}")

    # Graphique final — session complete
    fig2, (ax2_ppg, ax2_pzt, ax2_keys) = plt.subplots(
        3, 1, figsize=(14, 9), sharex=True
    )
    fig2.suptitle(
        f"Session complete — {TEST_DURATION}s  |  {len(captured_keys)} fleches",
        fontsize=13,
    )

    ax2_ppg.plot(all_ts, all_ppg, color="tab:red", linewidth=0.8)
    ax2_ppg.set_ylabel("PPG (pouls)")
    ax2_ppg.set_title("Photoplethysmographie")
    ax2_ppg.grid(True, alpha=0.3)

    ax2_pzt.plot(all_ts, all_pzt, color="tab:orange", linewidth=0.8)
    ax2_pzt.set_ylabel("PZT (respiration)")
    ax2_pzt.set_title("Respiration piezzoelectrique")
    ax2_pzt.grid(True, alpha=0.3)

    ax2_keys.set_ylabel("Fleches")
    ax2_keys.set_xlabel("Temps (secondes)")
    ax2_keys.set_title("Fleches tapees")
    ax2_keys.set_ylim(-0.5, 3.5)
    ax2_keys.set_yticks([0, 1, 2, 3])
    ax2_keys.set_yticklabels(["gauche", "bas", "haut", "droite"], fontsize=9)
    ax2_keys.grid(True, alpha=0.2)

    for ts_k, d in captured_keys:
        col = ARROW_COLOR[d]
        ax2_ppg.axvline(x=ts_k, color=col, linewidth=1.2, alpha=0.6, linestyle="--")
        ax2_pzt.axvline(x=ts_k, color=col, linewidth=1.2, alpha=0.6, linestyle="--")
        ax2_keys.scatter(ts_k, DIR_Y[d], color=col, s=120, zorder=5, marker="D")
        ax2_keys.annotate(
            {"UP": "haut", "DOWN": "bas", "LEFT": "gauche", "RIGHT": "droite"}[d],
            xy=(ts_k, DIR_Y[d]),
            fontsize=11,
            ha="center",
            va="bottom",
            color=col,
            fontweight="bold",
        )

    if captured_keys:
        patches = [
            mpatches.Patch(color=ARROW_COLOR[d], label=ARROW_LABEL[d])
            for d in ["UP", "DOWN", "LEFT", "RIGHT"]
            if any(ev[1] == d for ev in captured_keys)
        ]
        ax2_ppg.legend(handles=patches, loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.show()
    logging.info("Fermez la fenêtre pour quitter.")

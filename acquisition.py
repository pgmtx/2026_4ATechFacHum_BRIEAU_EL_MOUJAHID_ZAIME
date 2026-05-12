"""
==============================================================
ChunkyMemo — acquisition.py
==============================================================
Acquisition REELLE uniquement via BITalino + plux.
si plux n'est pas disponible ou si le
BITalino n'est pas connecté, le programme s'arrête avec un
message d'erreur clair.

Capteurs actifs : PPG (port 3) + PZT (port 4)

Comment tester :
  python acquisition.py
  → connecte le BITalino, 10 secondes d'acquisition,
    affiche les graphiques PPG + PZT + flèches clavier
==============================================================
"""

import platform
import sys
import time
import queue
import threading
import config

# ==============================================================
# IMPORT PLUX — obligatoire, pas de fallback
# ==============================================================

try:
    import plux
    _ = plux.SignalsDev
    print("[acquisition] plux charge avec succes")
except (ImportError, AttributeError):
    print("[acquisition] ERREUR : plux non installe")
    print("  Telechargez plux ici :")
    pv = platform.python_version().split(".")
    suffix = platform.architecture()[0][:2] + "_" + pv[0] + pv[1]
    os_name = platform.system()
    if os_name == "Windows":
        path = f"Win{suffix}"
    elif os_name == "Darwin":
        path = f"MacOS/Intel{pv[0]}{pv[1]}"
    else:
        path = "Linux64"
    print(f"  https://github.com/pluxbiosignals/python-samples/tree/master/PLUX-API-Python3/{path}")
    sys.exit(1)


# ==============================================================
# CLASSE DEVICE — sous-classe de plux.SignalsDev
# Identique au NewDevice du prof, données vers queue
# ==============================================================

class ChunkyDevice(plux.SignalsDev):
    """
    Sous-classe de plux.SignalsDev.
    onRawFrame envoie chaque frame dans la queue partagée.

    ACTIVE_PORTS = [3, 4]
      data[0] = port 3 = PPG   (config.IDX_PPG = 0)
      data[1] = port 4 = PZT   (config.IDX_PZT = 1)
    """

    def __init__(self, address: str, data_queue: queue.Queue,
                 stop_event: threading.Event):
        plux.SignalsDev.__init__(address)
        self.data_queue  = data_queue
        self.stop_event  = stop_event
        self.duration    = config.DURATION_MAX
        self.frequency   = config.SAMPLING_RATE
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
            "ts":   time.time(),              # horodatage Unix precis
            "nSeq": nSeq,                     # numero de frame depuis le debut
            "ppg":  int(data[config.IDX_PPG]),# pouls — valeur brute 0-65535
            "pzt":  int(data[config.IDX_PZT]),# respiration — valeur brute 0-65535
            "raw":  list(data),               # toutes les valeurs brutes du frame
        }

        try:
            self.data_queue.put_nowait(sample)  # non bloquant
        except queue.Full:
            pass   # queue pleine → on perd l echantillon plutot que de bloquer

        # Debug : 1 ligne par seconde dans la console
        now = time.time()
        if now - self._last_print >= 1.0:
            print(f"[BITalino] nSeq={nSeq:6d} | "
                  f"ppg={sample['ppg']:5d} | "
                  f"pzt={sample['pzt']:5d}")
            self._last_print = now

        # Condition d'arret — identique au prof
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
        super().__init__(daemon=True)   # s arrete avec le programme principal
        self.data_queue = data_queue
        self.stop_event = threading.Event()
        self.device     = None

    def run(self):
        """Acquisition reelle uniquement — pas de simulation."""
        try:
            print(f"[acquisition] Connexion a {config.MAC_ADDRESS} ...")
            self.device = ChunkyDevice(config.MAC_ADDRESS,
                                       self.data_queue, self.stop_event)
            self.device.duration  = config.DURATION_MAX
            self.device.frequency = config.SAMPLING_RATE

            # device.start(frequency, active_ports, resolution) — identique au prof
            self.device.start(config.SAMPLING_RATE,
                              config.ACTIVE_PORTS,
                              config.RESOLUTION)
            print(f"[acquisition] Demarre — "
                  f"ports={config.ACTIVE_PORTS} @ {config.SAMPLING_RATE}Hz")

            # device.loop() bloque jusqu a ce que onRawFrame retourne True
            self.device.loop()

        except Exception as e:
            print(f"[acquisition] ERREUR connexion BITalino : {e}")
            print("[acquisition] Verifiez :")
            print(f"  1. BITalino allume et bluetooth actif")
            print(f"  2. Adresse MAC correcte dans config.py : {config.MAC_ADDRESS}")
            print(f"  3. Ports correctement branches : {config.ACTIVE_PORTS}")
        finally:
            if self.device:
                try:
                    self.device.stop()
                    self.device.close()
                    print("[acquisition] Connexion fermee proprement")
                except Exception:
                    pass

    def stop(self):
        """Arret propre — signal a onRawFrame de retourner True."""
        print("[acquisition] Arret demande...")
        self.stop_event.set()


# ==============================================================
# TEST STANDALONE — python acquisition.py
# ==============================================================

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    print("=" * 50)
    print("TEST ACQUISITION REELLE — ChunkyMemo")
    print("=" * 50)
    print()

    if not config.validate():
        sys.exit(1)

    print()
    print("Assurez-vous que le BITalino est :")
    print("  - Allume (LED verte)")
    print("  - Bluetooth appaire a cet ordinateur")
    print(f"  - PPG branche sur port {config.ACTIVE_PORTS[config.IDX_PPG]}")
    print(f"  - PZT branche sur port {config.ACTIVE_PORTS[config.IDX_PZT]}")
    print()
    print("Pendant les 10 secondes : tapez Z/S/Q/D + Entree pour marquer des fleches")
    print()
    input("Appuyez sur Entree pour demarrer...")
    print()

    KEYMAP = {
        "z":"UP","Z":"UP","s":"DOWN","S":"DOWN",
        "q":"LEFT","Q":"LEFT","d":"RIGHT","D":"RIGHT",
    }
    ARROW_SYMBOL = {"UP":"haut","DOWN":"bas","LEFT":"gauche","RIGHT":"droite"}
    ARROW_COLOR  = {"UP":"green","DOWN":"red","LEFT":"blue","RIGHT":"purple"}

    key_events      = []
    key_events_lock = threading.Lock()

    def keyboard_listener(start_time, stop_flag):
        while not stop_flag[0]:
            try:
                raw = input()
                ts  = time.time() - start_time
                d   = KEYMAP.get(raw.strip())
                if d:
                    with key_events_lock:
                        key_events.append((ts, d))
                    print(f"  Fleche {ARROW_SYMBOL[d]} enregistree a t={ts:.2f}s")
            except (EOFError, KeyboardInterrupt):
                break

    data_q    = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
    acq       = AcquisitionThread(data_q)
    acq.start()

    TEST_DURATION = 10
    start         = time.time()
    stop_flag     = [False]

    kb_thread = threading.Thread(
        target=keyboard_listener, args=(start, stop_flag), daemon=True)
    kb_thread.start()

    all_ppg, all_pzt, all_ts = [], [], []
    print(f"Collecte en cours ({TEST_DURATION}s)...")

    while time.time() - start < TEST_DURATION:
        try:
            sample = data_q.get(timeout=0.1)
            all_ppg.append(sample["ppg"])
            all_pzt.append(sample["pzt"])
            all_ts.append(sample["ts"] - start)
        except queue.Empty:
            pass

    stop_flag[0] = True
    acq.stop()
    time.sleep(0.3)

    with key_events_lock:
        captured_keys = list(key_events)

    print()
    if not all_ppg:
        print("AUCUNE donnee recue — verifiez la connexion BITalino")
        sys.exit(1)

    print(f"Collecte      : {len(all_ppg)} echantillons")
    print(f"Freq. effect. : {len(all_ppg) / TEST_DURATION:.1f} Hz")
    print(f"Fleches tapees: {len(captured_keys)}")
    print(f"PPG — min={min(all_ppg):6d}  max={max(all_ppg):6d}  "
          f"amplitude={max(all_ppg)-min(all_ppg):6d}")
    print(f"PZT — min={min(all_pzt):6d}  max={max(all_pzt):6d}  "
          f"amplitude={max(all_pzt)-min(all_pzt):6d}")
    print()

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    fig.suptitle("Test acquisition reelle ChunkyMemo — PPG + PZT + fleches", fontsize=13)

    axes[0].plot(all_ts, all_ppg, color="tab:red", linewidth=0.8)
    axes[0].set_ylabel("PPG (pouls)")
    axes[0].set_title("Photoplethysmographie")

    axes[1].plot(all_ts, all_pzt, color="tab:orange", linewidth=0.8)
    axes[1].set_ylabel("PZT (respiration)")
    axes[1].set_xlabel("Temps (secondes)")
    axes[1].set_title("Respiration piezzoelectrique")

    for ts_k, direction in captured_keys:
        col = ARROW_COLOR[direction]
        for ax in axes:
            ax.axvline(x=ts_k, color=col, linewidth=1.5, alpha=0.7, linestyle="--")
        if all_ppg:
            axes[0].annotate(
                {"UP":"haut","DOWN":"bas","LEFT":"gauche","RIGHT":"droite"}[direction],
                xy=(ts_k, max(all_ppg)), fontsize=10, color=col,
                ha="center", va="bottom", fontweight="bold"
            )

    if captured_keys:
        patches = [mpatches.Patch(color=ARROW_COLOR[d], label=ARROW_SYMBOL[d])
                   for d in ["UP","DOWN","LEFT","RIGHT"]
                   if any(ev[1]==d for ev in captured_keys)]
        axes[0].legend(handles=patches, loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.show()
    print("Fermez la fenetre matplotlib pour quitter.")
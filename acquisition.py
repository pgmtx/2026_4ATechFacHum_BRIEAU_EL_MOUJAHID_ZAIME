"""
==============================================================
ChunkyMemo — acquisition.py
==============================================================
Gère la connexion au BITalino et l'acquisition des signaux.
Structure EXACTEMENT basée sur le main.py du professeur :
  - Sous-classe de plux.SignalsDev
  - Callback onRawFrame(nSeq, data)
  - device.start() → device.loop() → device.stop()

La seule différence : au lieu d'afficher dans matplotlib,
on envoie les données dans une queue partagée avec le jeu.

Comment tester ce fichier seul :
  python acquisition.py
  → démarre 10 secondes d'acquisition et affiche les valeurs
  → si plux n'est pas dispo, affiche des données simulées

Omar / Salma : si les valeurs sont toutes à 0 ou plates,
vérifiez les numéros de ports dans config.py
==============================================================
"""

import platform
import sys
import time
import queue
import threading
import math
import random
from collections import deque

# Import de notre configuration centrale
import config

# ==============================================================
# IMPORT PLUX — même logique que main.py du prof
# ==============================================================

try:
    import plux
    _ = plux.SignalsDev   # vérifie que le fichier .so/.dll est présent
    PLUX_AVAILABLE = True
    print("[acquisition] plux chargé avec succès")
except (ImportError, AttributeError):
    PLUX_AVAILABLE = False
    print("[acquisition] plux non disponible → mode simulation activé")
    print(f"[acquisition] Télécharger plux ici :")
    print(f"  https://github.com/pluxbiosignals/python-samples/tree/master/"
          f"PLUX-API-Python3/{config.OS_DIC.get(platform.system(), 'Linux64')}")


# ==============================================================
# CLASSE DEVICE — sous-classe de plux.SignalsDev
# Structure identique au NewDevice du prof, adaptée pour la queue
# ==============================================================

if PLUX_AVAILABLE:
    class ChunkyDevice(plux.SignalsDev):
        """
        Sous-classe de plux.SignalsDev.
        Exactement comme NewDevice dans main.py du prof,
        mais onRawFrame envoie dans une queue au lieu de matplotlib.

        Paramètres :
            address    : adresse MAC du BITalino
            data_queue : queue.Queue partagée avec le reste de l'appli
            stop_event : threading.Event — mettre .set() pour arrêter
        """

        def __init__(self, address: str, data_queue: queue.Queue,
                     stop_event: threading.Event):
            # Constructeur plux — identique au prof
            plux.SignalsDev.__init__(address)

            self.data_queue = data_queue    # où envoyer les données
            self.stop_event = stop_event    # signal d'arrêt
            self.duration   = config.DURATION_MAX
            self.frequency  = config.SAMPLING_RATE

            # Compteur pour debug
            self._frame_count = 0
            self._last_print  = 0

        def onRawFrame(self, nSeq, data):
            """
            Appelé automatiquement par plux à CHAQUE frame reçue.

            Paramètres (identiques au prof) :
                nSeq : int   — numéro de séquence, commence à 0
                data : tuple — valeurs des ports actifs
                               data[0] = port A1, data[1] = port A2, etc.

            Retourne True pour arrêter, False pour continuer.
            (Identique au prof : nSeq > duration * frequency)
            """
            self._frame_count += 1

            # ── Construction du sample ──────────────────────────────
            # On accède aux données via les index définis dans config.py
            # Si votre branchement est différent, changez IDX_* dans config.py
            sample = {
                "ts":    time.time(),                        # horodatage Unix
                "nSeq":  nSeq,                               # numéro de frame
                "acc_x": int(data[config.IDX_ACC_X]),        # accéléromètre X
                "acc_y": int(data[config.IDX_ACC_Y]),        # accéléromètre Y
                "ppg":   int(data[config.IDX_PPG]),          # pouls
                "pzt":   int(data[config.IDX_PZT]),          # respiration
                "raw":   list(data),                         # toutes les valeurs brutes
            }

            # ── Envoi dans la queue (non-bloquant) ──────────────────
            try:
                self.data_queue.put_nowait(sample)
            except queue.Full:
                # Queue pleine = le jeu n'a pas consommé assez vite
                # On ignore l'échantillon plutôt que de bloquer
                pass

            # ── Debug : afficher 1 ligne par seconde ────────────────
            now = time.time()
            if now - self._last_print >= 1.0:
                print(f"[plux] nSeq={nSeq:6d} | "
                      f"acc_x={sample['acc_x']:5d} "
                      f"acc_y={sample['acc_y']:5d} | "
                      f"ppg={sample['ppg']:5d} | "
                      f"pzt={sample['pzt']:5d}")
                self._last_print = now

            # ── Condition d'arrêt — identique au prof ───────────────
            # Retourner True arrête device.loop()
            time_exceeded = nSeq > self.duration * self.frequency
            user_stopped  = self.stop_event.is_set()
            return time_exceeded or user_stopped


# ==============================================================
# THREAD D'ACQUISITION
# Lance device.loop() dans un thread séparé pour ne pas bloquer Pygame
# ==============================================================

class AcquisitionThread(threading.Thread):
    """
    Thread daemon qui fait tourner l'acquisition en arrière-plan.

    Utilisation :
        q = queue.Queue(maxsize=2000)
        t = AcquisitionThread(q)
        t.start()
        # ... votre code principal ...
        t.stop()

    Si plux n'est pas disponible → simulation automatique.
    """

    def __init__(self, data_queue: queue.Queue):
        super().__init__(daemon=True)   # daemon = s'arrête avec le programme principal
        self.data_queue  = data_queue
        self.stop_event  = threading.Event()   # Event thread-safe pour l'arrêt
        self.device      = None
        self.is_simulating = not PLUX_AVAILABLE

    def run(self):
        """Lance l'acquisition (réelle ou simulée)."""
        if PLUX_AVAILABLE:
            self._run_real()
        else:
            self._run_simulation()

    def _run_real(self):
        """Acquisition réelle — structure identique à exampleAcquisition() du prof."""
        try:
            print(f"[acquisition] Connexion à {config.MAC_ADDRESS}...")
            self.device = ChunkyDevice(
                config.MAC_ADDRESS,
                self.data_queue,
                self.stop_event
            )

            # Paramètres — identiques au prof
            self.device.duration  = config.DURATION_MAX
            self.device.frequency = config.SAMPLING_RATE

            # Démarrage — identique au prof :
            # device.start(frequency, active_ports, resolution)
            self.device.start(
                config.SAMPLING_RATE,
                config.ACTIVE_PORTS,
                config.RESOLUTION
            )
            print(f"[acquisition] Démarré — ports={config.ACTIVE_PORTS} "
                  f"@ {config.SAMPLING_RATE}Hz")

            # Boucle — identique au prof
            # Bloque jusqu'à ce que onRawFrame retourne True
            self.device.loop()

        except Exception as e:
            print(f"[acquisition] ERREUR connexion plux : {e}")
            print("[acquisition] → Bascule en mode simulation")
            self.is_simulating = True
            self._run_simulation()
        finally:
            # Nettoyage — identique au prof
            if self.device:
                try:
                    self.device.stop()
                    self.device.close()
                    print("[acquisition] Connexion fermée proprement")
                except Exception as ex:
                    print(f"[acquisition] Erreur fermeture : {ex}")

    def _run_simulation(self):
        """
        Génère des signaux synthétiques réalistes.
        Utilisé quand plux n'est pas disponible.

        Signaux générés :
          ACC : bruit gaussien + légères dérives (bras au repos)
          PPG : onde de pouls à ~66 bpm avec bruit physiologique
          PZT : respiration à ~15 cycles/min avec variation naturelle
        """
        print("[acquisition] Simulation démarrée (signaux synthétiques)")
        t     = 0.0
        dt    = 1.0 / config.SAMPLING_RATE
        nSeq  = 0

        # Valeur de repos ACC (centre de la plage 16 bits)
        acc_rest = 32768

        while not self.stop_event.is_set():
            t    += dt
            nSeq += 1

            # ACC : position de repos + dérive lente + bruit
            # En jeu réel, les pics seront bien plus marqués lors des gestes
            acc_x = acc_rest + int(
                500 * math.sin(0.3 * t) +        # dérive lente
                random.gauss(0, 150)              # bruit physiologique
            )
            acc_y = acc_rest + int(
                400 * math.cos(0.2 * t) +
                random.gauss(0, 150)
            )

            # PPG : onde de pouls à 66 bpm (1.1 Hz)
            # Forme asymétrique typique d'une onde pléthysmographique
            phase_ppg = 2 * math.pi * 1.1 * t
            ppg = 32768 + int(
                6000 * math.sin(phase_ppg) * max(0, math.sin(phase_ppg)) +
                random.gauss(0, 200)
            )

            # PZT : respiration à 15 cycles/min (0.25 Hz)
            # Amplitude plus grande → signal respiratoire typique
            pzt = 32768 + int(
                10000 * math.sin(2 * math.pi * 0.25 * t) +
                random.gauss(0, 100)
            )

            sample = {
                "ts":    time.time(),
                "nSeq":  nSeq,
                "acc_x": acc_x,
                "acc_y": acc_y,
                "ppg":   ppg,
                "pzt":   pzt,
                "raw":   [acc_x, acc_y, ppg, pzt],
            }

            try:
                self.data_queue.put_nowait(sample)
            except queue.Full:
                pass

            # Debug : 1 ligne par seconde
            if nSeq % config.SAMPLING_RATE == 0:
                print(f"[SIM] t={t:.1f}s | "
                      f"acc_x={acc_x:6d} acc_y={acc_y:6d} | "
                      f"ppg={ppg:6d} | pzt={pzt:6d}")

            time.sleep(dt)

    def stop(self):
        """Arrêt propre — signal au thread et au device."""
        print("[acquisition] Arrêt demandé...")
        self.stop_event.set()   # signal à onRawFrame de retourner True


# ==============================================================
# TEST STANDALONE — python acquisition.py
# ==============================================================
# Lance 10 secondes d'acquisition et affiche les données.
# Permet de vérifier que le BITalino est bien détecté et
# que les bons capteurs sont sur les bons ports.
# ==============================================================

if __name__ == "__main__":
    import matplotlib.pyplot as plt

    print("=" * 50)
    print("TEST ACQUISITION — ChunkyMemo")
    print("=" * 50)
    print()

    # Valider la config
    if not config.validate():
        print("Corrigez config.py avant de continuer")
        sys.exit(1)

    print()
    print("Démarrage acquisition 10 secondes...")
    print("(Gardez le bras immobile pendant la calibration)")
    print()

    # Queue pour recevoir les données
    data_q = queue.Queue(maxsize=config.QUEUE_MAXSIZE)

    # Démarrer le thread d'acquisition
    acq = AcquisitionThread(data_q)
    acq.start()

    # Collecter 10 secondes de données
    TEST_DURATION = 10
    start = time.time()

    all_ppg   = []
    all_pzt   = []
    all_acc_x = []
    all_acc_y = []
    all_ts    = []

    print(f"Collecte en cours ({TEST_DURATION}s)...")
    while time.time() - start < TEST_DURATION:
        try:
            sample = data_q.get(timeout=0.5)
            all_ppg.append(sample["ppg"])
            all_pzt.append(sample["pzt"])
            all_acc_x.append(sample["acc_x"])
            all_acc_y.append(sample["acc_y"])
            all_ts.append(sample["ts"] - start)
        except queue.Empty:
            pass

    acq.stop()
    time.sleep(0.5)

    print()
    print(f"Collecté : {len(all_ppg)} échantillons")
    print(f"Fréquence effective : {len(all_ppg) / TEST_DURATION:.1f} Hz")
    print()
    print(f"PPG   — min={min(all_ppg):6d}  max={max(all_ppg):6d}  "
          f"amplitude={max(all_ppg)-min(all_ppg):6d}")
    print(f"PZT   — min={min(all_pzt):6d}  max={max(all_pzt):6d}  "
          f"amplitude={max(all_pzt)-min(all_pzt):6d}")
    print(f"ACC_X — min={min(all_acc_x):6d}  max={max(all_acc_x):6d}")
    print(f"ACC_Y — min={min(all_acc_y):6d}  max={max(all_acc_y):6d}")
    print()

    # Affichage matplotlib — identique au style du prof
    fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
    fig.suptitle("Test acquisition ChunkyMemo — 10 secondes", fontsize=14)

    axes[0].plot(all_ts, all_ppg, color="tab:red",    linewidth=0.8)
    axes[0].set_ylabel("PPG (pouls)")
    axes[0].set_title("Photopléthysmographie")

    axes[1].plot(all_ts, all_pzt, color="tab:orange", linewidth=0.8)
    axes[1].set_ylabel("PZT (resp.)")
    axes[1].set_title("Respiration piézoélectrique")

    axes[2].plot(all_ts, all_acc_x, color="tab:blue",  linewidth=0.8)
    axes[2].set_ylabel("ACC X")
    axes[2].set_title("Accéléromètre axe X")

    axes[3].plot(all_ts, all_acc_y, color="tab:green", linewidth=0.8)
    axes[3].set_ylabel("ACC Y")
    axes[3].set_xlabel("Temps (secondes)")
    axes[3].set_title("Accéléromètre axe Y")

    plt.tight_layout()
    plt.show()
    print("Fermez la fenêtre matplotlib pour quitter.")
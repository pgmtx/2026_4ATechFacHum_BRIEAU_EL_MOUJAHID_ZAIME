"""
==============================================================
ChunkyMemo — config.py
==============================================================
Fichier de configuration CENTRAL.
Tous les autres fichiers importent depuis ici.
==============================================================
"""

import platform
import sys
import os

# Ajoute le dossier du script dans sys.path pour trouver plux.pyd
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ==============================================================
# PLUX — compatibilite OS (copie du main.py du prof)
# ==============================================================

python_version = platform.python_version()
pv = python_version.split('.')

OS_DIC = {
    "Darwin":  "MacOS/Intel" + pv[0] + pv[1],
    "Linux":   "Linux64",
    "Windows": "Win" + platform.architecture()[0][:2] + "_" + pv[0] + pv[1],
}

if sys.platform == "darwin":
    import subprocess
    from os import linesep
    p = subprocess.Popen("sw_vers", stdout=subprocess.PIPE)
    result = p.communicate()[0].decode("utf-8").split("\t")[2].split(linesep)[0]
    if result.startswith("12."):
        OS_DIC["Darwin"] = "MacOS/Intel310"

# ==============================================================
# CONNEXION BITALINO
# ==============================================================

MAC_ADDRESS = "98:D3:11:FE:03:67"

# ==============================================================
# ACQUISITION
# ==============================================================

SAMPLING_RATE = 100   # Hz
RESOLUTION    = 16    # bits
DURATION_MAX  = 3600  # secondes max par session

# ==============================================================
# PORTS BITALINO — PPG + PZT uniquement (ACC desactive)
# ==============================================================
# Branchement physique :
#   Port 3 (A3) → PPG  (pince doigt, capteur de pouls)
#   Port 4 (A4) → PZT  (ceinture thoracique, respiration)
#
# ACC desactive pour le moment.
# Pour le reactiver plus tard : ajouter [1, 2] dans ACTIVE_PORTS
# et definir IDX_ACC_X = 0, IDX_ACC_Y = 1, puis decaler IDX_PPG/PZT.

ACTIVE_PORTS = [3, 4]   # port 3 = PPG,  port 4 = PZT

# Index dans data[] recu dans onRawFrame :
#   data[0] → premier port de ACTIVE_PORTS → port 3 → PPG
#   data[1] → deuxieme port de ACTIVE_PORTS → port 4 → PZT
IDX_PPG = 0
IDX_PZT = 1

# ==============================================================
# TRAITEMENT SIGNAL PPG (frequence cardiaque)
# ==============================================================

PPG_LOW_HZ       = 0.7   # Hz — 42 bpm minimum detectectable
PPG_HIGH_HZ      = 4.0   # Hz — 240 bpm maximum
PPG_FILTER_ORDER = 4     # ordre filtre Butterworth
PPG_WINDOW_SEC   = 10    # secondes de fenetre glissante

# ==============================================================
# TRAITEMENT SIGNAL PZT (respiration)
# ==============================================================

PZT_LOW_HZ       = 0.1   # Hz — 6 respirations/min minimum
PZT_HIGH_HZ      = 0.8   # Hz — 48 respirations/min maximum
PZT_FILTER_ORDER = 4
PZT_WINDOW_SEC   = 15    # fenetre plus large car respiration plus lente

# ==============================================================
# BUFFERS ET AFFICHAGE
# ==============================================================

QUEUE_MAXSIZE = 2000   # taille max queue entre thread acquisition et jeu
GRAPH_HISTORY = 500    # points affiches sur les courbes temps reel

# ==============================================================
# EXPORT DONNEES
# ==============================================================

CSV_OUTPUT_DIR = "sessions"   # cree automatiquement si absent

# ==============================================================
# VALIDATION — appelee au demarrage de chaque module
# ==============================================================

def validate():
    """
    Verifie que la configuration est coherente.
    Retourne True si tout est ok, False sinon.
    """
    ok = True

    if len(ACTIVE_PORTS) < 2:
        print("[CONFIG ERROR] Il faut au moins 2 ports actifs (PPG + PZT)")
        ok = False

    max_idx = max(IDX_PPG, IDX_PZT)
    if max_idx >= len(ACTIVE_PORTS):
        print("[CONFIG ERROR] IDX_PPG ou IDX_PZT depasse le nombre de ports actifs")
        print(f"              IDX_PPG={IDX_PPG}  IDX_PZT={IDX_PZT}  nb_ports={len(ACTIVE_PORTS)}")
        ok = False

    if PPG_LOW_HZ >= PPG_HIGH_HZ:
        print("[CONFIG ERROR] PPG_LOW_HZ doit etre < PPG_HIGH_HZ")
        ok = False

    if PZT_LOW_HZ >= PZT_HIGH_HZ:
        print("[CONFIG ERROR] PZT_LOW_HZ doit etre < PZT_HIGH_HZ")
        ok = False

    if ok:
        print("[CONFIG] ✓ Configuration valide")
        print(f"[CONFIG]   MAC        : {MAC_ADDRESS}")
        print(f"[CONFIG]   Ports      : {ACTIVE_PORTS}")
        print(f"[CONFIG]   IDX_PPG    : {IDX_PPG}  (data[{IDX_PPG}] = port {ACTIVE_PORTS[IDX_PPG]})")
        print(f"[CONFIG]   IDX_PZT    : {IDX_PZT}  (data[{IDX_PZT}] = port {ACTIVE_PORTS[IDX_PZT]})")
        print(f"[CONFIG]   Frequence  : {SAMPLING_RATE} Hz")
    return ok


if __name__ == "__main__":
    print("=== Test configuration ChunkyMemo ===")
    result = validate()
    if result:
        print("\nTout est bon — vous pouvez lancer acquisition.py")
    else:
        print("\nCorrigez les erreurs ci-dessus avant de continuer")
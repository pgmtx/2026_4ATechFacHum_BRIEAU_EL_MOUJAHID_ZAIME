"""
==============================================================
ChunkyMemo — config.py
==============================================================
Fichier de configuration CENTRAL.
Tous les autres fichiers importent depuis ici.
Si quelque chose ne marche pas, c'est probablement un réglage
à changer ici, pas dans le code des autres fichiers.

Omar / Salma : les seuls paramètres à toucher sont dans ce fichier.
==============================================================
"""

import platform
import sys

# ==============================================================
# PLUX — compatibilité OS (copié exactement du main.py du prof)
# ==============================================================

python_version = platform.python_version()

OS_DIC = {
    "Darwin":  f"MacOS/Intel{''.join(python_version.split('.')[:2])}",
    "Linux":   "Linux64",
    "Windows": f"Win{platform.architecture()[0][:2]}_{''.join(python_version.split('.')[:2])}",
}

# Cas spécial macOS Monterey (comme dans le main.py du prof)
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

# ← CHANGER PAR VOTRE ADRESSE MAC (visible dans OpenSignals)
MAC_ADDRESS = "98:D3:11:FE:03:67"

# ==============================================================
# ACQUISITION
# ==============================================================

SAMPLING_RATE = 100   # Hz — 100 échantillons par seconde (comme main.py du prof)
RESOLUTION    = 16    # bits — résolution ADC (comme main.py du prof)
DURATION_MAX  = 3600  # secondes — durée max de session (1 heure de sécurité)

# ==============================================================
# PORTS BITALINO — À ADAPTER SELON VOTRE BRANCHEMENT PHYSIQUE
# ==============================================================
# Le BITalino a 6 ports analogiques : A1 à A6
# Branchez vos capteurs sur ces ports et notez les numéros ici.
#
# Schéma de branchement recommandé :
#   Port 1 (A1) → ACC canal X  (accéléromètre, axe gauche/droite)
#   Port 2 (A2) → ACC canal Y  (accéléromètre, axe haut/bas)
#   Port 3 (A3) → PPG          (capteur de pouls, pince doigt)
#   Port 4 (A4) → PZT          (ceinture respiratoire)
#
# Si vous branchez différemment, changez juste les numéros ci-dessous.

ACTIVE_PORTS = [1, 2, 3, 4]   # ports physiques à activer (liste de int)

# Index dans data[] reçu dans onRawFrame :
# data[0] = premier port de ACTIVE_PORTS, data[1] = deuxième, etc.
IDX_ACC_X = 0   # data[0] → port 1 → ACC axe X
IDX_ACC_Y = 1   # data[1] → port 2 → ACC axe Y
IDX_PPG   = 2   # data[2] → port 3 → PPG
IDX_PZT   = 3   # data[3] → port 4 → PZT

# ==============================================================
# DÉTECTION DE GESTES (ACC)
# ==============================================================
# L'accéléromètre donne des valeurs 0-65535 (résolution 16 bits).
# Au repos, la valeur est environ au milieu (~32768).
# Un geste = écart par rapport à cette valeur de repos.

ACC_THRESHOLD    = 3000   # écart minimum pour qu'un geste soit validé
                           # ↑ augmenter si trop de faux gestes
                           # ↓ diminuer si les gestes ne sont pas détectés

ACC_DEBOUNCE_SEC = 0.5    # secondes minimum entre deux gestes consécutifs
                           # évite qu'un seul geste soit compté 10 fois

ACC_CALIB_SAMPLES = 100   # nombre d'échantillons pour calculer le point de repos
                           # = 1 seconde à 100 Hz → laisser le bras immobile au début

# ==============================================================
# TRAITEMENT SIGNAL PPG (fréquence cardiaque)
# ==============================================================
# Le PPG mesure les variations de volume sanguin dans le doigt.
# Pour extraire la fréquence cardiaque, on filtre le signal.

PPG_LOW_HZ  = 0.7    # fréquence min du filtre passe-bande (Hz)
                      # = 42 bpm minimum détectable (personne au repos)
PPG_HIGH_HZ = 4.0    # fréquence max du filtre passe-bande (Hz)
                      # = 240 bpm maximum détectable (effort intense)
PPG_FILTER_ORDER = 4  # ordre du filtre Butterworth (4 = bon compromis précision/vitesse)

# Fenêtre glissante pour le calcul en temps réel
PPG_WINDOW_SEC = 10   # secondes de signal utilisées pour calculer la FC
                       # 10s = bon compromis réactivité/stabilité

# ==============================================================
# TRAITEMENT SIGNAL PZT (respiration)
# ==============================================================
# Le PZT mesure la déformation de la ceinture thoracique.
# Fréquence respiratoire normale : 12-20 cycles/min = 0.2-0.33 Hz

PZT_LOW_HZ  = 0.1    # fréquence min passe-bande respiration (Hz) = 6 resp/min
PZT_HIGH_HZ = 0.8    # fréquence max passe-bande respiration (Hz) = 48 resp/min
PZT_FILTER_ORDER = 4

PZT_WINDOW_SEC = 15   # secondes pour calculer le rythme respiratoire
                       # plus long que PPG car la respiration est plus lente

# ==============================================================
# BUFFERS ET AFFICHAGE
# ==============================================================

QUEUE_MAXSIZE   = 2000   # taille max de la queue entre thread et jeu
GRAPH_HISTORY   = 500    # nombre de points affichés sur les courbes temps réel
                          # = 5 secondes à 100 Hz

# ==============================================================
# EXPORT DONNÉES
# ==============================================================

CSV_OUTPUT_DIR  = "sessions"   # dossier où sauvegarder les sessions
                                # créé automatiquement s'il n'existe pas

# ==============================================================
# VALIDATION — vérification automatique au démarrage
# ==============================================================

def validate():
    """
    Vérifie que la configuration est cohérente.
    Appelé au démarrage de chaque module.
    Affiche des warnings clairs si quelque chose est suspect.
    """
    ok = True

    if len(ACTIVE_PORTS) < 2:
        print("[CONFIG ERROR] Il faut au moins 2 ports actifs (ACC + 1 physiologique)")
        ok = False

    max_idx = max(IDX_ACC_X, IDX_ACC_Y, IDX_PPG, IDX_PZT)
    if max_idx >= len(ACTIVE_PORTS):
        print(f"[CONFIG ERROR] IDX_* ({max_idx}) dépasse le nombre de ports actifs ({len(ACTIVE_PORTS)})")
        ok = False

    if PPG_LOW_HZ >= PPG_HIGH_HZ:
        print("[CONFIG ERROR] PPG_LOW_HZ doit être < PPG_HIGH_HZ")
        ok = False

    if PZT_LOW_HZ >= PZT_HIGH_HZ:
        print("[CONFIG ERROR] PZT_LOW_HZ doit être < PZT_HIGH_HZ")
        ok = False

    if ok:
        print("[CONFIG] ✓ Configuration valide")
        print(f"[CONFIG]   MAC        : {MAC_ADDRESS}")
        print(f"[CONFIG]   Ports      : {ACTIVE_PORTS}")
        print(f"[CONFIG]   Fréquence  : {SAMPLING_RATE} Hz")
        print(f"[CONFIG]   ACC seuil  : {ACC_THRESHOLD}")
    return ok


# ==============================================================
# TEST RAPIDE — python config.py
# ==============================================================
if __name__ == "__main__":
    print("=== Test configuration ChunkyMemo ===")
    result = validate()
    if result:
        print("\nTout est bon — vous pouvez lancer acquisition.py")
    else:
        print("\nCorrigez les erreurs ci-dessus avant de continuer")
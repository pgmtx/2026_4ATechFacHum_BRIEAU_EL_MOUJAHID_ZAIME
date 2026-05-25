"""
==============================================================
ChunkyMemo — config.py
==============================================================
Central configuration file, needed by the other files.
==============================================================
"""

import logging
import os
import platform
import sys

# Makes sure the lib file is available even when not running from the project directory.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ==============================================================
# PLUX — OS compatibility
# ==============================================================

python_version = platform.python_version()
pv = python_version.split(".")

OS_DIC = {
    "Darwin": "MacOS/Intel" + pv[0] + pv[1],
    "Linux": "Linux64",
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
# BITALINO CONNECTION
# ==============================================================

MAC_ADDRESS = "98:D3:11:FE:03:67"

# ==============================================================
# ACQUISITION
# ==============================================================

SAMPLING_RATE = 100  # Hz
RESOLUTION = 16  # bits
DURATION_MAX = 3600  # max seconds per session

# ==============================================================
# BITALINO PORTS — PPG + PZT only
# ==============================================================
# Physical connections :
#   Port 3 (A3) → PPG (finger clip, pulse sensor)
#   Port 4 (A4) → PZT (chest strap, breathing)
#
# ACC currently disabled.
# To reenabled later: add [1, 2] to ACTIVE_PORTS
# and define IDX_ACC_X = 0, IDX_ACC_Y = 1, then shift IDX_PPG/PZT.

ACTIVE_PORTS = [3, 4]  # port 3 = PPG,  port 4 = PZT

# Indices inside data[] received in onRawFrame :
#   data[0] → first port of ACTIVE_PORTS → port 3 → PPG
#   data[1] → second port of ACTIVE_PORTS → port 4 → PZT
IDX_PPG = 0
IDX_PZT = 1

# ==============================================================
# PPG SIGNAL PROCESSING (heart rate)
# ==============================================================

PPG_LOW_HZ = 0.7  # Hz — Minimum detectable heart rate: 42 bpm
PPG_HIGH_HZ = 4.0  # Hz — Minimum detectable heart rate: 240 bpm
PPG_FILTER_ORDER = 4  # Butterworth filter order
PPG_WINDOW_SEC = 10  # sliding window seconds

# ==============================================================
# PZT SIGNAL PROCESSING (breathing)
# ==============================================================

PZT_LOW_HZ = 0.1  # Hz — 6 breaths per minute minimum
PZT_HIGH_HZ = 0.8  # Hz — 48 breaths per minute maximum
PZT_FILTER_ORDER = 4
PZT_WINDOW_SEC = 15  # a wider window because breathing is slower

# ==============================================================
# BUFFERS AND DISPLAY
# ==============================================================

QUEUE_MAXSIZE = 2000  # Maximum queue size between thread acquisition and execution
GRAPH_HISTORY = 500  # data points plotted on real-time curves

# ==============================================================
# DATA EXPORT
# ==============================================================

CSV_OUTPUT_DIR = "sessions"  # automatically created if absent

# ==============================================================
# VALIDATION — called when each module starts up
# ==============================================================


def validate():
    """
    Checks that the configuration is consistent.
    Returns True if everything is OK, False otherwise.
    """
    ok = True

    if len(ACTIVE_PORTS) < 2:
        logging.error("[CONFIG ERROR] Il faut au moins 2 ports actifs (PPG + PZT)")
        ok = False

    max_idx = max(IDX_PPG, IDX_PZT)
    if max_idx >= len(ACTIVE_PORTS):
        logging.error(
            "[CONFIG ERROR] IDX_PPG ou IDX_PZT depasse le nombre de ports actifs"
        )
        logging.error(
            f"              IDX_PPG={IDX_PPG}  IDX_PZT={IDX_PZT}  nb_ports={len(ACTIVE_PORTS)}"
        )
        ok = False

    if PPG_LOW_HZ >= PPG_HIGH_HZ:
        logging.error("[CONFIG ERROR] PPG_LOW_HZ doit etre < PPG_HIGH_HZ")
        ok = False

    if PZT_LOW_HZ >= PZT_HIGH_HZ:
        logging.error("[CONFIG ERROR] PZT_LOW_HZ doit etre < PZT_HIGH_HZ")
        ok = False

    if ok:
        logging.info("[CONFIG] ✓ Configuration valide")
        logging.info(f"[CONFIG]   MAC        : {MAC_ADDRESS}")
        logging.info(f"[CONFIG]   Ports      : {ACTIVE_PORTS}")
        logging.info(
            f"[CONFIG]   IDX_PPG    : {IDX_PPG}  (data[{IDX_PPG}] = port {ACTIVE_PORTS[IDX_PPG]})"
        )
        logging.info(
            f"[CONFIG]   IDX_PZT    : {IDX_PZT}  (data[{IDX_PZT}] = port {ACTIVE_PORTS[IDX_PZT]})"
        )
        logging.info(f"[CONFIG]   Frequence  : {SAMPLING_RATE} Hz")
    return ok


if __name__ == "__main__":
    logging.info("=== Test configuration ChunkyMemo ===")
    result = validate()
    if result:
        logging.info("\nTout est bon — vous pouvez lancer acquisition.py")
    else:
        logging.error("\nCorrigez les erreurs ci-dessus avant de continuer")

"""
==============================================================
ChunkyMemo — game_console.py
==============================================================
Jeu complet dans le terminal + acquisition BITalino reelle.

Deroulement :
  1. Calibration 30s au repos (FC, PWA, RR baseline)
  2. Menu : Mode Normal ou Mode Chunking
  3. Jeu de fleches avec clavier (Z/S/Q/D)
  4. Signaux PPG + PZT acquis en continu
  5. FC, RR, I_cog calcules en temps reel
  6. Graphiques + CSV exportes apres la session

Lancer :
  python game_console.py
==============================================================
"""

import sys, os, time, queue, threading, random, csv, platform, math, signal as os_signal
from datetime import datetime
from collections import deque

import config

# ── plux dans le meme dossier ────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    import plux
    _ = plux.SignalsDev
    PLUX_OK = True
except (ImportError, AttributeError):
    print("[ERREUR] plux.pyd introuvable")
    sys.exit(1)

from signal_processing import (
    PPGProcessor, PZTProcessor,
    KeyboardProcessor, CognitiveLoadIndex, CalibrationPhase
)

# ==============================================================
# BITALINO — identique au main.py du prof
# ==============================================================

class ChunkyDevice(plux.SignalsDev):
    def __init__(self, address):
        plux.SignalsDev.__init__(address)
        self.data_queue  = None
        self.stop_event  = None
        self.duration    = config.DURATION_MAX
        self.frequency   = config.SAMPLING_RATE
        self._last_print = 0

    def onRawFrame(self, nSeq, data):
        sample = {
            "ts":  time.time(),
            "nSeq": nSeq,
            "ppg": int(data[config.IDX_PPG]),
            "pzt": int(data[config.IDX_PZT]),
        }
        try:
            self.data_queue.put_nowait(sample)
        except queue.Full:
            pass
        return self.stop_event.is_set() or (nSeq > self.duration * self.frequency)


class AcquisitionThread(threading.Thread):
    def __init__(self, data_queue):
        super().__init__(daemon=True)
        self.data_queue = data_queue
        self.stop_event = threading.Event()
        self.device     = None

    def run(self):
        try:
            self.device = ChunkyDevice(config.MAC_ADDRESS)
            self.device.data_queue = self.data_queue
            self.device.stop_event = self.stop_event
            self.device.duration   = config.DURATION_MAX
            self.device.frequency  = config.SAMPLING_RATE
            self.device.start(config.SAMPLING_RATE, config.ACTIVE_PORTS, config.RESOLUTION)
            print(f"[BITalino] Connecte — ports={config.ACTIVE_PORTS} @ {config.SAMPLING_RATE}Hz")
            self.device.loop()
        except Exception as e:
            print(f"[BITalino] ERREUR : {e}")
        finally:
            if self.device:
                try: self.device.stop(); self.device.close()
                except: pass

    def stop(self):
        self.stop_event.set()


# ==============================================================
# PROCESSEUR SIGNAUX — tourne en arriere-plan
# ==============================================================

class SensorProcessor:
    """
    Lit la queue BITalino et alimente PPGProcessor + PZTProcessor.
    Gere aussi la phase de calibration.
    Apres calibration : calcule I_cog en continu.
    """
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.ppg        = PPGProcessor()
        self.pzt        = PZTProcessor()
        self.kb         = KeyboardProcessor()
        self.cog        = CognitiveLoadIndex()
        self.calib      = CalibrationPhase(self.ppg, self.pzt, self.cog)

        # Etat
        self.calibrated  = False
        self.all_samples = []
        self.ppg_display = deque(maxlen=40)
        self.pzt_display = deque(maxlen=40)

        # Historique par niveau pour les graphiques
        self.level_events = []   # (ts_relatif, niveau)
        self._start_time  = None

        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self, start_time):
        self._start_time = start_time
        self.calib.start()
        self._thread.start()

    def stop(self):
        self._stop.set()

    def mark_level(self, level):
        if self._start_time:
            ts_rel = time.time() - self._start_time
            self.level_events.append((ts_rel, level))

    def _loop(self):
        while not self._stop.is_set():
            batch = []
            while not self.data_queue.empty() and len(batch) < 50:
                try: batch.append(self.data_queue.get_nowait())
                except queue.Empty: break

            for s in batch:
                self.all_samples.append(s)
                self.ppg_display.append(s["ppg"])
                self.pzt_display.append(s["pzt"])

                if not self.calibrated:
                    self.calib.update(s)
                    if self.calib.is_done():
                        self.calib.finalize()
                        # Baseline RT sera definie apres les 5 premieres reponses
                        self.calibrated = True
                else:
                    self.ppg.update(s["ppg"], s["ts"])
                    self.pzt.update(s["pzt"], s["ts"])
                    self.cog.update(
                        self.ppg.fc_bpm,
                        self.ppg.pwa_raw,
                        self.pzt.rr_rpm,
                        self.kb.rt_ms,
                        s["ts"]
                    )

            time.sleep(0.02)


# ==============================================================
# COULEURS CONSOLE
# ==============================================================

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    PURPLE = "\033[95m"
    WHITE  = "\033[97m"

ARROW = {"UP":"↑","DOWN":"↓","LEFT":"←","RIGHT":"→"}

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def print_header(mode, level, score, sensor: SensorProcessor):
    fc_s  = f"{sensor.ppg.fc_bpm:.0f}bpm"  if sensor.ppg.fc_bpm  else "---"
    rr_s  = f"{sensor.pzt.rr_rpm:.0f}rpm"  if sensor.pzt.rr_rpm  else "---"
    ic_s  = f"I_cog={sensor.cog.i_cog:.2f}" if sensor.cog.i_cog is not None else "I_cog=---"
    ov_s  = f" {C.RED}SURCHARGE{C.RESET}" if sensor.cog.overload else ""
    ap_s  = f" {C.YELLOW}APNEE{C.RESET}" if sensor.pzt.apnea_detected else ""
    cal_s = f" {C.YELLOW}[CALIBRATION EN COURS]{C.RESET}" if not sensor.calibrated else ""

    print(f"{C.BOLD}{'='*65}{C.RESET}")
    print(f"  {C.BOLD}ChunkyMemo{C.RESET} [LIVE]"
          f" | Mode: {C.CYAN}{mode}{C.RESET}"
          f" | Niv: {C.YELLOW}{level}{C.RESET}"
          f" | Score: {C.GREEN}{score}{C.RESET}{cal_s}")
    print(f"  {C.GRAY}PPG:{fc_s}  PZT:{rr_s}  {ic_s}{ov_s}{ap_s}{C.RESET}")
    print(f"{C.BOLD}{'='*65}{C.RESET}")

def print_sequence(seq, mode):
    arrows = [ARROW[d] for d in seq]
    print(f"\n  {C.YELLOW}{C.BOLD}Memorisez !{C.RESET}\n")
    if mode == "NORMAL":
        print("  " + "  ".join(f"{C.WHITE}{C.BOLD}{a}{C.RESET}" for a in arrows))
    else:
        chunks = [seq[i:i+2] for i in range(0, len(seq), 2)]
        achunks = [arrows[i:i+2] for i in range(0, len(arrows), 2)]
        parts = []
        for i, (ca, cd) in enumerate(zip(achunks, chunks)):
            col = C.CYAN if i % 2 == 0 else C.PURPLE
            parts.append(f"[{col}{' '.join(ca)}{C.RESET}]")
        print("  " + "  ".join(parts))
        print(f"\n  {C.GRAY}(groupes par paires — chunking){C.RESET}")

def print_mini_sensors(sensor: SensorProcessor):
    if len(sensor.ppg_display) < 5:
        print(f"  {C.GRAY}[capteurs: calibration...]{C.RESET}")
        return
    chars = " ▁▂▃▄▅▆▇█"
    for buf, col, lbl in [(sensor.ppg_display, C.RED, "PPG"), (sensor.pzt_display, C.YELLOW, "PZT")]:
        vals = list(buf)[-40:]
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1
        bars = "".join(chars[int((v-mn)/rng*(len(chars)-1))] for v in vals)
        print(f"  {col}{lbl}: {bars}{C.RESET}")


# ==============================================================
# LECTURE CLAVIER
# ==============================================================

KEYMAP = {
    "z":"UP","Z":"UP","s":"DOWN","S":"DOWN",
    "q":"LEFT","Q":"LEFT","d":"RIGHT","D":"RIGHT",
    "up":"UP","down":"DOWN","left":"LEFT","right":"RIGHT",
}

def read_full_sequence(seq_len: int, sensor: SensorProcessor,
                       sequence: list, mode: str, level: int, score: int) -> list:
    """
    Lit seq_len reponses au clavier.
    Enregistre le RT via KeyboardProcessor a chaque fleche.
    """
    print(f"\n  {C.CYAN}Reproduisez {seq_len} fleches (Z=↑  S=↓  Q=←  D=→){C.RESET}\n")
    result = []

    while len(result) < seq_len:
        n = len(result)
        # Afficher progression
        prog = []
        for i, d in enumerate(sequence):
            if i < n:
                prog.append(f"{C.GREEN}{ARROW[result[i]]}{C.RESET}" if result[i]==d else f"{C.RED}✗{C.RESET}")
            elif i == n:
                prog.append(f"{C.YELLOW}_{C.RESET}")
            else:
                prog.append(f"{C.GRAY}·{C.RESET}")
        print(f"\r  {'  '.join(prog)}  ({n}/{seq_len})", end="", flush=True)

        # Enregistrer le moment ou on attend la fleche (pour RT)
        sensor.kb.arrow_shown(sequence[n], time.time())

        raw = input(f"  [{n+1}/{seq_len}] > ").strip()
        t_rep = time.time()
        d = KEYMAP.get(raw)
        if d is None:
            # Essai multi
            parts = [KEYMAP.get(p) for p in raw.split()]
            if all(p is not None for p in parts) and parts:
                for p in parts[:seq_len - n]:
                    sensor.kb.arrow_answered(p, t_rep)
                    result.append(p)
                    # Baseline RT apres 5 premieres reponses
                    if len(sensor.kb.rt_history) == 5 and not sensor.cog._baseline["rt"]["mu"]:
                        rt_vals = [v for _, v in sensor.kb.rt_history]
                        sensor.cog.set_baseline("rt", rt_vals)
                        print(f"\n  {C.GRAY}[Baseline RT definie : {sum(rt_vals)/len(rt_vals):.0f}ms]{C.RESET}")
                continue
            print(f"  {C.GRAY}(Z=↑  S=↓  Q=←  D=→){C.RESET}")
            continue

        sensor.kb.arrow_answered(d, t_rep)
        result.append(d)

        # Baseline RT apres 5 premieres reponses niveau 1
        if len(sensor.kb.rt_history) == 5 and not sensor.cog._baseline["rt"]["mu"]:
            rt_vals = [v for _, v in sensor.kb.rt_history]
            sensor.cog.set_baseline("rt", rt_vals)
            print(f"\n  {C.GRAY}[Baseline RT definie : {sum(rt_vals)/len(rt_vals):.0f}ms]{C.RESET}")

    print()
    return result


# ==============================================================
# JEU PRINCIPAL
# ==============================================================

class ChunkyMemoGame:
    MEMORIZE_SEC = 3.0
    FEEDBACK_SEC = 1.5

    def __init__(self):
        self.data_queue = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
        self.acq        = AcquisitionThread(self.data_queue)
        self.sensor     = SensorProcessor(self.data_queue)
        self.level      = 1
        self.score      = 0
        self.mode       = "NORMAL"

        # Donnees de session pour comparaison
        self.sessions = {}   # {"NORMAL": [...niveaux...], "CHUNKING": [...]}

    def start(self):
        # Connexion BITalino
        print(f"\n[BITalino] Connexion a {config.MAC_ADDRESS} ...")
        self.acq.start()
        start_time = time.time()

        # Attendre premiere donnee
        deadline = time.time() + 8
        while self.data_queue.empty() and time.time() < deadline:
            time.sleep(0.1)
        if self.data_queue.empty():
            print("[ERREUR] Aucune donnee BITalino. Verifiez connexion Bluetooth.")
            sys.exit(1)

        # Demarrer traitement signal + calibration
        self.sensor.start(start_time)

        # Afficher calibration
        print("\n" + "="*65)
        print("  CALIBRATION 30s — Restez IMMOBILE et respirez normalement")
        print("  Ne lancez le jeu qu'apres la calibration !")
        print("="*65)

        while not self.sensor.calibrated:
            elapsed = time.time() - start_time
            rem = max(0, 30 - elapsed)
            fc_s = f"FC={self.sensor.ppg.fc_bpm:.0f}bpm" if self.sensor.ppg.fc_bpm else "FC=---"
            rr_s = f"RR={self.sensor.pzt.rr_rpm:.0f}rpm" if self.sensor.pzt.rr_rpm else "RR=---"
            print(f"\r  {C.YELLOW}[{rem:.0f}s restantes]{C.RESET}  {fc_s}  {rr_s}    ", end="", flush=True)
            time.sleep(0.5)

        print(f"\n\n  {C.GREEN}Calibration terminee !{C.RESET}")
        print(f"  FC repos : {self.sensor.ppg.fc_bpm:.0f}bpm" if self.sensor.ppg.fc_bpm else "")
        print(f"  RR repos : {self.sensor.pzt.rr_rpm:.0f}rpm" if self.sensor.pzt.rr_rpm else "")
        print()

        self._show_menu()

    def _show_menu(self):
        while True:
            clear()
            print(f"""
{C.BOLD}{'='*65}{C.RESET}
{C.BOLD}  ChunkyMemo — Jeu de memoire de travail{C.RESET}
  Miller (1956) : limite 7 ± 2 elements
{C.BOLD}{'='*65}{C.RESET}

    {C.CYAN}[1]{C.RESET} Mode Normal    — fleches une par une
    {C.CYAN}[2]{C.RESET} Mode Chunking  — fleches groupees par paires
    {C.CYAN}[3]{C.RESET} Les deux modes (Normal puis Chunking + rapport)
    {C.CYAN}[Q]{C.RESET} Quitter

{C.BOLD}{'='*65}{C.RESET}
""")
            choice = input("  Votre choix : ").strip().upper()
            if choice == "1":
                self._run_session("NORMAL")
            elif choice == "2":
                self._run_session("CHUNKING")
            elif choice == "3":
                self._run_session("NORMAL")
                print(f"\n  {C.CYAN}Normal termine. Chunking dans 3s...{C.RESET}")
                time.sleep(3)
                self._run_session("CHUNKING")
                self._show_comparison()
            elif choice == "Q":
                self._quit(); return

    def _run_session(self, mode: str):
        self.mode  = mode
        self.level = 1
        self.score = 0
        levels_data = []

        clear()
        print(f"\n{C.BOLD}  Mode : {C.CYAN}{mode}{C.RESET}\n")
        print(f"  Z=↑  S=↓  Q=←  D=→  |  Entree apres chaque direction\n")
        input("  Appuyez sur Entree pour commencer...")

        self.sensor.mark_level(self.level)

        game_over = False
        while not game_over:
            seq_len = self.level + 2
            sequence = [random.choice(["UP","DOWN","LEFT","RIGHT"]) for _ in range(seq_len)]

            # ── Phase memorisation ────────────────────────────────
            ts_start = time.time()
            clear()
            print_header(mode, self.level, self.score, self.sensor)
            print_sequence(sequence, mode)
            print_mini_sensors(self.sensor)

            for r in range(int(self.MEMORIZE_SEC), 0, -1):
                print(f"\r  {C.YELLOW}Disparait dans {r}s...{C.RESET}  ", end="", flush=True)
                time.sleep(1)
            print()

            # ── Phase reproduction ────────────────────────────────
            clear()
            print_header(mode, self.level, self.score, self.sensor)
            player_input = read_full_sequence(
                seq_len, self.sensor, sequence, mode, self.level, self.score
            )
            ts_end = time.time()

            # ── Verification ──────────────────────────────────────
            success = (player_input == sequence)

            clear()
            print_header(mode, self.level, self.score, self.sensor)
            if success:
                print(f"\n  {C.GREEN}{C.BOLD}Correct !{C.RESET}")
            else:
                print(f"\n  {C.RED}{C.BOLD}Erreur !{C.RESET}")
                print(f"  Attendu : {'  '.join(ARROW[d] for d in sequence)}")
                print(f"  Tape    : {'  '.join(ARROW.get(d,'?') for d in player_input)}")

            # Enregistrement donnees niveau
            levels_data.append({
                "level":      self.level,
                "mode":       mode,
                "success":    success,
                "seq_len":    seq_len,
                "fc_bpm":     self.sensor.ppg.fc_bpm,
                "rr_rpm":     self.sensor.pzt.rr_rpm,
                "pwa":        self.sensor.ppg.pwa_raw,
                "rt_ms":      self.sensor.kb.rt_mean_ms,
                "error_rate": self.sensor.kb.error_rate,
                "i_cog":      self.sensor.cog.i_cog,
                "overload":   self.sensor.cog.overload,
                "apnea":      self.sensor.pzt.apnea_detected,
                "ts_start":   ts_start,
                "ts_end":     ts_end,
            })

            if success:
                self.score += seq_len * 10
                print(f"\n  {C.GREEN}+{seq_len*10} pts → Score : {self.score}{C.RESET}")
                if seq_len >= 7:
                    print(f"\n  {C.CYAN}→ {seq_len} elements : vous approchez la limite de Miller !{C.RESET}")
                self.level += 1
                self.sensor.mark_level(self.level)
                self.sensor.kb.reset_level()
                time.sleep(self.FEEDBACK_SEC)
            else:
                game_over = True
                print(f"\n  {C.RED}{C.BOLD}GAME OVER{C.RESET}")
                print(f"  Niveau max : {C.YELLOW}{self.level}{C.RESET}  Score : {C.GREEN}{self.score}{C.RESET}")
                if seq_len >= 7:
                    print(f"\n  {C.CYAN}→ {seq_len} elements depasses la limite 7±2 de Miller{C.RESET}")
                time.sleep(2)

        self.sessions[mode] = levels_data
        self._export_csv(mode, levels_data)
        self._show_graphs(mode, levels_data)

    def _export_csv(self, mode, levels_data):
        os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"{config.CSV_OUTPUT_DIR}/session_{mode}_{ts}.csv"
        fields = ["level","mode","success","seq_len","fc_bpm","rr_rpm",
                  "pwa","rt_ms","error_rate","i_cog","overload","apnea",
                  "ts_start","ts_end"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for row in levels_data:
                w.writerow({k: row.get(k,"") for k in fields})
        print(f"\n  {C.GREEN}CSV sauvegarde : {path}{C.RESET}")

        # CSV signaux bruts
        samples = self.sensor.all_samples
        if samples:
            path_raw = f"{config.CSV_OUTPUT_DIR}/raw_{mode}_{ts}.csv"
            with open(path_raw, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["ts","nSeq","ppg","pzt"])
                w.writeheader()
                w.writerows({k: s.get(k,"") for k in ["ts","nSeq","ppg","pzt"]} for s in samples)
            print(f"  {C.GREEN}CSV brut : {path_raw}{C.RESET}")
        input("\n  Appuyez sur Entree pour continuer...")

    def _show_graphs(self, mode, levels_data):
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            import matplotlib.gridspec as gridspec
            from signal_processing import CognitiveLoadIndex as _CI
        except ImportError:
            return

        samples = self.sensor.all_samples
        if not samples or not levels_data:
            return

        ts0  = samples[0]["ts"]
        ts_a = [s["ts"]-ts0 for s in samples]
        ppg_a = [s["ppg"] for s in samples]
        pzt_a = [s["pzt"] for s in samples]

        levels  = [d["level"]   for d in levels_data]
        fc_vals = [d["fc_bpm"]  for d in levels_data]
        rr_vals = [d["rr_rpm"]  for d in levels_data]
        ic_vals = [d["i_cog"]   for d in levels_data]
        rt_vals = [d["rt_ms"]   for d in levels_data]

        fig = plt.figure(figsize=(15, 12))
        gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.5, wspace=0.35)
        fig.suptitle(f"ChunkyMemo — Session {mode}  |  Niveau max {max(levels)}", fontsize=13)

        # PPG brut
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.plot(ts_a, ppg_a, color="tab:red", lw=0.6, alpha=0.8)
        for ts_ev, lv in self.sensor.level_events:
            ax1.axvline(x=ts_ev, color="gray", alpha=0.3, lw=1)
            ax1.text(ts_ev, max(ppg_a)*0.97, f"N{lv}", fontsize=7, color="gray", ha="center")
        ax1.set_title("PPG brut"); ax1.set_ylabel("Amplitude"); ax1.grid(True, alpha=0.3)

        # PZT brut
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.plot(ts_a, pzt_a, color="tab:orange", lw=0.6, alpha=0.8)
        for ts_ev, lv in self.sensor.level_events:
            ax2.axvline(x=ts_ev, color="gray", alpha=0.3, lw=1)
            ax2.text(ts_ev, max(pzt_a)*0.97, f"N{lv}", fontsize=7, color="gray", ha="center")
        ax2.set_title("PZT brut"); ax2.set_ylabel("Amplitude"); ax2.grid(True, alpha=0.3)

        # FC par niveau
        ax3 = fig.add_subplot(gs[1, 0])
        fc_clean = [(l,v) for l,v in zip(levels,fc_vals) if v is not None]
        if fc_clean:
            ll, vv = zip(*fc_clean)
            ax3.plot(ll, vv, "o-", color="crimson", lw=2, ms=7)
        ax3.axvline(x=5, color="purple", ls="--", alpha=0.5, label="Limite 7±2 (Miller)")
        ax3.set_title("FC par niveau"); ax3.set_ylabel("FC (bpm)")
        ax3.set_xlabel("Niveau"); ax3.legend(fontsize=8); ax3.grid(True, alpha=0.3)

        # RR par niveau
        ax4 = fig.add_subplot(gs[1, 1])
        rr_clean = [(l,v) for l,v in zip(levels,rr_vals) if v is not None]
        if rr_clean:
            ll, vv = zip(*rr_clean)
            ax4.plot(ll, vv, "s-", color="darkorange", lw=2, ms=7)
        ax4.axvline(x=5, color="purple", ls="--", alpha=0.5, label="Limite 7±2 (Miller)")
        ax4.set_title("RR par niveau"); ax4.set_ylabel("RR (rpm)")
        ax4.set_xlabel("Niveau"); ax4.legend(fontsize=8); ax4.grid(True, alpha=0.3)

        # I_cog par niveau
        ax5 = fig.add_subplot(gs[2, 0])
        ic_clean = [(l,v) for l,v in zip(levels,ic_vals) if v is not None]
        if ic_clean:
            ll, vv = zip(*ic_clean)
            ax5.plot(ll, vv, "D-", color="tab:purple", lw=2, ms=7)
            ax5.fill_between(ll, vv, _CI.OVERLOAD_THRESHOLD,
                where=[v > _CI.OVERLOAD_THRESHOLD for v in vv], color="red", alpha=0.2, label="Surcharge")
        ax5.axhline(y=_CI.OVERLOAD_THRESHOLD, color="red", ls="--", alpha=0.7, label=f"Seuil {_CI.OVERLOAD_THRESHOLD}")
        ax5.axhline(y=0, color="gray", ls=":", alpha=0.4)
        ax5.axvline(x=5, color="purple", ls="--", alpha=0.5)
        ax5.set_title("I_cog par niveau"); ax5.set_ylabel("I_cog")
        ax5.set_xlabel("Niveau"); ax5.legend(fontsize=8); ax5.grid(True, alpha=0.3)

        # RT par niveau
        ax6 = fig.add_subplot(gs[2, 1])
        rt_clean = [(l,v) for l,v in zip(levels,rt_vals) if v is not None]
        if rt_clean:
            ll, vv = zip(*rt_clean)
            ax6.plot(ll, vv, "^-", color="teal", lw=2, ms=7)
        ax6.axvline(x=5, color="purple", ls="--", alpha=0.5, label="Limite 7±2 (Miller)")
        ax6.set_title("Temps de reaction par niveau"); ax6.set_ylabel("RT (ms)")
        ax6.set_xlabel("Niveau"); ax6.legend(fontsize=8); ax6.grid(True, alpha=0.3)

        plt.tight_layout()
        os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"{config.CSV_OUTPUT_DIR}/graph_{mode}_{ts_str}.png"
        plt.savefig(path, dpi=130, bbox_inches="tight")
        print(f"\n  {C.GREEN}Graphique sauvegarde : {path}{C.RESET}")
        plt.show()

    def _show_comparison(self):
        """Rapport comparatif Normal vs Chunking."""
        if "NORMAL" not in self.sessions or "CHUNKING" not in self.sessions:
            return
        try:
            from analysis import generate_comparison_report
            from signal_processing import SessionData as SD
            # Creer des SessionData a partir des donnees collectees
            sn = SD("NORMAL")
            sc = SD("CHUNKING")
            for d in self.sessions["NORMAL"]:
                sn.levels.append(d)
            for d in self.sessions["CHUNKING"]:
                sc.levels.append(d)
            os.makedirs(config.CSV_OUTPUT_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{config.CSV_OUTPUT_DIR}/rapport_comparatif_{ts}.png"
            generate_comparison_report(sn, sc, save_path=path)
            print(f"\n  {C.GREEN}Rapport comparatif : {path}{C.RESET}")
        except Exception as e:
            print(f"  {C.GRAY}Rapport non disponible : {e}{C.RESET}")
        input("\n  Entree pour continuer...")

    def _quit(self):
        print(f"\n  {C.YELLOW}Fermeture...{C.RESET}")
        self.acq.stop()
        self.sensor.stop()
        time.sleep(0.5)
        print(f"  {C.GREEN}Au revoir !{C.RESET}\n")


# ==============================================================
# POINT D'ENTREE
# ==============================================================

if __name__ == "__main__":
    def _sigint(sig, frame):
        print(f"\n{C.YELLOW}Interruption.{C.RESET}"); sys.exit(0)
    os_signal.signal(os_signal.SIGINT, _sigint)

    print()
    config.validate()
    print()
    ChunkyMemoGame().start()
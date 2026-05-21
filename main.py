"""
ChunkyMemo — main.py (final)

Pygame : moitié gauche de l'écran (mode fenêtré)
Matplotlib : moitié droite (processus séparé via graph_process.py)
"""

import os, sys, queue, threading, time
import multiprocessing as mp

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Détection résolution pour positionner matplotlib
try:
    import ctypes
    _sw = ctypes.windll.user32.GetSystemMetrics(0)
    _sh = ctypes.windll.user32.GetSystemMetrics(1)
except Exception:
    _sw, _sh = 1920, 1080

import pygame
import config
from game import Game
from session_data import SessionData
from signal_processing import PPGProcessor, PZTProcessor, CognitiveLoadIndex
from graph_process import graph_worker

try:
    from acquisition import AcquisitionThread
    print("[main] AcquisitionThread importé")
except ImportError as e:
    print(f"[main] ERREUR : {e}"); sys.exit(1)


# ──────────────────────────────────────────────────────────────
class PhysioState:
    def __init__(self):
        self._lock = threading.Lock()
        self.fc_bpm=self.rr_rpm=self.pwa_raw=self.i_cog=None
        self.overload=self.calibrated=self.apnea=False

    def update(self, fc, rr, pwa, i_cog, overload, calibrated, apnea):
        with self._lock:
            self.fc_bpm=fc;self.rr_rpm=rr;self.pwa_raw=pwa
            self.i_cog=i_cog;self.overload=overload
            self.calibrated=calibrated;self.apnea=apnea

    def snapshot(self):
        with self._lock:
            return dict(fc_bpm=self.fc_bpm,rr_rpm=self.rr_rpm,
                        pwa_raw=self.pwa_raw,i_cog=self.i_cog,
                        overload=self.overload,calibrated=self.calibrated,
                        apnea=self.apnea)


# ──────────────────────────────────────────────────────────────
class SignalThread(threading.Thread):
    def __init__(self, data_queue, physio_state, graph_queue):
        super().__init__(daemon=True)
        self.dq=data_queue; self.phys=physio_state; self.gq=graph_queue
        self.stop_event=threading.Event()
        self.ppg=PPGProcessor(); self.pzt=PZTProcessor(); self.cog=CognitiveLoadIndex()
        self._t0=time.time(); self._calibrated=False
        self._cv={"fc":[],"pwa":[],"rr":[]}; self.CALIB_SEC=20.0
        self.session=None; self._slock=threading.Lock(); self._hlock=threading.Lock()
        self._all_ts=[]; self._all_ppg=[]; self._all_pzt=[]
        self._fc_ts=[]; self._fc_v=[]
        self._rr_ts=[]; self._rr_v=[]
        self._ic_ts=[]; self._ic_v=[]
        self._key_events=[]
        self._last_graph=0; self.GRAPH_SEC=0.5

    def start_session(self, mode="NORMAL"):
        with self._slock: self.session=SessionData(mode)
        self._t0=time.time(); self._calibrated=False
        self._cv={"fc":[],"pwa":[],"rr":[]}
        self.ppg=PPGProcessor(); self.pzt=PZTProcessor(); self.cog=CognitiveLoadIndex()
        with self._hlock:
            self._all_ts.clear();self._all_ppg.clear();self._all_pzt.clear()
            self._fc_ts.clear();self._fc_v.clear()
            self._rr_ts.clear();self._rr_v.clear()
            self._ic_ts.clear();self._ic_v.clear()
            self._key_events.clear()
        print(f"[signal] Session {mode}")

    def get_session(self):
        with self._slock: return self.session

    def mark_level_start(self, level):
        with self._slock:
            if self.session: self.session.start_level(level)

    def mark_level_end(self, level, success, error_rate=0.0):
        snap=self.phys.snapshot()
        with self._slock:
            if self.session:
                self.session.end_level(success=success,
                    hr_bpm=snap["fc_bpm"],rr_rpm=snap["rr_rpm"],
                    ppg_amplitude=snap["pwa_raw"],error_rate=error_rate)

    def add_key_event(self, direction, correct):
        ts=time.time()-self._t0
        with self._hlock: self._key_events.append((ts,direction,correct))

    def run(self):
        while not self.stop_event.is_set():
            batch=[]
            try:
                while len(batch)<50: batch.append(self.dq.get_nowait())
            except queue.Empty: pass
            for s in batch: self._process(s)
            if not batch: time.sleep(0.01)

    def _process(self, s):
        ts=s["ts"]; ts_rel=ts-self._t0
        with self._slock:
            if self.session: self.session.add_sample(s)
        with self._hlock:
            self._all_ts.append(ts_rel)
            self._all_ppg.append(s["ppg"])
            self._all_pzt.append(s["pzt"])

        if ts_rel < self.CALIB_SEC:
            self.ppg.update(s["ppg"],ts); self.pzt.update(s["pzt"],ts)
            if self.ppg.fc_bpm:
                self._cv["fc"].append(self.ppg.fc_bpm)
                with self._hlock: self._fc_ts.append(ts_rel);self._fc_v.append(self.ppg.fc_bpm)
            if self.ppg.pwa_raw: self._cv["pwa"].append(self.ppg.pwa_raw)
            if self.pzt.rr_rpm:
                self._cv["rr"].append(self.pzt.rr_rpm)
                with self._hlock: self._rr_ts.append(ts_rel);self._rr_v.append(self.pzt.rr_rpm)
        else:
            if not self._calibrated: self._calibrate()
            self.ppg.update(s["ppg"],ts); self.pzt.update(s["pzt"],ts)
            ic=self.cog.update(self.ppg.fc_bpm,self.ppg.pwa_raw,self.pzt.rr_rpm,None,ts)
            with self._hlock:
                if self.ppg.fc_bpm: self._fc_ts.append(ts_rel);self._fc_v.append(self.ppg.fc_bpm)
                if self.pzt.rr_rpm: self._rr_ts.append(ts_rel);self._rr_v.append(self.pzt.rr_rpm)
                if ic is not None:  self._ic_ts.append(ts_rel);self._ic_v.append(ic)

        self.phys.update(fc=self.ppg.fc_bpm,rr=self.pzt.rr_rpm,pwa=self.ppg.pwa_raw,
                         i_cog=self.cog.i_cog,overload=self.cog.overload,
                         calibrated=self._calibrated,apnea=self.pzt.apnea_detected)
        now=time.time()
        if now-self._last_graph>=self.GRAPH_SEC:
            self._last_graph=now; self._send(ts_rel)

    def _calibrate(self):
        import numpy as np
        self._calibrated=True
        if self._cv["pwa"]:
            self.ppg.set_baseline(float(np.mean(self._cv["pwa"])))
            self.cog.set_baseline("pwa",self._cv["pwa"])
        if self._cv["fc"]:  self.cog.set_baseline("fc", self._cv["fc"])
        if self._cv["rr"]:  self.cog.set_baseline("rr", self._cv["rr"])
        # Baseline RT par défaut 500ms ± 100ms (sera affinée en jeu)
        self.cog.set_baseline("rt", [400.0, 450.0, 500.0, 550.0, 600.0])
        print("[signal] Calibration appliquée")

    def _send(self, ts_rel):
        rem=max(0,self.CALIB_SEC-ts_rel)
        try:
            ppg_buf =list(self.ppg._buf)[-500:]
            pzt_buf =list(self.pzt._buf)[-500:]
            ppg_filt=list(self.ppg.get_filtered_signal())[-500:]
            pzt_filt=list(self.pzt.get_filtered_signal())[-500:]
            snap=self.phys.snapshot(); bl=self.cog._baseline
            with self._hlock:
                all_ts =list(self._all_ts)[-1000:]
                fc_ts  =list(self._fc_ts)[-600:];  fc_v =list(self._fc_v)[-600:]
                rr_ts  =list(self._rr_ts)[-600:];  rr_v =list(self._rr_v)[-600:]
                ic_ts  =list(self._ic_ts)[-600:];  ic_v =list(self._ic_v)[-600:]
                fc_hist=[(t,v) for t,v in zip(self._fc_ts,self._fc_v) if v is not None][-200:]
                rr_hist=[(t,v) for t,v in zip(self._rr_ts,self._rr_v) if v is not None][-200:]
                key_ev =list(self._key_events)[-200:]

            fc_str=f"{snap['fc_bpm']:.0f}bpm" if snap["fc_bpm"] else "---"
            rr_str=f"{snap['rr_rpm']:.0f}rpm" if snap["rr_rpm"] else "---"
            ic_str=f"{snap['i_cog']:.2f}"      if snap["i_cog"] is not None else "---"

            if not self._calibrated:
                self.gq.put_nowait({"type":"calib_update",
                    "ppg_raw":ppg_buf,"ppg_filt":ppg_filt,"ppg_peaks":list(self.ppg.last_peaks),
                    "pzt_raw":pzt_buf,"pzt_filt":pzt_filt,"pzt_peaks":list(self.pzt.last_peaks),
                    "fc_hist":fc_hist,"rr_hist":rr_hist,
                    "fc_str":fc_str,"rr_str":rr_str,"remaining":rem})
            else:
                self.gq.put_nowait({"type":"game_update",
                    "ppg_raw":ppg_buf,"ppg_filt":ppg_filt,"ppg_peaks":list(self.ppg.last_peaks),
                    "pzt_raw":pzt_buf,"pzt_filt":pzt_filt,"pzt_peaks":list(self.pzt.last_peaks),
                    "all_ts":all_ts,"fc_v":fc_v,"rr_v":rr_v,
                    "ic_ts":ic_ts,"ic_v":ic_v,"key_events":key_ev,
                    "bl_fc":bl["fc"]["mu"],"bl_rr":bl["rr"]["mu"],
                    "fc_str":fc_str,"rr_str":rr_str,"ic_str":ic_str,
                    "overload":snap["overload"],"apnea":snap["apnea"]})
        except Exception: pass

    def build_final_report_data(self):
        with self._slock: session=self.session
        with self._hlock:
            # Rapport final = TOUTE la session, pas de limite
            all_ts=list(self._all_ts);all_ppg=list(self._all_ppg);all_pzt=list(self._all_pzt)
            fc_ts=list(self._fc_ts);fc_v=list(self._fc_v)
            rr_ts=list(self._rr_ts);rr_v=list(self._rr_v)
            ic_ts=list(self._ic_ts);ic_v=list(self._ic_v)   # toute la session
            key_ev=list(self._key_events)
        bl=self.cog._baseline; snap=self.phys.snapshot()
        lvs=list(session.levels) if session else []
        lev_evs=list(session.level_events) if session else []
        for lv in lvs:
            lv["ts_start"]=next((t for t,l in lev_evs if l==lv.get("level")),None)
        return {"type":"final_report","levels":lvs,
            "all_ts":all_ts,"all_ppg":all_ppg,"all_pzt":all_pzt,
            "fc_ts":[t for t,v in zip(fc_ts,fc_v) if v is not None],
            "fc_v" :[v for v in fc_v if v is not None],
            "rr_ts":[t for t,v in zip(rr_ts,rr_v) if v is not None],
            "rr_v" :[v for v in rr_v if v is not None],
            "ic_ts":ic_ts,"ic_v":ic_v,
            "ppg_filt":list(self.ppg.get_filtered_signal()),
            "ppg_peaks":list(self.ppg.last_peaks),
            "pzt_filt":list(self.pzt.get_filtered_signal()),
            "pzt_peaks":list(self.pzt.last_peaks),
            "bl_fc":bl["fc"]["mu"],"bl_rr":bl["rr"]["mu"],
            "fc_final":snap["fc_bpm"],"rr_final":snap["rr_rpm"],
            "ic_final":snap["i_cog"],
            "mode":session.mode if session else "NORMAL",
            "key_events":key_ev,"calib_sec":self.CALIB_SEC}

    def stop(self): self.stop_event.set()


# ──────────────────────────────────────────────────────────────
def _gq(gq, msg):
    try: gq.put_nowait(msg)
    except Exception: pass

def patch_game(game, physio_state, sig_thread, gq):
    game.physio_state=physio_state; game.signal_thread=sig_thread
    game.gq=gq; game._graph_phase="none"
    _patch_calib(game,sig_thread,gq)
    _patch_single(game,sig_thread,gq)
    _patch_pair(game,sig_thread)
    _patch_lost(game,sig_thread,gq)
    _patch_summary(game,sig_thread,gq)

def _patch_calib(game,sig,gq):
    from game import CalibrationState
    orig=CalibrationState.update
    def nu(self_c):
        if not self_c.inited:
            sig.start_session("NORMAL")
            _gq(gq,{"type":"open_calib"}); game._graph_phase="calibration"
        orig(self_c)
        if game.current_state is not self_c and game._graph_phase=="calibration":
            _gq(gq,{"type":"close_calib"}); _gq(gq,{"type":"open_game"})
            game._graph_phase="game"
    CalibrationState.update=nu

def _patch_single(game,sig,gq):
    from game import SingleArrowState
    oi=SingleArrowState.__init__; on=SingleArrowState._start_next_round
    oh=SingleArrowState.handle_player_inputs
    _ld={"e":0,"t":0}
    def ni(self_s,gr):
        oi(self_s,gr)
        if game._graph_phase not in ("game",):
            _gq(gq,{"type":"close_game"}); _gq(gq,{"type":"open_game"})
            game._graph_phase="game"
        sig.mark_level_start(self_s.arrows_count); _ld["e"]=0;_ld["t"]=0
    def nn(self_s):
        sig.mark_level_end(self_s.arrows_count,True,_ld["e"]/max(1,_ld["t"]))
        on(self_s); sig.mark_level_start(self_s.arrows_count); _ld["e"]=0;_ld["t"]=0
    def nh(self_s):
        was=game.current_state
        if not self_s.show_arrows and self_s.chosen_direction is not None:
            _ld["t"]+=1
            exp=self_s.arrow_directions[self_s.pressed_directions]
            c=(self_s.chosen_direction==exp)
            if not c: _ld["e"]+=1
            sig.add_key_event(self_s.chosen_direction,c)
        oh(self_s)
        if game.current_state is not self_s and was is self_s:
            sig.mark_level_end(self_s.arrows_count,False,_ld["e"]/max(1,_ld["t"]))
    SingleArrowState.__init__=ni
    SingleArrowState._start_next_round=nn
    SingleArrowState.handle_player_inputs=nh

def _patch_pair(game,sig):
    from game import PairArrowState
    oi=PairArrowState.__init__; ou=PairArrowState.update
    def ni(self_p,gr,initial_count=1):
        oi(self_p,gr,initial_count); sig.mark_level_start(len(self_p.pair_directions))
    def nu(self_p):
        was=game.current_state; ou(self_p)
        if game.current_state is not self_p and was is self_p:
            sig.mark_level_end(len(self_p.pair_directions),False)
    PairArrowState.__init__=ni; PairArrowState.update=nu

def _patch_lost(game,sig,gq):
    from game import LostState
    orig=LostState.handle_events
    def nh(self_l,events):
        import pygame as _pg
        for ev in events:
            if ev.type==_pg.KEYDOWN and ev.key==_pg.K_SPACE:
                sig.start_session("NORMAL")
                _gq(gq,{"type":"close_game"}); _gq(gq,{"type":"open_game"})
                game._graph_phase="game"
        orig(self_l,events)
    LostState.handle_events=nh

def _patch_summary(game,sig,gq):
    from game import SummaryState
    oi=SummaryState.__init__; oh=SummaryState.handle_events
    def ni(self_s,gr):
        oi(self_s,gr); game._graph_phase="summary"
        _gq(gq,{"type":"close_game"})
        try: _gq(gq,sig.build_final_report_data())
        except Exception as e: print(f"[rapport] {e}")
    def nh(self_s,events):
        import pygame as _pg
        oh(self_s,events)
        for ev in events:
            if ev.type==_pg.KEYDOWN and ev.key==_pg.K_ESCAPE:
                game.current_state=game.states["menu"]; game._graph_phase="none"
    SummaryState.__init__=ni; SummaryState.handle_events=nh


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mp.freeze_support()
    config.validate()

    # Processus graphe (matplotlib dans la moitié droite)
    graph_queue = mp.Queue(maxsize=50)
    graph_proc  = mp.Process(target=graph_worker, args=(graph_queue, _sw), daemon=True)
    graph_proc.start()
    print(f"[main] Processus graphe démarré (écran={_sw}x{_sh})")

    data_q       = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
    physio_state = PhysioState()
    acq_thread   = AcquisitionThread(data_q)
    sig_thread   = SignalThread(data_q, physio_state, graph_queue)

    acq_thread.start(); sig_thread.start()

    print("[main] Attente données BITalino (3s max)...")
    for _ in range(30):
        if not data_q.empty(): break
        time.sleep(0.1)
    if data_q.empty():
        print("[main] AVERTISSEMENT : aucune donnée BITalino")

    # pygame dans la moitié gauche
    pygame.init()
    game = Game()

    game._graph_phase  = "none"

    patch_game(game, physio_state, sig_thread, graph_queue)

    print("[main] Jeu démarré — pygame gauche, graphes droite")
    game.run()
    pygame.quit()

    acq_thread.stop(); sig_thread.stop()
    _gq(graph_queue, {"type":"quit"})
    acq_thread.join(timeout=2); sig_thread.join(timeout=2)
    graph_proc.join(timeout=3)
    print("[main] Terminé")
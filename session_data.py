"""
SessionData — structure de données par session de jeu.
"""
import time


class SessionData:
    def __init__(self, mode: str):
        self.mode           = mode
        self.levels         = []
        self.raw_ppg        = []
        self.raw_pzt        = []
        self.timestamps     = []
        self.level_events   = []
        self._start_time    = time.time()
        self._current_level = None

    def add_sample(self, sample: dict):
        ts_rel = sample["ts"] - self._start_time
        self.timestamps.append(ts_rel)
        self.raw_ppg.append(sample.get("ppg", 0))
        self.raw_pzt.append(sample.get("pzt", 0))

    def start_level(self, level: int):
        self._current_level = level
        ts_rel = time.time() - self._start_time
        self.level_events.append((ts_rel, level))

    def end_level(self, success: bool, hr_bpm=None, rr_rpm=None,
                  ppg_amplitude=None, resp_pauses: int = 0,
                  rt_ms=None, error_rate: float = 0.0):
        """Enregistre les métriques physiologiques + comportementales d'un niveau."""
        self.levels.append({
            "level":         self._current_level,
            "success":       success,
            "hr_bpm":        hr_bpm,
            "rr_rpm":        rr_rpm,
            "ppg_amplitude": ppg_amplitude,
            "resp_pauses":   resp_pauses,
            "rt_ms":         rt_ms,
            "error_rate":    error_rate,
        })
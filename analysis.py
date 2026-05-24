"""
analysis.py - Comparaison Normal vs Chunking - figures individuelles
"""

import glob
import json
import logging
import os
import sys
import time

_HEADLESS = os.environ.get("MPLBACKEND") == "Agg"
if _HEADLESS:
    import matplotlib

    matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as ticker  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

EVENTS_FILE = "sessions/live_events.json"
MILLER = 5
C_N = "#E24B4A"
C_C = "#1D9E75"


def load_data():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE) as f:
            return json.load(f)
    files = sorted(glob.glob("sessions/live_events*.json"), reverse=True)
    if files:
        with open(files[0]) as f:
            return json.load(f)
    logging.error("Aucune session trouvée")
    sys.exit(1)


def _vals(levels, key):
    pairs = [(int(lv["level"]), lv[key]) for lv in levels if lv.get(key) is not None]
    if not pairs:
        return [], []
    pairs.sort()
    ls, vs = zip(*pairs)
    return list(ls), list(vs)


def _xmax(ln, lc):
    return max([max(ln) if ln else 0, max(lc) if lc else 0, MILLER + 1])


def _decor(ax, ln, lc):
    xmax = _xmax(ln, lc)
    ax.axvline(x=MILLER, color="purple", ls="--", alpha=0.7, lw=1.5)
    ax.axvspan(MILLER, xmax + 0.6, alpha=0.06, color="green")
    ax.set_xlim(0.5, xmax + 0.6)


def _base(ax, title, ylabel):
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Niveau du jeu", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.tick_params(labelsize=10)


def _legend():
    return [
        Line2D([0], [0], color=C_N, lw=2.5, marker="o", ms=8, label="Mode Normal"),
        Line2D([0], [0], color=C_C, lw=2.5, marker="s", ms=8, label="Mode Chunking"),
        Line2D(
            [0], [0], color="purple", lw=1.5, ls="--", label="Limite 7+/-2 (Miller)"
        ),
    ]


def _note(ax, txt):
    ax.text(
        0.97,
        0.05,
        txt,
        transform=ax.transAxes,
        fontsize=9,
        ha="right",
        va="bottom",
        color="#555",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.8, ec="#aaa"),
    )


def _no_data(ax):
    ax.text(
        0.5,
        0.5,
        "Pas de donnees physio disponibles",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=13,
        color="gray",
        style="italic",
    )


def _errs(keys, levels):
    res = {}
    for i, lv in enumerate(levels):
        t0 = lv["ts"]
        t1 = levels[i + 1]["ts"] if i + 1 < len(levels) else float("inf")
        lk = [k for k in keys if t0 <= k["ts"] < t1]
        if lk:
            res[int(lv["level"])] = (
                100 * sum(1 for k in lk if not k["correct"]) / len(lk)
            )
    return res


def save_figures(data, prefix):
    levels_n = [lv for lv in data.get("levels_normal", []) if lv.get("level")]
    levels_c = [lv for lv in data.get("levels_chunking", []) if lv.get("level")]
    keys_n = data.get("keys_normal", [])
    keys_c = data.get("keys_chunking", [])
    paths = []

    def _save(fig, name):
        p = f"{prefix}_{name}.png"
        fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        paths.append(p)
        logging.info(f"[analysis] {p}")

    # Figure 1 : FC
    fig, ax = plt.subplots(figsize=(8, 5))
    _base(ax, "Frequence cardiaque par niveau", "FC (bpm)")
    ln, vn = _vals(levels_n, "hr_bpm")
    lc, vc = _vals(levels_c, "hr_bpm")
    _decor(ax, ln, lc)
    if ln:
        ax.plot(ln, vn, "o-", color=C_N, lw=2.5, ms=8)
        ax.fill_between(ln, vn, alpha=0.12, color=C_N)
    if lc:
        ax.plot(lc, vc, "s--", color=C_C, lw=2.5, ms=8)
        ax.fill_between(lc, vc, alpha=0.12, color=C_C)
    if not ln and not lc:
        _no_data(ax)
    _note(ax, "FC augmente sous charge\n(Shi et al., 2023)")
    ax.legend(handles=_legend(), fontsize=10, loc="upper left")
    plt.tight_layout()
    _save(fig, "1_FC")

    # Figure 2 : RR
    fig, ax = plt.subplots(figsize=(8, 5))
    _base(ax, "Rythme respiratoire par niveau", "Resp. (cycles/min)")
    ln, vn = _vals(levels_n, "rr_rpm")
    lc, vc = _vals(levels_c, "rr_rpm")
    _decor(ax, ln, lc)
    if ln:
        ax.plot(ln, vn, "o-", color=C_N, lw=2.5, ms=8)
        ax.fill_between(ln, vn, alpha=0.12, color=C_N)
    if lc:
        ax.plot(lc, vc, "s--", color=C_C, lw=2.5, ms=8)
        ax.fill_between(lc, vc, alpha=0.12, color=C_C)
    if not ln and not lc:
        _no_data(ax)
    _note(ax, "Apnee cognitive N7+\n(Studer et al., 2021)")
    ax.legend(handles=_legend(), fontsize=10, loc="upper left")
    plt.tight_layout()
    _save(fig, "2_RR")

    # Figure 3 : PWA
    fig, ax = plt.subplots(figsize=(8, 5))
    _base(ax, "Amplitude onde de pouls (PWA)", "Amplitude PPG (u.a.)")
    ln, vn = _vals(levels_n, "ppg_amplitude")
    lc, vc = _vals(levels_c, "ppg_amplitude")
    _decor(ax, ln, lc)
    if ln:
        ax.plot(ln, vn, "o-", color=C_N, lw=2.5, ms=8)
        ax.fill_between(ln, vn, alpha=0.12, color=C_N)
    if lc:
        ax.plot(lc, vc, "s--", color=C_C, lw=2.5, ms=8)
        ax.fill_between(lc, vc, alpha=0.12, color=C_C)
    if not ln and not lc:
        _no_data(ax)
    ax.invert_yaxis()
    _note(ax, "PWA diminue = charge elevee\n(Shi et al., 2023)")
    ax.legend(handles=_legend(), fontsize=10, loc="upper left")
    plt.tight_layout()
    _save(fig, "3_PWA")

    # Figure 4 : Succes
    fig, ax = plt.subplots(figsize=(8, 5))
    _base(ax, "Succes par niveau", "Succes (1=oui, 0=non)")
    ax.set_ylim(0, 1.3)
    all_n = [lv["level"] for lv in levels_n]
    all_c = [lv["level"] for lv in levels_c]
    _decor(ax, all_n, all_c)
    for lv in levels_n:
        ax.bar(
            lv["level"] - 0.22,
            1 if lv.get("success") else 0,
            width=0.42,
            color=C_N,
            alpha=0.85,
            edgecolor="white",
        )
    for lv in levels_c:
        ax.bar(
            lv["level"] + 0.22,
            1 if lv.get("success") else 0,
            width=0.42,
            color=C_C,
            alpha=0.85,
            edgecolor="white",
        )
    ax.legend(handles=_legend()[:2], fontsize=10, loc="lower left")
    plt.tight_layout()
    _save(fig, "4_Succes")

    # Figure 5 : Taux d'erreur
    err_n = _errs(keys_n, levels_n)
    err_c = _errs(keys_c, levels_c)
    fig, ax = plt.subplots(figsize=(8, 5))
    _base(ax, "Taux d'erreur par niveau", "Taux d'erreur (%)")
    ax.set_ylim(0, 105)
    _decor(ax, list(err_n.keys()), list(err_c.keys()))
    if err_n:
        sl = sorted(err_n.keys())
        ax.bar(
            [l - 0.22 for l in sl],
            [err_n[l] for l in sl],
            width=0.42,
            color=C_N,
            alpha=0.85,
            edgecolor="white",
            label="Normal",
        )
    if err_c:
        sl = sorted(err_c.keys())
        ax.bar(
            [l + 0.22 for l in sl],
            [err_c[l] for l in sl],
            width=0.42,
            color=C_C,
            alpha=0.85,
            edgecolor="white",
            label="Chunking",
        )
    if not err_n and not err_c:
        _no_data(ax)
    ax.legend(fontsize=10, loc="upper left")
    plt.tight_layout()
    _save(fig, "5_Erreur")

    return paths


def main():
    data = load_data()
    os.makedirs("sessions", exist_ok=True)
    prefix = f"sessions/fig_{time.strftime('%Y%m%d_%H%M%S')}"
    paths = save_figures(data, prefix)
    # Aussi garder la figure combinee pour compatibilite
    try:
        # Ecrire le chemin des figures dans un fichier index
        index_file = "sessions/figures_index.json"
        with open(index_file, "w") as f:
            json.dump({"figures": paths, "ts": time.strftime("%Y%m%d_%H%M%S")}, f)
        logging.info(f"[analysis] Index: {index_file}")
    except Exception:
        pass


if __name__ == "__main__":
    main()

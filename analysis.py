"""
analysis.py - Comparaison Normal vs Chunking depuis live_events.json
"""
import json, sys, os, glob, time
import numpy as np

_HEADLESS = os.environ.get("MPLBACKEND") == "Agg"
if _HEADLESS:
    import matplotlib
    matplotlib.use("Agg")

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D

EVENTS_FILE = "sessions/live_events.json"
MILLER = 5
C_N = "#E24B4A"
C_C = "#1D9E75"

NOTE_FC  = "FC augmente sous charge\n(Shi et al., 2023)"
NOTE_RR  = "Apnee cognitive N7+\n(Studer et al., 2021)"
NOTE_PWA = "PWA diminue = charge elevee\n(Shi et al., 2023)"


def load_data():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE) as f:
            return json.load(f)
    files = sorted(glob.glob("sessions/live_events*.json"), reverse=True)
    if files:
        with open(files[0]) as f:
            return json.load(f)
    print("Aucune session trouvee"); sys.exit(1)


def build_figure(data):
    levels_n = [lv for lv in data.get("levels_normal",   []) if lv.get("level")]
    levels_c = [lv for lv in data.get("levels_chunking", []) if lv.get("level")]
    keys_n   = data.get("keys_normal",   [])
    keys_c   = data.get("keys_chunking", [])

    fig = plt.figure(figsize=(14, 11))
    gs  = gridspec.GridSpec(3, 2, figure=fig,
                            height_ratios=[2, 2, 2], hspace=0.55, wspace=0.38)

    fig.suptitle(
        "ChunkyMemo - Mode Normal vs Chunking\nImpact de la charge cognitive",
        fontsize=12, fontweight="bold")

    legend_elems = [
        Line2D([0],[0], color=C_N, lw=2, marker="o", ms=6, label="Mode Normal"),
        Line2D([0],[0], color=C_C, lw=2, marker="s", ms=6, label="Mode Chunking"),
        Line2D([0],[0], color="purple", lw=1, ls="--", label="Limite 7+/-2 Miller"),
    ]
    fig.legend(handles=legend_elems, loc="upper right",
               bbox_to_anchor=(0.98, 0.97), fontsize=10)

    def _vals(levels, key):
        pairs = [(int(lv["level"]), lv[key])
                 for lv in levels if lv.get(key) is not None]
        if not pairs:
            return [], []
        pairs.sort()
        ls, vs = zip(*pairs)
        return list(ls), list(vs)

    def _xmax(ln, lc):
        return max([max(ln) if ln else 0, max(lc) if lc else 0, MILLER+1])

    def _setup_ax(ax, title, ylabel):
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Niveau du jeu", fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    def _plot_metric(ax, levels_n, levels_c, key, title, ylabel, note):
        _setup_ax(ax, title, ylabel)
        ln, vn = _vals(levels_n, key)
        lc, vc = _vals(levels_c, key)
        xmax = _xmax(ln, lc)
        ax.axvline(x=MILLER, color="purple", ls="--", alpha=0.6, lw=1.2)
        ax.axvspan(MILLER, xmax+0.6, alpha=0.06, color="green")
        ax.set_xlim(0.5, xmax+0.6)
        if ln:
            ax.plot(ln, vn, "o-", color=C_N, lw=2, ms=7)
            ax.fill_between(ln, vn, alpha=0.12, color=C_N)
        if lc:
            ax.plot(lc, vc, "s--", color=C_C, lw=2, ms=7)
            ax.fill_between(lc, vc, alpha=0.12, color=C_C)
        if not ln and not lc:
            ax.text(0.5, 0.5, "Pas de donnees physio",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=10, color="gray", style="italic")
        ax.text(0.97, 0.05, note, transform=ax.transAxes, fontsize=7.5,
                ha="right", va="bottom", color="#555",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.7, ec="#aaa"))

    # ── FC
    _plot_metric(fig.add_subplot(gs[0, 0]), levels_n, levels_c,
                 "hr_bpm", "Frequence cardiaque par niveau", "FC (bpm)", NOTE_FC)

    # ── RR
    _plot_metric(fig.add_subplot(gs[0, 1]), levels_n, levels_c,
                 "rr_rpm", "Rythme respiratoire par niveau", "Resp. (cycles/min)", NOTE_RR)

    # ── PWA
    ax_pwa = fig.add_subplot(gs[1, 0])
    _plot_metric(ax_pwa, levels_n, levels_c,
                 "ppg_amplitude", "Amplitude onde de pouls (PWA)", "Amplitude PPG", NOTE_PWA)
    ax_pwa.invert_yaxis()

    # ── Succes
    ax_suc = fig.add_subplot(gs[1, 1])
    _setup_ax(ax_suc, "Succes par niveau", "Succes (1=oui, 0=non)")
    ax_suc.set_ylim(0, 1.3)
    all_lvs_n = [lv["level"] for lv in levels_n]
    all_lvs_c = [lv["level"] for lv in levels_c]
    xmax_s = _xmax(all_lvs_n, all_lvs_c)
    ax_suc.axvline(x=MILLER, color="purple", ls="--", alpha=0.6, lw=1.2)
    ax_suc.axvspan(MILLER, xmax_s+0.6, alpha=0.06, color="green")
    ax_suc.set_xlim(0.5, xmax_s+0.6)
    for lv in levels_n:
        ax_suc.bar(lv["level"]-0.2, 1 if lv.get("success") else 0,
                   width=0.38, color=C_N, alpha=0.85, edgecolor="white")
    for lv in levels_c:
        ax_suc.bar(lv["level"]+0.2, 1 if lv.get("success") else 0,
                   width=0.38, color=C_C, alpha=0.85, edgecolor="white")

    # ── Taux d'erreur
    ax_err = fig.add_subplot(gs[2, :])
    _setup_ax(ax_err, "Taux d'erreur par niveau - Normal vs Chunking", "Taux d'erreur (%)")
    ax_err.set_ylim(0, 105)

    def _compute_errors(keys, levels):
        result = {}
        for i, lv in enumerate(levels):
            t0 = lv["ts"]
            t1 = levels[i+1]["ts"] if i+1 < len(levels) else float("inf")
            lv_keys = [k for k in keys if t0 <= k["ts"] < t1]
            if lv_keys:
                n_err = sum(1 for k in lv_keys if not k["correct"])
                result[int(lv["level"])] = 100 * n_err / len(lv_keys)
        return result

    err_n = _compute_errors(keys_n, levels_n)
    err_c = _compute_errors(keys_c, levels_c)
    xmax_e = _xmax(list(err_n.keys()), list(err_c.keys()))
    ax_err.axvline(x=MILLER, color="purple", ls="--", alpha=0.6, lw=1.2)
    ax_err.axvspan(MILLER, xmax_e+0.6, alpha=0.06, color="green")
    ax_err.set_xlim(0.5, xmax_e+0.6)
    if err_n:
        lvs_sorted = sorted(err_n.keys())
        ax_err.bar([l-0.2 for l in lvs_sorted], [err_n[l] for l in lvs_sorted],
                   width=0.38, color=C_N, alpha=0.85, edgecolor="white", label="Normal")
    if err_c:
        lvs_sorted = sorted(err_c.keys())
        ax_err.bar([l+0.2 for l in lvs_sorted], [err_c[l] for l in lvs_sorted],
                   width=0.38, color=C_C, alpha=0.85, edgecolor="white", label="Chunking")
    if not err_n and not err_c:
        ax_err.text(0.5, 0.5, "Pas de touches enregistrees",
                    transform=ax_err.transAxes, ha="center", va="center",
                    fontsize=10, color="gray", style="italic")
    ax_err.legend(fontsize=9)

    plt.tight_layout(rect=[0, 0, 0.85, 0.93])
    return fig


def main():
    data  = load_data()
    fig   = build_figure(data)
    os.makedirs("sessions", exist_ok=True)
    fname = f"sessions/comparaison_{time.strftime('%Y%m%d_%H%M%S')}.png"
    fig.savefig(fname, dpi=130, bbox_inches="tight")
    print(f"[analysis] Sauvegarde : {fname}")
    if not _HEADLESS:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
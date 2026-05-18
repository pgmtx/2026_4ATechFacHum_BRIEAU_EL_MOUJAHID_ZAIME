#Génère les graphiques comparatifs entre mode Normal et mode Chunking après une session de jeu.


import time
import math
import random
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import signal as sp_signal

import config
from signal_processing import SessionData, PPGProcessor, PZTProcessor


#PALETTE DE COULEURS 

COLOR_NORMAL   = "#E24B4A"    # rouge pour mode normal (plus difficile)
COLOR_CHUNKING = "#1D9E75"    # vert  pour mode chunking (facilite par regroupement)
COLOR_PPG      = "#E24B4A"    # rouge pour PPG
COLOR_PZT      = "#EF9F27"    # orange pour PZT
COLOR_GRID     = "#EEEEEE"
COLOR_ANNOT    = "#888888"
ALPHA_FILL     = 0.15         # transparence des zones remplies


#fct principale pour generer tous les graphiques

def generate_comparison_report(
    session_normal:   SessionData,
    session_chunking: SessionData,
    save_path: str = None
):
    

    print("[analysis] Génération du rapport comparatif...")

    #extraction des métriques par niveau
    normal_data   = _extract_level_metrics(session_normal)
    chunking_data = _extract_level_metrics(session_chunking)

    #figure principale
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(
        "ChunkyMemo — Analyse physiologique : Mode Normal vs Chunking\n"
        "Impact de la charge cognitive sur les signaux PPG et PZT",
        fontsize=14, fontweight="bold", y=0.98
    )

    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

    ax1 = fig.add_subplot(gs[0, 0])   # FC par niveau
    ax2 = fig.add_subplot(gs[0, 1])   # Rythme resp. par niveau
    ax3 = fig.add_subplot(gs[1, 0])   # Amplitude PPG par niveau
    ax4 = fig.add_subplot(gs[1, 1])   # Taux de succès par niveau
    ax5 = fig.add_subplot(gs[2, :])   # Signal PZT brut annoté

    #Graph 1: Frequence cardiaque par niveau
    _plot_metric_comparison(
        ax1,
        normal_data,   "hr_bpm",
        chunking_data, "hr_bpm",
        title="Fréquence cardiaque par niveau",
        ylabel="FC (bpm)",
        ref_line=None,
        annotation="↑ FC sous charge cognitive\n(Shi et al., 2023)"
    )
    # Ligne de référence : zone normale au repos (60-80 bpm)
    ax1.axhspan(60, 80, alpha=0.08, color="gray", label="Zone repos (60–80 bpm)")

    #Graph 2: Rythme respiratoire
    _plot_metric_comparison(
        ax2,
        normal_data,   "rr_rpm",
        chunking_data, "rr_rpm",
        title="Rythme respiratoire par niveau",
        ylabel="Resp. (cycles/min)",
        ref_line=None,
        annotation="Apnée cognitive attendue\nà partir du niveau 7\n(Studer et al., 2021)"
    )
    #Ligne Miller: capacité limite mémoire de travail
    ax2.axvline(x=5, color="purple", linestyle="--", alpha=0.5,
                label="Limite 7±2 (Miller 1956)\n= niveau 5 (7 flèches)")

    #Graphique 3: amplitude PPG (proxy charge cognitive)
    _plot_metric_comparison(
        ax3,
        normal_data,   "ppg_amplitude",
        chunking_data, "ppg_amplitude",
        title="Amplitude onde de pouls (PWA)",
        ylabel="Amplitude PPG (u.a.)",
        annotation="↓ PWA = ↑ charge cognitive\n(Shi et al., 2023)"
    )
    ax3.invert_yaxis()   

    #Graphique 4: Taux de succès
    _plot_success_rate(ax4, normal_data, chunking_data)

    #Graphique 5 : Signal PZT brut annoté 
    _plot_raw_pzt_annotated(ax5, session_normal, session_chunking)

    #legende globale 
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color=COLOR_NORMAL,   linewidth=2, label="Mode Normal"),
        Line2D([0], [0], color=COLOR_CHUNKING, linewidth=2, label="Mode Chunking"),
        Line2D([0], [0], color="purple",       linewidth=1,
               linestyle="--", label="Limite 7±2 (Miller, 1956)"),
    ]
    fig.legend(handles=legend_elements, loc="upper right",
               bbox_to_anchor=(0.98, 0.97), fontsize=10)

    #sauvegarde/affichage
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[analysis] Rapport sauvegardé : {save_path}")
    else:
        plt.show()

    # resume statistique
    summary = _compute_summary(normal_data, chunking_data)
    _print_summary(summary)

    return summary


# fcts D'AIDE AUX GRAPHIQUES

def _extract_level_metrics(session: SessionData) -> dict:
   
    levels       = []
    hr_bpm       = []
    rr_rpm       = []
    ppg_amplitude = []
    success      = []

    for lv in session.levels:
        levels.append(lv["level"])
        hr_bpm.append(lv.get("hr_bpm"))
        rr_rpm.append(lv.get("rr_rpm"))
        ppg_amplitude.append(lv.get("ppg_amplitude"))
        success.append(1 if lv.get("success") else 0)

    return {
        "levels":        np.array(levels),
        "hr_bpm":        np.array([v if v is not None else np.nan for v in hr_bpm]),
        "rr_rpm":        np.array([v if v is not None else np.nan for v in rr_rpm]),
        "ppg_amplitude": np.array([v if v is not None else np.nan for v in ppg_amplitude]),
        "success":       np.array(success),
        "mode":          session.mode,
    }


def _plot_metric_comparison(ax, normal, normal_key, chunking, chunking_key,
                             title, ylabel, ref_line=None, annotation=None):
    
    # Mode Normal
    n_lvl = normal["levels"]
    n_val = normal[normal_key]
    valid_n = ~np.isnan(n_val)
    if valid_n.any():
        ax.plot(n_lvl[valid_n], n_val[valid_n],
                "o-", color=COLOR_NORMAL, linewidth=2, markersize=6,
                label="Normal", zorder=3)
        ax.fill_between(n_lvl[valid_n], n_val[valid_n],
                        alpha=ALPHA_FILL, color=COLOR_NORMAL)

    # Mode Chunking
    c_lvl = chunking["levels"]
    c_val = chunking[chunking_key]
    valid_c = ~np.isnan(c_val)
    if valid_c.any():
        ax.plot(c_lvl[valid_c], c_val[valid_c],
                "s--", color=COLOR_CHUNKING, linewidth=2, markersize=6,
                label="Chunking", zorder=3)
        ax.fill_between(c_lvl[valid_c], c_val[valid_c],
                        alpha=ALPHA_FILL, color=COLOR_CHUNKING)

    #ligne de référence optionnelle
    if ref_line is not None:
        ax.axhline(y=ref_line, color="gray", linestyle=":", linewidth=1)

    #ligne Miller (capacité mémoire de travail : 7 éléments = niveau 5)
    ax.axvline(x=5, color="purple", linestyle="--", alpha=0.4, linewidth=1)

    ax.set_title(title, fontsize=11, pad=8)
    ax.set_xlabel("Niveau du jeu", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, color=COLOR_GRID, linewidth=0.5)

    #annotation optionnelle
    if annotation:
        ax.text(0.97, 0.05, annotation,
                transform=ax.transAxes, fontsize=7,
                color=COLOR_ANNOT, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                          alpha=0.7, edgecolor=COLOR_ANNOT))


def _plot_success_rate(ax, normal, chunking):
   
    #aligner les niveaux communs
    all_levels = sorted(set(list(normal["levels"])) | set(list(chunking["levels"])))

    n_success  = []
    c_success  = []
    for lv in all_levels:
        # Succès mode Normal
        mask_n = normal["levels"] == lv
        n_success.append(float(normal["success"][mask_n][0])
                         if mask_n.any() else 0)
        # Succès mode Chunking
        mask_c = chunking["levels"] == lv
        c_success.append(float(chunking["success"][mask_c][0])
                         if mask_c.any() else 0)

    x      = np.arange(len(all_levels))
    width  = 0.35

    bars_n = ax.bar(x - width/2, n_success,  width,
                    color=COLOR_NORMAL,   alpha=0.8, label="Normal")
    bars_c = ax.bar(x + width/2, c_success, width,
                    color=COLOR_CHUNKING, alpha=0.8, label="Chunking")

    ax.set_title("Succès par niveau", fontsize=11, pad=8)
    ax.set_xlabel("Niveau du jeu", fontsize=9)
    ax.set_ylabel("Succès (1=oui, 0=non)", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([str(l) for l in all_levels], fontsize=8)
    ax.set_ylim(0, 1.2)
    ax.axvline(x=4.5, color="purple", linestyle="--", alpha=0.4, linewidth=1,
               label="Limite 7±2")
    ax.grid(True, axis="y", color=COLOR_GRID, linewidth=0.5)
    ax.tick_params(labelsize=8)


def _plot_raw_pzt_annotated(ax, session_normal, session_chunking):
    
    ax.set_title(
        "Signal PZT brut — Normal (gauche) vs Chunking (droite)\n"
        "Les pauses respiratoires sont visibles à partir du niveau 7+ en mode Normal",
        fontsize=10
    )

    #demi-figure gauche : mode Normal
    if session_normal.raw_pzt:
        n     = len(session_normal.raw_pzt)
        ts    = session_normal.timestamps
        #normaliser 0-1 pour superposer les deux sessions
        arr   = np.array(session_normal.raw_pzt, dtype=float)
        arr   = (arr - arr.min()) / (arr.max() - arr.min() + 1)
        ax.plot(ts, arr,
                color=COLOR_NORMAL, linewidth=0.6, alpha=0.8, label="Normal PZT")

        #annotations des niveaux
        for (t_ev, lv) in session_normal.level_events:
            ax.axvline(x=t_ev, color=COLOR_NORMAL, alpha=0.3, linewidth=1)
            ax.text(t_ev, 1.02, f"N{lv}", fontsize=7, color=COLOR_NORMAL,
                    ha="center", transform=ax.get_xaxis_transform())

    #demi figure droite : mode Chunking
    if session_chunking.raw_pzt:
        # Décaler dans le temps pour mettre côte à côte
        offset = max(session_normal.timestamps) + 5 if session_normal.timestamps else 0
        ts_c   = [t + offset for t in session_chunking.timestamps]
        arr_c  = np.array(session_chunking.raw_pzt, dtype=float)
        arr_c  = (arr_c - arr_c.min()) / (arr_c.max() - arr_c.min() + 1)
        ax.plot(ts_c, arr_c,
                color=COLOR_CHUNKING, linewidth=0.6, alpha=0.8, label="Chunking PZT")

        for (t_ev, lv) in session_chunking.level_events:
            ax.axvline(x=t_ev + offset, color=COLOR_CHUNKING, alpha=0.3, linewidth=1)
            ax.text(t_ev + offset, 1.02, f"N{lv}", fontsize=7, color=COLOR_CHUNKING,
                    ha="center", transform=ax.get_xaxis_transform())

        # Séparateur entre les deux sessions
        if session_normal.timestamps:
            ax.axvline(x=offset - 2.5, color="black", linewidth=2, alpha=0.5)
            ax.text(offset - 2.5, 0.5, " ← Normal  |  Chunking →",
                    fontsize=9, ha="center", va="center", rotation=90,
                    transform=ax.transData, color="black", alpha=0.6)

    ax.set_xlabel("Temps (secondes)", fontsize=9)
    ax.set_ylabel("PZT normalisé", fontsize=9)
    ax.set_ylim(-0.1, 1.15)
    ax.grid(True, color=COLOR_GRID, linewidth=0.5)
    ax.tick_params(labelsize=8)
    ax.legend(loc="upper right", fontsize=8)


# RÉSUMÉ STATISTIQUE

def _compute_summary(normal_data: dict, chunking_data: dict) -> dict:
    """Calcule les statistiques comparatives entre les deux modes."""

    def safe_mean(arr):
        valid = arr[~np.isnan(arr)]
        return float(np.mean(valid)) if len(valid) > 0 else None

    def safe_std(arr):
        valid = arr[~np.isnan(arr)]
        return float(np.std(valid)) if len(valid) > 0 else None

    return {
        "normal": {
            "max_level":       int(normal_data["levels"].max()) if len(normal_data["levels"]) > 0 else 0,
            "success_rate":    float(normal_data["success"].mean()) if len(normal_data["success"]) > 0 else 0,
            "hr_mean":         safe_mean(normal_data["hr_bpm"]),
            "hr_std":          safe_std(normal_data["hr_bpm"]),
            "rr_mean":         safe_mean(normal_data["rr_rpm"]),
            "ppg_amp_mean":    safe_mean(normal_data["ppg_amplitude"]),
        },
        "chunking": {
            "max_level":       int(chunking_data["levels"].max()) if len(chunking_data["levels"]) > 0 else 0,
            "success_rate":    float(chunking_data["success"].mean()) if len(chunking_data["success"]) > 0 else 0,
            "hr_mean":         safe_mean(chunking_data["hr_bpm"]),
            "hr_std":          safe_std(chunking_data["hr_bpm"]),
            "rr_mean":         safe_mean(chunking_data["rr_rpm"]),
            "ppg_amp_mean":    safe_mean(chunking_data["ppg_amplitude"]),
        },
    }


def _print_summary(summary: dict):
    """Affiche le résumé statistique dans la console"""
    print()
    print("=" * 55)
    print("RÉSUMÉ COMPARATIF — Normal vs Chunking")
    print("=" * 55)
    fmt = "{:<28} {:>10} {:>10}"
    print(fmt.format("Métrique", "Normal", "Chunking"))
    print("-" * 55)

    def v(d, k):
        val = d.get(k)
        return f"{val:.1f}" if val is not None else "N/A"

    n, c = summary["normal"], summary["chunking"]
    print(fmt.format("Niveau max atteint",     str(n["max_level"]),  str(c["max_level"])))
    print(fmt.format("Taux de succès (%)",     f"{n['success_rate']*100:.0f}%", f"{c['success_rate']*100:.0f}%"))
    print(fmt.format("FC moyenne (bpm)",       v(n, "hr_mean"),      v(c, "hr_mean")))
    print(fmt.format("FC écart-type",          v(n, "hr_std"),       v(c, "hr_std")))
    print(fmt.format("Resp. moyenne (rpm)",    v(n, "rr_mean"),      v(c, "rr_mean")))
    print(fmt.format("Amplitude PPG moyenne",  v(n, "ppg_amp_mean"), v(c, "ppg_amp_mean")))
    print("=" * 55)
    print()
    print("Interprétation attendue :")
    print("  • FC plus haute en mode Normal aux niveaux 7+")
    print("    → activation sympathique sous surcharge cognitive")
    print("  • Amplitude PPG plus faible en mode Normal")
    print("    → vasoconstriction périphérique (Shi et al., 2023)")
    print("  • Pauses respiratoires en mode Normal aux niveaux 7+")
    print("    → apnée cognitive (Studer et al., 2021)")
    print("  • Ces effets atténués en mode Chunking")
    print("    → confirmation de l'hypothèse Miller (1956)")
    print()



# GÉNÉRATION DE DONNÉES SYNTHÉTIQUES DE DÉMO

def _generate_demo_session(mode: str, n_levels: int = 9) -> SessionData:
    
    session = SessionData(mode)
    t_now   = time.time()

    # Parametres physiologiques de base
    hr_base  = 68.0   # FC repos
    rr_base  = 15.0   # resp. repos
    amp_base = 8000.0 # amplitude PPG repos

    for level in range(1, n_levels + 1):
        session.start_level(level)
        seq_len  = level + 2      # 3 flèches au niveau 1, etc.
        duration = 4 + level * 0.5  # niveaux plus longs au fil du temps

        # Génération de signal PZT pour ce niveau
        n_samples = int(duration * config.SAMPLING_RATE)
        t_local   = np.linspace(0, duration, n_samples)

        # Effet de la charge cognitive sur les signaux
        # À partir du niveau 5 (7 flèches = limite Miller),
        # les signaux changent de manière mesurable.
        load_factor = max(0, (level - 4) / 5.0)   # 0 pour niveaux 1-4, monte ensuite

        # Modulation selon le mode :
        # Chunking atténue l'effet de la charge
        if mode == "CHUNKING":
            load_factor *= 0.45   # chunking réduit la charge de ~55%

        # PZT : respiration ralentit et devient irrégulière sous charge
        rr_this    = rr_base * (1 + 0.15 * load_factor + random.gauss(0, 0.05))
        pzt_signal = (
            10000 * np.sin(2 * np.pi * (rr_this / 60) * t_local) +
            # Pauses respiratoires simulées (amplitude réduite sous charge)
            1000 * load_factor * np.random.normal(0, 1, n_samples) +
            np.random.normal(0, 100, n_samples)
        ) + 32768

        #ajout des échantillons PZT à la session
        for i, v in enumerate(pzt_signal.astype(int)):
            ts = t_now + i / config.SAMPLING_RATE
            session.add_sample({
                "ts":    ts,
                "ppg":   32768,
                "pzt":   int(v),
                "acc_x": 32768,
                "acc_y": 32768,
            })

        #metriques physiologiques pour ce niveau
        hr_this  = hr_base  + 8 * load_factor + random.gauss(0, 1.5)
        amp_this = amp_base * (1 - 0.3 * load_factor) + random.gauss(0, 100)

        #succes: plus difficile en mode Normal aux niveaux élevés
        if mode == "NORMAL":
            success_prob = max(0.05, 1.0 - 0.15 * max(0, level - 4))
        else:
            success_prob = max(0.2, 1.0 - 0.07 * max(0, level - 6))
        success = random.random() < success_prob

        session.end_level(
            success       = success,
            hr_bpm        = hr_this,
            rr_rpm        = rr_this,
            ppg_amplitude = amp_this,
            resp_pauses   = int(load_factor * 3),
        )

        t_now += duration
        if not success:
            break   # partie terminee sur echec

    return session


# TEST STANDALONE, python analysis.py

if __name__ == "__main__":
    print("=" * 55)
    print("TEST ANALYSE COMPARATIVE")
    print("=" * 55)

    config.validate()
    print()

    print("Génération des données de démo (simulées)...")
    print("  → Session Mode Normal (9 niveaux max)")
    session_n = _generate_demo_session("NORMAL",   n_levels=9)
    print(f"     Niveaux joués : {len(session_n.levels)}")

    print("  → Session Mode Chunking (9 niveaux max)")
    session_c = _generate_demo_session("CHUNKING", n_levels=9)
    print(f"     Niveaux joués : {len(session_c.levels)}")

    print()
    print("Génération du rapport comparatif...")

    summary = generate_comparison_report(
        session_n,
        session_c,
        save_path="rapport_chunkymemo_demo.png"
    )

    print()
    print("Fichier sauvegardé : rapport_chunkymemo_demo.png")
    print("Fermez la fenêtre matplotlib pour terminer")
    plt.show()
    
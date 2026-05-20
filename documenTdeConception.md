# ChunkyMemo

Jeu interactif de mémoire de travail basé sur la loi de Miller (7±2) avec mesure physiologique de la charge cognitive en temps réel.

---

## Description

Le joueur observe une séquence de flèches directionnelles, puis la reproduit au clavier. La longueur des séquences augmente progressivement jusqu'à dépasser la limite individuelle de la mémoire de travail. Le système mesure simultanément la charge cognitive via deux capteurs BITalino (PPG + PZT) et le comportement clavier (temps de réaction, taux d'erreur).

---

## Prérequis

```
Python 3.9+
pygame
scipy
numpy
bitalino
```

Installation des dépendances :

```bash
pip install pygame scipy numpy bitalino
```

---

## Lancement

```bash
python chunkymemo.py
```

Si le BITalino n'est pas connecté, le jeu bascule automatiquement en **mode simulation**.

---

## Matériel

| Composant | Détail |
|-----------|--------|
| Carte | BITalino (r)evolution Plugged Kit BLE/BT |
| MAC address | `98:D3:11:FE:03:67` |
| Fréquence d'échantillonnage | 100 Hz |
| Canal A1 | Capteur PPG — index, clip digital |
| Canal A2 | Capteur PZT — ceinture thoracique |
| Contrôle | Clavier — touches directionnelles ↑ ↓ ← → |

---

## Signaux acquis

| Signal | Ce que le BITalino envoie | Unité |
|--------|--------------------------|-------|
| PPG | Variation de volume sanguin dans le doigt | valeur brute 0–1023 (10 bits) |
| PZT | Déformation de la ceinture thoracique | valeur brute 0–1023 (10 bits) |

| Entrée | Ce que le jeu capture | Unité |
|--------|-----------------------|-------|
| Clavier | Horodatage de chaque appui | timestamp (ms) |

---

## Traitement du signal

### PPG → Fréquence cardiaque (FC)

**Ce qu'on extrait :** nombre de battements par minute

**Pourquoi :** la FC augmente de 3–8 bpm entre charge faible et charge élevée sur des tâches de mémoire de travail.
> Causse et al. (2023) *Task-evoked pulse wave amplitude tracks cognitive load* — Scientific Reports
> https://www.nature.com/articles/s41598-023-48917-5

**Transformations :**
1. Filtre passe-bande Butterworth ordre 4, bande **[0.7–4.0 Hz]** → élimine dérive lente + bruit haute fréquence
2. Détection de pics → chaque pic = un battement
3. `FC = 60 / IBI` où IBI = intervalle moyen entre les 5 derniers pics (en secondes)

> Elgendi (2012) *On the Analysis of Fingertip Photoplethysmogram Signals* — Current Cardiology Reviews
> https://www.ingentaconnect.com/content/ben/ccr/2012/00000008/00000001

---

### PPG → Amplitude de l'onde de pouls (PWA)

**Ce qu'on extrait :** hauteur de chaque battement dans le signal PPG, normalisée par rapport à la baseline

**Pourquoi :** sous charge cognitive, la vasoconstriction périphérique sympathique réduit l'amplitude du signal PPG. La PWA diminue indépendamment de la FC — deux métriques extraites du même canal.
> Causse et al. (2023) — même référence que FC

**Transformations :**
1. Même filtre que FC : Butterworth **[0.7–4.0 Hz]**
2. `PWA_brute = valeur_pic − valeur_creux_précédent`
3. `PWA_normalisée = PWA_brute / PWA_baseline`

---

### PZT → Rythme respiratoire (RR)

**Ce qu'on extrait :** nombre de cycles respiratoires par minute

**Pourquoi :** les épisodes mentalement exigeants s'accompagnent d'une respiration plus rapide. Le PZT répond quasi-immédiatement, contrairement à l'EDA (latence 3–5 s).
> Grassmann et al. (2016) *Respiratory Changes in Response to Cognitive Load: A Systematic Review* — Neural Plasticity
> https://doi.org/10.1155/2016/8146809

**Transformations :**
1. Filtre passe-bande Butterworth ordre 4, bande **[0.1–0.8 Hz]** → fréquences respiratoires (6–48 cycles/min)
2. Détection de pics → chaque pic = une inspiration
3. `RR = 60 / IBI_resp` où IBI_resp = intervalle moyen entre les 3 derniers pics (en secondes)

> Charlton et al. (2018) *Breathing Rate Estimation from the Electrocardiogram and Photoplethysmogram* — IEEE Reviews in Biomedical Engineering
> https://ieeexplore.ieee.org/abstract/document/8081839

---

### PZT → Détection d'apnée cognitive

**Ce qu'on extrait :** absence prolongée de cycle respiratoire (pause involontaire liée à la concentration)

**Pourquoi :** sous charge cognitive intense, le joueur retient involontairement sa respiration. Ces micro-apnées marquent le moment où la séquence dépasse la limite individuelle de mémoire de travail.
> Grassmann et al. (2016) — même référence que RR

**Transformations :**
1. Même filtre que RR : Butterworth **[0.1–0.8 Hz]**
2. `apnée = True` si `(t_actuel − t_dernier_pic) > 4.0 s`
3. Seuil de 4 s choisi pour dépasser l'intervalle normal maximum entre deux inspirations (≈ 10 s à 6 cycles/min) sans rater les apnées courtes de concentration

---

### Clavier → Temps de réaction (RT)

**Ce qu'on extrait :** délai entre l'affichage d'une flèche et l'appui de la touche correspondante

**Pourquoi :** le RT est l'un des indicateurs comportementaux les plus robustes de la charge cognitive. Complémentaire aux signaux physiologiques : PPG et PZT mesurent l'état interne, le RT mesure la performance observable.
> Welford (1980) *Reaction Times* — Academic Press
> Hick (1952) *On the rate of gain of information* — Quarterly Journal of Experimental Psychology

**Transformations :**
1. `RT = t_appui − t_affichage_flèche` (en ms)
2. `RT_moyen = moyenne glissante des 3 derniers RT`
3. `taux_erreur = nb_mauvaises_touches / nb_total_réponses` (par niveau)

---

### Indice de charge cognitive composite (I_cog)

**Ce qu'on calcule :** score unique combinant 4 métriques issues de 3 sources indépendantes (cardiovasculaire, respiratoire, comportementale)

**Calibration — 30 secondes au lancement (joueur au repos, immobile, yeux ouverts) :**
- `μ_FC, σ_FC` — moyenne et écart-type de FC
- `μ_PWA, σ_PWA` — moyenne et écart-type de PWA
- `μ_RR, σ_RR` — moyenne et écart-type de RR
- `μ_RT, σ_RT` — calculés sur les 5 premières réponses du niveau 1

**Z-scores :**
```
z_FC  = (FC  − μ_FC)  / σ_FC
z_PWA = (PWA − μ_PWA) / σ_PWA × −1   # inversé : PWA↓ = charge↑
z_RR  = (RR  − μ_RR)  / σ_RR
z_RT  = (RT  − μ_RT)  / σ_RT
```

**Indice composite :**
```
I_cog = (z_FC + z_PWA + z_RR + z_RT) / 4

I_cog > 1.5  →  surcharge détectée  →  retour visuel dans le dashboard
```

---

## Récapitulatif

| Source | Métrique | Traitement | Lien charge cognitive |
|--------|----------|------------|-----------------------|
| PPG | FC (bpm) | Butterworth [0.7–4.0 Hz] + détection pics | FC ↑ 3–8 bpm sous charge [Causse 2023] |
| PPG | PWA normalisée | Butterworth [0.7–4.0 Hz] + amplitude pic-creux | PWA ↓ vasoconstriction sympathique [Causse 2023] |
| PZT | RR (cycles/min) | Butterworth [0.1–0.8 Hz] + détection pics | RR ↑ sous charge [Grassmann 2016] |
| PZT | Apnée (booléen) | Butterworth [0.1–0.8 Hz] + seuil 4 s | Pause > 4 s = concentration intense [Grassmann 2016] |
| Clavier | RT (ms) | Différence de timestamps | RT ↑ sous charge cognitive [Welford 1980] |
| Clavier | Taux d'erreur (%) | Comptage par niveau | Erreurs ↑ sous surcharge [Hick 1952] |

---

## Export des données

Les métriques sont exportées automatiquement en CSV à la fin de chaque session dans le répertoire courant :
```
chunkymemo_session_YYYYMMDD_HHMMSS.csv
```

---

## Structure du projet

```
2026_4ATechFacHum_[Nom1]_[Nom2]_[Nom3]/
├── chunkymemo.py
├── README.md
└── documentation/
    ├── rapport.pdf
    └── slides.pdf
```